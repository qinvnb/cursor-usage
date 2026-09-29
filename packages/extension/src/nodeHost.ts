/**
 * Host implementation for the Cursor extension host (Node 20+/Electron).
 * No `vscode` import here so it can be unit-tested; vscode specifics are
 * injected through NodeHostDeps.
 */
import { L, type AlertsState, type Credentials, type CycleSnapshot, type Host, type HttpRequest, type HttpResponse, type LocalAuth, type Report, type Settings, type WidgetSummary } from "@cursor-usage/core";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const ALLOWED_HOSTS = new Set(["api2.cursor.sh", "cursor.com", "www.cursor.com"]);
const AUTH_PREFIX = "cursorAuth/";
const CREDENTIALS_KEY = "cursorUsage.credentials";

export interface JsonStore {
  read<T>(name: string): Promise<T | null>;
  write(name: string, value: unknown): Promise<void>;
}

export interface SecretStore {
  get(key: string): PromiseLike<string | undefined>;
  store(key: string, value: string): PromiseLike<void>;
  delete(key: string): PromiseLike<void>;
}

export interface NodeHostDeps {
  store: JsonStore;
  secrets: SecretStore;
  settings: () => Settings;
  /** Explicit state.vscdb path from settings, if any. */
  stateDbOverride: () => string;
  /** The extension's globalStorage directory (…/User/globalStorage/<publisher.name>). */
  globalStorageDir: string;
  notify: (title: string, message: string) => Promise<void>;
  onReport: (report: Report, summary: WidgetSummary) => void;
  fetchImpl?: typeof fetch;
  env?: NodeJS.ProcessEnv;
}

/** Cursor keeps its login in User/globalStorage/state.vscdb, the parent of our own storage dir. */
export function resolveStateDb(override: string, globalStorageDir: string, env: NodeJS.ProcessEnv = process.env): string {
  if (override.trim()) return override.trim();
  if (env.CURSOR_STATE_DB) return env.CURSOR_STATE_DB;
  const sibling = join(dirname(globalStorageDir), "state.vscdb");
  if (existsSync(sibling)) return sibling;
  if (process.platform === "win32") return join(env.APPDATA || "", "Cursor", "User", "globalStorage", "state.vscdb");
  if (process.platform === "darwin") return join(homedir(), "Library", "Application Support", "Cursor", "User", "globalStorage", "state.vscdb");
  return join(homedir(), ".config", "Cursor", "User", "globalStorage", "state.vscdb");
}

/**
 * node:sqlite via getBuiltinModule (Node 22.3+): bundlers leave it alone, and
 * older runtimes simply return undefined instead of failing at load time.
 */
function loadSqlite(): typeof import("node:sqlite") | undefined {
  try {
    return (process as unknown as { getBuiltinModule?: (id: string) => unknown }).getBuiltinModule?.("node:sqlite") as typeof import("node:sqlite") | undefined;
  } catch {
    return undefined;
  }
}

/** Read cursorAuth/* keys with the runtime's built-in SQLite (read-only; works on multi-GB WAL databases). */
export async function readLocalAuthFrom(path: string): Promise<LocalAuth> {
  if (!existsSync(path)) throw new Error(L(`找不到 Cursor 登录数据：${path}`, `Cursor sign-in data not found: ${path}`));
  const sqlite = loadSqlite();
  if (!sqlite)
    throw new Error(
      L(
        "当前 Cursor 版本缺少内置 SQLite，无法读取登录状态；请升级 Cursor，或在设置中粘贴手动凭证",
        "This Cursor version has no built-in SQLite, so the sign-in cannot be read; update Cursor or paste manual credentials in Settings",
      ),
    );
  const db = new sqlite.DatabaseSync(path, { readOnly: true });
  try {
    const rows = db.prepare("SELECT key, value FROM ItemTable WHERE key LIKE 'cursorAuth/%'").all() as { key: string; value: unknown }[];
    const out: Record<string, string> = {};
    for (const row of rows) {
      const value = typeof row.value === "string" ? row.value : row.value instanceof Uint8Array ? new TextDecoder().decode(row.value) : null;
      if (value !== null) out[row.key.slice(AUTH_PREFIX.length)] = value;
    }
    return out as LocalAuth;
  } finally {
    db.close();
  }
}

