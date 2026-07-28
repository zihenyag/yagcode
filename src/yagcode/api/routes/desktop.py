from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from yagcode.api.dependencies import Services, get_services
from yagcode.api.schemas import ReviewView
from yagcode.git.working_tree import ProjectInspection


router = APIRouter()

BlockingRunState = Literal[
    "RUNNING",
    "WAITING_PERMISSION",
    "WAITING_PRIVACY",
    "COMPACTING",
    "STOPPING",
    "INTERRUPTED",
]
ConnectionState = Literal["connected", "disconnected", "resync-required"]
ValidationStatus = Literal["passed", "failed", "running", "pending", "warning"]
OnboardingStep = Literal["CREATE_AGENT", "OPEN_FOLDER", "BIND_API", "CREATE_THREAD", "WORKBENCH"]
ThemeMode = Literal["system", "light", "dark"]
LocaleMode = Literal["zh-Hans", "zh-Hant", "en-US", "en-GB"]
DiffLineKind = Literal["context", "add", "delete", "hunk"]
ReviewState = Literal[
    "NOT_READY",
    "INCOMPLETE",
    "READY",
    "ACCEPTING",
    "ACCEPTED",
    "REJECTED",
    "CONFLICT",
    "RECOVERY_REQUIRED",
]


class NavigationProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    label: str


class NavigationProjectView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    label: str
    active: bool


class NavigationThreadView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    label: str
    unread_approvals: int = Field(ge=0)
    memory_suggestions: int = Field(ge=0)


class NavigationView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profiles: tuple[NavigationProfileView, ...]
    projects: tuple[NavigationProjectView, ...]
    threads: tuple[NavigationThreadView, ...]
    run_state: str


class OnboardingView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step: OnboardingStep
    completed_steps: tuple[OnboardingStep, ...]
    headline: str
    detail: str


class ModelOptionView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    label: str
    provider: str


class BudgetView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token_limit: int = Field(gt=0)
    time_limit_minutes: int = Field(gt=0)


class RetryPolicyView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection_retries: int = Field(ge=0)
    tool_retries: int = Field(ge=0)
    model_retries: int = Field(ge=0)


class TaskErrorView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: str
    side_effect_state: str
    scope: str
    recovery: str


class MessageView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    role: Literal["user", "assistant", "system"]
    title: str
    body: str
    at: str


class TaskWorkbenchView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    thread_id: str
    title: str
    run_state: str
    provider: str
    model: str
    models: tuple[ModelOptionView, ...]
    plan_mode: bool
    budget: BudgetView
    retry_policy: RetryPolicyView
    compact_after_lines: int = Field(gt=0)
    append_enabled: bool
    messages: tuple[MessageView, ...]
    error: TaskErrorView | None = None


class DiffView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    files_changed: int = Field(ge=0)
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)


class DiffLineView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: DiffLineKind
    old_line: int | None
    new_line: int | None
    content: str


class DiffFileView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    status: Literal["modified", "added", "deleted"]
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    lines: tuple[DiffLineView, ...]


class ValidationView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    title: str
    detail: str
    status: ValidationStatus
    command: str


class ApprovalActionView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    label: str
    enabled: bool
    high_risk: bool


class EvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    diff: DiffView
    diff_files: tuple[DiffFileView, ...]
    validations: tuple[ValidationView, ...]
    risks: tuple[str, ...]
    uncovered: tuple[str, ...]
    approval_actions: tuple[ApprovalActionView, ...]


class CredentialStatusView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str
    status: Literal["verified", "missing", "error"]
    updated_at: str | None
    detail: str
    docs_url: str


class SettingsView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    credential_statuses: tuple[CredentialStatusView, ...]
    retention_options: tuple[str, ...]
    selected_retention: str
    theme_mode: ThemeMode
    locale: LocaleMode
    theme_options: tuple[dict[str, str], ...]
    locale_options: tuple[dict[str, str], ...]


