import React, { useEffect, useState } from "react";
import "@yagcode/ui/tokens.css";
import "./styles.css";
import type { SidecarClient, WorkbenchCommand } from "./api/client.js";
import { adaptSnapshot, type WorkbenchModel } from "./api/adapters.js";
import { createInitialWorkbenchState, reduceEvent } from "./state/reducer.js";
import { NavigationPane } from "./views/NavigationPane.js";
import { TaskPane } from "./views/TaskPane.js";
import { EvidencePane } from "./views/EvidencePane.js";
import { OnboardingPane } from "./views/OnboardingPane.js";

declare global {
  interface Window {
    yagcode?: {
      chooseDirectory?(): Promise<unknown>;
      getStartupConnection?(): Promise<unknown>;
      notify?(notification: unknown): Promise<unknown>;
      requestIntentWindow?(intentId: string): Promise<unknown>;
    };
  }
}

function applyEventToModel(model: WorkbenchModel, event: unknown): WorkbenchModel {
  const state = createInitialWorkbenchState({
    generation: model.generation,
    lastSequence: model.lastSequence,
    runState: model.task.runState,
  });
  const reduced = reduceEvent(state, event);
  return {
    ...model,
    connection: reduced.connection,
    generation: reduced.generation,
    lastSequence: reduced.lastSequence,
    navigation: {
      ...model.navigation,
      runState: reduced.runState,
    },
    task: {
      ...model.task,
      runState: reduced.runState,
    },
  };
}

function commandPayloadText(commandValue: WorkbenchCommand): string {
  const payload = commandValue.payload;
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return "";
  const text = (payload as Record<string, unknown>).text;
  return typeof text === "string" ? text.trim() : "";
}

