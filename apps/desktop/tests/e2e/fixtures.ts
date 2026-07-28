import { test as base, _electron as electron, expect } from "@playwright/test";
import type { ElectronApplication, Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import type { IncomingMessage, Server, ServerResponse } from "node:http";
import { createRequire } from "node:module";
import type { Socket } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const repoRoot = resolve(desktopRoot, "../..");
const electronUserDataDirs = new WeakMap<ElectronApplication, string>();

function npmRunScriptCommand(script: string): { command: string; args: string[] } {
  if (process.platform !== "win32") return { command: "npm", args: ["run", script] };
  return {
    command: process.execPath,
    args: [join(dirname(process.execPath), "node_modules/npm/bin/npm-cli.js"), "run", script]
  };
}

export interface BlockingRun {
  id: string;
  state: "RUNNING" | "INTERRUPTED" | "STOPPING" | "WAITING_PERMISSION" | "WAITING_PRIVACY" | "COMPACTING";
  title?: string;
}

export interface StartupConnectionView {
  baseUrl: string;
  token: string;
  origin: string;
  connected: boolean;
}

interface IntentChallenge {
  intent_id: string;
  intent_type: string;
  one_time_token: string;
  resource_id: string;
}

export interface FixtureSidecar {
  readonly baseUrl: string;
  readonly token: string;
  readonly origin: string;
  readonly projectPath: string;
  commandTypes(): readonly string[];
  consumedIntents(): readonly string[];
  sendMalformedEvent(): void;
  setRunState(state: string): void;
  setBlockingRuns(runs: readonly BlockingRun[]): void;
  close(): Promise<void>;
}

function readJson(request: IncomingMessage): Promise<unknown> {
  return new Promise((resolveRead, reject) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => {
      body += chunk;
    });
    request.on("end", () => {
      if (body.length === 0) {
        resolveRead({});
        return;
      }
      try {
        resolveRead(JSON.parse(body) as unknown);
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

function sendJson(response: ServerResponse, status: number, value: unknown, origin: string): void {
  response.writeHead(status, {
    "access-control-allow-headers": "authorization,content-type,x-yagcode-principal",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-origin": origin,
    "content-type": "application/json"
  });
  response.end(JSON.stringify(value));
}

function authenticated(request: IncomingMessage, token: string, origin: string): boolean {
  return request.headers.authorization === `Bearer ${token}` && request.headers.origin === origin;
}

function bearerAuthenticated(request: IncomingMessage, token: string): boolean {
  return request.headers.authorization === `Bearer ${token}`;
}

type OnboardingStep = "CREATE_AGENT" | "OPEN_FOLDER" | "BIND_API" | "CREATE_THREAD" | "WORKBENCH";

interface FixtureMessage {
  id: string;
  role: "user" | "assistant" | "system";
  title: string;
  body: string;
  at: string;
}

interface FixtureState {
  agentName: string | null;
  projectPath: string | null;
  provider: string;
  model: string;
  providerConfigured: boolean;
  threadTitle: string | null;
  runState: string;
  reviewState: "NOT_READY" | "INCOMPLETE" | "READY" | "ACCEPTED" | "REJECTED" | "RECOVERY_REQUIRED";
  selectedPanel: string;
  planMode: boolean;
  privacyConfirmed: boolean;
  retention: string;
  permissionMode: string;
  themeMode: "system" | "light" | "dark";
  locale: "zh-Hans" | "zh-Hant" | "en-US" | "en-GB";
  diffActive: boolean;
  messages: FixtureMessage[];
  memories: { id: string; title: string; detail: string; pinned: boolean }[];
  checkpoints: { id: string; label: string; detail: string; current: boolean }[];
  audit: { id: string; title: string; detail: string; at: string }[];
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

const onboardingOrder: readonly OnboardingStep[] = [
  "CREATE_AGENT",
  "OPEN_FOLDER",
  "BIND_API",
  "CREATE_THREAD",
  "WORKBENCH",
];

function createFixtureState(): FixtureState {
  return {
    agentName: null,
    projectPath: null,
    provider: "openai",
    model: "gpt-5.6-sol",
    providerConfigured: false,
    threadTitle: null,
    runState: "IDLE",
    reviewState: "NOT_READY",
    selectedPanel: "审查",
    planMode: true,
    privacyConfirmed: false,
    retention: "permanent",
    permissionMode: "yes_once",
    themeMode: "system",
    locale: "zh-Hans",
    diffActive: false,
    messages: [],
    memories: [],
    checkpoints: [],
    audit: [],
  };
}

function now(): string {
  return "2026-07-26T00:00:00Z";
}

function appendAudit(state: FixtureState, title: string, detail: string): void {
  state.audit.push({ id: `audit-${state.audit.length + 1}`, title, detail, at: now() });
}

function appendMessage(state: FixtureState, role: FixtureMessage["role"], title: string, body: string): void {
  state.messages.push({ id: `msg-${state.messages.length + 1}`, role, title, body, at: now() });
}

function onboardingStep(state: FixtureState): OnboardingStep {
  if (state.agentName === null) return "CREATE_AGENT";
  if (state.projectPath === null) return "OPEN_FOLDER";
  if (!state.providerConfigured) return "BIND_API";
  if (state.threadTitle === null) return "CREATE_THREAD";
  return "WORKBENCH";
}

function completedSteps(step: OnboardingStep): readonly OnboardingStep[] {
  return onboardingOrder.slice(0, onboardingOrder.indexOf(step));
}

function onboardingHeadline(step: OnboardingStep): string {
  return {
    CREATE_AGENT: "创建 AGENT 档案",
    OPEN_FOLDER: "打开一个本地项目文件夹",
    BIND_API: "绑定至少一个模型 Provider",
    CREATE_THREAD: "创建第一个 bug 修复线程",
    WORKBENCH: "进入本地 Agent 工作台",
  }[step];
}

function onboardingDetail(step: OnboardingStep): string {
  return {
    CREATE_AGENT: "首次启动为空状态；先创建一个属于当前账号的 Agent/档案。",
    OPEN_FOLDER: "项目必须显式打开，后续线程、权限、记忆和审查都挂在该项目下。",
    BIND_API: "Key 只进入受控 sidecar 状态；snapshot、日志和界面不会回显原始 key。",
    CREATE_THREAD: "一个项目同一时间只运行一个线程；运行中追加信息，停止后才允许换模型。",
    WORKBENCH: "可以调试对话、Plan、模型、权限、记忆、隐私、审查、Diff 和回滚。",
  }[step];
}

function taskTitle(state: FixtureState, step: OnboardingStep): string {
  return state.threadTitle ?? onboardingHeadline(step);
}

function providerViews(state: FixtureState) {
  return providerDefinitions.map((provider) => {
    const configured = state.providerConfigured && provider.provider === state.provider;
    return {
      provider: provider.provider,
      label: provider.label,
      configured,
      status: configured ? "verified" : "missing",
      updated_at: configured ? now() : null,
      detail: configured ? "fixture verifier accepted key; raw key was discarded" : "尚未绑定",
      docs_url: provider.docs_url,
    };
  });
}

function modelOptions() {
  return [
    { id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" },
    { id: "gpt-5.6-terra", label: "OpenAI gpt-5.6-terra", provider: "openai" },
    { id: "qwen-turbo", label: "Qwen Turbo", provider: "qwen" },
    { id: "qwen-plus", label: "Qwen Plus", provider: "qwen" },
    { id: "glm-4.5", label: "GLM 4.5", provider: "glm" },
    { id: "deepseek-chat", label: "DeepSeek Chat", provider: "deepseek" },
    { id: "kimi-k2.7-code", label: "Kimi K2.7 Code", provider: "kimi" },
    { id: "kimi-k2.7-code", label: "NJU SE Hub / Kimi K2.7 Code", provider: "njusehub" },
  ];
}

function fixtureSnapshot(state: FixtureState) {
  const step = onboardingStep(state);
  const diffFiles = state.diffActive
    ? [
        {
          path: "src/example.py",
          status: "modified",
          additions: 1,
          deletions: 1,
          lines: [
            { kind: "hunk", old_line: null, new_line: null, content: "@@ -1,2 +1,2 @@" },
            { kind: "context", old_line: 1, new_line: 1, content: "def answer():" },
            { kind: "delete", old_line: 2, new_line: null, content: "    return 1" },
            { kind: "add", old_line: null, new_line: 2, content: "    return 2" },
          ],
        },
      ]
    : [];
  return {
    profile_id: "profile-1",
    generation: 1,
    last_sequence: 1,
    connection: "connected",
    onboarding: {
      step,
      completed_steps: completedSteps(step),
      headline: onboardingHeadline(step),
      detail: onboardingDetail(step),
    },
    navigation: {
      profiles: state.agentName === null ? [] : [{ id: "profile-1", label: state.agentName }],
      projects: state.projectPath === null ? [] : [{ id: "project-1", label: "yagcode", active: true }],
      threads: state.threadTitle === null ? [] : [{ id: "thread-1", label: state.threadTitle, unread_approvals: state.diffActive ? 1 : 0, memory_suggestions: 0 }],
      run_state: state.runState
    },
    task: {
      thread_id: state.threadTitle === null ? "" : "thread-1",
      title: taskTitle(state, step),
      run_state: state.runState,
      provider: state.provider,
      model: state.model,
      models: modelOptions(),
      plan_mode: state.planMode,
      budget: { token_limit: 1500, time_limit_minutes: 60 },
      retry_policy: { connection_retries: 5, tool_retries: 3, model_retries: 5 },
      compact_after_lines: 1500,
      append_enabled: step === "WORKBENCH",
      messages: state.messages,
    },
    review_view: {
      kind: "review",
      review_id: "review-1",
      state: state.reviewState,
      generation: 1,
      summary: state.diffActive ? "检测到 fixture Git diff，可审查或回滚。" : "当前没有可显示的 Git diff。"
    },
    evidence: {
      diff: { files_changed: diffFiles.length, additions: state.diffActive ? 1 : 0, deletions: state.diffActive ? 1 : 0 },
      diff_files: diffFiles,
      validations: [
        { id: "e2e", title: "Electron E2E", detail: "fixture sidecar", status: step === "WORKBENCH" ? "passed" : "running", command: "playwright test" },
        { id: "diff", title: "真实 Git Diff 预览", detail: state.diffActive ? "fixture diff ready" : "等待候选修改", status: state.diffActive ? "passed" : "pending", command: "git diff --no-ext-diff --unified=3 HEAD --" },
      ],
      risks: ["fixture sidecar 不执行真实文件操作"],
      uncovered: ["生产 sidecar 打包由 release packaging 覆盖"],
      approval_actions:
        step === "WORKBENCH"
          ? [
              { id: "accept_review", label: "接受当前候选", enabled: true, high_risk: false },
              { id: "reject_review", label: "拒绝当前候选", enabled: true, high_risk: false },
            ]
          : [],
    },
    settings: {
      credential_statuses: providerViews(state).map(({ configured: _configured, label: _label, ...credential }) => credential),
      retention_options: ["permanent", "30d", "60d", "90d", "180d", "1y", "2y"],
      selected_retention: state.retention,
      theme_mode: state.themeMode,
      locale: state.locale,
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
      project_memories: state.memories,
      cross_project_suggestions: step === "WORKBENCH" ? [{ id: "suggestion-1", title: "跨项目候选", detail: "确认进入 memory 不阻塞当前 run。" }] : [],
    },
    audit: { entries: state.audit },
    demo: {
      selected_panel: state.selectedPanel,
      theme_mode: state.themeMode,
      locale: state.locale,
      agent_name: state.agentName,
      project_path: state.projectPath,
      project:
        state.projectPath === null
          ? null
          : {
              path: state.projectPath,
              label: "yagcode",
              is_git_repo: true,
              git_root: state.projectPath,
              branch: "main",
              status_summary: state.diffActive ? [" M src/example.py"] : [],
              error: null,
            },
      providers: providerViews(state),
      privacy: {
        preview_confirmed: state.privacyConfirmed,
        retention: state.retention,
        preview_items: [
          {
            id: "conversation",
            category: "原始对话和工具输出",
            source: "当前线程首次发送",
            preview: "将发送：追加信息和工具摘要；凭据值会遮蔽。",
            confirmed: state.privacyConfirmed,
          },
        ],
      },
      permissions: {
        mode: state.permissionMode,
        options: [
          { id: "yes_once", label: "Yes once", detail: "仅本次。", active: state.permissionMode === "yes_once" },
          {
            id: "yes_similar_session",
            label: "Yes to similar actions for this app session",
            detail: "本会话相似操作。",
            active: state.permissionMode === "yes_similar_session",
          },
          { id: "full_access", label: "Full access for this app session", detail: "本会话完全访问。", active: state.permissionMode === "full_access" },
        ],
      },
      checkpoints: state.checkpoints,
    },
  };
}

function payloadRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function payloadString(value: unknown, key: string): string {
  const text = payloadRecord(value)[key];
  return typeof text === "string" ? text : "";
}

function handleCommand(state: FixtureState, request: unknown): { ok: boolean; reason?: string } {
  const record = payloadRecord(request);
  const type = typeof record.type === "string" ? record.type : "";
  const payload = record.payload;
  if (type === "create_agent") {
    const name = payloadString(payload, "name").trim();
    if (!name) return { ok: false, reason: "AGENT_NAME_REQUIRED" };
    state.agentName = name;
    state.projectPath = null;
    state.providerConfigured = false;
    state.threadTitle = null;
    state.messages = [];
    state.checkpoints = [];
    state.runState = "IDLE";
    state.reviewState = "NOT_READY";
    appendAudit(state, "创建 AGENT", name);
    return { ok: true };
  }
  if (type === "open_folder") {
    const projectPath = payloadString(payload, "path").trim();
    if (!projectPath) return { ok: false, reason: "PROJECT_PATH_REQUIRED" };
    state.projectPath = projectPath;
    state.threadTitle = null;
    state.messages = [];
    state.checkpoints = [];
    state.runState = "IDLE";
    state.reviewState = "NOT_READY";
    appendAudit(state, "打开文件夹", "yagcode · git:main");
    return { ok: true };
  }
  if (type === "bind_api") {
    const apiKey = payloadString(payload, "api_key").trim();
    if (!apiKey) return { ok: false, reason: "API_KEY_REQUIRED" };
    state.provider = payloadString(payload, "provider") || "openai";
    state.model = payloadString(payload, "model_id") || (state.provider === "njusehub" ? "qwen-turbo" : "gpt-5.6-sol");
    state.providerConfigured = true;
    appendAudit(state, "绑定 API", `${state.provider} 已通过 fixture 校验并丢弃原始 key。`);
    return { ok: true };
  }
  if (type === "create_thread") {
    const title = payloadString(payload, "title").trim();
    if (!title) return { ok: false, reason: "THREAD_TITLE_REQUIRED" };
    state.threadTitle = title;
    state.runState = "READY";
    state.reviewState = "INCOMPLETE";
    state.messages = [];
    appendMessage(
      state,
      "assistant",
      "本地工作台",
      "线程已创建。线程名称只作为界面元数据，不会发给模型；请在输入框发送真实任务内容后再启动 Agent step。",
    );
    state.memories = [{ id: "memory-1", title: "项目默认偏好", detail: "默认中文沟通；每个 bug 修完后展示 diff 和验证证据。", pinned: true }];
    state.checkpoints = [{ id: "checkpoint-1", label: "当前 Git 状态", detail: "打开项目并创建线程后的真实工作区状态。", current: true }];
    appendAudit(state, "创建线程", "thread-1 -> READY");
    return { ok: true };
  }
  if (type === "append_message") {
    const text = payloadString(payload, "text").trim();
    if (!text) return { ok: false, reason: "APPEND_MESSAGE_EMPTY" };
    appendMessage(state, "user", state.messages.some((message) => message.role === "user") ? "追加信息" : "任务输入", text);
    appendMessage(state, "assistant", "Sidecar", "已收到输入；下一次 Agent step 会把它作为 Provider prompt 的用户上下文。");
    appendAudit(state, "追加信息", "renderer 通过 /api/v1/commands 提交了追加上下文。");
    return { ok: true };
  }
  if (type === "resume_run") {
    if (!state.messages.some((message) => message.role === "user")) return { ok: false, reason: "AGENT_INPUT_REQUIRED" };
    state.runState = "FINISHED";
    state.reviewState = "READY";
    state.diffActive = true;
    state.checkpoints = state.checkpoints.map((checkpoint) => ({ ...checkpoint, current: false }));
    state.checkpoints.push({ id: "checkpoint-2", label: "run-1 候选修改", detail: "Provider calls: 2; patches applied: 1", current: true });
    appendMessage(state, "assistant", "Agent step", "真实 Provider action 已完成：TASK_COMPLETE；provider 调用 2 次，apply_patch 1 次。");
    appendAudit(state, "完成 run", "run-1 -> FINISHED");
    return { ok: true };
  }
  if (type === "rollback_checkpoint") {
    const checkpointId = payloadString(payload, "checkpoint_id");
    if (!state.checkpoints.some((checkpoint) => checkpoint.id === checkpointId)) return { ok: false, reason: "CHECKPOINT_NOT_FOUND" };
    state.diffActive = false;
    state.reviewState = "RECOVERY_REQUIRED";
    state.checkpoints = state.checkpoints.map((checkpoint) => ({ ...checkpoint, current: checkpoint.id === checkpointId }));
    appendAudit(state, "回滚 checkpoint", checkpointId);
    return { ok: true };
  }
  if (type === "open_panel") {
    state.selectedPanel = payloadString(payload, "panel") || "审查";
    return { ok: true };
  }
  if (type === "set_plan_mode") {
    state.planMode = payloadRecord(payload).enabled !== false;
    return { ok: true };
  }
  if (type === "switch_model") {
    state.provider = payloadString(payload, "provider") || state.provider;
    state.model = payloadString(payload, "model") || state.model;
    return { ok: true };
  }
  if (type === "confirm_privacy") {
    state.privacyConfirmed = true;
    return { ok: true };
  }
  if (type === "set_retention") {
    state.retention = payloadString(payload, "retention") || state.retention;
    return { ok: true };
  }
  if (type === "set_permission_mode") {
    state.permissionMode = payloadString(payload, "mode") || state.permissionMode;
    return { ok: true };
  }
  if (type === "accept_review") {
    state.reviewState = "ACCEPTED";
    return { ok: true };
  }
  if (type === "reject_review") {
    state.reviewState = "REJECTED";
    state.diffActive = false;
    return { ok: true };
  }
  if (type === "stop_run") {
    state.runState = "STOPPED";
    return { ok: true };
  }
  return { ok: false, reason: "COMMAND_UNSUPPORTED" };
}

export function startFixtureSidecar({
  token = "fixture-startup-token",
  origin = "app://yagcode"
}: {
  token?: string;
  origin?: string;
} = {}): Promise<FixtureSidecar> {
  const state = createFixtureState();
  const blockingRuns: BlockingRun[] = [];
  const commandLog: string[] = [];
  const consumed: string[] = [];
  const eventResponses = new Set<ServerResponse>();
  let nextIntent = 0;
  let closed = false;
  const challenges = new Map<string, IntentChallenge>();
  const sockets = new Set<Socket>();

  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (request.method === "OPTIONS") {
      sendJson(response, 204, {}, origin);
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/events") {
      if (!bearerAuthenticated(request, token)) {
        sendJson(response, 401, { detail: { reason_code: "SIDECAR_AUTH_REQUIRED" } }, origin);
        return;
      }
      response.writeHead(200, {
        "access-control-allow-origin": origin,
        "cache-control": "no-cache",
        "content-type": "text/event-stream",
      });
      response.write(": connected\n\n");
      eventResponses.add(response);
      response.once("close", () => eventResponses.delete(response));
      return;
    }
    if (!authenticated(request, token, origin)) {
      sendJson(response, 401, { detail: { reason_code: "SIDECAR_AUTH_REQUIRED" } }, origin);
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/health") {
      sendJson(response, 200, { version: "0.1.0", status: "ok", capabilities: { sse: true } }, origin);
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/workbench") {
      sendJson(response, 200, fixtureSnapshot(state), origin);
      return;
    }
    if (request.method === "POST" && url.pathname === "/api/v1/commands") {
      void readJson(request).then(
        (body) => {
          const commandType = payloadString(body, "type");
          if (commandType) commandLog.push(commandType);
          sendJson(response, 200, handleCommand(state, body), origin);
        },
        () => {
          sendJson(response, 400, { ok: false, reason: "COMMAND_JSON_INVALID" }, origin);
        },
      );
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/desktop/blocking-runs") {
      sendJson(response, 200, { runs: blockingRuns }, origin);
      return;
    }
    const intentMatch = /^\/api\/v1\/review\/([^/]+)\/accept-intent$/u.exec(url.pathname);
    if (request.method === "POST" && intentMatch?.[1]) {
      nextIntent += 1;
      const challenge: IntentChallenge = {
        intent_id: `intent-${nextIntent}`,
        intent_type: "ACCEPT_REVIEW",
        one_time_token: `token-${nextIntent}`,
        resource_id: decodeURIComponent(intentMatch[1])
      };
      challenges.set(challenge.intent_id, challenge);
      sendJson(response, 201, challenge, origin);
      return;
    }
    const consumeMatch = /^\/api\/v1\/intents\/([^/]+)\/consume$/u.exec(url.pathname);
    if (request.method === "POST" && consumeMatch?.[1]) {
      if (request.headers["x-yagcode-principal"] !== "main") {
        sendJson(response, 403, { detail: { reason_code: "MAIN_PRINCIPAL_REQUIRED" } }, origin);
        return;
      }
      void readJson(request).then((body) => {
        const intentId = decodeURIComponent(consumeMatch[1] ?? "");
        const challenge = challenges.get(intentId);
        if (
          challenge === undefined ||
          typeof body !== "object" ||
          body === null ||
          !("one_time_token" in body) ||
          body.one_time_token !== challenge.one_time_token
        ) {
          sendJson(response, 403, { detail: { reason_code: "INTENT_TOKEN_INVALID" } }, origin);
          return;
        }
        challenges.delete(intentId);
        consumed.push(intentId);
        sendJson(response, 200, { intent_id: intentId, intent_type: challenge.intent_type, state: "EXECUTED" }, origin);
      });
      return;
    }
    sendJson(response, 404, { detail: { reason_code: "NOT_FOUND" } }, origin);
  });
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });

  return new Promise((resolveStart, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        reject(new Error("FIXTURE_SIDECAR_PORT_MISSING"));
        return;
      }
      resolveStart({
        baseUrl: `http://127.0.0.1:${address.port}`,
        token,
        origin,
        projectPath: repoRoot,
        commandTypes() {
          return commandLog;
        },
        consumedIntents() {
          return consumed;
        },
        sendMalformedEvent() {
          for (const eventResponse of eventResponses) eventResponse.write("data: not-json\n\n");
        },
        setRunState(runState) {
          state.runState = runState;
        },
        setBlockingRuns(runs) {
          blockingRuns.splice(0, blockingRuns.length, ...runs);
        },
        close() {
          if (closed) return Promise.resolve();
          closed = true;
          for (const eventResponse of eventResponses) eventResponse.end();
          for (const socket of sockets) socket.destroy();
          return closeServer(server);
        }
      });
    });
  });
}

