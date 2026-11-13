import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PasswordField } from "@/components/PasswordField";
import { useAccess } from "@/lib/access";
import { ApiError } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useI18n, type TextKey } from "@/lib/i18n";
import { usePageTitle } from "@/hooks/use-page-title";

type Field = "password" | "repeat" | "code" | "form";

/**
 * Asks for the password, or at the first visit for one to be chosen.
 * From the Internet: for the one-time code too, and nothing is chosen.
 */
export function PasswordForm({ mode }: { mode: "choose" | "sign-in" }) {
  const choosing = mode === "choose";
  const {
    choosePassword,
    signIn,
    signedOutUnasked,
    retry,
    fromInternet,
    codeSet,
  } = useAccess();
  // From the Internet the password is not enough, and is not chosen.
  const withCode = !choosing && fromInternet && codeSet;
  const notFromHere = fromInternet && (choosing || !codeSet);
  const { t, lang } = useI18n();
  usePageTitle(t(choosing ? "title.choosePassword" : "title.signIn"));

  const [password, setPassword] = useState("");
  const [repeated, setRepeated] = useState("");
  const [code, setCode] = useState("");
  // Why it was not taken, and which field it is about.
  // Kept as it came, and worded when drawn: in the language the page is
  // in by then.
  const [refused, setRefused] = useState<{
    on: Field;
    why: TextKey | { failure: unknown };
    said: number;
  } | null>(null);
  const said = useRef(0);
  const [busy, setBusy] = useState(false);
  // Known at once, where `busy` is only once the page is drawn again.
  const underWay = useRef(false);
  const passwordField = useRef<HTMLInputElement>(null);
  const repeatField = useRef<HTMLInputElement>(null);
  const codeField = useRef<HTMLInputElement>(null);

  // The form became the other one: what was typed for one is not for
  // the other. What was said of the form as a whole stays.
  const shownAs = useRef(mode);
  useEffect(() => {
    if (shownAs.current === mode) return;
    shownAs.current = mode;
    setPassword("");
    setRepeated("");
    setCode("");
    setRefused((was) => (was?.on === "form" ? was : null));
  }, [mode]);

  const refuse = (on: Field, why: TextKey | { failure: unknown }) => {
    setRefused({ on, why, said: ++said.current });
    // Back to the field, to type it again.
    (on === "repeat"
      ? repeatField
      : on === "code"
        ? codeField
        : passwordField
    ).current?.focus();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (underWay.current) return;
    if (!password) {
      // Said, rather than a button that seems to do nothing.
      refuse("password", "error.password_missing");
      return;
    }
    if (choosing && password !== repeated) {
      refuse("repeat", "choose.mismatch");
      return;
    }
    if (withCode && !code.trim()) {
      refuse("code", "signIn.code.missing");
      return;
    }
    underWay.current = true;
    setBusy(true);
    setRefused(null);
    try {
      await (choosing
        ? choosePassword(password)
        : signIn(password, withCode ? code : undefined));
      setCode("");
    } catch (failure) {
      // Mariner is shut: the screen that replaces the form says it.
      if (failure instanceof ApiError && failure.code === "state_unavailable") {
        return;
      }
      if (
        withCode &&
        failure instanceof ApiError &&
        failure.code === "wrong_password"
      ) {
        // It may be either: neither field is marked, and the code, which
        // will not serve again, is to be typed anew.
        setCode("");
        refuse("form", "signIn.wrongEither");
        return;
      }
      // Only what is about the password marks its field as wrong.
      const aboutThePassword =
        failure instanceof ApiError &&
        [
          "wrong_password",
          "password_too_short",
          "password_too_long",
          "password_too_common",
        ].includes(failure.code ?? "");
      refuse(aboutThePassword ? "password" : "form", { failure });
      if (
        failure instanceof ApiError &&
        (failure.code === "password_already_set" ||
          failure.code === "password_not_set")
      ) {
        // Chosen from elsewhere meanwhile, or cleared: the form to show
        // is another.
        retry();
      }
    } finally {
      underWay.current = false;
      setBusy(false);
    }
  };

  const error = (on: Field) =>
    refused?.on !== on
      ? null
      : typeof refused.why === "string"
        ? t(refused.why)
        : errorText(refused.why.failure, t, lang);

  if (notFromHere) {
    return (
      <div className="grid gap-3 rounded-lg border bg-card p-6">
        <h1 className="text-2xl font-bold">
          {t(
            choosing ? "internet.notSetUp.heading" : "internet.noCode.heading",
          )}
        </h1>
        <p className="text-base leading-relaxed text-muted-foreground">
          {t(choosing ? "internet.notSetUp.text" : "internet.noCode.text")}
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      className="grid gap-5 rounded-lg border bg-card p-6"
    >
      <div>
        <h1 className="text-2xl font-bold">
          {t(choosing ? "choose.heading" : "signIn.heading")}
        </h1>
        {choosing && (
          <p className="mt-2 text-base leading-relaxed text-muted-foreground">
            {t("choose.intro")}
          </p>
        )}
        {signedOutUnasked && (
          <p
            id="session-over"
            className="mt-2 text-base leading-relaxed text-muted-foreground"
          >
            {t(choosing ? "choose.cleared" : "signIn.signedOut")}
          </p>
        )}
      </div>

      <PasswordField
        ref={passwordField}
        id="password"
        label={t(choosing ? "choose.new" : "signIn.password")}
        hint={choosing ? t("choose.hint") : undefined}
        // Focus lands in the field: what happened is read with it.
        describedBy={
          [
            signedOutUnasked ? "session-over" : null,
            error("form") ? "form-error" : null,
          ]
            .filter(Boolean)
            .join(" ") || undefined
        }
        autoComplete={choosing ? "new-password" : "current-password"}
        autoFocus
        value={password}
        error={error("password")}
        errorSaid={refused?.said}
        onChange={(value) => {
          setPassword(value);
          setRefused(null);
        }}
      />
      {choosing && (
        <PasswordField
          ref={repeatField}
          id="password-repeat"
          label={t("choose.repeat")}
          autoComplete="new-password"
          value={repeated}
          error={error("repeat")}
          errorSaid={refused?.said}
          onChange={(value) => {
            setRepeated(value);
            setRefused(null);
          }}
        />
      )}

      {withCode && (
        <PasswordField
          ref={codeField}
          id="one-time-code"
          label={t("signIn.code")}
          hint={t("signIn.code.hint")}
          autoComplete="one-time-code"
          inSight
          value={code}
          error={error("code")}
          errorSaid={refused?.said}
          onChange={(value) => {
            setCode(value);
            setRefused(null);
          }}
        />
      )}

      {error("form") && (
        <p
          key={refused?.said}
          id="form-error"
          role="alert"
          className="text-sm leading-relaxed text-danger [overflow-wrap:anywhere]"
        >
          {error("form")}
        </p>
      )}

      {/* Its words wrap: on one line they pushed the page wider than a
          phone's screen. */}
      <Button
        type="submit"
        size="lg"
        className="h-auto min-h-11 gap-2 whitespace-normal px-4"
        aria-disabled={busy}
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
        {choosing
          ? t(busy ? "choose.submitting" : "choose.submit")
          : t(busy ? "signIn.submitting" : "signIn.submit")}
      </Button>

      {!choosing && (
        <p className="text-sm leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
          {t("signIn.lost")}
        </p>
      )}
    </form>
  );
}
