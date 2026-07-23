"""Windows AppContainer/restricted-token sandbox with native fail-closed seams.

The production adapter keeps the original DACL for every touched directory and
restores it on every exit path.  An AppContainer SID is supplied to the child
through ``PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES``; merely creating a SID
is not considered an AppContainer launch.
"""

from __future__ import annotations

import ctypes
import os
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .base import (
    ProcessHandle,
    ProcessRequest,
    ReconciliationResult,
    SandboxAttestation,
    SandboxScope,
    ScopeSnapshot,
    TerminationResult,
    attest_snapshot,
    attestation_is_current,
    capture_scope_snapshot,
    minimal_environment,
    scope_failure_hash,
)

AclMode = Literal["write", "readonly", "deny", "traverse"]

class WindowsNativeOps(Protocol):
    def create_appcontainer(self, scope: ScopeSnapshot) -> str: ...
    def release_appcontainer(self, sid: str) -> None: ...
    def create_restricted_token(self, sid: str) -> str: ...
    def close_token(self, token: str) -> None: ...
    def grant_scope_acl(self, root: Path, sid: str, mode: AclMode) -> None: ...
    def create_kill_on_close_job(self) -> str: ...
    def spawn_suspended(
        self, request: ProcessRequest, cwd: Path, environment: dict[str, str], token: str, appcontainer_sid: str
    ) -> tuple[int, object]: ...
    def assign_job(self, pid: int, job: str) -> None: ...
    def terminate_suspended(self, pid: int, thread: object) -> None: ...
    def resume_suspended(self, thread: object) -> None: ...
    def close_job(self, job: str) -> None: ...
    def revoke_scope_acl(self, root: Path, sid: str) -> None: ...
    def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None: ...


@dataclass(slots=True)
class _NativeProcess:
    pid: int
    process_handle: int | None
    thread_handle: int | None


@dataclass(frozen=True, slots=True)
class _DaclBackup:
    descriptor: int
    dacl: int
    control: int
    dacl_present: bool
    dacl_protected: bool
    dacl_auto_inherited: bool
    mode: AclMode


