import { aggregateEventsByBucket, buildSummary, dailyModelBreakdown, dailyTokens, hourlyHeatmap, legacyModelsToRows, normalizeModels, totalTokens } from "./aggregate";
import { completeDaily } from "./daily";
import type { ResolvedAuth } from "./auth";
import { CursorApiError, jwtPayload, type CursorClient } from "./client";
import type { UsageEventCache } from "./events";
import { asInt } from "./num";
import { hasPoolSplit } from "./pools";
import type { CycleSnapshot, EventAggregation, JsonObject, Report, WidgetSummary } from "./types";

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

async function settle<T>(p: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await p };
  } catch (error) {
    return { ok: false, error };
  }
}

function unwrap<T>(result: Settled<T>): T {
  if (!result.ok) throw result.error;
  return result.value;
}

const PERIOD = "aiserver.v1.DashboardService/GetCurrentPeriodUsage";
const PLAN = "aiserver.v1.DashboardService/GetPlanInfo";
const POLICY = "aiserver.v1.DashboardService/GetUsageLimitPolicyStatus";

function accountFrom(auth: ResolvedAuth, extra: Partial<Report["account"]> = {}): Report["account"] {
  return { email: auth.email, membershipType: auth.membershipType, authSource: auth.source, ...extra };
}

/** Plan totals only (two calls): used for the frequent lightweight refresh. */
export async function lightweightReport(client: CursorClient, auth: ResolvedAuth): Promise<Report> {
  const [period, planRaw] = await Promise.all([
    settle(client.connectPost(PERIOD, auth.token)),
    settle(client.connectPost(PLAN, auth.token)),
  ]);
  const periodUsage = unwrap(period);
  const planResponse = unwrap(planRaw);
  const plan = planResponse.planInfo || planResponse;
  return {
    fetchedAt: new Date().toISOString(),
    account: accountFrom(auth),
    planInfo: plan,
    periodUsage,
    onDemandModels: [],
    includedModels: [],
    models: [],
    summary: buildSummary(periodUsage, plan, null, []),
  };
}

export async function fullReport(
  client: CursorClient,
  auth: ResolvedAuth,
  cache: UsageEventCache,
  warn: (message: string) => void = () => {},
): Promise<Report> {
  const token = auth.token;
  const [period, planRaw, policy, me] = await Promise.all([
    settle(client.connectPost(PERIOD, token)),
    settle(client.connectPost(PLAN, token)),
    settle(client.connectPost(POLICY, token)),
    settle(client.webGet("/api/auth/me", token)),
  ]);
  const periodUsage: JsonObject = unwrap(period);
  const planResponse: JsonObject = unwrap(planRaw);
  const plan = planResponse.planInfo || planResponse;
  const meData: JsonObject | null = me.ok ? me.value : null;
  if (!me.ok) warn(`/api/auth/me failed: ${(me.error as Error)?.message}`);

  const userId = asInt(meData?.id);
  const start = periodUsage.billingCycleStart;
  const end = periodUsage.billingCycleEnd;

  let eventAgg: EventAggregation | null = null;
  let dayModels: Report["dailyModels"];
  let hourly: Report["hourly"];
  let dayTokens: Report["dailyTokens"];
  let legacyAgg: JsonObject | null = null;
  if (userId && start && end) {
    try {
      const events = await cache.events(token, userId, start, end);
      eventAgg = aggregateEventsByBucket(events);
      dayModels = dailyModelBreakdown(events);
      hourly = hourlyHeatmap(events);
      dayTokens = dailyTokens(events);
    } catch (error) {
      if (!(error instanceof CursorApiError)) throw error;
      cache.clear();
      warn(`filtered events unavailable: ${error.message}`);
      try {
        legacyAgg = await client.webPost("/api/dashboard/get-aggregated-usage-events", token, {
          teamId: 0,
          startDate: String(start),
          endDate: String(end),
          userId,
        });
      } catch (fallbackError) {
        warn(`model aggregation unavailable: ${(fallbackError as Error).message}`);
      }
    }
  }

  const models = eventAgg ? eventAgg.models : legacyModelsToRows(normalizeModels(legacyAgg));
  let sub: string | null = null;
  try {
    sub = jwtPayload(token).sub ?? null;
  } catch {
    sub = meData?.sub ?? null;
  }
  return {
    fetchedAt: new Date().toISOString(),
    account: accountFrom(auth, {
      email: (auth.email?.includes("@") ? auth.email : meData?.email) || auth.email,
      userId: userId || null,
      sub,
    }),
    planInfo: plan,
    periodUsage,
    limitPolicy: policy.ok ? policy.value : null,
    onDemandModels: eventAgg ? eventAgg.onDemandModels : [],
    includedModels: eventAgg ? eventAgg.includedModels : [],
    models,
    daily: eventAgg ? eventAgg.daily : [],
    dailyModels: dayModels,
    dailyTokens: dayTokens,
    hourly,
    summary: buildSummary(periodUsage, plan, eventAgg, models),
  };
}

