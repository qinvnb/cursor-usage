/**
 * Browser-only host for `npm run dev` and screenshots: serves the golden
 * fixture through the real core (HTTP routes are faked, nothing leaves the page).
 */
import type { Host, HttpRequest } from "@cursor-usage/core";
import golden from "../../core/test/fixtures/golden.json";
import type { AppApi, SettingsMap } from "./api";

function jwt(payload: object): string {
  const enc = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${enc({ alg: "none" })}.${enc(payload)}.mock`;
}

export function createMockHost(): { host: Host; api: AppApi } {
  const g = golden as any;
  const token = jwt({ sub: "mock|user", exp: 9_999_999_999 });
  let settings: SettingsMap = {
    authSource: "auto",
    persistLocalRefresh: false,
    alertsEnabled: true,
    checkUpdates: false,
    refreshSeconds: 60,
    ballEnabled: true,
    dockEnabled: true,
    startHidden: true,
    launchAtStartup: false,
    ballSize: 120,
    ballOpacity: 100,
    dockWidth: 220,
    dockCompact: false,
    language: new URLSearchParams(location.search).get("lang") || "auto",
  };
  const history = [
    {
      cycleStart: String(Number(g.period.billingCycleStart) - 31 * 86_400_000),
      cycleEnd: String(g.period.billingCycleStart),
      planName: g.plan.planName,
      includedUsedCents: 2000,
      includedLimitCents: 2000,
      individualUsedCents: 55604,
      individualLimitCents: 60000,
      totalCents: 57604,
      eventCount: 1480,
      topModels: [{ model: "claude-4.5-opus-high-thinking", costCents: 41210 }],
      capturedAt: null,
      // Deterministic pseudo-random daily spend (API value), weekends quieter.
      dailyTotals: Array.from({ length: 31 }, (_, i) => Math.round((i % 7 === 5 || i % 7 === 6 ? 900 : 4200) * (0.6 + ((i * 37) % 11) / 10))),
    },
  ];
  const routes: Record<string, unknown> = {
    GetCurrentPeriodUsage: { ...g.period, autoBucketModels: ["default", "composer-2", "composer-2.5", "grok-4.5", "cursor-grok-4.5-high"] },
    GetPlanInfo: { planInfo: g.plan },
    GetUsageLimitPolicyStatus: {},
    "/api/auth/me": { id: 1, email: "you@example.com" },
    "get-filtered-usage-events": { totalUsageEventsCount: g.events.length, usageEventsDisplay: g.events },
  };
  const host: Host = {
    http: async (req: HttpRequest) => {
      await new Promise((r) => setTimeout(r, 250));
      const key = Object.keys(routes).find((k) => req.url.includes(k));
      return key ? { status: 200, headers: {}, body: JSON.stringify(routes[key]) } : { status: 404, headers: {}, body: "" };
    },
    envToken: async () => null,
    readLocalAuth: async () => ({ accessToken: token, cachedEmail: "you@example.com", stripeMembershipType: "team" }),
    writeLocalAuth: async () => {},
    getCredentials: async () => null,
    saveCredentials: async () => {},
    loadSettings: async () => settings as any,
    loadState: async () => ({ report: null, history, alerts: {} }),
    saveReport: async () => {},
    saveHistory: async () => {},
    saveAlertsState: async () => {},
    notify: async (title, message) => console.info("notify", title, message),
  };
  const api: AppApi = {
    loadSettings: async () => settings,
    saveSettings: async (patch) => (settings = { ...settings, ...patch }),
    saveCredentials: async () => {},
    clearCredentials: async () => settings,
    appInfo: async () => ({
      version: "dev",
      dataDir: "(mock)",
      platform: "browser",
      update: null,
      hasManualCredentials: false,
      hasRefreshToken: false,
      manualEmail: "",
      tokenPreview: "",
    }),
    componentStatus: async () => ({ ball: { running: true }, taskbarWidget: { state: "running", reason: "ok", visible: true } }),
    reembedDock: async () => {},
    exportFile: async (name, extension, content) => {
      console.info(name, extension, content.length);
      return "(mock)";
    },
    exportDiagnostics: async () => "(mock)",
    openUrl: async (url) => void window.open(url),
    log: async (level, message) => console.log(level, message),
    capabilities: { desktopWidgets: true, autostart: true, updates: true, localTokenRefresh: true, diagnostics: true },
  };
  return { host, api };
}
