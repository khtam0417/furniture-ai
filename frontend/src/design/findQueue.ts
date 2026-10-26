// "Find furniture" queue: one group (piece type + size) at a time, bounded, stoppable, failure-isolated.
// Pure logic (no React) so it can be unit-tested.

export type BranchResult = {
  // "unavailable": every selected marketplace refused automated reading recently, so nothing was searched or checked.
  branch: "new" | "used"; status: "ok" | "error" | "paused" | "unavailable"; searched: boolean; checked: number; verified: number;
  unavailable_sites?: string[];  // selected marketplaces skipped for now (recent refusals)
  skipped_refusing?: number;  // results from those marketplaces: counted, never checked
  source_note?: string | null;
  reasons: Record<string, number>; message: string | null; existing?: number;
  ready_existing?: number;  // saved options that fit and are within budget (the new branch skips the web only with 3+)
  target_cents?: number | null; good?: number; refined?: boolean; needs_refine?: boolean;
};
export type GroupResult = {
  key: string; label: string; branches: Record<string, BranchResult>; options: number; options_new: number; options_used: number;
  limited?: string | null;  // the AI request limit was reached: the queue pauses here
  options_fitting?: number;  // options that physically fit this piece (the others are listed but flagged)
  refine?: boolean;  // this result came from the bounded second pass
  needs_refine?: boolean;  // fewer than 3 ready options after the first pass: one more search may be offered (on request)
  options_ready?: number;  // distinct options that fit and are within the piece's share and the whole budget
  pieces?: number;  // pieces in the layout this search is for (same type and size)
  held_back?: Record<string, number>; held_text?: string | null;  // checked options that aren't recommended, and why
};
export type FindGroup = { key: string; category: string; size: string | null; label: string; item_ids: string[] };
export type GroupStatus = { key: string; label: string; state: "waiting" | "running" | "done" | "error" | "not_run"; result?: GroupResult; error?: string };

/** Run at most `max` groups in order. A failing group is recorded and the queue continues; `shouldStop()` is checked
 *  before each group (so "Stop" ends after the current one). Returns the final statuses and the keys not run yet. */
export async function runFindQueue(
  groups: FindGroup[],
  runOne: (key: string) => Promise<GroupResult>,
  opts: { max: number; shouldStop: () => boolean; onUpdate: (s: GroupStatus[]) => void; pauseOn?: (r: GroupResult) => string | null },
): Promise<{ statuses: GroupStatus[]; remaining: string[]; paused: string | null }> {
  const statuses: GroupStatus[] = groups.map((g) => ({ key: g.key, label: g.label, state: "waiting" }));
  const emit = () => opts.onUpdate(statuses.map((s) => ({ ...s })));
  emit();
  let ran = 0;
  let paused: string | null = null;
  for (let i = 0; i < groups.length; i++) {
    if (ran >= opts.max || paused || opts.shouldStop()) break;
    statuses[i].state = "running";
    emit();
    try {
      const r = await runOne(groups[i].key);
      paused = opts.pauseOn?.(r) ?? null;
      statuses[i].result = r;
      // A group stopped by the limit is retried on Continue (its found options, if any, stay visible).
      statuses[i].state = paused ? "not_run" : "done";
    } catch (e) {
      statuses[i].state = "error";
      statuses[i].error = (e as Error).message;
    }
    ran++;
    emit();
  }
  for (const s of statuses) if (s.state === "waiting") s.state = "not_run";
  emit();
  return { statuses, remaining: statuses.filter((s) => s.state === "not_run").map((s) => s.key), paused };
}

/** Why a run should stop after the current group: the user's Stop, or leaving the Choose step (the step stays mounted
 *  while hidden, so unmounting can't be relied on). Only an explicit new run or Continue clears it; returning doesn't. */
export type StopReason = "user" | "left";
export function makeStopper() {
  let reason: StopReason | null = null;
  return {
    stop: (r: StopReason) => { reason = reason ?? r; },
    reset: () => { reason = null; },
    shouldStop: () => reason !== null,
    reason: () => reason,
  };
}
export const STOP_TEXT: Record<StopReason, string> = {
  user: "Stopped after the current piece type.",
  left: "Stopped after the current piece type because you left this step.",
};

