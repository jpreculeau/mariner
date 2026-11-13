import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Loader2, Lock, Printer, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { PasswordForm } from "@/components/PasswordForm";
import { useAccess } from "@/lib/access";
import { ApiError } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useI18n, type TextKey } from "@/lib/i18n";
import { usePageTitle } from "@/hooks/use-page-title";

/**
 * Shows the page to who is signed in, and to anyone else what signs in.
 *
 * Nothing of the printer is drawn, or asked of Mariner, before that.
 */
export function Gate({ children }: { children: ReactNode }) {
  const { access, retry, failure } = useAccess();
  const { t, lang } = useI18n();
  // Mariner answered, to say that it will not: its reason is what helps
  // (a name it does not answer to, say), not "check that it is on".
  const refusedBy =
    failure instanceof ApiError && failure.status > 0 ? failure : null;

  // When the page opens after a form, put focus in it: the form went
  // with what had focus, and nothing else says that it worked. Not in a
  // page that opens signed in: nothing was lost.
  const shownAForm = useRef(false);
  const askedAgain = useRef(false);
  useEffect(() => {
    if (access !== "in") {
      shownAForm.current = access === "choose" || access === "sign-in";
    } else if (shownAForm.current) {
      shownAForm.current = false;
      document.getElementById("content")?.focus();
    }
  }, [access]);

  // From one of its screens to another, focus has a place to go when
  // what had it went: the button to try again.
  const againButton = useRef<HTMLButtonElement>(null);
  const before = useRef(access);
  useEffect(() => {
    const was = before.current;
    before.current = access;
    if (was === access) return;
    const asked = askedAgain.current;
    if (access !== "checking") askedAgain.current = false;
    if (asked && access === "unreachable") {
      // Still not reached: back on the button, to press it again.
      againButton.current?.focus();
      return;
    }
    // A page that is opening lost nothing: focus is left where the
    // browser put it.
    const opening = was === "checking" && !asked;
    const nowhere =
      !document.activeElement || document.activeElement === document.body;
    // What had focus went with the screen it was on.
    if (!opening && nowhere) document.getElementById("content")?.focus();
  }, [access]);

  if (access === "in") return <>{children}</>;

  const named: Partial<Record<typeof access, TextKey>> = {
    checking: "access.checking",
    unreachable: refusedBy
      ? "access.refused.title"
      : "dashboard.unreachable.title",
    shut: "access.shut.title",
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b bg-card/80">
        <div className="container flex h-14 items-center justify-between">
          <div className="flex items-center gap-2">
            <div
              className="flex h-8 w-8 items-center justify-center rounded bg-primary"
              aria-hidden
            >
              <Printer className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="font-display text-lg font-bold">Mariner 2</span>
          </div>
          {/* The language and the typeface, before anything is typed. */}
          <ThemeSwitcher />
        </div>
      </header>
      {named[access] && <Named title={t(named[access]!)} />}
      <main id="content" tabIndex={-1} className="focus:outline-none">
        <div className="container max-w-md py-10">
          {access === "checking" && (
            <div
              role="status"
              className="flex flex-col items-center rounded-lg border bg-card px-6 py-16"
            >
              <Loader2
                className="h-8 w-8 animate-spin text-primary"
                aria-hidden
              />
              <h1 className="mt-4 text-sm font-normal text-muted-foreground">
                {t("access.checking")}
              </h1>
            </div>
          )}
          {access === "unreachable" && (
            <div
              role="alert"
              className="flex flex-col items-center rounded-lg border border-danger/30 bg-destructive/5 px-6 py-12 text-center"
            >
              <WifiOff className="h-8 w-8 text-danger" aria-hidden />
              <h1 className="mt-4 text-lg font-semibold">
                {t(
                  refusedBy
                    ? "access.refused.title"
                    : "dashboard.unreachable.title",
                )}
              </h1>
              <p className="mt-1 text-base leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
                {refusedBy
                  ? errorText(refusedBy, t, lang)
                  : t("dashboard.unreachable.text")}
              </p>
              {/* Asking again shows "Opening Mariner…" meanwhile. */}
              <Button
                ref={againButton}
                variant="outline"
                className="mt-4"
                onClick={() => {
                  askedAgain.current = true;
                  retry();
                }}
              >
                {t("files.error.retry")}
              </Button>
            </div>
          )}
          {access === "shut" && (
            <div
              role="alert"
              className="flex flex-col items-center rounded-lg border border-danger/30 bg-destructive/5 px-6 py-12 text-center"
            >
              <Lock className="h-8 w-8 text-danger" aria-hidden />
              <h1 className="mt-4 text-lg font-semibold">
                {t("access.shut.title")}
              </h1>
              <p className="mt-1 text-base leading-relaxed text-muted-foreground">
                {t("access.shut.text")}
              </p>
            </div>
          )}
          {(access === "choose" || access === "sign-in") && (
            <PasswordForm mode={access} />
          )}
        </div>
      </main>
    </div>
  );
}

/** Names the page in the browser's tab, for a state that has no form. */
function Named({ title }: { title: string }) {
  usePageTitle(title);
  return null;
}
