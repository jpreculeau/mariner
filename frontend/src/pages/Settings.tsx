import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, LogOut, RotateCcw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PasswordField } from "@/components/PasswordField";
import { toast } from "@/components/ui/sonner";
import {
  api,
  ApiError,
  type Settings as Kept,
  type SettingsResponse,
} from "@/lib/api";
import { useAccess } from "@/lib/access";
import { errorText, saidByThePage } from "@/lib/errors";
import { useI18n, type TextKey } from "@/lib/i18n";
import { usePageTitle } from "@/hooks/use-page-title";

const KEY = ["settings"];
// How often, and how many times, Mariner is asked whether it is back
// from a restart: a minute in all.
const BACK_EVERY_MS = 1500;
const BACK_WITHIN_TRIES = 40;

type Switch = "uvtools_enabled" | "sdcp_enabled" | "assume_printer_off";

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 rounded-lg border bg-card p-5">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export default function Settings() {
  const { t, lang } = useI18n();
  usePageTitle(t("title.settings"));
  const queryClient = useQueryClient();
  const { signOut } = useAccess();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: KEY,
    queryFn: () => api.settings(),
  });
  // What is being kept: one change at a time.
  const [saving, setSaving] = useState<keyof Kept | null>(null);
  const underWay = useRef(false);
  const [restarting, setRestarting] = useState(false);

  const [name, setName] = useState("");
  const shownName = data?.settings.printer_display_name ?? "";
  useEffect(() => setName(shownName), [shownName]);

  const keep = async (changes: Partial<Kept>) => {
    if (underWay.current) return;
    underWay.current = true;
    setSaving(Object.keys(changes)[0] as keyof Kept);
    try {
      const before = queryClient.getQueryData<SettingsResponse>(KEY);
      const kept = await api.saveSettings(changes);
      queryClient.setQueryData<SettingsResponse>(KEY, kept);
      if ("printer_display_name" in changes) {
        // The dashboard shows it.
        document
          .querySelector('meta[name="printer-display-name"]')
          ?.setAttribute("content", kept.settings.printer_display_name ?? "");
      }
      // That it waits for a restart is said here too, where it is sure
      // to be heard and seen: the notice is at the top of the page.
      toast.success(
        kept.restart_needed && !before?.restart_needed
          ? `${t("settings.saved")}. ${t("settings.restartNeeded")}`
          : t("settings.saved"),
      );
    } catch (failure) {
      // Shown as it stands, which is as it was.
      if (!saidByThePage(failure)) toast.error(errorText(failure, t, lang));
    } finally {
      underWay.current = false;
      setSaving(null);
    }
  };

  const restart = async () => {
    if (restarting) return;
    setRestarting(true);
    try {
      await api.restart();
      toast.success(t("settings.restarted"));
    } catch (failure) {
      if (!saidByThePage(failure)) toast.error(errorText(failure, t, lang));
      setRestarting(false);
      return;
    }
    // Until Mariner is back, and says what it now runs with: left as
    // it was, the notice would ask for another restart.
    let back = false;
    let refusing = false;
    for (
      let tries = 0;
      tries < BACK_WITHIN_TRIES && !back && !refusing;
      tries++
    ) {
      await new Promise((resolve) => setTimeout(resolve, BACK_EVERY_MS));
      try {
        const now = await api.settings();
        queryClient.setQueryData<SettingsResponse>(KEY, now);
        back = true;
      } catch (failure) {
        // An answer, even one that refuses, is Mariner being back: the
        // session may not have outlasted the restart. No answer: not yet.
        refusing = failure instanceof ApiError && failure.status > 0;
      }
    }
    setRestarting(false);
    if (refusing) {
      // What it refuses with is shown by what fetches the settings, or
      // by the form to sign in.
      queryClient.invalidateQueries({ queryKey: KEY });
    } else if (back) {
      toast.success(t("settings.back"));
      // The button went with the notice it was in.
      setTimeout(() => {
        const nowhere =
          !document.activeElement || document.activeElement === document.body;
        if (nowhere) document.getElementById("content")?.focus();
      });
    } else {
      toast.error(t("settings.notBack"));
    }
  };

  const heading = (
    <h1 className="mb-6 text-2xl font-bold">{t("settings.heading")}</h1>
  );

  if (isLoading) {
    return (
      <div className="container max-w-2xl py-6">
        {heading}
        <div
          role="status"
          className="flex items-center justify-center rounded-lg border bg-card py-16"
        >
          <Loader2 className="h-6 w-6 animate-spin text-primary" aria-hidden />
          <span className="ml-2 text-sm text-muted-foreground">
            {t("settings.loading")}
          </span>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="container max-w-2xl py-6">
        {heading}
        <div
          role="alert"
          className="flex flex-col items-center rounded-lg border bg-card px-6 py-12 text-center"
        >
          <TriangleAlert className="h-8 w-8 text-danger" aria-hidden />
          <h2 className="mt-3 text-lg font-semibold">
            {t("settings.loadError")}
          </h2>
          <p className="mt-1 max-w-prose text-sm text-muted-foreground">
            {errorText(error, t, lang)}
          </p>
          <Button variant="outline" className="mt-4" onClick={() => refetch()}>
            {t("files.error.retry")}
          </Button>
        </div>
      </div>
    );
  }

  const box = (setting: Switch, label: TextKey, hint: TextKey) => (
    <div className="flex items-start gap-3">
      <input
        id={setting}
        type="checkbox"
        checked={data.settings[setting]}
        aria-describedby={`${setting}-hint`}
        aria-disabled={saving !== null}
        onChange={(event) => keep({ [setting]: event.target.checked })}
        className="mt-1 h-5 w-5 shrink-0 accent-primary ring-offset-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-disabled:opacity-50"
      />
      <div className="min-w-0">
        <label htmlFor={setting} className="font-medium">
          {t(label)}
        </label>
        <p
          id={`${setting}-hint`}
          className="text-sm leading-relaxed text-muted-foreground"
        >
          {t(hint)}
        </p>
      </div>
    </div>
  );

  return (
    <div className="container max-w-2xl py-6">
      {heading}
      <div className="grid gap-5">
        {data.restart_needed && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/40 bg-primary/5 p-4">
            {/* Not announced from here: the message that says "Saved"
                says it, and this would have it read out twice. */}
            <p className="min-w-[min(100%,14rem)] flex-1 text-base leading-relaxed">
              {t("settings.restartNeeded")}{" "}
              {!data.can_restart && t("settings.restartByHand")}
            </p>
            {data.can_restart && (
              <Button
                className="h-auto min-h-10 gap-2 whitespace-normal"
                aria-disabled={restarting}
                onClick={restart}
              >
                {restarting ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <RotateCcw className="h-4 w-4" aria-hidden />
                )}
                {t(restarting ? "settings.restarting" : "settings.restart")}
              </Button>
            )}
          </div>
        )}

        <Part title={t("settings.printer")}>
          <form
            className="grid gap-3"
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              keep({ printer_display_name: name });
            }}
          >
            <div className="grid gap-1.5">
              <label htmlFor="printer-name" className="text-sm font-medium">
                {t("settings.name")}
              </label>
              <input
                id="printer-name"
                value={name}
                maxLength={64}
                autoComplete="off"
                aria-describedby="printer-name-hint"
                onChange={(event) => setName(event.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-1 text-base shadow-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <p
                id="printer-name-hint"
                className="text-sm leading-relaxed text-muted-foreground"
              >
                {t("settings.name.hint")}
              </p>
            </div>
            <div>
              <Button
                type="submit"
                variant="outline"
                aria-disabled={saving !== null}
              >
                {t("settings.name.save")}
              </Button>
            </div>
          </form>
        </Part>

        <Part title={t("settings.slicers")}>
          <p className="text-base leading-relaxed text-muted-foreground">
            {t("settings.slicers.intro")}
          </p>
          {box("uvtools_enabled", "settings.uvtools", "settings.uvtools.hint")}
          {box("sdcp_enabled", "settings.sdcp", "settings.sdcp.hint")}
        </Part>

        <Part title={t("settings.files")}>
          {box(
            "assume_printer_off",
            "settings.assumeOff",
            "settings.assumeOff.hint",
          )}
        </Part>

        <Part title={t("settings.password")}>
          <ChangePassword />
          <div className="border-t pt-4">
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => {
                signOut().catch((failure) =>
                  toast.error(errorText(failure, t, lang)),
                );
              }}
            >
              <LogOut className="h-4 w-4" aria-hidden />
              {t("settings.signOut")}
            </Button>
          </div>
        </Part>
      </div>
    </div>
  );
}

