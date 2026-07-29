import { app, dialog, ipcMain, Notification } from "electron";
import type { BrowserWindow } from "electron";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createSecureWindow, applySessionSecurity, registerRendererProtocol, DESKTOP_ORIGIN } from "./security.js";
import { openIntentWindow, registerIntentHandlers } from "./intentWindow.js";
import { registerLifecycle } from "./lifecycle.js";
import { SidecarController } from "./sidecar.js";

const currentDir = dirname(fileURLToPath(import.meta.url));
const desktopRoot = resolve(currentDir, "..");
const distRoot = desktopRoot;
const preloadPath = join(desktopRoot, "preload", "index.cjs");
const intentPreloadPath = join(desktopRoot, "preload", "intent.cjs");
const projectRoot = process.env.YAGCODE_PROJECT_ROOT ?? resolve(desktopRoot, "../..");
const screenshotSceneIds = [
  "01-create-agent",
  "02-ready-workbench",
  "03-diff-review",
  "04-settings-api-bindings",
  "05-permissions-panel",
] as const;
const pendingIntentResults = new Map<
  string,
  { ok: true; result: unknown } | { ok: false; error: string }
>();

interface IntentOpenRequest {
  requestId: string;
  intentId: string;
}

function parseIntentOpenRequest(payload: unknown): IntentOpenRequest {
  if (typeof payload !== "object" || payload === null) throw new Error("INVALID_INTENT_OPEN_REQUEST");
  const record = payload as Record<string, unknown>;
  if (typeof record.requestId !== "string" || !/^[A-Za-z0-9._:-]{1,120}$/u.test(record.requestId)) {
    throw new Error("INVALID_INTENT_REQUEST_ID");
  }
  if (typeof record.intentId !== "string" || !/^[A-Za-z0-9._:-]{1,120}$/u.test(record.intentId)) {
    throw new Error("INVALID_INTENT_ID");
  }
  return { requestId: record.requestId, intentId: record.intentId };
}

function storeIntentResult(requestId: string, result: { ok: true; result: unknown } | { ok: false; error: string }): void {
  pendingIntentResults.set(requestId, result);
}

async function loadRenderer(window: BrowserWindow, screenshotScene?: string): Promise<void> {
  const rendererUrl = process.env.YAGCODE_DESKTOP_RENDERER_URL;
  if (rendererUrl !== undefined && rendererUrl.length > 0) {
    const url = new URL(rendererUrl);
    if (screenshotScene !== undefined) url.searchParams.set("yagcodeScreenshotScene", screenshotScene);
    await window.loadURL(url.toString());
  } else {
    const suffix = screenshotScene === undefined ? "" : `?yagcodeScreenshotScene=${encodeURIComponent(screenshotScene)}`;
    await window.loadURL(`${DESKTOP_ORIGIN}/index.html${suffix}`);
  }
}

