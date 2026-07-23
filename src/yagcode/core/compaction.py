"""Blocking compaction guards and failure accounting."""

from __future__ import annotations

from dataclasses import dataclass

from .context import ActiveContext


class CompactionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CompactionDecision:
    state: str
    reason_code: str
    original_artifact_refs: tuple[str, ...] = ()


class CompactionController:
    def __init__(self, *, max_context_tokens: int, threshold: float = 0.70) -> None:
        if max_context_tokens <= 0:
            raise ValueError("COMPACTION_CONTEXT_LIMIT_INVALID")
        self._max_context_tokens = max_context_tokens
        self._threshold = threshold

    def should_compact(self, estimated_tokens: int) -> bool:
        if estimated_tokens < 0:
            raise ValueError("COMPACTION_TOKEN_ESTIMATE_INVALID")
        return estimated_tokens / self._max_context_tokens >= self._threshold


class CompactionFailureTracker:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._originals: dict[str, set[str]] = {}

    def record_failure(self, run_id: str, original_artifact_ref: str) -> CompactionDecision:
        if type(run_id) is not str or not run_id or type(original_artifact_ref) is not str:
            raise ValueError("COMPACTION_FAILURE_INVALID")
        self._counts[run_id] = self._counts.get(run_id, 0) + 1
        self._originals.setdefault(run_id, set()).add(original_artifact_ref)
        originals = tuple(sorted(self._originals[run_id]))
        if self._counts[run_id] >= 3:
            return CompactionDecision(
                "PAUSED_FAILURE",
                "COMPACTION_FAILURE_LIMIT_REACHED",
                originals,
            )
        return CompactionDecision("COMPACTING", "COMPACTION_RETRY_AVAILABLE", originals)


def validate_compaction(before: ActiveContext, after: ActiveContext) -> None:
    before_required = {
        (item.kind, item.source_id, item.content_ref, item.content_hash)
        for item in before.items
    }
    after_required = {
        (item.kind, item.source_id, item.content_ref, item.content_hash)
        for item in after.items
    }
    if not before_required <= after_required or before.feedback_codes != after.feedback_codes:
        raise CompactionError("COMPACTION_REQUIRED_FIELD_LOSS")


__all__ = [
    "CompactionController",
    "CompactionDecision",
    "CompactionError",
    "CompactionFailureTracker",
    "validate_compaction",
]
