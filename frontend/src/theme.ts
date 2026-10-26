// Light / dark / system appearance (pure helpers + a small apply step; unit-tested).
// The choice is stored in this browser only ("furnishai-theme"); "system" follows the device setting live.

export type ThemePref = "light" | "dark" | "system";
export const THEME_KEY = "furnishai-theme";

type Store = Pick<Storage, "getItem" | "setItem">;

export function loadThemePref(store: Store | null | undefined): ThemePref {
  try {
    const v = store?.getItem(THEME_KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";  // storage blocked (private mode etc.)
  }
}

export function saveThemePref(store: Store | null | undefined, pref: ThemePref): void {
  try {
    store?.setItem(THEME_KEY, pref);
  } catch {
    /* not persisted; the choice still applies to this page */
  }
}

export function resolveTheme(pref: ThemePref, prefersDark: boolean): "light" | "dark" {
  return pref === "system" ? (prefersDark ? "dark" : "light") : pref;
}

/** Sets <html data-theme> (and the matching color-scheme) for the choice; returns the theme in use. */
export function applyTheme(root: HTMLElement, pref: ThemePref, prefersDark: boolean): "light" | "dark" {
  const t = resolveTheme(pref, prefersDark);
  root.dataset.theme = t;
  root.dataset.themePref = pref;
  root.style.colorScheme = t;
  return t;
}

export function prefersDarkNow(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}
