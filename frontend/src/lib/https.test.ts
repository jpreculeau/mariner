import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "./api";
import { navigation, secureAddress } from "./https";

const at = (href: string) => new URL(href);

describe("where the page is over HTTPS", () => {
  it("is the same place in the page, at the address Mariner gave", () => {
    expect(
      secureAddress(
        "https://printer.local:5443",
        at("http://printer.local:5000/files?sort=name#top"),
      ),
    ).toBe("https://printer.local:5443/files?sort=name#top");
  });

  it("is none for an address that is not Mariner's own", () => {
    // Whatever answered in the clear is not taken at its word.
    expect(
      secureAddress("https://elsewhere.example", at("http://printer.local/")),
    ).toBeNull();
  });

  it.each(["http://printer.local:5443", "javascript:alert(1)", "", 7, null])(
    "is none for %s",
    (given) => {
      expect(secureAddress(given, at("http://printer.local/"))).toBeNull();
    },
  );
});

describe("a page left open in the clear, once Mariner has HTTPS", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  const refused = (address: unknown) =>
    new Response(
      JSON.stringify({
        code: "https_required",
        description: "Mariner's page is served over HTTPS.",
        address,
      }),
      { status: 403 },
    );

  it("goes to the page over HTTPS by itself", async () => {
    // Else it says for ever that Mariner cannot be reached.
    const go = vi.spyOn(navigation, "replace").mockImplementation(() => {});
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(refused(`https://${window.location.hostname}:5443`));
    await api.printStatus().catch(() => {});
    expect(go).toHaveBeenCalledWith(
      `https://${window.location.hostname}:5443${window.location.pathname}`,
    );
  });

  it("stays where it is when the address is not Mariner's", async () => {
    const go = vi.spyOn(navigation, "replace").mockImplementation(() => {});
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(refused("https://elsewhere.example"));
    await api.printStatus().catch(() => {});
    expect(go).not.toHaveBeenCalled();
  });
});
