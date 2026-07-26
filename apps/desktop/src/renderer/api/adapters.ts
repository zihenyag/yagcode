import type { EventEnvelope, ReviewView } from "@yagcode/contracts";
import type { ValidationStatus } from "./client.js";
import { SchemaValidationError, toEventEnvelope } from "./events.js";

export interface ReviewPanelModel {
  reviewId: string;
  generation: number;
  state: ReviewView["state"];
  summary: string;
}

export interface RunStateEventModel {
  runId: string;
  runState: string;
  sequence: number;
  generation: number;
}

export interface WorkbenchModel {
  profileId: string;
  generation: number;
  lastSequence: number;
  connection: "connected" | "disconnected" | "resync-required";
  navigation: NavigationModel;
  task: TaskModel;
  evidence: EvidenceModel;
  settings: SettingsModel;
  memory: MemoryModel;
  audit: AuditModel;
}

export interface NavigationModel {
  profiles: readonly { id: string; label: string }[];
  projects: readonly { id: string; label: string; active: boolean }[];
  threads: readonly { id: string; label: string; unreadApprovals: number; memorySuggestions: number }[];
  runState: string;
}

export interface TaskModel {
  threadId: string;
  title: string;
  runState: string;
  provider: string;
  model: string;
  models: readonly { id: string; label: string; provider: string }[];
  planMode: boolean;
  budget: { tokenLimit: number; timeLimitMinutes: number };
  retryPolicy: { connectionRetries: number; toolRetries: number; modelRetries: number };
  compactAfterLines: number;
  appendEnabled: boolean;
  error?: { reason: string; sideEffectState: string; scope: string; recovery: string };
}

export interface EvidenceModel {
  review: ReviewPanelModel;
  diff: { filesChanged: number; additions: number; deletions: number };
  validations: readonly { id: string; title: string; detail: string; status: ValidationStatus; command?: string }[];
  risks: readonly string[];
  uncovered: readonly string[];
  approvalActions: readonly { id: string; label: string; enabled: boolean; highRisk: boolean }[];
}

export interface SettingsModel {
  credentialStatuses: readonly { provider: string; status: "present" | "missing" | "error"; updatedAt: string | null }[];
  retentionOptions: readonly string[];
  selectedRetention: string;
}

export interface MemoryModel {
  projectMemories: readonly { id: string; title: string; detail: string; pinned: boolean }[];
  crossProjectSuggestions: readonly { id: string; title: string; detail: string }[];
}

export interface AuditModel {
  entries: readonly { id: string; title: string; detail: string; at: string }[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) throw new SchemaValidationError([`${path} must be object`]);
  return value;
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string") throw new SchemaValidationError([`/${key} must be string`]);
  return value;
}

function readNullableString(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  if (value === null) return null;
  if (typeof value !== "string") throw new SchemaValidationError([`/${key} must be string or null`]);
  return value;
}

function readNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number") throw new SchemaValidationError([`/${key} must be number`]);
  return value;
}

function readBoolean(record: Record<string, unknown>, key: string): boolean {
  const value = record[key];
  if (typeof value !== "boolean") throw new SchemaValidationError([`/${key} must be boolean`]);
  return value;
}

function readArray(record: Record<string, unknown>, key: string): readonly unknown[] {
  const value = record[key];
  if (!Array.isArray(value)) throw new SchemaValidationError([`/${key} must be array`]);
  return value;
}

function readValidationStatus(record: Record<string, unknown>, key: string): ValidationStatus {
  const value = readString(record, key);
  if (value === "passed" || value === "failed" || value === "running" || value === "pending" || value === "warning") return value;
  throw new SchemaValidationError([`/${key} invalid validation status`]);
}

function readReviewState(record: Record<string, unknown>, key: string): ReviewView["state"] {
  const value = readString(record, key);
  if (
    value === "NOT_READY" ||
    value === "INCOMPLETE" ||
    value === "READY" ||
    value === "ACCEPTING" ||
    value === "ACCEPTED" ||
    value === "REJECTED" ||
    value === "CONFLICT" ||
    value === "RECOVERY_REQUIRED"
  ) {
    return value;
  }
  throw new SchemaValidationError([`/${key} invalid review state`]);
}