class CtypesWindowsNativeOps:
    """Direct Win32 binding, available only on Windows and never a shell fallback."""

    _CREATE_SUSPENDED = 0x00000004
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
    _SE_FILE_OBJECT = 1
    _DACL_SECURITY_INFORMATION = 0x00000004
    _UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
    _PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
    _SE_DACL_PROTECTED = 0x1000
    _SE_DACL_AUTO_INHERIT_REQ = 0x0100
    _SE_DACL_AUTO_INHERITED = 0x0400
    _DACL_RESTORE_CONTROL_MASK = _SE_DACL_PROTECTED | _SE_DACL_AUTO_INHERIT_REQ | _SE_DACL_AUTO_INHERITED
    _GRANT_ACCESS = 1
    _DENY_ACCESS = 3
    _TRUSTEE_IS_SID = 0
    _TRUSTEE_IS_UNKNOWN = 0
    _NO_MULTIPLE_TRUSTEE = 0
    _FILE_WRITE_SCOPE = 0x001201BF
    _FILE_READ_SCOPE = 0x001200A9
    _FILE_DENY_SCOPE = 0x001F01FF
    _FILE_TRAVERSE_SCOPE = 0x001200A0
    _STILL_ACTIVE = 259
    _WAIT_OBJECT_0 = 0
    _S_OK = 0
    _HRESULT_ALREADY_EXISTS = ctypes.c_long(0x800700B7).value

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("UNSUPPORTED_SANDBOX_PLATFORM")
        win_dll: Any = getattr(ctypes, "WinDLL")
        self._kernel32: Any = win_dll("kernel32", use_last_error=True)
        self._advapi32: Any = win_dll("advapi32", use_last_error=True)
        self._userenv: Any = win_dll("userenv", use_last_error=True)
        self._configure_abi()
        self._processes: dict[int, _NativeProcess] = {}
        self._sid_pointers: dict[str, int] = {}
        self._sid_profiles: dict[str, str] = {}
        self._acl_backups: dict[tuple[str, str], _DaclBackup] = {}
        self._acl_tree_members: dict[tuple[str, str], list[Path]] = {}

    @staticmethod
    def _bind(library: Any, name: str, restype: Any, argtypes: list[Any]) -> None:
        function: Any = getattr(library, name)
        function.restype = restype
        function.argtypes = argtypes

    def _configure_abi(self) -> None:
        """Declare every native ABI explicitly; x64 handles must never default to c_int."""
        void_p = ctypes.c_void_p
        dword = ctypes.c_ulong
        size_t = ctypes.c_size_t
        bool_t = ctypes.c_int
        wchar_p = ctypes.c_wchar_p
        self._bind(self._kernel32, "GetCurrentProcess", void_p, [])
        self._bind(self._kernel32, "LocalFree", void_p, [void_p])
        self._bind(self._kernel32, "CloseHandle", bool_t, [void_p])
        self._bind(self._kernel32, "CreateJobObjectW", void_p, [void_p, wchar_p])
        self._bind(self._kernel32, "SetInformationJobObject", bool_t, [void_p, ctypes.c_int, void_p, dword])
        self._bind(self._kernel32, "InitializeProcThreadAttributeList", bool_t, [void_p, dword, dword, ctypes.POINTER(size_t)])
        self._bind(self._kernel32, "UpdateProcThreadAttribute", bool_t, [void_p, dword, size_t, void_p, size_t, void_p, void_p])
        self._bind(self._kernel32, "DeleteProcThreadAttributeList", None, [void_p])
        self._bind(self._kernel32, "AssignProcessToJobObject", bool_t, [void_p, void_p])
        self._bind(self._kernel32, "ResumeThread", dword, [void_p])
        self._bind(self._kernel32, "TerminateProcess", bool_t, [void_p, dword])
        self._bind(self._kernel32, "WaitForSingleObject", dword, [void_p, dword])
        self._bind(self._kernel32, "GetExitCodeProcess", bool_t, [void_p, ctypes.POINTER(dword)])
        self._bind(self._kernel32, "CreateProcessW", bool_t, [wchar_p, void_p, void_p, void_p, bool_t, dword, void_p, wchar_p, void_p, void_p])
        self._bind(self._advapi32, "ConvertSidToStringSidW", bool_t, [void_p, ctypes.POINTER(wchar_p)])
        self._bind(self._advapi32, "FreeSid", void_p, [void_p])
        self._bind(self._advapi32, "OpenProcessToken", bool_t, [void_p, dword, ctypes.POINTER(void_p)])
        self._bind(self._advapi32, "CreateRestrictedToken", bool_t, [void_p, dword, dword, void_p, dword, void_p, dword, void_p, ctypes.POINTER(void_p)])
        self._bind(self._advapi32, "GetNamedSecurityInfoW", dword, [wchar_p, dword, dword, void_p, void_p, ctypes.POINTER(void_p), void_p, ctypes.POINTER(void_p)])
        self._bind(self._advapi32, "GetSecurityDescriptorDacl", bool_t, [void_p, ctypes.POINTER(bool_t), ctypes.POINTER(void_p), ctypes.POINTER(bool_t)])
        self._bind(self._advapi32, "GetSecurityDescriptorControl", bool_t, [void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(dword)])
        self._bind(self._advapi32, "SetSecurityDescriptorControl", bool_t, [void_p, ctypes.c_ushort, ctypes.c_ushort])
        self._bind(self._advapi32, "SetEntriesInAclW", dword, [dword, void_p, void_p, ctypes.POINTER(void_p)])
        self._bind(self._advapi32, "SetNamedSecurityInfoW", dword, [wchar_p, dword, dword, void_p, void_p, void_p, void_p])
        self._bind(self._advapi32, "SetFileSecurityW", bool_t, [wchar_p, dword, void_p])
        self._bind(self._userenv, "DeriveAppContainerSidFromAppContainerName", ctypes.c_long, [wchar_p, ctypes.POINTER(void_p)])
        self._bind(self._userenv, "CreateAppContainerProfile", ctypes.c_long, [wchar_p, wchar_p, wchar_p, void_p, dword, ctypes.POINTER(void_p)])
        self._bind(self._userenv, "DeleteAppContainerProfile", ctypes.c_long, [wchar_p])

    @staticmethod
    def _check(result: int, operation: str) -> int:
        if not result:
            get_last_error: Any = getattr(ctypes, "get_last_error", lambda: 0)
            raise OSError(get_last_error(), operation)
        return result

    @staticmethod
    def _pointer(value: int | None) -> ctypes.c_void_p:
        return ctypes.c_void_p(value) if value else ctypes.c_void_p()

    def create_appcontainer(self, scope: ScopeSnapshot) -> str:
        """Create a per-run AppContainer profile and return its package SID."""
        name = "Yagcode-" + scope.scope_hash[:32]
        sid = ctypes.c_void_p()
        hresult = self._userenv.CreateAppContainerProfile(
            name,
            name,
            "Yagcode sandbox profile",
            None,
            0,
            ctypes.byref(sid),
        )
        if hresult == self._HRESULT_ALREADY_EXISTS:
            hresult = self._userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
        if hresult != self._S_OK:
            raise OSError(hresult, "CreateAppContainerProfile")
        string_sid = ctypes.c_wchar_p()
        try:
            self._check(self._advapi32.ConvertSidToStringSidW(sid, ctypes.byref(string_sid)), "ConvertSidToStringSidW")
        except BaseException:
            if sid.value:
                self._advapi32.FreeSid(sid)
            raise
        try:
            value = str(string_sid.value)
        finally:
            self._kernel32.LocalFree(string_sid)
        if not sid.value:
            raise OSError("APPCONTAINER_SID_NULL")
        self._sid_pointers[value] = int(sid.value)
        self._sid_profiles[value] = name
        return value

    def release_appcontainer(self, sid: str) -> None:
        profile = self._sid_profiles.pop(sid, None)
        if profile is not None:
            hresult = self._userenv.DeleteAppContainerProfile(profile)
            if hresult != self._S_OK:
                self._sid_profiles[sid] = profile
                raise OSError(hresult, "DeleteAppContainerProfile")
        pointer = self._sid_pointers.pop(sid, None)
        if pointer is not None:
            self._advapi32.FreeSid(self._pointer(pointer))

    def create_restricted_token(self, sid: str) -> str:
        if sid not in self._sid_pointers:
            raise OSError("APPCONTAINER_SID_UNKNOWN")
        current = ctypes.c_void_p()
        self._check(
            self._advapi32.OpenProcessToken(self._kernel32.GetCurrentProcess(), 0x0002 | 0x0008, ctypes.byref(current)),
            "OpenProcessToken",
        )
        restricted = ctypes.c_void_p()
        try:
            self._check(
                self._advapi32.CreateRestrictedToken(current, 0x1, 0, None, 0, None, 0, None, ctypes.byref(restricted)),
                "CreateRestrictedToken",
            )
            return str(restricted.value)
        finally:
            self._kernel32.CloseHandle(current)

    def close_token(self, token: str) -> None:
        self._check(self._kernel32.CloseHandle(self._pointer(int(token))), "CloseHandle(token)")

    def _sid_pointer(self, sid: str) -> int:
        pointer = self._sid_pointers.get(sid)
        if pointer is None:
            raise OSError("APPCONTAINER_SID_UNKNOWN")
        return pointer

    def _dacl_security_information(self, dacl_protected: bool) -> int:
        _ = dacl_protected
        return self._DACL_SECURITY_INFORMATION

    def _remember_and_replace_dacl(self, root: Path, sid: str, mode: AclMode) -> None:
        class TRUSTEE_W(ctypes.Structure):
            _fields_ = [
                ("pMultipleTrustee", ctypes.c_void_p), ("MultipleTrusteeOperation", ctypes.c_ulong),
                ("TrusteeForm", ctypes.c_ulong), ("TrusteeType", ctypes.c_ulong), ("ptstrName", ctypes.c_void_p),
            ]

        class EXPLICIT_ACCESS_W(ctypes.Structure):
            _fields_ = [
                ("grfAccessPermissions", ctypes.c_ulong), ("grfAccessMode", ctypes.c_ulong),
                ("grfInheritance", ctypes.c_ulong), ("Trustee", TRUSTEE_W),
            ]

        key = (str(root), sid)
        if key in self._acl_backups:
            raise OSError("ACL_BACKUP_ALREADY_PRESENT")
        descriptor = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        present = ctypes.c_int()
        defaulted = ctypes.c_int()
        result = self._advapi32.GetNamedSecurityInfoW(
            str(root), self._SE_FILE_OBJECT, self._DACL_SECURITY_INFORMATION,
            None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor),
        )
        if result != 0:
            raise OSError(result, "GetNamedSecurityInfoW")
        try:
            self._check(
                self._advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)),
                "GetSecurityDescriptorDacl",
            )
            control = ctypes.c_ushort()
            revision = ctypes.c_ulong()
            self._check(
                self._advapi32.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)),
                "GetSecurityDescriptorControl",
            )
            if not descriptor.value or not present.value or not dacl.value:
                raise OSError("ACL_DACL_EXACT_RESTORE_UNAVAILABLE")
            dacl_protected = bool(control.value & self._SE_DACL_PROTECTED)
            dacl_auto_inherited = bool(control.value & self._SE_DACL_AUTO_INHERITED)
            trustee = TRUSTEE_W(None, self._NO_MULTIPLE_TRUSTEE, self._TRUSTEE_IS_SID, self._TRUSTEE_IS_UNKNOWN, self._pointer(self._sid_pointer(sid)))
            permissions, access_mode, inheritance = {
                "write": (self._FILE_WRITE_SCOPE, self._GRANT_ACCESS, 0x00000003),
                "readonly": (self._FILE_READ_SCOPE, self._GRANT_ACCESS, 0x00000003),
                "deny": (self._FILE_DENY_SCOPE, self._DENY_ACCESS, 0x00000003),
                "traverse": (self._FILE_TRAVERSE_SCOPE, self._GRANT_ACCESS, 0),
            }[mode]
            access = EXPLICIT_ACCESS_W(
                permissions,
                access_mode,
                inheritance,
                trustee,
            )
            new_dacl = ctypes.c_void_p()
            result = self._advapi32.SetEntriesInAclW(1, ctypes.byref(access), dacl, ctypes.byref(new_dacl))
            if result != 0:
                raise OSError(result, "SetEntriesInAclW")
            try:
                result = self._advapi32.SetNamedSecurityInfoW(
                    str(root), self._SE_FILE_OBJECT, self._dacl_security_information(dacl_protected), None, None, new_dacl, None
                )
                if result != 0:
                    raise OSError(result, "SetNamedSecurityInfoW")
            finally:
                self._kernel32.LocalFree(new_dacl)
        except BaseException:
            self._kernel32.LocalFree(descriptor)
            raise
        self._acl_backups[key] = _DaclBackup(
            int(descriptor.value),
            int(dacl.value),
            int(control.value),
            bool(present.value),
            dacl_protected,
            dacl_auto_inherited,
            mode,
        )

    @staticmethod
    def _is_reparse_path(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction()) if callable(is_junction) else path.is_symlink()

    @classmethod
    def _acl_member_paths(cls, root: Path, mode: AclMode) -> list[Path]:
        if sys.platform != "win32" or mode == "traverse" or not root.is_dir():
            return [root]
        members = [root]
        for current, directories, files in os.walk(root):
            current_path = Path(current)
            kept_directories: list[str] = []
            for directory in directories:
                child = current_path / directory
                if cls._is_reparse_path(child):
                    continue
                members.append(child)
                kept_directories.append(directory)
            directories[:] = kept_directories
            for file_name in files:
                child = current_path / file_name
                if not cls._is_reparse_path(child):
                    members.append(child)
        return members

    def grant_scope_acl(self, root: Path, sid: str, mode: AclMode) -> None:
        key = (str(root), sid)
        if key in self._acl_tree_members:
            raise OSError("ACL_BACKUP_ALREADY_PRESENT")
        applied: list[Path] = []
        try:
            for member in self._acl_member_paths(root, mode):
                self._remember_and_replace_dacl(member, sid, mode)
                applied.append(member)
        except BaseException:
            if applied:
                self._acl_tree_members[key] = applied
                try:
                    self.revoke_scope_acl(root, sid)
                except OSError:
                    pass
            raise
        self._acl_tree_members[key] = applied

    def _restore_scope_acl(self, root: Path, sid: str) -> None:
        key = (str(root), sid)
        original = self._acl_backups.get(key)
        if original is None:
            raise OSError("ACL_BACKUP_MISSING")
        self._check(
            self._advapi32.SetSecurityDescriptorControl(
                self._pointer(original.descriptor),
                self._DACL_RESTORE_CONTROL_MASK,
                original.control & self._DACL_RESTORE_CONTROL_MASK,
            ),
            "SetSecurityDescriptorControl",
        )
        if original.dacl_auto_inherited:
            result = self._advapi32.SetNamedSecurityInfoW(
                str(root),
                self._SE_FILE_OBJECT,
                self._dacl_security_information(original.dacl_protected),
                None,
                None,
                self._pointer(original.dacl),
                None,
            )
            if result != 0:
                raise OSError(result, "RestoreNamedSecurityInfoW")
        else:
            security_information = self._dacl_security_information(original.dacl_protected)
            if original.mode != "traverse":
                security_information |= (
                    self._PROTECTED_DACL_SECURITY_INFORMATION
                    if original.dacl_protected
                    else self._UNPROTECTED_DACL_SECURITY_INFORMATION
                )
            result = self._advapi32.SetFileSecurityW(
                str(root), security_information, self._pointer(original.descriptor)
            )
            if not result:
                get_last_error: Any = getattr(ctypes, "get_last_error", lambda: 0)
                raise OSError(get_last_error(), "RestoreFileSecurityW")
        self._acl_backups.pop(key)
        self._kernel32.LocalFree(self._pointer(original.descriptor))

    def revoke_scope_acl(self, root: Path, sid: str) -> None:
        key = (str(root), sid)
        members = self._acl_tree_members.get(key, [root])
        while members:
            member = members[-1]
            try:
                self._restore_scope_acl(member, sid)
            except OSError:
                self._acl_tree_members[key] = members
                raise
            members.pop()
        self._acl_tree_members.pop(key, None)

    def create_kill_on_close_job(self) -> str:
        job = self._check(self._kernel32.CreateJobObjectW(None, None), "CreateJobObjectW")
        buffer = ctypes.create_string_buffer(144)
        ctypes.c_uint32.from_buffer(buffer, 16).value = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            self._check(
                self._kernel32.SetInformationJobObject(job, self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, buffer, len(buffer)),
                "SetInformationJobObject",
            )
        except BaseException:
            self._kernel32.CloseHandle(self._pointer(job))
            raise
        return str(job)

    def spawn_suspended(
        self, request: ProcessRequest, cwd: Path, environment: dict[str, str], token: str, appcontainer_sid: str
    ) -> tuple[int, object]:
        _ = token
        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("lpReserved", ctypes.c_wchar_p), ("lpDesktop", ctypes.c_wchar_p),
                ("lpTitle", ctypes.c_wchar_p), ("dwX", ctypes.c_ulong), ("dwY", ctypes.c_ulong),
                ("dwXSize", ctypes.c_ulong), ("dwYSize", ctypes.c_ulong), ("dwXCountChars", ctypes.c_ulong),
                ("dwYCountChars", ctypes.c_ulong), ("dwFillAttribute", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("wShowWindow", ctypes.c_ushort), ("cbReserved2", ctypes.c_ushort), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", ctypes.c_void_p), ("hStdOutput", ctypes.c_void_p), ("hStdError", ctypes.c_void_p),
            ]

        class STARTUPINFOEX_W(ctypes.Structure):
            _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [("hProcess", ctypes.c_void_p), ("hThread", ctypes.c_void_p), ("dwProcessId", ctypes.c_ulong), ("dwThreadId", ctypes.c_ulong)]

        class SECURITY_CAPABILITIES(ctypes.Structure):
            _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.c_void_p), ("CapabilityCount", ctypes.c_ulong), ("Reserved", ctypes.c_ulong)]

        attribute_size = ctypes.c_size_t()
        self._kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attribute_size))
        attributes = ctypes.create_string_buffer(attribute_size.value)
        self._check(self._kernel32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(attribute_size)), "InitializeProcThreadAttributeList")
        capabilities = SECURITY_CAPABILITIES(self._pointer(self._sid_pointer(appcontainer_sid)), None, 0, 0)
        state: _NativeProcess | None = None
        try:
            self._check(
                self._kernel32.UpdateProcThreadAttribute(
                    attributes, 0, self._PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                    ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None,
                ),
                "UpdateProcThreadAttribute(SECURITY_CAPABILITIES)",
            )
            startup = STARTUPINFOEX_W()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            info = PROCESS_INFORMATION()
            environment_block = "\x00".join(f"{key}={value}" for key, value in sorted(environment.items())) + "\x00\x00"
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline([request.executable, *request.argv]))
            self._check(
                self._kernel32.CreateProcessW(
                    request.executable, command, None, None, False,
                    self._CREATE_SUSPENDED | self._CREATE_UNICODE_ENVIRONMENT | 0x00080000,
                    ctypes.create_unicode_buffer(environment_block), str(cwd), ctypes.byref(startup), ctypes.byref(info),
                ),
                "CreateProcessW",
            )
            state = _NativeProcess(int(info.dwProcessId), int(info.hProcess) if info.hProcess else None, int(info.hThread) if info.hThread else None)
            if state.pid <= 0 or state.process_handle is None or state.thread_handle is None:
                self._close_created_process(state)
                raise OSError("PROCESS_INFORMATION_INVALID")
            self._processes[state.pid] = state
            return state.pid, state
        finally:
            self._kernel32.DeleteProcThreadAttributeList(attributes)

    def _close_created_process(self, state: _NativeProcess) -> None:
        failure: OSError | None = None
        if state.process_handle is not None:
            try:
                self._check(self._kernel32.TerminateProcess(self._pointer(state.process_handle), 1), "TerminateProcess")
            except OSError as error:
                failure = error
        if state.thread_handle is not None:
            try:
                self._check(self._kernel32.CloseHandle(self._pointer(state.thread_handle)), "CloseHandle(thread)")
            except OSError as error:
                failure = failure or error
            else:
                state.thread_handle = None
        if state.process_handle is not None:
            try:
                self._check(self._kernel32.CloseHandle(self._pointer(state.process_handle)), "CloseHandle(process)")
            except OSError as error:
                failure = failure or error
            else:
                state.process_handle = None
        if failure is not None:
            raise failure

    def assign_job(self, pid: int, job: str) -> None:
        state = self._processes[pid]
        if state.process_handle is None:
            raise OSError("PROCESS_HANDLE_MISSING")
        self._check(self._kernel32.AssignProcessToJobObject(self._pointer(int(job)), self._pointer(state.process_handle)), "AssignProcessToJobObject")

    def terminate_suspended(self, pid: int, thread: object) -> None:
        state = self._processes.get(pid, thread if isinstance(thread, _NativeProcess) else None)
        if state is not None:
            if state.process_handle is None:
                raise OSError("PROCESS_HANDLE_MISSING")
            self._check(self._kernel32.TerminateProcess(self._pointer(state.process_handle), 1), "TerminateProcess")
            if state.thread_handle is not None:
                self._check(self._kernel32.CloseHandle(self._pointer(state.thread_handle)), "CloseHandle(thread)")
                state.thread_handle = None
            self._check(self._kernel32.CloseHandle(self._pointer(state.process_handle)), "CloseHandle(process)")
            state.process_handle = None
            self._processes.pop(pid, None)

    def resume_suspended(self, thread: object) -> None:
        if not isinstance(thread, _NativeProcess):
            raise OSError("INVALID_SUSPENDED_THREAD")
        if thread.thread_handle is None:
            raise OSError("SUSPENDED_THREAD_HANDLE_MISSING")
        self._check(self._kernel32.ResumeThread(self._pointer(thread.thread_handle)) != 0xFFFFFFFF, "ResumeThread")
        self._check(self._kernel32.CloseHandle(self._pointer(thread.thread_handle)), "CloseHandle(thread)")
        thread.thread_handle = None

    def close_job(self, job: str) -> None:
        self._check(self._kernel32.CloseHandle(self._pointer(int(job))), "CloseHandle(job)")

    def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
        state = self._processes.get(pid)
        if state is None or state.process_handle is None:
            return None
        status = self._kernel32.WaitForSingleObject(self._pointer(state.process_handle), timeout_ms)
        if status != self._WAIT_OBJECT_0:
            return None
        code = ctypes.c_ulong()
        self._check(self._kernel32.GetExitCodeProcess(self._pointer(state.process_handle), ctypes.byref(code)), "GetExitCodeProcess")
        self._check(self._kernel32.CloseHandle(self._pointer(state.process_handle)), "CloseHandle(process)")
        state.process_handle = None
        self._processes.pop(pid, None)
        return int(code.value)


