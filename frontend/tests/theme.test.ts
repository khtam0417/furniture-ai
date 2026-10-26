// Run: npm --prefix frontend test
import { test } from "node:test";
import assert from "node:assert/strict";
import { THEME_KEY, applyTheme, loadThemePref, resolveTheme, saveThemePref } from "../src/theme.ts";

const memory = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, m }; };

test("the appearance choice persists and defaults to System", () => {
  const s = memory();
  assert.equal(loadThemePref(s), "system");
  saveThemePref(s, "dark");
  assert.equal(s.m.get(THEME_KEY), "dark");
  assert.equal(loadThemePref(s), "dark");
  s.setItem(THEME_KEY, "<script>");  // anything unexpected falls back safely
  assert.equal(loadThemePref(s), "system");
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(loadThemePref(broken), "system");
  assert.doesNotThrow(() => saveThemePref(broken, "light"));
});

test("System follows the device; Light and Dark override it", () => {
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
  const root = { dataset: {} as Record<string, string>, style: {} as Record<string, string> };
  assert.equal(applyTheme(root as unknown as HTMLElement, "system", true), "dark");
  assert.deepEqual([root.dataset.theme, root.dataset.themePref, root.style.colorScheme], ["dark", "system", "dark"]);
  applyTheme(root as unknown as HTMLElement, "system", false);  // the device switched to light
  assert.equal(root.dataset.theme, "light");
});
