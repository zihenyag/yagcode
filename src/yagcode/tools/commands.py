"""Registered-template command adapter; no direct shell or ambient environment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from yagcode.domain.actions import RunCommandAction
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus
from yagcode.sandbox.base import (
    ProcessRequest,
    SandboxAttestation,
    SandboxScope,
    attest_snapshot,
    attestation_is_current,
    capture_scope_snapshot,
    minimal_environment,
)


@dataclass(frozen=True, slots=True)
class CommandTemplate:
    template_id: str
    executable: str
    argv: tuple[str, ...]
    allowed_arguments: tuple[str, ...]
    timeout_ms: int

    def __post_init__(self) -> None:
        if not self.template_id or not Path(self.executable).is_absolute():
            raise ValueError("COMMAND_TEMPLATE_INVALID")
        if self.timeout_ms < 1_000 or self.timeout_ms > 600_000:
            raise ValueError("COMMAND_TEMPLATE_TIMEOUT_INVALID")
        if len(set(self.allowed_arguments)) != len(self.allowed_arguments):
            raise ValueError("COMMAND_TEMPLATE_ARGUMENTS_INVALID")

    def render(self, arguments: Mapping[str, str]) -> tuple[str, ...]:
        values = dict(arguments)
        if set(values) != set(self.allowed_arguments):
            raise ValueError("COMMAND_ARGUMENTS_INVALID")
        if any(type(key) is not str or type(value) is not str for key, value in values.items()):
            raise ValueError("COMMAND_ARGUMENTS_INVALID")
        try:
            return tuple(item.format(**values) for item in self.argv)
        except (KeyError, ValueError) as error:
            raise ValueError("COMMAND_ARGUMENTS_INVALID") from error


@dataclass(frozen=True, slots=True)
class CommandRequest:
    process: ProcessRequest
    cwd: Path
    environment: dict[str, str]
    timeout_ms: int


class CommandHandle(Protocol):
    started: bool
    reason: str


class CommandSandbox(Protocol):
    def start_command(
        self,
        request: CommandRequest,
        attestation: SandboxAttestation,
    ) -> CommandHandle: ...


class TemplateRegistry:
    def __init__(self, templates: tuple[CommandTemplate, ...]) -> None:
        self._templates = {template.template_id: template for template in templates}
        if len(self._templates) != len(templates):
            raise ValueError("COMMAND_TEMPLATE_DUPLICATE")

    def require(self, template_id: str) -> CommandTemplate:
        try:
            return self._templates[template_id]
        except KeyError as error:
            raise ValueError("COMMAND_TEMPLATE_UNREGISTERED") from error


class CommandAdapter:
    def __init__(self, *, sandbox: CommandSandbox, templates: TemplateRegistry, shadow_root: Path) -> None:
        self.sandbox = sandbox
        self.templates = templates
        self.shadow_root = shadow_root.resolve(strict=True)

    def _denied(self, action: RunCommandAction, reason: str) -> ToolResult:
        return ToolResult(
            action_id=action.action_id,
            status=ToolStatus.DENIED,
            category="COMMAND",
            reason_code=reason,
            side_effect_state=SideEffectState.NONE,
            retryable=False,
        )

    def _resolve_cwd(self, action: RunCommandAction) -> Path:
        if action.payload.cwd_root_id != "shadow":
            raise ValueError("COMMAND_CWD_ROOT_UNSUPPORTED")
        relative = Path(action.payload.cwd_relative_path)
        if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
            raise ValueError("COMMAND_CWD_UNTRUSTED")
        cwd = (self.shadow_root / relative).resolve(strict=True)
        if not cwd.is_relative_to(self.shadow_root) or not cwd.is_dir():
            raise ValueError("COMMAND_CWD_UNTRUSTED")
        return cwd

    def run_action(self, action: RunCommandAction, attestation: object) -> ToolResult:
        if not isinstance(attestation, SandboxAttestation) or not attestation_is_current(attestation):
            return self._denied(action, "SANDBOX_ATTESTATION_REQUIRED")
        try:
            template = self.templates.require(action.payload.template_id)
        except ValueError:
            return self._denied(action, "COMMAND_TEMPLATE_UNREGISTERED")
        try:
            cwd = self._resolve_cwd(action)
        except (OSError, ValueError) as error:
            reason = str(error) if str(error) else "COMMAND_CWD_UNTRUSTED"
            if reason not in {"COMMAND_CWD_ROOT_UNSUPPORTED", "COMMAND_CWD_UNTRUSTED"}:
                reason = "COMMAND_CWD_UNTRUSTED"
            return self._denied(action, reason)
        try:
            argv = template.render(action.payload.arguments)
            process = ProcessRequest(template.executable, argv)
        except ValueError:
            return self._denied(action, "COMMAND_ARGUMENTS_INVALID")
        request = CommandRequest(
            process=process,
            cwd=cwd,
            environment=minimal_environment(),
            timeout_ms=template.timeout_ms,
        )
        handle = self.sandbox.start_command(request, attestation)
        status = ToolStatus.SUCCEEDED if handle.started else ToolStatus.FAILED
        side_effect = SideEffectState.UNKNOWN if handle.started else SideEffectState.NONE
        return ToolResult(
            action_id=action.action_id,
            status=status,
            category="COMMAND",
            reason_code=handle.reason,
            side_effect_state=side_effect,
            retryable=False,
        )


def attest_for_tests(shadow: Path, temporary: Path, protected: Path) -> SandboxAttestation:
    return attest_snapshot(capture_scope_snapshot(SandboxScope(shadow, temporary, protected)), backend="test")


__all__ = [
    "CommandAdapter",
    "CommandHandle",
    "CommandRequest",
    "CommandSandbox",
    "CommandTemplate",
    "TemplateRegistry",
    "attest_for_tests",
]
