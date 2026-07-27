import React, { useState } from "react";
import { DiffSummary, EvidenceList, StatusBadge } from "@yagcode/ui/desktop";
import type { LocaleMode } from "../api/client.js";
import type { AuditModel, DemoModel, EvidenceModel, MemoryModel, SettingsModel } from "../api/adapters.js";
import { uiText } from "../i18n.js";

export interface EvidencePaneProps {
  audit: AuditModel;
  demo: DemoModel;
  memory: MemoryModel;
  model: EvidenceModel;
  settings: SettingsModel;
  locale: LocaleMode;
  onCommand(command: { type: string; payload?: unknown }): void;
  onIntent(intent: { actionId: string; highRisk: boolean }): void;
}

const panelTabs = ["审查", "Changes", "记忆", "隐私", "权限", "设置", "审计", "AGENT"] as const;

function reviewTone(state: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (state === "READY" || state === "ACCEPTED") return "success";
  if (state === "CONFLICT" || state === "RECOVERY_REQUIRED" || state === "REJECTED") return "danger";
  if (state === "INCOMPLETE" || state === "ACCEPTING") return "warning";
  return "neutral";
}

function credentialTone(status: string): "success" | "warning" | "danger" {
  if (status === "verified") return "success";
  if (status === "error") return "danger";
  return "warning";
}

function normalizePanel(panel: string): (typeof panelTabs)[number] {
  if (panel === "切换" || panel === "创建") return "AGENT";
  if (panel === "审查" || panel === "Changes" || panel === "记忆" || panel === "隐私" || panel === "权限" || panel === "设置" || panel === "审计" || panel === "AGENT") return panel;
  return "审查";
}

function lineNumber(value: number | null): string {
  return value === null ? "" : String(value);
}

