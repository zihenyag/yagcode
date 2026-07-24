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
    };
    evidence: {
      diff: {
        filesChanged: number;
        additions: number;
        deletions: number;
      };
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
      ],
      plan_mode: true,
      budget: { token_limit: 1500, time_limit_minutes: 60 },
      retry_policy: { connection_retries: 5, tool_retries: 3, model_retries: 5 },
      compact_after_lines: 1500,
      append_enabled: true,
    },
    review_view: reviewFixture,
    evidence: {
      diff: { files_changed: 2, additions: 24, deletions: 5 },
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
      credential_statuses: [{ provider: "openai", status: "present", updated_at: "2026-07-24T00:00:00Z" }],
      retention_options: ["permanent", "30d", "60d", "90d", "180d", "1y", "2y"],
      selected_retention: "permanent",
    },
    memory: {
      project_memories: [{ id: "memory-1", title: "项目内偏好", detail: "中文沟通", pinned: true }],
      cross_project_suggestions: [{ id: "suggestion-1", title: "跨项目候选", detail: "需确认进入 memory" }],
    },
    audit: {
      entries: [{ id: "audit-1", title: "权限审批", detail: "yes once", at: "2026-07-24T00:00:00Z" }],
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
    expect(model.task).toMatchObject({ model: "gpt-5.6-sol", planMode: true });
    expect(model.evidence.diff).toEqual({ filesChanged: 2, additions: 24, deletions: 5 });
    expect(model).not.toHaveProperty("profile_id");
    expect(model.task).not.toHaveProperty("plan_mode");
    expect(model.evidence.diff).not.toHaveProperty("files_changed");
  });
});
