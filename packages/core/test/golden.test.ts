import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { aggregateEventsByBucket, buildSummary, normalizeModels } from "../src/aggregate";
import { pyRound, pySum } from "../src/num";

// fixtures/golden.json: the expected outputs were produced by the original Python
// implementation (cursor_usage_app/usage.py, v1.1.0). Inputs come from one billing
// cycle, anonymized (timestamps shifted by whole days, costs and tokens scaled,
// plan and limits replaced) and reduced to the fields aggregation uses, plus
// synthetic edge-case events. Timezone: UTC+8.
const golden = JSON.parse(readFileSync(new URL("./fixtures/golden.json", import.meta.url), "utf8"));

describe("golden: TypeScript core matches the Python implementation", () => {
  it("aggregates events identically", () => {
    expect(aggregateEventsByBucket(golden.events)).toEqual(golden.aggregation);
  });

  it("builds the summary identically", () => {
    const agg = aggregateEventsByBucket(golden.events);
    expect(buildSummary(golden.period, golden.plan, agg, agg.models)).toEqual(golden.summary);
    expect(buildSummary(golden.period, golden.plan, null, [])).toEqual(golden.summaryWithoutEvents);
  });

  it("normalizes legacy model aggregation identically", () => {
    expect(normalizeModels(golden.legacyAggregation)).toEqual(golden.legacyModels);
  });
});

describe("python numeric semantics", () => {
  it("round() is half-to-even on the exact binary value", () => {
    expect(pyRound(0.125, 2)).toBe(0.12);
    expect(pyRound(0.375, 2)).toBe(0.38);
    expect(pyRound(2.675, 2)).toBe(2.67); // 2.675 is really 2.67499999...
    expect(pyRound(-0.125, 2)).toBe(-0.12);
    expect(pyRound(1234.56789, 4)).toBe(1234.5679);
  });

  it("sum() uses compensated summation", () => {
    expect(pySum([0.1, 0.2, 0.3])).toBe(0.6);
    expect(pySum([1e100, 1.0, -1e100, 1.0])).toBe(2.0);
  });
});
