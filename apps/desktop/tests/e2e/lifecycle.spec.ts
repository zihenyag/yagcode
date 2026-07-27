import { completeFirstRunOnboarding, test, expect } from "./fixtures.js";

test("exposes only the governed preload surface and startup connection", async ({ window, fixtureSidecar }) => {
  await expect(window.locator("#onboarding-heading")).toHaveText("创建 AGENT 档案");
  const exposed = await window.evaluate(async () => {
    const api = (window as unknown as { yagcode?: { getStartupConnection?: () => Promise<unknown> } }).yagcode;
    return {
      requireType: typeof (window as unknown as { require?: unknown }).require,
      processType: typeof (window as unknown as { process?: unknown }).process,
      keys: Object.keys(api ?? {}),
      startup: api?.getStartupConnection ? await api.getStartupConnection() : null
    };
  });
  expect(exposed.requireType).toBe("undefined");
  expect(exposed.processType).toBe("undefined");
  expect(exposed.keys).toEqual(["chooseDirectory", "requestIntentWindow", "notify", "getStartupConnection"]);
  expect(exposed.startup).toEqual({
    baseUrl: fixtureSidecar.baseUrl,
    token: fixtureSidecar.token,
    origin: fixtureSidecar.origin,
    connected: true
  });
});

test("first-run desktop onboarding uses the native directory bridge and command sidecar", async ({ fixtureSidecar, window }) => {
  await completeFirstRunOnboarding(window, fixtureSidecar);
  await expect(window.getByRole("log", { name: "任务对话" })).toBeVisible();
  await expect(window.getByText("线程名称只作为界面元数据，不会发给模型")).toBeVisible();
  await expect(window.getByText("test-credential-value")).toHaveCount(0);
  expect(fixtureSidecar.commandTypes()).toEqual(["create_agent", "open_folder", "bind_api", "create_thread"]);
});

test("workbench sends task input, runs an agent step, previews diff, and rolls back", async ({ fixtureSidecar, window }) => {
  await completeFirstRunOnboarding(window, fixtureSidecar);

  await window.getByRole("textbox", { name: "追加信息" }).fill("请修复 src/example.py，让 answer() 返回 2。");
  await window.getByRole("button", { name: "发送并运行" }).click();
  await expect(window.getByText("已收到输入；下一次 Agent step 会把它作为 Provider prompt 的用户上下文。")).toBeVisible();
  await expect(window.getByText("真实 Provider action 已完成：TASK_COMPLETE")).toBeVisible();
  await expect(window.getByText("已生成候选修改，查看右侧 Changes")).toBeVisible();

  await window.getByRole("button", { name: "Changes" }).click();
  await expect(window.getByText("src/example.py", { exact: true })).toBeVisible();
  await expect(window.getByText(/\+\s+return 2/u)).toBeVisible();
  await expect(window.getByText(/-\s+return 1/u)).toBeVisible();

  await window.getByRole("button", { name: "审查", exact: true }).click();
  await window.getByRole("button", { name: "回滚到这里" }).first().click();
  await expect(window.getByText("暂无 Diff")).toBeVisible();
  await expect(window.getByText("RECOVERY_REQUIRED")).toBeVisible();
  expect(fixtureSidecar.commandTypes()).toEqual([
    "create_agent",
    "open_folder",
    "bind_api",
    "create_thread",
    "append_message",
    "resume_run",
    "open_panel",
    "open_panel",
    "rollback_checkpoint",
  ]);
});

test("active or interrupted runs block close and focus the run list", async ({ electronApp, fixtureSidecar, window }) => {
  fixtureSidecar.setBlockingRuns([{ id: "r1", state: "INTERRUPTED", title: "正在等待用户处理" }]);
  await electronApp.evaluate(({ BrowserWindow }) => {
    BrowserWindow.getAllWindows()[0]?.close();
  });
  expect(await electronApp.windows()).toHaveLength(1);
  await expect(window.getByRole("heading", { name: "运行中的任务" })).toBeVisible();
  await expect(window.getByText("r1 · INTERRUPTED")).toBeVisible();
});

test("sidecar event failures show a recoverable disconnected state", async ({ fixtureSidecar, window }) => {
  await completeFirstRunOnboarding(window, fixtureSidecar);
  fixtureSidecar.sendMalformedEvent();
  const runError = window.getByRole("alert", { name: "运行错误" });
  await expect(runError).toContainText("SCHEMA_VALIDATION_FAILED");
  await expect(runError).toContainText("新 action 已阻止");
});
