import type { CursorClient } from "./client";
import { asInt } from "./num";
import type { UsageEvent } from "./types";

const MAX_PAGES = 100;

export async function fetchFilteredUsageEvents(
  client: CursorClient,
  token: string,
  userId: number,
  startMs: string | number,
  endMs: string | number,
  pageSize = 200,
): Promise<UsageEvent[]> {
  const events: UsageEvent[] = [];
  let total: number | null = null;
  for (let page = 1; page <= MAX_PAGES; page++) {
    const data = await client.webPost("/api/dashboard/get-filtered-usage-events", token, {
      teamId: 0,
      startDate: String(startMs),
      endDate: String(endMs),
      userId,
      page,
      pageSize,
    });
    if (total === null) total = asInt(data.totalUsageEventsCount);
    const batch = data.usageEventsDisplay || [];
    if (!Array.isArray(batch)) break;
    events.push(...batch);
    if (!batch.length || events.length >= total) break;
  }
  return events;
}

export function eventTimestamp(event: UsageEvent): number {
  const n = Number(String(event.timestamp ?? 0));
  return Number.isFinite(n) ? n : 0;
}

export function slimEvent(event: UsageEvent): UsageEvent {
  const tu = (event.tokenUsage || {}) as Record<string, unknown>;
  const tokenUsage: Record<string, unknown> = {};
  for (const key of ["inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens", "totalCents"]) {
    if (key in tu) tokenUsage[key] = tu[key];
  }
  return {
    timestamp: event.timestamp ?? null,
    kind: event.kind ?? null,
    model: event.model ?? null,
    chargedCents: event.chargedCents ?? null,
    tokenUsage,
  };
}

export type EventFetcher = (token: string, userId: number, start: string | number, end: string | number) => Promise<UsageEvent[]>;

/**
 * In-memory cache of the current billing cycle's usage events.
 *
 * After the first full download, refreshes only re-fetch events newer than
 * `newest - OVERLAP_MS` and replace that window, so late cost corrections to
 * recent events are still picked up. A periodic full resync and any
 * cycle/user change discard the cache.
 */
export class UsageEventCache {
  static readonly OVERLAP_MS = 2 * 60 * 60 * 1000;
  static readonly FULL_RESYNC_MS = 6 * 60 * 60 * 1000;

  private key: string | null = null;
  private cached: UsageEvent[] = [];
  private syncedAt = 0;

  constructor(
    private readonly fetcher: EventFetcher,
    private readonly now: () => number = () => Date.now(),
  ) {}

  clear(): void {
    this.key = null;
    this.cached = [];
    this.syncedAt = 0;
  }

  async events(token: string, userId: number, start: string | number, end: string | number): Promise<UsageEvent[]> {
    const key = `${userId}|${start}|${end}`;
    const now = this.now();
    const full = this.key !== key || !this.cached.length || now - this.syncedAt >= UsageEventCache.FULL_RESYNC_MS;
    if (full) {
      const fresh = await this.fetcher(token, userId, start, end);
      this.cached = fresh.map(slimEvent);
      this.key = key;
      this.syncedAt = now;
    } else {
      const newest = this.cached.reduce((max, e) => Math.max(max, eventTimestamp(e)), 0);
      const since = Math.max(Number(start), newest - UsageEventCache.OVERLAP_MS);
      const fresh = await this.fetcher(token, userId, since, end);
      this.cached = [...this.cached.filter((e) => eventTimestamp(e) < since), ...fresh.map(slimEvent)];
    }
    return [...this.cached];
  }
}