function DiffPreview({ model }: { model: EvidenceModel }) {
  if (model.diffFiles.length === 0) {
    return (
      <div className="empty-state">
        <h4>暂无 Diff</h4>
        <p>创建线程后会显示候选改动。回滚或拒绝后这里会清空。</p>
      </div>
    );
  }
  return (
    <div className="diff-preview" aria-label="Diff 逐行预览">
      {model.diffFiles.map((file) => (
        <section className="diff-file" key={file.path}>
          <header className="diff-file__header">
            <span className="file-status">{file.status}</span>
            <strong>{file.path}</strong>
            <small>+{file.additions} / -{file.deletions}</small>
          </header>
          <div className="diff-lines">
            {file.lines.map((line, index) => (
              <div className={`diff-line diff-line--${line.kind}`} key={`${file.path}-${index}`}>
                <span className="diff-line__number">{lineNumber(line.oldLine)}</span>
                <span className="diff-line__number">{lineNumber(line.newLine)}</span>
                <code>{line.kind === "add" ? "+" : line.kind === "delete" ? "-" : line.kind === "hunk" ? "" : " "}{line.content}</code>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function ReviewPanel({
  model,
  demo,
  onCommand,
  onIntent,
}: {
  model: EvidenceModel;
  demo: DemoModel;
  onCommand(command: { type: string; payload?: unknown }): void;
  onIntent(intent: { actionId: string; highRisk: boolean }): void;
}) {
  return (
    <>
      <section className="inspector-section inspector-section--status" aria-labelledby="review-heading">
        <header className="inspector-header">
          <div>
            <p className="pane-kicker">Status</p>
            <h2 id="review-heading">变更审阅</h2>
          </div>
          <StatusBadge tone={reviewTone(model.review.state)} label={model.review.state} />
        </header>
        <p className="review-summary">{model.review.summary}</p>
        <dl className="status-grid" aria-label="当前 bug 状态">
          <div>
            <dt>Review</dt>
            <dd>#{model.review.reviewId}</dd>
          </div>
          <div>
            <dt>Generation</dt>
            <dd>{model.review.generation}</dd>
          </div>
        </dl>
      </section>

      <section className="inspector-section" aria-labelledby="changes-heading">
        <h3 id="changes-heading">Changes</h3>
        <DiffSummary filesChanged={model.diff.filesChanged} additions={model.diff.additions} deletions={model.diff.deletions} />
        <DiffPreview model={model} />
      </section>

      <section className="inspector-section" aria-labelledby="checkpoint-heading">
        <h3 id="checkpoint-heading">Checkpoints / 回档</h3>
        {demo.checkpoints.length === 0 ? (
          <div className="empty-state">
            <p>创建线程后会生成初始基线和候选修改 checkpoint。</p>
          </div>
        ) : (
          <ul className="checkpoint-list">
            {demo.checkpoints.map((checkpoint) => (
              <li className={checkpoint.current ? "checkpoint checkpoint--current" : "checkpoint"} key={checkpoint.id}>
                <span>{checkpoint.current ? "当前" : "可回档"}</span>
                <strong>{checkpoint.label}</strong>
                <small>{checkpoint.detail}</small>
                <button className="mini-button" onClick={() => onCommand({ type: "rollback_checkpoint", payload: { checkpoint_id: checkpoint.id } })} type="button">
                  回滚到这里
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="inspector-section" aria-labelledby="validation-heading">
        <h3 id="validation-heading">验证证据</h3>
        <EvidenceList items={model.validations} />
      </section>

      <section className="inspector-section" aria-labelledby="approval-heading">
        <h3 id="approval-heading">审阅操作</h3>
        <div className="button-row button-row--wrap button-row--left">
          {model.approvalActions.map((action) => (
            <button
              className={action.highRisk ? "yg-button yg-button--danger" : "yg-button"}
              disabled={!action.enabled}
              key={action.id}
              onClick={() => {
                if (action.highRisk) onIntent({ actionId: action.id, highRisk: true });
                else onCommand({ type: action.id });
              }}
              type="button"
            >
              {action.label}
            </button>
          ))}
          {model.approvalActions.length === 0 ? <span className="muted">完成 onboarding 后可审查候选修改。</span> : null}
        </div>
      </section>

      <section className="inspector-section" aria-labelledby="risk-heading">
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
    </>
  );
}

function MemoryPanel({ memory, onCommand }: { memory: MemoryModel; onCommand(command: { type: string; payload?: unknown }): void }) {
  const [title, setTitle] = useState("项目偏好");
  const [detail, setDetail] = useState("每个 bug 修完后先展示 diff 和验证证据。");
  return (
    <section className="inspector-section" aria-labelledby="memory-heading">
      <h3 id="memory-heading">记忆</h3>
      <div className="field-stack">
        <label className="field">
          <span>标题</span>
          <input aria-label="记忆标题" onChange={(event) => setTitle(event.currentTarget.value)} value={title} />
        </label>
        <label className="field">
          <span>内容</span>
          <textarea aria-label="记忆内容" onChange={(event) => setDetail(event.currentTarget.value)} rows={3} value={detail} />
        </label>
        <button className="yg-button" onClick={() => onCommand({ type: "add_memory", payload: { title, detail } })} type="button">
          新增项目内记忆
        </button>
      </div>
      <ul className="plain-list card-list">
        {memory.projectMemories.map((item) => (
          <li key={item.id}>
            <strong>{item.title}</strong>
            <span>{item.detail}</span>
            {item.pinned ? <em>已固定</em> : null}
            <button className="mini-button" onClick={() => onCommand({ type: "delete_memory", payload: { memory_id: item.id } })} type="button">
              删除
            </button>
          </li>
        ))}
      </ul>
      {memory.crossProjectSuggestions.length > 0 ? (
        <div className="suggestion-box">
          <h4>跨项目候选（不阻塞运行）</h4>
          {memory.crossProjectSuggestions.map((item) => (
            <p key={item.id}>{item.title}：{item.detail}</p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function PrivacyPanel({
  demo,
  settings,
  onCommand,
}: {
  demo: DemoModel;
  settings: SettingsModel;
  onCommand(command: { type: string; payload?: unknown }): void;
}) {
  return (
    <section className="inspector-section" aria-labelledby="privacy-heading">
      <header className="inspector-header">
        <h3 id="privacy-heading">隐私预览</h3>
        <StatusBadge tone={demo.privacy.previewConfirmed ? "success" : "warning"} label={demo.privacy.previewConfirmed ? "永久已确认" : "等待首次确认"} />
      </header>
      <div className="privacy-preview-list">
        {demo.privacy.previewItems.map((item) => (
          <article className={item.confirmed ? "privacy-preview privacy-preview--confirmed" : "privacy-preview"} key={item.id}>
            <span>{item.category}</span>
            <strong>{item.source}</strong>
            <p>{item.preview}</p>
          </article>
        ))}
      </div>
      <button className="yg-button yg-button--primary" disabled={demo.privacy.previewConfirmed} onClick={() => onCommand({ type: "confirm_privacy" })} type="button">
        永久确认首次隐私预览
      </button>
      <label className="field">
        <span>原始对话和工具输出保留</span>
        <select aria-label="原始对话和工具输出保留" onChange={(event) => onCommand({ type: "set_retention", payload: { retention: event.currentTarget.value } })} value={settings.selectedRetention}>
          {settings.retentionOptions.map((option) => (
            <option key={option} value={option}>
              {option === "permanent" ? "永久（默认）" : option}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}

function PermissionsPanel({ demo, onCommand }: { demo: DemoModel; onCommand(command: { type: string; payload?: unknown }): void }) {
  return (
    <section className="inspector-section" aria-labelledby="permissions-heading">
      <h3 id="permissions-heading">权限</h3>
      <div className="permission-options">
        {demo.permissions.options.map((option) => (
          <button
            className={option.active ? "permission-card permission-card--active" : "permission-card"}
            key={option.id}
            onClick={() => onCommand({ type: "set_permission_mode", payload: { mode: option.id } })}
            type="button"
          >
            <span>{option.active ? "✓ 当前" : "可选"}</span>
            <strong>{option.label}</strong>
            <small>{option.detail}</small>
          </button>
        ))}
      </div>
    </section>
  );
}

function SettingsPanel({
  settings,
  demo,
  locale,
  onCommand,
}: {
  settings: SettingsModel;
  demo: DemoModel;
  locale: LocaleMode;
  onCommand(command: { type: string; payload?: unknown }): void;
}) {
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [modelId, setModelId] = useState("");
  const [customProviderId, setCustomProviderId] = useState("");
  const [customProviderLabel, setCustomProviderLabel] = useState("");
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [customDocsUrl, setCustomDocsUrl] = useState("");
  return (
    <section className="inspector-section" aria-labelledby="settings-heading">
      <h3 id="settings-heading">{uiText(locale, "settingsApi")}</h3>
      <div className="settings-grid">
        {settings.credentialStatuses.map((credential) => (
          <div className="settings-row" key={credential.provider}>
            <span>{credential.provider}</span>
            <StatusBadge tone={credentialTone(credential.status)} label={credential.status === "verified" ? "已校验" : credential.status === "missing" ? "缺失" : "异常"} />
            <small>{credential.updatedAt ?? "未更新"}</small>
            <small>{credential.detail}</small>
            <a className="mini-link" href={credential.docsUrl} rel="noreferrer" target="_blank">文档</a>
            <button className="mini-button" disabled={credential.status !== "verified"} onClick={() => onCommand({ type: "delete_api", payload: { provider: credential.provider } })} type="button">
              删除
            </button>
          </div>
        ))}
      </div>
      <div className="field-stack">
        <label className="field">
          <span>{uiText(locale, "theme")}</span>
          <select aria-label={uiText(locale, "theme")} onChange={(event) => onCommand({ type: "set_theme_mode", payload: { mode: event.currentTarget.value } })} value={settings.themeMode}>
            {settings.themeOptions.map((option) => (
              <option key={option.id} value={option.id}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{uiText(locale, "language")}</span>
          <select aria-label={uiText(locale, "language")} onChange={(event) => onCommand({ type: "set_locale", payload: { locale: event.currentTarget.value } })} value={settings.locale}>
            {settings.localeOptions.map((option) => (
              <option key={option.id} value={option.id}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{uiText(locale, "provider")}</span>
          <select aria-label="绑定 Provider" onChange={(event) => setProvider(event.currentTarget.value)} value={provider}>
            {demo.providers.map((item) => (
              <option key={item.provider} value={item.provider}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{uiText(locale, "modelIdOptional")}</span>
          <input aria-label={uiText(locale, "modelIdOptional")} onChange={(event) => setModelId(event.currentTarget.value)} placeholder="provider-model-id" value={modelId} />
        </label>
        <label className="field">
          <span>{uiText(locale, "apiKey")}</span>
          <input aria-label={uiText(locale, "apiKey")} onChange={(event) => setApiKey(event.currentTarget.value)} type="password" value={apiKey} />
        </label>
        <button
          className="yg-button"
          onClick={() => {
            onCommand({ type: "bind_api", payload: { provider, model_id: modelId, api_key: apiKey } });
            setApiKey("");
          }}
          type="button"
        >
          {uiText(locale, "updateBinding")}
        </button>
        <button className="yg-button" onClick={() => onCommand({ type: "add_custom_model", payload: { provider, model: modelId } })} type="button">
          {uiText(locale, "addModelOnly")}
        </button>
      </div>
      <div className="field-stack custom-provider-box">
        <h4>{uiText(locale, "customProvider")}</h4>
        <label className="field">
          <span>{uiText(locale, "providerId")}</span>
          <input aria-label="设置页自定义 Provider ID" onChange={(event) => setCustomProviderId(event.currentTarget.value)} placeholder="my-provider" value={customProviderId} />
        </label>
        <label className="field">
          <span>{uiText(locale, "displayName")}</span>
          <input aria-label="设置页自定义 Provider 显示名称" onChange={(event) => setCustomProviderLabel(event.currentTarget.value)} placeholder="My Provider" value={customProviderLabel} />
        </label>
        <label className="field">
          <span>{uiText(locale, "chatCompletionsUrl")}</span>
          <input aria-label="设置页自定义 Provider Base URL" onChange={(event) => setCustomBaseUrl(event.currentTarget.value)} placeholder="https://provider.example/v1/chat/completions" value={customBaseUrl} />
        </label>
        <label className="field">
          <span>{uiText(locale, "docsUrl")}</span>
          <input aria-label="设置页自定义 Provider 文档 URL" onChange={(event) => setCustomDocsUrl(event.currentTarget.value)} placeholder="https://provider.example/docs" value={customDocsUrl} />
        </label>
        <label className="field">
          <span>{uiText(locale, "defaultModelId")}</span>
          <input aria-label="设置页自定义模型 ID" onChange={(event) => setModelId(event.currentTarget.value)} placeholder="my-model" value={modelId} />
        </label>
        <button
          className="yg-button"
          onClick={() =>
            onCommand({
              type: "add_custom_provider",
              payload: {
                provider: customProviderId,
                label: customProviderLabel,
                base_url: customBaseUrl,
                docs_url: customDocsUrl,
                model_id: modelId,
              },
            })
          }
          type="button"
        >
          {uiText(locale, "addCustomProviderModel")}
        </button>
      </div>
    </section>
  );
}

function AuditPanel({ audit }: { audit: AuditModel }) {
  return (
    <section className="inspector-section" aria-labelledby="audit-heading">
      <h3 id="audit-heading">审计</h3>
      {audit.entries.length === 0 ? (
        <div className="empty-state">
          <p>还没有审计记录。每个命令会留下本地工作台审计。</p>
        </div>
      ) : (
        <ol className="audit-list">
          {audit.entries.map((entry) => (
            <li key={entry.id}>
              <time dateTime={entry.at}>{entry.at}</time>
              <strong>{entry.title}</strong>
              <span>{entry.detail}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function AgentPanel({ demo, onCommand }: { demo: DemoModel; onCommand(command: { type: string; payload?: unknown }): void }) {
  const [agentName, setAgentName] = useState(demo.agentName ?? "新的 Agent");
  const [projectPath, setProjectPath] = useState(demo.projectPath ?? "");
  const [threadTitle, setThreadTitle] = useState("新线程：修复另一个 bug");
  return (
    <section className="inspector-section" aria-labelledby="agent-heading">
      <h3 id="agent-heading">AGENT / 项目 / 线程</h3>
      <div className="identity-card">
        <span>当前 Agent</span>
        <strong>{demo.agentName ?? "未创建"}</strong>
        <small>{demo.projectPath ?? "未打开项目"}</small>
        {demo.project ? (
          <small>
            {demo.project.isGitRepo ? `Git · ${demo.project.branch ?? "无分支"} · ${demo.project.statusSummary.length} 项状态` : "非 Git 仓库"}
          </small>
        ) : null}
      </div>
      <div className="field-stack">
        <label className="field">
          <span>创建/切换 Agent</span>
          <input aria-label="新 AGENT 名称" onChange={(event) => setAgentName(event.currentTarget.value)} value={agentName} />
        </label>
        <div className="button-row button-row--left">
          <button className="yg-button" onClick={() => onCommand({ type: "create_agent", payload: { name: agentName } })} type="button">
            创建/切换
          </button>
          <button className="yg-button" onClick={() => onCommand({ type: "delete_agent" })} type="button">
            删除当前 Agent
          </button>
        </div>
        <label className="field">
          <span>打开项目</span>
          <input aria-label="新的项目路径" onChange={(event) => setProjectPath(event.currentTarget.value)} value={projectPath} />
        </label>
        <div className="button-row button-row--left">
          <button className="yg-button" onClick={() => onCommand({ type: "open_folder", payload: { path: projectPath } })} type="button">
            打开/切换项目
          </button>
          <button className="yg-button" onClick={() => onCommand({ type: "delete_project" })} type="button">
            关闭项目
          </button>
        </div>
        <label className="field">
          <span>新线程</span>
          <input aria-label="新线程标题" onChange={(event) => setThreadTitle(event.currentTarget.value)} value={threadTitle} />
        </label>
        <div className="button-row button-row--left">
          <button className="yg-button" onClick={() => onCommand({ type: "create_thread", payload: { title: threadTitle } })} type="button">
            创建线程
          </button>
          <button className="yg-button" onClick={() => onCommand({ type: "delete_thread" })} type="button">
            删除当前线程
          </button>
        </div>
      </div>
    </section>
  );
}

export function EvidencePane({ audit, demo, memory, model, settings, locale, onCommand, onIntent }: EvidencePaneProps) {
  const selectedPanel = normalizePanel(demo.selectedPanel);
  return (
    <aside className="workbench-pane workbench-pane--evidence" aria-label="状态、变更与配置">
      <nav className="inspector-tabs" aria-label="右侧面板">
        {panelTabs.map((panel) => (
          <button
            className={selectedPanel === panel ? "inspector-tab inspector-tab--active" : "inspector-tab"}
            key={panel}
            onClick={() => onCommand({ type: "open_panel", payload: { panel } })}
            type="button"
          >
            {panel}
          </button>
        ))}
      </nav>

      {selectedPanel === "审查" ? <ReviewPanel demo={demo} model={model} onCommand={onCommand} onIntent={onIntent} /> : null}
      {selectedPanel === "Changes" ? (
        <section className="inspector-section" aria-labelledby="changes-only-heading">
          <h3 id="changes-only-heading">Changes / Diff 预览</h3>
          <DiffSummary filesChanged={model.diff.filesChanged} additions={model.diff.additions} deletions={model.diff.deletions} />
          <DiffPreview model={model} />
        </section>
      ) : null}
      {selectedPanel === "记忆" ? <MemoryPanel memory={memory} onCommand={onCommand} /> : null}
      {selectedPanel === "隐私" ? <PrivacyPanel demo={demo} settings={settings} onCommand={onCommand} /> : null}
      {selectedPanel === "权限" ? <PermissionsPanel demo={demo} onCommand={onCommand} /> : null}
      {selectedPanel === "设置" ? <SettingsPanel demo={demo} locale={locale} settings={settings} onCommand={onCommand} /> : null}
      {selectedPanel === "审计" ? <AuditPanel audit={audit} /> : null}
      {selectedPanel === "AGENT" ? <AgentPanel demo={demo} onCommand={onCommand} /> : null}
    </aside>
  );
}
