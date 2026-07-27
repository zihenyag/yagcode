"""Synchronous desktop demo Agent step backed by real Provider actions."""

from __future__ import annotations

import hashlib
import json
import os
import secrets

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from yagcode.domain.action_parser import ActionParseFailure, ActionParseSuccess, ActionParser
from yagcode.domain.actions import Action
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus
from yagcode.providers import ProviderContext, ProviderFailure, ProviderResult
from yagcode.tools.files import read_text_action
from yagcode.tools.patch import apply_action
from yagcode.tools.search import search_action


DesktopAgentStatus = Literal["FINISHED", "FAILED"]


class DesktopActionProvider(Protocol):
    def complete_once(self, context: ProviderContext) -> ProviderResult | ProviderFailure: ...


@dataclass(frozen=True, slots=True)
class DesktopAgentStepResult:
    status: DesktopAgentStatus
    reason_code: str
    observations: tuple[str, ...]
    provider_calls: int
    actions_executed: int
    patches_applied: int
    review_summary: str


def run_desktop_agent_step(
    *,
    provider: DesktopActionProvider,
    run_id: str,
    generation: int,
    provider_id: str,
    model: str,
    project_root: Path,
    user_messages: tuple[str, ...],
    max_steps: int = 8,
) -> DesktopAgentStepResult:
    """Run a small governed Provider -> action -> tool loop for the desktop demo."""

    parser = ActionParser()
    observations: list[str] = []
    provider_calls = 0
    actions_executed = 0
    patches_applied = 0
    review_summary = ""
    for _step in range(max_steps):
        provider_result = provider.complete_once(
            ProviderContext(
                run_id,
                generation,
                provider_id,
                model,
                tuple(observations[-8:]),
                prompt=_build_prompt(
                    run_id=run_id,
                    generation=generation,
                    user_messages=user_messages,
                    observations=tuple(observations[-8:]),
                ),
            )
        )
        provider_calls += 1
        if isinstance(provider_result, ProviderFailure):
            observations.append(f"provider:{provider_result.error_code}")
            return _finish(
                "FAILED",
                provider_result.error_code,
                observations,
                provider_calls,
                actions_executed,
                patches_applied,
                review_summary,
            )
        if not isinstance(provider_result, ProviderResult):
            observations.append("provider:PROVIDER_RESULT_INVALID")
            return _finish(
                "FAILED",
                "PROVIDER_RESULT_INVALID",
                observations,
                provider_calls,
                actions_executed,
                patches_applied,
                review_summary,
            )

        parsed = parser.parse(provider_result.action_candidate)
        if isinstance(parsed, ActionParseFailure):
            issue_summary = ",".join(f"{issue.path}:{issue.code}" for issue in parsed.issues[:8])
            observations.append(f"parse:{parsed.reason_code}:{issue_summary}")
            continue
        if not isinstance(parsed, ActionParseSuccess):
            observations.append("parse:ACTION_PARSE_RESULT_INVALID")
            continue

        action = parsed.action
        result, observation = _execute_action(action, project_root)
        actions_executed += 1
        observations.append(observation)
        if result.status is not ToolStatus.SUCCEEDED:
            continue
        if action.kind == "apply_patch" and result.side_effect_state is SideEffectState.APPLIED:
            patches_applied += 1
        if action.kind == "request_review":
            review_summary = action.payload.summary
            if patches_applied > 0:
                return _finish(
                    "FINISHED",
                    "REQUEST_REVIEW_READY",
                    observations,
                    provider_calls,
                    actions_executed,
                    patches_applied,
                    review_summary,
                )
            observations.append("review:PATCH_REQUIRED_BEFORE_REVIEW")

    return _finish(
        "FAILED",
        "AGENT_STEP_LIMIT_REACHED",
        observations,
        provider_calls,
        actions_executed,
        patches_applied,
        review_summary,
    )


