import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeSwitcher } from "./ThemeSwitcher";

describe("ThemeSwitcher", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.style.cssText = "";
  });

  it("lets the reader choose the typeface", async () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));

    const dyslexic = await screen.findByRole("button", {
      name: /OpenDyslexic/,
    });
    const legible = screen.getByRole("button", {
      name: /Atkinson Hyperlegible/,
    });
    expect(legible).toHaveAttribute("aria-pressed", "true");
    expect(dyslexic).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(dyslexic);

    expect(dyslexic).toHaveAttribute("aria-pressed", "true");
    expect(legible).toHaveAttribute("aria-pressed", "false");
    expect(
      document.documentElement.style.getPropertyValue("--font-body"),
    ).toContain("OpenDyslexic");
    expect(localStorage.getItem("mariner-font")).toBe("opendyslexic");
  });

  it("shows each typeface in its own letters", async () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    const dyslexic = await screen.findByRole("button", {
      name: /OpenDyslexic/,
    });
    expect(dyslexic.style.fontFamily).toContain("OpenDyslexic");
  });

  it("still lets the colours be chosen, and says which are", async () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    const saturn = await screen.findByRole("button", {
      name: /Elegoo Saturn/,
    });
    fireEvent.click(saturn);
    expect(saturn).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("mariner-theme")).toBe("saturn");
  });
});
