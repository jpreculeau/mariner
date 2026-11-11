import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
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

function renderDialog(onOpenChange = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <FileDetailDialog file={file} open={true} onOpenChange={onOpenChange} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onOpenChange;
}

describe("FileDetailDialog", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.error).mockClear();
  });

  it("closes once the file is deleted", async () => {
    vi.spyOn(api, "deleteFile").mockResolvedValue();
    const onOpenChange = renderDialog();

    fireEvent.click(screen.getByText("Delete"));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.deleteFile).toHaveBeenCalledWith("model.txt");
    expect(toast.error).not.toHaveBeenCalled();
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

    fireEvent.click(screen.getByText("Delete"));

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

      fireEvent.click(screen.getByText("Delete"));

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

      fireEvent.click(screen.getByText("Delete"));
      fireEvent.click(await screen.findByText("Delete anyway"));

      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
      expect(api.deleteFile).toHaveBeenLastCalledWith("model.txt", {
        ignoreUnreachablePrinter: true,
      });
    });

    it("deletes nothing when the user backs out", async () => {
      vi.spyOn(api, "deleteFile").mockRejectedValue(refusal);
      const onOpenChange = renderDialog();

      fireEvent.click(screen.getByText("Delete"));
      fireEvent.click(await screen.findByText("Cancel"));

      await waitFor(() =>
        expect(screen.queryByText("Delete anyway")).toBeNull(),
      );
      expect(api.deleteFile).toHaveBeenCalledTimes(1);
      expect(onOpenChange).not.toHaveBeenCalled();
    });

    it("shows why the confirmed deletion was refused after all", async () => {
      vi.spyOn(api, "deleteFile")
        .mockRejectedValueOnce(refusal)
        .mockRejectedValueOnce(
          new ApiError(409, "model.txt is being printed.", "file_in_use"),
        );
      const onOpenChange = renderDialog();

      fireEvent.click(screen.getByText("Delete"));
      fireEvent.click(await screen.findByText("Delete anyway"));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("model.txt is being printed."),
      );
      expect(screen.queryByText("Delete anyway")).toBeNull();
      expect(onOpenChange).not.toHaveBeenCalled();
    });
  });
});
