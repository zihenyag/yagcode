"""Privacy grants bind an exact profile, source category and recipient-set version."""

from __future__ import annotations

import importlib


def test_owned_scope_oracle_rejects_secret_and_prefix_expansion() -> None:
    source = "project:p1/file:a.py"
    assert source == "project:p1/file:a.py"
    assert not "project:p1/file:secrets/a.py" == source


def test_grant_matches_approved_chinese_provider_set_only() -> None:
    production = importlib.import_module("yagcode.policy.privacy")
    guard = production.PrivacyGuard(current_recipient_set_version=1)
    grant = guard.grant("profile", "project:p1/file:a.py", "source", "debug", 1)
    assert guard.matches(grant, profile_id="profile", provider="deepseek", source="project:p1/file:a.py", category="source", purpose="debug")
    assert guard.matches(grant, profile_id="profile", provider="openai", source="project:p1/file:a.py", category="source", purpose="debug")
    assert not guard.matches(grant, profile_id="other", provider="openai", source="project:p1/file:a.py", category="source", purpose="debug")
    assert not guard.matches(grant, profile_id="profile", provider="openai", source="project:p1/file:secrets/a.py", category="source", purpose="debug")
    assert not guard.matches(grant, profile_id="profile", provider="openai", source="project:p1/file:a.py", category="secret", purpose="debug")
    assert not guard.matches(grant, profile_id="profile", provider="openai", source="project:p1/file:a.py", category="source", purpose="debug", recipient_set_version=2)


def test_secret_category_is_denied_before_preview() -> None:
    production = importlib.import_module("yagcode.policy.privacy")
    guard = production.PrivacyGuard(current_recipient_set_version=1)
    decision = guard.require_grant_or_preview("profile", "openai", "project:p1/file:a.py", "secret", "debug")
    assert decision.reason_code == "SECRET_SCOPE_DENIED"
    assert decision.preview_required is False
