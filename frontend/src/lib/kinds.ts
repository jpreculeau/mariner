/**
 * The kinds of file the printer takes, as the server told the page:
 * [".ctb", ".fdg"]. Empty when it did not.
 */
export function supportedKinds(): string[] {
  const listed =
    document
      .querySelector('meta[name="supported-extensions"]')
      ?.getAttribute("content") || "";
  return listed
    .split(",")
    .map((kind) => kind.trim().toLowerCase().replace(/^\./, ""))
    .filter((kind) => /^[a-z0-9]+$/.test(kind))
    .map((kind) => `.${kind}`)
    .sort();
}

/** Whether a file of this name is of a kind the printer takes. */
export function isSupportedKind(name: string): boolean {
  const kinds = supportedKinds();
  // Not told which: the server says.
  if (kinds.length === 0) return true;
  // As the server will store it: without the spaces around it.
  const lower = name.trim().toLowerCase();
  return kinds.some((kind) => lower.endsWith(kind));
}

/**
 * Whether the server would take this name. It is the one that decides;
 * this spares sending a whole file to be told no. Its rule is in the text
 * of `error.name_not_allowed`.
 */
export function isUsableName(given: string): boolean {
  // As the server will store it: without the spaces around it.
  const name = given.trim();
  return (
    name.length > 0 &&
    name.length <= 255 &&
    // eslint-disable-next-line no-control-regex
    !/['\\/:*?"<>|\u0000-\u001f]/.test(name) &&
    !name.endsWith(".")
  );
}
