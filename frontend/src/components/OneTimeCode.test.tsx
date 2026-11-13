import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { OneTimeCode } from "./OneTimeCode";
import { api, ApiError } from "@/lib/api";
import { AccessContext, type AccessState } from "@/lib/access";
import { toast } from "@/components/ui/sonner";

vi.mock("@/components/ui/sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
const URI = `otpauth://totp/Mariner:Saturn?secret=${SECRET}&issuer=Mariner`;

const retry = vi.fn();
const renderIt = (more: Partial<AccessState> = {}) =>
  render(
    <AccessContext.Provider
      value={{
        access: "in",
        retry,
        failure: null,
        signedOutUnasked: false,
        fromInternet: false,
        codeSet: false,
        choosePassword: vi.fn(),
        signIn: vi.fn(),
        signOut: vi.fn(),
        ...more,
      }}
    >
      <OneTimeCode />
    </AccessContext.Provider>,
  );

const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("OneTimeCode", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    retry.mockClear();
    vi.mocked(toast.success).mockClear();
  });

  it("says that none is set up, and what that means", () => {
    renderIt();
    expect(
      screen.getByText(/nobody can sign in from the Internet/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Set up a one-time code" }),
    ).toBeInTheDocument();
  });

  it("gives the phone the key, to type or to open", async () => {
    vi.spyOn(api, "startCode").mockResolvedValue({ secret: SECRET, uri: URI });
    renderIt();
    fireEvent.click(
      screen.getByRole("button", { name: "Set up a one-time code" }),
    );
    // In groups of four, to be typed.
    expect(
      await screen.findByText("GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Open in the phone's application/ }),
    ).toHaveAttribute("href", URI);
    // Focus goes to what comes next.
    expect(document.activeElement).toBe(
      screen.getByLabelText("Code given by the phone"),
    );
  });

  it("puts it in force once a code of it is given", async () => {
    vi.spyOn(api, "startCode").mockResolvedValue({ secret: SECRET, uri: URI });
    const confirm = vi.spyOn(api, "confirmCode").mockResolvedValue();
    renderIt();
    fireEvent.click(
      screen.getByRole("button", { name: "Set up a one-time code" }),
    );
    await screen.findByLabelText("Code given by the phone");
    type("Code given by the phone", "287082");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith("287082"));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "The one-time code is set up.",
      ),
    );
    // The page asks again where it stands.
    expect(retry).toHaveBeenCalled();
    expect(screen.queryByLabelText("Code given by the phone")).toBeNull();
  });

  it("says by the field that a code is wrong", async () => {
    vi.spyOn(api, "startCode").mockResolvedValue({ secret: SECRET, uri: URI });
    vi.spyOn(api, "confirmCode").mockRejectedValue(
      new ApiError(400, "This is not the code of the moment.", "wrong_code"),
    );
    renderIt();
    fireEvent.click(
      screen.getByRole("button", { name: "Set up a one-time code" }),
    );
    await screen.findByLabelText("Code given by the phone");
    type("Code given by the phone", "000000");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This is not the code of the moment.",
    );
    expect(screen.getByLabelText("Code given by the phone")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("says what to type when nothing was", async () => {
    vi.spyOn(api, "startCode").mockResolvedValue({ secret: SECRET, uri: URI });
    const confirm = vi.spyOn(api, "confirmCode");
    renderIt();
    fireEvent.click(
      screen.getByRole("button", { name: "Set up a one-time code" }),
    );
    await screen.findByLabelText("Code given by the phone");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Type the code your phone gives.",
    );
    expect(confirm).not.toHaveBeenCalled();
  });

  it("names the key for who cannot see it", async () => {
    vi.spyOn(api, "startCode").mockResolvedValue({ secret: SECRET, uri: URI });
    renderIt();
    fireEvent.click(
      screen.getByRole("button", { name: "Set up a one-time code" }),
    );
    expect(await screen.findByLabelText("Key to type")).toHaveTextContent(
      "GEZD GNBV",
    );
    // The link is for the phone itself: said.
    expect(
      screen.getByText(/if this page is open on the phone/),
    ).toBeInTheDocument();
  });

  it("gives focus back to where it began, whatever the end", async () => {
    vi.spyOn(api, "startCode").mockResolvedValue({ secret: SECRET, uri: URI });
    vi.spyOn(api, "confirmCode").mockResolvedValue();
    renderIt();
    const setUp = () =>
      screen.getByRole("button", { name: "Set up a one-time code" });
    fireEvent.click(setUp());
    await screen.findByLabelText("Code given by the phone");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(setUp()));
    fireEvent.click(setUp());
    await screen.findByLabelText("Code given by the phone");
    type("Code given by the phone", "287082");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(screen.queryByLabelText("Code given by the phone")).toBeNull(),
    );
    await waitFor(() => expect(document.activeElement).toBe(setUp()));
  });

  it("asks for the password before another phone takes the place of the one in use", async () => {
    const start = vi
      .spyOn(api, "startCode")
      .mockResolvedValue({ secret: SECRET, uri: URI });
    renderIt({ codeSet: true });
    fireEvent.click(screen.getByRole("button", { name: "Replace the phone" }));
    // Said before it is done: the old phone's codes stop working.
    expect(
      screen.getByText(/codes of the phone in use will stop working/),
    ).toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
    type("Current password", "correct horse battery");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() =>
      expect(start).toHaveBeenCalledWith("correct horse battery"),
    );
    expect(
      await screen.findByLabelText("Code given by the phone"),
    ).toBeInTheDocument();
  });

  it("asks for the password to be typed before sending nothing", async () => {
    const start = vi.spyOn(api, "startCode");
    const remove = vi.spyOn(api, "removeCode");
    renderIt({ codeSet: true });
    fireEvent.click(screen.getByRole("button", { name: "Replace the phone" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Type the password.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Remove the one-time code" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Remove it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Type the password.",
    );
    expect(start).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });

  it("gives focus back to the button that was pressed", async () => {
    renderIt({ codeSet: true });
    const remove = () =>
      screen.getByRole("button", { name: "Remove the one-time code" });
    fireEvent.click(remove());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(remove()));
  });

  it("tells the page that something changed, for the journal to be read again", async () => {
    vi.spyOn(api, "removeCode").mockResolvedValue();
    const changed = vi.fn();
    render(
      <AccessContext.Provider
        value={
          {
            fromInternet: false,
            codeSet: true,
            retry,
          } as unknown as AccessState
        }
      >
        <OneTimeCode onChanged={changed} />
      </AccessContext.Provider>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Remove the one-time code" }),
    );
    type("Current password", "correct horse battery");
    fireEvent.click(screen.getByRole("button", { name: "Remove it" }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
  });

  it("is done away with by who gives the password", async () => {
    const remove = vi.spyOn(api, "removeCode").mockResolvedValue();
    renderIt({ codeSet: true });
    expect(screen.getByText(/A one-time code is set up/)).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Remove the one-time code" }),
    );
    type("Current password", "correct horse battery");
    fireEvent.click(screen.getByRole("button", { name: "Remove it" }));
    await waitFor(() =>
      expect(remove).toHaveBeenCalledWith("correct horse battery"),
    );
    await waitFor(() => expect(retry).toHaveBeenCalled());
  });

  it("is left alone from the Internet, and says why", () => {
    renderIt({ fromInternet: true, codeSet: true });
    expect(
      screen.getByText(/from the local network alone/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