class ProjectMemoryView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    title: str
    detail: str
    pinned: bool


class CrossProjectSuggestionView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    title: str
    detail: str


class MemoryView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_memories: tuple[ProjectMemoryView, ...]
    cross_project_suggestions: tuple[CrossProjectSuggestionView, ...]


class AuditEntryView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    title: str
    detail: str
    at: str


class AuditView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entries: tuple[AuditEntryView, ...]


class ProviderDemoView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str
    label: str
    configured: bool
    status: Literal["verified", "missing", "error"]
    updated_at: str | None
    detail: str
    docs_url: str


class ProjectRuntimeView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    label: str
    is_git_repo: bool
    git_root: str | None
    branch: str | None
    status_summary: tuple[str, ...]
    error: str | None


class PrivacyPreviewItemView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    category: str
    source: str
    preview: str
    confirmed: bool


class PrivacyView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preview_confirmed: bool
    retention: str
    preview_items: tuple[PrivacyPreviewItemView, ...]


class PermissionOptionView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    label: str
    detail: str
    active: bool


class PermissionsView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: str
    options: tuple[PermissionOptionView, ...]


class CheckpointView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    label: str
    detail: str
    current: bool


class DemoStateView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selected_panel: str
    theme_mode: ThemeMode
    locale: LocaleMode
    agent_name: str | None
    project_path: str | None
    project: ProjectRuntimeView | None
    providers: tuple[ProviderDemoView, ...]
    privacy: PrivacyView
    permissions: PermissionsView
    checkpoints: tuple[CheckpointView, ...]


class WorkbenchSnapshotView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile_id: str
    generation: int = Field(ge=0)
    last_sequence: int = Field(ge=0)
    connection: ConnectionState
    onboarding: OnboardingView
    navigation: NavigationView
    task: TaskWorkbenchView
    review_view: ReviewView
    evidence: EvidenceView
    settings: SettingsView
    memory: MemoryView
    audit: AuditView
    demo: DemoStateView


class WorkbenchCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: str = Field(min_length=1)
    payload: Any = None


class WorkbenchCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ok: bool
    reason: str | None = None


class BlockingRunView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    state: BlockingRunState
    title: str


class BlockingRunsView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    runs: tuple[BlockingRunView, ...]


def _builtin_model_options() -> tuple[tuple[str, str, str], ...]:
    return (
        ("gpt-5.6-sol", "OpenAI gpt-5.6-sol", "openai"),
        ("gpt-5.6-terra", "OpenAI gpt-5.6-terra", "openai"),
        ("qwen-turbo", "Qwen Turbo", "qwen"),
        ("qwen-plus", "Qwen Plus", "qwen"),
        ("qwen-max", "Qwen Max", "qwen"),
        ("qwen3-coder-plus", "Qwen3 Coder Plus", "qwen"),
        ("glm-4.5", "GLM 4.5", "glm"),
        ("glm-4.5-air", "GLM 4.5 Air", "glm"),
        ("glm-5.2", "GLM 5.2", "glm"),
        ("deepseek-chat", "DeepSeek Chat", "deepseek"),
        ("deepseek-reasoner", "DeepSeek Reasoner", "deepseek"),
        ("minimax-m2.5", "MiniMax M2.5", "minimax"),
        ("minimax-m3", "MiniMax M3", "minimax"),
        ("kimi-k2.7-code", "Kimi K2.7 Code", "kimi"),
        ("kimi-k3", "Kimi K3", "kimi"),
        ("glm-5.2", "NJU SE Hub / GLM 5.2", "njusehub"),
        ("qwen-turbo", "NJU SE Hub / Qwen Turbo", "njusehub"),
        ("deepseek-v4-pro", "NJU SE Hub / DeepSeek V4 Pro", "njusehub"),
        ("MiniMax-M2.5", "NJU SE Hub / MiniMax M2.5", "njusehub"),
        ("MiniMax/MiniMax-M3", "NJU SE Hub / MiniMax M3", "njusehub"),
        ("kimi-k2.7-code", "NJU SE Hub / Kimi K2.7 Code", "njusehub"),
        ("kimi/kimi-k3", "NJU SE Hub / Kimi K3", "njusehub"),
    )


