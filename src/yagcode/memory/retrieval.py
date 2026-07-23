"""Scope-first memory retrieval."""

from __future__ import annotations

from collections.abc import Iterable

from .models import MemoryRecord


def retrieve_scoped(
    records: Iterable[MemoryRecord],
    *,
    profile_id: str,
    project_id: str,
    thread_id: str,
    query: str,
    limit: int = 12,
) -> tuple[MemoryRecord, ...]:
    query_text = query.casefold()
    filtered = [
        record
        for record in records
        if _visible(record, profile_id=profile_id, project_id=project_id, thread_id=thread_id)
        and query_text in record.text.casefold()
    ]
    filtered.sort(key=lambda record: (-int(record.pinned), -record.created_sequence))
    return tuple(filtered[:limit])


def _visible(record: MemoryRecord, *, profile_id: str, project_id: str, thread_id: str) -> bool:
    if record.profile_id != profile_id or record.project_id != project_id or record.status == "deleted":
        return False
    if record.scope == "thread":
        return record.thread_id == thread_id and record.status == "tentative"
    if record.scope in {"project", "cross_project"}:
        return record.status == "formal"
    return False


__all__ = ["retrieve_scoped"]
