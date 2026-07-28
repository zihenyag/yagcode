from __future__ import annotations

import io
from pathlib import Path

from yagcode.cli import main
from yagcode.sidecar_cli import main as sidecar_main


def test_tui_script_file_runs_without_desktop_or_system_node(tmp_path: Path) -> None:
    script = tmp_path / "script.yagcode"
    script.write_text("/status\n/plan off\n/demo\n/quit\n", encoding="utf-8")
    stdout = io.StringIO()

    exit_code = main(["tui", "--script", str(script)], output_stream=stdout, cwd=tmp_path)

    rendered = stdout.getvalue()
    assert exit_code == 0
    assert '"state": "ready"' in rendered
    assert "Plan mode: off" in rendered
    assert "yagcode demo --workspace" in rendered


def test_internal_sidecar_health_and_version_are_separate_from_user_tui(capsys) -> None:
    assert sidecar_main(["health"]) == 0
    health = capsys.readouterr().out
    assert '"product": "yagcode-sidecar"' in health
    assert '"state": "ready"' in health

    assert sidecar_main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"
