import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import App from "./App";
import { api } from "@/lib/api";

describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.pushState({}, "", "/");
    vi.spyOn(api, "printStatus").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "listFiles").mockReturnValue(new Promise(() => {}));
  });
  afterEach(() => vi.restoreAllMocks());

  it("lets a keyboard go straight to the content, past the menu", () => {
    render(<App />);
    const skip = screen.getByRole("link", { name: "Skip to content" });
    // First of the page, so the first that Tab reaches.
    expect(document.querySelector("a, button")).toBe(skip);
    const main = screen.getByRole("main");
    expect(skip).toHaveAttribute("href", `#${main.id}`);
    // And something focus can land on.
    expect(main).toHaveAttribute("tabindex", "-1");
  });

  it("is read in the language chosen in its menu", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    fireEvent.click(await screen.findByRole("button", { name: "Français" }));

    expect(
      screen.getByRole("link", { name: "Aller au contenu" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Tableau de bord de l'imprimante",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Police de caractères")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("fr");
  });

  it("says that there is nothing at an unknown address, and the way back", () => {
    window.history.pushState({}, "", "/nowhere");
    render(<App />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Page not found" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to the dashboard" }),
    ).toHaveAttribute("href", "/");
    expect(document.title).toBe("Page not found · Mariner");
  });
});
