import { CursorApiError, jwtPayload, tokenExpired, type CursorClient } from "./client";
import { L } from "./i18n";
import type { Credentials, Host } from "./host";
import type { AuthSource, Settings } from "./types";

export interface ResolvedAuth {
  token: string;
  source: AuthSource;
  email: string | null;
  membershipType: string | null;
}

async function manualToken(host: Host, client: CursorClient, creds: Credentials): Promise<string> {
  const access = (creds.accessToken || "").trim();
  const refresh = (creds.refreshToken || "").trim();
  if (!access) throw new CursorApiError(L("手动凭证为空，请在设置中粘贴 Session Token", "No manual credentials: paste a session token in Settings"));
  if (!tokenExpired(access)) return access;
  if (!refresh)
    throw new CursorApiError(L("手动 access token 已过期，且没有 refresh token，请重新粘贴凭证", "The manual access token expired and there is no refresh token; paste new credentials"));
  const data = await client.refreshAccessToken(refresh);
  if (data.shouldLogout || !data.access_token)
    throw new CursorApiError(L("手动凭证会话已失效，请重新粘贴凭证", "The manual session is no longer valid; paste new credentials"));
  await host.saveCredentials({ accessToken: data.access_token, refreshToken: data.refresh_token || refresh });
  return data.access_token;
}

async function manualAuth(host: Host, client: CursorClient, creds: Credentials): Promise<ResolvedAuth> {
  return {
    token: await manualToken(host, client, creds),
    source: "manual",
    email: creds.email || L("(手动凭证)", "(manual credentials)"),
    membershipType: null,
  };
}

/**
 * Resolve an access token: env var, then manual credentials when selected,
 * then the local Cursor session (falling back to manual credentials).
 *
 * An expired local token is refreshed only when persistLocalRefresh is on,
 * because the refresh token may rotate: refreshing without writing the new
 * pair back to state.vscdb could sign the Cursor app itself out.
 */
export async function resolveAuth(host: Host, client: CursorClient, settings: Settings): Promise<ResolvedAuth> {
  const env = await host.envToken();
  if (env) return { token: env, source: "env", email: L("(环境变量)", "(environment variable)"), membershipType: null };

  const creds = await host.getCredentials();
  if (settings.authSource === "manual" && creds?.accessToken) return manualAuth(host, client, creds);

  try {
    const local = await host.readLocalAuth();
    const access = local.accessToken;
    if (!access) throw new CursorApiError(L("本机 Cursor 未登录：请先在 Cursor 中登录", "Cursor is not signed in on this machine: sign in to Cursor first"));
    let token = access;
    if (tokenExpired(access)) {
      if (!settings.persistLocalRefresh) {
        throw new CursorApiError(
          L(
            "本机 Cursor 登录令牌已过期：请打开 Cursor 让其自动续期，或在设置中开启“令牌过期时由本工具刷新并写回 Cursor”",
            'The local Cursor token expired: open Cursor so it renews itself, or enable "refresh and write back to Cursor" in Settings',
          ),
        );
      }
      if (!local.refreshToken) throw new CursorApiError(L("本机令牌已过期，且没有 refresh token", "The local token expired and there is no refresh token"));
      const data = await client.refreshAccessToken(local.refreshToken);
      if (data.shouldLogout || !data.access_token)
        throw new CursorApiError(L("Cursor 会话已失效，请在 Cursor 中重新登录", "The Cursor session is no longer valid: sign in to Cursor again"));
      token = data.access_token;
      await host.writeLocalAuth({ accessToken: token, refreshToken: data.refresh_token || undefined });
    }
    return {
      token,
      source: "local",
      email: local.cachedEmail || null,
      membershipType: local.stripeMembershipType || null,
    };
  } catch (error) {
    if (creds?.accessToken) return manualAuth(host, client, creds);
    throw error;
  }
}

/** Accept a JWT, `userId::jwt`, or a WorkosCursorSessionToken cookie value. */
export function parseSessionInput(raw: string): { accessToken: string; emailHint: string } {
  let s = (raw || "").trim();
  if (!s) throw new CursorApiError(L("凭证不能为空", "Credentials cannot be empty"));
  if (s.includes("WorkosCursorSessionToken=")) {
    s = s.split("WorkosCursorSessionToken=")[1].split(";")[0].trim();
  }
  try {
    s = decodeURIComponent(s);
  } catch {
    /* keep as-is */
  }
  s = s.replace(/%3A%3A/gi, "::").trim();
  if (s.toLowerCase().startsWith("bearer ")) s = s.slice(7).trim();
  if (s.includes("::")) {
    const [left, right] = [s.slice(0, s.indexOf("::")).trim(), s.slice(s.indexOf("::") + 2).trim()];
    if (right.split(".").length >= 3) s = right;
    else if (left.split(".").length >= 3) s = left;
    else throw new CursorApiError(L("无法识别凭证格式，请粘贴 access token 或 WorkosCursorSessionToken", "Unrecognized format: paste an access token or WorkosCursorSessionToken"));
  }
  if (s.split(".").length < 3) throw new CursorApiError(L("看起来不是有效的 JWT access token", "This does not look like a valid JWT access token"));
  let emailHint = "";
  try {
    const sub = String(jwtPayload(s).sub || "");
    if (sub.includes("@")) emailHint = sub;
  } catch (error) {
    throw new CursorApiError(L(`无法解析 token：${(error as Error).message}`, `Cannot parse token: ${(error as Error).message}`));
  }
  return { accessToken: s, emailHint };
}
