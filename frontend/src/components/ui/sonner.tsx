import { useEffect, useState } from "react";
import { Toaster as Sonner, toast as sonner } from "sonner";
import { translate, useI18n, type Lang } from "@/lib/i18n";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const NARROW = "(max-width: 640px)";

/** Whether the screen is as narrow as a phone's. */
function useNarrowScreen(): boolean {
  const query = () =>
    typeof window.matchMedia === "function" ? window.matchMedia(NARROW) : null;
  const [narrow, setNarrow] = useState(() => query()?.matches ?? false);
  useEffect(() => {
    const media = query();
    if (!media) return;
    const follow = () => setNarrow(media.matches);
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);
  return narrow;
}

const Toaster = ({ ...props }: ToasterProps) => {
  const { t } = useI18n();
  const narrow = useNarrowScreen();
  return (
    <Sonner
      theme="dark"
      // On a phone the bottom is where the buttons are: a message there
      // sat on the very button it was about.
      position={narrow ? "top-center" : "bottom-right"}
      // Above a dialog, which takes the page out of reach of the pointer:
      // what a toast says must still be dismissable.
      className="toaster group pointer-events-auto"
      containerAriaLabel={t("toasts.region")}
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg focus-visible:ring-2 focus-visible:ring-ring",
          description: "group-[.toast]:text-muted-foreground",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-foreground",
        },
      }}
      {...props}
    />
  );
};

/** The language the page is shown in, as it tells the browser. */
function pageLanguage(): Lang {
  return document.documentElement.lang === "fr" ? "fr" : "en";
}

/**
 * Messages about what was just done.
 *
 * A success passes by itself. An error stays until the reader closes it:
 * a refusal and what to do about it take longer to read than a message
 * stays, and it cannot be asked for again.
 */
const toast = {
  success: (message: string) => sonner.success(message),
  error: (message: string) =>
    sonner.error(message, {
      duration: Infinity,
      cancel: {
        label: translate(pageLanguage(), "common.close"),
        onClick: () => {},
      },
    }),
};

export { Toaster, toast };