def _default_models(services: Services | None = None) -> tuple[ModelOptionView, ...]:
    models: list[ModelOptionView] = [
        ModelOptionView(id=model_id, label=label, provider=provider)
        for model_id, label, provider in _builtin_model_options()
    ]
    if services is not None:
        labels = _provider_labels(services)
        all_dynamic_providers = set(services.desktop_demo.provider_models) | set(services.desktop_demo.custom_models)
        for provider in sorted(all_dynamic_providers):
            model_ids = (
                *services.desktop_demo.provider_models.get(provider, ()),
                *services.desktop_demo.custom_models.get(provider, ()),
            )
            provider_label = labels.get(provider, provider)
            for model_id in model_ids:
                models.append(ModelOptionView(id=model_id, label=f"{provider_label} / {model_id}", provider=provider))
    deduped: list[ModelOptionView] = []
    seen: set[tuple[str, str]] = set()
    for model in models:
        key = (model.provider, model.id)
        if key in seen:
            continue
        deduped.append(model)
        seen.add(key)
    return tuple(deduped)


def _provider_labels(services: Services | None = None) -> dict[str, str]:
    labels = {
        "openai": "OpenAI",
        "qwen": "Qwen",
        "glm": "GLM",
        "deepseek": "DeepSeek",
        "minimax": "MiniMax",
        "kimi": "Kimi / Moonshot",
        "njusehub": "NJU SE Hub",
    }
    if services is not None:
        labels.update({provider: definition.label for provider, definition in services.desktop_demo.custom_providers.items()})
    return labels


def _provider_for_model(model: str, services: Services | None = None) -> str:
    for option in _default_models(services):
        if option.id == model:
            return option.provider
    return "openai"


def _credential_statuses(services: Services) -> tuple[CredentialStatusView, ...]:
    configured = services.desktop_demo.configured_providers
    labels = _provider_labels(services)
    return tuple(
        CredentialStatusView(
            provider=provider,
            status=configured[provider].status if provider in configured else "missing",
            updated_at=configured[provider].updated_at if provider in configured else None,
            detail=configured[provider].detail if provider in configured else "尚未绑定",
            docs_url=configured[provider].docs_url
            if provider in configured
            else services._provider_endpoints[provider].docs_url,
        )
        for provider in labels
    )


def _provider_views(services: Services) -> tuple[ProviderDemoView, ...]:
    labels = _provider_labels(services)
    configured = services.desktop_demo.configured_providers
    return tuple(
        ProviderDemoView(
            provider=provider,
            label=labels[provider],
            configured=provider in configured and configured[provider].status == "verified",
            status=configured[provider].status if provider in configured else "missing",
            updated_at=configured[provider].updated_at if provider in configured else None,
            detail=configured[provider].detail if provider in configured else "尚未绑定",
            docs_url=configured[provider].docs_url
            if provider in configured
            else services._provider_endpoints[provider].docs_url,
        )
        for provider in labels
    )


