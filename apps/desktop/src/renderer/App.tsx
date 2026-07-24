import React, { useEffect, useState } from "react";
import "@yagcode/ui/tokens.css";
import "./styles.css";
import type { SidecarClient, WorkbenchCommand } from "./api/client.js";
import { adaptSnapshot, type WorkbenchModel } from "./api/adapters.js";
import { createInitialWorkbenchState, reduceEvent } from "./state/reducer.js";
import { NavigationPane } from "./views/NavigationPane.js";
import { TaskPane } from "./views/TaskPane.js";
import { EvidencePane } from "./views/EvidencePane.js";
import { SettingsView } from "./views/SettingsView.js";
import { MemoryView } from "./views/MemoryView.js";
import { AuditView } from "./views/AuditView.js";

interface YagcodeRendererApi {
  requestIntentWindow?(intent: { actionId: string; highRisk: boolean }): void;
}

declare global {
  interface Window {
    yagcode?: YagcodeRendererApi;
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

export function App({ client }: { client: SidecarClient }) {
  const [model, setModel] = useState<WorkbenchModel | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

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

  function command(commandValue: WorkbenchCommand) {
    void client.command(commandValue);
  }

  function requestIntent(intent: { actionId: string; highRisk: boolean }) {
    if (intent.highRisk) window.yagcode?.requestIntentWindow?.(intent);
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
    <main className="workbench" data-connection={model.connection}>
      <NavigationPane model={model.navigation} />
      <TaskPane model={model.task} onCommand={command} />
      <div className="right-column">
        <EvidencePane model={model.evidence} onIntent={requestIntent} />
        <SettingsView model={model.settings} />
        <MemoryView model={model.memory} />
        <AuditView model={model.audit} />
      </div>
    </main>
  );
}