@dataclass(slots=True)
class _WindowsHandleState:
    sid: str
    job: str
    snapshot: ScopeSnapshot
    pending_acl_roots: list[Path]
    job_closed: bool = False
    returncode: int | None = None
    sid_released: bool = False


@dataclass(slots=True)
class _WindowsCleanupDebt:
    sid: str
    token: str | None
    job: str | None
    pending_acl_roots: list[Path]
    termination_pid: int | None = None
    termination_thread: object | None = None
    job_closed: bool = False
    sid_released: bool = False


class WindowsSandboxRunner:
    """Attest only after a real AppContainer canary; all launch failures are atomic."""

    def __init__(self, *, native_ops: WindowsNativeOps | None = None) -> None:
        self._ops = native_ops if native_ops is not None else (CtypesWindowsNativeOps() if sys.platform == "win32" else None)
        self._attestations: dict[str, SandboxAttestation] = {}
        self._states: dict[int, _WindowsHandleState] = {}
        self._cleanup_debts: list[_WindowsCleanupDebt] = []

    @staticmethod
    def _system_runtime_root() -> Path | None:
        if sys.platform != "win32":
            return None
        value = os.environ.get("SystemRoot")
        return Path(value).resolve() if value else None

    @classmethod
    def _acl_managed_runtime_roots(cls, snapshot: ScopeSnapshot) -> list[Path]:
        system_root = cls._system_runtime_root()
        if system_root is None:
            return list(snapshot.readonly_runtime_roots)
        return [
            root
            for root in snapshot.readonly_runtime_roots
            if root != system_root and not root.is_relative_to(system_root)
        ]

    @classmethod
    def _granted_roots(cls, snapshot: ScopeSnapshot) -> list[Path]:
        return [
            snapshot.shadow_root,
            snapshot.temporary_root,
            *cls._acl_managed_runtime_roots(snapshot),
        ]

    @staticmethod
    def _strict_traverse_ancestors(roots: list[Path]) -> list[Path]:
        """Grant non-inherited directory traversal to parents needed to reach exact roots."""
        if sys.platform != "win32":
            return []
        result: list[Path] = []
        seen: set[Path] = set()
        root_set = set(roots)
        for root in roots:
            current = root.parent
            while current != current.parent:
                if current not in root_set and current not in seen:
                    seen.add(current)
                    result.append(current)
                current = current.parent
            if os.name == "nt" and current not in root_set and current not in seen:
                seen.add(current)
                result.append(current)
        return list(reversed(result))

    @classmethod
    def _acl_grants(cls, snapshot: ScopeSnapshot) -> list[tuple[Path, AclMode]]:
        roots = cls._granted_roots(snapshot)
        return [
            *((root, "traverse") for root in cls._strict_traverse_ancestors(roots)),
            (snapshot.shadow_root, "write"),
            (snapshot.temporary_root, "write"),
            *((root, "readonly") for root in cls._acl_managed_runtime_roots(snapshot)),
        ]

    def _retry_debt(self, debt: _WindowsCleanupDebt) -> bool:
        assert self._ops is not None
        if debt.termination_pid is not None:
            try:
                self._ops.terminate_suspended(debt.termination_pid, debt.termination_thread)
            except (OSError, RuntimeError, ValueError):
                return False
            debt.termination_pid = None
            debt.termination_thread = None
        if not debt.job_closed and debt.job is not None:
            try:
                self._ops.close_job(debt.job)
            except (OSError, RuntimeError, ValueError):
                return False
            debt.job_closed = True
        while debt.pending_acl_roots:
            root = debt.pending_acl_roots[-1]
            try:
                self._ops.revoke_scope_acl(root, debt.sid)
            except (OSError, RuntimeError, ValueError):
                return False
            debt.pending_acl_roots.pop()
        if debt.token is not None:
            try:
                self._ops.close_token(debt.token)
            except (OSError, RuntimeError, ValueError):
                return False
            debt.token = None
        if not debt.sid_released:
            try:
                self._ops.release_appcontainer(debt.sid)
            except (OSError, RuntimeError, ValueError):
                return False
            debt.sid_released = True
        return True

    def _record_cleanup_debt(
        self,
        sid: str,
        token: str | None,
        granted: list[Path],
        job: str | None,
        termination_pid: int | None = None,
        termination_thread: object | None = None,
    ) -> bool:
        debt = _WindowsCleanupDebt(sid, token, job, list(granted), termination_pid, termination_thread)
        if self._retry_debt(debt):
            return True
        self._cleanup_debts.append(debt)
        return False

    def _retry_debts(self) -> bool:
        pending: list[_WindowsCleanupDebt] = []
        for debt in self._cleanup_debts:
            if not self._retry_debt(debt):
                pending.append(debt)
        self._cleanup_debts = pending
        return not pending

    def _retry_handle_cleanup(self, pid: int, state: _WindowsHandleState) -> bool:
        assert self._ops is not None
        if not state.job_closed:
            try:
                self._ops.close_job(state.job)
            except (OSError, RuntimeError, ValueError):
                return False
            state.job_closed = True
        while state.pending_acl_roots:
            root = state.pending_acl_roots[-1]
            try:
                self._ops.revoke_scope_acl(root, state.sid)
            except (OSError, RuntimeError, ValueError):
                return False
            state.pending_acl_roots.pop()
        if not state.sid_released:
            try:
                self._ops.release_appcontainer(state.sid)
            except (OSError, RuntimeError, ValueError):
                return False
            state.sid_released = True
        self._states.pop(pid, None)
        return True

    @staticmethod
    def _environment(snapshot: ScopeSnapshot) -> dict[str, str]:
        """Keep the Windows loader/runtime roots explicit in the attested scope."""
        if sys.platform != "win32":
            return minimal_environment()
        system_root = Path(os.environ.get("SystemRoot", "")).resolve()
        runtime_roots = snapshot.readonly_runtime_roots
        required = (system_root, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
        if not system_root.is_dir() or any(
            not any(required_root.is_relative_to(root) for root in runtime_roots)
            for required_root in required
        ):
            raise ValueError("WINDOWS_RUNTIME_ROOT_NOT_ATTESTED")
        environment = {
            "SystemRoot": str(system_root),
            "WINDIR": str(system_root),
            "SystemDrive": system_root.anchor.rstrip("\\"),
            "PATH": str(system_root / "System32"),
            "COMSPEC": str(system_root / "System32" / "cmd.exe"),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "OS": "Windows_NT",
            "USERPROFILE": str(snapshot.temporary_root),
            "HOMEDRIVE": snapshot.temporary_root.drive,
            "HOMEPATH": str(snapshot.temporary_root).removeprefix(snapshot.temporary_root.drive),
            "APPDATA": str(snapshot.temporary_root),
            "LOCALAPPDATA": str(snapshot.temporary_root),
            "TEMP": str(snapshot.temporary_root),
            "TMP": str(snapshot.temporary_root),
            "LANG": "C",
            "LC_ALL": "C",
        }
        for drive, current in (
            (system_root.drive, system_root),
            (snapshot.shadow_root.drive, snapshot.shadow_root),
        ):
            if drive:
                environment[f"={drive}"] = str(current)
        return environment

    def _setup(self, snapshot: ScopeSnapshot) -> tuple[str, str, list[Path], str]:
        assert self._ops is not None
        sid = ""
        token: str | None = None
        granted: list[Path] = []
        job: str | None = None
        try:
            sid = self._ops.create_appcontainer(snapshot)
            token = self._ops.create_restricted_token(sid)
            for root, mode in self._acl_grants(snapshot):
                self._ops.grant_scope_acl(root, sid, mode)
                granted.append(root)
            job = self._ops.create_kill_on_close_job()
            assert token is not None
            return sid, token, granted, job
        except BaseException:
            if sid:
                self._record_cleanup_debt(sid, token, granted, job)
            raise

    def _canary(self, snapshot: ScopeSnapshot) -> bool:
        assert self._ops is not None
        sid = ""
        token: str | None = None
        granted: list[Path] = []
        job: str | None = None
        pid: int | None = None
        termination_required = False
        canary_passed = False
        challenge = secrets.token_hex(16)
        protected_canary = snapshot.protected_root / f".yagcode-windows-canary-{challenge}"
        shadow_canary = snapshot.shadow_root / f".yagcode-windows-shadow-{challenge}"
        output = snapshot.shadow_root / f".yagcode-windows-receipt-{challenge}"
        stolen = snapshot.protected_root / f".yagcode-windows-stolen-{challenge}"
        listener: socket.socket | None = None
        try:
            descriptor = os.open(
                protected_canary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as file:
                file.write(b"must-remain-unreadable")
            shadow_canary.write_text("before", encoding="utf-8")
            output.unlink(missing_ok=True)
            sid, token, granted, job = self._setup(snapshot)
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.setblocking(False)
            host, port = listener.getsockname()
            code = (
                "from pathlib import Path; import socket, subprocess, sys\n"
                "protected, output, canary, stolen = map(Path, sys.argv[1:5])\n"
                "existing = Path(sys.argv[5]); challenge = sys.argv[6]\n"
                "checks=[]\n"
                "for attempt in (lambda: canary.read_bytes(), lambda: stolen.write_bytes(b'x'), lambda: socket.create_connection((sys.argv[7], int(sys.argv[8])), timeout=1).close()):\n"
                "    try: attempt(); checks.append(False)\n"
                "    except OSError: checks.append(True)\n"
                "try: before=existing.read_text(); existing.write_text('after'); checks.append(before == 'before' and existing.read_text() == 'after')\n"
                "except OSError: checks.append(False)\n"
                "child = 'from pathlib import Path; import sys; p=Path(sys.argv[1]);\\ntry: p.read_bytes(); raise SystemExit(9)\\nexcept OSError: raise SystemExit(0)'\n"
                "checks.append(subprocess.run([sys.executable, '-c', child, str(canary)]).returncode == 0)\n"
                "output.write_text(challenge + ':' + ','.join(map(str, checks)))\n"
                "raise SystemExit(0 if all(checks) else 7)\n"
            )
            request = ProcessRequest(
                sys.executable,
                ("-c", code, str(snapshot.protected_root), str(output), str(protected_canary), str(stolen), str(shadow_canary), challenge, host, str(port)),
            )
            pid, thread = self._ops.spawn_suspended(request, snapshot.shadow_root, self._environment(snapshot), token, sid)
            termination_required = True
            self._ops.assign_job(pid, job)
            self._ops.resume_suspended(thread)
            self._ops.close_token(token)
            token = None
            exit_code = self._ops.wait_for_exit(pid, 10_000)
            termination_required = exit_code is None
            try:
                connection, _ = listener.accept()
            except BlockingIOError:
                network_connected = False
            else:
                connection.close()
                network_connected = True
            canary_passed = (
                not network_connected
                and exit_code == 0
                and output.read_text(encoding="utf-8") == f"{challenge}:True,True,True,True,True"
            )
        except (OSError, RuntimeError, ValueError):
            canary_passed = False
        finally:
            if sid:
                canary_passed = self._record_cleanup_debt(
                    sid, token, granted, job, pid if termination_required else None, thread if termination_required else None
                ) and canary_passed
            if listener is not None:
                listener.close()
            protected_canary.unlink(missing_ok=True)
            shadow_canary.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            stolen.unlink(missing_ok=True)
        return canary_passed

    def self_test(self, scope: SandboxScope) -> SandboxAttestation:
        if not self._retry_debts():
            return SandboxAttestation(scope_failure_hash(scope), False, "SANDBOX_CLEANUP_UNCONFIRMED", "windows")
        try:
            snapshot = capture_scope_snapshot(scope)
        except (OSError, ValueError):
            return SandboxAttestation(scope_failure_hash(scope), False, "SANDBOX_SCOPE_INVALID", "windows")
        if self._ops is None:
            reason = "WINDOWS_APPCONTAINER_ADAPTER_UNAVAILABLE" if sys.platform == "win32" else "UNSUPPORTED_SANDBOX_PLATFORM"
            return SandboxAttestation(snapshot.scope_hash, False, reason, "windows", snapshot)
        if not self._canary(snapshot):
            if self._cleanup_debts:
                return SandboxAttestation(snapshot.scope_hash, False, "SANDBOX_CLEANUP_UNCONFIRMED", "windows", snapshot)
            return SandboxAttestation(snapshot.scope_hash, False, "WINDOWS_SANDBOX_CANARY_FAILED", "windows", snapshot)
        attestation = attest_snapshot(snapshot, backend="windows")
        self._attestations[attestation.scope_hash] = attestation
        return attestation

    def start(self, request: ProcessRequest, attestation: SandboxAttestation) -> ProcessHandle:
        if not self._retry_debts():
            return ProcessHandle(False, "SANDBOX_CLEANUP_UNCONFIRMED")
        if self._ops is None or not attestation_is_current(attestation) or self._attestations.get(attestation.scope_hash) != attestation or attestation.snapshot is None:
            return ProcessHandle(False, "SANDBOX_UNAVAILABLE")
        snapshot = attestation.snapshot
        sid = ""
        token: str | None = None
        granted: list[Path] = []
        job: str | None = None
        try:
            sid, token, granted, job = self._setup(snapshot)
            pid, thread = self._ops.spawn_suspended(request, snapshot.shadow_root, self._environment(snapshot), token, sid)
            self._ops.assign_job(pid, job)
            self._ops.resume_suspended(thread)
            self._ops.close_token(token)
            token = None
        except (OSError, RuntimeError, ValueError):
            if "pid" in locals() and "thread" in locals():
                if sid:
                    self._record_cleanup_debt(sid, token, granted, job, pid, thread)
                else:
                    try:
                        self._ops.terminate_suspended(pid, thread)
                    except (OSError, RuntimeError, ValueError):
                        return ProcessHandle(False, "SANDBOX_CLEANUP_UNCONFIRMED")
            elif sid:
                self._record_cleanup_debt(sid, token, granted, job)
            if self._cleanup_debts:
                return ProcessHandle(False, "SANDBOX_CLEANUP_UNCONFIRMED")
            return ProcessHandle(False, "SANDBOX_START_FAILED")
        self._states[pid] = _WindowsHandleState(sid, job, snapshot, list(granted))
        return ProcessHandle(True, "PROCESS_STARTED", pid)

    def terminate_tree(self, handle: ProcessHandle) -> TerminationResult:
        if handle.pid is None or self._ops is None:
            return TerminationResult("PROCESS_NOT_STARTED", False)
        state = self._states.get(handle.pid)
        if state is None:
            return TerminationResult("PROCESS_NOT_STARTED", False)
        exited = False
        if state.returncode is None:
            try:
                if not state.job_closed:
                    self._ops.close_job(state.job)
                    state.job_closed = True
                code = self._ops.wait_for_exit(handle.pid, 10_000)
                if code is not None:
                    state.returncode = code
                    exited = True
            except (OSError, RuntimeError, ValueError):
                exited = False
        else:
            exited = True
        restored = self._retry_handle_cleanup(handle.pid, state) if exited else False
        return TerminationResult(
            "PROCESS_TREE_TERMINATED" if exited and restored else "PROCESS_TREE_TERMINATION_UNCONFIRMED", exited and restored
        )

    def reconcile(self, handle: ProcessHandle) -> ReconciliationResult:
        if handle.pid is None or self._ops is None:
            return ReconciliationResult("PROCESS_NOT_STARTED", None)
        state = self._states.get(handle.pid)
        if state is not None and state.returncode is not None:
            if not self._retry_handle_cleanup(handle.pid, state):
                return ReconciliationResult("PROCESS_CLEANUP_UNCONFIRMED", state.returncode)
            return ReconciliationResult("PROCESS_EXITED", state.returncode)
        try:
            code = self._ops.wait_for_exit(handle.pid, 0)
        except (OSError, RuntimeError, ValueError):
            return ReconciliationResult("PROCESS_STATUS_UNAVAILABLE", None)
        if code is None:
            return ReconciliationResult("PROCESS_RUNNING", None)
        if state is not None:
            state.returncode = code
            if not self._retry_handle_cleanup(handle.pid, state):
                return ReconciliationResult("PROCESS_CLEANUP_UNCONFIRMED", code)
        return ReconciliationResult("PROCESS_EXITED", code)


__all__ = ["CtypesWindowsNativeOps", "WindowsNativeOps", "WindowsSandboxRunner"]