/** The saved settings a search depends on. Found/progress results belong to one key: a saved change to any of these
 *  makes them stale. Choosing products (a design version bump) doesn't change it. */
export function searchKey(p: { condition: string; styles: string[]; bed_size: string; fulfillment?: string | null;
  resale_sites?: string[] | null; retailers: string[]; budget_cents: number | null; reserve_pct: number }, location: string): string {
  return JSON.stringify([p.condition, [...p.styles].sort(), p.bed_size, p.fulfillment ?? "either", [...(p.resale_sites ?? [])].sort(),
    [...p.retailers].sort(), p.budget_cents, p.reserve_pct, location]);
}

/** Row summary for the options shown under the active New/Secondhand filter (never "choose below" when none show). */
export function optionsLine(pv: { total: number; total_new: number; total_used: number; total_all?: number; held_text?: string | null } | undefined,
  filter: "all" | "new" | "used"): { text: string; ready: boolean } | null {
  // `total` counts ready recommendations only; options held back (over budget, too big…) are explained, never "ready".
  if (pv && pv.total <= 0 && (pv.total_all ?? 0) > 0) return { ready: false, text: pv.held_text ?? "No option that fits your budget and room yet." };
  if (!pv || pv.total <= 0) return null;
  const n = (k: number, what: string) => `${k} ${what}option${k === 1 ? "" : "s"}`;
  if (filter === "all") {
    return { ready: true, text: `${n(pv.total, "")} ready${pv.total_new && pv.total_used ? ` (${pv.total_new} new, ${pv.total_used} used)` : ""}. Choose one below.` };
  }
  const [mine, other, mineName, otherName, otherTab] = filter === "used"
    ? [pv.total_used, pv.total_new, "secondhand ", "new ", "All/New"] : [pv.total_new, pv.total_used, "new ", "secondhand ", "All/Secondhand"];
  const rest = other ? ` ${n(other, otherName)} available under ${otherTab}.` : "";
  return mine
    ? { ready: true, text: `${n(mine, mineName)} ready. Choose one below.${rest}` }
    : { ready: false, text: `No checked ${mineName}options yet.${rest}` };
}

const dollars =(c: number) => `$${Math.round(c / 100).toLocaleString("en-US")}`;

/** Budget only (placement is a separate line): the price against this piece's planning target (its share of what's
 *  left for ALL open pieces), and over the whole remaining item budget when it is. Never "within budget" overall. */
export function budgetNote(c: {
  price_cents: number | null; budget_left_cents?: number | null; over_budget_by_cents?: number | null;
  budget_target_cents?: number | null; over_target_by_cents?: number | null; open_pieces?: number | null;
}): { text: string; over: boolean } | null {
  if (c.price_cents == null || c.budget_left_cents == null) return null;
  const left = dollars(Math.max(c.budget_left_cents, 0));
  if (c.over_budget_by_cents) return { text: `${dollars(c.over_budget_by_cents)} over the ${left} item budget left`, over: true };
  if (c.budget_target_cents == null) return { text: `Within the ${left} item budget left`, over: false };
  const share = `this piece’s share (${dollars(c.budget_target_cents)}${c.open_pieces && c.open_pieces > 1 ? ` of ${left} for ${c.open_pieces} open pieces` : ""})`;
  return c.over_target_by_cents
    ? { text: `${dollars(c.over_target_by_cents)} over ${share}`, over: true }
    : { text: `Within ${share}`, over: false };
}

export type Placement = { status: "fits" | "moved" | "conflict" | "not_placed"; hard: string[]; soft: string[] };

