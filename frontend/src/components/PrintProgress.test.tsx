import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PrintProgress } from "./PrintProgress";
import type { PrintJob } from "./PrintProgress";

const mockJob: PrintJob = {
  fileName: "dragon.ctb",
  currentLayer: 847,
  totalLayers: 2140,
  progress: 39.6,
  elapsedTime: 4820,
  remainingTime: 7340,
  status: "printing",
};

describe("PrintProgress", () => {
  it("renders progress percentage", () => {
    render(<PrintProgress job={mockJob} />);
    expect(screen.getByText("39.6%")).toBeInTheDocument();
  });

  it("renders current layer", () => {
    render(<PrintProgress job={mockJob} />);
    expect(screen.getByText("847")).toBeInTheDocument();
  });

  it("renders total layers", () => {
    render(<PrintProgress job={mockJob} />);
    expect(screen.getByText("2140")).toBeInTheDocument();
  });

  it("renders elapsed time", () => {
    render(<PrintProgress job={mockJob} />);
    expect(screen.getByText("1h 20m")).toBeInTheDocument();
  });

  it("renders remaining time", () => {
    render(<PrintProgress job={mockJob} />);
    expect(screen.getByText("2h 2m")).toBeInTheDocument();
  });

  it("renders file name", () => {
    render(<PrintProgress job={mockJob} />);
    expect(screen.getByText("dragon.ctb")).toBeInTheDocument();
  });

  it("names its bar, and says how far it is", () => {
    render(<PrintProgress job={mockJob} />);
    const bar = screen.getByRole("progressbar", { name: "Print progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "39.6");
    expect(bar).toHaveAttribute("aria-valuetext", "39.6%");
  });

  it("says that its times are estimates", () => {
    // Both come from the same percentage: neither is measured.
    render(<PrintProgress job={mockJob} />);
    expect(screen.getByText("Elapsed (estimate)")).toBeInTheDocument();
    expect(screen.getByText("Remaining (estimate)")).toBeInTheDocument();
  });

  it("says what the file name shown is the name of", () => {
    render(<PrintProgress job={mockJob} />);
    expect(screen.getByText("File being printed")).toBeInTheDocument();
  });

  it("keeps its bar within its ends whatever figure it is given", () => {
    // Out of them, the bar would say nothing at all of how far it is.
    const { rerender } = render(
      <PrintProgress job={{ ...mockJob, progress: 100.4 }} />,
    );
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "100");
    rerender(<PrintProgress job={{ ...mockJob, progress: -0.9 }} />);
    expect(bar).toHaveAttribute("aria-valuenow", "0");
  });
});
