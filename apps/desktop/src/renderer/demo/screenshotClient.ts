import type { SidecarClient, WorkbenchApiSnapshot, WorkbenchCommand } from "../api/client.js";

export type ScreenshotSceneId =
  | "01-create-agent"
  | "02-ready-workbench"
  | "03-diff-review"
  | "04-settings-api-bindings"
  | "05-permissions-panel";

const sceneIds: readonly ScreenshotSceneId[] = [
  "01-create-agent",
  "02-ready-workbench",
  "03-diff-review",
  "04-settings-api-bindings",
  "05-permissions-panel",
];

const now = "2026-07-27T00:00:00Z";

function isScreenshotSceneId(value: string | null): value is ScreenshotSceneId {
  return sceneIds.includes(value as ScreenshotSceneId);
}

export function screenshotInitialPanel(scene: string | null): string | null {
  if (scene === "04-settings-api-bindings") return "设置";
  if (scene === "05-permissions-panel") return "权限";
  return null;
}

function modelOptions() {
  return [
    { id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" },
    { id: "gpt-5.6-terra", label: "OpenAI gpt-5.6-terra", provider: "openai" },
    { id: "qwen-plus", label: "Qwen Plus", provider: "qwen" },
    { id: "glm-4.5", label: "GLM 4.5", provider: "glm" },
    { id: "deepseek-chat", label: "DeepSeek Chat", provider: "deepseek" },
    { id: "kimi-k2.7-code", label: "Kimi K2.7 Code", provider: "kimi" },
    { id: "kimi-k2.7-code", label: "NJU SE Hub / Kimi K2.7 Code", provider: "njusehub" },
  ];
}

const providerDefinitions = [
  {
    provider: "openai",
    label: "OpenAI",
    docs_url: "https://platform.openai.com/docs/api-reference/responses",
  },
  {
    provider: "qwen",
    label: "Qwen",
    docs_url: "https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope",
  },
  {
    provider: "glm",
    label: "GLM",
    docs_url: "https://docs.bigmodel.cn/api-reference/model-api/chat-completion",
  },
  {
    provider: "deepseek",
    label: "DeepSeek",
    docs_url: "https://api-docs.deepseek.com/api/create-chat-completion",
  },
  {
    provider: "minimax",
    label: "MiniMax",
    docs_url: "https://platform.minimaxi.com/document/ChatCompletion%20v2",
  },
  {
    provider: "kimi",
    label: "Kimi / Moonshot",
    docs_url: "https://platform.moonshot.cn/docs/api/chat",
  },
  {
    provider: "njusehub",
    label: "NJU SE Hub",
    docs_url: "https://dongshao.github.io/GAIHub1/njusehubdoc.html",
  },
] as const;

function providerViews(configuredProvider: string) {
  return providerDefinitions.map((provider) => {
    const configured = provider.provider === configuredProvider;
    return {
      provider: provider.provider,
      label: provider.label,
      configured,
      status: configured ? ("verified" as const) : ("missing" as const),
      updated_at: configured ? now : null,
      detail: configured ? "本地截图 fixture：已校验，未保存原始 key" : "尚未绑定",
      docs_url: provider.docs_url,
    };
  });
}

function diffFiles(active: boolean): WorkbenchApiSnapshot["evidence"]["diff_files"] {
  if (!active) return [];
  return [
    {
      path: "src/example.py",
      status: "modified",
      additions: 5,
      deletions: 3,
      lines: [
        { kind: "hunk", old_line: null, new_line: null, content: "@@ -1,7 +1,9 @@" },
        { kind: "context", old_line: 1, new_line: 1, content: "from pathlib import Path" },
        { kind: "context", old_line: 2, new_line: 2, content: "" },
        { kind: "context", old_line: 3, new_line: 3, content: "def answer():" },
        { kind: "delete", old_line: 4, new_line: null, content: "    return 1" },
        { kind: "add", old_line: null, new_line: 4, content: "    return 2" },
        { kind: "context", old_line: 5, new_line: 5, content: "" },
        { kind: "context", old_line: 6, new_line: 6, content: "def allowed_path(workspace, candidate):" },
        { kind: "delete", old_line: 7, new_line: null, content: "    return str(candidate).startswith(str(workspace))" },
        { kind: "delete", old_line: 8, new_line: null, content: "    # TODO: handle ../ traversal" },
        { kind: "add", old_line: null, new_line: 7, content: "    root = Path(workspace).resolve()" },
        { kind: "add", old_line: null, new_line: 8, content: "    target = Path(candidate).resolve()" },
        { kind: "add", old_line: null, new_line: 9, content: "    return target == root or root in target.parents" },
        { kind: "add", old_line: null, new_line: 10, content: "    # fixture: prevents sibling-directory escape" },
      ],
    },
    {
      path: "tests/test_example.py",
      status: "modified",
      additions: 2,
      deletions: 1,
      lines: [
        { kind: "hunk", old_line: null, new_line: null, content: "@@ -1,4 +1,5 @@" },
        { kind: "context", old_line: 1, new_line: 1, content: "from src.example import answer, allowed_path" },
        { kind: "context", old_line: 2, new_line: 2, content: "" },
        { kind: "delete", old_line: 3, new_line: null, content: "assert answer() == 1" },
        { kind: "add", old_line: null, new_line: 3, content: "assert answer() == 2" },
        { kind: "add", old_line: null, new_line: 4, content: "assert not allowed_path('/repo/app', '/repo/app/../secret')" },
      ],
    },
  ];
}

function baseSnapshot(scene: ScreenshotSceneId): WorkbenchApiSnapshot {
  const configuredProvider = "openai";
  const activeDiff = scene === "03-diff-review" || scene === "04-settings-api-bindings" || scene === "05-permissions-panel";
  const workbenchReady = scene !== "01-create-agent";
  const files = diffFiles(activeDiff);
  const providers = providerViews(configuredProvider);
  return {
    profile_id: "profile-screenshot",
    generation: activeDiff ? 2 : 1,
    last_sequence: activeDiff ? 7 : 3,
    connection: "connected",
    onboarding: {
      step: workbenchReady ? "WORKBENCH" : "CREATE_AGENT",
      completed_steps: workbenchReady ? ["CREATE_AGENT", "OPEN_FOLDER", "BIND_API", "CREATE_THREAD"] : [],
      headline: workbenchReady ? "进入本地 Agent 工作台" : "创建 AGENT 档案",
      detail: workbenchReady
        ? "可以调试对话、Plan、模型、权限、记忆、隐私、审查、Diff 和回滚。"
        : "首次启动为空状态；先创建一个属于当前账号的 Agent/档案。",
    },
    navigation: {
      profiles: workbenchReady ? [{ id: "profile-screenshot", label: "测试 Agent" }] : [],
      projects: workbenchReady ? [{ id: "project-yagcode", label: "yagcode", active: true }] : [],
      threads: workbenchReady ? [{ id: "thread-permission", label: "调试一个权限边界 bug", unread_approvals: activeDiff ? 1 : 0, memory_suggestions: 0 }] : [],
      run_state: activeDiff ? "FINISHED" : workbenchReady ? "READY" : "IDLE",
    },
    task: {
      thread_id: workbenchReady ? "thread-permission" : "",
      title: workbenchReady ? "调试一个权限边界 bug" : "创建 AGENT 档案",
      run_state: activeDiff ? "FINISHED" : workbenchReady ? "READY" : "IDLE",
      provider: configuredProvider,
      model: "gpt-5.6-sol",
      models: modelOptions(),
      plan_mode: true,
      budget: { token_limit: 1500, time_limit_minutes: 60 },
      retry_policy: { connection_retries: 5, tool_retries: 3, model_retries: 5 },
      compact_after_lines: 1500,
      append_enabled: workbenchReady,
      messages: workbenchReady
        ? [
            {
              id: "msg-1",
              role: "assistant",
              title: "本地工作台",
              body: "线程已创建。线程名称只作为界面元数据，不会发给模型；请在输入框发送真实任务内容后再启动 Agent step。",
              at: now,
            },
            {
              id: "msg-2",
              role: "assistant",
              title: "安全边界",
              body: "默认启用 Plan 模式；运行中可以追加信息，必须中断后才能切换模型。",
              at: "OpenAI · gpt-5.6-sol",
            },
            {
              id: "msg-3",
              role: "assistant",
              title: "隐私预览",
              body: "首次发送原始对话和工具输出前会预览并确认；截图 fixture 不包含真实 key。",
              at: "本地 fixture",
            },
            ...(activeDiff
              ? [
                  {
                    id: "msg-4",
                    role: "user" as const,
                    title: "任务输入",
                    body: "请修复 src/example.py，让 answer() 返回 2，并阻止 ../ 越界访问。",
                    at: now,
                  },
                  {
                    id: "msg-5",
                    role: "assistant" as const,
                    title: "Agent step",
                    body: "样例 Provider action 已完成：TASK_COMPLETE；provider 调用 2 次，apply_patch 1 次。",
                    at: "OpenAI · gpt-5.6-sol",
                  },
                  {
                    id: "msg-6",
                    role: "assistant" as const,
                    title: "验证摘要",
                    body: "RED: pytest tests/test_example.py 失败；GREEN: 聚焦测试通过，候选 diff 已生成，可在右侧 Changes 审查或回滚。",
                    at: "本地验证",
                  },
                ]
              : []),
          ]
        : [],
    },
    review_view: {
      kind: "review",
      review_id: "review-screenshot",
      state: activeDiff ? "READY" : workbenchReady ? "INCOMPLETE" : "NOT_READY",
      generation: activeDiff ? 2 : 1,
      summary: activeDiff ? "检测到候选 Git diff，可审查或回滚。" : "当前没有可显示的 Git diff。",
    },
    evidence: {
      diff: { files_changed: files.length, additions: activeDiff ? 7 : 0, deletions: activeDiff ? 4 : 0 },
      diff_files: files,
      validations: [
        { id: "red", title: "RED", detail: activeDiff ? "pytest tests/test_example.py 失败" : "等待用户输入", status: activeDiff ? "passed" : "pending", command: "pytest tests/test_example.py" },
        { id: "green", title: "GREEN", detail: activeDiff ? "聚焦测试通过" : "等待候选修改", status: activeDiff ? "passed" : "pending", command: "pytest tests/test_example.py" },
      ],
      risks: ["截图 fixture 不执行真实文件操作"],
      uncovered: ["发布安装包 smoke 由 覆盖"],
      approval_actions: workbenchReady
        ? [
            { id: "accept_review", label: "接受当前候选", enabled: activeDiff, high_risk: false },
            { id: "reject_review", label: "拒绝当前候选", enabled: activeDiff, high_risk: false },
          ]
        : [],
    },
    settings: {
      credential_statuses: providers.map(({ configured: _configured, label: _label, ...credential }) => credential),
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
      project_memories: workbenchReady ? [{ id: "memory-1", title: "项目默认偏好", detail: "默认中文沟通；每个 bug 修完后展示 diff 和验证证据。", pinned: true }] : [],
      cross_project_suggestions: workbenchReady ? [{ id: "suggestion-1", title: "跨项目候选", detail: "确认进入 memory 不阻塞当前 run。" }] : [],
    },
    audit: {
      entries: workbenchReady
        ? [
            { id: "audit-1", title: "创建 AGENT", detail: "测试 Agent", at: now },
            { id: "audit-2", title: "打开文件夹", detail: "yagcode · git:main", at: now },
            { id: "audit-3", title: "绑定 API", detail: "openai 已通过 fixture 校验并丢弃原始 key。", at: now },
          ]
        : [],
    },
    demo: {
      selected_panel: "审阅",
      theme_mode: "system",
      locale: "zh-Hans",
      agent_name: workbenchReady ? "测试 Agent" : null,
      project_path: workbenchReady ? "/Users/demo/yagcode" : null,
      project: workbenchReady
        ? {
            path: "/Users/demo/yagcode",
            label: "yagcode",
            is_git_repo: true,
            git_root: "/Users/demo/yagcode",
            branch: "main",
            status_summary: activeDiff ? [" M src/example.py", " M tests/test_example.py"] : [],
            error: null,
          }
        : null,
      providers,
      privacy: {
        preview_confirmed: activeDiff,
        retention: "permanent",
        preview_items: [
          {
            id: "conversation",
            category: "原始对话和工具输出",
            source: "当前线程首次发送",
            preview: "将发送：追加信息和工具摘要；凭据值会遮蔽。",
            confirmed: activeDiff,
          },
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
      checkpoints: workbenchReady
        ? [
            { id: "checkpoint-1", label: "当前 Git 状态", detail: "打开项目并创建线程后的真实工作区状态。", current: !activeDiff },
            { id: "checkpoint-2", label: "run-1 候选修改", detail: "Provider calls: 2; patches applied: 1", current: activeDiff },
          ]
        : [],
    },
  };
}

export function createScreenshotSceneClient(scene: string | null): SidecarClient | null {
  if (!isScreenshotSceneId(scene)) return null;
  const snapshot = baseSnapshot(scene);
  return {
    async getSnapshot() {
      return snapshot;
    },
    async getReview() {
      return snapshot.review_view;
    },
    subscribe() {
      return { close() {} };
    },
    async command(_command: WorkbenchCommand) {
      return { ok: true };
    },
  };
}
