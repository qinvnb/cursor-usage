"""Library wrapper around usage.py — local Cursor session or manual credentials."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import store
from . import usage

# One error type for every "usage could not be fetched" condition.
UsageError = usage.CursorApiError

FULL_REFRESH_DEADLINE_SECONDS = 150
LIGHT_REFRESH_DEADLINE_SECONDS = 45


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


def _manual_auth(creds: dict[str, Any]) -> tuple[dict[str, str], str, str]:
    token = _resolve_manual_token(creds)
    auth = {
        "cursorAuth/accessToken": token,
        "cursorAuth/refreshToken": creds.get("refreshToken") or "",
        "cursorAuth/cachedEmail": creds.get("email") or "(手动凭证)",
    }
    return auth, token, "manual"


def resolve_auth() -> tuple[dict[str, str], str, str]:
    """Return (auth_dict, access_token, source) where source is manual|local|env."""
    env = usage.env_token()
    if env:
        auth = {
            "cursorAuth/accessToken": env,
            "cursorAuth/cachedEmail": "(环境变量)",
        }
        return auth, env, "env"

    settings = store.load_settings()
    creds = store.load_credentials()
    if settings.get("authSource") == "manual" and creds.get("accessToken"):
        return _manual_auth(creds)

    try:
        db_path = usage.state_db_path()
        auth = usage.read_auth_keys(db_path)
        token = usage.resolve_token(
            auth, db_path, persist=bool(settings.get("persistLocalRefresh"))
        )
        return auth, token, "local"
    except UsageError:
        # Fall back to manual credentials if the local Cursor session is unusable.
        if creds.get("accessToken"):
            return _manual_auth(creds)
        raise


def _lightweight_report(auth: dict[str, str], token: str, source: str) -> dict[str, Any]:
    period, plan_raw = usage._run_parallel(
        lambda: usage.connect_post("aiserver.v1.DashboardService/GetCurrentPeriodUsage", token),
        lambda: usage.connect_post("aiserver.v1.DashboardService/GetPlanInfo", token),
    )
    for result in (period, plan_raw):
        if isinstance(result, Exception):
            raise result
    plan = plan_raw.get("planInfo") or plan_raw
    return {
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


def fetch_report(*, include_models: bool = True) -> dict[str, Any]:
    deadline = FULL_REFRESH_DEADLINE_SECONDS if include_models else LIGHT_REFRESH_DEADLINE_SECONDS
    try:
        with usage.request_deadline(deadline):
            auth, token, source = resolve_auth()
            if not include_models:
                return _lightweight_report(auth, token, source)

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
    except Exception as e:
        raise UsageError(str(e)) from e
