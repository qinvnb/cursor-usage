/** Raw usage event as returned by /api/dashboard/get-filtered-usage-events (slimmed). */
export interface UsageEvent {
  timestamp?: string | number | null;
  kind?: string | null;
  model?: string | null;
  chargedCents?: number | string | null;
  tokenUsage?: TokenUsage | null;
}

export interface TokenUsage {
  inputTokens?: number | string | null;
  outputTokens?: number | string | null;
  cacheReadTokens?: number | string | null;
  cacheWriteTokens?: number | string | null;
  totalCents?: number | string | null;
}

export interface TokenCounts {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
}

export interface BucketModelRow extends TokenCounts {
  model: string;
  costCents: number;
  costDollars: number;
  sharePercent: number;
  eventCount: number;
}

export interface ModelRow extends TokenCounts {
  model: string;
  onDemandCostCents: number;
  onDemandCostDollars: number;
  includedCostCents: number;
  includedCostDollars: number;
  totalCostCents: number;
  totalCostDollars: number;
  eventCount: number;
}

export interface DailyRow {
  date: string;
  onDemandCostCents: number;
  includedCostCents: number;
  totalCostCents: number;
  eventCount: number;
  topOnDemandModel: string | null;
  onDemandModels: { model: string; costCents: number }[];
}

export interface EventAggregation {
  eventCount: number;
  kindTotalsCents: Record<string, number>;
  onDemandModels: BucketModelRow[];
  includedModels: BucketModelRow[];
  models: ModelRow[];
  daily: DailyRow[];
  onDemandTotalCents: number;
  includedTotalCents: number;
}

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: any };

export interface Summary {
  planName: string | null;
  planPrice: string | null;
  includedLimitCents: number;
  includedUsedCents: number;
  includedRemainingCents: number;
  bonusSpendCents: number;
  individualLimitCents: number;
  individualUsedCents: number;
  individualRemainingCents: number;
  pooledUsedCents: number | null;
  pooledLimitCents: number | null;
  pooledRemainingCents: number | null;
  onDemandTotalSpendCents: number | null;
  unifiedUsedCents: number;
  unifiedUsedDollars: number;
  onDemandEventCostCents: number;
  onDemandEventCostDollars: number;
  includedEventCostCents: number;
  includedEventCostDollars: number;
  autoPercentUsed: number;
  apiPercentUsed: number;
  totalPercentUsed: number;
  modelCount: number;
  topOnDemandModel: string | null;
  topModel: string | null;
  displayMessage: string | null;
  billingCycleStart: string | null;
  billingCycleEnd: string | null;
  eventCount: number | null;
}

export type AuthSource = "local" | "manual" | "env";

export interface Report {
  fetchedAt: string;
  account: {
    email?: string | null;
    membershipType?: string | null;
    userId?: number | null;
    sub?: string | null;
    authSource?: AuthSource;
  };
  planInfo: JsonObject;
  periodUsage: JsonObject;
  limitPolicy?: JsonObject | null;
  onDemandModels: BucketModelRow[];
  includedModels: BucketModelRow[];
  models: ModelRow[];
  daily?: DailyRow[];
  /** date -> models used that day, both buckets. */
  dailyModels?: Record<string, { model: string; includedCostCents: number; onDemandCostCents: number; eventCount: number; tokens?: number }[]>;
  /** date -> token counts, billable events only. */
  dailyTokens?: Record<string, TokenCounts>;
  /** Weekday x hour usage grid (local time). */
  hourly?: { counts: number[][]; cents: number[][] };
  summary: Summary;
}

/** Few-hundred-byte summary read by the tray, floating ball and taskbar widget. */
export interface WidgetSummary {
  email: string | null;
  planName: string | null;
  unifiedUsedCents: number | null;
  individualUsedCents: number;
  individualLimitCents: number;
  individualRemainingCents: number;
  includedUsedCents: number | null;
  includedLimitCents: number | null;
  includedRemainingCents: number | null;
  /** This cycle's tokens across all models; absent when model details are unavailable. */
  tokens?: TokenCounts & { total: number };
  /** Included pools in percent: Cursor models (Auto / Composer) and other models (API). Null when the plan has no split. */
  autoPercentUsed?: number | null;
  apiPercentUsed?: number | null;
  usedPercent: number;
  topOnDemandModel: string | null;
  billingCycleStart: string | null;
  billingCycleEnd: string | null;
}

export interface CycleSnapshot {
  cycleStart: string;
  cycleEnd: string;
  planName: string | null;
  includedUsedCents: number;
  includedLimitCents: number;
  individualUsedCents: number;
  individualLimitCents: number;
  totalCents: number;
  eventCount: number | null;
  topModels: { model: string; costCents: number }[];
  capturedAt: string | null;
  /** API-value total per cycle day (index 0 = first day); absent in snapshots saved before 2.1. */
  dailyTotals?: number[];
}

export interface AlertsState {
  cycle?: string;
  sent?: string[];
  [key: string]: unknown;
}

export interface Settings {
  authSource: "auto" | "manual";
  persistLocalRefresh: boolean;
  alertsEnabled: boolean;
  refreshSeconds: number;
  /** Alert thresholds in percent, e.g. [80, 95]. */
  alertThresholds?: number[];
  /** Personal on-demand budget in dollars; 0/absent = use the Cursor limit. */
  onDemandBudget?: number;
  /** Display language: "auto" follows the system / editor locale. */
  language?: "auto" | "zh" | "en";
  [key: string]: unknown;
}
