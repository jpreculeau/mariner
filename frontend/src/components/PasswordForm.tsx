import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PasswordField } from "@/components/PasswordField";
import { useAccess } from "@/lib/access";
import { errorText } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { usePageTitle } from "@/hooks/use-page-title";

/**
 * Asks for the password, or at the first visit for one to be chosen.
 */
export function PasswordForm({ mode }: { mode: "choose" | "sign-in" }) {
  const choosing = mode === "choose";
  const { choosePassword, signIn } = useAccess();
  const { t, lang } = useI18n();
  usePageTitle(t(choosing ? "title.choosePassword" : "title.signIn"));

  const [password, setPassword] = useState("");
  const [repeated, setRepeated] = useState("");
  // Why it was not taken, and which field it is about.
  const [refused, setRefused] = useState<{
    on: "password" | "repeat";
    why: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  // Known at once, where `busy` is only once the page is drawn again.
  const underWay = useRef(false);
  const passwordField = useRef<HTMLInputElement>(null);
  const repeatField = useRef<HTMLInputElement>(null);

  const refuse = (on: "password" | "repeat", why: string) => {
    setRefused({ on, why });
    // Back to the field, to type it again.
    (on === "repeat" ? repeatField : passwordField).current?.focus();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (underWay.current || !password) return;
    if (choosing && password !== repeated) {
      refuse("repeat", t("choose.mismatch"));
      return;
    }
    underWay.current = true;
    setBusy(true);
    setRefused(null);
    try {
      await (choosing ? choosePassword(password) : signIn(password));
    } catch (failure) {
      refuse("password", errorText(failure, t, lang));
    } finally {
      underWay.current = false;
      setBusy(false);
    }
  };

  const error = (on: "password" | "repeat") =>
    refused?.on === on ? refused.why : null;

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
      </div>

      <PasswordField
        ref={passwordField}
        id="password"
        label={t(choosing ? "choose.new" : "signIn.password")}
        hint={choosing ? t("choose.hint") : undefined}
        autoComplete={choosing ? "new-password" : "current-password"}
        autoFocus
        value={password}
        error={error("password")}
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
          onChange={(value) => {
            setRepeated(value);
            setRefused(null);
          }}
        />
      )}

      <Button type="submit" size="lg" className="gap-2" aria-disabled={busy}>
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
