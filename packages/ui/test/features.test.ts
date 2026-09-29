import { describe, expect, it } from "vitest";
import { RemoteEngine } from "../src/api";
import { vendorOf } from "../src/components/kit";
import { samePointComparison } from "../src/components/Pages";
import { cacheHitRate, costPerRequest } from "../src/components/Tables";

const pt = (date: string, total: number) => ({ date, total, ond: 0, inc: total, events: 1, tokens: 0 });

describe("same point in the previous cycle", () => {
  it("compares running totals at the same cycle day", () => {
    const history: any[] = [{ cycleStart: "1", dailyTotals: [100, 100, 100, 100] }];
    const r = samePointComparison(history, [pt("a", 150), pt("b", 150)]);
    expect(r).toEqual({ prev: 200, cur: 300, pct: 50 });
  });

  it("is unavailable without per-day history", () => {
    expect(samePointComparison([{ cycleStart: "1" } as any], [pt("a", 1)])).toBeNull();
  });
});

describe("model helpers", () => {
  it("vendor detection", () => {
    expect(vendorOf("claude-opus-5-5-medium")).toBe("anthropic");
    expect(vendorOf("Claude Fable 5.1 (Auto Intelligence)")).toBe("anthropic");
    expect(vendorOf("gpt-5.6-sol-medium")).toBe("openai");
    expect(vendorOf("grok-4.7-xhigh")).toBe("xai");
    expect(vendorOf("gemini-3-pro")).toBe("google");
    expect(vendorOf("mystery-model")).toBe("other");
  });

  it("efficiency metrics", () => {
    expect(cacheHitRate({ inputTokens: 25, cacheReadTokens: 75 })).toBe(0.75);
    expect(cacheHitRate({ inputTokens: 0, cacheReadTokens: 0 })).toBe(0);
    expect(costPerRequest({ totalCostCents: 300, eventCount: 4 })).toBe(75);
    expect(costPerRequest({ totalCostCents: 300, eventCount: 0 })).toBe(0);
  });
});

describe("RemoteEngine", () => {
  it("mirrors pushed snapshots and forwards refresh", async () => {
    const calls: unknown[][] = [];
    const engine = new RemoteEngine(async (method, ...args) => void calls.push([method, ...args]));
    const seen: unknown[] = [];
    engine.subscribe((s) => seen.push(s.status.state));
    engine.receive({ report: null, history: [], status: { state: "running" } as any });
    expect(engine.snapshot().status.state).toBe("running");
    expect(seen).toEqual(["running"]);
    await engine.refresh({ full: true });
    expect(calls).toEqual([["refresh", { full: true }]]);
  });
});
