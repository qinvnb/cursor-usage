import {
  autoBucketModels,
  cycleSnapshot,
  getLang,
  hasPoolSplit,
  includedPools,
  L,
  localDateKey,
  modelPool,
  poolLabel,
  totalTokens,
  type BucketModelRow,
  type CycleSnapshot,
  type Pool,
  type PoolUsage,
  type Report,
} from "@cursor-usage/core";
import { useMemo, useState } from "preact/hooks";
import {
  burnRate,
  concentration,
  costModels,
  filterRange,
  longestStreak,
  movingAverage,
  peak,
  stdev,
  sumBy,
  weekdayAverages,
  type DayPoint,
  type RangeMode,
  type Series,
} from "../analysis";
import { quota, type Cycle, type DaySeries } from "../derive";
import { count, dayLabel, dayTitle, daysUnit, percent, tokens, usd, weekday, weekdayName } from "../format";
import { Card, ColumnChart, HBars, Heatmap, Legend, MetricGrid, Notes, SplitBar, type TipRow } from "./charts";
import { DailyChart, TOKEN_PARTS } from "./DailyChart";
import { DownloadIcon } from "./icons";
import type { Tone } from "./kit";
import { PoolBlock, QuotaBlock, Quotas, bucketDetail, poolExhaustedText, poolPace } from "./Quotas";
import { HistoryTable, ModelsTable, Table, cacheHitRate, toCsv, type Column } from "./Tables";

export interface PageContext {
  report: Report;
  cycle: Cycle | null;
  days: DaySeries;
  series: Series;
  history: CycleSnapshot[];
  onExport: (name: string, csv: string) => void;
  onPickDay: (date: string) => void;
  onPickModel: (model: string) => void;
}

const wowChip = (wow: number | null): { tone: Tone; text: string } | undefined =>
  wow === null ? undefined : { tone: wow > 3 ? "warn" : wow < -3 ? "ok" : "neutral", text: `${wow > 0 ? "↑" : wow < 0 ? "↓" : "→"} ${Math.abs(wow).toFixed(0)}%` };
/** Days until empty; anything beyond the rest of the cycle just "lasts the cycle". */
const daysText = (days: number | null, daysLeft: number | null) => {
  if (days === null || !Number.isFinite(days)) return L("撑过本周期", "Lasts the cycle");
  if (daysLeft !== null && days > daysLeft) return L("撑过本周期", "Lasts the cycle");
  return daysUnit(Math.max(0, days).toFixed(1));
};
const shortLabels = (points: DayPoint[]) => points.map((p) => dayLabel(p.date));
const pointTip =
  (points: DayPoint[], extra?: (i: number) => TipRow[]) =>
  (i: number): { title: string; rows: TipRow[] } => {
    const p = points[i];
    return {
      title: dayTitle(p.date),
      rows: [
        [L("套餐内", "Included"), usd(p.inc), "fill-included"],
        [L("按需", "On-demand"), usd(p.ond), "fill-ondemand"],
        [L("请求", "Requests"), count(p.events)],
        ...(p.tokens > 0 ? [["Token", tokens(p.tokens)] as TipRow] : []),
        ...(extra ? extra(i) : []),
      ],
    };
  };
const splitLegend = () => [
  { label: L("套餐内（API 价）", "Included (API price)"), cls: "fill-included" },
  { label: L("个人按需", "On-demand"), cls: "fill-ondemand" },
];
const exportBtn = (onClick: () => void) => (
  <button class="link-btn" onClick={onClick}>
    <DownloadIcon />
    {L("导出 CSV", "Export CSV")}
  </button>
);

/** Compare this cycle's running total with the same day of the previous cycle. */
export function samePointComparison(history: CycleSnapshot[], points: DayPoint[]): { prev: number; cur: number; pct: number | null } | null {
  const prev = [...history].reverse().find((c) => c.dailyTotals && c.dailyTotals.length);
  if (!prev || !points.length) return null;
  const n = points.length;
  const prevCum = sumBy(prev.dailyTotals!.slice(0, n), (v) => v);
  const cur = sumBy(points, (p) => p.total);
  return { prev: prevCum, cur, pct: prevCum > 0 ? ((cur - prevCum) / prevCum) * 100 : null };
}

// ---- Overview -----------------------------------------------------------------

