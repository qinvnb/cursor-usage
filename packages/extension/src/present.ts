/** Status bar text/tooltip and webview HTML: pure functions, unit-tested. */
import { L, type EngineStatus, type WidgetSummary } from "@cursor-usage/core";

export type StatusBarMode = "auto" | "ondemand" | "included" | "both" | "hidden";
export type Level = "ok" | "warn" | "danger";

const usd = (cents: number | null | undefined, compact = false) => {
  const d = Number(cents || 0) / 100;
  if (compact && d >= 100) return `$${Math.round(d).toLocaleString("en-US")}`;
  return `$${d.toFixed(2)}`;
};

export function levelOf(used: number, limit: number, thresholds: number[] = [80, 95]): Level {
  if (limit <= 0) return "ok";
  const pct = (used / limit) * 100;
  const sorted = [...thresholds].sort((a, b) => a - b);
  if (pct >= (sorted[sorted.length - 1] ?? 95)) return "danger";
  if (pct >= (sorted[0] ?? 80)) return "warn";
  return "ok";
}

export interface StatusView {
  text: string;
  level: Level;
  tooltip: string;
}

export function statusView(summary: WidgetSummary | null, status: EngineStatus, mode: StatusBarMode, thresholds?: number[]): StatusView {
  if (!summary) {
    const text = status.state === "error" ? `$(warning) ${L("用量", "Usage")}` : `$(sync~spin) ${L("用量", "Usage")}`;
    return { text, level: status.state === "error" ? "warn" : "ok", tooltip: status.lastError || L("正在同步 Cursor 用量…", "Syncing Cursor usage…") };
  }
  const inc = { used: Number(summary.includedUsedCents || 0), limit: Number(summary.includedLimitCents || 0) };
  const ond = { used: summary.individualUsedCents, limit: summary.individualLimitCents };
  const pools = poolsOf(summary);
  // With pools, the API pool is what named-model requests fall through from.
  const includedLeft = pools ? pools.api < 100 : inc.limit > 0 && inc.used < inc.limit;
  const show = mode === "auto" ? (includedLeft ? "included" : "ondemand") : mode;
  const part = (b: { used: number; limit: number }) => (b.limit > 0 ? `${usd(b.used, true)} / ${usd(b.limit, true)}` : usd(b.used, true));
  const incPart = pools ? `Auto ${pct(pools.auto)} · API ${pct(pools.api)}` : part(inc);
  const plan = L("套餐", "Plan");
  const onDemand = L("按需", "On-demand");
  const text =
    show === "both"
      ? `$(pulse) ${plan} ${incPart} · ${onDemand} ${part(ond)}`
      : show === "included"
        ? `$(pulse) ${plan} ${incPart}`
        : `$(pulse) ${onDemand} ${part(ond)}`;
  const incLevel = pools ? worst(levelOf(pools.auto, 100, thresholds), levelOf(pools.api, 100, thresholds)) : levelOf(inc.used, inc.limit, thresholds);
  const level =
    show === "both"
      ? worst(incLevel, levelOf(ond.used, ond.limit, thresholds))
      : show === "included"
        ? incLevel
        : levelOf(ond.used, ond.limit, thresholds);
  const incRows = pools
    ? [
        `| ${L("套餐内 · Cursor 模型（Auto）", "Included · Cursor models (Auto)")} | ${pct(pools.auto)} | 100% | ${pct(Math.max(0, 100 - pools.auto))} |`,
        `| ${L("套餐内 · 其他模型（API）", "Included · Other models (API)")} | ${pct(pools.api)} | 100% | ${pct(Math.max(0, 100 - pools.api))} |`,
      ]
    : [`| ${L("套餐内", "Included")} | ${usd(inc.used)} | ${usd(inc.limit)} | ${usd(Math.max(0, inc.limit - inc.used))} |`];
  const lines = [
    `**${L("Cursor 用量", "Cursor Usage")}**`,
    "",
    `| | ${L("已用", "Used")} | ${L("上限", "Limit")} | ${L("剩余", "Left")} |`,
    `|---|---:|---:|---:|`,
    ...incRows,
    `| ${L("个人按需", "On-demand")} | ${usd(ond.used)} | ${usd(ond.limit)} | ${usd(summary.individualRemainingCents)} |`,
    "",
    ...(summary.tokens ? [tokenLine(summary.tokens), ""] : []),
    status.state === "error"
      ? `${L("同步失败", "Sync failed")}: ${status.lastError}`
      : status.lastSuccessAt
        ? `${L("更新于", "Updated")} ${new Date(status.lastSuccessAt).toLocaleTimeString()}`
        : "",
    "",
    L("点击打开用量看板", "Click to open the usage dashboard"),
  ];
  return { text, level, tooltip: lines.join("\n") };
}

