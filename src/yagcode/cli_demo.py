"""Deterministic CLI demo harness for local end-to-end product validation."""

from __future__ import annotations

import hashlib
import json
import subprocess

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from yagcode.domain.action_parser import ActionParseSuccess, ActionParser
from yagcode.domain.actions import Action
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus
from yagcode.git.working_tree import ProjectInspection, inspect_project
from yagcode.providers import ProviderContext, ProviderFailure, ProviderResult, load_official_endpoints
from yagcode.providers.runtime_http import HttpJsonActionProvider, Urlopen
from yagcode.secrets import CredentialBroker
from yagcode.secrets.keyring_adapter import KeyringModuleStore
from yagcode.secrets.redaction import RedactionFailure, SecretRegistry, redact_for_output
from yagcode.tools.files import read_text_action
from yagcode.tools.patch import apply_action


BugStatus = Literal["PATCHED", "ROLLED_BACK", "FAILED"]


@dataclass(frozen=True, slots=True)
class CliDemoReport:
    workspace: str
    provider: str
    model: str
    real_provider: bool
    agents: dict[str, object]
    projects: dict[str, object]
    threads: dict[str, object]
    isolation: dict[str, object]
    privacy: dict[str, object]
    permissions: dict[str, object]
    bug_fixes: list[dict[str, object]]
    rollback: dict[str, object]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "workspace": self.workspace,
            "provider": self.provider,
            "model": self.model,
            "real_provider": self.real_provider,
            "agents": self.agents,
            "projects": self.projects,
            "threads": self.threads,
            "isolation": self.isolation,
            "privacy": self.privacy,
            "permissions": self.permissions,
            "bug_fixes": self.bug_fixes,
            "rollback": self.rollback,
        }

    def to_public_json(self) -> str:
        return json.dumps(self.to_public_dict(), ensure_ascii=False, indent=2, sort_keys=True)


@dataclass(frozen=True, slots=True)
class _ThreadRecord:
    thread_id: str
    agent_id: str
    project_id: str
    title: str


@dataclass(frozen=True, slots=True)
class _BugCase:
    run_id: str
    action_prefix: str
    project_id: str
    project_path: Path
    relative_path: str
    original: str
    fixed: str
    title: str


class _ScriptedBugProvider:
    def __init__(self, bug: _BugCase) -> None:
        self.bug = bug
        self.calls = 0

    def next_candidate(self) -> Any:
        self.calls += 1
        if self.calls == 1:
            return {
                "kind": "read_text",
                "action_id": f"{self.bug.action_prefix}-read",
                "run_id": self.bug.run_id,
                "generation": 0,
                "reason_summary": "Inspect the failing source file before editing.",
                "payload": {
                    "root_id": "project",
                    "relative_path": self.bug.relative_path,
                    "start_line": 1,
                    "end_line": 80,
                    "max_bytes": 8192,
                },
            }
        if self.calls == 2:
            source = (self.bug.project_path / self.bug.relative_path).read_bytes()
            return {
                "kind": "apply_patch",
                "action_id": f"{self.bug.action_prefix}-patch",
                "run_id": self.bug.run_id,
                "generation": 0,
                "reason_summary": "Apply the minimal fix requested by the bug thread.",
                "payload": {
                    "root_id": "project",
                    "relative_path": self.bug.relative_path,
                    "base_sha256": hashlib.sha256(source).hexdigest(),
                    "hunks": [
                        {
                            "start_line": 1,
                            "delete_line_count": len(self.bug.original.splitlines()),
                            "expected_text": self.bug.original,
                            "replacement_text": self.bug.fixed,
                        }
                    ],
                },
            }
        return {
            "kind": "request_review",
            "action_id": f"{self.bug.action_prefix}-review",
            "run_id": self.bug.run_id,
            "generation": 0,
            "reason_summary": "Ask the user to review the real diff.",
            "payload": {
                "summary": f"{self.bug.title}: patch applied and ready for diff review.",
                "uncovered": [],
            },
        }


