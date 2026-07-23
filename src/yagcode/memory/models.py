"""Typed memory records and lifecycle values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MemoryScope = Literal["thread", "project", "cross_project"]
MemoryStatus = Literal["tentative", "formal", "deleted"]
FactType = Literal["project_fact", "user_rule", "model_hypothesis"]


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    profile_id: str
    project_id: str
    thread_id: str | None
    scope: MemoryScope
    status: MemoryStatus
    fact_type: FactType
    text: str
    content_ref: str
    source_ids: tuple[str, ...]
    pinned: bool = False


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    profile_id: str
    project_id: str
    thread_id: str | None
    scope: MemoryScope
    status: MemoryStatus
    fact_type: FactType
    text: str
    content_ref: str
    source_ids: tuple[str, ...]
    created_sequence: int
    pinned: bool = False


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    candidate_id: str
    source_memory_id: str
    target_project: str


__all__ = [
    "FactType",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStatus",
    "MemoryWrite",
    "PromotionCandidate",
]
