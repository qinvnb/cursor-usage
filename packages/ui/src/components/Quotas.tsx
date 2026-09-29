import { hasPoolSplit, includedPools, L, POOL_HINT, poolLabel, totalTokens, type BucketModelRow, type Pool, type PoolUsage, type Report } from "@cursor-usage/core";
import { quota, type Cycle, type DaySeries, type Quota } from "../derive";
import { count, times, tokens, usd } from "../format";
import { Chip, Ring, type Tone } from "./kit";

const fastBy = (ratio: number, fraction: number) => Math.round((ratio - fraction) * 100);

function status(q: Quota, cycle: Cycle | null): { tone: Tone; text: string } {
  if (q.limitCents <= 0) return { tone: "neutral", text: L("未设上限", "No limit") };
  if (q.remainingCents <= 0) return { tone: "danger", text: L("已用完", "Used up") };
  if (q.projectedCents !== null && q.projectedCents > q.limitCents) return { tone: "warn", text: L("可能超额", "May exceed") };
  if (cycle && q.ratio - cycle.fraction > 0.1) {
    const by = fastBy(q.ratio, cycle.fraction);
    return { tone: "warn", text: L(`偏快 ${by}%`, `${by}% ahead`) };
  }
  return { tone: "ok", text: L("正常", "On track") };
}

type Line = { text: string; cls?: string };
const noPace = () => L("周期刚开始，暂无节奏预测", "Too early in the cycle to project");

/**
 * Shared card layout. Always renders three single-line rows so cards placed
 * side by side keep their rows aligned at any width.
 */
function QuotaCard({
  ring,
  kind,
  label,
  hint,
  chip,
  value,
  unit,
  lines,
  single,
}: {
  ring: preact.ComponentChildren;
  kind: string;
  label: string;
  hint?: string;
  chip: { tone: Tone; text: string };
  value: string;
  unit?: string;
  lines: [Line, Line, Line?];
  single: boolean;
}) {
  return (
    <div class={`panel quota-card${single ? " single" : ""}`}>
      {ring}
      <div class="quota-main">
        <div class="quota-head">
          <span class="label" title={hint ? `${label} (${hint})` : label}>
            <i class={`legend-dot fill-${kind}`} />
            <span class="name">{label}</span>
            {hint && <span class="hint">{hint}</span>}
          </span>
          <Chip tone={chip.tone}>{chip.text}</Chip>
        </div>
        <div class="quota-value num">
          <span class="used">{value}</span>
          {unit && <span class="limit">{unit}</span>}
        </div>
        <div class="quota-lines num">
          {lines.map((l, i) =>
            l ? (
              <span key={i} class={l.cls} title={l.text}>
                {l.text}
              </span>
            ) : null,
          )}
        </div>
      </div>
    </div>
  );
}

export function QuotaBlock({
  label,
  q,
  kind,
  cycle,
  detail,
  single = false,
}: {
  label: string;
  q: Quota;
  kind: "included" | "ondemand";
  cycle: Cycle | null;
  /** Third row, e.g. API value and request count. */
  detail?: string;
  single?: boolean;
}) {
  const hasLimit = q.limitCents > 0;
  const over = hasLimit && q.projectedCents !== null && q.projectedCents > q.limitCents;
  const ringTone: Tone = q.level === "danger" ? "danger" : q.level === "warn" ? "warn" : "info";
  const left = usd(Math.max(0, q.remainingCents));
  const first: Line = hasLimit ? { text: L(`剩余 ${left}`, `${left} left`) } : { text: L("本周期未设置上限", "No limit this cycle") };
  const second: Line =
    hasLimit && q.remainingCents <= 0
      ? {
          text: kind === "included" ? L("之后的用量计入个人按需", "Further usage is billed on-demand") : L("已达到按需上限", "On-demand limit reached"),
          cls: "over",
        }
      : q.projectedCents !== null
        ? over
          ? { text: L(`按当前节奏，周期末将达到 ${usd(q.projectedCents)}`, `At this pace: ${usd(q.projectedCents)} by cycle end`), cls: "over" }
          : { text: L(`预计周期末 ${usd(q.projectedCents)}`, `Projected ${usd(q.projectedCents)} by cycle end`) }
        : { text: noPace() };
  return (
    <QuotaCard
      ring={<Ring value={hasLimit ? q.ratio : 0} marker={hasLimit && cycle ? cycle.fraction : null} tone={ringTone} kind={kind} label={hasLimit ? `${Math.round(q.ratio * 100)}%` : "—"} />}
      kind={kind}
      label={label}
      chip={status(q, cycle)}
      value={usd(q.usedCents)}
      unit={hasLimit ? `/ ${usd(q.limitCents)}` : undefined}
      lines={[first, second, detail ? { text: detail, cls: "faint" } : undefined]}
      single={single}
    />
  );
}

