import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SignIns } from "./SignIns";
import { api } from "@/lib/api";

const renderIt = () =>
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SignIns />
    </QueryClientProvider>,
  );

const AT = Date.UTC(2026, 10, 13, 9, 30) / 1000;

describe("SignIns", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("lists what happened, with when and where from", async () => {
    vi.spyOn(api, "journal").mockResolvedValue({
      wrong_since_last_visit: 0,
      wrong_codes_since_last_visit: 0,
      entries: [
        { at: AT, what: "signed_in", from: "192.168.1.20", internet: false },
        {
          at: AT - 60,
          what: "wrong_password",
          from: "203.0.113.5",
          internet: true,
        },
      ],
    });
    renderIt();
    const table = await screen.findByRole("table", {
      name: "Recent sign-ins and attempts",
    });
    const rows = within(table).getAllByRole("row");
    // The headings, then the latest first.
    expect(rows).toHaveLength(3);
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((heading) => heading.textContent),
    ).toEqual(["When", "What", "Where from"]);
    expect(rows[1]).toHaveTextContent("Signed in");
    expect(rows[1]).toHaveTextContent("Local network (192.168.1.20)");
    expect(rows[2]).toHaveTextContent("Wrong password");
    expect(rows[2]).toHaveTextContent("Internet (203.0.113.5)");
    // A time a program can read, beside the one a person does.
    expect(rows[1].querySelector("time")).toHaveAttribute(
      "datetime",
      new Date(AT * 1000).toISOString(),
    );
  });

  it("says how many wrong ones one line stands for", async () => {
    vi.spyOn(api, "journal").mockResolvedValue({
      wrong_since_last_visit: 0,
      wrong_codes_since_last_visit: 0,
      entries: [
        {
          at: AT,
          what: "wrong_password",
          from: "203.0.113.5",
          internet: true,
          count: 12,
        },
        { at: AT - 5, what: "wrong_code", from: "203.0.113.5", internet: true },
        {
          at: AT - 9,
          what: "code_locked",
          from: "203.0.113.5",
          internet: true,
        },
      ],
    });
    renderIt();
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Wrong password, 12 times");
    expect(rows[2]).toHaveTextContent("Right password, wrong one-time code");
    expect(rows[3]).toHaveTextContent(
      "Sign-in closed from the Internet until someone signs in at home",
    );
  });

  it("says how many tried since the visit before", async () => {
    vi.spyOn(api, "journal").mockResolvedValue({
      wrong_since_last_visit: 3,
      wrong_codes_since_last_visit: 0,
      entries: [
        { at: AT, what: "signed_in", from: "192.168.1.20", internet: false },
      ],
    });
    renderIt();
    expect(
      await screen.findByText(
        "3 wrong passwords were sent since your previous visit.",
      ),
    ).toBeInTheDocument();
  });

  it("says when the right password came with wrong codes", async () => {
    vi.spyOn(api, "journal").mockResolvedValue({
      wrong_since_last_visit: 0,
      wrong_codes_since_last_visit: 4,
      entries: [],
    });
    renderIt();
    expect(
      await screen.findByText(
        "The right password was sent 4 times with a wrong one-time code since your previous visit: somebody else may know your password. Change it in Settings.",
      ),
    ).toBeInTheDocument();
  });

  it("says it in the singular for one", async () => {
    vi.spyOn(api, "journal").mockResolvedValue({
      wrong_since_last_visit: 1,
      wrong_codes_since_last_visit: 0,
      entries: [],
    });
    renderIt();
    expect(
      await screen.findByText(
        "1 wrong password was sent since your previous visit.",
      ),
    ).toBeInTheDocument();
  });

  it("says so when there is nothing yet", async () => {
    vi.spyOn(api, "journal").mockResolvedValue({
      wrong_since_last_visit: 0,
      wrong_codes_since_last_visit: 0,
      entries: [],
    });
    renderIt();
    expect(await screen.findByText("Nothing yet.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText(/since your previous visit/)).toBeNull();
  });

  it("says so when it cannot be read", async () => {
    vi.spyOn(api, "journal").mockRejectedValue(new Error("no"));
    renderIt();
    expect(
      await screen.findByText("The journal could not be read."),
    ).toBeInTheDocument();
  });

  it("shows what it does not know of as it is named", async () => {
    // Noted by a newer Mariner than this page.
    vi.spyOn(api, "journal").mockResolvedValue({
      wrong_since_last_visit: 0,
      wrong_codes_since_last_visit: 0,
      entries: [
        {
          at: AT,
          what: "something_new",
          from: "192.168.1.20",
          internet: false,
        },
      ],
    });
    renderIt();
    expect(await screen.findByText("something_new")).toBeInTheDocument();
  });
});
