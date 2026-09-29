import { L, totalTokens, type Report, type TokenCounts } from "@cursor-usage/core";
import { useState } from "preact/hooks";
import type { DaySeries } from "../derive";
import { count, dayLabel, dayTitle, tokens, usd } from "../format";
import { ColumnChart, Legend, type TipRow } from "./charts";

interface Props {
  series: DaySeries;
  selected: string | null;
  onSelect: (date: string | null) => void;
  includedLimitCents: number;
  /** Per-day token counts; enables the Token view when present. */
  dailyTokens?: Report["dailyTokens"];
  title?: string;
  children?: preact.ComponentChildren;
}

type Mode = "daily" | "cumulative" | "tokens";

export const TOKEN_PARTS = (): { key: keyof TokenCounts; label: string; cls: string }[] => [
  { key: "inputTokens", label: L("输入", "Input"), cls: "fill-included" },
  { key: "outputTokens", label: L("输出", "Output"), cls: "fill-ondemand" },
  { key: "cacheReadTokens", label: L("缓存读取", "Cache read"), cls: "fill-neutral" },
  { key: "cacheWriteTokens", label: L("缓存写入", "Cache write"), cls: "fill-muted" },
];

/** Whole-cycle daily chart (future days as placeholders), with cumulative and token views. */
export function DailyChart({ series, selected, onSelect, includedLimitCents, dailyTokens, title, children }: Props) {
  const [mode, setMode] = useState<Mode>("daily");
  const { rows, todayKey } = series;
  const todayIndex = rows.findIndex((r) => r.date === todayKey);
  const futureFrom = todayIndex >= 0 ? todayIndex + 1 : rows.findIndex((r) => r.date > todayKey);
  const cumulative: number[] = [];
  let running = 0;
  for (const r of rows) {
    running += r.onDemandCostCents + r.includedCostCents;
    cumulative.push(running);
  }
  const selectedIndex = selected ? rows.findIndex((r) => r.date === selected) : -1;
  const hasTokens = !!dailyTokens && Object.keys(dailyTokens).length > 0;
  const view: Mode = mode === "tokens" && !hasTokens ? "daily" : mode;
  const tokenOf = (date: string, key: keyof TokenCounts) => Number(dailyTokens?.[date]?.[key] || 0);

  const bars =
    view === "daily"
      ? [
          { key: "inc", label: L("套餐内", "Included"), cls: "fill-included", values: rows.map((r) => r.includedCostCents) },
          { key: "ond", label: L("按需", "On-demand"), cls: "fill-ondemand", values: rows.map((r) => r.onDemandCostCents) },
        ]
      : view === "tokens"
        ? TOKEN_PARTS().map((p) => ({ key: p.key, label: p.label, cls: p.cls, values: rows.map((r) => tokenOf(r.date, p.key)) }))
        : [];

  return (
    <section class="section">
      <div class="section-head">
        <h2>{title ?? L("每日用量", "Daily usage")}</h2>
        <div class="segmented" role="group" aria-label={L("图表模式", "Chart mode")}>
          <button aria-pressed={view === "daily"} onClick={() => setMode("daily")}>
            {L("每日", "Daily")}
          </button>
          <button aria-pressed={view === "cumulative"} onClick={() => setMode("cumulative")}>
            {L("累计", "Cumulative")}
          </button>
          {hasTokens && (
            <button aria-pressed={view === "tokens"} onClick={() => setMode("tokens")}>
              Token
            </button>
          )}
        </div>
      </div>
      <div class="panel">
        <ColumnChart
          height={200}
          labels={rows.map((r) => (r.date === todayKey ? L("今天", "Today") : dayLabel(r.date)))}
          highlight={todayIndex >= 0 ? todayIndex : undefined}
          futureFrom={futureFrom >= 0 ? futureFrom : undefined}
          bars={bars}
          lines={view === "cumulative" ? [{ key: "cum", label: L("累计", "Cumulative"), cls: "line-main", values: cumulative, area: true }] : []}
          refLine={
            view === "cumulative" && includedLimitCents > 0
              ? { value: includedLimitCents, label: L(`套餐内额度 ${usd(includedLimitCents)}`, `Included ${usd(includedLimitCents)}`) }
              : undefined
          }
          yFormat={view === "tokens" ? (v) => tokens(v) : undefined}
          selected={selectedIndex >= 0 ? selectedIndex : null}
          onSelect={(i) => onSelect(i === null ? null : rows[i].date)}
          tooltip={(i) => {
            const r = rows[i];
            if (view === "tokens") {
              const day = dailyTokens?.[r.date];
              return {
                title: dayTitle(r.date),
                rows: [
                  ...TOKEN_PARTS().map((p) => [p.label, tokens(tokenOf(r.date, p.key)), p.cls] as TipRow),
                  [L("合计", "Total"), tokens(totalTokens(day))],
                ],
              };
            }
            const out: TipRow[] = [
              [L("套餐内", "Included"), usd(r.includedCostCents), "fill-included"],
              [L("按需", "On-demand"), usd(r.onDemandCostCents), "fill-ondemand"],
              [L("请求", "Requests"), count(r.eventCount)],
            ];
            const dayTokens = totalTokens(dailyTokens?.[r.date]);
            if (dayTokens > 0) out.push(["Token", tokens(dayTokens)]);
            if (view === "cumulative") out.push([L("累计", "Cumulative"), usd(cumulative[i])]);
            return { title: dayTitle(r.date), rows: out };
          }}
        />
        <Legend
          items={
            view === "tokens"
              ? TOKEN_PARTS().map((p) => ({ label: p.label, cls: p.cls }))
              : [
                  { label: L("套餐内（API 价）", "Included (API price)"), cls: "fill-included" },
                  { label: L("个人按需", "On-demand"), cls: "fill-ondemand" },
                ]
          }
          note={L("点击某一天查看模型明细", "Click a day for its model breakdown")}
        />
        {children}
      </div>
    </section>
  );
}
