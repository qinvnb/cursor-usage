import { asFloat, asInt, dollarsFromCents, pyFloat, pyInt, pyRound, pySum, truthy } from "./num";
import type {
  BucketModelRow,
  DailyRow,
  EventAggregation,
  JsonObject,
  ModelRow,
  Summary,
  TokenCounts,
  UsageEvent,
} from "./types";

type Bucket = "onDemand" | "included";
const TOKEN_KEYS = ["inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"] as const;

const emptyTokens = (): TokenCounts => ({ inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0 });

export function eventChargedCents(event: UsageEvent): number {
  const c = event.chargedCents;
  if (c !== null && c !== undefined && c !== "" && c !== "-") {
    try {
      return pyFloat(c);
    } catch {
      /* fall through to tokenUsage */
    }
  }
  const tu = event.tokenUsage || {};
  if (tu.totalCents !== null && tu.totalCents !== undefined) return asFloat(tu.totalCents);
  return 0;
}

/** Return "onDemand", "included", or null (skip). */
export function classifyEventBucket(kind: string | null | undefined): Bucket | null {
  const k = (kind || "").toUpperCase();
  if (k.includes("ERRORED") || k.includes("NOT_CHARGED")) return null;
  if (k.includes("USAGE_BASED")) return "onDemand";
  if (k.includes("INCLUDED")) return "included";
  return null;
}

