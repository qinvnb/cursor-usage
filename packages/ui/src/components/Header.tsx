import { L, type EngineStatus, type Lang, type Report } from "@cursor-usage/core";
import type { Cycle } from "../derive";
import { durationShort, relativeTime, shortDate } from "../format";
import { GlobeIcon, LogoMark, RefreshIcon, SlidersIcon } from "./icons";

interface Props {
  report: Report | null;
  cycle: Cycle | null;
  status: EngineStatus;
  now: number;
  lang: Lang;
  onLang: (lang: Lang) => void;
  onRefresh: () => void;
  onSettings: () => void;
  children?: preact.ComponentChildren;
}

function syncText(status: EngineStatus, now: number): { text: string; cls: string } {
  if (status.state === "running") {
    return { text: status.runningFull ? L("正在同步明细…", "Syncing details…") : L("正在同步…", "Syncing…"), cls: "running" };
  }
  if (status.state === "error") {
    const wait = status.retryAt ? durationShort(status.retryAt - now) : "";
    return { text: wait ? L(`同步失败，${wait}后重试`, `Sync failed, retry in ${wait}`) : L("同步失败", "Sync failed"), cls: "error" };
  }
  if (!status.lastSuccessAt) return { text: L("尚未同步", "Not synced yet"), cls: "" };
  return { text: L(`更新于${relativeTime(status.lastSuccessAt, now)}`, `Updated ${relativeTime(status.lastSuccessAt, now)}`), cls: "" };
}

/** Toolbar button in the same style as refresh / settings: globe + current language; click toggles. */
export function LangSwitch({ lang, onLang }: { lang: Lang; onLang: (lang: Lang) => void }) {
  const next: Lang = lang === "zh" ? "en" : "zh";
  const hint = next === "en" ? "Switch to English (L)" : "切换到中文（L）";
  return (
    <button class="icon-btn lang-btn" title={hint} aria-label={`Language / 语言: ${lang === "zh" ? "中文" : "English"}`} onClick={() => onLang(next)}>
      <GlobeIcon />
      <span lang={lang === "zh" ? "zh-CN" : "en"}>{lang === "zh" ? "中文" : "EN"}</span>
    </button>
  );
}

export function Header({ report, cycle, status, now, lang, onLang, onRefresh, onSettings, children }: Props) {
  const plan = report?.summary?.planName;
  const price = report?.summary?.planPrice;
  const email = report?.account?.email;
  const sync = syncText(status, now);
  return (
    <header class="header">
      <div class="header-row">
        <div>
          <div class="brand">
            <LogoMark />
            <h1>{L("Cursor 用量", "Cursor Usage")}</h1>
            {plan && (
              <span class="plan-chip">
                {plan}
                {price ? ` · ${price}` : ""}
              </span>
            )}
            {email && <span class="email hide-narrow">{email}</span>}
          </div>
          <div class="cycle-line num">
            {cycle ? (
              <>
                <span>
                  {shortDate(cycle.startMs)} – {shortDate(cycle.endMs)}
                </span>
                <span
                  class="day-pill"
                  title={L(`计费周期已过 ${Math.round(cycle.fraction * 100)}%`, `${Math.round(cycle.fraction * 100)}% of the billing cycle elapsed`)}
                >
                  {L(`第 ${cycle.dayNumber} / ${cycle.totalDays} 天`, `Day ${cycle.dayNumber} / ${cycle.totalDays}`)}
                  <span class="track">
                    <span style={{ width: `${cycle.fraction * 100}%` }} />
                  </span>
                  {L(`剩 ${Math.ceil(cycle.daysLeft)} 天`, `${Math.ceil(cycle.daysLeft)} days left`)}
                </span>
              </>
            ) : (
              <span>{report ? "" : L("正在读取本机 Cursor 登录…", "Reading the local Cursor sign-in…")}</span>
            )}
          </div>
        </div>
        <div class="actions">
          <span class={`sync ${sync.cls}`} title={status.lastError || undefined}>
            {sync.text}
          </span>
          <LangSwitch lang={lang} onLang={onLang} />
          <button
            class="icon-btn"
            title={L("立即刷新（R）", "Refresh now (R)")}
            aria-label={L("立即刷新", "Refresh now")}
            onClick={onRefresh}
            disabled={status.state === "running"}
          >
            <RefreshIcon spinning={status.state === "running"} />
          </button>
          <button class="icon-btn" title={L("设置（,）", "Settings (,)")} aria-label={L("设置", "Settings")} onClick={onSettings}>
            <SlidersIcon />
          </button>
        </div>
      </div>
      {children}
    </header>
  );
}
