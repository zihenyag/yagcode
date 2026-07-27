import type { EventEnvelope, ReviewView } from "@yagcode/contracts";
import type { LocaleMode, OnboardingStep, ThemeMode, ValidationStatus } from "./client.js";
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
  onboarding: OnboardingModel;
  navigation: NavigationModel;
  task: TaskModel;
  evidence: EvidenceModel;
  settings: SettingsModel;
  memory: MemoryModel;
  audit: AuditModel;
  demo: DemoModel;
}

export interface OnboardingModel {
  step: OnboardingStep;
  completedSteps: readonly OnboardingStep[];
  headline: string;
  detail: string;
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
  messages: readonly { id: string; role: "user" | "assistant" | "system"; title: string; body: string; at: string }[];
  error?: { reason: string; sideEffectState: string; scope: string; recovery: string };
}

export interface EvidenceModel {
  review: ReviewPanelModel;
  diff: { filesChanged: number; additions: number; deletions: number };
  diffFiles: readonly {
    path: string;
    status: "modified" | "added" | "deleted";
    additions: number;
    deletions: number;
    lines: readonly {
      kind: "context" | "add" | "delete" | "hunk";
      oldLine: number | null;
      newLine: number | null;
      content: string;
    }[];
  }[];
  validations: readonly { id: string; title: string; detail: string; status: ValidationStatus; command?: string }[];
  risks: readonly string[];
  uncovered: readonly string[];
  approvalActions: readonly { id: string; label: string; enabled: boolean; highRisk: boolean }[];
}

export interface SettingsModel {
  credentialStatuses: readonly {
    provider: string;
    status: "verified" | "missing" | "error";
    updatedAt: string | null;
    detail: string;
    docsUrl: string;
  }[];
  retentionOptions: readonly string[];
  selectedRetention: string;
  themeMode: ThemeMode;
  locale: LocaleMode;
  themeOptions: readonly { id: ThemeMode; label: string }[];
  localeOptions: readonly { id: LocaleMode; label: string }[];
}

export interface MemoryModel {
  projectMemories: readonly { id: string; title: string; detail: string; pinned: boolean }[];
  crossProjectSuggestions: readonly { id: string; title: string; detail: string }[];
}

export interface AuditModel {
  entries: readonly { id: string; title: string; detail: string; at: string }[];
}