def _onboarding_view(step: OnboardingStep) -> OnboardingView:
    order: tuple[OnboardingStep, ...] = (
        "CREATE_AGENT",
        "OPEN_FOLDER",
        "BIND_API",
        "CREATE_THREAD",
        "WORKBENCH",
    )
    headlines = {
        "CREATE_AGENT": "创建 AGENT 档案",
        "OPEN_FOLDER": "打开一个本地项目文件夹",
        "BIND_API": "绑定至少一个模型 Provider",
        "CREATE_THREAD": "创建第一个 bug 修复线程",
        "WORKBENCH": "进入本地 Agent 工作台",
    }
    details = {
        "CREATE_AGENT": "首次启动为空状态；先创建一个属于当前账号的 Agent/档案。",
        "OPEN_FOLDER": "项目必须显式打开，后续线程、权限、记忆和审查都挂在该项目下。",
        "BIND_API": "Key 只进入受控 sidecar 状态；snapshot、日志和界面不会回显原始 key。",
        "CREATE_THREAD": "一个项目同一时间只运行一个线程；运行中追加信息，停止后才允许换模型。",
        "WORKBENCH": "可以调试对话、Plan、模型、权限、记忆、隐私、审查、Diff 和回滚。",
    }
    index = order.index(step)
    return OnboardingView(
        step=step,
        completed_steps=order[:index],
        headline=headlines[step],
        detail=details[step],
    )


def _task_title(step: OnboardingStep, thread_title: str | None) -> str:
    if thread_title:
        return thread_title
    return {
        "CREATE_AGENT": "先创建 AGENT",
        "OPEN_FOLDER": "打开项目后才能创建线程",
        "BIND_API": "绑定 API 后才能运行 Agent",
        "CREATE_THREAD": "创建第一个线程",
        "WORKBENCH": "本地工作台",
    }[step]


def _review_summary(services: Services, step: OnboardingStep) -> str:
    state = services.desktop_demo
    if step != "WORKBENCH":
        return "尚未创建线程。完成 onboarding 后这里会读取真实项目 Git 状态与 Changes。"
    if state.review_state == "ACCEPTED":
        return "候选修改已接受；checkpoint 和审计记录可用于回档。"
    if state.review_state == "REJECTED":
        return "候选修改已拒绝；diff 已撤销，等待继续运行。"
    if state.review_state == "RECOVERY_REQUIRED":
        return "已执行回滚；当前需要重新运行或追加信息后再生成 diff。"
    if state.diff_active:
        return "检测到真实项目 Git diff。先检查红绿行、验证证据和风险，再决定下一步。"
    return "当前真实项目没有可显示的 Git diff；可以追加 bug 信息或启动真实 Agent step。"


def _review_state(value: str) -> ReviewState:
    if value not in {
        "NOT_READY",
        "INCOMPLETE",
        "READY",
        "ACCEPTING",
        "ACCEPTED",
        "REJECTED",
        "CONFLICT",
        "RECOVERY_REQUIRED",
    }:
        raise RuntimeError("INVALID_REVIEW_STATE")
    return cast(ReviewState, value)


def _diff_files(inspection: ProjectInspection | None, active: bool) -> tuple[DiffFileView, ...]:
    if not active or inspection is None:
        return ()
    return tuple(
        DiffFileView(
            path=file.path,
            status=file.status,
            additions=file.additions,
            deletions=file.deletions,
            lines=tuple(
                DiffLineView(
                    kind=line.kind,
                    old_line=line.old_line,
                    new_line=line.new_line,
                    content=line.content,
                )
                for line in file.lines
            ),
        )
        for file in inspection.diff_files
    )


