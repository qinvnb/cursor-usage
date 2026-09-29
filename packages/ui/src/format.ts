import { L } from "@cursor-usage/core";

const DAY = 86_400_000;

export function usd(cents: number | null | undefined, { compact = false } = {}): string {
  const dollars = Number(cents || 0) / 100;
  if (compact && Math.abs(dollars) >= 1000) return `$${(dollars / 1000).toFixed(dollars >= 10_000 ? 0 : 1)}k`;
  const digits = compact && Math.abs(dollars) >= 100 ? 0 : 2;
  return `$${dollars.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function tokens(n: number | null | undefined): string {
  const v = Number(n || 0);
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

export function count(n: number | null | undefined): string {
  return Number(n || 0).toLocaleString("en-US");
}

export function percent(ratio: number, digits = 0): string {
  return `${(ratio * 100).toFixed(digits)}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS_ZH = "日一二三四五六";
const WEEKDAYS_EN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function shortDate(ms: number | string | null | undefined): string {
  const d = new Date(Number(ms));
  if (Number.isNaN(d.getTime())) return "—";
  return L(`${d.getMonth() + 1}月${d.getDate()}日`, `${MONTHS[d.getMonth()]} ${d.getDate()}`);
}

export function dayLabel(key: string): string {
  const [, m, d] = key.split("-");
  return `${Number(m)}/${Number(d)}`;
}

/** Weekday index (0 = Sunday) of a YYYY-MM-DD key. */
export function weekdayIndex(key: string): number {
  return new Date(`${key}T00:00:00`).getDay();
}

/** Full weekday label: "周一" / "Mon". */
export function weekday(key: string): string {
  return weekdayName(weekdayIndex(key));
}

export function weekdayName(index: number): string {
  return L(`周${WEEKDAYS_ZH[index]}`, WEEKDAYS_EN[index]);
}

/** Title for one day: "9/28 周一" / "Mon 9/28". */
export function dayTitle(key: string): string {
  return L(`${dayLabel(key)} ${weekday(key)}`, `${weekday(key)} ${dayLabel(key)}`);
}

export function relativeTime(ms: number | null, now = Date.now()): string {
  if (!ms) return L("尚未同步", "not synced yet");
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 45) return L("刚刚", "just now");
  if (s < 3600) return L(`${Math.round(s / 60)} 分钟前`, `${Math.round(s / 60)} min ago`);
  if (s < DAY / 1000) return L(`${Math.round(s / 3600)} 小时前`, `${Math.round(s / 3600)} h ago`);
  return shortDate(ms);
}

export function durationShort(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return L(`${s} 秒`, `${s}s`);
  if (s < 3600) return L(`${Math.round(s / 60)} 分钟`, `${Math.round(s / 60)} min`);
  return L(`${(s / 3600).toFixed(1)} 小时`, `${(s / 3600).toFixed(1)} h`);
}

/** "3 天" / "3 days". */
export function daysUnit(n: string | number): string {
  return L(`${n} 天`, `${n} days`);
}

/** "12 次" / "12 req". */
export function times(n: number): string {
  return L(`${count(n)} 次`, `${count(n)} req`);
}
