import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";
import { reviewFixture } from "@yagcode/contracts/fixtures";

interface LoadedWorkbenchModule {
  App: React.ComponentType<{ client: unknown }>;
}

interface LoadedTaskPaneModule {
  ModelSelector: React.ComponentType<{
    runState: string;
    model: string;
    models: readonly { id: string; label: string; provider: string }[];
    onChange?: (model: string) => void;
  }>;
}

async function loadWorkbenchProduction(): Promise<LoadedWorkbenchModule> {
  const modulePath = "../App";
  try {
    return (await import(modulePath)) as LoadedWorkbenchModule;
  } catch (error) {
    throw new Error(`RENDERER_PRODUCTION_MISSING:${modulePath}`, { cause: error });
  }
}

async function loadTaskPaneProduction(): Promise<LoadedTaskPaneModule> {
  const modulePath = "../views/TaskPane";
  try {
    return (await import(modulePath)) as LoadedTaskPaneModule;
  } catch (error) {
    throw new Error(`RENDERER_PRODUCTION_MISSING:${modulePath}`, { cause: error });
  }
}

afterEach(() => cleanup());

function fixtureSnapshot(reviewState = "READY") {
  return {
    profile_id: "profile-1",
    generation: 2,
    last_sequence: 7,
    connection: "connected",
    navigation: {
      profiles: [{ id: "profile-1", label: "默认档案" }],
      projects: [{ id: "project-1", label: "yagcode", active: true }],
      threads: [{ id: "thread-1", label: "修复权限 bug", unread_approvals: 1, memory_suggestions: 2 }],
      run_state: "INTERRUPTED",
    },
    task: {
      thread_id: "thread-1",
      title: "修复权限 bug",
      run_state: "INTERRUPTED",
      provider: "openai",
      model: "gpt-5.6-sol",
      models: [
        { id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" },
        { id: "gpt-5.6-terra", label: "OpenAI gpt-5.6-terra", provider: "openai" },
        { id: "qwen-plus", label: "Qwen Plus", provider: "qwen" },
        { id: "glm-4.5", label: "GLM 4.5", provider: "glm" },
        { id: "deepseek-chat", label: "DeepSeek Chat", provider: "deepseek" },
      ],
      plan_mode: true,
      budget: { token_limit: 1500, time_limit_minutes: 60 },
      retry_policy: { connection_retries: 5, tool_retries: 3, model_retries: 5 },
      compact_after_lines: 1500,
      append_enabled: true,
      error: {
        reason: "sidecar 心跳超时",
        side_effect_state: "未写入工作区",
        scope: "当前线程",
        recovery: "重新连接后从最后 sequence 同步",
      },
    },
    review_view: { ...reviewFixture, state: reviewState },
    evidence: {
      diff: { files_changed: 2, additions: 24, deletions: 5 },
      validations: [
        { id: "test", title: "单元测试", detail: "pytest 通过", status: "passed", command: "pytest" },
        { id: "windows", title: "Windows full suite", detail: "等待复验", status: "warning", command: "npm run test:all" },
      ],
      risks: ["真实 Provider 未接入此测试"],
      uncovered: ["未覆盖发布流程"],
      approval_actions: [
        { id: "continue", label: "继续修改", enabled: true, high_risk: false },
        { id: "accept", label: "接受更改", enabled: true, high_risk: false },
        { id: "accept_commit", label: "接受并提交", enabled: true, high_risk: true },
        { id: "reject", label: "拒绝", enabled: true, high_risk: false },
      ],
    },
    settings: {
      credential_statuses: [
        { provider: "openai", status: "present", updated_at: "2026-07-24T00:00:00Z" },
        { provider: "qwen", status: "missing", updated_at: null },
      ],
      retention_options: ["permanent", "30d", "60d", "90d", "180d", "1y", "2y"],
      selected_retention: "permanent",
    },
    memory: {
      project_memories: [{ id: "memory-1", title: "项目内偏好", detail: "默认中文沟通", pinned: true }],
      cross_project_suggestions: [{ id: "suggestion-1", title: "跨项目候选", detail: "需要用户确认进入 memory" }],
    },
    audit: {
      entries: [{ id: "audit-1", title: "权限审批", detail: "yes once", at: "2026-07-24T00:00:00Z" }],
    },
  };
}

function fixtureClient(snapshot = fixtureSnapshot()) {
  return {
    command: vi.fn(async () => ({ ok: true })),
    async getSnapshot() {
      return snapshot;
    },
    subscribe() {
      return { close() {} };
    },
  };
}

describe("workbench test-owned DOM harness", () => {
  it("test_owned_dom_cleanup_removes_previous_rendered_nodes", () => {
    render(<button type="button">临时按钮</button>);
    expect(screen.getByRole("button", { name: "临时按钮" })).toBeVisible();
    cleanup();
    expect(screen.queryByRole("button", { name: "临时按钮" })).toBeNull();
  });
});

describe("desktop workbench", () => {
  it("shows structured review evidence rather than raw chat only", async () => {
    const { App } = await loadWorkbenchProduction();
    render(<App client={fixtureClient(fixtureSnapshot("READY"))} />);
    expect(await screen.findByRole("heading", { name: "变更审阅" })).toBeVisible();
    expect(screen.getByText("验证证据")).toBeVisible();
    expect(screen.getByText("风险与未覆盖项")).toBeVisible();
    expect(screen.getByRole("button", { name: "接受更改" })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "记忆" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "审计" })).toBeVisible();
  });

  it("disables model changes for every active execution state", async () => {
    const { ModelSelector } = await loadTaskPaneProduction();
    for (const state of ["RUNNING", "COMPACTING", "WAITING_PERMISSION", "WAITING_PRIVACY", "STOPPING", "INTERRUPTED"]) {
      render(
        <ModelSelector
          runState={state}
          model="gpt-5.6-sol"
          models={[{ id: "gpt-5.6-sol", label: "OpenAI gpt-5.6-sol", provider: "openai" }]}
        />,
      );
      expect(screen.getByRole("combobox", { name: "模型" })).toBeDisabled();
      cleanup();
    }
  });

  it("keeps Plan mode on by default but lets the user turn it off", async () => {
    const { App } = await loadWorkbenchProduction();
    render(<App client={fixtureClient(fixtureSnapshot("READY"))} />);
    const planToggle = await screen.findByRole("checkbox", { name: "Plan 模式" });
    expect(planToggle).toBeChecked();
    fireEvent.click(planToggle);
    expect(planToggle).not.toBeChecked();
  });

  it("has no serious or critical automated accessibility violations", async () => {
    const { App } = await loadWorkbenchProduction();
    const { container } = render(<App client={fixtureClient(fixtureSnapshot("READY"))} />);
    await screen.findByRole("heading", { name: "变更审阅" });
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    const blocking = results.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
    expect(blocking).toEqual([]);
  });
});