export function OverviewPage({ report, cycle, days, series, history, onExport, onPickDay, onPickModel }: PageContext) {
  const s = report.summary;
  const avgActive = series.active.length ? sumBy(series.points, (p) => p.total) / series.active.length : 0;
  const top = peak(series.points);
  const billed = s.individualUsedCents + s.includedUsedCents;
  const projected = series.daysElapsed && series.cycleDays ? (billed / series.daysElapsed) * series.cycleDays : null;
  const limits = s.includedLimitCents + s.individualLimitCents;
  const pace = limits > 0 ? billed / limits : null;
  const timeFrac = series.daysElapsed && series.cycleDays ? series.daysElapsed / series.cycleDays : null;
  const ahead = pace !== null && timeFrac !== null ? pace - timeFrac : null;
  const same = samePointComparison(history, series.points);
  const spark14 = series.last14.map((p) => p.total);
  const requests = count(sumBy(series.points, (p) => p.events));
  const apiTotal = usd(sumBy(series.points, (p) => p.total));

  return (
    <>
      <Quotas report={report} cycle={cycle} series={days} />
      <MetricGrid
        items={[
          {
            label: L("活跃日均", "Per active day"),
            value: usd(avgActive),
            sub: L(`${series.active.length} 个有用量的日子`, `${series.active.length} active days`),
            spark: spark14,
          },
          { label: L("峰值日", "Peak day"), value: top ? usd(top.total) : "—", sub: top ? dayTitle(top.date) : L("暂无", "None yet") },
          {
            label: L("近 7 日合计", "Last 7 days"),
            value: usd(series.last7Sum),
            sub: series.wow === null ? L("周期内不足 14 天，暂无对比", "Needs 14 days in the cycle to compare") : L("与前 7 天相比", "vs. the 7 days before"),
            chip: wowChip(series.wow),
            spark: series.last7.map((p) => p.total),
          },
          {
            label: L("与上周期同期", "vs. last cycle"),
            value: same && same.pct !== null ? `${same.pct > 0 ? "+" : ""}${same.pct.toFixed(0)}%` : "—",
            sub: same ? L(`上周期同期 ${usd(same.prev)}`, `${usd(same.prev)} at this point last cycle`) : L("上个周期结束后开始对比", "Starts after the first full cycle"),
            chip:
              same && same.pct !== null
                ? { tone: same.pct > 10 ? "warn" : same.pct < -10 ? "ok" : "neutral", text: same.pct > 0 ? L("更多", "More") : L("更少", "Less") }
                : undefined,
          },
          {
            label: L("周期末扣费预估", "Projected billing"),
            value: projected !== null ? usd(projected) : "—",
            sub: series.daysLeft !== null ? L(`剩余约 ${series.daysLeft} 天`, `~${series.daysLeft} days left`) : undefined,
          },
        ]}
      />
      <DailyChart
        series={days}
        selected={null}
        onSelect={(d) => d && onPickDay(d)}
        includedLimitCents={s.includedLimitCents}
        dailyTokens={report.dailyTokens}
      />
      <div class="grid-2">
        <Card title={L("本周期构成", "This cycle")}>
          <SplitBar
            parts={[
              { label: L("套餐内", "Included"), value: s.includedUsedCents, cls: "fill-included", text: usd(s.includedUsedCents) },
              { label: L("个人按需", "On-demand"), value: s.individualUsedCents, cls: "fill-ondemand", text: usd(s.individualUsedCents) },
              { label: L("赠送", "Bonus"), value: s.bonusSpendCents, cls: "fill-neutral", text: usd(s.bonusSpendCents) },
            ]}
          />
        </Card>
        <Notes
          items={[
            L(`本周期共 ${requests} 次计费请求，按 API 价合计约 ${apiTotal}。`, `${requests} billable requests this cycle, about ${apiTotal} at API prices.`),
            ahead !== null &&
              (ahead > 0.05
                ? L(
                    `扣费进度（相对套餐内与按需两项额度）比时间进度快约 ${(ahead * 100).toFixed(0)} 个百分点。`,
                    `Billing (against included + on-demand limits) is about ${(ahead * 100).toFixed(0)} points ahead of the calendar.`,
                  )
                : ahead < -0.05
                  ? L(
                      `扣费进度比时间进度慢约 ${(Math.abs(ahead) * 100).toFixed(0)} 个百分点，节奏偏稳。`,
                      `Billing is about ${(Math.abs(ahead) * 100).toFixed(0)} points behind the calendar, a comfortable pace.`,
                    )
                  : L("扣费进度与时间进度基本同步。", "Billing is roughly in step with the calendar.")),
            series.wow !== null &&
              (series.wow > 3
                ? L(`近 7 日用量上升 ${series.wow.toFixed(0)}%，留意按需额度。`, `Usage rose ${series.wow.toFixed(0)}% over the last 7 days; watch the on-demand limit.`)
                : series.wow < -3
                  ? L(`近 7 日用量下降 ${Math.abs(series.wow).toFixed(0)}%。`, `Usage fell ${Math.abs(series.wow).toFixed(0)}% over the last 7 days.`)
                  : L("近 7 日用量与此前基本持平。", "Usage over the last 7 days is flat.")),
            same &&
              same.pct !== null &&
              L(
                `与上个周期的同一天相比，用量${same.pct >= 0 ? "多" : "少"} ${Math.abs(same.pct).toFixed(0)}%。`,
                `${Math.abs(same.pct).toFixed(0)}% ${same.pct >= 0 ? "more" : "less"} than at the same point last cycle.`,
              ),
          ]}
        />
      </div>
      <ModelsTable report={report} onExport={onExport} onPick={onPickModel} />
    </>
  );
}

// ---- On-demand / Included -----------------------------------------------------

function BucketModels({
  rows,
  title,
  onExport,
  exportName,
  onPick,
  cls,
}: {
  rows: BucketModelRow[];
  title: string;
  onExport: PageContext["onExport"];
  exportName: string;
  onPick: (model: string) => void;
  cls: string;
}) {
  const shown = rows.filter((m) => m.costCents > 0);
  const columns: Column<BucketModelRow>[] = [
    { key: "model", label: L("模型", "Model"), value: (m) => m.model },
    { key: "events", label: L("请求", "Requests"), right: true, value: (m) => m.eventCount, render: (m) => count(m.eventCount) },
    { key: "cost", label: L("成本", "Cost"), right: true, value: (m) => m.costCents, render: (m) => usd(m.costCents), csv: (m) => (m.costCents / 100).toFixed(2) },
    { key: "share", label: L("占比", "Share"), right: true, value: (m) => m.sharePercent, render: (m) => `${m.sharePercent.toFixed(1)}%` },
  ];
  return (
    <Card title={title} extra={shown.length ? exportBtn(() => onExport(exportName, toCsv(shown, columns))) : undefined}>
      {shown.length ? (
        <HBars rows={shown.map((m) => ({ label: m.model, value: m.costCents }))} models primaryCls={cls} onPick={onPick} />
      ) : (
        <div class="empty">{L("本周期暂无这部分的模型用量", "No model usage here this cycle")}</div>
      )}
    </Card>
  );
}

