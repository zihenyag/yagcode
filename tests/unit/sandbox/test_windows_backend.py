"""Deterministic contract for the Windows native-primitive adapter boundary."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest


def _production() -> tuple[object, object]:
    try:
        return (
            importlib.import_module("yagcode.sandbox.base"),
            importlib.import_module("yagcode.sandbox.windows"),
        )
    except ModuleNotFoundError as error:
        pytest.fail(f"SANDBOX_CONTRACT_MISSING:{error.name}")


def _write_windows_canary_receipt(request: object, shadow: Path) -> None:
    argv = getattr(request, "argv")
    output = next(Path(value) for value in argv if Path(value).parent == shadow)
    challenge = next((value for value in argv if len(value) == 32), None)
    receipt = f"{challenge}:True,True,True,True,True" if challenge else "True,True,True,True,True"
    output.write_text(receipt, encoding="utf-8")


def _neutral_fake_runner(windows: object, ops: object, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setattr(windows.sys, "platform", "linux")
    return windows.WindowsSandboxRunner(native_ops=ops)


def test_windows_backend_calls_native_primitives_in_fail_closed_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class FakeNativeOps:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.spawn_count = 0

        def create_appcontainer(self, scope: object) -> str:
            self.calls.append("appcontainer")
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            assert sid == "sid"
            self.calls.append("release-appcontainer")

        def create_restricted_token(self, sid: str) -> str:
            assert sid == "sid"
            self.calls.append("restricted-token")
            return "token"

        def close_token(self, token: str) -> None:
            assert token == "token"
            self.calls.append("close-token")

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            assert sid == "sid"
            self.calls.append(f"acl:{root.name}:{mode}")

        def create_kill_on_close_job(self) -> str:
            self.calls.append("job")
            return "job"

        def spawn_suspended(self, request: object, cwd: Path, environment: dict[str, str], token: str, appcontainer_sid: str) -> tuple[int, str]:
            assert cwd.name == "shadow"
            assert set(environment) <= {"PATH", "LANG", "LC_ALL"}
            assert token == "token"
            assert appcontainer_sid == "sid"
            self.calls.append("spawn-suspended")
            self.spawn_count += 1
            if getattr(request, "argv", ()) and request.argv[:1] == ("-c",):
                _write_windows_canary_receipt(request, cwd)
            return 42, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            assert (pid, job) == (42, "job")
            self.calls.append("assign-job")

        def terminate_suspended(self, pid: int, thread: str) -> None:
            self.calls.append("terminate-suspended")

        def resume_suspended(self, thread: str) -> None:
            assert thread == "thread"
            self.calls.append("resume")

        def close_job(self, job: str) -> None:
            assert job == "job"
            self.calls.append("close-job")

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            assert sid == "sid"
            self.calls.append(f"revoke:{root.name}")

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            assert pid == 42
            self.calls.append("wait")
            return 0

    ops = FakeNativeOps()
    runner = _neutral_fake_runner(windows, ops, monkeypatch)
    scope = base.SandboxScope(*roots)
    attestation = runner.self_test(scope)
    assert attestation.verified
    ops.calls.clear()
    handle = runner.start(base.ProcessRequest("C:\\Windows\\System32\\cmd.exe", ("/c", "exit", "0")), attestation)
    assert handle.started and handle.pid == 42
    assert runner.terminate_tree(handle).terminated
    assert ops.calls == [
        "appcontainer",
        "restricted-token",
        "acl:shadow:write",
        "acl:temp:write",
        "job",
        "spawn-suspended",
        "assign-job",
        "resume",
        "close-token",
        "close-job",
        "wait",
        "revoke:temp",
        "revoke:shadow",
        "release-appcontainer",
    ]


def test_windows_backend_fails_before_spawn_when_acl_setup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class FailingOps:
        spawn_count = 0

        def create_appcontainer(self, scope: object) -> str:
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            pass

        def create_restricted_token(self, sid: str) -> str:
            return "token"

        def close_token(self, token: str) -> None:
            pass

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            raise OSError("acl unavailable")

    runner = _neutral_fake_runner(windows, FailingOps(), monkeypatch)
    attestation = runner.self_test(base.SandboxScope(*roots))
    assert not attestation.verified
    assert attestation.reason == "WINDOWS_SANDBOX_CANARY_FAILED"


def test_windows_start_failure_revokes_acls_and_never_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class FakeOps:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.fail_at: str | None = None

        def create_appcontainer(self, scope: object) -> str:
            self.calls.append("appcontainer")
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            self.calls.append("release-appcontainer")

        def create_restricted_token(self, sid: str) -> str:
            self.calls.append("token")
            return "token"

        def close_token(self, token: str) -> None:
            self.calls.append("close-token")

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            self.calls.append(f"grant:{root.name}")
            if self.fail_at == f"grant:{root.name}":
                raise OSError("injected")

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            self.calls.append(f"revoke:{root.name}")

        def create_kill_on_close_job(self) -> str:
            self.calls.append("job")
            if self.fail_at == "job":
                raise OSError("injected")
            return "job"

        def spawn_suspended(self, request: object, cwd: Path, environment: dict[str, str], token: str, appcontainer_sid: str) -> tuple[int, str]:
            self.calls.append("spawn-suspended")
            if self.fail_at == "spawn-suspended":
                raise OSError("injected")
            if getattr(request, "argv", ()) and request.argv[:1] == ("-c",):
                _write_windows_canary_receipt(request, cwd)
            return 73, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            self.calls.append("assign-job")
            if self.fail_at == "assign-job":
                raise OSError("injected")

        def terminate_suspended(self, pid: int, thread: str) -> None:
            self.calls.append("terminate-suspended")

        def resume_suspended(self, thread: str) -> None:
            self.calls.append("resume")
            if self.fail_at == "resume":
                raise OSError("injected")

        def close_job(self, job: str) -> None:
            self.calls.append("close-job")

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            self.calls.append("wait")
            return 0

    for failure, expected in (
        ("grant:temp", ["revoke:shadow", "close-token", "release-appcontainer"]),
        ("job", ["revoke:temp", "revoke:shadow", "close-token", "release-appcontainer"]),
        ("spawn-suspended", ["close-job", "revoke:temp", "revoke:shadow", "close-token", "release-appcontainer"]),
        ("assign-job", ["terminate-suspended", "close-job", "revoke:temp", "revoke:shadow", "close-token", "release-appcontainer"]),
        ("resume", ["terminate-suspended", "close-job", "revoke:temp", "revoke:shadow", "close-token", "release-appcontainer"]),
    ):
        ops = FakeOps()
        runner = _neutral_fake_runner(windows, ops, monkeypatch)
        attestation = runner.self_test(base.SandboxScope(*roots))
        assert attestation.verified
        ops.calls.clear()
        ops.fail_at = failure
        result = runner.start(base.ProcessRequest("C:\\Windows\\System32\\cmd.exe", ("/c", "exit", "0")), attestation)
        assert not result.started
        assert "resume" not in ops.calls or failure == "resume"
        assert ops.calls[-len(expected) :] == expected


def test_cleanup_failures_need_retry_instead_of_losing_runner_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class Ops:
        def __init__(self) -> None:
            self.fail_revoke = True
            self.calls: list[str] = []
        def create_appcontainer(self, scope: object) -> str: return "sid"
        def release_appcontainer(self, sid: str) -> None: self.calls.append("release")
        def create_restricted_token(self, sid: str) -> str: return "token"
        def close_token(self, token: str) -> None: self.calls.append("token-close")
        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None: pass
        def create_kill_on_close_job(self) -> str: return "job"
        def spawn_suspended(self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str) -> tuple[int, str]: return 77, "thread"
        def assign_job(self, pid: int, job: str) -> None: pass
        def terminate_suspended(self, pid: int, thread: str) -> None: pass
        def resume_suspended(self, thread: str) -> None: pass
        def close_job(self, job: str) -> None: self.calls.append("job-close")
        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            self.calls.append(f"revoke:{root.name}")
            if self.fail_revoke:
                raise OSError("injected")

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            return 0

    ops = Ops()
    runner = _neutral_fake_runner(windows, ops, monkeypatch)
    attestation = base.attest_snapshot(base.capture_scope_snapshot(base.SandboxScope(*roots)), backend="windows")
    runner._attestations[attestation.scope_hash] = attestation
    handle = runner.start(base.ProcessRequest("C:\\Windows\\System32\\cmd.exe", ()), attestation)
    assert handle.started
    ops.calls.clear()
    first = runner.terminate_tree(handle)
    assert first.reason == "PROCESS_TREE_TERMINATION_UNCONFIRMED"
    assert ops.calls == ["job-close", "revoke:temp"]
    ops.fail_revoke = False
    second = runner.terminate_tree(handle)
    assert second.terminated
    assert ops.calls == [
        "job-close",
        "revoke:temp",
        "revoke:temp",
        "revoke:shadow",
        "release",
    ]


def test_self_test_retains_canary_cleanup_debt_until_a_retry_restores_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class Ops:
        def __init__(self) -> None:
            self.fail_revoke = True
            self.calls: list[str] = []

        def create_appcontainer(self, scope: object) -> str:
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            self.calls.append("release")

        def create_restricted_token(self, sid: str) -> str:
            return "token"

        def close_token(self, token: str) -> None:
            self.calls.append("token-close")

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            pass

        def create_kill_on_close_job(self) -> str:
            return "job"

        def spawn_suspended(
            self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str
        ) -> tuple[int, str]:
            _write_windows_canary_receipt(request, cwd)
            return 77, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            pass

        def terminate_suspended(self, pid: int, thread: str) -> None:
            pass

        def resume_suspended(self, thread: str) -> None:
            pass

        def close_job(self, job: str) -> None:
            self.calls.append("job-close")

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            self.calls.append(f"revoke:{root.name}")
            if self.fail_revoke:
                raise OSError("injected")

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            return 0

    ops = Ops()
    runner = _neutral_fake_runner(windows, ops, monkeypatch)
    first = runner.self_test(base.SandboxScope(*roots))
    assert not first.verified
    assert first.reason == "SANDBOX_CLEANUP_UNCONFIRMED"
    assert ops.calls == ["token-close", "job-close", "revoke:temp"]

    ops.fail_revoke = False
    second = runner.self_test(base.SandboxScope(*roots))
    assert second.verified
    assert ops.calls[:5] == [
        "token-close",
        "job-close",
        "revoke:temp",
        "revoke:temp",
        "revoke:shadow",
    ]
    assert ops.calls[5] == "release"


def test_start_blocks_on_unconfirmed_setup_cleanup_and_retries_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class Ops:
        def __init__(self) -> None:
            self.fail_revoke = True
            self.fail_spawn = True
            self.calls: list[str] = []

        def create_appcontainer(self, scope: object) -> str:
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            self.calls.append("release")

        def create_restricted_token(self, sid: str) -> str:
            return "token"

        def close_token(self, token: str) -> None:
            self.calls.append("token-close")

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            pass

        def create_kill_on_close_job(self) -> str:
            return "job"

        def spawn_suspended(
            self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str
        ) -> tuple[int, str]:
            self.calls.append("spawn")
            if self.fail_spawn:
                raise OSError("injected")
            return 77, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            pass

        def terminate_suspended(self, pid: int, thread: str) -> None:
            pass

        def resume_suspended(self, thread: str) -> None:
            pass

        def close_job(self, job: str) -> None:
            self.calls.append("job-close")

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            self.calls.append(f"revoke:{root.name}")
            if self.fail_revoke:
                raise OSError("injected")

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            return 0

    ops = Ops()
    runner = _neutral_fake_runner(windows, ops, monkeypatch)
    attestation = base.attest_snapshot(
        base.capture_scope_snapshot(base.SandboxScope(*roots)), backend="windows"
    )
    runner._attestations[attestation.scope_hash] = attestation
    first = runner.start(base.ProcessRequest("C:\\Windows\\System32\\cmd.exe", ()), attestation)
    assert first.reason == "SANDBOX_CLEANUP_UNCONFIRMED"
    assert ops.calls == ["spawn", "job-close", "revoke:temp"]

    ops.fail_revoke = False
    ops.fail_spawn = False
    second = runner.start(base.ProcessRequest("C:\\Windows\\System32\\cmd.exe", ()), attestation)
    assert second.started
    assert ops.calls[:6] == [
        "spawn",
        "job-close",
        "revoke:temp",
        "revoke:temp",
        "revoke:shadow",
        "token-close",
    ]
    assert ops.calls[6] == "release"
    assert ops.calls[7] == "spawn"


def test_reconcile_retries_partial_cleanup_with_the_recorded_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class Ops:
        def __init__(self) -> None:
            self.fail_revoke = True
            self.calls: list[str] = []

        def create_appcontainer(self, scope: object) -> str:
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            self.calls.append("release")

        def create_restricted_token(self, sid: str) -> str:
            return "token"

        def close_token(self, token: str) -> None:
            self.calls.append("token-close")

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            pass

        def create_kill_on_close_job(self) -> str:
            return "job"

        def spawn_suspended(
            self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str
        ) -> tuple[int, str]:
            return 77, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            pass

        def terminate_suspended(self, pid: int, thread: str) -> None:
            pass

        def resume_suspended(self, thread: str) -> None:
            pass

        def close_job(self, job: str) -> None:
            self.calls.append("job-close")

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            self.calls.append(f"revoke:{root.name}")
            if self.fail_revoke:
                raise OSError("injected")

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            self.calls.append("wait")
            return 23

    ops = Ops()
    runner = _neutral_fake_runner(windows, ops, monkeypatch)
    attestation = base.attest_snapshot(
        base.capture_scope_snapshot(base.SandboxScope(*roots)), backend="windows"
    )
    runner._attestations[attestation.scope_hash] = attestation
    handle = runner.start(base.ProcessRequest("C:\\Windows\\System32\\cmd.exe", ()), attestation)
    assert handle.started
    ops.calls.clear()

    first = runner.reconcile(handle)
    assert first.reason == "PROCESS_CLEANUP_UNCONFIRMED"
    assert first.returncode == 23
    assert ops.calls == ["wait", "job-close", "revoke:temp"]

    ops.fail_revoke = False
    second = runner.reconcile(handle)
    assert second.reason == "PROCESS_EXITED"
    assert second.returncode == 23
    assert ops.calls == [
        "wait",
        "job-close",
        "revoke:temp",
        "revoke:temp",
        "revoke:shadow",
        "release",
    ]


def test_windows_runner_never_acl_manages_system_runtime_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base, windows = _production()
    shadow, temporary, protected, runtime, system_root = (
        tmp_path / name for name in ("shadow", "temp", "protected", "runtime", "system")
    )
    for root in (shadow, temporary, protected, runtime, system_root):
        root.mkdir()
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", str(system_root))

    class Ops:
        def __init__(self) -> None:
            self.acl_calls: list[tuple[str, str, str | None]] = []

        def create_appcontainer(self, scope: object) -> str:
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            pass

        def create_restricted_token(self, sid: str) -> str:
            return "token"

        def close_token(self, token: str) -> None:
            pass

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            self.acl_calls.append(("grant", root.name, mode))

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            self.acl_calls.append(("revoke", root.name, None))

        def create_kill_on_close_job(self) -> str:
            return "job"

        def spawn_suspended(
            self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str
        ) -> tuple[int, str]:
            _write_windows_canary_receipt(request, cwd)
            return 77, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            pass

        def terminate_suspended(self, pid: int, thread: str) -> None:
            pass

        def resume_suspended(self, thread: str) -> None:
            pass

        def close_job(self, job: str) -> None:
            pass

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            return 0

    ops = Ops()
    runner = windows.WindowsSandboxRunner(native_ops=ops)
    runner._environment = lambda snapshot: base.minimal_environment()
    attestation = runner.self_test(
        base.SandboxScope(
            shadow,
            temporary,
            protected,
            readonly_runtime_roots=(runtime, system_root),
        )
    )

    assert attestation.verified
    assert ("grant", "system", "readonly") not in ops.acl_calls
    assert ("grant", "protected", "deny") not in ops.acl_calls
    assert ("grant", "runtime", "readonly") in ops.acl_calls
    assert ("grant", "shadow", "write") in ops.acl_calls
    assert ("grant", "temp", "write") in ops.acl_calls
    assert ("revoke", "runtime", None) in ops.acl_calls
    assert ("revoke", "shadow", None) in ops.acl_calls
    assert ("revoke", "temp", None) in ops.acl_calls


def test_windows_acl_plan_uses_traverse_only_parent_grants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    shadow = tmp_path / "run" / "shadow"
    temporary = tmp_path / "run" / "temp"
    protected = tmp_path / "run" / "protected"
    runtime = tmp_path / "runtime"
    system_root = tmp_path / "system"
    for root in (shadow, temporary, protected, runtime, system_root):
        root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", str(system_root))

    snapshot = base.capture_scope_snapshot(
        base.SandboxScope(
            shadow,
            temporary,
            protected,
            readonly_runtime_roots=(runtime, system_root),
        )
    )
    grants = windows.WindowsSandboxRunner._acl_grants(snapshot)
    traverse_roots = [root for root, mode in grants if mode == "traverse"]
    substantive_grants = [grant for grant in grants if grant[1] != "traverse"]

    assert protected not in traverse_roots
    assert all(root != protected and not root.is_relative_to(protected) for root in traverse_roots)
    assert (shadow.parent, "traverse") in grants
    assert (runtime.parent, "traverse") in grants
    assert (shadow, "write") in substantive_grants
    assert (temporary, "write") in substantive_grants
    assert (runtime, "readonly") in substantive_grants
    assert (system_root, "readonly") not in substantive_grants


def test_windows_canary_uses_unique_files_without_touching_legacy_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    shadow, temporary, protected = (tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in (shadow, temporary, protected):
        root.mkdir()
    legacy = {
        protected / ".yagcode-windows-canary": b"legacy-canary",
        protected / "stolen": b"legacy-stolen",
        shadow / "windows-attestation.txt": b"legacy-receipt",
    }
    for path, content in legacy.items():
        path.write_bytes(content)

    class Ops:
        def create_appcontainer(self, scope: object) -> str:
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            pass

        def create_restricted_token(self, sid: str) -> str:
            return "token"

        def close_token(self, token: str) -> None:
            pass

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            pass

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            pass

        def create_kill_on_close_job(self) -> str:
            return "job"

        def spawn_suspended(
            self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str
        ) -> tuple[int, str]:
            output = next(Path(value) for value in getattr(request, "argv") if Path(value).parent == shadow)
            challenge = next((value for value in getattr(request, "argv") if len(value) == 32), None)
            output.write_text(
                    f"{challenge}:True,True,True,True,True" if challenge else "True,True,True,True,True",
                encoding="utf-8",
            )
            return 77, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            pass

        def terminate_suspended(self, pid: int, thread: str) -> None:
            pass

        def resume_suspended(self, thread: str) -> None:
            pass

        def close_job(self, job: str) -> None:
            pass

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            return 0

    monkeypatch.setattr(windows.secrets, "token_hex", lambda size: "a" * (size * 2))
    attestation = _neutral_fake_runner(windows, Ops(), monkeypatch).self_test(base.SandboxScope(shadow, temporary, protected))

    assert attestation.verified
    assert {path: path.read_bytes() for path in legacy} == legacy
    assert not list(shadow.glob(".yagcode-windows-receipt-*"))
    assert not list(protected.glob(".yagcode-windows-*-" + "a" * 32))


def test_start_termination_failure_retains_cleanup_debt_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class Ops:
        def __init__(self) -> None:
            self.fail_terminate = True
            self.fail_assign = True
            self.revoked: list[str] = []

        def create_appcontainer(self, scope: object) -> str:
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            pass

        def create_restricted_token(self, sid: str) -> str:
            return "token"

        def close_token(self, token: str) -> None:
            pass

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            pass

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            self.revoked.append(root.name)

        def create_kill_on_close_job(self) -> str:
            return "job"

        def spawn_suspended(
            self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str
        ) -> tuple[int, str]:
            return 77, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            if self.fail_assign:
                raise OSError("injected")

        def terminate_suspended(self, pid: int, thread: str) -> None:
            if self.fail_terminate:
                raise OSError("injected")

        def resume_suspended(self, thread: str) -> None:
            pass

        def close_job(self, job: str) -> None:
            pass

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            return 0

    ops = Ops()
    runner = _neutral_fake_runner(windows, ops, monkeypatch)
    attestation = base.attest_snapshot(base.capture_scope_snapshot(base.SandboxScope(*roots)), backend="windows")
    runner._attestations[attestation.scope_hash] = attestation

    first = runner.start(base.ProcessRequest("C:\\Windows\\System32\\cmd.exe", ()), attestation)
    assert first.reason == "SANDBOX_CLEANUP_UNCONFIRMED"
    assert ops.revoked == []

    ops.fail_terminate = False
    ops.fail_assign = False
    second = runner.start(base.ProcessRequest("C:\\Windows\\System32\\cmd.exe", ()), attestation)
    assert second.started
    assert ops.revoked == ["temp", "shadow"]


def test_windows_canary_post_spawn_failure_keeps_termination_before_acl_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class Ops:
        def __init__(self) -> None:
            self.fail_terminate = True
            self.calls: list[str] = []

        def create_appcontainer(self, scope: object) -> str:
            return "sid"

        def release_appcontainer(self, sid: str) -> None:
            self.calls.append("release")

        def create_restricted_token(self, sid: str) -> str:
            return "token"

        def close_token(self, token: str) -> None:
            self.calls.append("token-close")

        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None:
            pass

        def revoke_scope_acl(self, root: Path, sid: str) -> None:
            self.calls.append(f"revoke:{root.name}")

        def create_kill_on_close_job(self) -> str:
            return "job"

        def spawn_suspended(
            self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str
        ) -> tuple[int, str]:
            return 77, "thread"

        def assign_job(self, pid: int, job: str) -> None:
            raise OSError("injected")

        def terminate_suspended(self, pid: int, thread: str) -> None:
            self.calls.append("terminate")
            if self.fail_terminate:
                raise OSError("injected")

        def resume_suspended(self, thread: str) -> None:
            pass

        def close_job(self, job: str) -> None:
            self.calls.append("close-job")

        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None:
            return 0

    ops = Ops()
    result = _neutral_fake_runner(windows, ops, monkeypatch).self_test(base.SandboxScope(*roots))

    assert result.reason == "SANDBOX_CLEANUP_UNCONFIRMED"
    assert ops.calls == ["terminate"]


def test_windows_canary_real_executable_connection_is_an_attestation_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, windows = _production()
    roots = tuple(tmp_path / name for name in ("shadow", "temp", "protected"))
    for root in roots:
        root.mkdir()

    class Ops:
        def __init__(self) -> None:
            self.request: object | None = None
            self.returncode: int | None = None

        def create_appcontainer(self, scope: object) -> str: return "sid"
        def release_appcontainer(self, sid: str) -> None: pass
        def create_restricted_token(self, sid: str) -> str: return "token"
        def close_token(self, token: str) -> None: pass
        def grant_scope_acl(self, root: Path, sid: str, mode: str) -> None: pass
        def revoke_scope_acl(self, root: Path, sid: str) -> None: pass
        def create_kill_on_close_job(self) -> str: return "job"
        def close_job(self, job: str) -> None: pass
        def spawn_suspended(self, request: object, cwd: Path, environment: dict[str, str], token: str, sid: str) -> tuple[int, str]:
            self.request = request
            return 41, "thread"
        def assign_job(self, pid: int, job: str) -> None: pass
        def resume_suspended(self, thread: str) -> None:
            assert self.request is not None
            self.returncode = subprocess.run(
                [getattr(self.request, "executable"), *getattr(self.request, "argv")], check=False, timeout=5
            ).returncode
        def terminate_suspended(self, pid: int, thread: str) -> None: pass
        def wait_for_exit(self, pid: int, timeout_ms: int) -> int | None: return self.returncode

    attestation = _neutral_fake_runner(windows, Ops(), monkeypatch).self_test(base.SandboxScope(*roots))
    assert not attestation.verified
    assert attestation.reason == "WINDOWS_SANDBOX_CANARY_FAILED"
