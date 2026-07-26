import { test as base, _electron as electron, expect } from "@playwright/test";
import type { ElectronApplication, Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import type { IncomingMessage, Server, ServerResponse } from "node:http";
import { createRequire } from "node:module";
import type { Socket } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const repoRoot = resolve(desktopRoot, "../..");

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
  consumedIntents(): readonly string[];
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

function fixtureSnapshot() {
  return {
    profile_id: "profile-1",
    generation: 1,
    last_sequence: 1,
    connection: "connected",
    navigation: {
      profiles: [{ id: "profile-1", label: "默认档案" }],
      projects: [{ id: "project-1", label: "yagcode", active: true }],
      threads: [{ id: "thread-1", label: "桌面联调", unread_approvals: 1, memory_suggestions: 0 }],
      run_state: "INTERRUPTED"
    },
    task: {
      thread_id: "thread-1",
      title: "桌面生命周期",
      run_state: "INTERRUPTED",
      provider: "openai",
      model: "gpt-5.6-sol",
      models: [
        { id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" },
        { id: "gpt-5.6-terra", label: "OpenAI gpt-5.6-terra", provider: "openai" },
        { id: "qwen-plus", label: "Qwen Plus", provider: "qwen" },
        { id: "glm-4.5", label: "GLM 4.5", provider: "glm" },
        { id: "deepseek-chat", label: "DeepSeek Chat", provider: "deepseek" }
      ],
      plan_mode: true,
      budget: { token_limit: 1500, time_limit_minutes: 60 },
      retry_policy: { connection_retries: 5, tool_retries: 3, model_retries: 5 },
      compact_after_lines: 1500,
      append_enabled: true,
      error: {
        reason: "fixture sidecar 已连接",
        side_effect_state: "未写入工作区",
        scope: "当前 E2E",
        recovery: "停止运行后允许关闭"
      }
    },
    review_view: {
      kind: "review",
      review_id: "review-1",
      state: "READY",
      generation: 1,
      summary: "fixture review"
    },
    evidence: {
      diff: { files_changed: 1, additions: 12, deletions: 2 },
      validations: [{ id: "e2e", title: "Electron E2E", detail: "fixture", status: "running" }],
      risks: ["fixture sidecar 不执行真实文件操作"],
      uncovered: ["生产 sidecar 打包由 覆盖"],
      approval_actions: [{ id: "review-1", label: "接受并提交", enabled: true, high_risk: true }]
    },
    settings: {
      credential_statuses: [{ provider: "openai", status: "missing", updated_at: null }],
      retention_options: ["permanent", "30d", "60d", "90d", "180d", "1y", "2y"],
      selected_retention: "permanent"
    },
    memory: { project_memories: [], cross_project_suggestions: [] },
    audit: { entries: [] }
  };
}

export function startFixtureSidecar({
  token = "fixture-startup-token",
  origin = "app://yagcode"
}: {
  token?: string;
  origin?: string;
} = {}): Promise<FixtureSidecar> {
  const blockingRuns: BlockingRun[] = [];
  const consumed: string[] = [];
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
    if (!authenticated(request, token, origin)) {
      sendJson(response, 401, { detail: { reason_code: "SIDECAR_AUTH_REQUIRED" } }, origin);
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/health") {
      sendJson(response, 200, { version: "0.1.0", status: "ok", capabilities: { sse: true } }, origin);
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/workbench") {
      sendJson(response, 200, fixtureSnapshot(), origin);
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
        consumedIntents() {
          return consumed;
        },
        setBlockingRuns(runs) {
          blockingRuns.splice(0, blockingRuns.length, ...runs);
        },
        close() {
          if (closed) return Promise.resolve();
          closed = true;
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
  const app = await electron.launch({
    executablePath,
    args: [resolve(desktopRoot, "dist/main/main.js")],
    cwd: desktopRoot,
    env: {
      ...process.env,
      YAGCODE_PROJECT_ROOT: repoRoot,
      YAGCODE_SIDECAR_BASE_URL: fixtureSidecar.baseUrl,
      YAGCODE_SIDECAR_TOKEN: fixtureSidecar.token,
      YAGCODE_DESKTOP_ORIGIN: fixtureSidecar.origin,
      YAGCODE_E2E: "1"
    }
  });
  return app;
}

async function closeElectronApp(app: ElectronApplication): Promise<void> {
  const child = app.process();
  if (process.platform === "win32" && child.pid !== undefined) {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", shell: false });
  } else if (!child.killed) {
    child.kill();
  }
  await new Promise((resolveClose) => setTimeout(resolveClose, 250));
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
