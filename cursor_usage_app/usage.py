#!/usr/bin/env python3
"""Fetch Cursor plan / period usage from the signed-in local session.

Uses undocumented Cursor dashboard Connect-RPC + cookie REST endpoints with the
access token stored by the Cursor app. No third-party calls. Requires network.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API2 = "https://api2.cursor.sh"
CURSOR_WEB = "https://cursor.com"
OAUTH_CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"
CONNECT_HEADERS = {
    "Content-Type": "application/json",
    "Connect-Protocol-Version": "1",
}


def state_db_path() -> Path:
    override = os.environ.get("CURSOR_STATE_DB")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise SystemExit("APPDATA is not set")
        return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    return Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def read_auth_keys(db_path: Path) -> dict[str, str]:
    if not db_path.is_file():
        raise SystemExit(
            f"Cursor state DB not found: {db_path}\n"
            "Sign in to Cursor, then retry."
        )
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT key, value FROM ItemTable WHERE key LIKE 'cursorAuth/%'"
        ).fetchall()
    finally:
        conn.close()
    return {k: v for k, v in rows if isinstance(v, str)}


def write_auth_key(db_path: Path, key: str, value: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO ItemTable(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def jwt_payload(token: str) -> dict[str, Any]:
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def token_expired(token: str, skew_s: int = 60) -> bool:
    try:
        exp = int(jwt_payload(token).get("exp") or 0)
    except Exception:
        return True
    return exp <= int(time.time()) + skew_s


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    body = json.dumps(
        {
            "grant_type": "refresh_token",
            "client_id": OAUTH_CLIENT_ID,
            "refresh_token": refresh_token,
        }
    ).encode()
    req = urllib.request.Request(
        f"{API2}/oauth/token",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def resolve_token(auth: dict[str, str], db_path: Path, persist: bool) -> str:
    env = os.environ.get("CURSOR_SESSION_TOKEN") or os.environ.get("CURSOR_ACCESS_TOKEN")
    if env:
        raw = env.replace("%3A%3A", "::")
        return raw.split("::", 1)[-1].strip()

    access = auth.get("cursorAuth/accessToken")
    refresh = auth.get("cursorAuth/refreshToken")
    if not access:
        raise SystemExit(
            "No cursorAuth/accessToken in local Cursor state. Sign in to Cursor first."
        )

    if not token_expired(access):
        return access

    if not refresh:
        raise SystemExit("Access token expired and no refresh token is available.")

    data = refresh_access_token(refresh)
    if data.get("shouldLogout") or not data.get("access_token"):
        raise SystemExit("Session expired. Sign in to Cursor again.")

    new_access = data["access_token"]
    if persist:
        write_auth_key(db_path, "cursorAuth/accessToken", new_access)
        if data.get("refresh_token"):
            write_auth_key(db_path, "cursorAuth/refreshToken", data["refresh_token"])
    return new_access


def session_cookie(token: str) -> str:
    sub = jwt_payload(token).get("sub")
    if not sub:
        raise SystemExit("JWT missing sub claim; cannot build session cookie.")
    # WorkOS cookie: sub%3A%3Ajwt
    return f"WorkosCursorSessionToken={sub}%3A%3A{token}"


def connect_post(path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    body = json.dumps(payload if payload is not None else {}).encode()
    req = urllib.request.Request(
        f"{API2}/{path}",
        data=body,
        headers={**CONNECT_HEADERS, "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:800]
        raise SystemExit(f"HTTP {e.code} from {path}: {detail}") from e


def web_get(path: str, token: str) -> Any:
    req = urllib.request.Request(
        f"{CURSOR_WEB}{path}",
        headers={"Cookie": session_cookie(token)},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:800]
        raise SystemExit(f"HTTP {e.code} from {path}: {detail}") from e


def web_post(path: str, token: str, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{CURSOR_WEB}{path}",
        data=body,
        headers={
            "Cookie": session_cookie(token),
            "Content-Type": "application/json",
            "Origin": CURSOR_WEB,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:800]
        raise SystemExit(f"HTTP {e.code} from {path}: {detail}") from e


def as_float(n: Any, default: float = 0.0) -> float:
    try:
        if n is None or n == "":
            return default
        return float(n)
    except (TypeError, ValueError):
        return default


def as_int(n: Any, default: int = 0) -> int:
    try:
        if n is None or n == "":
            return default
        return int(float(n))
    except (TypeError, ValueError):
        return default


def cents(n: Any) -> str:
    try:
        return f"${float(n) / 100:.2f}"
    except (TypeError, ValueError):
        return "n/a"


def dollars_from_cents(n: Any) -> float:
    return round(as_float(n) / 100.0, 2)


def ms_to_local(ms: Any) -> str:
    try:
        ts = int(str(ms)) / 1000.0
        dt = datetime.fromtimestamp(ts).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M %z")
    except Exception:
        return str(ms)


def remaining_cents(usage: dict[str, Any]) -> Any:
    if usage.get("remaining") is not None:
        return usage.get("remaining")
    try:
        return max(0, int(usage.get("limit") or 0) - int(usage.get("includedSpend") or 0))
    except (TypeError, ValueError):
        return None


def pct(n: Any) -> str:
    try:
        return f"{float(n):.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def fmt_tokens(n: Any) -> str:
    v = as_int(n)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def event_charged_cents(event: dict[str, Any]) -> float:
    c = event.get("chargedCents")
    if c is not None and c != "" and c != "-":
        try:
            return float(c)
        except (TypeError, ValueError):
            pass
    tu = event.get("tokenUsage") or {}
    if tu.get("totalCents") is not None:
        return as_float(tu.get("totalCents"))
    return 0.0


def classify_event_bucket(kind: str | None) -> str | None:
    """Return 'onDemand', 'included', or None (skip)."""
    k = (kind or "").upper()
    if "ERRORED" in k or "NOT_CHARGED" in k:
        return None
    if "USAGE_BASED" in k:
        return "onDemand"
    if "INCLUDED" in k:
        return "included"
    return None


def rows_from_cost_map(
    costs: dict[str, float],
    tokens: dict[str, dict[str, int]],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    total = sum(costs.values())
    rows: list[dict[str, Any]] = []
    for model, cost in costs.items():
        tok = tokens.get(model) or {}
        share = (cost / total * 100.0) if total > 0 else 0.0
        rows.append(
            {
                "model": model,
                "costCents": cost,
                "costDollars": round(cost / 100.0, 4),
                "sharePercent": round(share, 2),
                "eventCount": counts.get(model, 0),
                "inputTokens": tok.get("inputTokens", 0),
                "outputTokens": tok.get("outputTokens", 0),
                "cacheReadTokens": tok.get("cacheReadTokens", 0),
                "cacheWriteTokens": tok.get("cacheWriteTokens", 0),
            }
        )
    rows.sort(key=lambda r: r["costCents"], reverse=True)
    return rows


def fetch_filtered_usage_events(
    token: str, user_id: int, start_ms: Any, end_ms: Any, page_size: int = 200
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    page = 1
    total: int | None = None
    while page <= 100:
        payload = {
            "teamId": 0,
            "startDate": str(start_ms),
            "endDate": str(end_ms),
            "userId": user_id,
            "page": page,
            "pageSize": page_size,
        }
        data = web_post("/api/dashboard/get-filtered-usage-events", token, payload)
        if total is None:
            total = as_int(data.get("totalUsageEventsCount"))
        batch = data.get("usageEventsDisplay") or []
        if not isinstance(batch, list):
            break
        events.extend(batch)
        if not batch or (total is not None and len(events) >= total):
            break
        page += 1
    return events


def aggregate_events_by_bucket(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    cost_maps: dict[str, dict[str, float]] = {
        "onDemand": {},
        "included": {},
    }
    token_maps: dict[str, dict[str, dict[str, int]]] = {
        "onDemand": {},
        "included": {},
    }
    count_maps: dict[str, dict[str, int]] = {"onDemand": {}, "included": {}}
    kind_totals: dict[str, float] = {}
    daily_maps: dict[str, dict[str, float]] = {}
    daily_models: dict[str, dict[str, dict[str, float]]] = {}

    for event in events:
        kind = event.get("kind") or "unknown"
        bucket = classify_event_bucket(str(kind))
        cost = event_charged_cents(event)
        kind_totals[str(kind)] = kind_totals.get(str(kind), 0.0) + cost
        if bucket is None:
            continue
        model = str(event.get("model") or "unknown")
        cost_maps[bucket][model] = cost_maps[bucket].get(model, 0.0) + cost
        count_maps[bucket][model] = count_maps[bucket].get(model, 0) + 1
        tok_slot = token_maps[bucket].setdefault(
            model,
            {
                "inputTokens": 0,
                "outputTokens": 0,
                "cacheReadTokens": 0,
                "cacheWriteTokens": 0,
            },
        )
        tu = event.get("tokenUsage") or {}
        for key in tok_slot:
            tok_slot[key] += as_int(tu.get(key))

        # Local calendar day from event timestamp (ms).
        day = "unknown"
        try:
            ts = int(str(event.get("timestamp") or 0)) / 1000.0
            if ts > 0:
                day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            day = "unknown"
        day_slot = daily_maps.setdefault(
            day, {"onDemandCostCents": 0.0, "includedCostCents": 0.0, "eventCount": 0}
        )
        if bucket == "onDemand":
            day_slot["onDemandCostCents"] += cost
        else:
            day_slot["includedCostCents"] += cost
        day_slot["eventCount"] += 1
        dm = daily_models.setdefault(day, {"onDemand": {}, "included": {}})
        dm[bucket][model] = dm[bucket].get(model, 0.0) + cost

    on_demand_rows = rows_from_cost_map(
        cost_maps["onDemand"], token_maps["onDemand"], count_maps["onDemand"]
    )
    included_rows = rows_from_cost_map(
        cost_maps["included"], token_maps["included"], count_maps["included"]
    )

    # Combined per-model view (on-demand + included).
    combined_costs: dict[str, dict[str, float]] = {}
    combined_tokens: dict[str, dict[str, int]] = {}
    combined_counts: dict[str, int] = {}
    for bucket, rows in (("onDemand", on_demand_rows), ("included", included_rows)):
        field = "onDemandCostCents" if bucket == "onDemand" else "includedCostCents"
        for row in rows:
            model = row["model"]
            slot = combined_costs.setdefault(
                model, {"onDemandCostCents": 0.0, "includedCostCents": 0.0}
            )
            slot[field] = row["costCents"]
            combined_counts[model] = combined_counts.get(model, 0) + row["eventCount"]
            tok = combined_tokens.setdefault(
                model,
                {
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheReadTokens": 0,
                    "cacheWriteTokens": 0,
                },
            )
            for key in tok:
                tok[key] += row[key]

    combined_rows: list[dict[str, Any]] = []
    for model, costs in combined_costs.items():
        on_c = costs["onDemandCostCents"]
        in_c = costs["includedCostCents"]
        total_c = on_c + in_c
        tok = combined_tokens.get(model) or {}
        combined_rows.append(
            {
                "model": model,
                "onDemandCostCents": on_c,
                "onDemandCostDollars": round(on_c / 100.0, 4),
                "includedCostCents": in_c,
                "includedCostDollars": round(in_c / 100.0, 4),
                "totalCostCents": total_c,
                "totalCostDollars": round(total_c / 100.0, 4),
                "eventCount": combined_counts.get(model, 0),
                "inputTokens": tok.get("inputTokens", 0),
                "outputTokens": tok.get("outputTokens", 0),
                "cacheReadTokens": tok.get("cacheReadTokens", 0),
                "cacheWriteTokens": tok.get("cacheWriteTokens", 0),
            }
        )
    combined_rows.sort(key=lambda r: r["totalCostCents"], reverse=True)

    daily_rows: list[dict[str, Any]] = []
    for day, vals in daily_maps.items():
        if day == "unknown":
            continue
        on_c = float(vals.get("onDemandCostCents") or 0)
        in_c = float(vals.get("includedCostCents") or 0)
        models = daily_models.get(day) or {"onDemand": {}, "included": {}}
        top_ond = sorted(models["onDemand"].items(), key=lambda x: -x[1])
        daily_rows.append(
            {
                "date": day,
                "onDemandCostCents": on_c,
                "includedCostCents": in_c,
                "totalCostCents": on_c + in_c,
                "eventCount": int(vals.get("eventCount") or 0),
                "topOnDemandModel": top_ond[0][0] if top_ond else None,
                "onDemandModels": [
                    {"model": m, "costCents": c} for m, c in top_ond
                ],
            }
        )
    daily_rows.sort(key=lambda r: r["date"])

    return {
        "eventCount": len(events),
        "kindTotalsCents": kind_totals,
        "onDemandModels": on_demand_rows,
        "includedModels": included_rows,
        "models": combined_rows,
        "daily": daily_rows,
        "onDemandTotalCents": sum(cost_maps["onDemand"].values()),
        "includedTotalCents": sum(cost_maps["included"].values()),
    }


def normalize_models(agg: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not agg:
        return []
    rows: list[dict[str, Any]] = []
    total_cost = as_float(agg.get("totalCostCents"))
    for item in agg.get("aggregations") or []:
        cost = as_float(item.get("totalCents"))
        share = (cost / total_cost * 100.0) if total_cost > 0 else 0.0
        rows.append(
            {
                "model": item.get("modelIntent") or item.get("model") or "unknown",
                "tier": item.get("tier"),
                "costCents": cost,
                "costDollars": round(cost / 100.0, 4),
                "sharePercent": round(share, 2),
                "inputTokens": as_int(item.get("inputTokens")),
                "outputTokens": as_int(item.get("outputTokens")),
                "cacheReadTokens": as_int(item.get("cacheReadTokens")),
                "cacheWriteTokens": as_int(item.get("cacheWriteTokens")),
            }
        )
    rows.sort(key=lambda r: r["costCents"], reverse=True)
    return rows


def build_summary(
    period: dict[str, Any],
    plan: dict[str, Any],
    event_agg: dict[str, Any] | None,
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    usage = period.get("planUsage") or {}
    spend = period.get("spendLimitUsage") or {}
    included_limit = as_float(usage.get("limit"))
    included_used = as_float(usage.get("includedSpend"))
    included_left = as_float(remaining_cents(usage))
    individual_limit = as_float(spend.get("individualLimit"))
    individual_used = as_float(spend.get("individualUsed"))
    individual_left = as_float(spend.get("individualRemaining"))
    if individual_left == 0 and individual_limit and spend.get("individualRemaining") is None:
        individual_left = max(0.0, individual_limit - individual_used)

    on_demand_event = as_float((event_agg or {}).get("onDemandTotalCents"))
    included_event = as_float((event_agg or {}).get("includedTotalCents"))
    unified_used = included_used + individual_used
    if unified_used <= 0 and (on_demand_event + included_event) > 0:
        unified_used = on_demand_event + included_used

    top_on_demand = None
    on_rows = (event_agg or {}).get("onDemandModels") or []
    if on_rows:
        top_on_demand = on_rows[0].get("model")

    return {
        "planName": plan.get("planName"),
        "planPrice": plan.get("price"),
        "includedLimitCents": included_limit,
        "includedUsedCents": included_used,
        "includedRemainingCents": included_left,
        "bonusSpendCents": as_float(usage.get("bonusSpend")),
        "individualLimitCents": individual_limit,
        "individualUsedCents": individual_used,
        "individualRemainingCents": individual_left,
        "pooledUsedCents": as_float(spend.get("pooledUsed")) if spend else None,
        "pooledLimitCents": as_float(spend.get("pooledLimit"))
        if spend.get("pooledLimit") is not None
        else None,
        "pooledRemainingCents": as_float(spend.get("pooledRemaining"))
        if spend.get("pooledRemaining") is not None
        else None,
        "onDemandTotalSpendCents": as_float(spend.get("totalSpend")) if spend else None,
        "unifiedUsedCents": unified_used,
        "unifiedUsedDollars": dollars_from_cents(unified_used),
        "onDemandEventCostCents": on_demand_event,
        "onDemandEventCostDollars": dollars_from_cents(on_demand_event),
        "includedEventCostCents": included_event,
        "includedEventCostDollars": dollars_from_cents(included_event),
        "autoPercentUsed": as_float(usage.get("autoPercentUsed")),
        "apiPercentUsed": as_float(usage.get("apiPercentUsed")),
        "totalPercentUsed": as_float(usage.get("totalPercentUsed")),
        "modelCount": len(models),
        "topOnDemandModel": top_on_demand,
        "topModel": models[0]["model"] if models else top_on_demand,
        "displayMessage": period.get("displayMessage"),
        "billingCycleStart": period.get("billingCycleStart"),
        "billingCycleEnd": period.get("billingCycleEnd"),
        "eventCount": (event_agg or {}).get("eventCount"),
    }


def build_report(auth: dict[str, str], token: str) -> dict[str, Any]:
    period = connect_post(
        "aiserver.v1.DashboardService/GetCurrentPeriodUsage", token
    )
    plan_raw = connect_post("aiserver.v1.DashboardService/GetPlanInfo", token)
    plan = plan_raw.get("planInfo") or plan_raw
    try:
        policy = connect_post(
            "aiserver.v1.DashboardService/GetUsageLimitPolicyStatus", token
        )
    except SystemExit:
        policy = None

    me: dict[str, Any] | None = None
    try:
        me = web_get("/api/auth/me", token)
    except SystemExit as e:
        sys.stderr.write(f"Warning: /api/auth/me failed: {e}\n")

    user_id = as_int((me or {}).get("id"))
    start = period.get("billingCycleStart")
    end = period.get("billingCycleEnd")

    event_agg: dict[str, Any] | None = None
    legacy_agg: dict[str, Any] | None = None
    if user_id and start and end:
        try:
            events = fetch_filtered_usage_events(token, user_id, start, end)
            event_agg = aggregate_events_by_bucket(events)
        except SystemExit as e:
            sys.stderr.write(f"Warning: filtered events unavailable: {e}\n")
            try:
                legacy_agg = web_post(
                    "/api/dashboard/get-aggregated-usage-events",
                    token,
                    {
                        "teamId": 0,
                        "startDate": str(start),
                        "endDate": str(end),
                        "userId": user_id,
                    },
                )
            except SystemExit as e2:
                sys.stderr.write(f"Warning: model aggregation unavailable: {e2}\n")

    if event_agg:
        on_demand_models = event_agg["onDemandModels"]
        included_models = event_agg["includedModels"]
        models = event_agg["models"]
        daily = event_agg.get("daily") or []
    else:
        legacy_models = normalize_models(legacy_agg)
        on_demand_models = []
        included_models = legacy_models
        daily = []
        models = [
            {
                "model": m["model"],
                "onDemandCostCents": 0.0,
                "onDemandCostDollars": 0.0,
                "includedCostCents": m["costCents"],
                "includedCostDollars": m["costDollars"],
                "totalCostCents": m["costCents"],
                "totalCostDollars": m["costDollars"],
                "eventCount": 0,
                "inputTokens": m["inputTokens"],
                "outputTokens": m["outputTokens"],
                "cacheReadTokens": m["cacheReadTokens"],
                "cacheWriteTokens": m["cacheWriteTokens"],
            }
            for m in legacy_models
        ]

    summary = build_summary(period, plan, event_agg, models)

    email = auth.get("cursorAuth/cachedEmail") or (me or {}).get("email")
    membership = auth.get("cursorAuth/stripeMembershipType")
    try:
        sub = jwt_payload(token).get("sub")
    except Exception:
        sub = (me or {}).get("sub")

    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "account": {
            "email": email,
            "membershipType": membership,
            "userId": user_id or None,
            "sub": sub,
        },
        "planInfo": plan,
        "periodUsage": period,
        "limitPolicy": policy,
        "eventAggregation": event_agg,
        "onDemandModels": on_demand_models,
        "includedModels": included_models,
        "models": models,
        "daily": daily,
        "summary": summary,
    }


def format_human(report: dict[str, Any]) -> str:
    acct = report.get("account") or {}
    plan = report.get("planInfo") or {}
    period = report.get("periodUsage") or {}
    usage = period.get("planUsage") or {}
    spend = period.get("spendLimitUsage") or {}
    policy = report.get("limitPolicy") or {}
    summary = report.get("summary") or {}
    on_demand_models = report.get("onDemandModels") or []
    included_models = report.get("includedModels") or []
    models = report.get("models") or []

    lines = [
        "Cursor 用量",
        "==========",
        f"账号:       {acct.get('email') or '未知'}",
        f"会员类型:   {acct.get('membershipType') or '未知'}",
        f"套餐:       {plan.get('planName') or '未知'} ({plan.get('price') or '无'})",
        f"套餐额度:   {cents(plan.get('includedAmountCents'))} / 周期",
        f"计费周期:   {ms_to_local(period.get('billingCycleStart'))} -> {ms_to_local(period.get('billingCycleEnd'))}",
        "",
        "统一已用量（本周期）",
        "--------------------",
        f"套餐内已用:     {cents(summary.get('includedUsedCents'))} / {cents(summary.get('includedLimitCents'))}  （剩余 {cents(summary.get('includedRemainingCents'))}）",
        f"个人按需已用:   {cents(summary.get('individualUsedCents'))} / {cents(summary.get('individualLimitCents'))}  （剩余 {cents(summary.get('individualRemainingCents'))}）",
        f"统一已用合计:   {cents(summary.get('unifiedUsedCents'))}",
    ]

    if summary.get("bonusSpendCents"):
        lines.append(f"赠送用量:       {cents(summary.get('bonusSpendCents'))}")

    lines.extend(
        [
            "",
            "套餐内占用",
            "----------",
            f"合计:       {pct(usage.get('totalPercentUsed'))}",
            f"Auto:       {pct(usage.get('autoPercentUsed'))}",
            f"API:        {pct(usage.get('apiPercentUsed'))}",
        ]
    )

    if spend:
        lines.extend(
            [
                "",
                "按需 / 团队",
                "-----------",
                f"限额类型:   {spend.get('limitType') or '无'}",
            ]
        )
        if spend.get("pooledUsed") is not None:
            lines.append(
                f"团队池已用: {cents(spend.get('pooledUsed'))}"
            )

    def append_model_section(title: str, rows: list[dict[str, Any]], total_cents: Any) -> None:
        if not rows:
            return
        lines.extend(["", title, "-" * len(title)])
        lines.append(
            f"{'模型':<36} {'成本':>10} {'占比':>8} {'次数':>6} {'输入':>8} {'输出':>8}"
        )
        for m in rows:
            lines.append(
                f"{str(m['model'])[:36]:<36} "
                f"{cents(m['costCents']):>10} "
                f"{m.get('sharePercent', 0):>7.1f}% "
                f"{m.get('eventCount', 0):>6} "
                f"{fmt_tokens(m.get('inputTokens')):>8} "
                f"{fmt_tokens(m.get('outputTokens')):>8}"
            )
        lines.append(f"{'合计':<36} {cents(total_cents):>10}")

    append_model_section(
        "个人按需 · 按模型",
        on_demand_models,
        summary.get("onDemandEventCostCents") or summary.get("individualUsedCents"),
    )
    append_model_section(
        "套餐内 · 按模型",
        included_models,
        summary.get("includedEventCostCents"),
    )

    if models and (on_demand_models or included_models):
        lines.extend(
            [
                "",
                "合计 · 按模型",
                "-------------",
                f"{'模型':<36} {'按需':>10} {'套餐内':>10} {'合计':>10}",
            ]
        )
        for m in models:
            lines.append(
                f"{str(m['model'])[:36]:<36} "
                f"{cents(m.get('onDemandCostCents')):>10} "
                f"{cents(m.get('includedCostCents')):>10} "
                f"{cents(m.get('totalCostCents')):>10}"
            )

    if policy:
        lines.extend(
            [
                "",
                "限额策略",
                "--------",
                f"类型:       {policy.get('limitType') or '无'}",
            ]
        )
        btn = policy.get("primaryButton") or {}
        if btn.get("label"):
            lines.append(f"建议操作:   {btn.get('label')}")

    lines.append("")
    lines.append("面板: https://cursor.com/dashboard/usage")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show Cursor plan usage for the signed-in account"
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument(
        "--no-models",
        action="store_true",
        help="Skip per-model aggregation (faster, plan totals only)",
    )
    parser.add_argument(
        "--no-persist-refresh",
        action="store_true",
        help="Do not write refreshed tokens back to state.vscdb",
    )
    args = parser.parse_args()

    db_path = state_db_path()
    auth = read_auth_keys(db_path)
    token = resolve_token(auth, db_path, persist=not args.no_persist_refresh)

    if args.no_models:
        period = connect_post(
            "aiserver.v1.DashboardService/GetCurrentPeriodUsage", token
        )
        plan_raw = connect_post("aiserver.v1.DashboardService/GetPlanInfo", token)
        plan = plan_raw.get("planInfo") or plan_raw
        report = {
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "account": {
                "email": auth.get("cursorAuth/cachedEmail"),
                "membershipType": auth.get("cursorAuth/stripeMembershipType"),
            },
            "planInfo": plan,
            "periodUsage": period,
            "onDemandModels": [],
            "includedModels": [],
            "models": [],
            "summary": build_summary(period, plan, None, []),
        }
    else:
        report = build_report(auth, token)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_human(report))
    return 0


if __name__ == "__main__":
    try:
        # Prefer UTF-8 on Windows consoles so Chinese labels render correctly.
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
                sys.stderr.reconfigure(encoding="utf-8")
            except Exception:
                pass
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
