"""Platform-neutral DACL snapshot and restoration contracts."""

from __future__ import annotations

import ctypes
import importlib
from pathlib import Path

import pytest


def _production() -> object:
    try:
        return importlib.import_module("yagcode.sandbox.windows")
    except ModuleNotFoundError as error:
        pytest.fail(f"WINDOWS_DACL_CONTRACT_MISSING:{error.name}")


class _Function:
    def __init__(self) -> None:
        self.restype: object | None = None
        self.argtypes: list[object] | None = None

    def __call__(self, *args: object) -> int:
        return 1


class _Library:
    def __init__(self) -> None:
        self.functions: dict[str, _Function] = {}

    def __getattr__(self, name: str) -> _Function:
        return self.functions.setdefault(name, _Function())


class _Kernel:
    def __init__(self) -> None:
        self.freed: list[int | None] = []

    def LocalFree(self, value: ctypes.c_void_p) -> None:
        self.freed.append(value.value)


class _Advapi:
    def __init__(self, *, present: bool = True, dacl: int | None = 0x2222, control: int = 0) -> None:
        self.present = present
        self.dacl = dacl
        self.control = control
        self.security_infos: list[int] = []
        self.control_updates: list[tuple[int, int]] = []
        self.fail_control_update = False
        self.fail_restore = False

    @staticmethod
    def _set_pointer(target: object, value: int | None) -> None:
        ctypes.cast(target, ctypes.POINTER(ctypes.c_void_p)).contents.value = value

    def GetNamedSecurityInfoW(
        self,
        path: str,
        object_type: int,
        security_info: int,
        owner: object,
        group: object,
        dacl: object,
        sacl: object,
        descriptor: object,
    ) -> int:
        self._set_pointer(dacl, self.dacl)
        self._set_pointer(descriptor, 0x1111)
        return 0

    def GetSecurityDescriptorDacl(self, descriptor: object, present: object, dacl: object, defaulted: object) -> int:
        ctypes.cast(present, ctypes.POINTER(ctypes.c_int)).contents.value = int(self.present)
        self._set_pointer(dacl, self.dacl)
        ctypes.cast(defaulted, ctypes.POINTER(ctypes.c_int)).contents.value = 0
        return 1

    def GetSecurityDescriptorControl(self, descriptor: object, control: object, revision: object) -> int:
        ctypes.cast(control, ctypes.POINTER(ctypes.c_ushort)).contents.value = self.control
        ctypes.cast(revision, ctypes.POINTER(ctypes.c_ulong)).contents.value = 1
        return 1

    def SetSecurityDescriptorControl(self, descriptor: ctypes.c_void_p, control_bits: int, bits_to_set: int) -> int:
        self.control_updates.append((control_bits, bits_to_set))
        return 0 if self.fail_control_update else 1

    def SetEntriesInAclW(self, count: int, entries: object, old_dacl: object, new_dacl: object) -> int:
        self._set_pointer(new_dacl, 0x3333)
        return 0

    def SetNamedSecurityInfoW(
        self,
        path: str,
        object_type: int,
        security_info: int,
        owner: object,
        group: object,
        dacl: ctypes.c_void_p,
        sacl: object,
    ) -> int:
        self.security_infos.append(security_info)
        if self.fail_restore and dacl.value == self.dacl:
            return 5
        return 0

    def SetFileSecurityW(self, path: str, security_info: int, descriptor: ctypes.c_void_p) -> int:
        self.security_infos.append(security_info)
        if self.fail_restore and descriptor.value == 0x1111:
            return 0
        return 1


def _ops(windows: object, **kwargs: object) -> tuple[object, _Kernel, _Advapi]:
    ops = object.__new__(windows.CtypesWindowsNativeOps)
    kernel = _Kernel()
    advapi = _Advapi(**kwargs)
    ops._kernel32 = kernel
    ops._advapi32 = advapi
    ops._sid_pointers = {"sid": 0x4444}
    ops._acl_backups = {}
    ops._acl_tree_members = {}
    return ops, kernel, advapi


def test_dacl_control_abi_is_bound_with_x64_pointer_types() -> None:
    windows = _production()
    ops = object.__new__(windows.CtypesWindowsNativeOps)
    ops._kernel32 = _Library()
    ops._advapi32 = _Library()
    ops._userenv = _Library()

    ops._configure_abi()

    function = ops._advapi32.functions["GetSecurityDescriptorControl"]
    assert function.restype is ctypes.c_int
    assert function.argtypes == [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_ulong),
    ]
    restore_function = ops._advapi32.functions["SetSecurityDescriptorControl"]
    assert restore_function.restype is ctypes.c_int
    assert restore_function.argtypes == [
        ctypes.c_void_p,
        ctypes.c_ushort,
        ctypes.c_ushort,
    ]