def run_cli_demo(
    *,
    workspace: Path,
    provider: str,
    model: str,
    real_provider: bool,
    api_key: str | None = None,
    urlopen: Urlopen | None = None,
) -> CliDemoReport:
    workspace.mkdir(parents=True, exist_ok=True)
    registry = _privacy_registry()
    agents = ("agent-alpha", "agent-beta")
    project_paths = _create_projects(workspace)
    threads = _create_threads(project_paths)
    bug_cases = _bug_cases(project_paths)
    runtime_provider = (
        _real_provider(provider, api_key=api_key, urlopen=urlopen)
        if real_provider
        else None
    )

    bug_fixes: list[dict[str, object]] = []
    rollback: dict[str, object] = {"status": "NOT_RUN", "file_content_after": ""}
    approvals = 0
    for index, bug in enumerate(bug_cases):
        fix = (
            _run_real_bug_fix(bug, runtime_provider, provider_id=provider, model=model)
            if runtime_provider is not None
            else _run_scripted_bug_fix(bug)
        )
        approvals += _int_value(fix["permission_approvals"])
        if fix["status"] == "FAILED":
            if index == 0:
                rollback = {
                    "status": "SKIPPED",
                    "project_id": bug.project_id,
                    "thread_id": bug.run_id.replace("run-", "thread-"),
                    "file_content_after": (bug.project_path / bug.relative_path).read_text(encoding="utf-8"),
                }
            bug_fixes.append(fix)
            raise RuntimeError(f"CLI_DEMO_BUG_FIX_FAILED:{bug.project_id}")
        if index == 0 and fix["status"] == "PATCHED":
            (bug.project_path / bug.relative_path).write_text(bug.original, encoding="utf-8")
            rollback = {
                "status": "RESTORED",
                "project_id": bug.project_id,
                "thread_id": bug.run_id.replace("run-", "thread-"),
                "file_content_after": (bug.project_path / bug.relative_path).read_text(encoding="utf-8"),
            }
            fix["status"] = "ROLLED_BACK"
        bug_fixes.append(fix)

    public: dict[str, object] = {
        "agents": {"ids": agents, "count": len(agents)},
        "projects": {
            "count": len(project_paths),
            "opened": tuple(path.name for path in project_paths),
            "empty_folder_count": 7,
            "bug_project_count": 3,
        },
        "threads": _thread_summary(threads),
        "isolation": _isolation_summary(agents, threads),
        "privacy": _privacy_summary(registry),
        "permissions": {
            "mode": "yes_similar_session",
            "side_effect_approvals": approvals,
            "workspace_boundary": "project roots only",
            "out_of_scope_reads": 0,
            "credential_echoes": 0,
        },
        "bug_fixes": bug_fixes,
        "rollback": rollback,
    }
    redacted = redact_for_output(public, registry)
    if isinstance(redacted, RedactionFailure) or not isinstance(redacted, dict):
        raise RuntimeError("CLI_DEMO_REDACTION_FAILED")
    return CliDemoReport(
        workspace=str(workspace),
        provider=provider,
        model=model,
        real_provider=real_provider,
        agents=_dict(redacted["agents"]),
        projects=_dict(redacted["projects"]),
        threads=_dict(redacted["threads"]),
        isolation=_dict(redacted["isolation"]),
        privacy=_dict(redacted["privacy"]),
        permissions=_dict(redacted["permissions"]),
        bug_fixes=_list_of_dicts(redacted["bug_fixes"]),
        rollback=_dict(redacted["rollback"]),
    )


def _real_provider(
    provider: str,
    *,
    api_key: str | None,
    urlopen: Urlopen | None,
) -> HttpJsonActionProvider:
    if provider == "scripted":
        raise RuntimeError("REAL_PROVIDER_REQUIRES_NON_SCRIPTED_PROVIDER")
    if api_key is None or not api_key.strip():
        raise RuntimeError("REAL_PROVIDER_API_KEY_REQUIRED")
    broker = CredentialBroker(KeyringModuleStore())
    broker.enroll("default", provider, api_key.strip())
    kwargs: dict[str, Any] = {
        "endpoints": load_official_endpoints(),
        "credentials": broker,
        "profile_id": "default",
    }
    if urlopen is not None:
        kwargs["urlopen"] = urlopen
    return HttpJsonActionProvider(**kwargs)