export const POOL_FILL: Record<Pool, "auto" | "included"> = { cursor: "auto", api: "included" };

export interface PoolPace {
  ratio: number;
  /** Straight-line percent at cycle end; null until half a day of data. */
  projectedPercent: number | null;
  /** Days until 100% at the cycle-average pace; null without a pace yet. */
  daysToFull: number | null;
  status: { tone: Tone; text: string };
}

export function poolPace(p: PoolUsage, cycle: Cycle | null): PoolPace {
  const pct = p.percentUsed ?? 0;
  const ratio = pct / 100;
  const paced = !!cycle && cycle.elapsedDays >= 0.5 && pct > 0;
  const projectedPercent = paced ? (pct / cycle!.elapsedDays) * cycle!.totalDays : null;
  const daysToFull = paced ? Math.max(0, (100 - pct) / (pct / cycle!.elapsedDays)) : null;
  let st: PoolPace["status"] = { tone: "ok", text: L("正常", "On track") };
  if (pct >= 100) st = { tone: "danger", text: L("已用完", "Used up") };
  else if (projectedPercent !== null && projectedPercent > 100) st = { tone: "warn", text: L("可能用完", "May run out") };
  else if (cycle && ratio - cycle.fraction > 0.1) {
    const by = fastBy(ratio, cycle.fraction);
    st = { tone: "warn", text: L(`偏快 ${by}%`, `${by}% ahead`) };
  }
  return { ratio, projectedPercent, daysToFull, status: st };
}

const pctText = (v: number) => `${v >= 99.95 || v === 0 ? v.toFixed(0) : v.toFixed(1)}%`;

const apiValue = (cents: number, events: number) => L(`API 价 ${usd(cents)} · ${times(events)}`, `${usd(cents)} API value · ${times(events)}`);

/** After a pool is used up, where its requests go. */
export function poolExhaustedText(pool: Pool): string {
  return pool === "api"
    ? L("之后指定模型的请求计入个人按需", "Named-model requests now bill on-demand")
    : L("之后的 Auto 请求计入个人按需", "Auto requests now bill on-demand");
}

/** One included pool: Cursor models (Auto / Composer) or other models (API), in percent of the pool. */
export function PoolBlock({ p, cycle, single = false }: { p: PoolUsage; cycle: Cycle | null; single?: boolean }) {
  const pct = p.percentUsed ?? 0;
  const pace = poolPace(p, cycle);
  const tone: Tone = pct >= 95 ? "danger" : pct >= 80 ? "warn" : "info";
  const kind = POOL_FILL[p.pool];
  const over = pace.projectedPercent !== null && pace.projectedPercent > 100;
  const second: Line =
    pct >= 100
      ? { text: poolExhaustedText(p.pool), cls: "over" }
      : pace.projectedPercent === null
        ? { text: noPace() }
        : over && pace.daysToFull !== null
          ? { text: L(`按当前节奏约 ${pace.daysToFull.toFixed(1)} 天后用完`, `Runs out in ~${pace.daysToFull.toFixed(1)} days at this pace`), cls: "over" }
          : { text: L(`预计周期末约 ${pace.projectedPercent.toFixed(0)}%`, `~${pace.projectedPercent.toFixed(0)}% by cycle end`) };
  const left = pctText(Math.max(0, 100 - pct));
  return (
    <QuotaCard
      ring={<Ring value={pace.ratio} marker={cycle ? cycle.fraction : null} tone={tone} kind={kind} label={`${Math.round(pct)}%`} />}
      kind={kind}
      label={poolLabel(p.pool)}
      hint={POOL_HINT[p.pool]}
      chip={pace.status}
      value={pctText(pct)}
      unit={L("已用", "used")}
      lines={[{ text: L(`剩余约 ${left}`, `~${left} left`) }, second, { text: apiValue(p.costCents, p.eventCount), cls: "faint" }]}
      single={single}
    />
  );
}

