"""Test-owned approval-token oracles; policy production is runtime-loaded only."""

from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest


def _production() -> object:
    return importlib.import_module("yagcode.policy")


@dataclass
class _FakeRecord:
    used: bool = False
    expiry: int = 10


def _fake_consume(record: _FakeRecord, *, now: int, matches: bool) -> str:
    if record.used:
        return "APPROVAL_TOKEN_CONSUMED"
    if now >= record.expiry:
        return "APPROVAL_TOKEN_EXPIRED"
    if not matches:
        return "APPROVAL_BINDING_MISMATCH"
    record.used = True
    return "ALLOWED"


def test_owned_replay_oracle_distinguishes_expiry_binding_and_replay() -> None:
    assert _fake_consume(_FakeRecord(), now=0, matches=False) == "APPROVAL_BINDING_MISMATCH"
    assert _fake_consume(_FakeRecord(), now=10, matches=True) == "APPROVAL_TOKEN_EXPIRED"
    record = _FakeRecord()
    assert _fake_consume(record, now=0, matches=True) == "ALLOWED"
    assert _fake_consume(record, now=0, matches=True) == "APPROVAL_TOKEN_CONSUMED"


def _binding(production: object, **changed: object) -> object:
    capability = production.Capability(
        profile_id="profile", project_id="project", action_kind="apply_patch", verb="write",
        side_effect_class="sandboxed", canonical_target="/shadow/file", resource_identity="id:1",
        read_write_capability="write", executable_identity=None, normalized_argv=(),
        canonical_cwd="/shadow", sanitized_environment_hash="env", recursive_flag=False,
        network_scheme=None, idna_host=None, network_port=None, precondition_hash="pre", policy_version=3,
    )
    values: dict[str, object] = {
        "profile_id": "profile", "run_id": "run", "generation": 2, "action_id": "action",
        "payload_hash": "payload", "capabilities": (capability,), "resolved_target_identities": ("id:1",),
        "policy_version": 3, "precondition_hash": "pre",
    }
    values.update(changed)
    return production.IntentBinding.from_capabilities(**values)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_repository_keeps_only_hmac_digest_not_plaintext_token() -> None:
    production = _production()
    clock = _Clock()
    repository = production.InMemoryIntentRepository()
    service = production.ApprovalService(repository, key=b"k" * 32, clock=clock, ttl=timedelta(minutes=1))
    token = service.issue_for_main(_binding(production))
    assert token not in repr(repository.records())
    assert all(record.token_digest != token for record in repository.records())
    assert len(repository.records()[0].token_digest) == 64


@pytest.mark.parametrize(
    "field,value",
    (
        ("profile_id", "other-profile"), ("run_id", "other-run"), ("generation", 3),
        ("action_id", "other-action"), ("payload_hash", "other-payload"),
        ("resolved_target_identities", ("id:2",)), ("policy_version", 4),
        ("precondition_hash", "other-pre"),
    ),
)
def test_once_token_rejects_each_explicit_bound_field(field: str, value: object) -> None:
    production = _production()
    clock = _Clock()
    service = production.ApprovalService(production.InMemoryIntentRepository(), key=b"k" * 32, clock=clock)
    binding = _binding(production)
    token = service.issue_for_main(binding)
    decision = service.consume_for_main(token, replace(binding, **{field: value}))
    assert not decision.allowed
    assert decision.reason == "APPROVAL_BINDING_MISMATCH"


