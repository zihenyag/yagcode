"""Immutable, canonical capability values used by deterministic policy decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from typing import Literal


ReadWriteCapability = Literal["read", "write", "execute"]


def _required_text(name: str, value: object, *, maximum: int = 1024) -> None:
    if type(value) is not str or not 1 <= len(value) <= maximum or "\x00" in value:
        raise ValueError(f"CAPABILITY_{name.upper()}_INVALID")


def _optional_text(name: str, value: object, *, maximum: int = 4096) -> None:
    if value is not None:
        _required_text(name, value, maximum=maximum)


@dataclass(frozen=True, slots=True)
class Capability:
    profile_id: str
    project_id: str
    action_kind: str
    verb: str
    side_effect_class: str
    canonical_target: str | None
    resource_identity: str | None
    read_write_capability: ReadWriteCapability
    executable_identity: str | None
    normalized_argv: tuple[str, ...]
    canonical_cwd: str | None
    sanitized_environment_hash: str
    recursive_flag: bool
    network_scheme: str | None
    idna_host: str | None
    network_port: int | None
    precondition_hash: str | None
    policy_version: int

    def __post_init__(self) -> None:
        for name in (
            "profile_id",
            "project_id",
            "action_kind",
            "verb",
            "side_effect_class",
            "sanitized_environment_hash",
        ):
            _required_text(name, getattr(self, name), maximum=128)
        for name in (
            "canonical_target",
            "resource_identity",
            "executable_identity",
            "canonical_cwd",
            "network_scheme",
            "idna_host",
            "precondition_hash",
        ):
            _optional_text(name, getattr(self, name))
        if type(self.read_write_capability) is not str or self.read_write_capability not in {
            "read",
            "write",
            "execute",
        }:
            raise ValueError("CAPABILITY_READ_WRITE_CAPABILITY_INVALID")
        if type(self.normalized_argv) is not tuple or len(self.normalized_argv) > 256:
            raise ValueError("CAPABILITY_NORMALIZED_ARGV_INVALID")
        for argument in self.normalized_argv:
            _required_text("normalized_argv", argument, maximum=4096)
        if type(self.recursive_flag) is not bool:
            raise ValueError("CAPABILITY_RECURSIVE_FLAG_INVALID")
        if self.network_port is not None and (
            type(self.network_port) is not int or not 1 <= self.network_port <= 65535
        ):
            raise ValueError("CAPABILITY_NETWORK_PORT_INVALID")
        if type(self.policy_version) is not int or self.policy_version < 0:
            raise ValueError("CAPABILITY_POLICY_VERSION_INVALID")

    def has_complete_network_tuple(self) -> bool:
        network_fields = (self.network_scheme, self.idna_host, self.network_port)
        return all(value is None for value in network_fields) or all(
            value is not None for value in network_fields
        )

    def is_valid(self) -> bool:
        try:
            self.__post_init__()
            self.canonical_bytes()
        except (AttributeError, OverflowError, TypeError, ValueError):
            return False
        return True

    def canonical_bytes(self) -> bytes:
        payload = {field.name: getattr(self, field.name) for field in fields(self)}
        payload["normalized_argv"] = list(self.normalized_argv)
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def canonical_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class PersistentRule:
    rule_id: str
    capabilities: tuple[Capability, ...]

    def __post_init__(self) -> None:
        _required_text("rule_id", self.rule_id, maximum=128)
        if type(self.capabilities) is not tuple or not self.capabilities:
            raise ValueError("PERSISTENT_RULE_CAPABILITIES_INVALID")
        if any(type(capability) is not Capability for capability in self.capabilities):
            raise ValueError("PERSISTENT_RULE_CAPABILITIES_INVALID")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("PERSISTENT_RULE_CAPABILITIES_DUPLICATE")

    def contains(self, requested: tuple[Capability, ...]) -> bool:
        return set(requested) <= set(self.capabilities)


__all__ = ["Capability", "PersistentRule", "ReadWriteCapability"]
