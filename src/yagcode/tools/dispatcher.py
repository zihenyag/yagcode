"""One-shot, action-bound dispatcher. Denials have no journal/backend effects."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from yagcode.domain.actions import Action
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus

from .metadata import ToolMetadata, default_tool_registry


@dataclass(frozen=True, slots=True)
class ExecutionToken:
    value: str
    action_digest: str


@dataclass(frozen=True, slots=True)
class TokenDecision:
    allowed: bool
    reason_code: str


class ExecutionTokenStore(Protocol):
    def issue(self, action: Action) -> ExecutionToken: ...

    def consume(self, token: ExecutionToken | None, action: Action) -> TokenDecision: ...


class ToolBackend(Protocol):
    def execute(self, action: Action) -> ToolResult: ...


class ToolJournal(Protocol):
    def record_intent(self, action: Action, *, side_effecting: bool) -> None: ...

    def record_result(self, action: Action, result: ToolResult) -> None: ...


def _digest(action: Action) -> str:
    return hashlib.sha256(action.model_dump_json().encode("utf-8")).hexdigest()


def _result(
    action: Action,
    status: ToolStatus,
    reason: str,
    *,
    side: SideEffectState = SideEffectState.NONE,
    retryable: bool = False,
    category: str = "DISPATCH",
) -> ToolResult:
    return ToolResult(
        action_id=action.action_id,
        status=status,
        category=category,
        reason_code=reason,
        side_effect_state=side,
        retryable=retryable,
    )


class InMemoryExecutionTokenStore:
    """Deterministic one-shot token store used by tests and local dev adapters."""

    def __init__(self, *, events: list[str] | None = None) -> None:
        self._issued: dict[str, str] = {}
        self._consumed: set[str] = set()
        self._events = events

    def issue(self, action: Action) -> ExecutionToken:
        value = secrets.token_urlsafe(32)
        digest = _digest(action)
        self._issued[value] = digest
        return ExecutionToken(value, digest)

    def consume(self, token: ExecutionToken | None, action: Action) -> TokenDecision:
        if token is None:
            return TokenDecision(False, "EXECUTION_TOKEN_REQUIRED")
        if token.value in self._consumed:
            return TokenDecision(False, "EXECUTION_TOKEN_CONSUMED")
        action_digest = _digest(action)
        if self._issued.get(token.value) != action_digest or token.action_digest != action_digest:
            return TokenDecision(False, "EXECUTION_TOKEN_MISMATCH")
        self._consumed.add(token.value)
        if self._events is not None:
            self._events.append("token_consumed")
        return TokenDecision(True, "EXECUTION_TOKEN_CONSUMED")


class ToolDispatcher:
    def __init__(
        self,
        *,
        backends: Mapping[str, ToolBackend],
        journal: ToolJournal | None = None,
        registry: Mapping[str, ToolMetadata] | None = None,
        token_store: ExecutionTokenStore | None = None,
    ) -> None:
        self.backends = dict(backends)
        self.journal = journal
        self.registry = default_tool_registry() if registry is None else registry
        self._token_store = InMemoryExecutionTokenStore() if token_store is None else token_store

    def issue_token(self, action: Action) -> ExecutionToken:
        return self._token_store.issue(action)

    def execute(self, action: Action, token: ExecutionToken | None) -> ToolResult:
        backend = self.backends.get(action.kind)
        metadata = self.registry.get(action.kind)
        if backend is None or metadata is None:
            return _result(action, ToolStatus.DENIED, "TOOL_UNREGISTERED")
        decision = self._token_store.consume(token, action)
        if not decision.allowed:
            return _result(action, ToolStatus.DENIED, decision.reason_code)
        if self.journal is not None:
            self.journal.record_intent(action, side_effecting=not metadata.read_only)
        try:
            result = backend.execute(action)
        except Exception:
            result = _result(
                action,
                ToolStatus.UNKNOWN,
                "BACKEND_EXCEPTION",
                side=SideEffectState.UNKNOWN,
                category="TOOL",
            )
        if self.journal is not None:
            self.journal.record_result(action, result)
        return result