def test_once_token_rejects_capability_hash_and_each_capability_field_mutation() -> None:
    production = _production()
    clock = _Clock()
    binding = _binding(production)
    capability = binding.capabilities[0]
    fields = ("profile_id", "project_id", "action_kind", "verb", "side_effect_class", "canonical_target",
              "resource_identity", "read_write_capability", "executable_identity", "normalized_argv",
              "canonical_cwd", "sanitized_environment_hash", "recursive_flag", "network_scheme", "idna_host",
              "network_port", "precondition_hash", "policy_version")
    changes = {"profile_id": "p2", "project_id": "q2", "action_kind": "read_text", "verb": "read",
               "side_effect_class": "external", "canonical_target": "/other", "resource_identity": "id:2",
               "read_write_capability": "read", "executable_identity": "exe:2", "normalized_argv": ("x",),
               "canonical_cwd": "/other", "sanitized_environment_hash": "env2", "recursive_flag": True,
               "network_scheme": "https", "idna_host": "api.example.test", "network_port": 443,
               "precondition_hash": "pre2", "policy_version": 4}
    for field in fields:
        service = production.ApprovalService(production.InMemoryIntentRepository(), key=b"k" * 32, clock=clock)
        token = service.issue_for_main(binding)
        mutated = replace(capability, **{field: changes[field]})
        changed_binding = production.IntentBinding.from_capabilities(
            profile_id=binding.profile_id, run_id=binding.run_id, generation=binding.generation,
            action_id=binding.action_id, payload_hash=binding.payload_hash, capabilities=(mutated,),
            resolved_target_identities=binding.resolved_target_identities, policy_version=binding.policy_version,
            precondition_hash=binding.precondition_hash,
        )
        assert service.consume_for_main(token, changed_binding).reason == "APPROVAL_BINDING_MISMATCH", field


def test_expiry_wrong_token_replay_and_action_failure_have_zero_authorization() -> None:
    production = _production()
    clock = _Clock()
    repo = production.InMemoryIntentRepository()
    service = production.ApprovalService(repo, key=b"k" * 32, clock=clock, ttl=timedelta(seconds=1))
    binding = _binding(production)
    token = service.issue_for_main(binding)
    assert service.consume_for_main("wrong", binding).reason == "APPROVAL_TOKEN_INVALID"
    clock.now += timedelta(seconds=1)
    assert service.consume_for_main(token, binding).reason == "APPROVAL_TOKEN_EXPIRED"
    clock.now -= timedelta(seconds=1)
    token = service.issue_for_main(binding)
    created: list[str] = []
    assert service.consume_and_create_system_action(token, binding, lambda: created.append("created")).allowed
    assert created == ["created"]
    assert service.consume_and_create_system_action(token, binding, lambda: created.append("replay")).reason == "APPROVAL_TOKEN_CONSUMED"
    token = service.issue_for_main(binding)
    with pytest.raises(RuntimeError, match="create failed"):
        service.consume_and_create_system_action(token, binding, lambda: (_ for _ in ()).throw(RuntimeError("create failed")))
    assert service.consume_for_main(token, binding).allowed


def test_renderer_can_request_but_never_read_or_consume_plaintext_challenge() -> None:
    production = _production()
    service = production.ApprovalService(production.InMemoryIntentRepository(), key=b"k" * 32, clock=_Clock())
    request = service.request_from_renderer(_binding(production), "approve_permission")
    assert request.kind == "approve_permission"
    assert not hasattr(request, "token")
    with pytest.raises(PermissionError, match="MAIN_CHANNEL_REQUIRED"):
        service.issue_for_renderer(_binding(production))
    with pytest.raises(PermissionError, match="MAIN_CHANNEL_REQUIRED"):
        service.consume_for_renderer("anything", _binding(production))


@pytest.mark.parametrize("mismatch", ["profile", "policy"])
def test_binding_rejects_capability_owner_or_policy_inconsistency(mismatch: str) -> None:
    production = _production()
    binding = _binding(production)
    values = {
        "profile_id": "other" if mismatch == "profile" else binding.profile_id,
        "run_id": binding.run_id,
        "generation": binding.generation,
        "action_id": binding.action_id,
        "payload_hash": binding.payload_hash,
        "capabilities": binding.capabilities,
        "resolved_target_identities": binding.resolved_target_identities,
        "policy_version": 99 if mismatch == "policy" else binding.policy_version,
        "precondition_hash": binding.precondition_hash,
    }
    inconsistent = production.IntentBinding.from_capabilities(**values)
    service = production.ApprovalService(
        production.InMemoryIntentRepository(),
        key=b"k" * 32,
        clock=_Clock(),
    )
    with pytest.raises(ValueError, match="INTENT_CAPABILITY_(OWNER|POLICY)_MISMATCH"):
        service.issue_for_main(inconsistent)