function ChangePassword() {
  const { t, lang } = useI18n();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  // Kept as it came, and worded when drawn: in the language the page is
  // in by then.
  const [refused, setRefused] = useState<{
    on: "current" | "new" | "again" | "form";
    why: TextKey | { failure: unknown };
    said: number;
  } | null>(null);
  const said = useRef(0);
  const [busy, setBusy] = useState(false);
  const underWay = useRef(false);
  const fields = {
    current: useRef<HTMLInputElement>(null),
    new: useRef<HTMLInputElement>(null),
    again: useRef<HTMLInputElement>(null),
  };

  const refuse = (
    on: "current" | "new" | "again" | "form",
    why: TextKey | { failure: unknown },
  ) => {
    setRefused({ on, why, said: ++said.current });
    // What is about no field is read from the first one.
    fields[on === "form" ? "current" : on].current?.focus();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (underWay.current) return;
    if (!current || !next) {
      // Said, rather than a button that seems to do nothing.
      refuse(current ? "new" : "current", "error.password_missing");
      return;
    }
    if (next !== again) {
      refuse("again", "choose.mismatch");
      return;
    }
    underWay.current = true;
    setBusy(true);
    setRefused(null);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setAgain("");
      toast.success(t("settings.password.changed"));
    } catch (failure) {
      const aboutTheNew =
        failure instanceof ApiError &&
        (failure.code === "password_too_short" ||
          failure.code === "password_too_long" ||
          failure.code === "password_too_common");
      const aboutTheCurrent =
        failure instanceof ApiError && failure.code === "wrong_password";
      // Anything else is about no field: none is marked as wrong.
      refuse(aboutTheNew ? "new" : aboutTheCurrent ? "current" : "form", {
        failure,
      });
    } finally {
      underWay.current = false;
      setBusy(false);
    }
  };

  const error = (on: "current" | "new" | "again" | "form") =>
    refused?.on !== on
      ? null
      : typeof refused.why === "string"
        ? t(refused.why)
        : errorText(refused.why.failure, t, lang);
  const typed = (set: (value: string) => void) => (value: string) => {
    set(value);
    setRefused(null);
  };

  return (
    <form onSubmit={submit} noValidate className="grid gap-4">
      <PasswordField
        ref={fields.current}
        id="current-password"
        label={t("settings.password.current")}
        describedBy={error("form") ? "change-password-error" : undefined}
        autoComplete="current-password"
        value={current}
        error={error("current")}
        errorSaid={refused?.said}
        onChange={typed(setCurrent)}
      />
      <PasswordField
        ref={fields.new}
        id="new-password"
        label={t("choose.new")}
        hint={t("choose.hint")}
        autoComplete="new-password"
        value={next}
        error={error("new")}
        errorSaid={refused?.said}
        onChange={typed(setNext)}
      />
      <PasswordField
        ref={fields.again}
        id="new-password-again"
        label={t("settings.password.repeat")}
        autoComplete="new-password"
        value={again}
        error={error("again")}
        errorSaid={refused?.said}
        onChange={typed(setAgain)}
      />
      {error("form") && (
        <p
          key={refused?.said}
          id="change-password-error"
          role="alert"
          className="text-sm leading-relaxed text-danger"
        >
          {error("form")}
        </p>
      )}
      <div>
        <Button
          type="submit"
          className="h-auto min-h-10 gap-2 whitespace-normal"
          aria-disabled={busy}
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
          {t("settings.password.change")}
        </Button>
      </div>
    </form>
  );
}
