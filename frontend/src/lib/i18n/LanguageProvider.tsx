import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { remember } from "@/lib/storage";
import {
  I18nContext,
  LANGUAGE_KEY,
  detectLanguage,
  i18nFor,
  type I18n,
  type Lang,
} from "./core";

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLanguage);

  // Screen readers pick their voice, and browsers their hyphenation, from
  // the language the page says it is in.
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    remember(LANGUAGE_KEY, next);
    setLangState(next);
  }, []);

  const value = useMemo<I18n>(() => i18nFor(lang, setLang), [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
