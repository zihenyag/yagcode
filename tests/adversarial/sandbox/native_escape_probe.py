"""Real platform probe; explicitly selected because python_files excludes native_* names.

The single marked case deliberately branches at runtime instead of using
``skipif``: ``--require-native-probe`` must reject an unavailable target rather
than turning a missing platform proof into a passing report.
"""

from __future__ import annotations

import importlib
import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.native_sandbox


WINDOWS_DISPATCHER_MATRIX_EVENTS = frozenset(
    {
        "existing_overwrite",
        "empty_write",
        "same_id_content_stale",
        "renamed_target_stale",
        "parent_junction_stale",
        "missing_relative_create",
        "missing_create_race_stale",
        "root_reparse_stale",
        "hardlink_alias_stale",
        "loopback_connect_denied",
        "protected_outside_hash",
        "flush_reopen_bytes",
        "dacl_after_self_test",
        "dacl_after_reconcile",
        "dacl_after_terminate",
        "existing_shadow_access",
        "existing_shadow_child_dacl_restored",
        "system_root_dacl_read_only",
    }
)

_WINDOWS_VOLATILE_DACL_CONTROL = 0x0400  # SE_DACL_AUTO_INHERITED is recomputed by Windows.


def windows_dispatcher_matrix_errors(events: set[str]) -> tuple[str, ...]:
    """Return each required native assertion that this probe did not execute."""
    return tuple(sorted(WINDOWS_DISPATCHER_MATRIX_EVENTS - events))


def windows_dacl_snapshot_matches(current: tuple[bytes, int], expected: tuple[bytes, int]) -> bool:
    """Compare effective DACL bytes while ignoring the Windows-managed auto-inherited bit."""
    return current[0] == expected[0] and (
        current[1] & ~_WINDOWS_VOLATILE_DACL_CONTROL
    ) == (expected[1] & ~_WINDOWS_VOLATILE_DACL_CONTROL)


def assert_windows_dacls_restored(before: dict[Path, tuple[bytes, int]]) -> None:
    for root, expected in before.items():
        current = _windows_dacl_snapshot(root)
        assert windows_dacl_snapshot_matches(current, expected), root


def _native_production() -> object:
    try:
        return importlib.import_module("yagcode.sandbox.macos")
    except ModuleNotFoundError as error:
        if error.name in {"yagcode.sandbox", "yagcode.sandbox.macos"}:
            pytest.fail("SANDBOX_CONTRACT_MISSING")
        raise


def _windows_dacl_snapshot(path: Path) -> tuple[bytes, int]:
    """Read the current DACL bytes and control word without mutating the target."""
    import ctypes

    if sys.platform != "win32":
        raise RuntimeError("WINDOWS_DACL_SNAPSHOT_UNAVAILABLE")
    dword = ctypes.c_ulong
    bool_t = ctypes.c_int
    void_p = ctypes.c_void_p
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.LocalFree.argtypes = [void_p]
    kernel32.LocalFree.restype = void_p
    advapi32.GetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p,
        dword,
        dword,
        void_p,
        void_p,
        ctypes.POINTER(void_p),
        void_p,
        ctypes.POINTER(void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = dword
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        void_p,
        ctypes.POINTER(bool_t),
        ctypes.POINTER(void_p),
        ctypes.POINTER(bool_t),
    ]
    advapi32.GetSecurityDescriptorDacl.restype = bool_t
    advapi32.GetSecurityDescriptorControl.argtypes = [
        void_p,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(dword),
    ]
    advapi32.GetSecurityDescriptorControl.restype = bool_t
    advapi32.GetAclInformation.argtypes = [void_p, void_p, dword, dword]
    advapi32.GetAclInformation.restype = bool_t

    class ACL_SIZE_INFORMATION(ctypes.Structure):
        _fields_ = [("AceCount", dword), ("AclBytesInUse", dword), ("AclBytesFree", dword)]

    descriptor = void_p()
    dacl = void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,  # SE_FILE_OBJECT
        0x00000004,  # DACL_SECURITY_INFORMATION
        None,
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise OSError(result, "GetNamedSecurityInfoW")
    try:
        present = bool_t()
        defaulted = bool_t()
        if not advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise OSError(ctypes.get_last_error(), "GetSecurityDescriptorDacl")
        control = ctypes.c_ushort()
        revision = dword()
        if not advapi32.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise OSError(ctypes.get_last_error(), "GetSecurityDescriptorControl")
        if not present.value or not dacl.value:
            raise OSError("WINDOWS_DACL_SNAPSHOT_UNAVAILABLE")
        size = ACL_SIZE_INFORMATION()
        if not advapi32.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2):  # AclSizeInformation
            raise OSError(ctypes.get_last_error(), "GetAclInformation")
        return ctypes.string_at(dacl, size.AclBytesInUse), int(control.value)
    finally:
        kernel32.LocalFree(descriptor)


