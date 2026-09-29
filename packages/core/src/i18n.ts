/**
 * Two-language text helper. Each call site carries both strings, so a
 * translation always sits next to the original:  L("剩余", "left").
 * The language is process-wide; the dashboard re-renders after setLang().
 */
export type Lang = "zh" | "en";
export type LangPref = "auto" | Lang;

let current: Lang = "zh";
const listeners = new Set<(lang: Lang) => void>();

/** "auto" follows the given system / editor locale; anything not Chinese is English. */
export function resolveLang(pref: unknown, systemLocale?: string | null): Lang {
  if (pref === "zh" || pref === "en") return pref;
  const locale = String(systemLocale || "").toLowerCase();
  if (!locale) return "zh";
  return locale.startsWith("zh") ? "zh" : "en";
}

export function normalizeLangPref(pref: unknown): LangPref {
  return pref === "zh" || pref === "en" ? pref : "auto";
}

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  if (lang === current) return;
  current = lang;
  for (const fn of listeners) fn(lang);
}

export function onLangChange(fn: (lang: Lang) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function L(zh: string, en: string): string {
  return current === "en" ? en : zh;
}

/** English plural helper: plural(3, "request") -> "3 requests". */
export function plural(n: number, word: string, words = `${word}s`): string {
  return `${n} ${n === 1 ? word : words}`;
}
