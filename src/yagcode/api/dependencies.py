"""In-memory application services used by governed desktop API routes."""

from __future__ import annotations

import secrets
import subprocess

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Literal, TypeAlias, cast

from starlette.requests import Request

from yagcode.api.desktop_agent import DesktopActionProvider, run_desktop_agent_step
from yagcode.api.schemas import ProjectView, RunView
from yagcode.git.identity import run_git
from yagcode.git.working_tree import ProjectInspection, inspect_project
from yagcode.providers import OfficialEndpoint, load_official_endpoints
from yagcode.providers.runtime_http import HttpJsonActionProvider
from yagcode.providers.validation import (
    HttpProviderCredentialVerifier,
    ProviderCredentialVerifier,
    ProviderVerificationResult,
)
from yagcode.secrets import CredentialBroker
from yagcode.secrets.keyring_adapter import KeyringModuleStore


RunRecordState: TypeAlias = Literal[
    "RUNNING",
    "WAITING_PERMISSION",
    "WAITING_PRIVACY",
    "COMPACTING",
    "STOPPING",
    "INTERRUPTED",
    "STOPPED",
    "FINISHED",
    "FAILED",
]
ProviderStatus: TypeAlias = Literal["verified", "error"]
ThemeMode: TypeAlias = Literal["system", "light", "dark"]
LocaleMode: TypeAlias = Literal["zh-Hans", "zh-Hant", "en-US", "en-GB"]
Clock: TypeAlias = Callable[[], datetime]

BUILT_IN_PROVIDERS = ("openai", "qwen", "glm", "deepseek", "minimax", "kimi", "njusehub")


class ApiDomainError(RuntimeError):
    def __init__(self, reason_code: str, *, http_status: int = 409) -> None:
        self.reason_code = reason_code
        self.http_status = http_status
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class Checkpoint:
    thread_id: str
    kind: Literal["PLAN_REQUIRED", "PLAN_BYPASS"]


@dataclass(slots=True)
class CheckpointStore:
    _records: list[Checkpoint] = field(default_factory=list)

    def append(self, checkpoint: Checkpoint) -> None:
        self._records.append(checkpoint)

    def last(self, thread_id: str) -> Checkpoint:
        for checkpoint in reversed(self._records):
            if checkpoint.thread_id == thread_id:
                return checkpoint
        raise ApiDomainError("CHECKPOINT_NOT_FOUND", http_status=404)


@dataclass(slots=True)
class PermissionState:
    full_access_enabled: bool = False


@dataclass(frozen=True, slots=True)
class ThreadRecord:
    thread_id: str
    project_id: str
    title: str
    plan_enabled: bool
    state: Literal["READY", "RUNNING", "STOPPED"] = "READY"


@dataclass(slots=True)
class RunRecord:
    run_id: str
    project_id: str
    thread_id: str
    model: str
    generation: int
    state: RunRecordState


@dataclass(frozen=True, slots=True)
class IntentChallenge:
    intent_id: str
    intent_type: str
    one_time_token: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class PrivilegedActionResult:
    intent_id: str
    intent_type: str
    state: Literal["EXECUTED"]


@dataclass(frozen=True, slots=True)
class DemoMessage:
    message_id: str
    role: Literal["user", "assistant", "system"]
    title: str
    body: str
    at: str


@dataclass(frozen=True, slots=True)
class DemoAuditEntry:
    entry_id: str
    title: str
    detail: str
    at: str


@dataclass(frozen=True, slots=True)
class DemoMemoryItem:
    memory_id: str
    title: str
    detail: str
    pinned: bool


@dataclass(frozen=True, slots=True)
class DemoFileSnapshot:
    relative_path: str
    content: bytes | None