function closeServer(server: Server): Promise<void> {
  return new Promise((resolveClose, reject) => {
    server.close((error) => {
      if (error) reject(error);
      else resolveClose();
    });
  });
}

export function buildDesktopForE2e(): void {
  const command = npmRunScriptCommand("build");
  const result = spawnSync(command.command, command.args, {
    cwd: desktopRoot,
    env: process.env,
    stdio: "pipe",
    shell: false,
    encoding: "utf8"
  });
  if (result.status !== 0) {
    const stdout = typeof result.stdout === "string" ? result.stdout.trim() : "";
    const stderr = typeof result.stderr === "string" ? result.stderr.trim() : "";
    throw new Error(
      [
        "DESKTOP_E2E_BUILD_FAILED",
        result.error ? `spawn error: ${result.error.message}` : "",
        result.signal ? `signal: ${result.signal}` : "",
        stdout,
        stderr
      ]
        .filter(Boolean)
        .join("\n")
    );
  }
}

export async function launchElectronApp(fixtureSidecar: FixtureSidecar): Promise<ElectronApplication> {
  const executablePath = require("electron") as string;
  const userDataDir = mkdtempSync(join(tmpdir(), "yagcode-electron-e2e-"));
  const { YAGCODE_CAPTURE_LANDING_SCREENSHOTS: _captureLandingScreenshots, ...electronEnv } = process.env;
  const app = await electron.launch({
    executablePath,
    args: [`--user-data-dir=${userDataDir}`, resolve(desktopRoot, "dist/main/main.js")],
    cwd: desktopRoot,
    env: {
      ...electronEnv,
      YAGCODE_PROJECT_ROOT: repoRoot,
      YAGCODE_SIDECAR_BASE_URL: fixtureSidecar.baseUrl,
      YAGCODE_SIDECAR_TOKEN: fixtureSidecar.token,
      YAGCODE_DESKTOP_ORIGIN: fixtureSidecar.origin,
      YAGCODE_E2E_DIRECTORY_PATH: fixtureSidecar.projectPath,
      YAGCODE_E2E: "1"
    }
  });
  electronUserDataDirs.set(app, userDataDir);
  return app;
}