const pct = (v: number) => `${Math.round(v)}%`;

export function tokenCount(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(Math.round(n));
}

function tokenLine(t: NonNullable<WidgetSummary["tokens"]>): string {
  const parts = [
    [L("输入", "input"), t.inputTokens],
    [L("输出", "output"), t.outputTokens],
    [L("缓存读取", "cache read"), t.cacheReadTokens],
    [L("缓存写入", "cache write"), t.cacheWriteTokens],
  ]
    .map(([k, v]) => `${k} ${tokenCount(Number(v))}`)
    .join(" · ");
  return L(`本周期 Token：${tokenCount(t.total)}（${parts}）`, `Tokens this cycle: ${tokenCount(t.total)} (${parts})`);
}

/** Included pools in percent, or null when the plan reports a single dollar amount. */
function poolsOf(summary: WidgetSummary): { auto: number; api: number } | null {
  if (summary.autoPercentUsed == null && summary.apiPercentUsed == null) return null;
  return { auto: Number(summary.autoPercentUsed || 0), api: Number(summary.apiPercentUsed || 0) };
}

function worst(a: Level, b: Level): Level {
  const rank = { ok: 0, warn: 1, danger: 2 } as const;
  return rank[a] >= rank[b] ? a : b;
}

export function summaryText(summary: WidgetSummary | null): string {
  if (!summary) return L("Cursor 用量：尚未同步", "Cursor usage: not synced yet");
  const pools = poolsOf(summary);
  const title = L("Cursor 用量", "Cursor usage");
  return [
    summary.planName ? L(`${title}（${summary.planName}）`, `${title} (${summary.planName})`) : title,
    ...(pools
      ? [
          L(`套餐内 Cursor 模型（Auto）：已用 ${pct(pools.auto)}`, `Included Cursor models (Auto): ${pct(pools.auto)} used`),
          L(`套餐内其他模型（API）：已用 ${pct(pools.api)}`, `Included other models (API): ${pct(pools.api)} used`),
        ]
      : [L(`套餐内：${usd(summary.includedUsedCents)} / ${usd(summary.includedLimitCents)}`, `Included: ${usd(summary.includedUsedCents)} / ${usd(summary.includedLimitCents)}`)]),
    L(
      `个人按需：${usd(summary.individualUsedCents)} / ${usd(summary.individualLimitCents)}，剩余 ${usd(summary.individualRemainingCents)}`,
      `On-demand: ${usd(summary.individualUsedCents)} / ${usd(summary.individualLimitCents)}, ${usd(summary.individualRemainingCents)} left`,
    ),
    ...(summary.tokens ? [tokenLine(summary.tokens)] : []),
  ].join("\n");
}

/**
 * Inject a strict CSP, a nonce, and the editor's display language (used when
 * the language setting is "auto") into the single-file dashboard.
 */
export function dashboardHtml(raw: string, nonce: string, cspSource: string, locale = ""): string {
  const csp = [
    "default-src 'none'",
    `script-src 'nonce-${nonce}'`,
    // Inline style attributes (Preact style props) need 'unsafe-inline'.
    `style-src ${cspSource} 'unsafe-inline'`,
    `img-src ${cspSource} data:`,
    `font-src ${cspSource}`,
  ].join("; ");
  const meta = `<meta http-equiv="Content-Security-Policy" content="${csp}">`;
  const localeScript = `<script>window.__cursorUsageLocale=${JSON.stringify(String(locale)).replace(/</g, "\\u003c")};</script>`;
  const withMeta = raw.replace(/<head>/i, `<head>\n    ${meta}\n    ${localeScript}`);
  return withMeta.replace(/<script(?![^>]*\bnonce=)/gi, `<script nonce="${nonce}"`);
}