@dataclass(frozen=True, slots=True)
class DemoCheckpoint:
    checkpoint_id: str
    label: str
    detail: str
    current: bool
    files: tuple[DemoFileSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeProviderBinding:
    provider: str
    status: ProviderStatus
    updated_at: str
    detail: str
    docs_url: str
    credential_stored: bool
    models: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeProviderDefinition:
    provider: str
    label: str
    method: str
    url: str
    docs_url: str


@dataclass(slots=True)
class DesktopDemoState:
    agent_name: str | None = None
    selected_provider: str = "openai"
    selected_model: str = "gpt-5.6-sol"
    theme_mode: ThemeMode = "system"
    locale: LocaleMode = "zh-Hans"
    plan_mode: bool = True
    project_path: str | None = None
    project_id: str | None = None
    thread_id: str | None = None
    last_run_id: str | None = None
    configured_providers: dict[str, RuntimeProviderBinding] = field(default_factory=dict)
    custom_providers: dict[str, RuntimeProviderDefinition] = field(default_factory=dict)
    provider_models: dict[str, tuple[str, ...]] = field(default_factory=dict)
    custom_models: dict[str, tuple[str, ...]] = field(default_factory=dict)
    project_inspection: ProjectInspection | None = None
    retention: str = "permanent"
    privacy_preview_confirmed: bool = False
    permission_mode: str = "yes_once"
    review_state: str = "NOT_READY"
    diff_active: bool = False
    selected_panel: str = "审查"
    _next_message: int = 0
    _next_audit: int = 0
    _next_memory: int = 0
    _next_checkpoint: int = 0
    messages: list[DemoMessage] = field(default_factory=list)
    audit_entries: list[DemoAuditEntry] = field(default_factory=list)
    memories: list[DemoMemoryItem] = field(default_factory=list)
    checkpoints: list[DemoCheckpoint] = field(default_factory=list)

    def append_message(
        self,
        *,
        role: Literal["user", "assistant", "system"],
        title: str,
        body: str,
    ) -> DemoMessage:
        self._next_message += 1
        message = DemoMessage(
            message_id=f"msg-{self._next_message}",
            role=role,
            title=title,
            body=body,
            at=f"2026-07-26T00:00:{self._next_message:02d}Z",
        )
        self.messages.append(message)
        return message

    def append_audit(self, *, title: str, detail: str) -> DemoAuditEntry:
        self._next_audit += 1
        entry = DemoAuditEntry(
            entry_id=f"audit-{self._next_audit}",
            title=title,
            detail=detail,
            at=f"2026-07-26T00:01:{self._next_audit:02d}Z",
        )
        self.audit_entries.insert(0, entry)
        return entry

    def append_memory(self, *, title: str, detail: str, pinned: bool = False) -> DemoMemoryItem:
        self._next_memory += 1
        item = DemoMemoryItem(
            memory_id=f"memory-{self._next_memory}",
            title=title,
            detail=detail,
            pinned=pinned,
        )
        self.memories.append(item)
        return item

    def replace_memory(self, memory_id: str, *, title: str, detail: str, pinned: bool) -> None:
        self.memories = [
            DemoMemoryItem(memory_id=item.memory_id, title=title, detail=detail, pinned=pinned)
            if item.memory_id == memory_id
            else item
            for item in self.memories
        ]

    def delete_memory(self, memory_id: str) -> None:
        self.memories = [item for item in self.memories if item.memory_id != memory_id]

    def append_checkpoint(
        self,
        *,
        label: str,
        detail: str,
        current: bool = True,
        files: tuple[DemoFileSnapshot, ...] = (),
    ) -> DemoCheckpoint:
        self._next_checkpoint += 1
        if current:
            self.checkpoints = [
                DemoCheckpoint(
                    checkpoint_id=item.checkpoint_id,
                    label=item.label,
                    detail=item.detail,
                    current=False,
                    files=item.files,
                )
                for item in self.checkpoints
            ]
        checkpoint = DemoCheckpoint(
            checkpoint_id=f"checkpoint-{self._next_checkpoint}",
            label=label,
            detail=detail,
            current=current,
            files=files,
        )
        self.checkpoints.append(checkpoint)
        return checkpoint

    def clear_thread_state(self) -> None:
        self.thread_id = None
        self.last_run_id = None
        self.messages.clear()
        self.review_state = "NOT_READY"
        self.diff_active = False
        self.checkpoints.clear()


@dataclass(slots=True)
class IntentStore:
    _next_intent: int = 0
    _records: dict[str, IntentChallenge] = field(default_factory=dict)

    def create(self, intent_type: str, resource_id: str) -> IntentChallenge:
        self._next_intent += 1
        intent = IntentChallenge(
            intent_id=f"intent-{self._next_intent}",
            intent_type=intent_type,
            one_time_token=secrets.token_urlsafe(16),
            resource_id=resource_id,
        )
        self._records[intent.intent_id] = intent
        return intent

    def consume(self, intent_id: str, one_time_token: str) -> PrivilegedActionResult:
        intent = self._records.get(intent_id)
        if intent is None:
            raise ApiDomainError("INTENT_NOT_FOUND", http_status=404)
        if not secrets.compare_digest(intent.one_time_token, one_time_token):
            raise ApiDomainError("INTENT_TOKEN_INVALID", http_status=403)
        del self._records[intent_id]
        return PrivilegedActionResult(intent.intent_id, intent.intent_type, "EXECUTED")


class Services:
    def __init__(
        self,
        profile_id: str = "default",
        *,
        credential_broker: CredentialBroker | None = None,
        provider_verifier: ProviderCredentialVerifier | None = None,
        action_provider: DesktopActionProvider | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.profile_id = profile_id
        self._clock = clock if clock is not None else _utc_now
        self._provider_endpoints = load_official_endpoints()
        self.credentials = credential_broker or CredentialBroker(
            KeyringModuleStore(),
            clock=self._clock,
        )
        self.provider_verifier = provider_verifier or HttpProviderCredentialVerifier(
            endpoints=self._provider_endpoints,
            clock=self._clock,
        )
        self.action_provider = action_provider or HttpJsonActionProvider(
            endpoints=self._provider_endpoints,
            credentials=self.credentials,
            profile_id=self.profile_id,
        )
        self.checkpoints = CheckpointStore()
        self.permissions = PermissionState()
        self.intents = IntentStore()
        self.desktop_demo = DesktopDemoState()
        self._next_project = 0
        self._next_thread = 0
        self._next_run = 0
        self._projects: dict[str, ProjectView] = {}
        self._threads: dict[str, ThreadRecord] = {}
        self._runs: dict[str, RunRecord] = {}
        self._active_run_by_project: dict[str, str] = {}

    def create_project(self, name: str) -> ProjectView:
        self._next_project += 1
        project = ProjectView(kind="project", project_id=f"project-{self._next_project}", name=name)
        self._projects[project.project_id] = project
        return project

    def create_thread(self, project_id: str, *, title: str, plan_enabled: bool) -> ThreadRecord:
        if project_id not in self._projects:
            raise ApiDomainError("PROJECT_NOT_FOUND", http_status=404)
        self._next_thread += 1
        thread = ThreadRecord(f"thread-{self._next_thread}", project_id, title, plan_enabled)
        self._threads[thread.thread_id] = thread
        self.checkpoints.append(
            Checkpoint(thread.thread_id, "PLAN_REQUIRED" if plan_enabled else "PLAN_BYPASS")
        )
        return thread

    def start_run(self, thread_id: str, *, model: str) -> RunView:
        thread = self._threads.get(thread_id)
        if thread is None:
            raise ApiDomainError("THREAD_NOT_FOUND", http_status=404)
        if thread.project_id in self._active_run_by_project:
            raise ApiDomainError("PROJECT_RUN_ACTIVE")
        self._next_run += 1
        run = RunRecord(f"run-{self._next_run}", thread.project_id, thread.thread_id, model, 0, "RUNNING")
        self._runs[run.run_id] = run
        self._active_run_by_project[thread.project_id] = run.run_id
        return RunView(kind="run", run_id=run.run_id, state=run.state, generation=run.generation)

    def stop_run(self, run_id: str) -> RunRecord:
        run = self._runs.get(run_id)
        if run is None:
            raise ApiDomainError("RUN_NOT_FOUND", http_status=404)
        run.state = "STOPPED"
        self._active_run_by_project.pop(run.project_id, None)
        return run

    def switch_model(self, run_id: str, *, model: str) -> RunRecord:
        run = self._runs.get(run_id)
        if run is None:
            raise ApiDomainError("RUN_NOT_FOUND", http_status=404)
        if run.state not in {"STOPPED", "FINISHED", "FAILED"}:
            raise ApiDomainError("RUN_MUST_STOP_BEFORE_MODEL_SWITCH")
        run.model = model
        run.generation += 1
        return run

    def blocking_runs(self) -> tuple[RunRecord, ...]:
        blocking_states = {
            "RUNNING",
            "WAITING_PERMISSION",
            "WAITING_PRIVACY",
            "COMPACTING",
            "STOPPING",
            "INTERRUPTED",
        }
        return tuple(
            run for run in self._runs.values() if run.state in blocking_states
        )

    def desktop_demo_step(
        self,
    ) -> Literal["CREATE_AGENT", "OPEN_FOLDER", "BIND_API", "CREATE_THREAD", "WORKBENCH"]:
        state = self.desktop_demo
        if state.agent_name is None:
            return "CREATE_AGENT"
        if state.project_id not in self._projects:
            return "OPEN_FOLDER"
        if not self._has_verified_provider():
            return "BIND_API"
        if state.thread_id not in self._threads:
            return "CREATE_THREAD"
        return "WORKBENCH"

    def desktop_demo_records(self) -> tuple[ProjectView | None, ThreadRecord | None, RunRecord | None]:
        state = self.desktop_demo
        project = self._projects.get(state.project_id or "")
        thread = self._threads.get(state.thread_id or "")
        run = self._runs.get(state.last_run_id or "")
        return project, thread, run

    def create_demo_agent(self, name: str) -> None:
        normalized = name.strip()
        if not normalized:
            raise ApiDomainError("AGENT_NAME_REQUIRED", http_status=400)
        self.desktop_demo = DesktopDemoState(agent_name=normalized)
        self.desktop_demo.append_audit(title="创建 AGENT", detail=normalized)

    def delete_demo_agent(self) -> None:
        self._active_run_by_project.clear()
        self.desktop_demo = DesktopDemoState()

    def register_demo_project(self, path: str) -> None:
        if self.desktop_demo.agent_name is None:
            raise ApiDomainError("AGENT_NOT_CREATED")
        normalized = path.strip()
        if not normalized:
            raise ApiDomainError("PROJECT_PATH_REQUIRED", http_status=400)
        inspection = inspect_project(normalized)
        if inspection.error in {"PROJECT_PATH_NOT_FOUND", "PROJECT_PATH_NOT_DIRECTORY"}:
            raise ApiDomainError(inspection.error, http_status=400)
        label = inspection.label or _path_label(normalized)
        project = self.create_project(label)
        self.desktop_demo.project_id = project.project_id
        self.desktop_demo.project_path = inspection.path
        self.desktop_demo.project_inspection = inspection
        self.desktop_demo.clear_thread_state()
        git_detail = (
            f"{label} · git:{inspection.branch or 'detached'}"
            if inspection.is_git_repo
            else f"{label} · 非 Git 仓库"
        )
        self.desktop_demo.append_audit(title="打开文件夹", detail=git_detail)

    def refresh_demo_project_inspection(self) -> ProjectInspection | None:
        path = self.desktop_demo.project_path
        if path is None:
            return None
        inspection = inspect_project(path)
        self.desktop_demo.project_inspection = inspection
        return inspection

    def delete_demo_project(self) -> None:
        project = self._projects.get(self.desktop_demo.project_id or "")
        if project is None:
            raise ApiDomainError("PROJECT_NOT_OPENED")
        self._active_run_by_project.pop(project.project_id, None)
        self.desktop_demo.project_id = None
        self.desktop_demo.project_path = None
        self.desktop_demo.clear_thread_state()
        self.desktop_demo.append_audit(title="关闭项目", detail=project.name)

    def configure_demo_provider(
        self,
        provider: str,
        api_key: str,
        *,
        label: str | None = None,
        base_url: str | None = None,
        docs_url: str | None = None,
        model_id: str | None = None,
    ) -> None:
        if self.desktop_demo.project_id not in self._projects:
            raise ApiDomainError("PROJECT_NOT_OPENED")
        normalized_provider = _provider_id(provider)
        if normalized_provider not in self._provider_endpoints:
            self.register_custom_provider(
                provider=normalized_provider,
                label=label or normalized_provider,
                base_url=base_url or "",
                docs_url=docs_url or "",
            )
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ApiDomainError("API_KEY_REQUIRED", http_status=400)
        result = self.provider_verifier.verify(normalized_provider, normalized_key)
        binding = self._binding_from_verification(result, credential_stored=False)
        if result.ok:
            self.credentials.enroll(self.profile_id, normalized_provider, normalized_key)
            binding = self._binding_from_verification(result, credential_stored=True)
            self.desktop_demo.configured_providers[normalized_provider] = binding
            if result.models:
                self.desktop_demo.provider_models[normalized_provider] = result.models
            self.add_custom_model(normalized_provider, model_id or "")
            self.desktop_demo.selected_provider = normalized_provider
            if model_id and model_id.strip():
                self.desktop_demo.selected_model = model_id.strip()
            elif result.models:
                self.desktop_demo.selected_model = result.models[0]
            self.desktop_demo.append_audit(
                title="绑定 API",
                detail=f"{normalized_provider} 已通过真实 provider 校验并写入 keyring。",
            )
            return
        self.desktop_demo.configured_providers[normalized_provider] = binding
        self.desktop_demo.append_audit(title="绑定 API 失败", detail=f"{normalized_provider}: {result.detail}")
        raise ApiDomainError("PROVIDER_VALIDATION_FAILED", http_status=400)

    def create_demo_thread(self, title: str) -> RunRecord:
        project = self._projects.get(self.desktop_demo.project_id or "")
        if project is None:
            raise ApiDomainError("PROJECT_NOT_OPENED")
        if not self._has_verified_provider():
            raise ApiDomainError("PROVIDER_NOT_CONFIGURED")
        normalized = title.strip()
        if not normalized:
            raise ApiDomainError("THREAD_TITLE_REQUIRED", http_status=400)
        thread = self.create_thread(project.project_id, title=normalized, plan_enabled=self.desktop_demo.plan_mode)
        self.desktop_demo.thread_id = thread.thread_id
        self.desktop_demo.last_run_id = None
        inspection = self.refresh_demo_project_inspection()
        has_diff = bool(inspection and inspection.diff_files)
        self.desktop_demo.review_state = "READY" if has_diff else "INCOMPLETE"
        self.desktop_demo.diff_active = has_diff
        self.desktop_demo.messages.clear()
        self.desktop_demo.append_message(
            role="assistant",
            title="本地工作台",
            body=(
                "线程已创建。线程名称只作为界面元数据，不会发给模型；"
                "请在输入框发送真实任务内容后再启动 Agent step。"
            ),
        )
        if not self.desktop_demo.memories:
            self.desktop_demo.append_memory(
                title="项目默认偏好",
                detail="默认中文沟通；每个 bug 修完后展示 diff 和验证证据。",
                pinned=True,
            )
        if not self.desktop_demo.checkpoints:
            self.desktop_demo.append_checkpoint(
                label="当前 Git 状态",
                detail="打开项目并创建线程后的真实工作区快照。",
                current=True,
                files=_capture_project_snapshot(self.desktop_demo.project_path),
            )
        self.desktop_demo.append_audit(title="创建线程", detail=f"{thread.thread_id} -> READY")
        return RunRecord(
            run_id="",
            project_id=project.project_id,
            thread_id=thread.thread_id,
            model=self.desktop_demo.selected_model,
            generation=0,
            state="STOPPED",
        )

    def delete_demo_thread(self) -> None:
        thread = self._threads.get(self.desktop_demo.thread_id or "")
        if thread is None:
            raise ApiDomainError("THREAD_NOT_CREATED")
        self._active_run_by_project.pop(thread.project_id, None)
        self.desktop_demo.clear_thread_state()
        self.desktop_demo.append_audit(title="删除线程", detail=thread.title)

    def append_demo_context(self, text: str) -> None:
        if self.desktop_demo.thread_id not in self._threads:
            raise ApiDomainError("THREAD_NOT_CREATED")
        normalized = text.strip()
        if not normalized:
            raise ApiDomainError("APPEND_MESSAGE_EMPTY", http_status=400)
        user_message_count = sum(1 for message in self.desktop_demo.messages if message.role == "user")
        self.desktop_demo.append_message(
            role="user",
            title="任务输入" if user_message_count == 0 else "追加信息",
            body=normalized,
        )
        self.desktop_demo.append_message(
            role="assistant",
            title="Sidecar",
            body="已收到输入；下一次 Agent step 会把它作为 Provider prompt 的用户上下文。",
        )
        self.desktop_demo.append_audit(title="追加信息", detail="renderer 通过 /api/v1/commands 提交了追加上下文。")

    def stop_demo_run(self) -> RunRecord:
        project = self._projects.get(self.desktop_demo.project_id or "")
        if project is None or self.desktop_demo.thread_id not in self._threads:
            raise ApiDomainError("THREAD_NOT_CREATED")
        active_run_id = self._active_run_by_project.get(project.project_id)
        if active_run_id is None:
            raise ApiDomainError("NO_ACTIVE_RUN", http_status=409)
        run = self.stop_run(active_run_id)
        self.desktop_demo.last_run_id = run.run_id
        self.desktop_demo.append_message(
            role="system",
            title="运行状态",
            body="已停止当前 run，项目锁释放；现在允许切换模型。",
        )
        self.desktop_demo.append_audit(title="停止 run", detail=f"{run.run_id} -> STOPPED")
        return run

    def resume_demo_run(self) -> RunRecord:
        project = self._projects.get(self.desktop_demo.project_id or "")
        thread = self._threads.get(self.desktop_demo.thread_id or "")
        if project is None or thread is None:
            raise ApiDomainError("THREAD_NOT_CREATED")
        if project.project_id in self._active_run_by_project:
            raise ApiDomainError("PROJECT_RUN_ACTIVE", http_status=409)
        user_messages = tuple(message.body for message in self.desktop_demo.messages if message.role == "user")
        if not user_messages:
            raise ApiDomainError("AGENT_INPUT_REQUIRED", http_status=400)
        project_path = self.desktop_demo.project_path
        if project_path is None:
            raise ApiDomainError("PROJECT_NOT_OPENED")
        provider_id = self.desktop_demo.selected_provider
        binding = self.desktop_demo.configured_providers.get(provider_id)
        if binding is None or binding.status != "verified":
            raise ApiDomainError("PROVIDER_NOT_CONFIGURED")
        run_view = self.start_run(thread.thread_id, model=self.desktop_demo.selected_model)
        run = self._runs[run_view.run_id]
        self.desktop_demo.last_run_id = run.run_id
        self.desktop_demo.append_message(
            role="system",
            title="运行状态",
            body=f"正在使用 {provider_id} / {run.model} 请求 Provider 并执行受控 action。",
        )
        self.desktop_demo.append_audit(title="启动 run", detail=f"{run.run_id} -> RUNNING")
        result = run_desktop_agent_step(
            provider=self.action_provider,
            run_id=run.run_id,
            generation=run.generation,
            provider_id=provider_id,
            model=run.model,
            project_root=Path(project_path),
            user_messages=user_messages,
        )
        self._active_run_by_project.pop(project.project_id, None)
        run.state = result.status
        self.refresh_demo_project_inspection()
        if result.status == "FINISHED":
            self.desktop_demo.review_state = "READY"
            self.desktop_demo.diff_active = True
            self.desktop_demo.append_checkpoint(
                label=f"{run.run_id} 候选修改",
                detail=f"Provider calls: {result.provider_calls}; patches applied: {result.patches_applied}",
                current=True,
                files=_capture_project_snapshot(self.desktop_demo.project_path),
            )
            self.desktop_demo.append_message(
                role="assistant",
                title="Agent step",
                body=(
                    f"真实 Provider action 已完成：{result.reason_code}；"
                    f"provider 调用 {result.provider_calls} 次，执行 action {result.actions_executed} 次，"
                    f"apply_patch {result.patches_applied} 次。最后观察：{result.observations[-1] if result.observations else '无'}"
                ),
            )
            self.desktop_demo.append_audit(title="完成 run", detail=f"{run.run_id} -> FINISHED")
            return run
        self.desktop_demo.review_state = "INCOMPLETE"
        self.desktop_demo.append_message(
            role="system",
            title="运行失败",
            body=(
                f"Agent step 未生成可审查修改：{result.reason_code}；"
                f"provider 调用 {result.provider_calls} 次，执行 action {result.actions_executed} 次。"
            ),
        )
        self.desktop_demo.append_audit(title="运行失败", detail=f"{run.run_id} -> {result.reason_code}")
        return run

    def switch_demo_model(self, model: str, *, provider: str | None = None) -> RunRecord | None:
        project = self._projects.get(self.desktop_demo.project_id or "")
        thread = self._threads.get(self.desktop_demo.thread_id or "")
        run = self._runs.get(self.desktop_demo.last_run_id or "")
        if project is None or thread is None:
            raise ApiDomainError("THREAD_NOT_CREATED")
        if project.project_id in self._active_run_by_project:
            raise ApiDomainError("RUN_MUST_STOP_BEFORE_MODEL_SWITCH", http_status=409)
        if not model.strip():
            raise ApiDomainError("MODEL_REQUIRED", http_status=400)
        normalized_provider = _provider_id(provider) if provider is not None else self.desktop_demo.selected_provider
        if normalized_provider not in self._provider_endpoints:
            raise ApiDomainError("PROVIDER_UNSUPPORTED", http_status=400)
        self.desktop_demo.selected_provider = normalized_provider
        self.desktop_demo.selected_model = model.strip()
        if run is not None and run.state in {"STOPPED", "FINISHED", "FAILED"}:
            run = self.switch_model(run.run_id, model=self.desktop_demo.selected_model)
        self.desktop_demo.append_message(
            role="system",
            title="模型切换",
            body=f"已切换到 {self.desktop_demo.selected_provider} / {self.desktop_demo.selected_model}；恢复运行后从新 generation 继续。",
        )
        self.desktop_demo.append_audit(title="切换模型", detail=f"{self.desktop_demo.selected_provider}/{self.desktop_demo.selected_model}")
        return run

    def set_demo_plan_mode(self, enabled: bool) -> None:
        self.desktop_demo.plan_mode = enabled
        self.desktop_demo.append_audit(
            title="Plan 模式",
            detail="已开启" if enabled else "已关闭",
        )

    def delete_demo_provider(self, provider: str) -> None:
        normalized_provider = _provider_id(provider)
        if normalized_provider not in self._provider_endpoints:
            raise ApiDomainError("PROVIDER_UNSUPPORTED", http_status=400)
        binding = self.desktop_demo.configured_providers.pop(normalized_provider, None)
        if binding is not None and binding.credential_stored:
            self.credentials.clear(self.profile_id, normalized_provider)
        self.desktop_demo.append_audit(title="删除 API 绑定", detail=normalized_provider)

    def register_custom_provider(self, *, provider: str, label: str, base_url: str, docs_url: str) -> None:
        normalized_provider = _provider_id(provider)
        normalized_label = label.strip() or normalized_provider
        normalized_url = base_url.strip()
        normalized_docs = docs_url.strip() or normalized_url
        if normalized_provider in BUILT_IN_PROVIDERS:
            return
        if not normalized_url.startswith("https://") or "\x00" in normalized_url:
            raise ApiDomainError("PROVIDER_BASE_URL_INVALID", http_status=400)
        if "\x00" in normalized_docs:
            raise ApiDomainError("PROVIDER_DOCS_URL_INVALID", http_status=400)
        self._provider_endpoints[normalized_provider] = OfficialEndpoint(
            method="POST",
            url=normalized_url,
            docs_url=normalized_docs,
            retrieved_at="runtime",
        )
        self.desktop_demo.custom_providers[normalized_provider] = RuntimeProviderDefinition(
            provider=normalized_provider,
            label=normalized_label,
            method="POST",
            url=normalized_url,
            docs_url=normalized_docs,
        )
        self.desktop_demo.append_audit(title="新增自定义 Provider", detail=f"{normalized_provider} -> {normalized_url}")

    def add_custom_model(self, provider: str, model_id: str) -> None:
        normalized_provider = _provider_id(provider)
        normalized_model = model_id.strip()
        if not normalized_model:
            return
        if normalized_provider not in self._provider_endpoints:
            raise ApiDomainError("PROVIDER_UNSUPPORTED", http_status=400)
        if "\x00" in normalized_model or len(normalized_model) > 256:
            raise ApiDomainError("MODEL_INVALID", http_status=400)
        existing = self.desktop_demo.custom_models.get(normalized_provider, ())
        if normalized_model not in existing:
            self.desktop_demo.custom_models[normalized_provider] = (*existing, normalized_model)
        self.desktop_demo.append_audit(title="新增自定义模型", detail=f"{normalized_provider}/{normalized_model}")

    def set_demo_theme_mode(self, mode: str) -> None:
        if mode not in {"system", "light", "dark"}:
            raise ApiDomainError("THEME_MODE_INVALID", http_status=400)
        self.desktop_demo.theme_mode = cast(ThemeMode, mode)
        self.desktop_demo.append_audit(title="主题", detail=mode)

    def set_demo_locale(self, locale: str) -> None:
        if locale not in {"zh-Hans", "zh-Hant", "en-US", "en-GB"}:
            raise ApiDomainError("LOCALE_INVALID", http_status=400)
        self.desktop_demo.locale = cast(LocaleMode, locale)
        self.desktop_demo.append_audit(title="语言", detail=locale)

    def add_demo_memory(self, title: str, detail: str) -> None:
        normalized_title = title.strip()
        normalized_detail = detail.strip()
        if not normalized_title or not normalized_detail:
            raise ApiDomainError("MEMORY_REQUIRED", http_status=400)
        item = self.desktop_demo.append_memory(
            title=normalized_title,
            detail=normalized_detail,
            pinned=False,
        )
        self.desktop_demo.append_audit(title="新增记忆", detail=item.title)

    def delete_demo_memory(self, memory_id: str) -> None:
        before = len(self.desktop_demo.memories)
        self.desktop_demo.delete_memory(memory_id)
        if len(self.desktop_demo.memories) == before:
            raise ApiDomainError("MEMORY_NOT_FOUND", http_status=404)
        self.desktop_demo.append_audit(title="删除记忆", detail=memory_id)

    def confirm_demo_privacy(self) -> None:
        self.desktop_demo.privacy_preview_confirmed = True
        self.desktop_demo.append_audit(title="隐私预览", detail="已永久确认首次发送预览。")

    def set_demo_retention(self, retention: str) -> None:
        if retention not in {"permanent", "30d", "60d", "90d", "180d", "1y", "2y"}:
            raise ApiDomainError("RETENTION_INVALID", http_status=400)
        self.desktop_demo.retention = retention
        self.desktop_demo.append_audit(title="保留期限", detail=retention)

    def set_demo_permission_mode(self, mode: str) -> None:
        if mode not in {"yes_once", "yes_similar_session", "full_access"}:
            raise ApiDomainError("PERMISSION_MODE_INVALID", http_status=400)
        self.desktop_demo.permission_mode = mode
        self.desktop_demo.append_audit(title="权限模式", detail=mode)

    def rollback_demo_checkpoint(self, checkpoint_id: str) -> None:
        target_checkpoint = next(
            (item for item in self.desktop_demo.checkpoints if item.checkpoint_id == checkpoint_id),
            None,
        )
        if target_checkpoint is None:
            raise ApiDomainError("CHECKPOINT_NOT_FOUND", http_status=404)
        restored_files = _restore_project_snapshot(self.desktop_demo.project_path, target_checkpoint)
        inspection = self.refresh_demo_project_inspection()
        remaining = len(inspection.diff_files) if inspection is not None else 0
        self.desktop_demo.diff_active = remaining > 0
        self.desktop_demo.review_state = "RECOVERY_REQUIRED"
        self.desktop_demo.checkpoints = [
            DemoCheckpoint(
                checkpoint_id=item.checkpoint_id,
                label=item.label,
                detail=item.detail,
                current=item.checkpoint_id == checkpoint_id,
                files=item.files,
            )
            for item in self.desktop_demo.checkpoints
        ]
        self.desktop_demo.append_message(
            role="system",
            title="回滚",
            body=f"已恢复 {checkpoint_id}；真实工作区恢复了 {restored_files} 个文件。",
        )
        self.desktop_demo.append_audit(title="回滚", detail=f"{checkpoint_id}; remaining diff files: {remaining}")

    def accept_demo_review(self) -> None:
        if self.desktop_demo.review_state not in {"READY", "RECOVERY_REQUIRED"}:
            raise ApiDomainError("REVIEW_NOT_READY")
        self.desktop_demo.review_state = "ACCEPTED"
        self.desktop_demo.append_audit(title="审查接受", detail="可信确认后接受当前候选。")

    def reject_demo_review(self) -> None:
        self.desktop_demo.review_state = "REJECTED"
        self.desktop_demo.diff_active = False
        self.desktop_demo.append_message(
            role="system",
            title="审查",
            body="已拒绝当前审查项；如需撤回候选修改，请执行 rollback。",
        )
        self.desktop_demo.append_audit(title="审查拒绝", detail="当前候选已拒绝。")

    def open_demo_panel(self, panel: str) -> None:
        self.desktop_demo.selected_panel = panel
        self.desktop_demo.append_audit(title="打开面板", detail=panel)

    def _has_verified_provider(self) -> bool:
        return any(binding.status == "verified" for binding in self.desktop_demo.configured_providers.values())

    def _binding_from_verification(
        self,
        result: ProviderVerificationResult,
        *,
        credential_stored: bool,
    ) -> RuntimeProviderBinding:
        endpoint = self._provider_endpoints[result.provider]
        return RuntimeProviderBinding(
            provider=result.provider,
            status=result.status,
            updated_at=result.checked_at.isoformat().replace("+00:00", "Z"),
            detail=result.detail,
            docs_url=endpoint.docs_url,
            credential_stored=credential_stored,
            models=result.models,
        )


def _path_label(path: str) -> str:
    candidate = PureWindowsPath(path) if "\\" in path or ":" in path else PurePosixPath(path)
    return candidate.name or "当前项目"


def _provider_id(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "\x00" in normalized or len(normalized) > 64:
        raise ApiDomainError("PROVIDER_ID_INVALID", http_status=400)
    if not all(character.isalnum() or character in {"-", "_"} for character in normalized):
        raise ApiDomainError("PROVIDER_ID_INVALID", http_status=400)
    return normalized


def _utc_now() -> datetime:
    return datetime.now(UTC)


def get_services(request: Request) -> Services:
    services = getattr(request.app.state, "services", None)
    if not isinstance(services, Services):
        raise ApiDomainError("SERVICES_UNAVAILABLE", http_status=500)
    return services


def _capture_project_snapshot(project_path: str | None) -> tuple[DemoFileSnapshot, ...]:
    if project_path is None:
        return ()
    root = Path(project_path)
    try:
        listing = run_git(root, "ls-files", "-co", "--exclude-standard", "-z").stdout
    except (OSError, subprocess.CalledProcessError):
        return ()
    snapshots: list[DemoFileSnapshot] = []
    for relative_path in listing.split("\0"):
        if not relative_path:
            continue
        target = _snapshot_target(root, relative_path)
        if target is None:
            continue
        try:
            content = target.read_bytes() if target.is_file() and not target.is_symlink() else None
        except OSError:
            content = None
        snapshots.append(DemoFileSnapshot(relative_path=relative_path, content=content))
    return tuple(snapshots)


def _restore_project_snapshot(project_path: str | None, checkpoint: DemoCheckpoint) -> int:
    if project_path is None:
        raise ApiDomainError("PROJECT_NOT_OPENED")
    root = Path(project_path)
    snapshot = {item.relative_path: item.content for item in checkpoint.files}
    inspection = inspect_project(project_path)
    if inspection.diff_files and not checkpoint.files:
        raise ApiDomainError("CHECKPOINT_SNAPSHOT_MISSING", http_status=409)
    restored = 0
    for diff_file in inspection.diff_files:
        target = _snapshot_target(root, diff_file.path)
        if target is None:
            raise ApiDomainError("CHECKPOINT_PATH_UNSAFE", http_status=400)
        content = snapshot.get(diff_file.path)
        try:
            if content is None:
                if target.exists():
                    target.unlink()
                    restored += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != content:
                target.write_bytes(content)
                restored += 1
        except OSError as error:
            raise ApiDomainError("CHECKPOINT_RESTORE_FAILED", http_status=500) from error
    return restored


def _snapshot_target(root: Path, relative_path: str) -> Path | None:
    if relative_path == "" or Path(relative_path).is_absolute():
        return None
    relative = Path(relative_path)
    if any(part in {"", ".", ".."} for part in relative.parts):
        return None
    try:
        trusted_root = root.resolve(strict=True)
    except OSError:
        return None
    target = (trusted_root / relative).resolve(strict=False)
    if not target.is_relative_to(trusted_root):
        return None
    return target


__all__ = [
    "ApiDomainError",
    "Checkpoint",
    "CheckpointStore",
    "IntentChallenge",
    "PermissionState",
    "PrivilegedActionResult",
    "RunRecord",
    "RunRecordState",
    "Services",
    "ThreadRecord",
    "DemoAuditEntry",
    "DemoMessage",
    "get_services",
]