export function OnDemandPage({ report, cycle, series, onExport, onPickModel }: PageContext) {
  const s = report.summary;
  const used = s.individualUsedCents;
  const limit = s.individualLimitCents;
  const left = s.individualRemainingCents;
  const avg = series.active.length ? sumBy(series.points, (p) => p.ond) / series.active.length : 0;
  const burn = burnRate(series.last7, "ond", left);
  const models = (report.onDemandModels || []).filter((m) => m.costCents > 0);
  const conc = concentration(models.map((m) => m.costCents));
  const top = models[0];
  let running = 0;
  const cumulative = series.points.map((p) => (running += p.ond));
  const soon = left > 0 && burn.daysToEmpty !== null && series.daysLeft !== null && burn.daysToEmpty < Math.min(7, series.daysLeft);

  return (
    <>
      <QuotaBlock single label={L("个人按需", "On-demand")} q={quota(used, limit, left, cycle)} kind="ondemand" cycle={cycle} detail={bucketDetail(report.onDemandModels)} />
      <MetricGrid
        items={[
          { label: L("已用占比", "Used"), value: limit > 0 ? percent(used / limit) : "—", sub: `${usd(used)} / ${usd(limit)}` },
          {
            label: L("活跃日均", "Per active day"),
            value: usd(avg),
            sub: L(`近 7 日日均 ${usd(burn.perDay)}`, `${usd(burn.perDay)}/day over the last 7 days`),
            spark: series.last14.map((p) => p.ond),
            sparkKind: "ondemand",
          },
          {
            label: L("按近 7 日节奏用完", "Runs out at 7-day pace"),
            value: left > 0 ? daysText(burn.daysToEmpty, series.daysLeft) : L("已用完", "Used up"),
            sub: left > 0 ? L(`剩余 ${usd(left)}`, `${usd(left)} left`) : undefined,
            chip: soon ? { tone: "warn", text: L("偏快", "Fast") } : undefined,
          },
          {
            label: L("前三模型占比", "Top 3 models"),
            value: models.length ? percent(conc.top3) : "—",
            sub: models.length ? L(`HHI ${(conc.hhi * 100).toFixed(0)}（越高越集中）`, `HHI ${(conc.hhi * 100).toFixed(0)} (higher = more concentrated)`) : undefined,
          },
        ]}
      />
      <div class="grid-2">
        <Card title={L("按需累计", "Cumulative on-demand")}>
          <ColumnChart
            labels={shortLabels(series.points)}
            lines={[{ key: "cum", label: L("累计", "Cumulative"), cls: "line-accent", values: cumulative, area: true }]}
            refLine={limit > 0 ? { value: limit, label: L(`上限 ${usd(limit)}`, `Limit ${usd(limit)}`) } : undefined}
            tooltip={pointTip(series.points, (i) => [[L("累计", "Cumulative"), usd(cumulative[i])]])}
          />
        </Card>
        <Card title={L("近 14 日按需", "On-demand, last 14 days")}>
          <ColumnChart
            labels={shortLabels(series.last14)}
            bars={[{ key: "ond", label: L("按需", "On-demand"), cls: "fill-ondemand", values: series.last14.map((p) => p.ond) }]}
            tooltip={pointTip(series.last14)}
          />
        </Card>
      </div>
      <BucketModels
        rows={report.onDemandModels || []}
        title={L("按需模型分布", "On-demand by model")}
        onExport={onExport}
        exportName={L("按需模型", "on-demand-models")}
        onPick={onPickModel}
        cls="fill-ondemand"
      />
      <Notes
        items={[
          top &&
            (getLang() === "zh" ? (
              <>
                头部模型 <strong>{top.model}</strong> 约占 {(conc.shares[0] * 100).toFixed(1)}%（{usd(top.costCents)}）。
              </>
            ) : (
              <>
                <strong>{top.model}</strong> accounts for about {(conc.shares[0] * 100).toFixed(1)}% ({usd(top.costCents)}).
              </>
            )),
          models.length > 0 &&
            (conc.hhi > 0.35
              ? L("模型结构较集中，成本对少数模型更敏感。", "Spend is concentrated; costs hinge on a few models.")
              : L("模型结构较分散。", "Spend is spread across models.")),
          burn.daysToEmpty !== null &&
            series.daysLeft !== null &&
            left > 0 &&
            (burn.daysToEmpty < series.daysLeft
              ? L(
                  `按当前节奏，按需额度可能比周期结束早约 ${(series.daysLeft - burn.daysToEmpty).toFixed(0)} 天用完。`,
                  `At this pace the on-demand limit may run out about ${(series.daysLeft - burn.daysToEmpty).toFixed(0)} days before the cycle ends.`,
                )
              : L("按当前节奏，按需额度大概率能撑过本周期。", "At this pace the on-demand limit should last the cycle.")),
          !models.length && L("本周期还没有按需用量。", "No on-demand usage this cycle yet."),
        ]}
      />
    </>
  );
}

/** Per-day included cost split by pool, aligned with `points`. */
export function poolDaily(report: Report, points: DayPoint[]): Record<Pool, number[]> {
  const bucket = autoBucketModels(report);
  const out: Record<Pool, number[]> = { cursor: [], api: [] };
  for (const p of points) {
    let cursor = 0;
    let api = 0;
    for (const m of report.dailyModels?.[p.date] || []) {
      const cents = Number(m.includedCostCents || 0);
      if (modelPool(m.model, bucket) === "cursor") cursor += cents;
      else api += cents;
    }
    out.cursor.push(cursor);
    out.api.push(api);
  }
  return out;
}

