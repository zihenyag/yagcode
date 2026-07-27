from __future__ import annotations

import hashlib
import json
import subprocess

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from yagcode.api.app import Runtime, create_app
from yagcode.api.dependencies import Services
from yagcode.providers import ProviderContext, ProviderFailure, ProviderResult
from yagcode.providers.validation import ProviderVerificationResult
from yagcode.secrets import CredentialBroker


class _Keyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.deleted: list[tuple[str, str]] = []

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.deleted.append((service, account))
        self.values.pop((service, account), None)


class _Verifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def verify(self, provider: str, api_key: str) -> ProviderVerificationResult:
        self.calls.append((provider, api_key))
        status = "error" if api_key == "bad-key" else "verified"
        detail = "PROVIDER_AUTH_REJECTED" if status == "error" else "GET /models verified"
        return ProviderVerificationResult(
            provider=provider,
            status=status,
            checked_at=_clock(),
            detail=detail,
            models=(f"{provider}-model-from-api",) if status == "verified" else (),
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
                    "action_id": "desktop-read",
                    "run_id": context.run_id,
                    "generation": context.generation,
                    "reason_summary": "Read the buggy file before patching.",
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
                    "action_id": "desktop-patch",
                    "run_id": context.run_id,
                    "generation": context.generation,
                    "reason_summary": "Fix the answer return value.",
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
                "action_id": "desktop-review",
                "run_id": context.run_id,
                "generation": context.generation,
                "reason_summary": "Ask the user to review the diff.",
                "payload": {"summary": "真实 Provider action 已修复 src/example.py", "uncovered": []},
            },
        )


class _LineMismatchPatchProvider(_ActionProvider):
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
                    "action_id": "desktop-read",
                    "run_id": context.run_id,
                    "generation": context.generation,
                    "reason_summary": "Read the buggy file before patching.",
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
                    "action_id": "desktop-patch",
                    "run_id": context.run_id,
                    "generation": context.generation,
                    "reason_summary": "Patch with exact unique text but wrong line count.",
                    "payload": {
                        "root_id": "project",
                        "relative_path": "src/example.py",
                        "base_sha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
                        "hunks": [
                            {
                                "start_line": 1,
                                "delete_line_count": 1,
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
                "action_id": "desktop-review",
                "run_id": context.run_id,
                "generation": context.generation,
                "reason_summary": "Ask the user to review the diff.",
                "payload": {"summary": "Line-count mismatch recovered safely.", "uncovered": []},
            },
        )


def _clock() -> datetime:
    return datetime(2026, 7, 26, tzinfo=UTC)


def _client_and_services(
    *,
    action_provider: _ActionProvider | None = None,
) -> tuple[TestClient, Services, _Verifier, _Keyring]:
    verifier = _Verifier()
    keyring = _Keyring()
    services = Services(
        credential_broker=CredentialBroker(keyring, clock=_clock),
        provider_verifier=verifier,
        clock=_clock,
        action_provider=action_provider,
    )
    runtime = Runtime(startup_token="startup", desktop_origin="app://yagcode")
    return TestClient(create_app(runtime, services=services)), services, verifier, keyring


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer startup", "Origin": "app://yagcode"}


def _start_run(client: TestClient) -> tuple[str, str]:
    project = client.post("/api/v1/projects", headers=_headers(), json={"name": "demo"}).json()
    thread = client.post(
        f"/api/v1/projects/{project['project_id']}/threads",
        headers=_headers(),
        json={"title": "bug fix", "plan_enabled": True},
    ).json()
    run = client.post(
        f"/api/v1/threads/{thread['thread_id']}/runs",
        headers=_headers(),
        json={"model": "openai:gpt-5.6-sol"},
    ).json()
    return thread["thread_id"], run["run_id"]


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *argv],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )


def _make_dirty_git_project(tmp_path: Path) -> Path:
    repo = tmp_path / "project-alpha"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True, shell=False)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    source = repo / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("def answer():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "src/example.py")
    _git(repo, "commit", "-m", "test: baseline")
    source.write_text("def answer():\n    return 2\n\nprint(answer())\n", encoding="utf-8")
    (repo / "notes.txt").write_text("untracked note\n", encoding="utf-8")
    return repo


def _make_clean_bug_project(tmp_path: Path) -> Path:
    repo = tmp_path / "project-beta"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True, shell=False)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    source = repo / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("def answer():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "src/example.py")
    _git(repo, "commit", "-m", "test: baseline")
    return repo


def _bootstrap_desktop_workbench(client: TestClient, repo: Path) -> None:
    for command in (
        {"type": "create_agent", "payload": {"name": "我的 Agent"}},
        {"type": "open_folder", "payload": {"path": str(repo)}},
        {"type": "bind_api", "payload": {"provider": "openai", "api_key": "sk-test-demo-key"}},
        {"type": "create_thread", "payload": {"title": "调试一个权限边界 bug"}},
    ):
        assert client.post("/api/v1/commands", headers=_headers(), json=command).json() == {"ok": True}


@pytest.mark.parametrize(
    "blocking_state",
    ["RUNNING", "WAITING_PERMISSION", "WAITING_PRIVACY", "COMPACTING", "STOPPING", "INTERRUPTED"],
)
def test_desktop_blocking_runs_include_all_non_closable_states(blocking_state: str) -> None:
    client, services, _verifier, _keyring = _client_and_services()
    thread_id, run_id = _start_run(client)
    services._runs[run_id].state = blocking_state

    response = client.get("/api/v1/desktop/blocking-runs", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"runs": [{"id": run_id, "state": blocking_state, "title": thread_id}]}


def test_desktop_blocking_runs_exclude_stopped_runs() -> None:
    client, _services, _verifier, _keyring = _client_and_services()
    _thread_id, run_id = _start_run(client)
    client.post(f"/api/v1/runs/{run_id}/stop", headers=_headers())

    response = client.get("/api/v1/desktop/blocking-runs", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"runs": []}


def test_desktop_workbench_starts_empty_for_first_run_onboarding() -> None:
    client, _services, _verifier, _keyring = _client_and_services()

    response = client.get("/api/v1/workbench", headers=_headers())

    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["profile_id"] == "default"
    assert snapshot["connection"] == "connected"
    assert snapshot["onboarding"]["step"] == "CREATE_AGENT"
    assert snapshot["navigation"]["profiles"] == []
    assert snapshot["navigation"]["projects"] == []
    assert snapshot["navigation"]["threads"] == []
    assert snapshot["task"]["run_state"] == "IDLE"
    models = snapshot["task"]["models"]
    assert {"id": "gpt-5.6-sol", "label": "OpenAI gpt-5.6-sol", "provider": "openai"} in models
    assert {"id": "qwen3-coder-plus", "label": "Qwen3 Coder Plus", "provider": "qwen"} in models
    assert {"id": "glm-5.2", "label": "GLM 5.2", "provider": "glm"} in models
    assert {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner", "provider": "deepseek"} in models
    assert {"id": "minimax-m3", "label": "MiniMax M3", "provider": "minimax"} in models
    assert {"id": "kimi-k3", "label": "Kimi K3", "provider": "kimi"} in models
    assert {"id": "MiniMax/MiniMax-M3", "label": "NJU SE Hub / MiniMax M3", "provider": "njusehub"} in models
    assert {"id": "kimi/kimi-k3", "label": "NJU SE Hub / Kimi K3", "provider": "njusehub"} in models
    assert snapshot["task"]["retry_policy"] == {
        "connection_retries": 5,
        "tool_retries": 3,
        "model_retries": 5,
    }
    assert snapshot["evidence"]["validations"][0]["command"] == "GET /api/v1/workbench"
    assert snapshot["settings"]["credential_statuses"][0]["updated_at"] is None
    assert snapshot["settings"]["theme_mode"] == "system"
    assert snapshot["settings"]["locale"] == "zh-Hans"
    assert snapshot["settings"]["theme_options"] == [
        {"id": "system", "label": "跟随系统"},
        {"id": "light", "label": "Light"},
        {"id": "dark", "label": "Dark"},
    ]
    assert snapshot["settings"]["locale_options"] == [
        {"id": "zh-Hans", "label": "中文（简体）"},
        {"id": "zh-Hant", "label": "中文（繁體）"},
        {"id": "en-US", "label": "English (US)"},
        {"id": "en-GB", "label": "English (UK)"},
    ]
    assert snapshot["settings"]["retention_options"] == [
        "permanent",
        "30d",
        "60d",
        "90d",
        "180d",
        "1y",
        "2y",
    ]


def test_desktop_onboarding_walks_real_agent_folder_key_thread_flow(tmp_path: Path) -> None:
    repo = _make_dirty_git_project(tmp_path)
    client, _services, verifier, keyring = _client_and_services()

    create_agent = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "create_agent", "payload": {"name": "我的 Agent"}},
    )
    assert create_agent.status_code == 200
    assert create_agent.json() == {"ok": True}
    after_agent = client.get("/api/v1/workbench", headers=_headers()).json()
    assert after_agent["onboarding"]["step"] == "OPEN_FOLDER"
    assert after_agent["navigation"]["profiles"] == [{"id": "default", "label": "我的 Agent"}]

    open_folder = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "open_folder", "payload": {"path": str(repo)}},
    )
    assert open_folder.status_code == 200
    assert open_folder.json() == {"ok": True}
    after_folder = client.get("/api/v1/workbench", headers=_headers()).json()
    assert after_folder["onboarding"]["step"] == "BIND_API"
    assert after_folder["navigation"]["projects"][0]["label"] == "project-alpha"
    assert after_folder["demo"]["project"]["is_git_repo"] is True
    assert any("src/example.py" in line for line in after_folder["demo"]["project"]["status_summary"])

    raw_key = "sk-" + "test-this-secret-must-not-be-returned"
    bind_api = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "bind_api", "payload": {"provider": "openai", "api_key": raw_key}},
    )
    assert bind_api.status_code == 200
    assert bind_api.json() == {"ok": True}
    assert verifier.calls == [("openai", raw_key)]
    after_key = client.get("/api/v1/workbench", headers=_headers()).json()
    assert raw_key not in str(after_key)
    assert any(raw_key == value for value in keyring.values.values())
    assert after_key["onboarding"]["step"] == "CREATE_THREAD"
    assert after_key["settings"]["credential_statuses"][0]["status"] == "verified"
    assert after_key["settings"]["credential_statuses"][0]["detail"] == "GET /models verified"
    assert {"id": "openai-model-from-api", "label": "OpenAI / openai-model-from-api", "provider": "openai"} in after_key["task"]["models"]

    create_thread = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "create_thread", "payload": {"title": "调试一个权限边界 bug"}},
    )
    assert create_thread.status_code == 200
    assert create_thread.json() == {"ok": True}
    workbench = client.get("/api/v1/workbench", headers=_headers()).json()
    assert workbench["onboarding"]["step"] == "WORKBENCH"
    assert workbench["task"]["run_state"] == "READY"
    assert workbench["navigation"]["threads"][0]["label"] == "调试一个权限边界 bug"
    assert "调试一个权限边界 bug" not in json.dumps(workbench["task"]["messages"], ensure_ascii=False)
    assert "scripted" not in str(workbench)
    assert "当前 demo" not in str(workbench)
    assert workbench["evidence"]["diff"]["files_changed"] == 1
    assert workbench["evidence"]["diff_files"][0]["path"] == "src/example.py"
    assert any(line["kind"] == "delete" and line["content"] == "    return 1" for line in workbench["evidence"]["diff_files"][0]["lines"])
    assert any(line["kind"] == "add" and line["content"] == "    return 2" for line in workbench["evidence"]["diff_files"][0]["lines"])
    assert "src/yagcode/policy/credentials.py" not in str(workbench)


