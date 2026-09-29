/** Handles requests from the dashboard webview (see packages/ui/src/api.ts createVsCodeHost). */
import type { RefreshOptions } from "@cursor-usage/core";

export interface ExtensionFacade {
  refresh(options: RefreshOptions): Promise<unknown>;
  loadSettings(): Promise<Record<string, unknown>>;
  saveSettings(patch: Record<string, unknown>): Promise<Record<string, unknown>>;
  saveCredentials(patch: Record<string, unknown>): Promise<void>;
  clearCredentials(): Promise<Record<string, unknown>>;
  appInfo(): Promise<Record<string, unknown>>;
  exportFile(name: string, extension: string, content: string): Promise<string>;
  openUrl(url: string): Promise<void>;
  log(level: string, message: string): Promise<void>;
}

const METHODS = new Set<keyof ExtensionFacade>([
  "refresh",
  "loadSettings",
  "saveSettings",
  "saveCredentials",
  "clearCredentials",
  "appInfo",
  "exportFile",
  "openUrl",
  "log",
]);

export type Reply = { type: "response"; id: number; ok: true; result: unknown } | { type: "response"; id: number; ok: false; error: string };

/** Dispatch one webview request to the facade; unknown methods are rejected. */
export async function route(facade: ExtensionFacade, msg: { id: number; method: string; args?: unknown[] }): Promise<Reply> {
  if (!METHODS.has(msg.method as keyof ExtensionFacade)) {
    return { type: "response", id: msg.id, ok: false, error: `unknown method: ${msg.method}` };
  }
  try {
    const fn = facade[msg.method as keyof ExtensionFacade] as (...args: unknown[]) => Promise<unknown>;
    const result = await fn.apply(facade, Array.isArray(msg.args) ? msg.args : []);
    return { type: "response", id: msg.id, ok: true, result: result ?? null };
  } catch (error) {
    return { type: "response", id: msg.id, ok: false, error: (error as Error)?.message || String(error) };
  }
}
