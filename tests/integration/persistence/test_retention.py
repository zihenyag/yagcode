"""Retention decisions are deterministic and profile deletion cleans all records."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta


def test_owned_retention_boundary_oracle() -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    assert now - timedelta(days=30) <= now
    assert now - timedelta(days=31) < now - timedelta(days=30)


def test_retention_keeps_permanent_preview_and_audit_then_profile_delete() -> None:
    production = importlib.import_module("yagcode.policy.privacy")
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    retention = production.RetentionService(clock=lambda: clock[0])
    retention.record("profile", "conversation", "30d", "body")
    retention.record("profile", "tool_output", "30d", "tool")
    retention.record("profile", "privacy_preview", "permanent", "preview")
    retention.record("profile", "audit", "permanent", "audit")
    clock[0] += timedelta(days=31)
    retention.cleanup()
    assert retention.values("profile") == ("preview", "audit")
    retention.delete_profile("profile")
    assert retention.values("profile") == ()