export interface DemoModel {
  selectedPanel: string;
  themeMode: ThemeMode;
  locale: LocaleMode;
  agentName: string | null;
  projectPath: string | null;
  project: {
    path: string;
    label: string;
    isGitRepo: boolean;
    gitRoot: string | null;
    branch: string | null;
    statusSummary: readonly string[];
    error: string | null;
  } | null;
  providers: readonly {
    provider: string;
    label: string;
    configured: boolean;
    status: "verified" | "missing" | "error";
    updatedAt: string | null;
    detail: string;
    docsUrl: string;
  }[];
  privacy: {
    previewConfirmed: boolean;
    retention: string;
    previewItems: readonly { id: string; category: string; source: string; preview: string; confirmed: boolean }[];
  };
  permissions: {
    mode: string;
    options: readonly { id: string; label: string; detail: string; active: boolean }[];
  };
  checkpoints: readonly { id: string; label: string; detail: string; current: boolean }[];
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

function readNullableNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  if (value === null) return null;
  if (typeof value !== "number") throw new SchemaValidationError([`/${key} must be number or null`]);
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

function readOnboardingStep(record: Record<string, unknown>, key: string): OnboardingStep {
  const value = readString(record, key);
  if (value === "CREATE_AGENT" || value === "OPEN_FOLDER" || value === "BIND_API" || value === "CREATE_THREAD" || value === "WORKBENCH") return value;
  throw new SchemaValidationError([`/${key} invalid onboarding step`]);
}

function readDiffLineKind(record: Record<string, unknown>, key: string): "context" | "add" | "delete" | "hunk" {
  const value = readString(record, key);
  if (value === "context" || value === "add" || value === "delete" || value === "hunk") return value;
  throw new SchemaValidationError([`/${key} invalid diff line kind`]);
}

function readDiffStatus(record: Record<string, unknown>, key: string): "modified" | "added" | "deleted" {
  const value = readString(record, key);
  if (value === "modified" || value === "added" || value === "deleted") return value;
  throw new SchemaValidationError([`/${key} invalid diff file status`]);
}

function readProviderStatus(record: Record<string, unknown>, key: string): "verified" | "missing" | "error" {
  const value = readString(record, key);
  if (value === "verified" || value === "missing" || value === "error") return value;
  throw new SchemaValidationError([`/${key} invalid provider status`]);
}

function readThemeMode(record: Record<string, unknown>, key: string): ThemeMode {
  const value = readString(record, key);
  if (value === "system" || value === "light" || value === "dark") return value;
  throw new SchemaValidationError([`/${key} invalid theme mode`]);
}

function readLocale(record: Record<string, unknown>, key: string): LocaleMode {
  const value = readString(record, key);
  if (value === "zh-Hans" || value === "zh-Hant" || value === "en-US" || value === "en-GB") return value;
  throw new SchemaValidationError([`/${key} invalid locale`]);
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

function readMessageRole(record: Record<string, unknown>, key: string): "user" | "assistant" | "system" {
  const value = readString(record, key);
  if (value === "user" || value === "assistant" || value === "system") return value;
  throw new SchemaValidationError([`/${key} invalid message role`]);
}

function readMessages(task: Record<string, unknown>): TaskModel["messages"] {
  const value = task.messages;
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new SchemaValidationError(["/task/messages must be array"]);
  return value.map((item) => {
    const record = requireRecord(item, "/task/messages[]");
    return {
      id: readString(record, "id"),
      role: readMessageRole(record, "role"),
      title: readString(record, "title"),
      body: readString(record, "body"),
      at: readString(record, "at"),
    };
  });
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
  const onboarding = requireRecord(root.onboarding, "/onboarding");
  const navigation = requireRecord(root.navigation, "/navigation");
  const task = requireRecord(root.task, "/task");
  const budget = requireRecord(task.budget, "/task/budget");
  const retryPolicy = requireRecord(task.retry_policy, "/task/retry_policy");
  const evidence = requireRecord(root.evidence, "/evidence");
  const diff = requireRecord(evidence.diff, "/evidence/diff");
  const settings = requireRecord(root.settings, "/settings");
  const memory = requireRecord(root.memory, "/memory");
  const audit = requireRecord(root.audit, "/audit");
  const demo = requireRecord(root.demo, "/demo");
  const privacy = requireRecord(demo.privacy, "/demo/privacy");
  const permissions = requireRecord(demo.permissions, "/demo/permissions");
  const error = task.error === undefined || task.error === null ? undefined : requireRecord(task.error, "/task/error");
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
          messages: readMessages(task),
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
          messages: readMessages(task),
          error: taskError,
        };

  return {
    profileId: readString(root, "profile_id"),
    generation: readNumber(root, "generation"),
    lastSequence: readNumber(root, "last_sequence"),
    connection: readConnection(root),
    onboarding: {
      step: readOnboardingStep(onboarding, "step"),
      completedSteps: readArray(onboarding, "completed_steps").map((item) => {
        if (typeof item !== "string") throw new SchemaValidationError(["/onboarding/completed_steps[] must be string"]);
        return readOnboardingStep({ step: item }, "step");
      }),
      headline: readString(onboarding, "headline"),
      detail: readString(onboarding, "detail"),
    },
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
      diffFiles: readArray(evidence, "diff_files").map((item) => {
        const file = requireRecord(item, "/evidence/diff_files[]");
        return {
          path: readString(file, "path"),
          status: readDiffStatus(file, "status"),
          additions: readNumber(file, "additions"),
          deletions: readNumber(file, "deletions"),
          lines: readArray(file, "lines").map((lineItem) => {
            const line = requireRecord(lineItem, "/evidence/diff_files[]/lines[]");
            return {
              kind: readDiffLineKind(line, "kind"),
              oldLine: readNullableNumber(line, "old_line"),
              newLine: readNullableNumber(line, "new_line"),
              content: readString(line, "content"),
            };
          }),
        };
      }),
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
        return {
          provider: readString(record, "provider"),
          status: readProviderStatus(record, "status"),
          updatedAt: readNullableString(record, "updated_at"),
          detail: readString(record, "detail"),
          docsUrl: readString(record, "docs_url"),
        };
      }),
      retentionOptions: readArray(settings, "retention_options").map((item) => {
        if (typeof item !== "string") throw new SchemaValidationError(["/settings/retention_options[] must be string"]);
        return item;
      }),
      selectedRetention: readString(settings, "selected_retention"),
      themeMode: readThemeMode(settings, "theme_mode"),
      locale: readLocale(settings, "locale"),
      themeOptions: readArray(settings, "theme_options").map((item) => {
        const record = requireRecord(item, "/settings/theme_options[]");
        return { id: readThemeMode(record, "id"), label: readString(record, "label") };
      }),
      localeOptions: readArray(settings, "locale_options").map((item) => {
        const record = requireRecord(item, "/settings/locale_options[]");
        return { id: readLocale(record, "id"), label: readString(record, "label") };
      }),
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
    demo: {
      selectedPanel: readString(demo, "selected_panel"),
      themeMode: readThemeMode(demo, "theme_mode"),
      locale: readLocale(demo, "locale"),
      agentName: readNullableString(demo, "agent_name"),
      projectPath: readNullableString(demo, "project_path"),
      project:
        demo.project === null
          ? null
          : (() => {
              const project = requireRecord(demo.project, "/demo/project");
              return {
                path: readString(project, "path"),
                label: readString(project, "label"),
                isGitRepo: readBoolean(project, "is_git_repo"),
                gitRoot: readNullableString(project, "git_root"),
                branch: readNullableString(project, "branch"),
                statusSummary: readArray(project, "status_summary").map((item) => {
                  if (typeof item !== "string") throw new SchemaValidationError(["/demo/project/status_summary[] must be string"]);
                  return item;
                }),
                error: readNullableString(project, "error"),
              };
            })(),
      providers: readArray(demo, "providers").map((item) => {
        const record = requireRecord(item, "/demo/providers[]");
        return {
          provider: readString(record, "provider"),
          label: readString(record, "label"),
          configured: readBoolean(record, "configured"),
          status: readProviderStatus(record, "status"),
          updatedAt: readNullableString(record, "updated_at"),
          detail: readString(record, "detail"),
          docsUrl: readString(record, "docs_url"),
        };
      }),
      privacy: {
        previewConfirmed: readBoolean(privacy, "preview_confirmed"),
        retention: readString(privacy, "retention"),
        previewItems: readArray(privacy, "preview_items").map((item) => {
          const record = requireRecord(item, "/demo/privacy/preview_items[]");
          return {
            id: readString(record, "id"),
            category: readString(record, "category"),
            source: readString(record, "source"),
            preview: readString(record, "preview"),
            confirmed: readBoolean(record, "confirmed"),
          };
        }),
      },
      permissions: {
        mode: readString(permissions, "mode"),
        options: readArray(permissions, "options").map((item) => {
          const record = requireRecord(item, "/demo/permissions/options[]");
          return {
            id: readString(record, "id"),
            label: readString(record, "label"),
            detail: readString(record, "detail"),
            active: readBoolean(record, "active"),
          };
        }),
      },
      checkpoints: readArray(demo, "checkpoints").map((item) => {
        const record = requireRecord(item, "/demo/checkpoints[]");
        return {
          id: readString(record, "id"),
          label: readString(record, "label"),
          detail: readString(record, "detail"),
          current: readBoolean(record, "current"),
        };
      }),
    },
  };
}
