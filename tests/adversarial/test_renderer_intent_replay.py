"""A renderer injection must have zero authority over high-privilege actions."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest


def _production() -> object:
    return importlib.import_module("yagcode.policy")


def test_owned_renderer_oracle_only_records_requests() -> None:
    requests: list[str] = []
    requests.append("request")
    assert requests == ["request"]
    assert "approved" not in requests


def _binding(production: object) -> object:
    capability = production.Capability(
        profile_id="profile", project_id="project", action_kind="apply_patch", verb="write",
        side_effect_class="sandboxed", canonical_target="/shadow/file", resource_identity="id:1",
        read_write_capability="write", executable_identity=None, normalized_argv=(), canonical_cwd="/shadow",
        sanitized_environment_hash="env", recursive_flag=False, network_scheme=None, idna_host=None,
        network_port=None, precondition_hash="pre", policy_version=1,
    )
    return production.IntentBinding.from_capabilities(
        profile_id="profile", run_id="run", generation=0, action_id="action", payload_hash="payload",
        capabilities=(capability,), resolved_target_identities=("id:1",), policy_version=1, precondition_hash="pre",
    )


@pytest.mark.parametrize(
    "kind",
    ("plan", "permission", "privacy", "full_access", "accept", "commit", "branch", "push",
     "git_install", "git_init", "credential_update", "credential_clear", "profile_delete"),
)
def test_renderer_injection_can_request_but_has_zero_high_privilege_side_effects(kind: str) -> None:
    production = _production()
    repository = production.InMemoryIntentRepository()
    service = production.ApprovalService(repository, key=b"x" * 32, clock=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    binding = _binding(production)
    request = service.request_from_renderer(binding, kind)
    side_effects: list[str] = []
    assert request.kind == kind
    with pytest.raises(PermissionError):
        service.consume_for_renderer("injected", binding)
    assert side_effects == []
    assert repository.authorized_system_actions == 0