const EVENT_DERIVED_SUMMARY_KEYS = [
  "onDemandEventCostCents",
  "onDemandEventCostDollars",
  "includedEventCostCents",
  "includedEventCostDollars",
  "modelCount",
  "topOnDemandModel",
  "topModel",
  "eventCount",
] as const;

/** Keep expensive event/model data while replacing lightweight totals. */
export function mergeLightweightReport(cached: Report | null, fresh: Report): Report {
  if (!cached) return fresh;
  const merged: Report = { ...cached, ...fresh };
  for (const key of ["daily", "dailyModels", "dailyTokens", "hourly", "models", "onDemandModels", "includedModels"] as const) {
    const value = fresh[key] as unknown;
    const empty = !value || (Array.isArray(value) ? !value.length : !Object.keys(value as object).length);
    if (empty) (merged as any)[key] = cached[key];
  }
  const nonEmpty = (obj: object) => Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== null && v !== undefined && v !== ""));
  merged.account = { ...cached.account, ...nonEmpty(fresh.account) };
  const summary: any = { ...cached.summary, ...nonEmpty(fresh.summary) };
  for (const key of EVENT_DERIVED_SUMMARY_KEYS) {
    if (key in (cached.summary || {})) summary[key] = (cached.summary as any)[key];
  }
  merged.summary = summary;
  return merged;
}

export function widgetSummary(report: Report): WidgetSummary {
  const s: any = report.summary || {};
  const used = Number(s.individualUsedCents || 0);
  const limit = Number(s.individualLimitCents || 0);
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const split = hasPoolSplit(report);
  const round1 = (v: unknown) => Math.round(Number(v || 0) * 10) / 10;
  const models = report.models || [];
  const sumOf = (key: "inputTokens" | "outputTokens" | "cacheReadTokens" | "cacheWriteTokens") => models.reduce((a, m) => a + Number(m[key] || 0), 0);
  const tokenCounts = { inputTokens: sumOf("inputTokens"), outputTokens: sumOf("outputTokens"), cacheReadTokens: sumOf("cacheReadTokens"), cacheWriteTokens: sumOf("cacheWriteTokens") };
  return {
    email: report.account?.email ?? null,
    planName: report.planInfo?.planName ?? null,
    unifiedUsedCents: s.unifiedUsedCents ?? null,
    individualUsedCents: used,
    individualLimitCents: limit,
    individualRemainingCents: Number(s.individualRemainingCents || 0),
    includedUsedCents: s.includedUsedCents ?? null,
    includedLimitCents: s.includedLimitCents ?? null,
    includedRemainingCents: s.includedRemainingCents ?? null,
    ...(models.length ? { tokens: { ...tokenCounts, total: totalTokens(tokenCounts) } } : {}),
    autoPercentUsed: split ? round1(s.autoPercentUsed) : null,
    apiPercentUsed: split ? round1(s.apiPercentUsed) : null,
    usedPercent: Math.round(pct * 10) / 10,
    topOnDemandModel: s.topOnDemandModel ?? null,
    billingCycleStart: s.billingCycleStart ?? null,
    billingCycleEnd: s.billingCycleEnd ?? null,
  };
}

export const HISTORY_LIMIT = 24;

export function cycleSnapshot(report: Report): CycleSnapshot | null {
  const s = report.summary;
  if (!s?.billingCycleStart) return null;
  const included = Number(s.includedUsedCents || 0);
  const individual = Number(s.individualUsedCents || 0);
  return {
    cycleStart: String(s.billingCycleStart),
    cycleEnd: String(s.billingCycleEnd || ""),
    planName: report.planInfo?.planName ?? null,
    includedUsedCents: included,
    includedLimitCents: Number(s.includedLimitCents || 0),
    individualUsedCents: individual,
    individualLimitCents: Number(s.individualLimitCents || 0),
    totalCents: included + individual,
    eventCount: s.eventCount ?? null,
    topModels: (report.models || []).slice(0, 5).map((m) => ({ model: m.model, costCents: Number(m.totalCostCents || 0) })),
    capturedAt: report.fetchedAt ?? null,
    dailyTotals: cycleDailyTotals(report),
  };
}

/** API-value total for each day of the cycle up to the report's fetch time. */
export function cycleDailyTotals(report: Report): number[] {
  const fetched = Date.parse(report.fetchedAt || "");
  const rows = completeDaily(report, { nowMs: Number.isFinite(fetched) ? fetched : Date.now() });
  return rows.map((r) => Number(r.includedCostCents || 0) + Number(r.onDemandCostCents || 0));
}

/** On billing-cycle rollover, keep the finished cycle's final numbers. Returns null if unchanged. */
export function nextHistory(history: CycleSnapshot[], previous: Report | null, current: Report): CycleSnapshot[] | null {
  if (!previous) return null;
  const old = cycleSnapshot(previous);
  const newStart = String(current.summary?.billingCycleStart || "");
  if (!old || !newStart || old.cycleStart === newStart) return null;
  const cycles = history.filter((c) => c.cycleStart !== old.cycleStart);
  cycles.push(old);
  cycles.sort((a, b) => Number(a.cycleStart) - Number(b.cycleStart));
  return cycles.slice(-HISTORY_LIMIT);
}
