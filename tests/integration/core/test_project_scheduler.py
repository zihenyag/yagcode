"""project scheduler lock integration tests."""

from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest


def test_owned_project_root_overlap_scheduler_oracle() -> None:
    oracle = _OwnedSchedulerOracle()
    assert oracle.try_acquire("run-a", "project-a", ("/repo",))
    assert not oracle.try_acquire("run-b", "project-a", ("/other",))
    assert not oracle.try_acquire("run-c", "project-c", ("/repo/sub",))
    assert oracle.try_acquire("run-d", "project-d", ("/other",))
    oracle.release("run-a")
    assert oracle.try_acquire("run-e", "project-a", ("/repo/sub",))


def load_scheduler_contract():
    try:
        return importlib.import_module("yagcode.core.scheduler")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"CORE_LOOP_CONTRACT_MISSING: {error.name}")
        raise


def test_project_scheduler_rejects_same_project_and_overlapping_roots() -> None:
    scheduler_mod = load_scheduler_contract()
    scheduler = scheduler_mod.ProjectScheduler()

    first = scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-a", "profile-a", "project-a", ("/repo",), "RUNNING")
    )
    same_project = scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-b", "profile-a", "project-a", ("/other",), "RUNNING")
    )
    overlap = scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-c", "profile-a", "project-c", ("/repo/sub",), "RUNNING")
    )
    disjoint = scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-d", "profile-a", "project-d", ("/other",), "RUNNING")
    )

    assert first.allowed
    assert same_project.reason_code == "PROJECT_LOCK_HELD"
    assert overlap.reason_code == "WRITE_ROOT_OVERLAP"
    assert disjoint.allowed


def test_scheduler_holds_waiting_states_and_releases_terminal_states() -> None:
    scheduler_mod = load_scheduler_contract()
    scheduler = scheduler_mod.ProjectScheduler()
    assert scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-a", "profile-a", "project-a", ("/repo",), "RUNNING")
    ).allowed

    scheduler.update_state("run-a", "WAITING_PERMISSION")
    waiting_conflict = scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-b", "profile-a", "project-a", ("/repo2",), "RUNNING")
    )
    assert waiting_conflict.reason_code == "PROJECT_LOCK_HELD"

    scheduler.update_state("run-a", "FINISHED")
    after_release = scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-b", "profile-a", "project-a", ("/repo2",), "RUNNING")
    )
    assert after_release.allowed


@pytest.mark.parametrize(
    "state",
    ["RUNNING", "WAITING_PERMISSION", "WAITING_PRIVACY", "COMPACTING", "STOPPING", "INTERRUPTED"],
)
def test_scheduler_holds_every_locking_run_state(state: str) -> None:
    scheduler_mod = load_scheduler_contract()
    scheduler = scheduler_mod.ProjectScheduler()
    assert scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-a", "profile-a", "project-a", ("/repo",), "RUNNING")
    ).allowed

    scheduler.update_state("run-a", state)
    conflict = scheduler.try_acquire(
        scheduler_mod.RunLeaseRequest("run-b", "profile-a", "project-b", ("/repo/sub",), "RUNNING")
    )

    assert conflict.reason_code == "WRITE_ROOT_OVERLAP"


@dataclass
class _OwnedLease:
    run_id: str
    project_id: str
    roots: tuple[str, ...]


class _OwnedSchedulerOracle:
    def __init__(self) -> None:
        self._active: dict[str, _OwnedLease] = {}

    def try_acquire(self, run_id: str, project_id: str, roots: tuple[str, ...]) -> bool:
        if any(lease.project_id == project_id for lease in self._active.values()):
            return False
        if any(_roots_overlap(roots, lease.roots) for lease in self._active.values()):
            return False
        self._active[run_id] = _OwnedLease(run_id, project_id, roots)
        return True

    def release(self, run_id: str) -> None:
        self._active.pop(run_id, None)


def _roots_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return any(_root_overlaps_one(a, b) for a in left for b in right)


def _root_overlaps_one(left: str, right: str) -> bool:
    left_norm = left.rstrip("/")
    right_norm = right.rstrip("/")
    return (
        left_norm == right_norm
        or right_norm.startswith(left_norm + "/")
        or left_norm.startswith(right_norm + "/")
    )
