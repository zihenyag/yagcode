import { spawnSync } from "node:child_process";
import { dirname, resolve, win32 } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(packageRoot, "../..");

export const CONTRACT_CHECKS = Object.freeze([
  Object.freeze(["run", "check:generated", "--workspace", "packages/contracts"]),
  Object.freeze(["run", "typecheck", "--workspace", "packages/contracts"]),
]);

function npmCommandForPlatform(platform, nodePath = process.execPath) {
  if (platform !== "win32") return { command: "npm", prefixArgv: [] };
  return {
    command: nodePath,
    prefixArgv: [win32.join(win32.dirname(nodePath), "node_modules", "npm", "bin", "npm-cli.js")],
  };
}

export function runContractChecks({
  platform = process.platform,
  nodePath = process.execPath,
  cwd = repoRoot,
  env = process.env,
  spawn = spawnSync,
} = {}) {
  const { command, prefixArgv } = npmCommandForPlatform(platform, nodePath);
  for (const argv of CONTRACT_CHECKS) {
    let result;
    try {
      result = spawn(command, [...prefixArgv, ...argv], { cwd, env, stdio: "inherit", shell: false });
    } catch {
      return 1;
    }
    if (result.error || result.signal || result.status === null || result.status === undefined || result.status !== 0) {
      return 1;
    }
  }
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exitCode = runContractChecks();
}
