import React, { useState } from "react";
import { StatusBadge } from "@yagcode/ui/desktop";
import type { LocaleMode } from "../api/client.js";
import type { TaskModel } from "../api/adapters.js";
import { uiText } from "../i18n.js";
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
  provider,
  model,
  models,
  locale = "zh-Hans",
  onChange,
}: {
  runState: string;
  provider: string;
  model: string;
  models: readonly { id: string; label: string; provider: string }[];
  locale?: LocaleMode;
  onChange?: (provider: string, model: string) => void;
}) {
  const locked = isModelLocked(runState);
  const selectedValue = modelOptionValue(provider, model);
  return (
    <label className="model-field">
      <span className="control-label">{uiText(locale, "model")}</span>
      <select
        aria-label={uiText(locale, "model")}
        disabled={locked}
        value={selectedValue}
        onChange={(event) => {
          const next = parseModelOptionValue(event.currentTarget.value);
          onChange?.(next.provider, next.model);
        }}
      >
        {models.map((candidate) => (
          <option key={modelOptionValue(candidate.provider, candidate.id)} value={modelOptionValue(candidate.provider, candidate.id)}>
            {candidate.label}
          </option>
        ))}
      </select>
      {locked ? <small>{uiText(locale, "modelSwitchLocked")}</small> : null}
    </label>
  );
}

function modelOptionValue(provider: string, model: string): string {
  return `${encodeURIComponent(provider)}::${encodeURIComponent(model)}`;
}

function parseModelOptionValue(value: string): { provider: string; model: string } {
  const [provider = "", model = ""] = value.split("::", 2);
  return { provider: decodeURIComponent(provider), model: decodeURIComponent(model) };
}

function runStateLabel(runState: string, locale: LocaleMode): string {
  const labels: Record<string, string> =
    locale === "zh-Hant"
      ? {
          IDLE: "尚未開始",
          READY: "等待輸入 / 發送後啟動",
          RUNNING: "正在請求 Provider 並執行受控 action",
          FINISHED: "已生成候選修改，查看右側 Changes",
          FAILED: "運行失敗，查看錯誤與觀察",
          STOPPED: "已停止，可切換模型",
        }
      : locale === "en-US" || locale === "en-GB"
        ? {
            IDLE: "Not started",
            READY: "Waiting for input / send to start",
            RUNNING: "Requesting provider and executing governed action",
            FINISHED: "Candidate change is ready; review Changes",
            FAILED: "Run failed; inspect the error and observations",
            STOPPED: "Stopped; model switching is available",
          }
        : {
            IDLE: "尚未开始",
            READY: "等待输入 / 发送后启动",
            RUNNING: "正在请求 Provider 并执行受控 action",
            FINISHED: "已生成候选修改，查看右侧 Changes",
            FAILED: "运行失败，查看错误与观察",
            STOPPED: "已停止，可切换模型",
          };
  return labels[runState] ?? runState;
}

function shouldRunAfterSend(runState: string): boolean {
  return runState === "IDLE" || runState === "READY" || runState === "STOPPED" || runState === "FAILED";
}

function ArrowUpIcon() {
  return (
    <svg aria-hidden="true" className="composer-icon" focusable="false" viewBox="0 0 24 24">
      <path d="M12 18V6" />
      <path d="M7 11l5-5 5 5" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg aria-hidden="true" className="composer-icon composer-icon--stop" focusable="false" viewBox="0 0 24 24">
      <rect height="8" rx="1.5" width="8" x="8" y="8" />
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg aria-hidden="true" className="attachment-icon" focusable="false" viewBox="0 0 24 24">
      <rect height="14" rx="2.5" width="16" x="4" y="5" />
      <path d="M8 15l3-3 2.5 2.5L15 13l3 3" />
      <circle cx="9" cy="9" r="1.2" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg aria-hidden="true" className="attachment-icon" focusable="false" viewBox="0 0 24 24">
      <path d="M8 4h6l4 4v12H8z" />
      <path d="M14 4v5h5" />
      <path d="M10 13h6" />
      <path d="M10 16h5" />
    </svg>
  );
}