def _validations(
    step: OnboardingStep,
    diff_active: bool,
    inspection: ProjectInspection | None,
    services: Services,
) -> tuple[ValidationView, ...]:
    onboarding_status: ValidationStatus = "passed" if step == "WORKBENCH" else "running"
    diff_status: ValidationStatus = "passed" if diff_active else "pending"
    provider_status: ValidationStatus = "passed" if services._has_verified_provider() else "pending"
    git_detail = (
        f"{inspection.label} · {inspection.branch or '无分支'} · {len(inspection.status_summary)} status 行"
        if inspection is not None and inspection.is_git_repo
        else "项目不是 Git 仓库，无法生成真实 Git diff。"
    )
    return (
        ValidationView(
            id="sidecar",
            title="真实 sidecar",
            detail="/api/v1/workbench 由本地 FastAPI sidecar 提供，并在每次命令后重新拉取。",
            status="passed",
            command="GET /api/v1/workbench",
        ),
        ValidationView(
            id="onboarding",
            title="本地 onboarding 状态机",
            detail="创建 AGENT → 打开文件夹 → 绑定 API → 创建线程。",
            status=onboarding_status,
            command="POST /api/v1/commands",
        ),
        ValidationView(
            id="provider",
            title="Provider API 绑定",
            detail="绑定 key 时会向对应 provider 发起轻量 GET /models 校验；自动化测试使用 fake verifier。",
            status=provider_status,
            command="GET /models",
        ),
        ValidationView(
            id="diff-preview",
            title="真实 Git Diff 预览",
            detail=git_detail,
            status=diff_status,
            command="git diff --no-ext-diff --unified=3 HEAD --",
        ),
    )


def _permission_options(mode: str) -> tuple[PermissionOptionView, ...]:
    options = (
        (
            "yes_once",
            "Yes once",
            "仅批准当前这一次 action；下一次相似 action 仍需确认。",
        ),
        (
            "yes_similar_session",
            "Yes to similar actions for this app session",
            "在整个应用会话内批准相似 action；关闭应用后失效。",
        ),
        (
            "full_access",
            "Full access for this app session",
            "整个应用会话内授予完全访问；适合用户明确接管风险的本地调试。",
        ),
    )
    return tuple(
        PermissionOptionView(id=option_id, label=label, detail=detail, active=option_id == mode)
        for option_id, label, detail in options
    )


def _demo_view(services: Services) -> DemoStateView:
    state = services.desktop_demo
    project = state.project_inspection
    return DemoStateView(
        selected_panel=state.selected_panel,
        theme_mode=state.theme_mode,
        locale=state.locale,
        agent_name=state.agent_name,
        project_path=state.project_path,
        project=None
        if project is None
        else ProjectRuntimeView(
            path=project.path,
            label=project.label,
            is_git_repo=project.is_git_repo,
            git_root=project.git_root,
            branch=project.branch,
            status_summary=project.status_summary,
            error=project.error,
        ),
        providers=_provider_views(services),
        privacy=PrivacyView(
            preview_confirmed=state.privacy_preview_confirmed,
            retention=state.retention,
            preview_items=(
                PrivacyPreviewItemView(
                    id="conversation",
                    category="原始对话和工具输出",
                    source="当前线程首次发送",
                    preview="将发送：任务标题、追加信息、工具摘要；凭据值会遮蔽。",
                    confirmed=state.privacy_preview_confirmed,
                ),
                PrivacyPreviewItemView(
                    id="credential-preview",
                    category="凭据/隐私片段",
                    source="首次读取敏感文件时",
                    preview="示例：sk-****、token=****、/Users/.../private-file",
                    confirmed=state.privacy_preview_confirmed,
                ),
            ),
        ),
        permissions=PermissionsView(
            mode=state.permission_mode,
            options=_permission_options(state.permission_mode),
        ),
        checkpoints=tuple(
            CheckpointView(
                id=checkpoint.checkpoint_id,
                label=checkpoint.label,
                detail=checkpoint.detail,
                current=checkpoint.current,
            )
            for checkpoint in state.checkpoints
        ),
    )


