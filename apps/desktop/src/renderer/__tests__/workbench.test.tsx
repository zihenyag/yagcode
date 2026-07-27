import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";
import { reviewFixture } from "@yagcode/contracts/fixtures";
import type { TaskModel } from "../api/adapters.js";

interface LoadedWorkbenchModule {
  App: React.ComponentType<{ client: unknown }>;
}

interface LoadedTaskPaneModule {
  ModelSelector: React.ComponentType<{
    runState: string;
    provider: string;
    model: string;
    models: readonly { id: string; label: string; provider: string }[];
    onChange?: (provider: string, model: string) => void;
  }>;
  TaskPane: React.ComponentType<{
    model: TaskModel;
    onCommand(command: { type: string; payload?: unknown }): void;
  }>;
}

async function loadWorkbenchProduction(): Promise<LoadedWorkbenchModule> {
  const modulePath = "../App";
  try {
    return (await import(modulePath)) as LoadedWorkbenchModule;
  } catch (error) {
    throw new Error(`RENDERER_PRODUCTION_MISSING:${modulePath}`, { cause: error });
  }
}

async function loadTaskPaneProduction(): Promise<LoadedTaskPaneModule> {
  const modulePath = "../views/TaskPane";
  try {
    return (await import(modulePath)) as LoadedTaskPaneModule;
  } catch (error) {
    throw new Error(`RENDERER_PRODUCTION_MISSING:${modulePath}`, { cause: error });
  }
}

afterEach(() => cleanup());

function readRendererStyles(): string {
  return readFileSync(resolve(process.cwd(), "src/renderer/styles.css"), "utf8");
}