def test_desktop_open_folder_rejects_nonexistent_template_path() -> None:
    client, _services, _verifier, _keyring = _client_and_services()
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "create_agent", "payload": {"name": "我的 Agent"}},
    ).json() == {"ok": True}

    response = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "open_folder", "payload": {"path": "/Users/demo/project-alpha"}},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "reason": "PROJECT_PATH_NOT_FOUND"}


def test_desktop_bind_api_records_real_validation_error_without_storing_key(tmp_path: Path) -> None:
    repo = _make_dirty_git_project(tmp_path)
    client, _services, verifier, keyring = _client_and_services()
    assert client.post("/api/v1/commands", headers=_headers(), json={"type": "create_agent", "payload": {"name": "我的 Agent"}}).json() == {"ok": True}
    assert client.post("/api/v1/commands", headers=_headers(), json={"type": "open_folder", "payload": {"path": str(repo)}}).json() == {"ok": True}

    response = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "bind_api", "payload": {"provider": "njusehub", "api_key": "bad-key"}},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "reason": "PROVIDER_VALIDATION_FAILED"}
    assert verifier.calls == [("njusehub", "bad-key")]
    assert keyring.values == {}
    snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert snapshot["onboarding"]["step"] == "BIND_API"
    njusehub = [item for item in snapshot["settings"]["credential_statuses"] if item["provider"] == "njusehub"][0]
    assert njusehub["status"] == "error"
    assert njusehub["detail"] == "PROVIDER_AUTH_REJECTED"
    assert "bad-key" not in str(snapshot)


