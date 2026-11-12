import type { ReactNode } from "react";
import { Loader2, Printer, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { PasswordForm } from "@/components/PasswordForm";
import { useAccess } from "@/lib/access";
import { useI18n } from "@/lib/i18n";

/**
 * Shows the page to who is signed in, and to anyone else what signs in.
 *
 * Nothing of the printer is drawn, or asked of Mariner, before that.
 */
export function Gate({ children }: { children: ReactNode }) {
  const { access, retry } = useAccess();
  const { t } = useI18n();

  if (access === "in") return <>{children}</>;

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
              <p className="mt-4 text-sm text-muted-foreground">
                {t("access.checking")}
              </p>
            </div>
          )}
          {access === "unreachable" && (
            <div
              role="alert"
              className="flex flex-col items-center rounded-lg border border-danger/30 bg-destructive/5 px-6 py-12 text-center"
            >
              <WifiOff className="h-8 w-8 text-danger" aria-hidden />
              <h1 className="mt-4 text-lg font-semibold">
                {t("dashboard.unreachable.title")}
              </h1>
              <p className="mt-1 text-base leading-relaxed text-muted-foreground">
                {t("dashboard.unreachable.text")}
              </p>
              <Button variant="outline" className="mt-4" onClick={retry}>
                {t("files.error.retry")}
              </Button>
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
