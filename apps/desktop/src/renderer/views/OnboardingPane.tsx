import React, { useState } from "react";
import type { DemoModel, OnboardingModel, TaskModel } from "../api/adapters.js";

const steps: readonly { id: OnboardingModel["step"]; label: string }[] = [
  { id: "CREATE_AGENT", label: "Agent" },
  { id: "OPEN_FOLDER", label: "Project" },
  { id: "BIND_API", label: "API" },
  { id: "CREATE_THREAD", label: "Thread" },
  { id: "WORKBENCH", label: "Workbench" },
];

function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    openai: "OpenAI",
    qwen: "Qwen",
    glm: "GLM",
    deepseek: "DeepSeek",
    minimax: "MiniMax",
    kimi: "Kimi",
    njusehub: "NJU SE Hub",
  };
  return labels[provider] ?? provider;
}

export function OnboardingPane({
  onboarding,
  demo,
  task,
  onCommand,
}: {
  onboarding: OnboardingModel;
  demo: DemoModel;
  task: TaskModel;
  onCommand(command: { type: string; payload?: unknown }): void;
}) {
  const [agentName, setAgentName] = useState(demo.agentName ?? "我的 YagCode Agent");
  const [projectPath, setProjectPath] = useState(demo.projectPath ?? "");
  const [provider, setProvider] = useState("openai");
  const [customProviderId, setCustomProviderId] = useState("");
  const [customProviderLabel, setCustomProviderLabel] = useState("");
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [customDocsUrl, setCustomDocsUrl] = useState("");
  const [customModelId, setCustomModelId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [threadTitle, setThreadTitle] = useState("");
  const [directoryError, setDirectoryError] = useState<string | null>(null);

  async function chooseDirectory() {
    setDirectoryError(null);
    try {
      const result = await window.yagcode?.chooseDirectory?.();
      if (typeof result !== "object" || result === null) {
        setDirectoryError("桌面端目录选择器不可用；请确认正在通过 YagCode 桌面应用打开，或临时手填绝对路径。");
        return;
      }
      const record = result as { canceled?: unknown; paths?: unknown };
      if (record.canceled === true) return;
      if (Array.isArray(record.paths) && typeof record.paths[0] === "string") {
        setProjectPath(record.paths[0]);
      }
    } catch (error: unknown) {
      setDirectoryError(error instanceof Error ? error.message : "DIRECTORY_PICKER_FAILED");
    }
  }

  function submitCurrentStep() {
    if (onboarding.step === "CREATE_AGENT") {
      onCommand({ type: "create_agent", payload: { name: agentName } });
    } else if (onboarding.step === "OPEN_FOLDER") {
      onCommand({ type: "open_folder", payload: { path: projectPath } });
    } else if (onboarding.step === "BIND_API") {
      const payload =
        provider === "__custom__"
          ? {
              provider: customProviderId,
              label: customProviderLabel,
              base_url: customBaseUrl,
              docs_url: customDocsUrl,
              model_id: customModelId,
              api_key: apiKey,
            }
          : { provider, model_id: customModelId, api_key: apiKey };
      onCommand({ type: "bind_api", payload });
      setApiKey("");
    } else if (onboarding.step === "CREATE_THREAD") {
      onCommand({ type: "create_thread", payload: { title: threadTitle } });
    }
  }

  return (
    <section className="workbench-pane workbench-pane--task onboarding-pane" aria-labelledby="onboarding-heading">
      <header className="task-titlebar">
        <div>
          <p className="pane-kicker">首次配置</p>
          <h2 id="onboarding-heading">{onboarding.headline}</h2>
        </div>
        <span className="onboarding-step-badge">{steps.findIndex((step) => step.id === onboarding.step) + 1}/5</span>
      </header>

      <div className="onboarding-body">
        <ol className="onboarding-progress" aria-label="配置进度">
          {steps.map((step) => {
            const done = onboarding.completedSteps.includes(step.id);
            const active = onboarding.step === step.id;
            return (
              <li className={done ? "onboarding-progress__item onboarding-progress__item--done" : active ? "onboarding-progress__item onboarding-progress__item--active" : "onboarding-progress__item"} key={step.id}>
                <span>{done ? "✓" : active ? "●" : "○"}</span>
                {step.label}
              </li>
            );
          })}
        </ol>

        <section className="onboarding-card">
          <div className="onboarding-copy">
            <p className="pane-kicker">当前步骤</p>
            <h3>{onboarding.headline}</h3>
            <p>{onboarding.detail}</p>
          </div>

          {onboarding.step === "CREATE_AGENT" ? (
            <label className="field">
              <span>AGENT / 档案名称</span>
              <input aria-label="AGENT 名称" onChange={(event) => setAgentName(event.currentTarget.value)} value={agentName} />
            </label>
          ) : null}

          {onboarding.step === "OPEN_FOLDER" ? (
            <div className="field-stack">
              <label className="field">
                <span>项目路径</span>
                <input aria-label="项目路径" onChange={(event) => setProjectPath(event.currentTarget.value)} placeholder="/path/to/your/project" value={projectPath} />
              </label>
              <div className="button-row button-row--left">
                <button className="yg-button" onClick={chooseDirectory} type="button">
                  选择文件夹
                </button>
              </div>
              {directoryError ? <p className="inline-warning">{directoryError}</p> : null}
            </div>
          ) : null}

          {onboarding.step === "BIND_API" ? (
            <div className="field-stack">
              <label className="field">
                <span>Provider</span>
                <select aria-label="Provider" onChange={(event) => setProvider(event.currentTarget.value)} value={provider}>
                  {demo.providers.map((item) => (
                    <option key={item.provider} value={item.provider}>
                      {item.label}
                    </option>
                  ))}
                  <option value="__custom__">自定义 OpenAI-compatible Provider…</option>
                </select>
              </label>
              {provider === "__custom__" ? (
                <>
                  <label className="field">
                    <span>自定义 Provider ID</span>
                    <input aria-label="自定义 Provider ID" onChange={(event) => setCustomProviderId(event.currentTarget.value)} placeholder="my-provider" value={customProviderId} />
                  </label>
                  <label className="field">
                    <span>显示名称</span>
                    <input aria-label="自定义 Provider 显示名称" onChange={(event) => setCustomProviderLabel(event.currentTarget.value)} placeholder="My Provider" value={customProviderLabel} />
                  </label>
                  <label className="field">
                    <span>Chat Completions Base URL</span>
                    <input aria-label="自定义 Provider Base URL" onChange={(event) => setCustomBaseUrl(event.currentTarget.value)} placeholder="https://provider.example/v1/chat/completions" value={customBaseUrl} />
                  </label>
                  <label className="field">
                    <span>文档 URL</span>
                    <input aria-label="自定义 Provider 文档 URL" onChange={(event) => setCustomDocsUrl(event.currentTarget.value)} placeholder="https://provider.example/docs" value={customDocsUrl} />
                  </label>
                </>
              ) : null}
              <label className="field">
                <span>模型 ID（可选，可稍后再填）</span>
                <input aria-label="模型 ID" onChange={(event) => setCustomModelId(event.currentTarget.value)} placeholder="provider-model-id" value={customModelId} />
              </label>
              <label className="field">
                <span>API Key（不会回显）</span>
                <input aria-label="API Key" onChange={(event) => setApiKey(event.currentTarget.value)} placeholder={`${providerLabel(provider)} key`} type="password" value={apiKey} />
              </label>
              <p className="privacy-note">提交后 snapshot 只显示“已配置”和更新时间；原始 key 不进入界面、日志或测试断言。</p>
            </div>
          ) : null}

          {onboarding.step === "CREATE_THREAD" ? (
            <label className="field">
              <span>线程标题 / bug 描述</span>
              <textarea aria-label="线程标题" onChange={(event) => setThreadTitle(event.currentTarget.value)} placeholder="描述你要调试的 bug、复现步骤或目标文件" rows={4} value={threadTitle} />
            </label>
          ) : null}

          <div className="button-row">
            <button className="yg-button yg-button--primary" onClick={submitCurrentStep} type="button">
              {onboarding.step === "CREATE_AGENT" ? "创建 AGENT" : onboarding.step === "OPEN_FOLDER" ? "打开项目" : onboarding.step === "BIND_API" ? "绑定 API" : "创建线程"}
            </button>
          </div>
        </section>

        <section className="onboarding-preview" aria-label="当前受控状态">
          <h3>当前状态</h3>
          <div className="state-strip">
            <span>Agent：{demo.agentName ?? "未创建"}</span>
            <span>Project：{demo.projectPath ?? "未打开"}</span>
            <span>Git：{demo.project ? (demo.project.isGitRepo ? `${demo.project.branch ?? "无分支"} · ${demo.project.statusSummary.length} 项状态` : "非 Git 仓库") : "未检查"}</span>
            <span>Provider：{demo.providers.filter((item) => item.configured).map((item) => item.label).join(" / ") || "未绑定"}</span>
            <span>Thread：{task.threadId || "未创建"}</span>
          </div>
          {demo.providers.some((item) => item.status === "error") ? (
            <div className="inline-warning">
              {demo.providers.filter((item) => item.status === "error").map((item) => `${item.label}: ${item.detail}`).join("；")}
            </div>
          ) : null}
        </section>
      </div>
    </section>
  );
}
