import React, { useState } from "react";
import { StatusBadge } from "@yagcode/ui/desktop";
import type { TaskModel } from "../api/adapters.js";
import { isModelLocked } from "../state/reducer.js";

function runTone(runState: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (runState === "FINISHED") return "success";
  if (runState === "FAILED") return "danger";
  if (runState === "WAITING_PERMISSION" || runState === "WAITING_PRIVACY" || runState === "INTERRUPTED") return "warning";
  if (runState === "RUNNING" || runState === "COMPACTING" || runState === "STOPPING") return "info";
  return "neutral";
}

export function ModelSelector({
  runState,
  model,
  models,
  onChange,
}: {
  runState: string;
  model: string;
  models: readonly { id: string; label: string; provider: string }[];
  onChange?: (model: string) => void;
}) {
  const locked = isModelLocked(runState);
  return (
    <label className="field">
      <span>模型</span>
      <select aria-label="模型" disabled={locked} value={model} onChange={(event) => onChange?.(event.currentTarget.value)}>
        {models.map((candidate) => (
          <option key={candidate.id} value={candidate.id}>
            {candidate.label}
          </option>
        ))}
      </select>
      <small>{locked ? "必须中断并保存 checkpoint 后才能切换模型" : "可在当前 Provider/模型列表中切换"}</small>
    </label>
  );
}

export function TaskPane({
  model,
  onCommand,
}: {
  model: TaskModel;
  onCommand(command: { type: string; payload?: unknown }): void;
}) {
  const [planMode, setPlanMode] = useState(model.planMode);
  const [selectedModel, setSelectedModel] = useState(model.model);
  return (
    <section className="workbench-pane workbench-pane--task" aria-labelledby="task-heading">
      <header className="pane-header pane-header--inline">
        <div>
          <p className="pane-kicker">当前任务</p>
          <h2 id="task-heading">{model.title}</h2>
        </div>
        <StatusBadge tone={runTone(model.runState)} label={model.runState} />
      </header>

      <div className="task-controls" aria-label="运行控制">
        <label className="toggle-row">
          <input checked={planMode} onChange={(event) => setPlanMode(event.currentTarget.checked)} type="checkbox" />
          <span>Plan 模式</span>
        </label>
        <ModelSelector model={selectedModel} models={model.models} runState={model.runState} onChange={setSelectedModel} />
      </div>

      <dl className="metric-grid" aria-label="预算、重试与压缩">
        <div>
          <dt>Token 预算</dt>
          <dd>{model.budget.tokenLimit}</dd>
        </div>
        <div>
          <dt>时间预算</dt>
          <dd>{model.budget.timeLimitMinutes} 分钟</dd>
        </div>
        <div>
          <dt>连接中断重试</dt>
          <dd>{model.retryPolicy.connectionRetries} 次</dd>
        </div>
        <div>
          <dt>工具重试</dt>
          <dd>{model.retryPolicy.toolRetries} 次</dd>
        </div>
        <div>
          <dt>模型重试</dt>
          <dd>{model.retryPolicy.modelRetries} 次</dd>
        </div>
        <div>
          <dt>压缩阈值</dt>
          <dd>{model.compactAfterLines} 行</dd>
        </div>
      </dl>

      {model.error ? (
        <section className="error-card" role="alert" aria-labelledby="task-error-heading">
          <h3 id="task-error-heading">运行错误</h3>
          <p>原因：{model.error.reason}</p>
          <p>副作用状态：{model.error.sideEffectState}</p>
          <p>影响范围：{model.error.scope}</p>
          <p>恢复操作：{model.error.recovery}</p>
        </section>
      ) : null}

      <label className="field field--stretch">
        <span>追加信息</span>
        <textarea disabled={!model.appendEnabled} placeholder="运行中可以追加约束、日志或复现步骤" rows={6} />
      </label>

      <div className="button-row">
        <button className="yg-button" onClick={() => onCommand({ type: "stop_run" })} type="button">
          停止
        </button>
        <button className="yg-button" onClick={() => onCommand({ type: "resume_run" })} type="button">
          恢复
        </button>
        <button className="yg-button" onClick={() => onCommand({ type: "append_message" })} type="button">
          追加到线程
        </button>
      </div>
    </section>
  );
}
