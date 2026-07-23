"""Action-boundary steer queue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SteerMerge:
    messages: tuple[str, ...]
    generation: int


class SteerQueue:
    def __init__(self) -> None:
        self._messages: dict[str, list[str]] = {}

    def append(self, run_id: str, message: str) -> None:
        if type(run_id) is not str or not run_id or type(message) is not str or not message:
            raise ValueError("STEER_MESSAGE_INVALID")
        self._messages.setdefault(run_id, []).append(message)

    def pending_count(self, run_id: str) -> int:
        return len(self._messages.get(run_id, ()))

    def drain_at_boundary(self, run_id: str, *, current_generation: int) -> SteerMerge:
        messages = tuple(self._messages.pop(run_id, ()))
        generation = current_generation + 1 if messages else current_generation
        return SteerMerge(messages, generation)


__all__ = ["SteerMerge", "SteerQueue"]
