import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { join, resolve } from "node:path";
import { DESKTOP_ORIGIN } from "./security.js";

export interface StartupConnection {
  baseUrl: string;
  token: string;
  origin: string;
  connected: boolean;
}

export interface BlockingRun {
  id: string;
  state: string;
  title?: string;
}

export interface IntentChallenge {
  intent_id: string;
  intent_type: string;
  one_time_token: string;
  resource_id: string;
}

export interface PrivilegedActionResult {
  intent_id: string;
  intent_type: string;
  state: "EXECUTED";
}

export interface SidecarEnvironment {
  cwd: string;
  env: NodeJS.ProcessEnv;
  platform: NodeJS.Platform;
}

function token(): string {
  return randomBytes(24).toString("base64url");
}

function findFreePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        server.close(() => reject(new Error("SIDECAR_PORT_MISSING")));
        return;
      }
      const port = address.port;
      server.close(() => resolvePort(port));
    });
  });
}

function parseError(value: unknown, fallback: string): string {
  if (typeof value !== "object" || value === null || !("detail" in value)) return fallback;
  const detail = (value as { detail?: unknown }).detail;
  if (typeof detail === "object" && detail !== null && "reason_code" in detail) {
    const reason = (detail as { reason_code?: unknown }).reason_code;
    if (typeof reason === "string") return reason;
  }
  return fallback;
}

export class SidecarController {
  private child: ChildProcess | undefined;
  private connection: StartupConnection | undefined;

  constructor(private readonly environment: SidecarEnvironment) {}

  async start(): Promise<StartupConnection> {
    if (this.connection !== undefined) return this.connection;
    const origin = this.environment.env.YAGCODE_DESKTOP_ORIGIN ?? DESKTOP_ORIGIN;
    const externalBaseUrl = this.environment.env.YAGCODE_SIDECAR_BASE_URL;
    if (externalBaseUrl !== undefined && externalBaseUrl.length > 0) {
      this.connection = {
        baseUrl: externalBaseUrl.replace(/\/+$/u, ""),
        token: this.environment.env.YAGCODE_SIDECAR_TOKEN ?? token(),
        origin,
        connected: false
      };
      await this.waitForHealth();
      this.connection = { ...this.connection, connected: true };
      return this.connection;
    }

    const port = await findFreePort();
    const startupToken = token();
    const python = this.resolvePython();
    this.child = spawn(
      python,
      [
        "-m",
        "yagcode.api.server",
        "--host",
        "127.0.0.1",
        "--port",
        String(port),
        "--origin",
        origin,
        "--token",
        startupToken
      ],
      {
        cwd: this.environment.cwd,
        env: { ...this.environment.env, PYTHONPATH: join(this.environment.cwd, "src") },
        shell: false,
        stdio: ["ignore", "pipe", "pipe"]
      }
    );
    this.connection = {
      baseUrl: `http://127.0.0.1:${port}`,
      token: startupToken,
      origin,
      connected: false
    };
    await this.waitForHealth();
    this.connection = { ...this.connection, connected: true };
    return this.connection;
  }

  connectionView(): StartupConnection {
    if (this.connection === undefined) {
      return { baseUrl: "", token: "", origin: DESKTOP_ORIGIN, connected: false };
    }
    return this.connection;
  }

  async getBlockingRuns(): Promise<readonly BlockingRun[]> {
    try {
      const value = await this.fetchJson("/api/v1/desktop/blocking-runs");
      if (typeof value !== "object" || value === null || !("runs" in value) || !Array.isArray(value.runs)) return [];
      return value.runs.filter(isBlockingRun);
    } catch {
      return [];
    }
  }

  async createReviewIntent(reviewId: string): Promise<IntentChallenge> {
    const value = await this.fetchJson(`/api/v1/review/${encodeURIComponent(reviewId)}/accept-intent`, {
      method: "POST"
    });
    if (!isIntentChallenge(value)) throw new Error("INTENT_CHALLENGE_INVALID");
    return value;
  }

  async consumeIntent(challenge: IntentChallenge): Promise<PrivilegedActionResult> {
    const value = await this.fetchJson(`/api/v1/intents/${encodeURIComponent(challenge.intent_id)}/consume`, {
      body: JSON.stringify({ one_time_token: challenge.one_time_token }),
      headers: { "content-type": "application/json", "X-Yagcode-Principal": "main" },
      method: "POST"
    });
    if (!isPrivilegedActionResult(value)) throw new Error("INTENT_RESULT_INVALID");
    return value;
  }

  async stop(): Promise<void> {
    const child = this.child;
    this.child = undefined;
    this.connection = undefined;
    if (child === undefined || child.killed) return;
    child.kill(this.environment.platform === "win32" ? undefined : "SIGTERM");
  }

  private resolvePython(): string {
    const override = this.environment.env.YAGCODE_PYTHON;
    if (override !== undefined && override.length > 0) return override;
    const relative = this.environment.platform === "win32" ? join(".venv", "Scripts", "python.exe") : join(".venv", "bin", "python");
    const resolved = resolve(this.environment.cwd, relative);
    if (!existsSync(resolved)) throw new Error("PYTHON_VENV_MISSING");
    return resolved;
  }

  private async waitForHealth(): Promise<void> {
    let lastError: unknown;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        const health = await this.fetchJson("/api/v1/health");
        if (typeof health === "object" && health !== null && "status" in health && health.status === "ok") return;
      } catch (error) {
        lastError = error;
      }
      await new Promise((resolveWait) => setTimeout(resolveWait, 150));
    }
    throw lastError instanceof Error ? lastError : new Error("SIDECAR_HEALTH_TIMEOUT");
  }

  private async fetchJson(path: string, init: RequestInit = {}): Promise<Record<string, unknown>> {
    const connection = this.connection;
    if (connection === undefined) throw new Error("SIDECAR_NOT_STARTED");
    const headers = new Headers(init.headers);
    headers.set("authorization", `Bearer ${connection.token}`);
    headers.set("origin", connection.origin);
    const response = await fetch(`${connection.baseUrl}${path}`, { ...init, headers });
    let value: unknown = {};
    try {
      value = (await response.json()) as unknown;
    } catch {
      value = {};
    }
    if (!response.ok) throw new Error(parseError(value, `HTTP_${response.status}`));
    if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("SIDECAR_JSON_INVALID");
    return value as Record<string, unknown>;
  }
}

function isBlockingRun(value: unknown): value is BlockingRun {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.id === "string" && typeof record.state === "string";
}

function isIntentChallenge(value: unknown): value is IntentChallenge {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.intent_id === "string" &&
    typeof record.intent_type === "string" &&
    typeof record.one_time_token === "string" &&
    typeof record.resource_id === "string"
  );
}

function isPrivilegedActionResult(value: unknown): value is PrivilegedActionResult {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.intent_id === "string" && typeof record.intent_type === "string" && record.state === "EXECUTED";
}