/** Physical fit, never mixed with budget. "Estimated" when the plan has no usable printed sizes. */
export function placementNote(p: Placement | undefined, basis: "printed" | "relative" | undefined): { text: string; bad: boolean } | null {
  if (!p) return null;
  const est = basis === "relative" ? " (estimated: the plan isn’t to scale)" : "";
  if (p.status === "fits") return { text: `Fits where it is on the plan${est || " (an estimate, not a guarantee)"}`, bad: false };
  if (p.status === "moved") return { text: `Fits at another spot in the same room on the plan${est || " (an estimate)"}; choosing it moves the piece there`, bad: false };
  if (p.status === "not_placed") return { text: "Not on the plan yet, so its fit isn’t checked", bad: false };
  return { text: `Doesn’t fit in its room: ${p.hard[0] ?? "no clear spot"}`, bad: true };
}

/** Where an option's price and size came from, when it isn't the store's own page read directly. */
export function sourceNote(c: { read_via?: string | null; checked_at?: string | null }): string | null {
  if (c.read_via !== "public_reader") return null;
  const d = c.checked_at ? c.checked_at.slice(0, 10) : "an unknown date";
  return `Price, size and condition come from a public copy of the listing page read on ${d} (through a page reader). `
    + "How current that copy was is unknown, and the item may have changed or sold: check the listing.";
}

/** "Choose for me" waits until finding furniture has stopped or finished, so it never picks from half the options. */
export function autoChooseState(o: { finding: boolean; dirty: boolean; open: number }): { enabled: boolean; why: string | null } {
  if (o.finding) return { enabled: false, why: "Wait until finding furniture finishes (or stop it), so every piece’s options are in." };
  if (o.dirty) return { enabled: false, why: "Save your budget and style first." };
  if (!o.open) return { enabled: false, why: "Every piece already has a product." };
  return { enabled: true, why: null };
}

/** Coverage across pieces (not a raw verified count): pieces with an option that physically fits, with options that
 *  don't fit, and with none yet. */
export function coverage(pieces: { id: string }[],
  previews: Record<string, { total: number; total_all?: number; fitting?: number; fitting_affordable?: number } | undefined>):
  { fitting: number; affordable: number; onlyBad: number; none: number; total: number } {
  let fitting = 0, affordable = 0, onlyBad = 0, none = 0;
  for (const p of pieces) {
    const pv = previews[p.id];
    if (!pv || (pv.total_all ?? pv.total) === 0) none++;
    else if ((pv.fitting ?? pv.total) > 0) {
      fitting++;
      if ((pv.fitting_affordable ?? 0) > 0) affordable++;
    } else onlyBad++;
  }
  return { fitting, affordable, onlyBad, none, total: pieces.length };
}

/** Piece types whose FIRST search left fewer than 3 ready options (none, one or two that fit and are affordable) and
 *  haven't had the extra search yet: these (only) may be offered "Search more" (an explicit, paid extra web search per
 *  type). Never run automatically. */
export function refineCandidates(found: Record<string, GroupResult | undefined>, current?: string[]): string[] {
  return Object.entries(found).filter(([k, r]) => r && r.needs_refine && !r.refine && (!current || current.includes(k)))
    .map(([k]) => k);
}

/** What to run after saving settings first: if the SEARCH settings changed, earlier results no longer apply, so a
 *  "Search more"/Continue request becomes a fresh first pass over every piece type (never a refinement of the old
 *  query, never just the old remaining types). Otherwise the requested run stands. */
export function runAfterSave(searchChanged: boolean, only?: string[], refine = false):
  { only?: string[]; refine: boolean; restarted: boolean } {
  return searchChanged && (refine || only) ? { only: undefined, refine: false, restarted: true } : { only, refine, restarted: false };
}

/** A later run's statuses replace the same piece types' earlier ones; the rest of the earlier list stays visible. */
export function mergeProgress(prev: GroupStatus[], next: GroupStatus[]): GroupStatus[] {
  return [...prev.filter((g) => !next.some((x) => x.key === g.key)), ...next];
}

/** Whether the plan has a CONFIRMED sleeping room (bedroom/sleeping/studio), and whether some areas are unsure
 *  (unread map, "other" rooms, or uses that aren't confirmed). Never guessed from the apartment type. */
