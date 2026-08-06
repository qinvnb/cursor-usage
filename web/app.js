let ondPie, ondBar, dailyChart;
let homeTrendChart, homeMixChart;
let ondCumChart, ondTrendChart;
let incTrendChart, incAutoApiChart, incModelChart;
let dailyMaChart, dailyWeekdayChart;
let modelTotalChart, modelStackChart;
let refreshSeconds = 60;
let timer = null;
let fullData = null;
let selectedDay = null;
let currentView = "home";
let loadInFlight = null;
let baseFingerprint = "";
const pageFingerprints = new Map();

const COLORS = ["#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed", "#0891b2"];
const INSIGHT_ICONS = ["↗", "≈", "◆", "◎"];

function usd(cents) {
  return `$${(Number(cents || 0) / 100).toFixed(2)}`;
}

function pct(used, limit) {
  if (!limit) return 0;
  return Math.min(100, (used / limit) * 100);
}

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso || "";
  }
}

function fmtAge(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "未知";
  const value = Math.max(0, Number(seconds));
  if (value < 60) return `${Math.round(value)}秒`;
  if (value < 3600) return `${Math.round(value / 60)}分钟`;
  return `${(value / 3600).toFixed(1)}小时`;
}

function msToDate(ms) {
  try {
    return new Date(Number(ms)).toLocaleDateString("zh-CN");
  } catch {
    return "";
  }
}

function destroyChart(chart) {
  if (chart) chart.destroy();
}

function chartDefaults() {
  Chart.defaults.color = "#6b7280";
  Chart.defaults.borderColor = "#e5e7eb";
  Chart.defaults.animation.duration = 700;
  Chart.defaults.animation.easing = "easeOutQuart";
  Chart.defaults.interaction.mode = "index";
  Chart.defaults.interaction.intersect = false;
  Chart.defaults.plugins.tooltip.backgroundColor = "rgba(15, 23, 42, 0.94)";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
}

function setStatus(text, cls) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = `pill ${cls || ""}`;
}

async function fetchStatus() {
  try {
    return await fetch("/api/status", { cache: "no-store" }).then((r) => r.json());
  } catch {
    return null;
  }
}

function renderStats(summary) {
  const items = [
    { value: usd(summary.unifiedUsedCents), label: "统一已用", cls: "info", icon: "∑" },
    {
      value: `${usd(summary.individualUsedCents)} / ${usd(summary.individualLimitCents)}`,
      label: "个人按需 已用 / 上限",
      cls: "danger",
      icon: "↗",
    },
    {
      value: usd(summary.individualRemainingCents),
      label: "个人按需剩余",
      cls: "ok",
      icon: "◇",
    },
    {
      value: `${usd(summary.includedUsedCents)} / ${usd(summary.includedLimitCents)}`,
      label: "套餐内 已用 / 上限",
      cls: "",
      icon: "◫",
    },
  ];
  document.getElementById("stats").innerHTML = items
    .map(
      (i) =>
        `<div class="stat ${i.cls}"><div class="stat-icon">${i.icon}</div><div class="value">${i.value}</div><div class="label">${i.label}</div></div>`
    )
    .join("");
}

function renderBars(summary) {
  const incUsed = Number(summary.includedUsedCents || 0) / 100;
  const incLimit = Number(summary.includedLimitCents || 0) / 100;
  const ondUsed = Number(summary.individualUsedCents || 0) / 100;
  const ondLimit = Number(summary.individualLimitCents || 0) / 100;

  const incLeft = `已用 ${pct(incUsed, incLimit).toFixed(0)}%`;
  const incRight = `${usd(summary.includedUsedCents)} / ${usd(summary.includedLimitCents)}`;
  const incDetail =
    `剩余 ${usd(summary.includedRemainingCents)} · 赠送 ${usd(summary.bonusSpendCents)} · Auto ${Number(summary.autoPercentUsed || 0).toFixed(1)}% · API ${Number(summary.apiPercentUsed || 0).toFixed(1)}%`;
  const ondLeft = `已用 ${pct(ondUsed, ondLimit).toFixed(0)}%`;
  const ondRight = `${usd(summary.individualUsedCents)} / ${usd(summary.individualLimitCents)}`;
  const ondDetail =
    `已用 ${usd(summary.individualUsedCents)}，上限 ${usd(summary.individualLimitCents)}，剩余 ${usd(summary.individualRemainingCents)}`;

  const setBar = (leftId, rightId, barId, detailId, left, right, width, detail) => {
    const l = document.getElementById(leftId);
    const r = document.getElementById(rightId);
    const b = document.getElementById(barId);
    const d = document.getElementById(detailId);
    if (l) l.textContent = left;
    if (r) r.textContent = right;
    if (b) b.style.width = `${width}%`;
    if (d) d.textContent = detail;
  };

  setBar("incLeftLabel", "incRightLabel", "incBar", "incDetail", incLeft, incRight, pct(incUsed, incLimit), incDetail);
  setBar("ondLeftLabel", "ondRightLabel", "ondBar", "ondDetail", ondLeft, ondRight, pct(ondUsed, ondLimit), ondDetail);
  setBar("homeIncLeft", "homeIncRight", "homeIncBar", "homeIncDetail", incLeft, incRight, pct(incUsed, incLimit), incDetail);
  setBar("homeOndLeft", "homeOndRight", "homeOndBar", "homeOndDetail", ondLeft, ondRight, pct(ondUsed, ondLimit), ondDetail);

  const extra = document.getElementById("incExtra");
  if (extra) {
    extra.textContent =
      `套餐内已用 ${usd(summary.includedUsedCents)} / 上限 ${usd(summary.includedLimitCents)}；` +
      `剩余 ${usd(summary.includedRemainingCents)}；赠送 ${usd(summary.bonusSpendCents)}；` +
      `Auto ${Number(summary.autoPercentUsed || 0).toFixed(1)}% · API ${Number(summary.apiPercentUsed || 0).toFixed(1)}%`;
  }
}

function dayTotalCents(row) {
  return Number(row.onDemandCostCents || 0) + Number(row.includedCostCents || 0);
}

function sumKey(arr, key) {
  return arr.reduce((a, x) => a + Number(x[key] || 0), 0);
}

