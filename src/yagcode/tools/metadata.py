"""Immutable registration data for the closed governed-tool surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    action_kind: str
    read_only: bool
    side_effect_class: str
    max_total_attempts: int
    requires_sandbox: bool

    def __post_init__(self) -> None:
        if not self.action_kind:
            raise ValueError("TOOL_ACTION_KIND_INVALID")
        if not self.side_effect_class:
            raise ValueError("TOOL_SIDE_EFFECT_CLASS_INVALID")
        expected_attempts = 3 if self.read_only else 1
        if self.max_total_attempts != expected_attempts:
            raise ValueError("TOOL_RETRY_POLICY_INVALID")
        if self.read_only and self.requires_sandbox:
            raise ValueError("TOOL_READ_ONLY_SANDBOX_INVALID")


def default_tool_registry() -> Mapping[str, ToolMetadata]:
    readonly = ("list_directory", "read_text", "search_literal", "git_inspect")
    side_effecting = ("apply_patch", "run_command", "run_validation", "request_review")
    registry = {
        **{kind: ToolMetadata(kind, True, "read_only", 3, False) for kind in readonly},
        **{
            kind: ToolMetadata(kind, False, "side_effect", 1, kind.startswith("run_"))
            for kind in side_effecting
        },
    }
    return MappingProxyType(registry)