def _snapshot_for_preview(services: Services) -> WorkbenchSnapshotView:
    inspection = services.refresh_demo_project_inspection()
    step = services.desktop_demo_step()
    onboarding = _onboarding_view(step)
    project, thread, run = services.desktop_demo_records()
    run_state = run.state if run is not None else ("READY" if thread is not None else "IDLE")
    selected_model = services.desktop_demo.selected_model if run is None else run.model
    selected_provider = services.desktop_demo.selected_provider
    diff_active = bool(inspection and inspection.diff_files)
    services.desktop_demo.diff_active = diff_active
    if step == "WORKBENCH" and services.desktop_demo.review_state not in {
        "ACCEPTED",
        "REJECTED",
        "RECOVERY_REQUIRED",
    }:
        services.desktop_demo.review_state = "READY" if diff_active else "INCOMPLETE"
    diff_files = _diff_files(inspection, diff_active)
    diff_additions = sum(file.additions for file in diff_files)
    diff_deletions = sum(file.deletions for file in diff_files)
    return WorkbenchSnapshotView(
        profile_id=services.profile_id,
        generation=1,
        last_sequence=1,
        connection="connected",
        onboarding=onboarding,
        navigation=NavigationView(
            profiles=()
            if services.desktop_demo.agent_name is None
            else (NavigationProfileView(id=services.profile_id, label=services.desktop_demo.agent_name),),
            projects=()
            if project is None
            else (NavigationProjectView(id=project.project_id, label=project.name, active=True),),
            threads=(
                NavigationThreadView(
                    id=thread.thread_id,
                    label=thread.title,
                    unread_approvals=1 if diff_active else 0,
                    memory_suggestions=0,
                ),
            )
            if thread is not None
            else (),
            run_state=run_state,
        ),
        task=TaskWorkbenchView(
            thread_id=thread.thread_id if thread is not None else "",
            title=_task_title(step, thread.title if thread is not None else None),
            run_state=run_state,
            provider=selected_provider,
            model=selected_model,
            models=_default_models(services),
            plan_mode=services.desktop_demo.plan_mode,
            budget=BudgetView(token_limit=1500, time_limit_minutes=60),
            retry_policy=RetryPolicyView(
                connection_retries=5,
                tool_retries=3,
                model_retries=5,
            ),
            compact_after_lines=1500,
            append_enabled=step == "WORKBENCH",
            messages=tuple(
                MessageView(
                    id=message.message_id,
                    role=message.role,
                    title=message.title,
                    body=message.body,
                    at=message.at,
                )
                for message in services.desktop_demo.messages
            ),
            error=None,
        ),
        review_view=ReviewView(
            kind="review",
            review_id="review-1",
            state=_review_state(services.desktop_demo.review_state),
            generation=1,
            summary=_review_summary(services, step),
        ),
        evidence=EvidenceView(
            diff=DiffView(
                files_changed=len(diff_files),
                additions=diff_additions,
                deletions=diff_deletions,
            ),
            diff_files=diff_files,
            validations=_validations(step, diff_active, inspection, services),
            risks=(
                "Changes 只读取真实 Git diff；未跟踪文件暂不读取内容，避免首次隐私预览前泄露。",
            ),
            uncovered=("Release 打包和 GitHub Pages 落地页不属于当前桌面联调范围。",),
            approval_actions=()
            if step != "WORKBENCH"
            else (
                ApprovalActionView(
                    id="accept_review",
                    label="接受当前候选",
                    enabled=services.desktop_demo.review_state in {"READY", "RECOVERY_REQUIRED"},
                    high_risk=False,
                ),
                ApprovalActionView(
                    id="reject_review",
                    label="拒绝当前候选",
                    enabled=services.desktop_demo.review_state in {"READY", "RECOVERY_REQUIRED", "ACCEPTED"},
                    high_risk=False,
                ),
            ),
        ),
        settings=SettingsView(
            credential_statuses=_credential_statuses(services),
            retention_options=("permanent", "30d", "60d", "90d", "180d", "1y", "2y"),
            selected_retention=services.desktop_demo.retention,
            theme_mode=services.desktop_demo.theme_mode,
            locale=services.desktop_demo.locale,
            theme_options=(
                {"id": "system", "label": "跟随系统"},
                {"id": "light", "label": "Light"},
                {"id": "dark", "label": "Dark"},
            ),
            locale_options=(
                {"id": "zh-Hans", "label": "中文（简体）"},
                {"id": "zh-Hant", "label": "中文（繁體）"},
                {"id": "en-US", "label": "English (US)"},
                {"id": "en-GB", "label": "English (UK)"},
            ),
        ),
        memory=MemoryView(
            project_memories=tuple(
                ProjectMemoryView(
                    id=item.memory_id,
                    title=item.title,
                    detail=item.detail,
                    pinned=item.pinned,
                )
                for item in services.desktop_demo.memories
            ),
            cross_project_suggestions=(
                CrossProjectSuggestionView(
                    id="suggestion-1",
                    title="跨项目记忆候选",
                    detail="这个偏好可以进入跨项目 memory；确认不阻塞当前 run。",
                ),
            )
            if step == "WORKBENCH"
            else (),
        ),
        audit=AuditView(
            entries=tuple(
                AuditEntryView(
                    id=entry.entry_id,
                    title=entry.title,
                    detail=entry.detail,
                    at=entry.at,
                )
                for entry in services.desktop_demo.audit_entries
            ),
        ),
        demo=_demo_view(services),
    )


