from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path

from yagcode.cli import main
from yagcode.api.dependencies import Services
from yagcode.providers import ProviderContext, ProviderFailure, ProviderResult
from yagcode.providers.validation import ProviderVerificationResult
from yagcode.tui import TuiState, health_payload, render_screen


class _Keyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


class _Verifier:
    def verify(self, provider: str, api_key: str) -> ProviderVerificationResult:
        from datetime import UTC, datetime

        return ProviderVerificationResult(
            provider=provider,
            status="verified",
            checked_at=datetime(2026, 7, 29, tzinfo=UTC),
            detail="GET /models verified",
            models=(f"{provider}-cli-model",),
        )


class _ActionProvider:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.contexts: list[ProviderContext] = []

    def complete_once(self, context: ProviderContext) -> ProviderResult | ProviderFailure:
        self.contexts.append(context)
        source = self.repo / "src" / "example.py"
        current = source.read_text(encoding="utf-8")
        if len(self.contexts) == 1:
            return ProviderResult.from_candidate(
                context.provider,
                context.model,
                context.generation,
                {
                    "kind": "read_text",
                    "action_id": "cli-read",
                    "run_id": context.run_id,
                    "generation": context.generation,
                    "reason_summary": "Read the target file before patching.",
                    "payload": {
                        "root_id": "project",
                        "relative_path": "src/example.py",
                        "start_line": 1,
                        "end_line": 40,
                        "max_bytes": 4096,
                    },
                },
            )
        if len(self.contexts) == 2:
            return ProviderResult.from_candidate(
                context.provider,
                context.model,
                context.generation,
                {
                    "kind": "apply_patch",
                    "action_id": "cli-patch",
                    "run_id": context.run_id,
                    "generation": context.generation,
                    "reason_summary": "Fix the return value.",
                    "payload": {
                        "root_id": "project",
                        "relative_path": "src/example.py",
                        "base_sha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
                        "hunks": [
                            {
                                "start_line": 1,
                                "delete_line_count": 2,
                                "expected_text": current,
                                "replacement_text": "def answer():\n    return 2\n",
                            }
                        ],
                    },
                },
            )
        return ProviderResult.from_candidate(
            context.provider,
            context.model,
            context.generation,
            {
                "kind": "request_review",
                "action_id": "cli-review",
                "run_id": context.run_id,
                "generation": context.generation,
                "reason_summary": "Ask the user to review the diff.",
                "payload": {"summary": "CLI 已生成候选 diff", "uncovered": []},
            },
        )


def _make_bug_project(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True, shell=False)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    source = repo / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("def answer():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "src/example.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "test: baseline"], check=True, capture_output=True, text=True, shell=False)
    return repo


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


def test_cli_terminal_flow_matches_desktop_bug_review_lifecycle(tmp_path: Path) -> None:
    repo = _make_bug_project(tmp_path)
    keyring = _Keyring()
    from yagcode.secrets import CredentialBroker

    services = Services(
        credential_broker=CredentialBroker(keyring),
        provider_verifier=_Verifier(),
        action_provider=_ActionProvider(repo),
    )
    stdin = io.StringIO(
        "\n".join(
            (
                "/provider add openai --model openai-cli-model",
                "/thread 修复 answer 返回值",
                "请修复 src/example.py，让 answer 返回 2",
                "/run",
                "/changes",
                "/diff",
                "/accept",
                "/model openai-after-review",
                "/memory",
                "/audit",
                "/quit",
                "",
            )
        )
    )
    stdout = io.StringIO()

    exit_code = main(
        [],
        input_stream=stdin,
        output_stream=stdout,
        cwd=repo,
        services=services,
        secret_prompt=lambda _prompt: "sk-test-cli-key",
    )

    rendered = stdout.getvalue()
    assert exit_code == 0
    assert "Provider openai 已验证，模型 openai-cli-model" in rendered
    assert "Thread: 修复 answer 返回值" in rendered
    assert "Task queued: 请修复 src/example.py，让 answer 返回 2" in rendered
    assert "Run: FINISHED REQUEST_REVIEW_READY" in rendered
    assert "Changes: 1 file, +1/-1" in rendered
    assert "Diff: src/example.py" in rendered
    assert "-    return 1" in rendered
    assert "+    return 2" in rendered
    assert "Review: ACCEPTED" in rendered
    assert "Model: openai-after-review" in rendered
    assert "Memory:" in rendered
    assert "Audit:" in rendered
    assert "sk-test-cli-key" not in rendered
    assert any(value == "sk-test-cli-key" for value in keyring.values.values())
    assert (repo / "src" / "example.py").read_text(encoding="utf-8") == "def answer():\n    return 2\n"


def test_cli_can_reject_and_rollback_candidate_review(tmp_path: Path) -> None:
    repo = _make_bug_project(tmp_path)
    from yagcode.secrets import CredentialBroker

    services = Services(
        credential_broker=CredentialBroker(_Keyring()),
        provider_verifier=_Verifier(),
        action_provider=_ActionProvider(repo),
    )
    stdin = io.StringIO(
        "\n".join(
            (
                "/provider add openai",
                "/thread 修复 answer 返回值",
                "请修复 src/example.py",
                "/run",
                "/reject",
                "/rollback checkpoint-1",
                "/quit",
                "",
            )
        )
    )
    stdout = io.StringIO()

    assert main(
        [],
        input_stream=stdin,
        output_stream=stdout,
        cwd=repo,
        services=services,
        secret_prompt=lambda _prompt: "sk-test-cli-key",
    ) == 0

    rendered = stdout.getvalue()
    assert "Review: REJECTED" in rendered
    assert "Rollback: checkpoint-1" in rendered
    assert (repo / "src" / "example.py").read_text(encoding="utf-8") == "def answer():\n    return 1\n"