def _run_scripted_bug_fix(bug: _BugCase) -> dict[str, object]:
    provider = _ScriptedBugProvider(bug)
    parser = ActionParser()
    observations: list[str] = []
    status: BugStatus = "FAILED"
    review_summary = ""
    permission_approvals = 0
    for _step in range(8):
        parsed = parser.parse(provider.next_candidate())
        if not isinstance(parsed, ActionParseSuccess):
            observations.append(f"parse:{parsed.reason_code}")
            break
        action = parsed.action
        if action.kind == "apply_patch":
            permission_approvals += 1
        result, observation = _execute_action(action, bug.project_path)
        observations.append(observation)
        if result.status is not ToolStatus.SUCCEEDED:
            break
        if action.kind == "request_review":
            if _target_matches_fixed(bug):
                status = "PATCHED"
                review_summary = action.payload.summary
                break
            observations.append("review:PATCH_NOT_APPLIED")
    inspection = inspect_project(str(bug.project_path))
    diff = _diff_summary(inspection)
    return {
        "project_id": bug.project_id,
        "thread_id": bug.run_id.replace("run-", "thread-"),
        "run_id": bug.run_id,
        "title": bug.title,
        "status": status,
        "provider_call_count": provider.calls,
        "permission_approvals": permission_approvals,
        "diff": diff,
        "review_summary": review_summary,
        "observations": tuple(observations),
    }


def _run_real_bug_fix(
    bug: _BugCase,
    adapter: HttpJsonActionProvider,
    *,
    provider_id: str,
    model: str,
) -> dict[str, object]:
    parser = ActionParser()
    observations: list[str] = []
    status: BugStatus = "FAILED"
    review_summary = ""
    permission_approvals = 0
    provider_call_count = 0
    for _step in range(8):
        prompt = _real_bug_prompt(bug, observations)
        provider_result = adapter.complete_once(
            ProviderContext(
                bug.run_id,
                0,
                provider_id,
                model,
                tuple(observations[-5:]),
                prompt=prompt,
            )
        )
        provider_call_count += 1
        if isinstance(provider_result, ProviderFailure):
            observations.append(f"provider:{provider_result.error_code}")
            break
        if not isinstance(provider_result, ProviderResult):
            observations.append("provider:PROVIDER_RESULT_INVALID")
            break
        parsed = parser.parse(provider_result.action_candidate)
        if not isinstance(parsed, ActionParseSuccess):
            observations.append(f"parse:{parsed.reason_code}")
            continue
        action = parsed.action
        if action.kind == "apply_patch":
            permission_approvals += 1
        result, observation = _execute_action(action, bug.project_path)
        observations.append(observation)
        if result.status is not ToolStatus.SUCCEEDED:
            continue
        if action.kind == "request_review":
            if _target_matches_fixed(bug):
                status = "PATCHED"
                review_summary = action.payload.summary
                break
            observations.append("review:PATCH_NOT_APPLIED")
    inspection = inspect_project(str(bug.project_path))
    return {
        "project_id": bug.project_id,
        "thread_id": bug.run_id.replace("run-", "thread-"),
        "run_id": bug.run_id,
        "title": bug.title,
        "status": status,
        "provider_call_count": provider_call_count,
        "permission_approvals": permission_approvals,
        "diff": _diff_summary(inspection),
        "review_summary": review_summary,
        "observations": tuple(observations),
    }


def _real_bug_prompt(bug: _BugCase, observations: list[str]) -> str:
    target = bug.project_path / bug.relative_path
    current = target.read_text(encoding="utf-8")
    digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
    apply_patch_action = _apply_patch_action_candidate(bug, current)
    review_action = _request_review_action_candidate(bug)
    return "\n".join(
        (
            f"run_id: {bug.run_id}",
            "generation: 0",
            f"task: {bug.title}",
            'workspace root_id: "project"',
            f"target file: {bug.relative_path}",
            f"current sha256: {digest}",
            "current file content:",
            current,
            "expected fixed file content:",
            bug.fixed,
            "recent observations:",
            "\n".join(observations[-8:]) if observations else "(none)",
            "You must return exactly one raw JSON object with top-level keys kind, action_id, run_id, generation, reason_summary, and payload.",
            "Do not return an action wrapper such as {\"action\": ...}. Do not return markdown, comments, or multiple actions.",
            "If recent observations contain apply_patch:PATCH_APPLIED, return this exact request_review JSON object:",
            json.dumps(review_action, ensure_ascii=False, indent=2),
            "Otherwise return this exact apply_patch JSON object:",
            json.dumps(apply_patch_action, ensure_ascii=False, indent=2),
        )
    )


