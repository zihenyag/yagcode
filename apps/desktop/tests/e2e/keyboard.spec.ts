import { completeFirstRunOnboarding, test, expect } from "./fixtures.js";
import type { Locator, Page } from "@playwright/test";

async function focusByTab(window: Page, locator: Locator): Promise<void> {
  for (let index = 0; index < 24; index += 1) {
    if (await locator.evaluate((element) => document.activeElement === element).catch(() => false)) return;
    await window.keyboard.press("Tab");
  }
  throw new Error("FOCUS_TARGET_NOT_REACHED");
}

async function pressAndAllowNavigationInterception(window: Page, key: string): Promise<void> {
  await window.keyboard.press(key).catch((error: unknown) => {
    if (!(error instanceof Error) || !error.message.includes("Target page, context or browser has been closed")) {
      throw error;
    }
  });
}

test("keyboard users can reach plan mode, model selection, and run controls", async ({ fixtureSidecar, window }) => {
  await completeFirstRunOnboarding(window, fixtureSidecar);
  const planMode = window.getByRole("checkbox", { name: "Plan 模式" });
  await expect(planMode).toBeVisible();
  await focusByTab(window, planMode);
  await expect(planMode).toBeFocused();
  await expect(window.getByRole("combobox", { name: "模型" })).toBeEnabled();
  await window.getByRole("textbox", { name: "追加信息" }).fill("键盘可达性检查");
  await focusByTab(window, window.getByRole("button", { name: "发送并运行" }));
  await expect(window.getByRole("button", { name: "发送并运行" })).toBeFocused();
});

test("trusted intent confirmation works with keyboard only", async ({ electronApp, fixtureSidecar, window }) => {
  const intentWindowPromise = electronApp.waitForEvent("window");
  await window.evaluate(() => {
    const api = (window as unknown as { yagcode: { requestIntentWindow(intentId: string): Promise<unknown> } }).yagcode;
    (window as unknown as { __keyboardIntentPromise?: Promise<unknown> }).__keyboardIntentPromise = api.requestIntentWindow("review-2");
  });
  const intentWindow = await intentWindowPromise;
  await intentWindow.waitForLoadState("domcontentloaded");
  await expect
    .poll(() => intentWindow.evaluate(() => typeof (window as unknown as { yagcodeIntent?: { confirm?: unknown } }).yagcodeIntent?.confirm))
    .toBe("function");
  const confirm = intentWindow.getByRole("button", { name: "确认执行" });
  await focusByTab(intentWindow, confirm);
  await expect(confirm).toBeFocused();
  await pressAndAllowNavigationInterception(intentWindow, "Enter");
  await expect
    .poll(() => fixtureSidecar.consumedIntents().join(","))
    .toBe("intent-1");
  const result = await window.evaluate(() => (window as unknown as { __keyboardIntentPromise: Promise<unknown> }).__keyboardIntentPromise);
  expect(result).toEqual({ intent_id: "intent-1", intent_type: "ACCEPT_REVIEW", state: "EXECUTED" });
});
