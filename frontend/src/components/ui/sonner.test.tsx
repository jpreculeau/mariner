import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { toast as sonner, Toaster as Shown } from "sonner";
import { toast, Toaster } from "./sonner";

vi.mock("sonner", () => ({
  Toaster: vi.fn(() => null),
  toast: { error: vi.fn(), success: vi.fn(), dismiss: vi.fn() },
}));

describe("toast", () => {
  beforeEach(() => {
    vi.mocked(sonner.error).mockClear();
    document.documentElement.lang = "en";
  });

  it("keeps an error until the reader closes it", () => {
    // A refusal and what to do about it take longer to read than a
    // message stays, and it cannot be asked for again.
    toast.error("No room.");
    const [message, options] = vi.mocked(sonner.error).mock.calls[0];
    expect(message).toBe("No room.");
    expect(options?.duration).toBe(Infinity);
    expect((options?.cancel as { label: string }).label).toBe("Close");
  });

  it("names the button to close it in the page's language", () => {
    document.documentElement.lang = "fr";
    toast.error("Plus de place.");
    const [, options] = vi.mocked(sonner.error).mock.calls[0];
    expect((options?.cancel as { label: string }).label).toBe("Fermer");
  });

  it("lets a success pass by itself", () => {
    toast.success("Done");
    expect(sonner.success).toHaveBeenCalledWith("Done");
  });
});

describe("where messages are shown", () => {
  const screenIs = (narrow: boolean) =>
    vi.stubGlobal("matchMedia", () => ({
      matches: narrow,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));

  it("is at the top on a phone, away from the buttons they are about", () => {
    // At the bottom they sat on Pause, and on the buttons of a dialog.
    screenIs(true);
    render(<Toaster />);
    expect(vi.mocked(Shown).mock.lastCall?.[0].position).toBe("top-center");
  });

  it("is at the bottom right on a wide screen", () => {
    screenIs(false);
    render(<Toaster />);
    expect(vi.mocked(Shown).mock.lastCall?.[0].position).toBe("bottom-right");
  });

  it("shows every message, so that none takes focus unseen", () => {
    // Stacked, those behind could be reached by the keyboard but not
    // seen.
    render(<Toaster />);
    const props = vi.mocked(Shown).mock.lastCall?.[0];
    expect(props?.expand).toBe(true);
    expect(props?.visibleToasts).toBe(9);
  });

  describe("on Escape", () => {
    const shown = document.createElement("ol");
    shown.innerHTML = "<li data-sonner-toast>refused</li>";

    beforeEach(() => vi.mocked(sonner.dismiss).mockClear());

    it("closes the messages: one can cover what the keyboard is on", () => {
      document.body.appendChild(shown);
      try {
        render(<Toaster />);
        fireEvent.keyDown(document.body, { key: "Escape" });
        expect(sonner.dismiss).toHaveBeenCalledTimes(1);
        fireEvent.keyDown(document.body, { key: "Enter" });
        expect(sonner.dismiss).toHaveBeenCalledTimes(1);
      } finally {
        shown.remove();
      }
    });

    it("leaves it to a dialog or a menu that took it", () => {
      document.body.appendChild(shown);
      try {
        render(<Toaster />);
        const taken = (event: Event) => event.preventDefault();
        document.body.addEventListener("keydown", taken);
        fireEvent.keyDown(document.body, { key: "Escape" });
        document.body.removeEventListener("keydown", taken);
        expect(sonner.dismiss).not.toHaveBeenCalled();
      } finally {
        shown.remove();
      }
    });

    it("does nothing when there is no message", () => {
      render(<Toaster />);
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(sonner.dismiss).not.toHaveBeenCalled();
    });
  });
});

describe("closing one message of several", () => {
  it("puts focus on the next rather than nowhere", () => {
    const list = document.createElement("ol");
    list.innerHTML =
      '<li data-sonner-toast tabindex="0">first<button>Close</button></li>' +
      '<li data-sonner-toast tabindex="0">second</li>';
    document.body.appendChild(list);
    try {
      vi.mocked(sonner.error).mockClear();
      toast.error("No room.");
      const [, options] = vi.mocked(sonner.error).mock.calls[0];
      const close = (
        options?.cancel as {
          onClick: (event: { currentTarget: Element }) => void;
        }
      ).onClick;
      const button = list.querySelector("button")!;
      button.focus();

      close({ currentTarget: button });

      expect(document.activeElement).toBe(list.children[1]);
    } finally {
      list.remove();
    }
  });
});

describe("closing the last message", () => {
  const list = document.createElement("ol");
  list.setAttribute("data-sonner-toaster", "");
  const row = document.createElement("button");

  beforeEach(() => {
    list.innerHTML =
      '<li data-sonner-toast tabindex="0">only<button>Close</button></li>';
    document.body.append(row, list);
    vi.mocked(sonner.error).mockClear();
    vi.mocked(sonner.dismiss).mockClear();
  });
  afterEach(() => {
    list.remove();
    row.remove();
  });

  const closeOf = () => {
    toast.error("No room.");
    const [, options] = vi.mocked(sonner.error).mock.calls[0];
    return (
      options?.cancel as {
        onClick: (event: { currentTarget: Element }) => void;
      }
    ).onClick;
  };

  it("puts focus back where it was before the messages", () => {
    // A browser says nothing when the button pressed goes: focus fell to
    // the top of the page after every error.
    render(<Toaster />);
    row.focus();
    const button = list.querySelector("button")!;
    button.focus();

    closeOf()({ currentTarget: button });

    expect(document.activeElement).toBe(row);
  });

  it("puts it on the content when that place is gone", () => {
    const content = document.createElement("main");
    content.id = "content";
    content.tabIndex = -1;
    document.body.appendChild(content);
    try {
      render(<Toaster />);
      row.focus();
      const button = list.querySelector("button")!;
      button.focus();
      row.remove();

      closeOf()({ currentTarget: button });

      expect(document.activeElement).toBe(content);
    } finally {
      content.remove();
    }
  });

  it("does the same on Escape pressed from within a message", () => {
    render(<Toaster />);
    row.focus();
    const button = list.querySelector("button")!;
    button.focus();

    fireEvent.keyDown(button, { key: "Escape" });

    expect(sonner.dismiss).toHaveBeenCalled();
    expect(document.activeElement).toBe(row);
  });
});
