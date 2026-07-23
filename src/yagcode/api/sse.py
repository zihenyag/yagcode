"""SSE serialization helpers."""

from __future__ import annotations

from yagcode.api.schemas import EventEnvelope


def encode_sse(event: EventEnvelope) -> str:
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {event.model_dump_json()}\n\n"


__all__ = ["encode_sse"]
