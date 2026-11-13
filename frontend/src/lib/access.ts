import { createContext, useContext } from "react";

/**
 * Where this page stands with the password: finding out, unable to
 * (Mariner does not answer), shut (Mariner cannot reach what it keeps),
 * at the first visit (one is to be chosen), to sign in, or in.
 */
export type Access =
  "checking" | "unreachable" | "shut" | "choose" | "sign-in" | "in";

export interface AccessState {
  access: Access;
  /** Ask Mariner again where the page stands. */
  retry: () => void;
  /** Why Mariner could not be asked, when `access` is "unreachable". */
  failure: unknown;
  /** Whether the page was signed in and no longer is, not by its own
   * doing: its session ended, or the password was changed or cleared
   * elsewhere. */
  signedOutUnasked: boolean;
  /** Choose the password, at the first visit. Rejects with the reason. */
  choosePassword: (password: string) => Promise<void>;
  /** Whether the page is seen from outside the local network. */
  fromInternet: boolean;
  /** Whether a one-time code is set up: asked for, from the Internet. */
  codeSet: boolean;
  /** Rejects with the reason when the password is not taken. */
  signIn: (password: string, code?: string) => Promise<void>;
  signOut: () => Promise<void>;
}

export const AccessContext = createContext<AccessState | null>(null);

export function useAccess(): AccessState {
  const access = useContext(AccessContext);
  if (!access) throw new Error("useAccess needs an AccessProvider above it");
  return access;
}