def _assert_macos_probe(tmp_path: Path) -> None:
    production = _native_production()
    base = importlib.import_module("yagcode.sandbox.base")
    shadow = tmp_path / "shadow"
    temporary = tmp_path / "temp"
    protected = tmp_path / "protected"
    shadow.mkdir()
    temporary.mkdir()
    protected.mkdir()
    canary = protected / "canary.txt"
    canary.write_text("do-not-read", encoding="utf-8")
    scope = base.SandboxScope(shadow, temporary, protected)
    runner = production.MacOSSandboxRunner()
    attestation = runner.self_test(scope)
    assert attestation.verified, attestation.reason

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.setblocking(False)
    host, port = listener.getsockname()
    probe = (
        "from pathlib import Path; import socket\n"
        "protected, shadow = map(Path, __import__('sys').argv[1:3])\n"
        "host, port = __import__('sys').argv[3:5]\n"
        "out = []\n"
        "for fn in (lambda: (protected / 'canary.txt').read_text(), "
        "lambda: (protected / 'stolen').write_text('x'), "
        "lambda: socket.create_connection((host, int(port)), timeout=1).close()):\n"
        "    try: fn(); out.append('ESCAPED')\n"
        "    except OSError: out.append('DENIED')\n"
        "shadow.joinpath('probe.txt').write_text(','.join(out))\n"
    )
    try:
        handle = runner.start(base.ProcessRequest(sys.executable, ("-c", probe, str(protected), str(shadow), host, str(port))), attestation)
        deadline = time.monotonic() + 5
        while True:
            reconciled = runner.reconcile(handle)
            if reconciled.reason != "PROCESS_RUNNING":
                break
            if time.monotonic() >= deadline:
                pytest.fail("MACOS_PROBE_PROCESS_TIMEOUT")
            time.sleep(0.02)
        assert reconciled.reason == "PROCESS_EXITED" and reconciled.returncode == 0
        with pytest.raises(BlockingIOError):
            listener.accept()
        assert (shadow / "probe.txt").read_text(encoding="utf-8") == "DENIED,DENIED,DENIED"
    finally:
        listener.close()

    child_pid = shadow / "child.pid"
    parent = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(child_pid)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    persistent = runner.start(base.ProcessRequest(sys.executable, ("-c", parent)), attestation)
    for _ in range(100):
        if child_pid.exists():
            break
        time.sleep(0.01)
    assert child_pid.exists()
    child = int(child_pid.read_text(encoding="utf-8"))
    assert runner.terminate_tree(persistent).terminated
    with pytest.raises(ProcessLookupError):
        os.kill(persistent.pid, 0)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    assert runner.reconcile(persistent).reason == "PROCESS_EXITED"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_windows_junction(link: Path, target: Path) -> None:
    assert all(str(path).casefold().startswith("e:\\") for path in (link, target))
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        pytest.fail(f"WINDOWS_JUNCTION_CREATE_FAILED:{result.returncode}:{result.stdout}:{result.stderr}")


