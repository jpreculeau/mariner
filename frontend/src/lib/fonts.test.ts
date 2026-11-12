import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fonts, applyFont, getStoredFontId } from "./fonts";

const root = () => document.documentElement.style;

describe("fonts", () => {
  beforeEach(() => {
    localStorage.clear();
    root().cssText = "";
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("offers a typeface drawn to be told apart, and one for dyslexic readers", () => {
    expect(fonts.map((font) => font.id)).toEqual([
      "hyperlegible",
      "opendyslexic",
    ]);
  });

  it("starts with the first when nothing was chosen", () => {
    expect(getStoredFontId()).toBe("hyperlegible");
  });

  it("applies the chosen typeface to text and headings, and remembers it", () => {
    applyFont("opendyslexic");
    expect(root().getPropertyValue("--font-body")).toContain("OpenDyslexic");
    expect(root().getPropertyValue("--font-display")).toContain("OpenDyslexic");
    // Figures stay in the fixed-width face, whose digits line up.
    expect(root().getPropertyValue("--font-mono")).toContain(
      "Atkinson Hyperlegible Mono",
    );
    expect(getStoredFontId()).toBe("opendyslexic");

    applyFont("hyperlegible");
    expect(root().getPropertyValue("--font-body")).toContain(
      "Atkinson Hyperlegible Next",
    );
    expect(getStoredFontId()).toBe("hyperlegible");
  });

  it("falls back on the system's own typeface, never on one fetched elsewhere", () => {
    for (const font of fonts) {
      for (const stack of [font.body, font.display, font.mono]) {
        expect(stack).toMatch(/(sans-serif|monospace)$/);
      }
    }
  });

  it("takes an unknown choice for the first", () => {
    localStorage.setItem("mariner-font", "comic");
    expect(getStoredFontId()).toBe("hyperlegible");
    applyFont("comic");
    expect(root().getPropertyValue("--font-body")).toContain(
      "Atkinson Hyperlegible Next",
    );
  });

  it("works in a browser that keeps nothing", () => {
    // Storage switched off: reading or writing it throws.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(getStoredFontId()).toBe("hyperlegible");
    expect(() => applyFont("opendyslexic")).not.toThrow();
    expect(root().getPropertyValue("--font-body")).toContain("OpenDyslexic");
  });
});

describe("the page's own files", () => {
  const read = (path: string) =>
    readFileSync(resolve(__dirname, "../..", path), "utf-8");

  it("fetches nothing from another site: styles, typefaces, scripts", () => {
    // What the page loads from elsewhere tells that site who opens the
    // printer's page, and fails where there is no way out to the internet.
    for (const file of ["src/index.css", "index.html", "src/main.tsx"]) {
      expect(read(file)).not.toMatch(/https?:\/\/(?!www\.w3\.org)/);
    }
  });

  it("carries its typefaces with it", () => {
    const entry = read("src/main.tsx");
    for (const packaged of [
      "@fontsource-variable/atkinson-hyperlegible-next",
      "@fontsource-variable/atkinson-hyperlegible-mono",
      "@fontsource/opendyslexic",
    ]) {
      expect(entry).toContain(packaged);
    }
  });

  it("ships the licence each typeface is given under", () => {
    for (const licence of [
      "atkinson-hyperlegible-next",
      "atkinson-hyperlegible-mono",
      "opendyslexic",
    ]) {
      expect(read(`public/licenses/${licence}-OFL.txt`)).toContain(
        "SIL OPEN FONT LICENSE Version 1.1",
      );
    }
  });
});
