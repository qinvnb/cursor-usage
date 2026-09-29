import { completeDaily, localDateKey, type DailyRow, type Report } from "@cursor-usage/core";

const DAY = 86_400_000;

export interface Cycle {
  startMs: number;
  endMs: number;
  totalDays: number;
  /** Fractional days elapsed, clamped to the cycle. */
  elapsedDays: number;
  dayNumber: number;
  daysLeft: number;
  fraction: number;
}

export function cycleOf(report: Report, now = Date.now()): Cycle | null {
  const startMs = Number(report.summary?.billingCycleStart || 0);
  const endMs = Number(report.summary?.billingCycleEnd || 0);
  if (!startMs || !endMs || endMs <= startMs) return null;
  const totalDays = Math.max(1, Math.round((endMs - startMs) / DAY));
  const elapsedMs = Math.min(Math.max(now - startMs, 0), endMs - startMs);
  return {
    startMs,
    endMs,
    totalDays,
    elapsedDays: elapsedMs / DAY,
    dayNumber: Math.min(totalDays, Math.floor(elapsedMs / DAY) + 1),
    daysLeft: Math.max(0, (endMs - now) / DAY),
    fraction: elapsedMs / (endMs - startMs),
  };
}

export interface Quota {
  usedCents: number;
  limitCents: number;
  remainingCents: number;
  ratio: number;
  /** Straight-line projection of spend at cycle end, from the average daily pace so far. */
  projectedCents: number | null;
  level: "ok" | "warn" | "danger";
}

function level(ratio: number): Quota["level"] {
  if (ratio >= 0.9) return "danger";
  if (ratio >= 0.7) return "warn";
  return "ok";
}

export function quota(used: number, limit: number, remaining: number, cycle: Cycle | null): Quota {
  const ratio = limit > 0 ? used / limit : 0;
  // Needs at least half a day of data before a projection means anything.
  const projected = cycle && cycle.elapsedDays >= 0.5 ? (used / cycle.elapsedDays) * cycle.totalDays : null;
  return { usedCents: used, limitCents: limit, remainingCents: remaining, ratio, projectedCents: projected, level: level(ratio) };
}

export interface DaySeries {
  rows: DailyRow[];
  todayKey: string;
  maxTotal: number;
  activeDays: number;
  totalCents: number;
  events: number;
}

export function daySeries(report: Report, now = Date.now()): DaySeries {
  const rows = completeDaily(report, { throughEnd: true, nowMs: now });
  const todayKey = localDateKey(new Date(now));
  let maxTotal = 0;
  let activeDays = 0;
  let totalCents = 0;
  let events = 0;
  for (const r of rows) {
    const t = r.onDemandCostCents + r.includedCostCents;
    maxTotal = Math.max(maxTotal, t);
    if (t > 0) activeDays += 1;
    totalCents += t;
    events += r.eventCount;
  }
  return { rows, todayKey, maxTotal, activeDays, totalCents, events };
}

/** Round a chart maximum up to a readable tick. */
export function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  const n = value / exp;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return step * exp;
}
