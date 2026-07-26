import { spawn, spawnSync } from "node:child_process";
import { request } from "node:http";
import { createServer } from "node:net";
import { dirname, join } from "node:path";

function parseArgs(argv) {
  return { smoke: argv.includes("--smoke") };
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        server.close(() => reject(new Error("PORT_RESOLUTION_FAILED")));
        return;
      }
      const port = address.port;
      server.close(() => resolve(port));
    });
  });
}

function waitForHttp(url, { timeoutMs = 10_000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    function attempt() {
      const req = request(url, { method: "GET", timeout: 1_000 }, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 500) {
          resolve();
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
        reject(new Error("VITE_SMOKE_TIMEOUT"));
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

function nodePackageCommand(kind) {
  if (process.platform !== "win32") return { command: kind, args: [] };
  const script = kind === "npm" ? "npm-cli.js" : "npx-cli.js";
  return {
    command: process.execPath,
    args: [join(dirname(process.execPath), "node_modules/npm/bin", script)]
  };
}

const { smoke } = parseArgs(process.argv.slice(2));
const port = await findFreePort();
const npx = nodePackageCommand("npx");
const vite = spawn(
  npx.command,
  [...npx.args, "--no-install", "vite", "src/renderer", "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
  {
    cwd: process.cwd(),
    env: { ...process.env, BROWSER: "none" },
    stdio: smoke ? ["ignore", "pipe", "pipe"] : "inherit",
    shell: false
  }
);

if (!smoke) {
  vite.once("exit", (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    process.exitCode = code ?? 1;
  });
} else {
  try {
    await waitForHttp(`http://127.0.0.1:${port}/`);
    console.log(`DEV_RENDERER_SMOKE_OK http://127.0.0.1:${port}/`);
  } finally {
    stopProcess(vite);
  }
}
