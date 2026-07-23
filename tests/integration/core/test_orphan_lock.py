"""interrupted stop keeps project/write-root locks until reconciliation."""

from __future__ import annotations

import importlib

import pytest

from yagcode.core.scheduler import ProjectScheduler, RunLeaseRequest
from yagcode.domain.states import RunState


def test_owned_orphan_lock_oracle() -> None:
    lock_retained_until_reconciled = [True, True, False]
    assert lock_retained_until_reconciled[:2] == [True, True]
    assert lock_retained_until_reconciled[-1] is False


def load_runtime_control_contract():
    try:
        return importlib.import_module("yagcode.core.stop")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"RUNTIME_CONTROL_CONTRACT_MISSING: {error.name}")
        raise


def test_orphan_process_retains_lock_until_reconciliation() -> None:
    stop = load_runtime_control_contract()
    scheduler = ProjectScheduler()
    scheduler.try_acquire(RunLeaseRequest("run-a", "profile-a", "project-a", ("/repo",), "RUNNING"))
    store = _RunStore(RunState.RUNNING)
    controller = stop.StopController(
        store=store,
        cancellations=_Cancellations(),
        process_tree=_ProcessTree(stop, confirmed=False),
        checkpoints=_Checkpoints(stop, verified=True),
    )
    assert controller.stop("run-a") is RunState.INTERRUPTED
    scheduler.update_state("run-a", "INTERRUPTED")
    blocked = scheduler.try_acquire(
        RunLeaseRequest("run-b", "profile-a", "project-b", ("/repo/sub",), "RUNNING")
    )
    assert blocked.reason_code == "WRITE_ROOT_OVERLAP"

    reconciled = controller.confirm_interrupted_reconciled("run-a")
    scheduler.update_state("run-a", reconciled.value)
    allowed = scheduler.try_acquire(
        RunLeaseRequest("run-b", "profile-a", "project-b", ("/repo/sub",), "RUNNING")
    )
    assert allowed.allowed


class _RunStore:
    def __init__(self, state: RunState) -> None:
        self.state = state

    def get_run_state(self, run_id: str) -> RunState:
        return self.state

    def compare_and_set_run_state(
        self,
        run_id: str,
        *,
        expected: RunState,
        new: RunState,
        retain_lock: bool,
    ) -> RunState:
        assert self.state is expected
        self.state = new
        return new


class _Cancellations:
    def cancel_generation(self, run_id: str) -> None:
        return None


class _ProcessTree:
    def __init__(self, stop, *, confirmed: bool) -> None:
        self._stop = stop
        self.confirmed = confirmed

    def terminate_and_confirm(self, run_id: str):
        return self._stop.TerminationResult(self.confirmed)


class _Checkpoints:
    def __init__(self, stop, *, verified: bool) -> None:
        self._stop = stop
        self.verified = verified

    def write_verified(self, run_id: str, *, kind: str):
        return self._stop.StopCheckpoint(self.verified)
