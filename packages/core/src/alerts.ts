import { L } from "./i18n";
import type { AlertsState, WidgetSummary } from "./types";

export const DEFAULT_THRESHOLDS = [95, 80] as const;
export const PACE_ALERT_DAYS = 3;
const DAY_MS = 86_400_000;

export interface Alert {
  key: string;
  title: string;
  message: string;
}

export interface AlertConfig {
  /** Percent thresholds, any order (default 80 / 95). */
  thresholds?: number[];
  /** Personal on-demand budget in cents; replaces the Cursor limit when lower. */
  onDemandBudgetCents?: number;
}

const usd = (cents: number) => `$${(cents / 100).toFixed(2)}`;
const num = (v: unknown) => {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
};

export function normalizeThresholds(values?: number[]): number[] {
  const clean = (values && values.length ? values : [...DEFAULT_THRESHOLDS])
    .map((v) => Math.round(Number(v)))
    .filter((v) => Number.isFinite(v) && v >= 1 && v <= 100);
  return [...new Set(clean)].sort((a, b) => b - a);
}

/** The on-demand limit alerts use: the personal budget when set and lower than Cursor's limit. */
export function effectiveOnDemandLimit(summary: WidgetSummary, config: AlertConfig = {}): { limit: number; budget: boolean } {
  const limit = num(summary.individualLimitCents);
  const budget = num(config.onDemandBudgetCents);
  if (budget > 0 && (limit <= 0 || budget < limit)) return { limit: budget, budget: true };
  return { limit, budget: false };
}

/** Every alert whose condition currently holds (sent-state is not applied). */
export function evaluateAlerts(summary: WidgetSummary, nowMs = Date.now(), config: AlertConfig = {}): Alert[] {
  const alerts: Alert[] = [];
  const thresholds = normalizeThresholds(config.thresholds);
  const ond = effectiveOnDemandLimit(summary, config);
  const buckets = [
    [ond.budget ? "ondb" : "ond", ond.budget ? L("按需预算", "on-demand budget") : L("个人按需", "on-demand usage"), summary.individualUsedCents, ond.limit],
    ["inc", L("套餐内额度", "included usage"), summary.includedUsedCents, summary.includedLimitCents],
  ] as const;
  const split = summary.autoPercentUsed != null || summary.apiPercentUsed != null;
  for (const [prefix, label, usedRaw, limitRaw] of buckets) {
    if (prefix === "inc" && split) continue;
    const used = num(usedRaw);
    const limit = num(limitRaw);
    if (limit <= 0) continue;
    const ratio = used / limit;
    const threshold = thresholds.find((t) => ratio * 100 >= t);
    if (threshold !== undefined) {
      alerts.push({
        key: `${prefix}-${threshold}`,
        title: L(`Cursor ${label}已用 ${Math.round(ratio * 100)}%`, `Cursor ${label} at ${Math.round(ratio * 100)}%`),
        message: L(
          `已用 ${usd(used)} / ${usd(limit)}，剩余 ${usd(Math.max(0, limit - used))}`,
          `${usd(used)} of ${usd(limit)} used, ${usd(Math.max(0, limit - used))} left`,
        ),
      });
    }
  }
  if (split) {
    const pools = [
      [
        "auto",
        L("套餐内 Cursor 模型（Auto）", "included Cursor models (Auto)"),
        summary.autoPercentUsed,
        L("之后的 Auto / Composer 请求将计入个人按需", "further Auto / Composer requests are billed on-demand"),
      ],
      [
        "api",
        L("套餐内其他模型（API）", "included other models (API)"),
        summary.apiPercentUsed,
        L("之后指定模型的请求将计入个人按需", "further requests to named models are billed on-demand"),
      ],
    ] as const;
    for (const [prefix, label, pctRaw, after] of pools) {
      const pct = num(pctRaw);
      const threshold = thresholds.find((t) => pct >= t);
      if (threshold === undefined) continue;
      const left = Math.max(0, 100 - pct).toFixed(0);
      alerts.push({
        key: `${prefix}-${threshold}`,
        title: L(`Cursor ${label}已用 ${Math.round(pct)}%`, `Cursor ${label} at ${Math.round(pct)}%`),
        message: pct >= 100 ? L(`额度已用完，${after}`, `Used up; ${after}`) : L(`剩余约 ${left}%`, `About ${left}% left`),
      });
    }
  }

  const start = num(summary.billingCycleStart);
  const end = num(summary.billingCycleEnd);
  const used = num(summary.individualUsedCents);
  const limit = ond.limit;
  const remaining = Math.max(0, limit - used);
  const hasCycle = summary.billingCycleStart != null && summary.billingCycleStart !== "" && end > start;
  // Past the top threshold the user has just been warned; a pace alert adds nothing.
  const belowTop = limit > 0 && (used / limit) * 100 < (thresholds[0] ?? 95);
  if (hasCycle && belowTop && used > 0 && remaining > 0 && nowMs > start) {
    const daysElapsed = Math.max(1, (Math.min(nowMs, end) - start) / DAY_MS);
    const daysLeft = Math.max(0, (end - nowMs) / DAY_MS);
    const burnPerDay = used / daysElapsed;
    const daysToEmpty = remaining / burnPerDay;
    if (daysToEmpty < Math.min(PACE_ALERT_DAYS, daysLeft)) {
      alerts.push({
        key: "ond-pace",
        title: ond.budget
          ? L("Cursor 按需预算即将用完", "Cursor on-demand budget running out")
          : L("Cursor 个人按需额度即将用完", "Cursor on-demand limit running out"),
        message: L(
          `按本周期日均 ${usd(burnPerDay)} 的节奏，约 ${daysToEmpty.toFixed(1)} 天后用完，距周期结束还有 ${daysLeft.toFixed(1)} 天`,
          `At ${usd(burnPerDay)}/day this cycle it runs out in about ${daysToEmpty.toFixed(1)} days; ${daysLeft.toFixed(1)} days remain in the cycle`,
        ),
      });
    }
  }
  return alerts;
}

/**
 * Filter out alerts already sent this cycle. Crossing a threshold also marks
 * every lower threshold as sent so a later dip and rise does not produce a
 * stale lower-threshold alert.
 */
export function pendingAlerts(
  summary: WidgetSummary,
  state: AlertsState,
  nowMs = Date.now(),
  config: AlertConfig = {},
): { toSend: Alert[]; state: AlertsState } {
  const cycle = String(summary.billingCycleStart ?? "");
  const sent = new Set(state.cycle === cycle ? state.sent || [] : []);
  const thresholds = normalizeThresholds(config.thresholds);
  const toSend = evaluateAlerts(summary, nowMs, config).filter((a) => !sent.has(a.key));
  for (const alert of toSend) {
    sent.add(alert.key);
    const [prefix, level] = alert.key.split("-");
    if (/^\d+$/.test(level)) {
      for (const t of thresholds) if (t <= Number(level)) sent.add(`${prefix}-${t}`);
    }
  }
  return { toSend, state: { ...state, cycle, sent: [...sent].sort() } };
}