export function IncludedPage(ctx: PageContext) {
  const { report, cycle, series, onExport, onPickModel } = ctx;
  if (!hasPoolSplit(report)) return <LegacyIncludedPage {...ctx} />;
  const s = report.summary;
  const pools = includedPools(report);
  const bucket = autoBucketModels(report);
  const rows = (report.includedModels || []).filter((m) => m.costCents > 1);
  const daily14 = poolDaily(report, series.last14);
  const poolMetric = (p: PoolUsage) => {
    const pct = p.percentUsed ?? 0;
    const days = poolPace(p, cycle).daysToFull;
    return {
      label: L(`${poolLabel(p.pool)}按节奏用完`, `${poolLabel(p.pool)} run out`),
      value: pct >= 100 ? L("已用完", "Used up") : daysText(days, series.daysLeft),
      sub: pct >= 100 ? poolExhaustedText(p.pool) : L(`已用 ${pct.toFixed(1)}%，按本周期平均节奏`, `${pct.toFixed(1)}% used, at the cycle-average pace`),
      chip: pct >= 100 ? ({ tone: "danger", text: L("已用完", "Used up") } as const) : undefined,
    };
  };
  const poolValue = (p: PoolUsage) =>
    L(`${count(p.eventCount)} 次请求 · ${p.models.length} 个模型`, `${count(p.eventCount)} requests · ${p.models.length} models`);
  const api = pools.api.percentUsed ?? 0;
  const auto = pools.cursor.percentUsed ?? 0;
  const cursorName = L("Cursor 模型", "Cursor models");
  const otherName = L("其他模型", "Other models");

  return (
    <>
      <div class="quota-cards">
        <PoolBlock p={pools.cursor} cycle={cycle} />
        <PoolBlock p={pools.api} cycle={cycle} />
      </div>
      <MetricGrid
        items={[
          poolMetric(pools.cursor),
          poolMetric(pools.api),
          { label: L("Cursor 模型（API 价）", "Cursor models (API price)"), value: usd(pools.cursor.costCents), sub: poolValue(pools.cursor), spark: daily14.cursor, sparkKind: "auto" },
          { label: L("其他模型（API 价）", "Other models (API price)"), value: usd(pools.api.costCents), sub: poolValue(pools.api), spark: daily14.api },
          {
            label: L("赠送额度", "Bonus credit"),
            value: usd(s.bonusSpendCents),
            sub: L(`套餐金额 ${usd(s.includedUsedCents)} / ${usd(s.includedLimitCents)}`, `Plan allowance ${usd(s.includedUsedCents)} / ${usd(s.includedLimitCents)}`),
          },
        ]}
      />
      <div class="grid-2">
        <Card title={L("近 14 日套餐内（API 价）", "Included, last 14 days (API price)")}>
          <ColumnChart
            labels={shortLabels(series.last14)}
            bars={[
              { key: "cursor", label: cursorName, cls: "fill-auto", values: daily14.cursor },
              { key: "api", label: otherName, cls: "fill-included", values: daily14.api },
            ]}
            tooltip={(i) => {
              const p = series.last14[i];
              return {
                title: dayTitle(p.date),
                rows: [
                  [cursorName, usd(daily14.cursor[i]), "fill-auto"],
                  [otherName, usd(daily14.api[i]), "fill-included"],
                  [L("按需", "On-demand"), usd(p.ond), "fill-ondemand"],
                ],
              };
            }}
          />
          <Legend
            items={[
              { label: L("Cursor 模型（Auto / Composer）", "Cursor models (Auto / Composer)"), cls: "fill-auto" },
              { label: L("其他模型（API）", "Other models (API)"), cls: "fill-included" },
            ]}
          />
        </Card>
        <Card title={L("套餐内用量构成（API 价）", "Included mix (API price)")}>
          <SplitBar
            parts={[
              { label: cursorName, value: pools.cursor.costCents, cls: "fill-auto", text: usd(pools.cursor.costCents) },
              { label: otherName, value: pools.api.costCents, cls: "fill-included", text: usd(pools.api.costCents) },
            ]}
          />
          <div class="notes-inline muted">
            {L(
              `两个额度池相互独立、分别计算百分比：Cursor 模型已用 ${auto.toFixed(1)}%，其他模型已用 ${api.toFixed(1)}%。`,
              `The two pools are independent, each measured in percent: Cursor models ${auto.toFixed(1)}% used, other models ${api.toFixed(1)}% used.`,
            )}
          </div>
        </Card>
      </div>
      <div class="grid-2">
        <BucketModels
          rows={rows.filter((m) => modelPool(m.model, bucket) === "cursor")}
          title={L("Cursor 模型（Auto / Composer）", "Cursor models (Auto / Composer)")}
          onExport={onExport}
          exportName={L("套餐内-Cursor模型", "included-cursor-models")}
          onPick={onPickModel}
          cls="fill-auto"
        />
        <BucketModels
          rows={rows.filter((m) => modelPool(m.model, bucket) === "api")}
          title={L("其他模型（API）", "Other models (API)")}
          onExport={onExport}
          exportName={L("套餐内-其他模型", "included-other-models")}
          onPick={onPickModel}
          cls="fill-included"
        />
      </div>
      <Notes
        items={[
          L(
            "Cursor 模型指 Auto、Composer 等 Cursor 自有或自动路由的模型；其他模型指手动指定的模型，按 API 价计入。",
            "Cursor models are Auto, Composer and other Cursor-owned or auto-routed models; other models are the ones you pick by name, counted at API prices.",
          ),
          api >= 100 &&
            L(
              "其他模型额度已用完，之后手动指定模型的请求计入个人按需；切换到 Auto 仍走 Cursor 模型额度。",
              "The other-models pool is used up: named-model requests now bill on-demand, while Auto still draws on the Cursor-models pool.",
            ),
          auto >= 100 && L("Cursor 模型额度已用完，之后的 Auto 请求计入个人按需。", "The Cursor-models pool is used up; Auto requests now bill on-demand."),
          api < 100 && auto < 100 && api - auto > 30 && L("其他模型额度消耗明显更快，可以多用 Auto 来节省。", "The other-models pool is draining much faster; using Auto more can stretch it."),
          L(
            `套餐内请求按 API 价合计约 ${usd(pools.cursor.costCents + pools.api.costCents)}。`,
            `Included requests total about ${usd(pools.cursor.costCents + pools.api.costCents)} at API prices.`,
          ),
        ]}
      />
    </>
  );
}

