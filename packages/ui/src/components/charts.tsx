import { Fragment } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { niceCeil } from "../derive";
import { L } from "@cursor-usage/core";
import { times, usd, weekdayName } from "../format";
import { Chip, ModelDot, Sparkline, type Tone } from "./kit";

export function useWidth<T extends Element>(): [preact.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.round(entry.contentRect.width))));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

export interface BarSeries {
  key: string;
  label: string;
  /** CSS class for the rect fill (see styles.css .fill-*). */
  cls: string;
  values: number[];
}

export interface LineSeries {
  key: string;
  label: string;
  cls: string;
  values: (number | null)[];
  area?: boolean;
}

export type TipRow = [string, string] | [string, string, string];

export interface ColumnChartProps {
  /** One label per slot (x axis). */
  labels: string[];
  bars?: BarSeries[];
  lines?: LineSeries[];
  refLine?: { value: number; label: string };
  height?: number;
  /** Slots at/after this index are drawn as empty future days. */
  futureFrom?: number;
  /** Slot rendered as the emphasized "today" label. */
  highlight?: number;
  selected?: number | null;
  onSelect?: (index: number | null) => void;
  /** Rows are [label, value, optional swatch class]. */
  tooltip?: (index: number) => { title: string; rows: TipRow[] };
  yFormat?: (cents: number) => string;
}

const PAD = { top: 8, right: 8, bottom: 22, left: 48 };

