import { useRef } from "react";
import type { FocusEvent } from "react";

/**
 * Notes whether focus is within an area, so that it can be given a place
 * to go when what it was on is taken away: a browser then leaves it on
 * the page as a whole, and reading starts again from the top.
 */
export function useFocusWithin() {
  // What last had focus in the area, while focus has not gone elsewhere.
  const last = useRef<Element | null>(null);
  return {
    /** For the area: `<div {...area}>`. */
    area: {
      onFocus: (event: FocusEvent) => {
        last.current = event.target;
      },
      onBlur: (event: FocusEvent) => {
        if (event.relatedTarget) {
          // Gone elsewhere by the reader's doing.
          last.current = null;
          return;
        }
        // Gone nowhere: what had it is being taken away, or the reader
        // pressed on the page where nothing takes focus. Only a moment
        // later can the two be told apart: in the second it is still
        // there.
        const was = event.target;
        setTimeout(() => {
          const nowhere =
            !document.activeElement || document.activeElement === document.body;
          if (last.current === was && was.isConnected && nowhere) {
            last.current = null;
          }
        });
      },
    },
    /**
     * Whether focus was in the area and is now nowhere because what had
     * it is gone. Not when the reader put it nowhere themselves, by
     * pressing on the page where nothing takes it.
     */
    lost: () =>
      last.current !== null &&
      !last.current.isConnected &&
      (!document.activeElement || document.activeElement === document.body),
    forget: () => {
      last.current = null;
    },
  };
}

/** Put focus on the page's main area. */
export function focusContent() {
  document.getElementById("content")?.focus();
}