function readConnection(record: Record<string, unknown>): WorkbenchModel["connection"] {
  const value = readString(record, "connection");
  if (value === "connected" || value === "disconnected" || value === "resync-required") return value;
  throw new SchemaValidationError(["/connection invalid"]);
}

export function adaptReviewView(view: unknown): ReviewPanelModel {
  const record = requireRecord(view, "/review");
  const kind = readString(record, "kind");
  if (kind !== "review") throw new SchemaValidationError(["/kind must be review"]);
  return {
    reviewId: readString(record, "review_id"),
    generation: readNumber(record, "generation"),
    state: readReviewState(record, "state"),
    summary: readString(record, "summary"),
  };
}

export function adaptRunStateEvent(event: unknown): RunStateEventModel {
  const envelope: EventEnvelope = toEventEnvelope(event);
  if (envelope.event_type !== "run.state") throw new SchemaValidationError(["/event_type must be run.state"]);
  if (!("run_id" in envelope.payload) || !("state" in envelope.payload)) throw new SchemaValidationError(["/payload must be run.state"]);
  return {
    runId: envelope.payload.run_id,
    runState: envelope.payload.state,
    sequence: envelope.sequence,
    generation: envelope.generation ?? 0,
  };
}

export function adaptSnapshot(snapshot: unknown): WorkbenchModel {
  const root = requireRecord(snapshot, "/");
  const navigation = requireRecord(root.navigation, "/navigation");
  const task = requireRecord(root.task, "/task");
  const budget = requireRecord(task.budget, "/task/budget");
  const retryPolicy = requireRecord(task.retry_policy, "/task/retry_policy");
  const evidence = requireRecord(root.evidence, "/evidence");
  const diff = requireRecord(evidence.diff, "/evidence/diff");
  const settings = requireRecord(root.settings, "/settings");
  const memory = requireRecord(root.memory, "/memory");
  const audit = requireRecord(root.audit, "/audit");
  const error = task.error === undefined ? undefined : requireRecord(task.error, "/task/error");
  const taskError =
    error === undefined
      ? undefined
      : {
          reason: readString(error, "reason"),
          sideEffectState: readString(error, "side_effect_state"),
          scope: readString(error, "scope"),
          recovery: readString(error, "recovery"),
        };
  const taskModel: TaskModel =
    taskError === undefined
      ? {
          threadId: readString(task, "thread_id"),
          title: readString(task, "title"),
          runState: readString(task, "run_state"),
          provider: readString(task, "provider"),
          model: readString(task, "model"),
          models: readArray(task, "models").map((item) => {
            const record = requireRecord(item, "/task/models[]");
            return {
              id: readString(record, "id"),
              label: readString(record, "label"),
              provider: readString(record, "provider"),
            };
          }),
          planMode: readBoolean(task, "plan_mode"),
          budget: {
            tokenLimit: readNumber(budget, "token_limit"),
            timeLimitMinutes: readNumber(budget, "time_limit_minutes"),
          },
          retryPolicy: {
            connectionRetries: readNumber(retryPolicy, "connection_retries"),
            toolRetries: readNumber(retryPolicy, "tool_retries"),
            modelRetries: readNumber(retryPolicy, "model_retries"),
          },
          compactAfterLines: readNumber(task, "compact_after_lines"),
          appendEnabled: readBoolean(task, "append_enabled"),
        }
      : {
          threadId: readString(task, "thread_id"),
          title: readString(task, "title"),
          runState: readString(task, "run_state"),
          provider: readString(task, "provider"),
          model: readString(task, "model"),
          models: readArray(task, "models").map((item) => {
            const record = requireRecord(item, "/task/models[]");
            return {
              id: readString(record, "id"),
              label: readString(record, "label"),
              provider: readString(record, "provider"),
            };
          }),
          planMode: readBoolean(task, "plan_mode"),
          budget: {
            tokenLimit: readNumber(budget, "token_limit"),
            timeLimitMinutes: readNumber(budget, "time_limit_minutes"),
          },
          retryPolicy: {
            connectionRetries: readNumber(retryPolicy, "connection_retries"),
            toolRetries: readNumber(retryPolicy, "tool_retries"),
            modelRetries: readNumber(retryPolicy, "model_retries"),
          },
          compactAfterLines: readNumber(task, "compact_after_lines"),
          appendEnabled: readBoolean(task, "append_enabled"),
          error: taskError,
        };

  return {
    profileId: readString(root, "profile_id"),
    generation: readNumber(root, "generation"),
    lastSequence: readNumber(root, "last_sequence"),
    connection: readConnection(root),
    navigation: {
      profiles: readArray(navigation, "profiles").map((item) => {
        const record = requireRecord(item, "/navigation/profiles[]");
        return {
          id: readString(record, "id"),
          label: readString(record, "label"),
        };
      }),
      projects: readArray(navigation, "projects").map((item) => {
        const record = requireRecord(item, "/navigation/projects[]");
        return {
          id: readString(record, "id"),
          label: readString(record, "label"),
          active: readBoolean(record, "active"),
        };
      }),
      threads: readArray(navigation, "threads").map((item) => {
        const record = requireRecord(item, "/navigation/threads[]");
        return {
          id: readString(record, "id"),
          label: readString(record, "label"),
          unreadApprovals: readNumber(record, "unread_approvals"),
          memorySuggestions: readNumber(record, "memory_suggestions"),
        };
      }),
      runState: readString(navigation, "run_state"),
    },
    task: taskModel,
    evidence: {
      review: adaptReviewView(root.review_view),
      diff: {
        filesChanged: readNumber(diff, "files_changed"),
        additions: readNumber(diff, "additions"),
        deletions: readNumber(diff, "deletions"),
      },
      validations: readArray(evidence, "validations").map((item) => {
        const record = requireRecord(item, "/evidence/validations[]");
        const command = record.command === undefined ? undefined : readString(record, "command");
        return command === undefined
          ? {
              id: readString(record, "id"),
              title: readString(record, "title"),
              detail: readString(record, "detail"),
              status: readValidationStatus(record, "status"),
            }
          : {
              id: readString(record, "id"),
              title: readString(record, "title"),
              detail: readString(record, "detail"),
              status: readValidationStatus(record, "status"),
              command,
            };
      }),
      risks: readArray(evidence, "risks").map((item) => {
        if (typeof item !== "string") throw new SchemaValidationError(["/evidence/risks[] must be string"]);
        return item;
      }),
      uncovered: readArray(evidence, "uncovered").map((item) => {
        if (typeof item !== "string") throw new SchemaValidationError(["/evidence/uncovered[] must be string"]);
        return item;
      }),
      approvalActions: readArray(evidence, "approval_actions").map((item) => {
        const record = requireRecord(item, "/evidence/approval_actions[]");
        return {
          id: readString(record, "id"),
          label: readString(record, "label"),
          enabled: readBoolean(record, "enabled"),
          highRisk: readBoolean(record, "high_risk"),
        };
      }),
    },
    settings: {
      credentialStatuses: readArray(settings, "credential_statuses").map((item) => {
        const record = requireRecord(item, "/settings/credential_statuses[]");
        const status = readString(record, "status");
        if (status !== "present" && status !== "missing" && status !== "error") throw new SchemaValidationError(["/settings/credential_statuses[]/status invalid"]);
        return {
          provider: readString(record, "provider"),
          status,
          updatedAt: readNullableString(record, "updated_at"),
        };
      }),
      retentionOptions: readArray(settings, "retention_options").map((item) => {
        if (typeof item !== "string") throw new SchemaValidationError(["/settings/retention_options[] must be string"]);
        return item;
      }),
      selectedRetention: readString(settings, "selected_retention"),
    },
    memory: {
      projectMemories: readArray(memory, "project_memories").map((item) => {
        const record = requireRecord(item, "/memory/project_memories[]");
        return {
          id: readString(record, "id"),
          title: readString(record, "title"),
          detail: readString(record, "detail"),
          pinned: readBoolean(record, "pinned"),
        };
      }),
      crossProjectSuggestions: readArray(memory, "cross_project_suggestions").map((item) => {
        const record = requireRecord(item, "/memory/cross_project_suggestions[]");
        return {
          id: readString(record, "id"),
          title: readString(record, "title"),
          detail: readString(record, "detail"),
        };
      }),
    },
    audit: {
      entries: readArray(audit, "entries").map((item) => {
        const record = requireRecord(item, "/audit/entries[]");
        return {
          id: readString(record, "id"),
          title: readString(record, "title"),
          detail: readString(record, "detail"),
          at: readString(record, "at"),
        };
      }),
    },
  };
}
