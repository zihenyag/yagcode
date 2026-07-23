"""stop and steer queue tests."""

from __future__ import annotations

import importlib

import pytest

from yagcode.domain.states import RunState


def test_owned_stop_and_steer_oracle() -> None:
    events: list[str] = []
    events.append("cancel_generation")
    events.append("terminate_tree")
    assert events == ["cancel_generation", "terminate_tree"]
    pending = ["extra context"]
    generation = 1
    assert generation + (1 if pending else 0) == 2


def load_runtime_control_contract():
    try:
        return (
            importlib.import_module("yagcode.core.stop"),
            importlib.import_module("yagcode.core.steer"),
        )
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"RUNTIME_CONTROL_CONTRACT_MISSING: {error.name}")
        raise


def test_stop_confirms_process_tree_dead_and_releases_lock() -> None:
    stop, _ = load_runtime_control_contract()
    store = _RunStore(RunState.RUNNING)
    controller = stop.StopController(
        store=store,
        cancellations=_Cancellations(),
        process_tree=_ProcessTree(stop, confirmed=True),
        checkpoints=_Checkpoints(stop, verified=True),
    )
    result = controller.stop("run-a")
    assert result is RunState.PAUSED_BY_USER
    assert store.retained_locks == [True, False]


def test_stop_failure_interrupts_and_retains_lock() -> None:
    stop, _ = load_runtime_control_contract()
    store = _RunStore(RunState.RUNNING)
    controller = stop.StopController(
        store=store,
        cancellations=_Cancellations(),
        process_tree=_ProcessTree(stop, confirmed=False),
        checkpoints=_Checkpoints(stop, verified=True),
    )
    result = controller.stop("run-a")
    assert result is RunState.INTERRUPTED
    assert store.retained_locks == [True, True]


def test_steer_merges_only_at_action_boundary_and_invalidates_generation() -> None:
    _, steer = load_runtime_control_contract()
    queue = steer.SteerQueue()
    queue.append("run-a", "more context")
    assert queue.pending_count("run-a") == 1
    result = queue.drain_at_boundary("run-a", current_generation=7)
    assert result.messages == ("more context",)
    assert result.generation == 8
    assert queue.pending_count("run-a") == 0


class _RunStore:
    def __init__(self, state: RunState) -> None:
        self.state = state
        self.retained_locks: list[bool] = []

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
        self.retained_locks.append(retain_lock)
        return new


class _Cancellations:
    def __init__(self) -> None:
        self.calls = 0

    def cancel_generation(self, run_id: str) -> None:
        self.calls += 1


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
