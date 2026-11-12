import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { themes } from "./themes";

type Hsl = [number, number, number];

/** The colours of the page as shown (always the dark set). */
function pageColours(): Record<string, Hsl> {
  const css = readFileSync(resolve(__dirname, "../index.css"), "utf-8");
  const dark = css.slice(css.indexOf(".dark {"));
  const block = dark.slice(0, dark.indexOf("}"));
  const colours: Record<string, Hsl> = {};
  for (const [, name, h, s, l] of block.matchAll(
    /--([\w-]+):\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%/g,
  )) {
    colours[name] = [Number(h), Number(s), Number(l)];
  }
  return colours;
}

const parse = (value: string): Hsl => {
  const [h, s, l] = value.replace(/%/g, "").split(/\s+/).map(Number);
  return [h, s, l];
};

function luminance([h, s, l]: Hsl): number {
  const sat = s / 100;
  const light = l / 100;
  const a = sat * Math.min(light, 1 - light);
  const channel = (n: number) => {
    const k = (n + h / 30) % 12;
    const value = light - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(8) + 0.0722 * channel(4);
}

/** How far apart two colours are, as WCAG measures it: 1 to 21. */
function contrast(one: Hsl, other: Hsl): number {
  const [light, dark] = [luminance(one), luminance(other)].sort(
    (a, b) => b - a,
  );
  return (light + 0.05) / (dark + 0.05);
}

describe("colours", () => {
  const c = pageColours();
  const grounds = ["background", "card", "muted"] as const;

  it("measures as the standard does", () => {
    expect(contrast([0, 0, 100], [0, 0, 0])).toBeCloseTo(21, 1);
    expect(contrast([0, 0, 50], [0, 0, 50])).toBe(1);
  });

  it.each(["foreground", "muted-foreground", "danger", "success", "warning"])(
    "sets text in %s apart from every ground it is read on",
    (text) => {
      for (const ground of grounds) {
        expect(
          contrast(c[text], c[ground]),
          `${text} on ${ground}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    },
  );

  it("sets the words of a red button apart from its red", () => {
    expect(
      contrast(c["destructive-foreground"], c.destructive),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("draws the edge of a field where it can be seen", () => {
    for (const ground of ["background", "card"] as const) {
      expect(
        contrast(c.input, c[ground]),
        `field edge on ${ground}`,
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it.each(themes.map((theme) => [theme.name, theme] as const))(
    "keeps the %s theme readable",
    (_name, theme) => {
      const primary = parse(theme.vars.primary);
      // As text and icons on the page's grounds.
      for (const ground of grounds) {
        expect(
          contrast(primary, c[ground]),
          `accent on ${ground}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      // And under the words of a button filled with it.
      expect(
        contrast(parse(theme.vars["primary-foreground"]), primary),
      ).toBeGreaterThanOrEqual(4.5);
    },
  );
});

describe("the dark set of colours", () => {
  it("is the whole page's, dialogs and menus included", () => {
    // Those are drawn outside the page's frame, at the root of the
    // document: set on the frame alone, the dark colours left them light.
    const html = readFileSync(resolve(__dirname, "../../index.html"), "utf-8");
    expect(html).toMatch(/<html[^>]*\bclass="dark"/);
  });
});

describe("movement", () => {
  it("stops what moves without end for a reader who asked for stillness", () => {
    const css = readFileSync(resolve(__dirname, "../index.css"), "utf-8");
    const still = css.slice(css.indexOf("prefers-reduced-motion: reduce"));
    expect(still).toMatch(/animation-iteration-count:\s*1\s*!important/);
    expect(still).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
  });
});
