/**
 * Number coercions that mirror the original Python implementation exactly
 * (float()/int() semantics and round-half-even on the exact binary value), so
 * aggregated totals stay bit-identical with previously stored reports.
 */

const INT_LITERAL = /^\s*[+-]?\d+(_\d+)*\s*$/;
const FLOAT_LITERAL = /^\s*[+-]?(\d+(_\d+)*\.?(\d+(_\d+)*)?|\.\d+(_\d+)*)([eE][+-]?\d+)?\s*$/;
const SPECIAL_FLOAT = /^\s*[+-]?(inf|infinity|nan)\s*$/i;

/** Python float(value); throws for values float() would reject. */
export function pyFloat(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "string") {
    if (FLOAT_LITERAL.test(value)) return Number(value.replace(/_/g, ""));
    if (SPECIAL_FLOAT.test(value)) {
      const v = value.trim().toLowerCase().replace(/^\+/, "");
      if (v.endsWith("nan")) return Number.NaN;
      return v.startsWith("-") ? -Infinity : Infinity;
    }
  }
  throw new TypeError(`could not convert to float: ${String(value)}`);
}

/** Python int(value); throws for values int() would reject. */
export function pyInt(value: unknown): number {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("cannot convert non-finite float to int");
    return Math.trunc(value);
  }
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "string" && INT_LITERAL.test(value)) return Number(value.replace(/_/g, ""));
  throw new TypeError(`invalid literal for int(): ${String(value)}`);
}

export function asFloat(n: unknown, fallback = 0): number {
  if (n === null || n === undefined || n === "") return fallback;
  try {
    return pyFloat(n);
  } catch {
    return fallback;
  }
}

export function asInt(n: unknown, fallback = 0): number {
  if (n === null || n === undefined || n === "") return fallback;
  try {
    return pyInt(pyFloat(n));
  } catch {
    return fallback;
  }
}

/** Python truthiness for the values that appear in API payloads. */
export function truthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false || value === 0 || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  if (typeof value === "number" && Number.isNaN(value)) return true;
  return true;
}

function exactParts(x: number): { mantissa: bigint; exponent: number } {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const bits = view.getBigUint64(0);
  const rawExp = Number((bits >> 52n) & 0x7ffn);
  let mantissa = bits & 0xfffffffffffffn;
  let exponent: number;
  if (rawExp === 0) {
    exponent = -1074;
  } else {
    mantissa |= 1n << 52n;
    exponent = rawExp - 1075;
  }
  return { mantissa, exponent };
}

/** Python round(x, ndigits): exact half-to-even rounding of the binary value. */
export function pyRound(x: number, ndigits: number): number {
  if (!Number.isFinite(x) || x === 0) return x;
  const negative = x < 0;
  const { mantissa, exponent } = exactParts(Math.abs(x));
  // value = mantissa * 2^exponent; scaled = value * 10^ndigits as a fraction num/den.
  let num = mantissa * 10n ** BigInt(Math.max(0, ndigits));
  let den = 1n;
  if (ndigits < 0) den *= 10n ** BigInt(-ndigits);
  if (exponent >= 0) num <<= BigInt(exponent);
  else den <<= BigInt(-exponent);
  let q = num / den;
  const r = num % den;
  const twice = r * 2n;
  if (twice > den || (twice === den && q % 2n === 1n)) q += 1n;
  const result = ndigits >= 0 ? Number(q) / 10 ** ndigits : Number(q) * 10 ** -ndigits;
  return negative ? -result : result;
}

export function dollarsFromCents(n: unknown): number {
  return pyRound(asFloat(n) / 100.0, 2);
}

/**
 * CPython 3.12+ sum() over floats: Neumaier compensated summation. Plain
 * `+=` accumulation elsewhere in the port mirrors explicit `+=` in Python.
 */
export function pySum(values: Iterable<number>): number {
  let total = 0;
  let c = 0;
  for (const x of values) {
    const t = total + x;
    if (Math.abs(total) >= Math.abs(x)) c += total - t + x;
    else c += x - t + total;
    total = t;
  }
  if (c && Number.isFinite(c)) total += c;
  return total;
}
