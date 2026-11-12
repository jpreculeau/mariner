import { useEffect, useId, useState, type ReactNode } from "react";
import { Check, Palette } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { themes, getStoredThemeId, applyTheme } from "@/lib/themes";
import { fonts, getStoredFontId, applyFont } from "@/lib/fonts";
import { languages, useI18n, type TextKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** A set of choices of which one is made, under its heading. */
function Choices({
  heading,
  children,
}: {
  heading: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="mt-3 first:mt-0">
      <p
        id={id}
        className="mb-2 px-2 text-xs font-medium text-muted-foreground"
      >
        {heading}
      </p>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

/** One choice. The one made is marked: not told by a shade alone. */
function Choice({
  chosen,
  onChoose,
  children,
  className,
  ...rest
}: {
  chosen: boolean;
  onChoose: () => void;
  children: ReactNode;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick">) {
  return (
    <button
      onClick={onChoose}
      aria-pressed={chosen}
      className={cn(
        "flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm transition-colors",
        chosen
          ? "bg-muted font-medium text-foreground"
          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
        className,
      )}
      {...rest}
    >
      <span className="flex min-w-0 flex-1 items-center gap-3">{children}</span>
      {chosen && (
        <Check
          className="h-4 w-4 shrink-0 text-primary"
          aria-hidden
          data-chosen
        />
      )}
    </button>
  );
}

export function ThemeSwitcher() {
  const [activeId, setActiveId] = useState(getStoredThemeId);
  const [fontId, setFontId] = useState(getStoredFontId);
  const { t, lang, setLang } = useI18n();

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
          aria-label={t("appearance.open")}
        >
          <Palette className="h-4 w-4" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        aria-label={t("appearance.open")}
        className="w-64 p-2"
      >
        <Choices heading={t("appearance.theme")}>
          {themes.map((theme) => (
            <Choice
              key={theme.id}
              chosen={activeId === theme.id}
              onChoose={() => setActiveId(theme.id)}
            >
              <span
                className="h-3.5 w-3.5 shrink-0 rounded-full border border-border"
                style={{ backgroundColor: theme.accent }}
                aria-hidden
              />
              {theme.name}
            </Choice>
          ))}
        </Choices>
        <Choices heading={t("appearance.typeface")}>
          {fonts.map((font) => (
            <Choice
              key={font.id}
              chosen={fontId === font.id}
              onChoose={() => setFontId(font.id)}
              // Shown in its own letters, whichever is in use.
              style={{ fontFamily: font.body }}
            >
              <span className="flex flex-col">
                {font.name}
                <span className="text-xs font-normal leading-relaxed text-muted-foreground">
                  {t(`font.${font.id}.hint` as TextKey)}
                </span>
              </span>
            </Choice>
          ))}
        </Choices>
        <Choices heading={t("appearance.language")}>
          {languages.map((language) => (
            <Choice
              key={language.id}
              chosen={lang === language.id}
              onChoose={() => setLang(language.id)}
              // Each under its own name, read aloud in its own voice.
              lang={language.id}
            >
              {language.name}
            </Choice>
          ))}
        </Choices>
      </PopoverContent>
    </Popover>
  );
}