@pytest.mark.parametrize(
    ("control", "expected_restore_flag"),
    ((0, 0x20000004), (0x0400, 0x00000004), (0x1000, 0x80000004)),
)
def test_dacl_restore_preserves_control_flags(control: int, expected_restore_flag: int, tmp_path: Path) -> None:
    windows = _production()
    ops, kernel, advapi = _ops(windows, control=control)
    root = tmp_path / "root"
    root.mkdir()

    ops.grant_scope_acl(root, "sid", "write")
    backup = ops._acl_backups[(str(root), "sid")]
    assert backup.dacl == 0x2222
    assert backup.control == control
    assert backup.dacl_present
    assert backup.dacl_protected is bool(control & 0x1000)
    assert backup.dacl_auto_inherited is bool(control & 0x0400)
    assert backup.mode == "write"
    ops.revoke_scope_acl(root, "sid")

    assert advapi.control_updates == [(0x1500, control & 0x1500)]
    assert advapi.security_infos == [0x00000004, expected_restore_flag]
    assert ops._acl_backups == {}
    assert kernel.freed == [0x3333, 0x1111]


def test_auto_inherited_dacl_restore_failure_retains_backup_until_retry(tmp_path: Path) -> None:
    windows = _production()
    ops, kernel, advapi = _ops(windows, control=0x0400)
    root = tmp_path / "root"
    root.mkdir()
    ops.grant_scope_acl(root, "sid", "write")
    advapi.fail_restore = True

    with pytest.raises(OSError, match="RestoreNamedSecurityInfoW"):
        ops.revoke_scope_acl(root, "sid")

    assert (str(root), "sid") in ops._acl_backups
    assert kernel.freed == [0x3333]
    advapi.fail_restore = False
    ops.revoke_scope_acl(root, "sid")

    assert ops._acl_backups == {}
    assert advapi.control_updates == [(0x1500, 0x0400), (0x1500, 0x0400)]
    assert advapi.security_infos == [0x00000004, 0x00000004, 0x00000004]
    assert kernel.freed == [0x3333, 0x1111]


@pytest.mark.parametrize(("present", "dacl"), ((False, 0x2222), (True, None)))
def test_dacl_backup_rejects_absent_or_null_dacl_before_grant(present: bool, dacl: int | None, tmp_path: Path) -> None:
    windows = _production()
    ops, kernel, advapi = _ops(windows, present=present, dacl=dacl)
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(OSError, match="ACL_DACL_EXACT_RESTORE_UNAVAILABLE"):
        ops.grant_scope_acl(root, "sid", "write")

    assert advapi.security_infos == []
    assert ops._acl_backups == {}
    assert kernel.freed == [0x1111]


def test_non_auto_dacl_restore_failure_retains_backup_until_the_same_restore_retries(tmp_path: Path) -> None:
    windows = _production()
    ops, kernel, advapi = _ops(windows, control=0x1000)
    root = tmp_path / "root"
    root.mkdir()
    ops.grant_scope_acl(root, "sid", "write")
    advapi.fail_restore = True

    with pytest.raises(OSError, match="RestoreFileSecurityW"):
        ops.revoke_scope_acl(root, "sid")

    assert (str(root), "sid") in ops._acl_backups
    assert kernel.freed == [0x3333]
    advapi.fail_restore = False
    ops.revoke_scope_acl(root, "sid")

    assert ops._acl_backups == {}
    assert advapi.control_updates == [(0x1500, 0x1000), (0x1500, 0x1000)]
    assert advapi.security_infos == [0x00000004, 0x80000004, 0x80000004]
    assert kernel.freed == [0x3333, 0x1111]


def test_traverse_dacl_restore_uses_descriptor_without_inheritance_control(tmp_path: Path) -> None:
    windows = _production()
    ops, kernel, advapi = _ops(windows)
    root = tmp_path / "root"
    root.mkdir()
    ops.grant_scope_acl(root, "sid", "traverse")
    advapi.fail_restore = True

    with pytest.raises(OSError, match="RestoreFileSecurityW"):
        ops.revoke_scope_acl(root, "sid")

    assert (str(root), "sid") in ops._acl_backups
    assert kernel.freed == [0x3333]
    advapi.fail_restore = False
    ops.revoke_scope_acl(root, "sid")

    assert ops._acl_backups == {}
    assert advapi.control_updates == [(0x1500, 0), (0x1500, 0)]
    assert advapi.security_infos == [0x00000004, 0x00000004, 0x00000004]
    assert kernel.freed == [0x3333, 0x1111]


def test_dacl_grant_on_windows_covers_existing_children_and_restores_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _production()
    ops, kernel, advapi = _ops(windows)
    root = tmp_path / "root"
    child = root / "child.txt"
    root.mkdir()
    child.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(windows.sys, "platform", "win32")

    ops.grant_scope_acl(root, "sid", "readonly")

    assert set(ops._acl_backups) == {(str(root), "sid"), (str(child), "sid")}
    ops.revoke_scope_acl(root, "sid")
    assert ops._acl_backups == {}
    assert ops._acl_tree_members == {}
    assert advapi.control_updates == [(0x1500, 0), (0x1500, 0)]
    assert advapi.security_infos == [0x00000004, 0x00000004, 0x20000004, 0x20000004]
    assert kernel.freed == [0x3333, 0x3333, 0x1111, 0x1111]
