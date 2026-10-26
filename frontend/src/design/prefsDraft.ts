// Keeping the Choose-furniture form in step with settings saved elsewhere (e.g. by the design helper), without losing
// the user's own unsaved edits. Pure; unit-tested.

export function budgetTextOf(cents: number | null | undefined): string {
  return cents != null ? String(Math.round(cents / 100)) : "";
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** A field the user hasn't touched (draft still equals the previously saved value) follows the newly saved value;
 *  a field the user changed keeps the user's edit (it stays visibly unsaved). */
export function mergeDraft<T extends object>(prevSaved: T, nextSaved: T, draft: T): T {
  const out = { ...draft } as Record<string, unknown>;
  const prev = prevSaved as Record<string, unknown>, next = nextSaved as Record<string, unknown>;
  for (const k of Object.keys(next)) {
    if (same((draft as Record<string, unknown>)[k], prev[k])) out[k] = next[k];
  }
  return out as T;
}

/** The budget box is text: it follows a newly saved budget only if the user hadn't typed something else. */
export function mergeBudgetText(prevCents: number | null, nextCents: number | null, text: string): string {
  return text === budgetTextOf(prevCents) ? budgetTextOf(nextCents) : text;
}
