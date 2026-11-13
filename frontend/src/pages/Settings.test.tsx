import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Settings from "./Settings";
import { api, ApiError, type SettingsResponse } from "@/lib/api";
import { AccessContext, type AccessState } from "@/lib/access";
import { toast } from "@/components/ui/sonner";

vi.mock("@/components/ui/sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const shown: SettingsResponse = {
  settings: {
    printer_display_name: "Saturn",
    uvtools_enabled: true,
    sdcp_enabled: true,
    assume_printer_off: false,
  },
  restart_needed: false,
  can_restart: true,
};

const access: AccessState = {
  access: "in",
  retry: vi.fn(),
  signedOutUnasked: false,
  choosePassword: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn().mockResolvedValue(undefined),
};

function renderSettings() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AccessContext.Provider value={access}>
        <Settings />
      </AccessContext.Provider>
    </QueryClientProvider>,
  );
}

const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("Settings", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
    vi.mocked(access.signOut).mockReset().mockResolvedValue(undefined);
    vi.spyOn(api, "settings").mockResolvedValue(shown);
  });

  it("shows them as they stand, each with what it does", async () => {
    renderSettings();
    expect(
      await screen.findByLabelText("Name shown for the printer"),
    ).toHaveValue("Saturn");
    expect(document.title).toBe("Settings · Mariner");
    const sdcp = screen.getByRole("checkbox", { name: "ChiTuBox (SDCP)" });
    expect(sdcp).toBeChecked();
    expect(sdcp).toHaveAccessibleDescription(/3030/);
    expect(screen.getByRole("checkbox", { name: "UVtools" })).toBeChecked();
    expect(
      screen.getByRole("checkbox", {
        name: "Do not ask when the printer does not answer",
      }),
    ).not.toBeChecked();
    // Said where they are switched: they are not behind the password.
    expect(screen.getByText(/without the password/)).toBeInTheDocument();
    // One heading for the page, one for each part.
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getAllByRole("heading", { level: 2 }).length).toBe(4);
  });

  it("keeps a switch as soon as it is changed, and says so", async () => {
    const save = vi.spyOn(api, "saveSettings").mockResolvedValue({
      ...shown,
      settings: { ...shown.settings, assume_printer_off: true },
    });
    renderSettings();
    const box = await screen.findByRole("checkbox", {
      name: "Do not ask when the printer does not answer",
    });

    fireEvent.click(box);

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ assume_printer_off: true }),
    );
    await waitFor(() => expect(box).toBeChecked());
    expect(toast.success).toHaveBeenCalledWith("Saved");
    expect(screen.queryByText(/started again/)).toBeNull();
  });

  it("says that a slicer's switch waits for a restart, and offers one", async () => {
    vi.spyOn(api, "saveSettings").mockResolvedValue({
      ...shown,
      settings: { ...shown.settings, sdcp_enabled: false },
      restart_needed: true,
    });
    const restart = vi.spyOn(api, "restart").mockResolvedValue();
    renderSettings();
    fireEvent.click(
      await screen.findByRole("checkbox", { name: "ChiTuBox (SDCP)" }),
    );

    expect(
      await screen.findByText(
        /This change takes effect when Mariner is started again\./,
      ),
    ).toBeInTheDocument();
    // Said with "Saved" too, where it is sure to be heard and seen: the
    // notice is at the top of the page, and the switch is one of safety.
    expect(toast.success).toHaveBeenCalledWith(
      "Saved. This change takes effect when Mariner is started again.",
    );
    const restartButton = screen.getByRole("button", {
      name: "Restart Mariner",
    });
    expect(restartButton).toHaveClass("whitespace-normal");
    fireEvent.click(restartButton);
    await waitFor(() => expect(restart).toHaveBeenCalledTimes(1));
    expect(toast.success).toHaveBeenCalledWith(
      "Mariner is restarting. This page comes back by itself.",
    );
  });

  it("says to restart by hand where it cannot from the page", async () => {
    vi.spyOn(api, "settings").mockResolvedValue({
      ...shown,
      restart_needed: true,
      can_restart: false,
    });
    renderSettings();
    await screen.findByLabelText("Name shown for the printer");
    expect(
      screen.getByText(/Restart Mariner the way it was started/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Restart Mariner" }),
    ).toBeNull();
  });

  it("puts a switch back and says why when it was not kept", async () => {
    vi.spyOn(api, "saveSettings").mockRejectedValue(
      new ApiError(500, "x", "internal_error"),
    );
    renderSettings();
    const box = await screen.findByRole("checkbox", { name: "UVtools" });
    fireEvent.click(box);
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(box).toBeChecked();
  });

  it("keeps the name when its form is sent", async () => {
    const save = vi.spyOn(api, "saveSettings").mockResolvedValue({
      ...shown,
      settings: { ...shown.settings, printer_display_name: "Workshop" },
    });
    renderSettings();
    await screen.findByLabelText("Name shown for the printer");
    type("Name shown for the printer", "Workshop");
    fireEvent.click(screen.getByRole("button", { name: "Save the name" }));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ printer_display_name: "Workshop" }),
    );
    expect(toast.success).toHaveBeenCalledWith("Saved");
  });

  describe("changing the password", () => {
    const fill = async (current: string, next: string, again: string) => {
      await screen.findByLabelText("Current password");
      type("Current password", current);
      type("New password", next);
      type("Repeat the new password", again);
      fireEvent.click(
        screen.getByRole("button", { name: "Change the password" }),
      );
    };

    it("does not send two new ones that differ", async () => {
      const change = vi.spyOn(api, "changePassword").mockResolvedValue();
      renderSettings();
      await fill("old words", "new words 1", "new words 2");
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The two passwords are not the same.",
      );
      expect(change).not.toHaveBeenCalled();
    });

    it("says by its field that the current one is wrong", async () => {
      vi.spyOn(api, "changePassword").mockRejectedValue(
        new ApiError(
          401,
          "This is not the password in place.",
          "wrong_password",
        ),
      );
      renderSettings();
      await fill("not it", "new words", "new words");
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("This is not the password in place.");
      const field = screen.getByLabelText("Current password");
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(document.activeElement).toBe(field);
    });

    it("says by its field that the new one was not taken", async () => {
      vi.spyOn(api, "changePassword").mockRejectedValue(
        new ApiError(
          400,
          "A password has at least 8 characters.",
          "password_too_short",
        ),
      );
      renderSettings();
      await fill("old words", "short", "short");
      await screen.findByRole("alert");
      expect(screen.getByLabelText("New password")).toHaveAttribute(
        "aria-invalid",
        "true",
      );
    });

    it("changes it, says so, and empties the fields", async () => {
      const change = vi.spyOn(api, "changePassword").mockResolvedValue();
      renderSettings();
      await fill("old words", "new words", "new words");
      await waitFor(() =>
        expect(change).toHaveBeenCalledWith("old words", "new words"),
      );
      await waitFor(() =>
        expect(toast.success).toHaveBeenCalledWith(
          "Password changed. Other browsers were signed out.",
        ),
      );
      expect(screen.getByLabelText("Current password")).toHaveValue("");
      expect(screen.getByLabelText("New password")).toHaveValue("");
    });
  });

  it("signs out", async () => {
    renderSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(access.signOut).toHaveBeenCalledTimes(1));
  });

  it("says that they could not be fetched, and lets it be tried again", async () => {
    const fetched = vi
      .spyOn(api, "settings")
      .mockRejectedValue(
        new ApiError(0, "Mariner cannot be reached.", "network"),
      );
    renderSettings();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The settings could not be fetched",
    );
    fetched.mockResolvedValue(shown);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByLabelText("Name shown for the printer"),
    ).toBeInTheDocument();
  });

  it("says that a password is missing, rather than do nothing", async () => {
    const change = vi.spyOn(api, "changePassword").mockResolvedValue();
    renderSettings();
    fireEvent.click(
      await screen.findByRole("button", { name: "Change the password" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No password was given.",
    );
    expect(document.activeElement).toBe(
      screen.getByLabelText("Current password"),
    );
    expect(change).not.toHaveBeenCalled();
  });

  it("shows where the keyboard is on a box that is ticked", async () => {
    renderSettings();
    const box = await screen.findByRole("checkbox", { name: "UVtools" });
    // A ring against the box's own fill cannot be seen: it stands off.
    expect(box.className).toContain("focus-visible:ring-offset-2");
  });

  it("takes the notice away once Mariner is back from its restart", async () => {
    // Left there, it asked for another restart, and each one cuts a
    // file that is being sent.
    const fetched = vi.spyOn(api, "settings").mockResolvedValue({
      ...shown,
      restart_needed: true,
    });
    vi.spyOn(api, "restart").mockResolvedValue();
    renderSettings();
    const button = await screen.findByRole("button", {
      name: "Restart Mariner",
    });
    // Gone for a moment, then back with nothing left to apply.
    fetched
      .mockRejectedValueOnce(
        new ApiError(0, "Mariner cannot be reached.", "network"),
      )
      .mockResolvedValue({ ...shown, restart_needed: false });

    fireEvent.click(button);

    expect(
      await screen.findByRole("button", { name: "Restarting…" }),
    ).toHaveAttribute("aria-disabled", "true");
    await waitFor(
      () => expect(screen.queryByText(/takes effect when Mariner/)).toBeNull(),
      { timeout: 6000 },
    );
  }, 10000);

  it("puts the refusal of a password too common by the new one", async () => {
    vi.spyOn(api, "changePassword").mockRejectedValue(
      new ApiError(
        400,
        "This password is among the first anyone would try. Choose another.",
        "password_too_common",
      ),
    );
    renderSettings();
    await screen.findByLabelText("Current password");
    type("Current password", "old words");
    type("New password", "motdepasse");
    type("Repeat the new password", "motdepasse");
    fireEvent.click(
      screen.getByRole("button", { name: "Change the password" }),
    );
    await screen.findByRole("alert");
    expect(screen.getByLabelText("New password")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText("Current password")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
  });

  it("says that Mariner is back, and keeps the keyboard's place", async () => {
    const content = document.createElement("main");
    content.id = "content";
    content.tabIndex = -1;
    document.body.appendChild(content);
    try {
      const fetched = vi.spyOn(api, "settings").mockResolvedValue({
        ...shown,
        restart_needed: true,
      });
      vi.spyOn(api, "restart").mockResolvedValue();
      renderSettings();
      const button = await screen.findByRole("button", {
        name: "Restart Mariner",
      });
      fetched.mockResolvedValue({ ...shown, restart_needed: false });
      button.focus();
      fireEvent.click(button);
      await waitFor(
        () => expect(toast.success).toHaveBeenCalledWith("Mariner is back."),
        { timeout: 6000 },
      );
      // The button went with the notice it was in.
      await waitFor(() => expect(document.activeElement).toBe(content));
    } finally {
      content.remove();
    }
  }, 10000);

  it("takes an answer that refuses for Mariner being back", async () => {
    // The session did not outlast the restart: the form to sign in is
    // what shows, and "not back yet" would be false.
    const fetched = vi.spyOn(api, "settings").mockResolvedValue({
      ...shown,
      restart_needed: true,
    });
    vi.spyOn(api, "restart").mockResolvedValue();
    renderSettings();
    const button = await screen.findByRole("button", {
      name: "Restart Mariner",
    });
    fetched.mockRejectedValue(
      new ApiError(
        401,
        "Sign in with Mariner's password first.",
        "login_required",
      ),
    );

    fireEvent.click(button);
    await screen.findByRole("button", { name: "Restarting…" });

    // At the first answer, not after a minute of them.
    await waitFor(
      () =>
        expect(
          screen.queryByRole("button", { name: "Restarting…" }),
        ).toBeNull(),
      { timeout: 4000 },
    );
    expect(toast.error).not.toHaveBeenCalled();
  }, 10000);

  it("says so when Mariner is not back within a minute", async () => {
    const fetched = vi.spyOn(api, "settings").mockResolvedValue({
      ...shown,
      restart_needed: true,
    });
    vi.spyOn(api, "restart").mockResolvedValue();
    renderSettings();
    const button = await screen.findByRole("button", {
      name: "Restart Mariner",
    });
    fetched.mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    vi.useFakeTimers();
    try {
      fireEvent.click(button);
      await vi.advanceTimersByTimeAsync(61000);
    } finally {
      vi.useRealTimers();
    }
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Mariner is not back yet"),
      ),
    );
  });

  it("does not say twice that the session is over", async () => {
    // The form to sign in says it, by the field that takes focus.
    vi.spyOn(api, "saveSettings").mockRejectedValue(
      new ApiError(
        401,
        "Sign in with Mariner's password first.",
        "login_required",
      ),
    );
    renderSettings();
    fireEvent.click(await screen.findByRole("checkbox", { name: "UVtools" }));
    await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("says once that a restart is waited for, not at each change after", async () => {
    vi.spyOn(api, "settings").mockResolvedValue({
      ...shown,
      restart_needed: true,
    });
    vi.spyOn(api, "saveSettings").mockResolvedValue({
      ...shown,
      settings: { ...shown.settings, assume_printer_off: true },
      restart_needed: true,
    });
    renderSettings();
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "Do not ask when the printer does not answer",
      }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Saved"));
  });

  it("sends one change at a time", async () => {
    let done: (kept: SettingsResponse) => void = () => {};
    const save = vi.spyOn(api, "saveSettings").mockReturnValue(
      new Promise((resolve) => {
        done = resolve;
      }),
    );
    renderSettings();
    fireEvent.click(await screen.findByRole("checkbox", { name: "UVtools" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "ChiTuBox (SDCP)" }));
    expect(save).toHaveBeenCalledTimes(1);
    done(shown);
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });

  it("gives the new name to the rest of the page", async () => {
    const meta = document.createElement("meta");
    meta.name = "printer-display-name";
    meta.content = "Saturn";
    document.head.appendChild(meta);
    try {
      vi.spyOn(api, "saveSettings").mockResolvedValue({
        ...shown,
        settings: { ...shown.settings, printer_display_name: "Workshop" },
      });
      renderSettings();
      await screen.findByLabelText("Name shown for the printer");
      type("Name shown for the printer", "Workshop");
      fireEvent.click(screen.getByRole("button", { name: "Save the name" }));
      await waitFor(() => expect(meta.content).toBe("Workshop"));
    } finally {
      meta.remove();
    }
  });

  it("says why when signing out did not work", async () => {
    vi.mocked(access.signOut).mockRejectedValue(
      new ApiError(0, "Mariner cannot be reached.", "network"),
    );
    renderSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("says that a restart is waited for in one place that is announced", async () => {
    // The message that says "Saved" says it: the notice, put in the
    // page at the same moment, would have it read out twice.
    vi.spyOn(api, "settings").mockResolvedValue({
      ...shown,
      restart_needed: true,
    });
    renderSettings();
    await screen.findByRole("button", { name: "Restart Mariner" });
    expect(screen.getByText(/started again/)).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("leaves it to the form to say that the session is over, on restarting", async () => {
    vi.spyOn(api, "settings").mockResolvedValue({
      ...shown,
      restart_needed: true,
    });
    const sent = vi
      .spyOn(api, "restart")
      .mockRejectedValue(
        new ApiError(
          401,
          "Sign in with Mariner's password first.",
          "login_required",
        ),
      );
    renderSettings();
    fireEvent.click(
      await screen.findByRole("button", { name: "Restart Mariner" }),
    );
    await waitFor(() => expect(sent).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("leaves it to the screen that says Mariner is shut to say so", async () => {
    vi.spyOn(api, "saveSettings").mockRejectedValue(
      new ApiError(503, "Mariner cannot use the folder.", "state_unavailable"),
    );
    renderSettings();
    fireEvent.click(await screen.findByRole("checkbox", { name: "UVtools" }));
    await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("marks no field as wrong for what is not about a field", async () => {
    vi.spyOn(api, "changePassword").mockRejectedValue(
      new ApiError(500, "Mariner could not keep this.", "state_not_written"),
    );
    renderSettings();
    await screen.findByLabelText("Current password");
    type("Current password", "old words");
    type("New password", "new words!");
    type("Repeat the new password", "new words!");
    fireEvent.click(
      screen.getByRole("button", { name: "Change the password" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Mariner could not keep this.",
    );
    for (const label of [
      "Current password",
      "New password",
      "Repeat the new password",
    ]) {
      expect(screen.getByLabelText(label)).toHaveAttribute(
        "aria-invalid",
        "false",
      );
    }
  });
});
