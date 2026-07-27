import type { EventEnvelope, ReviewView } from "@yagcode/contracts";
import { parseEventEnvelope, readSseMessages, SchemaValidationError } from "./events.js";

export type ConnectionState = "connected" | "disconnected" | "resync-required";
export type ValidationStatus = "passed" | "failed" | "running" | "pending" | "warning";

export interface WorkbenchApiSnapshot {
  profile_id: string;
  generation: number;
  last_sequence: number;
  connection: ConnectionState;
  onboarding: OnboardingApiView;
  navigation: NavigationApiView;
  task: TaskApiView;
  review_view: ReviewView;
  evidence: EvidenceApiView;
  settings: SettingsApiView;
  memory: MemoryApiView;
  audit: AuditApiView;
  demo: DemoApiView;
}

export type OnboardingStep = "CREATE_AGENT" | "OPEN_FOLDER" | "BIND_API" | "CREATE_THREAD" | "WORKBENCH";
export type ThemeMode = "system" | "light" | "dark";
export type LocaleMode = "zh-Hans" | "zh-Hant" | "en-US" | "en-GB";

export interface OnboardingApiView {
  step: OnboardingStep;
  completed_steps: readonly OnboardingStep[];
  headline: string;
  detail: string;
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
  messages?: readonly { id: string; role: "user" | "assistant" | "system"; title: string; body: string; at: string }[];
  error?: { reason: string; side_effect_state: string; scope: string; recovery: string } | null;
}

export interface EvidenceApiView {
  diff: { files_changed: number; additions: number; deletions: number };
  diff_files: readonly {
    path: string;
    status: "modified" | "added" | "deleted";
    additions: number;
    deletions: number;
    lines: readonly {
      kind: "context" | "add" | "delete" | "hunk";
      old_line: number | null;
      new_line: number | null;
      content: string;
    }[];
  }[];
  validations: readonly { id: string; title: string; detail: string; status: ValidationStatus; command?: string }[];
  risks: readonly string[];
  uncovered: readonly string[];
  approval_actions: readonly { id: string; label: string; enabled: boolean; high_risk: boolean }[];
}

export interface SettingsApiView {
  credential_statuses: readonly {
    provider: string;
    status: "verified" | "missing" | "error";
    updated_at: string | null;
    detail: string;
    docs_url: string;
  }[];
  retention_options: readonly string[];
  selected_retention: string;
  theme_mode: ThemeMode;
  locale: LocaleMode;
  theme_options: readonly { id: ThemeMode; label: string }[];
  locale_options: readonly { id: LocaleMode; label: string }[];
}

export interface MemoryApiView {
  project_memories: readonly { id: string; title: string; detail: string; pinned: boolean }[];
  cross_project_suggestions: readonly { id: string; title: string; detail: string }[];
}

export interface AuditApiView {
  entries: readonly { id: string; title: string; detail: string; at: string }[];
}

export interface DemoApiView {
  selected_panel: string;
  theme_mode: ThemeMode;
  locale: LocaleMode;
  agent_name: string | null;
  project_path: string | null;
  project: {
    path: string;
    label: string;
    is_git_repo: boolean;
    git_root: string | null;
    branch: string | null;
    status_summary: readonly string[];
    error: string | null;
  } | null;
  providers: readonly {
    provider: string;
    label: string;
    configured: boolean;
    status: "verified" | "missing" | "error";
    updated_at: string | null;
    detail: string;
    docs_url: string;
  }[];
  privacy: {
    preview_confirmed: boolean;
    retention: string;
    preview_items: readonly { id: string; category: string; source: string; preview: string; confirmed: boolean }[];
  };
  permissions: {
    mode: string;
    options: readonly { id: string; label: string; detail: string; active: boolean }[];
  };
  checkpoints: readonly { id: string; label: string; detail: string; current: boolean }[];
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
      if (!isRecord(value)) return { ok: false, reason: "COMMAND_REJECTED" };
      if (value.ok !== true) {
        return { ok: false, reason: typeof value.reason === "string" ? value.reason : "COMMAND_REJECTED" };
      }
      return { ok: true };
    },
  };
}
