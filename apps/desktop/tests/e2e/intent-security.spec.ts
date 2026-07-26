import { test, expect } from "./fixtures.js";

test("ordinary renderer cannot access trusted intent internals", async ({ window }) => {
  const surfaces = await window.evaluate(() => ({
    hasIpcRenderer: "ipcRenderer" in window,
    hasYagcodeIntent: "yagcodeIntent" in window,
    hasShell: "shell" in window
  }));
  expect(surfaces).toEqual({ hasIpcRenderer: false, hasYagcodeIntent: false, hasShell: false });
});

test("main window refuses arbitrary loopback navigation", async ({ window }) => {
  const before = window.url();
  await window.evaluate(() => {
    window.location.href = "http://127.0.0.1:9/untrusted-local-page";
  });
  await expect.poll(() => window.url()).toBe(before);
});

test("app protocol rejects renderer path traversal", async ({ window }) => {
  const result = await window.evaluate(async () => {
    try {
      const response = await fetch("app://yagcode/%2e%2e/package.json");
      return { status: response.status, text: await response.text() };
    } catch (error) {
      return { status: "blocked", text: error instanceof Error ? error.message : String(error) };
    }
  });
  expect(result.status).not.toBe(200);
  expect(result.text).not.toContain("\"@yagcode/desktop\"");
});

test("trusted intent window consumes the sidecar challenge exactly once", async ({ electronApp, fixtureSidecar, window }) => {
  const intentWindowPromise = electronApp.waitForEvent("window");
  await window.evaluate(() => {
    const api = (window as unknown as { yagcode: { requestIntentWindow(intentId: string): Promise<unknown> } }).yagcode;
    (window as unknown as { __intentPromise?: Promise<unknown> }).__intentPromise = api.requestIntentWindow("review-1");
  });
  const intentWindow = await intentWindowPromise;
  await intentWindow.waitForLoadState("domcontentloaded");
  await expect
    .poll(() => intentWindow.evaluate(() => typeof (window as unknown as { yagcodeIntent?: { confirm?: unknown } }).yagcodeIntent?.confirm))
    .toBe("function");
  await intentWindow.getByRole("button", { name: "确认执行" }).click({ noWaitAfter: true });
  const result = await window.evaluate(() => (window as unknown as { __intentPromise: Promise<unknown> }).__intentPromise);
  expect(result).toEqual({ intent_id: "intent-1", intent_type: "ACCEPT_REVIEW", state: "EXECUTED" });
  expect(fixtureSidecar.consumedIntents()).toEqual(["intent-1"]);
});

test("invalid intent identifiers fail closed before opening a trusted window", async ({ electronApp, window }) => {
  const countBefore = (await electronApp.windows()).length;
  const result = await window.evaluate(async () => {
    const api = (window as unknown as { yagcode: { requestIntentWindow(intentId: string): Promise<unknown> } }).yagcode;
    try {
      await api.requestIntentWindow("../review-1");
      return "unexpected-ok";
    } catch (error) {
      return error instanceof Error ? error.message : String(error);
    }
  });
  expect(result).toContain("INVALID_INTENT_ID");
  expect(await electronApp.windows()).toHaveLength(countBefore);
});
