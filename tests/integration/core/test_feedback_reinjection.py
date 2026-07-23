"""feedback codes affect the next deterministic Provider action."""

from __future__ import annotations

import importlib

import pytest

from yagcode.core.context import SnapshotContextBuilder
from yagcode.core.loop import AgentLoop
from yagcode.core.ports import PolicyDecision, StepSnapshot
from yagcode.domain.action_parser import ActionParser
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus
from yagcode.providers import ScriptedProvider


def test_owned_branching_script_oracle() -> None:
    branches = {(): "run_validation", ("TEST_ASSERTION_FAILED",): "apply_patch"}
    assert branches[()] != branches[("TEST_ASSERTION_FAILED",)]


def load_feedback_contract():
    try:
        return importlib.import_module("yagcode.core.feedback")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"FEEDBACK_CONTRACT_MISSING: {error.name}")
        raise


def test_failure_code_changes_the_next_scripted_action() -> None:
    feedback = load_feedback_contract()
    store = _FeedbackStore()
    provider = ScriptedProvider(
        "scripted",
        {
            (): _run_validation_action(),
            ("TEST_ASSERTION_FAILED",): _apply_patch_action(),
        },
    )
    dispatcher = _Dispatcher()
    loop = AgentLoop(
        run_id="run-a",
        store=store,
        context_builder=SnapshotContextBuilder(),
        provider=provider,
        parser=ActionParser(),
        policy=_Policy(),
        dispatcher=dispatcher,
        feedback=feedback.FeedbackNormalizer(),
    )

    first = loop.step()
    second = loop.step()

    assert first.reason_code == "STEP_DISPATCHED"
    assert second.reason_code == "STEP_DISPATCHED"
    assert dispatcher.actions == ("run_validation", "apply_patch")
    assert store.feedback_codes == ("TEST_ASSERTION_FAILED", "PATCH_APPLIED")


def _run_validation_action() -> dict[str, object]:
    return {
        "kind": "run_validation",
        "action_id": "validate-1",
        "run_id": "run-a",
        "generation": 0,
        "reason_summary": "run test",
        "payload": {"validator_id": "unit", "target_paths": ["tests/test_x.py"]},
    }


def _apply_patch_action() -> dict[str, object]:
    return {
        "kind": "apply_patch",
        "action_id": "patch-1",
        "run_id": "run-a",
        "generation": 0,
        "reason_summary": "fix failed test",
        "payload": {
            "root_id": "project",
            "relative_path": "src/x.py",
            "base_sha256": "0" * 64,
            "hunks": [
                {
                    "start_line": 1,
                    "delete_line_count": 0,
                    "expected_text": "",
                    "replacement_text": "pass\n",
                }
            ],
        },
    }


class _FeedbackStore:
    def __init__(self) -> None:
        self.feedback_codes: tuple[str, ...] = ()

    def load_step_snapshot(self, run_id: str) -> StepSnapshot:
        return StepSnapshot(
            run_id=run_id,
            generation=0,
            provider="scripted",
            model="script",
            context_items=(),
            feedback_codes=self.feedback_codes,
            budget_version=1,
        )

    def record_stale(self, snapshot, provider_result):
        return ("stale",)

    def finish_provider_failure(self, snapshot, failure):
        return ("provider_failure",)

    def finish_parse_failure(self, snapshot, failure):
        return ("parse_failure",)

    def finish_policy_wait(self, snapshot, action, decision):
        return ("policy_wait",)

    def finish_step(self, snapshot, action, result, feedback):
        self.feedback_codes = (*self.feedback_codes, feedback.reason_code)
        return (action.kind, feedback.reason_code)


class _Policy:
    def evaluate(self, action, snapshot) -> PolicyDecision:
        return PolicyDecision(True, "ALLOW")


class _Dispatcher:
    def __init__(self) -> None:
        self.actions: tuple[str, ...] = ()

    def issue_token(self, action):
        return object()

    def execute(self, action, token) -> ToolResult:
        self.actions = (*self.actions, action.kind)
        failed_validation = action.kind == "run_validation"
        return ToolResult(
            action_id=action.action_id,
            status=ToolStatus.FAILED if failed_validation else ToolStatus.SUCCEEDED,
            category="VALIDATION" if failed_validation else "PATCH",
            reason_code="TEST_ASSERTION_FAILED" if failed_validation else "PATCH_APPLIED",
            side_effect_state=SideEffectState.NONE if failed_validation else SideEffectState.APPLIED,
            retryable=False,
        )
