import { createRoot } from "react-dom/client";
import App from "./App.tsx";
// The page's typefaces, served with it. A browser fetches each only when
// text is shown in it.
import "@fontsource-variable/atkinson-hyperlegible-next/wght.css";
import "@fontsource-variable/atkinson-hyperlegible-mono/wght.css";
import "./index.css";
import { applyFont, getStoredFontId } from "@/lib/fonts";

// Before anything is drawn, so that the page does not change face.
applyFont(getStoredFontId());

createRoot(document.getElementById("root")!).render(<App />);
