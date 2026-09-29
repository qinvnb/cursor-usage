import { getLang, L, onLangChange, resolveLang, setLang, type EngineSnapshot, type Lang } from "@cursor-usage/core";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { buildSeries } from "../analysis";
import type { AppApi, EngineApi, SettingsMap } from "../api";
import { cycleOf, daySeries } from "../derive";
import { Header } from "./Header";
import { DailyPage, HistoryPage, IncludedPage, ModelsPage, OnDemandPage, OverviewPage, type PageContext } from "./Pages";
import { DayPanel, ModelPanel } from "./Panels";
import { SettingsDrawer } from "./Settings";

export interface AppProps {
  engine: EngineApi;
  api: AppApi;
  active: { value: boolean; subscribe: (fn: (v: boolean) => void) => () => void };
  settingsVersion: { subscribe: (fn: () => void) => () => void };
}

export const TABS = [
  { id: "home", label: () => L("总览", "Overview"), page: OverviewPage },
  { id: "ondemand", label: () => L("个人按需", "On-demand"), page: OnDemandPage },
  { id: "included", label: () => L("套餐内", "Included"), page: IncludedPage },
  { id: "daily", label: () => L("日期", "Daily"), page: DailyPage },
  { id: "models", label: () => L("模型", "Models"), page: ModelsPage },
  { id: "history", label: () => L("历史周期", "History"), page: HistoryPage },
] as const;

/** Apply a saved language preference; "auto" follows the editor locale (plugin) or the browser locale. */
export function applyLanguage(pref: unknown): Lang {
  const editorLocale = typeof window !== "undefined" ? (window as { __cursorUsageLocale?: string }).__cursorUsageLocale : "";
  const lang = resolveLang(pref, editorLocale || (typeof navigator !== "undefined" ? navigator.language : ""));
  setLang(lang);
  if (typeof document !== "undefined") document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  return lang;
}
type TabId = (typeof TABS)[number]["id"];
const isTab = (v: unknown): v is TabId => TABS.some((t) => t.id === v);

type Overlay = { kind: "settings" } | { kind: "day"; date: string } | { kind: "model"; model: string } | null;

