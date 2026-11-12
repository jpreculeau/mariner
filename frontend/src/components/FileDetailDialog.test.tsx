import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { FileDetailDialog } from "./FileDetailDialog";
import { api, ApiError } from "@/lib/api";
import { toast } from "@/components/ui/sonner";

vi.mock("@/components/ui/sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const file = {
  filename: "model.txt",
  path: "model.txt",
  can_be_printed: false,
};

const otherFile = {
  filename: "precious.txt",
  path: "precious.txt",
  can_be_printed: false,
};

const queryClient = new QueryClient();

function dialogFor(shown: typeof file, onOpenChange: () => void) {
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FileDetailDialog
          file={shown}
          open={true}
          onOpenChange={onOpenChange}
        />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderDialog(onOpenChange = vi.fn()) {
  const { rerender } = render(dialogFor(file, onOpenChange));
  // Shows another file in the same dialog, as picking one in the list does.
  showOther = () => rerender(dialogFor(otherFile, onOpenChange));
  return onOpenChange;
}

let showOther: () => void;

/** Ask to delete the file on screen and say yes to the question. */
async function deleteConfirmed() {
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete the file" }),
  );
}

const printable = {
  filename: "dragon.ctb",
  path: "dragon.ctb",
  can_be_printed: true,
};

