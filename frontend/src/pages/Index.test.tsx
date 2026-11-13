import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Index from "./Index";
import { api, ApiError, type PrintStatusResponse } from "@/lib/api";
import { toast } from "@/components/ui/sonner";
import { LanguageProvider, useI18n } from "@/lib/i18n";

vi.mock("@/components/ui/sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const printing: PrintStatusResponse = {
  state: "PRINTING",
  selected_file: "dragon.ctb",
  progress: 39.6,
  current_layer: 847,
  layer_count: 2140,
  print_time_secs: 12160,
  time_left_secs: 7340,
};

/** The page's main area, where focus goes when it has nowhere else. */
function withContent(): HTMLElement {
  const content = document.createElement("main");
  content.id = "content";
  content.tabIndex = -1;
  document.body.appendChild(content);
  return content;
}

function renderIndex() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <LanguageProvider>
          <Index />
        </LanguageProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Index", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
    localStorage.clear();
  });

  it("names the page in the browser's tab", async () => {
    vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    renderIndex();
    await screen.findByText("39.6%");
    expect(document.title).toBe("Dashboard · Mariner");
  });

  it("has a heading while it waits for the printer", () => {
    vi.spyOn(api, "printStatus").mockReturnValue(new Promise(() => {}));
    renderIndex();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Printer dashboard",
    );
    // Said to those who cannot see the spinner turn.
    expect(screen.getByRole("status")).toHaveTextContent(
      "Connecting to the printer…",
    );
  });

  it("says that Mariner cannot be reached, and what to check", async () => {
    vi.spyOn(api, "printStatus").mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    renderIndex();
    expect(
      await screen.findByRole("heading", { name: "Mariner cannot be reached" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(
      screen.getByText(/switched on and on the network/),
    ).toBeInTheDocument();
  });

  it("says that the printer does not answer, and what to check", async () => {
    vi.spyOn(api, "printStatus").mockResolvedValue({
      ...printing,
      state: "CLOSED",
    });
    renderIndex();
    expect(
      await screen.findByRole("heading", { name: "Printer not answering" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/its cable/)).toBeInTheDocument();
  });

  it("announces the state of the printer", async () => {
    vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    renderIndex();
    await screen.findByText("39.6%");
    expect(screen.getByRole("status")).toHaveAccessibleName(
      "Printer: Printing",
    );
  });

  it("says that a print was paused", async () => {
    vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    vi.spyOn(api, "printerCommand").mockResolvedValue();
    renderIndex();

    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Print paused"),
    );
    expect(api.printerCommand).toHaveBeenCalledWith("pause_print");
  });

  it("leaves it to the form to say that the session is over", async () => {
    vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    const sent = vi
      .spyOn(api, "printerCommand")
      .mockRejectedValue(
        new ApiError(
          401,
          "Sign in with Mariner's password first.",
          "login_required",
        ),
      );
    renderIndex();
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    await waitFor(() => expect(sent).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("says why a command was not taken", async () => {
    vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    vi.spyOn(api, "printerCommand").mockRejectedValue(
      new ApiError(503, "The printer did not answer.", "printer_not_answering"),
    );
    renderIndex();

    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("The printer did not answer."),
    );
    expect(toast.success).not.toHaveBeenCalled();
    // And the button can be pressed again.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Pause" })).not.toHaveAttribute(
        "aria-disabled",
        "true",
      ),
    );
  });

  it("cancels a print only once confirmed, and says so", async () => {
    vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    vi.spyOn(api, "printerCommand").mockResolvedValue();
    renderIndex();

    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel print" }),
    );
    expect(api.printerCommand).not.toHaveBeenCalled();
    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel the print" }),
    );

    await waitFor(() =>
      expect(api.printerCommand).toHaveBeenCalledWith("cancel_print"),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Print cancelled"),
    );
  });

  it("does not go on showing a state it no longer knows", async () => {
    // Mariner stopped answering during a print: what it last said of the
    // printer is not what the printer is doing now.
    vi.spyOn(api, "printStatus")
      .mockResolvedValueOnce(printing)
      .mockRejectedValue(
        new ApiError(0, "Mariner cannot be reached.", "network"),
      );
    vi.spyOn(api, "printerCommand").mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    renderIndex();

    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));

    expect(
      await screen.findByRole("heading", { name: "Mariner cannot be reached" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText("Printing")).toBeNull();
  });

  it("says how a command went in the language of the page as it is then", async () => {
    // Changed while the printer was answering.
    function Switch() {
      const { setLang } = useI18n();
      return <button onClick={() => setLang("fr")}>switch</button>;
    }
    let done: () => void = () => {};
    vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    vi.spyOn(api, "printerCommand").mockReturnValue(
      new Promise<void>((resolve) => (done = resolve)),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <LanguageProvider>
            <Switch />
            <Index />
          </LanguageProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    await act(async () => done());

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Impression en pause"),
    );
  });

  it("asks the printer again where it is once a command was sent", async () => {
    const status = vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    vi.spyOn(api, "printerCommand").mockResolvedValue();
    renderIndex();
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));

    await waitFor(() => expect(status.mock.calls.length).toBeGreaterThan(1));
  });

  it("is read in French by a French reader", async () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    vi.spyOn(api, "printStatus").mockResolvedValue(printing);
    vi.spyOn(api, "printerCommand").mockRejectedValue(
      new ApiError(500, "The printer did not answer.", "printer_error"),
    );
    renderIndex();

    fireEvent.click(
      await screen.findByRole("button", { name: "Mettre en pause" }),
    );

    await waitFor(() =>
      expect(vi.mocked(toast.error).mock.calls[0][0]).toContain(
        "n'a pas accepté la commande",
      ),
    );
    expect(document.title).toBe("Tableau de bord · Mariner");
    expect(screen.getByText("Couche en cours")).toBeInTheDocument();
    // Figures as French writes them.
    expect(screen.getByText("1 h 20 min")).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Avancement de l'impression" }),
    ).toHaveAttribute("aria-valuetext", "39,6\u00a0%");
  });

  it("gives focus a place to go when the print it was on is over", async () => {
    const content = withContent();
    try {
      const status = vi.spyOn(api, "printStatus").mockResolvedValue(printing);
      vi.spyOn(api, "printerCommand").mockResolvedValue();
      renderIndex();
      const pause = await screen.findByRole("button", { name: "Pause" });
      pause.focus();
      status.mockResolvedValue({ ...printing, state: "IDLE" });

      fireEvent.click(pause);

      await screen.findByText("See the files");
      expect(document.activeElement).toBe(content);
    } finally {
      content.remove();
    }
  });

  it("gives focus a place to go when Mariner stops answering", async () => {
    const content = withContent();
    try {
      const status = vi.spyOn(api, "printStatus").mockResolvedValue(printing);
      vi.spyOn(api, "printerCommand").mockResolvedValue();
      renderIndex();
      const pause = await screen.findByRole("button", { name: "Pause" });
      pause.focus();
      status.mockRejectedValue(
        new ApiError(0, "Mariner cannot be reached.", "network"),
      );

      fireEvent.click(pause);

      await screen.findByRole("alert");
      expect(document.activeElement).toBe(content);
    } finally {
      content.remove();
    }
  });

  it("moves focus once for a print that is over, not at every change after", async () => {
    const content = withContent();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    try {
      const status = vi.spyOn(api, "printStatus").mockResolvedValue(printing);
      vi.spyOn(api, "printerCommand").mockResolvedValue();
      render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <LanguageProvider>
              <Index />
            </LanguageProvider>
          </MemoryRouter>
        </QueryClientProvider>,
      );
      const pause = await screen.findByRole("button", { name: "Pause" });
      pause.focus();
      status.mockResolvedValue({ ...printing, state: "IDLE" });
      fireEvent.click(pause);
      await screen.findByText("See the files");
      expect(document.activeElement).toBe(content);

      // The reader puts focus nowhere; the printer then stops answering.
      act(() => content.blur());
      expect(document.activeElement).toBe(document.body);
      status.mockResolvedValue({ ...printing, state: "CLOSED" });
      await act(async () => {
        await client.invalidateQueries({ queryKey: ["printStatus"] });
      });
      await screen.findByText("Printer not answering");

      expect(document.activeElement).toBe(document.body);
    } finally {
      content.remove();
    }
  });
});