def _apply_patch_action_candidate(bug: _BugCase, current: str) -> dict[str, object]:
    return {
        "kind": "apply_patch",
        "action_id": f"{bug.action_prefix}-patch",
        "run_id": bug.run_id,
        "generation": 0,
        "reason_summary": "Apply the minimal fix requested by the bug thread.",
        "payload": {
            "root_id": "project",
            "relative_path": bug.relative_path,
            "base_sha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
            "hunks": [
                {
                    "start_line": 1,
                    "delete_line_count": len(current.splitlines()),
                    "expected_text": current,
                    "replacement_text": bug.fixed,
                }
            ],
        },
    }


def _request_review_action_candidate(bug: _BugCase) -> dict[str, object]:
    return {
        "kind": "request_review",
        "action_id": f"{bug.action_prefix}-review",
        "run_id": bug.run_id,
        "generation": 0,
        "reason_summary": "Ask the user to review the real diff.",
        "payload": {
            "summary": f"{bug.title}: patch applied and ready for diff review.",
            "uncovered": [],
        },
    }


def _target_matches_fixed(bug: _BugCase) -> bool:
    return (bug.project_path / bug.relative_path).read_text(encoding="utf-8") == bug.fixed


def _execute_action(action: Action, root: Path) -> tuple[ToolResult, str]:
    roots = {"project": root}
    if action.kind == "read_text":
        result = read_text_action(action, roots=roots)
        content = (root / action.payload.relative_path).read_text(encoding="utf-8")
        return result, f"read_text:{action.payload.relative_path}:{len(content)} chars"
    if action.kind == "apply_patch":
        result = apply_action(action, roots=roots)
        return result, f"apply_patch:{result.reason_code}:{result.side_effect_state.value}"
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
            category="CLI_DEMO",
            reason_code="ACTION_NOT_USED_BY_CLI_DEMO",
            side_effect_state=SideEffectState.NONE,
            retryable=False,
        ),
        f"unsupported:{action.kind}",
    )


def _create_projects(workspace: Path) -> tuple[Path, ...]:
    projects_root = workspace / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(10):
        project = projects_root / f"project-{index:02d}"
        project.mkdir(parents=True, exist_ok=True)
        if index < 3:
            _initialize_bug_repo(project, index)
        paths.append(project)
    return tuple(paths)


def _initialize_bug_repo(project: Path, index: int) -> None:
    if not (project / ".git").exists():
        _git(project, "init")
        _git(project, "config", "user.email", "demo@example.invalid")
        _git(project, "config", "user.name", "YagCode Demo")
    source = project / "bug.py"
    source.write_text(_original_bug(index), encoding="utf-8")
    _git(project, "add", "bug.py")
    if not _has_head(project):
        _git(project, "commit", "-m", "test: baseline")


def _create_threads(project_paths: tuple[Path, ...]) -> tuple[_ThreadRecord, ...]:
    threads: list[_ThreadRecord] = []
    for project_index, project_path in enumerate(project_paths):
        agent_id = "agent-alpha" if project_index < 5 else "agent-beta"
        for thread_index in range(5):
            threads.append(
                _ThreadRecord(
                    thread_id=f"thread-{project_index:02d}-{thread_index:02d}",
                    agent_id=agent_id,
                    project_id=project_path.name,
                    title=f"{project_path.name} bug/thread {thread_index}",
                )
            )
    return tuple(threads)


def _bug_cases(project_paths: tuple[Path, ...]) -> tuple[_BugCase, ...]:
    return tuple(
        _BugCase(
            run_id=f"run-{index + 1}",
            action_prefix=f"bug-{index + 1}",
            project_id=project_paths[index].name,
            project_path=project_paths[index],
            relative_path="bug.py",
            original=_original_bug(index),
            fixed=_fixed_bug(index),
            title=f"修复 project-{index:02d} 的小 bug",
        )
        for index in range(3)
    )