def _build_prompt(*, run_id: str, generation: int, user_messages: tuple[str, ...], observations: tuple[str, ...]) -> str:
    read_example = {
        "kind": "read_text",
        "action_id": "read-bug-file",
        "run_id": run_id,
        "generation": generation,
        "reason_summary": "Read the file mentioned by the user before patching.",
        "payload": {
            "root_id": "project",
            "relative_path": "src/example.py",
            "start_line": 1,
            "end_line": 200,
            "max_bytes": 20_000,
        },
    }
    patch_example = {
        "kind": "apply_patch",
        "action_id": "patch-bug-file",
        "run_id": run_id,
        "generation": generation,
        "reason_summary": "Replace the exact buggy text with the corrected implementation.",
        "payload": {
            "root_id": "project",
            "relative_path": "src/example.py",
            "base_sha256": "copy the sha256 from the read_text observation",
            "hunks": [
                {
                    "start_line": 1,
                    "delete_line_count": 1,
                    "expected_text": "exact old text",
                    "replacement_text": "new text",
                }
            ],
        },
    }
    review_example = {
        "kind": "request_review",
        "action_id": "request-user-review",
        "run_id": run_id,
        "generation": generation,
        "reason_summary": "Ask the user to review the diff.",
        "payload": {"summary": "what changed", "uncovered": []},
    }
    return "\n".join(
        (
            "You are running inside YagCode desktop sidecar.",
            "Thread names are UI metadata and are intentionally not included in this prompt.",
            "Use only the user messages and tool observations below as task context.",
            'Workspace root_id is "project".',
            f'Current run_id is "{run_id}" and generation is {generation}.',
            "Allowed actions in this desktop demo step: list_directory, read_text, search_literal, apply_patch, request_review.",
            "Return exactly one raw JSON YagCode action object; no markdown and no wrapper such as {\"action\": ...}.",
            "Required action examples with exact current run values:",
            json.dumps(read_example, ensure_ascii=False),
            json.dumps(patch_example, ensure_ascii=False),
            json.dumps(review_example, ensure_ascii=False),
            "If the user mentions a file path, first return read_text for that path.",
            "For apply_patch, copy base_sha256 from the read_text observation and set expected_text to the exact old file text being replaced.",
            "After a successful apply_patch observation, return request_review.",
            "",
            "User messages:",
            "\n".join(f"- {message}" for message in user_messages),
            "",
            "Recent tool observations:",
            "\n".join(observations) if observations else "(none)",
        )
    )


def _execute_action(action: Action, project_root: Path) -> tuple[ToolResult, str]:
    roots = {"project": project_root}
    if action.kind == "list_directory":
        return _list_directory_action(action, project_root)
    if action.kind == "read_text":
        result = read_text_action(action, roots=roots)
        if result.status is ToolStatus.SUCCEEDED:
            return result, _read_text_observation(action.payload.relative_path, project_root)
        return result, f"read_text:{action.payload.relative_path}:{result.reason_code}"
    if action.kind == "search_literal":
        result = search_action(action, roots=roots)
        refs = ",".join(result.artifact_refs[:24])
        return result, f"search_literal:{result.reason_code}:{refs}"
    if action.kind == "apply_patch":
        result = apply_action(action, roots=roots)
        if result.reason_code == "EXPECTED_TEXT_MISMATCH":
            recovered = _apply_patch_by_unique_expected_text(action, project_root)
            if recovered is not None:
                return recovered, f"apply_patch:{recovered.reason_code}:{recovered.side_effect_state.value}"
        return result, _apply_patch_observation(action, result, project_root)
    if action.kind == "request_review":
        return (
            ToolResult(
                action_id=action.action_id,
                status=ToolStatus.SUCCEEDED,
                category="REVIEW",
                reason_code="REVIEW_REQUESTED",
                side_effect_state=SideEffectState.NONE,
                retryable=False,
            ),
            f"request_review:{action.payload.summary}",
        )
    return (
        ToolResult(
            action_id=action.action_id,
            status=ToolStatus.DENIED,
            category="DESKTOP_AGENT",
            reason_code="ACTION_NOT_SUPPORTED_BY_DESKTOP_DEMO",
            side_effect_state=SideEffectState.NONE,
            retryable=False,
        ),
        f"unsupported:{action.kind}",
    )


def _safe_child(root: Path, relative_path: str) -> Path | None:
    if relative_path == "" or Path(relative_path).is_absolute():
        return None
    relative = Path(relative_path)
    if any(part in {"", ".", ".."} for part in relative.parts):
        return None
    trusted_root = root.resolve(strict=True)
    target = (trusted_root / relative).resolve(strict=False)
    if not target.is_relative_to(trusted_root) or target.is_symlink():
        return None
    return target


def _read_text_observation(relative_path: str, project_root: Path) -> str:
    target = _safe_child(project_root, relative_path)
    if target is None or not target.is_file():
        return f"read_text:{relative_path}:CONTENT_UNAVAILABLE"
    try:
        raw = target.read_bytes()
        content = raw.decode("utf-8")[:20_000]
    except (OSError, UnicodeError):
        return f"read_text:{relative_path}:CONTENT_UNAVAILABLE"
    digest = hashlib.sha256(raw).hexdigest()
    return f"read_text:{relative_path}:sha256:{digest}:BEGIN\n{content}\nread_text:{relative_path}:END"


