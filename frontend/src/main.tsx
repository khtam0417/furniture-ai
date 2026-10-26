import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { applyTheme, loadThemePref, prefersDarkNow } from "./theme";

// Apply the saved appearance before the first paint (no light flash in dark mode).
applyTheme(document.documentElement, loadThemePref(typeof localStorage !== "undefined" ? localStorage : null), prefersDarkNow());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