def test_parallel_token_consumption_authorizes_exactly_one_system_action() -> None:
    production = _production()
    repository = production.InMemoryIntentRepository()
    service = production.ApprovalService(
        repository,
        key=b"k" * 32,
        clock=_Clock(),
    )
    binding = _binding(production)
    token = service.issue_for_main(binding)
    barrier = threading.Barrier(2)
    decisions: list[object] = []

    def consume() -> None:
        barrier.wait()
        decisions.append(
            service.consume_and_create_system_action(token, binding, lambda: None)
        )

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(decision.allowed for decision in decisions) == 1
    assert {decision.reason for decision in decisions} == {"ALLOWED", "APPROVAL_TOKEN_CONSUMED"}
    assert repository.authorized_system_actions == 1


def test_renderer_rejects_unregistered_intent_kind_without_creating_challenge() -> None:
    production = _production()
    repository = production.InMemoryIntentRepository()
    service = production.ApprovalService(
        repository,
        key=b"k" * 32,
        clock=_Clock(),
    )
    with pytest.raises(ValueError, match="APPROVAL_KIND_INVALID"):
        service.request_from_renderer(_binding(production), "prompt-controlled-kind")
    assert repository.records() == ()
    assert repository.authorized_system_actions == 0


def test_main_issues_once_from_server_side_renderer_request_binding() -> None:
    production = _production()
    repository = production.InMemoryIntentRepository()
    service = production.ApprovalService(
        repository,
        key=b"k" * 32,
        clock=_Clock(),
    )
    binding = _binding(production)
    request = service.request_from_renderer(binding, "permission")
    assert repository.records() == ()
    token = service.issue_requested_for_main(request.request_id)
    assert service.consume_for_main(token, binding).allowed
    with pytest.raises(ValueError, match="APPROVAL_REQUEST_INVALID"):
        service.issue_requested_for_main(request.request_id)


def test_intent_binding_rejects_duplicate_atomic_capabilities() -> None:
    production = _production()
    binding = _binding(production)
    capability = binding.capabilities[0]
    with pytest.raises(ValueError, match="INTENT_CAPABILITIES_DUPLICATE"):
        production.IntentBinding.from_capabilities(
            profile_id=binding.profile_id,
            run_id=binding.run_id,
            generation=binding.generation,
            action_id=binding.action_id,
            payload_hash=binding.payload_hash,
            capabilities=(capability, capability),
            resolved_target_identities=binding.resolved_target_identities,
            policy_version=binding.policy_version,
            precondition_hash=binding.precondition_hash,
        )


def test_token_digest_collision_never_creates_a_second_consumable_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _production()
    approvals = importlib.import_module("yagcode.policy.approvals")
    monkeypatch.setattr(approvals.secrets, "token_urlsafe", lambda _: "fixed-token")
    repository = production.InMemoryIntentRepository()
    service = production.ApprovalService(
        repository,
        key=b"k" * 32,
        clock=_Clock(),
    )
    assert service.issue_for_main(_binding(production)) == "fixed-token"
    with pytest.raises(RuntimeError, match="APPROVAL_TOKEN_GENERATION_COLLISION"):
        service.issue_for_main(_binding(production))
    assert len(repository.records()) == 1


def test_consume_revalidates_capability_mirror_forged_capability_hash() -> None:
    production = _production()
    repository = production.InMemoryIntentRepository()
    service = production.ApprovalService(
        repository,
        key=b"k" * 32,
        clock=_Clock(),
    )
    binding = _binding(production)
    token = service.issue_for_main(binding)
    object.__setattr__(binding.capabilities[0], "canonical_target", "/forged-target")
    decision = service.consume_for_main(token, binding)
    assert not decision.allowed
    assert decision.reason == "APPROVAL_BINDING_MISMATCH"
    assert repository.authorized_system_actions == 0