function LegacyIncludedPage({ report, cycle, series, onExport, onPickModel }: PageContext) {
  const s = report.summary;
  const used = s.includedUsedCents;
  const limit = s.includedLimitCents;
  const left = s.includedRemainingCents;
  const avg = series.active.length ? sumBy(series.points, (p) => p.inc) / series.active.length : 0;
  const burn = burnRate(series.last7, "inc", left);
  const eventTotal = s.includedEventCostCents || sumBy(series.points, (p) => p.inc);

  return (
    <>
      <QuotaBlock single label={L("套餐内额度", "Included usage")} q={quota(used, limit, left, cycle)} kind="included" cycle={cycle} detail={bucketDetail(report.includedModels)} />
      <MetricGrid
        items={[
          { label: L("已用占比", "Used"), value: limit > 0 ? percent(used / limit) : "—", sub: `${usd(used)} / ${usd(limit)}` },
          {
            label: L("活跃日均（API 价）", "Per active day (API price)"),
            value: usd(avg),
            sub: L(`近 7 日日均 ${usd(burn.perDay)}`, `${usd(burn.perDay)}/day over the last 7 days`),
            spark: series.last14.map((p) => p.inc),
          },
          {
            label: L("按近 7 日节奏用完", "Runs out at 7-day pace"),
            value: left > 0 ? daysText(burn.daysToEmpty, series.daysLeft) : L("已用完", "Used up"),
            sub: L(`剩余 ${usd(left)}`, `${usd(left)} left`),
            chip: left <= 0 && limit > 0 ? { tone: "danger", text: L("已用完", "Used up") } : undefined,
          },
          { label: L("赠送额度", "Bonus credit"), value: usd(s.bonusSpendCents) },
        ]}
      />
      <Card title={L("近 14 日套餐内（API 价）", "Included, last 14 days (API price)")}>
        <ColumnChart
          labels={shortLabels(series.last14)}
          bars={[{ key: "inc", label: L("套餐内", "Included"), cls: "fill-included", values: series.last14.map((p) => p.inc) }]}
          tooltip={pointTip(series.last14)}
        />
      </Card>
      <BucketModels
        rows={(report.includedModels || []).filter((m) => m.costCents > 1)}
        title={L("套餐内模型（API 价）", "Included by model (API price)")}
        onExport={onExport}
        exportName={L("套餐内模型", "included-models")}
        onPick={onPickModel}
        cls="fill-included"
      />
      <Notes
        items={[
          L(
            `套餐内请求按 API 价合计约 ${usd(eventTotal)}，实际扣减套餐额度 ${usd(used)}。`,
            `Included requests total about ${usd(eventTotal)} at API prices; ${usd(used)} was deducted from the plan.`,
          ),
          left > 0 &&
            burn.daysToEmpty !== null &&
            series.daysLeft !== null &&
            (burn.daysToEmpty < series.daysLeft
              ? L(
                  `按当前节奏，套餐额度可能提前约 ${(series.daysLeft - burn.daysToEmpty).toFixed(0)} 天用完。`,
                  `At this pace the included usage may run out about ${(series.daysLeft - burn.daysToEmpty).toFixed(0)} days early.`,
                )
              : L("按当前节奏，套餐额度大概率可撑过本周期。", "At this pace the included usage should last the cycle.")),
          left <= 0 && limit > 0 && L("套餐内额度已用完，之后的用量计入个人按需。", "Included usage is used up; further usage bills on-demand."),
        ]}
      />
    </>
  );
}

// ---- Daily --------------------------------------------------------------------

const ranges = (): [RangeMode, string][] => [
  ["cycle", L("本周期", "This cycle")],
  ["7", L("近 7 天", "7 days")],
  ["14", L("近 14 天", "14 days")],
  ["30", L("近 30 天", "30 days")],
  ["custom", L("自定义", "Custom")],
];

