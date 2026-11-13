/**
 * A page left open at Mariner's address in the clear, once Mariner serves
 * it over HTTPS: everything it asks for is refused there, with the address
 * the page now has. It goes there by itself.
 */

/** What moves the page: apart, so that tests can watch it. */
export const navigation = {
  replace(url: string) {
    window.location.replace(url);
  },
};

/**
 * Where the page shown at `from` is over HTTPS, given the address Mariner
 * answered with; null if that is not an address of Mariner's own. What
 * answered in the clear is not taken at its word: only another port of
 * the same host, over HTTPS.
 */
export function secureAddress(
  given: unknown,
  from: { hostname: string; pathname: string; search: string; hash: string },
): string | null {
  if (typeof given !== "string") return null;
  let address: URL;
  try {
    address = new URL(given);
  } catch {
    return null;
  }
  if (address.protocol !== "https:" || address.hostname !== from.hostname) {
    return null;
  }
  return address.origin + from.pathname + from.search + from.hash;
}

/** Go there, if `body` is Mariner's refusal to answer in the clear. */
export function followToHttps(body: unknown): void {
  if (typeof body !== "object" || body === null) return;
  const refusal = body as { code?: unknown; address?: unknown };
  if (refusal.code !== "https_required") return;
  const where = secureAddress(refusal.address, window.location);
  if (where !== null) navigation.replace(where);
}
