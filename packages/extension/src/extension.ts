import {
  L,
  normalizeLangPref,
  resolveLang,
  setLang,
  UsageEngine,
  widgetSummary,
  type EngineSnapshot,
  type Host,
  type HttpRequest,
  type Settings,
  type WidgetSummary,
} from "@cursor-usage/core";
import { randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import * as vscode from "vscode";
import { clearCredentials, createNodeHost, credentialsInfo, type JsonStore } from "./nodeHost";
import { dashboardHtml, statusView, summaryText, type StatusBarMode } from "./present";
import { route, type ExtensionFacade } from "./router";

const CONFIG = "cursorUsage";
/** Settings that live in VS Code configuration; everything else is UI state in globalState. */
const CONFIG_KEYS: Record<string, string> = {
  refreshSeconds: "refreshSeconds",
  alertsEnabled: "alerts.enabled",
  alertThresholds: "alerts.thresholds",
  onDemandBudget: "onDemandBudget",
  language: "language",
};

function jsonStore(dir: string): JsonStore {
  return {
    async read<T>(name: string) {
      try {
        return JSON.parse(await readFile(join(dir, `${name}.json`), "utf8")) as T;
      } catch {
        return null;
      }
    },
    async write(name: string, value: unknown) {
      await mkdir(dir, { recursive: true });
      await writeFile(join(dir, `${name}.json`), JSON.stringify(value), "utf8");
    },
  };
}

/** Log every Host call with its duration (trace level; visible with "Developer: Set Log Level"). */
function traced(host: Host, log: vscode.LogOutputChannel): Host {
  const out = {} as Host;
  for (const key of Object.keys(host) as (keyof Host)[]) {
    const fn = host[key] as (...args: unknown[]) => Promise<unknown>;
    (out as any)[key] = async (...args: unknown[]) => {
      const started = Date.now();
      const label = key === "http" ? `http ${new URL((args[0] as HttpRequest).url).pathname}` : key;
      try {
        const result = await fn(...args);
        log.trace(`${label} ok ${Date.now() - started}ms${key === "http" ? ` status ${(result as { status: number }).status}` : ""}`);
        return result;
      } catch (error) {
        log.warn(`${label} failed after ${Date.now() - started}ms: ${(error as Error)?.message}`);
        throw error;
      }
    };
  }
  return out;
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const log = vscode.window.createOutputChannel("Cursor Usage", { log: true });
  const storageDir = context.globalStorageUri.fsPath;
  const store = jsonStore(storageDir);
  const config = () => vscode.workspace.getConfiguration(CONFIG);
  const uiState = () => context.globalState.get<Record<string, unknown>>("ui", {});

  const settings = (): Settings => {
    const c = config();
    return {
      ...uiState(),
      authSource: (uiState().authSource as Settings["authSource"]) || "auto",
      persistLocalRefresh: false,
      refreshSeconds: c.get<number>("refreshSeconds", 120),
      alertsEnabled: c.get<boolean>("alerts.enabled", true),
      alertThresholds: c.get<number[]>("alerts.thresholds", [80, 95]),
      onDemandBudget: c.get<number>("onDemandBudget", 0),
      language: normalizeLangPref(c.get<string>("language", "auto")),
    };
  };
  // "auto" follows Cursor's display language (vscode.env.language, e.g. "zh-cn" / "en").
  const applyLanguage = () => setLang(resolveLang(config().get<string>("language", "auto"), vscode.env.language));
  applyLanguage();

  let panel: vscode.WebviewPanel | undefined;
  const statusItem = vscode.window.createStatusBarItem("cursorUsage.status", vscode.StatusBarAlignment.Right, 100);
  statusItem.name = "Cursor Usage";
  statusItem.command = "cursorUsage.openDashboard";
  let lastSummary: WidgetSummary | null = null;

  const host = createNodeHost({
    store,
    secrets: context.secrets,
    settings,
    stateDbOverride: () => config().get<string>("stateDbPath", ""),
    globalStorageDir: storageDir,
    // showWarningMessage resolves only when the user reacts; never make the refresh wait for it.
    notify: async (title, message) => {
      void Promise.resolve(vscode.window.showWarningMessage(`${title}${L("：", ": ")}${message}`, L("打开看板", "Open dashboard"))).then((choice) => {
        if (choice) void vscode.commands.executeCommand("cursorUsage.openDashboard");
      });
    },
    onReport: (_report, summary) => {
      lastSummary = summary;
    },
  });
  const engine = new UsageEngine(traced(host, log), { warn: (m) => log.warn(m) });

  const renderStatus = (snap: EngineSnapshot) => {
    const mode = config().get<StatusBarMode>("statusBar", "auto");
    if (mode === "hidden") return statusItem.hide();
    const summary = lastSummary ?? (snap.report ? widgetSummary(snap.report) : null);
    const view = statusView(summary, snap.status, mode, config().get<number[]>("alerts.thresholds", [80, 95]));
    statusItem.text = view.text;
    statusItem.tooltip = new vscode.MarkdownString(view.tooltip);
    statusItem.backgroundColor =
      view.level === "danger" ? new vscode.ThemeColor("statusBarItem.errorBackground") : view.level === "warn" ? new vscode.ThemeColor("statusBarItem.warningBackground") : undefined;
    statusItem.show();
  };

  let lastState = "";
  engine.subscribe((snap) => {
    renderStatus(snap);
    void panel?.webview.postMessage({ type: "snapshot", snapshot: snap });
    const state = `${snap.status.state}${snap.status.runningFull ? " (full)" : ""}`;
    if (state !== lastState) {
      lastState = state;
      if (snap.status.state === "error") log.warn(`refresh failed: ${snap.status.lastError}`);
      else log.info(`refresh ${state}`);
    }
  });

  const facade: ExtensionFacade = {
    refresh: (options) => engine.refresh(options),
    loadSettings: async () => settings(),
    saveSettings: async (patch) => {
      const ui = { ...uiState() };
      for (const [key, value] of Object.entries(patch)) {
        if (key in CONFIG_KEYS) await config().update(CONFIG_KEYS[key], value, vscode.ConfigurationTarget.Global);
        else ui[key] = value;
      }
      await context.globalState.update("ui", ui);
      return settings();
    },
    saveCredentials: async (patch) => {
      await host.saveCredentials(patch as Record<string, string>);
    },
    clearCredentials: async () => {
      await clearCredentials(context.secrets);
      await context.globalState.update("ui", { ...uiState(), authSource: "auto" });
      return settings();
    },
    appInfo: async () => ({
      version: String(context.extension.packageJSON.version),
      dataDir: storageDir,
      platform: `cursor-extension/${process.platform}`,
      update: null,
      ...(await credentialsInfo(context.secrets)),
    }),
    exportFile: async (name, extension, content) => {
      const target = await vscode.window.showSaveDialog({
        defaultUri: vscode.Uri.file(join(storageDir, `${name}.${extension}`)),
        filters: extension === "csv" ? { CSV: ["csv"] } : { JSON: ["json"] },
      });
      if (!target) return L("已取消", "Cancelled");
      const body = extension === "csv" ? `\ufeff${content}` : content;
      await vscode.workspace.fs.writeFile(target, new TextEncoder().encode(body));
      return target.fsPath;
    },
    openUrl: async (url) => {
      const uri = vscode.Uri.parse(url);
      if (uri.scheme === "https") await vscode.env.openExternal(uri);
    },
    log: async (level, message) => {
      if (level === "error") log.error(message);
      else if (level === "warning") log.warn(message);
      else log.info(message);
    },
  };

  const openDashboard = () => {
    if (panel) return panel.reveal();
    panel = vscode.window.createWebviewPanel("cursorUsage.dashboard", L("Cursor 用量", "Cursor Usage"), vscode.ViewColumn.Active, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [],
    });
    panel.iconPath = vscode.Uri.joinPath(context.extensionUri, "media", "icon.png");
    void readFile(join(context.extensionPath, "media", "dashboard.html"), "utf8").then((raw) => {
      if (panel) panel.webview.html = dashboardHtml(raw, randomBytes(16).toString("base64"), panel.webview.cspSource, vscode.env.language);
    });
    panel.webview.onDidReceiveMessage(async (msg) => {
      if (!panel || !msg || typeof msg !== "object") return;
      if (msg.type === "ready") void panel.webview.postMessage({ type: "snapshot", snapshot: engine.snapshot() });
      else if (msg.type === "request") void panel.webview.postMessage(await route(facade, msg));
    });
    panel.onDidDispose(() => (panel = undefined));
  };

  let timer: ReturnType<typeof setInterval> | undefined;
  const schedule = () => {
    if (timer) clearInterval(timer);
    const seconds = Math.max(30, config().get<number>("refreshSeconds", 120));
    timer = setInterval(() => void engine.refresh({ auto: true }), seconds * 1000);
  };

  context.subscriptions.push(
    log,
    statusItem,
    vscode.commands.registerCommand("cursorUsage.openDashboard", openDashboard),
    vscode.commands.registerCommand("cursorUsage.refresh", () => engine.refresh({ full: true })),
    vscode.commands.registerCommand("cursorUsage.copySummary", async () => {
      await vscode.env.clipboard.writeText(summaryText(lastSummary ?? (engine.snapshot().report ? widgetSummary(engine.snapshot().report!) : null)));
      void vscode.window.setStatusBarMessage(L("已复制 Cursor 用量摘要", "Copied Cursor usage summary"), 2000);
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration(CONFIG)) return;
      applyLanguage();
      if (panel) panel.title = L("Cursor 用量", "Cursor Usage");
      schedule();
      renderStatus(engine.snapshot());
      void panel?.webview.postMessage({ type: "settingsChanged" });
    }),
    { dispose: () => timer && clearInterval(timer) },
  );

  const initial = await engine.init();
  renderStatus(initial);
  schedule();
  // Let Cursor finish starting up before the first network refresh.
  setTimeout(() => void engine.refresh(), 3000);
  log.info(`activated; data in ${storageDir}`);
}

export function deactivate(): void {}
