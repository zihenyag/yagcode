import React, { useId } from "react";
import { StatusBadge } from "./StatusBadge.js";

export interface DangerAction {
  id: string;
  label: string;
  disabled?: boolean;
  variant?: "default" | "danger";
  onClick?: () => void;
}

export interface DangerPanelProps {
  title: string;
  impact: string;
  actions?: readonly DangerAction[];
}

export function DangerPanel({ title, impact, actions = [] }: DangerPanelProps) {
  const titleId = useId();
  return (
    <section className="yg-danger-panel" role="alert" aria-labelledby={titleId}>
      <div className="yg-danger-panel__header">
        <h3 className="yg-danger-panel__title" id={titleId}>
          {title}
        </h3>
        <StatusBadge tone="danger" label="高风险" iconLabel="危险" />
      </div>
      <p className="yg-danger-panel__impact">{impact}</p>
      {actions.length > 0 ? (
        <div className="yg-danger-panel__actions">
          {actions.map((action) => (
            <button
              className={["yg-button", action.variant === "danger" ? "yg-button--danger" : undefined].filter(Boolean).join(" ")}
              disabled={action.disabled}
              key={action.id}
              onClick={action.onClick}
              type="button"
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}
