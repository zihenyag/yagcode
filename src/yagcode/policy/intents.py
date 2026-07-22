"""Canonical high-privilege intent bindings and renderer-safe request values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .capabilities import Capability


def _text(name: str, value: object) -> None:
    if type(value) is not str or not 1 <= len(value) <= 1024 or "\x00" in value:
        raise ValueError(f"INTENT_{name.upper()}_INVALID")


def _capability_set_hash(capabilities: tuple[Capability, ...]) -> str:
    ordered = sorted(capability.canonical_bytes() for capability in capabilities)
    framed = b"".join(len(item).to_bytes(8, "big") + item for item in ordered)
    return hashlib.sha256(framed).hexdigest()


@dataclass(frozen=True, slots=True)
class IntentBinding:
    profile_id: str
    run_id: str
    generation: int
    action_id: str
    payload_hash: str
    capabilities: tuple[Capability, ...]
    capability_hash: str
    resolved_target_identities: tuple[str, ...]
    policy_version: int
    precondition_hash: str | None

    @classmethod
    def from_capabilities(
        cls,
        *,
        profile_id: str,
        run_id: str,
        generation: int,
        action_id: str,
        payload_hash: str,
        capabilities: tuple[Capability, ...],
        resolved_target_identities: tuple[str, ...],
        policy_version: int,
        precondition_hash: str | None,
    ) -> IntentBinding:
        ordered = tuple(sorted(capabilities, key=lambda capability: capability.canonical_bytes()))
        return cls(
            profile_id=profile_id,
            run_id=run_id,
            generation=generation,
            action_id=action_id,
            payload_hash=payload_hash,
            capabilities=ordered,
            capability_hash=_capability_set_hash(ordered),
            resolved_target_identities=resolved_target_identities,
            policy_version=policy_version,
            precondition_hash=precondition_hash,
        )

    def __post_init__(self) -> None:
        for name in ("profile_id", "run_id", "action_id", "payload_hash", "capability_hash"):
            _text(name, getattr(self, name))
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("INTENT_GENERATION_INVALID")
        if type(self.capabilities) is not tuple or not self.capabilities or any(
            type(capability) is not Capability for capability in self.capabilities
        ):
            raise ValueError("INTENT_CAPABILITIES_INVALID")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("INTENT_CAPABILITIES_DUPLICATE")
        if self.capability_hash != _capability_set_hash(self.capabilities):
            raise ValueError("INTENT_CAPABILITY_HASH_INVALID")
        if type(self.resolved_target_identities) is not tuple:
            raise ValueError("INTENT_TARGET_IDENTITIES_INVALID")
        for identity in self.resolved_target_identities:
            _text("target_identity", identity)
        if type(self.policy_version) is not int or self.policy_version < 0:
            raise ValueError("INTENT_POLICY_VERSION_INVALID")
        if self.precondition_hash is not None:
            _text("precondition_hash", self.precondition_hash)

    def consistency_error(self) -> str | None:
        if any(capability.profile_id != self.profile_id for capability in self.capabilities):
            return "INTENT_CAPABILITY_OWNER_MISMATCH"
        if any(capability.policy_version != self.policy_version for capability in self.capabilities):
            return "INTENT_CAPABILITY_POLICY_MISMATCH"
        return None

    def is_valid(self) -> bool:
        try:
            self.__post_init__()
        except (AttributeError, OverflowError, TypeError, ValueError):
            return False
        return all(capability.is_valid() for capability in self.capabilities)

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "action_id": self.action_id,
                "capability_hash": self.capability_hash,
                "generation": self.generation,
                "payload_hash": self.payload_hash,
                "policy_version": self.policy_version,
                "precondition_hash": self.precondition_hash,
                "profile_id": self.profile_id,
                "resolved_target_identities": list(self.resolved_target_identities),
                "run_id": self.run_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class RendererIntentRequest:
    request_id: str
    kind: str
    binding_digest: str


__all__ = ["IntentBinding", "RendererIntentRequest"]
