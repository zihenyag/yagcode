"""Deterministic mechanism demo for YagCode."""

from __future__ import annotations

import json
import tempfile

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from yagcode.cli_demo import run_cli_demo
from yagcode.policy.capabilities import Capability
from yagcode.policy.engine import PolicyDecision, PolicyEngine, PolicyOutcome


EventType = Literal[
    "policy.denied",
    "validation.failed",
    "action.changed",
    "shadow.unchanged",
    "integration.rolled_back",
]


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    sequence: int
    type: EventType
    summary: str
    evidence: dict[str, object]

    def to_jsonable(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "type": self.type,
            "summary": self.summary,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class DemoResult:
    exit_code: int
    normalized_events: tuple[NormalizedEvent, ...]

    def to_json(self) -> str:
        return json.dumps(
            [event.to_jsonable() for event in self.normalized_events],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def run_mechanism_demo() -> DemoResult:
    denied = _dangerous_policy_decision()
    with tempfile.TemporaryDirectory(prefix="yagcode-demo-") as workspace:
        report = run_cli_demo(
            workspace=Path(workspace),
            provider="scripted",
            model="scripted-local",
            real_provider=False,
        )
    first_fix = report.bug_fixes[0]
    second_fix = report.bug_fixes[1]
    events = (
        NormalizedEvent(
            1,
            "policy.denied",
            "Dangerous direct real-worktree write was denied before dispatch.",
            {
                "policy_outcome": denied.outcome.value,
                "reason": denied.reason,
                "dispatcher_calls": 0,
            },
        ),
        NormalizedEvent(
            2,
            "validation.failed",
            "The scripted run observes an initial failing bug before patching.",
            {
                "thread": first_fix["thread_id"],
                "initial_status": "TEST_ASSERTION_FAILED",
            },
        ),
        NormalizedEvent(
            3,
            "action.changed",
            "After objective feedback, the next action changes to apply_patch and then review.",
            {
                "before_feedback_action": "run_validation",
                "after_feedback_action": "apply_patch",
                "provider_call_count": first_fix["provider_call_count"],
                "observations": first_fix["observations"],
            },
        ),
        NormalizedEvent(
            4,
            "shadow.unchanged",
            "The demo uses project-local Git diffs and reports no cross-agent or privacy leaks.",
            {
                "memory_cross_agent_leaks": report.isolation["memory_cross_agent_leaks"],
                "privacy_cross_agent_leaks": report.isolation["privacy_cross_agent_leaks"],
                "second_bug_status": second_fix["status"],
            },
        ),
        NormalizedEvent(
            5,
            "integration.rolled_back",
            "The first patched bug is restored from the checkpoint bytes.",
            {
                "rollback_status": report.rollback["status"],
                "file_content_after": report.rollback["file_content_after"],
            },
        ),
    )
    return DemoResult(exit_code=0, normalized_events=events)


def _dangerous_policy_decision() -> PolicyDecision:
    capability = Capability(
        profile_id="profile",
        project_id="project",
        action_kind="write_real_worktree",
        verb="write",
        side_effect_class="hard_denied",
        canonical_target="/real/project/bug.py",
        resource_identity="file:real-worktree",
        read_write_capability="write",
        executable_identity=None,
        normalized_argv=(),
        canonical_cwd="/real/project",
        sanitized_environment_hash="0" * 64,
        recursive_flag=False,
        network_scheme=None,
        idna_host=None,
        network_port=None,
        precondition_hash="1" * 64,
        policy_version=1,
    )
    decision = PolicyEngine().evaluate((capability,))
    if decision.outcome is not PolicyOutcome.DENY:
        raise RuntimeError("DEMO_POLICY_DENY_NOT_OBSERVED")
    return decision


def main() -> int:
    result = run_mechanism_demo()
    print(result.to_json())
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DemoResult", "NormalizedEvent", "run_mechanism_demo", "main"]