async function main(): Promise<void> {
  await app.whenReady();
  applySessionSecurity();
  registerRendererProtocol({ distRoot });

  if (process.env.YAGCODE_DESKTOP_SCREENSHOT_SCENES === "1") {
    let screenshotWindows: BrowserWindow[] = [];
    async function createScreenshotWindows(): Promise<void> {
      screenshotWindows = [];
      for (const [index, scene] of screenshotSceneIds.entries()) {
        const window = createSecureWindow({ preloadPath, show: true });
        window.setTitle(`YagCode screenshot ${index + 1}: ${scene}`);
        window.setSize(1440, 960);
        window.setMinimumSize(1080, 720);
        window.setPosition(42 + index * 34, 42 + index * 34, false);
        window.on("closed", () => {
          screenshotWindows = screenshotWindows.filter((candidate) => candidate !== window);
        });
        screenshotWindows.push(window);
        await loadRenderer(window, scene);
      }
      screenshotWindows.at(-1)?.focus();
    }
    await createScreenshotWindows();
    app.on("activate", () => {
      const visibleWindows = screenshotWindows.filter((window) => !window.isDestroyed());
      if (visibleWindows.length > 0) {
        visibleWindows.at(-1)?.show();
        visibleWindows.at(-1)?.focus();
        return;
      }
      void createScreenshotWindows().catch((error: unknown) => {
        console.error(error instanceof Error ? error.message : "DESKTOP_SCREENSHOT_WINDOWS_RECREATE_FAILED");
      });
    });
    return;
  }

  const sidecarCwd = app.isPackaged ? app.getPath("userData") : projectRoot;
  const sidecar = new SidecarController({
    cwd: sidecarCwd,
    env: process.env,
    platform: process.platform,
    arch: process.arch,
    packaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
  });
  await sidecar.start();
  registerIntentHandlers(sidecar);
  let mainWindow: BrowserWindow | null = null;

  async function createMainWindow(): Promise<BrowserWindow> {
    await sidecar.start();
    const window = createSecureWindow({ preloadPath, show: process.env.YAGCODE_DESKTOP_SMOKE !== "1" });
    mainWindow = window;
    window.on("closed", () => {
      if (mainWindow === window) mainWindow = null;
    });
    registerLifecycle(window, sidecar);
    await loadRenderer(window);
    return window;
  }

  ipcMain.handle("sidecar:connection", () => sidecar.connectionView());
  ipcMain.handle("directory:choose", async () => {
    if (process.env.YAGCODE_E2E === "1" && process.env.YAGCODE_E2E_DIRECTORY_PATH) {
      return { canceled: false, paths: [process.env.YAGCODE_E2E_DIRECTORY_PATH] };
    }
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"] });
    return result.canceled ? { canceled: true, paths: [] } : { canceled: false, paths: result.filePaths };
  });
  ipcMain.handle("notification:show", (_event, notification: unknown) => {
    if (typeof notification !== "object" || notification === null) throw new Error("INVALID_NOTIFICATION");
    const record = notification as Record<string, unknown>;
    const title = typeof record.title === "string" ? record.title : "YagCode";
    const body = typeof record.body === "string" ? record.body : "";
    if (Notification.isSupported()) new Notification({ title, body }).show();
    return { ok: true };
  });

  ipcMain.on("intent:open", (event, payload: unknown) => {
    const request = parseIntentOpenRequest(payload);
    const parent = mainWindow;
    if (parent === null || parent.isDestroyed()) {
      storeIntentResult(request.requestId, { ok: false, error: "MAIN_WINDOW_UNAVAILABLE" });
      return;
    }
    void openIntentWindow({ parent, preloadPath: intentPreloadPath, sidecar, intentId: request.intentId }).then(
      (result) => storeIntentResult(request.requestId, { ok: true, result }),
      (error: unknown) => {
        const message = error instanceof Error ? error.message : "INTENT_FAILED";
        storeIntentResult(request.requestId, { ok: false, error: message });
      },
    );
  });
  ipcMain.handle("intent:poll-result", (_event, requestId: unknown) => {
    if (typeof requestId !== "string" || !/^[A-Za-z0-9._:-]{1,120}$/u.test(requestId)) {
      throw new Error("INVALID_INTENT_REQUEST_ID");
    }
    const result = pendingIntentResults.get(requestId);
    if (result === undefined) return { ready: false };
    pendingIntentResults.delete(requestId);
    return { ready: true, ...result };
  });
  await createMainWindow();

  app.on("activate", () => {
    if (mainWindow !== null && !mainWindow.isDestroyed()) {
      mainWindow.show();
      mainWindow.focus();
      return;
    }
    void createMainWindow().catch((error: unknown) => {
      console.error(error instanceof Error ? error.message : "DESKTOP_WINDOW_RECREATE_FAILED");
    });
  });

  if (process.env.YAGCODE_DESKTOP_SMOKE === "1") {
    await sidecar.stop();
    app.exit(0);
  }
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

void main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : "DESKTOP_MAIN_FAILED");
  app.exit(1);
});