function stdev(values) {
  if (!values.length) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const v = values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length;
  return Math.sqrt(v);
}

function movingAvg(values, window) {
  return values.map((_, i) => {
    const from = Math.max(0, i - window + 1);
    const slice = values.slice(from, i + 1);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
}

function herfindahl(shares) {
  // shares as fractions 0-1
  return shares.reduce((a, s) => a + s * s, 0);
}

function fillInsightCards(elId, items) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = items
    .map(
      (c, index) =>
        `<div class="insight"><div class="insight-head"><span class="insight-icon">${c.icon || INSIGHT_ICONS[index % INSIGHT_ICONS.length]}</span><div><div class="value">${c.value}</div><div class="label">${c.label}</div></div></div><div class="delta ${c.deltaCls || "flat"}">${c.delta || ""}</div></div>`
    )
    .join("");
}

function fillInsightList(elId, bullets) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = bullets.map((b) => `<li>${b}</li>`).join("");
}

function lineOpts() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { position: "bottom" } },
    scales: { y: { ticks: { callback: (v) => `$${v}` } } },
  };
}

function buildSeries(data) {
  const daily = (data.daily || []).slice().sort((a, b) => a.date.localeCompare(b.date));
  const summary = data.summary || {};
  const totals = daily.map((r) => ({
    date: r.date,
    total: dayTotalCents(r),
    ond: Number(r.onDemandCostCents || 0),
    inc: Number(r.includedCostCents || 0),
    events: Number(r.eventCount || 0),
  }));
  const active = totals.filter((t) => t.total > 0);
  const startMs = Number(summary.billingCycleStart || 0);
  const endMs = Number(summary.billingCycleEnd || 0);
  const now = Date.now();
  let daysLeft = null;
  let daysElapsed = null;
  let cycleDays = null;
  if (startMs && endMs && endMs > startMs) {
    daysLeft = Math.max(0, Math.ceil((endMs - now) / 86400000));
    daysElapsed = Math.max(1, Math.ceil((Math.min(now, endMs) - startMs) / 86400000));
    cycleDays = Math.max(1, Math.ceil((endMs - startMs) / 86400000));
  }
  const last7 = totals.slice(-7);
  const prev7 = totals.slice(-14, -7);
  const last7Sum = sumKey(last7, "total");
  const prev7Sum = sumKey(prev7, "total");
  let wow = null;
  if (prev7Sum > 0) wow = ((last7Sum - prev7Sum) / prev7Sum) * 100;
  else if (last7Sum > 0) wow = 100;

  return {
    daily,
    totals,
    active,
    summary,
    daysLeft,
    daysElapsed,
    cycleDays,
    last7,
    last7Sum,
    wow,
    last14: totals.slice(-14),
  };
}

