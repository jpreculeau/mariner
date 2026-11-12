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

  it("says in the page's words what the server words for its log", () => {
    // In English too: "unexpected response: ''" is not for a reader.
    const silent = new ApiError(
      500,
      "The printer returned an unexpected response: ''",
      "printer_error",
    );
    expect(errorText(silent, t("en"), "en")).toBe(
      "The printer did not accept the command. Check that it is switched on and that its cable is plugged in.",
    );
    const broken = new ApiError(500, "KeyError: 'x'", "internal_error");
    expect(errorText(broken, t("en"), "en")).toBe(
      "Mariner ran into an error. Its log says more.",
    );
  });

  describe("a kind of file the printer does not take", () => {
    const refused = new ApiError(
      400,
      "This is not a file the printer can print. Mariner takes: .ctb, .fdg.",
      "type_not_supported",
    );
    const told = document.createElement("meta");
    told.name = "supported-extensions";

    it("lists the kinds it does take, in French too", () => {
      told.content = ".fdg,.ctb";
      document.head.appendChild(told);
      try {
        expect(errorText(refused, t("fr"), "fr")).toBe(
          "Ce n'est pas un fichier que l'imprimante sait imprimer. Mariner accepte\u00a0: .ctb, .fdg.",
        );
      } finally {
        told.remove();
      }
    });

    it("keeps to the server's words when the page was not told the kinds", () => {
      expect(errorText(refused, t("fr"), "fr")).toBe(refused.message);
    });
  });

  it("says how long to wait when it is one second", () => {
    const wait = new ApiError(
      429,
      "Too many wrong passwords. Try again in 1 second.",
      "too_many_attempts",
    );
    expect(errorText(wait, t("fr"), "fr")).toBe(
      "Trop de mots de passe erronés. Réessayez dans 1\u00a0s.",
    );
  });

  it("says how long to wait, in French too", () => {
    const wait = new ApiError(
      429,
      "Too many wrong passwords. Try again in 16 seconds.",
      "too_many_attempts",
    );
    expect(errorText(wait, t("fr"), "fr")).toBe(
      "Trop de mots de passe erronés. Réessayez dans 16\u00a0s.",
    );
  });
});