def _assert_windows_dispatcher_matrix(
    tmp_path: Path, shadow: Path, protected: Path, resolver: object, dispatcher: object, events: set[str]
) -> None:
    paths = importlib.import_module("yagcode.policy.windows_paths")
    safe = shadow / "safe"
    safe.mkdir()
    target = safe / "native.txt"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_target = outside / "outside.txt"
    outside_target.write_bytes(b"outside-original")
    protected_canary = protected / "canary.txt"
    protected_hash = _digest(protected_canary)
    outside_hash = _digest(outside_target)

    target.write_bytes(b"old-nonempty-content")
    resolved = resolver.resolve_for_write(str(shadow), ("safe", "native.txt"))
    assert dispatcher.write(resolved, b"replacement") == "WRITTEN"
    assert target.read_bytes() == b"replacement"
    events.add("existing_overwrite")
    events.add("flush_reopen_bytes")

    resolved = resolver.resolve_for_write(str(shadow), ("safe", "native.txt"))
    assert dispatcher.write(resolved, b"") == "WRITTEN"
    assert target.read_bytes() == b"" and target.stat().st_size == 0
    events.add("empty_write")

    target.write_bytes(b"same-id-before")
    resolved = resolver.resolve_for_write(str(shadow), ("safe", "native.txt"))
    target.write_bytes(b"same-id-external-change")
    assert dispatcher.write(resolved, b"blocked") == "STALE_TARGET"
    assert target.read_bytes() == b"same-id-external-change"
    events.add("same_id_content_stale")

    target.write_bytes(b"renamed-original")
    resolved = resolver.resolve_for_write(str(shadow), ("safe", "native.txt"))
    renamed = safe / "native-original.txt"
    target.replace(renamed)
    target.write_bytes(b"replacement-target")
    assert dispatcher.write(resolved, b"blocked") == "STALE_TARGET"
    assert renamed.read_bytes() == b"renamed-original"
    assert target.read_bytes() == b"replacement-target"
    assert _digest(outside_target) == outside_hash
    events.add("renamed_target_stale")

    parent = shadow / "junction-parent"
    parent.mkdir()
    parent_target = parent / "target.txt"
    parent_target.write_bytes(b"parent-original")
    resolved = resolver.resolve_for_write(str(shadow), ("junction-parent", "target.txt"))
    original_parent = shadow / "junction-parent-original"
    parent.replace(original_parent)
    _create_windows_junction(parent, outside)
    try:
        assert dispatcher.write(resolved, b"blocked") in {"STALE_TARGET", "WINDOWS_REPARSE_POINT_REJECTED"}
        assert outside_target.read_bytes() == b"outside-original"
    finally:
        parent.rmdir()
        original_parent.replace(parent)
    events.add("parent_junction_stale")

    missing = resolver.resolve_for_write(str(shadow), ("safe", "missing.txt"))
    assert missing.target_identity is None
    assert dispatcher.write(missing, b"relative-create") == "WRITTEN"
    assert (safe / "missing.txt").read_bytes() == b"relative-create"
    events.add("missing_relative_create")

    raced = resolver.resolve_for_write(str(shadow), ("safe", "race.txt"))
    assert raced.target_identity is None
    (safe / "race.txt").write_bytes(b"race-winner")
    assert dispatcher.write(raced, b"blocked") == "STALE_TARGET"
    assert (safe / "race.txt").read_bytes() == b"race-winner"
    events.add("missing_create_race_stale")

    root_junction = shadow / "root-junction"
    _create_windows_junction(root_junction, safe)
    try:
        with pytest.raises(paths.WindowsPathError, match="WINDOWS_REPARSE_POINT_REJECTED"):
            resolver.resolve_for_write(str(root_junction), ("native.txt",))
    finally:
        root_junction.rmdir()
    events.add("root_reparse_stale")

    hardlink = safe / "outside-alias.txt"
    os.link(outside_target, hardlink)
    try:
        with pytest.raises(paths.WindowsPathError, match="WINDOWS_HARDLINK_REJECTED"):
            resolver.resolve_for_write(str(shadow), ("safe", hardlink.name))
        assert outside_target.read_bytes() == b"outside-original"
    finally:
        hardlink.unlink(missing_ok=True)
    events.add("hardlink_alias_stale")

    assert _digest(protected_canary) == protected_hash
    assert _digest(outside_target) == outside_hash
    events.add("protected_outside_hash")


def _reconcile_windows_until_exit(runner: object, handle: object) -> object:
    deadline = time.monotonic() + 5
    while True:
        reconciled = runner.reconcile(handle)
        if reconciled.reason != "PROCESS_RUNNING":
            return reconciled
        if time.monotonic() >= deadline:
            pytest.fail("WINDOWS_PROBE_PROCESS_TIMEOUT")
        time.sleep(0.02)


