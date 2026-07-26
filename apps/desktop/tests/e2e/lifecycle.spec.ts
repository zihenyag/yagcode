import { test, expect } from "./fixtures.js";

test("exposes only the governed preload surface and startup connection", async ({ window, fixtureSidecar }) => {
  await expect(window.getByRole("heading", { name: "桌面生命周期" })).toBeVisible();
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

test("active or interrupted runs block close and focus the run list", async ({ electronApp, fixtureSidecar, window }) => {
  fixtureSidecar.setBlockingRuns([{ id: "r1", state: "INTERRUPTED", title: "正在等待用户处理" }]);
  await electronApp.evaluate(({ BrowserWindow }) => {
    BrowserWindow.getAllWindows()[0]?.close();
  });
  expect(await electronApp.windows()).toHaveLength(1);
  await expect(window.getByRole("heading", { name: "运行中的任务" })).toBeVisible();
  await expect(window.getByText("r1 · INTERRUPTED")).toBeVisible();
});

test("sidecar event failures show a recoverable disconnected state", async ({ window }) => {
  const runError = window.getByRole("alert", { name: "运行错误" });
  await expect(runError).toContainText("SSE_CONNECT_FAILED");
  await expect(runError).toContainText("新 action 已阻止");
});