/** Stacked columns plus optional lines, drawn in cents on a shared y axis. */
export function ColumnChart({
  labels,
  bars = [],
  lines = [],
  refLine,
  height = 180,
  futureFrom,
  highlight,
  selected = null,
  onSelect,
  tooltip,
  yFormat = (c) => usd(c, { compact: true }),
}: ColumnChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const n = Math.max(1, labels.length);
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const slot = plotW / n;
  const barW = Math.max(2, Math.min(28, slot * 0.64));
  const future = futureFrom ?? n;

  let max = refLine?.value ?? 0;
  for (let i = 0; i < n; i++) {
    const stacked = bars.reduce((a, s) => a + (s.values[i] || 0), 0);
    max = Math.max(max, stacked, ...lines.map((l) => l.values[i] ?? 0));
  }
  const yMax = niceCeil(max / 100) * 100;
  const y = (cents: number) => PAD.top + plotH - (cents / yMax) * plotH;
  const x = (i: number) => PAD.left + slot * i + slot / 2;
  const fit = Math.max(1, Math.floor(plotW / 44));
  const every = Math.max(1, Math.ceil(n / fit));
  const showLabel = (i: number) =>
    i === highlight || (i % every === 0 && (highlight === undefined || Math.abs(i - highlight) >= Math.max(2, every)));

  const linePath = (values: (number | null)[]) => {
    let d = "";
    values.forEach((v, i) => {
      if (v === null || i >= future) return;
      d += `${d ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    });
    return d;
  };

  const tip = hover !== null && tooltip ? tooltip(hover) : null;
  const tipLeft = hover !== null ? Math.min(Math.max(x(hover) - 80, 0), width - 170) : 0;

  return (
    <div class="chart" ref={ref} onMouseLeave={() => setHover(null)}>
      <svg height={height} viewBox={`0 0 ${width} ${height}`} role="img">
        <g class="grid">
          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(f * yMax)} y2={y(f * yMax)} />
              <text x={PAD.left - 8} y={y(f * yMax) + 4} text-anchor="end" class="num">
                {yFormat(f * yMax)}
              </text>
            </g>
          ))}
        </g>

        {selected !== null && selected < future && (
          <rect class="col-selected" x={PAD.left + slot * selected} y={PAD.top} width={slot} height={plotH} rx={4} />
        )}
        {hover !== null && hover !== selected && hover < future && (
          <rect class="col-hover" x={PAD.left + slot * hover} y={PAD.top} width={slot} height={plotH} rx={4} />
        )}

        {labels.map((_, i) => {
          const cx = x(i) - barW / 2;
          if (i >= future) {
            return bars.length ? <rect key={i} class="bar-future" x={cx} y={y(0) - 2} width={barW} height={2} rx={1} /> : null;
          }
          let base = 0;
          return (
            <g key={i}>
              {bars.map((s) => {
                const v = s.values[i] || 0;
                if (v <= 0) return null;
                const top = y(base + v);
                const h = Math.max(1, y(base) - top);
                base += v;
                return <rect key={s.key} class={`bar ${s.cls}`} x={cx} y={top} width={barW} height={h} rx={Math.min(3, barW / 3)} />;
              })}
            </g>
          );
        })}

        {lines.map((l) => {
          const d = linePath(l.values);
          if (!d) return null;
          const lastIndex = Math.min(future, n) - 1;
          return (
            <g key={l.key}>
              {l.area && <path class={`area${l.cls === "line-accent" ? " ondemand" : ""}`} d={`${d}L${x(lastIndex).toFixed(1)},${y(0)}L${x(0).toFixed(1)},${y(0)}Z`} />}
              <path class={l.cls} d={d} />
            </g>
          );
        })}

        {refLine && refLine.value > 0 && refLine.value <= yMax && (
          <g>
            <line class="limit" x1={PAD.left} x2={width - PAD.right} y1={y(refLine.value)} y2={y(refLine.value)} />
            <text class="limit-label" x={width - PAD.right} y={y(refLine.value) - 5} text-anchor="end">
              {refLine.label}
            </text>
          </g>
        )}

        <g class="axis">
          {labels.map((label, i) =>
            showLabel(i) ? (
              <text key={i} x={x(i)} y={height - 6} text-anchor="middle" class={i === highlight ? "today num" : "num"}>
                {label}
              </text>
            ) : null,
          )}
        </g>

        {(tooltip || onSelect) &&
          labels.map((_, i) =>
            i >= future ? null : (
              <rect
                key={i}
                class={`hit${onSelect ? "" : " passive"}`}
                x={PAD.left + slot * i}
                y={PAD.top}
                width={slot}
                height={plotH}
                onMouseEnter={() => setHover(i)}
                onClick={onSelect ? () => onSelect(selected === i ? null : i) : undefined}
              />
            ),
          )}
      </svg>
      {tip && (
        <div class="tooltip num" style={{ left: `${tipLeft}px`, top: "8px" }}>
          <div class="date">{tip.title}</div>
          {tip.rows.map(([k, v, cls]) => (
            <div class="row" key={k}>
              <span class="k">
                {cls && <i class={`swatch ${cls}`} style={{ margin: 0 }} />}
                {k}
              </span>
              <span>{v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Legend({ items, note }: { items: { label: string; cls: string }[]; note?: string }) {
  return (
    <div class="legend">
      {items.map((it) => (
        <span key={it.label}>
          <i class={`swatch ${it.cls}`} />
          {it.label}
        </span>
      ))}
      {note && <span class="faint">{note}</span>}
    </div>
  );
}

/** Ranked horizontal bars (replaces pie/doughnut charts). */
export function HBars({
  rows,
  format = (v: number) => usd(v),
  limit = 10,
  models = false,
  primaryCls = "fill-primary",
  onPick,
}: {
  rows: { label: string; value: number; secondary?: number }[];
  format?: (v: number) => string;
  limit?: number;
  /** Labels are model names: prefix a vendor dot. */
  models?: boolean;
  primaryCls?: string;
  onPick?: (label: string) => void;
}) {
  const shown = rows.slice(0, limit);
  const max = Math.max(1, ...shown.map((r) => r.value + (r.secondary || 0)));
  if (!shown.length) return <div class="empty">{L("暂无数据", "No data")}</div>;
  return (
    <div class="hbars">
      {shown.map((r) => (
        <div
          class="hbar"
          key={r.label}
          style={onPick ? { cursor: "pointer" } : undefined}
          onClick={onPick ? () => onPick(r.label) : undefined}
        >
          <div class="hbar-label" title={r.label}>
            {models && <ModelDot model={r.label} />}
            <span>{r.label}</span>
          </div>
          <div class="hbar-track">
            <span class={primaryCls} style={{ width: `${(r.value / max) * 100}%` }} />
            {r.secondary ? <span class="fill-secondary" style={{ width: `${(r.secondary / max) * 100}%` }} /> : null}
          </div>
          <div class="hbar-value num">{format(r.value + (r.secondary || 0))}</div>
        </div>
      ))}
    </div>
  );
}

/** One horizontal bar split into proportional segments. */
export function SplitBar({ parts }: { parts: { label: string; value: number; cls: string; text: string }[] }) {
  const total = parts.reduce((a, p) => a + Math.max(0, p.value), 0) || 1;
  return (
    <div class="splitbar-wrap">
      <div class="splitbar">
        {parts.map((p) => (p.value > 0 ? <span key={p.label} class={p.cls} style={{ width: `${(p.value / total) * 100}%` }} /> : null))}
      </div>
      <div class="legend">
        {parts.map((p) => (
          <span key={p.label}>
            <i class={`swatch ${p.cls}`} />
            {p.label} <span class="num">{p.text}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export interface Metric {
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | "flat";
  /** Optional status chip shown next to the label. */
  chip?: { tone: Tone; text: string };
  /** Optional mini trend (e.g. last 14 days). */
  spark?: number[];
  sparkKind?: "included" | "ondemand" | "auto" | "neutral";
}

export function MetricGrid({ items }: { items: Metric[] }) {
  return (
    <div class="metrics">
      {items.map((m) => (
        <div class="metric panel" key={m.label}>
          <div class="quota-head">
            <span class="metric-label">{m.label}</span>
            {m.chip && <Chip tone={m.chip.tone}>{m.chip.text}</Chip>}
          </div>
          <div class="metric-row">
            <div class="metric-value num">{m.value}</div>
            {m.spark && m.spark.some((v) => v > 0) && <Sparkline values={m.spark} kind={m.sparkKind || "included"} width={72} height={24} />}
          </div>
          {m.sub && <div class={`metric-sub num${m.trend && m.trend !== "flat" ? ` ${m.trend}` : ""}`}>{m.sub}</div>}
        </div>
      ))}
    </div>
  );
}

export function Notes({ items }: { items: preact.ComponentChildren[] }) {
  const shown = items.filter(Boolean);
  if (!shown.length) return null;
  return (
    <section class="section">
      <div class="section-head">
        <h2>{L("要点", "Highlights")}</h2>
      </div>
      <ul class="notes panel">
        {shown.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

const HEAT_ROWS = [1, 2, 3, 4, 5, 6, 0]; // Monday first

/** Weekday x hour grid; cell intensity scales with the chosen metric. */
export function Heatmap({ counts, cents, metric }: { counts: number[][]; cents: number[][]; metric: "counts" | "cents" }) {
  const grid = metric === "counts" ? counts : cents;
  const max = Math.max(1, ...grid.flat());
  const cell = (wd: number, h: number) => {
    const v = grid[wd]?.[h] || 0;
    const pct = v > 0 ? Math.round(18 + (v / max) * 82) : 0;
    const title = `${weekdayName(wd)} ${h}:00–${h + 1}:00 · ${times(counts[wd]?.[h] || 0)} · ${usd(cents[wd]?.[h] || 0)}`;
    return (
      <div
        key={h}
        class="heat-cell"
        title={title}
        style={pct ? { background: `color-mix(in srgb, var(--c-included) ${pct}%, var(--surface-2))` } : undefined}
      />
    );
  };
  return (
    <div class="heatmap">
      <div class="heatmap-grid">
        <span />
        {Array.from({ length: 24 }, (_, h) => (
          <span class="hhour num" key={h}>
            {h % 3 === 0 ? h : ""}
          </span>
        ))}
        {HEAT_ROWS.map((wd) => (
          <Fragment key={wd}>
            <span class="hlabel">{weekdayName(wd)}</span>
            {Array.from({ length: 24 }, (_, h) => cell(wd, h))}
          </Fragment>
        ))}
      </div>
      <div class="heat-scale">
        {L("少", "Less")}
        {[0, 30, 55, 80, 100].map((p) => (
          <span key={p} class="heat-cell" style={p ? { background: `color-mix(in srgb, var(--c-included) ${p}%, var(--surface-2))` } : undefined} />
        ))}
        {L("多", "More")}
      </div>
    </div>
  );
}

export function Card({ title, extra, children }: { title: string; extra?: preact.ComponentChildren; children: preact.ComponentChildren }) {
  return (
    <section class="section">
      <div class="section-head">
        <h2>{title}</h2>
        {extra}
      </div>
      <div class="panel">{children}</div>
    </section>
  );
}
