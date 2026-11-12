import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppNav } from "./AppNav";

function renderNav(at: string) {
  render(
    <MemoryRouter initialEntries={[at]}>
      <AppNav />
    </MemoryRouter>,
  );
}

describe("AppNav", () => {
  beforeEach(() => localStorage.clear());

  it("names its links whatever the width of the screen", () => {
    // On a phone only the icons show.
    renderNav("/");
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Files" })).toBeInTheDocument();
  });

  it("says which page is the one shown, not by colour alone", () => {
    renderNav("/files");
    expect(screen.getByRole("link", { name: "Files" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("is a named place to go to", () => {
    renderNav("/");
    expect(
      screen.getByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
  });
});
