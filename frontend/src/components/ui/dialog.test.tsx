import { describe, it, expect } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./dialog";

function Opened({ removeOpener = false }: { removeOpener?: boolean }) {
  const [open, setOpen] = useState(false);
  const [gone, setGone] = useState(false);
  return (
    <>
      <main id="content" tabIndex={-1}>
        {!gone && (
          <button
            onClick={() => {
              setOpen(true);
              if (removeOpener) setTimeout(() => setGone(true));
            }}
          >
            open
          </button>
        )}
      </main>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle>Question</DialogTitle>
          <DialogDescription>Text</DialogDescription>
          {/* As the field of a new folder does: it takes focus the
              moment it is shown. */}
          <input autoFocus aria-label="name" />
          <button onClick={() => setOpen(false)}>shut</button>
        </DialogContent>
      </Dialog>
    </>
  );
}

describe("Dialog", () => {
  it("gives focus back to what opened it", async () => {
    // Opened by the page, not by a trigger of its own: left alone, focus
    // would fall to the top of the page.
    render(<Opened />);
    const opener = screen.getByRole("button", { name: "open" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(await screen.findByRole("button", { name: "shut" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("gives focus to the content when what opened it is gone", async () => {
    render(<Opened removeOpener />);
    const opener = screen.getByRole("button", { name: "open" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(await screen.findByRole("button", { name: "shut" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
  });

  it("names its button to close in the page's language", async () => {
    render(<Opened />);
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    expect(
      await screen.findByRole("button", { name: "Close" }),
    ).toBeInTheDocument();
  });

  it("stays open when a message shown above it is dismissed", async () => {
    // A message says why something was refused: closing it must not also
    // close what the reader was doing.
    render(
      <>
        <Opened />
        <ol data-sonner-toaster>
          <li>
            <button>dismiss</button>
          </li>
        </ol>
        <button>elsewhere</button>
      </>,
    );
    fireEvent.click(screen.getByText("open"));
    await screen.findByRole("dialog");
    // The dialog starts listening a moment after it is shown.
    await new Promise((resolve) => setTimeout(resolve, 20));

    fireEvent.pointerDown(screen.getByText("dismiss"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("dialog")).toBeInTheDocument();

    // Anywhere else still closes it.
    fireEvent.pointerDown(screen.getByText("elsewhere"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
