import type { Host, HttpRequest } from "./host";
import { L } from "./i18n";

export const API2 = "https://api2.cursor.sh";
export const CURSOR_WEB = "https://cursor.com";
export const OAUTH_CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB";
const RETRY_STATUS = new Set([429, 500, 502, 503, 504]);
const MAX_ATTEMPTS = 3;

export class CursorApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "CursorApiError";
  }
}

export type Sleep = (ms: number) => Promise<void>;
const defaultSleep: Sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * HTTP client for the Cursor dashboard APIs: JSON in/out, bounded retries on
 * 429/5xx/transport errors, and one overall deadline shared by every call.
 */
export class CursorClient {
  private deadline: number | null = null;

  constructor(
    private readonly host: Host,
    private readonly sleep: Sleep = defaultSleep,
    private readonly now: () => number = () => Date.now(),
  ) {}

  /** Run `fn` with every request bounded by a total of `ms` wall time. */
  async withDeadline<T>(ms: number, fn: () => Promise<T>): Promise<T> {
    const previous = this.deadline;
    this.deadline = this.now() + ms;
    try {
      return await fn();
    } finally {
      this.deadline = previous;
    }
  }

  private timeout(defaultMs: number): number {
    if (this.deadline === null) return defaultMs;
    const remaining = this.deadline - this.now();
    if (remaining <= 0) throw new CursorApiError(L("获取用量超时，请检查网络后重试", "Fetching usage timed out; check your network and try again"));
    return Math.max(1000, Math.min(defaultMs, remaining));
  }

  async requestJson(
    req: Omit<HttpRequest, "timeoutMs">,
    { timeoutMs = 30_000, label, retry = true }: { timeoutMs?: number; label: string; retry?: boolean },
  ): Promise<any> {
    let delay = 1000;
    const attempts = retry ? MAX_ATTEMPTS : 1;
    for (let attempt = 1; attempt <= attempts; attempt++) {
      let wait = delay;
      try {
        const res = await this.host.http({ ...req, timeoutMs: this.timeout(timeoutMs) });
        if (res.status >= 200 && res.status < 300) {
          return res.body ? JSON.parse(res.body) : {};
        }
        const detail = (res.body || "").slice(0, 800);
        if (!RETRY_STATUS.has(res.status) || attempt === attempts) {
          throw new CursorApiError(`HTTP ${res.status} from ${label}: ${detail}`, res.status);
        }
        const retryAfter = Number(res.headers["retry-after"] ?? res.headers["Retry-After"]);
        if (Number.isFinite(retryAfter) && retryAfter > 0) wait = Math.min(10_000, retryAfter * 1000);
      } catch (error) {
        if (error instanceof CursorApiError) throw error;
        if (error instanceof SyntaxError) throw new CursorApiError(`Invalid JSON from ${label}`);
        if (attempt === attempts) {
          const detail = (error as Error)?.message ?? error;
          throw new CursorApiError(L(`网络错误（${label}）: ${detail}`, `Network error (${label}): ${detail}`));
        }
      }
      if (this.deadline !== null && this.now() + wait >= this.deadline) {
        throw new CursorApiError(L(`获取用量超时（${label}）`, `Fetching usage timed out (${label})`));
      }
      await this.sleep(wait);
      delay *= 2;
    }
    throw new CursorApiError(L(`请求失败（${label}）`, `Request failed (${label})`));
  }

  connectPost(path: string, token: string, payload: unknown = {}): Promise<any> {
    return this.requestJson(
      {
        url: `${API2}/${path}`,
        method: "POST",
        headers: { "Content-Type": "application/json", "Connect-Protocol-Version": "1", Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload ?? {}),
      },
      { label: path },
    );
  }

  webGet(path: string, token: string): Promise<any> {
    return this.requestJson(
      { url: `${CURSOR_WEB}${path}`, method: "GET", headers: { Cookie: sessionCookie(token) } },
      { label: path },
    );
  }

  webPost(path: string, token: string, payload: unknown): Promise<any> {
    return this.requestJson(
      {
        url: `${CURSOR_WEB}${path}`,
        method: "POST",
        headers: { Cookie: sessionCookie(token), "Content-Type": "application/json", Origin: CURSOR_WEB },
        body: JSON.stringify(payload),
      },
      { label: path, timeoutMs: 60_000 },
    );
  }

  /** OAuth refresh is never retried: a rotated refresh token must not be spent twice. */
  refreshAccessToken(refreshToken: string): Promise<any> {
    return this.requestJson(
      {
        url: `${API2}/oauth/token`,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grant_type: "refresh_token", client_id: OAUTH_CLIENT_ID, refresh_token: refreshToken }),
      },
      { label: "oauth/token", retry: false },
    );
  }
}

function base64UrlDecode(part: string): string {
  const padded = part.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (part.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

export function jwtPayload(token: string): Record<string, any> {
  const part = token.split(".")[1];
  if (!part) throw new Error("not a JWT");
  return JSON.parse(base64UrlDecode(part));
}

export function tokenExpired(token: string, skewSeconds = 60, nowMs = Date.now()): boolean {
  try {
    const exp = Number(jwtPayload(token).exp || 0);
    return exp <= Math.floor(nowMs / 1000) + skewSeconds;
  } catch {
    return true;
  }
}

export function sessionCookie(token: string): string {
  const sub = jwtPayload(token).sub;
  if (!sub) throw new CursorApiError("JWT missing sub claim; cannot build session cookie.");
  return `WorkosCursorSessionToken=${sub}%3A%3A${token}`;
}
