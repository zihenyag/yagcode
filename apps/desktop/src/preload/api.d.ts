export interface StartupConnectionView {
  baseUrl: string;
  token: string;
  origin: string;
  connected: boolean;
}

export interface YagcodeDesktopApi {
  chooseDirectory(): Promise<{ canceled: boolean; paths: readonly string[] }>;
  requestIntentWindow(intentId: string): Promise<unknown>;
  notify(notification: { title: string; body?: string }): Promise<{ ok: true }>;
  getStartupConnection(): Promise<StartupConnectionView>;
}

declare global {
  interface Window {
    yagcode?: YagcodeDesktopApi;
  }
}
