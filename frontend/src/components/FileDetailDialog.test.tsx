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
});
