import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast as sonner } from "sonner";
import { toast } from "./sonner";

vi.mock("sonner", () => ({
  Toaster: () => null,
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
