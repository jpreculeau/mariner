/**
 * What the reader chose, kept by the browser between visits.
 *
 * A browser set to keep nothing throws when asked: the page then works
 * with what it starts with, and forgets the choice at the next visit.
 */
export function remembered(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Not kept: nothing to do about it.
  }
}
