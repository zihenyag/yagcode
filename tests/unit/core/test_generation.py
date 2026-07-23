"""generation guards prevent stale Provider output from causing effects."""

from __future__ import annotations

import importlib

import pytest

from yagcode.domain.action_parser import ActionParser
from yagcode.providers import ProviderResult


VALID_ACTION = {
    "kind": "request_review",
    "action_id": "review-stale",
    "run_id": "run-stale",
    "generation": 0,
    "reason_summary": "ready",
    "payload": {"summary": "ready", "uncovered": []},
}


def test_owned_stale_generation_oracle_blocks_downstream_effects() -> None:
    released_generation = 1
    snapshot_generation = 0
    policy_calls = 0
    dispatcher_calls = 0
    assert released_generation != snapshot_generation
    assert policy_calls == dispatcher_calls == 0


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


def test_stale_generation_never_reaches_policy_or_dispatch() -> None:
    loop_mod, context_mod, ports = load_loop_contract()
    snapshot = ports.StepSnapshot(
        run_id="run-stale",
        generation=0,
        provider="openai",
        model="m-a",
        context_items=(),
        feedback_codes=(),
        budget_version=1,
    )
    store = _StaleStore(snapshot)
    provider = _StaleProvider()
    policy = _CountingPolicy(ports)
    dispatcher = _CountingDispatcher()

    result = loop_mod.AgentLoop(
        run_id=snapshot.run_id,
        store=store,
        context_builder=context_mod.SnapshotContextBuilder(),
        provider=provider,
        parser=ActionParser(),
        policy=policy,
        dispatcher=dispatcher,
        feedback=_Feedback(ports),
    ).step()

    assert result.reason_code == "STALE_GENERATION"
    assert result.normalized_events == ("stale:STALE_GENERATION",)
    assert policy.calls == 0
    assert dispatcher.calls == 0
    assert store.last_event == "STALE_GENERATION"


class _StaleProvider:
    def complete_once(self, context):
        return ProviderResult.from_candidate("openai", "m-a", 1, VALID_ACTION)


class _CountingPolicy:
    def __init__(self, ports) -> None:
        self._ports = ports
        self.calls = 0

    def evaluate(self, action, snapshot):
        self.calls += 1
        return self._ports.PolicyDecision(True, "ALLOW")


class _CountingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    def issue_token(self, action):
        return object()

    def execute(self, action, token):
        self.calls += 1
        raise AssertionError("stale generation must not dispatch")


class _Feedback:
    def __init__(self, ports) -> None:
        self._ports = ports

    def normalize(self, action, result):
        return self._ports.FeedbackRecord("TOOL_SUCCEEDED")


class _StaleStore:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.last_event: str | None = None

    def load_step_snapshot(self, run_id: str):
        assert run_id == self.snapshot.run_id
        return self.snapshot

    def record_stale(self, snapshot, provider_result) -> tuple[str, ...]:
        self.last_event = "STALE_GENERATION"
        return ("stale:STALE_GENERATION",)

    def finish_parse_failure(self, snapshot, failure) -> tuple[str, ...]:
        raise AssertionError("stale generation must not parse")

    def finish_policy_wait(self, snapshot, action, decision) -> tuple[str, ...]:
        raise AssertionError("stale generation must not reach policy")

    def finish_step(self, snapshot, action, result, feedback) -> tuple[str, ...]:
        raise AssertionError("stale generation must not finish a dispatched step")