export function DailyPage({ report, series, onExport, onPickDay }: PageContext) {
  const [mode, setMode] = useState<RangeMode>("cycle");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [heatMetric, setHeatMetric] = useState<"counts" | "cents">("counts");
  const points = useMemo(() => filterRange(series.points, mode, from, to), [series.points, mode, from, to]);
  const totals = points.map((p) => p.total);
  const active = totals.filter((v) => v > 0);
  const avg = active.length ? active.reduce((a, b) => a + b, 0) / active.length : 0;
  const sd = stdev(active);
  const top = peak(points);
  const ond = sumBy(points, (p) => p.ond);
  const inc = sumBy(points, (p) => p.inc);
  const all = ond + inc || 1;
  const ma = movingAverage(totals, 7);
  const weekdays = weekdayAverages(points);
  const topModel = (date: string) => report.dailyModels?.[date]?.[0]?.model || report.daily?.find((d) => d.date === date)?.topOnDemandModel || "";

  const columns: Column<DayPoint>[] = [
    {
      key: "date",
      label: L("日期", "Date"),
      value: (p) => p.date,
      render: (p) => (
        <span class="num">
          {p.date} {weekday(p.date)}
        </span>
      ),
    },
    { key: "events", label: L("请求", "Requests"), right: true, value: (p) => p.events, render: (p) => count(p.events) },
    { key: "inc", label: L("套餐内", "Included"), right: true, value: (p) => p.inc, render: (p) => usd(p.inc), csv: (p) => (p.inc / 100).toFixed(2) },
    { key: "ond", label: L("按需", "On-demand"), right: true, value: (p) => p.ond, render: (p) => usd(p.ond), csv: (p) => (p.ond / 100).toFixed(2) },
    { key: "total", label: L("合计", "Total"), right: true, value: (p) => p.total, render: (p) => usd(p.total), csv: (p) => (p.total / 100).toFixed(2) },
    { key: "tokens", label: "Token", right: true, narrowHidden: true, value: (p) => p.tokens, render: (p) => (p.tokens ? tokens(p.tokens) : "—"), csv: (p) => p.tokens },
    {
      key: "top",
      label: L("当日主要模型", "Top model"),
      narrowHidden: true,
      value: (p) => topModel(p.date),
      render: (p) => <span class="muted">{topModel(p.date) || "—"}</span>,
    },
  ];
  const weekdayLabels = [0, 1, 2, 3, 4, 5, 6].map(weekdayName);

  return (
    <>
      <section class="section">
        <div class="filters">
          <div class="segmented" role="group" aria-label={L("日期范围", "Date range")}>
            {ranges().map(([id, label]) => (
              <button key={id} aria-pressed={mode === id} onClick={() => setMode(id)}>
                {label}
              </button>
            ))}
          </div>
          {mode === "custom" && (
            <>
              <input type="date" value={from} onInput={(e) => setFrom((e.target as HTMLInputElement).value)} aria-label={L("开始日期", "Start date")} />
              <span class="faint">{L("至", "to")}</span>
              <input type="date" value={to} onInput={(e) => setTo((e.target as HTMLInputElement).value)} aria-label={L("结束日期", "End date")} />
            </>
          )}
        </div>
      </section>
      <MetricGrid
        items={[
          {
            label: L("活跃日均", "Per active day"),
            value: usd(avg),
            sub: L(`${active.length} / ${points.length} 天有用量`, `${active.length} / ${points.length} days active`),
            spark: totals.slice(-14),
          },
          {
            label: L("波动（标准差）", "Variation (std dev)"),
            value: usd(sd),
            sub: avg ? L(`变异系数 ${((sd / avg) * 100).toFixed(0)}%`, `Coefficient of variation ${((sd / avg) * 100).toFixed(0)}%`) : "—",
            chip: active.length > 1 && sd > avg * 0.8 ? { tone: "warn", text: L("波动大", "Volatile") } : undefined,
          },
          { label: L("区间峰值", "Peak day"), value: top ? usd(top.total) : "—", sub: top ? `${top.date} ${weekday(top.date)}` : "—" },
          {
            label: L("最长连续使用", "Longest streak"),
            value: daysUnit(longestStreak(points)),
            sub: L(`按需占比 ${((ond / all) * 100).toFixed(0)}%`, `${((ond / all) * 100).toFixed(0)}% on-demand`),
          },
        ]}
      />
      <Card title={L("每日用量", "Daily usage")}>
        <ColumnChart
          height={210}
          labels={shortLabels(points)}
          bars={[
            { key: "inc", label: L("套餐内", "Included"), cls: "fill-included", values: points.map((p) => p.inc) },
            { key: "ond", label: L("按需", "On-demand"), cls: "fill-ondemand", values: points.map((p) => p.ond) },
          ]}
          onSelect={(i) => i !== null && onPickDay(points[i].date)}
          tooltip={pointTip(points)}
        />
        <Legend items={splitLegend()} note={L("点击柱子或表格行查看当天明细", "Click a bar or row for that day's details")} />
      </Card>
      <div class="grid-2">
        <Card title={L("7 日移动平均", "7-day moving average")}>
          <ColumnChart
            labels={shortLabels(points)}
            lines={[
              { key: "total", label: L("每日", "Daily"), cls: "line-soft", values: totals },
              { key: "ma", label: L("7 日均线", "7-day average"), cls: "line-main", values: ma },
            ]}
            tooltip={(i) => ({
              title: dayTitle(points[i].date),
              rows: [
                [L("当日", "Day"), usd(totals[i]), "fill-line-soft"],
                [L("7 日均线", "7-day average"), usd(ma[i]), "fill-line"],
              ],
            })}
          />
          <Legend
            items={[
              { label: L("每日", "Daily"), cls: "fill-line-soft" },
              { label: L("7 日均线", "7-day average"), cls: "fill-line" },
            ]}
          />
        </Card>
        <Card title={L("星期分布（日均）", "By weekday (daily average)")}>
          <ColumnChart
            labels={weekdayLabels}
            bars={[{ key: "wd", label: L("日均", "Average"), cls: "fill-included", values: weekdays }]}
            tooltip={(i) => ({ title: weekdayLabels[i], rows: [[L("日均", "Average"), usd(weekdays[i]), "fill-included"]] })}
          />
        </Card>
      </div>
      {report.hourly && (
        <Card
          title={L("使用时段（本周期）", "Activity by hour (this cycle)")}
          extra={
            <div class="segmented" role="group" aria-label={L("热力图指标", "Heatmap metric")}>
              <button aria-pressed={heatMetric === "counts"} onClick={() => setHeatMetric("counts")}>
                {L("请求数", "Requests")}
              </button>
              <button aria-pressed={heatMetric === "cents"} onClick={() => setHeatMetric("cents")}>
                {L("成本", "Cost")}
              </button>
            </div>
          }
        >
          <Heatmap counts={report.hourly.counts} cents={report.hourly.cents} metric={heatMetric} />
        </Card>
      )}
      <Card title={L("按日明细", "By day")} extra={exportBtn(() => onExport(L("按日用量", "daily-usage"), toCsv(points, columns)))}>
        <Table rows={points} columns={columns} initialSort="date" initialDir={-1} rowKey={(p) => p.date} onRowClick={(p) => onPickDay(p.date)} />
      </Card>
      <Notes
        items={[
          top &&
            L(
              `峰值日 ${top.date}，合计 ${usd(top.total)}（按需 ${usd(top.ond)} / 套餐内 ${usd(top.inc)}）。`,
              `Peak day ${top.date}: ${usd(top.total)} (on-demand ${usd(top.ond)} / included ${usd(top.inc)}).`,
            ),
          active.length > 1 &&
            (sd > avg * 0.8
              ? L("日用量波动较大，高峰日对额度影响明显。", "Daily usage swings a lot; peak days weigh heavily on the limits.")
              : L("日用量相对平稳。", "Daily usage is fairly steady.")),
          L(`所选范围内按需 ${usd(ond)}，套餐内 ${usd(inc)}。`, `In this range: on-demand ${usd(ond)}, included ${usd(inc)}.`),
          report.hourly && busiestHour(report.hourly.counts),
        ]}
      />
    </>
  );
}

