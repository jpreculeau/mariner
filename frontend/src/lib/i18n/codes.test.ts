import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { en } from "./en";

/**
 * The codes the server gives its refusals, read from its source: wherever
 * one is written as the code of an answer.
 */
function serverCodes(): string[] {
  const server = resolve(__dirname, "../../../../mariner/server");
  const sources = readdirSync(server)
    .filter((name) => name.endsWith(".py"))
    .map((name) => readFileSync(resolve(server, name), "utf-8"));
  const patterns = [
    /"code":\s*"([a-z_]+)"/g, // in the body of an answer
    /"code":\s*"([a-z_]+)" if [^\n]+ else "([a-z_]+)"/g, // one of two
    /_refuse\(\s*"([a-z_]+)"/g, // a request the page is told why not
    /Refusal\(\s*"([a-z_]+)"/g, // a request turned away
    /Usage\.\w+: \(\s*"([a-z_]+)"/g, // a file that cannot change now
  ];
  const codes = new Set<string>();
  for (const source of sources) {
    for (const pattern of patterns) {
      for (const found of source.matchAll(pattern)) {
        found.slice(1).forEach((code) => code && codes.add(code));
      }
    }
  }
  return [...codes].sort();
}

describe("what the server can refuse", () => {
  const codes = serverCodes();

  it("is found in the server's source", () => {
    // Else this test would pass by finding nothing.
    expect(codes.length).toBeGreaterThan(15);
    for (const known of [
      "print_in_progress",
      "printer_not_answering",
      "folder_exists",
      "token_refused",
      "cross_site_request",
    ]) {
      expect(codes).toContain(known);
    }
  });

  it.each(codes)("has words in the page for %s", (code) => {
    // Without them a French reader is answered in English.
    expect(en).toHaveProperty([`error.${code}`]);
  });
});
