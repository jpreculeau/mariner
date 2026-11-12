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

    expect(await screen.findByRole("status")).toHaveTextContent(
      "This change takes effect when Mariner is started again.",
    );
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
    expect(screen.getByRole("status")).toHaveTextContent(
      "Restart Mariner the way it was started",
    );
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
          "Password changed. Other pages were signed out.",
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
});
