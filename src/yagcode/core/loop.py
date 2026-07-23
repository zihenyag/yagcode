"""Self-implemented context-to-action loop for one deterministic step."""

from __future__ import annotations

from yagcode.domain.action_parser import ActionParseFailure, ActionParseSuccess, ActionParser
from yagcode.providers import ProviderContext, ProviderFailure

from .ports import (
    ContextBuilderPort,
    DispatcherPort,
    FeedbackPort,
    PolicyPort,
    ProviderPort,
    StepResult,
    StepStorePort,
)


class AgentLoop:
    """Run one context -> Provider -> parse -> policy -> dispatch -> feedback step."""

    def __init__(
        self,
        *,
        run_id: str,
        store: StepStorePort,
        context_builder: ContextBuilderPort,
        provider: ProviderPort,
        parser: ActionParser,
        policy: PolicyPort,
        dispatcher: DispatcherPort,
        feedback: FeedbackPort,
    ) -> None:
        self.run_id = run_id
        self.store = store
        self.context_builder = context_builder
        self.provider = provider
        self.parser = parser
        self.policy = policy
        self.dispatcher = dispatcher
        self.feedback = feedback

    def step(self) -> StepResult:
        snapshot = self.store.load_step_snapshot(self.run_id)
        active_context = self.context_builder.build(snapshot)
        provider_result = self.provider.complete_once(
            ProviderContext(
                active_context.run_id,
                active_context.generation,
                snapshot.provider,
                snapshot.model,
                active_context.feedback_codes,
            )
        )
        provider_calls = 1
        if provider_result.generation != snapshot.generation:
            events = self.store.record_stale(snapshot, provider_result)
            return StepResult(
                snapshot.run_id,
                snapshot.generation,
                "STALE",
                "STALE_GENERATION",
                events,
                provider_calls,
                0,
            )
        if isinstance(provider_result, ProviderFailure):
            events = self.store.finish_provider_failure(snapshot, provider_result)
            return StepResult(
                snapshot.run_id,
                snapshot.generation,
                "PROVIDER_FAILED",
                provider_result.error_code,
                events,
                provider_calls,
                0,
            )

        parsed = self.parser.parse(provider_result.action_candidate)
        if isinstance(parsed, ActionParseFailure):
            events = self.store.finish_parse_failure(snapshot, parsed)
            return StepResult(
                snapshot.run_id,
                snapshot.generation,
                "PARSE_FAILED",
                parsed.reason_code,
                events,
                provider_calls,
                0,
            )
        if not isinstance(parsed, ActionParseSuccess):
            raise RuntimeError("ACTION_PARSE_RESULT_INVALID")

        action = parsed.action
        decision = self.policy.evaluate(action, snapshot)
        if not decision.allowed:
            events = self.store.finish_policy_wait(snapshot, action, decision)
            return StepResult(
                snapshot.run_id,
                snapshot.generation,
                "WAITING_POLICY",
                decision.reason_code,
                events,
                provider_calls,
                1,
            )

        token = self.dispatcher.issue_token(action)
        tool_result = self.dispatcher.execute(action, token)
        feedback = self.feedback.normalize(action, tool_result)
        events = self.store.finish_step(snapshot, action, tool_result, feedback)
        return StepResult(
            snapshot.run_id,
            snapshot.generation,
            "DISPATCHED",
            "STEP_DISPATCHED",
            events,
            provider_calls,
            1,
        )


__all__ = ["AgentLoop"]
