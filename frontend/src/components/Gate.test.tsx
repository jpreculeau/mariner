import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AccessProvider } from "./AccessProvider";
import { Gate } from "./Gate";
import { api, ApiError } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";
import { useAccess } from "@/lib/access";

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
            <main id="content" tabIndex={-1}>
              <p>the printer's page</p>
            </main>
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

  it("says that it is shut when Mariner cannot reach what it keeps", async () => {
    // Not for want of a password: nothing is offered to be chosen.
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
      unavailable: true,
    });
    renderGate();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Mariner cannot open its page",
    );
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(screen.queryByLabelText("New password")).toBeNull();
    expect(document.title).toBe("Mariner cannot open its page · Mariner");
  });

  it("puts focus in the page once signed in", async () => {
    // The form goes: without this, focus would be nowhere and nothing
    // would say that it worked.
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
    });
    vi.spyOn(api, "signIn").mockResolvedValue();
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    type("Password", "secret words");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("the printer's page");
    await waitFor(() =>
      expect(document.activeElement).toBe(document.getElementById("content")),
    );
  });

  it("does not take focus in a page that opens signed in", async () => {
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: true,
    });
    renderGate();
    await screen.findByText("the printer's page");
    expect(document.activeElement).toBe(document.body);
  });

  it("says that no password was given, rather than do nothing", async () => {
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
    });
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No password was given.",
    );
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(document.activeElement).toBe(screen.getByLabelText("Password"));
  });

  it("says why the form is back when the session ended under the reader", async () => {
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
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      expect(
        screen.getByText("Your session is over. Sign in again."),
      ).toBeInTheDocument();
    } finally {
      globalThis.fetch = realFetch;
    }
  });

  it("does not say so to who opens the page signed out", async () => {
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
    });
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    expect(screen.queryByText(/Your session is over/)).toBeNull();
  });

  it("shows that it is trying again, and names the page meanwhile", async () => {
    const state = vi
      .spyOn(api, "authState")
      .mockRejectedValue(
        new ApiError(0, "Mariner cannot be reached.", "network"),
      );
    renderGate();
    await screen.findByRole("alert");
    expect(document.title).toBe("Mariner cannot be reached · Mariner");
    state.mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    // Said, where the same message unchanged would say nothing.
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Opening Mariner…",
    );
  });

  it("lets its buttons wrap rather than push the page wider than the screen", async () => {
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: false,
      signed_in: false,
    });
    renderGate();
    expect(
      await screen.findByRole("button", { name: "Set the password" }),
    ).toHaveClass("whitespace-normal");
  });

  it("says what the server said, when it answered that it will not", async () => {
    // Reached, under a name it does not answer to: its words say what
    // to add to its configuration. "Check that it is switched on" would
    // send the reader the wrong way.
    vi.spyOn(api, "authState").mockRejectedValue(
      new ApiError(
        403,
        "Mariner does not answer to the name printer.example. Add it to allowed_hosts.",
        "host_not_allowed",
      ),
    );
    renderGate();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Add it to allowed_hosts");
    expect(alert).not.toHaveTextContent("switched on");
  });

  it("tries again by itself while Mariner cannot be reached", async () => {
    // As its message says: someone who opened the page while the
    // computer was starting is let in when it has.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const state = vi
        .spyOn(api, "authState")
        .mockRejectedValue(
          new ApiError(0, "Mariner cannot be reached.", "network"),
        );
      renderGate();
      await screen.findByRole("alert");
      state.mockResolvedValue({ password_set: true, signed_in: true });
      // Without a flicker of "Opening…" at each try.
      await vi.advanceTimersByTimeAsync(5500);
      expect(await screen.findByText("the printer's page")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps saying that it cannot be reached while it tries by itself", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const state = vi
        .spyOn(api, "authState")
        .mockRejectedValue(
          new ApiError(0, "Mariner cannot be reached.", "network"),
        );
      renderGate();
      await screen.findByRole("alert");
      state.mockReturnValue(new Promise(() => {}));
      await vi.advanceTimersByTimeAsync(5500);
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Mariner cannot be reached",
      );
      expect(screen.queryByRole("status")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("puts an error into the language the page is changed to", async () => {
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
    });
    vi.spyOn(api, "signIn").mockRejectedValue(
      new ApiError(401, "This is not the password.", "wrong_password"),
    );
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    type("Password", "not the one");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("alert");

    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    fireEvent.click(await screen.findByRole("button", { name: "Français" }));

    expect(
      screen.getByText("Ce n'est pas le mot de passe."),
    ).toBeInTheDocument();
  });

  it("keeps nothing of what was fetched before, once signed in or out", async () => {
    // It belonged to no session, or to another.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
    });
    vi.spyOn(api, "signIn").mockResolvedValue();
    vi.spyOn(api, "signOut").mockResolvedValue();
    let leave: () => Promise<void> = async () => {};
    function Leave() {
      leave = useAccess().signOut;
      return null;
    }
    render(
      <QueryClientProvider client={client}>
        <LanguageProvider>
          <AccessProvider>
            <Leave />
            <Gate>
              <p>the printer's page</p>
            </Gate>
          </AccessProvider>
        </LanguageProvider>
      </QueryClientProvider>,
    );
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    client.setQueryData(["files", "."], { files: [], directories: [] });
    type("Password", "secret words");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("the printer's page");
    expect(client.getQueryData(["files", "."])).toBeUndefined();

    client.setQueryData(["files", "."], { files: [], directories: [] });
    await act(() => leave());
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    expect(client.getQueryData(["files", "."])).toBeUndefined();
  });
});