def _apply_patch_observation(action: Action, result: ToolResult, project_root: Path) -> str:
    base = f"apply_patch:{result.reason_code}:{result.side_effect_state.value}"
    if action.kind != "apply_patch" or result.reason_code != "EXPECTED_TEXT_MISMATCH":
        return base
    target = _safe_child(project_root, action.payload.relative_path)
    if target is None or not target.is_file():
        return base
    try:
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError):
        return base
    hints: list[str] = []
    for index, hunk in enumerate(action.payload.hunks[:3], start=1):
        start = hunk.start_line - 1
        stop = start + hunk.delete_line_count
        if start < 0 or stop > len(lines):
            hints.append(f"hunk_{index}:line_range_out_of_bounds")
            continue
        actual_text = "".join(lines[start:stop])
        hints.append(
            f"hunk_{index}:actual_text_json={json.dumps(actual_text, ensure_ascii=False)};"
            f"delete_line_count={hunk.delete_line_count}"
        )
    if not hints:
        return base
    return base + "\n" + "\n".join(hints)


def _apply_patch_by_unique_expected_text(action: Action, project_root: Path) -> ToolResult | None:
    if action.kind != "apply_patch":
        return None
    target = _safe_child(project_root, action.payload.relative_path)
    if target is None or not target.is_file():
        return None
    try:
        source = target.read_bytes()
        if hashlib.sha256(source).hexdigest() != action.payload.base_sha256:
            return None
        text = source.decode("utf-8")
    except (OSError, UnicodeError):
        return None
    patched = text
    for hunk in action.payload.hunks:
        if hunk.expected_text == "":
            return None
        if patched.count(hunk.expected_text) != 1:
            return None
        patched = patched.replace(hunk.expected_text, hunk.replacement_text, 1)
    if patched == text:
        return None
    staged = target.with_name(f".{target.name}.yagcode-stage-{secrets.token_hex(12)}")
    try:
        if staged.parent != target.parent or staged.name == target.name:
            return None
        staged.write_bytes(patched.encode("utf-8"))
        if hashlib.sha256(target.read_bytes()).hexdigest() != action.payload.base_sha256:
            staged.unlink(missing_ok=True)
            return None
        os.replace(staged, target)
    except OSError:
        staged.unlink(missing_ok=True)
        return None
    return ToolResult(
        action_id=action.action_id,
        status=ToolStatus.SUCCEEDED,
        category="PATCH",
        reason_code="PATCH_APPLIED_UNIQUE_EXPECTED_TEXT",
        side_effect_state=SideEffectState.APPLIED,
        retryable=False,
    )


def _list_directory_action(action: Action, project_root: Path) -> tuple[ToolResult, str]:
    if action.kind != "list_directory":
        raise RuntimeError("LIST_DIRECTORY_ACTION_REQUIRED")
    target: Path | None
    if action.payload.relative_path == "":
        target = project_root.resolve(strict=True)
    else:
        target = _safe_child(project_root, action.payload.relative_path)
    if target is None or not target.is_dir():
        return _tool_denied(action, "LIST_PATH_UNTRUSTED"), f"list_directory:{action.payload.relative_path}:LIST_PATH_UNTRUSTED"
    entries: list[str] = []
    max_depth = action.payload.max_depth
    try:
        for path in sorted(target.rglob("*")):
            relative_parts = path.relative_to(target).parts
            if len(relative_parts) > max_depth + 1:
                continue
            if path.is_symlink():
                continue
            marker = "/" if path.is_dir() else ""
            entries.append(f"{path.relative_to(project_root).as_posix()}{marker}")
            if len(entries) >= action.payload.max_entries:
                break
    except OSError:
        return _tool_denied(action, "LIST_DIRECTORY_FAILED"), f"list_directory:{action.payload.relative_path}:LIST_DIRECTORY_FAILED"
    return (
        ToolResult(
            action_id=action.action_id,
            status=ToolStatus.SUCCEEDED,
            category="LIST",
            reason_code="LIST_OK",
            artifact_refs=entries,
            side_effect_state=SideEffectState.NONE,
            retryable=True,
        ),
        f"list_directory:{action.payload.relative_path}:BEGIN\n" + "\n".join(entries) + "\nlist_directory:END",
    )


def _tool_denied(action: Action, reason_code: str) -> ToolResult:
    return ToolResult(
        action_id=action.action_id,
        status=ToolStatus.DENIED,
        category="DESKTOP_AGENT",
        reason_code=reason_code,
        side_effect_state=SideEffectState.NONE,
        retryable=False,
    )


def _finish(
    status: DesktopAgentStatus,
    reason_code: str,
    observations: list[str],
    provider_calls: int,
    actions_executed: int,
    patches_applied: int,
    review_summary: str,
) -> DesktopAgentStepResult:
    return DesktopAgentStepResult(
        status=status,
        reason_code=reason_code,
        observations=tuple(observations),
        provider_calls=provider_calls,
        actions_executed=actions_executed,
        patches_applied=patches_applied,
        review_summary=review_summary,
    )


__all__ = ["DesktopActionProvider", "DesktopAgentStepResult", "run_desktop_agent_step"]
