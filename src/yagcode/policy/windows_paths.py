"""Windows no-reparse relative-handle traversal.

The resolver is platform-neutral through ``WindowsRelativeHandleOps``; the
Windows adapter uses ``NtCreateFile`` with ``OBJECT_ATTRIBUTES.RootDirectory``
for every component, so no post-resolution path string is trusted.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from dataclasses import dataclass
from typing import Any, Protocol


class WindowsPathError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WindowsFileIdentity:
    volume_serial: str
    file_id: str
    reparse_tag: int
    link_count: int = 1


@dataclass(frozen=True, slots=True)
class WindowsResolvedTarget:
    root_identity: WindowsFileIdentity
    component_identities: tuple[WindowsFileIdentity, ...]
    root: str
    parent_components: tuple[str, ...]
    basename: str
    target_identity: WindowsFileIdentity | None
    target_precondition_hash: str | None


class WindowsRelativeHandleOps(Protocol):
    def open_root(self, root: str) -> object: ...
    def open_relative_no_reparse(self, parent: object, component: str, directory: bool) -> object: ...
    def identity(self, handle: object) -> WindowsFileIdentity: ...
    def content_hash(self, handle: object) -> str: ...
    def write_relative_no_reparse(
        self, parent: object, basename: str, expected: WindowsFileIdentity | None, expected_hash: str | None, content: bytes
    ) -> None: ...
    def close(self, handle: object) -> None: ...


class WindowsNoReparseResolver:
    """Open each lexical component relative to its verified parent handle."""

    def __init__(self, ops: WindowsRelativeHandleOps) -> None:
        self._ops = ops

    def resolve_for_write(self, root: str, components: tuple[str, ...]) -> WindowsResolvedTarget:
        if not components or any(
            not part or part in {".", ".."} or "\\" in part or "/" in part or ":" in part or "\x00" in part
            for part in components
        ):
            raise WindowsPathError("WINDOWS_PATH_COMPONENT_INVALID")
        handles: list[object] = []
        try:
            current = self._ops.open_root(root)
            handles.append(current)
            root_identity = self._ops.identity(current)
            if root_identity.reparse_tag:
                raise WindowsPathError("WINDOWS_REPARSE_POINT_REJECTED")
            identities = [root_identity]
            for component in components[:-1]:
                current = self._ops.open_relative_no_reparse(current, component, True)
                handles.append(current)
                identity = self._ops.identity(current)
                if identity.reparse_tag:
                    raise WindowsPathError("WINDOWS_REPARSE_POINT_REJECTED")
                identities.append(identity)
            try:
                target = self._ops.open_relative_no_reparse(current, components[-1], False)
            except FileNotFoundError:
                target_identity = None
                target_precondition_hash: str | None = None
            else:
                handles.append(target)
                target_identity = self._ops.identity(target)
                if target_identity.reparse_tag:
                    raise WindowsPathError("WINDOWS_REPARSE_POINT_REJECTED")
                if target_identity.link_count != 1:
                    raise WindowsPathError("WINDOWS_HARDLINK_REJECTED")
                target_precondition_hash = self._ops.content_hash(target)
            return WindowsResolvedTarget(identities[0], tuple(identities), root, components[:-1], components[-1], target_identity, target_precondition_hash)
        finally:
            while handles:
                self._ops.close(handles.pop())


class WindowsSecurePathDispatcher:
    """Reopen the trusted handle chain and write only after identity revalidation."""

    def __init__(self, ops: WindowsRelativeHandleOps) -> None:
        self._ops = ops

    def write(self, target: WindowsResolvedTarget, content: bytes) -> str:
        if type(target) is not WindowsResolvedTarget or type(content) is not bytes:
            return "WINDOWS_PATH_ARGUMENT_INVALID"
        handles: list[object] = []
        try:
            current = self._ops.open_root(target.root)
            handles.append(current)
            root_identity = self._ops.identity(current)
            if root_identity.reparse_tag:
                return "WINDOWS_REPARSE_POINT_REJECTED"
            observed = [root_identity]
            for component in target.parent_components:
                current = self._ops.open_relative_no_reparse(current, component, True)
                handles.append(current)
                identity = self._ops.identity(current)
                if identity.reparse_tag:
                    return "WINDOWS_REPARSE_POINT_REJECTED"
                observed.append(identity)
            if tuple(observed) != target.component_identities:
                return "STALE_TARGET"
            self._ops.write_relative_no_reparse(
                current, target.basename, target.target_identity, target.target_precondition_hash, content
            )
            return "WRITTEN"
        except (FileNotFoundError, OSError, WindowsPathError):
            return "STALE_TARGET"
        finally:
            while handles:
                self._ops.close(handles.pop())


class NtCreateFileRelativeOps:
    """Win32/NT adapter boundary; instantiated only by the Windows runtime.

    Native implementation must call NtCreateFile with OBJ_DONT_REPARSE and the
    parent handle as RootDirectory, then GetFileInformationByHandleEx for volume
    serial/file ID/reparse tag.  It intentionally raises until loaded on a
    Windows release runner rather than falling back to CreateFile path strings.
    """

    _OBJ_CASE_INSENSITIVE = 0x00000040
    _OBJ_DONT_REPARSE = 0x00001000
    _FILE_OPEN = 0x00000001
    _FILE_CREATE = 0x00000002
    _FILE_DIRECTORY_FILE = 0x00000001
    _FILE_NON_DIRECTORY_FILE = 0x00000040
    _FILE_OPEN_REPARSE_POINT = 0x00200000
    _FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
    _FILE_SHARE_READ_WRITE_DELETE = 0x00000007
    _FILE_READ_DATA = 0x00000001
    _FILE_READ_ATTRIBUTES = 0x00000080
    _FILE_WRITE_DATA = 0x00000002
    _FILE_WRITE_ATTRIBUTES = 0x00000100
    _SYNCHRONIZE = 0x00100000
    _FILE_ID_INFO = 18
    _FILE_STANDARD_INFO = 1
    _FSCTL_GET_REPARSE_POINT = 0x000900A8
    _ERROR_NOT_A_REPARSE_POINT = 4390
    _MISSING_STATUSES = frozenset({0xC000000F, 0xC0000034, 0xC000003A})
    _STATUS_REPARSE_POINT_ENCOUNTERED = 0xC000050B

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise WindowsPathError("WINDOWS_NTCREATEFILE_ADAPTER_REQUIRES_NATIVE_RUNNER")
        win_dll: Any = getattr(ctypes, "WinDLL")
        self._ntdll: Any = win_dll("ntdll", use_last_error=True)
        self._kernel32: Any = win_dll("kernel32", use_last_error=True)
        self._configure_abi()

    @staticmethod
    def _bind(library: Any, name: str, restype: Any, argtypes: list[Any]) -> None:
        function: Any = getattr(library, name)
        function.restype = restype
        function.argtypes = argtypes

    def _configure_abi(self) -> None:
        void_p = ctypes.c_void_p
        dword = ctypes.c_ulong
        self._bind(
            self._ntdll,
            "NtCreateFile",
            ctypes.c_long,
            [ctypes.POINTER(void_p), dword, void_p, void_p, void_p, dword, dword, dword, dword, void_p, dword],
        )
        self._bind(self._ntdll, "NtSetInformationFile", ctypes.c_long, [void_p, void_p, void_p, dword, ctypes.c_int])
        self._bind(self._ntdll, "NtWriteFile", ctypes.c_long, [void_p, void_p, void_p, void_p, void_p, void_p, dword, void_p, void_p])
        self._bind(self._ntdll, "NtFlushBuffersFile", ctypes.c_long, [void_p, void_p])
        self._bind(self._kernel32, "GetFileInformationByHandleEx", ctypes.c_int, [void_p, ctypes.c_int, void_p, dword])
        self._bind(self._kernel32, "DeviceIoControl", ctypes.c_int, [void_p, dword, void_p, dword, void_p, dword, ctypes.POINTER(dword), void_p])
        self._bind(self._kernel32, "CloseHandle", ctypes.c_int, [void_p])
        self._bind(self._kernel32, "GetFileSizeEx", ctypes.c_int, [void_p, ctypes.POINTER(ctypes.c_longlong)])
        self._bind(self._kernel32, "SetFilePointerEx", ctypes.c_int, [void_p, ctypes.c_longlong, void_p, dword])
        self._bind(self._kernel32, "ReadFile", ctypes.c_int, [void_p, void_p, dword, ctypes.POINTER(dword), void_p])

    @staticmethod
    def _check_nt(status: int, operation: str) -> None:
        unsigned_status = status & 0xFFFFFFFF
        if unsigned_status in NtCreateFileRelativeOps._MISSING_STATUSES:
            raise FileNotFoundError(f"WINDOWS_NTCREATEFILE_{operation}_MISSING")
        if unsigned_status == NtCreateFileRelativeOps._STATUS_REPARSE_POINT_ENCOUNTERED:
            raise WindowsPathError("WINDOWS_REPARSE_POINT_REJECTED")
        if status < 0:  # NT_SUCCESS: warning/informational statuses are not failures.
            raise WindowsPathError(f"WINDOWS_NTCREATEFILE_{operation}_FAILED:{status:#x}")

    @staticmethod
    def _native_path(root: str) -> str:
        if "\x00" in root:
            raise WindowsPathError("WINDOWS_PATH_ROOT_INVALID")
        absolute = os.path.abspath(root)
        if not os.path.isabs(absolute):
            raise WindowsPathError("WINDOWS_PATH_ROOT_INVALID")
        if absolute.startswith("\\\\"):
            return "\\??\\UNC\\" + absolute[2:]
        return "\\??\\" + absolute

    @staticmethod
    def _unicode(value: str) -> tuple[ctypes.Structure, ctypes.Array[ctypes.c_wchar]]:
        class UNICODE_STRING(ctypes.Structure):
            _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort), ("Buffer", ctypes.c_wchar_p)]

        buffer = ctypes.create_unicode_buffer(value)
        length = len(value.encode("utf-16-le"))
        return UNICODE_STRING(length, length + ctypes.sizeof(ctypes.c_wchar), ctypes.cast(buffer, ctypes.c_wchar_p)), buffer

    @staticmethod
    def _attributes(path: ctypes.Structure, root: int | None, *, dont_reparse: bool = True) -> ctypes.Structure:
        class OBJECT_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("Length", ctypes.c_ulong),
                ("RootDirectory", ctypes.c_void_p),
                ("ObjectName", ctypes.c_void_p),
                ("Attributes", ctypes.c_ulong),
                ("SecurityDescriptor", ctypes.c_void_p),
                ("SecurityQualityOfService", ctypes.c_void_p),
            ]

        return OBJECT_ATTRIBUTES(
            ctypes.sizeof(OBJECT_ATTRIBUTES),
            ctypes.c_void_p(root) if root is not None else None,
            ctypes.cast(ctypes.byref(path), ctypes.c_void_p),
            NtCreateFileRelativeOps._OBJ_CASE_INSENSITIVE
            | (NtCreateFileRelativeOps._OBJ_DONT_REPARSE if dont_reparse else 0),
            None,
            None,
        )

    def _open(
        self,
        name: str,
        parent: int | None,
        directory: bool,
        *,
        desired_access: int | None = None,
        disposition: int | None = None,
        dont_reparse: bool = True,
    ) -> int:
        class IO_STATUS_BLOCK(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_long), ("Information", ctypes.c_size_t)]

        unicode_name, _buffer = self._unicode(name)
        attributes = self._attributes(unicode_name, parent, dont_reparse=dont_reparse)
        status_block = IO_STATUS_BLOCK()
        handle = ctypes.c_void_p()
        create_options = self._FILE_OPEN_REPARSE_POINT | (
            self._FILE_DIRECTORY_FILE if directory else self._FILE_NON_DIRECTORY_FILE
        ) | self._FILE_SYNCHRONOUS_IO_NONALERT
        status = self._ntdll.NtCreateFile(
            ctypes.byref(handle),
            desired_access if desired_access is not None else self._SYNCHRONIZE | self._FILE_READ_ATTRIBUTES,
            ctypes.byref(attributes),
            ctypes.byref(status_block),
            None,
            0,
            self._FILE_SHARE_READ_WRITE_DELETE,
            disposition if disposition is not None else self._FILE_OPEN,
            create_options,
            None,
            0,
        )
        self._check_nt(status, "OPEN")
        if not handle.value:
            raise WindowsPathError("WINDOWS_NTCREATEFILE_NULL_HANDLE")
        return int(handle.value)

    def open_root(self, root: str) -> object:
        return self._open(self._native_path(root), None, True, dont_reparse=False)

    def open_relative_no_reparse(self, parent: object, component: str, directory: bool) -> object:
        if not isinstance(parent, int) or parent <= 0:
            raise WindowsPathError("WINDOWS_PATH_PARENT_HANDLE_INVALID")
        desired_access = self._SYNCHRONIZE | self._FILE_READ_ATTRIBUTES
        if not directory:
            desired_access |= self._FILE_READ_DATA
        return self._open(component, parent, directory, desired_access=desired_access)

    def write_relative_no_reparse(
        self, parent: object, basename: str, expected: WindowsFileIdentity | None, expected_hash: str | None, content: bytes
    ) -> None:
        if not isinstance(parent, int) or parent <= 0:
            raise WindowsPathError("WINDOWS_PATH_PARENT_HANDLE_INVALID")

        class IO_STATUS_BLOCK(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_long), ("Information", ctypes.c_size_t)]

        handle = self._open(
            basename,
            parent,
            False,
            desired_access=self._SYNCHRONIZE | self._FILE_READ_DATA | self._FILE_READ_ATTRIBUTES | self._FILE_WRITE_DATA | self._FILE_WRITE_ATTRIBUTES,
            disposition=self._FILE_CREATE if expected is None else self._FILE_OPEN,
        )
        try:
            actual_identity = self.identity(handle)
            if actual_identity.reparse_tag or (expected is not None and actual_identity != expected):
                raise WindowsPathError("WINDOWS_PATH_TARGET_STALE")
            if actual_identity.link_count != 1:
                raise WindowsPathError("WINDOWS_HARDLINK_REJECTED")
            if expected_hash is not None and self.content_hash(handle) != expected_hash:
                raise WindowsPathError("WINDOWS_PATH_CONTENT_STALE")
            if not self._kernel32.SetFilePointerEx(ctypes.c_void_p(handle), ctypes.c_longlong(0), None, 0):
                raise WindowsPathError("WINDOWS_PATH_WRITE_SEEK_FAILED")
            status = IO_STATUS_BLOCK()
            end = ctypes.c_longlong(0)
            self._check_nt(self._ntdll.NtSetInformationFile(ctypes.c_void_p(handle), ctypes.byref(status), ctypes.byref(end), ctypes.sizeof(end), 20), "TRUNCATE")
            self._check_nt(status.Status, "TRUNCATE_COMPLETION")
            data = ctypes.create_string_buffer(content)
            self._check_nt(self._ntdll.NtWriteFile(ctypes.c_void_p(handle), None, None, None, ctypes.byref(status), data, len(content), None, None), "WRITE")
            self._check_nt(status.Status, "WRITE_COMPLETION")
            if status.Information != len(content):
                raise WindowsPathError("WINDOWS_NTCREATEFILE_PARTIAL_WRITE")
            self._check_nt(self._ntdll.NtFlushBuffersFile(ctypes.c_void_p(handle), ctypes.byref(status)), "FLUSH")
            self._check_nt(status.Status, "FLUSH_COMPLETION")
        finally:
            self.close(handle)

    def content_hash(self, handle: object) -> str:
        if not isinstance(handle, int) or handle <= 0:
            raise WindowsPathError("WINDOWS_PATH_HANDLE_INVALID")
        size = ctypes.c_longlong()
        if not self._kernel32.GetFileSizeEx(ctypes.c_void_p(handle), ctypes.byref(size)) or size.value < 0:
            raise WindowsPathError("WINDOWS_PATH_CONTENT_SIZE_FAILED")
        if not self._kernel32.SetFilePointerEx(ctypes.c_void_p(handle), ctypes.c_longlong(0), None, 0):
            raise WindowsPathError("WINDOWS_PATH_CONTENT_SEEK_FAILED")
        digest = hashlib.sha256()
        remaining = size.value
        while remaining:
            request = min(remaining, 1 << 20)
            buffer = ctypes.create_string_buffer(request)
            received = ctypes.c_ulong()
            if not self._kernel32.ReadFile(ctypes.c_void_p(handle), buffer, request, ctypes.byref(received), None):
                raise WindowsPathError("WINDOWS_PATH_CONTENT_READ_FAILED")
            if received.value == 0:
                raise WindowsPathError("WINDOWS_PATH_CONTENT_SHORT_READ")
            digest.update(buffer.raw[: received.value])
            remaining -= received.value
        return digest.hexdigest()

    def identity(self, handle: object) -> WindowsFileIdentity:
        if not isinstance(handle, int) or handle <= 0:
            raise WindowsPathError("WINDOWS_PATH_HANDLE_INVALID")

        class FILE_ID_128(ctypes.Structure):
            _fields_ = [("Identifier", ctypes.c_byte * 16)]

        class FILE_ID_INFO(ctypes.Structure):
            _fields_ = [("VolumeSerialNumber", ctypes.c_ulonglong), ("FileId", FILE_ID_128)]

        class FILE_STANDARD_INFO(ctypes.Structure):
            _fields_ = [
                ("AllocationSize", ctypes.c_longlong),
                ("EndOfFile", ctypes.c_longlong),
                ("NumberOfLinks", ctypes.c_ulong),
                ("DeletePending", ctypes.c_ubyte),
                ("Directory", ctypes.c_ubyte),
            ]

        info = FILE_ID_INFO()
        if not self._kernel32.GetFileInformationByHandleEx(
            ctypes.c_void_p(handle), self._FILE_ID_INFO, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise WindowsPathError("WINDOWS_PATH_IDENTITY_QUERY_FAILED")
        standard = FILE_STANDARD_INFO()
        if not self._kernel32.GetFileInformationByHandleEx(
            ctypes.c_void_p(handle), self._FILE_STANDARD_INFO, ctypes.byref(standard), ctypes.sizeof(standard)
        ):
            raise WindowsPathError("WINDOWS_PATH_LINK_COUNT_QUERY_FAILED")
        output = ctypes.create_string_buffer(16 * 1024)
        returned = ctypes.c_ulong()
        reparse_tag = 0
        if not self._kernel32.DeviceIoControl(
            ctypes.c_void_p(handle), self._FSCTL_GET_REPARSE_POINT, None, 0, output, len(output), ctypes.byref(returned), None
        ):
            get_last_error: Any = getattr(ctypes, "get_last_error")
            if get_last_error() != self._ERROR_NOT_A_REPARSE_POINT:
                raise WindowsPathError("WINDOWS_PATH_REPARSE_QUERY_FAILED")
        elif returned.value >= 4:
            reparse_tag = int.from_bytes(output.raw[:4], "little")
        return WindowsFileIdentity(str(info.VolumeSerialNumber), bytes(info.FileId.Identifier).hex(), reparse_tag, int(standard.NumberOfLinks))

    def close(self, handle: object) -> None:
        if isinstance(handle, int) and handle > 0 and not self._kernel32.CloseHandle(ctypes.c_void_p(handle)):
            raise WindowsPathError("WINDOWS_PATH_HANDLE_CLOSE_FAILED")