function renderHomeAnalytics(data) {
  const s = buildSeries(data);
  const summary = s.summary;
  const avgDaily = s.active.length ? sumKey(s.totals, "total") / s.active.length : 0;
  const peak = s.active.slice().sort((a, b) => b.total - a.total)[0] || null;
  const used = Number(summary.individualUsedCents || 0) + Number(summary.includedUsedCents || 0);
  const projected = s.daysElapsed && s.cycleDays ? (used / s.daysElapsed) * s.cycleDays : null;
  const pace =
    s.daysElapsed && s.cycleDays ? used / (Number(summary.includedLimitCents || 0) + Number(summary.individualLimitCents || 0) || 1) : null;
  const timeFrac = s.daysElapsed && s.cycleDays ? s.daysElapsed / s.cycleDays : null;

  const wowCls = s.wow == null ? "flat" : s.wow > 3 ? "up" : s.wow < -3 ? "down" : "flat";
  const wowText =
    s.wow == null ? "暂无对比" : `${s.wow > 0 ? "↑" : s.wow < 0 ? "↓" : "→"} ${Math.abs(s.wow).toFixed(0)}% vs 前 7 天`;

  fillInsightCards("homeInsightCards", [
    { value: usd(avgDaily), label: "活跃日均合计", delta: `${s.active.length} 个活跃日` },
    { value: peak ? usd(peak.total) : "—", label: "峰值日", delta: peak ? peak.date : "暂无" },
    { value: usd(s.last7Sum), label: "近 7 日合计", delta: wowText, deltaCls: wowCls },
    {
      value: projected != null ? usd(projected) : "—",
      label: "周期合计预估",
      delta: s.daysLeft != null ? `剩余约 ${s.daysLeft} 天` : "—",
    },
  ]);

  const bullets = [];
  bullets.push(`本周期已发生 ${sumKey(s.totals, "events")} 次计费事件，合计约 ${usd(sumKey(s.totals, "total"))}。`);
  if (timeFrac != null && pace != null) {
    const ahead = pace - timeFrac;
    bullets.push(
      ahead > 0.05
        ? `消耗进度（相对双额度）快于时间进度约 ${(ahead * 100).toFixed(0)} 个百分点。`
        : ahead < -0.05
          ? `消耗进度慢于时间进度约 ${(Math.abs(ahead) * 100).toFixed(0)} 个百分点，节奏偏稳。`
          : `消耗进度与时间进度基本同步。`
    );
  }
  if (s.wow != null) {
    bullets.push(
      s.wow > 3
        ? `近 7 日用量上升 ${s.wow.toFixed(0)}%，留意按需额度。`
        : s.wow < -3
          ? `近 7 日用量下降 ${Math.abs(s.wow).toFixed(0)}%。`
          : `近 7 日用量与此前基本持平。`
    );
  }
  fillInsightList("homeInsightList", bullets);

  const trendEl = document.getElementById("homeTrendChart");
  if (trendEl) {
    destroyChart(homeTrendChart);
    homeTrendChart = new Chart(trendEl, {
      type: "line",
      data: {
        labels: s.last14.map((r) => r.date.slice(5)),
        datasets: [
          {
            label: "合计",
            data: s.last14.map((r) => r.total / 100),
            borderColor: "#2563eb",
            backgroundColor: "rgba(37,99,235,0.12)",
            fill: true,
            tension: 0.3,
            pointRadius: 2,
          },
          {
            label: "个人按需",
            data: s.last14.map((r) => r.ond / 100),
            borderColor: "#dc2626",
            borderDash: [4, 3],
            fill: false,
            tension: 0.3,
            pointRadius: 0,
          },
        ],
      },
      options: lineOpts(),
    });
  }

  const mixEl = document.getElementById("homeMixChart");
  if (mixEl) {
    destroyChart(homeMixChart);
    homeMixChart = new Chart(mixEl, {
      type: "doughnut",
      data: {
        labels: ["个人按需", "套餐内", "赠送"],
        datasets: [
          {
            data: [
              Number(summary.individualUsedCents || 0) / 100,
              Number(summary.includedUsedCents || 0) / 100,
              Number(summary.bonusSpendCents || 0) / 100,
            ],
            backgroundColor: ["#2563eb", "#d97706", "#94a3b8"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
      },
    });
  }
}

function renderOndemandAnalytics(data) {
  const s = buildSeries(data);
  const summary = s.summary;
  const used = Number(summary.individualUsedCents || 0);
  const limit = Number(summary.individualLimitCents || 0);
  const left = Number(summary.individualRemainingCents || 0);
  const avgOnd = s.active.length ? sumKey(s.totals, "ond") / s.active.length : 0;
  const burn7 = sumKey(s.last7, "ond") / Math.max(1, s.last7.filter((x) => x.ond > 0).length || s.last7.length || 1);
  const daysToEmpty = burn7 > 0 ? left / burn7 : null;
  const models = (data.onDemandModels || []).filter((m) => Number(m.costCents) > 0);
  const totalM = sumKey(models, "costCents") || 1;
  const shares = models.map((m) => Number(m.costCents) / totalM);
  const hhi = herfindahl(shares);
  const top = models[0];
  const top3 = shares.slice(0, 3).reduce((a, b) => a + b, 0);

  fillInsightCards("ondInsightCards", [
    { value: `${pct(used / 100, limit / 100).toFixed(0)}%`, label: "按需已用占比", delta: `${usd(used)} / ${usd(limit)}` },
    { value: usd(avgOnd), label: "活跃日均按需", delta: `近 7 日日均约 ${usd(burn7)}` },
    {
      value: daysToEmpty != null && Number.isFinite(daysToEmpty) ? `${Math.max(0, daysToEmpty).toFixed(1)} 天` : "—",
      label: "按近 7 日节奏耗尽",
      delta: left > 0 ? `剩余 ${usd(left)}` : "已用尽",
      deltaCls: daysToEmpty != null && daysToEmpty < 7 ? "up" : "flat",
    },
    {
      value: `${(top3 * 100).toFixed(0)}%`,
      label: "Top3 模型集中度",
      delta: `HHI ${(hhi * 100).toFixed(0)}（越高越集中）`,
    },
  ]);

  const bullets = [];
  if (top) bullets.push(`头部模型 <strong>${top.model}</strong> 约占 ${(shares[0] * 100).toFixed(1)}%（${usd(top.costCents)}）。`);
  bullets.push(
    hhi > 0.35
      ? "模型结构较集中，成本对少数模型更敏感。"
      : "模型结构较分散，风险相对分散。"
  );
  if (daysToEmpty != null && s.daysLeft != null) {
    bullets.push(
      daysToEmpty < s.daysLeft
        ? `按当前节奏，按需额度可能早于周期结束约 ${(s.daysLeft - daysToEmpty).toFixed(0)} 天耗尽。`
        : `按当前节奏，按需额度大概率能撑过本周期（预估 ${daysToEmpty.toFixed(0)} 天）。`
    );
  }
  fillInsightList("ondInsightList", bullets);

  let cum = 0;
  const cumPts = s.totals.map((r) => {
    cum += r.ond;
    return cum / 100;
  });
  const cumEl = document.getElementById("ondCumChart");
  if (cumEl) {
    destroyChart(ondCumChart);
    ondCumChart = new Chart(cumEl, {
      type: "line",
      data: {
        labels: s.totals.map((r) => r.date.slice(5)),
        datasets: [
          {
            label: "累计按需",
            data: cumPts,
            borderColor: "#2563eb",
            backgroundColor: "rgba(37,99,235,0.1)",
            fill: true,
            tension: 0.25,
            pointRadius: 0,
          },
          ...(limit
            ? [
                {
                  label: "上限",
                  data: s.totals.map(() => limit / 100),
                  borderColor: "#ef4444",
                  borderDash: [6, 4],
                  pointRadius: 0,
                  fill: false,
                },
              ]
            : []),
        ],
      },
      options: lineOpts(),
    });
  }

  const trEl = document.getElementById("ondTrendChart");
  if (trEl) {
    destroyChart(ondTrendChart);
    ondTrendChart = new Chart(trEl, {
      type: "bar",
      data: {
        labels: s.last14.map((r) => r.date.slice(5)),
        datasets: [{ label: "个人按需", data: s.last14.map((r) => r.ond / 100), backgroundColor: "#2563eb", borderRadius: 4 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: (v) => `$${v}` } } },
      },
    });
  }
}

function renderIncludedAnalytics(data) {
  const s = buildSeries(data);
  const summary = s.summary;
  const used = Number(summary.includedUsedCents || 0);
  const limit = Number(summary.includedLimitCents || 0);
  const left = Number(summary.includedRemainingCents || 0);
  const autoP = Number(summary.autoPercentUsed || 0);
  const apiP = Number(summary.apiPercentUsed || 0);
  const avgInc = s.active.length ? sumKey(s.totals, "inc") / s.active.length : 0;
  const burn7 = sumKey(s.last7, "inc") / Math.max(1, s.last7.filter((x) => x.inc > 0).length || s.last7.length || 1);
  const daysToEmpty = burn7 > 0 ? left / burn7 : null;
  const incModels = (data.includedModels || []).filter((m) => Number(m.costCents) > 1).slice(0, 8);

  fillInsightCards("incInsightCards", [
    { value: `${pct(used / 100, limit / 100).toFixed(0)}%`, label: "套餐已用占比", delta: `${usd(used)} / ${usd(limit)}` },
    { value: usd(avgInc), label: "活跃日均套餐内", delta: `近 7 日日均约 ${usd(burn7)}` },
    {
      value: daysToEmpty != null && Number.isFinite(daysToEmpty) ? `${Math.max(0, daysToEmpty).toFixed(1)} 天` : "—",
      label: "按近 7 日节奏耗尽",
      delta: `剩余 ${usd(left)}`,
      deltaCls: daysToEmpty != null && daysToEmpty < 7 ? "up" : "flat",
    },
    {
      value: `${autoP.toFixed(0)}% / ${apiP.toFixed(0)}%`,
      label: "Auto / API 用量%",
      delta: `赠送 ${usd(summary.bonusSpendCents)}`,
    },
  ]);

  const bullets = [];
  bullets.push(`套餐内事件合计约 ${usd(summary.includedEventCostCents || sumKey(s.totals, "inc"))}。`);
  if (autoP || apiP) {
    bullets.push(
      autoP >= apiP
        ? `Auto 占比更高（${autoP.toFixed(1)}%），偏自动路由消耗。`
        : `API 占比更高（${apiP.toFixed(1)}%），偏显式调用。`
    );
  }
  if (daysToEmpty != null && s.daysLeft != null) {
    bullets.push(
      daysToEmpty < s.daysLeft
        ? `按当前节奏，套餐额度可能提前约 ${(s.daysLeft - daysToEmpty).toFixed(0)} 天用完。`
        : `按当前节奏，套餐额度大概率可撑过本周期。`
    );
  }
  fillInsightList("incInsightList", bullets);

  const trEl = document.getElementById("incTrendChart");
  if (trEl) {
    destroyChart(incTrendChart);
    incTrendChart = new Chart(trEl, {
      type: "line",
      data: {
        labels: s.last14.map((r) => r.date.slice(5)),
        datasets: [
          {
            label: "套餐内",
            data: s.last14.map((r) => r.inc / 100),
            borderColor: "#d97706",
            backgroundColor: "rgba(217,119,6,0.12)",
            fill: true,
            tension: 0.3,
            pointRadius: 2,
          },
        ],
      },
      options: lineOpts(),
    });
  }

  const aaEl = document.getElementById("incAutoApiChart");
  if (aaEl) {
    destroyChart(incAutoApiChart);
    const autoV = Math.max(0, autoP);
    const apiV = Math.max(0, apiP);
    const other = Math.max(0, 100 - autoV - apiV);
    incAutoApiChart = new Chart(aaEl, {
      type: "doughnut",
      data: {
        labels: ["Auto", "API", "其他/未拆分"],
        datasets: [{ data: [autoV, apiV, other], backgroundColor: ["#2563eb", "#059669", "#e5e7eb"], borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
          tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${Number(ctx.raw).toFixed(1)}%` } },
        },
      },
    });
  }

  const mEl = document.getElementById("incModelChart");
  if (mEl) {
    destroyChart(incModelChart);
    incModelChart = new Chart(mEl, {
      type: "bar",
      data: {
        labels: incModels.map((m) => m.model),
        datasets: [{ label: "套餐内", data: incModels.map((m) => Number(m.costCents) / 100), backgroundColor: "#f59e0b", borderRadius: 6 }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { callback: (v) => `$${v}` } } },
      },
    });
  }
}

function renderDailyAnalytics(data) {
  const rows = filteredDaily(data.daily || []);
  const totals = rows.map((r) => dayTotalCents(r));
  const activeTotals = totals.filter((v) => v > 0);
  const avg = activeTotals.length ? activeTotals.reduce((a, b) => a + b, 0) / activeTotals.length : 0;
  const sd = stdev(activeTotals);
  const peakIdx = totals.reduce((best, v, i) => (v > totals[best] ? i : best), 0);
  const peak = rows[peakIdx];
  const ondShare = sumKey(rows, "onDemandCostCents");
  const incShare = sumKey(rows, "includedCostCents");
  const all = ondShare + incShare || 1;

  // longest active streak
  let streak = 0;
  let bestStreak = 0;
  rows.forEach((r) => {
    if (dayTotalCents(r) > 0) {
      streak += 1;
      bestStreak = Math.max(bestStreak, streak);
    } else streak = 0;
  });

  fillInsightCards("dailyInsightCards", [
    { value: usd(avg), label: "筛选范围 · 活跃日均", delta: `${activeTotals.length} / ${rows.length} 天有用量` },
    { value: usd(sd), label: "波动（标准差）", delta: avg ? `变异系数 ${((sd / avg) * 100).toFixed(0)}%` : "—" },
    { value: peak ? usd(dayTotalCents(peak)) : "—", label: "区间峰值", delta: peak ? peak.date : "—" },
    { value: `${bestStreak} 天`, label: "最长连续活跃", delta: `按需占比 ${((ondShare / all) * 100).toFixed(0)}%` },
  ]);

  const bullets = [];
  if (peak) bullets.push(`峰值日 <strong>${peak.date}</strong>，合计 ${usd(dayTotalCents(peak))}（按需 ${usd(peak.onDemandCostCents)} / 套餐 ${usd(peak.includedCostCents)}）。`);
  bullets.push(
    sd > avg * 0.8 && avg > 0
      ? "日用量波动较大，高峰日对额度影响明显。"
      : "日用量相对平稳。"
  );
  bullets.push(`区间内按需 ${usd(ondShare)}，套餐内 ${usd(incShare)}。`);
  fillInsightList("dailyInsightList", bullets);

  const ma = movingAvg(totals.map((v) => v / 100), 7);
  const maEl = document.getElementById("dailyMaChart");
  if (maEl) {
    destroyChart(dailyMaChart);
    dailyMaChart = new Chart(maEl, {
      type: "line",
      data: {
        labels: rows.map((r) => r.date.slice(5)),
        datasets: [
          {
            label: "合计",
            data: totals.map((v) => v / 100),
            borderColor: "#94a3b8",
            pointRadius: 0,
            tension: 0.2,
          },
          {
            label: "7 日均线",
            data: ma,
            borderColor: "#2563eb",
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
          },
        ],
      },
      options: lineOpts(),
    });
  }

  const weekday = [0, 0, 0, 0, 0, 0, 0];
  const weekdayN = [0, 0, 0, 0, 0, 0, 0];
  rows.forEach((r) => {
    const wd = new Date(r.date + "T00:00:00").getDay();
    weekday[wd] += dayTotalCents(r);
    weekdayN[wd] += 1;
  });
  const weekdayAvg = weekday.map((v, i) => (weekdayN[i] ? v / weekdayN[i] : 0));
  const wdNames = ["日", "一", "二", "三", "四", "五", "六"];
  const wdEl = document.getElementById("dailyWeekdayChart");
  if (wdEl) {
    destroyChart(dailyWeekdayChart);
    dailyWeekdayChart = new Chart(wdEl, {
      type: "bar",
      data: {
        labels: wdNames.map((n) => `周${n}`),
        datasets: [{ label: "日均合计", data: weekdayAvg.map((v) => v / 100), backgroundColor: "#93c5fd", borderRadius: 6 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: (v) => `$${v}` } } },
      },
    });
  }
}

function renderModelAnalytics(data) {
  const models = (data.models || [])
    .map((m) => ({
      model: m.model,
      ond: Number(m.onDemandCostCents || 0),
      inc: Number(m.includedCostCents || 0),
      total: Number(m.totalCostCents || 0),
    }))
    .filter((m) => m.total > 1)
    .sort((a, b) => b.total - a.total);
  const totalAll = models.reduce((a, m) => a + m.total, 0) || 1;
  const shares = models.map((m) => m.total / totalAll);
  const hhi = herfindahl(shares);
  const top3 = shares.slice(0, 3).reduce((a, b) => a + b, 0);
  let running = 0;
  let cover80 = models.length;
  for (let i = 0; i < shares.length; i++) {
    running += shares[i];
    if (running >= 0.8) {
      cover80 = i + 1;
      break;
    }
  }
  const ondTotal = models.reduce((a, m) => a + m.ond, 0);
  const incTotal = models.reduce((a, m) => a + m.inc, 0);

  fillInsightCards("modelInsightCards", [
    { value: String(models.length), label: "有成本模型数", delta: `合计 ${usd(totalAll)}` },
    { value: `${(top3 * 100).toFixed(0)}%`, label: "Top3 合计占比", delta: models[0] ? `冠军 ${models[0].model}` : "—" },
    { value: String(cover80), label: "覆盖 80% 成本所需模型数", delta: `HHI ${(hhi * 100).toFixed(0)}` },
    {
      value: `${((ondTotal / totalAll) * 100).toFixed(0)}% / ${((incTotal / totalAll) * 100).toFixed(0)}%`,
      label: "按需 / 套餐 结构",
      delta: `${usd(ondTotal)} · ${usd(incTotal)}`,
    },
  ]);

  const bullets = [];
  if (models[0]) bullets.push(`成本最高模型 <strong>${models[0].model}</strong>，占 ${(shares[0] * 100).toFixed(1)}%。`);
  bullets.push(`约 ${cover80} 个模型贡献了 80% 成本。`);
  bullets.push(
    hhi > 0.25 ? "模型成本高度集中，切换主力模型会显著改变账单结构。" : "模型成本较分散，没有过度依赖单一模型。"
  );
  fillInsightList("modelInsightList", bullets);

  const top = models.slice(0, 10);
  const tEl = document.getElementById("modelTotalChart");
  if (tEl) {
    destroyChart(modelTotalChart);
    modelTotalChart = new Chart(tEl, {
      type: "bar",
      data: {
        labels: top.map((m) => m.model),
        datasets: [{ label: "合计", data: top.map((m) => m.total / 100), backgroundColor: "#2563eb", borderRadius: 6 }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { callback: (v) => `$${v}` } } },
      },
    });
  }

  const sEl = document.getElementById("modelStackChart");
  if (sEl) {
    destroyChart(modelStackChart);
    modelStackChart = new Chart(sEl, {
      type: "bar",
      data: {
        labels: top.map((m) => m.model),
        datasets: [
          { label: "个人按需", data: top.map((m) => m.ond / 100), backgroundColor: "#2563eb", borderRadius: 4 },
          { label: "套餐内", data: top.map((m) => m.inc / 100), backgroundColor: "#f59e0b", borderRadius: 4 },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
        scales: {
          x: { stacked: true, ticks: { callback: (v) => `$${v}` } },
          y: { stacked: true },
        },
      },
    });
  }

  const combined = document.getElementById("combinedTable");
  if (combined) {
    combined.innerHTML = models
      .map(
        (m) =>
          `<tr><td>${m.model}</td><td class="num">${usd(m.ond)}</td><td class="num">${usd(m.inc)}</td><td class="num">${usd(m.total)}</td></tr>`
      )
      .join("");
  }
}

function renderPageAnalytics(data, view) {
  const v = view || currentView;
  if (v === "home") renderHomeAnalytics(data);
  else if (v === "ondemand") renderOndemandAnalytics(data);
  else if (v === "included") renderIncludedAnalytics(data);
  else if (v === "daily") renderDailyAnalytics(data);
  else if (v === "models") renderModelAnalytics(data);
}

function pageFingerprint(data, view) {
  const common = { summary: data.summary, daily: data.daily };
  if (view === "home") return JSON.stringify(common);
  if (view === "ondemand") {
    return JSON.stringify({ ...common, onDemandModels: data.onDemandModels });
  }
  if (view === "included") {
    return JSON.stringify({ ...common, includedModels: data.includedModels });
  }
  if (view === "daily") {
    const range = document.getElementById("rangeSelect");
    return JSON.stringify({
      daily: data.daily,
      range: range?.value,
      from: document.getElementById("dateFrom")?.value,
      to: document.getElementById("dateTo")?.value,
    });
  }
  if (view === "models") return JSON.stringify({ models: data.models });
  return "";
}

function renderCurrentPage(data, force = false) {
  if (currentView === "settings") return;
  const signature = pageFingerprint(data, currentView);
  if (!force && pageFingerprints.get(currentView) === signature) return;
  if (currentView === "ondemand") renderModels(data);
  if (currentView === "daily") renderDaily(data);
  renderPageAnalytics(data, currentView);
  pageFingerprints.set(currentView, signature);
}

function chartsForView(view) {
  const charts = {
    home: [homeTrendChart, homeMixChart],
    ondemand: [ondCumChart, ondTrendChart, ondPie, ondBar],
    included: [incTrendChart, incAutoApiChart, incModelChart],
    daily: [dailyChart, dailyMaChart, dailyWeekdayChart],
    models: [modelTotalChart, modelStackChart],
  };
  return (charts[view] || []).filter(Boolean);
}

function replayChartMotion(view) {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      chartsForView(view).forEach((chart) => {
        chart.resize();
        chart.reset();
        chart.update();
      });
    });
  });
}

function filteredDaily(daily) {
  const rows = (daily || []).slice().sort((a, b) => a.date.localeCompare(b.date));
  const mode = document.getElementById("rangeSelect").value;
  if (mode === "cycle") return rows;
  if (mode === "custom") {
    const from = document.getElementById("dateFrom").value;
    const to = document.getElementById("dateTo").value;
    return rows.filter((r) => (!from || r.date >= from) && (!to || r.date <= to));
  }
  const n = Number(mode) || 7;
  if (!rows.length) return rows;
  const last = rows[rows.length - 1].date;
  const end = new Date(last + "T00:00:00");
  const start = new Date(end);
  start.setDate(end.getDate() - (n - 1));
  const startStr = start.toISOString().slice(0, 10);
  return rows.filter((r) => r.date >= startStr);
}

function renderDaily(data) {
  const rows = filteredDaily(data.daily || []);
  const labels = rows.map((r) => r.date.slice(5));
  const ond = rows.map((r) => Number(r.onDemandCostCents || 0) / 100);
  const inc = rows.map((r) => Number(r.includedCostCents || 0) / 100);

  destroyChart(dailyChart);
  dailyChart = new Chart(document.getElementById("dailyChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "个人按需", data: ond, backgroundColor: "#2563eb", borderRadius: 4 },
        { label: "套餐内", data: inc, backgroundColor: "#93c5fd", borderRadius: 4 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom" },
        tooltip: {
          callbacks: { label: (ctx) => ` ${ctx.dataset.label}: $${Number(ctx.raw).toFixed(2)}` },
        },
      },
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: {
          stacked: true,
          ticks: { callback: (v) => `$${v}` },
        },
      },
      onClick: (_e, els) => {
        if (!els.length) return;
        const idx = els[0].index;
        selectedDay = rows[idx]?.date || null;
        renderDailyTable(rows);
        showDayDetail(rows[idx]);
      },
    },
  });

  renderDailyTable(rows);
  if (selectedDay) {
    const hit = rows.find((r) => r.date === selectedDay);
    showDayDetail(hit || null);
  } else {
    const ondSum = rows.reduce((a, r) => a + Number(r.onDemandCostCents || 0), 0);
    const incSum = rows.reduce((a, r) => a + Number(r.includedCostCents || 0), 0);
    document.getElementById("dayDetail").textContent = rows.length
      ? `范围内合计：个人按需 ${usd(ondSum)}，套餐内 ${usd(incSum)}（共 ${rows.length} 天）。点击柱状图某一天可看当日模型明细。`
      : "所选范围内暂无按日数据，请先刷新。";
  }
}

function renderDailyTable(rows) {
  document.getElementById("dailyTable").innerHTML = rows
    .map((r) => {
      const active = r.date === selectedDay ? "active" : "";
      return `<tr class="${active}" data-day="${r.date}">
        <td>${r.date}</td>
        <td class="num">${usd(r.onDemandCostCents)}</td>
        <td class="num">${usd(r.includedCostCents)}</td>
        <td class="num">${usd(r.totalCostCents)}</td>
        <td>${r.topOnDemandModel || "-"}</td>
      </tr>`;
    })
    .join("");

  document.querySelectorAll("#dailyTable tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      selectedDay = tr.getAttribute("data-day");
      const row = rows.find((r) => r.date === selectedDay);
      renderDailyTable(rows);
      showDayDetail(row);
    });
  });
}

function showDayDetail(row) {
  if (!row) {
    document.getElementById("dayDetail").textContent = "";
    return;
  }
  const models = (row.onDemandModels || [])
    .slice(0, 5)
    .map((m) => `${m.model} ${usd(m.costCents)}`)
    .join(" · ");
  document.getElementById("dayDetail").textContent =
    `${row.date}：个人按需 ${usd(row.onDemandCostCents)}，套餐内 ${usd(row.includedCostCents)}，事件 ${row.eventCount} 次` +
    (models ? `。按需头部：${models}` : "");
}

function renderModels(data) {
  const ond = (data.onDemandModels || []).filter((m) => Number(m.costCents) > 1);
  const ondLabels = ond.map((m) => m.model);
  const ondValues = ond.map((m) => Number(m.costCents) / 100);

  const pieEl = document.getElementById("ondPie");
  const barEl = document.getElementById("ondBarChart");
  if (pieEl && barEl) {
    destroyChart(ondPie);
    destroyChart(ondBar);
    ondPie = new Chart(pieEl, {
      type: "doughnut",
      data: {
        labels: ondLabels,
        datasets: [{ data: ondValues, backgroundColor: COLORS, borderWidth: 0 }],
      },
      options: { plugins: { legend: { position: "bottom" } } },
    });
    ondBar = new Chart(barEl, {
      type: "bar",
      data: {
        labels: ondLabels,
        datasets: [{ label: "个人按需", data: ondValues, backgroundColor: "#2563eb", borderRadius: 6 }],
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { callback: (v) => `$${v}` } },
          y: { grid: { display: false } },
        },
      },
    });
  }

  const ondTable = document.getElementById("ondTable");
  if (ondTable) {
    ondTable.innerHTML = (data.onDemandModels || [])
      .map(
        (m) =>
          `<tr><td>${m.model}</td><td class="num">${usd(m.costCents)}</td><td class="num">${Number(m.sharePercent || 0).toFixed(1)}%</td></tr>`
      )
      .join("");
  }
}

function paint(data) {
  fullData = data;
  const s = data.summary || {};
  const acct = data.account || {};
  const plan = data.planInfo || {};
  document.getElementById("meta").textContent =
    `${acct.email || "未知账号"} · ${plan.planName || ""}（${plan.price || ""}）· 周期 ${msToDate(s.billingCycleStart)} → ${msToDate(s.billingCycleEnd)} · 本地 ${fmtTime(data.fetchedAt)}` +
    (acct.authSource ? ` · 凭证:${acct.authSource === "manual" ? "手动" : acct.authSource === "env" ? "环境变量" : "本机"}` : "");
  const nextBaseFingerprint = JSON.stringify(s);
  if (baseFingerprint !== nextBaseFingerprint) {
    renderStats(s);
    renderBars(s);
    baseFingerprint = nextBaseFingerprint;
  }
  renderCurrentPage(data);
}

async function loadUsage() {
  if (loadInFlight) return loadInFlight;
  loadInFlight = (async () => {
    const err = document.getElementById("error");
    err.hidden = true;
    try {
      const res = await fetch("/api/usage", { cache: "no-store" });
      const data = await res.json();
      if (!res.ok || data.error) {
        const st = data.status || (await fetchStatus());
        if (st && st.refreshing) {
          setStatus(st.refreshState === "pending" ? "刷新排队中" : "后台拉取中", "");
          err.hidden = false;
          err.textContent = "本地暂无缓存，正在后台更新 data/usage.json…";
          return;
        }
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      const st = await fetchStatus();
      paint(data);
      const age = st?.ageSeconds ?? data.cache?.ageSeconds;
      const state = st?.refreshState || data.cache?.refreshState;
      if (state === "pending") setStatus(`刷新排队中 · 数据${fmtAge(age)}`, "");
      else if (state === "running") setStatus(`后台刷新中 · 数据${fmtAge(age)}`, "");
      else if (state === "error") setStatus(`缓存回退 · 数据${fmtAge(age)}`, "err");
      else setStatus(`本地已加载 · 数据${fmtAge(age)}`, "ok");
      if (state === "error" && (st?.lastError || data.cache?.lastError)) {
        err.hidden = false;
        err.textContent = `刷新失败，继续显示缓存：${st?.lastError || data.cache.lastError}`;
      }
    } catch (e) {
      err.hidden = false;
      err.textContent = `加载失败：${e.message || e}`;
      setStatus("失败", "err");
    }
  })();
  try {
    return await loadInFlight;
  } finally {
    loadInFlight = null;
  }
}

async function triggerRefresh() {
  const btn = document.getElementById("refreshBtn");
  btn.disabled = true;
  setStatus("已触发刷新", "");
  try {
    await fetch("/api/refresh", { cache: "no-store" });
    const started = Date.now();
    while (Date.now() - started < 180000) {
      await new Promise((r) => setTimeout(r, 800));
      const st = await fetchStatus();
      if (!st) continue;
      if (!st.refreshing) {
        await loadUsage();
        if (st.lastError) {
          document.getElementById("error").hidden = false;
          document.getElementById("error").textContent = `刷新完成但有错误：${st.lastError}`;
          setStatus("有错误", "err");
        }
        return;
      }
      setStatus(st.refreshState === "pending" ? "刷新排队中" : "后台刷新中", "");
    }
    setStatus("刷新超时", "err");
  } catch {
    setStatus("刷新失败", "err");
  } finally {
    btn.disabled = false;
  }
}

function schedule() {
  if (timer) clearInterval(timer);
  const poll = Math.max(5, Math.min(Number(uiPollSeconds || 15), Number(refreshSeconds) || 60));
  timer = setInterval(loadUsage, poll * 1000);
}

function showView(name) {
  const views = ["home", "ondemand", "included", "daily", "models", "settings"];
  const target = views.includes(name) ? name : "home";
  currentView = target;
  views.forEach((v) => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.hidden = v !== target;
  });
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-view") === target);
  });
  const refreshBtn = document.getElementById("refreshBtn");
  if (refreshBtn) refreshBtn.hidden = false;
  if (target === "settings") loadSettingsForm();
  if (!fullData || target === "settings") return;
  try {
    const alreadyRendered = pageFingerprints.has(target);
    renderCurrentPage(fullData);
    if (alreadyRendered) replayChartMotion(target);
  } catch (_) {}
}

async function loadSettingsForm() {
  const msg = document.getElementById("settingsMsg");
  msg.textContent = "";
  try {
    const s = await fetch("/api/settings", { cache: "no-store" }).then((r) => r.json());
    document.getElementById("setRefresh").value = Number(s.refreshSeconds || 60);
    document.getElementById("setPoll").value = Number(s.uiPollSeconds || 15);
    document.getElementById("setBall").checked = !!s.ballEnabled;
    document.getElementById("setDock").checked = !!s.dockEnabled;
    document.getElementById("setAutostart").checked = !!s.launchAtStartup;
    document.getElementById("setStartHidden").checked = s.startHidden !== false;
    document.getElementById("setBallSize").value = Number(s.ballSize || 120);
    document.getElementById("setBallOpacity").value = Number(s.ballOpacity || 100);
    document.getElementById("setBallRefresh").value = Number(s.ballRefreshMs || 4000);
    document.getElementById("setBallFont").value = Number(s.ballFontSize || 14);
    document.getElementById("setBallRing").value = Number(s.ballRingWidth || 7);
    document.getElementById("setDockWidth").value = Number(s.dockWidth || 290);
    document.getElementById("setDockCompact").checked = !!s.dockCompact;
    document.getElementById("setAuthSource").value = s.authSource === "manual" ? "manual" : "auto";
    document.getElementById("setEmail").value = s.manualEmail || "";
    document.getElementById("setSessionToken").value = "";
    document.getElementById("setRefreshToken").value = "";
    document.getElementById("setDataDir").textContent = s.dataDir || "—";
    const bits = [];
    if (s.hasManualCredentials) {
      bits.push(`已保存手动凭证 ${s.tokenPreview || ""}`);
      if (s.hasRefreshToken) bits.push("含 refresh");
      if (s.manualEmail) bits.push(s.manualEmail);
    } else {
      bits.push("尚未保存手动凭证");
    }
    bits.push(s.authSource === "manual" ? "当前优先手动" : "当前优先本机 Cursor");
    document.getElementById("authStatus").textContent = bits.join(" · ");
    await loadTaskbarHealth();
  } catch (e) {
    msg.textContent = `读取设置失败：${e.message || e}`;
  }
}

async function loadTaskbarHealth() {
  const status = document.getElementById("taskbarStatus");
  const reason = document.getElementById("taskbarReason");
  const dot = document.getElementById("taskbarStatusDot");
  if (!status || !reason || !dot) return;
  try {
    const data = await fetch("/api/health", { cache: "no-store" }).then((r) => r.json());
    const taskbar = data.components?.taskbarWidget || {};
    const state = taskbar.state || (document.getElementById("setDock").checked ? "waiting" : "stopped");
    const labels = {
      running: "已嵌入",
      starting: "正在启动",
      retrying: "等待 Explorer / 重试中",
      hidden: "等待可用空间",
      stopped: "已暂停",
      error: "组件异常",
      waiting: "等待 Explorer",
    };
    status.textContent = labels[state] || state;
    reason.textContent = taskbar.reason || (state === "stopped" ? "嵌入任务栏已关闭" : "等待状态更新");
    dot.className = `health-dot ${state === "running" ? "ok" : state === "error" ? "err" : "wait"}`;
  } catch (e) {
    status.textContent = "状态不可用";
    reason.textContent = e.message || String(e);
    dot.className = "health-dot err";
  }
}

async function saveSettings(extra = {}) {
  const msg = document.getElementById("settingsMsg");
  const btn = document.getElementById("saveSettingsBtn");
  btn.disabled = true;
  msg.textContent = "保存中…";
  try {
    const body = {
      refreshSeconds: Number(document.getElementById("setRefresh").value || 60),
      uiPollSeconds: Number(document.getElementById("setPoll").value || 15),
      ballEnabled: document.getElementById("setBall").checked,
      dockEnabled: document.getElementById("setDock").checked,
      launchAtStartup: document.getElementById("setAutostart").checked,
      startHidden: document.getElementById("setStartHidden").checked,
      ballSize: Number(document.getElementById("setBallSize").value || 120),
      ballOpacity: Number(document.getElementById("setBallOpacity").value || 100),
      ballRefreshMs: Number(document.getElementById("setBallRefresh").value || 4000),
      ballFontSize: Number(document.getElementById("setBallFont").value || 14),
      ballRingWidth: Number(document.getElementById("setBallRing").value || 7),
      dockWidth: Number(document.getElementById("setDockWidth").value || 290),
      dockCompact: document.getElementById("setDockCompact").checked,
      authSource: document.getElementById("setAuthSource").value,
      email: document.getElementById("setEmail").value.trim(),
      ...extra,
    };
    const sessionToken = document.getElementById("setSessionToken").value.trim();
    const refreshToken = document.getElementById("setRefreshToken").value.trim();
    if (sessionToken) body.sessionToken = sessionToken;
    if (refreshToken) body.refreshToken = refreshToken;

    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    refreshSeconds = Math.max(15, Number(data.settings.refreshSeconds || body.refreshSeconds));
    uiPollSeconds = Math.max(5, Number(data.settings.uiPollSeconds || body.uiPollSeconds));
    schedule();
    document.getElementById("setSessionToken").value = "";
    document.getElementById("setRefreshToken").value = "";
    await loadSettingsForm();
    msg.textContent = sessionToken
      ? "已保存凭证并开始刷新用量"
      : "已保存，组件 / 自启 / 刷新间隔已应用";
    if (sessionToken || extra.clearCredentials) {
      setTimeout(() => typeof loadUsage === "function" && loadUsage(), 1200);
    }
  } catch (e) {
    msg.textContent = `保存失败：${e.message || e}`;
  } finally {
    btn.disabled = false;
  }
}

function onSettingsApplied() {
  loadSettingsForm();
  schedule();
}

function wireNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.getAttribute("data-view")));
  });
  document.getElementById("saveSettingsBtn").addEventListener("click", () => saveSettings());
  document.getElementById("clearCredBtn").addEventListener("click", () => {
    if (!confirm("确定清除已保存的手动凭证，并改回本机 Cursor 登录？")) return;
    saveSettings({ clearCredentials: true, authSource: "auto" });
  });
  document.getElementById("resetPosBtn").addEventListener("click", async () => {
    const msg = document.getElementById("settingsMsg");
    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resetWidgetPositions: true }),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      msg.textContent = "已重置悬浮球位置";
    } catch (e) {
      msg.textContent = `重置失败：${e.message || e}`;
    }
  });
  document.getElementById("reembedDockBtn").addEventListener("click", async () => {
    const msg = document.getElementById("settingsMsg");
    try {
      const res = await fetch("/api/taskbar/reembed", { method: "POST" });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
      msg.textContent = "已请求重新嵌入任务栏";
      setTimeout(loadTaskbarHealth, 1200);
    } catch (e) {
      msg.textContent = `重新嵌入失败：${e.message || e}`;
    }
  });
  document.getElementById("exportDiagnosticsBtn").addEventListener("click", async () => {
    const msg = document.getElementById("settingsMsg");
    try {
      const res = await fetch("/api/diagnostics/export", { method: "POST" });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
      msg.textContent = `诊断包已导出：${data.path}`;
    } catch (e) {
      msg.textContent = `导出失败：${e.message || e}`;
    }
  });
}

function wireFilters() {
  const range = document.getElementById("rangeSelect");
  const from = document.getElementById("dateFrom");
  const to = document.getElementById("dateTo");
  const sync = () => {
    const custom = range.value === "custom";
    from.disabled = !custom;
    to.disabled = !custom;
    if (fullData && currentView === "daily") {
      pageFingerprints.delete("daily");
      renderCurrentPage(fullData);
    }
  };
  range.addEventListener("change", sync);
  from.addEventListener("change", sync);
  to.addEventListener("change", sync);
}

let uiPollSeconds = 15;

async function boot() {
  chartDefaults();
  try {
    const cfg = await fetch("/api/config").then((r) => r.json());
    refreshSeconds = Math.max(15, Number(cfg.refreshSeconds || 60));
    uiPollSeconds = Math.max(5, Number(cfg.uiPollSeconds || 15));
  } catch {
    refreshSeconds = 60;
    uiPollSeconds = 15;
  }
  document.getElementById("refreshBtn").addEventListener("click", triggerRefresh);
  wireFilters();
  wireNav();
  window.loadUsage = loadUsage;
  window.triggerRefresh = triggerRefresh;
  window.onSettingsApplied = onSettingsApplied;
  await loadUsage();
  schedule();
}

boot();
