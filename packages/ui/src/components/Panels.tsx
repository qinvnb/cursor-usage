/** Right-hand detail panels: one day, or one model. They link to each other. */
import { L, totalTokens, type Report } from "@cursor-usage/core";
import { useEffect } from "preact/hooks";
import type { DayPoint } from "../analysis";
import { count, dayLabel, dayTitle, tokens, usd } from "../format";
import { ColumnChart, Legend, SplitBar } from "./charts";
import { CloseIcon } from "./icons";
import { ModelName } from "./kit";
import { cacheHitRate, costPerRequest } from "./Tables";

function Panel({ title, onClose, children }: { title: preact.ComponentChildren; onClose: () => void; children: preact.ComponentChildren }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && (e.stopPropagation(), onClose());
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  return (
    <>
      <div class="scrim" onClick={onClose} />
      <aside class="drawer wide" role="dialog">
        <div class="drawer-head">
          <h2>{title}</h2>
          <button class="icon-btn" aria-label={L("关闭", "Close")} title={L("关闭（Esc）", "Close (Esc)")} onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
        <div class="drawer-body">{children}</div>
      </aside>
    </>
  );
}

function Kv({ items }: { items: [string, string][] }) {
  return (
    <div class="panel kv num">
      {items.map(([k, v]) => (
        <div key={k}>
          <span class="k">{k}</span>
          <span class="v">{v}</span>
        </div>
      ))}
    </div>
  );
}

const legendItems = () => [
  { label: L("套餐内（API 价）", "Included (API price)"), cls: "fill-included" },
  { label: L("个人按需", "On-demand"), cls: "fill-ondemand" },
];

