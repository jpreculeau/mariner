import { ApiError } from "@/lib/api";
import { en } from "@/lib/i18n/en";
import type { Lang, TextKey, Translate } from "@/lib/i18n";

function textFor(code: string | undefined): TextKey | null {
  const key = `error.${code}`;
  return code && key in en ? (key as TextKey) : null;
}

/**
 * What went wrong, in words for the reader and in their language.
 *
 * The server explains its refusals in English, with a code. In English
 * its own words are shown: they say more (the name of the file, how much
 * room there is). In another language the code picks the text; a code the
 * page has no text for is shown in the server's words rather than not at
 * all.
 */
export function errorText(error: unknown, t: Translate, lang: Lang): string {
  if (error instanceof ApiError) {
    if (error.code === "network") return t("error.network");
    if (!error.code) return t("error.unknown", { status: error.status });
    const key = textFor(error.code);
    return lang !== "en" && key ? t(key) : error.message;
  }
  if (error instanceof TypeError) {
    // What a browser throws when nothing answered.
    return t("error.network");
  }
  return t("error.unknown", { status: "?" });
}
