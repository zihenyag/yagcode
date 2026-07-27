import type { BrowserWindow } from "electron";
import type { SidecarController } from "./sidecar.js";

export function registerLifecycle(window: BrowserWindow, sidecar: SidecarController): void {
  let closeAllowed = false;
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