export function bucketDetail(rows: BucketModelRow[] | undefined): string {
  const list = rows || [];
  return apiValue(
    list.reduce((a, m) => a + Number(m.costCents || 0), 0),
    list.reduce((a, m) => a + Number(m.eventCount || 0), 0),
  );
}

export function Quotas({ report, cycle, series }: { report: Report; cycle: Cycle | null; series: DaySeries }) {
  const s = report.summary;
  const split = hasPoolSplit(report);
  const pools = includedPools(report);
  const included = quota(s.includedUsedCents, s.includedLimitCents, s.includedRemainingCents, cycle);
  const onDemand = quota(s.individualUsedCents, s.individualLimitCents, s.individualRemainingCents, cycle);
  const avg = cycle && cycle.elapsedDays >= 0.5 ? series.totalCents / Math.max(1, cycle.elapsedDays) : null;
  const sumTokens = (key: "inputTokens" | "outputTokens" | "cacheReadTokens" | "cacheWriteTokens") =>
    (report.models || []).reduce((a, m) => a + Number(m[key] || 0), 0);
  const tokenCount = (report.models || []).reduce((a, m) => a + totalTokens(m), 0);
  return (
    <>
      <div class={`quota-cards${split ? " three" : ""}`}>
        {split ? (
          <>
            <PoolBlock p={pools.cursor} cycle={cycle} />
            <PoolBlock p={pools.api} cycle={cycle} />
          </>
        ) : (
          <QuotaBlock label={L("套餐内额度", "Included usage")} q={included} kind="included" cycle={cycle} detail={bucketDetail(report.includedModels)} />
        )}
        <QuotaBlock label={L("个人按需", "On-demand")} q={onDemand} kind="ondemand" cycle={cycle} detail={bucketDetail(report.onDemandModels)} />
      </div>
      <div class="totals num">
        <span class="stat-pill" title={L("按各模型 API 价格累计的用量价值，套餐内部分不等于实际扣费", "Usage valued at each model's API price; the included part is not what you are billed")}>
          {L("用量价值（API 价）", "Usage value (API price)")}
          <b>{usd(series.totalCents)}</b>
        </span>
        {avg !== null && (
          <span class="stat-pill">
            {L("日均", "Per day")}
            <b>{usd(avg)}</b>
          </span>
        )}
        <span class="stat-pill">
          {L("请求", "Requests")}
          <b>{count(series.events)}</b>
        </span>
        {tokenCount > 0 && (
          <span
            class="stat-pill"
            title={L(
              `输入 ${tokens(sumTokens("inputTokens"))} · 输出 ${tokens(sumTokens("outputTokens"))} · 缓存读取 ${tokens(sumTokens("cacheReadTokens"))} · 缓存写入 ${tokens(sumTokens("cacheWriteTokens"))}`,
              `Input ${tokens(sumTokens("inputTokens"))} · output ${tokens(sumTokens("outputTokens"))} · cache read ${tokens(sumTokens("cacheReadTokens"))} · cache write ${tokens(sumTokens("cacheWriteTokens"))}`,
            )}
          >
            Token<b>{tokens(tokenCount)}</b>
          </span>
        )}
        <span class="stat-pill">
          {L("有用量的天数", "Active days")}
          <b>{series.activeDays}</b>
        </span>
        {split && s.includedLimitCents > 0 && (
          <span
            class="stat-pill"
            title={L("套餐自带的金额额度；超出部分由赠送额度承担，两个额度池以百分比为准", "The plan's dollar allowance; beyond it bonus credit applies. The two pools above are the real measure.")}
          >
            {L("套餐金额", "Plan allowance")}
            <b>
              {usd(s.includedUsedCents)} / {usd(s.includedLimitCents)}
            </b>
          </span>
        )}
        {s.bonusSpendCents > 0 && (
          <span class="stat-pill">
            {L("赠送额度", "Bonus credit")}
            <b>{usd(s.bonusSpendCents)}</b>
          </span>
        )}
      </div>
    </>
  );
}
