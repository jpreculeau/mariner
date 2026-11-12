import { createContext, useContext } from "react";
import { remember, remembered } from "@/lib/storage";
import { en, type TextKey } from "./en";
import { fr } from "./fr";

export type { TextKey };
export type Lang = "en" | "fr";

/** The languages the page can be read in, each under its own name. */
export const languages: { id: Lang; name: string }[] = [
  { id: "en", name: "English" },
  { id: "fr", name: "Français" },
];

const texts: Record<Lang, Record<TextKey, string>> = { en, fr };
export const LANGUAGE_KEY = "mariner-language";

function known(tag: string | null | undefined): Lang | null {
  const primary = (tag || "").toLowerCase().split("-")[0];
  return languages.find((language) => language.id === primary)?.id ?? null;
}

/**
 * The language to start in: the one the reader chose, else the first of
 * the browser's that the page has, else English.
 */
export function detectLanguage(): Lang {
  const chosen = known(remembered(LANGUAGE_KEY));
  if (chosen) return chosen;
  const spoken =
    typeof navigator !== "undefined" ? navigator.languages || [] : [];
  for (const tag of spoken) {
    const language = known(tag);
    if (language) return language;
  }
  return "en";
}

/** A text in a language, its `{blanks}` filled from `values`. */
export function translate(
  lang: Lang,
  key: TextKey,
  values: Record<string, string | number> = {},
): string {
  return texts[lang][key].replace(/\{(\w+)\}/g, (blank, name) =>
    name in values ? String(values[name]) : blank,
  );
}

/** A number as the language writes it, with so many decimals. */
export function formatNumber(lang: Lang, value: number, digits = 0): string {
  return new Intl.NumberFormat(lang, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  }).format(value);
}

/** A percentage: "39.6%" in English, "39,6 %" in French. */
export function formatPercent(lang: Lang, value: number, digits = 0): string {
  const number = formatNumber(lang, value, digits);
  return lang === "fr" ? `${number}\u00a0%` : `${number}%`;
}

/**
 * A length of time, to the minute: "1h 33m" in English, "1 h 33 min" in
 * French, where "m" alone is read as metres.
 */
export function formatDuration(lang: Lang, seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (lang === "fr") {
    const min = `${minutes}\u00a0min`;
    return hours > 0 ? `${hours}\u00a0h\u00a0${min}` : min;
  }
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export type Translate = (
  key: TextKey,
  values?: Record<string, string | number>,
) => string;

export interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: Translate;
  /** Figures as the page's language writes them. */
  duration: (seconds: number) => string;
  percent: (value: number, digits?: number) => string;
  number: (value: number, digits?: number) => string;
}

/** What the page is given for a language. */
export function i18nFor(lang: Lang, setLang: (lang: Lang) => void): I18n {
  return {
    lang,
    setLang,
    t: (key, values) => translate(lang, key, values),
    duration: (seconds) => formatDuration(lang, seconds),
    percent: (value, digits) => formatPercent(lang, value, digits),
    number: (value, digits) => formatNumber(lang, value, digits),
  };
}

// Where no language was set up (a component shown alone), English.
export const I18nContext = createContext<I18n>(i18nFor("en", () => {}));

export function useI18n(): I18n {
  return useContext(I18nContext);
}
