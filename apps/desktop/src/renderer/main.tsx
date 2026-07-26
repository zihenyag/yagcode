import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.js";
import { createSidecarClient } from "./api/client.js";
import type { SidecarClient, WorkbenchApiSnapshot, WorkbenchCommand } from "./api/client.js";

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
    navigation: {
      profiles: [{ id: "profile-1", label: "默认档案" }],
      projects: [{ id: "project-1", label: "未连接项目", active: true }],
      threads: [{ id: "thread-1", label: "等待 sidecar", unread_approvals: 0, memory_suggestions: 0 }],
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
      validations: [{ id: "sidecar", title: "sidecar 连接", detail: "等待 Electron Main 注入", status: "pending" }],
      risks: ["当前 renderer 只能展示状态，不能执行本地动作"],
      uncovered: ["真实桌面生命周期由 覆盖"],
      approval_actions: [],
    },
    settings: {
      credential_statuses: [{ provider: "openai", status: "missing", updated_at: null }],
      retention_options: ["permanent", "30d", "60d", "90d", "180d", "1y", "2y"],
      selected_retention: "permanent",
    },
    memory: {
      project_memories: [],
      cross_project_suggestions: [],
    },
    audit: {
      entries: [],
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

const root = document.getElementById("root");
if (root === null) throw new Error("ROOT_ELEMENT_MISSING");

async function resolveClient(): Promise<SidecarClient> {
  const bootstrap = window as BootstrapWindow;
  if (bootstrap.yagcodeClient) return bootstrap.yagcodeClient;
  const connection = await bootstrap.yagcode?.getStartupConnection?.();
  if (isStartupConnection(connection) && connection.connected === true && connection.baseUrl.length > 0 && connection.token.length > 0) {
    return createSidecarClient({ baseUrl: connection.baseUrl, token: connection.token });
  }
  return createUnavailableClient();
}

const rootHandle = createRoot(root);
rootHandle.render(
  <React.StrictMode>
    <App client={createUnavailableClient()} />
  </React.StrictMode>,
);

void resolveClient().catch(() => createUnavailableClient()).then((client) => {
  rootHandle.render(
    <React.StrictMode>
      <App client={client} />
    </React.StrictMode>,
  );
});
