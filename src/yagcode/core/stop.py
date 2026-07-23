"""Safe stop and interrupted-run reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from yagcode.domain.states import RunState
from yagcode.domain.transitions import RunGuards, transition_run


@dataclass(frozen=True, slots=True)
class TerminationResult:
    confirmed_dead: bool


@dataclass(frozen=True, slots=True)
class StopCheckpoint:
    verified: bool


class CheckpointError(RuntimeError):
    pass


class RunStateStore(Protocol):
    def get_run_state(self, run_id: str) -> RunState: ...

    def compare_and_set_run_state(
        self,
        run_id: str,
        *,
        expected: RunState,
        new: RunState,
        retain_lock: bool,
    ) -> RunState: ...


class CancellationPort(Protocol):
    def cancel_generation(self, run_id: str) -> None: ...


class ProcessTreePort(Protocol):
    def terminate_and_confirm(self, run_id: str) -> TerminationResult: ...


class CheckpointPort(Protocol):
    def write_verified(self, run_id: str, *, kind: str) -> StopCheckpoint: ...


class StopController:
    def __init__(
        self,
        *,
        store: RunStateStore,
        cancellations: CancellationPort,
        process_tree: ProcessTreePort,
        checkpoints: CheckpointPort,
    ) -> None:
        self._store = store
        self._cancellations = cancellations
        self._process_tree = process_tree
        self._checkpoints = checkpoints

    def stop(self, run_id: str) -> RunState:
        current = self._store.get_run_state(run_id)
        stopping = transition_run(current, "request_stop")
        if current is not RunState.STOPPING:
            self._store.compare_and_set_run_state(
                run_id,
                expected=current,
                new=stopping,
                retain_lock=True,
            )
            self._cancellations.cancel_generation(run_id)
        termination = self._process_tree.terminate_and_confirm(run_id)
        if not termination.confirmed_dead:
            return self._interrupt(run_id, stopping)
        try:
            checkpoint = self._checkpoints.write_verified(run_id, kind="USER_STOP")
        except CheckpointError:
            return self._interrupt(run_id, stopping)
        if not checkpoint.verified:
            return self._interrupt(run_id, stopping)
        paused = transition_run(
            stopping,
            "stop_confirmed",
            RunGuards(process_tree_dead=True, stop_checkpoint_persisted=True),
        )
        return self._store.compare_and_set_run_state(
            run_id,
            expected=stopping,
            new=paused,
            retain_lock=False,
        )

    def confirm_interrupted_reconciled(self, run_id: str) -> RunState:
        current = self._store.get_run_state(run_id)
        paused = transition_run(
            current,
            "stop_confirmed",
            RunGuards(
                process_tree_dead=True,
                stop_checkpoint_persisted=True,
                unknown_side_effects_reconciled=True,
            ),
        )
        return self._store.compare_and_set_run_state(
            run_id,
            expected=current,
            new=paused,
            retain_lock=False,
        )

    def _interrupt(self, run_id: str, stopping: RunState) -> RunState:
        interrupted = transition_run(stopping, "stop_unconfirmed")
        return self._store.compare_and_set_run_state(
            run_id,
            expected=stopping,
            new=interrupted,
            retain_lock=True,
        )


__all__ = [
    "CheckpointError",
    "StopCheckpoint",
    "StopController",
    "TerminationResult",
]
