import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Files from "./Files";
import { UploadProvider } from "@/components/UploadProvider";
import { UploadStatus } from "@/components/UploadStatus";
import { api, ApiError } from "@/lib/api";
import { toast } from "@/components/ui/sonner";

vi.mock("@/components/ui/sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

function renderFiles() {
  const { container } = render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <UploadProvider>
          <UploadStatus />
          <Files />
        </UploadProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return container.querySelector('input[type="file"]') as HTMLInputElement;
}

/** The page's main area, where focus goes when it has nowhere else. */
function withContent(): HTMLElement {
  const content = document.createElement("main");
  content.id = "content";
  content.tabIndex = -1;
  document.body.appendChild(content);
  return content;
}

function pick(input: HTMLInputElement, file: File) {
  fireEvent.change(input, { target: { files: [file] } });
}

describe("Files", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
    vi.spyOn(api, "listFiles").mockResolvedValue({
      directories: [],
      files: [],
    });
  });

  it("uploads the chosen file and refreshes the list", async () => {
    vi.spyOn(api, "uploadFile").mockResolvedValue();
    const input = renderFiles();
    await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));

    pick(input, new File(["x"], "model.ctb"));

    await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(2));
    expect(api.uploadFile).toHaveBeenCalledWith(
      expect.any(File),
      ".",
      { ignoreUnreachablePrinter: false },
      expect.any(Function),
      expect.any(AbortSignal),
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("shows why an upload was refused", async () => {
    vi.spyOn(api, "uploadFile").mockRejectedValue(
      new ApiError(
        409,
        "The printer did not say whether model.ctb is being printed.",
        "printer_not_answering",
      ),
    );
    const input = renderFiles();
    await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));

    pick(input, new File(["x"], "model.ctb"));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "The printer did not say whether model.ctb is being printed.",
      ),
    );
    // Nothing changed on the server, so the list is not fetched again.
    expect(api.listFiles).toHaveBeenCalledTimes(1);
  });

  it("takes one upload at a time", async () => {
    // With a silent printer the answer takes seconds. A second upload sent
    // meanwhile could have its question replace the first one's unseen.
    let finish: () => void = () => {};
    vi.spyOn(api, "uploadFile").mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const input = renderFiles();
    await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));
    const button = screen.getByRole("button", { name: "Upload a file" });

    pick(input, new File(["x"], "first.ctb"));
    await waitFor(() =>
      expect(button).toHaveAttribute("aria-disabled", "true"),
    );
    pick(input, new File(["x"], "second.ctb"));
    finish();

    await waitFor(() =>
      expect(button).not.toHaveAttribute("aria-disabled", "true"),
    );
    expect(api.uploadFile).toHaveBeenCalledTimes(1);
  });

  it("lets the same file be picked again after a refusal", async () => {
    // A file input reports no change when the same file is chosen twice,
    // unless it was emptied in between.
    vi.spyOn(api, "uploadFile").mockRejectedValue(
      new ApiError(409, "model.ctb is being printed.", "file_in_use"),
    );
    const input = renderFiles();
    await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));
    Object.defineProperty(input, "value", {
      value: "model.ctb",
      writable: true,
    });

    pick(input, new File(["x"], "model.ctb"));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(input.value).toBe("");
  });

  describe("when the printer does not answer", () => {
    const refusal = new ApiError(
      409,
      "The printer is not answering.",
      "printer_not_answering",
      "Printer Not Answering",
      true,
    );

    it("asks before replacing anyway", async () => {
      vi.spyOn(api, "uploadFile").mockRejectedValue(refusal);
      const input = renderFiles();
      await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));

      pick(input, new File(["x"], "model.ctb"));

      expect(await screen.findByText("Replace anyway")).toBeTruthy();
      expect(screen.getByText("The printer is not answering.")).toBeTruthy();
      expect(api.uploadFile).toHaveBeenCalledTimes(1);
      expect(toast.error).not.toHaveBeenCalled();
    });

    it("sends the same file with the override once confirmed", async () => {
      vi.spyOn(api, "uploadFile")
        .mockRejectedValueOnce(refusal)
        .mockResolvedValueOnce();
      const input = renderFiles();
      await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));
      const file = new File(["x"], "model.ctb");

      pick(input, file);
      fireEvent.click(await screen.findByText("Replace anyway"));

      await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(2));
      expect(api.uploadFile).toHaveBeenLastCalledWith(
        file,
        ".",
        { ignoreUnreachablePrinter: true },
        expect.any(Function),
        expect.any(AbortSignal),
      );
      expect(screen.queryByText("Replace anyway")).toBeNull();
    });

    it("sends nothing more when the user backs out", async () => {
      vi.spyOn(api, "uploadFile").mockRejectedValue(refusal);
      const input = renderFiles();
      await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));

      pick(input, new File(["x"], "model.ctb"));
      fireEvent.click(await screen.findByText("Cancel"));

      await waitFor(() =>
        expect(screen.queryByText("Replace anyway")).toBeNull(),
      );
      expect(api.uploadFile).toHaveBeenCalledTimes(1);
      expect(api.listFiles).toHaveBeenCalledTimes(1);
    });

    it("takes no other upload while the confirmed one is under way", async () => {
      // The slowest path of all: the printer is asked again, then the
      // file is sent again.
      let finish: () => void = () => {};
      vi.spyOn(api, "uploadFile")
        .mockRejectedValueOnce(refusal)
        .mockReturnValueOnce(
          new Promise<void>((resolve) => {
            finish = resolve;
          }),
        );
      const input = renderFiles();
      await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));
      const button = screen.getByRole("button", { name: "Upload a file" });

      pick(input, new File(["x"], "model.ctb"));
      fireEvent.click(await screen.findByText("Replace anyway"));
      await waitFor(() =>
        expect(button).toHaveAttribute("aria-disabled", "true"),
      );
      pick(input, new File(["x"], "other.ctb"));
      finish();

      await waitFor(() =>
        expect(button).not.toHaveAttribute("aria-disabled", "true"),
      );
      expect(api.uploadFile).toHaveBeenCalledTimes(2);
    });

    it("does not ask twice about the same upload", async () => {
      // The printer is still silent when the confirmed upload is moved
      // into place, and the server says so again.
      vi.spyOn(api, "uploadFile").mockRejectedValue(refusal);
      const input = renderFiles();
      await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));

      pick(input, new File(["x"], "model.ctb"));
      fireEvent.click(await screen.findByText("Replace anyway"));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "The printer is not answering.",
        ),
      );
      expect(screen.queryByText("Replace anyway")).toBeNull();
      expect(api.uploadFile).toHaveBeenCalledTimes(2);
    });

    it("sends the file to the folder it was meant for", async () => {
      // The user opens another folder while the question is on screen.
      vi.mocked(api.listFiles).mockResolvedValue({
        directories: [{ dirname: "batch" }],
        files: [],
      });
      vi.spyOn(api, "uploadFile")
        .mockRejectedValueOnce(refusal)
        .mockResolvedValueOnce();
      const input = renderFiles();
      const file = new File(["x"], "model.ctb");

      pick(input, file);
      const confirm = await screen.findByText("Replace anyway");
      fireEvent.click(await screen.findByText("batch"));
      await waitFor(() =>
        expect(api.listFiles).toHaveBeenLastCalledWith("batch"),
      );
      fireEvent.click(confirm);

      await waitFor(() => expect(api.uploadFile).toHaveBeenCalledTimes(2));
      expect(api.uploadFile).toHaveBeenLastCalledWith(
        file,
        ".",
        { ignoreUnreachablePrinter: true },
        expect.any(Function),
        expect.any(AbortSignal),
      );
    });

    it("shows why the confirmed upload was refused after all", async () => {
      vi.spyOn(api, "uploadFile")
        .mockRejectedValueOnce(refusal)
        .mockRejectedValueOnce(
          new ApiError(409, "model.ctb is being printed.", "file_in_use"),
        );
      const input = renderFiles();
      await waitFor(() => expect(api.listFiles).toHaveBeenCalledTimes(1));

      pick(input, new File(["x"], "model.ctb"));
      fireEvent.click(await screen.findByText("Replace anyway"));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("model.ctb is being printed."),
      );
      expect(screen.queryByText("Replace anyway")).toBeNull();
    });
  });

  describe("while a file is being sent", () => {
    it("shows how far the upload is, and says when it is done", async () => {
      let report: (fraction: number) => void = () => {};
      let finish: () => void = () => {};
      vi.spyOn(api, "uploadFile").mockImplementation(
        (_file, _path, _options, onProgress) => {
          report = onProgress!;
          return new Promise<void>((resolve) => (finish = resolve));
        },
      );
      const input = renderFiles();
      pick(input, new File(["x"], "dragon.ctb"));

      const bar = await screen.findByRole("progressbar", {
        name: "Upload progress",
      });
      act(() => report(0.42));
      expect(bar).toHaveAttribute("aria-valuenow", "42");
      expect(screen.getByText("Uploading dragon.ctb: 42%")).toBeInTheDocument();

      await act(async () => finish());

      await waitFor(() =>
        expect(toast.success).toHaveBeenCalledWith("dragon.ctb uploaded"),
      );
      expect(screen.queryByRole("progressbar")).toBeNull();
    });

    it("says how far it is to those who cannot see the bar, a quarter at a time", async () => {
      let report: (fraction: number) => void = () => {};
      vi.spyOn(api, "uploadFile").mockImplementation(
        (_file, _path, _options, onProgress) => {
          report = onProgress!;
          return new Promise<void>(() => {});
        },
      );
      const input = renderFiles();
      pick(input, new File(["x"], "dragon.ctb"));
      await screen.findByRole("progressbar");
      const said = () =>
        screen
          .getAllByRole("status")
          .map((status) => status.textContent)
          .filter((text) => text?.includes("dragon.ctb"));

      expect(said()).toEqual(["Uploading dragon.ctb: 0%"]);
      // Not at every step: it would never stop talking.
      act(() => report(0.1));
      act(() => report(0.2));
      expect(said()).toEqual(["Uploading dragon.ctb: 0%"]);
      act(() => report(0.26));
      expect(said()).toEqual(["Uploading dragon.ctb: 25%"]);
      act(() => report(0.8));
      expect(said()).toEqual(["Uploading dragon.ctb: 75%"]);
    });

    it("can be given up", async () => {
      let given: AbortSignal | undefined;
      vi.spyOn(api, "uploadFile").mockImplementation(
        (_file, _path, _options, _onProgress, signal) => {
          given = signal;
          return new Promise<void>((_resolve, reject) => {
            signal!.addEventListener("abort", () =>
              reject(new ApiError(0, "Upload cancelled.", "cancelled")),
            );
          });
        },
      );
      const input = renderFiles();
      pick(input, new File(["x"], "dragon.ctb"));

      fireEvent.click(
        await screen.findByRole("button", { name: "Cancel the upload" }),
      );

      expect(given!.aborted).toBe(true);
      await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull());
      // Said as what the reader did, not as something that went wrong.
      expect(toast.error).not.toHaveBeenCalled();
      expect(toast.success).toHaveBeenCalledWith("Upload cancelled");
      // And another file can be sent.
      expect(
        screen.getByRole("button", { name: "Upload a file" }),
      ).not.toHaveAttribute("aria-disabled", "true");
    });

    it("warns before the page is left, and only then", async () => {
      // Leaving the page drops the upload.
      const leaving = () => {
        const event = new Event("beforeunload", { cancelable: true });
        window.dispatchEvent(event);
        return event.defaultPrevented;
      };
      let finish: () => void = () => {};
      vi.spyOn(api, "uploadFile").mockReturnValue(
        new Promise<void>((resolve) => (finish = resolve)),
      );
      const input = renderFiles();
      expect(leaving()).toBe(false);

      pick(input, new File(["x"], "dragon.ctb"));
      await screen.findByRole("progressbar");
      expect(leaving()).toBe(true);

      await act(async () => finish());
      await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull());
      expect(leaving()).toBe(false);
    });

    it("removes the bar when the upload is refused", async () => {
      vi.spyOn(api, "uploadFile").mockRejectedValue(
        new ApiError(507, "No room.", "upload_not_stored"),
      );
      const input = renderFiles();
      pick(input, new File(["x"], "dragon.ctb"));

      await waitFor(() => expect(toast.error).toHaveBeenCalledWith("No room."));
      expect(screen.queryByRole("progressbar")).toBeNull();
      expect(toast.success).not.toHaveBeenCalled();
    });
  });

  it("lets any file be picked: the server says which kinds it takes", () => {
    // The kinds of file a printer takes are not kinds a phone knows: told
    // to offer only those, some phones offer none.
    expect(renderFiles().accept).toBe("");
  });

  it("says that the files could not be listed, and lets the reader try again", async () => {
    vi.spyOn(api, "listFiles").mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    renderFiles();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The files could not be listed");
    expect(alert).toHaveTextContent("cannot be reached");

    vi.mocked(api.listFiles).mockResolvedValue({
      directories: [],
      files: [],
    });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(
      await screen.findByText("This folder is empty."),
    ).toBeInTheDocument();
  });

  it("names its buttons whatever the width of the screen", () => {
    // On a phone only the icons show.
    renderFiles();
    expect(
      screen.getByRole("button", { name: "New folder" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Upload a file" }),
    ).toBeInTheDocument();
  });

  it("labels the name of a new folder", async () => {
    renderFiles();
    fireEvent.click(screen.getByRole("button", { name: "New folder" }));
    expect(await screen.findByLabelText("Folder name")).toBeInTheDocument();
  });

  it("says why a folder could not be made, by the field it is about", async () => {
    // Not in a passing message at the foot of the screen, under the
    // keyboard of a phone.
    vi.spyOn(api, "createDirectory").mockRejectedValue(
      new ApiError(
        400,
        "A folder of this name is already there.",
        "folder_exists",
      ),
    );
    renderFiles();
    fireEvent.click(screen.getByRole("button", { name: "New folder" }));
    const field = await screen.findByLabelText("Folder name");
    expect(field).not.toHaveAttribute("aria-invalid", "true");
    fireEvent.change(field, { target: { value: "prints" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A folder of this name is already there.");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(
      "A folder of this name is already there.",
    );
    expect(toast.error).not.toHaveBeenCalled();

    // Gone as soon as the name is changed.
    fireEvent.change(field, { target: { value: "prints2" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(field).not.toHaveAttribute("aria-invalid", "true");
  });

  it("tells a file that can be printed from one that cannot, in words", async () => {
    vi.mocked(api.listFiles).mockResolvedValue({
      directories: [{ dirname: "batch" }],
      files: [
        {
          filename: "dragon.ctb",
          path: "dragon.ctb",
          can_be_printed: true,
          print_time_secs: 7200,
        },
        { filename: "notes.txt", path: "notes.txt", can_be_printed: false },
      ],
    });
    renderFiles();

    const printable = await screen.findByRole("button", {
      name: /dragon\.ctb/,
    });
    expect(printable).toHaveTextContent("Printable");
    expect(printable).toHaveAccessibleName(/Print time: 2h 0m/);
    expect(
      screen.getByRole("button", { name: /notes\.txt/ }),
    ).not.toHaveTextContent("Printable");
    expect(
      screen.getByRole("button", { name: "Open folder batch" }),
    ).toBeInTheDocument();
  });

  it("puts focus on the list, named by its folder, when a folder is opened", async () => {
    // The row that was pressed is gone with the list it was in.
    vi.mocked(api.listFiles).mockImplementation((path = ".") =>
      Promise.resolve(
        path === "."
          ? { directories: [{ dirname: "batch" }], files: [] }
          : { directories: [], files: [] },
      ),
    );
    renderFiles();
    const folder = await screen.findByRole("button", {
      name: "Open folder batch",
    });
    folder.focus();
    fireEvent.click(folder);

    const list = await screen.findByRole("region", { name: "Folder: /batch" });
    await waitFor(() => expect(list).toHaveFocus());

    // And when going back up.
    const up = screen.getByRole("button", { name: "Up to the folder above" });
    up.focus();
    fireEvent.click(up);
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Folder: /" })).toHaveFocus(),
    );
  });

  it("leaves focus alone when the list is first shown", async () => {
    renderFiles();
    await screen.findByText("This folder is empty.");
    expect(screen.getByRole("region", { name: "Folder: /" })).not.toHaveFocus();
  });

  it("offers the way up when a folder cannot be listed", async () => {
    // Removed elsewhere, say: without it there is no way out but to
    // reload the page.
    vi.mocked(api.listFiles).mockImplementation((path = ".") =>
      path === "."
        ? Promise.resolve({ directories: [{ dirname: "batch" }], files: [] })
        : Promise.reject(new ApiError(404, "API error: 404")),
    );
    renderFiles();
    fireEvent.click(
      await screen.findByRole("button", { name: "Open folder batch" }),
    );
    await screen.findByRole("alert");

    fireEvent.click(
      screen.getByRole("button", { name: "Up to the folder above" }),
    );

    expect(
      await screen.findByRole("button", { name: "Open folder batch" }),
    ).toBeInTheDocument();
  });

  it("says that the file is being finished once all of it is sent", async () => {
    // The server still has it to check and store: "100%" for ten seconds
    // looks like something stuck.
    let report: (fraction: number) => void = () => {};
    vi.spyOn(api, "uploadFile").mockImplementation(
      (_file, _path, _options, onProgress) => {
        report = onProgress!;
        return new Promise<void>(() => {});
      },
    );
    const input = renderFiles();
    pick(input, new File(["x"], "dragon.ctb"));
    await screen.findByRole("progressbar");

    act(() => report(1));

    expect(screen.getAllByText("Finishing dragon.ctb…").length).toBeGreaterThan(
      0,
    );
  });

  it("keeps the keyboard's place when trying again fails again", async () => {
    // The button pressed goes with the message it was in.
    // As over a network: not so fast that the page never shows it is
    // asking.
    vi.mocked(api.listFiles).mockImplementation(
      () =>
        new Promise((_resolve, reject) =>
          setTimeout(() => reject(new ApiError(500, "x")), 10),
        ),
    );
    renderFiles();
    const again = await screen.findByRole("button", { name: "Try again" });
    again.focus();

    fireEvent.click(again);

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("region", { name: "Folder: /" }),
      ),
    );
  });

  it("keeps the keyboard's place in a folder that cannot be listed", async () => {
    vi.mocked(api.listFiles).mockImplementation((path = ".") =>
      path === "."
        ? Promise.resolve({ directories: [{ dirname: "batch" }], files: [] })
        : Promise.reject(new ApiError(500, "x")),
    );
    renderFiles();
    const folder = await screen.findByRole("button", {
      name: "Open folder batch",
    });
    folder.focus();
    fireEvent.click(folder);
    await screen.findByRole("alert");

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("region", { name: "Folder: /batch" }),
      ),
    );
  });

  it("does not take focus when the list is shown with none lost", async () => {
    vi.mocked(api.listFiles).mockResolvedValue({ directories: [], files: [] });
    renderFiles();
    await screen.findByText("This folder is empty.");
    expect(document.activeElement).toBe(document.body);
  });

  it("gives focus a place to go when the upload it was on is over", async () => {
    const content = withContent();
    try {
      vi.spyOn(api, "uploadFile").mockImplementation(
        (_file, _path, _options, _onProgress, signal) =>
          new Promise<void>((_resolve, reject) => {
            signal!.addEventListener("abort", () =>
              reject(new ApiError(0, "Upload cancelled.", "cancelled")),
            );
          }),
      );
      const input = renderFiles();
      pick(input, new File(["x"], "dragon.ctb"));
      const giveUp = await screen.findByRole("button", {
        name: "Cancel the upload",
      });
      giveUp.focus();

      fireEvent.click(giveUp);

      await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull());
      expect(document.activeElement).toBe(content);
    } finally {
      content.remove();
    }
  });

  it("lets a long way up wrap rather than run off a narrow screen", async () => {
    vi.mocked(api.listFiles).mockImplementation((path = ".") =>
      path === "."
        ? Promise.resolve({ directories: [{ dirname: "batch" }], files: [] })
        : Promise.reject(new ApiError(404, "x")),
    );
    renderFiles();
    fireEvent.click(
      await screen.findByRole("button", { name: "Open folder batch" }),
    );
    await screen.findByRole("alert");
    expect(
      screen.getByRole("button", { name: "Up to the folder above" }),
    ).toHaveClass("whitespace-normal");
  });

  it("goes back to the name of a folder that was refused", async () => {
    vi.spyOn(api, "createDirectory").mockRejectedValue(
      new ApiError(400, "A folder of this name is already there."),
    );
    renderFiles();
    fireEvent.click(screen.getByRole("button", { name: "New folder" }));
    const name = await screen.findByLabelText("Folder name");
    fireEvent.change(name, { target: { value: "batch" } });
    const create = screen.getByRole("button", { name: "Create" });
    create.focus();

    fireEvent.click(create);

    // Not switched off while it works: that would drop the focus it has.
    expect(create).not.toBeDisabled();
    await screen.findByRole("alert");
    expect(document.activeElement).toBe(name);
  });
});
