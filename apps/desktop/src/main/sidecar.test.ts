// @vitest-environment node

import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bundledSidecarExecutable, resolveSidecarLaunch, sidecarTargetKey } from "./sidecar.js";

function createBundledSidecar(platform: NodeJS.Platform, arch: NodeJS.Architecture): string {
  const root = mkdtempSync(join(tmpdir(), "yagcode-sidecar-test-"));
  const key = sidecarTargetKey(platform, arch);
  const name = platform === "win32" ? "yagcode-sidecar.exe" : "yagcode-sidecar";
  const directory = join(root, "sidecar", key, "yagcode-sidecar");
  mkdirSync(directory, { recursive: true });
  writeFileSync(join(directory, name), "fake", "utf8");
  return root;
}

describe("packaged sidecar launch contract", () => {
  it("uses bundled macOS sidecar executable instead of the project venv", () => {
    const resourcesPath = createBundledSidecar("darwin", "arm64");
    const launch = resolveSidecarLaunch(
      {
        cwd: "/repo",
        env: {},
        platform: "darwin",
        arch: "arm64",
        packaged: true,
        resourcesPath,
      },
      { origin: "app://yagcode", port: 48123, token: "startup-token" },
    );

    expect(launch.command).toBe(join(resourcesPath, "sidecar", "darwin-arm64", "yagcode-sidecar", "yagcode-sidecar"));
    expect(launch.argv).toEqual([
      "serve",
      "--host",
      "127.0.0.1",
      "--port",
      "48123",
      "--origin",
      "app://yagcode",
      "--token",
      "startup-token",
    ]);
    expect(launch.env.PYTHONPATH).toBeUndefined();
  });

  it("uses the bundled Windows sidecar executable name", () => {
    const resourcesPath = createBundledSidecar("win32", "x64");

    expect(
      bundledSidecarExecutable({
        cwd: "C:\\repo",
        env: {},
        platform: "win32",
        arch: "x64",
        packaged: true,
        resourcesPath,
      }).replaceAll("\\", "/"),
    ).toContain("/sidecar/win32-x64/yagcode-sidecar/yagcode-sidecar.exe");
  });

  it("keeps development launches on the project Python venv", () => {
    const root = mkdtempSync(join(tmpdir(), "yagcode-dev-sidecar-test-"));
    const python = join(root, ".venv", "bin", "python");
    mkdirSync(join(root, ".venv", "bin"), { recursive: true });
    writeFileSync(python, "fake", "utf8");

    const launch = resolveSidecarLaunch(
      { cwd: root, env: {}, platform: "darwin", arch: "arm64", packaged: false },
      { origin: "app://yagcode", port: 48123, token: "startup-token" },
    );

    expect(launch.command).toBe(python);
    expect(launch.argv.slice(0, 2)).toEqual(["-m", "yagcode.api.server"]);
    expect(launch.argv).toContain("--origin");
    expect(launch.argv).toContain("--token");
    expect(launch.env.PYTHONPATH).toBe(join(root, "src"));
  });
});
