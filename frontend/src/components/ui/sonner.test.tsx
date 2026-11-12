import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
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
});
