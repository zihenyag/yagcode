import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Ajv2020 } from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

type JsonObject = Record<string, unknown>;
type TestOwnedSpawnResult = { status: number | null; signal: NodeJS.Signals | null; error?: Error };
type SpawnLike = (
  command: string,
  argv: readonly string[],
  options: { cwd: string; env: NodeJS.ProcessEnv; stdio: "inherit"; shell: false },
) => TestOwnedSpawnResult;

function readJson(relativePath: string): JsonObject {
  return JSON.parse(readFileSync(resolve(repoRoot, relativePath), "utf8")) as JsonObject;
}

function validateWithSchema(schemaPath: string, value: JsonObject): boolean {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  const validate = ajv.compile(readJson(schemaPath));
  return validate(value) === true;
}

function cloneWithout(source: JsonObject, key: string): JsonObject {
  const copy = { ...source };
  delete copy[key];
  return copy;
}

function canonicalGeneratedFixtureSource(name: string, typeName: string, value: JsonObject): string {
  return [
    'import type { EventEnvelope, ReviewView } from "./api.js";',
    "",
    `export const ${name} = ${JSON.stringify(value, null, 2)} as const satisfies ${typeName};`,
    "",
  ].join("\n");
}

const testOwnedContractCommands = Object.freeze([
  ["run", "check:generated", "--workspace", "packages/contracts"],
  ["run", "typecheck", "--workspace", "packages/contracts"],
] as const);

function runTestOwnedContractChecks({
  platform,
  nodePath,
  cwd,
  env,
  spawn,
}: {
  platform: NodeJS.Platform;
  nodePath: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
  spawn: SpawnLike;
}): number {
  for (const argv of testOwnedContractCommands) {
    const command = platform === "win32" ? nodePath : "npm";
    const prefixArgv =
      platform === "win32" ? [`${nodePath.slice(0, nodePath.lastIndexOf("\\"))}\\node_modules\\npm\\bin\\npm-cli.js`] : [];
    const result = spawn(command, [...prefixArgv, ...argv], { cwd, env, stdio: "inherit", shell: false });
    if (result.error || result.signal || result.status !== 0) return 1;
  }
  return 0;
}

function containsForbiddenRuntimeImport(source: string): boolean {
  return /@yagcode\/contracts|contracts\/api|sidecar|provider|shell/i.test(source);
}

describe("test-owned contract oracles", () => {
  it("test_owned_schema_fixture_oracle_rejects_required_unknown_and_enum_mutations", () => {
    const review = readJson("contracts/api/fixtures/review-view.json");
    expect(validateWithSchema("contracts/api/public-views.schema.json", review)).toBe(true);
    expect(validateWithSchema("contracts/api/public-views.schema.json", cloneWithout(review, "review_id"))).toBe(false);
    expect(validateWithSchema("contracts/api/public-views.schema.json", { ...review, unknown: true })).toBe(false);
    expect(validateWithSchema("contracts/api/public-views.schema.json", { ...review, state: "APPROVED_ANYWAY" })).toBe(false);

    const event = readJson("contracts/api/fixtures/run-state-event.json");
    expect(validateWithSchema("contracts/api/events.schema.json", event)).toBe(true);
    expect(validateWithSchema("contracts/api/events.schema.json", cloneWithout(event, "sequence"))).toBe(false);
    expect(validateWithSchema("contracts/api/events.schema.json", { ...event, extra: "leak" })).toBe(false);
    expect(validateWithSchema("contracts/api/events.schema.json", { ...event, event_type: "run.finished" })).toBe(false);
  });

  it("test_owned_generated_fixture_oracle_changes_when_fixture_bytes_change", () => {
    const review = readJson("contracts/api/fixtures/review-view.json");
    const original = canonicalGeneratedFixtureSource("reviewFixture", "ReviewView", review);
    const mutated = canonicalGeneratedFixtureSource("reviewFixture", "ReviewView", { ...review, summary: "mutated" });
    expect(original).toContain("satisfies ReviewView");
    expect(original).not.toEqual(mutated);
  });

  it("test_owned_runner_oracle_uses_array_argv_shell_false_and_fail_fast", () => {
    const calls: Array<{ command: string; argv: string[]; shell: boolean | undefined }> = [];
    const passingSpawn: SpawnLike = (command, argv, options) => {
      calls.push({ command, argv: [...argv], shell: options.shell });
      return { status: 0, signal: null };
    };
    expect(runTestOwnedContractChecks({ platform: "darwin", nodePath: "/opt/node/bin/node", cwd: "/repo", env: {}, spawn: passingSpawn })).toBe(0);
    expect(calls).toEqual([
      { command: "npm", argv: ["run", "check:generated", "--workspace", "packages/contracts"], shell: false },
      { command: "npm", argv: ["run", "typecheck", "--workspace", "packages/contracts"], shell: false },
    ]);

    let count = 0;
    const failingSpawn: SpawnLike = () => {
      count += 1;
      return { status: 1, signal: null };
    };
    expect(runTestOwnedContractChecks({ platform: "win32", nodePath: "C:\\Program Files\\nodejs\\node.exe", cwd: "/repo", env: {}, spawn: failingSpawn })).toBe(1);
    expect(count).toBe(1);
  });

  it("test_owned_runtime_graph_oracle_flags_contracts_sidecar_provider_and_shell_imports", () => {
    expect(containsForbiddenRuntimeImport('import { StatusBadge } from "./components/StatusBadge.js"')).toBe(false);
    expect(containsForbiddenRuntimeImport('import type { ReviewView } from "@yagcode/contracts"')).toBe(true);
    expect(containsForbiddenRuntimeImport('import { connectSidecar } from "../sidecar/client.js"')).toBe(true);
    expect(containsForbiddenRuntimeImport('import { provider } from "../provider.js"')).toBe(true);
    expect(containsForbiddenRuntimeImport('import { exec } from "node:child_process"; exec("shell")')).toBe(true);
  });
});
