import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PrintControls } from "./PrintControls";

function controls(
  overrides: Partial<Parameters<typeof PrintControls>[0]> = {},
) {
  const props = {
    status: "printing" as const,
    fileName: "dragon.ctb",
    progress: 39.6,
    onPause: vi.fn().mockResolvedValue(undefined),
    onResume: vi.fn().mockResolvedValue(undefined),
    onCancel: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  render(<PrintControls {...props} />);
  return props;
}

const button = (name: string | RegExp) => screen.getByRole("button", { name });

describe("PrintControls", () => {
  it("offers to pause a print under way", () => {
    controls();
    expect(button("Pause")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });

  it("offers to resume a paused print", () => {
    controls({ status: "paused" });
    expect(button("Resume")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("offers to cancel a print under way or paused", () => {
    controls({ status: "paused" });
    expect(button("Cancel print")).toBeInTheDocument();
  });

  it("pauses when asked", async () => {
    const { onPause } = controls();
    fireEvent.click(button("Pause"));
    await waitFor(() => expect(onPause).toHaveBeenCalledTimes(1));
  });

  it("resumes when asked", async () => {
    const { onResume } = controls({ status: "paused" });
    fireEvent.click(button("Resume"));
    await waitFor(() => expect(onResume).toHaveBeenCalledTimes(1));
  });

  it("asks before cancelling, naming the file and what would be lost", async () => {
    const { onCancel } = controls();
    fireEvent.click(button("Cancel print"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Cancel this print?");
    expect(dialog).toHaveTextContent("dragon.ctb");
    expect(dialog).toHaveTextContent("39.6%");
    expect(dialog).toHaveTextContent("cannot be resumed");
    // Nothing is cancelled by the first press.
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("cancels nothing when the reader backs out", async () => {
    const { onCancel } = controls();
    fireEvent.click(button("Cancel print"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Do not cancel" }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("cancels once confirmed", async () => {
    const { onCancel } = controls();
    fireEvent.click(button("Cancel print"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel the print" }),
    );

    await waitFor(() => expect(onCancel).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("sends a command once however often the button is pressed", async () => {
    let done: () => void = () => {};
    const onPause = vi.fn(
      () => new Promise<void>((resolve) => (done = resolve)),
    );
    controls({ onPause });

    fireEvent.click(button("Pause"));
    // Said while it lasts, and nothing else can be asked meanwhile.
    const waiting = await screen.findByRole("button", { name: "Pausing…" });
    expect(waiting).toHaveAttribute("aria-disabled", "true");
    expect(button("Cancel print")).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(waiting);
    expect(onPause).toHaveBeenCalledTimes(1);

    done();
    await waitFor(() =>
      expect(button("Pause")).not.toHaveAttribute("aria-disabled", "true"),
    );
  });

  it("can be used again after a command that failed", async () => {
    const onPause = vi.fn().mockRejectedValue(new Error("refused"));
    controls({ onPause });

    fireEvent.click(button("Pause"));

    await waitFor(() => expect(onPause).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(button("Pause")).not.toHaveAttribute("aria-disabled", "true"),
    );
  });

  it("keeps focus on the button that was pressed while its command lasts", async () => {
    // Switched off, a button drops focus to the top of the page.
    let done: () => void = () => {};
    const onPause = vi.fn(
      () => new Promise<void>((resolve) => (done = resolve)),
    );
    controls({ onPause });
    const pause = button("Pause");
    pause.focus();
    fireEvent.click(pause);

    const waiting = await screen.findByRole("button", { name: "Pausing…" });
    expect(waiting).toHaveFocus();
    done();
    await waitFor(() => expect(button("Pause")).toHaveFocus());
  });
});
