import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
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

  it("never says that the computer is going down on a failure", async () => {
    vi.spyOn(api, "hostShutdown").mockRejectedValue(
      new TypeError("Failed to fetch"),
    );
    await confirmShutdown();
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
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

  it("does not say that the computer is going down when nothing answered", async () => {
    // The computer answers before it goes down. No answer more often
    // means it was never asked, and told otherwise the reader pulls the
    // plug on a computer that is running.
    vi.spyOn(api, "hostShutdown").mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    await confirmShutdown();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Mariner did not answer: the computer may be going down, or may not have been asked. Check before unplugging it.",
      ),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("asks once when the button is pressed twice in one go", async () => {
    const shutdown = vi
      .spyOn(api, "hostShutdown")
      .mockReturnValue(new Promise(() => {}));
    render(<PowerMenu />);
    fireEvent.click(
      screen.getByRole("button", { name: "Shut down or restart" }),
    );
    fireEvent.click(await screen.findByText("Shut down"));
    const confirm = await screen.findByText("Confirm shutdown?");

    act(() => {
      confirm.click();
      confirm.click();
    });

    expect(shutdown).toHaveBeenCalledTimes(1);
    // And says that it is asking, to those who do not see it too.
    const busy = await screen.findByRole("button", { name: "Shutting down…" });
    expect(busy).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Shutting down…");
    // The other choice waits: it is not armed for a press that would
    // then do nothing.
    const other = screen.getByRole("button", { name: "Restart" });
    expect(other).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(other);
    expect(screen.getByRole("button", { name: "Restart" })).toBe(other);
    expect(screen.getByRole("status")).toHaveTextContent("Shutting down…");
  });

  it("says that it is asking the computer to restart", async () => {
    vi.spyOn(api, "hostReboot").mockReturnValue(new Promise(() => {}));
    render(<PowerMenu />);
    fireEvent.click(
      screen.getByRole("button", { name: "Shut down or restart" }),
    );
    fireEvent.click(await screen.findByText("Restart"));
    fireEvent.click(await screen.findByText("Confirm restart?"));

    expect(
      await screen.findByRole("button", { name: "Restarting…" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Restarting…");
  });
});
