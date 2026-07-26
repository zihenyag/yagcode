import { BrowserWindow, protocol, session } from "electron";
import type { BrowserWindowConstructorOptions } from "electron";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { isAbsolute, join, normalize, relative } from "node:path";

export const DESKTOP_ORIGIN = "app://yagcode";

export interface RendererLocation {
  distRoot: string;
  devServerUrl?: string;
}

protocol.registerSchemesAsPrivileged([
  {
    scheme: "app",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true
    }
  }
]);

function resolveRendererFile(distRoot: string, pathname: string): string {
  if (pathname === "/" || pathname === "/index.html") {
    const nested = join(distRoot, "src", "renderer", "index.html");
    if (existsSync(nested)) return nested;
    return join(distRoot, "index.html");
  }
  const relative = pathname.replace(/^\/+/u, "");
  return join(distRoot, relative);
}

export function registerRendererProtocol({ distRoot }: RendererLocation): void {
  if (protocol.isProtocolHandled("app")) return;
  protocol.handle("app", async (request) => {
    const url = new URL(request.url);
    if (url.hostname !== "yagcode") {
      return new Response("APP_ORIGIN_DENIED", { status: 403 });
    }
    const filePath = normalize(resolveRendererFile(distRoot, decodeURIComponent(url.pathname)));
    const relativePath = relative(normalize(distRoot), filePath);
    if (relativePath.startsWith("..") || isAbsolute(relativePath)) {
      return new Response("APP_PATH_DENIED", { status: 403 });
    }
    const bytes = await readFile(filePath);
    return new Response(bytes, {
      headers: {
        "Access-Control-Allow-Origin": DESKTOP_ORIGIN,
        "content-type": contentType(filePath)
      }
    });
  });
}

function isAllowedMainWindowNavigation(rawUrl: string): boolean {
  if (rawUrl === DESKTOP_ORIGIN || rawUrl.startsWith(`${DESKTOP_ORIGIN}/`)) return true;
  const rendererUrl = process.env.YAGCODE_DESKTOP_RENDERER_URL;
  if (rendererUrl === undefined || rendererUrl.length === 0) return false;
  try {
    return new URL(rawUrl).origin === new URL(rendererUrl).origin;
  } catch {
    return false;
  }
}

function contentType(filePath: string): string {
  if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
  if (filePath.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
  if (filePath.endsWith(".svg")) return "image/svg+xml";
  if (filePath.endsWith(".png")) return "image/png";
  if (filePath.endsWith(".jpg") || filePath.endsWith(".jpeg")) return "image/jpeg";
  return "application/octet-stream";
}

export function applySessionSecurity(): void {
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*",
    "object-src 'none'",
    "frame-src 'none'",
    "base-uri 'none'",
    "form-action 'none'"
  ].join("; ");

  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [csp]
      }
    });
  });
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => {
    callback(false);
  });
}

export function createSecureWindow({
  preloadPath,
  show = true
}: {
  preloadPath: string;
  show?: boolean;
}): BrowserWindow {
  const chromeOptions: BrowserWindowConstructorOptions =
    process.platform === "darwin"
      ? {
          titleBarStyle: "hiddenInset",
          trafficLightPosition: { x: 18, y: 18 },
        }
      : {};
  const window = new BrowserWindow({
    ...chromeOptions,
    height: 840,
    minHeight: 720,
    minWidth: 1080,
    show,
    title: "YagCode",
    width: 1280,
    webPreferences: {
      preload: preloadPath,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true
    }
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, url) => {
    if (isAllowedMainWindowNavigation(url)) return;
    event.preventDefault();
  });
  return window;
}
