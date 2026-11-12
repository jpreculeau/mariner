import { remember, remembered } from "@/lib/storage";

export interface PrinterTheme {
  id: string;
  name: string;
  accent: string; // preview swatch color (hex)
  vars: {
    primary: string;
    "primary-foreground": string;
    accent: string;
    "accent-foreground": string;
    ring: string;
    "sidebar-primary": string;
    "sidebar-ring": string;
  };
}

export const themes: PrinterTheme[] = [
  {
    id: "default",
    name: "ChiTu Cyan",
    accent: "#1ab5a0",
    vars: {
      primary: "175 70% 45%",
      "primary-foreground": "220 20% 6%",
      accent: "175 70% 45%",
      "accent-foreground": "220 20% 6%",
      ring: "175 70% 45%",
      "sidebar-primary": "175 70% 45%",
      "sidebar-ring": "175 70% 45%",
    },
  },
  {
    id: "mars",
    name: "Elegoo Mars",
    accent: "#dc2626",
    vars: {
      // Lighter than the red of the swatch: as text on the page's dark
      // grounds that red could not be read.
      primary: "0 80% 66%",
      "primary-foreground": "0 0% 7%",
      accent: "0 80% 66%",
      "accent-foreground": "0 0% 7%",
      ring: "0 80% 66%",
      "sidebar-primary": "0 80% 66%",
      "sidebar-ring": "0 80% 66%",
    },
  },
  {
    id: "saturn",
    name: "Elegoo Saturn",
    accent: "#eab308",
    vars: {
      primary: "48 96% 53%",
      "primary-foreground": "48 96% 8%",
      accent: "48 96% 53%",
      "accent-foreground": "48 96% 8%",
      ring: "48 96% 53%",
      "sidebar-primary": "48 96% 53%",
      "sidebar-ring": "48 96% 53%",
    },
  },
  {
    id: "photon",
    name: "Anycubic Photon",
    accent: "#22c55e",
    vars: {
      primary: "142 71% 45%",
      "primary-foreground": "142 71% 6%",
      accent: "142 71% 45%",
      "accent-foreground": "142 71% 6%",
      ring: "142 71% 45%",
      "sidebar-primary": "142 71% 45%",
      "sidebar-ring": "142 71% 45%",
    },
  },
];

const THEME_KEY = "mariner-theme";

export function getStoredThemeId(): string {
  return remembered(THEME_KEY) || "default";
}

export function applyTheme(themeId: string) {
  const theme = themes.find((t) => t.id === themeId) || themes[0];
  // On the document itself: dialogs and menus are drawn at its root,
  // outside the page's frame.
  const style = document.documentElement.style;
  Object.entries(theme.vars).forEach(([key, value]) => {
    style.setProperty(`--${key}`, value);
  });
  remember(THEME_KEY, theme.id);
}
