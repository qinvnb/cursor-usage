import type { DailyRow, Report } from "./types";

/** YYYY-MM-DD in local time (toISOString() would shift the day in UTC+N zones). */
export function localDateKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

const emptyDay = (date: string): DailyRow => ({
  date,
  onDemandCostCents: 0,
  includedCostCents: 0,
  totalCostCents: 0,
  eventCount: 0,
  topOnDemandModel: null,
  onDemandModels: [],
});

/**
 * Every calendar day of the billing cycle, zero-filled. The API only emits
 * days that had events; without this, "last 7 days", streaks and averages
 * would be computed over active days only.
 *
 * With `throughEnd` the whole cycle is returned (future days as zero rows),
 * otherwise it stops at today.
 */
export function completeDaily(report: Pick<Report, "daily" | "summary">, { throughEnd = false, nowMs = Date.now() } = {}): DailyRow[] {
  const rows = [...(report.daily || [])].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const startMs = Number(report.summary?.billingCycleStart || 0);
  const endMs = Number(report.summary?.billingCycleEnd || 0);
  if (!startMs || !endMs || endMs <= startMs) return rows;

  const byDate = new Map(rows.map((r) => [r.date, r]));
  const cursor = new Date(startMs);
  cursor.setHours(0, 0, 0, 0);
  const lastKey = localDateKey(new Date(throughEnd ? endMs - 1 : Math.min(nowMs, endMs - 1)));
  const out: DailyRow[] = [];
  for (let guard = 0; guard < 400; guard++) {
    const key = localDateKey(cursor);
    if (key > lastKey) break;
    out.push(byDate.get(key) || emptyDay(key));
    cursor.setDate(cursor.getDate() + 1);
  }
  const first = out[0]?.date;
  for (const r of rows) if ((first && r.date < first) || r.date > lastKey) out.push(r);
  out.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return out;
}
