import type { AlertsState, CycleSnapshot, Report, Settings, WidgetSummary } from "./types";

export interface HttpRequest {
  url: string;
  method: "GET" | "POST";
  headers: Record<string, string>;
  body?: string;
  timeoutMs: number;
}

export interface HttpResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
}

/** Tokens stored by the Cursor app in state.vscdb (keys without the cursorAuth/ prefix). */
export interface LocalAuth {
  accessToken?: string;
  refreshToken?: string;
  cachedEmail?: string;
  stripeMembershipType?: string;
}

export interface Credentials {
  accessToken: string;
  refreshToken: string;
  email: string;
}

export interface PersistedState {
  report: Report | null;
  history: CycleSnapshot[];
  alerts: AlertsState;
}

/**
 * Everything platform-specific. The desktop app implements this with a Python
 * bridge; a Cursor extension implements it with Node fetch + sql.js.
 *
 * http() must resolve for any HTTP status and reject only on transport errors
 * (DNS, TLS, timeout).
 */
export interface Host {
  http(req: HttpRequest): Promise<HttpResponse>;
  envToken(): Promise<string | null>;
  readLocalAuth(): Promise<LocalAuth>;
  writeLocalAuth(patch: { accessToken?: string; refreshToken?: string }): Promise<void>;
  getCredentials(): Promise<Credentials | null>;
  saveCredentials(patch: Partial<Credentials>): Promise<void>;
  loadSettings(): Promise<Settings>;
  loadState(): Promise<PersistedState>;
  saveReport(report: Report, summary: WidgetSummary): Promise<void>;
  saveHistory(cycles: CycleSnapshot[]): Promise<void>;
  saveAlertsState(state: AlertsState): Promise<void>;
  notify(title: string, message: string): Promise<void>;
}
