import type { EngineSnapshot, EngineStatus, Host, RefreshOptions } from "@cursor-usage/core";

export interface AppInfo {
  version: string;
  dataDir: string;
  platform: string;
  update: { version: string; url: string; name: string } | null;
  hasManualCredentials: boolean;
  hasRefreshToken: boolean;
  manualEmail: string;
  tokenPreview: string;
}

export interface ComponentStatus {
  ball: { running: boolean };
  taskbarWidget: { state?: string; reason?: string; visible?: boolean };
}

export type SettingsMap = Record<string, any>;

/** Which optional features a host provides; the UI hides the rest. */
export interface Capabilities {
  desktopWidgets: boolean;
  autostart: boolean;
  updates: boolean;
  localTokenRefresh: boolean;
  diagnostics: boolean;
}

/** Host features beyond the core: settings UI, exports, desktop components. */
export interface AppApi {
  loadSettings(): Promise<SettingsMap>;
  saveSettings(patch: SettingsMap): Promise<SettingsMap>;
  saveCredentials(patch: { accessToken?: string; refreshToken?: string; email?: string }): Promise<void>;
  clearCredentials(): Promise<SettingsMap>;
  appInfo(): Promise<AppInfo>;
  componentStatus(): Promise<ComponentStatus>;
  reembedDock(): Promise<void>;
  exportFile(name: string, extension: "csv" | "json", content: string): Promise<string>;
  exportDiagnostics(): Promise<string>;
  openUrl(url: string): Promise<void>;
  log(level: "debug" | "info" | "warning" | "error", message: string): Promise<void>;
  capabilities: Capabilities;
}

/** What the UI needs from the engine; satisfied by UsageEngine and RemoteEngine. */
export interface EngineApi {
  snapshot(): EngineSnapshot;
  subscribe(listener: (snapshot: EngineSnapshot) => void): () => void;
  refresh(options?: RefreshOptions): Promise<EngineStatus | unknown>;
}

// ---- Desktop (pywebview) -----------------------------------------------

type PyApi = Record<string, (...args: any[]) => Promise<any>>;

declare global {
  interface Window {
    pywebview?: { api: PyApi };
    acquireVsCodeApi?: () => { postMessage(message: unknown): void; getState(): unknown; setState(state: unknown): void };
  }
}

function waitForPywebview(timeoutMs = 10_000): Promise<PyApi> {
  return new Promise((resolve, reject) => {
    if (window.pywebview?.api?.http) return resolve(window.pywebview.api);
    const timer = setTimeout(() => reject(new Error("pywebview bridge unavailable")), timeoutMs);
    window.addEventListener(
      "pywebviewready",
      () => {
        clearTimeout(timer);
        resolve(window.pywebview!.api);
      },
      { once: true },
    );
  });
}

export function hasPywebview(): boolean {
  return typeof window !== "undefined" && ("pywebview" in window || navigator.userAgent.includes("pywebview"));
}

export function hasVsCode(): boolean {
  return typeof window !== "undefined" && typeof window.acquireVsCodeApi === "function";
}

/** Desktop app: every call goes to cursor_usage_app/bridge.py. */
export async function createDesktopHost(): Promise<{ host: Host; api: AppApi }> {
  const py = await waitForPywebview();
  const host: Host = {
    http: (req) => py.http(req),
    envToken: () => py.envToken(),
    readLocalAuth: () => py.readLocalAuth(),
    writeLocalAuth: (patch) => py.writeLocalAuth(patch),
    getCredentials: () => py.getCredentials(),
    saveCredentials: (patch) => py.saveCredentials(patch),
    loadSettings: () => py.loadSettings(),
    loadState: () => py.loadState(),
    saveReport: (report, summary) => py.saveReport(report, summary),
    saveHistory: (cycles) => py.saveHistory(cycles),
    saveAlertsState: (state) => py.saveAlertsState(state),
    notify: (title, message) => py.notify(title, message),
  };
  const api: AppApi = {
    loadSettings: () => py.loadSettings(),
    saveSettings: (patch) => py.saveSettings(patch),
    saveCredentials: (patch) => py.saveCredentials(patch),
    clearCredentials: () => py.clearCredentials(),
    appInfo: () => py.appInfo(),
    componentStatus: () => py.componentStatus(),
    reembedDock: () => py.reembedDock(),
    exportFile: (name, extension, content) => py.exportFile(name, extension, content),
    exportDiagnostics: () => py.exportDiagnostics(),
    openUrl: (url) => py.openUrl(url),
    log: (level, message) => py.log(level, message),
    capabilities: { desktopWidgets: true, autostart: true, updates: true, localTokenRefresh: true, diagnostics: true },
  };
  return { host, api };
}

