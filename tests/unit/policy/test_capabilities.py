"""Test-owned capability oracles for the deterministic policy contract."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, replace

import pytest


def _production() -> object:
    return importlib.import_module("yagcode.policy")


@dataclass(frozen=True)
class _FakeCapability:
    action_kind: str
    target: str
    network_port: int | None


def _fake_exact_rule(rule: tuple[_FakeCapability, ...], request: tuple[_FakeCapability, ...]) -> bool:
    """Independent oracle: every requested atomic capability must be present."""
    return set(request) <= set(rule)


def test_owned_exact_set_oracle_rejects_every_atomic_field() -> None:
    base = _FakeCapability("run_command", "/shadow/a", 443)
    assert _fake_exact_rule((base,), (base,))
    assert not _fake_exact_rule((base,), (replace(base, action_kind="apply_patch"),))
    assert not _fake_exact_rule((base,), (replace(base, target="/shadow/b"),))
    assert not _fake_exact_rule((base,), (replace(base, network_port=8443),))


def _capability(production: object, **changed: object) -> object:
    values: dict[str, object] = {
        "profile_id": "profile-a",
        "project_id": "project-a",
        "action_kind": "run_command",
        "verb": "execute",
        "side_effect_class": "sandboxed",
        "canonical_target": "/shadow/project/src/app.py",
        "resource_identity": "file:11:22",
        "read_write_capability": "execute",
        "executable_identity": "exe:python:1",
        "normalized_argv": ("python", "-m", "pytest"),
        "canonical_cwd": "/shadow/project",
        "sanitized_environment_hash": "env-a",
        "recursive_flag": False,
        "network_scheme": "https",
        "idna_host": "api.example.test",
        "network_port": 443,
        "precondition_hash": "pre-a",
        "policy_version": 7,
    }
    values.update(changed)
    return production.Capability(**values)


def test_capability_canonical_bytes_cover_every_spec_field() -> None:
    production = _production()
    base = _capability(production)
    fields = (
        "profile_id", "project_id", "action_kind", "verb", "side_effect_class",
        "canonical_target", "resource_identity", "read_write_capability",
        "executable_identity", "normalized_argv", "canonical_cwd",
        "sanitized_environment_hash", "recursive_flag", "network_scheme", "idna_host",
        "network_port", "precondition_hash", "policy_version",
    )
    for field in fields:
        replacement = {
            "profile_id": "profile-b", "project_id": "project-b", "action_kind": "read_text",
            "verb": "read", "side_effect_class": "external", "canonical_target": "/shadow/other",
            "resource_identity": "file:99:99", "read_write_capability": "read",
            "executable_identity": "exe:other", "normalized_argv": ("other",),
            "canonical_cwd": "/shadow/other", "sanitized_environment_hash": "env-b",
            "recursive_flag": True, "network_scheme": "http", "idna_host": "xn--fsqu00a.xn--0zwm56d",
            "network_port": 8443, "precondition_hash": "pre-b", "policy_version": 8,
        }[field]
        assert base.canonical_bytes() != replace(base, **{field: replacement}).canonical_bytes(), field


def test_persistent_rule_matches_only_complete_atomic_capabilities() -> None:
    production = _production()
    base = _capability(production)
    engine = production.PolicyEngine(persistent_rules=(production.PersistentRule("r1", (base,)),))
    assert engine.evaluate((base,)).outcome == production.PolicyOutcome.ALLOW
    mutations = {
        "action_kind": "apply_patch", "canonical_target": "/shadow/other", "resource_identity": "file:2",
        "read_write_capability": "write", "executable_identity": "exe:other",
        "normalized_argv": ("python", "-c", "bad"), "canonical_cwd": "/shadow/other",
        "network_scheme": "http", "idna_host": "other.example.test", "network_port": 8443,
    }
    for field, value in mutations.items():
        assert engine.evaluate((replace(base, **{field: value}),)).outcome == production.PolicyOutcome.REQUIRE_APPROVAL


def test_safe_read_is_allowed_but_default_write_requires_approval() -> None:
    production = _production()
    safe_read = _capability(
        production, action_kind="read_text", verb="read", side_effect_class="read_only",
        read_write_capability="read", executable_identity=None, normalized_argv=(), network_scheme=None,
        idna_host=None, network_port=None,
    )
    write = replace(safe_read, action_kind="apply_patch", verb="write", side_effect_class="sandboxed",
                    read_write_capability="write")
    engine = production.PolicyEngine()
    assert engine.evaluate((safe_read,)).outcome == production.PolicyOutcome.ALLOW
    assert engine.evaluate((write,)).outcome == production.PolicyOutcome.REQUIRE_APPROVAL


@pytest.mark.parametrize(
    "kind",
    ("credential_read", "bypass_dispatcher", "project_direct_network", "write_real_worktree", "model_accept"),
)
def test_hard_denials_never_allow_even_with_session_full_access(kind: str) -> None:
    production = _production()
    engine = production.PolicyEngine()
    engine.enable_session_full_access()
    capability = _capability(production, action_kind=kind, side_effect_class="hard_denied")
    decision = engine.evaluate((capability,))
    assert decision.outcome == production.PolicyOutcome.DENY
    assert decision.reason == "HARD_DENY"


@pytest.mark.parametrize("kind", ("accept", "commit", "branch", "push", "remote_intent"))
def test_session_full_access_never_auto_accepts_privileged_intents(kind: str) -> None:
    production = _production()
    engine = production.PolicyEngine()
    engine.enable_session_full_access()
    assert engine.evaluate((_capability(production, action_kind=kind),)).outcome == production.PolicyOutcome.REQUIRE_APPROVAL


def test_session_full_access_is_revocable_and_not_restart_durable() -> None:
    production = _production()
    capability = _capability(production)
    engine = production.PolicyEngine()
    engine.enable_session_full_access()
    assert engine.evaluate((capability,)).outcome == production.PolicyOutcome.ALLOW
    engine.revoke_session_full_access()
    assert engine.evaluate((capability,)).outcome == production.PolicyOutcome.REQUIRE_APPROVAL
    restarted = production.PolicyEngine()
    assert restarted.evaluate((capability,)).outcome == production.PolicyOutcome.REQUIRE_APPROVAL


def test_policy_fails_closed_for_empty_or_partial_network_capability_sets() -> None:
    production = _production()
    engine = production.PolicyEngine()
    assert engine.evaluate(()).outcome == production.PolicyOutcome.DENY
    partial = _capability(production, network_port=None)
    decision = engine.evaluate((partial,))
    assert decision.outcome == production.PolicyOutcome.DENY
    assert decision.reason == "CAPABILITY_NETWORK_TUPLE_INCOMPLETE"


def test_persistent_rule_and_full_access_cannot_override_explicit_or_hard_boundaries() -> None:
    production = _production()
    explicit = _capability(production, action_kind="push")
    hard = _capability(
        production,
        action_kind="bypass_audit",
        side_effect_class="hard_denied",
    )
    engine = production.PolicyEngine(
        persistent_rules=(production.PersistentRule("unsafe", (explicit, hard)),)
    )
    engine.enable_session_full_access()
    assert engine.evaluate((explicit,)).outcome == production.PolicyOutcome.REQUIRE_APPROVAL
    assert engine.evaluate((hard,)).outcome == production.PolicyOutcome.DENY


def test_rule_rejects_duplicate_atomic_capabilities() -> None:
    production = _production()
    capability = _capability(production)
    with pytest.raises(ValueError, match="PERSISTENT_RULE_CAPABILITIES_DUPLICATE"):
        production.PersistentRule("duplicate", (capability, capability))


def test_policy_revalidates_capability_mirror_forged_capability_before_full_access() -> None:
    production = _production()
    capability = _capability(production)
    object.__setattr__(capability, "network_port", True)
    engine = production.PolicyEngine()
    engine.enable_session_full_access()
    decision = engine.evaluate((capability,))
    assert decision.outcome == production.PolicyOutcome.DENY
    assert decision.reason == "CAPABILITY_SET_INVALID"


def test_session_full_access_denies_unknown_action_kind() -> None:
    production = _production()
    engine = production.PolicyEngine()
    engine.enable_session_full_access()
    decision = engine.evaluate((_capability(production, action_kind="model_invented_kind"),))
    assert decision.outcome == production.PolicyOutcome.DENY
    assert decision.reason == "CAPABILITY_ACTION_KIND_UNKNOWN"
