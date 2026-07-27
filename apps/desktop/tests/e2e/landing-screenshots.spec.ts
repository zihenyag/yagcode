import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { platform } from "node:os";
import { resolve } from "node:path";
import type { ElectronApplication, Page } from "@playwright/test";
import { completeFirstRunOnboarding, expect, test } from "./fixtures.js";

const captureMarker = "/private/tmp/yagcode-capture-landing-screenshots";
const swiftModuleCache = "/private/tmp/yagcode-swift-module-cache";
const screenshotDir = resolve(process.cwd(), "../..", "docs/landing/assets/screenshots");

test.skip(!existsSync(captureMarker), `create ${captureMarker} to update landing screenshots`);

interface NativeMacWindow {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

function nativeMacWindowForPid(pid: number): NativeMacWindow {
  mkdirSync(swiftModuleCache, { recursive: true });
  const source = `
import CoreGraphics
import Darwin
import Foundation

let targetPid = ${pid}
let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []

func readInt(_ value: Any?) -> Int {
  if let number = value as? NSNumber { return number.intValue }
  if let int = value as? Int { return int }
  if let double = value as? Double { return Int(double) }
  return 0
}

func area(_ window: [String: Any]) -> Int {
  guard let bounds = window[kCGWindowBounds as String] as? [String: Any] else { return 0 }
  return readInt(bounds["Width"]) * readInt(bounds["Height"])
}

let matches = windows
  .filter { readInt($0[kCGWindowOwnerPID as String]) == targetPid }
  .filter { readInt($0[kCGWindowLayer as String]) == 0 }
  .filter { area($0) > 100_000 }
  .sorted { area($0) > area($1) }

if let window = matches.first {
  let bounds = window[kCGWindowBounds as String] as? [String: Any] ?? [:]
  print("\\(readInt(window[kCGWindowNumber as String])),\\(readInt(bounds["X"])),\\(readInt(bounds["Y"])),\\(readInt(bounds["Width"])),\\(readInt(bounds["Height"]))")
} else {
  fputs("No visible normal macOS window for pid \\(targetPid)\\n", stderr)
  exit(2)
}
`;
  const [id = "", x = "", y = "", width = "", height = ""] = execFileSync("swift", ["-module-cache-path", swiftModuleCache, "-e", source], {
    encoding: "utf8",
    stdio: "pipe",
  }).trim().split(",");
  const parsed = {
    id,
    x: Number.parseInt(x, 10),
    y: Number.parseInt(y, 10),
    width: Number.parseInt(width, 10),
    height: Number.parseInt(height, 10),
  };
  if (!parsed.id || !Number.isFinite(parsed.x) || !Number.isFinite(parsed.y) || !Number.isFinite(parsed.width) || !Number.isFinite(parsed.height)) {
    throw new Error(`NATIVE_WINDOW_BOUNDS_INVALID: ${JSON.stringify(parsed)}`);
  }
  return parsed;
}

async function saveLandingScreenshot(electronApp: ElectronApplication, window: Page, filename: string): Promise<void> {
  mkdirSync(screenshotDir, { recursive: true });
  const path = resolve(screenshotDir, filename);
  if (platform() !== "darwin") {
    await window.screenshot({ path, fullPage: true });
    return;
  }
  await electronApp.evaluate(({ BrowserWindow }) => {
    const mainWindow = BrowserWindow.getAllWindows()[0];
    mainWindow?.show();
    mainWindow?.focus();
    mainWindow?.moveTop();
  });
  await window.waitForTimeout(250);
  const pid = electronApp.process().pid;
  if (pid === undefined) throw new Error("ELECTRON_PID_UNAVAILABLE");
  const nativeWindow = nativeMacWindowForPid(pid);
  try {
    execFileSync("screencapture", ["-x", `-l${nativeWindow.id}`, path], { stdio: "pipe" });
  } catch (error: unknown) {
    throw new Error(
      [
        "NATIVE_MAC_WINDOW_SCREENSHOT_FAILED",
        `window_id=${nativeWindow.id}`,
        `bounds=${nativeWindow.x},${nativeWindow.y},${nativeWindow.width},${nativeWindow.height}`,
        "macOS did not allow screencapture to capture the Electron window; grant Screen Recording permission to the terminal host and rerun the screenshot spec.",
        error instanceof Error ? error.message : String(error),
      ].join("\n"),
    );
  }
}

test("captures landing page desktop screenshots", async ({ electronApp, fixtureSidecar, window }) => {
  await electronApp.evaluate(({ BrowserWindow }) => {
    BrowserWindow.getAllWindows()[0]?.setSize(1440, 960);
  });

  await expect(window.locator("#onboarding-heading")).toHaveText("创建 AGENT 档案");
  await saveLandingScreenshot(electronApp, window, "01-create-agent.png");

  await completeFirstRunOnboarding(window, fixtureSidecar);
  await expect(window.getByRole("log", { name: "任务对话" })).toBeVisible();
  await saveLandingScreenshot(electronApp, window, "02-ready-workbench.png");

  await window.getByRole("textbox", { name: "追加信息" }).fill("请修复 src/example.py，让 answer() 返回 2。");
  await window.getByRole("button", { name: "发送并运行" }).click();
  await expect(window.getByText("真实 Provider action 已完成：TASK_COMPLETE")).toBeVisible();
  await expect(window.getByLabel("Diff 逐行预览")).toBeVisible();
  await saveLandingScreenshot(electronApp, window, "03-diff-review.png");

  await window.getByRole("button", { name: /测试 Agent/u }).click();
  await window.getByRole("menuitem", { name: "设置" }).click();
  await expect(window.getByRole("dialog", { name: "设置" })).toBeVisible();
  await saveLandingScreenshot(electronApp, window, "04-settings-api-bindings.png");

  await window.getByRole("button", { name: "关闭悬浮窗" }).click();
  await window.getByRole("button", { name: /测试 Agent/u }).click();
  await window.getByRole("menuitem", { name: "权限" }).click();
  await expect(window.getByRole("dialog", { name: "权限" })).toBeVisible();
  await saveLandingScreenshot(electronApp, window, "05-permissions-panel.png");
});
