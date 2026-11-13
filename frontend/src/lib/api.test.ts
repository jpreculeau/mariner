import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  api,
  ApiError,
  mapPrinterState,
  formatFileSize,
  shouldRetry,
} from "./api";

describe("mapPrinterState", () => {
  it("maps PRINTING to printing", () => {
    expect(mapPrinterState("PRINTING")).toBe("printing");
  });

  it("maps STARTING_PRINT to printing", () => {
    expect(mapPrinterState("STARTING_PRINT")).toBe("printing");
  });

  it("maps PAUSED to paused", () => {
    expect(mapPrinterState("PAUSED")).toBe("paused");
  });

  it("maps CLOSED to offline", () => {
    expect(mapPrinterState("CLOSED")).toBe("offline");
  });

  it("maps IDLE to idle", () => {
    expect(mapPrinterState("IDLE")).toBe("idle");
  });

  it("maps unknown states to idle", () => {
    expect(mapPrinterState("UNKNOWN")).toBe("idle");
  });
});

describe("formatFileSize", () => {
  it("formats bytes", () => {
    expect(formatFileSize(512)).toBe("512 B");
  });

  it("formats kilobytes", () => {
    expect(formatFileSize(2048)).toBe("2.0 KB");
  });

  it("formats megabytes", () => {
    expect(formatFileSize(48_200_000)).toBe("46.0 MB");
  });
});

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches print status", async () => {
    const mockResponse = {
      state: "IDLE",
      selected_file: "",
      progress: 0,
    };
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    } as Response);

    const result = await api.printStatus();
    expect(result).toEqual(mockResponse);
    expect(fetch).toHaveBeenCalledWith("/api/print_status", expect.any(Object));
  });

  it("fetches file list with path", async () => {
    const mockResponse = { files: [], directories: [] };
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    } as Response);

    await api.listFiles("subdir");
    expect(fetch).toHaveBeenCalledWith(
      "/api/list_files?path=subdir",
      expect.any(Object),
    );
  });

  it("throws on non-ok response", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    } as Response);

    await expect(api.printStatus()).rejects.toThrow("API error: 500");
  });

  it("throws the explanation the server gave", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "CONFLICT",
      json: () =>
        Promise.resolve({
          code: "file_in_use",
          title: "File In Use",
          description: "model.ctb is in use by the print in progress.",
        }),
    } as Response);

    const error = await api.deleteFile("model.ctb").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("model.ctb is in use by the print in progress.");
    expect(error.status).toBe(409);
    expect(error.code).toBe("file_in_use");
  });

  it("sends CSRF token from meta tag", async () => {
    const meta = document.createElement("meta");
    meta.name = "csrf-token";
    meta.content = "test-csrf-token";
    document.head.appendChild(meta);

    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);

    await api.printStatus();
    expect(fetch).toHaveBeenCalledWith(
      "/api/print_status",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-CSRFToken": "test-csrf-token",
        }),
      }),
    );

    document.head.removeChild(meta);
  });

  it("sends what sets the one-time code up as JSON, which the server reads", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    globalThis.fetch = fetchMock;
    await api.confirmCode("287082");
    await api.removeCode("correct horse battery");
    for (const [index, body] of [
      [0, { code: "287082" }],
      [1, { current: "correct horse battery" }],
    ] as const) {
      const sent = fetchMock.mock.calls[index][1];
      expect(sent.headers["Content-Type"]).toBe("application/json");
      expect(JSON.parse(sent.body)).toEqual(body);
    }
  });

  describe("when the page's token is out of date", () => {
    // Real answers: what is read of one cannot be read again.
    const json = (status: number, body: unknown) => () =>
      Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );
    const refused = json(400, {
      code: "token_refused",
      title: "Page Out Of Date",
      description: "Reload the page and try again.",
    });
    const newToken = json(200, { csrf_token: "fresh-token" });
    const served = json(200, {});

    it("asks for a new one and sends the request again", async () => {
      const fetchMock = vi
        .fn()
        .mockImplementationOnce(refused)
        .mockImplementationOnce(newToken)
        .mockImplementationOnce(served);
      globalThis.fetch = fetchMock;

      await api.printerCommand("pause_print");

      expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
        "/api/printer/command/pause_print",
        "/api/csrf_token",
        "/api/printer/command/pause_print",
      ]);
      expect(fetchMock.mock.calls[2][1].headers["X-CSRFToken"]).toBe(
        "fresh-token",
      );
      // And keeps it for what follows.
      fetchMock.mockImplementationOnce(served);
      await api.printerCommand("resume_print");
      expect(fetchMock.mock.calls[3][1].headers["X-CSRFToken"]).toBe(
        "fresh-token",
      );
    });

    it("shows what the server said of a refusal it read to tell which", async () => {
      const fetchMock = vi
        .fn()
        .mockImplementationOnce(
          json(400, { code: "folder_too_deep", description: "Too deep." }),
        );
      globalThis.fetch = fetchMock;

      await expect(api.createDirectory(".", "x")).rejects.toMatchObject({
        message: "Too deep.",
      });
    });

    it("tries once only, then says what the server said", async () => {
      const fetchMock = vi
        .fn()
        .mockImplementationOnce(refused)
        .mockImplementationOnce(newToken)
        .mockImplementationOnce(refused);
      globalThis.fetch = fetchMock;

      // The answer was read once already, to tell why it was refused.
      await expect(api.printerCommand("pause_print")).rejects.toMatchObject({
        code: "token_refused",
        message: "Reload the page and try again.",
      });
      expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    it("says what the server said when no new token can be had", async () => {
      const fetchMock = vi
        .fn()
        .mockImplementationOnce(refused)
        .mockImplementationOnce(() => Promise.reject(new Error("offline")));
      globalThis.fetch = fetchMock;

      await expect(api.printerCommand("pause_print")).rejects.toMatchObject({
        code: "token_refused",
      });
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it("does not send again a request refused for another reason", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: "BAD REQUEST",
        json: () =>
          Promise.resolve({
            code: "folder_too_deep",
            description: "Too deep.",
          }),
      });
      globalThis.fetch = fetchMock;

      await expect(api.createDirectory(".", "x")).rejects.toMatchObject({
        code: "folder_too_deep",
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
  });

  it("sends printer commands with POST", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    } as Response);

    await api.printerCommand("pause_print");
    expect(fetch).toHaveBeenCalledWith(
      "/api/printer/command/pause_print",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("sends filename with start_print command", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    } as Response);

    await api.printerCommand("start_print", "test.ctb");
    expect(fetch).toHaveBeenCalledWith(
      "/api/printer/command/start_print?filename=test.ctb",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("generates correct file preview URL", () => {
    expect(api.filePreviewUrl("subdir/test.ctb")).toBe(
      "/api/file_preview?filename=subdir%2Ftest.ctb",
    );
  });

  it("creates a directory with POST", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    } as Response);

    await api.createDirectory("foo/bar", "new_dir");
    expect(fetch).toHaveBeenCalledWith(
      "/api/create_directory?path=foo%2Fbar&name=new_dir",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("says when a refusal can be overridden", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "CONFLICT",
      json: () =>
        Promise.resolve({
          code: "printer_not_answering",
          title: "Printer Not Answering",
          description: "The printer is not answering.",
          can_be_overridden: true,
        }),
    } as Response);

    const error = await api.deleteFile("model.ctb").catch((e) => e);
    expect(error.canBeOverridden).toBe(true);
  });

  it("takes a refusal as final unless the server says otherwise", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "CONFLICT",
      json: () =>
        Promise.resolve({
          code: "file_in_use",
          title: "File In Use",
          description: "model.ctb is in use by the print in progress.",
          can_be_overridden: "yes",
        }),
    } as Response);

    const error = await api.deleteFile("model.ctb").catch((e) => e);
    expect(error.canBeOverridden).toBe(false);
  });

  it("deletes without the override unless asked", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    } as Response);

    await api.deleteFile("a b.ctb");
    expect(fetch).toHaveBeenCalledWith(
      "/api/delete_file?filename=a+b.ctb",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("deletes with the override when asked", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    } as Response);

    await api.deleteFile("model.ctb", { ignoreUnreachablePrinter: true });
    expect(fetch).toHaveBeenCalledWith(
      "/api/delete_file?filename=model.ctb&ignore_unreachable_printer=1",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("asking again after a failure", () => {
  it("does when nothing answered, a few times", () => {
    const down = new ApiError(0, "Mariner cannot be reached.", "network");
    expect(shouldRetry(0, down)).toBe(true);
    expect(shouldRetry(1, down)).toBe(true);
    expect(shouldRetry(3, down)).toBe(false);
    // And on an error of the server's own.
    expect(shouldRetry(0, new ApiError(500, "x"))).toBe(true);
  });

  it("does not when the server said no: it would say so again", () => {
    for (const status of [400, 403, 404, 409]) {
      expect(shouldRetry(0, new ApiError(status, "x"))).toBe(false);
    }
  });
});
