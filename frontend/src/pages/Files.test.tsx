import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
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
    expect(api.uploadFile).toHaveBeenCalledWith(expect.any(File), ".");
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
});
