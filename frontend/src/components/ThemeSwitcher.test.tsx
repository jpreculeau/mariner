import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { LanguageProvider } from "@/lib/i18n";

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

  it("lets the reader choose the language, each under its own name", async () => {
    render(
      <LanguageProvider>
        <ThemeSwitcher />
      </LanguageProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    const french = await screen.findByRole("button", { name: "Français" });
    expect(french).toHaveAttribute("lang", "fr");
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(french);

    expect(french).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Langue")).toBeInTheDocument();
    expect(
      screen.getByText("Des lettres dessinées pour ne pas se confondre"),
    ).toBeInTheDocument();
    expect(localStorage.getItem("mariner-language")).toBe("fr");
  });
});
