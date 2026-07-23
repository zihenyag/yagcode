"""Retention policy helpers for memory-adjacent records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


Clock = Callable[[], datetime]
RETENTION_DAYS: dict[str, int | None] = {
    "permanent": None,
    "30d": 30,
    "60d": 60,
    "90d": 90,
    "180d": 180,
    "1y": 365,
    "2y": 730,
}


def _default_clock() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RetentionRecord:
    profile_id: str
    category: str
    value: str
    retention: str
    created_at: datetime


class RetentionStore:
    def __init__(self, *, clock: Clock = _default_clock) -> None:
        self._clock = clock
        self._records: list[RetentionRecord] = []

    def add(self, profile_id: str, category: str, value: str, retention: str) -> None:
        if retention not in RETENTION_DAYS:
            raise ValueError("RETENTION_POLICY_INVALID")
        self._records.append(RetentionRecord(profile_id, category, value, retention, self._clock()))

    def cleanup(self) -> None:
        now = self._clock()
        kept: list[RetentionRecord] = []
        for record in self._records:
            days = RETENTION_DAYS[record.retention]
            if days is None or now - record.created_at <= timedelta(days=days):
                kept.append(record)
        self._records = kept

    def values(self, profile_id: str) -> tuple[str, ...]:
        return tuple(record.value for record in self._records if record.profile_id == profile_id)


__all__ = ["RETENTION_DAYS", "RetentionRecord", "RetentionStore"]
