import { BrowserWindow, ipcMain } from "electron";
import type { IpcMainEvent } from "electron";
import type { IntentChallenge, PrivilegedActionResult, SidecarController } from "./sidecar.js";

interface PendingIntent {
  challenge: IntentChallenge;
  window: BrowserWindow;
  resolve(result: PrivilegedActionResult): void;
  reject(error: Error): void;
}

const pendingByWebContents = new Map<number, PendingIntent>();

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/gu, (char) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;"
    };
    return entities[char] ?? char;
  });
}

function validateIntentId(intentId: string): void {
  if (!/^[A-Za-z0-9._:-]{1,120}$/u.test(intentId)) throw new Error("INVALID_INTENT_ID");
}

function takePending(webContentsId: number): PendingIntent | undefined {
  const exact = pendingByWebContents.get(webContentsId);
  if (exact !== undefined) {
    pendingByWebContents.delete(webContentsId);
    return exact;
  }
  if (pendingByWebContents.size !== 1) return undefined;
  const [fallbackId, fallback] = [...pendingByWebContents.entries()][0] ?? [];
  if (fallbackId === undefined || fallback === undefined) return undefined;
  pendingByWebContents.delete(fallbackId);
  return fallback;
}

function finishIntentWindow(window: BrowserWindow): void {
  if (window.isDestroyed()) return;
  window.hide();
  setTimeout(() => {
    if (!window.isDestroyed()) window.destroy();
  }, 250);
}

async function confirmIntent(webContentsId: number, sidecar: SidecarController): Promise<PrivilegedActionResult | undefined> {
  const pending = takePending(webContentsId);
  if (pending === undefined) return;
  try {
    const result = await sidecar.consumeIntent(pending.challenge);
    pending.resolve(result);
    finishIntentWindow(pending.window);
    return result;
  } catch (error) {
    pending.reject(error instanceof Error ? error : new Error("INTENT_CONSUME_FAILED"));
    finishIntentWindow(pending.window);
    throw error;
  }
}

function cancelIntent(webContentsId: number): void {
  const pending = takePending(webContentsId);
  if (pending !== undefined) {
    pending.reject(new Error("INTENT_CANCELLED"));
    finishIntentWindow(pending.window);
  }
}

function intentNavigationAction(rawUrl: string): "confirm" | "cancel" | undefined {
  try {
    const url = new URL(rawUrl);
    if (url.protocol !== "app:" || url.hostname !== "yagcode") return undefined;
    if (url.pathname === "/__intent/confirm") return "confirm";
    if (url.pathname === "/__intent/cancel") return "cancel";
    return undefined;
  } catch {
    return undefined;
  }
}

function intentControllerScript(): string {
  return `(() => {
  const bind = (selector, method) => {
    const button = document.querySelector(selector);
    if (!button || button.dataset.yagcodeIntentMainBound === "1") return;
    button.dataset.yagcodeIntentMainBound = "1";
    button.addEventListener("click", () => window.yagcodeIntent?.[method]?.());
  };
  bind("[data-intent-confirm]", "confirm");
  bind("[data-intent-cancel]", "cancel");
})();`;
}

function intentHtml(challenge: IntentChallenge): string {
  const payloadHash = Buffer.from(`${challenge.intent_type}:${challenge.resource_id}`).toString("base64url").slice(0, 24);
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
  <title>可信确认</title>
  <style>
    body { margin: 0; font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #111318; color: #f2f4f8; }
    main { padding: 24px; display: grid; gap: 14px; }
    h1 { margin: 0; font-size: 18px; }
    dl { display: grid; grid-template-columns: 96px 1fr; gap: 8px 12px; margin: 0; }
    dt { color: #aab1bd; }
    dd { margin: 0; word-break: break-all; }
    button { border: 1px solid #6c7480; border-radius: 8px; background: #f2f4f8; color: #111318; padding: 8px 12px; }
    button:focus-visible { outline: 2px solid #85b7ff; outline-offset: 2px; }
    .actions { display: flex; gap: 8px; }
  </style>
</head>
<body>
  <main>
    <h1>可信确认</h1>
    <p>此窗口由 Electron Main 打开，不加载第三方内容。确认后将消费一次性 intent。</p>
    <dl>
      <dt>能力</dt><dd>${escapeHtml(challenge.intent_type)}</dd>
      <dt>资源</dt><dd>${escapeHtml(challenge.resource_id)}</dd>
      <dt>Payload Hash</dt><dd>${escapeHtml(payloadHash)}</dd>
      <dt>有效期</dt><dd>仅当前确认窗口，一次性使用</dd>
    </dl>
    <div class="actions">
      <button type="button" data-intent-confirm autofocus>确认执行</button>
      <button type="button" data-intent-cancel>取消</button>
    </div>
  </main>
</body>
</html>`;
}

export function registerIntentHandlers(sidecar: SidecarController): void {
  ipcMain.on("intent:confirm", (event: IpcMainEvent) => {
    void confirmIntent(event.sender.id, sidecar);
  });
  ipcMain.on("intent:cancel", (event: IpcMainEvent) => {
    cancelIntent(event.sender.id);
  });
}

export async function openIntentWindow({
  parent,
  preloadPath,
  sidecar,
  intentId
}: {
  parent: BrowserWindow;
  preloadPath: string;
  sidecar: SidecarController;
  intentId: string;
}): Promise<PrivilegedActionResult> {
  validateIntentId(intentId);
  const challenge = await sidecar.createReviewIntent(intentId);
  const child = new BrowserWindow({
    height: 420,
    parent,
    modal: false,
    show: false,
    title: "YagCode 可信确认",
    width: 520,
    webPreferences: {
      additionalArguments: ["--yagcode-intent-window"],
      contextIsolation: true,
      nodeIntegration: false,
      preload: preloadPath,
      sandbox: true,
      webSecurity: true
    }
  });
  child.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  const handleIntentNavigation = (event: Electron.Event<{ url: string }>, url: string): void => {
    const action = intentNavigationAction(url);
    if (action === undefined) {
      event.preventDefault();
      return;
    }
    event.preventDefault();
    if (action === "confirm") void confirmIntent(child.webContents.id, sidecar);
    if (action === "cancel") cancelIntent(child.webContents.id);
  };
  child.webContents.on("will-navigate", (event) => {
    handleIntentNavigation(event, event.url);
  });
  child.webContents.on("will-frame-navigate", (event) => {
    handleIntentNavigation(event, event.url);
  });
  const result = new Promise<PrivilegedActionResult>((resolve, reject) => {
    pendingByWebContents.set(child.webContents.id, { challenge, window: child, resolve, reject });
    child.on("closed", () => {
      const pending = pendingByWebContents.get(child.webContents.id);
      if (pending !== undefined) {
        pendingByWebContents.delete(child.webContents.id);
        pending.reject(new Error("INTENT_WINDOW_CLOSED"));
      }
    });
  });
  await child.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(intentHtml(challenge))}`);
  await child.webContents.executeJavaScript(intentControllerScript(), true);
  if (!child.isDestroyed()) child.show();
  return result;
}