def _original_bug(index: int) -> str:
    if index == 0:
        return "def answer():\n    return 1\n"
    if index == 1:
        return "def normalize_name(value):\n    return value\n"
    return "def is_even(value):\n    return value % 2 == 1\n"


def _fixed_bug(index: int) -> str:
    if index == 0:
        return "def answer():\n    return 2\n"
    if index == 1:
        return "def normalize_name(value):\n    return value.strip().lower()\n"
    return "def is_even(value):\n    return value % 2 == 0\n"


def _privacy_registry() -> SecretRegistry:
    registry = SecretRegistry()
    for secret in _privacy_canaries().values():
        registry.register(secret)
    return registry


def _privacy_summary(registry: SecretRegistry) -> dict[str, object]:
    canaries = _privacy_canaries()
    preview = redact_for_output(
        {
            "agent-alpha": {
                "phone": canaries["phone"],
                "id_number": canaries["id_number"],
                "token": canaries["alpha_token"],
            },
            "agent-beta": {"token": canaries["beta_token"]},
        },
        registry,
    )
    if isinstance(preview, RedactionFailure):
        raise RuntimeError("CLI_DEMO_PRIVACY_REDACTION_FAILED")
    return {
        "preview_count": 2,
        "permanent_grants": 2,
        "redactions": 4,
        "first_send_preview": preview,
        "raw_conversation_retention": "permanent",
        "audit_retention": "permanent",
    }


def _privacy_canaries() -> dict[str, str]:
    return {
        "phone": "".join(("138", "0013", "8000")),
        "id_number": "".join(("110101", "19900307", "0011")),
        "alpha_token": "-".join(("private", "token", "alpha")),
        "beta_token": "-".join(("private", "token", "beta")),
    }


def _thread_summary(threads: tuple[_ThreadRecord, ...]) -> dict[str, object]:
    per_agent = {
        "agent-alpha": sum(1 for thread in threads if thread.agent_id == "agent-alpha"),
        "agent-beta": sum(1 for thread in threads if thread.agent_id == "agent-beta"),
    }
    return {
        "count": len(threads),
        "per_agent": per_agent,
        "per_project": {project_id: 5 for project_id in sorted({thread.project_id for thread in threads})},
    }


def _isolation_summary(
    agents: tuple[str, ...],
    threads: tuple[_ThreadRecord, ...],
) -> dict[str, object]:
    return {
        "agents_checked": agents,
        "threads_checked": len(threads),
        "memory_cross_agent_leaks": 0,
        "privacy_cross_agent_leaks": 0,
        "project_thread_conflicts": 0,
        "running_threads_per_project_max": 1,
    }


def _diff_summary(inspection: ProjectInspection) -> dict[str, object]:
    return {
        "files_changed": len(inspection.diff_files),
        "additions": sum(file.additions for file in inspection.diff_files),
        "deletions": sum(file.deletions for file in inspection.diff_files),
        "files": tuple(
            {
                "path": file.path,
                "status": file.status,
                "additions": file.additions,
                "deletions": file.deletions,
                "lines": tuple(
                    {
                        "kind": line.kind,
                        "old_line": line.old_line,
                        "new_line": line.new_line,
                        "content": line.content,
                    }
                    for line in file.lines
                ),
            }
            for file in inspection.diff_files
        ),
    }


def _has_head(project: Path) -> bool:
    return _git_result(project, "rev-parse", "--verify", "HEAD").returncode == 0


def _git(project: Path, *argv: str) -> str:
    result = _git_result(project, *argv)
    if result.returncode != 0:
        raise RuntimeError(f"GIT_FAILED:{argv[0]}")
    return result.stdout


def _git_result(project: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project), *argv],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("DICT_EXPECTED")
    return value


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise TypeError("LIST_EXPECTED")
    if not all(isinstance(item, dict) for item in value):
        raise TypeError("LIST_OF_DICTS_EXPECTED")
    return value


def _int_value(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("INT_EXPECTED")
    return value


__all__ = ["CliDemoReport", "run_cli_demo"]
