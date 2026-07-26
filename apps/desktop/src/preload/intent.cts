import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld(
  "yagcodeIntent",
  Object.freeze({
    confirm: () => ipcRenderer.send("intent:confirm"),
    cancel: () => ipcRenderer.send("intent:cancel"),
  }),
);