def test_desktop_custom_provider_model_theme_and_locale_are_user_controlled(tmp_path: Path) -> None:
    repo = _make_dirty_git_project(tmp_path)
    client, services, verifier, keyring = _client_and_services()
    assert client.post("/api/v1/commands", headers=_headers(), json={"type": "create_agent", "payload": {"name": "我的 Agent"}}).json() == {"ok": True}
    assert client.post("/api/v1/commands", headers=_headers(), json={"type": "open_folder", "payload": {"path": str(repo)}}).json() == {"ok": True}

    add_provider = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={
            "type": "add_custom_provider",
            "payload": {
                "provider": "localise",
                "label": "Local ISE",
                "base_url": "https://localise.invalid/v1/chat/completions",
                "docs_url": "https://localise.invalid/docs",
                "model_id": "localise-coder",
            },
        },
    )
    assert add_provider.json() == {"ok": True}
    assert services._provider_endpoints["localise"].url == "https://localise.invalid/v1/chat/completions"

    bind = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={
            "type": "bind_api",
            "payload": {
                "provider": "localise",
                "api_key": "local-secret",
                "model_id": "localise-pro",
            },
        },
    )
    assert bind.json() == {"ok": True}
    assert verifier.calls[-1] == ("localise", "local-secret")
    assert any("local-secret" == value for value in keyring.values.values())

    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "set_theme_mode", "payload": {"mode": "dark"}},
    ).json() == {"ok": True}
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "set_locale", "payload": {"locale": "en-GB"}},
    ).json() == {"ok": True}

    snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert "local-secret" not in str(snapshot)
    assert snapshot["settings"]["theme_mode"] == "dark"
    assert snapshot["settings"]["locale"] == "en-GB"
    assert any(item["provider"] == "localise" and item["label"] == "Local ISE" for item in snapshot["demo"]["providers"])
    assert {"id": "localise-coder", "label": "Local ISE / localise-coder", "provider": "localise"} in snapshot["task"]["models"]
    assert {"id": "localise-pro", "label": "Local ISE / localise-pro", "provider": "localise"} in snapshot["task"]["models"]
    assert {"id": "localise-model-from-api", "label": "Local ISE / localise-model-from-api", "provider": "localise"} in snapshot["task"]["models"]


def test_desktop_events_endpoint_accepts_sse_subscriptions() -> None:
    client, _services, _verifier, _keyring = _client_and_services()

    response = client.get(
        "/api/v1/events?profile_id=default&last_sequence=0",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_desktop_commands_reject_actions_before_onboarding_requirements() -> None:
    client, _services, _verifier, _keyring = _client_and_services()

    response = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "append_message", "payload": {"text": "补充信息"}},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "reason": "THREAD_NOT_CREATED"}


