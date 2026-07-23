"""Deterministic context objects assembled before each Provider call."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextItem:
    kind: str
    source_id: str
    content_ref: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ActiveContext:
    run_id: str
    generation: int
    items: tuple[ContextItem, ...]
    feedback_codes: tuple[str, ...]
    budget_version: int


class SnapshotContextBuilder:
    """Build the context directly from a persisted step snapshot."""

    def build(self, snapshot: object) -> ActiveContext:
        return ActiveContext(
            run_id=_text(getattr(snapshot, "run_id", None), "CONTEXT_RUN_ID_INVALID"),
            generation=_non_negative_int(
                getattr(snapshot, "generation", None),
                "CONTEXT_GENERATION_INVALID",
            ),
            items=_context_items(getattr(snapshot, "context_items", None)),
            feedback_codes=_text_tuple(
                getattr(snapshot, "feedback_codes", None),
                "CONTEXT_FEEDBACK_CODES_INVALID",
            ),
            budget_version=_non_negative_int(
                getattr(snapshot, "budget_version", None),
                "CONTEXT_BUDGET_VERSION_INVALID",
            ),
        )


def _context_items(value: object) -> tuple[ContextItem, ...]:
    if type(value) is not tuple or any(type(item) is not ContextItem for item in value):
        raise ValueError("CONTEXT_ITEMS_INVALID")
    return value


def _text_tuple(value: object, reason: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str or not item for item in value):
        raise ValueError(reason)
    return value


def _text(value: object, reason: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError(reason)
    return value


def _non_negative_int(value: object, reason: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(reason)
    return value


__all__ = ["ActiveContext", "ContextItem", "SnapshotContextBuilder"]