function busiestHour(counts: number[][]): string | null {
  let best = { wd: -1, h: -1, v: 0 };
  const byHour = new Array(24).fill(0);
  counts.forEach((row, wd) =>
    row.forEach((v, h) => {
      byHour[h] += v;
      if (v > best.v) best = { wd, h, v };
    }),
  );
  if (best.v <= 0) return null;
  const peakHour = byHour.indexOf(Math.max(...byHour));
  return L(
    `最常用的时段是 ${peakHour}:00–${peakHour + 1}:00；单个时段最多的是${weekdayName(best.wd)} ${best.h}:00（${best.v} 次）。`,
    `Busiest hour: ${peakHour}:00–${peakHour + 1}:00; the single busiest slot was ${weekdayName(best.wd)} ${best.h}:00 (${best.v} requests).`,
  );
}

// ---- Models -------------------------------------------------------------------

export function ModelsPage({ report, onExport, onPickModel }: PageContext) {
  const models = costModels(report);
  const conc = concentration(models.map((m) => m.totalCostCents));
  const total = sumBy(models, (m) => m.totalCostCents);
  const ond = sumBy(models, (m) => m.onDemandCostCents);
  const inc = sumBy(models, (m) => m.includedCostCents);
  const all = total || 1;
  const requests = sumBy(report.models || [], (m) => m.eventCount);
  const input = sumBy(report.models || [], (m) => m.inputTokens);
  const output = sumBy(report.models || [], (m) => m.outputTokens);
  const cacheRead = sumBy(report.models || [], (m) => m.cacheReadTokens);
  const cacheWrite = sumBy(report.models || [], (m) => m.cacheWriteTokens);
  const overallHit = cacheHitRate({ inputTokens: input, cacheReadTokens: cacheRead });
  const allTokens = input + output + cacheRead + cacheWrite;
  const tokenShare = (v: number) => (allTokens ? L(`占 ${((v / allTokens) * 100).toFixed(1)}%`, `${((v / allTokens) * 100).toFixed(1)}% of all`) : undefined);
  const priciest = [...models].filter((m) => m.eventCount >= 3).sort((a, b) => b.totalCostCents / b.eventCount - a.totalCostCents / a.eventCount)[0];

  return (
    <>
      <MetricGrid
        items={[
          { label: L("有成本的模型", "Models with cost"), value: String(models.length), sub: L(`合计 ${usd(total)}`, `${usd(total)} total`) },
          {
            label: L("前三合计占比", "Top 3 share"),
            value: models.length ? percent(conc.top3) : "—",
            sub: models[0] ? L(`最高：${models[0].model}`, `Top: ${models[0].model}`) : undefined,
          },
          {
            label: L("覆盖 80% 成本", "80% of cost"),
            value: models.length ? L(`${conc.cover80} 个模型`, `${conc.cover80} models`) : "—",
            sub: models.length ? `HHI ${(conc.hhi * 100).toFixed(0)}` : undefined,
          },
          {
            label: L("按需 / 套餐内", "On-demand / included"),
            value: `${((ond / all) * 100).toFixed(0)}% / ${((inc / all) * 100).toFixed(0)}%`,
            sub: `${usd(ond)} · ${usd(inc)}`,
          },
        ]}
      />
      <section class="section">
        <div class="section-head">
          <h2>{L("成本效率", "Cost efficiency")}</h2>
        </div>
        <MetricGrid
          items={[
            {
              label: L("每次请求平均", "Per request"),
              value: usd(requests ? total / requests : 0),
              sub: L(`${count(requests)} 次请求`, `${count(requests)} requests`),
            },
            {
              label: L("缓存命中率", "Cache hit rate"),
              value: `${(overallHit * 100).toFixed(0)}%`,
              sub: L("缓存读取 / (输入 + 缓存读取)", "cache read / (input + cache read)"),
              chip:
                overallHit >= 0.7
                  ? { tone: "ok", text: L("良好", "Good") }
                  : overallHit > 0 && overallHit < 0.4
                    ? { tone: "warn", text: L("偏低", "Low") }
                    : undefined,
            },
            {
              label: L("输出 / 全部输入", "Output / all input"),
              value: input + cacheRead + cacheWrite ? (output / (input + cacheRead + cacheWrite)).toFixed(3) : "—",
              sub: L("全部输入含缓存读写", "All input includes cache reads and writes"),
            },
            {
              label: L("单次最贵", "Priciest per request"),
              value: priciest ? usd(priciest.totalCostCents / priciest.eventCount) : "—",
              sub: priciest ? priciest.model : L("至少 3 次请求的模型", "Models with at least 3 requests"),
            },
          ]}
        />
      </section>
      <section class="section">
        <div class="section-head">
          <h2>{L("Token 用量", "Token usage")}</h2>
        </div>
        <MetricGrid
          items={[
            {
              label: L("本周期 Token", "Tokens this cycle"),
              value: tokens(allTokens),
              sub: requests ? L(`每次请求约 ${tokens(allTokens / requests)}`, `~${tokens(allTokens / requests)} per request`) : undefined,
            },
            { label: L("输入", "Input"), value: tokens(input), sub: tokenShare(input) },
            { label: L("输出", "Output"), value: tokens(output), sub: tokenShare(output) },
            { label: L("缓存读取", "Cache read"), value: tokens(cacheRead), sub: tokenShare(cacheRead) },
            { label: L("缓存写入", "Cache write"), value: tokens(cacheWrite), sub: tokenShare(cacheWrite) },
          ]}
        />
      </section>
      <div class="grid-2">
        <Card title={L("Token Top 10", "Top 10 by tokens")}>
          <HBars
            rows={[...(report.models || [])]
              .map((m) => ({ label: m.model, value: totalTokens(m) }))
              .filter((r) => r.value > 0)
              .sort((a, b) => b.value - a.value)}
            format={(v) => tokens(v)}
            models
            onPick={onPickModel}
          />
        </Card>
        <Card title={L("Token 构成", "Token mix")}>
          <SplitBar
            parts={TOKEN_PARTS().map((p) => ({
              label: p.label,
              value: { inputTokens: input, outputTokens: output, cacheReadTokens: cacheRead, cacheWriteTokens: cacheWrite }[p.key],
              cls: p.cls,
              text: tokens({ inputTokens: input, outputTokens: output, cacheReadTokens: cacheRead, cacheWriteTokens: cacheWrite }[p.key]),
            }))}
          />
          <div class="notes-inline muted">
            {L(
              "缓存读取按较低单价计费，占比越高通常越省钱；输出 token 单价最高。",
              "Cache reads are billed at a lower rate, so a high share usually saves money; output tokens cost the most.",
            )}
          </div>
        </Card>
      </div>
      <div class="grid-2">
        <Card title={L("合计成本 Top 10", "Top 10 by cost")}>
          <HBars rows={models.map((m) => ({ label: m.model, value: m.totalCostCents }))} models onPick={onPickModel} />
        </Card>
        <Card title={L("套餐内 与 按需（Top 10）", "Included vs. on-demand (top 10)")}>
          <HBars
            rows={models.map((m) => ({ label: m.model, value: m.includedCostCents, secondary: m.onDemandCostCents }))}
            models
            primaryCls="fill-included"
            onPick={onPickModel}
          />
          <Legend items={splitLegend()} />
        </Card>
      </div>
      <ModelsTable report={report} onExport={onExport} onPick={onPickModel} />
      <Notes
        items={[
          models[0] &&
            L(
              `成本最高的模型是 ${models[0].model}，占 ${(conc.shares[0] * 100).toFixed(1)}%。`,
              `${models[0].model} costs the most, at ${(conc.shares[0] * 100).toFixed(1)}%.`,
            ),
          models.length > 0 && L(`约 ${conc.cover80} 个模型贡献了 80% 的成本。`, `About ${conc.cover80} models make up 80% of the cost.`),
          models.length > 0 &&
            (conc.hhi > 0.25
              ? L("成本高度集中在少数模型，切换主力模型会明显改变账单结构。", "Cost is concentrated in a few models; switching your main model changes the bill noticeably.")
              : L("成本分布较分散，没有过度依赖单一模型。", "Cost is spread out, with no heavy reliance on one model.")),
          overallHit > 0 &&
            overallHit < 0.4 &&
            L(
              "缓存命中率偏低：在同一会话中继续提问、少切换上下文，可以更多地复用缓存。",
              "Cache hit rate is low: staying in the same conversation and switching context less reuses more cache.",
            ),
        ]}
      />
    </>
  );
}

