"""In-memory project/write-root scheduler used by the deterministic loop tests."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass


_RELEASE_STATES = frozenset(
    {
        "FINISHED",
        "DONE",
        "FAILED",
        "CANCELED",
        "CANCELLED",
        "REVIEWABLE",
        "PAUSED_BY_USER",
        "PAUSED_BUDGET",
        "PAUSED_FAILURE",
    }
)


@dataclass(frozen=True, slots=True)
class RunLeaseRequest:
    run_id: str
    profile_id: str
    project_id: str
    write_roots: tuple[str, ...]
    state: str


@dataclass(frozen=True, slots=True)
class SchedulerDecision:
    allowed: bool
    reason_code: str


@dataclass(frozen=True, slots=True)
class _Lease:
    run_id: str
    profile_id: str
    project_id: str
    write_roots: tuple[str, ...]
    state: str


class ProjectScheduler:
    def __init__(self) -> None:
        self._leases: dict[str, _Lease] = {}

    def try_acquire(self, request: RunLeaseRequest) -> SchedulerDecision:
        if request.state in _RELEASE_STATES:
            self.release(request.run_id)
            return SchedulerDecision(False, "RUN_STATE_DOES_NOT_HOLD_LOCK")
        roots = _normalize_roots(request.write_roots)
        if request.run_id in self._leases:
            self._leases[request.run_id] = _Lease(
                request.run_id,
                request.profile_id,
                request.project_id,
                roots,
                request.state,
            )
            return SchedulerDecision(True, "LOCK_REFRESHED")
        for lease in self._leases.values():
            if lease.project_id == request.project_id:
                return SchedulerDecision(False, "PROJECT_LOCK_HELD")
        for lease in self._leases.values():
            if _roots_overlap(roots, lease.write_roots):
                return SchedulerDecision(False, "WRITE_ROOT_OVERLAP")
        self._leases[request.run_id] = _Lease(
            request.run_id,
            request.profile_id,
            request.project_id,
            roots,
            request.state,
        )
        return SchedulerDecision(True, "LOCK_ACQUIRED")

    def update_state(self, run_id: str, state: str) -> None:
        lease = self._leases.get(run_id)
        if lease is None:
            return
        if state in _RELEASE_STATES:
            self.release(run_id)
            return
        self._leases[run_id] = _Lease(
            lease.run_id,
            lease.profile_id,
            lease.project_id,
            lease.write_roots,
            state,
        )

    def release(self, run_id: str) -> None:
        self._leases.pop(run_id, None)


def _normalize_roots(roots: tuple[str, ...]) -> tuple[str, ...]:
    if type(roots) is not tuple or not roots:
        raise ValueError("SCHEDULER_WRITE_ROOTS_INVALID")
    normalized: list[str] = []
    for root in roots:
        if type(root) is not str or not root.startswith("/") or "\x00" in root:
            raise ValueError("SCHEDULER_WRITE_ROOT_INVALID")
        normalized.append(posixpath.normpath(root))
    return tuple(sorted(set(normalized)))


def _roots_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return any(_root_overlaps_one(a, b) for a in left for b in right)


def _root_overlaps_one(left: str, right: str) -> bool:
    return left == right or right.startswith(left + "/") or left.startswith(right + "/")


__all__ = ["ProjectScheduler", "RunLeaseRequest", "SchedulerDecision"]
