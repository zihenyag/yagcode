import React from "react";

export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral";

export interface StatusBadgeProps {
  tone?: StatusTone;
  label: string;
  iconLabel?: string;
  className?: string;
}

const toneLabels: Record<StatusTone, string> = {
  success: "通过",
  warning: "等待",
  danger: "危险",
  info: "信息",
  neutral: "普通",
};

const toneIcons: Record<StatusTone, string> = {
  success: "✓",
  warning: "!",
  danger: "!",
  info: "i",
  neutral: "·",
};

export function StatusBadge({ tone = "neutral", label, iconLabel = toneLabels[tone], className }: StatusBadgeProps) {
  const classes = ["yg-status-badge", `yg-status-badge--${tone}`, className].filter(Boolean).join(" ");
  return (
    <span className={classes} aria-label={`${label}，状态：${iconLabel}`}>
      <span className="yg-status-badge__icon" aria-hidden="true">
        {toneIcons[tone]}
      </span>
      <span>{label}</span>
    </span>
  );
}
