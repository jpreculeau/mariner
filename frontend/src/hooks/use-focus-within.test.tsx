import { describe, it, expect } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { useFocusWithin } from "./use-focus-within";

let lost: () => boolean;
let forget: () => void;

function Area() {
  const focus = useFocusWithin();
  lost = focus.lost;
  forget = focus.forget;
  const [shown, setShown] = useState(true);
  return (
    <div {...focus.area}>
      {shown && <button onClick={() => setShown(false)}>goes</button>}
      <button>stays</button>
    </div>
  );
}

describe("useFocusWithin", () => {
  it("says focus is lost when what had it was taken away", () => {
    render(<Area />);
    const goes = screen.getByText("goes");
    goes.focus();
    fireEvent.click(goes);
    expect(document.activeElement).toBe(document.body);
    expect(lost()).toBe(true);
  });

  it("does not when the reader took focus away themselves", () => {
    // By pressing on the page where nothing takes focus: moving it then
    // would be moving it from where the reader put it.
    render(<Area />);
    const stays = screen.getByText("stays");
    stays.focus();
    act(() => stays.blur());
    expect(document.activeElement).toBe(document.body);
    expect(lost()).toBe(false);
  });

  it("does not when focus was never in the area", () => {
    render(<Area />);
    expect(lost()).toBe(false);
  });

  it("does not when the reader took focus away and it then went", async () => {
    // Put nowhere by the reader first: taking away what had it loses
    // nothing.
    render(<Area />);
    const goes = screen.getByText("goes");
    goes.focus();
    act(() => goes.blur());
    await new Promise((resolve) => setTimeout(resolve, 5));

    fireEvent.click(goes);

    expect(lost()).toBe(false);
  });

  it("says it once: what was lost is then forgotten", () => {
    render(<Area />);
    const goes = screen.getByText("goes");
    goes.focus();
    fireEvent.click(goes);
    expect(lost()).toBe(true);
    forget();
    expect(lost()).toBe(false);
  });
});
