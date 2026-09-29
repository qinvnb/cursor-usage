import { pendingAlerts } from "./alerts";
import { resolveAuth } from "./auth";
import { CursorApiError, CursorClient, type Sleep } from "./client";
import { fetchFilteredUsageEvents, UsageEventCache } from "./events";
import type { Host } from "./host";
import { L } from "./i18n";
import { fullReport, lightweightReport, mergeLightweightReport, nextHistory, widgetSummary } from "./report";
import type { AlertsState, CycleSnapshot, Report } from "./types";

export const FULL_REFRESH_MS = 10 * 60 * 1000;
const FULL_DEADLINE_MS = 150_000;
const LIGHT_DEADLINE_MS = 45_000;
const BACKOFF_BASE_MS = 30_000;
const BACKOFF_MAX_MS = 15 * 60 * 1000;

export type RefreshState = "idle" | "running" | "error";

export interface EngineStatus {
  state: RefreshState;
  runningFull: boolean;
  lastError: string | null;
  lastSuccessAt: number | null;
  consecutiveFailures: number;
  /** Epoch ms when automatic refreshes resume after failures; null when not backing off. */
  retryAt: number | null;
}

export interface EngineSnapshot {
  report: Report | null;
  history: CycleSnapshot[];
  status: EngineStatus;
}

export interface RefreshOptions {
  /** Force a full (events + models) or lightweight refresh; default decides by age. */
  full?: boolean;
  /** Scheduler/stale-data triggers: skipped while backing off after failures. */
  auto?: boolean;
}

export interface EngineOptions {
  now?: () => number;
  sleep?: Sleep;
  warn?: (message: string) => void;
}

/**
 * Stateful usage client shared by every host. Refresh requests are serialized
 * and merged: a request arriving while one is running is satisfied by a
 * follow-up run (full wins over lightweight).
 */
export class UsageEngine {
  private report: Report | null = null;
  private history: CycleSnapshot[] = [];
  private alerts: AlertsState = {};
  private lastFullAt = 0;
  private status: EngineStatus = {
    state: "idle",
    runningFull: false,
    lastError: null,
    lastSuccessAt: null,
    consecutiveFailures: 0,
    retryAt: null,
  };
  private running: Promise<EngineStatus> | null = null;
  private pending: { full: boolean } | null = null;
  private readonly listeners = new Set<(snapshot: EngineSnapshot) => void>();
  private readonly client: CursorClient;
  private readonly cache: UsageEventCache;
  private readonly now: () => number;
  private readonly warn: (message: string) => void;

  constructor(
    private readonly host: Host,
    options: EngineOptions = {},
  ) {
    this.now = options.now ?? (() => Date.now());
    this.warn = options.warn ?? (() => {});
    this.client = new CursorClient(host, options.sleep, this.now);
    this.cache = new UsageEventCache(
      (token, userId, start, end) => fetchFilteredUsageEvents(this.client, token, userId, start, end),
      this.now,
    );
  }

  async init(): Promise<EngineSnapshot> {
    const state = await this.host.loadState();
    this.report = state.report;
    this.history = state.history || [];
    this.alerts = state.alerts || {};
    if (this.report?.fetchedAt) {
      const t = Date.parse(this.report.fetchedAt);
      if (Number.isFinite(t)) this.status.lastSuccessAt = t;
    }
    this.emit();
    return this.snapshot();
  }

  snapshot(): EngineSnapshot {
    return { report: this.report, history: this.history, status: { ...this.status } };
  }

  subscribe(listener: (snapshot: EngineSnapshot) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    const snap = this.snapshot();
    for (const listener of this.listeners) {
      try {
        listener(snap);
      } catch (error) {
        this.warn(`listener failed: ${(error as Error).message}`);
      }
    }
  }

  /** Whether the next non-forced refresh should download events. */
  private wantsFull(): boolean {
    return !this.report?.daily || this.now() - this.lastFullAt >= FULL_REFRESH_MS;
  }

  refresh(options: RefreshOptions = {}): Promise<EngineStatus> {
    const full = options.full ?? this.wantsFull();
    if (options.auto && !this.running && this.status.retryAt !== null && this.now() < this.status.retryAt) {
      return Promise.resolve({ ...this.status });
    }
    if (this.running) {
      // A running equal-or-stronger refresh satisfies this request; otherwise
      // the loop runs one more (full) pass before resolving.
      if (full && !this.status.runningFull) this.pending = { full: true };
      return this.running;
    }
    this.running = this.loop(full).finally(() => {
      this.running = null;
    });
    return this.running;
  }

  private async loop(full: boolean): Promise<EngineStatus> {
    let nextFull: boolean | null = full;
    while (nextFull !== null) {
      await this.runOnce(nextFull);
      nextFull = this.pending ? this.pending.full : null;
      this.pending = null;
    }
    return { ...this.status };
  }

  private async runOnce(full: boolean): Promise<void> {
    this.status = { ...this.status, state: "running", runningFull: full };
    this.emit();
    try {
      const report = await this.client.withDeadline(full ? FULL_DEADLINE_MS : LIGHT_DEADLINE_MS, async () => {
        const settings = await this.host.loadSettings();
        const auth = await resolveAuth(this.host, this.client, settings);
        if (!full) return mergeLightweightReport(this.report, await lightweightReport(this.client, auth));
        const fresh = await fullReport(this.client, auth, this.cache, this.warn);
        if (auth.source === "manual" && fresh.account.email?.includes("@")) {
          await this.host.saveCredentials({ email: fresh.account.email });
        }
        return fresh;
      });
      if (full) this.lastFullAt = this.now();
      await this.commit(report);
      this.status = {
        state: "idle",
        runningFull: false,
        lastError: null,
        lastSuccessAt: this.now(),
        consecutiveFailures: 0,
        retryAt: null,
      };
    } catch (error) {
      const message = error instanceof CursorApiError ? error.message : `${L("未知错误", "Unexpected error")}: ${(error as Error)?.message ?? error}`;
      const failures = this.status.consecutiveFailures + 1;
      const delay = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** (failures - 1));
      this.status = {
        ...this.status,
        state: "error",
        runningFull: false,
        lastError: message,
        consecutiveFailures: failures,
        retryAt: this.now() + delay,
      };
    }
    this.emit();
  }

  private async commit(report: Report): Promise<void> {
    const history = nextHistory(this.history, this.report, report);
    if (history) {
      this.history = history;
      await this.host.saveHistory(history);
    }
    this.report = report;
    const summary = widgetSummary(report);
    await this.host.saveReport(report, summary);

    const settings = await this.host.loadSettings();
    if (settings.alertsEnabled === false) return;
    const { toSend, state } = pendingAlerts(summary, this.alerts, this.now(), {
      thresholds: settings.alertThresholds,
      onDemandBudgetCents: Math.round(Number(settings.onDemandBudget || 0) * 100),
    });
    if (toSend.length || state.cycle !== this.alerts.cycle) {
      this.alerts = state;
      await this.host.saveAlertsState(state);
    }
    for (const alert of toSend) await this.host.notify(alert.title, alert.message);
  }
}
