import { ApiError } from "@/lib/api";
import { en } from "@/lib/i18n/en";
import type { Lang, TextKey, Translate } from "@/lib/i18n";
import { supportedKinds } from "@/lib/kinds";

// What the server words for its log rather than for a reader: the page's
// own text is shown in every language.
const NOT_WORDED_FOR_READERS = new Set(["printer_error", "internal_error"]);

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
    if (!key) return error.message;
    if (NOT_WORDED_FOR_READERS.has(error.code)) return t(key);
    if (lang === "en") return error.message;
    if (error.code === "too_many_attempts") {
      // How long, which the server's words say.
      const seconds = /(\d+) seconds/.exec(error.message)?.[1];
      return seconds ? t(key, { seconds }) : error.message;
    }
    if (error.code === "type_not_supported") {
      // The kinds that are taken, which the server's words list.
      const kinds = supportedKinds();
      return kinds.length ? t(key, { kinds: kinds.join(", ") }) : error.message;
    }
    return t(key);
  }
  if (error instanceof TypeError) {
    // What a browser throws when nothing answered.
    return t("error.network");
  }
  return t("error.unknown", { status: "?" });
}