function fixtureSnapshot(reviewState = "READY") {
  return {
    profile_id: "profile-1",
    generation: 2,
    last_sequence: 7,
    connection: "connected",
    onboarding: {
      step: "WORKBENCH",
      completed_steps: ["CREATE_AGENT", "OPEN_FOLDER", "BIND_API", "CREATE_THREAD"],
      headline: "进入本地 Agent 工作台",
      detail: "可以调试对话、Plan、模型、权限、记忆、隐私、审查、Diff 和回滚。",
    },
    navigation: {
      profiles: [{ id: "profile-1", label: "默认档案" }],
      projects: [{ id: "project-1", label: "yagcode", active: true }],
      threads: [{ id: "thread-1", label: "修复权限 bug", unread_approvals: 1, memory_suggestions: 2 }],
      run_state: "INTERRUPTED",
    },
    task: {
      thread_id: "thread-1",
      title: "修复权限 bug",
      run_state: "INTERRUPTED",
      provider: "openai",
      model: "gpt-5.6-sol",
      models: [
        { id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" },
        { id: "gpt-5.6-terra", label: "OpenAI gpt-5.6-terra", provider: "openai" },
        { id: "qwen-plus", label: "Qwen Plus", provider: "qwen" },
        { id: "glm-4.5", label: "GLM 4.5", provider: "glm" },
        { id: "deepseek-chat", label: "DeepSeek Chat", provider: "deepseek" },
        { id: "glm-5.2", label: "NJU SE Hub / GLM 5.2", provider: "njusehub" },
        { id: "kimi-k2.7-code", label: "Kimi K2.7 Code", provider: "kimi" },
        { id: "kimi-k2.7-code", label: "NJU SE Hub / Kimi K2.7 Code", provider: "njusehub" },
      ],
      plan_mode: true,
      budget: { token_limit: 1500, time_limit_minutes: 60 },
      retry_policy: { connection_retries: 5, tool_retries: 3, model_retries: 5 },
      compact_after_lines: 1500,
      append_enabled: true,
      messages: [
        { id: "msg-1", role: "user", title: "用户请求", body: "修复权限 bug", at: "2026-07-24T00:00:00Z" },
        { id: "msg-2", role: "assistant", title: "Agent 运行", body: "已连接本地 sidecar。", at: "2026-07-24T00:00:01Z" },
      ],
      error: {
        reason: "sidecar 心跳超时",
        side_effect_state: "未写入工作区",
        scope: "当前线程",
        recovery: "重新连接后从最后 sequence 同步",
      },
    },
    review_view: { ...reviewFixture, state: reviewState },
    evidence: {
      diff: { files_changed: 1, additions: 3, deletions: 1 },
      diff_files: [
        {
          path: "src/example.py",
          status: "modified",
          additions: 3,
          deletions: 1,
          lines: [
            { kind: "hunk", old_line: null, new_line: null, content: "@@ -1,2 +1,3 @@" },
            { kind: "context", old_line: 1, new_line: 1, content: "def answer():" },
            { kind: "delete", old_line: 2, new_line: null, content: "    return 1" },
            { kind: "add", old_line: null, new_line: 2, content: "    return 2" },
            { kind: "add", old_line: null, new_line: 3, content: "" },
            { kind: "add", old_line: null, new_line: 4, content: "print(answer())" },
          ],
        },
      ],
      validations: [
        { id: "test", title: "单元测试", detail: "pytest 通过", status: "passed", command: "pytest" },
        { id: "windows", title: "Windows full suite", detail: "等待复验", status: "warning", command: "npm run test:all" },
      ],
      risks: ["真实 Provider 未接入此测试"],
      uncovered: ["未覆盖发布流程"],
      approval_actions: [
        { id: "accept_review", label: "接受当前候选", enabled: true, high_risk: false },
        { id: "reject_review", label: "拒绝当前候选", enabled: true, high_risk: false },
      ],
    },
    settings: {
      credential_statuses: [
        {
          provider: "openai",
          status: "verified",
          updated_at: "2026-07-24T00:00:00Z",
          detail: "GET /models verified",
          docs_url: "https://platform.openai.com/docs/api-reference/responses",
        },
        {
          provider: "qwen",
          status: "missing",
          updated_at: null,
          detail: "尚未绑定",
          docs_url: "https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope",
        },
      ],
      retention_options: ["permanent", "30d", "60d", "90d", "180d", "1y", "2y"],
      selected_retention: "permanent",
      theme_mode: "system",
      locale: "zh-Hans",
      theme_options: [
        { id: "system", label: "跟随系统" },
        { id: "light", label: "Light" },
        { id: "dark", label: "Dark" },
      ],
      locale_options: [
        { id: "zh-Hans", label: "中文（简体）" },
        { id: "zh-Hant", label: "中文（繁體）" },
        { id: "en-US", label: "English (US)" },
        { id: "en-GB", label: "English (UK)" },
      ],
    },
    memory: {
      project_memories: [{ id: "memory-1", title: "项目内偏好", detail: "默认中文沟通", pinned: true }],
      cross_project_suggestions: [{ id: "suggestion-1", title: "跨项目候选", detail: "需要用户确认进入 memory" }],
    },
    audit: {
      entries: [{ id: "audit-1", title: "权限审批", detail: "yes once", at: "2026-07-24T00:00:00Z" }],
    },
    demo: {
      selected_panel: "审查",
      theme_mode: "system",
      locale: "zh-Hans",
      agent_name: "默认档案" as string | null,
      project_path: "/Users/demo/yagcode" as string | null,
      project: {
        path: "/Users/demo/yagcode",
        label: "yagcode",
        is_git_repo: true,
        git_root: "/Users/demo/yagcode",
        branch: "main",
        status_summary: ["## main", " M src/example.py", "?? notes.txt"],
        error: null,
      },
      providers: [
        {
          provider: "openai",
          label: "OpenAI",
          configured: true,
          status: "verified",
          updated_at: "2026-07-24T00:00:00Z",
          detail: "GET /models verified",
          docs_url: "https://platform.openai.com/docs/api-reference/responses",
        },
        {
          provider: "qwen",
          label: "Qwen",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "尚未绑定",
          docs_url: "https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope",
        },
        {
          provider: "glm",
          label: "GLM",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "尚未绑定",
          docs_url: "https://docs.bigmodel.cn/api-reference/model-api/chat-completion",
        },
        {
          provider: "deepseek",
          label: "DeepSeek",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "尚未绑定",
          docs_url: "https://api-docs.deepseek.com/api/create-chat-completion",
        },
        {
          provider: "minimax",
          label: "MiniMax",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "尚未绑定",
          docs_url: "https://platform.minimaxi.com/document/ChatCompletion%20v2",
        },
        {
          provider: "kimi",
          label: "Kimi / Moonshot",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "尚未绑定",
          docs_url: "https://platform.moonshot.cn/docs/api/chat",
        },
        {
          provider: "njusehub",
          label: "NJU SE Hub",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "尚未绑定",
          docs_url: "https://dongshao.github.io/GAIHub1/njusehubdoc.html",
        },
      ],
      privacy: {
        preview_confirmed: false,
        retention: "permanent",
        preview_items: [
          { id: "conversation", category: "原始对话", source: "当前线程", preview: "任务标题和工具摘要", confirmed: false },
        ],
      },
      permissions: {
        mode: "yes_once",
        options: [
          { id: "yes_once", label: "Yes once", detail: "仅本次。", active: true },
          { id: "yes_similar_session", label: "Yes to similar actions for this app session", detail: "本会话相似操作。", active: false },
          { id: "full_access", label: "Full access for this app session", detail: "本会话完全访问。", active: false },
        ],
      },
      checkpoints: [
        { id: "checkpoint-1", label: "初始基线", detail: "安全回档点", current: false },
        { id: "checkpoint-2", label: "候选修改", detail: "当前 diff", current: true },
      ],
    },
  };
}

type FixtureSnapshot = ReturnType<typeof fixtureSnapshot>;

function onboardingSnapshot(step: FixtureSnapshot["onboarding"]["step"]): FixtureSnapshot {
  const snapshot = fixtureSnapshot("NOT_READY");
  snapshot.onboarding.step = step;
  snapshot.onboarding.completed_steps =
    step === "CREATE_AGENT"
      ? []
      : step === "OPEN_FOLDER"
        ? ["CREATE_AGENT"]
        : step === "BIND_API"
          ? ["CREATE_AGENT", "OPEN_FOLDER"]
          : step === "CREATE_THREAD"
            ? ["CREATE_AGENT", "OPEN_FOLDER", "BIND_API"]
            : ["CREATE_AGENT", "OPEN_FOLDER", "BIND_API", "CREATE_THREAD"];
  snapshot.onboarding.headline =
    step === "CREATE_AGENT"
      ? "创建 AGENT 档案"
      : step === "OPEN_FOLDER"
        ? "打开一个本地项目文件夹"
        : step === "BIND_API"
          ? "绑定至少一个模型 Provider"
          : "创建第一个 bug 修复线程";
  snapshot.navigation.profiles = step === "CREATE_AGENT" ? [] : [{ id: "profile-1", label: "我的 Agent" }];
  snapshot.navigation.projects = step === "CREATE_AGENT" || step === "OPEN_FOLDER" ? [] : [{ id: "project-1", label: "project-alpha", active: true }];
  snapshot.navigation.threads = step === "CREATE_THREAD" || step === "WORKBENCH" ? snapshot.navigation.threads : [];
  snapshot.task.thread_id = step === "WORKBENCH" ? "thread-1" : "";
  snapshot.task.title = step === "WORKBENCH" ? "修复权限 bug" : snapshot.onboarding.headline;
  snapshot.task.run_state = step === "WORKBENCH" ? "RUNNING" : "IDLE";
  snapshot.task.append_enabled = step === "WORKBENCH";
  snapshot.task.messages = step === "WORKBENCH" ? snapshot.task.messages : [];
  snapshot.evidence.diff = step === "WORKBENCH" ? snapshot.evidence.diff : { files_changed: 0, additions: 0, deletions: 0 };
  snapshot.evidence.diff_files = step === "WORKBENCH" ? snapshot.evidence.diff_files : [];
  snapshot.evidence.approval_actions = step === "WORKBENCH" ? snapshot.evidence.approval_actions : [];
  snapshot.demo.agent_name = step === "CREATE_AGENT" ? null : "我的 Agent";
  snapshot.demo.project_path = step === "CREATE_AGENT" || step === "OPEN_FOLDER" ? null : "/Users/demo/project-alpha";
  snapshot.settings.credential_statuses = snapshot.settings.credential_statuses.map((credential) =>
    credential.provider === "openai" && (step === "CREATE_THREAD" || step === "WORKBENCH")
      ? { ...credential, status: "verified", updated_at: "2026-07-24T00:00:00Z" }
      : credential,
  );
  snapshot.demo.providers = snapshot.demo.providers.map((item) =>
    item.provider === "openai" && (step === "CREATE_THREAD" || step === "WORKBENCH")
      ? { ...item, configured: true, status: "verified", updated_at: "2026-07-24T00:00:00Z" }
      : item,
  );
  return snapshot;
}

function fixtureClient(snapshot: FixtureSnapshot | FixtureSnapshot[] = fixtureSnapshot()) {
  const snapshots = Array.isArray(snapshot) ? [...snapshot] : [snapshot];
  return {
    command: vi.fn(async () => ({ ok: true })),
    async getSnapshot() {
      return snapshots.shift() ?? snapshots[snapshots.length - 1] ?? fixtureSnapshot();
    },
    subscribe() {
      return { close() {} };
    },
  };
}

describe("workbench test-owned DOM harness", () => {
  it("test_owned_dom_cleanup_removes_previous_rendered_nodes", () => {
    render(<button type="button">临时按钮</button>);
    expect(screen.getByRole("button", { name: "临时按钮" })).toBeVisible();
    cleanup();
    expect(screen.queryByRole("button", { name: "临时按钮" })).toBeNull();
  });
});

describe("desktop workbench", () => {
  it("walks the empty first-run onboarding with real commands and refreshed snapshots", async () => {
    const { App } = await loadWorkbenchProduction();
    const client = fixtureClient([
      onboardingSnapshot("CREATE_AGENT"),
      onboardingSnapshot("OPEN_FOLDER"),
      onboardingSnapshot("BIND_API"),
      onboardingSnapshot("CREATE_THREAD"),
      fixtureSnapshot("READY"),
    ]);

    render(<App client={client} />);
    expect((await screen.findAllByRole("heading", { name: "创建 AGENT 档案" }))[0]).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "AGENT 名称" }), { target: { value: "我的 Agent" } });
    fireEvent.click(screen.getByRole("button", { name: "创建 AGENT" }));
    expect(client.command).toHaveBeenCalledWith({ type: "create_agent", payload: { name: "我的 Agent" } });

    expect((await screen.findAllByRole("heading", { name: "打开一个本地项目文件夹" }))[0]).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "项目路径" }), { target: { value: "/Users/demo/project-alpha" } });
    fireEvent.click(screen.getByRole("button", { name: "打开项目" }));
    expect(client.command).toHaveBeenCalledWith({ type: "open_folder", payload: { path: "/Users/demo/project-alpha" } });

    expect((await screen.findAllByRole("heading", { name: "绑定至少一个模型 Provider" }))[0]).toBeVisible();
    fireEvent.change(screen.getByLabelText(/API Key/u), { target: { value: "sk-test-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "绑定 API" }));
    expect(client.command).toHaveBeenCalledWith({ type: "bind_api", payload: { provider: "openai", model_id: "", api_key: "sk-test-secret" } });
    expect(screen.queryByText("sk-test-secret")).toBeNull();

    expect((await screen.findAllByRole("heading", { name: "创建第一个 bug 修复线程" }))[0]).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "线程标题" }), { target: { value: "调试一个权限边界 bug" } });
    fireEvent.click(screen.getByRole("button", { name: "创建线程" }));
    expect(client.command).toHaveBeenCalledWith({ type: "create_thread", payload: { title: "调试一个权限边界 bug" } });

    expect(await screen.findByRole("log", { name: "任务对话" })).toBeVisible();
    expect(screen.getByText("src/example.py")).toBeVisible();
  });

  it("renders a local-engineering conversation workbench instead of a dashboard", async () => {
    const { App } = await loadWorkbenchProduction();
    render(<App client={fixtureClient(fixtureSnapshot("READY"))} />);
    expect(await screen.findByRole("log", { name: "任务对话" })).toBeVisible();
    expect(screen.getByText("用户请求")).toBeVisible();
    expect(screen.getByText("Agent 运行")).toBeVisible();
    expect(await screen.findByRole("heading", { name: "变更审阅" })).toBeVisible();
    expect(screen.getByText("验证证据")).toBeVisible();
    expect(screen.getByText("风险与未覆盖项")).toBeVisible();
    expect(screen.getByText("src/example.py")).toBeVisible();
    expect(screen.getByText("+ return 2")).toBeVisible();
    expect(screen.getByText("- return 1")).toBeVisible();
    expect(screen.getByRole("button", { name: "接受当前候选" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: "记忆" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "审计" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "设置" })).toBeNull();
  });

  it("disables model changes for every active execution state", async () => {
    const { ModelSelector } = await loadTaskPaneProduction();
    for (const state of ["RUNNING", "COMPACTING", "WAITING_PERMISSION", "WAITING_PRIVACY", "STOPPING", "INTERRUPTED"]) {
      render(
        <ModelSelector
          runState={state}
          provider="openai"
          model="gpt-5.6-sol"
          models={[{ id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" }]}
        />,
      );
      expect(screen.getByRole("combobox", { name: "模型" })).toBeDisabled();
      cleanup();
    }
  });

  it("keeps duplicate model ids provider-aware in the selector", async () => {
    const { ModelSelector } = await loadTaskPaneProduction();
    const onChange = vi.fn();
    render(
      <ModelSelector
        runState="STOPPED"
        provider="njusehub"
        model="kimi-k2.7-code"
        models={[
          { id: "kimi-k2.7-code", label: "Kimi K2.7 Code", provider: "kimi" },
          { id: "kimi-k2.7-code", label: "NJU SE Hub / Kimi K2.7 Code", provider: "njusehub" },
        ]}
        onChange={onChange}
      />,
    );

    const selector = screen.getByRole("combobox", { name: "模型" });
    expect(selector).toHaveValue("njusehub::kimi-k2.7-code");
    fireEvent.change(selector, { target: { value: "kimi::kimi-k2.7-code" } });
    expect(onChange).toHaveBeenCalledWith("kimi", "kimi-k2.7-code");
  });

  it("does not render an empty thread title as a user message", async () => {
    const { TaskPane } = await loadTaskPaneProduction();
    const task: TaskModel = {
      threadId: "thread-1",
      title: "调试一个权限边界 bug",
      runState: "READY",
      provider: "openai",
      model: "gpt-5.6-sol",
      models: [{ id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" }],
      planMode: true,
      budget: { tokenLimit: 1500, timeLimitMinutes: 60 },
      retryPolicy: { connectionRetries: 5, toolRetries: 3, modelRetries: 5 },
      compactAfterLines: 1500,
      appendEnabled: true,
      messages: [],
    };

    render(<TaskPane model={task} onCommand={vi.fn()} />);

    expect(screen.queryByText("用户请求")).toBeNull();
    expect(screen.getByText("线程名称只作为界面元数据，不会发给模型。请在输入框发送真实任务内容；发送后会启动 Agent step。")).toBeVisible();
  });

  it("keeps Plan mode on by default but lets the user turn it off", async () => {
    const { App } = await loadWorkbenchProduction();
    const initial = fixtureSnapshot("READY");
    const updated = fixtureSnapshot("READY");
    updated.task.plan_mode = false;
    const client = fixtureClient([initial, updated]);
    render(<App client={client} />);
    const planToggle = await screen.findByRole("checkbox", { name: "Plan 模式" });
    expect(planToggle).toBeChecked();
    fireEvent.click(planToggle);
    expect(client.command).toHaveBeenCalledWith({ type: "set_plan_mode", payload: { enabled: false } });
    await waitFor(() => expect(planToggle).not.toBeChecked());
  });

  it("lets the user choose system light dark theme and four supported locales", async () => {
    const { App } = await loadWorkbenchProduction();
    const initial = fixtureSnapshot("READY");
    initial.demo.selected_panel = "设置";
    const themeUpdated = fixtureSnapshot("READY");
    themeUpdated.demo.selected_panel = "设置";
    themeUpdated.settings.theme_mode = "dark";
    const localeUpdated = fixtureSnapshot("READY");
    localeUpdated.demo.selected_panel = "设置";
    localeUpdated.settings.theme_mode = "dark";
    localeUpdated.settings.locale = "en-GB";
    const client = fixtureClient([initial, themeUpdated, localeUpdated]);

    const { container } = render(<App client={client} />);
    const root = await screen.findByLabelText("状态、变更与配置");
    expect(container.querySelector(".workbench")).toHaveAttribute("data-theme-mode", "system");
    expect(root).toBeVisible();

    fireEvent.change(screen.getByRole("combobox", { name: "主题" }), { target: { value: "dark" } });
    expect(client.command).toHaveBeenCalledWith({ type: "set_theme_mode", payload: { mode: "dark" } });
    await waitFor(() => expect(container.querySelector(".workbench")).toHaveAttribute("data-theme-mode", "dark"));

    fireEvent.change(screen.getByRole("combobox", { name: "语言" }), { target: { value: "en-GB" } });
    expect(client.command).toHaveBeenCalledWith({ type: "set_locale", payload: { locale: "en-GB" } });
    expect(await screen.findByRole("heading", { name: "Settings / API bindings" })).toBeVisible();
  });

  it("keeps shared status, diff, and inspector tokens light in the light/system theme", () => {
    const styles = readRendererStyles();
    expect(styles).toMatch(/\.workbench\s*\{[\s\S]*--status-neutral-bg: #ebe7de;/);
    expect(styles).toMatch(/\.workbench\s*\{[\s\S]*--yg-surface-1: #faf9f5;/);
    expect(styles).toMatch(/\.workbench\s*\{[\s\S]*color: var\(--text\);/);
    expect(styles).toMatch(/\.inspector-tab--active\s*\{[\s\S]*background: var\(--inspector-tab-active-bg\);/);
    expect(styles).toMatch(/\.yg-diff-summary__metric--files\s*\{[\s\S]*background: var\(--status-neutral-bg\);/);
  });

  it("exposes custom provider and model controls without leaking the API key", async () => {
    const { App } = await loadWorkbenchProduction();
    const initial = fixtureSnapshot("READY");
    initial.demo.selected_panel = "设置";
    const client = fixtureClient(initial);
    render(<App client={client} />);

    await screen.findByRole("heading", { name: "设置 / API 绑定" });
    fireEvent.change(screen.getByRole("textbox", { name: "设置页自定义 Provider ID" }), { target: { value: "localise" } });
    fireEvent.change(screen.getByRole("textbox", { name: "设置页自定义 Provider 显示名称" }), { target: { value: "Local ISE" } });
    fireEvent.change(screen.getByRole("textbox", { name: "设置页自定义 Provider Base URL" }), { target: { value: "https://localise.invalid/v1/chat/completions" } });
    fireEvent.change(screen.getByRole("textbox", { name: "设置页自定义 Provider 文档 URL" }), { target: { value: "https://localise.invalid/docs" } });
    fireEvent.change(screen.getByRole("textbox", { name: "设置页自定义模型 ID" }), { target: { value: "localise-coder" } });
    fireEvent.click(screen.getByRole("button", { name: "添加自定义 Provider/模型" }));
    expect(client.command).toHaveBeenCalledWith({
      type: "add_custom_provider",
      payload: {
        provider: "localise",
        label: "Local ISE",
        base_url: "https://localise.invalid/v1/chat/completions",
        docs_url: "https://localise.invalid/docs",
        model_id: "localise-coder",
      },
    });

    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "provider-secret" } });
    fireEvent.change(screen.getByRole("textbox", { name: "模型 ID（可选）" }), { target: { value: "manual-model" } });
    fireEvent.click(screen.getByRole("button", { name: "增加/更新绑定" }));
    expect(client.command).toHaveBeenCalledWith({ type: "bind_api", payload: { provider: "openai", model_id: "manual-model", api_key: "provider-secret" } });
    expect(screen.queryByText("provider-secret")).toBeNull();
  });

  it("sends user input and starts a ready run with one click", async () => {
    const { App } = await loadWorkbenchProduction();
    const initial = fixtureSnapshot("READY");
    initial.navigation.run_state = "READY";
    initial.task.run_state = "READY";
    (initial.task as { error: unknown }).error = null;
    const afterAppend = fixtureSnapshot("READY");
    afterAppend.navigation.run_state = "READY";
    afterAppend.task.run_state = "READY";
    (afterAppend.task as { error: unknown }).error = null;
    afterAppend.task.messages = [
      ...initial.task.messages,
      { id: "msg-3", role: "user", title: "追加信息", body: "点击发送后应该直接运行", at: "2026-07-24T00:00:02Z" },
      { id: "msg-4", role: "assistant", title: "Sidecar", body: "已收到输入；下一次 Agent step 会把它作为 Provider prompt 的用户上下文。", at: "2026-07-24T00:00:03Z" },
    ];
    const afterResume = fixtureSnapshot("READY");
    afterResume.navigation.run_state = "FINISHED";
    afterResume.task.run_state = "FINISHED";
    (afterResume.task as { error: unknown }).error = null;
    const client = fixtureClient([initial, afterAppend, afterResume]);

    render(<App client={client} />);
    const input = await screen.findByRole("textbox", { name: "追加信息" });
    fireEvent.change(input, { target: { value: "点击发送后应该直接运行" } });
    fireEvent.click(screen.getByRole("button", { name: "发送并运行" }));

    await waitFor(() =>
      expect(client.command).toHaveBeenNthCalledWith(1, {
        type: "append_message",
        payload: { text: "点击发送后应该直接运行" },
      }),
    );
    expect(client.command).toHaveBeenNthCalledWith(2, { type: "resume_run" });
    expect(await screen.findByText("已生成候选修改，查看右侧 Changes")).toBeVisible();
  });

  it("refetches the real sidecar snapshot after sending appended context", async () => {
    const { App } = await loadWorkbenchProduction();
    const initial = fixtureSnapshot("READY");
    const updated = fixtureSnapshot("READY");
    updated.task.messages = [
      ...initial.task.messages,
      { id: "msg-3", role: "user", title: "追加信息", body: "复现步骤：点击发送", at: "2026-07-24T00:00:02Z" },
      { id: "msg-4", role: "assistant", title: "Sidecar", body: "已收到输入；下一次 Agent step 会把它作为 Provider prompt 的用户上下文。", at: "2026-07-24T00:00:03Z" },
    ];
    const client = fixtureClient([initial, updated]);

    render(<App client={client} />);
    const input = await screen.findByRole("textbox", { name: "追加信息" });
    fireEvent.change(input, { target: { value: "复现步骤：点击发送" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(client.command).toHaveBeenCalledWith({
      type: "append_message",
      payload: { text: "复现步骤：点击发送" },
    });
    expect(await screen.findByText("已收到输入；下一次 Agent step 会把它作为 Provider prompt 的用户上下文。")).toBeVisible();
  });

  it("has no serious or critical automated accessibility violations", async () => {
    const { App } = await loadWorkbenchProduction();
    const { container } = render(<App client={fixtureClient(fixtureSnapshot("READY"))} />);
    await screen.findByRole("heading", { name: "变更审阅" });
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    const blocking = results.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
    expect(blocking).toEqual([]);
  });
});