export async function httpRequest(req: HttpRequest, fetchImpl: typeof fetch = fetch): Promise<HttpResponse> {
  const url = new URL(req.url);
  if (url.protocol !== "https:" || !ALLOWED_HOSTS.has(url.hostname)) throw new Error(`blocked request to ${url.hostname}`);
  const res = await fetchImpl(url, {
    method: req.method,
    headers: req.headers,
    body: req.body,
    signal: AbortSignal.timeout(Math.max(1000, req.timeoutMs)),
  });
  const headers: Record<string, string> = {};
  res.headers.forEach((value, key) => (headers[key.toLowerCase()] = value));
  return { status: res.status, headers, body: await res.text() };
}

export function createNodeHost(deps: NodeHostDeps): Host {
  const env = deps.env ?? process.env;
  return {
    http: (req) => httpRequest(req, deps.fetchImpl),
    envToken: async () => {
      const raw = env.CURSOR_SESSION_TOKEN || env.CURSOR_ACCESS_TOKEN;
      return raw ? raw.replace(/%3A%3A/g, "::").split("::").pop()!.trim() || null : null;
    },
    readLocalAuth: () => readLocalAuthFrom(resolveStateDb(deps.stateDbOverride(), deps.globalStorageDir, env)),
    // Never write into a database the running Cursor owns.
    writeLocalAuth: async () => {
      throw new Error(L("插件不会写回 Cursor 的登录数据", "The extension never writes to Cursor's sign-in data"));
    },
    getCredentials: async () => {
      const raw = await deps.secrets.get(CREDENTIALS_KEY);
      if (!raw) return null;
      try {
        const creds = JSON.parse(raw) as Credentials;
        return creds.accessToken ? creds : null;
      } catch {
        return null;
      }
    },
    saveCredentials: async (patch) => {
      const current = JSON.parse((await deps.secrets.get(CREDENTIALS_KEY)) || "{}");
      const next = { accessToken: "", refreshToken: "", email: "", ...current };
      for (const key of ["accessToken", "refreshToken", "email"] as const) {
        if (patch[key] !== undefined && patch[key] !== null) next[key] = String(patch[key]).trim();
      }
      await deps.secrets.store(CREDENTIALS_KEY, JSON.stringify(next));
    },
    loadSettings: async () => ({ ...deps.settings(), persistLocalRefresh: false }),
    loadState: async () => ({
      report: await deps.store.read<Report>("usage"),
      history: ((await deps.store.read<{ cycles: CycleSnapshot[] }>("history"))?.cycles as CycleSnapshot[]) || [],
      alerts: (await deps.store.read<AlertsState>("alerts")) || {},
    }),
    saveReport: async (report, summary) => {
      await deps.store.write("usage", report);
      await deps.store.write("summary", summary);
      deps.onReport(report, summary);
    },
    saveHistory: (cycles) => deps.store.write("history", { cycles }),
    saveAlertsState: (state) => deps.store.write("alerts", state),
    notify: (title, message) => deps.notify(title, message),
  };
}

export async function clearCredentials(secrets: SecretStore): Promise<void> {
  await secrets.delete(CREDENTIALS_KEY);
}

export async function credentialsInfo(secrets: SecretStore): Promise<{ hasManualCredentials: boolean; hasRefreshToken: boolean; manualEmail: string; tokenPreview: string }> {
  let creds: Partial<Credentials> = {};
  try {
    creds = JSON.parse((await secrets.get(CREDENTIALS_KEY)) || "{}");
  } catch {
    creds = {};
  }
  const access = creds.accessToken || "";
  return {
    hasManualCredentials: !!access,
    hasRefreshToken: !!creds.refreshToken,
    manualEmail: creds.email || "",
    tokenPreview: access ? (access.length > 8 ? `…${access.slice(-8)}` : L("已设置", "set")) : "",
  };
}
