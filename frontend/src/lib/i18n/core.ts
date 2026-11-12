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

export type Translate = (
  key: TextKey,
  values?: Record<string, string | number>,
) => string;

export interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: Translate;
}

// Where no language was set up (a component shown alone), English.
export const I18nContext = createContext<I18n>({
  lang: "en",
  setLang: () => {},
  t: (key, values) => translate("en", key, values),
});

export function useI18n(): I18n {
  return useContext(I18nContext);
}
