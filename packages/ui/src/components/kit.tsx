/** Small visual building blocks shared by every page. */
import { L } from "@cursor-usage/core";

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

/** Circular progress; `marker` (0-1) draws a tick where time says usage "should" be. */
export function Ring({
  value,
  marker,
  size = 88,
  stroke = 8,
  tone = "info",
  kind = "included",
  label,
}: {
  value: number;
  marker?: number | null;
  size?: number;
  stroke?: number;
  tone?: Tone;
  kind?: "included" | "ondemand" | "auto";
  label?: preact.ComponentChildren;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  const cls = tone === "warn" || tone === "danger" ? `ring-${tone}` : `ring-${kind}`;
  const markerAngle = marker != null ? Math.max(0, Math.min(1, marker)) * 2 * Math.PI - Math.PI / 2 : null;
  const cx = size / 2;
  return (
    <div class="ring" style={{ width: `${size}px`, height: `${size}px` }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle class="ring-track" cx={cx} cy={cx} r={r} stroke-width={stroke} fill="none" />
        <circle
          class={`ring-value ${cls}`}
          cx={cx}
          cy={cx}
          r={r}
          stroke-width={stroke}
          fill="none"
          stroke-linecap="round"
          stroke-dasharray={`${c * v} ${c}`}
          transform={`rotate(-90 ${cx} ${cx})`}
        />
        {markerAngle !== null && (
          <line
            class="ring-marker"
            x1={cx + (r - stroke / 2 - 2) * Math.cos(markerAngle)}
            y1={cx + (r - stroke / 2 - 2) * Math.sin(markerAngle)}
            x2={cx + (r + stroke / 2 + 2) * Math.cos(markerAngle)}
            y2={cx + (r + stroke / 2 + 2) * Math.sin(markerAngle)}
          />
        )}
      </svg>
      {label !== undefined && <div class="ring-label num">{label}</div>}
    </div>
  );
}

/** Tiny trend line for metric cards. */
export function Sparkline({ values, kind = "included", width = 96, height = 28 }: { values: number[]; kind?: "included" | "ondemand" | "auto" | "neutral"; width?: number; height?: number }) {
  if (values.length < 2) return <svg width={width} height={height} aria-hidden="true" />;
  const max = Math.max(...values, 1);
  const step = width / (values.length - 1);
  const pts = values.map((v, i) => [i * step, height - 2 - (v / max) * (height - 4)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const area = `${line}L${width},${height}L0,${height}Z`;
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg class={`spark spark-${kind}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path class="spark-area" d={area} />
      <path class="spark-line" d={line} />
      <circle class="spark-dot" cx={lx} cy={ly} r={2.2} />
    </svg>
  );
}

export function Chip({ tone = "neutral", children, title }: { tone?: Tone; children: preact.ComponentChildren; title?: string }) {
  return (
    <span class={`chip chip-${tone}`} title={title}>
      {children}
    </span>
  );
}

export type Vendor = "anthropic" | "openai" | "xai" | "google" | "deepseek" | "cursor" | "other";

export function vendorOf(model: string): Vendor {
  const m = model.toLowerCase();
  if (/claude|anthropic|opus|sonnet|haiku|fable/.test(m)) return "anthropic";
  if (/\bgpt|openai|codex|\bo[134]\b|o[134]-/.test(m)) return "openai";
  if (/grok|xai/.test(m)) return "xai";
  if (/gemini|google/.test(m)) return "google";
  if (/deepseek/.test(m)) return "deepseek";
  if (/cursor|composer|auto/.test(m)) return "cursor";
  return "other";
}

const VENDOR_LABEL: Record<Vendor, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  xai: "xAI",
  google: "Google",
  deepseek: "DeepSeek",
  cursor: "Cursor",
  other: "",
};

export function vendorLabel(vendor: Vendor): string {
  return VENDOR_LABEL[vendor] || L("其他", "Other");
}

export function ModelDot({ model }: { model: string }) {
  const vendor = vendorOf(model);
  return <i class={`model-dot v-${vendor}`} title={vendorLabel(vendor)} aria-hidden="true" />;
}

export function ModelName({ model }: { model: string }) {
  return (
    <span class="model-name" title={model}>
      <ModelDot model={model} />
      <span>{model}</span>
    </span>
  );
}
