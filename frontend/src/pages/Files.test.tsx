import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Files from "./Files";
import { api, ApiError } from "@/lib/api";
import { toast } from "@/components/ui/sonner";

vi.mock("@/components/ui/sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

function renderFiles() {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Files />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return container.querySelector('input[type="file"]') as HTMLInputElement;
}

function pick(input: HTMLInputElement, file: File) {
  fireEvent.change(input, { target: { files: [file] } });
}

describe("Files", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.error).mockClear();
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
    expect(api.uploadFile).toHaveBeenCalledWith(expect.any(File), ".", {
      ignoreUnreachablePrinter: false,
    });
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
      expect(api.uploadFile).toHaveBeenLastCalledWith(file, ".", {
        ignoreUnreachablePrinter: true,
      });
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
      expect(api.uploadFile).toHaveBeenLastCalledWith(file, ".", {
        ignoreUnreachablePrinter: true,
      });
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
});
