import { L, type CycleSnapshot, type ModelRow, type Report } from "@cursor-usage/core";
import { useMemo, useState } from "preact/hooks";
import { count, dayTitle, shortDate, tokens, usd } from "../format";
import { ModelName } from "./kit";

// ---- Sortable table plumbing --------------------------------------------

export interface Column<T> {
  key: string;
  label: string;
  right?: boolean;
  narrowHidden?: boolean;
  value: (row: T) => number | string;
  render?: (row: T) => preact.ComponentChildren;
  csv?: (row: T) => string | number;
}

function useSort<T>(rows: T[], columns: Column<T>[], initial: string, initialDir: 1 | -1) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: initial, dir: initialDir });
  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    return [...rows].sort((a, b) => {
      const va = col.value(a);
      const vb = col.value(b);
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return cmp * sort.dir;
    });
  }, [rows, columns, sort]);
  const toggle = (key: string, numeric: boolean) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: numeric ? -1 : 1 }));
  return { sorted, sort, toggle };
}

export function Table<T>({
  rows,
  columns,
  initialSort,
  rowKey,
  initialDir = -1,
  onRowClick,
  activeKey,
}: {
  rows: T[];
  columns: Column<T>[];
  initialSort: string;
  rowKey: (r: T) => string;
  initialDir?: 1 | -1;
  onRowClick?: (r: T) => void;
  activeKey?: string | null;
}) {
  const { sorted, sort, toggle } = useSort(rows, columns, initialSort, initialDir);
  return (
    <div class="table-scroll">
    <table>
      <thead>
        <tr>
          {columns.map((c) => (
            <th
              key={c.key}
              class={`sortable${c.right ? " r" : ""}${c.narrowHidden ? " hide-narrow" : ""}`}
              aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
              tabIndex={0}
              onClick={() => toggle(c.key, !!c.right)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle(c.key, !!c.right))}
            >
              {c.label}
              <span class="dir">{sort.key === c.key ? (sort.dir === 1 ? "↑" : "↓") : ""}</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((row) => (
          <tr
            key={rowKey(row)}
            class={`${onRowClick ? "clickable" : ""}${activeKey && activeKey === rowKey(row) ? " active" : ""}`}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
          >
            {columns.map((c) => (
              <td key={c.key} class={`${c.right ? "r num" : ""}${c.key === "model" ? " model" : ""}${c.narrowHidden ? " hide-narrow" : ""}`}>
                {c.render ? c.render(row) : c.value(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

export function toCsv<T>(rows: T[], columns: Column<T>[]): string {
  const quote = (v: unknown) => {
    const s = String(v ?? "");
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map((c) => quote(c.label)).join(","), ...rows.map((r) => columns.map((c) => quote(c.csv ? c.csv(r) : c.value(r))).join(","))].join("\r\n");
}

// ---- Models -------------------------------------------------------------

const cents2 = (c: number) => (c / 100).toFixed(2);
const INITIAL_ROWS = 8;

export const cacheHitRate = (m: { inputTokens: number; cacheReadTokens: number }) => {
  const denom = m.inputTokens + m.cacheReadTokens;
  return denom > 0 ? m.cacheReadTokens / denom : 0;
};
export const costPerRequest = (m: { totalCostCents: number; eventCount: number }) => (m.eventCount > 0 ? m.totalCostCents / m.eventCount : 0);

export function ModelsTable({ report, onExport, onPick }: { report: Report; onExport: (name: string, csv: string) => void; onPick?: (model: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const rows = (report.models || []).filter((m) => m.totalCostCents > 0 || m.eventCount > 0);
  const total = rows.reduce((a, m) => a + m.totalCostCents, 0) || 1;

  const columns: Column<ModelRow>[] = [
    {
      key: "model",
      label: L("模型", "Model"),
      value: (m) => m.model,
      render: (m) => (
        <>
          <ModelName model={m.model} />
          <div class="share">
            <span class="inc" style={{ width: `${(m.includedCostCents / total) * 100}%` }} />
            <span class="ond" style={{ width: `${(m.onDemandCostCents / total) * 100}%` }} />
          </div>
        </>
      ),
    },
    { key: "events", label: L("请求", "Requests"), right: true, value: (m) => m.eventCount, render: (m) => count(m.eventCount) },
    { key: "input", label: L("输入", "Input"), right: true, narrowHidden: true, value: (m) => m.inputTokens, render: (m) => tokens(m.inputTokens) },
    { key: "output", label: L("输出", "Output"), right: true, narrowHidden: true, value: (m) => m.outputTokens, render: (m) => tokens(m.outputTokens) },
    { key: "cache", label: L("缓存读取", "Cache read"), right: true, narrowHidden: true, value: (m) => m.cacheReadTokens, render: (m) => tokens(m.cacheReadTokens) },
    {
      key: "hit",
      label: L("缓存命中", "Cache hit"),
      right: true,
      narrowHidden: true,
      value: cacheHitRate,
      render: (m) => `${(cacheHitRate(m) * 100).toFixed(0)}%`,
      csv: (m) => (cacheHitRate(m) * 100).toFixed(1),
    },
    { key: "per", label: L("每次", "Per req"), right: true, value: costPerRequest, render: (m) => usd(costPerRequest(m)), csv: (m) => (costPerRequest(m) / 100).toFixed(4) },
    { key: "included", label: L("套餐内", "Included"), right: true, value: (m) => m.includedCostCents, render: (m) => usd(m.includedCostCents), csv: (m) => cents2(m.includedCostCents) },
    { key: "ondemand", label: L("按需", "On-demand"), right: true, value: (m) => m.onDemandCostCents, render: (m) => usd(m.onDemandCostCents), csv: (m) => cents2(m.onDemandCostCents) },
    { key: "total", label: L("合计", "Total"), right: true, value: (m) => m.totalCostCents, render: (m) => usd(m.totalCostCents), csv: (m) => cents2(m.totalCostCents) },
  ];
  const visible = expanded ? rows : rows.slice(0, INITIAL_ROWS);

  return (
    <section class="section">
      <div class="section-head">
        <h2>{L("模型", "Models")}</h2>
        {rows.length > 0 && (
          <button class="link-btn" onClick={() => onExport(L("模型用量", "model-usage"), toCsv(rows, columns))}>
            {L("导出 CSV", "Export CSV")}
          </button>
        )}
      </div>
      <div class="panel">
        {rows.length ? (
          <>
            <Table rows={visible} columns={columns} initialSort="total" rowKey={(m) => m.model} onRowClick={onPick ? (m) => onPick(m.model) : undefined} />
            {rows.length > INITIAL_ROWS && (
              <div class="table-foot">
                <span>{L(`共 ${rows.length} 个模型`, `${rows.length} models`)}</span>
                <button class="link-btn" onClick={() => setExpanded(!expanded)}>
                  {expanded ? L("收起", "Show less") : L("显示全部", "Show all")}
                </button>
              </div>
            )}
          </>
        ) : (
          <div class="empty">{L("本周期暂无模型用量明细", "No model usage this cycle yet")}</div>
        )}
      </div>
    </section>
  );
}

// ---- Day detail ----------------------------------------------------------

export function DayDetail({ report, date, onClose }: { report: Report; date: string; onClose: () => void }) {
  const rows = report.dailyModels?.[date] || [];
  const day = (report.daily || []).find((d) => d.date === date);
  return (
    <div class="day-detail">
      <button class="link-btn close" onClick={onClose}>
        {L("关闭", "Close")}
      </button>
      <h3 class="num">
        {dayTitle(date)} · {usd((day?.includedCostCents || 0) + (day?.onDemandCostCents || 0))} ·{" "}
        {L(`${count(day?.eventCount || 0)} 次请求`, `${count(day?.eventCount || 0)} requests`)}
      </h3>
      {rows.length ? (
        <table>
          <thead>
            <tr>
              <th>{L("模型", "Model")}</th>
              <th class="r">{L("请求", "Requests")}</th>
              <th class="r">{L("套餐内", "Included")}</th>
              <th class="r">{L("按需", "On-demand")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.model}>
                <td class="model">
                  <ModelName model={m.model} />
                </td>
                <td class="r num">{count(m.eventCount)}</td>
                <td class="r num">{usd(m.includedCostCents)}</td>
                <td class="r num">{usd(m.onDemandCostCents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div class="faint">
          {day?.eventCount ? L("明细将在下次完整同步后显示", "Details appear after the next full sync") : L("这一天没有用量", "No usage on this day")}
        </div>
      )}
    </div>
  );
}

// ---- History ---------------------------------------------------------------

interface HistoryRow extends CycleSnapshot {
  live: boolean;
  delta: number | null;
}

export function HistoryTable({ history, current, onExport }: { history: CycleSnapshot[]; current: CycleSnapshot | null; onExport: (name: string, csv: string) => void }) {
  const base: (CycleSnapshot & { live: boolean })[] = history.map((c) => ({ ...c, live: false }));
  if (current && !base.some((c) => c.cycleStart === current.cycleStart)) base.push({ ...current, live: true });
  if (base.length < 2) return null;
  const rows: HistoryRow[] = base.map((c, i) => {
    const prev = base[i - 1];
    return { ...c, delta: prev && prev.totalCents > 0 && !c.live ? (c.totalCents - prev.totalCents) / prev.totalCents : null };
  });
  const columns: Column<HistoryRow>[] = [
    {
      key: "cycle",
      label: L("计费周期", "Billing cycle"),
      value: (c) => Number(c.cycleStart),
      render: (c) => (
        <span class="num">
          {shortDate(c.cycleStart)} – {shortDate(c.cycleEnd)}
          {c.live && <span class="faint">{L("（进行中）", " (current)")}</span>}
        </span>
      ),
      csv: (c) => `${shortDate(c.cycleStart)} – ${shortDate(c.cycleEnd)}`,
    },
    { key: "included", label: L("套餐内", "Included"), right: true, value: (c) => c.includedUsedCents, render: (c) => usd(c.includedUsedCents), csv: (c) => cents2(c.includedUsedCents) },
    { key: "ondemand", label: L("按需", "On-demand"), right: true, value: (c) => c.individualUsedCents, render: (c) => usd(c.individualUsedCents), csv: (c) => cents2(c.individualUsedCents) },
    { key: "total", label: L("合计", "Total"), right: true, value: (c) => c.totalCents, render: (c) => usd(c.totalCents), csv: (c) => cents2(c.totalCents) },
    {
      key: "delta",
      label: L("较上期", "vs. previous"),
      right: true,
      value: (c) => c.delta ?? -Infinity,
      render: (c) =>
        c.delta === null ? <span class="faint">—</span> : <span class={c.delta > 0.03 ? "up" : c.delta < -0.03 ? "down" : ""}>{`${c.delta > 0 ? "+" : ""}${Math.round(c.delta * 100)}%`}</span>,
      csv: (c) => (c.delta === null ? "" : `${Math.round(c.delta * 100)}%`),
    },
    {
      key: "top",
      label: L("主要模型", "Top model"),
      narrowHidden: true,
      value: (c) => c.topModels?.[0]?.model || "",
      render: (c) => (c.topModels?.[0]?.model ? <ModelName model={c.topModels[0].model} /> : <span class="faint">—</span>),
    },
  ];
  return (
    <section class="section">
      <div class="section-head">
        <h2>{L("历史周期", "Past cycles")}</h2>
        <button class="link-btn" onClick={() => onExport(L("历史周期", "history"), toCsv(rows, columns))}>
          {L("导出 CSV", "Export CSV")}
        </button>
      </div>
      <div class="panel">
        <Table rows={rows} columns={columns} initialSort="cycle" rowKey={(c) => c.cycleStart} />
      </div>
    </section>
  );
}
