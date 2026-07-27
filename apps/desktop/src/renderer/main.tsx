import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.js";
import { createSidecarClient } from "./api/client.js";
import type { SidecarClient, WorkbenchApiSnapshot, WorkbenchCommand } from "./api/client.js";
import { createScreenshotSceneClient, screenshotInitialPanel } from "./demo/screenshotClient.js";

type BootstrapWindow = Window & {
  yagcodeClient?: SidecarClient;
  yagcode?: {
    getStartupConnection?: () => Promise<unknown>;
    requestIntentWindow?: (intentId: string) => Promise<unknown>;
  };
};

interface StartupConnection {
  baseUrl: string;
  token: string;
  connected: boolean;
}

interface ViteInjectedEnv {
  VITE_YAGCODE_SIDECAR_BASE_URL?: string;
  VITE_YAGCODE_SIDECAR_TOKEN?: string;
}

function isStartupConnection(value: unknown): value is StartupConnection {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.baseUrl === "string" && typeof record.token === "string" && typeof record.connected === "boolean";
}

function createUnavailableClient(): SidecarClient {
  const unavailableSnapshot: WorkbenchApiSnapshot = {
    profile_id: "profile-1",
    generation: 0,
    last_sequence: 0,
    connection: "disconnected",
    onboarding: {
      step: "CREATE_AGENT",
      completed_steps: [],
      headline: "等待 sidecar",
      detail: "Electron preload 尚未注入真实连接，当前只能显示不可用状态。",
    },
    navigation: {
      profiles: [],
      projects: [],
      threads: [],
      run_state: "IDLE",
    },
    task: {
      thread_id: "thread-1",
      title: "等待 sidecar 连接",
      run_state: "IDLE",
      provider: "openai",
      model: "gpt-5.6-sol",
      models: [{ id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" }],
      plan_mode: true,
      budget: { token_limit: 1500, time_limit_minutes: 60 },
      retry_policy: { connection_retries: 5, tool_retries: 3, model_retries: 5 },
      compact_after_lines: 1500,
      append_enabled: false,
      error: {
        reason: "Electron preload 尚未注入 sidecar client",
        side_effect_state: "renderer 未获得文件或 shell 能力",
        scope: "当前窗口",
        recovery: "接入 Electron Main/preload 后恢复真实 sidecar",
      },
    },
    review_view: {
      kind: "review",
      review_id: "review-unavailable",
      state: "NOT_READY",
      generation: 0,
      summary: "sidecar 未连接，暂无 diff 和验证证据。",
    },
    evidence: {
      diff: { files_changed: 0, additions: 0, deletions: 0 },
      diff_files: [],
      validations: [{ id: "sidecar", title: "sidecar 连接", detail: "等待 Electron Main 注入", status: "pending" }],
      risks: ["当前 renderer 只能展示状态，不能执行本地动作"],
      uncovered: ["真实桌面生命周期由 覆盖"],
      approval_actions: [],
    },
    settings: {
      credential_statuses: [
        {
          provider: "openai",
          status: "missing",
          updated_at: null,
          detail: "sidecar 未连接",
          docs_url: "https://platform.openai.com/docs/api-reference/responses",
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
      project_memories: [],
      cross_project_suggestions: [],
    },
    audit: {
      entries: [],
    },
    demo: {
      selected_panel: "审查",
      theme_mode: "system",
      locale: "zh-Hans",
      agent_name: null,
      project_path: null,
      project: null,
      providers: [
        {
          provider: "openai",
          label: "OpenAI",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "sidecar 未连接",
          docs_url: "https://platform.openai.com/docs/api-reference/responses",
        },
        {
          provider: "qwen",
          label: "Qwen",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "sidecar 未连接",
          docs_url: "https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope",
        },
        {
          provider: "glm",
          label: "GLM",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "sidecar 未连接",
          docs_url: "https://docs.bigmodel.cn/api-reference/model-api/chat-completion",
        },
        {
          provider: "deepseek",
          label: "DeepSeek",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "sidecar 未连接",
          docs_url: "https://api-docs.deepseek.com/api/create-chat-completion",
        },
        {
          provider: "minimax",
          label: "MiniMax",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "sidecar 未连接",
          docs_url: "https://platform.minimaxi.com/document/ChatCompletion%20v2",
        },
        {
          provider: "kimi",
          label: "Kimi / Moonshot",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "sidecar 未连接",
          docs_url: "https://platform.moonshot.cn/docs/api/chat",
        },
        {
          provider: "njusehub",
          label: "NJU SE Hub",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "sidecar 未连接",
          docs_url: "https://dongshao.github.io/GAIHub1/njusehubdoc.html",
        },
      ],
      privacy: {
        preview_confirmed: false,
        retention: "permanent",
        preview_items: [],
      },
      permissions: {
        mode: "yes_once",
        options: [
          { id: "yes_once", label: "Yes once", detail: "仅本次。", active: true },
          { id: "yes_similar_session", label: "Yes to similar actions for this app session", detail: "本会话相似操作。", active: false },
          { id: "full_access", label: "Full access for this app session", detail: "本会话完全访问。", active: false },
        ],
      },
      checkpoints: [],
    },
  };
  return {
    async getSnapshot() {
      return unavailableSnapshot;
    },
    async getReview() {
      return unavailableSnapshot.review_view;
    },
    subscribe() {
      return { close() {} };
    },
    async command(_command: WorkbenchCommand) {
      return { ok: false, reason: "SIDECAR_DISCONNECTED" };
    },
  };
}

function devInjectedConnection(): StartupConnection | null {
  const viteEnv = (import.meta as unknown as { env?: ViteInjectedEnv }).env;
  const baseUrl = viteEnv?.VITE_YAGCODE_SIDECAR_BASE_URL;
  const token = viteEnv?.VITE_YAGCODE_SIDECAR_TOKEN;
  if (typeof baseUrl !== "string" || baseUrl.length === 0) return null;
  if (typeof token !== "string" || token.length === 0) return null;
  return { baseUrl, token, connected: true };
}

function screenshotSceneFromLocation(): string | null {
  try {
    return new URL(window.location.href).searchParams.get("yagcodeScreenshotScene");
  } catch {
    return null;
  }
}

const root = document.getElementById("root");
if (root === null) throw new Error("ROOT_ELEMENT_MISSING");

const screenshotScene = screenshotSceneFromLocation();
const initialFloatingPanel = screenshotInitialPanel(screenshotScene);

async function resolveClient(): Promise<SidecarClient> {
  const bootstrap = window as BootstrapWindow;
  if (bootstrap.yagcodeClient) return bootstrap.yagcodeClient;
  const screenshotClient = createScreenshotSceneClient(screenshotScene);
  if (screenshotClient !== null) return screenshotClient;
  const connection = await bootstrap.yagcode?.getStartupConnection?.();
  if (isStartupConnection(connection) && connection.connected === true && connection.baseUrl.length > 0 && connection.token.length > 0) {
    return createSidecarClient({ baseUrl: connection.baseUrl, token: connection.token });
  }
  const devConnection = devInjectedConnection();
  if (devConnection !== null) {
    return createSidecarClient({ baseUrl: devConnection.baseUrl, token: devConnection.token });
  }
  return createUnavailableClient();
}

const rootHandle = createRoot(root);
rootHandle.render(
  <React.StrictMode>
    <App client={createUnavailableClient()} initialFloatingPanel={initialFloatingPanel} />
  </React.StrictMode>,
);

void resolveClient().catch(() => createUnavailableClient()).then((client) => {
  rootHandle.render(
    <React.StrictMode>
      <App client={client} initialFloatingPanel={initialFloatingPanel} />
    </React.StrictMode>,
  );
});
