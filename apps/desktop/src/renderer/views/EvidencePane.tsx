import React from "react";
import { DangerPanel, DiffSummary, EvidenceList, StatusBadge } from "@yagcode/ui/desktop";
import type { EvidenceModel } from "../api/adapters.js";

export interface EvidencePaneProps {
  model: EvidenceModel;
  onIntent(intent: { actionId: string; highRisk: boolean }): void;
}

function reviewTone(state: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (state === "READY" || state === "ACCEPTED") return "success";
  if (state === "CONFLICT" || state === "RECOVERY_REQUIRED" || state === "REJECTED") return "danger";
  if (state === "INCOMPLETE" || state === "ACCEPTING") return "warning";
  return "neutral";
}

export function EvidencePane({ model, onIntent }: EvidencePaneProps) {
  const normalActions = model.approvalActions.filter((action) => !action.highRisk);
  const highRiskActions = model.approvalActions.filter((action) => action.highRisk);
  return (
    <aside className="workbench-pane workbench-pane--evidence" aria-label="审阅、记忆与审计">
      <section className="review-section" aria-labelledby="review-heading">
        <header className="pane-header pane-header--inline">
          <div>
            <p className="pane-kicker">Review #{model.review.reviewId}</p>
            <h2 id="review-heading">变更审阅</h2>
          </div>
          <StatusBadge tone={reviewTone(model.review.state)} label={model.review.state} />
        </header>
        <p className="review-summary">{model.review.summary}</p>
        <DiffSummary filesChanged={model.diff.filesChanged} additions={model.diff.additions} deletions={model.diff.deletions} />
      </section>

      <section className="review-section" aria-labelledby="validation-heading">
        <h3 id="validation-heading">验证证据</h3>
        <EvidenceList items={model.validations} />
      </section>

      <section className="review-section" aria-labelledby="risk-heading">
        <h3 id="risk-heading">风险与未覆盖项</h3>
        <ul className="plain-list">
          {model.risks.map((risk) => (
            <li key={`risk-${risk}`}>风险：{risk}</li>
          ))}
          {model.uncovered.map((item) => (
            <li key={`uncovered-${item}`}>未覆盖：{item}</li>
          ))}
        </ul>
      </section>

      <section className="review-section" aria-labelledby="approval-heading">
        <h3 id="approval-heading">审阅操作</h3>
        <div className="button-row button-row--wrap">
          {normalActions.map((action) => (
            <button className="yg-button" disabled={!action.enabled} key={action.id} onClick={() => onIntent({ actionId: action.id, highRisk: false })} type="button">
              {action.label}
            </button>
          ))}
        </div>
        {highRiskActions.length > 0 ? (
          <DangerPanel
            title="高风险确认"
            impact="这些操作会进入 Electron Main 的可信确认窗口；renderer 只提交结构化意图，不直接执行文件、Git 或 shell。"
            actions={highRiskActions.map((action) => ({
              id: action.id,
              label: action.label,
              disabled: !action.enabled,
              variant: "danger",
              onClick: () => onIntent({ actionId: action.id, highRisk: true }),
            }))}
          />
        ) : null}
      </section>
    </aside>
  );
}
