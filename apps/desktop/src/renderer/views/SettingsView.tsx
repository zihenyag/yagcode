import React from "react";
import { StatusBadge } from "@yagcode/ui/desktop";
import type { SettingsModel } from "../api/adapters.js";

function credentialTone(status: string): "success" | "warning" | "danger" {
  if (status === "present") return "success";
  if (status === "error") return "danger";
  return "warning";
}

export function SettingsView({ model }: { model: SettingsModel }) {
  return (
    <section className="review-section" aria-labelledby="settings-heading">
      <h3 id="settings-heading">设置</h3>
      <div className="settings-grid">
        {model.credentialStatuses.map((credential) => (
          <div className="settings-row" key={credential.provider}>
            <span>{credential.provider}</span>
            <StatusBadge tone={credentialTone(credential.status)} label={credential.status === "present" ? "已配置" : credential.status === "missing" ? "缺失" : "异常"} />
            <small>{credential.updatedAt ?? "未更新"}</small>
          </div>
        ))}
      </div>
      <label className="field">
        <span>原始对话和工具输出保留</span>
        <select defaultValue={model.selectedRetention}>
          {model.retentionOptions.map((option) => (
            <option key={option} value={option}>
              {option === "permanent" ? "永久（默认）" : option}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}
