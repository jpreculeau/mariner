import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { PasswordField } from "@/components/PasswordField";
import { toast } from "@/components/ui/sonner";
import { useAccess } from "@/lib/access";
import { api } from "@/lib/api";
import { errorText, saidByThePage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

/**
 * The one-time code asked, besides the password, of who signs in from
 * the Internet: set up with a phone, or done away with. From the local
 * network alone.
 */
export function OneTimeCode({ onChanged }: { onChanged?: () => void }) {
  const { fromInternet, codeSet, retry } = useAccess();
  const { t, lang } = useI18n();
  // What is being done: nothing, giving the password to replace the
  // phone, taking a key in, or removing the code.
  const [doing, setDoing] = useState<
    "nothing" | "replacing" | "setting" | "removing"
  >("nothing");
  const [key, setKey] = useState<{ secret: string; uri: string } | null>(null);
  const [typed, setTyped] = useState("");
  const [refused, setRefused] = useState<{
    why: unknown;
    said: number;
  } | null>(null);
  const said = useRef(0);
  const underWay = useRef(false);
  const field = useRef<HTMLInputElement>(null);
  // The button that opened the form under way: focus goes back to it.
  const opener = useRef<"first" | "remove">("first");
  const section = useRef<HTMLDivElement>(null);
  const began = useRef(false);

  // Focus goes to what comes next, once it is drawn; and back to where
  // it all began once it is over, however it ended: left on a form that
  // is gone, it would be at the top of the page.
  useEffect(() => {
    if (doing !== "nothing") {
      began.current = true;
      field.current?.focus();
    } else if (began.current) {
      began.current = false;
      // Found again by what it is: it was drawn anew.
      // The first, where the one pressed is gone with the code.
      (
        section.current?.querySelector<HTMLElement>(
          `[data-code-button="${opener.current}"]`,
        ) ??
        section.current?.querySelector<HTMLElement>(
          '[data-code-button="first"]',
        )
      )?.focus();
    }
  }, [doing, key]);

  const refuse = (why: unknown) => {
    if (saidByThePage(why)) return;
    setRefused({ why, said: ++said.current });
    field.current?.focus();
  };
  const missing = (words: string) => {
    setRefused({ why: { words }, said: ++said.current });
    field.current?.focus();
  };
  const once = async (work: () => Promise<void>) => {
    if (underWay.current) return;
    underWay.current = true;
    setRefused(null);
    try {
      await work();
    } catch (failure) {
      refuse(failure);
    } finally {
      underWay.current = false;
    }
  };
  const done = (words: string) => {
    setDoing("nothing");
    setKey(null);
    setTyped("");
    toast.success(words);
    // The page asks again where it stands, and reads its journal again.
    retry();
    onChanged?.();
  };

  const start = (current?: string) =>
    once(async () => {
      const given = await api.startCode(current);
      setKey(given);
      setTyped("");
      setDoing("setting");
    });

  const why = refused?.why;
  const error = !refused
    ? null
    : typeof why === "object" && why !== null && "words" in why
      ? String((why as { words: string }).words)
      : errorText(why, t, lang);
  const status = (
    <p className="text-base leading-relaxed text-muted-foreground">
      {t(codeSet ? "settings.code.set" : "settings.code.none")}
    </p>
  );

  if (fromInternet) {
    return (
      <div className="grid gap-2">
        {status}
        <p className="text-base leading-relaxed text-muted-foreground">
          {t("settings.code.localOnly")}
        </p>
      </div>
    );
  }

  return (
    <div ref={section} className="grid gap-4">
      {status}
      {doing === "nothing" && (
        <div className="flex flex-wrap gap-2">
          <Button
            data-code-button="first"
            variant="outline"
            className="h-auto min-h-10 whitespace-normal"
            onClick={() => {
              opener.current = "first";
              if (!codeSet) {
                start();
                return;
              }
              // Another phone in the place of the one in use: not by
              // whoever finds the page open.
              setRefused(null);
              setTyped("");
              setDoing("replacing");
            }}
          >
            {t(codeSet ? "settings.code.again" : "settings.code.setUp")}
          </Button>
          {codeSet && (
            <Button
              variant="outline"
              className="h-auto min-h-10 whitespace-normal"
              data-code-button="remove"
              onClick={() => {
                opener.current = "remove";
                setRefused(null);
                setTyped("");
                setDoing("removing");
              }}
            >
              {t("settings.code.remove")}
            </Button>
          )}
        </div>
      )}
      {doing === "nothing" && error && (
        <p
          key={refused?.said}
          role="alert"
          className="text-sm leading-relaxed text-danger"
        >
          {error}
        </p>
      )}

      {doing === "setting" && key && (
        <form
          noValidate
          className="grid gap-4"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (!typed.trim()) {
              missing(t("signIn.code.missing"));
              return;
            }
            once(async () => {
              await api.confirmCode(typed);
              done(t("settings.code.done"));
            });
          }}
        >
          <p className="text-base leading-relaxed">{t("settings.code.how")}</p>
          <p>
            <code
              role="group"
              aria-label={t("settings.code.key")}
              className="block rounded border bg-muted px-3 py-2 font-mono text-base [overflow-wrap:anywhere]"
            >
              {key.secret.match(/.{1,4}/g)?.join(" ")}
            </code>
          </p>
          <p className="text-base leading-relaxed">
            <a href={key.uri} className="underline underline-offset-4">
              {t("settings.code.open")}
            </a>
            <span className="block text-sm text-muted-foreground">
              {t("settings.code.open.hint")}
            </span>
          </p>
          <PasswordField
            ref={field}
            id="new-one-time-code"
            label={t("settings.code.given")}
            hint={t("settings.code.given.hint")}
            autoComplete="one-time-code"
            inSight
            value={typed}
            error={error}
            errorSaid={refused?.said}
            onChange={(value) => {
              setTyped(value);
              setRefused(null);
            }}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit">{t("settings.code.confirm")}</Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setDoing("nothing");
                setKey(null);
                setRefused(null);
              }}
            >
              {t("settings.code.cancel")}
            </Button>
          </div>
        </form>
      )}

      {doing === "replacing" && (
        <form
          noValidate
          className="grid gap-4"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (!typed) {
              missing(t("settings.code.password.missing"));
              return;
            }
            start(typed);
          }}
        >
          <p className="text-base leading-relaxed">
            {t("settings.code.replace.what")}
          </p>
          <PasswordField
            ref={field}
            id="code-replace-password"
            label={t("settings.password.current")}
            autoComplete="current-password"
            value={typed}
            error={error}
            errorSaid={refused?.said}
            onChange={(value) => {
              setTyped(value);
              setRefused(null);
            }}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit">{t("settings.code.continue")}</Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setDoing("nothing");
                setTyped("");
                setRefused(null);
              }}
            >
              {t("settings.code.cancel")}
            </Button>
          </div>
        </form>
      )}

      {doing === "removing" && (
        <form
          noValidate
          className="grid gap-4"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (!typed) {
              missing(t("settings.code.password.missing"));
              return;
            }
            once(async () => {
              await api.removeCode(typed);
              done(t("settings.code.removed"));
            });
          }}
        >
          <p className="text-base leading-relaxed">
            {t("settings.code.remove.what")}
          </p>
          <PasswordField
            ref={field}
            id="code-current-password"
            label={t("settings.password.current")}
            autoComplete="current-password"
            value={typed}
            error={error}
            errorSaid={refused?.said}
            onChange={(value) => {
              setTyped(value);
              setRefused(null);
            }}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit">{t("settings.code.remove.confirm")}</Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setDoing("nothing");
                setTyped("");
                setRefused(null);
              }}
            >
              {t("settings.code.cancel")}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
