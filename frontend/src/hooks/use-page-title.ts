import { useEffect } from "react";

/** Name the page in the browser's tab, its history and its bookmarks. */
export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · Mariner`;
  }, [title]);
}
