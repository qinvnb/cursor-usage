// Run: node tests/web/daily.test.cjs   (set TZ=Asia/Shanghai to exercise UTC+8)
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const elements = { rangeSelect: { value: "7" }, dateFrom: { value: "" }, dateTo: { value: "" } };
const sandbox = {
  console,
  Date,
  Math,
  Number,
  String,
  JSON,
  Map,
  WeakMap,
  Promise,
  setTimeout,
  clearTimeout,
  setInterval: () => 0,
  clearInterval: () => {},
  requestAnimationFrame: () => 0,
  localStorage: { getItem: () => null, setItem: () => {} },
  location: { hash: "" },
  matchMedia: () => ({ matches: false, addEventListener: () => {} }),
  getComputedStyle: () => ({ getPropertyValue: () => "" }),
  fetch: () => new Promise(() => {}),
  document: {
    hidden: false,
    getElementById: (id) => elements[id] || null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    documentElement: { dataset: {} },
  },
  window: {},
  Chart: { defaults: { animation: {}, interaction: {}, plugins: { tooltip: {}, legend: { labels: {} } }, scale: { grid: {} } } },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(`${source}\n;globalThis.__t = { completeDaily, filteredDaily, localDateKey, buildSeries, escapeHtml };`, sandbox);
const t = sandbox.__t;

function day(offset) {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  d.setDate(d.getDate() + offset);
  return d;
}

// localDateKey never shifts across the UTC boundary.
const midnight = new Date(2026, 8, 28, 0, 30);
assert.strictEqual(t.localDateKey(midnight), "2026-09-28");

const cycleStart = day(-20);
cycleStart.setHours(0, 0, 0, 0);
const data = {
  summary: { billingCycleStart: String(cycleStart.getTime()), billingCycleEnd: String(day(10).getTime()) },
  daily: [
    { date: t.localDateKey(day(-15)), onDemandCostCents: 100, includedCostCents: 0, eventCount: 1 },
    { date: t.localDateKey(day(-2)), onDemandCostCents: 50, includedCostCents: 25, eventCount: 2 },
  ],
};

const full = t.completeDaily(data);
assert.strictEqual(full.length, 21, "cycle start .. today inclusive");
assert.strictEqual(full[0].date, t.localDateKey(cycleStart));
assert.strictEqual(full[full.length - 1].date, t.localDateKey(day(0)));
assert.strictEqual(full.filter((r) => r.eventCount > 0).length, 2);

elements.rangeSelect.value = "7";
const last7 = t.filteredDaily(data);
assert.strictEqual(last7.length, 7, "range 7 must contain exactly 7 calendar days");
assert.strictEqual(last7[0].date, t.localDateKey(day(-6)));

const series = t.buildSeries(data);
assert.strictEqual(series.last7.length, 7);
assert.strictEqual(series.last7Sum, 75);

assert.strictEqual(t.escapeHtml('<img src=x onerror="a">'), "&lt;img src=x onerror=&quot;a&quot;&gt;");

console.log("daily.test.cjs: all assertions passed");
