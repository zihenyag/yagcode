import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import React from "react";
import { describe, expect, it } from "vitest";

const srcRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

async function loadUiProduction() {
  try {
    const modulePath = "../desktop.ts";
    return await import(/* @vite-ignore */ modulePath);
  } catch (error) {
    throw new Error("UI_PRODUCTION_MISSING", { cause: error });
  }
}

async function expectNoSeriousOrCriticalA11yIssues(container: Element) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical")).toEqual([]);
}

function readSource(relativePath: string): string {
  return readFileSync(resolve(srcRoot, relativePath), "utf8");
}

describe("shared UI components", () => {
  it("renders risk without relying on color", async () => {
    const { DangerPanel } = await loadUiProduction();
    const { container } = render(<DangerPanel title="需要确认" impact="将写入 2 个文件" />);
    expect(screen.getByRole("alert")).toHaveTextContent("需要确认");
    expect(screen.getByText("高风险")).toBeVisible();
    expect(screen.getByText("将写入 2 个文件")).toBeVisible();
    await expectNoSeriousOrCriticalA11yIssues(container);
  });

  it("renders evidence as a semantic list with explicit status text", async () => {
    const { EvidenceList } = await loadUiProduction();
    const { container } = render(
      <EvidenceList
        label="验证证据"
        items={[
          { id: "red", title: "RED", detail: "失败落在 production 边界", status: "failed" },
          { id: "green", title: "GREEN", detail: "聚焦测试通过", status: "passed" },
        ]}
      />,
    );
    expect(screen.getByRole("list", { name: "验证证据" })).toBeVisible();
    expect(screen.getByText("未通过")).toBeVisible();
    expect(screen.getByText("已通过")).toBeVisible();
    await expectNoSeriousOrCriticalA11yIssues(container);
  });

  it("labels diff additions and deletions with text as well as color", async () => {
    const { DiffSummary } = await loadUiProduction();
    render(<DiffSummary filesChanged={2} additions={18} deletions={4} />);
    expect(screen.getByRole("group", { name: "Diff 摘要" })).toBeVisible();
    expect(screen.getByText("+18 新增")).toBeVisible();
    expect(screen.getByText("-4 删除")).toBeVisible();
    expect(screen.getByText("2 个文件")).toBeVisible();
  });

  it("keeps status badges explicit and keyboard-safe", async () => {
    const { StatusBadge } = await loadUiProduction();
    render(<StatusBadge tone="warning" label="等待审批" iconLabel="等待" />);
    const badge = screen.getByText("等待审批");
    expect(badge).toBeVisible();
    expect(badge.closest("[aria-label]")).toHaveAttribute("aria-label", "等待审批，状态：等待");
  });

  it("exposes required tokens and blocks contract/runtime dependencies", async () => {
    await loadUiProduction();
    const tokens = readSource("tokens.css");
    expect(tokens).toContain("--focus-ring: #0b63ce");
    expect(tokens).toContain("--status-danger-bg: #fff0f0");
    expect(tokens).toContain("--status-danger-fg: #8b0000");
    expect(tokens).toContain("--diff-add-bg: #e8f7ed");
    expect(tokens).toContain("--diff-delete-bg: #fff0f0");
    expect(tokens).toContain(":focus-visible");
    expect(tokens).toContain("prefers-reduced-motion: reduce");

    for (const file of ["public.ts", "desktop.ts"]) {
      expect(readSource(file)).not.toMatch(/@yagcode\/contracts|contracts\/api|sidecar|provider|shell/i);
    }
  });
});