// ---- Cursor / VS Code webview ---------------------------------------------

/** Messages between the webview and packages/extension (see its router.ts). */
export type ToHost = { type: "request"; id: number; method: string; args: unknown[] } | { type: "ready" };
export type FromHost =
  | { type: "response"; id: number; ok: true; result: unknown }
  | { type: "response"; id: number; ok: false; error: string }
  | { type: "snapshot"; snapshot: EngineSnapshot }
  | { type: "settingsChanged" };

const EMPTY_STATUS: EngineStatus = {
  state: "idle",
  runningFull: false,
  lastError: null,
  lastSuccessAt: null,
  consecutiveFailures: 0,
  retryAt: null,
};

/** Mirrors the engine running in the extension host; snapshots arrive by postMessage. */
export class RemoteEngine implements EngineApi {
  private current: EngineSnapshot = { report: null, history: [], status: EMPTY_STATUS };
  private readonly listeners = new Set<(s: EngineSnapshot) => void>();

  constructor(private readonly call: (method: string, ...args: unknown[]) => Promise<any>) {}

  receive(snapshot: EngineSnapshot): void {
    this.current = snapshot;
    this.listeners.forEach((fn) => fn(snapshot));
  }

  snapshot(): EngineSnapshot {
    return this.current;
  }

  subscribe(listener: (s: EngineSnapshot) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  refresh(options?: RefreshOptions): Promise<unknown> {
    return this.call("refresh", options ?? {});
  }
}

export function createVsCodeHost(onSettingsChanged: () => void): { engine: RemoteEngine; api: AppApi } {
  const vscode = window.acquireVsCodeApi!();
  let nextId = 1;
  const pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();
  const call = (method: string, ...args: unknown[]) =>
    new Promise<any>((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      vscode.postMessage({ type: "request", id, method, args } satisfies ToHost);
    });
  const engine = new RemoteEngine(call);

  window.addEventListener("message", (event: MessageEvent<FromHost>) => {
    const msg = event.data;
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "snapshot") engine.receive(msg.snapshot);
    else if (msg.type === "settingsChanged") onSettingsChanged();
    else if (msg.type === "response") {
      const waiter = pending.get(msg.id);
      if (!waiter) return;
      pending.delete(msg.id);
      if (msg.ok) waiter.resolve(msg.result);
      else waiter.reject(new Error(msg.error));
    }
  });

  const api: AppApi = {
    loadSettings: () => call("loadSettings"),
    saveSettings: (patch) => call("saveSettings", patch),
    saveCredentials: (patch) => call("saveCredentials", patch),
    clearCredentials: () => call("clearCredentials"),
    appInfo: () => call("appInfo"),
    componentStatus: async () => ({ ball: { running: false }, taskbarWidget: {} }),
    reembedDock: async () => {},
    exportFile: (name, extension, content) => call("exportFile", name, extension, content),
    exportDiagnostics: async () => "",
    openUrl: (url) => call("openUrl", url),
    log: (level, message) => call("log", level, message),
    capabilities: { desktopWidgets: false, autostart: false, updates: false, localTokenRefresh: false, diagnostics: false },
  };
  vscode.postMessage({ type: "ready" } satisfies ToHost);
  return { engine, api };
}