export function DayPanel({ report, date, onClose, onPickModel }: { report: Report; date: string; onClose: () => void; onPickModel: (model: string) => void }) {
  const day = (report.daily || []).find((d) => d.date === date);
  const rows = report.dailyModels?.[date] || [];
  const inc = day?.includedCostCents || 0;
  const ond = day?.onDemandCostCents || 0;
  const dayTokens = report.dailyTokens?.[date];
  const hasTokens = rows.some((m) => m.tokens !== undefined);
  return (
    <Panel title={dayTitle(date)} onClose={onClose}>
      <Kv
        items={[
          [L("合计（API 价）", "Total (API price)"), usd(inc + ond)],
          [L("请求", "Requests"), count(day?.eventCount || 0)],
          [L("模型数", "Models"), String(rows.length)],
          [L("套餐内", "Included"), usd(inc)],
          [L("个人按需", "On-demand"), usd(ond)],
          [L("每次平均", "Per request"), usd(day?.eventCount ? (inc + ond) / day.eventCount : 0)],
          ...(dayTokens
            ? ([
                ["Token", tokens(totalTokens(dayTokens))],
                [L("输入 / 输出", "Input / output"), `${tokens(dayTokens.inputTokens)} / ${tokens(dayTokens.outputTokens)}`],
                [L("缓存读取 / 写入", "Cache read / write"), `${tokens(dayTokens.cacheReadTokens)} / ${tokens(dayTokens.cacheWriteTokens)}`],
              ] as [string, string][])
            : []),
        ]}
      />
      <div class="panel">
        {rows.length ? (
          <table>
            <thead>
              <tr>
                <th>{L("模型", "Model")}</th>
                <th class="r">{L("请求", "Requests")}</th>
                {hasTokens && <th class="r">Token</th>}
                <th class="r">{L("套餐内", "Included")}</th>
                <th class="r">{L("按需", "On-demand")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.model} class="clickable" onClick={() => onPickModel(m.model)}>
                  <td class="model">
                    <ModelName model={m.model} />
                  </td>
                  <td class="r num">{count(m.eventCount)}</td>
                  {hasTokens && <td class="r num">{tokens(m.tokens || 0)}</td>}
                  <td class="r num">{usd(m.includedCostCents)}</td>
                  <td class="r num">{usd(m.onDemandCostCents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div class="empty">
            {day?.eventCount ? L("明细将在下次完整同步后显示", "Details appear after the next full sync") : L("这一天没有用量", "No usage on this day")}
          </div>
        )}
      </div>
    </Panel>
  );
}

export function ModelPanel({
  report,
  model,
  points,
  onClose,
  onPickDay,
}: {
  report: Report;
  model: string;
  points: DayPoint[];
  onClose: () => void;
  onPickDay: (date: string) => void;
}) {
  const row = (report.models || []).find((m) => m.model === model);
  const total = (report.models || []).reduce((a, m) => a + m.totalCostCents, 0) || 1;
  const perDay = points.map((p) => (report.dailyModels?.[p.date] || []).find((m) => m.model === model));
  const inc = perDay.map((m) => m?.includedCostCents || 0);
  const ond = perDay.map((m) => m?.onDemandCostCents || 0);
  const activeDays = perDay.filter((m) => m && m.eventCount > 0).length;
  const allInput = row ? row.inputTokens + row.cacheReadTokens + row.cacheWriteTokens : 0;

  return (
    <Panel title={<ModelName model={model} />} onClose={onClose}>
      {row ? (
        <>
          <Kv
            items={[
              [L("合计（API 价）", "Total (API price)"), usd(row.totalCostCents)],
              [L("占全部模型", "Share of all models"), `${((row.totalCostCents / total) * 100).toFixed(1)}%`],
              ["Token", tokens(totalTokens(row))],
              [L("请求", "Requests"), count(row.eventCount)],
              [L("每次平均", "Per request"), usd(costPerRequest(row))],
              [L("缓存命中", "Cache hit"), `${(cacheHitRate(row) * 100).toFixed(0)}%`],
              [L("输出 / 全部输入", "Output / all input"), allInput ? (row.outputTokens / allInput).toFixed(3) : "—"],
            ]}
          />
          <section class="section">
            <div class="section-head">
              <h2>{L("每日用量", "Daily usage")}</h2>
              <span class="faint">{L(`${activeDays} 天有用量`, `${activeDays} active days`)}</span>
            </div>
            <div class="panel">
              <ColumnChart
                height={160}
                labels={points.map((p) => dayLabel(p.date))}
                bars={[
                  { key: "inc", label: L("套餐内", "Included"), cls: "fill-included", values: inc },
                  { key: "ond", label: L("按需", "On-demand"), cls: "fill-ondemand", values: ond },
                ]}
                onSelect={(i) => i !== null && onPickDay(points[i].date)}
                tooltip={(i) => ({
                  title: dayTitle(points[i].date),
                  rows: [
                    [L("套餐内", "Included"), usd(inc[i]), "fill-included"],
                    [L("按需", "On-demand"), usd(ond[i]), "fill-ondemand"],
                    [L("请求", "Requests"), count(perDay[i]?.eventCount || 0)],
                  ],
                })}
              />
              <Legend items={legendItems()} note={L("点击某天查看当天明细", "Click a day for its details")} />
            </div>
          </section>
          <section class="section">
            <div class="section-head">
              <h2>{L("Token 构成", "Token mix")}</h2>
            </div>
            <div class="panel">
              <SplitBar
                parts={[
                  { label: L("输入", "Input"), value: row.inputTokens, cls: "fill-included", text: tokens(row.inputTokens) },
                  { label: L("输出", "Output"), value: row.outputTokens, cls: "fill-ondemand", text: tokens(row.outputTokens) },
                  { label: L("缓存读取", "Cache read"), value: row.cacheReadTokens, cls: "fill-neutral", text: tokens(row.cacheReadTokens) },
                  { label: L("缓存写入", "Cache write"), value: row.cacheWriteTokens, cls: "fill-muted", text: tokens(row.cacheWriteTokens) },
                ]}
              />
            </div>
          </section>
        </>
      ) : (
        <div class="panel empty">{L("本周期没有这个模型的数据", "No data for this model this cycle")}</div>
      )}
    </Panel>
  );
}
