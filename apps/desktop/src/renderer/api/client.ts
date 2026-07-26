import type { EventEnvelope, ReviewView } from "@yagcode/contracts";
import { parseEventEnvelope, readSseMessages, SchemaValidationError } from "./events.js";

export type ConnectionState = "connected" | "disconnected" | "resync-required";
export type ValidationStatus = "passed" | "failed" | "running" | "pending" | "warning";

export interface WorkbenchApiSnapshot {
  profile_id: string;
  generation: number;
  last_sequence: number;
  connection: ConnectionState;
  navigation: NavigationApiView;
  task: TaskApiView;
  review_view: ReviewView;
  evidence: EvidenceApiView;
  settings: SettingsApiView;
  memory: MemoryApiView;
  audit: AuditApiView;
}

export interface NavigationApiView {
  profiles: readonly { id: string; label: string }[];
  projects: readonly { id: string; label: string; active: boolean }[];
  threads: readonly { id: string; label: string; unread_approvals: number; memory_suggestions: number }[];
  run_state: string;
}

export interface TaskApiView {
  thread_id: string;
  title: string;
  run_state: string;
  provider: string;
  model: string;
  models: readonly { id: string; label: string; provider: string }[];
  plan_mode: boolean;
  budget: { token_limit: number; time_limit_minutes: number };
  retry_policy: { connection_retries: number; tool_retries: number; model_retries: number };
  compact_after_lines: number;
  append_enabled: boolean;
  error?: { reason: string; side_effect_state: string; scope: string; recovery: string };
}

export interface EvidenceApiView {
  diff: { files_changed: number; additions: number; deletions: number };
  validations: readonly { id: string; title: string; detail: string; status: ValidationStatus; command?: string }[];
  risks: readonly string[];
  uncovered: readonly string[];
  approval_actions: readonly { id: string; label: string; enabled: boolean; high_risk: boolean }[];
}

export interface SettingsApiView {
  credential_statuses: readonly { provider: string; status: "present" | "missing" | "error"; updated_at: string | null }[];
  retention_options: readonly string[];
  selected_retention: string;
}

export interface MemoryApiView {
  project_memories: readonly { id: string; title: string; detail: string; pinned: boolean }[];
  cross_project_suggestions: readonly { id: string; title: string; detail: string }[];
}

export interface AuditApiView {
  entries: readonly { id: string; title: string; detail: string; at: string }[];
}

export interface SubscribeArgs {
  profileId: string;
  lastSequence: number;
  onEvent(event: EventEnvelope): void;
  onDisconnect(reason: string): void;
}

export interface WorkbenchCommand {
  type: string;
  payload?: unknown;
}

export type CommandResult = { ok: true } | { ok: false; reason: string };
export interface SidecarSubscription {
  close(): void;
}

export interface SseTransport {
  connect(args: {
    url: string;
    headers: Record<string, string>;
    onMessage(raw: string): void;
    onDisconnect(reason: string): void;
  }): SidecarSubscription;
}

export interface SidecarClient {
  getSnapshot(): Promise<WorkbenchApiSnapshot>;
  getReview(reviewId: string): Promise<ReviewView>;
  subscribe(args: SubscribeArgs): SidecarSubscription;
  command(command: WorkbenchCommand): Promise<CommandResult>;
}

export interface SidecarClientOptions {
  baseUrl: string;
  token: string;
  apiPrefix?: string;
  fetchImpl?: typeof fetch;
  sseTransport?: SseTransport;
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/u, "");
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireReviewView(value: unknown): ReviewView {
  if (!isRecord(value)) throw new SchemaValidationError(["/ must be object"]);
  const kind = readString(value, "kind");
  const state = readString(value, "state");
  if (kind !== "review") throw new SchemaValidationError(["/kind must be review"]);
  if (!["NOT_READY", "INCOMPLETE", "READY", "ACCEPTING", "ACCEPTED", "REJECTED", "CONFLICT", "RECOVERY_REQUIRED"].includes(state)) {
    throw new SchemaValidationError(["/state invalid"]);
  }
  return {
    generation: readNumber(value, "generation"),
    kind: "review",
    review_id: readString(value, "review_id"),
    state: state as ReviewView["state"],
    summary: readString(value, "summary"),
  };
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string") throw new SchemaValidationError([`/${key} must be string`]);
  return value;
}

function readNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number") throw new SchemaValidationError([`/${key} must be number`]);
  return value;
}

function defaultSseTransport(fetchImpl: typeof fetch): SseTransport {
  return {
    connect({ url, headers, onMessage, onDisconnect }) {
      const controller = new AbortController();
      void fetchImpl(url, { headers, signal: controller.signal })
        .then(async (response) => {
          if (!response.ok || response.body === null) {
            onDisconnect("SSE_CONNECT_FAILED");
            return;
          }
          await readSseMessages(response.body, onMessage);
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          onDisconnect(error instanceof Error ? error.message : "SSE_CONNECT_FAILED");
        });
      return {
        close() {
          controller.abort();
        },
      };
    },
  };
}

function normalizeApiPrefix(apiPrefix: string | undefined): string {
  const value = apiPrefix ?? "/api/v1";
  return `/${value.replace(/^\/+|\/+$/gu, "")}`;
}

function buildEventUrl(baseUrl: string, apiPrefix: string, profileId: string, lastSequence: number): string {
  const url = new URL(`${baseUrl}${apiPrefix}/events`);
  url.searchParams.set("profile_id", profileId);
  url.searchParams.set("last_sequence", String(lastSequence));
  return url.toString();
}

export function createSidecarClient(options: SidecarClientOptions): SidecarClient {
  const baseUrl = normalizeBaseUrl(options.baseUrl);
  const apiPrefix = normalizeApiPrefix(options.apiPrefix);
  const fetchImpl = options.fetchImpl ?? fetch;
  const sseTransport = options.sseTransport ?? defaultSseTransport(fetchImpl);
  let connection: ConnectionState = "connected";

  async function fetchJson(path: string, init: RequestInit = {}): Promise<unknown> {
    const headers = new Headers(init.headers);
    for (const [key, value] of Object.entries(authHeaders(options.token))) headers.set(key, value);
    const response = await fetchImpl(`${baseUrl}${apiPrefix}${path}`, { ...init, headers });
    if (!response.ok) throw new Error(`HTTP_${response.status}`);
    return (await response.json()) as unknown;
  }

  return {
    async getSnapshot() {
      const value = await fetchJson("/workbench");
      if (!isRecord(value)) throw new SchemaValidationError(["/ must be object"]);
      return value as unknown as WorkbenchApiSnapshot;
    },
    async getReview(reviewId) {
      return requireReviewView(await fetchJson(`/reviews/${encodeURIComponent(reviewId)}`));
    },
    subscribe({ profileId, lastSequence, onEvent, onDisconnect }) {
      return sseTransport.connect({
        url: buildEventUrl(baseUrl, apiPrefix, profileId, lastSequence),
        headers: authHeaders(options.token),
        onMessage(raw) {
          try {
            const event = parseEventEnvelope(raw);
            connection = "connected";
            onEvent(event);
          } catch (error: unknown) {
            connection = "disconnected";
            const reason = error instanceof SchemaValidationError ? error.code : "SSE_PARSE_FAILED";
            onDisconnect(reason);
          }
        },
        onDisconnect(reason) {
          connection = "disconnected";
          onDisconnect(reason);
        },
      });
    },
    async command(command) {
      if (connection !== "connected") return { ok: false, reason: "SIDECAR_DISCONNECTED" };
      const value = await fetchJson("/commands", {
        body: JSON.stringify(command),
        headers: { "content-type": "application/json" },
        method: "POST",
      });
      if (!isRecord(value) || value.ok !== true) return { ok: false, reason: "COMMAND_REJECTED" };
      return { ok: true };
    },
  };
}
