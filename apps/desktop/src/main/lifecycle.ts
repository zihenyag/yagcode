import type { BrowserWindow } from "electron";
import type { SidecarController } from "./sidecar.js";

let closeAllowed = false;

export function registerLifecycle(window: BrowserWindow, sidecar: SidecarController): void {
  window.on("close", (event) => {
    if (closeAllowed) return;
    event.preventDefault();
    void (async () => {
      const blockingRuns = await sidecar.getBlockingRuns();
      if (blockingRuns.length > 0) {
        window.show();
        window.focus();
        window.webContents.send("runs:blocking", { runs: blockingRuns });
        return;
      }
      closeAllowed = true;
      await sidecar.stop();
      window.close();
    })();
  });
}
