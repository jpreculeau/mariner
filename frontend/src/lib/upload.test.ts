import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError } from "./api";
import { FakeXhr, useFakeXhr } from "@/test/fakeXhr";

const file = () => new File(["x"], "model.ctb");
const json = (body: unknown) => JSON.stringify(body);
const noNewToken = () => Promise.reject(new Error("offline"));
const newToken = () =>
  Promise.resolve(new Response(json({ csrf_token: "fresh-token" })));

describe("sending a file", () => {
  beforeEach(() => {
    useFakeXhr();
    globalThis.fetch = vi.fn().mockImplementation(noNewToken);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the file to the folder it is for", async () => {
    await api.uploadFile(file(), "sub/folder");

    expect(FakeXhr.requests).toHaveLength(1);
    const sent = FakeXhr.requests[0];
    expect(sent.method).toBe("POST");
    expect(sent.url).toBe("/api/upload_file?path=sub%2Ffolder");
    expect(sent.body).toBeInstanceOf(FormData);
    expect((sent.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("says so when the reader confirmed that the printer is off", async () => {
    await api.uploadFile(file(), ".", { ignoreUnreachablePrinter: true });
    expect(FakeXhr.requests[0].url).toBe(
      "/api/upload_file?path=.&ignore_unreachable_printer=1",
    );
  });

  it("tells how much of the file has been sent as it goes", async () => {
    FakeXhr.answers = [{ status: 200, progress: [0.25, 0.5, 1] }];
    const seen: number[] = [];

    await api.uploadFile(file(), ".", {}, (fraction) => seen.push(fraction));

    // The last of it is told by the browser saying that all has gone.
    expect(seen).toEqual([0.25, 0.5, 0.999, 1]);
  });

  it("makes sure of its token before sending", async () => {
    // A file refused for its token has been sent whole by then, and
    // would be sent whole again.
    globalThis.fetch = vi.fn().mockImplementation(newToken);

    await api.uploadFile(file(), ".");

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/csrf_token");
    expect(FakeXhr.requests[0].headers["X-CSRFToken"]).toBe("fresh-token");
  });

  it("sends the file all the same when no token can be asked for", async () => {
    await api.uploadFile(file(), ".");
    expect(FakeXhr.requests).toHaveLength(1);
  });

  it("asks for a new token and sends again when its own is refused", async () => {
    globalThis.fetch = vi
      .fn()
      .mockImplementationOnce(noNewToken)
      .mockImplementationOnce(newToken);
    FakeXhr.answers = [
      { status: 400, body: json({ code: "token_refused", description: "x" }) },
      { status: 200 },
    ];

    await api.uploadFile(file(), ".");

    expect(FakeXhr.requests).toHaveLength(2);
    expect(FakeXhr.requests[1].headers["X-CSRFToken"]).toBe("fresh-token");
  });

  it("tries once only, then says what the server said", async () => {
    globalThis.fetch = vi.fn().mockImplementation(newToken);
    const refused = {
      status: 400,
      body: json({ code: "token_refused", description: "Reload the page." }),
    };
    FakeXhr.answers = [refused, refused, refused];

    await expect(api.uploadFile(file(), ".")).rejects.toMatchObject({
      code: "token_refused",
      message: "Reload the page.",
    });
    expect(FakeXhr.requests).toHaveLength(2);
  });

  it("throws the explanation the server gave for a refused upload", async () => {
    FakeXhr.answers = [
      {
        status: 409,
        statusText: "CONFLICT",
        body: json({
          code: "printer_not_answering",
          title: "Printer Not Answering",
          description:
            "The printer did not say whether model.ctb is being printed.",
          can_be_overridden: true,
        }),
      },
    ];

    const error = await api.uploadFile(file()).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.code).toBe("printer_not_answering");
    expect(error.message).toContain("did not say");
    expect(error.canBeOverridden).toBe(true);
  });

  it("says a file is too large when the web server itself refused it", async () => {
    // Past the limit the web server answers before Mariner does, in plain
    // text.
    FakeXhr.answers = [{ status: 413, body: "Request Entity Too Large" }];

    const refusal = await api.uploadFile(file()).catch((error) => error);
    expect(refusal).toBeInstanceOf(ApiError);
    expect(refusal.code).toBe("file_too_large");
  });

  it("gives the status when the answer explains nothing", async () => {
    FakeXhr.answers = [{ status: 502, body: "<html>Bad Gateway</html>" }];

    const refusal = await api.uploadFile(file()).catch((error) => error);
    expect(refusal).toBeInstanceOf(ApiError);
    expect(refusal.status).toBe(502);
    expect(refusal.code).toBeUndefined();
  });

  it("ends, and says so, on an answer it cannot make sense of", async () => {
    // Left waiting, the page would show the upload for ever.
    for (const status of [205, 0, 99, 600]) {
      FakeXhr.answers = [{ status, body: "x" }];
      const outcome = await api.uploadFile(file()).catch((error) => error);
      expect(outcome, `status ${status}`).toBeInstanceOf(ApiError);
    }
  });

  it("is not given up once the whole file has gone", async () => {
    // The server then stores it whatever the browser does: dropping the
    // answer would only leave the page saying something untrue.
    FakeXhr.answers = [{ status: 200, held: true, sentBeforeHeld: true }];
    const giveUp = new AbortController();
    const seen: number[] = [];
    const sent = api.uploadFile(
      file(),
      ".",
      {},
      (fraction) => seen.push(fraction),
      giveUp.signal,
    );
    await vi.waitFor(() => expect(seen).toEqual([1]));

    giveUp.abort();
    FakeXhr.held.forEach((deliver) => deliver());

    await expect(sent).resolves.toBeUndefined();
    expect(FakeXhr.requests[0].aborted).toBe(false);
  });

  it("does not wait for ever for the answer once the file has gone", async () => {
    // The computer may have lost power: nothing more can be given up by
    // then, and no other file is taken meanwhile.
    const timers = vi.spyOn(globalThis, "setTimeout");
    FakeXhr.answers = [{ status: 200, held: true, sentBeforeHeld: true }];
    const sent = api.uploadFile(file()).catch((error) => error);
    // Five minutes, and more for a large file: the server copies it and
    // writes it out after the last of it has come.
    const waited = () =>
      timers.mock.calls.find(
        ([, wait]) => typeof wait === "number" && wait >= 5 * 60_000,
      );
    await vi.waitFor(() => expect(waited()).toBeDefined());
    const expire = waited()![0] as () => void;

    expire();

    const outcome = await sent;
    expect(outcome).toBeInstanceOf(ApiError);
    expect(outcome.code).toBe("upload_unanswered");
    expect(FakeXhr.requests[0].aborted).toBe(true);
  });

  it("waits longer for the answer to a larger file", async () => {
    const timers = vi.spyOn(globalThis, "setTimeout");
    const waitFor = async (size: number) => {
      timers.mockClear();
      FakeXhr.answers = [{ status: 200, held: true, sentBeforeHeld: true }];
      const large = new File(["x"], "model.ctb");
      Object.defineProperty(large, "size", { value: size });
      api.uploadFile(large).catch(() => {});
      let wait = 0;
      await vi.waitFor(() => {
        wait = Math.max(
          ...timers.mock.calls.map(([, ms]) => (ms as number) ?? 0),
        );
        expect(wait).toBeGreaterThanOrEqual(5 * 60_000);
      });
      FakeXhr.held.splice(0).forEach((deliver) => deliver());
      return wait;
    };
    expect(await waitFor(1024)).toBeLessThan(5 * 60_000 + 1000);
    // A second for every two megabytes: seventeen minutes more for two
    // gigabytes.
    expect(await waitFor(2048 * 1024 * 1024)).toBe(5 * 60_000 + 1024 * 1000);
  });

  it("says that all has gone only when all has", async () => {
    // The last report of progress can come before the last of the file.
    FakeXhr.answers = [{ status: 200, held: true, progress: [1] }];
    const seen: number[] = [];
    api.uploadFile(file(), ".", {}, (fraction) => seen.push(fraction));
    await vi.waitFor(() => expect(FakeXhr.held.length).toBe(1));
    expect(seen).toEqual([]);

    FakeXhr.held.forEach((deliver) => deliver());
    await vi.waitFor(() => expect(seen.at(-1)).toBe(1));
    expect(seen[0]).toBeLessThan(1);
  });

  it("says that Mariner could not be reached when the connection drops", async () => {
    FakeXhr.answers = [{ status: 0, fails: true }];

    const failure = await api.uploadFile(file()).catch((error) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.code).toBe("network");
  });
});

describe("giving up on a file being sent", () => {
  beforeEach(() => {
    useFakeXhr();
    globalThis.fetch = vi.fn().mockImplementation(noNewToken);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("stops sending and says that it was given up", async () => {
    FakeXhr.answers = [{ status: 200, held: true }];
    const giveUp = new AbortController();
    const sent = api
      .uploadFile(file(), ".", {}, undefined, giveUp.signal)
      .catch((error) => error);
    await vi.waitFor(() => expect(FakeXhr.requests).toHaveLength(1));

    giveUp.abort();

    const outcome = await sent;
    expect(FakeXhr.requests[0].aborted).toBe(true);
    expect(outcome).toBeInstanceOf(ApiError);
    expect(outcome.code).toBe("cancelled");
  });

  it("sends nothing when it was given up before it started", async () => {
    const giveUp = new AbortController();
    giveUp.abort();

    const outcome = await api
      .uploadFile(file(), ".", {}, undefined, giveUp.signal)
      .catch((error) => error);

    expect(outcome.code).toBe("cancelled");
    expect(FakeXhr.requests).toHaveLength(0);
  });
});

describe("asking Mariner", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("says that Mariner could not be reached when the request fails", async () => {
    // What a browser throws is in its own words and language.
    globalThis.fetch = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));

    const failure = await api.listFiles(".").catch((error) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.code).toBe("network");
    expect(failure.status).toBe(0);
  });
});
