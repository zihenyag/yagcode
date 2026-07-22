"""Pure deterministic policy evaluation over complete atomic capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .capabilities import Capability, PersistentRule


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason: str
    matched_rule_id: str | None = None


_HARD_DENIED_ACTIONS = frozenset(
    {
        "credential_read",
        "credential_access",
        "credential_egress",
        "bypass_dispatcher",
        "bypass_sandbox",
        "bypass_audit",
        "project_direct_network",
        "unconfined_host_access",
        "write_real_worktree",
        "write_real_worktree_before_review",
        "model_accept",
        "auto_accept",
    }
)
_ALWAYS_EXPLICIT_ACTIONS = frozenset(
    {
        "plan",
        "permission",
        "privacy",
        "full_access",
        "accept",
        "commit",
        "branch",
        "push",
        "force_push",
        "remote_intent",
        "remote_delete",
        "publish",
        "deploy",
        "git_install",
        "git_init",
        "credential_update",
        "credential_clear",
        "profile_delete",
    }
)
_KNOWN_ACTIONS = _HARD_DENIED_ACTIONS | _ALWAYS_EXPLICIT_ACTIONS | frozenset(
    {
        "list_directory",
        "read_text",
        "search_literal",
        "apply_patch",
        "git_inspect",
        "run_command",
        "run_validation",
        "request_review",
        "external_root_read",
        "external_root_write",
        "http_request",
        "provider_request",
        "model_list",
        "trusted_manifest_fetch",
    }
)


class PolicyEngine:
    def __init__(self, *, persistent_rules: tuple[PersistentRule, ...] = ()) -> None:
        if type(persistent_rules) is not tuple or any(
            type(rule) is not PersistentRule for rule in persistent_rules
        ):
            raise ValueError("POLICY_RULES_INVALID")
        self._persistent_rules = persistent_rules
        self._session_full_access = False

    def enable_session_full_access(self) -> None:
        self._session_full_access = True

    def revoke_session_full_access(self) -> None:
        self._session_full_access = False

    def evaluate(self, capabilities: tuple[Capability, ...]) -> PolicyDecision:
        if type(capabilities) is not tuple or not capabilities or any(
            type(capability) is not Capability or not capability.is_valid()
            for capability in capabilities
        ):
            return PolicyDecision(PolicyOutcome.DENY, "CAPABILITY_SET_INVALID")
        if any(not capability.has_complete_network_tuple() for capability in capabilities):
            return PolicyDecision(PolicyOutcome.DENY, "CAPABILITY_NETWORK_TUPLE_INCOMPLETE")
        if any(
            capability.action_kind in _HARD_DENIED_ACTIONS
            or capability.side_effect_class == "hard_denied"
            for capability in capabilities
        ):
            return PolicyDecision(PolicyOutcome.DENY, "HARD_DENY")
        if any(capability.action_kind not in _KNOWN_ACTIONS for capability in capabilities):
            return PolicyDecision(PolicyOutcome.DENY, "CAPABILITY_ACTION_KIND_UNKNOWN")
        if any(capability.action_kind in _ALWAYS_EXPLICIT_ACTIONS for capability in capabilities):
            return PolicyDecision(PolicyOutcome.REQUIRE_APPROVAL, "EXPLICIT_INTENT_REQUIRED")
        if all(
            capability.side_effect_class == "read_only"
            and capability.read_write_capability == "read"
            and capability.network_scheme is None
            for capability in capabilities
        ):
            return PolicyDecision(PolicyOutcome.ALLOW, "SAFE_PROJECT_READ")
        for rule in self._persistent_rules:
            if rule.contains(capabilities):
                return PolicyDecision(PolicyOutcome.ALLOW, "PERSISTENT_RULE", rule.rule_id)
        if self._session_full_access:
            return PolicyDecision(PolicyOutcome.ALLOW, "SESSION_FULL_ACCESS")
        return PolicyDecision(PolicyOutcome.REQUIRE_APPROVAL, "NO_MATCHING_RULE")


__all__ = ["PolicyDecision", "PolicyEngine", "PolicyOutcome"]