async function closeElectronApp(app: ElectronApplication): Promise<void> {
  const child = app.process();
  const userDataDir = electronUserDataDirs.get(app);
  await app.evaluate(({ app: electronApp }) => {
    electronApp.exit(0);
  }).catch(() => {});
  await Promise.race([
    app.close(),
    new Promise<void>((resolveClose) => {
      setTimeout(resolveClose, 1_000);
    }),
  ]).catch(() => {});
  if (child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === "win32" && child.pid !== undefined) {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", shell: false });
  } else {
    child.kill("SIGTERM");
    await new Promise<void>((resolveClose) => {
      const timer = setTimeout(resolveClose, 750);
      child.once("exit", () => {
        clearTimeout(timer);
        resolveClose();
      });
    });
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
  }
  await new Promise<void>((resolveClose) => {
    const timer = setTimeout(resolveClose, 1_000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolveClose();
    });
  });
  if (userDataDir !== undefined) {
    rmSync(userDataDir, { force: true, recursive: true });
    electronUserDataDirs.delete(app);
  }
}

export async function completeFirstRunOnboarding(window: Page, fixtureSidecar: FixtureSidecar): Promise<void> {
  const onboardingHeading = window.locator("#onboarding-heading");
  await expect(onboardingHeading).toHaveText("创建 AGENT 档案");
  await window.getByRole("textbox", { name: "AGENT 名称" }).fill("测试 Agent");
  await window.getByRole("button", { name: "创建 AGENT", exact: true }).click();

  await expect(onboardingHeading).toHaveText("打开一个本地项目文件夹");
  await window.getByRole("button", { name: "选择文件夹", exact: true }).click();
  await expect(window.getByRole("textbox", { name: "项目路径" })).toHaveValue(fixtureSidecar.projectPath);
  await window.getByRole("button", { name: "打开项目", exact: true }).click();

  await expect(onboardingHeading).toHaveText("绑定至少一个模型 Provider");
  await window.getByLabel("Provider", { exact: true }).selectOption("njusehub");
  await window.getByRole("textbox", { name: "模型 ID" }).fill("qwen-turbo");
  await window.getByLabel("API Key").fill("test-credential-value");
  await window.getByRole("button", { name: "绑定 API", exact: true }).click();

  await expect(onboardingHeading).toHaveText("创建第一个 bug 修复线程");
  await window.getByRole("textbox", { name: "线程标题" }).fill("调试一个权限边界 bug");
  await window.getByRole("button", { name: "创建线程", exact: true }).click();
  await expect(window.getByRole("heading", { name: "调试一个权限边界 bug" })).toBeVisible();
}

export const test = base.extend<{
  fixtureSidecar: FixtureSidecar;
  electronApp: ElectronApplication;
  window: Page;
}>({
  fixtureSidecar: async ({}, use) => {
    const sidecar = await startFixtureSidecar();
    try {
      await use(sidecar);
    } finally {
      await sidecar.close();
    }
  },
  electronApp: async ({ fixtureSidecar }, use) => {
    buildDesktopForE2e();
    const app = await launchElectronApp(fixtureSidecar);
    try {
      await use(app);
    } finally {
      fixtureSidecar.setBlockingRuns([]);
      await closeElectronApp(app);
    }
  },
  window: async ({ electronApp }, use) => {
    const page = await electronApp.firstWindow();
    await page.waitForLoadState("domcontentloaded");
    await use(page);
  }
});

export { expect };
