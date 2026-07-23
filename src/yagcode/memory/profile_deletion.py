"""Profile deletion reconciliation helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


DeleteFn = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class NamedDeleter:
    name: str
    delete: DeleteFn


@dataclass(frozen=True, slots=True)
class DeletionResult:
    complete: bool
    incomplete: tuple[str, ...]


class ProfileDeletionService:
    def __init__(self, deleters: tuple[NamedDeleter, ...]) -> None:
        self._deleters = deleters

    def delete_profile(self, profile_id: str) -> DeletionResult:
        incomplete: list[str] = []
        for deleter in self._deleters:
            if not deleter.delete(profile_id):
                incomplete.append(deleter.name)
        return DeletionResult(not incomplete, tuple(incomplete))


__all__ = ["DeletionResult", "NamedDeleter", "ProfileDeletionService"]
