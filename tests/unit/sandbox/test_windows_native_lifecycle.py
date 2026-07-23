"""Platform-neutral ctypes seam contracts for Windows process ownership."""

from __future__ import annotations

import ctypes
import importlib
from pathlib import Path

import pytest


def _production() -> tuple[object, object]:
    try:
        return (
            importlib.import_module("yagcode.sandbox.base"),
            importlib.import_module("yagcode.sandbox.windows"),
        )
    except ModuleNotFoundError as error:
        pytest.fail(f"WINDOWS_NATIVE_LIFECYCLE_MISSING:{error.name}")


class _Kernel:
    def __init__(self, *, update_result: int = 1, close_result: int = 1) -> None:
        self.update_result = update_result
        self.close_result = close_result
        self.deleted_attribute_lists = 0
        self.closed: list[int | None] = []
        self.terminated: list[int | None] = []
        self.application_name: str | None = None
        self.command_line: str | None = None
        self.valid_process_info = True

    def InitializeProcThreadAttributeList(self, attributes: object, count: int, flags: int, size: object) -> int:
        ctypes.cast(size, ctypes.POINTER(ctypes.c_size_t)).contents.value = 64
        return int(attributes is not None)

    def UpdateProcThreadAttribute(self, *args: object) -> int:
        return self.update_result

    def DeleteProcThreadAttributeList(self, attributes: object) -> None:
        self.deleted_attribute_lists += 1

    def CloseHandle(self, handle: ctypes.c_void_p) -> int:
        self.closed.append(handle.value)
        return self.close_result

    def ResumeThread(self, handle: ctypes.c_void_p) -> int:
        return 1

    def TerminateProcess(self, handle: ctypes.c_void_p, code: int) -> int:
        self.terminated.append(handle.value)
        return 1

    def CreateProcessW(
        self,
        application_name: str | None,
        command_line: object,
        process_attributes: object,
        thread_attributes: object,
        inherit_handles: bool,
        flags: int,
        environment: object,
        cwd: str,
        startup: object,
        process_info: object,
    ) -> int:
        self.application_name = application_name
        self.command_line = ctypes.wstring_at(command_line)
        address = ctypes.cast(process_info, ctypes.c_void_p).value
        assert address is not None
        ctypes.c_void_p.from_address(address).value = 0x100
        ctypes.c_void_p.from_address(address + ctypes.sizeof(ctypes.c_void_p)).value = 0x200
        ctypes.c_ulong.from_address(address + 2 * ctypes.sizeof(ctypes.c_void_p)).value = 77 if self.valid_process_info else 0
        return 1


def _ops(windows: object, kernel: _Kernel, *, valid_process_info: bool = True) -> object:
    ops = object.__new__(windows.CtypesWindowsNativeOps)
    kernel.valid_process_info = valid_process_info
    ops._kernel32 = kernel
    ops._sid_pointers = {"sid": 0x123}
    ops._processes = {}
    return ops


def test_native_spawn_uses_exact_application_name_and_closes_resumed_thread_once(tmp_path: Path) -> None:
    base, windows = _production()
    kernel = _Kernel()
    ops = _ops(windows, kernel)
    request = base.ProcessRequest("C:\\Program Files\\Yagcode\\runner.exe", ("--task", "quoted value"))

    pid, state = ops.spawn_suspended(request, tmp_path, {"PATH": "C:\\Windows"}, "9", "sid")

    assert pid == 77
    assert kernel.application_name == request.executable
    assert kernel.command_line is not None and request.executable in kernel.command_line
    ops.resume_suspended(state)
    assert state.thread_handle is None
    ops.terminate_suspended(pid, state)
    assert kernel.closed == [0x200, 0x100]
    assert kernel.deleted_attribute_lists == 1


def test_native_spawn_attribute_failure_deletes_attribute_list_without_process_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    kernel = _Kernel(update_result=0)
    ops = _ops(windows, kernel)
    monkeypatch.setattr(windows.ctypes, "get_last_error", lambda: 5, raising=False)

    with pytest.raises(OSError, match="UpdateProcThreadAttribute"):
        ops.spawn_suspended(base.ProcessRequest("C:\\runner.exe", ()), tmp_path, {"PATH": "C:\\Windows"}, "9", "sid")

    assert kernel.deleted_attribute_lists == 1
    assert kernel.closed == []
    assert ops._processes == {}


def test_native_resume_close_failure_is_observable_and_keeps_thread_owned(tmp_path: Path) -> None:
    base, windows = _production()
    kernel = _Kernel(close_result=0)
    ops = _ops(windows, kernel)
    request = base.ProcessRequest("C:\\runner.exe", ())
    _, state = ops.spawn_suspended(request, tmp_path, {"PATH": "C:\\Windows"}, "9", "sid")

    with pytest.raises(OSError, match=r"CloseHandle\(thread\)"):
        ops.resume_suspended(state)

    assert state.thread_handle == 0x200
    assert kernel.closed == [0x200]


def test_native_spawn_releases_created_handles_when_process_information_is_invalid(tmp_path: Path) -> None:
    base, windows = _production()
    kernel = _Kernel()
    ops = _ops(windows, kernel, valid_process_info=False)

    with pytest.raises(OSError, match="PROCESS_INFORMATION_INVALID"):
        ops.spawn_suspended(base.ProcessRequest("C:\\runner.exe", ()), tmp_path, {"PATH": "C:\\Windows"}, "9", "sid")

    assert kernel.terminated == [0x100]
    assert kernel.closed == [0x200, 0x100]
    assert kernel.deleted_attribute_lists == 1
    assert ops._processes == {}
