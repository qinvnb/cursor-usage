"""Quota alerts: decide which notifications to show, at most once per billing cycle."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

THRESHOLDS = (0.95, 0.8)
PACE_ALERT_DAYS = 3.0
DAY_MS = 86_400_000


@dataclass(frozen=True)
class Alert:
    key: str
    title: str
    message: str


def _usd(cents: float) -> str:
    return f"${cents / 100:.2f}"


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def evaluate(summary: dict[str, Any], *, now_ms: float | None = None) -> list[Alert]:
    """Return every alert whose condition currently holds (sent-state is not applied)."""
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    alerts: list[Alert] = []

    buckets = (
        ("ond", "个人按需", "individualUsedCents", "individualLimitCents"),
        ("inc", "套餐内额度", "includedUsedCents", "includedLimitCents"),
    )
    for prefix, label, used_key, limit_key in buckets:
        used, limit = _num(summary.get(used_key)), _num(summary.get(limit_key))
        if limit <= 0:
            continue
        ratio = used / limit
        for threshold in THRESHOLDS:
            if ratio >= threshold:
                alerts.append(
                    Alert(
                        key=f"{prefix}-{int(threshold * 100)}",
                        title=f"Cursor {label}已用 {ratio * 100:.0f}%",
                        message=f"已用 {_usd(used)} / {_usd(limit)}，剩余 {_usd(max(0.0, limit - used))}",
                    )
                )
                break  # only the highest crossed threshold

    start = _num(summary.get("billingCycleStart"))
    end = _num(summary.get("billingCycleEnd"))
    used = _num(summary.get("individualUsedCents"))
    limit = _num(summary.get("individualLimitCents"))
    remaining = max(0.0, limit - used)
    has_cycle = summary.get("billingCycleStart") not in (None, "") and end > start
    # Past the top threshold the user has just been warned; a pace alert adds nothing.
    below_top = limit > 0 and used / limit < THRESHOLDS[0]
    if has_cycle and below_top and used > 0 and remaining > 0 and now_ms > start:
        days_elapsed = max(1.0, (min(now_ms, end) - start) / DAY_MS)
        days_left = max(0.0, (end - now_ms) / DAY_MS)
        burn_per_day = used / days_elapsed
        days_to_empty = remaining / burn_per_day
        if days_to_empty < min(PACE_ALERT_DAYS, days_left):
            alerts.append(
                Alert(
                    key="ond-pace",
                    title="Cursor 个人按需额度即将用完",
                    message=(
                        f"按本周期日均 {_usd(burn_per_day)} 的节奏，约 {days_to_empty:.1f} 天后用完，"
                        f"距周期结束还有 {days_left:.1f} 天"
                    ),
                )
            )
    return alerts


def pending_alerts(
    summary: dict[str, Any], state: dict[str, Any], *, now_ms: float | None = None
) -> tuple[list[Alert], dict[str, Any]]:
    """Filter out alerts already sent this cycle. Returns (to_send, new_state).

    Crossing 95% also marks 80% as sent so a later dip and rise does not
    produce a stale lower-threshold notification.
    """
    cycle = str(summary.get("billingCycleStart") or "")
    sent = set(state.get("sent") or []) if state.get("cycle") == cycle else set()
    to_send = [a for a in evaluate(summary, now_ms=now_ms) if a.key not in sent]
    for alert in to_send:
        sent.add(alert.key)
        prefix, _, level = alert.key.partition("-")
        if level.isdigit():
            sent.update(f"{prefix}-{int(t * 100)}" for t in THRESHOLDS if t * 100 <= int(level))
    return to_send, {"cycle": cycle, "sent": sorted(sent)}