export function bedroomInfo(rooms: { id: string; kind: string }[], uses: Record<string, { status: string } | undefined>, mapped: boolean):
  { bedroomRecognized: boolean; unsureAreas: boolean } {
  const bedroomRecognized = rooms.some((r) => ["bedroom", "sleeping", "studio"].includes(r.kind) && uses[r.id]?.status === "confirmed");
  const unsureAreas = !mapped || rooms.some((r) => r.kind === "other" || (uses[r.id] && uses[r.id]!.status !== "confirmed"));
  return { bedroomRecognized, unsureAreas };
}

/** What the Choose step shops for: the pieces in the layout (each row is one piece, not one search), with a pointer
 *  to Arrange for anything missing. With no bedroom recognized in a plan with unread or unsure areas, it says so
 *  plainly (a bedroom is never guessed from a "1 bedroom" label). */
export function shoppingLine(o: { pieces: number; searches: number; hasBed: boolean; bedroomRecognized: boolean; unsureAreas: boolean }): string {
  const what = `Shopping for ${o.pieces} piece${o.pieces === 1 ? "" : "s"} in your layout`;
  const share = o.searches && o.searches < o.pieces ? ` (${o.searches} search${o.searches === 1 ? "" : "es"}: pieces of the same type and size share one, and each piece gets its own choice)` : "";
  const room = !o.bedroomRecognized && o.unsureAreas
    ? " No bedroom was recognized on this floor plan (some areas couldn’t be read clearly), so no bed was added. If one of those areas is a bedroom, mark it in Arrange your space, or add a bed there yourself."
    : "";
  return `${what}${share}. Missing ${o.hasBed ? "a piece" : "a bed or another piece"}? Add furniture in Arrange your space.${room}`;
}

/** The queue's live state for one piece (its type+size group), for the piece's own row. */
export function pieceQueueText(state: GroupStatus["state"] | undefined): string | null {
  if (state === "waiting") return "Waiting to search…";
  if (state === "running") return "Searching and checking listings…";
  return null;
}

const REASON_TEXT: Record<string, string> = {
  verified: "verified", sold: "sold or unavailable", missing_price: "no price on the page", missing_size: "no size on the page",
  wrong_size: "a different size", not_matching: "not matching your settings",
  incomplete: "incomplete", access_blocked: "page blocked or unreadable", wrong_type: "different item",
  doesnt_fit: "doesn’t fit the room", gone: "no longer online", over_budget: "above your budget",
  condition_not_shown: "condition not shown as used", other: "not usable",
};

/** One short line per branch, e.g. "new: 3 saved options" / "used: 1 verified, 1 sold". */
export function describeGroup(r: GroupResult): string {
  return Object.values(r.branches).map((b) => {
    const name = b.branch === "used" ? "used" : "new";
    if (b.status === "error") return `${name}: couldn’t search (${b.message ?? "error"})`;
    if (b.status === "paused") return `${name}: paused (${b.message ?? "AI request limit reached"})`;
    if (b.status === "unavailable") return `${name}: ${b.message ?? "your selected marketplaces refused automated reading recently; nothing was searched"}`;
    const skip = b.unavailable_sites?.length ? ` (further checks skipped for ${b.unavailable_sites.join(", ")}: listing pages refused automated access)` : "";
    if (b.searched && !b.checked && b.skipped_refusing) return `${name}: ${b.message ?? "listings came back only from marketplaces that refused automated reading, so none could be checked"}`;
    if (!b.searched) {
      const n = b.ready_existing ?? b.existing ?? 0;
      return `${name}: ${n} saved option${n === 1 ? "" : "s"}${b.ready_existing != null ? " that fit and are within budget" : ""}`;
    }
    if (!b.checked) return `${name}: no product pages found${skip}`;
    return `${name}: ` + Object.entries(b.reasons).map(([k, n]) => `${n} ${REASON_TEXT[k] ?? k}`).join(", ") + skip;
  }).join(" · ");
}
