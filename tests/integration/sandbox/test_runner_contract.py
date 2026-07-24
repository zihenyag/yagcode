"""Platform-neutral fail-closed runner contract."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


def _sandbox_production() -> object:
    try:
        return importlib.import_module("yagcode.sandbox.base")
    except ModuleNotFoundError as error:
        if error.name in {"yagcode.sandbox", "yagcode.sandbox.base"}:
            pytest.fail("SANDBOX_CONTRACT_MISSING")
        raise


def test_owned_unverified_attestation_oracle_never_spawns() -> None:
    spawned = 0
    verified = False
    if verified:
        spawned += 1
    assert spawned == 0


def test_unverified_sandbox_never_starts_process(tmp_path: Path) -> None:
    production = _sandbox_production()
    shadow = tmp_path / "shadow"
    temporary = tmp_path / "temp"
    protected = tmp_path / "protected"
    for directory in (shadow, temporary, protected):
        directory.mkdir()

    class FakeBackend:
        spawn_count = 0

        def self_test(self, scope: object) -> object:
            return production.SandboxAttestation(scope_hash="scope", verified=False, reason="CANARY_FAILED")

        def start(self, request: object, attestation: object) -> object:
            self.spawn_count += 1
            raise AssertionError("must not spawn")

    scope = production.SandboxScope(shadow, temporary, protected)
    request = production.ProcessRequest("/usr/bin/true", ())
    backend = FakeBackend()
    runner = production.SandboxRunner(backend)
    attestation = runner.self_test(scope)
    result = runner.start(request, attestation)

    assert result.reason == "SANDBOX_UNAVAILABLE"
    assert backend.spawn_count == 0


@pytest.mark.posix_only
def test_attestation_rejects_shadow_root_replaced_by_symlink_before_start(tmp_path: Path) -> None:
    production = _sandbox_production()
    shadow = tmp_path / "shadow"
    temporary = tmp_path / "temp"
    protected = tmp_path / "protected"
    outside = tmp_path / "outside"
    for directory in (shadow, temporary, protected, outside):
        directory.mkdir()

    class FakeBackend:
        spawn_count = 0

        def self_test(self, scope: object) -> object:
            snapshot = production.capture_scope_snapshot(scope)
            return production.attest_snapshot(snapshot, backend="fake")

        def start(self, request: object, attestation: object) -> object:
            self.spawn_count += 1
            return production.ProcessHandle(True, "UNEXPECTED_SPAWN")

        def terminate_tree(self, handle: object) -> object:
            return production.TerminationResult("unused", False)

        def reconcile(self, handle: object) -> object:
            return production.ReconciliationResult("unused", None)

    backend = FakeBackend()
    runner = production.SandboxRunner(backend)
    scope = production.SandboxScope(shadow, temporary, protected)
    attestation = runner.self_test(scope)
    shadow.rmdir()
    shadow.symlink_to(outside, target_is_directory=True)

    result = runner.start(production.ProcessRequest("/usr/bin/true", ()), attestation)
    assert result.reason == "SANDBOX_UNAVAILABLE"
    assert backend.spawn_count == 0


@pytest.mark.posix_only
def test_terminate_tree_reaps_a_persistent_child_and_reconcile_is_stable(tmp_path: Path) -> None:
    production = _sandbox_production()
    process_tree = importlib.import_module("yagcode.sandbox.process_tree")
    child_pid = tmp_path / "child.pid"
    parent = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(child_pid)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    process = subprocess.Popen([sys.executable, "-c", parent], start_new_session=True)
    handle = production.ProcessHandle(True, "PROCESS_STARTED", process.pid, process)
    try:
        for _ in range(100):
            if child_pid.exists():
                break
            time.sleep(0.01)
        assert child_pid.exists()
        child = int(child_pid.read_text())
        result = process_tree.terminate_process_tree(handle)
        assert result.terminated
        with pytest.raises(ProcessLookupError):
            os.kill(process.pid, 0)
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
        assert process_tree.reconcile_process(handle).reason == "PROCESS_EXITED"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.macos_only
def test_scope_replaced_before_self_test_returns_stable_failure_without_spawn(tmp_path: Path) -> None:
    production = _sandbox_production()
    macos = importlib.import_module("yagcode.sandbox.macos")
    shadow, temporary, protected, outside = (tmp_path / name for name in ("shadow", "temp", "protected", "outside"))
    for directory in (shadow, temporary, protected, outside):
        directory.mkdir()
    scope = production.SandboxScope(shadow, temporary, protected)
    shadow.rmdir()
    shadow.symlink_to(outside, target_is_directory=True)

    attestation = macos.MacOSSandboxRunner().self_test(scope)
    assert not attestation.verified
    assert attestation.reason == "SANDBOX_SCOPE_INVALID"


def test_scope_reparse_root_is_rejected_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    production = _sandbox_production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()
    monkeypatch.setattr(production, "_is_reparse_directory", lambda path: path == roots[0])

    with pytest.raises(ValueError, match="SANDBOX_SCOPE_DIRECTORY_INVALID"):
        production.SandboxScope(*roots)


def test_reconcile_running_process_is_nonblocking_and_stable() -> None:
    production = _sandbox_production()
    process_tree = importlib.import_module("yagcode.sandbox.process_tree")
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    handle = production.ProcessHandle(True, "PROCESS_STARTED", process.pid, process)
    try:
        assert process_tree.reconcile_process(handle).reason == "PROCESS_RUNNING"
    finally:
        process.kill()
        process.wait()


@pytest.mark.posix_only
def test_terminate_tree_reaps_child_that_ignores_sigterm_after_parent_exits(tmp_path: Path) -> None:
    production = _sandbox_production()
    process_tree = importlib.import_module("yagcode.sandbox.process_tree")
    child_pid = tmp_path / "stubborn-child.pid"
    parent = (
        "import signal, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])\n"
        f"open({str(child_pid)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    process = subprocess.Popen([sys.executable, "-c", parent], start_new_session=True)
    handle = production.ProcessHandle(True, "PROCESS_STARTED", process.pid, process)
    child: int | None = None
    try:
        deadline = time.monotonic() + 3
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert child_pid.exists()
        child = int(child_pid.read_text())
        result = process_tree.terminate_process_tree(handle)
        assert result.terminated
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if child is not None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.macos_only
def test_macos_deny_default_profile_has_only_required_python_startup_ipc(tmp_path: Path) -> None:
    production = _sandbox_production()
    macos = importlib.import_module("yagcode.sandbox.macos")
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()
    snapshot = production.capture_scope_snapshot(production.SandboxScope(*roots))
    profile = macos.MacOSSandboxRunner()._profile(snapshot)
    assert "(deny default)" in profile
    assert "(allow network" not in profile
    assert "(allow sysctl-read)" in profile
    assert '(global-name "com.apple.cfprefsd.daemon")' in profile
    assert '(allow file-read* (literal "/"))' in profile
    assert f'(allow file-read* (subpath "{roots[0]}"))' in profile
    assert f'(allow file-read* (subpath "{roots[1]}"))' in profile


@pytest.mark.macos_only
def test_macos_profile_grants_only_literal_ancestors_for_runtime_and_writable_roots(tmp_path: Path) -> None:
    production = _sandbox_production()
    macos = importlib.import_module("yagcode.sandbox.macos")
    shadow = tmp_path / "shadow"
    temporary = tmp_path / "temp"
    protected = tmp_path / "protected"
    runtime = tmp_path / "runtime" / "venv"
    for root in (shadow, temporary, protected, runtime):
        root.mkdir(parents=True, exist_ok=True)
    snapshot = production.capture_scope_snapshot(
        production.SandboxScope(shadow, temporary, protected, readonly_runtime_roots=(runtime,))
    )
    profile = macos.MacOSSandboxRunner()._profile(snapshot)
    for root in (shadow, temporary, runtime):
        for ancestor in (root.parent, root.parent.parent):
            assert f'(allow file-read* (literal "{ancestor}"))' in profile
            assert f'(allow file-read* (subpath "{ancestor}"))' not in profile
    assert f'(allow file-read* (literal "{protected}"))' not in profile
    assert f'(allow file-read* (subpath "{protected}"))' not in profile


@pytest.mark.macos_only
def test_macos_self_test_uses_a_real_protected_canary_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    production = _sandbox_production()
    macos = importlib.import_module("yagcode.sandbox.macos")
    shadow, temporary, protected = (tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in (shadow, temporary, protected):
        root.mkdir()
    captured: list[tuple[str, ...]] = []

    def fake_run(scope: object, executable: str, argv: tuple[str, ...]) -> object:
        captured.append(argv)
        canary = next(protected.glob(".yagcode-self-test-canary-*"))
        assert canary.read_bytes() == b"must-remain-unreadable"
        Path(argv[-4]).write_text(f"{argv[-3]}:True,True,True,True", encoding="utf-8")
        return subprocess.CompletedProcess([executable, *argv], 0)

    runner = macos.MacOSSandboxRunner()
    monkeypatch.setattr(runner, "_run", fake_run)
    attestation = runner.self_test(production.SandboxScope(shadow, temporary, protected))

    assert attestation.verified
    assert captured
    assert ".yagcode-self-test-canary-" in captured[0][1]
    assert not list(protected.glob(".yagcode-self-test-canary-*"))


@pytest.mark.macos_only
def test_macos_self_test_missing_attestation_receipt_is_a_stable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = _sandbox_production()
    macos = importlib.import_module("yagcode.sandbox.macos")
    shadow, temporary, protected = (tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in (shadow, temporary, protected):
        root.mkdir()

    def fake_run(scope: object, executable: str, argv: tuple[str, ...]) -> object:
        return subprocess.CompletedProcess([executable, *argv], 0)

    runner = macos.MacOSSandboxRunner()
    monkeypatch.setattr(runner, "_run", fake_run)
    attestation = runner.self_test(production.SandboxScope(shadow, temporary, protected))
    assert not attestation.verified
    assert attestation.reason == "SANDBOX_CANARY_FAILED"


@pytest.mark.macos_only
def test_macos_canary_fails_when_an_unsandboxed_child_reaches_parent_loopback_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = _sandbox_production()
    macos = importlib.import_module("yagcode.sandbox.macos")
    shadow, temporary, protected = (tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in (shadow, temporary, protected):
        root.mkdir()
    accepted = False
    original_socket = macos.socket.socket

    class TrackingSocket:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._socket = original_socket(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._socket, name)

        def accept(self) -> tuple[object, object]:
            nonlocal accepted
            connection = self._socket.accept()
            accepted = True
            return connection

    def unsandboxed_run(scope: object, executable: str, argv: tuple[str, ...]) -> object:
        return subprocess.run([executable, *argv], check=False, capture_output=True, text=True)

    monkeypatch.setattr(macos.socket, "socket", TrackingSocket)
    monkeypatch.setattr(macos.sys, "platform", "darwin")
    monkeypatch.setattr(macos.shutil, "which", lambda *args, **kwargs: "/usr/bin/sandbox-exec")
    runner = macos.MacOSSandboxRunner()
    monkeypatch.setattr(runner, "_run", unsandboxed_run)
    attestation = runner.self_test(production.SandboxScope(shadow, temporary, protected))

    assert accepted
    assert not attestation.verified
    assert attestation.reason == "SANDBOX_CANARY_FAILED"


@pytest.mark.macos_only
def test_macos_canary_uses_challenge_bound_stolen_path_without_touching_legacy_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = _sandbox_production()
    macos = importlib.import_module("yagcode.sandbox.macos")
    shadow, temporary, protected = (tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in (shadow, temporary, protected):
        root.mkdir()
    legacy = {
        protected / ".yagcode-self-test-canary": b"legacy-canary",
        protected / "stolen": b"legacy-stolen",
    }
    for path, content in legacy.items():
        path.write_bytes(content)

    def fake_run(scope: object, executable: str, argv: tuple[str, ...]) -> object:
        receipt = Path(argv[-4])
        challenge = argv[-3]
        receipt.write_text(f"{challenge}:True,True,True,True", encoding="utf-8")
        return subprocess.CompletedProcess([executable, *argv], 0)

    monkeypatch.setattr(macos.secrets, "token_hex", lambda size: "b" * (size * 2))
    runner = macos.MacOSSandboxRunner()
    monkeypatch.setattr(runner, "_run", fake_run)
    attestation = runner.self_test(production.SandboxScope(shadow, temporary, protected))

    assert attestation.verified
    assert {path: path.read_bytes() for path in legacy} == legacy
    assert not list(protected.glob(".yagcode-self-test-*-" + "b" * 32))
    assert not list(shadow.glob(".yagcode-attestation-*"))
