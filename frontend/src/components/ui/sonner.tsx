import { useEffect, useState } from "react";
import { Toaster as Sonner, toast as sonner } from "sonner";
import { translate, useI18n, type Lang } from "@/lib/i18n";

type ToasterProps = React.ComponentProps<typeof Sonner>;

// What last had focus outside the messages: where focus goes back when
// the last of them is closed from within. A browser says nothing when
// the button pressed goes with its message, and leaves focus on the page
// as a whole.
let lastOutside: Element | null = null;

function noteFocus(event: FocusEvent) {
  const on = event.target;
  if (on instanceof Element && !on.closest("[data-sonner-toaster]")) {
    lastOutside = on;
  }
}

/** The reader put focus nowhere: there is then no place to go back to. */
function forgetFocus(event: FocusEvent) {
  if (event.relatedTarget) return;
  const was = event.target;
  // A moment later, when it can be told from what had focus being taken
  // away: it is then still there.
  setTimeout(() => {
    const nowhere =
      !document.activeElement || document.activeElement === document.body;
    if (lastOutside === was && was instanceof Element && was.isConnected) {
      if (nowhere) lastOutside = null;
    }
  });
}

function focusBackOutside() {
  const content = () => document.getElementById("content");
  const back =
    lastOutside instanceof HTMLElement && lastOutside.isConnected
      ? lastOutside
      : content();
  back?.focus();
  // What focus went back to can go in its turn: the button of a menu
  // that the same press closed.
  setTimeout(() => {
    const nowhere =
      !document.activeElement || document.activeElement === document.body;
    const messages = document.querySelector(
      '[data-sonner-toast]:not([data-removed="true"])',
    );
    if (nowhere && !messages) content()?.focus();
  }, 400);
}

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
  // Escape closes the messages: one can sit on the very button the
  // keyboard is on, far from it in the order of the page. A dialog or a
  // menu that is open takes the key first, and says so.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !event.defaultPrevented &&
        document.querySelector('[data-sonner-toast]:not([data-removed="true"])')
      ) {
        const within =
          document.activeElement?.closest("[data-sonner-toaster]") != null;
        sonner.dismiss();
        if (within) focusBackOutside();
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("focusin", noteFocus);
    document.addEventListener("focusout", forgetFocus);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", noteFocus);
      document.removeEventListener("focusout", forgetFocus);
    };
  }, []);
  return (
    <Sonner
      theme="dark"
      // On a phone the bottom is where the buttons are: a message there
      // sat on the very button it was about.
      position={narrow ? "top-center" : "bottom-right"}
      // All of them in sight: stacked, those behind could be reached by
      // the keyboard without being seen.
      expand
      visibleToasts={9}
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
 * stays, and it cannot be asked for again. So does a notice, which has
 * something to say that is no error.
 */
const toast = {
  /** Close every message: what they said no longer holds. */
  dismiss: () => {
    sonner.dismiss();
  },
  success: (message: string) => sonner.success(message),
  /** Something to know, that stays until closed: nothing went wrong. */
  notice: (message: string) => sonner(message, untilClosed()),
  error: (message: string) => sonner.error(message, untilClosed()),
};

/** What makes a message stay until its reader closes it. */
const untilClosed = () =>
  ({
    duration: Infinity,
    cancel: {
      label: translate(pageLanguage(), "common.close"),
      // On to the next message, if there is one, and else back to
      // where focus was: the button pressed goes with its message.
      onClick: (event: { currentTarget: Element }) => {
        // Not when the reader is not in the messages: some browsers do
        // not give focus to a button that is pressed.
        if (!document.activeElement?.closest("[data-sonner-toaster]")) return;
        const here = event.currentTarget.closest("[data-sonner-toast]");
        const next = here?.nextElementSibling ?? here?.previousElementSibling;
        if (next instanceof HTMLElement) next.focus();
        else focusBackOutside();
      },
    },
  }) as const;

export { Toaster, toast };
