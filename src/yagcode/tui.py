"""Small terminal workbench used by the user-facing ``yagcode`` command."""

from __future__ import annotations

import json
import getpass
import shlex

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, TextIO

from yagcode import __version__
from yagcode.api.dependencies import ApiDomainError, Services
from yagcode.git.working_tree import WorktreeDiffFile


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
            (
                "Commands: /provider add|status, /thread <title>, /run, /stop, "
                "/changes, /diff, /accept, /reject, /rollback <checkpoint>, "
                "/plan on|off, /model <id>, /memory, /audit, /demo, /quit"
            ),
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
    services: Services | None = None,
    secret_prompt: Callable[[str], str] | None = None,
) -> int:
    state = TuiState(cwd=(cwd or Path.cwd()).resolve())
    services = services or Services(profile_id="cli")
    secret_prompt = secret_prompt or getpass.getpass
    _ensure_cli_session(services, state.cwd)
    _write(output_stream, render_screen(state))
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("/"):
            _handle_task_input(services, line, output_stream)
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
        if command == "/provider":
            _handle_provider(services, argument, output_stream, secret_prompt)
            state = replace(
                state,
                model=services.desktop_demo.selected_model,
                run_state=_run_state(services),
            )
            continue
        if command == "/thread":
            _handle_thread(services, argument, output_stream)
            state = replace(state, run_state=_run_state(services))
            continue
        if command == "/plan":
            state = _set_plan_mode(state, argument.strip())
            services.set_demo_plan_mode(state.plan_mode)
            _write(output_stream, f"Plan mode: {'on' if state.plan_mode else 'off'}")
            continue
        if command == "/model":
            if state.run_state in {"running", "waiting_permission", "waiting_privacy", "compacting", "stopping", "interrupted"}:
                _write(output_stream, "请先停止当前运行，再切换模型")
                continue
            model = argument.strip() or state.model
            try:
                services.switch_demo_model(model)
            except ApiDomainError:
                pass
            state = replace(state, model=model)
            _write(output_stream, f"Model: {state.model}")
            continue
        if command == "/run":
            _handle_run(services, output_stream)
            state = replace(state, run_state=_run_state(services))
            continue
        if command == "/stop":
            _handle_stop(services, output_stream)
            state = replace(state, run_state=_run_state(services))
            continue
        if command in {"/changes", "/diff"}:
            state = replace(state, active_panel="Changes")
            _write_changes(services, output_stream, include_diff=command == "/diff")
            continue
        if command == "/accept":
            _handle_accept(services, output_stream)
            state = replace(state, run_state=_run_state(services))
            continue
        if command == "/reject":
            _handle_reject(services, output_stream)
            state = replace(state, run_state=_run_state(services))
            continue
        if command == "/rollback":
            _handle_rollback(services, argument, output_stream)
            state = replace(state, run_state=_run_state(services))
            continue
        if command == "/memory":
            state = replace(state, active_panel="Memory")
            _write_memory(services, output_stream)
            continue
        if command == "/audit":
            state = replace(state, active_panel="Audit")
            _write_audit(services, output_stream)
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


def _ensure_cli_session(services: Services, cwd: Path) -> None:
    if services.desktop_demo.agent_name is None:
        services.create_demo_agent("YagCode CLI")
    if services.desktop_demo.project_path is None:
        services.register_demo_project(str(cwd))


def _handle_provider(
    services: Services,
    argument: str,
    output_stream: TextIO,
    secret_prompt: Callable[[str], str],
) -> None:
    argv = _split_args(argument)
    if not argv or argv[0] == "status":
        configured = [
            binding
            for binding in services.desktop_demo.configured_providers.values()
            if binding.status == "verified"
        ]
        if not configured:
            _write(output_stream, "Provider: 未配置；使用 /provider add <provider> 绑定。")
            return
        binding = configured[-1]
        _write(output_stream, f"Provider: {binding.provider} verified; model {services.desktop_demo.selected_model}")
        return
    if argv[0] != "add" or len(argv) < 2:
        _write(output_stream, "Provider: 用法 /provider add <provider> [--model <model>]")
        return
    provider = argv[1]
    model = _option_value(argv[2:], "--model")
    api_key = secret_prompt(f"{provider} API key: ")
    try:
        services.configure_demo_provider(provider, api_key, model_id=model)
    except ApiDomainError as error:
        _write(output_stream, f"Provider: {error.reason_code}")
        return
    _write(output_stream, f"Provider {provider} 已验证，模型 {services.desktop_demo.selected_model}")


def _handle_thread(services: Services, argument: str, output_stream: TextIO) -> None:
    title = argument.strip()
    if not title:
        _write(output_stream, "Thread: 用法 /thread <title>")
        return
    try:
        services.create_demo_thread(title)
    except ApiDomainError as error:
        _write(output_stream, f"Thread: {error.reason_code}")
        return
    _write(output_stream, f"Thread: {title}")


