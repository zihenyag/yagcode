from __future__ import annotations

import io
import json
from pathlib import Path

from yagcode.cli import main
from yagcode.tui import TuiState, health_payload, render_screen


def test_default_yagcode_enters_project_terminal_workbench(tmp_path: Path) -> None:
    stdin = io.StringIO("/status\n/changes\n/quit\n")
    stdout = io.StringIO()

    exit_code = main([], input_stream=stdin, output_stream=stdout, cwd=tmp_path)

    rendered = stdout.getvalue()
    assert exit_code == 0
    assert "YagCode 0.1.0" in rendered
    assert tmp_path.name in rendered
    assert "Plan on" in rendered
    assert "Panels: Chat | Changes | Diff | Approvals | Memory | Audit" in rendered
    assert "Changes: no accepted patch is staged in the real worktree." in rendered
    assert '"state": "ready"' in rendered


def test_tui_supports_plan_model_memory_and_audit_controls(tmp_path: Path) -> None:
    stdin = io.StringIO("/plan off\n/model qwen-plus\n/memory\n/audit\n/quit\n")
    stdout = io.StringIO()

    assert main([], input_stream=stdin, output_stream=stdout, cwd=tmp_path) == 0

    rendered = stdout.getvalue()
    assert "Plan mode: off" in rendered
    assert "Model: qwen-plus" in rendered
    assert "Memory: project memory is available after a run is accepted." in rendered
    assert "Audit: approvals and validation events are recorded locally." in rendered


def test_health_and_version_subcommands_are_scriptable(tmp_path: Path, capsys) -> None:
    assert health_payload(cwd=tmp_path)["project"] == str(tmp_path.resolve())
    assert "Plan on" in render_screen(TuiState(cwd=tmp_path))

    stdout = io.StringIO()
    assert main(["health"], output_stream=stdout, cwd=tmp_path) == 0
    health = json.loads(stdout.getvalue())
    assert health["state"] == "ready"
    assert health["product"] == "yagcode-cli"
    assert health["version"] == "0.1.0"

    stdout = io.StringIO()
    assert main(["version"], output_stream=stdout, cwd=tmp_path) == 0
    assert stdout.getvalue().strip() == "0.1.0"
