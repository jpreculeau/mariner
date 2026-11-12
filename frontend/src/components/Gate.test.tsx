import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AccessProvider } from "./AccessProvider";
import { Gate } from "./Gate";
import { api, ApiError } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";

function renderGate() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <LanguageProvider>
        <AccessProvider>
          <Gate>
            <p>the printer's page</p>
            <button onClick={() => api.printStatus().catch(() => {})}>
              ask
            </button>
          </Gate>
        </AccessProvider>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("Gate", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the page to who is signed in", async () => {
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: true,
    });
    renderGate();
    expect(await screen.findByText("the printer's page")).toBeInTheDocument();
  });

  it("shows nothing of it while it finds out", () => {
    vi.spyOn(api, "authState").mockReturnValue(new Promise(() => {}));
    renderGate();
    expect(screen.queryByText("the printer's page")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Opening Mariner…");
  });

  describe("at the first visit", () => {
    beforeEach(() => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: false,
        signed_in: false,
      });
    });

    it("asks for a password to be chosen, and says what it is for", async () => {
      renderGate();
      expect(
        await screen.findByRole("heading", { name: "Choose a password" }),
      ).toBeInTheDocument();
      expect(screen.queryByText("the printer's page")).toBeNull();
      expect(document.title).toBe("Choose a password · Mariner");
      // Typed twice: it cannot be read back.
      expect(screen.getByLabelText("New password")).toHaveAttribute(
        "autocomplete",
        "new-password",
      );
      expect(screen.getByLabelText("Repeat the password")).toHaveAttribute(
        "type",
        "password",
      );
      // Said before it is chosen: slicers are not asked for it.
      expect(screen.getByText(/Slicers/)).toBeInTheDocument();
    });

    it("does not send two passwords that differ", async () => {
      const choose = vi.spyOn(api, "choosePassword").mockResolvedValue();
      renderGate();
      await screen.findByRole("heading", { name: "Choose a password" });
      type("New password", "secret words");
      type("Repeat the password", "secret word");
      fireEvent.click(screen.getByRole("button", { name: "Set the password" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The two passwords are not the same.",
      );
      expect(choose).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(
        screen.getByLabelText("Repeat the password"),
      );
    });

    it("says by the field why one was not taken", async () => {
      vi.spyOn(api, "choosePassword").mockRejectedValue(
        new ApiError(
          400,
          "A password has at least 8 characters.",
          "password_too_short",
        ),
      );
      renderGate();
      await screen.findByRole("heading", { name: "Choose a password" });
      type("New password", "short");
      type("Repeat the password", "short");
      fireEvent.click(screen.getByRole("button", { name: "Set the password" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("A password has at least 8 characters.");
      const field = screen.getByLabelText("New password");
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field.getAttribute("aria-describedby")).toContain(alert.id);
      expect(document.activeElement).toBe(field);
    });

    it("opens the page once one is chosen", async () => {
      const choose = vi.spyOn(api, "choosePassword").mockResolvedValue();
      renderGate();
      await screen.findByRole("heading", { name: "Choose a password" });
      type("New password", "secret words");
      type("Repeat the password", "secret words");
      fireEvent.click(screen.getByRole("button", { name: "Set the password" }));

      expect(await screen.findByText("the printer's page")).toBeInTheDocument();
      expect(choose).toHaveBeenCalledWith("secret words");
    });
  });

  describe("when a password is set", () => {
    beforeEach(() => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
      });
    });

    it("asks for it", async () => {
      renderGate();
      expect(
        await screen.findByRole("heading", { name: "Sign in to Mariner" }),
      ).toBeInTheDocument();
      expect(document.title).toBe("Sign in · Mariner");
      const field = screen.getByLabelText("Password");
      expect(field).toHaveAttribute("autocomplete", "current-password");
      expect(field).toHaveAttribute("type", "password");
      // And says what to do when it is lost.
      expect(screen.getByText(/reset-password/)).toBeInTheDocument();
    });

    it("says that a password is wrong, and leaves it to be typed again", async () => {
      vi.spyOn(api, "signIn").mockRejectedValue(
        new ApiError(401, "This is not the password.", "wrong_password"),
      );
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "not the one");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "This is not the password.",
      );
      const field = screen.getByLabelText("Password");
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(document.activeElement).toBe(field);
      expect(screen.queryByText("the printer's page")).toBeNull();
      // And the button can be pressed again.
      expect(
        screen.getByRole("button", { name: "Sign in" }),
      ).not.toHaveAttribute("aria-disabled", "true");
    });

    it("sends it once however often the button is pressed", async () => {
      const signIn = vi
        .spyOn(api, "signIn")
        .mockReturnValue(new Promise(() => {}));
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "secret words");
      const button = screen.getByRole("button", { name: "Sign in" });
      fireEvent.click(button);
      fireEvent.click(button);
      expect(signIn).toHaveBeenCalledTimes(1);
      expect(
        await screen.findByRole("button", { name: "Signing in…" }),
      ).toHaveAttribute("aria-disabled", "true");
    });

    it("opens the page with the right one", async () => {
      vi.spyOn(api, "signIn").mockResolvedValue();
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "secret words");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      expect(await screen.findByText("the printer's page")).toBeInTheDocument();
    });

    it("does not send an empty one", async () => {
      const signIn = vi.spyOn(api, "signIn").mockResolvedValue();
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      expect(signIn).not.toHaveBeenCalled();
    });
  });

  it("asks for the password again when the server says the session is over", async () => {
    // Ended, or the password changed from another page.
    const realFetch = globalThis.fetch;
    const state = vi
      .spyOn(api, "authState")
      .mockResolvedValue({ password_set: true, signed_in: true });
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ code: "login_required", description: "Sign in." }),
          { status: 401 },
        ),
      );
    try {
      renderGate();
      await screen.findByText("the printer's page");
      state.mockResolvedValue({ password_set: true, signed_in: false });

      fireEvent.click(screen.getByRole("button", { name: "ask" }));

      expect(
        await screen.findByRole("heading", { name: "Sign in to Mariner" }),
      ).toBeInTheDocument();
      expect(screen.queryByText("the printer's page")).toBeNull();
    } finally {
      globalThis.fetch = realFetch;
    }
  });

  it("says that Mariner cannot be reached, and lets it be tried again", async () => {
    const state = vi
      .spyOn(api, "authState")
      .mockRejectedValue(
        new ApiError(0, "Mariner cannot be reached.", "network"),
      );
    renderGate();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Mariner cannot be reached",
    );
    state.mockResolvedValue({ password_set: true, signed_in: true });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getByText("the printer's page")).toBeInTheDocument(),
    );
  });

  it("asks in French of a French reader", async () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
    });
    renderGate();
    expect(
      await screen.findByRole("heading", { name: "Connexion à Mariner" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Mot de passe")).toBeInTheDocument();
  });
});
