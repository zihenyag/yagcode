import React from "react";
import { StatusBadge, type StatusTone } from "./StatusBadge.js";

export type EvidenceStatus = "passed" | "failed" | "running" | "pending" | "warning";

export interface EvidenceItem {
  id: string;
  title: string;
  detail: string;
  status: EvidenceStatus;
  command?: string;
}

export interface EvidenceListProps {
  label?: string;
  items: readonly EvidenceItem[];
}

const statusCopy: Record<EvidenceStatus, { label: string; iconLabel: string; tone: StatusTone }> = {
  passed: { label: "已通过", iconLabel: "通过", tone: "success" },
  failed: { label: "未通过", iconLabel: "失败", tone: "danger" },
  running: { label: "运行中", iconLabel: "运行", tone: "info" },
  pending: { label: "待执行", iconLabel: "等待", tone: "neutral" },
  warning: { label: "需关注", iconLabel: "警告", tone: "warning" },
};

export function EvidenceList({ label = "验证证据", items }: EvidenceListProps) {
  return (
    <ul className="yg-evidence-list" aria-label={label}>
      {items.map((item) => {
        const status = statusCopy[item.status];
        return (
          <li className="yg-evidence-list__item" key={item.id}>
            <div className="yg-evidence-list__header">
              <span className="yg-evidence-list__title">{item.title}</span>
              <StatusBadge tone={status.tone} label={status.label} iconLabel={status.iconLabel} />
            </div>
            <span className="yg-evidence-list__detail">{item.detail}</span>
            {item.command ? <code className="yg-evidence-list__command">{item.command}</code> : null}
          </li>
        );
      })}
    </ul>
  );
}