export function TaskPane({
  model,
  locale = "zh-Hans",
  onCommand,
}: {
  model: TaskModel;
  locale?: LocaleMode;
  onCommand(command: { type: string; payload?: unknown }): void;
}) {
  const [draft, setDraft] = useState("");
  const messages =
    model.messages.length > 0
      ? model.messages
      : [
          {
            id: "fallback-agent",
            role: "assistant" as const,
            title: "本地工作台",
            body: "线程名称只作为界面元数据，不会发给模型。请在输入框发送真实任务内容；发送后会启动 Agent step。",
            at: `${model.provider} · ${model.model}`,
          },
        ];
  const runAfterSend = shouldRunAfterSend(model.runState);
  const runActive = isModelLocked(model.runState);
  const hasDraft = draft.trim().length > 0;
  const actionStopsRun = runActive && !hasDraft;
  const actionLabel = actionStopsRun ? "停止" : runActive ? "追加信息" : runAfterSend ? "发送并运行" : "发送";
  function sendDraft() {
    const text = draft.trim();
    if (text.length === 0) return;
    onCommand({ type: runAfterSend ? "send_and_resume" : "append_message", payload: { text } });
    setDraft("");
  }
  function runComposerAction() {
    if (actionStopsRun) {
      onCommand({ type: "stop_run" });
      return;
    }
    sendDraft();
  }
  return (
    <section className="workbench-pane workbench-pane--task" aria-labelledby="task-heading">
      <header className="task-titlebar">
        <div>
          <p className="pane-kicker">当前任务</p>
          <h2 id="task-heading">{model.title}</h2>
        </div>
        <StatusBadge tone={runTone(model.runState)} label={model.runState} />
      </header>

      <div className={`run-strip run-strip--${model.runState.toLowerCase()}`} aria-live="polite">
        <StatusBadge tone={runTone(model.runState)} label={runStateLabel(model.runState, locale)} />
        <span>{model.provider} · {model.model}</span>
      </div>

      <div className="conversation" role="log" aria-label="任务对话">
        {messages.map((message) => (
          <article className={`message message--${message.role}`} key={message.id}>
            <div className="message__avatar" aria-hidden="true">
              {message.role === "user" ? "你" : message.role === "assistant" ? "Y" : "!"}
            </div>
            <div className="message__content">
              <header className="message__meta">
                <span>{message.title}</span>
                <span>{message.at}</span>
              </header>
              <div className={message.role === "system" ? "message__bubble message__bubble--warning" : "message__bubble"}>
                <p>{message.body}</p>
              </div>
            </div>
          </article>
        ))}

        <article className="message message--assistant">
          <div className="message__avatar" aria-hidden="true">Y</div>
          <div className="message__content">
            <header className="message__meta">
              <span>运行约束</span>
              <span>{model.provider} · {model.model}</span>
            </header>
            <div className="message__bubble">
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
          <textarea
            aria-label="追加信息"
            disabled={!model.appendEnabled}
            onChange={(event) => setDraft(event.currentTarget.value)}
            placeholder="输入约束、日志或复现步骤。支持图片/文件引用由 API 能力决定。"
            rows={3}
            value={draft}
          />
        </label>
        <div className="composer__footer">
          <div className="attachment-row" aria-label="附件入口">
            <button aria-label="上传图片" className="icon-button icon-button--attachment" title="上传图片" type="button">
              <ImageIcon />
            </button>
            <button aria-label="上传文件" className="icon-button icon-button--attachment" title="上传文件" type="button">
              <FileIcon />
            </button>
          </div>
          <label className="plan-toggle">
            <input
              checked={model.planMode}
              onChange={(event) => onCommand({ type: "set_plan_mode", payload: { enabled: event.currentTarget.checked } })}
              type="checkbox"
            />
            <span>{uiText(locale, "planMode")}</span>
          </label>
          <ModelSelector
            locale={locale}
            provider={model.provider}
            model={model.model}
            models={model.models}
            runState={model.runState}
            onChange={(nextProvider, nextModel) => onCommand({ type: "switch_model", payload: { provider: nextProvider, model: nextModel } })}
          />
          <button
            aria-label={actionLabel}
            className={actionStopsRun ? "composer-action composer-action--stop" : "composer-action composer-action--send"}
            disabled={!actionStopsRun && (!model.appendEnabled || !hasDraft)}
            onClick={runComposerAction}
            title={actionLabel}
            type="button"
          >
            {actionStopsRun ? <StopIcon /> : <ArrowUpIcon />}
          </button>
        </div>
      </div>
    </section>
  );
}
