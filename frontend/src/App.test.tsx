import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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

  it("puts focus in the content when another page is shown", async () => {
    // Else it stays on a link of the menu, or falls to the top.
    render(<App />);
    const files = screen.getByRole("link", { name: "Files" });
    files.focus();
    fireEvent.click(files);

    await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
    expect(document.title).toBe("Files · Mariner");
  });

  it("does not take focus when the page is first shown", () => {
    render(<App />);
    expect(screen.getByRole("main")).not.toHaveFocus();
  });

  it("has one place for its messages", () => {
    render(<App />);
    expect(screen.getAllByRole("region")).toHaveLength(1);
  });

  it("goes on showing an upload on whichever page is shown", async () => {
    // The file goes on being sent when the reader looks at the printer.
    vi.mocked(api.listFiles).mockResolvedValue({ directories: [], files: [] });
    vi.spyOn(api, "uploadFile").mockReturnValue(new Promise(() => {}));
    window.history.pushState({}, "", "/files");
    const { container } = render(<App />);
    await screen.findByText("This folder is empty.");
    fireEvent.change(
      container.querySelector('input[type="file"]') as HTMLInputElement,
      { target: { files: [new File(["x"], "dragon.ctb")] } },
    );
    await screen.findByRole("progressbar", { name: "Upload progress" });

    fireEvent.click(screen.getByRole("link", { name: "Dashboard" }));

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Printer dashboard",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Upload progress" }),
    ).toBeInTheDocument();

    // And no second file is taken meanwhile, back on the files.
    fireEvent.click(screen.getByRole("link", { name: "Files" }));
    expect(
      await screen.findByRole("button", { name: "Upload a file" }),
    ).toHaveAttribute("aria-disabled", "true");
  });
});
