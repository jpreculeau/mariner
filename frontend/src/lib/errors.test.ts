import { describe, it, expect } from "vitest";
import { ApiError } from "./api";
import { errorText } from "./errors";
import { translate, type Lang, type Translate } from "./i18n";

const t =
  (lang: Lang): Translate =>
  (key, values) =>
    translate(lang, key, values);

describe("errorText", () => {
  const refused = new ApiError(
    409,
    "model.ctb is being printed and was left untouched.",
    "print_in_progress",
  );

  it("gives the server's own words in English, which say more", () => {
    expect(errorText(refused, t("en"), "en")).toBe(
      "model.ctb is being printed and was left untouched.",
    );
  });

  it("says it in French by the code the server gave", () => {
    expect(errorText(refused, t("fr"), "fr")).toContain("imprime déjà");
  });

  it("falls back on the server's words for a code it has no French for", () => {
    const other = new ApiError(418, "I am a teapot.", "teapot");
    expect(errorText(other, t("fr"), "fr")).toBe("I am a teapot.");
  });

  it("names the status when the server explained nothing", () => {
    const bare = new ApiError(502, "API error: 502 Bad Gateway");
    expect(errorText(bare, t("en"), "en")).toBe(
      "Something went wrong (error 502).",
    );
    expect(errorText(bare, t("fr"), "fr")).toContain("erreur 502");
  });

  it("says that Mariner cannot be reached, in the reader's language", () => {
    const down = new ApiError(0, "Mariner cannot be reached.", "network");
    expect(errorText(down, t("en"), "en")).toContain("cannot be reached");
    expect(errorText(down, t("fr"), "fr")).toContain("injoignable");
    // Also for what a browser throws by itself.
    expect(
      errorText(new TypeError("Failed to fetch"), t("fr"), "fr"),
    ).toContain("injoignable");
  });

  it("makes something readable of anything else", () => {
    expect(errorText("boom", t("en"), "en")).toBe(
      "Something went wrong (error ?).",
    );
  });
});
