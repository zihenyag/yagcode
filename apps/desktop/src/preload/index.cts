import { contextBridge, ipcRenderer } from "electron";

interface NotificationView {
  title: string;
  body?: string;
}

let nextIntentRequest = 0;

function requireIntentId(intentId: unknown): string {
  if (typeof intentId !== "string" || !/^[A-Za-z0-9._:-]{1,120}$/u.test(intentId)) {
    throw new Error("INVALID_INTENT_ID");
  }
  return intentId;
}

function nextIntentRequestId(): string {
  nextIntentRequest += 1;
  return `intent-request-${nextIntentRequest}`;
}

function handleIntentPollResponse(payload: unknown, resolve: (result: unknown) => void, reject: (error: Error) => void): boolean {
  if (typeof payload !== "object" || payload === null || !("ready" in payload)) {
    reject(new Error("INTENT_RESULT_INVALID"));
    return true;
  }
  const record = payload as Record<string, unknown>;
  if (record.ready === false) return false;
  if (record.ready !== true) {
    reject(new Error("INTENT_RESULT_INVALID"));
    return true;
  }
  if (record.ok === true) {
    resolve(record.result);
    return true;
  }
  const message = typeof record.error === "string" && record.error.length > 0 ? record.error : "INTENT_FAILED";
  reject(new Error(message));
  return true;
}

function pollIntentResult(
  requestId: string,
  resolve: (result: unknown) => void,
  reject: (error: Error) => void,
  deadline: number,
): void {
  void ipcRenderer.invoke("intent:poll-result", requestId).then(
    (payload: unknown) => {
      if (handleIntentPollResponse(payload, resolve, reject)) return;
      if (Date.now() > deadline) {
        reject(new Error("INTENT_RESULT_TIMEOUT"));
        return;
      }
      window.setTimeout(() => pollIntentResult(requestId, resolve, reject, deadline), 50);
    },
    (error: unknown) => {
      reject(error instanceof Error ? error : new Error("INTENT_RESULT_FAILED"));
    },
  );
}

function requestIntentWindow(intentId: unknown): Promise<unknown> {
  const safeIntentId = requireIntentId(intentId);
  const requestId = nextIntentRequestId();
  return new Promise((resolve, reject) => {
    ipcRenderer.send("intent:open", { requestId, intentId: safeIntentId });
    pollIntentResult(requestId, resolve, reject, Date.now() + 300_000);
  });
}

function installBlockingRunEvents(): void {
  ipcRenderer.on("runs:blocking", (_event, payload: unknown) => {
    window.dispatchEvent(new CustomEvent("yagcode:blocking-runs", { detail: payload }));
  });
}

installBlockingRunEvents();
contextBridge.exposeInMainWorld(
  "yagcode",
  Object.freeze({
    chooseDirectory: () => ipcRenderer.invoke("directory:choose"),
    requestIntentWindow,
    notify: (notification: NotificationView) => ipcRenderer.invoke("notification:show", notification),
    getStartupConnection: () => ipcRenderer.invoke("sidecar:connection"),
  }),
);