def _handle_task_input(services: Services, line: str, output_stream: TextIO) -> None:
    try:
        services.append_demo_context(line)
    except ApiDomainError as error:
        _write(output_stream, f"Task: {error.reason_code}")
        return
    _write(output_stream, f"Task queued: {line}")


def _handle_run(services: Services, output_stream: TextIO) -> None:
    try:
        run = services.resume_demo_run()
    except ApiDomainError as error:
        _write(output_stream, f"Run: {error.reason_code}")
        return
    reason = "REQUEST_REVIEW_READY" if run.state == "FINISHED" else "INCOMPLETE"
    _write(output_stream, f"Run: {run.state} {reason}")


def _handle_stop(services: Services, output_stream: TextIO) -> None:
    try:
        run = services.stop_demo_run()
    except ApiDomainError as error:
        _write(output_stream, f"Stop: {error.reason_code}")
        return
    _write(output_stream, f"Stop: {run.state}")


def _handle_accept(services: Services, output_stream: TextIO) -> None:
    try:
        services.accept_demo_review()
    except ApiDomainError as error:
        _write(output_stream, f"Review: {error.reason_code}")
        return
    _write(output_stream, f"Review: {services.desktop_demo.review_state}")


def _handle_reject(services: Services, output_stream: TextIO) -> None:
    services.reject_demo_review()
    _write(output_stream, f"Review: {services.desktop_demo.review_state}")


def _handle_rollback(services: Services, argument: str, output_stream: TextIO) -> None:
    checkpoint_id = argument.strip() or _current_checkpoint_id(services)
    if not checkpoint_id:
        _write(output_stream, "Rollback: CHECKPOINT_NOT_FOUND")
        return
    try:
        services.rollback_demo_checkpoint(checkpoint_id)
    except ApiDomainError as error:
        _write(output_stream, f"Rollback: {error.reason_code}")
        return
    _write(output_stream, f"Rollback: {checkpoint_id}")


def _write_changes(services: Services, output_stream: TextIO, *, include_diff: bool) -> None:
    inspection = services.refresh_demo_project_inspection()
    files = () if inspection is None else inspection.diff_files
    if not files:
        _write(output_stream, "Changes: no accepted patch is staged in the real worktree.")
        return
    additions = sum(file.additions for file in files)
    deletions = sum(file.deletions for file in files)
    noun = "file" if len(files) == 1 else "files"
    _write(output_stream, f"Changes: {len(files)} {noun}, +{additions}/-{deletions}")
    for file in files:
        _write(output_stream, f"- {file.path} ({file.status}, +{file.additions}/-{file.deletions})")
        if include_diff:
            _write_diff_file(file, output_stream)


def _write_diff_file(file: WorktreeDiffFile, output_stream: TextIO) -> None:
    _write(output_stream, f"Diff: {file.path}")
    for line in file.lines:
        if line.kind == "add":
            _write(output_stream, f"+{line.content}")
        elif line.kind == "delete":
            _write(output_stream, f"-{line.content}")
        elif line.kind == "hunk":
            _write(output_stream, line.content)
        else:
            _write(output_stream, f" {line.content}")


def _write_memory(services: Services, output_stream: TextIO) -> None:
    if not services.desktop_demo.memories:
        _write(output_stream, "Memory: project memory is available after a run is accepted.")
        return
    _write(output_stream, "Memory:")
    for item in services.desktop_demo.memories:
        pin = " pinned" if item.pinned else ""
        _write(output_stream, f"- {item.title}{pin}: {item.detail}")


def _write_audit(services: Services, output_stream: TextIO) -> None:
    _write(output_stream, "Audit: approvals and validation events are recorded locally.")
    if not services.desktop_demo.audit_entries:
        return
    _write(output_stream, "Audit:")
    for entry in services.desktop_demo.audit_entries[:12]:
        _write(output_stream, f"- {entry.title}: {entry.detail}")


def _run_state(services: Services) -> str:
    _project, thread, run = services.desktop_demo_records()
    if run is not None:
        return run.state.lower()
    if thread is not None:
        return "ready"
    return "idle"


def _current_checkpoint_id(services: Services) -> str:
    for checkpoint in services.desktop_demo.checkpoints:
        if checkpoint.current:
            return checkpoint.checkpoint_id
    return services.desktop_demo.checkpoints[-1].checkpoint_id if services.desktop_demo.checkpoints else ""


def _split_args(argument: str) -> list[str]:
    try:
        return shlex.split(argument)
    except ValueError:
        return []


def _option_value(argv: list[str], name: str) -> str | None:
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return argv[index + 1]
    return None


__all__ = ["TuiState", "health_payload", "render_screen", "run_tui"]