export function App({ client }: { client: SidecarClient }) {
  const [model, setModel] = useState<WorkbenchModel | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [blockingRuns, setBlockingRuns] = useState<readonly { id: string; state: string; title?: string }[]>([]);

  async function refreshSnapshot(): Promise<void> {
    const snapshot = await client.getSnapshot();
    setModel(adaptSnapshot(snapshot));
    setLoadError(null);
  }

  function showCommandError(reason: string) {
    setModel((current) =>
      current === null
        ? current
        : {
            ...current,
            task: {
              ...current.task,
              error: {
                reason,
                sideEffectState: "命令未执行",
                scope: "当前线程",
                recovery: "查看状态后重新选择可用操作",
              },
            },
          },
    );
  }

  function showOptimisticRunning() {
    setModel((current) => {
      if (current === null) return current;
      const { error: _error, ...taskWithoutError } = current.task;
      return {
        ...current,
        navigation: {
          ...current.navigation,
          runState: "RUNNING",
        },
        task: {
          ...taskWithoutError,
          runState: "RUNNING",
        },
      };
    });
  }

  useEffect(() => {
    let active = true;
    let subscription: { close(): void } | undefined;
    void client
      .getSnapshot()
      .then((snapshot) => {
        if (!active) return;
        const adapted = adaptSnapshot(snapshot);
        setModel(adapted);
        subscription = client.subscribe({
          profileId: adapted.profileId,
          lastSequence: adapted.lastSequence,
          onEvent(event) {
            setModel((current) => (current === null ? current : applyEventToModel(current, event)));
          },
          onDisconnect(reason) {
            setModel((current) =>
              current === null
                ? current
                : {
                    ...current,
                    connection: "disconnected",
                    task: {
                      ...current.task,
                      error: {
                        reason,
                        sideEffectState: "新 action 已阻止",
                        scope: "当前线程",
                        recovery: "重新同步完整状态后再提交操作",
                      },
                    },
                  },
            );
          },
        });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setLoadError(error instanceof Error ? error.message : "WORKBENCH_LOAD_FAILED");
      });
    return () => {
      active = false;
      subscription?.close();
    };
  }, [client]);

  useEffect(() => {
    function onBlockingRuns(event: Event) {
      const detail = (event as CustomEvent<unknown>).detail;
      if (typeof detail !== "object" || detail === null || !("runs" in detail) || !Array.isArray(detail.runs)) return;
      setBlockingRuns(
        detail.runs.filter((run: unknown): run is { id: string; state: string; title?: string } => {
          if (typeof run !== "object" || run === null) return false;
          const record = run as Record<string, unknown>;
          return typeof record.id === "string" && typeof record.state === "string";
        }),
      );
    }
    window.addEventListener("yagcode:blocking-runs", onBlockingRuns);
    return () => window.removeEventListener("yagcode:blocking-runs", onBlockingRuns);
  }, []);

  useEffect(() => {
    if (model === null) return;
    document.documentElement.dataset.themeMode = model.settings.themeMode;
    document.documentElement.lang = model.settings.locale;
  }, [model]);

  async function runCommand(commandValue: WorkbenchCommand, options: { optimisticRun?: boolean } = {}): Promise<boolean> {
    if (options.optimisticRun === true) showOptimisticRunning();
    try {
      const result = await client.command(commandValue);
      if (!result.ok) {
        await refreshSnapshot();
        showCommandError(result.reason);
        return false;
      }
      await refreshSnapshot();
      return true;
    } catch (error: unknown) {
      showCommandError(error instanceof Error ? error.message : "COMMAND_FAILED");
      return false;
    }
  }

  async function sendAndResume(commandValue: WorkbenchCommand): Promise<void> {
    const text = commandPayloadText(commandValue);
    if (text.length === 0) {
      showCommandError("APPEND_MESSAGE_EMPTY");
      return;
    }
    const appended = await runCommand({ type: "append_message", payload: { text } });
    if (!appended) return;
    await runCommand({ type: "resume_run" }, { optimisticRun: true });
  }

  function command(commandValue: WorkbenchCommand) {
    if (commandValue.type === "send_and_resume") {
      void sendAndResume(commandValue);
      return;
    }
    void runCommand(commandValue, { optimisticRun: commandValue.type === "resume_run" });
  }

  function requestIntent(intent: { actionId: string; highRisk: boolean }) {
    if (intent.highRisk) {
      void window.yagcode?.requestIntentWindow?.(intent.actionId).then(
        () => refreshSnapshot(),
        (error: unknown) => showCommandError(error instanceof Error ? error.message : "INTENT_FAILED"),
      );
    }
    else command({ type: "review_intent", payload: intent });
  }

  if (loadError !== null) {
    return (
      <main className="workbench workbench--center" role="alert">
        <section className="error-card">
          <h1>无法连接 sidecar</h1>
          <p>原因：{loadError}</p>
          <p>副作用状态：未提交新 action。</p>
          <p>恢复操作：确认本地 sidecar 已启动并重新打开工作台。</p>
        </section>
      </main>
    );
  }

  if (model === null) {
    return (
      <main className="workbench workbench--center" aria-busy="true">
        <p className="loading">正在连接本地 sidecar…</p>
      </main>
    );
  }

  return (
    <main
      className="workbench"
      data-connection={model.connection}
      data-locale={model.settings.locale}
      data-theme-mode={model.settings.themeMode}
    >
      <NavigationPane model={model.navigation} onCommand={command} />
      {model.onboarding.step === "WORKBENCH" ? (
        <TaskPane locale={model.settings.locale} model={model.task} onCommand={command} />
      ) : (
        <OnboardingPane onboarding={model.onboarding} demo={model.demo} task={model.task} onCommand={command} />
      )}
      <div className="right-column">
        {blockingRuns.length > 0 ? (
          <section className="blocking-card" aria-labelledby="blocking-runs-heading" tabIndex={-1}>
            <h2 id="blocking-runs-heading">运行中的任务</h2>
            <p>存在活动或已中断 Run，关闭前需要先手动停止。</p>
            <ul>
              {blockingRuns.map((run) => (
                <li key={run.id}>
                  {run.id} · {run.state}
                  {run.title ? ` · ${run.title}` : ""}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <EvidencePane
          audit={model.audit}
          demo={model.demo}
          locale={model.settings.locale}
          memory={model.memory}
          model={model.evidence}
          onCommand={command}
          onIntent={requestIntent}
          settings={model.settings}
        />
      </div>
    </main>
  );
}
