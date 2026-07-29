from __future__ import annotations

import json
from pathlib import Path

from yagcode.cli import main
from yagcode.cli_demo import run_cli_demo
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus


def test_cli_demo_runs_two_agents_ten_projects_fifty_threads_three_bug_fixes_and_rollback(
    tmp_path: Path,
) -> None:
    report = run_cli_demo(
        workspace=tmp_path / "cli-demo",
        provider="scripted",
        model="scripted-local",
        real_provider=False,
    )
    public = report.to_public_dict()
    rendered = json.dumps(public, ensure_ascii=False, sort_keys=True)

    assert public["agents"]["count"] == 2
    assert public["projects"]["count"] == 10
    assert public["threads"]["count"] == 50
    assert public["threads"]["per_agent"] == {"agent-alpha": 25, "agent-beta": 25}

    assert public["isolation"]["memory_cross_agent_leaks"] == 0
    assert public["isolation"]["privacy_cross_agent_leaks"] == 0
    assert public["isolation"]["project_thread_conflicts"] == 0

    assert [item["status"] for item in public["bug_fixes"]] == [
        "ROLLED_BACK",
        "PATCHED",
        "PATCHED",
    ]
    assert all(item["provider_call_count"] >= 3 for item in public["bug_fixes"])
    assert all(item["diff"]["files_changed"] == 1 for item in public["bug_fixes"])
    assert all(item["diff"]["additions"] >= 1 for item in public["bug_fixes"])
    assert all(item["diff"]["deletions"] >= 1 for item in public["bug_fixes"])
    assert public["rollback"]["status"] == "RESTORED"
    assert public["rollback"]["file_content_after"] == "def answer():\n    return 1\n"

    assert public["privacy"]["preview_count"] >= 2
    assert public["privacy"]["permanent_grants"] >= 2
    assert public["privacy"]["redactions"] >= 3
    assert "".join(("138", "0013", "8000")) not in rendered
    assert "".join(("110101", "19900307", "0011")) not in rendered
    assert "-".join(("private", "token", "alpha")) not in rendered


def test_cli_demo_json_command_outputs_public_report_without_privacy_leaks(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "demo",
            "--workspace",
            str(tmp_path / "cli-demo"),
            "--provider",
            "scripted",
            "--model",
            "scripted-local",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)

    assert exit_code == 0
    assert report["agents"]["count"] == 2
    assert report["projects"]["count"] == 10
    assert report["threads"]["count"] == 50
    assert report["bug_fixes"][1]["status"] == "PATCHED"
    assert "-".join(("private", "token", "alpha")) not in rendered


def test_cli_demo_falls_back_when_git_executable_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("yagcode.cli_demo._git_available", lambda: False)

    report = run_cli_demo(
        workspace=tmp_path / "cli-demo",
        provider="scripted",
        model="scripted-local",
        real_provider=False,
    )
    public = report.to_public_dict()

    assert [item["status"] for item in public["bug_fixes"]] == [
        "ROLLED_BACK",
        "PATCHED",
        "PATCHED",
    ]
    assert public["rollback"]["status"] == "RESTORED"
    assert all(item["diff"]["files_changed"] == 1 for item in public["bug_fixes"])
    assert all(item["diff"]["files"][0]["path"] == "bug.py" for item in public["bug_fixes"])


def test_cli_demo_falls_back_when_patch_resolver_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    def deny_patch(action, *, roots):
        return ToolResult(
            action_id=action.action_id,
            status=ToolStatus.DENIED,
            category="UNTRUSTED_TARGET",
            reason_code="TARGET_UNSAFE",
            side_effect_state=SideEffectState.NONE,
            retryable=False,
        )

    monkeypatch.setattr("yagcode.cli_demo._git_available", lambda: False)
    monkeypatch.setattr("yagcode.cli_demo._patch_resolver_fallback_allowed", lambda: True)
    monkeypatch.setattr("yagcode.cli_demo.apply_action", deny_patch)

    report = run_cli_demo(
        workspace=tmp_path / "cli-demo",
        provider="scripted",
        model="scripted-local",
        real_provider=False,
    )
    public = report.to_public_dict()

    assert [item["status"] for item in public["bug_fixes"]] == [
        "ROLLED_BACK",
        "PATCHED",
        "PATCHED",
    ]
    assert all("apply_patch:PATCH_APPLIED:APPLIED" in item["observations"] for item in public["bug_fixes"])
