import { useEffect, useState } from "react";
import { applyTheme, loadThemePref, prefersDarkNow, saveThemePref, type ThemePref } from "./theme";

const LABEL: Record<ThemePref, string> = { light: "Light", dark: "Dark", system: "System" };

/** Light / Dark / System appearance. "System" follows the device setting, also when it changes later. */
export default function ThemeToggle() {
  const [pref, setPref] = useState<ThemePref>(() => loadThemePref(typeof localStorage !== "undefined" ? localStorage : null));
  useEffect(() => {
    applyTheme(document.documentElement, pref, prefersDarkNow());
    if (pref !== "system" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => applyTheme(document.documentElement, "system", mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [pref]);
  const pick = (p: ThemePref) => { setPref(p); saveThemePref(localStorage, p); };
  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Appearance">
      {(["light", "dark", "system"] as ThemePref[]).map((p) => (
        <button key={p} type="button" role="radio" aria-checked={pref === p} className={`theme-opt ${pref === p ? "theme-on" : ""}`}
          onClick={() => pick(p)} title={p === "system" ? "Follow this device’s light or dark setting" : `${LABEL[p]} appearance`}>
          {LABEL[p]}
        </button>
      ))}
    </div>
  );
}