async def _preview_event_stream() -> AsyncIterator[str]:
    yield ": connected\n\n"


def _blocking_run_state(state: str) -> BlockingRunState:
    if state not in {
        "RUNNING",
        "WAITING_PERMISSION",
        "WAITING_PRIVACY",
        "COMPACTING",
        "STOPPING",
        "INTERRUPTED",
    }:
        raise RuntimeError("NON_BLOCKING_RUN_RETURNED")
    return cast(BlockingRunState, state)


@router.get("/workbench", response_model=WorkbenchSnapshotView)
def workbench_snapshot(services: Services = Depends(get_services)) -> WorkbenchSnapshotView:
    return _snapshot_for_preview(services)


@router.get("/events")
def events(_services: Services = Depends(get_services)) -> StreamingResponse:
    return StreamingResponse(_preview_event_stream(), media_type="text/event-stream")


def _payload_record(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _payload_text(value: object) -> str:
    payload = _payload_record(value)
    text = payload.get("text")
    return text if isinstance(text, str) else ""


def _payload_string(value: object, key: str) -> str:
    payload = _payload_record(value)
    text = payload.get(key)
    return text if isinstance(text, str) else ""


def _payload_model(value: object) -> str:
    return _payload_string(value, "model")


def _payload_provider(value: object) -> str | None:
    return _payload_string(value, "provider") or None


def _payload_provider_definition(value: object) -> tuple[str, str | None, str | None, str | None, str | None]:
    payload = _payload_record(value)
    provider = _payload_string(payload, "provider")
    label = _payload_string(payload, "label") or None
    base_url = _payload_string(payload, "base_url") or None
    docs_url = _payload_string(payload, "docs_url") or None
    model_id = _payload_string(payload, "model_id") or None
    return provider, label, base_url, docs_url, model_id


def _payload_enabled(value: object) -> bool:
    payload = _payload_record(value)
    enabled = payload.get("enabled")
    return enabled if isinstance(enabled, bool) else True


def _handle_review_intent(services: Services, payload: object) -> None:
    action_id = _payload_string(payload, "actionId") or _payload_string(payload, "action_id")
    if action_id == "accept_review":
        services.accept_demo_review()
    elif action_id == "reject_review":
        services.reject_demo_review()
    else:
        raise RuntimeError("REVIEW_INTENT_UNSUPPORTED")


@router.post("/commands", response_model=WorkbenchCommandResult, response_model_exclude_none=True)
def commands(
    request: WorkbenchCommandRequest,
    services: Services = Depends(get_services),
) -> WorkbenchCommandResult:
    try:
        if request.type == "create_agent":
            services.create_demo_agent(_payload_string(request.payload, "name"))
        elif request.type == "delete_agent":
            services.delete_demo_agent()
        elif request.type in {"open_folder", "create_project"}:
            services.register_demo_project(_payload_string(request.payload, "path"))
        elif request.type == "delete_project":
            services.delete_demo_project()
        elif request.type == "bind_api":
            provider, label, base_url, docs_url, model_id = _payload_provider_definition(request.payload)
            services.configure_demo_provider(
                provider,
                _payload_string(request.payload, "api_key"),
                label=label,
                base_url=base_url,
                docs_url=docs_url,
                model_id=model_id,
            )
        elif request.type == "delete_api":
            services.delete_demo_provider(_payload_string(request.payload, "provider"))
        elif request.type == "add_custom_provider":
            provider, label, base_url, docs_url, model_id = _payload_provider_definition(request.payload)
            services.register_custom_provider(provider=provider, label=label or provider, base_url=base_url or "", docs_url=docs_url or "")
            services.add_custom_model(provider, model_id or "")
        elif request.type == "add_custom_model":
            services.add_custom_model(_payload_string(request.payload, "provider"), _payload_model(request.payload))
        elif request.type == "create_thread":
            services.create_demo_thread(_payload_string(request.payload, "title"))
        elif request.type == "delete_thread":
            services.delete_demo_thread()
        elif request.type == "append_message":
            services.append_demo_context(_payload_text(request.payload))
        elif request.type == "stop_run":
            services.stop_demo_run()
        elif request.type == "resume_run":
            services.resume_demo_run()
        elif request.type == "switch_model":
            services.switch_demo_model(_payload_model(request.payload), provider=_payload_provider(request.payload))
        elif request.type == "set_plan_mode":
            services.set_demo_plan_mode(_payload_enabled(request.payload))
        elif request.type == "add_memory":
            services.add_demo_memory(
                _payload_string(request.payload, "title"),
                _payload_string(request.payload, "detail"),
            )
        elif request.type == "delete_memory":
            services.delete_demo_memory(_payload_string(request.payload, "memory_id"))
        elif request.type == "confirm_privacy":
            services.confirm_demo_privacy()
        elif request.type == "set_retention":
            services.set_demo_retention(_payload_string(request.payload, "retention"))
        elif request.type == "set_theme_mode":
            services.set_demo_theme_mode(_payload_string(request.payload, "mode"))
        elif request.type == "set_locale":
            services.set_demo_locale(_payload_string(request.payload, "locale"))
        elif request.type == "set_permission_mode":
            services.set_demo_permission_mode(_payload_string(request.payload, "mode"))
        elif request.type == "rollback_checkpoint":
            services.rollback_demo_checkpoint(_payload_string(request.payload, "checkpoint_id"))
        elif request.type == "accept_review":
            services.accept_demo_review()
        elif request.type == "reject_review":
            services.reject_demo_review()
        elif request.type == "review_intent":
            _handle_review_intent(services, request.payload)
        elif request.type in {
            "choose_project",
            "choose_thread",
            "open_search",
            "open_profile_menu",
            "open_panel",
            "history_back",
            "history_forward",
        }:
            if request.type == "open_panel":
                services.open_demo_panel(_payload_string(request.payload, "panel"))
            services.desktop_demo.append_audit(title="UI 操作", detail=request.type)
        else:
            return WorkbenchCommandResult(ok=False, reason="COMMAND_UNSUPPORTED")
    except Exception as error:
        reason = getattr(error, "reason_code", None)
        return WorkbenchCommandResult(ok=False, reason=reason if isinstance(reason, str) else "COMMAND_FAILED")
    return WorkbenchCommandResult(ok=True)


@router.get("/desktop/blocking-runs", response_model=BlockingRunsView)
def blocking_runs(services: Services = Depends(get_services)) -> BlockingRunsView:
    return BlockingRunsView(
        runs=tuple(
            BlockingRunView(id=run.run_id, state=_blocking_run_state(run.state), title=run.thread_id)
            for run in services.blocking_runs()
        )
    )


__all__ = ["router"]
