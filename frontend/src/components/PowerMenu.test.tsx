import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PowerMenu } from "./PowerMenu";
import { api, ApiError } from "@/lib/api";
import { toast } from "@/components/ui/sonner";

vi.mock("@/components/ui/sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

async function confirmShutdown() {
  render(<PowerMenu />);
  fireEvent.click(screen.getByRole("button"));
  fireEvent.click(await screen.findByText("Shut Down"));
  fireEvent.click(await screen.findByText("Confirm Shutdown?"));
}

describe("PowerMenu", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.error).mockClear();
  });

  it("says so when the host refuses to shut down", async () => {
    vi.spyOn(api, "hostShutdown").mockRejectedValue(
      new ApiError(
        503,
        "The computer did not accept the command.",
        "host_command_refused",
      ),
    );
    await confirmShutdown();
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "The computer did not accept the command.",
      ),
    );
  });

  it("says nothing when the connection drops as the host goes down", async () => {
    vi.spyOn(api, "hostShutdown").mockRejectedValue(
      new TypeError("Failed to fetch"),
    );
    await confirmShutdown();
    await waitFor(() => expect(api.hostShutdown).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalled();
  });
});