def test_desktop_commands_update_real_demo_state(tmp_path: Path) -> None:
    repo = _make_clean_bug_project(tmp_path)
    action_provider = _ActionProvider(repo)
    client, _services, _verifier, _keyring = _client_and_services(action_provider=action_provider)

    _bootstrap_desktop_workbench(client, repo)
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={
            "type": "bind_api",
            "payload": {"provider": "njusehub", "api_key": "sk-test-demo-key", "model_id": "kimi-k2.7-code"},
        },
    ).json() == {"ok": True}

    append = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "append_message", "payload": {"text": "复现步骤：点击发送后应显示"}},
    )
    assert append.status_code == 200
    assert append.json() == {"ok": True}
    appended_snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert appended_snapshot["task"]["messages"][-2]["body"] == "复现步骤：点击发送后应显示"
    assert appended_snapshot["task"]["messages"][-1]["body"] == "已收到输入；下一次 Agent step 会把它作为 Provider prompt 的用户上下文。"
    assert appended_snapshot["task"]["provider"] == "njusehub"
    assert appended_snapshot["task"]["model"] == "kimi-k2.7-code"

    resumed = client.post("/api/v1/commands", headers=_headers(), json={"type": "resume_run"})
    assert resumed.status_code == 200
    assert resumed.json() == {"ok": True}
    assert action_provider.contexts[0].provider == "njusehub"
    assert action_provider.contexts[0].model == "kimi-k2.7-code"
    resumed_snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert resumed_snapshot["task"]["run_state"] == "FINISHED"
    assert resumed_snapshot["task"]["provider"] == "njusehub"
    assert resumed_snapshot["task"]["model"] == "kimi-k2.7-code"

    switched = client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "switch_model", "payload": {"provider": "deepseek", "model": "deepseek-chat"}},
    )
    assert switched.status_code == 200
    assert switched.json() == {"ok": True}
    switched_snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert switched_snapshot["task"]["provider"] == "deepseek"
    assert switched_snapshot["task"]["model"] == "deepseek-chat"


def test_desktop_resume_requires_real_user_message_not_thread_title(tmp_path: Path) -> None:
    repo = _make_clean_bug_project(tmp_path)
    action_provider = _ActionProvider(repo)
    client, _services, _verifier, _keyring = _client_and_services(action_provider=action_provider)
    _bootstrap_desktop_workbench(client, repo)

    response = client.post("/api/v1/commands", headers=_headers(), json={"type": "resume_run"})

    assert response.status_code == 200
    assert response.json() == {"ok": False, "reason": "AGENT_INPUT_REQUIRED"}
    assert action_provider.contexts == []


