import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  LanguageProvider,
  detectLanguage,
  translate,
  useI18n,
  languages,
} from "./index";
import { en } from "./en";
import { fr } from "./fr";

function browserSpeaks(...tags: string[]) {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(tags);
}

function Sample() {
  const { t, lang, setLang } = useI18n();
  return (
    <div>
      <p>{t("nav.files")}</p>
      <p>{lang}</p>
      <button onClick={() => setLang("fr")}>fr</button>
      <button onClick={() => setLang("en")}>en</button>
    </div>
  );
}

describe("languages", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.lang = "en";
  });
  afterEach(() => vi.restoreAllMocks());

  it("offers English and French", () => {
    expect(languages.map((language) => language.id)).toEqual(["en", "fr"]);
    // Each under its own name, whatever the page is read in.
    expect(languages.map((language) => language.name)).toEqual([
      "English",
      "Français",
    ]);
  });

  it("starts in the first language of the browser that the page has", () => {
    browserSpeaks("fr-FR", "en");
    expect(detectLanguage()).toBe("fr");
    browserSpeaks("de-DE", "fr-CA", "en");
    expect(detectLanguage()).toBe("fr");
    browserSpeaks("de-DE", "en-GB", "fr");
    expect(detectLanguage()).toBe("en");
    browserSpeaks("ja");
    expect(detectLanguage()).toBe("en");
    browserSpeaks();
    expect(detectLanguage()).toBe("en");
  });

  it("keeps to the language the reader chose", () => {
    browserSpeaks("fr-FR");
    localStorage.setItem("mariner-language", "en");
    expect(detectLanguage()).toBe("en");
    // Not to one the page does not have.
    localStorage.setItem("mariner-language", "tlh");
    expect(detectLanguage()).toBe("fr");
  });

  it("works in a browser that keeps nothing", () => {
    browserSpeaks("fr");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(detectLanguage()).toBe("fr");
  });

  it("says every English text in French too, with the same blanks", () => {
    const blanks = (text: string) => (text.match(/\{\w+\}/g) || []).sort();
    expect(Object.keys(fr).sort()).toEqual(Object.keys(en).sort());
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(fr[key].trim(), key).not.toBe("");
      expect(blanks(fr[key]), key).toEqual(blanks(en[key]));
    }
  });

  it("fills the blanks of a text", () => {
    expect(translate("fr", "files.newFolder.in", { path: "/a" })).toContain(
      "/a",
    );
    // A blank left unfilled shows, rather than a word going missing.
    expect(translate("en", "files.newFolder.in")).toContain("{path}");
  });

  it("writes French as French is written", () => {
    // A space before ? ! : ; that does not break, and « » for quotes.
    for (const [key, text] of Object.entries(fr)) {
      expect(text, key).not.toMatch(/[^\s\u00a0\u202f][?!;]/);
      expect(text, key).not.toMatch(/ [?!:;]/);
      expect(text, key).not.toMatch(/\.\.\./);
    }
  });

  it("shows the page in the chosen language and tells the browser which", () => {
    browserSpeaks("en-US");
    render(
      <LanguageProvider>
        <Sample />
      </LanguageProvider>,
    );
    expect(screen.getByText("Files")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");

    fireEvent.click(screen.getByText("fr"));

    expect(screen.getByText("Fichiers")).toBeInTheDocument();
    // Read aloud with the right voice, hyphenated by the right rules.
    expect(document.documentElement.lang).toBe("fr");
    expect(localStorage.getItem("mariner-language")).toBe("fr");
  });

  it("reads in English where no language was set up", () => {
    render(<Sample />);
    expect(screen.getByText("Files")).toBeInTheDocument();
  });
});
