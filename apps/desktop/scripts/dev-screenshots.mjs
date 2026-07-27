import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";
import { request } from "node:http";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(scriptDir, "..");
const repoRoot = resolve(desktopDir, "../..");

function findFreePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        server.close(() => reject(new Error("PORT_RESOLUTION_FAILED")));
        return;
      }
      const port = address.port;
      server.close(() => resolvePort(port));
    });
  });
}

function waitForHttp(url, { timeoutMs = 10_000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolveWait, reject) => {
    function attempt() {
      const req = request(url, { method: "GET", timeout: 1_000 }, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
          resolveWait();
          return;
        }
        retry();
      });
      req.once("timeout", () => {
        req.destroy();
        retry();
      });
      req.once("error", retry);
      req.end();
    }
    function retry() {
      if (Date.now() >= deadline) {
        reject(new Error("HTTP_SMOKE_TIMEOUT"));
        return;
      }
      setTimeout(attempt, 150);
    }
    attempt();
  });
}

function stopProcess(child) {
  if (child.killed) return;
  if (process.platform === "win32" && child.pid !== undefined) {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", shell: false });
    return;
  }
  child.kill(process.platform === "win32" ? undefined : "SIGTERM");
}

function waitForProcessExit(child) {
  return new Promise((resolveWait, rejectWait) => {
    child.once("exit", (code, signal) => {
      resolveWait({ code, signal });
    });
    child.once("error", rejectWait);
  });
}

function nodePackageCommand(kind) {
  if (process.platform !== "win32") return { command: kind, args: [] };
  const script = kind === "npm" ? "npm-cli.js" : "npx-cli.js";
  return {
    command: process.execPath,
    args: [join(dirname(process.execPath), "node_modules/npm/bin", script)]
  };
}

const rendererPort = await findFreePort();
const rendererUrl = `http://127.0.0.1:${rendererPort}/`;
const npx = nodePackageCommand("npx");
const npm = nodePackageCommand("npm");

const renderer = spawn(
  npx.command,
  [...npx.args, "--no-install", "vite", "src/renderer", "--host", "127.0.0.1", "--port", String(rendererPort), "--strictPort"],
  {
    cwd: desktopDir,
    env: {
      ...process.env,
      BROWSER: "none",
    },
    stdio: "inherit",
    shell: false
  }
);

let electron;
try {
  await waitForHttp(rendererUrl);
  await new Promise((resolveBuild, rejectBuild) => {
    const build = spawn(npm.command, [...npm.args, "run", "build:main"], {
      cwd: desktopDir,
      env: process.env,
      stdio: "inherit",
      shell: false
    });
    build.once("exit", (code) => {
      if (code === 0) resolveBuild();
      else rejectBuild(new Error(`DESKTOP_MAIN_BUILD_FAILED:${code ?? "null"}`));
    });
    build.once("error", rejectBuild);
  });
  electron = spawn(
    npm.command,
    [...npm.args, "run", "start:electron"],
    {
      cwd: desktopDir,
      env: {
        ...process.env,
        YAGCODE_PROJECT_ROOT: repoRoot,
        YAGCODE_DESKTOP_ORIGIN: new URL(rendererUrl).origin,
        YAGCODE_DESKTOP_RENDERER_URL: rendererUrl,
        YAGCODE_DESKTOP_SCREENSHOT_SCENES: "1",
      },
      stdio: "inherit",
      shell: false
    }
  );
  const { code, signal } = await waitForProcessExit(electron);
  if (signal) process.exitCode = 1;
  else process.exitCode = code ?? 1;
} finally {
  if (electron) stopProcess(electron);
  stopProcess(renderer);
}
