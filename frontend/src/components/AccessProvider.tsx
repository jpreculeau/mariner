import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, onSignedOut, type AuthState, type Tried } from "@/lib/api";
import { AccessContext, type Access, type AccessState } from "@/lib/access";
import { toast } from "@/components/ui/sonner";
import { useI18n } from "@/lib/i18n";

const KEY = ["auth"];
const RETRY_EVERY_MS = 5000;
const RENEW_EVERY_MS = 12 * 60 * 60 * 1000;

/**
 * Knows whether this page is signed in, and signs it in and out.
 *
 * Mariner is asked once; after that it says so itself, by refusing a
 * request, when the session is over.
 */
export function AccessProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { data, error, refetch } = useQuery({
    queryKey: KEY,
    queryFn: () => api.authState(),
    // Said at once when Mariner does not answer: the reader has a button
    // to try again.
    retry: false,
    // Not asked again by itself once answered: a refusal tells. While
    // Mariner cannot be reached it is, every few seconds: who opened the
    // page as the computer was starting is let in when it has.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.status === "success" && !query.state.data?.unavailable
        ? // Twice a day in a page left open: the month a session lasts
          // starts again each time.
          RENEW_EVERY_MS
        : RETRY_EVERY_MS,
  });
  // Whether the last answer was a failure, and whether the reader asked
  // for another try: tried by itself, the page goes on saying that
  // Mariner cannot be reached; asked for, it shows that it is trying.
  const failed = useRef<unknown>(null);
  const [asked, setAsked] = useState(false);
  if (data) failed.current = null;
  else if (error) failed.current = error;
  useEffect(() => {
    if (data || error) setAsked(false);
  }, [data, error]);

  useEffect(
    () =>
      onSignedOut(() => {
        queryClient.invalidateQueries({ queryKey: KEY });
      }),
    [queryClient],
  );

  const access: Access = data
    ? data.unavailable
      ? "shut"
      : data.signed_in
        ? "in"
        : data.password_set
          ? "sign-in"
          : "choose"
    : error || (failed.current && !asked)
      ? "unreachable"
      : "checking";

  // Whether the page was in, and whether it left by its own doing.
  const wasIn = useRef(false);
  const leftByItself = useRef(false);
  if (access === "in") {
    wasIn.current = true;
    leftByItself.current = false;
  }
  const signedOutUnasked =
    (access === "sign-in" || access === "choose") &&
    wasIn.current &&
    !leftByItself.current;

  // What the sign-in under way was told had been tried meanwhile.
  const tried = useRef<Tried>({ passwords: 0, codes: 0 });
  const { t } = useI18n();
  // As a reference: the effect below must not run again, and close the
  // messages, when the language changes.
  const say = useRef(t);
  say.current = t;
  const stood = useRef(access);
  useEffect(() => {
    const was = stood.current;
    stood.current = access;
    if (access === "in") {
      // What was said while the page was not open no longer holds once
      // it is: that Mariner is shut, say.
      toast.dismiss();
      const { passwords, codes, orMore } = tried.current;
      tried.current = { passwords: 0, codes: 0 };
      // After the messages above are closed, not before: somebody has
      // been at the door while its owner was away.
      if (codes > 0) {
        toast.error(
          say.current(
            codes === 1 ? "signIn.triedCodes.one" : "signIn.triedCodes.many",
            { count: String(codes) },
          ),
        );
      }
      if (passwords > 0) {
        // The lot of anything reachable from the Internet: to know, and
        // not said as loudly as a password that is known.
        toast.notice(
          say.current(
            orMore
              ? "signIn.tried.more"
              : passwords === 1
                ? "signIn.tried.one"
                : "signIn.tried.many",
            { count: String(passwords) },
          ),
        );
      }
    }
    if (was === "in" && access !== "in") {
      // What was fetched under the page that went, its failures
      // included, is not drawn again when the page opens.
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== KEY[0],
      });
    }
  }, [access, queryClient]);

  const failure = failed.current;
  const fromInternet = data?.from_internet === true;
  const codeSet = data?.code_set === true;
  // Offered unless Mariner says it would refuse.
  const hostCommands = data?.host_commands !== false;
  const value = useMemo<AccessState>(() => {
    const signedIn = async () => {
      // An answer asked for before this must not come after it and
      // say otherwise.
      await queryClient.cancelQueries({ queryKey: KEY });
      // What was said to who was not signed in no longer holds.
      toast.dismiss();
      // What was fetched before belongs to no session, or to another.
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== KEY[0],
      });
      queryClient.setQueryData<AuthState>(KEY, (was) => ({
        ...was,
        password_set: true,
        signed_in: true,
      }));
      // Where the page is seen from may not be where it was when this
      // was last asked: signed in outside, then back home. Only that is
      // taken of the answer: who is signed in is known here.
      api
        .authState()
        .then((now) =>
          queryClient.setQueryData<AuthState>(KEY, (was) =>
            was?.signed_in
              ? {
                  ...was,
                  from_internet: now.from_internet,
                  code_set: now.code_set,
                  host_commands: now.host_commands,
                }
              : was,
          ),
        )
        .catch(() => {});
    };
    return {
      access,
      retry: () => {
        setAsked(true);
        refetch();
      },
      failure,
      signedOutUnasked,
      choosePassword: async (password) => {
        await api.choosePassword(password);
        await signedIn();
      },
      fromInternet,
      codeSet,
      hostCommands,
      signIn: async (password, code) => {
        // Nothing, from a Mariner that does not say.
        tried.current = (await api.signIn(password, code)) ?? {
          passwords: 0,
          codes: 0,
        };
        await signedIn();
      },
      signOut: async () => {
        await api.signOut();
        await queryClient.cancelQueries({ queryKey: KEY });
        leftByItself.current = true;
        queryClient.setQueryData<AuthState>(KEY, (was) => ({
          ...was,
          password_set: true,
          signed_in: false,
        }));
        // Nothing of the printer stays in the page of who signed out.
        queryClient.removeQueries({
          predicate: (query) => query.queryKey[0] !== KEY[0],
        });
      },
    };
  }, [
    access,
    queryClient,
    refetch,
    signedOutUnasked,
    failure,
    fromInternet,
    codeSet,
    hostCommands,
  ]);

  return (
    <AccessContext.Provider value={value}>{children}</AccessContext.Provider>
  );
}
