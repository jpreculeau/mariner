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
  fireEvent.click(screen.getByRole("button", { name: "Shut down or restart" }));
  fireEvent.click(await screen.findByText("Shut down"));
  fireEvent.click(await screen.findByText("Confirm shutdown?"));
}

describe("PowerMenu", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
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

  it("says aloud that a second press is asked for", async () => {
    // The name of a button that has focus is not read again when it
    // changes: unheard, a second Enter would switch the computer off.
    render(<PowerMenu />);
    fireEvent.click(
      screen.getByRole("button", { name: "Shut down or restart" }),
    );
    const status = await screen.findByRole("status");
    expect(status).toBeEmptyDOMElement();

    fireEvent.click(await screen.findByText("Shut down"));

    expect(status).toHaveTextContent("Press again to shut the computer down.");
  });

  it("says that the computer is going down", async () => {
    vi.spyOn(api, "hostReboot").mockResolvedValue();
    render(<PowerMenu />);
    fireEvent.click(
      screen.getByRole("button", { name: "Shut down or restart" }),
    );
    fireEvent.click(await screen.findByText("Restart"));
    fireEvent.click(await screen.findByText("Confirm restart?"));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "The computer is restarting. This page comes back by itself.",
      ),
    );
  });

  it("is a named place, in the page's language", async () => {
    render(<PowerMenu />);
    fireEvent.click(
      screen.getByRole("button", { name: "Shut down or restart" }),
    );
    expect(
      await screen.findByRole("dialog", { name: "Shut down or restart" }),
    ).toBeInTheDocument();
  });

  it("takes a connection that drops for the computer going down", async () => {
    // It is what a computer that shuts down does.
    vi.spyOn(api, "hostShutdown").mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    await confirmShutdown();

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "The computer is shutting down.",
      ),
    );
    expect(toast.error).not.toHaveBeenCalled();
  });
});
