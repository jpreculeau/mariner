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
import { toast } from "@/components/ui/sonner";

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
          "A password has at least 14 characters.",
          "password_too_short",
        ),
      );
      renderGate();
      await screen.findByRole("heading", { name: "Choose a password" });
      type("New password", "short");
      type("Repeat the password", "short");
      fireEvent.click(screen.getByRole("button", { name: "Set the password" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("A password has at least 14 characters.");
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
    // The tab says the same as the page.
    expect(document.title).toBe("Mariner did not open its page · Mariner");
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

  it("asks again where it stands when a password was chosen meanwhile", async () => {
    // From another tab or device: the form to choose one would stay,
    // with nothing to do but reload.
    const state = vi
      .spyOn(api, "authState")
      .mockResolvedValue({ password_set: false, signed_in: false });
    vi.spyOn(api, "choosePassword").mockRejectedValue(
      new ApiError(
        409,
        "A password has already been chosen.",
        "password_already_set",
      ),
    );
    renderGate();
    await screen.findByRole("heading", { name: "Choose a password" });
    state.mockResolvedValue({ password_set: true, signed_in: false });
    type("New password", "secret words");
    type("Repeat the password", "secret words");
    fireEvent.click(screen.getByRole("button", { name: "Set the password" }));
    expect(
      await screen.findByRole("heading", { name: "Sign in to Mariner" }),
    ).toBeInTheDocument();
  });

  it("ties what it says of the session to the field that takes focus", async () => {
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
      const field = await screen.findByLabelText("Password");
      expect(field).toHaveAccessibleDescription(
        "Your session is over. Sign in again.",
      );
    } finally {
      globalThis.fetch = realFetch;
    }
  });

  it("goes on asking while the page is shut", async () => {
    // Put right and restarted, Mariner opens it without a reload.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const state = vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
        unavailable: true,
      });
      renderGate();
      await screen.findByRole("alert");
      state.mockResolvedValue({ password_set: true, signed_in: false });
      await vi.advanceTimersByTimeAsync(5500);
      expect(
        await screen.findByRole("heading", { name: "Sign in to Mariner" }),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the keyboard's place when another try is asked for", async () => {
    vi.spyOn(api, "authState").mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    renderGate();
    const again = await screen.findByRole("button", { name: "Try again" });
    again.focus();
    fireEvent.click(again);
    await waitFor(() =>
      expect(document.activeElement).toBe(document.getElementById("content")),
    );
    // Still not reached: back on the button, to press it again.
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Try again" }),
      ),
    );
  });

  it("enters when another tab of the browser signs in", async () => {
    const state = vi
      .spyOn(api, "authState")
      .mockResolvedValue({ password_set: true, signed_in: false });
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    state.mockResolvedValue({ password_set: true, signed_in: true });
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "mariner-page-key",
          newValue: "another-tab",
        }),
      );
    });
    expect(await screen.findByText("the printer's page")).toBeInTheDocument();
  });

  it("gives the screen it opens on a heading", () => {
    vi.spyOn(api, "authState").mockReturnValue(new Promise(() => {}));
    renderGate();
    expect(
      screen.getByRole("heading", { level: 1, name: "Opening Mariner…" }),
    ).toBeInTheDocument();
  });

  it("says again what it said, when the form is sent again as it was", async () => {
    // Left in place, nothing would be announced the second time.
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
    });
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const first = await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert")).not.toBe(first));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No password was given.",
    );
  });

  it("is not put back on the form by an answer asked for before signing in", async () => {
    let answer: (state: {
      password_set: boolean;
      signed_in: boolean;
    }) => void = () => {};
    const state = vi
      .spyOn(api, "authState")
      .mockResolvedValue({ password_set: true, signed_in: false });
    vi.spyOn(api, "signIn").mockResolvedValue();
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    // Asked again, and slow to answer.
    state.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "mariner-page-key" }),
      );
    });
    await waitFor(() => expect(state).toHaveBeenCalledTimes(2));
    type("Password", "secret words");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("the printer's page");

    await act(async () => {
      answer({ password_set: true, signed_in: false });
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(screen.getByText("the printer's page")).toBeInTheDocument();
  });

  describe("with a way out in the page", () => {
    let leave: () => Promise<void>;
    function Leave() {
      leave = useAccess().signOut;
      return null;
    }
    const renderWithLeave = () =>
      render(
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
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

    it("does not say that the session is over to who signed out", async () => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: true,
      });
      vi.spyOn(api, "signOut").mockResolvedValue();
      renderWithLeave();
      await screen.findByText("the printer's page");
      await act(() => leave());
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      expect(screen.queryByText(/Your session is over/)).toBeNull();
    });

    it("takes away what was said before signing in", async () => {
      const dismiss = vi.spyOn(toast, "dismiss");
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
      });
      vi.spyOn(api, "signIn").mockResolvedValue();
      renderWithLeave();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "secret words");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await screen.findByText("the printer's page");
      expect(dismiss).toHaveBeenCalled();
    });
  });

  it("asks where it stands twice a day in a page left open", async () => {
    // The month a session lasts starts again each time.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const state = vi
        .spyOn(api, "authState")
        .mockResolvedValue({ password_set: true, signed_in: true });
      renderGate();
      await screen.findByText("the printer's page");
      expect(state).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(12 * 60 * 60 * 1000 + 1000);
      expect(state).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("marks no field as wrong for what is not about the password", async () => {
    vi.spyOn(api, "authState").mockResolvedValue({
      password_set: true,
      signed_in: false,
    });
    vi.spyOn(api, "signIn").mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    type("Password", "secret words");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /cannot be reached/,
    );
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
    // Read with the field all the same, where focus is.
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      /cannot be reached/,
    );
    expect(document.activeElement).toBe(screen.getByLabelText("Password"));
    // Said again when it happens again.
    const said = screen.getByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert")).not.toBe(said));
  });

  it("empties the form when it becomes the other one", async () => {
    // What was typed to sign in is not a password being chosen.
    const state = vi
      .spyOn(api, "authState")
      .mockResolvedValue({ password_set: true, signed_in: false });
    vi.spyOn(api, "signIn").mockRejectedValue(
      new ApiError(401, "No password has been chosen yet.", "password_not_set"),
    );
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    type("Password", "secret words");
    state.mockResolvedValue({ password_set: false, signed_in: false });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Choose a password" });
    expect(screen.getByLabelText("New password")).toHaveValue("");
    expect(screen.getByLabelText("New password")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
    // Why it is another form is still said.
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No password has been chosen yet.",
    );
  });

  it("gives the keyboard a place when the page opens after another try", async () => {
    const state = vi
      .spyOn(api, "authState")
      .mockRejectedValue(
        new ApiError(0, "Mariner cannot be reached.", "network"),
      );
    renderGate();
    const again = await screen.findByRole("button", { name: "Try again" });
    again.focus();
    state.mockResolvedValue({ password_set: true, signed_in: true });
    fireEvent.click(again);
    await screen.findByText("the printer's page");
    await waitFor(() =>
      expect(document.activeElement).toBe(document.getElementById("content")),
    );
  });

  it("gives the keyboard a place when a form gives way to Mariner being shut", async () => {
    const state = vi
      .spyOn(api, "authState")
      .mockResolvedValue({ password_set: true, signed_in: false });
    vi.spyOn(api, "signIn").mockImplementation(async () => {
      state.mockResolvedValue({
        password_set: true,
        signed_in: false,
        unavailable: true,
      });
      window.dispatchEvent(
        new StorageEvent("storage", { key: "mariner-page-key" }),
      );
      throw new ApiError(
        503,
        "Mariner cannot use the folder.",
        "state_unavailable",
      );
    });
    renderGate();
    await screen.findByRole("heading", { name: "Sign in to Mariner" });
    type("Password", "secret words");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText(/Mariner cannot open its page/);
    await waitFor(() =>
      expect(document.activeElement).toBe(document.getElementById("content")),
    );
    // Said by the screen alone.
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  describe("under a page that is open", () => {
    const realFetch = globalThis.fetch;
    afterEach(() => {
      globalThis.fetch = realFetch;
    });
    const refuseWith = (status: number, code: string) => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code, description: "No." }), {
          status,
        }),
      );
    };

    it("says that the password was cleared, to who is asked to choose one", async () => {
      const state = vi
        .spyOn(api, "authState")
        .mockResolvedValue({ password_set: true, signed_in: true });
      refuseWith(401, "password_not_set");
      renderGate();
      await screen.findByText("the printer's page");
      state.mockResolvedValue({ password_set: false, signed_in: false });
      fireEvent.click(screen.getByRole("button", { name: "ask" }));
      await screen.findByRole("heading", { name: "Choose a password" });
      expect(
        screen.getByText("Mariner's password was cleared. Choose a new one."),
      ).toBeInTheDocument();
      expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
        /was cleared/,
      );
    });

    it("does not say so at a first visit", async () => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: false,
        signed_in: false,
      });
      renderGate();
      await screen.findByRole("heading", { name: "Choose a password" });
      expect(screen.queryByText(/was cleared/)).toBeNull();
    });

    it("gives the keyboard a place when Mariner shuts", async () => {
      const state = vi
        .spyOn(api, "authState")
        .mockResolvedValue({ password_set: true, signed_in: true });
      refuseWith(503, "state_unavailable");
      renderGate();
      await screen.findByText("the printer's page");
      state.mockResolvedValue({
        password_set: true,
        signed_in: false,
        unavailable: true,
      });
      const ask = screen.getByRole("button", { name: "ask" });
      ask.focus();
      fireEvent.click(ask);
      await screen.findByText(/Mariner cannot open its page/);
      await waitFor(() =>
        expect(document.activeElement).toBe(document.getElementById("content")),
      );
    });

    it("keeps nothing of what was fetched under a page that shut", async () => {
      // Drawn again as it was when the page opens, it would say for a
      // moment that Mariner cannot be reached.
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const state = vi
        .spyOn(api, "authState")
        .mockResolvedValue({ password_set: true, signed_in: true });
      refuseWith(503, "state_unavailable");
      render(
        <QueryClientProvider client={client}>
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
      await screen.findByText("the printer's page");
      client.setQueryData(["print_status"], { state: "idle" });
      state.mockResolvedValue({
        password_set: true,
        signed_in: false,
        unavailable: true,
      });
      fireEvent.click(screen.getByRole("button", { name: "ask" }));
      await screen.findByText(/Mariner cannot open its page/);
      await waitFor(() =>
        expect(client.getQueryData(["print_status"])).toBeUndefined(),
      );
    });

    it("takes away what was said while it was shut, once it opens again", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const dismiss = vi.spyOn(toast, "dismiss");
        const state = vi.spyOn(api, "authState").mockResolvedValue({
          password_set: true,
          signed_in: false,
          unavailable: true,
        });
        renderGate();
        await screen.findByRole("alert");
        dismiss.mockClear();
        state.mockResolvedValue({ password_set: true, signed_in: true });
        await vi.advanceTimersByTimeAsync(5500);
        await screen.findByText("the printer's page");
        expect(dismiss).toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });
  });

  it("is not let back in by an answer asked for before signing out", async () => {
    let answer: (state: {
      password_set: boolean;
      signed_in: boolean;
    }) => void = () => {};
    const state = vi
      .spyOn(api, "authState")
      .mockResolvedValue({ password_set: true, signed_in: true });
    vi.spyOn(api, "signOut").mockResolvedValue();
    let leave: () => Promise<void> = async () => {};
    function Leave() {
      leave = useAccess().signOut;
      return null;
    }
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
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
    await screen.findByText("the printer's page");
    state.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "mariner-page-key" }),
      );
    });
    await waitFor(() => expect(state).toHaveBeenCalledTimes(2));
    await act(() => leave());
    await screen.findByRole("heading", { name: "Sign in to Mariner" });

    await act(async () => {
      answer({ password_set: true, signed_in: true });
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(screen.queryByText("the printer's page")).toBeNull();
  });

  describe("seen from the Internet", () => {
    const from = (more: object) =>
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
        from_internet: true,
        ...more,
      });

    it("asks for the code besides the password", async () => {
      from({ code_set: true });
      const signIn = vi.spyOn(api, "signIn").mockResolvedValue();
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      const code = screen.getByLabelText("One-time code");
      expect(code).toHaveAttribute("autocomplete", "one-time-code");
      expect(code).toHaveAttribute("inputmode", "numeric");
      type("Password", "correct horse battery");
      type("One-time code", "287 082");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await waitFor(() =>
        expect(signIn).toHaveBeenCalledWith("correct horse battery", "287 082"),
      );
    });

    it("does not send the password without the code", async () => {
      from({ code_set: true });
      const signIn = vi.spyOn(api, "signIn").mockResolvedValue();
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "correct horse battery");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Type the code your phone gives.",
      );
      const code = screen.getByLabelText("One-time code");
      expect(code).toHaveAttribute("aria-invalid", "true");
      expect(document.activeElement).toBe(code);
      expect(signIn).not.toHaveBeenCalled();
    });

    it("does not say which of the two was wrong", async () => {
      from({ code_set: true });
      vi.spyOn(api, "signIn").mockRejectedValue(
        new ApiError(
          401,
          "This is not the password, or not the code of the moment.",
          "wrong_password",
        ),
      );
      vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
      renderGate();
      await screen.findByRole("heading", { name: "Connexion à Mariner" });
      type("Mot de passe", "correct horse battery");
      type("Code à usage unique", "000000");
      fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Ce n'est pas le mot de passe, ou pas le code du moment.",
      );
      // Neither field is marked: it may be either.
      expect(screen.getByLabelText("Mot de passe")).toHaveAttribute(
        "aria-invalid",
        "false",
      );
    });

    it("keeps a code that may still serve when the two are refused", async () => {
      from({ code_set: true });
      vi.spyOn(api, "signIn").mockRejectedValue(
        new ApiError(401, "This is not the password.", "wrong_password"),
      );
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "correct horse battery");
      type("One-time code", "287082");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await screen.findByRole("alert");
      // A slip in the password: the code is not to be typed again.
      expect(screen.getByLabelText("One-time code")).toHaveValue("287082");
    });

    it("says that sign-in is closed until somebody signs in at home", async () => {
      from({ code_set: true });
      vi.spyOn(api, "signIn").mockRejectedValue(
        new ApiError(403, "Too many wrong one-time codes…", "code_locked"),
      );
      vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
      renderGate();
      await screen.findByRole("heading", { name: "Connexion à Mariner" });
      type("Mot de passe", "correct horse battery");
      type("Code à usage unique", "287082");
      fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        /fermée jusqu'à ce que quelqu'un se connecte depuis le réseau local/,
      );
    });

    it("lets one who has come home ask again", async () => {
      const state = from({ code_set: false });
      renderGate();
      await screen.findByRole("heading", {
        name: "Signing in from the Internet is not set up",
      });
      state.mockResolvedValue({
        password_set: true,
        signed_in: false,
        from_internet: false,
        code_set: false,
      });
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
      expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    });

    it("asks for no code on the local network", async () => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
        from_internet: false,
        code_set: true,
      });
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      expect(screen.queryByLabelText("One-time code")).toBeNull();
    });

    it("says that no code is set up, in place of a form that cannot serve", async () => {
      from({ code_set: false });
      renderGate();
      expect(
        await screen.findByRole("heading", {
          name: "Signing in from the Internet is not set up",
        }),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("Password")).toBeNull();
      expect(screen.getByText(/one-time code/)).toBeInTheDocument();
    });

    it("does not offer to choose the password from there", async () => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: false,
        signed_in: false,
        from_internet: true,
        code_set: false,
      });
      renderGate();
      expect(
        await screen.findByRole("heading", {
          name: "Mariner is not set up yet",
        }),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("New password")).toBeNull();
    });
  });

  describe("once signed in", () => {
    it("says that somebody tried while the owner was away", async () => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
      });
      vi.spyOn(api, "signIn").mockResolvedValue({ passwords: 3, codes: 0 });
      const said = vi.spyOn(toast, "error");
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "correct horse battery");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await waitFor(() =>
        expect(said).toHaveBeenCalledWith(
          "3 wrong passwords were sent since your previous visit. See Settings, Recent sign-ins.",
        ),
      );
    });

    it("says it plainly when the password itself is known to somebody", async () => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
      });
      vi.spyOn(api, "signIn").mockResolvedValue({ passwords: 0, codes: 10 });
      const said = vi.spyOn(toast, "error");
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "correct horse battery");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await waitFor(() =>
        expect(said).toHaveBeenCalledWith(
          "The right password was sent 10 times with a wrong one-time code since your previous visit: somebody else may know your password. Change it in Settings.",
        ),
      );
      expect(said).toHaveBeenCalledTimes(1);
    });

    it("says that there were more than is remembered", async () => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
      });
      vi.spyOn(api, "signIn").mockResolvedValue({
        passwords: 50,
        codes: 0,
        orMore: true,
      });
      const said = vi.spyOn(toast, "error");
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "correct horse battery");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await waitFor(() =>
        expect(said).toHaveBeenCalledWith(
          "50 wrong passwords or more were sent since your previous visit. See Settings, Recent sign-ins.",
        ),
      );
    });

    it("says nothing of it when nobody did", async () => {
      vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
      });
      vi.spyOn(api, "signIn").mockResolvedValue({ passwords: 0, codes: 0 });
      const said = vi.spyOn(toast, "error");
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      type("Password", "correct horse battery");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await screen.findByText("the printer's page");
      expect(said).not.toHaveBeenCalled();
    });

    it("asks again where the page is seen from", async () => {
      // Signed in outside, the state was that of the Internet; home is
      // not the same.
      const state = vi.spyOn(api, "authState").mockResolvedValue({
        password_set: true,
        signed_in: false,
      });
      vi.spyOn(api, "signIn").mockResolvedValue({ passwords: 0, codes: 0 });
      renderGate();
      await screen.findByRole("heading", { name: "Sign in to Mariner" });
      const asked = state.mock.calls.length;
      state.mockResolvedValue({ password_set: true, signed_in: true });
      type("Password", "correct horse battery");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await waitFor(() =>
        expect(state.mock.calls.length).toBeGreaterThan(asked),
      );
    });
  });
});
