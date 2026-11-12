import { remember, remembered } from "@/lib/storage";

/**
 * The typefaces the page can be read in. All are free (SIL Open Font
 * License) and served with the page: nothing is fetched from another site.
 */
export interface ReadingFont {
  id: string;
  name: string;
  body: string;
  display: string;
  mono: string;
}

const HYPERLEGIBLE =
  '"Atkinson Hyperlegible Next Variable", system-ui, sans-serif';
// Figures and file names: every character the same width, and 0 O, 1 l I
// drawn apart.
const MONO = '"Atkinson Hyperlegible Mono Variable", ui-monospace, monospace';
const OPENDYSLEXIC = `"OpenDyslexic", ${HYPERLEGIBLE}`;

export const fonts: ReadingFont[] = [
  {
    id: "hyperlegible",
    name: "Atkinson Hyperlegible",
    // Drawn by the Braille Institute so that letters and digits that look
    // alike (b d p q, I l 1, O 0) cannot be taken for one another.
    body: HYPERLEGIBLE,
    display: HYPERLEGIBLE,
    mono: MONO,
  },
  {
    id: "opendyslexic",
    name: "OpenDyslexic",
    // Heavy at the foot of each letter, which some dyslexic readers find
    // keeps letters from turning and swapping.
    body: OPENDYSLEXIC,
    display: OPENDYSLEXIC,
    mono: MONO,
  },
];

const FONT_KEY = "mariner-font";

function fontOf(id: string | null): ReadingFont {
  return fonts.find((font) => font.id === id) || fonts[0];
}

export function getStoredFontId(): string {
  return fontOf(remembered(FONT_KEY)).id;
}

export function applyFont(fontId: string) {
  const font = fontOf(fontId);
  const style = document.documentElement.style;
  style.setProperty("--font-body", font.body);
  style.setProperty("--font-display", font.display);
  style.setProperty("--font-mono", font.mono);
  remember(FONT_KEY, font.id);
}
