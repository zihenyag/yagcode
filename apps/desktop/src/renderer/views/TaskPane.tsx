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
    <label className="model-field">
      <span className="control-label">模型</span>
      <select aria-label="模型" disabled={locked} value={model} onChange={(event) => onChange?.(event.currentTarget.value)}>
        {models.map((candidate) => (
          <option key={candidate.id} value={candidate.id}>
            {candidate.label}
          </option>
        ))}
      </select>
      <small>{locked ? "中断并保存 checkpoint 后可切换" : "可切换当前模型"}</small>
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
      <header className="task-titlebar">
        <div>
          <p className="pane-kicker">当前任务</p>
          <h2 id="task-heading">{model.title}</h2>
        </div>
        <StatusBadge tone={runTone(model.runState)} label={model.runState} />
      </header>

      <div className="conversation" role="log" aria-label="任务对话">
        <article className="message message--user">
          <div className="message__avatar" aria-hidden="true">你</div>
          <div className="message__content">
            <header className="message__meta">
              <span>用户请求</span>
              <span>{model.threadId}</span>
            </header>
            <div className="message__bubble">
              <p>{model.title}</p>
            </div>
          </div>
        </article>

        <article className="message message--assistant">
          <div className="message__avatar" aria-hidden="true">Y</div>
          <div className="message__content">
            <header className="message__meta">
              <span>Agent 运行</span>
              <span>{model.provider} · {selectedModel}</span>
            </header>
            <div className="message__bubble">
              <p>已连接本地 sidecar。桌面端只展示状态、收集追加信息和发起可信确认；文件、Git、shell 与 Agent loop 都由 sidecar 执行。</p>
              <ul className="message-facts" aria-label="当前运行约束">
                <li>{model.budget.tokenLimit} tokens</li>
                <li>{model.budget.timeLimitMinutes} 分钟</li>
                <li>连接重试 {model.retryPolicy.connectionRetries} 次</li>
                <li>工具重试 {model.retryPolicy.toolRetries} 次</li>
                <li>模型重试 {model.retryPolicy.modelRetries} 次</li>
                <li>{model.compactAfterLines} 行压缩</li>
              </ul>
            </div>
          </div>
        </article>

        {model.error ? (
          <article className="message message--system" role="alert" aria-labelledby="task-error-heading">
            <div className="message__avatar" aria-hidden="true">!</div>
            <div className="message__content">
              <header className="message__meta">
                <span id="task-error-heading">运行错误</span>
                <span>{model.error.scope}</span>
              </header>
              <div className="message__bubble message__bubble--warning">
                <p>原因：{model.error.reason}</p>
                <p>副作用状态：{model.error.sideEffectState}</p>
                <p>恢复操作：{model.error.recovery}</p>
              </div>
            </div>
          </article>
        ) : null}
      </div>

      <div className="composer" aria-label="输入与运行控制">
        <label className="composer__input">
          <textarea aria-label="追加信息" disabled={!model.appendEnabled} placeholder="输入约束、日志或复现步骤。支持图片/文件引用由 API 能力决定。" rows={3} />
        </label>
        <div className="composer__footer">
          <div className="attachment-row" aria-label="附件入口">
            <button className="icon-button" type="button">图片</button>
            <button className="icon-button" type="button">文件</button>
          </div>
          <label className="plan-toggle">
            <input checked={planMode} onChange={(event) => setPlanMode(event.currentTarget.checked)} type="checkbox" />
            <span>Plan 模式</span>
          </label>
          <ModelSelector model={selectedModel} models={model.models} runState={model.runState} onChange={setSelectedModel} />
          <div className="button-row">
            <button className="yg-button" onClick={() => onCommand({ type: "stop_run" })} type="button">
              停止
            </button>
            <button className="yg-button" onClick={() => onCommand({ type: "resume_run" })} type="button">
              恢复
            </button>
            <button className="yg-button yg-button--primary" onClick={() => onCommand({ type: "append_message" })} type="button">
              发送
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