function useNow(active: AppProps["active"]): number {
  const [now, setNow] = useState(Date.now());
  const [isActive, setActive] = useState(active.value);
  useEffect(() => active.subscribe(setActive), []);
  useEffect(() => {
    if (!isActive) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, [isActive]);
  return now;
}

/** `?open=settings | day:YYYY-MM-DD | model:NAME` opens a panel on load (screenshots, deep links). */
function initialOverlay(): Overlay {
  const open = new URLSearchParams(location.search).get("open") || "";
  if (open === "settings") return { kind: "settings" };
  if (open.startsWith("day:")) return { kind: "day", date: open.slice(4) };
  if (open.startsWith("model:")) return { kind: "model", model: open.slice(6) };
  return null;
}

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

export function App({ engine, api, active, settingsVersion }: AppProps) {
  const [snap, setSnap] = useState<EngineSnapshot>(engine.snapshot());
  const [settings, setSettings] = useState<SettingsMap>({});
  const [overlay, setOverlay] = useState<Overlay>(initialOverlay);
  const hashTab = location.hash.slice(1);
  const [tab, setTab] = useState<TabId>(isTab(hashTab) ? hashTab : "home");
  const restored = useRef(isTab(hashTab));
  const now = useNow(active);
  const [lang, setLangState] = useState<Lang>(getLang);
  useEffect(() => onLangChange(setLangState), []);
  const changeLang = (next: Lang) => {
    applyLanguage(next);
    setSettings((s) => ({ ...s, language: next }));
    void api.saveSettings({ language: next }).catch(() => {});
  };

  useEffect(() => {
    const unsubscribe = engine.subscribe(setSnap);
    // A snapshot may have arrived between the first render and this subscription.
    setSnap(engine.snapshot());
    return unsubscribe;
  }, []);
  useEffect(() => {
    const load = () =>
      api
        .loadSettings()
        .then((s) => {
          setSettings(s);
          applyLanguage(s.language);
          if (!restored.current) {
            restored.current = true;
            if (isTab(s.lastView)) setTab(s.lastView);
          }
        })
        .catch(() => {});
    load();
    return settingsVersion.subscribe(load);
  }, []);

  const selectTab = (id: TabId) => {
    setTab(id);
    restored.current = true;
    void api.saveSettings({ lastView: id }).catch(() => {});
  };
  const refresh = () => void engine.refresh({ full: true });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      if (e.key === "Escape") return setOverlay(null);
      if (overlay) return;
      const index = Number(e.key) - 1;
      if (Number.isInteger(index) && index >= 0 && index < TABS.length) return selectTab(TABS[index].id);
      if (e.key === "r" || e.key === "R") return refresh();
      if (e.key === ",") return setOverlay({ kind: "settings" });
      if (e.key === "l" || e.key === "L") return changeLang(getLang() === "zh" ? "en" : "zh");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [overlay]);

  const { report, history, status } = snap;
  const cycle = useMemo(() => (report ? cycleOf(report, now) : null), [report, now]);
  const days = useMemo(() => (report ? daySeries(report, now) : null), [report, now]);
  const series = useMemo(() => (report ? buildSeries(report, now) : null), [report, now]);
  const onExport = (name: string, csv: string) => void api.exportFile(name, "csv", csv).catch(() => {});
  const Page = TABS.find((t) => t.id === tab)!.page;
  const ctx: PageContext | null =
    report && days && series
      ? {
          report,
          cycle,
          days,
          series,
          history,
          onExport,
          onPickDay: (date) => setOverlay({ kind: "day", date }),
          onPickModel: (model) => setOverlay({ kind: "model", model }),
        }
      : null;

  return (
    <div class="page">
      <Header
        report={report}
        cycle={cycle}
        status={status}
        now={now}
        lang={lang}
        onLang={changeLang}
        onRefresh={refresh}
        onSettings={() => setOverlay({ kind: "settings" })}
      >
        <nav class="tabs" role="tablist" aria-label={L("分析页面", "Pages")}>
          {TABS.map((t, i) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => selectTab(t.id)} title={L(`快捷键 ${i + 1}`, `Shortcut ${i + 1}`)}>
              {t.label()}
            </button>
          ))}
        </nav>
      </Header>

      {status.state === "error" && status.lastError && (
        <div class="banner">
          <strong>{L("同步失败", "Sync failed")}</strong>
          {report ? L("，正在显示上次的数据。", ", showing the last data. ") : L("。", ". ")}
          {status.lastError}
        </div>
      )}

      {ctx ? <Page {...ctx} /> : status.state !== "error" && <Placeholder />}

      {overlay?.kind === "settings" && (
        <SettingsDrawer
          api={api}
          report={report}
          settings={settings}
          onChange={setSettings}
          onClose={() => setOverlay(null)}
          onCredentialsChanged={refresh}
        />
      )}
      {overlay?.kind === "day" && report && (
        <DayPanel report={report} date={overlay.date} onClose={() => setOverlay(null)} onPickModel={(model) => setOverlay({ kind: "model", model })} />
      )}
      {overlay?.kind === "model" && report && series && (
        <ModelPanel
          report={report}
          model={overlay.model}
          points={series.points}
          onClose={() => setOverlay(null)}
          onPickDay={(date) => setOverlay({ kind: "day", date })}
        />
      )}
    </div>
  );
}

function Placeholder() {
  return (
    <div class="quota-cards" aria-busy="true">
      {[0, 1].map((i) => (
        <div class="panel quota-card" key={i}>
          <div class="skeleton" style={{ width: "88px", height: "88px", borderRadius: "50%" }} />
          <div class="quota-main">
            <div class="skeleton" style={{ width: "80px", height: "14px" }} />
            <div class="skeleton" style={{ width: "160px", height: "30px", marginTop: "10px" }} />
            <div class="skeleton" style={{ width: "120px", height: "12px", marginTop: "12px" }} />
          </div>
        </div>
      ))}
    </div>
  );
}
