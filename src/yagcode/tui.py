"""Small terminal workbench used by the user-facing ``yagcode`` command."""

from __future__ import annotations

import json

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from yagcode import __version__


@dataclass(frozen=True, slots=True)
class TuiState:
    cwd: Path
    plan_mode: bool = True
    model: str = "scripted-local"
    run_state: str = "idle"
    active_panel: str = "Changes"

    @property
    def project_name(self) -> str:
        return self.cwd.name or str(self.cwd)


def render_screen(state: TuiState) -> str:
    plan = "on" if state.plan_mode else "off"
    return "\n".join(
        (
            f"YagCode {__version__} | {state.project_name} | {state.run_state} | Plan {plan} | {state.model}",
            "Panels: Chat | Changes | Diff | Approvals | Memory | Audit",
            "Composer: describe a bug, paste logs, or type /help",
            "Changes: no accepted patch is staged in the real worktree.",
            "Commands: /plan on|off, /model <id>, /status, /changes, /memory, /audit, /demo, /quit",
        )
    )


def health_payload(*, cwd: Path | None = None) -> dict[str, object]:
    root = cwd or Path.cwd()
    return {
        "state": "ready",
        "product": "yagcode-cli",
        "version": __version__,
        "project": str(root.resolve()),
    }


def run_tui(
    *,
    cwd: Path | None = None,
    input_stream: TextIO,
    output_stream: TextIO,
) -> int:
    state = TuiState(cwd=(cwd or Path.cwd()).resolve())
    _write(output_stream, render_screen(state))
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("/"):
            _write(output_stream, f"queued message: {line}")
            continue
        command, _, argument = line.partition(" ")
        if command == "/quit":
            _write(output_stream, "bye")
            return 0
        if command == "/help":
            _write(output_stream, render_screen(state))
            continue
        if command == "/status":
            _write(output_stream, json.dumps(health_payload(cwd=state.cwd), sort_keys=True))
            continue
        if command == "/plan":
            state = _set_plan_mode(state, argument.strip())
            _write(output_stream, f"Plan mode: {'on' if state.plan_mode else 'off'}")
            continue
        if command == "/model":
            if state.run_state != "idle":
                _write(output_stream, "请先停止当前运行，再切换模型")
                continue
            state = replace(state, model=argument.strip() or state.model)
            _write(output_stream, f"Model: {state.model}")
            continue
        if command in {"/changes", "/diff"}:
            state = replace(state, active_panel="Changes")
            _write(output_stream, "Changes: no accepted patch is staged in the real worktree.")
            continue
        if command == "/memory":
            state = replace(state, active_panel="Memory")
            _write(output_stream, "Memory: project memory is available after a run is accepted.")
            continue
        if command == "/audit":
            state = replace(state, active_panel="Audit")
            _write(output_stream, "Audit: approvals and validation events are recorded locally.")
            continue
        if command == "/demo":
            _write(output_stream, "Demo: run `yagcode demo --workspace <dir> --json` for the full scripted flow.")
            continue
        _write(output_stream, f"Unknown command: {command}")
    return 0


def _set_plan_mode(state: TuiState, value: str) -> TuiState:
    if value == "off":
        return replace(state, plan_mode=False)
    if value == "on":
        return replace(state, plan_mode=True)
    return state


def _write(output_stream: TextIO, text: str) -> None:
    output_stream.write(text)
    output_stream.write("\n")
    output_stream.flush()


__all__ = ["TuiState", "health_payload", "render_screen", "run_tui"]
