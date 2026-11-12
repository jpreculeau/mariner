import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusIndicator } from "./StatusIndicator";

describe("StatusIndicator", () => {
  it.each([
    ["idle", "Ready"],
    ["printing", "Printing"],
    ["paused", "Paused"],
    ["offline", "Offline"],
  ] as const)("shows %s as %s", (status, label) => {
    render(<StatusIndicator status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("is announced when it changes, with what it is the state of", () => {
    const { rerender } = render(<StatusIndicator status="printing" />);
    const indicator = screen.getByRole("status");
    expect(indicator).toHaveAccessibleName("Printer: Printing");
    rerender(<StatusIndicator status="paused" />);
    expect(indicator).toHaveAccessibleName("Printer: Paused");
  });
});
