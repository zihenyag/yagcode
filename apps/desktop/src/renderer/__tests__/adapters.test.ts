import { describe, expect, it } from "vitest";
import { eventFixture, reviewFixture } from "@yagcode/contracts/fixtures";

interface LoadedAdaptersModule {
  adaptReviewView(view: unknown): {
    reviewId: string;
    generation: number;
    state: string;
    summary: string;
  };
  adaptRunStateEvent(event: unknown): {
    runId: string;
    runState: string;
    sequence: number;
    generation: number;
  };
  adaptSnapshot(snapshot: unknown): {
    profileId: string;
    generation: number;
    lastSequence: number;
    task: {
      model: string;
      planMode: boolean;
      error?: { reason: string; sideEffectState: string; scope: string; recovery: string };
    };
    onboarding: {
      step: string;
    };
    evidence: {
      diff: {
        filesChanged: number;
        additions: number;
        deletions: number;
      };
      diffFiles: readonly {
        path: string;
        lines: readonly {
          kind: string;
          oldLine: number | null;
          newLine: number | null;
          content: string;
        }[];
      }[];
      validations: readonly {
        command?: string;
        detail: string;
        id: string;
        status: string;
        title: string;
      }[];
    };
    settings: {
      themeMode: string;
      locale: string;
      credentialStatuses: readonly {
        provider: string;
        status: string;
        updatedAt: string | null;
        detail: string;
        docsUrl: string;
      }[];
    };
    demo: {
      themeMode: string;
      locale: string;
      project: { isGitRepo: boolean; branch: string | null; statusSummary: readonly string[] } | null;
      providers: readonly { provider: string; configured: boolean; status: string; updatedAt: string | null }[];
    };
  };
}

async function loadAdaptersProduction(): Promise<LoadedAdaptersModule> {
  const modulePath = "../api/adapters";
  try {
    return (await import(modulePath)) as LoadedAdaptersModule;
  } catch (error) {
    throw new Error(`RENDERER_PRODUCTION_MISSING:${modulePath}`, { cause: error });
  }
}

function testOwnedMapSnakeToCamel(input: { review_id: string; risk_count: number }) {
  return {
    reviewId: input.review_id,
    riskCount: input.risk_count,
  };
}