function localDay(timestamp: UsageEvent["timestamp"]): string {
  // Python: int(str(timestamp or 0)) / 1000 -> local calendar day.
  let ms: number;
  try {
    const raw = truthy(timestamp) ? timestamp : 0;
    if (typeof raw === "number" && !Number.isInteger(raw)) return "unknown";
    ms = pyInt(typeof raw === "number" ? raw : String(raw));
  } catch {
    return "unknown";
  }
  if (!(ms > 0)) return "unknown";
  const d = new Date(ms);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function rowsFromCostMap(
  costs: Map<string, number>,
  tokens: Map<string, TokenCounts>,
  counts: Map<string, number>,
): BucketModelRow[] {
  const total = pySum(costs.values());
  const rows: BucketModelRow[] = [];
  for (const [model, cost] of costs) {
    const tok = tokens.get(model) || emptyTokens();
    const share = total > 0 ? (cost / total) * 100.0 : 0.0;
    rows.push({
      model,
      costCents: cost,
      costDollars: pyRound(cost / 100.0, 4),
      sharePercent: pyRound(share, 2),
      eventCount: counts.get(model) || 0,
      inputTokens: tok.inputTokens,
      outputTokens: tok.outputTokens,
      cacheReadTokens: tok.cacheReadTokens,
      cacheWriteTokens: tok.cacheWriteTokens,
    });
  }
  rows.sort((a, b) => b.costCents - a.costCents);
  return rows;
}

export function aggregateEventsByBucket(events: UsageEvent[]): EventAggregation {
  const costMaps: Record<Bucket, Map<string, number>> = { onDemand: new Map(), included: new Map() };
  const tokenMaps: Record<Bucket, Map<string, TokenCounts>> = { onDemand: new Map(), included: new Map() };
  const countMaps: Record<Bucket, Map<string, number>> = { onDemand: new Map(), included: new Map() };
  const kindTotals: Record<string, number> = {};
  const dailyMaps = new Map<string, { onDemandCostCents: number; includedCostCents: number; eventCount: number }>();
  const dailyModels = new Map<string, Record<Bucket, Map<string, number>>>();

  for (const event of events) {
    const kind = String(event.kind || "unknown");
    const bucket = classifyEventBucket(kind);
    const cost = eventChargedCents(event);
    kindTotals[kind] = (kindTotals[kind] ?? 0) + cost;
    if (bucket === null) continue;
    const model = String(event.model || "unknown");
    costMaps[bucket].set(model, (costMaps[bucket].get(model) ?? 0) + cost);
    countMaps[bucket].set(model, (countMaps[bucket].get(model) ?? 0) + 1);
    let slot = tokenMaps[bucket].get(model);
    if (!slot) {
      slot = emptyTokens();
      tokenMaps[bucket].set(model, slot);
    }
    const tu = (event.tokenUsage || {}) as Record<string, unknown>;
    for (const key of TOKEN_KEYS) slot[key] += asInt(tu[key]);

    const day = localDay(event.timestamp);
    let daySlot = dailyMaps.get(day);
    if (!daySlot) {
      daySlot = { onDemandCostCents: 0, includedCostCents: 0, eventCount: 0 };
      dailyMaps.set(day, daySlot);
    }
    if (bucket === "onDemand") daySlot.onDemandCostCents += cost;
    else daySlot.includedCostCents += cost;
    daySlot.eventCount += 1;
    let dm = dailyModels.get(day);
    if (!dm) {
      dm = { onDemand: new Map(), included: new Map() };
      dailyModels.set(day, dm);
    }
    dm[bucket].set(model, (dm[bucket].get(model) ?? 0) + cost);
  }

  const onDemandRows = rowsFromCostMap(costMaps.onDemand, tokenMaps.onDemand, countMaps.onDemand);
  const includedRows = rowsFromCostMap(costMaps.included, tokenMaps.included, countMaps.included);

  const combinedCosts = new Map<string, { onDemandCostCents: number; includedCostCents: number }>();
  const combinedTokens = new Map<string, TokenCounts>();
  const combinedCounts = new Map<string, number>();
  for (const [bucket, rows] of [
    ["onDemand", onDemandRows],
    ["included", includedRows],
  ] as const) {
    const field = bucket === "onDemand" ? "onDemandCostCents" : "includedCostCents";
    for (const row of rows) {
      let slot = combinedCosts.get(row.model);
      if (!slot) {
        slot = { onDemandCostCents: 0, includedCostCents: 0 };
        combinedCosts.set(row.model, slot);
      }
      slot[field] = row.costCents;
      combinedCounts.set(row.model, (combinedCounts.get(row.model) ?? 0) + row.eventCount);
      let tok = combinedTokens.get(row.model);
      if (!tok) {
        tok = emptyTokens();
        combinedTokens.set(row.model, tok);
      }
      for (const key of TOKEN_KEYS) tok[key] += row[key];
    }
  }

  const combinedRows: ModelRow[] = [];
  for (const [model, costs] of combinedCosts) {
    const onC = costs.onDemandCostCents;
    const inC = costs.includedCostCents;
    const totalC = onC + inC;
    const tok = combinedTokens.get(model) || emptyTokens();
    combinedRows.push({
      model,
      onDemandCostCents: onC,
      onDemandCostDollars: pyRound(onC / 100.0, 4),
      includedCostCents: inC,
      includedCostDollars: pyRound(inC / 100.0, 4),
      totalCostCents: totalC,
      totalCostDollars: pyRound(totalC / 100.0, 4),
      eventCount: combinedCounts.get(model) || 0,
      inputTokens: tok.inputTokens,
      outputTokens: tok.outputTokens,
      cacheReadTokens: tok.cacheReadTokens,
      cacheWriteTokens: tok.cacheWriteTokens,
    });
  }
  combinedRows.sort((a, b) => b.totalCostCents - a.totalCostCents);

  const dailyRows: DailyRow[] = [];
  for (const [day, vals] of dailyMaps) {
    if (day === "unknown") continue;
    const onC = vals.onDemandCostCents || 0;
    const inC = vals.includedCostCents || 0;
    const models = dailyModels.get(day);
    const topOnd = [...(models?.onDemand ?? new Map<string, number>())].sort((a, b) => -a[1] - -b[1]);
    dailyRows.push({
      date: day,
      onDemandCostCents: onC,
      includedCostCents: inC,
      totalCostCents: onC + inC,
      eventCount: vals.eventCount || 0,
      topOnDemandModel: topOnd.length ? topOnd[0][0] : null,
      onDemandModels: topOnd.map(([model, costCents]) => ({ model, costCents })),
    });
  }
  dailyRows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

  return {
    eventCount: events.length,
    kindTotalsCents: kindTotals,
    onDemandModels: onDemandRows,
    includedModels: includedRows,
    models: combinedRows,
    daily: dailyRows,
    onDemandTotalCents: pySum(costMaps.onDemand.values()),
    includedTotalCents: pySum(costMaps.included.values()),
  };
}

export interface DayModelRow {
  model: string;
  includedCostCents: number;
  onDemandCostCents: number;
  eventCount: number;
  /** All tokens (input + output + cache read + cache write); absent in reports saved before tokens were tracked. */
  tokens?: number;
}

export const totalTokens = (t: Partial<TokenCounts> | null | undefined): number =>
  t ? Number(t.inputTokens || 0) + Number(t.outputTokens || 0) + Number(t.cacheReadTokens || 0) + Number(t.cacheWriteTokens || 0) : 0;

/** Per-day token counts (local date) for billable events. */
export function dailyTokens(events: UsageEvent[]): Record<string, TokenCounts> {
  const out: Record<string, TokenCounts> = {};
  for (const event of events) {
    if (classifyEventBucket(String(event.kind || "unknown")) === null) continue;
    const day = localDay(event.timestamp);
    if (day === "unknown") continue;
    const slot = (out[day] ||= emptyTokens());
    const tu = (event.tokenUsage || {}) as Record<string, unknown>;
    for (const key of TOKEN_KEYS) slot[key] += asInt(tu[key]);
  }
  return out;
}

/** Per-day, per-model costs for both buckets (the legacy daily rows only list on-demand models). */
export function dailyModelBreakdown(events: UsageEvent[]): Record<string, DayModelRow[]> {
  const days = new Map<string, Map<string, DayModelRow>>();
  for (const event of events) {
    const bucket = classifyEventBucket(String(event.kind || "unknown"));
    if (bucket === null) continue;
    const day = localDay(event.timestamp);
    if (day === "unknown") continue;
    const model = String(event.model || "unknown");
    let models = days.get(day);
    if (!models) {
      models = new Map();
      days.set(day, models);
    }
    let row = models.get(model);
    if (!row) {
      row = { model, includedCostCents: 0, onDemandCostCents: 0, eventCount: 0, tokens: 0 };
      models.set(model, row);
    }
    const cost = eventChargedCents(event);
    if (bucket === "onDemand") row.onDemandCostCents += cost;
    else row.includedCostCents += cost;
    row.eventCount += 1;
    const tu = (event.tokenUsage || {}) as Record<string, unknown>;
    row.tokens = (row.tokens || 0) + TOKEN_KEYS.reduce((a, key) => a + asInt(tu[key]), 0);
  }
  const out: Record<string, DayModelRow[]> = {};
  for (const [day, models] of days) {
    out[day] = [...models.values()].sort(
      (a, b) => b.includedCostCents + b.onDemandCostCents - (a.includedCostCents + a.onDemandCostCents),
    );
  }
  return out;
}

export interface HourlyHeatmap {
  /** [weekday 0=Sunday][hour 0-23] request counts, local time. */
  counts: number[][];
  /** Same grid, cost in cents. */
  cents: number[][];
}

/** Weekday x hour usage grid (local time) for billable events. */
export function hourlyHeatmap(events: UsageEvent[]): HourlyHeatmap {
  const counts = Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
  const cents = Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
  for (const event of events) {
    if (classifyEventBucket(String(event.kind || "unknown")) === null) continue;
    const ms = Number(String(event.timestamp ?? ""));
    if (!Number.isFinite(ms) || ms <= 0) continue;
    const d = new Date(ms);
    counts[d.getDay()][d.getHours()] += 1;
    cents[d.getDay()][d.getHours()] += eventChargedCents(event);
  }
  return { counts, cents };
}

export interface LegacyModelRow extends TokenCounts {
  model: string;
  tier: unknown;
  costCents: number;
  costDollars: number;
  sharePercent: number;
}

/** Fallback when filtered events are unavailable: /get-aggregated-usage-events. */
export function normalizeModels(agg: JsonObject | null | undefined): LegacyModelRow[] {
  if (!truthy(agg)) return [];
  const rows: LegacyModelRow[] = [];
  const totalCost = asFloat(agg!.totalCostCents);
  for (const item of (agg!.aggregations as JsonObject[]) || []) {
    const cost = asFloat(item.totalCents);
    const share = totalCost > 0 ? (cost / totalCost) * 100.0 : 0.0;
    rows.push({
      model: item.modelIntent || item.model || "unknown",
      tier: item.tier ?? null,
      costCents: cost,
      costDollars: pyRound(cost / 100.0, 4),
      sharePercent: pyRound(share, 2),
      inputTokens: asInt(item.inputTokens),
      outputTokens: asInt(item.outputTokens),
      cacheReadTokens: asInt(item.cacheReadTokens),
      cacheWriteTokens: asInt(item.cacheWriteTokens),
    });
  }
  rows.sort((a, b) => b.costCents - a.costCents);
  return rows;
}

export function legacyModelsToRows(legacy: LegacyModelRow[]): ModelRow[] {
  return legacy.map((m) => ({
    model: m.model,
    onDemandCostCents: 0,
    onDemandCostDollars: 0,
    includedCostCents: m.costCents,
    includedCostDollars: m.costDollars,
    totalCostCents: m.costCents,
    totalCostDollars: m.costDollars,
    eventCount: 0,
    inputTokens: m.inputTokens,
    outputTokens: m.outputTokens,
    cacheReadTokens: m.cacheReadTokens,
    cacheWriteTokens: m.cacheWriteTokens,
  }));
}

function remainingCents(usage: JsonObject): unknown {
  if (usage.remaining !== null && usage.remaining !== undefined) return usage.remaining;
  try {
    const limit = truthy(usage.limit) ? usage.limit : 0;
    const spent = truthy(usage.includedSpend) ? usage.includedSpend : 0;
    return Math.max(0, pyInt(limit) - pyInt(spent));
  } catch {
    return null;
  }
}

export function buildSummary(
  period: JsonObject,
  plan: JsonObject,
  eventAgg: EventAggregation | null,
  models: { model: string }[],
): Summary {
  const usage: JsonObject = period.planUsage || {};
  const spend: JsonObject = period.spendLimitUsage || {};
  const includedLimit = asFloat(usage.limit);
  const includedUsed = asFloat(usage.includedSpend);
  const includedLeft = asFloat(remainingCents(usage));
  const individualLimit = asFloat(spend.individualLimit);
  const individualUsed = asFloat(spend.individualUsed);
  let individualLeft = asFloat(spend.individualRemaining);
  if (individualLeft === 0 && individualLimit && (spend.individualRemaining === null || spend.individualRemaining === undefined)) {
    individualLeft = Math.max(0.0, individualLimit - individualUsed);
  }

  const agg: Partial<EventAggregation> = eventAgg || {};
  const onDemandEvent = asFloat(agg.onDemandTotalCents);
  const includedEvent = asFloat(agg.includedTotalCents);
  let unifiedUsed = includedUsed + individualUsed;
  if (unifiedUsed <= 0 && onDemandEvent + includedEvent > 0) unifiedUsed = onDemandEvent + includedUsed;

  const onRows = agg.onDemandModels || [];
  const topOnDemand = onRows.length ? onRows[0].model : null;
  const hasSpend = truthy(spend);

  return {
    planName: plan.planName ?? null,
    planPrice: plan.price ?? null,
    includedLimitCents: includedLimit,
    includedUsedCents: includedUsed,
    includedRemainingCents: includedLeft,
    bonusSpendCents: asFloat(usage.bonusSpend),
    individualLimitCents: individualLimit,
    individualUsedCents: individualUsed,
    individualRemainingCents: individualLeft,
    pooledUsedCents: hasSpend ? asFloat(spend.pooledUsed) : null,
    pooledLimitCents: spend.pooledLimit !== null && spend.pooledLimit !== undefined ? asFloat(spend.pooledLimit) : null,
    pooledRemainingCents:
      spend.pooledRemaining !== null && spend.pooledRemaining !== undefined ? asFloat(spend.pooledRemaining) : null,
    onDemandTotalSpendCents: hasSpend ? asFloat(spend.totalSpend) : null,
    unifiedUsedCents: unifiedUsed,
    unifiedUsedDollars: dollarsFromCents(unifiedUsed),
    onDemandEventCostCents: onDemandEvent,
    onDemandEventCostDollars: dollarsFromCents(onDemandEvent),
    includedEventCostCents: includedEvent,
    includedEventCostDollars: dollarsFromCents(includedEvent),
    autoPercentUsed: asFloat(usage.autoPercentUsed),
    apiPercentUsed: asFloat(usage.apiPercentUsed),
    totalPercentUsed: asFloat(usage.totalPercentUsed),
    modelCount: models.length,
    topOnDemandModel: topOnDemand,
    topModel: models.length ? models[0].model : topOnDemand,
    displayMessage: period.displayMessage ?? null,
    billingCycleStart: period.billingCycleStart ?? null,
    billingCycleEnd: period.billingCycleEnd ?? null,
    eventCount: eventAgg ? eventAgg.eventCount : null,
  };
}
