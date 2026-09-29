import { describe, expect, it } from "vitest";
import { dailyModelBreakdown, dailyTokens, hourlyHeatmap, totalTokens } from "../src/aggregate";
import { evaluateAlerts, normalizeThresholds, pendingAlerts } from "../src/alerts";
import { parseSessionInput } from "../src/auth";
import { CursorApiError, CursorClient } from "../src/client";
import { completeDaily, localDateKey } from "../src/daily";
import { UsageEngine } from "../src/engine";
import { UsageEventCache } from "../src/events";
import type { Host, HttpRequest, HttpResponse } from "../src/host";
import { normalizeLangPref, resolveLang, setLang } from "../src/i18n";
import { includedPools, modelPool } from "../src/pools";
import { cycleDailyTotals, cycleSnapshot, mergeLightweightReport, nextHistory, widgetSummary } from "../src/report";
import type { Report, WidgetSummary } from "../src/types";

const DAY = 86_400_000;
const HOUR = 3_600_000;

function jwt(payload: object): string {
  const enc = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "none" })}.${enc(payload)}.sig`;
}

const summary = (used: number, limit = 1000, extra: Partial<WidgetSummary> = {}): WidgetSummary => ({
  email: null,
  planName: null,
  unifiedUsedCents: used,
  individualUsedCents: used,
  individualLimitCents: limit,
  individualRemainingCents: limit - used,
  includedUsedCents: 0,
  includedLimitCents: 0,
  includedRemainingCents: 0,
  usedPercent: 0,
  topOnDemandModel: null,
  billingCycleStart: "0",
  billingCycleEnd: String(30 * DAY),
  ...extra,
});

describe("alerts", () => {
  it("only the highest threshold fires, once per cycle", () => {
    expect(evaluateAlerts(summary(960), 29 * DAY).map((a) => a.key)).toEqual(["ond-95"]);
    const first = pendingAlerts(summary(850), {}, 29 * DAY);
    expect(first.toSend.map((a) => a.key)).toEqual(["ond-80"]);
    expect(pendingAlerts(summary(860), first.state, 29 * DAY).toSend).toEqual([]);
    const higher = pendingAlerts(summary(990), first.state, 29 * DAY);
    expect(higher.toSend.map((a) => a.key)).toEqual(["ond-95"]);
  });

  it("pace alert when running out early, suppressed past 95%", () => {
    expect(evaluateAlerts(summary(500), 2 * DAY).map((a) => a.key)).toContain("ond-pace");
    expect(evaluateAlerts(summary(300), 15 * DAY)).toEqual([]);
  });

  it("new cycle resets sent state", () => {
    const { state } = pendingAlerts(summary(850), {}, 29 * DAY);
    const next = pendingAlerts(summary(850, 1000, { billingCycleStart: String(30 * DAY), billingCycleEnd: String(60 * DAY) }), state, 59 * DAY);
    expect(next.toSend.map((a) => a.key)).toEqual(["ond-80"]);
  });
});

describe("configurable alerts", () => {
  it("custom thresholds replace the defaults", () => {
    const cfg = { thresholds: [50, 75] };
    expect(evaluateAlerts(summary(600), 29 * DAY, cfg).map((a) => a.key)).toEqual(["ond-50"]);
    const first = pendingAlerts(summary(800), {}, 29 * DAY, cfg);
    expect(first.toSend.map((a) => a.key)).toEqual(["ond-75"]);
    expect(first.state.sent).toEqual(["ond-50", "ond-75"]);
  });

  it("a personal budget lower than the Cursor limit drives on-demand alerts", () => {
    const cfg = { onDemandBudgetCents: 10_000 };
    const alerts = evaluateAlerts(summary(9_600, 60_000), 29 * DAY, cfg);
    expect(alerts.map((a) => a.key)).toEqual(["ondb-95"]);
    expect(alerts[0].title).toContain("按需预算");
    // A budget above the limit is ignored.
    expect(evaluateAlerts(summary(960, 1000), 29 * DAY, { onDemandBudgetCents: 5000 }).map((a) => a.key)).toEqual(["ond-95"]);
  });

  it("ignores invalid thresholds", () => {
    expect(normalizeThresholds([0, 101, 80, 80, 95.4])).toEqual([95, 80]);
    expect(normalizeThresholds([])).toEqual([95, 80]);
  });
});

describe("included pools", () => {
  const bucket = ["default", "composer-2", "grok-4.5", "cursor-grok-4.5-high"];
  const report = (planUsage: object | null) =>
    ({
      periodUsage: { planUsage, autoBucketModels: bucket },
      includedModels: [
        { model: "claude-opus-5-5-medium", costCents: 900, eventCount: 3 },
        { model: "Grok 4.5 (Auto Intelligence)", costCents: 60, eventCount: 2 },
        { model: "composer-2", costCents: 40, eventCount: 5 },
      ],
      summary: { autoPercentUsed: 10.37, apiPercentUsed: 100 },
    }) as unknown as Report;

  it("classifies models by Cursor's auto bucket and the (Auto …) label", () => {
    expect(modelPool("Claude Fable 5.1 (Auto Balanced)", bucket)).toBe("cursor");
    expect(modelPool("composer-2.5-fast")).toBe("cursor");
    expect(modelPool("default")).toBe("cursor");
    expect(modelPool("Grok-4.5", bucket)).toBe("cursor");
    expect(modelPool("grok-4.7-xhigh", bucket)).toBe("api");
    expect(modelPool("gpt-5.6-sol-medium", bucket)).toBe("api");
    expect(modelPool(null)).toBe("api");
  });

  it("sums included cost per pool and carries Cursor's percentages", () => {
    const pools = includedPools(report({ autoPercentUsed: 10.37, apiPercentUsed: 100 }));
    expect(pools.cursor).toMatchObject({ percentUsed: 10.37, costCents: 100, eventCount: 7 });
    expect(pools.api).toMatchObject({ percentUsed: 100, costCents: 900, eventCount: 3, models: ["claude-opus-5-5-medium"] });
    expect(includedPools(report({ limit: 2000 })).api.percentUsed).toBeNull();
  });

  it("widget summary exposes pool percentages only when the plan has them", () => {
    const w = widgetSummary({ ...report({ autoPercentUsed: 10.37, apiPercentUsed: 100 }), account: {}, planInfo: {} });
    expect([w.autoPercentUsed, w.apiPercentUsed]).toEqual([10.4, 100]);
    const legacy = widgetSummary({ ...report({ limit: 2000 }), account: {}, planInfo: {} });
    expect([legacy.autoPercentUsed, legacy.apiPercentUsed]).toEqual([null, null]);
  });

  it("alerts per pool replace the dollar-based included alert", () => {
    const s = summary(0, 1000, { includedUsedCents: 2000, includedLimitCents: 2000, autoPercentUsed: 82, apiPercentUsed: 100 });
    const alerts = evaluateAlerts(s, 29 * DAY);
    expect(alerts.map((a) => a.key)).toEqual(["auto-80", "api-95"]);
    expect(alerts[1].title).toContain("其他模型（API）");
    expect(alerts[1].message).toContain("计入个人按需");
    const legacy = summary(0, 1000, { includedUsedCents: 2000, includedLimitCents: 2000 });
    expect(evaluateAlerts(legacy, 29 * DAY).map((a) => a.key)).toEqual(["inc-95"]);
  });
});

describe("tokens", () => {
  const ev = (ts: number, kind: string, t: Partial<Record<string, number>>) => ({ timestamp: String(ts), kind, model: "m", chargedCents: 1, tokenUsage: t });
  it("sums tokens per local day for billable events only", () => {
    const day = Date.parse("2026-09-28T10:00:00+08:00");
    const events = [
      ev(day, "USAGE_EVENT_KIND_USAGE_BASED", { inputTokens: 10, outputTokens: 5, cacheReadTokens: 100 }),
      ev(day + HOUR, "USAGE_EVENT_KIND_INCLUDED_IN_BUSINESS", { inputTokens: 1, cacheWriteTokens: 2 }),
      ev(day + 2 * HOUR, "USAGE_EVENT_KIND_ERRORED_NOT_CHARGED", { inputTokens: 999 }),
    ];
    expect(dailyTokens(events)).toEqual({ "2026-09-28": { inputTokens: 11, outputTokens: 5, cacheReadTokens: 100, cacheWriteTokens: 2 } });
    expect(dailyModelBreakdown(events)["2026-09-28"][0].tokens).toBe(118);
    expect(totalTokens({ inputTokens: 1, outputTokens: 2, cacheReadTokens: 3, cacheWriteTokens: 4 })).toBe(10);
  });

  it("widget summary totals tokens across models", () => {
    const w = widgetSummary({
      account: {},
      planInfo: {},
      periodUsage: {},
      summary: {},
      models: [
        { model: "a", inputTokens: 1, outputTokens: 2, cacheReadTokens: 3, cacheWriteTokens: 4 },
        { model: "b", inputTokens: 10, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0 },
      ],
    } as unknown as Report);
    expect(w.tokens).toEqual({ inputTokens: 11, outputTokens: 2, cacheReadTokens: 3, cacheWriteTokens: 4, total: 20 });
    expect(widgetSummary({ account: {}, planInfo: {}, summary: {}, models: [] } as unknown as Report).tokens).toBeUndefined();
  });
});

describe("i18n", () => {
  it("resolves auto from the locale and keeps explicit choices", () => {
    expect(resolveLang("auto", "zh-CN")).toBe("zh");
    expect(resolveLang("auto", "zh-tw")).toBe("zh");
    expect(resolveLang("auto", "en-US")).toBe("en");
    expect(resolveLang("auto", "ja")).toBe("en");
    expect(resolveLang("auto", "")).toBe("zh");
    expect(resolveLang("en", "zh-CN")).toBe("en");
    expect(resolveLang("zh", "en")).toBe("zh");
    expect(normalizeLangPref("fr")).toBe("auto");
  });

  it("alerts follow the current language", () => {
    const s = summary(0, 1000, { autoPercentUsed: 10, apiPercentUsed: 100 });
    setLang("en");
    try {
      const [alert] = evaluateAlerts(s, 29 * DAY);
      expect(alert.title).toBe("Cursor included other models (API) at 100%");
      expect(alert.message).toContain("billed on-demand");
    } finally {
      setLang("zh");
    }
    expect(evaluateAlerts(s, 29 * DAY)[0].title).toContain("已用 100%");
  });
});

describe("heatmap & cycle series", () => {
  it("buckets billable events by local weekday and hour", () => {
    const t = new Date(2026, 8, 28, 14, 30).getTime(); // Monday 14:30
    const grid = hourlyHeatmap([
      { timestamp: String(t), kind: "USAGE_BASED", chargedCents: 5 },
      { timestamp: String(t + 60_000), kind: "INCLUDED_IN_PRO", chargedCents: 2 },
      { timestamp: String(t), kind: "ERRORED_NOT_CHARGED", chargedCents: 9 },
      { timestamp: "bad", kind: "USAGE_BASED", chargedCents: 1 },
    ]);
    expect(grid.counts[1][14]).toBe(2);
    expect(grid.cents[1][14]).toBe(7);
    expect(grid.counts.flat().reduce((a, b) => a + b, 0)).toBe(2);
  });

  it("snapshots carry per-day totals for same-point comparisons", () => {
    const start = new Date(2026, 8, 1, 8).getTime();
    const report = {
      fetchedAt: new Date(2026, 8, 3, 20).toISOString(),
      summary: { billingCycleStart: String(start), billingCycleEnd: String(start + 30 * DAY), includedUsedCents: 0, individualUsedCents: 0 },
      daily: [{ date: "2026-09-02", includedCostCents: 100, onDemandCostCents: 50, totalCostCents: 150, eventCount: 1, topOnDemandModel: null, onDemandModels: [] }],
      models: [],
      planInfo: {},
    } as unknown as Report;
    expect(cycleDailyTotals(report)).toEqual([0, 150, 0]);
    expect(cycleSnapshot(report)?.dailyTotals).toEqual([0, 150, 0]);
  });
});

describe("event cache", () => {
  it("re-fetches only the overlap window and replaces it", async () => {
    const calls: number[] = [];
    const server = [10 * HOUR, 20 * HOUR, 29 * HOUR].map((t) => ({ timestamp: String(t), kind: "USAGE_BASED", chargedCents: 1 }));
    const cache = new UsageEventCache(async (_t, _u, start) => {
      calls.push(Number(start));
      return server.filter((e) => Number(e.timestamp) >= Number(start));
    });
    expect(await cache.events("t", 1, 0, 100 * HOUR)).toHaveLength(3);
    server[2] = { timestamp: String(29 * HOUR), kind: "USAGE_BASED", chargedCents: 5 };
    server.push({ timestamp: String(30 * HOUR), kind: "USAGE_BASED", chargedCents: 1 });
    const second = await cache.events("t", 1, 0, 100 * HOUR);
    expect(calls).toEqual([0, 29 * HOUR - UsageEventCache.OVERLAP_MS]);
    expect(second.map((e) => Number(e.timestamp))).toEqual([10 * HOUR, 20 * HOUR, 29 * HOUR, 30 * HOUR]);
    expect(second[2].chargedCents).toBe(5);
  });
});

describe("client", () => {
  const hostWith = (responses: (HttpResponse | Error)[]) =>
    ({
      http: async () => {
        const next = responses.shift()!;
        if (next instanceof Error) throw next;
        return next;
      },
    }) as unknown as Host;

  it("retries 5xx and transport errors, not 4xx", async () => {
    const ok = { status: 200, headers: {}, body: '{"ok":true}' };
    const client = new CursorClient(hostWith([{ status: 503, headers: {}, body: "" }, new Error("ECONNRESET"), ok]), async () => {});
    expect(await client.requestJson({ url: "x", method: "GET", headers: {} }, { label: "x" })).toEqual({ ok: true });

    const bad = new CursorClient(hostWith([{ status: 401, headers: {}, body: "no" }]), async () => {});
    await expect(bad.requestJson({ url: "x", method: "GET", headers: {} }, { label: "x" })).rejects.toMatchObject({ status: 401 });
  });

  it("deadline bounds the whole operation", async () => {
    let now = 0;
    const client = new CursorClient(hostWith([{ status: 503, headers: {}, body: "" }]), async () => {}, () => now);
    await expect(
      client.withDeadline(500, async () => {
        now = 1000;
        return client.requestJson({ url: "x", method: "GET", headers: {} }, { label: "x" });
      }),
    ).rejects.toBeInstanceOf(CursorApiError);
  });
});

describe("parseSessionInput", () => {
  const token = jwt({ sub: "user@example.com", exp: 9_999_999_999 });
  it("accepts cookie, user::jwt and bearer forms", () => {
    expect(parseSessionInput(`WorkosCursorSessionToken=abc%3A%3A${token}; Path=/`).accessToken).toBe(token);
    expect(parseSessionInput(`abc::${token}`).emailHint).toBe("user@example.com");
    expect(parseSessionInput(`Bearer ${token}`).accessToken).toBe(token);
    expect(() => parseSessionInput("nope")).toThrow(CursorApiError);
  });
});

describe("daily & history", () => {
  it("fills calendar days in local time", () => {
    const start = new Date(2026, 8, 23, 10).getTime();
    const report = {
      daily: [{ date: "2026-09-25", onDemandCostCents: 1, includedCostCents: 0, totalCostCents: 1, eventCount: 1, topOnDemandModel: null, onDemandModels: [] }],
      summary: { billingCycleStart: String(start), billingCycleEnd: String(start + 30 * DAY) } as any,
    };
    const rows = completeDaily(report, { nowMs: new Date(2026, 8, 28, 23, 59).getTime() });
    expect(rows.map((r) => r.date)).toEqual(["2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27", "2026-09-28"]);
    expect(completeDaily(report, { throughEnd: true }).length).toBe(31);
    expect(localDateKey(new Date(2026, 8, 28, 0, 30))).toBe("2026-09-28");
  });

  it("records the finished cycle on rollover only", () => {
    const rep = (start: string, used: number) => ({ summary: { billingCycleStart: start, billingCycleEnd: "9", individualUsedCents: used, includedUsedCents: 1 }, models: [], planInfo: {} }) as unknown as Report;
    expect(nextHistory([], rep("1", 5), rep("1", 6))).toBeNull();
    const h = nextHistory([], rep("1", 9), rep("2", 1))!;
    expect(h).toHaveLength(1);
    expect(h[0]).toMatchObject({ cycleStart: "1", totalCents: 10 });
  });

  it("lightweight merge keeps event-derived fields", () => {
    const cached = { account: { email: "a@b.c", userId: 7 }, summary: { individualUsedCents: 1, eventCount: 42, topOnDemandModel: "m" }, daily: [{}], models: [{}] } as any;
    const fresh = { account: { email: "a@b.c", userId: null }, summary: { individualUsedCents: 2, eventCount: null, topOnDemandModel: null }, models: [] } as any;
    const merged = mergeLightweightReport(cached, fresh);
    expect(merged.account.userId).toBe(7);
    expect(merged.summary).toMatchObject({ individualUsedCents: 2, eventCount: 42, topOnDemandModel: "m" });
    expect(merged.models).toEqual([{}]);
  });
});

describe("engine", () => {
  function fakeHost(overrides: Partial<Host> = {}) {
    const token = jwt({ sub: "auth0|u", exp: 9_999_999_999 });
    const saved: Report[] = [];
    const notified: string[] = [];
    const routes: Record<string, unknown> = {
      GetCurrentPeriodUsage: { billingCycleStart: "1000", billingCycleEnd: String(1000 + 30 * DAY), spendLimitUsage: { individualLimit: 1000, individualUsed: 900 } },
      GetPlanInfo: { planInfo: { planName: "Pro" } },
      GetUsageLimitPolicyStatus: {},
      "/api/auth/me": { id: 5, email: "me@x.y" },
      "get-filtered-usage-events": { totalUsageEventsCount: 1, usageEventsDisplay: [{ timestamp: "2000", kind: "USAGE_BASED", model: "m", chargedCents: 900 }] },
    };
    let failNext = 0;
    const host: Host = {
      http: async (req: HttpRequest) => {
        if (failNext-- > 0) return { status: 503, headers: {}, body: "" };
        const key = Object.keys(routes).find((k) => req.url.includes(k))!;
        return { status: 200, headers: {}, body: JSON.stringify(routes[key]) };
      },
      envToken: async () => null,
      readLocalAuth: async () => ({ accessToken: token, cachedEmail: "me@x.y" }),
      writeLocalAuth: async () => {},
      getCredentials: async () => null,
      saveCredentials: async () => {},
      loadSettings: async () => ({ authSource: "auto", persistLocalRefresh: false, alertsEnabled: true, refreshSeconds: 60 }),
      loadState: async () => ({ report: null, history: [], alerts: {} }),
      saveReport: async (r) => void saved.push(r),
      saveHistory: async () => {},
      saveAlertsState: async () => {},
      notify: async (title) => void notified.push(title),
      ...overrides,
    };
    return { host, saved, notified, fail: (n: number) => (failNext = n) };
  }

  it("full refresh saves a report and fires the 80% alert once", async () => {
    const { host, saved, notified } = fakeHost();
    const engine = new UsageEngine(host, { sleep: async () => {} });
    await engine.init();
    const status = await engine.refresh();
    expect(status.state).toBe("idle");
    expect(saved[0].summary.individualUsedCents).toBe(900);
    expect(saved[0].models[0].model).toBe("m");
    expect(notified).toHaveLength(1);
    await engine.refresh({ full: false });
    expect(notified).toHaveLength(1);
    expect(saved[1].models[0].model).toBe("m");
  });

  it("concurrent requests merge into one run", async () => {
    const { host, saved } = fakeHost();
    const engine = new UsageEngine(host, { sleep: async () => {} });
    await engine.init();
    await Promise.all([engine.refresh(), engine.refresh(), engine.refresh({ full: false })]);
    expect(saved).toHaveLength(1);
  });

  it("backs off automatic refreshes after failures", async () => {
    let now = 1_000_000;
    const { host, saved, fail } = fakeHost();
    const engine = new UsageEngine(host, { sleep: async () => {}, now: () => now });
    await engine.init();
    fail(99);
    const failed = await engine.refresh();
    expect(failed.state).toBe("error");
    expect(failed.retryAt).toBe(now + 30_000);
    fail(0);
    await engine.refresh({ auto: true });
    expect(saved).toHaveLength(0);
    await engine.refresh();
    expect(saved).toHaveLength(1);
  });
});
