"""retention and profile deletion tests."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import pytest


def test_owned_retention_and_delete_oracle() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    expired = now - timedelta(days=31)
    assert now - expired > timedelta(days=30)
    complete = [True, False]
    assert not all(complete)


def load_memory_contract():
    try:
        return (
            importlib.import_module("yagcode.memory.retention"),
            importlib.import_module("yagcode.memory.profile_deletion"),
        )
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.memory"):
            pytest.fail(f"MEMORY_CONTRACT_MISSING: {error.name}")
        raise


def test_retention_keeps_permanent_and_removes_expired_records() -> None:
    retention, _ = load_memory_contract()
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    store = retention.RetentionStore(clock=clock)
    store.add("p", "conversation", "old", "30d")
    store.add("p", "audit", "forever", "permanent")
    clock.now += timedelta(days=31)
    store.cleanup()
    assert store.values("p") == ("forever",)


def test_profile_delete_reports_incomplete_deleters() -> None:
    _, deletion = load_memory_contract()
    service = deletion.ProfileDeletionService(
        (
            deletion.NamedDeleter("memory", lambda profile_id: True),
            deletion.NamedDeleter("keyring", lambda profile_id: False),
        )
    )
    result = service.delete_profile("p")
    assert result.complete is False
    assert result.incomplete == ("keyring",)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now
