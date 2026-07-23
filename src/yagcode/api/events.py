"""Durable-enough in-memory event store used by deterministic sidecar tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from yagcode.api.schemas import EventEnvelope


@dataclass(slots=True)
class EventStore:
    profile_id: str
    _events: list[EventEnvelope] = field(default_factory=list)

    def append(self, event: EventEnvelope) -> EventEnvelope:
        if event.profile_id != self.profile_id:
            raise ValueError("EVENT_PROFILE_MISMATCH")
        if self._events and event.sequence <= self._events[-1].sequence:
            raise ValueError("EVENT_SEQUENCE_NOT_MONOTONIC")
        self._events.append(event)
        return event

    def replay_after(self, last_event_id: str | None) -> tuple[EventEnvelope, ...]:
        try:
            last_seen = int(last_event_id) if last_event_id is not None else 0
        except ValueError:
            last_seen = 0
        return tuple(event for event in self._events if event.sequence > last_seen)


__all__ = ["EventStore"]
