from __future__ import annotations

import json
import subprocess
import sys

from yagcode.demo import run_mechanism_demo


def test_mechanism_demo_replays_identically_offline() -> None:
    first = run_mechanism_demo()
    second = run_mechanism_demo()
    assert first.exit_code == second.exit_code == 0
    assert first.to_json() == second.to_json()
    assert [event.type for event in first.normalized_events] == [
        "policy.denied",
        "validation.failed",
        "action.changed",
        "shadow.unchanged",
        "integration.rolled_back",
    ]
    assert first.normalized_events[0].evidence["dispatcher_calls"] == 0
    assert first.normalized_events[2].evidence["after_feedback_action"] == "apply_patch"
    assert first.normalized_events[4].evidence["rollback_status"] == "RESTORED"


def test_mechanism_demo_cli_stdout_is_canonical() -> None:
    first = subprocess.run(
        [sys.executable, "-m", "yagcode.demo"],
        check=False,
        capture_output=True,
    )
    second = subprocess.run(
        [sys.executable, "-m", "yagcode.demo"],
        check=False,
        capture_output=True,
    )
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    assert first.stdout == second.stdout
    decoded = json.loads(first.stdout)
    assert [event["type"] for event in decoded] == [
        "policy.denied",
        "validation.failed",
        "action.changed",
        "shadow.unchanged",
        "integration.rolled_back",
    ]