def _assert_windows_probe(tmp_path: Path) -> None:
    import ctypes

    windows = importlib.import_module("yagcode.sandbox.windows")
    base = importlib.import_module("yagcode.sandbox.base")
    paths = importlib.import_module("yagcode.policy.windows_paths")
    shadow, temporary, protected = (tmp_path / name for name in ("shadow", "temp", "protected"))
    for directory in (shadow, temporary, protected):
        directory.mkdir()
    (protected / "canary.txt").write_text("do-not-read", encoding="utf-8")
    existing_shadow = shadow / "existing-shadow.txt"
    existing_shadow.write_text("before-attestation", encoding="utf-8")
    native_path_ops = paths.NtCreateFileRelativeOps()
    resolver = paths.WindowsNoReparseResolver(native_path_ops)
    dispatcher = paths.WindowsSecurePathDispatcher(native_path_ops)
    events: set[str] = set()

    runtime_roots = tuple(
        dict.fromkeys(
            (
                Path(sys.prefix).resolve(),
                Path(sys.base_prefix).resolve(),
                Path(os.environ["SystemRoot"]).resolve(),
            )
        )
    )
    scope = base.SandboxScope(
        shadow,
        temporary,
        protected,
        readonly_runtime_roots=runtime_roots,
    )
    runner = windows.WindowsSandboxRunner()
    managed_runtime = Path(sys.prefix).resolve()
    managed_base_runtime = Path(sys.base_prefix).resolve()
    system_root = Path(os.environ["SystemRoot"]).resolve()
    before_dacls = {
        root: _windows_dacl_snapshot(root)
        for root in (shadow, temporary, protected, managed_runtime, managed_base_runtime, existing_shadow)
    }
    system_dacl = _windows_dacl_snapshot(system_root)
    attestation = runner.self_test(scope)
    assert attestation.verified, attestation.reason
    assert attestation.snapshot is not None
    managed_roots = runner._granted_roots(attestation.snapshot)
    assert all(root != system_root and not root.is_relative_to(system_root) for root in managed_roots)
    assert all(
        root.is_relative_to(tmp_path)
        or root.is_relative_to(managed_runtime)
        or root.is_relative_to(managed_base_runtime)
        for root in managed_roots
    )
    assert all(str(root).casefold().startswith("e:\\") for root in managed_roots)
    assert_windows_dacls_restored(before_dacls)
    assert _windows_dacl_snapshot(system_root) == system_dacl
    events.update({"dacl_after_self_test", "system_root_dacl_read_only"})
    _assert_windows_dispatcher_matrix(tmp_path, shadow, protected, resolver, dispatcher, events)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.setblocking(False)
    host, port = listener.getsockname()
    probe = (
        "from pathlib import Path; import socket\n"
        "protected, shadow, existing = map(Path, __import__('sys').argv[1:4])\n"
        "host, port, replacement = __import__('sys').argv[4:7]\n"
        "out=[]\n"
        "for fn in (lambda: (protected/'canary.txt').read_text(), lambda: (protected/'stolen').write_text('x'), lambda: socket.create_connection((host, int(port)), timeout=1).close()):\n"
        "    try: fn(); out.append('ESCAPED')\n"
        "    except OSError: out.append('DENIED')\n"
        "try: before=existing.read_text(); existing.write_text(replacement); out.append('ALLOWED' if before == 'before-attestation' and existing.read_text() == replacement else 'ESCAPED')\n"
        "except OSError: out.append('DENIED')\n"
        "shadow.joinpath('probe.txt').write_text(','.join(out))\n"
    )
    try:
        replacement = f"native-shadow-{attestation.scope_hash}"
        handle = runner.start(base.ProcessRequest(sys.executable, ("-c", probe, str(protected), str(shadow), str(existing_shadow), host, str(port), replacement)), attestation)
        assert handle.started, handle.reason
        reconciled = _reconcile_windows_until_exit(runner, handle)
        assert reconciled.reason == "PROCESS_EXITED" and reconciled.returncode == 0
        with pytest.raises(BlockingIOError):
            listener.accept()
        assert (shadow / "probe.txt").read_text(encoding="utf-8") == "DENIED,DENIED,DENIED,ALLOWED"
        assert existing_shadow.read_text(encoding="utf-8") == replacement
        events.update({"loopback_connect_denied", "existing_shadow_access", "existing_shadow_child_dacl_restored"})
    finally:
        listener.close()
    assert_windows_dacls_restored(before_dacls)
    assert _windows_dacl_snapshot(system_root) == system_dacl
    events.add("dacl_after_reconcile")

    child_pid = shadow / "child.pid"
    parent = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(child_pid)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    persistent = runner.start(base.ProcessRequest(sys.executable, ("-c", parent)), attestation)
    assert persistent.started, persistent.reason
    for _ in range(100):
        if child_pid.exists():
            break
        time.sleep(0.05)
    assert child_pid.exists()
    child = int(child_pid.read_text(encoding="utf-8"))
    assert runner.terminate_tree(persistent).terminated
    assert_windows_dacls_restored(before_dacls)
    assert _windows_dacl_snapshot(system_root) == system_dacl
    events.add("dacl_after_terminate")
    def is_alive(pid: int) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            assert kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    for _ in range(100):
        if not is_alive(child):
            break
        time.sleep(0.05)
    else:
        pytest.fail("WINDOWS_JOB_OBJECT_CHILD_STILL_RUNNING")
    assert windows_dispatcher_matrix_errors(events) == ()


def test_native_runner_blocks_protected_root_network_and_reaps_children(tmp_path: Path) -> None:
    if sys.platform == "darwin":
        _assert_macos_probe(tmp_path)
    elif sys.platform == "win32":
        _assert_windows_probe(tmp_path)
    else:
        pytest.fail("NATIVE_SANDBOX_PLATFORM_UNSUPPORTED")
