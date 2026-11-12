import { useState, useEffect } from "react";
import { Palette } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { themes, getStoredThemeId, applyTheme } from "@/lib/themes";
import { fonts, getStoredFontId, applyFont } from "@/lib/fonts";
import { cn } from "@/lib/utils";

export function ThemeSwitcher() {
  const [activeId, setActiveId] = useState(getStoredThemeId);

  const [fontId, setFontId] = useState(getStoredFontId);

  useEffect(() => {
    applyTheme(activeId);
  }, [activeId]);

  useEffect(() => {
    applyFont(fontId);
  }, [fontId]);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Appearance"
        >
          <Palette className="h-4 w-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2">
        <p className="mb-2 px-2 text-xs font-medium text-muted-foreground">
          Printer Theme
        </p>
        <div className="space-y-0.5">
          {themes.map((theme) => (
            <button
              key={theme.id}
              onClick={() => setActiveId(theme.id)}
              aria-pressed={activeId === theme.id}
              className={cn(
                "flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors",
                activeId === theme.id
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              <span
                className="h-3.5 w-3.5 rounded-full border border-border"
                style={{ backgroundColor: theme.accent }}
              />
              {theme.name}
            </button>
          ))}
        </div>
        <p className="mb-2 mt-3 px-2 text-xs font-medium text-muted-foreground">
          Typeface
        </p>
        <div className="space-y-0.5">
          {fonts.map((font) => (
            <button
              key={font.id}
              onClick={() => setFontId(font.id)}
              aria-pressed={fontId === font.id}
              // Shown in its own letters, whichever is in use.
              style={{ fontFamily: font.body }}
              className={cn(
                "flex w-full flex-col items-start rounded-md px-2 py-2 text-left text-sm transition-colors",
                fontId === font.id
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              {font.name}
              <span className="text-xs font-normal text-muted-foreground">
                {font.hint}
              </span>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