function fixtureSnapshot() {
  return {
    profile_id: "profile-1",
    generation: 2,
    last_sequence: 7,
    connection: "connected",
    onboarding: {
      step: "WORKBENCH",
      completed_steps: ["CREATE_AGENT", "OPEN_FOLDER", "BIND_API", "CREATE_THREAD"],
      headline: "进入本地 Agent 工作台",
      detail: "可以调试对话、Plan、模型、权限、记忆、隐私、审查、Diff 和回滚。",
    },
    navigation: {
      profiles: [{ id: "profile-1", label: "默认档案" }],
      projects: [{ id: "project-1", label: "yagcode", active: true }],
      threads: [{ id: "thread-1", label: "修复权限 bug", unread_approvals: 1, memory_suggestions: 2 }],
      run_state: "RUNNING",
    },
    task: {
      thread_id: "thread-1",
      title: "修复权限 bug",
      run_state: "INTERRUPTED",
      provider: "openai",
      model: "gpt-5.6-sol",
      models: [
        { id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" },
        { id: "deepseek-chat", label: "DeepSeek Chat", provider: "deepseek" },
        { id: "glm-5.2", label: "NJU SE Hub / GLM 5.2", provider: "njusehub" },
      ],
      plan_mode: true,
      budget: { token_limit: 1500, time_limit_minutes: 60 },
      retry_policy: { connection_retries: 5, tool_retries: 3, model_retries: 5 },
      compact_after_lines: 1500,
      append_enabled: true,
      error: undefined as undefined | null | { reason: string; side_effect_state: string; scope: string; recovery: string },
    },
    review_view: reviewFixture,
    evidence: {
      diff: { files_changed: 1, additions: 3, deletions: 1 },
      diff_files: [
        {
          path: "src/example.py",
          status: "modified",
          additions: 3,
          deletions: 1,
          lines: [
            { kind: "hunk", old_line: null, new_line: null, content: "@@ -1,2 +1,3 @@" },
            { kind: "context", old_line: 1, new_line: 1, content: "def answer():" },
            { kind: "delete", old_line: 2, new_line: null, content: "    return 1" },
            { kind: "add", old_line: null, new_line: 2, content: "    return 2" },
            { kind: "add", old_line: null, new_line: 3, content: "" },
            { kind: "add", old_line: null, new_line: 4, content: "print(answer())" },
          ],
        },
      ],
      validations: [
        { id: "test", title: "单元测试", detail: "pytest 通过", status: "passed", command: "pytest" },
      ],
      risks: ["Windows 端仍需 full suite"],
      uncovered: ["未覆盖真实 Provider"],
      approval_actions: [
        { id: "accept", label: "接受更改", enabled: true, high_risk: false },
        { id: "accept_commit", label: "接受并提交", enabled: true, high_risk: true },
      ],
    },
    settings: {
      credential_statuses: [
        {
          provider: "openai",
          status: "verified",
          updated_at: "2026-07-24T00:00:00Z" as string | null,
          detail: "GET /models verified",
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
      project_memories: [{ id: "memory-1", title: "项目内偏好", detail: "中文沟通", pinned: true }],
      cross_project_suggestions: [{ id: "suggestion-1", title: "跨项目候选", detail: "需确认进入 memory" }],
    },
    audit: {
      entries: [{ id: "audit-1", title: "权限审批", detail: "yes once", at: "2026-07-24T00:00:00Z" }],
    },
    demo: {
      selected_panel: "审查",
      theme_mode: "system",
      locale: "zh-Hans",
      agent_name: "默认档案",
      project_path: "/Users/demo/yagcode",
      project: {
        path: "/Users/demo/yagcode",
        label: "yagcode",
        is_git_repo: true,
        git_root: "/Users/demo/yagcode",
        branch: "main",
        status_summary: ["## main", " M src/example.py"],
        error: null,
      },
      providers: [
        {
          provider: "openai",
          label: "OpenAI",
          configured: true,
          status: "verified",
          updated_at: "2026-07-24T00:00:00Z" as string | null,
          detail: "GET /models verified",
          docs_url: "https://platform.openai.com/docs/api-reference/responses",
        },
        {
          provider: "qwen",
          label: "Qwen",
          configured: false,
          status: "missing",
          updated_at: null,
          detail: "尚未绑定",
          docs_url: "https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope",
        },
      ],
      privacy: {
        preview_confirmed: false,
        retention: "permanent",
        preview_items: [
          { id: "conversation", category: "原始对话", source: "当前线程", preview: "任务标题和工具摘要", confirmed: false },
        ],
      },
      permissions: {
        mode: "yes_once",
        options: [
          { id: "yes_once", label: "Yes once", detail: "仅本次。", active: true },
          { id: "full_access", label: "Full access for this app session", detail: "本会话完全访问。", active: false },
        ],
      },
      checkpoints: [
        { id: "checkpoint-1", label: "初始基线", detail: "安全回档点", current: false },
        { id: "checkpoint-2", label: "候选修改", detail: "当前 diff", current: true },
      ],
    },
  };
}

describe("adapter test-owned oracle", () => {
  it("test_owned_adapter_oracle_uses_explicit_snake_to_camel_mapping", () => {
    expect(testOwnedMapSnakeToCamel({ review_id: "review-1", risk_count: 2 })).toEqual({
      reviewId: "review-1",
      riskCount: 2,
    });
  });
});

describe("renderer adapters", () => {
  it("maps generated review and event contracts into camelCase UI props", async () => {
    const { adaptReviewView, adaptRunStateEvent } = await loadAdaptersProduction();
    expect(adaptReviewView(reviewFixture)).toEqual({
      reviewId: "review-1",
      generation: 1,
      state: "READY",
      summary: "2 files changed",
    });
    expect(adaptRunStateEvent(eventFixture)).toEqual({
      runId: "run-1",
      runState: "RUNNING",
      sequence: 1,
      generation: 1,
    });
  });

  it("rejects schema-invalid API views instead of guessing fields", async () => {
    const { adaptReviewView } = await loadAdaptersProduction();
    expect(() => adaptReviewView({ ...reviewFixture, review_id: 42 })).toThrow("SCHEMA_VALIDATION_FAILED");
  });

  it("keeps snake_case API fields behind the adapter boundary", async () => {
    const { adaptSnapshot } = await loadAdaptersProduction();
    const model = adaptSnapshot(fixtureSnapshot());
    expect(model.profileId).toBe("profile-1");
    expect(model.lastSequence).toBe(7);
    expect(model.onboarding.step).toBe("WORKBENCH");
    expect(model.task).toMatchObject({ model: "gpt-5.6-sol", planMode: true });
    expect(model.settings).toMatchObject({ themeMode: "system", locale: "zh-Hans" });
    expect(model.demo).toMatchObject({ themeMode: "system", locale: "zh-Hans" });
    expect(model.evidence.diff).toEqual({ filesChanged: 1, additions: 3, deletions: 1 });
    expect(model.evidence.diffFiles[0]?.lines[2]).toMatchObject({ kind: "delete", oldLine: 2, newLine: null });
    expect(model.demo.project).toMatchObject({ isGitRepo: true, branch: "main", statusSummary: ["## main", " M src/example.py"] });
    expect(model.demo.providers[0]).toMatchObject({ provider: "openai", configured: true, status: "verified", updatedAt: "2026-07-24T00:00:00Z" });
    expect(model).not.toHaveProperty("profile_id");
    expect(model.task).not.toHaveProperty("plan_mode");
    expect(model.evidence.diff).not.toHaveProperty("files_changed");
  });

  it("accepts the real sidecar preview shape used by dev:desktop", async () => {
    const { adaptSnapshot } = await loadAdaptersProduction();
    const snapshot = fixtureSnapshot();
    snapshot.evidence.validations = [
      {
        id: "sidecar",
        title: "真实 sidecar",
        detail: "/api/v1/workbench 已由 FastAPI 进程提供",
        status: "passed",
        command: "GET /api/v1/workbench",
      },
    ];
    snapshot.settings.credential_statuses = [
      {
        provider: "openai",
        status: "missing",
        updated_at: null,
        detail: "尚未绑定",
        docs_url: "https://platform.openai.com/docs/api-reference/responses",
      },
    ];
    snapshot.task.error = null;

    const model = adaptSnapshot(snapshot);

    expect(model.evidence.validations[0]?.command).toBe("GET /api/v1/workbench");
    expect(model.task.error).toBeUndefined();
    expect(model.settings.credentialStatuses[0]).toEqual({
      provider: "openai",
      status: "missing",
      updatedAt: null,
      detail: "尚未绑定",
      docsUrl: "https://platform.openai.com/docs/api-reference/responses",
    });
  });
});