describe("FileDetailDialog", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
  });

  it("closes once the file is deleted", async () => {
    vi.spyOn(api, "deleteFile").mockResolvedValue();
    const onOpenChange = renderDialog();

    await deleteConfirmed();

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.deleteFile).toHaveBeenCalledWith("model.txt", {
      ignoreUnreachablePrinter: false,
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("refreshes the file list once the file is deleted", async () => {
    vi.spyOn(api, "deleteFile").mockResolvedValue();
    const refresh = vi.spyOn(queryClient, "invalidateQueries");
    const onOpenChange = renderDialog();

    await deleteConfirmed();

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(refresh).toHaveBeenCalledWith({ queryKey: ["files"] });
  });

  it("shows why a deletion was refused and stays open", async () => {
    vi.spyOn(api, "deleteFile").mockRejectedValue(
      new ApiError(
        409,
        "model.txt is in use by the print in progress.",
        "file_in_use",
      ),
    );
    const onOpenChange = renderDialog();

    await deleteConfirmed();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "model.txt is in use by the print in progress.",
      ),
    );
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  describe("when the printer does not answer", () => {
    const refusal = new ApiError(
      409,
      "The printer is not answering.",
      "printer_not_answering",
      "Printer Not Answering",
      true,
    );

    it("asks before deleting anyway", async () => {
      vi.spyOn(api, "deleteFile").mockRejectedValue(refusal);
      const onOpenChange = renderDialog();

      await deleteConfirmed();

      expect(await screen.findByText("Delete anyway")).toBeTruthy();
      expect(screen.getByText("The printer is not answering.")).toBeTruthy();
      expect(api.deleteFile).toHaveBeenCalledTimes(1);
      expect(toast.error).not.toHaveBeenCalled();
      expect(onOpenChange).not.toHaveBeenCalled();
    });

    it("deletes with the override once confirmed", async () => {
      vi.spyOn(api, "deleteFile")
        .mockRejectedValueOnce(refusal)
        .mockResolvedValueOnce();
      const onOpenChange = renderDialog();

      await deleteConfirmed();
      fireEvent.click(await screen.findByText("Delete anyway"));

      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
      expect(api.deleteFile).toHaveBeenLastCalledWith("model.txt", {
        ignoreUnreachablePrinter: true,
      });
    });

    it("deletes nothing when the user backs out", async () => {
      vi.spyOn(api, "deleteFile").mockRejectedValue(refusal);
      const onOpenChange = renderDialog();

      await deleteConfirmed();
      fireEvent.click(await screen.findByText("Cancel"));

      await waitFor(() =>
        expect(screen.queryByText("Delete anyway")).toBeNull(),
      );
      expect(api.deleteFile).toHaveBeenCalledTimes(1);
      expect(onOpenChange).not.toHaveBeenCalled();
    });

    it("drops the question when another file is shown", async () => {
      vi.spyOn(api, "deleteFile")
        .mockRejectedValueOnce(refusal)
        .mockResolvedValue();
      renderDialog();

      await deleteConfirmed();
      await screen.findByText("Delete anyway");
      showOther();

      // The question went away with the file it was about.
      await waitFor(() =>
        expect(screen.queryByText("Delete anyway")).toBeNull(),
      );
      expect(api.deleteFile).toHaveBeenCalledTimes(1);
    });

    it("does not ask about a file the user has moved on from", async () => {
      // The printer takes seconds to give up on; the answer comes late.
      let refuse: (error: ApiError) => void = () => {};
      vi.spyOn(api, "deleteFile").mockReturnValue(
        new Promise<void>((_, reject) => {
          refuse = reject;
        }),
      );
      const onOpenChange = renderDialog();

      await deleteConfirmed();
      showOther();
      refuse(refusal);

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "The printer is not answering.",
        ),
      );
      expect(screen.queryByText("Delete anyway")).toBeNull();
      expect(api.deleteFile).toHaveBeenCalledTimes(1);
      expect(onOpenChange).not.toHaveBeenCalled();
    });

    it("leaves the dialog of another file open when a deletion ends late", async () => {
      let finish: () => void = () => {};
      vi.spyOn(api, "deleteFile").mockReturnValue(
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
      );
      const onOpenChange = renderDialog();

      await deleteConfirmed();
      showOther();
      finish();

      await waitFor(() => expect(api.deleteFile).toHaveBeenCalledTimes(1));
      await Promise.resolve();
      expect(onOpenChange).not.toHaveBeenCalled();
    });

    it("does not ask twice about the same deletion", async () => {
      // The printer is still silent when the confirmed deletion is made,
      // and the server says so again.
      vi.spyOn(api, "deleteFile").mockRejectedValue(refusal);
      renderDialog();

      await deleteConfirmed();
      fireEvent.click(await screen.findByText("Delete anyway"));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "The printer is not answering.",
        ),
      );
      expect(screen.queryByText("Delete anyway")).toBeNull();
      expect(api.deleteFile).toHaveBeenCalledTimes(2);
    });

    it("shows why the confirmed deletion was refused after all", async () => {
      vi.spyOn(api, "deleteFile")
        .mockRejectedValueOnce(refusal)
        .mockRejectedValueOnce(
          new ApiError(409, "model.txt is being printed.", "file_in_use"),
        );
      const onOpenChange = renderDialog();

      await deleteConfirmed();
      fireEvent.click(await screen.findByText("Delete anyway"));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("model.txt is being printed."),
      );
      expect(screen.queryByText("Delete anyway")).toBeNull();
      expect(onOpenChange).not.toHaveBeenCalled();
    });
  });

  describe("before deleting", () => {
    it("asks, naming the file", async () => {
      vi.spyOn(api, "deleteFile").mockResolvedValue();
      renderDialog();

      fireEvent.click(screen.getByRole("button", { name: "Delete" }));

      const question = await screen.findByRole("dialog", {
        name: "Delete this file?",
      });
      expect(question).toHaveTextContent("model.txt will be deleted for good.");
      // Nothing is deleted by the first press.
      expect(api.deleteFile).not.toHaveBeenCalled();
    });

    it("deletes nothing when the reader backs out", async () => {
      vi.spyOn(api, "deleteFile").mockResolvedValue();
      const onOpenChange = renderDialog();

      fireEvent.click(screen.getByRole("button", { name: "Delete" }));
      await screen.findByRole("dialog", { name: "Delete this file?" });
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

      await waitFor(() =>
        expect(screen.queryByText("Delete this file?")).toBeNull(),
      );
      expect(api.deleteFile).not.toHaveBeenCalled();
      // The file's own dialog stays.
      expect(onOpenChange).not.toHaveBeenCalled();
    });

    it("says that the file was deleted", async () => {
      vi.spyOn(api, "deleteFile").mockResolvedValue();
      renderDialog();

      await deleteConfirmed();

      await waitFor(() =>
        expect(toast.success).toHaveBeenCalledWith("model.txt deleted"),
      );
    });

    it("deletes once however often the button is pressed", async () => {
      let done: () => void = () => {};
      vi.spyOn(api, "deleteFile").mockReturnValue(
        new Promise<void>((resolve) => (done = resolve)),
      );
      renderDialog();

      await deleteConfirmed();
      const waiting = await screen.findByRole("button", { name: "Deleting…" });
      expect(waiting).toHaveAttribute("aria-disabled", "true");
      fireEvent.click(waiting);

      expect(api.deleteFile).toHaveBeenCalledTimes(1);
      done();
    });
  });

  describe("starting a print", () => {
    function renderPrintable(onOpenChange = vi.fn()) {
      vi.spyOn(api, "fileDetails").mockResolvedValue({
        filename: "dragon.ctb",
        path: "dragon.ctb",
        bed_size_mm: [68, 120, 150],
        height_mm: 42.5,
        layer_count: 850,
        layer_height_mm: 0.05,
        resolution: [1440, 2560],
        print_time_secs: 7200,
      });
      render(dialogFor(printable, onOpenChange));
      return onOpenChange;
    }

    it("says that the print was started and closes", async () => {
      vi.spyOn(api, "printerCommand").mockResolvedValue();
      const onOpenChange = renderPrintable();

      fireEvent.click(screen.getByRole("button", { name: "Start print" }));

      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
      expect(api.printerCommand).toHaveBeenCalledWith(
        "start_print",
        "dragon.ctb",
      );
      expect(toast.success).toHaveBeenCalledWith("Print started");
    });

    it("says why the print was not started, and stays open", async () => {
      vi.spyOn(api, "printerCommand").mockRejectedValue(
        new ApiError(409, "A print is already under way.", "print_in_progress"),
      );
      const onOpenChange = renderPrintable();

      fireEvent.click(screen.getByRole("button", { name: "Start print" }));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "A print is already under way.",
        ),
      );
      expect(onOpenChange).not.toHaveBeenCalled();
      expect(toast.success).not.toHaveBeenCalled();
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Start print" }),
        ).not.toHaveAttribute("aria-disabled", "true"),
      );
    });

    it("starts one print however often the button is pressed", async () => {
      let done: () => void = () => {};
      vi.spyOn(api, "printerCommand").mockReturnValue(
        new Promise<void>((resolve) => (done = resolve)),
      );
      renderPrintable();

      fireEvent.click(screen.getByRole("button", { name: "Start print" }));
      const waiting = await screen.findByRole("button", { name: "Starting…" });
      expect(waiting).toHaveAttribute("aria-disabled", "true");
      // Nor can the file be deleted while its print is being started.
      expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
      fireEvent.click(waiting);

      expect(api.printerCommand).toHaveBeenCalledTimes(1);
      done();
    });

    it("says what its figures are", async () => {
      renderPrintable();
      expect(await screen.findByText("Layers")).toBeInTheDocument();
      expect(screen.getByText("850")).toBeInTheDocument();
      expect(screen.getByText("Print time")).toBeInTheDocument();
      expect(screen.getByText("42.5 mm")).toBeInTheDocument();
      expect(
        screen.getByRole("img", { name: "Preview of the print" }),
      ).toBeInTheDocument();
    });
  });

  describe("when the file is no longer there", () => {
    const gone = new ApiError(
      404,
      "This file is no longer there.",
      "file_gone",
    );

    it("says so, closes and has the list fetched again", async () => {
      vi.spyOn(api, "deleteFile").mockRejectedValue(gone);
      const invalidate = vi.spyOn(queryClient, "invalidateQueries");
      const onOpenChange = renderDialog();

      await deleteConfirmed();

      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
      expect(toast.error).toHaveBeenCalledWith("This file is no longer there.");
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["files"] });
    });

    it("does the same when a print of it is asked for", async () => {
      vi.spyOn(api, "fileDetails").mockRejectedValue(gone);
      vi.spyOn(api, "printerCommand").mockRejectedValue(gone);
      const invalidate = vi.spyOn(queryClient, "invalidateQueries");
      const onOpenChange = vi.fn();
      render(dialogFor(printable, onOpenChange));

      fireEvent.click(screen.getByRole("button", { name: "Start print" }));

      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
      expect(toast.error).toHaveBeenCalledWith("This file is no longer there.");
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["files"] });
    });
  });

  it("goes to the dashboard once a print is started", async () => {
    vi.spyOn(api, "fileDetails").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "printerCommand").mockResolvedValue();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/files"]}>
          <FileDetailDialog
            file={printable}
            open={true}
            onOpenChange={vi.fn()}
          />
          <Routes>
            <Route path="/" element={<p>the dashboard</p>} />
            <Route path="/files" element={<p>the files</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText("the files")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start print" }));

    expect(await screen.findByText("the dashboard")).toBeInTheDocument();
  });

  it("deletes once when the confirmation is pressed twice in one go", async () => {
    const remove = vi
      .spyOn(api, "deleteFile")
      .mockReturnValue(new Promise(() => {}));
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const confirm = await screen.findByRole("button", {
      name: "Delete the file",
    });

    act(() => {
      confirm.click();
      confirm.click();
    });

    expect(remove).toHaveBeenCalledTimes(1);
  });
});