def test_desktop_resume_runs_provider_action_loop_and_refreshes_real_git_diff(tmp_path: Path) -> None:
    repo = _make_clean_bug_project(tmp_path)
    action_provider = _ActionProvider(repo)
    client, _services, _verifier, _keyring = _client_and_services(action_provider=action_provider)
    _bootstrap_desktop_workbench(client, repo)
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "append_message", "payload": {"text": "请修复 src/example.py，让 answer 返回 2。"}},
    ).json() == {"ok": True}

    response = client.post("/api/v1/commands", headers=_headers(), json={"type": "resume_run"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(action_provider.contexts) == 3
    prompt = action_provider.contexts[0].prompt
    assert "请修复 src/example.py，让 answer 返回 2。" in prompt
    assert "调试一个权限边界 bug" not in prompt
    assert (repo / "src" / "example.py").read_text(encoding="utf-8") == "def answer():\n    return 2\n"
    snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert snapshot["task"]["run_state"] == "FINISHED"
    assert snapshot["review_view"]["state"] == "READY"
    assert snapshot["evidence"]["diff"] == {"files_changed": 1, "additions": 1, "deletions": 1}
    assert snapshot["evidence"]["diff_files"][0]["path"] == "src/example.py"
    assert any(line["kind"] == "delete" and line["content"] == "    return 1" for line in snapshot["evidence"]["diff_files"][0]["lines"])
    assert any(line["kind"] == "add" and line["content"] == "    return 2" for line in snapshot["evidence"]["diff_files"][0]["lines"])
    assert any(message["title"] == "Agent step" and "request_review" in message["body"] for message in snapshot["task"]["messages"])


def test_desktop_resume_recovers_unique_expected_text_patch_when_model_line_count_is_wrong(tmp_path: Path) -> None:
    repo = _make_clean_bug_project(tmp_path)
    action_provider = _LineMismatchPatchProvider(repo)
    client, _services, _verifier, _keyring = _client_and_services(action_provider=action_provider)
    _bootstrap_desktop_workbench(client, repo)
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "append_message", "payload": {"text": "请修复 src/example.py，让 answer 返回 2。"}},
    ).json() == {"ok": True}

    response = client.post("/api/v1/commands", headers=_headers(), json={"type": "resume_run"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert (repo / "src" / "example.py").read_text(encoding="utf-8") == "def answer():\n    return 2\n"
    snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert snapshot["task"]["run_state"] == "FINISHED"
    assert snapshot["evidence"]["diff"] == {"files_changed": 1, "additions": 1, "deletions": 1}


def test_desktop_commands_cover_demo_panels_diff_memory_privacy_permissions_and_rollback(tmp_path: Path) -> None:
    repo = _make_dirty_git_project(tmp_path)
    client, _services, _verifier, _keyring = _client_and_services()
    _bootstrap_desktop_workbench(client, repo)

    initial = client.get("/api/v1/workbench", headers=_headers()).json()
    assert initial["evidence"]["diff"] == {"files_changed": 1, "additions": 3, "deletions": 1}
    assert initial["evidence"]["diff_files"][0]["path"] == "src/example.py"
    assert any(line["kind"] == "delete" for line in initial["evidence"]["diff_files"][0]["lines"])
    assert any(line["kind"] == "add" for line in initial["evidence"]["diff_files"][0]["lines"])
    assert initial["demo"]["checkpoints"][0]["current"] is True

    secret = "sk-" + "qwen-secret-must-not-return"
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "bind_api", "payload": {"provider": "qwen", "api_key": secret}},
    ).json() == {"ok": True}
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "delete_api", "payload": {"provider": "openai"}},
    ).json() == {"ok": True}
    api_snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert secret not in str(api_snapshot)
    assert api_snapshot["settings"]["credential_statuses"][0]["status"] == "missing"
    assert api_snapshot["settings"]["credential_statuses"][1]["status"] == "verified"

    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "set_permission_mode", "payload": {"mode": "yes_similar_session"}},
    ).json() == {"ok": True}
    assert client.post("/api/v1/commands", headers=_headers(), json={"type": "confirm_privacy"}).json() == {"ok": True}
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "set_retention", "payload": {"retention": "30d"}},
    ).json() == {"ok": True}
    policy_snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    assert policy_snapshot["demo"]["permissions"]["mode"] == "yes_similar_session"
    assert policy_snapshot["demo"]["privacy"]["preview_confirmed"] is True
    assert policy_snapshot["settings"]["selected_retention"] == "30d"

    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "add_memory", "payload": {"title": "调试偏好", "detail": "先给 diff 再继续。"}},
    ).json() == {"ok": True}
    memory_snapshot = client.get("/api/v1/workbench", headers=_headers()).json()
    added_memory = memory_snapshot["memory"]["project_memories"][-1]
    assert added_memory["title"] == "调试偏好"
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "delete_memory", "payload": {"memory_id": added_memory["id"]}},
    ).json() == {"ok": True}
    after_delete = client.get("/api/v1/workbench", headers=_headers()).json()
    assert all(item["id"] != added_memory["id"] for item in after_delete["memory"]["project_memories"])

    assert client.post("/api/v1/commands", headers=_headers(), json={"type": "accept_review"}).json() == {"ok": True}
    accepted = client.get("/api/v1/workbench", headers=_headers()).json()
    assert accepted["review_view"]["state"] == "ACCEPTED"

    rollback_id = accepted["demo"]["checkpoints"][0]["id"]
    assert client.post(
        "/api/v1/commands",
        headers=_headers(),
        json={"type": "rollback_checkpoint", "payload": {"checkpoint_id": rollback_id}},
    ).json() == {"ok": True}
    rolled_back = client.get("/api/v1/workbench", headers=_headers()).json()
    assert rolled_back["review_view"]["state"] == "RECOVERY_REQUIRED"
    assert rolled_back["evidence"]["diff"] == {"files_changed": 1, "additions": 3, "deletions": 1}
    assert rolled_back["demo"]["checkpoints"][0]["current"] is True
    assert rolled_back["task"]["messages"][-1]["body"].endswith("未对真实工作区执行 Git 回滚。")
