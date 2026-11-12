import { useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, onSignedOut, type AuthState } from "@/lib/api";
import { AccessContext, type Access, type AccessState } from "@/lib/access";

const KEY = ["auth"];

/**
 * Knows whether this page is signed in, and signs it in and out.
 *
 * Mariner is asked once; after that it says so itself, by refusing a
 * request, when the session is over.
 */
export function AccessProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: KEY,
    queryFn: () => api.authState(),
    // Said at once when Mariner does not answer: the reader has a button
    // to try again.
    retry: false,
    // Not asked again by itself: a refusal tells.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  useEffect(
    () =>
      onSignedOut(() => {
        queryClient.invalidateQueries({ queryKey: KEY });
      }),
    [queryClient],
  );

  const access: Access = data
    ? data.signed_in
      ? "in"
      : data.password_set
        ? "sign-in"
        : "choose"
    : isLoading
      ? "checking"
      : error
        ? "unreachable"
        : "checking";

  const value = useMemo<AccessState>(() => {
    const signedIn = () => {
      // What was fetched before belongs to no session, or to another.
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== KEY[0],
      });
      queryClient.setQueryData<AuthState>(KEY, {
        password_set: true,
        signed_in: true,
      });
    };
    return {
      access,
      retry: () => {
        refetch();
      },
      choosePassword: async (password) => {
        await api.choosePassword(password);
        signedIn();
      },
      signIn: async (password) => {
        await api.signIn(password);
        signedIn();
      },
      signOut: async () => {
        await api.signOut();
        queryClient.setQueryData<AuthState>(KEY, {
          password_set: true,
          signed_in: false,
        });
        // Nothing of the printer stays in the page of who signed out.
        queryClient.removeQueries({
          predicate: (query) => query.queryKey[0] !== KEY[0],
        });
      },
    };
  }, [access, queryClient, refetch]);

  return (
    <AccessContext.Provider value={value}>{children}</AccessContext.Provider>
  );
}
