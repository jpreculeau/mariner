import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError, onSignedOut } from "./api";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("signing in", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("asks whether a password is set and whether this page is signed in", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(json(200, { password_set: true, signed_in: false }));
    expect(await api.authState()).toEqual({
      password_set: true,
      signed_in: false,
    });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/auth/state");
  });

  it.each([
    ["signIn", "/api/auth/login", { password: "secret words" }],
    ["choosePassword", "/api/auth/setup", { password: "secret words" }],
  ] as const)("sends the password as JSON: %s", async (method, url, body) => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(json(200, { success: true, csrf_token: "fresh" }));
    await api[method]("secret words");
    const [sentTo, options] = vi.mocked(fetch).mock.calls[0];
    expect(sentTo).toBe(url);
    expect(options?.method).toBe("POST");
    expect(JSON.parse(options?.body as string)).toEqual(body);
    expect((options?.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json",
    );
  });

  it("uses from then on the token that came with the new session", async () => {
    // The one the page was loaded with went with the session it had.
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(json(200, { success: true, csrf_token: "fresh" }))
      .mockResolvedValue(json(200, { success: true }));
    await api.signIn("secret words");
    await api.signOut();
    const [, options] = vi.mocked(fetch).mock.calls[1];
    expect((options?.headers as Record<string, string>)["X-CSRFToken"]).toBe(
      "fresh",
    );
  });

  it("says why a password was not taken", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      json(401, {
        code: "wrong_password",
        description: "This is not the password.",
      }),
    );
    const outcome = await api.signIn("nope").catch((error) => error);
    expect(outcome).toBeInstanceOf(ApiError);
    expect(outcome.code).toBe("wrong_password");
  });

  it("sends both passwords to change it", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(json(200, { success: true, csrf_token: "fresh" }));
    await api.changePassword("old words", "new words");
    const [sentTo, options] = vi.mocked(fetch).mock.calls[0];
    expect(sentTo).toBe("/api/auth/password");
    expect(JSON.parse(options?.body as string)).toEqual({
      current: "old words",
      new: "new words",
    });
  });
});

describe("being signed out", () => {
  const realFetch = globalThis.fetch;
  let told: ReturnType<typeof vi.fn>;
  let stop: () => void;

  beforeEach(() => {
    told = vi.fn();
    stop = onSignedOut(told);
  });
  afterEach(() => {
    stop();
    globalThis.fetch = realFetch;
  });

  it.each(["login_required", "password_not_set"])(
    "is told to whoever listens when the server says %s",
    async (code) => {
      // The session ended, or the password was changed from elsewhere.
      globalThis.fetch = vi
        .fn()
        .mockResolvedValue(json(401, { code, description: "Sign in." }));
      await api.printStatus().catch(() => {});
      expect(told).toHaveBeenCalledTimes(1);
    },
  );

  it("is not told for a wrong password, nor for another refusal", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        json(401, { code: "wrong_password", description: "No." }),
      )
      .mockResolvedValue(
        json(404, { code: "file_gone", description: "Gone." }),
      );
    await api.signIn("nope").catch(() => {});
    await api.listFiles().catch(() => {});
    expect(told).not.toHaveBeenCalled();
  });

  it("is no longer told once it stops listening", async () => {
    stop();
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        json(401, { code: "login_required", description: "Sign in." }),
      );
    await api.printStatus().catch(() => {});
    expect(told).not.toHaveBeenCalled();
  });
});

describe("settings", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("are fetched, changed and Mariner restarted at their addresses", async () => {
    globalThis.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve(
        json(200, {
          settings: {
            printer_display_name: null,
            uvtools_enabled: true,
            sdcp_enabled: true,
            assume_printer_off: false,
          },
          restart_needed: false,
          can_restart: true,
        }),
      ),
    );
    await api.settings();
    await api.saveSettings({ sdcp_enabled: false });
    await api.restart();
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls[0][0]).toBe("/api/settings");
    expect(calls[1][0]).toBe("/api/settings");
    expect(calls[1][1]?.method).toBe("POST");
    expect(JSON.parse(calls[1][1]?.body as string)).toEqual({
      sdcp_enabled: false,
    });
    expect(calls[2][0]).toBe("/api/restart");
    expect(calls[2][1]?.method).toBe("POST");
  });
});