// ---- History ------------------------------------------------------------------

const cycleStartLabel = (c: CycleSnapshot) => dayLabel(localDateKey(new Date(Number(c.cycleStart))));

function shortCycle(c: CycleSnapshot): string {
  return L(`${cycleStartLabel(c)} 起`, `From ${cycleStartLabel(c)}`);
}

export function HistoryPage({ report, history, onExport }: PageContext) {
  const current = cycleSnapshot(report);
  const cycles = [...history.filter((c) => c.cycleStart !== current?.cycleStart), ...(current ? [current] : [])];
  if (cycles.length < 2) {
    return (
      <section class="section panel">
        <div class="empty">
          {L(
            "暂无历史周期。当前计费周期结束后会自动保存一份快照，最多保留 24 个周期。",
            "No past cycles yet. A snapshot is saved automatically when the current billing cycle ends; up to 24 cycles are kept.",
          )}
        </div>
      </section>
    );
  }
  const labels = cycles.map((c, i) => `${cycleStartLabel(c)}${i === cycles.length - 1 ? "*" : ""}`);
  const withDaily = cycles.filter((c) => c.dailyTotals && c.dailyTotals.length).slice(-4).reverse();
  const maxDays = Math.max(0, ...withDaily.map((c) => c.dailyTotals!.length));
  const cumulative = (values: number[]) => {
    let run = 0;
    return Array.from({ length: maxDays }, (_, i) => (i < values.length ? (run += values[i]) : null));
  };
  const dayN = (n: number) => L(`第 ${n} 天`, `Day ${n}`);

  return (
    <>
      <Card title={L("各周期扣费", "Billing per cycle")}>
        <ColumnChart
          labels={labels}
          bars={[
            { key: "inc", label: L("套餐内", "Included"), cls: "fill-included", values: cycles.map((c) => c.includedUsedCents) },
            { key: "ond", label: L("按需", "On-demand"), cls: "fill-ondemand", values: cycles.map((c) => c.individualUsedCents) },
          ]}
          tooltip={(i) => ({
            title: `${shortCycle(cycles[i])}${i === cycles.length - 1 ? L("（进行中）", " (current)") : ""}`,
            rows: [
              [L("套餐内", "Included"), usd(cycles[i].includedUsedCents), "fill-included"],
              [L("按需", "On-demand"), usd(cycles[i].individualUsedCents), "fill-ondemand"],
              [L("合计", "Total"), usd(cycles[i].totalCents)],
            ],
          })}
        />
        <Legend
          items={[
            { label: L("套餐内", "Included"), cls: "fill-included" },
            { label: L("个人按需", "On-demand"), cls: "fill-ondemand" },
          ]}
          note={L("* 进行中的周期", "* current cycle")}
        />
      </Card>
      {withDaily.length >= 2 && (
        <Card title={L("逐日累计对比（API 价）", "Cumulative by day (API price)")}>
          <ColumnChart
            labels={Array.from({ length: maxDays }, (_, i) => L(`第${i + 1}天`, `D${i + 1}`))}
            lines={withDaily.map((c, i) => ({ key: c.cycleStart, label: shortCycle(c), cls: `line-series-${i}`, values: cumulative(c.dailyTotals!) }))}
            tooltip={(d) => ({
              title: dayN(d + 1),
              rows: withDaily.map((c, i) => [shortCycle(c), usd(cumulative(c.dailyTotals!)[d] ?? 0), `fill-series-${i}`] as TipRow),
            })}
          />
          <Legend
            items={withDaily.map((c, i) => ({
              label: shortCycle(c) + (i === 0 && c.cycleStart === current?.cycleStart ? L("（本周期）", " (this cycle)") : ""),
              cls: `fill-series-${i}`,
            }))}
          />
        </Card>
      )}
      <HistoryTable history={history} current={current} onExport={onExport} />
    </>
  );
}
