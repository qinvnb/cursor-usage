import { L } from "./i18n";
import type { Report } from "./types";

/**
 * Cursor splits included usage into two independent pools:
 * "cursor" = Cursor models (Auto / Composer and other auto-bucket models),
 * "api"    = every other (named) model, billed at API prices.
 */
export type Pool = "cursor" | "api";

export interface PoolUsage {
  pool: Pool;
  /** Percent of this pool used, as reported by Cursor; null when the plan has no split. */
  percentUsed: number | null;
  /** Included requests in this pool, valued at API prices. */
  costCents: number;
  eventCount: number;
  models: string[];
}

export function poolLabel(pool: Pool): string {
  return pool === "cursor" ? L("Cursor 模型", "Cursor models") : L("其他模型", "Other models");
}
export const POOL_HINT: Record<Pool, string> = { cursor: "Auto", api: "API" };

const norm = (name: string) => name.trim().toLowerCase();

export function autoBucketModels(report: Pick<Report, "periodUsage"> | null | undefined): string[] {
  const list = report?.periodUsage?.autoBucketModels;
  return Array.isArray(list) ? list.filter((m): m is string => typeof m === "string") : [];
}

/** Which included pool a model's requests draw from. */
export function modelPool(model: string | null | undefined, autoBucket: readonly string[] = []): Pool {
  const name = norm(String(model ?? ""));
  if (!name) return "api";
  // Auto-routed requests are reported as "<model> (Auto Intelligence)" etc.
  if (/\(auto\b/.test(name)) return "cursor";
  if (name === "auto" || name === "default" || name.startsWith("composer")) return "cursor";
  return autoBucket.some((m) => norm(m) === name) ? "cursor" : "api";
}

function percent(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** True when Cursor reports separate Auto / API percentages for this plan. */
export function hasPoolSplit(report: Pick<Report, "periodUsage"> | null | undefined): boolean {
  const usage = report?.periodUsage?.planUsage;
  return !!usage && (percent(usage.autoPercentUsed) !== null || percent(usage.apiPercentUsed) !== null);
}

export function includedPools(report: Pick<Report, "periodUsage" | "includedModels">): Record<Pool, PoolUsage> {
  const bucket = autoBucketModels(report);
  const usage = report.periodUsage?.planUsage || {};
  const split = hasPoolSplit(report);
  const pools: Record<Pool, PoolUsage> = {
    cursor: { pool: "cursor", percentUsed: split ? (percent(usage.autoPercentUsed) ?? 0) : null, costCents: 0, eventCount: 0, models: [] },
    api: { pool: "api", percentUsed: split ? (percent(usage.apiPercentUsed) ?? 0) : null, costCents: 0, eventCount: 0, models: [] },
  };
  for (const row of report.includedModels || []) {
    const p = pools[modelPool(row.model, bucket)];
    p.costCents += Number(row.costCents || 0);
    p.eventCount += Number(row.eventCount || 0);
    p.models.push(row.model);
  }
  return pools;
}
