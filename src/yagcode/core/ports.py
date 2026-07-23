"""Ports for the self-implemented loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from yagcode.domain.action_parser import ActionParseFailure
from yagcode.domain.actions import Action
from yagcode.domain.results import ToolResult
from yagcode.providers import ProviderContext, ProviderFailure, ProviderResult

from .context import ActiveContext, ContextItem


@dataclass(frozen=True, slots=True)
class StepSnapshot:
    run_id: str
    generation: int
    provider: str
    model: str
    context_items: tuple[ContextItem, ...]
    feedback_codes: tuple[str, ...]
    budget_version: int


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_code: str


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    reason_code: str


@dataclass(frozen=True, slots=True)
class StepResult:
    run_id: str
    generation: int
    status: str
    reason_code: str
    normalized_events: tuple[str, ...]
    provider_calls: int
    decision_count: int


class ContextBuilderPort(Protocol):
    def build(self, snapshot: StepSnapshot) -> ActiveContext: ...


class StepStorePort(Protocol):
    def load_step_snapshot(self, run_id: str) -> StepSnapshot: ...

    def record_stale(
        self,
        snapshot: StepSnapshot,
        provider_result: ProviderResult | ProviderFailure,
    ) -> tuple[str, ...]: ...

    def finish_provider_failure(
        self,
        snapshot: StepSnapshot,
        failure: ProviderFailure,
    ) -> tuple[str, ...]: ...

    def finish_parse_failure(
        self,
        snapshot: StepSnapshot,
        failure: ActionParseFailure,
    ) -> tuple[str, ...]: ...

    def finish_policy_wait(
        self,
        snapshot: StepSnapshot,
        action: Action,
        decision: PolicyDecision,
    ) -> tuple[str, ...]: ...

    def finish_step(
        self,
        snapshot: StepSnapshot,
        action: Action,
        result: ToolResult,
        feedback: FeedbackRecord,
    ) -> tuple[str, ...]: ...


class ProviderPort(Protocol):
    def complete_once(self, context: ProviderContext) -> ProviderResult | ProviderFailure: ...


class PolicyPort(Protocol):
    def evaluate(self, action: Action, snapshot: StepSnapshot) -> PolicyDecision: ...


class DispatcherPort(Protocol):
    def issue_token(self, action: Action) -> object: ...

    def execute(self, action: Action, token: object) -> ToolResult: ...


class FeedbackPort(Protocol):
    def normalize(self, action: Action, result: ToolResult) -> FeedbackRecord: ...


__all__ = [
    "ContextBuilderPort",
    "DispatcherPort",
    "FeedbackPort",
    "FeedbackRecord",
    "PolicyDecision",
    "PolicyPort",
    "ProviderPort",
    "StepResult",
    "StepSnapshot",
    "StepStorePort",
]
