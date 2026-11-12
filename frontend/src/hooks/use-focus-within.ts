import { useRef } from "react";
import type { FocusEvent } from "react";

/**
 * Notes whether focus is within an area, so that it can be given a place
 * to go when what it was on is taken away: a browser then leaves it on
 * the page as a whole, and reading starts again from the top.
 */
export function useFocusWithin() {
  const within = useRef(false);
  return {
    /** For the area: `<div {...area}>`. */
    area: {
      onFocus: () => {
        within.current = true;
      },
      onBlur: (event: FocusEvent) => {
        // Gone elsewhere by the reader's doing. With nowhere to go, what
        // had it may just have been removed.
        if (event.relatedTarget) within.current = false;
      },
    },
    /** Whether focus was in the area and is now nowhere. */
    lost: () =>
      within.current &&
      (!document.activeElement || document.activeElement === document.body),
    forget: () => {
      within.current = false;
    },
  };
}

/** Put focus on the page's main area. */
export function focusContent() {
  document.getElementById("content")?.focus();
}
