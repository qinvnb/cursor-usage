/**
 * The dashboard's analysis metrics (ported from the v1 multi-page dashboard).
 * Pure functions over calendar-complete daily rows, so they are unit-testable.
 */
import { localDateKey, type DailyRow, type ModelRow, type Report } from "@cursor-usage/core";
import { completeDaily, totalTokens } from "@cursor-usage/core";

const DAY = 86_400_000;

export interface DayPoint {
  date: string;
  total: number;
  ond: number;
  inc: number;
  events: number;
  /** All tokens that day (0 when the report predates token tracking). */
  tokens: number;
}

export interface Series {
  /** Cycle start .. today, zero-filled. */
  points: DayPoint[];
  active: DayPoint[];
  last7: DayPoint[];
  prev7: DayPoint[];
  last14: DayPoint[];
  last7Sum: number;
  /** Week-over-week change in percent; null when there is nothing to compare. */
  wow: number | null;
  daysElapsed: number | null;
  daysLeft: number | null;
  cycleDays: number | null;
}

export const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
export const sumBy = <T>(rows: T[], f: (r: T) => number) => rows.reduce((a, r) => a + f(r), 0);

export function toPoints(rows: DailyRow[], dailyTokens?: Report["dailyTokens"]): DayPoint[] {
  return rows.map((r) => ({
    date: r.date,
    total: Number(r.onDemandCostCents || 0) + Number(r.includedCostCents || 0),
    ond: Number(r.onDemandCostCents || 0),
    inc: Number(r.includedCostCents || 0),
    events: Number(r.eventCount || 0),
    tokens: totalTokens(dailyTokens?.[r.date]),
  }));
}

export function buildSeries(report: Report, now = Date.now()): Series {
  const points = toPoints(completeDaily(report, { nowMs: now }), report.dailyTokens);
  const start = Number(report.summary?.billingCycleStart || 0);
  const end = Number(report.summary?.billingCycleEnd || 0);
  let daysElapsed: number | null = null;
  let daysLeft: number | null = null;
  let cycleDays: number | null = null;
  if (start && end && end > start) {
    daysLeft = Math.max(0, Math.ceil((end - now) / DAY));
    daysElapsed = Math.max(1, Math.ceil((Math.min(now, end) - start) / DAY));
    cycleDays = Math.max(1, Math.ceil((end - start) / DAY));
  }
  const last7 = points.slice(-7);
  const prev7 = points.slice(-14, -7);
  const last7Sum = sumBy(last7, (p) => p.total);
  const prev7Sum = sumBy(prev7, (p) => p.total);
  // Only compare against a complete prior week inside this cycle.
  const wow = prev7.length < 7 ? null : prev7Sum > 0 ? ((last7Sum - prev7Sum) / prev7Sum) * 100 : last7Sum > 0 ? 100 : null;
  return {
    points,
    active: points.filter((p) => p.total > 0),
    last7,
    prev7,
    last14: points.slice(-14),
    last7Sum,
    wow,
    daysElapsed,
    daysLeft,
    cycleDays,
  };
}

export function peak(points: DayPoint[], key: "total" | "ond" | "inc" = "total"): DayPoint | null {
  let best: DayPoint | null = null;
  for (const p of points) if (p[key] > 0 && (!best || p[key] > best[key])) best = p;
  return best;
}

export function stdev(values: number[]): number {
  if (!values.length) return 0;
  const mean = sum(values) / values.length;
  return Math.sqrt(sum(values.map((v) => (v - mean) ** 2)) / values.length);
}

export function movingAverage(values: number[], window: number): number[] {
  return values.map((_, i) => {
    const slice = values.slice(Math.max(0, i - window + 1), i + 1);
    return sum(slice) / slice.length;
  });
}

export function longestStreak(points: DayPoint[]): number {
  let run = 0;
  let best = 0;
  for (const p of points) {
    run = p.total > 0 ? run + 1 : 0;
    best = Math.max(best, run);
  }
  return best;
}

/** Average total per weekday (0 = Sunday), zero days included. */
export function weekdayAverages(points: DayPoint[]): number[] {
  const totals = [0, 0, 0, 0, 0, 0, 0];
  const counts = [0, 0, 0, 0, 0, 0, 0];
  for (const p of points) {
    const wd = new Date(`${p.date}T00:00:00`).getDay();
    totals[wd] += p.total;
    counts[wd] += 1;
  }
  return totals.map((t, i) => (counts[i] ? t / counts[i] : 0));
}

export interface Concentration {
  shares: number[];
  /** Herfindahl index over shares (0-1). */
  hhi: number;
  top3: number;
  /** Number of models covering 80% of cost. */
  cover80: number;
}

export function concentration(costs: number[]): Concentration {
  const total = sum(costs) || 1;
  const shares = costs.map((c) => c / total);
  let running = 0;
  let cover80 = costs.length;
  for (let i = 0; i < shares.length; i++) {
    running += shares[i];
    if (running >= 0.8) {
      cover80 = i + 1;
      break;
    }
  }
  return {
    shares,
    hhi: sum(shares.map((s) => s * s)),
    top3: sum(shares.slice(0, 3)),
    cover80,
  };
}

/** Daily burn over the last 7 calendar days and the days until `remaining` runs out. */
export function burnRate(last7: DayPoint[], key: "ond" | "inc", remaining: number): { perDay: number; daysToEmpty: number | null } {
  const perDay = sumBy(last7, (p) => p[key]) / Math.max(1, last7.length);
  return { perDay, daysToEmpty: perDay > 0 ? remaining / perDay : null };
}

export type RangeMode = "cycle" | "7" | "14" | "30" | "custom";

export function filterRange(points: DayPoint[], mode: RangeMode, from = "", to = ""): DayPoint[] {
  if (mode === "cycle") return points;
  if (mode === "custom") return points.filter((p) => (!from || p.date >= from) && (!to || p.date <= to));
  if (!points.length) return points;
  const end = new Date(`${points[points.length - 1].date}T00:00:00`);
  end.setDate(end.getDate() - (Number(mode) - 1));
  const startKey = localDateKey(end);
  return points.filter((p) => p.date >= startKey);
}

export function costModels(report: Report, minCents = 1): ModelRow[] {
  return (report.models || []).filter((m) => m.totalCostCents > minCents).sort((a, b) => b.totalCostCents - a.totalCostCents);
}

export type Trend = "up" | "down" | "flat";
export const trendOf = (pct: number | null, threshold = 3): Trend => (pct === null ? "flat" : pct > threshold ? "up" : pct < -threshold ? "down" : "flat");
