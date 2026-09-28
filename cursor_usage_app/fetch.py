"""Library wrapper around usage.py — local Cursor session or manual credentials."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import store
from . import usage


class UsageError(RuntimeError):
    """Raised when usage cannot be fetched."""


def parse_session_input(raw: str) -> dict[str, str]:
    """Accept JWT, userId::jwt, or WorkosCursorSessionToken cookie value."""
    import urllib.parse

    s = (raw or "").strip()
    if not s:
        raise UsageError("凭证不能为空")
    if "WorkosCursorSessionToken=" in s:
        s = s.split("WorkosCursorSessionToken=", 1)[1]
        s = s.split(";", 1)[0].strip()
    s = urllib.parse.unquote(s).replace("%3A%3A", "::").strip()
    if s.lower().startswith("bearer "):
        s = s[7:].strip()

    email_hint = ""
    if "::" in s:
        left, right = s.split("::", 1)
        left, right = left.strip(), right.strip()
        if right.count(".") >= 2:
            s = right
        elif left.count(".") >= 2:
            s = left
        else:
            raise UsageError("无法识别凭证格式，请粘贴 access token 或 WorkosCursorSessionToken")

    if s.count(".") < 2:
        raise UsageError("看起来不是有效的 JWT access token")

    try:
        payload = usage.jwt_payload(s)
        sub = str(payload.get("sub") or "")
        if "@" in sub:
            email_hint = sub
    except Exception as e:
        raise UsageError(f"无法解析 token：{e}") from e

    return {"accessToken": s, "emailHint": email_hint}


def _resolve_manual_token(creds: dict[str, Any]) -> str:
    access = str(creds.get("accessToken") or "").strip()
    refresh = str(creds.get("refreshToken") or "").strip()
    if not access:
        raise UsageError("手动凭证为空，请在设置中粘贴 Session Token")

    if not usage.token_expired(access):
        return access

    if not refresh:
        raise UsageError("手动 access token 已过期，且没有 refresh token，请重新粘贴凭证")

    data = usage.refresh_access_token(refresh)
    if data.get("shouldLogout") or not data.get("access_token"):
        raise UsageError("手动凭证会话已失效，请重新粘贴凭证")

    new_access = data["access_token"]
    new_refresh = data.get("refresh_token") or refresh
    store.save_credentials({"accessToken": new_access, "refreshToken": new_refresh})
    return new_access


def _resolve_local_auth() -> tuple[dict[str, str], str]:
    db_path = usage.state_db_path()
    auth = usage.read_auth_keys(db_path)
    token = usage.resolve_token(auth, db_path, persist=True)
    return auth, token


def resolve_auth() -> tuple[dict[str, str], str, str]:
    """Return (auth_dict, access_token, source) where source is manual|local|env."""
    env = __import__("os").environ.get("CURSOR_SESSION_TOKEN") or __import__("os").environ.get(
        "CURSOR_ACCESS_TOKEN"
    )
    if env:
        raw = env.replace("%3A%3A", "::")
        token = raw.split("::", 1)[-1].strip()
        auth = {
            "cursorAuth/accessToken": token,
            "cursorAuth/cachedEmail": "(环境变量)",
        }
        return auth, token, "env"

    settings = store.load_settings()
    creds = store.load_credentials()
    prefer_manual = settings.get("authSource") == "manual" and bool(creds.get("accessToken"))

    if prefer_manual:
        token = _resolve_manual_token(creds)
        auth = {
            "cursorAuth/accessToken": token,
            "cursorAuth/refreshToken": creds.get("refreshToken") or "",
            "cursorAuth/cachedEmail": creds.get("email") or "(手动凭证)",
        }
        return auth, token, "manual"

    try:
        auth, token = _resolve_local_auth()
        return auth, token, "local"
    except SystemExit as e:
        # Fallback to manual if local Cursor session missing
        if creds.get("accessToken"):
            token = _resolve_manual_token(creds)
            auth = {
                "cursorAuth/accessToken": token,
                "cursorAuth/refreshToken": creds.get("refreshToken") or "",
                "cursorAuth/cachedEmail": creds.get("email") or "(手动凭证)",
            }
            return auth, token, "manual"
        raise UsageError(str(e.args[0] if e.args else e)) from e


def fetch_report(*, persist_refresh: bool = True, include_models: bool = True) -> dict[str, Any]:
    try:
        auth, token, source = resolve_auth()
        if not include_models:
            period = usage.connect_post(
                "aiserver.v1.DashboardService/GetCurrentPeriodUsage", token
            )
            plan_raw = usage.connect_post(
                "aiserver.v1.DashboardService/GetPlanInfo", token
            )
            plan = plan_raw.get("planInfo") or plan_raw
            report = {
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "account": {
                    "email": auth.get("cursorAuth/cachedEmail"),
                    "membershipType": auth.get("cursorAuth/stripeMembershipType"),
                    "authSource": source,
                },
                "planInfo": plan,
                "periodUsage": period,
                "onDemandModels": [],
                "includedModels": [],
                "models": [],
                "summary": usage.build_summary(period, plan, None, []),
            }
            return report

        report = usage.build_report(auth, token)
        account = report.setdefault("account", {})
        account["authSource"] = source
        if source == "manual" and not account.get("email"):
            account["email"] = auth.get("cursorAuth/cachedEmail")
        # Persist email from /api/auth/me into credentials when manual
        if source == "manual":
            email = account.get("email")
            if email and "@" in str(email):
                store.save_credentials({"email": str(email)})
        return report
    except UsageError:
        raise
    except SystemExit as e:
        msg = e.args[0] if e.args else "获取用量失败"
        raise UsageError(str(msg)) from e
    except Exception as e:
        raise UsageError(str(e)) from e
