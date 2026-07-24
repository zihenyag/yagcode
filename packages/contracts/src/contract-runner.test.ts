import { describe, expect, it } from "vitest";

type SpawnResult = { status?: number | null; signal?: NodeJS.Signals | null; error?: Error };
type SpawnCall = {
  command: string;
  argv: string[];
  options: { cwd?: string; env?: NodeJS.ProcessEnv; shell?: boolean; stdio?: string };
};

async function loadRunner() {
  try {
    const modulePath = new URL("../scripts/check-contract.mjs", import.meta.url).href;
    return await import(/* @vite-ignore */ modulePath);
  } catch (error) {
    throw new Error("CONTRACT_RUNNER_MISSING", { cause: error });
  }
}

describe("contract runner", () => {
  it("runs generated drift before strict typecheck with shell disabled", async () => {
    const { runContractChecks } = await loadRunner();
    const calls: SpawnCall[] = [];
    const spawn = (command: string, argv: readonly string[], options: SpawnCall["options"]): SpawnResult => {
      calls.push({ command, argv: [...argv], options });
      return { status: 0, signal: null };
    };

    expect(runContractChecks({ platform: "darwin", cwd: "/repo", env: { KEEP: "1" }, spawn })).toBe(0);
    expect(calls).toEqual([
      {
        command: "npm",
        argv: ["run", "check:generated", "--workspace", "packages/contracts"],
        options: { cwd: "/repo", env: { KEEP: "1" }, stdio: "inherit", shell: false },
      },
      {
        command: "npm",
        argv: ["run", "typecheck", "--workspace", "packages/contracts"],
        options: { cwd: "/repo", env: { KEEP: "1" }, stdio: "inherit", shell: false },
      },
    ]);
  });

  it("uses node plus npm-cli on Windows without shell", async () => {
    const { runContractChecks } = await loadRunner();
    const calls: SpawnCall[] = [];
    const spawn = (command: string, argv: readonly string[], options: SpawnCall["options"]): SpawnResult => {
      calls.push({ command, argv: [...argv], options });
      return { status: 0, signal: null };
    };

    expect(runContractChecks({ platform: "win32", nodePath: "C:\\Program Files\\nodejs\\node.exe", cwd: "C:/repo", env: {}, spawn })).toBe(0);
    expect(calls).toEqual([
      {
        command: "C:\\Program Files\\nodejs\\node.exe",
        argv: [
          "C:\\Program Files\\nodejs\\node_modules\\npm\\bin\\npm-cli.js",
          "run",
          "check:generated",
          "--workspace",
          "packages/contracts",
        ],
        options: { cwd: "C:/repo", env: {}, stdio: "inherit", shell: false },
      },
      {
        command: "C:\\Program Files\\nodejs\\node.exe",
        argv: [
          "C:\\Program Files\\nodejs\\node_modules\\npm\\bin\\npm-cli.js",
          "run",
          "typecheck",
          "--workspace",
          "packages/contracts",
        ],
        options: { cwd: "C:/repo", env: {}, stdio: "inherit", shell: false },
      },
    ]);
  });

  it("fails fast on the first check failure and on the second check failure", async () => {
    const { runContractChecks } = await loadRunner();
    let firstFailureCalls = 0;
    const firstFailureSpawn = (): SpawnResult => {
      firstFailureCalls += 1;
      return { status: 1, signal: null };
    };
    expect(runContractChecks({ platform: "darwin", cwd: "/repo", env: {}, spawn: firstFailureSpawn })).toBe(1);
    expect(firstFailureCalls).toBe(1);

    let secondFailureCalls = 0;
    const secondFailureSpawn = (): SpawnResult => {
      secondFailureCalls += 1;
      return { status: secondFailureCalls === 1 ? 0 : 1, signal: null };
    };
    expect(runContractChecks({ platform: "darwin", cwd: "/repo", env: {}, spawn: secondFailureSpawn })).toBe(1);
    expect(secondFailureCalls).toBe(2);
  });
});
