"""deterministic loop golden trace tests with runtime production loading."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from yagcode.domain.action_parser import ActionParser
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus
from yagcode.providers import ProviderResult


TRACE_PATH = Path("tests/fixtures/traces/basic_loop.json")


def test_owned_trace_normalizer_fixture_and_oracle() -> None:
    trace = _load_trace()
    events = _normalize_test_trace(trace)
    assert events == tuple(trace["expected_events"])
    mutated = copy.deepcopy(trace)
    mutated["expected_events"][3] = "policy:DENY"
    assert _normalize_test_trace(mutated) != tuple(mutated["expected_events"])


def load_loop_contract():
    try:
        return (
            importlib.import_module("yagcode.core.loop"),
            importlib.import_module("yagcode.core.context"),
            importlib.import_module("yagcode.core.ports"),
        )
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"CORE_LOOP_CONTRACT_MISSING: {error.name}")
        raise


def test_same_script_produces_same_normalized_trace() -> None:
    loop_mod, context_mod, ports = load_loop_contract()
    trace = _load_trace()

    first = _loop_from_trace(loop_mod, context_mod, ports, trace).step()
    second = _loop_from_trace(loop_mod, context_mod, ports, trace).step()

    assert first.normalized_events == second.normalized_events
    assert first.normalized_events == tuple(trace["expected_events"])
    assert first.provider_calls == first.decision_count == 1
    assert first.reason_code == "STEP_DISPATCHED"


def test_parse_failure_records_feedback_without_policy_or_dispatch() -> None:
    loop_mod, context_mod, ports = load_loop_contract()
    trace = _load_trace()
    trace["provider_candidate"] = ["not", "an", "action"]
    harness = _loop_from_trace(loop_mod, context_mod, ports, trace)

    result = harness.step()

    assert result.reason_code == "ACTION_CANDIDATE_INVALID"
    assert harness.policy.calls == 0
    assert harness.dispatcher.calls == 0
    assert result.normalized_events[-1] == "parse_failure:ACTION_CANDIDATE_INVALID"


def _load_trace() -> dict[str, Any]:
    raw = json.loads(TRACE_PATH.read_text())
    assert type(raw) is dict
    return raw


def _normalize_test_trace(trace: dict[str, Any]) -> tuple[str, ...]:
    candidate = trace["provider_candidate"]
    kind = candidate["kind"] if type(candidate) is dict else "invalid"
    return (
        f"context:generation={trace['snapshot']['generation']}",
        f"provider:{trace['snapshot']['provider']}:{trace['snapshot']['model']}:generation={trace['snapshot']['generation']}",
        f"parse:{kind}",
        "policy:ALLOW",
        f"dispatch:{kind}:SUCCEEDED",
        "feedback:TOOL_SUCCEEDED",
    )


def _loop_from_trace(loop_mod, context_mod, ports, trace: dict[str, Any]):
    snapshot = _snapshot_from_trace(ports, context_mod, trace)
    store = _TraceStore(snapshot)
    provider = _Provider(trace["provider_candidate"], snapshot.provider, snapshot.model, snapshot.generation)
    policy = _Policy(ports)
    dispatcher = _Dispatcher()
    feedback = _Feedback(ports)
    harness = loop_mod.AgentLoop(
        run_id=snapshot.run_id,
        store=store,
        context_builder=context_mod.SnapshotContextBuilder(),
        provider=provider,
        parser=ActionParser(),
        policy=policy,
        dispatcher=dispatcher,
        feedback=feedback,
    )
    harness.policy = policy
    harness.dispatcher = dispatcher
    return harness


def _snapshot_from_trace(ports, context_mod, trace: dict[str, Any]):
    items = tuple(context_mod.ContextItem(**item) for item in trace["snapshot"]["context_items"])
    return ports.StepSnapshot(
        run_id=trace["snapshot"]["run_id"],
        generation=trace["snapshot"]["generation"],
        provider=trace["snapshot"]["provider"],
        model=trace["snapshot"]["model"],
        context_items=items,
        feedback_codes=tuple(trace["snapshot"]["feedback_codes"]),
        budget_version=trace["snapshot"]["budget_version"],
    )


class _Provider:
    def __init__(self, candidate: object, provider: str, model: str, generation: int) -> None:
        self._candidate = candidate
        self._provider = provider
        self._model = model
        self._generation = generation
        self.calls = 0

    def complete_once(self, context):
        self.calls += 1
        return ProviderResult.from_candidate(
            self._provider,
            self._model,
            self._generation,
            self._candidate,
        )


class _Policy:
    def __init__(self, ports) -> None:
        self._ports = ports
        self.calls = 0

    def evaluate(self, action, snapshot):
        self.calls += 1
        return self._ports.PolicyDecision(True, "ALLOW")


class _Dispatcher:
    def __init__(self) -> None:
        self.calls = 0

    def issue_token(self, action):
        return object()

    def execute(self, action, token) -> ToolResult:
        self.calls += 1
        return ToolResult(
            action_id=action.action_id,
            status=ToolStatus.SUCCEEDED,
            category="TOOL",
            reason_code="SUCCEEDED",
            side_effect_state=SideEffectState.NONE,
            retryable=False,
        )


class _Feedback:
    def __init__(self, ports) -> None:
        self._ports = ports

    def normalize(self, action, result):
        return self._ports.FeedbackRecord("TOOL_SUCCEEDED")


class _TraceStore:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.events: list[str] = []

    def load_step_snapshot(self, run_id: str):
        assert run_id == self.snapshot.run_id
        return self.snapshot

    def record_stale(self, snapshot, provider_result) -> tuple[str, ...]:
        self.events.append("stale:STALE_GENERATION")
        return tuple(self.events)

    def finish_parse_failure(self, snapshot, failure) -> tuple[str, ...]:
        self.events.append(f"parse_failure:{failure.reason_code}")
        return tuple(self.events)

    def finish_policy_wait(self, snapshot, action, decision) -> tuple[str, ...]:
        self.events.append(f"policy:{decision.reason_code}")
        return tuple(self.events)

    def finish_step(self, snapshot, action, result, feedback) -> tuple[str, ...]:
        self.events.extend(
            (
                f"context:generation={snapshot.generation}",
                f"provider:{snapshot.provider}:{snapshot.model}:generation={snapshot.generation}",
                f"parse:{action.kind}",
                "policy:ALLOW",
                f"dispatch:{action.kind}:{result.status.value}",
                f"feedback:{feedback.reason_code}",
            )
        )
        return tuple(self.events)
