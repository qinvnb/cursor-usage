import { L, UsageEngine, type RefreshOptions } from "@cursor-usage/core";
import { render } from "preact";
import { createDesktopHost, createVsCodeHost, hasPywebview, hasVsCode, type AppApi, type EngineApi } from "./api";
import { App, applyLanguage } from "./components/App";
import "./styles.css";

declare const __MOCK__: boolean;

function signal<T>(initial: T) {
  let value = initial;
  const listeners = new Set<(v: T) => void>();
  return {
    get value() {
      return value;
    },
    set(next: T) {
      value = next;
      listeners.forEach((fn) => fn(next));
    },
    subscribe(fn: (v: T) => void) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

const settingsVersion = signal(0);
const bumpSettings = () => settingsVersion.set(settingsVersion.value + 1);

/** Pick the host: Cursor webview (engine lives in the extension), desktop (engine lives here), or dev mock. */
async function createRuntime(): Promise<{ engine: EngineApi; api: AppApi; local?: UsageEngine }> {
  if (hasVsCode()) return createVsCodeHost(bumpSettings);
  let runtime: Awaited<ReturnType<typeof createDesktopHost>> | null = null;
  if (__MOCK__ && (!hasPywebview() || location.search.includes("mock"))) runtime = (await import("./mock")).createMockHost();
  const { host, api } = runtime ?? (await createDesktopHost());
  const local = new UsageEngine(host, { warn: (m) => void api.log("warning", m).catch(() => {}) });
  return { engine: local, api, local };
}

async function boot() {
  applyLanguage("auto");
  const { engine, api, local } = await createRuntime();
  // Resolve the saved language before the first paint to avoid a flash of the other one.
  await api
    .loadSettings()
    .then((s) => applyLanguage(s.language))
    .catch(() => {});
  const active = signal(true);

  // Called by the desktop host (cursor_usage_app/__main__.py) via evaluate_js.
  (window as any).cursorUsage = {
    refresh: (options?: RefreshOptions) => engine.refresh(options),
    setActive: (value: boolean) => active.set(!!value),
    reloadSettings: bumpSettings,
  };

  render(
    <App engine={engine} api={api} active={active} settingsVersion={{ subscribe: (fn) => settingsVersion.subscribe(() => fn()) }} />,
    document.getElementById("app")!,
  );
  if (local) {
    await local.init();
    await local.refresh();
  }
}

boot().catch((error) => {
  const banner = document.createElement("div");
  banner.className = "banner";
  banner.textContent = `${L("启动失败", "Failed to start")}: ${String(error?.message || error)}`;
  const page = document.createElement("div");
  page.className = "page";
  page.appendChild(banner);
  document.getElementById("app")!.replaceChildren(page);
});
