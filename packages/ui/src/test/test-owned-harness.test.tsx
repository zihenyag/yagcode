import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import React from "react";
import { describe, expect, it } from "vitest";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

async function getSeriousOrCriticalViolations(container: Element) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
}

function hasForbiddenRuntimeImport(source: string): boolean {
  return /@yagcode\/contracts|contracts\/api|sidecar|provider|shell/i.test(source);
}

function statusHasNonColorMeaning(status: { tone: string; label?: string; iconLabel?: string }): boolean {
  return Boolean(status.label?.trim()) && Boolean(status.iconLabel?.trim());
}

describe("test-owned UI harness", () => {
  it("test_owned_jsdom_jest_dom_and_focus_helpers_are_active", () => {
    render(<button type="button">追加信息</button>);
    const button = screen.getByRole("button", { name: "追加信息" });
    expect(button).toBeVisible();
    button.focus();
    expect(button).toHaveFocus();
  });

  it("test_owned_axe_helper_detects_accessibility_regressions", async () => {
    const { container, rerender } = render(<button type="button">停止运行</button>);
    await expect(getSeriousOrCriticalViolations(container)).resolves.toEqual([]);

    rerender(<button type="button" aria-label="" />);
    const violations = await getSeriousOrCriticalViolations(container);
    expect(violations.some((violation) => violation.id === "button-name")).toBe(true);
  });

  it("test_owned_display_props_oracle_rejects_color_only_state", () => {
    expect(statusHasNonColorMeaning({ tone: "danger", label: "高风险", iconLabel: "危险" })).toBe(true);
    expect(statusHasNonColorMeaning({ tone: "danger" })).toBe(false);
    expect(statusHasNonColorMeaning({ tone: "danger", label: "高风险" })).toBe(false);
  });

  it("test_owned_runtime_graph_oracle_flags_forbidden_runtime_imports", () => {
    const packageJson = JSON.parse(readFileSync(resolve(packageRoot, "package.json"), "utf8")) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
      peerDependencies?: Record<string, string>;
    };
    expect(packageJson.dependencies?.["@yagcode/contracts"]).toBeUndefined();
    expect(packageJson.devDependencies?.["@yagcode/contracts"]).toBeUndefined();
    expect(packageJson.peerDependencies?.["@yagcode/contracts"]).toBeUndefined();

    expect(hasForbiddenRuntimeImport('export { StatusBadge } from "./components/StatusBadge.js";')).toBe(false);
    expect(hasForbiddenRuntimeImport('import type { ReviewView } from "@yagcode/contracts";')).toBe(true);
    expect(hasForbiddenRuntimeImport('import { sidecar } from "../sidecar.js";')).toBe(true);
    expect(hasForbiddenRuntimeImport('import { provider } from "../provider.js";')).toBe(true);
    expect(hasForbiddenRuntimeImport('import { shell } from "electron";')).toBe(true);
  });
});
