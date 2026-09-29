import { describe, expect, it } from "vitest";
import {
  burnRate,
  buildSeries,
  concentration,
  filterRange,
  longestStreak,
  movingAverage,
  peak,
  stdev,
  weekdayAverages,
  type DayPoint,
} from "../src/analysis";

const pt = (date: string, total: number, ond = 0): DayPoint => ({ date, total, ond, inc: total - ond, events: total ? 1 : 0, tokens: total * 1000 });

describe("analysis", () => {
  it("streak, peak and stdev use calendar days", () => {
    const points = [pt("2026-09-21", 5), pt("2026-09-22", 0), pt("2026-09-23", 2), pt("2026-09-24", 9), pt("2026-09-25", 1)];
    expect(longestStreak(points)).toBe(3);
    expect(peak(points)?.date).toBe("2026-09-24");
    expect(stdev([2, 4, 4, 4, 5, 5, 7, 9])).toBe(2);
  });

  it("moving average and weekday averages include zero days", () => {
    expect(movingAverage([7, 0, 14], 2)).toEqual([7, 3.5, 7]);
    // 2026-09-27 is a Sunday.
    const w = weekdayAverages([pt("2026-09-27", 10), pt("2026-10-04", 0), pt("2026-09-28", 6)]);
    expect(w[0]).toBe(5);
    expect(w[1]).toBe(6);
  });

  it("concentration: top3, HHI and models covering 80%", () => {
    const c = concentration([50, 30, 10, 10]);
    expect(c.top3).toBeCloseTo(0.9);
    expect(c.hhi).toBeCloseTo(0.25 + 0.09 + 0.01 + 0.01);
    expect(c.cover80).toBe(2);
  });

  it("burn rate over 7 calendar days", () => {
    const last7 = [0, 0, 0, 0, 0, 70, 70].map((v, i) => pt(`2026-09-2${i}`, v, v));
    expect(burnRate(last7, "ond", 200)).toEqual({ perDay: 20, daysToEmpty: 10 });
    expect(burnRate([pt("2026-09-20", 0)], "ond", 200).daysToEmpty).toBeNull();
  });

  it("range filter counts exactly N calendar days", () => {
    const points = Array.from({ length: 20 }, (_, i) => pt(`2026-09-${String(i + 1).padStart(2, "0")}`, 1));
    expect(filterRange(points, "7").map((p) => p.date)).toEqual(points.slice(-7).map((p) => p.date));
    expect(filterRange(points, "custom", "2026-09-03", "2026-09-05")).toHaveLength(3);
  });

  it("series: week-over-week and cycle days", () => {
    const start = new Date(2026, 8, 1).getTime();
    const report: any = {
      summary: { billingCycleStart: String(start), billingCycleEnd: String(start + 30 * 86_400_000) },
      daily: [
        { date: "2026-09-03", onDemandCostCents: 0, includedCostCents: 100, eventCount: 1 },
        { date: "2026-09-12", onDemandCostCents: 50, includedCostCents: 100, eventCount: 2 },
      ],
    };
    const s = buildSeries(report, new Date(2026, 8, 14, 12).getTime());
    expect(s.points).toHaveLength(14);
    expect(s.last7Sum).toBe(150);
    expect(s.wow).toBe(50);
    expect(s.cycleDays).toBe(30);
    expect(s.active).toHaveLength(2);

    const early = buildSeries(report, new Date(2026, 8, 6, 12).getTime());
    expect(early.wow).toBeNull();
  });
});
