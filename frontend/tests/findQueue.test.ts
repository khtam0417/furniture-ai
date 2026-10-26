// Run: npm --prefix frontend test
import { test } from "node:test";
import assert from "node:assert/strict";
import { autoChooseState, bedroomInfo, budgetNote, coverage, describeGroup, makeStopper, mergeProgress, optionsLine, pieceQueueText, placementNote, refineCandidates, runAfterSave, runFindQueue, searchKey, shoppingLine, sourceNote, type FindGroup, type GroupResult, type GroupStatus } from "../src/design/findQueue.ts";

test("over-budget options are explained, never 'ready'; a type with 1-2 ready options can be searched more", () => {
  // The production case: a $14,500 sofa was the only checked option on a $3,000 budget.
  const sofa = { total: 0, total_new: 0, total_used: 0, total_all: 1,
    held_text: "1 checked option not recommended: 1 was above the item budget left. Looking for affordable options that fit." };
  const line = optionsLine(sofa, "all");
  assert.equal(line?.ready, false);
  assert.ok(line && !/ready/.test(line.text) && /above the item budget/.test(line.text));
  assert.deepEqual(coverage([{ id: "s" }], { s: { ...sofa, fitting: 1, fitting_affordable: 0 } }),
    { fitting: 1, affordable: 0, onlyBad: 0, none: 0, total: 1 });  // has options, none affordable: not "none", not "ready"
  const base = { label: "x", branches: {}, options: 2, options_new: 0, options_used: 2 };
  const found: Record<string, GroupResult> = {
    "coffee_table|": { ...base, key: "coffee_table|", options_ready: 2, needs_refine: true },  // two ready: still offered
    "sofa|": { ...base, key: "sofa|", options_ready: 3, needs_refine: false },
  };
  assert.deepEqual(refineCandidates(found), ["coffee_table|"]);
  assert.match(describeGroup({ ...base, key: "k", branches: { used: { branch: "used", status: "ok", searched: true, checked: 3, verified: 1,
    reasons: { verified: 1, over_budget: 2 }, message: null } } }), /2 above your budget/);
  assert.match(describeGroup({ ...base, key: "k", branches: { new: { branch: "new", status: "ok", searched: false, checked: 0, verified: 0,
    reasons: {}, message: null, existing: 9, ready_existing: 3 } } }), /3 saved options that fit and are within budget/);
});

test("marketplaces that refused automated reading are named, never shown as an empty search", () => {
  const base = { key: "bed_frame|queen", label: "queen bed frame", options: 0, options_new: 0, options_used: 0 };
  const all = describeGroup({ ...base, branches: { used: { branch: "used", status: "unavailable", searched: false, checked: 0, verified: 0,
    reasons: {}, unavailable_sites: ["eBay", "AptDeco"],
    message: "Not searched: all your selected marketplaces (eBay, AptDeco) refused automated reading of listing pages recently, so nothing could be checked. You can choose other marketplaces, or new items, in Shopping preferences." } } });
  assert.match(all, /eBay, AptDeco/);
  assert.match(all, /Shopping preferences/);
  assert.ok(!/saved option|no product pages found|minutes/.test(all));
  const onlyBlocked = describeGroup({ ...base, branches: { used: { branch: "used", status: "ok", searched: true, checked: 0, verified: 0,
    reasons: {}, skipped_refusing: 2, unavailable_sites: ["eBay"],
    message: "Listing pages came back only from eBay, which refused automated reading recently, so none could be checked." } } });
  assert.ok(!/no product pages found/.test(onlyBlocked) && /only from eBay/.test(onlyBlocked));
  const partly = describeGroup({ ...base, branches: { used: { branch: "used", status: "ok", searched: true, checked: 3, verified: 1,
    reasons: { verified: 1, over_budget: 2 }, message: null, skipped_refusing: 2, unavailable_sites: ["eBay"] } } });
  assert.match(partly, /1 verified, 2 above your budget \(further checks skipped for eBay: listing pages refused automated access\)/);
  assert.ok(!/other marketplaces/.test(partly));  // no claim about other sites without evidence
});

test("the Choose step says what it shops for, and explains an unrecognized bedroom without guessing one", () => {
  // Two rows = two design pieces (a sofa and a coffee table), not two searches.
  const two = shoppingLine({ pieces: 2, searches: 2, hasBed: false, bedroomRecognized: false, unsureAreas: false });
  assert.equal(two, "Shopping for 2 pieces in your layout. Missing a bed or another piece? Add furniture in Arrange your space.");
  // A low-confidence plan with an "other" room and no confirmed bedroom: said plainly, no bed invented.
  const rooms = [{ id: "r1", kind: "other" }, { id: "r2", kind: "dining" }, { id: "r3", kind: "living" }];
  const uses = { r1: { status: "uncertain" }, r2: { status: "confirmed" }, r3: { status: "confirmed" } };
  const info = bedroomInfo(rooms, uses, true);
  assert.deepEqual(info, { bedroomRecognized: false, unsureAreas: true });
  assert.match(shoppingLine({ pieces: 2, searches: 2, hasBed: false, ...info }), /No bedroom was recognized.*no bed was added/);
  assert.deepEqual(bedroomInfo([{ id: "r1", kind: "bedroom" }], { r1: { status: "conflict" } }, true),
    { bedroomRecognized: false, unsureAreas: true });  // a "bedroom" with bath fixtures isn't a bedroom
  assert.equal(bedroomInfo([{ id: "r1", kind: "bedroom" }], { r1: { status: "confirmed" } }, true).bedroomRecognized, true);
  // Same type and size share one search, but each piece is its own choice.
  assert.match(shoppingLine({ pieces: 4, searches: 3, hasBed: true, bedroomRecognized: true, unsureAreas: false }),
    /Shopping for 4 pieces in your layout \(3 searches: .*each piece gets its own choice\)\. Missing a piece\?/);
});

test("one click searches every type once; 'Search more' is offered only for unmatched, not-yet-refined types", () => {
  const base = { label: "x", branches: {}, options: 0, options_new: 0, options_used: 0 };
  const found: Record<string, GroupResult> = {
    "bed_frame|queen": { ...base, key: "bed_frame|queen", needs_refine: true },
    "sofa|": { ...base, key: "sofa|", needs_refine: false, options: 3 },
    "mattress|queen": { ...base, key: "mattress|queen", needs_refine: true, refine: true },  // already searched more
    "desk|": { ...base, key: "desk|", needs_refine: true },
  };
  assert.deepEqual(refineCandidates(found), ["bed_frame|queen", "desk|"]);
  assert.deepEqual(refineCandidates(found, ["bed_frame|queen", "sofa|"]), ["bed_frame|queen"]);  // only this plan's types
  // After the explicit extra search, its result replaces the first one and is never offered again (no hidden repeats).
  const after = { ...found, "bed_frame|queen": { ...found["bed_frame|queen"], refine: true, needs_refine: false } };
  assert.deepEqual(refineCandidates(after), ["desk|"]);
});

test("changed search settings never refine or continue an old query: a fresh first pass runs instead", () => {
  assert.deepEqual(runAfterSave(true, ["bed_frame|queen"], true), { only: undefined, refine: false, restarted: true });
  assert.deepEqual(runAfterSave(true, ["sofa|"], false), { only: undefined, refine: false, restarted: true });  // Continue
  assert.deepEqual(runAfterSave(false, ["bed_frame|queen"], true), { only: ["bed_frame|queen"], refine: true, restarted: false });
  assert.deepEqual(runAfterSave(false, ["sofa|"], false), { only: ["sofa|"], refine: false, restarted: false });
  assert.deepEqual(runAfterSave(true, undefined, false), { only: undefined, refine: false, restarted: false });  // already fresh
  // Saved settings belong to a new search key, so earlier results (and their "Search more" offers) are dropped.
  const prefs = { condition: "secondhand", styles: ["modern"], bed_size: "queen", fulfillment: "either", resale_sites: [],
    retailers: [], budget_cents: 350000, reserve_pct: 10 };
  assert.notEqual(searchKey(prefs, "New Haven"), searchKey({ ...prefs, budget_cents: 300000 }, "New Haven"));
});

test("a 'Search more' run keeps earlier statuses visible and a paused one leaves the rest for Continue", async () => {
  const first: GroupStatus[] = [{ key: "a", label: "a", state: "done" }, { key: "b", label: "b", state: "done" }];
  const merged = mergeProgress(first, [{ key: "b", label: "b (searching more)", state: "running" }]);
  assert.deepEqual(merged.map((g) => [g.key, g.state]), [["a", "done"], ["b", "running"]]);
  const sent: [string, boolean][] = [];
  const res = await runFindQueue(groups(3), async (k) => {
    sent.push([k, true]);
    return k === "g1" ? { ...result(k), limited: "This session’s search allowance would be exceeded (an estimated $2.00 in total for this browser session)." } : result(k);
  }, { max: 12, shouldStop: () => false, onUpdate: () => undefined, pauseOn: (r) => r.limited ?? null });
  assert.deepEqual(res.remaining, ["g1", "g2"]);  // Continue resumes these, as "searching more" runs
  assert.match(res.paused!, /^This session’s search allowance/);
  assert.equal(sent.length, 2);  // nothing after the limit
});

test("options read from a public page copy say so, with the date and no freshness promise", () => {
  const n = sourceNote({ read_via: "public_reader", checked_at: "2026-10-26T14:21:00+00:00" })!;
  assert.match(n, /public copy of the listing page read on 2026-10-26/);
  assert.match(n, /How current that copy was is unknown/);
  assert.ok(!/in stock|available now|fresh/i.test(n));
  assert.equal(sourceNote({ read_via: null, checked_at: "2026-10-26" }), null);  // read directly: the usual date line
});

const groups = (n: number): FindGroup[] =>
  Array.from({ length: n }, (_, i) => ({ key: `g${i}`, category: "nightstand", size: null, label: `group ${i}`, item_ids: [`pc_${i}`] }));
const result = (key: string): GroupResult => ({
  key, label: key, options: 1, options_new: 1, options_used: 0,
  branches: { new: { branch: "new", status: "ok", searched: false, checked: 0, verified: 0, reasons: {}, message: null, existing: 4 } },
});

test("runs groups one at a time, up to the limit, and leaves the rest for Continue", async () => {
  const ran: string[] = [];
  const seen: GroupStatus[][] = [];
  const out = await runFindQueue(groups(5), async (k) => { ran.push(k); return result(k); },
    { max: 3, shouldStop: () => false, onUpdate: (s) => seen.push(s) });
  assert.deepEqual(ran, ["g0", "g1", "g2"]);
  assert.deepEqual(out.remaining, ["g3", "g4"]);
  assert.ok(seen.some((s) => s[0].state === "running" && s[1].state === "waiting"));  // visible progress per group
});

test("a failing group is recorded and the others still run", async () => {
  const out = await runFindQueue(groups(3), async (k) => { if (k === "g1") throw new Error("AI not connected"); return result(k); },
    { max: 12, shouldStop: () => false, onUpdate: () => undefined });
  assert.deepEqual(out.statuses.map((s) => s.state), ["done", "error", "done"]);
  assert.equal(out.statuses[1].error, "AI not connected");
});

test("stop ends after the current group", async () => {
  let stop = false;
  const out = await runFindQueue(groups(4), async (k) => { if (k === "g1") stop = true; return result(k); },
    { max: 12, shouldStop: () => stop, onUpdate: () => undefined });
  assert.deepEqual(out.statuses.map((s) => s.state), ["done", "done", "not_run", "not_run"]);
});

test("each branch is described honestly", () => {
  const r: GroupResult = { ...result("g"), branches: {
    new: { branch: "new", status: "ok", searched: false, checked: 0, verified: 0, reasons: {}, message: null, existing: 3 },
    used: { branch: "used", status: "ok", searched: true, checked: 3, verified: 1, reasons: { verified: 1, sold: 1, access_blocked: 1 }, message: null },
  } };
  assert.equal(describeGroup(r), "new: 3 saved options · used: 1 verified, 1 sold or unavailable, 1 page blocked or unreadable");
  const e: GroupResult = { ...result("g"), branches: { used: { branch: "used", status: "error", searched: false, checked: 0, verified: 0, reasons: {}, message: "AI not connected" } } };
  assert.equal(describeGroup(e), "used: couldn’t search (AI not connected)");
});

test("the AI request limit pauses the queue with its message and keeps the rest continuable", async () => {
  const ran: string[] = [];
  const out = await runFindQueue(groups(4), async (k) => {
    ran.push(k);
    return k === "g1" ? { ...result(k), limited: "Rate limit: at most 12 AI requests per 10 minutes per session." } : result(k);
  }, { max: 12, shouldStop: () => false, onUpdate: () => undefined, pauseOn: (r) => r.limited ?? null });
  assert.deepEqual(ran, ["g0", "g1"]);  // no further requests after the limit
  assert.equal(out.paused, "Rate limit: at most 12 AI requests per 10 minutes per session.");
  assert.deepEqual(out.remaining, ["g1", "g2", "g3"]);  // the limited group is retried on Continue
});

test("option cards separate budget from fit and never call the whole remainder this piece's", () => {
  // The reported case: $2,495 bed, $3,150 left for 6 open pieces, the bed's share about $630.
  assert.deepEqual(budgetNote({ price_cents: 249500, budget_left_cents: 315000, over_budget_by_cents: null,
    budget_target_cents: 63000, over_target_by_cents: 186500, open_pieces: 6 }),
    { text: "$1,865 over this piece’s share ($630 of $3,150 for 6 open pieces)", over: true });
  assert.equal(budgetNote({ price_cents: 349500, budget_left_cents: 234400, over_budget_by_cents: 115100 })?.text,
    "$1,151 over the $2,344 item budget left");
  assert.equal(budgetNote({ price_cents: 50000, budget_left_cents: 315000, budget_target_cents: 63000, over_target_by_cents: null,
    open_pieces: 6 })?.text, "Within this piece’s share ($630 of $3,150 for 6 open pieces)");
  assert.equal(budgetNote({ price_cents: 99500, budget_left_cents: null }), null);  // no budget set: no claim
  assert.ok(!JSON.stringify(budgetNote({ price_cents: 1, budget_left_cents: 315000 })).includes("for this piece"));
});

test("fit is its own line: where it is, moved within the room, or not fitting", () => {
  assert.deepEqual(placementNote({ status: "fits", hard: [], soft: [] }, "printed"),
    { text: "Fits where it is on the plan (an estimate, not a guarantee)", bad: false });
  assert.match(placementNote({ status: "fits", hard: [], soft: [] }, "relative")!.text, /estimated: the plan isn’t to scale/);
  assert.match(placementNote({ status: "moved", hard: ["Extends outside Bedroom."], soft: [] }, "printed")!.text, /same room/);
  assert.deepEqual(placementNote({ status: "conflict", hard: ["Extends outside Bedroom."], soft: [] }, "printed"),
    { text: "Doesn’t fit in its room: Extends outside Bedroom.", bad: true });
  assert.equal(placementNote(undefined, "printed"), null);
});

test("Choose for me waits for the finding queue and coverage counts pieces, not verified pages", () => {
  assert.deepEqual(autoChooseState({ finding: true, dirty: false, open: 5 }).enabled, false);
  assert.match(autoChooseState({ finding: true, dirty: false, open: 5 }).why!, /Wait until finding furniture finishes/);
  assert.equal(autoChooseState({ finding: false, dirty: false, open: 5 }).enabled, true);
  assert.equal(autoChooseState({ finding: false, dirty: true, open: 5 }).enabled, false);
  assert.equal(autoChooseState({ finding: false, dirty: false, open: 0 }).enabled, false);
  const pieces = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }];
  assert.deepEqual(coverage(pieces, { a: { total: 3, fitting: 2 }, b: { total: 1, fitting: 0 }, c: { total: 0 } }),
    { fitting: 1, affordable: 0, onlyBad: 1, none: 2, total: 4 });
  // The root's case: 4 pieces have an option that fits the plan, none within its share: never reported as "ready".
  const four = { a: { total: 1, fitting: 1, fitting_affordable: 0 }, b: { total: 2, fitting: 2, fitting_affordable: 0 },
    c: { total: 1, fitting: 1, fitting_affordable: 0 }, d: { total: 6, fitting: 6, fitting_affordable: 0 } };
  assert.deepEqual(coverage(pieces, four), { fitting: 4, affordable: 0, onlyBad: 0, none: 0, total: 4 });
});

test("each piece row shows the queue's live state", () => {
  assert.equal(pieceQueueText("waiting"), "Waiting to search…");
  assert.equal(pieceQueueText("running"), "Searching and checking listings…");
  assert.equal(pieceQueueText("done"), null);
  assert.equal(pieceQueueText(undefined), null);
});

test("leaving the step stops after the current group; returning doesn't resume; Continue runs only the rest", async () => {
  const stopper = makeStopper();
  const saved: string[] = [];
  const ran: string[] = [];
  const out = await runFindQueue(groups(4), async (k) => {
    ran.push(k);
    if (k === "g1") stopper.stop("left");  // the user clicks Next while g1 is searching
    saved.push(k);  // the in-flight group still finishes and its evidence is kept
    return result(k);
  }, { max: 12, shouldStop: stopper.shouldStop, onUpdate: () => undefined });
  assert.deepEqual(ran, ["g0", "g1"]);
  assert.deepEqual(saved, ["g0", "g1"]);
  assert.deepEqual(out.statuses.map((s) => s.state), ["done", "done", "not_run", "not_run"]);
  assert.deepEqual(out.remaining, ["g2", "g3"]);
  stopper.stop("user");
  assert.equal(stopper.reason(), "left");  // the first reason is the one reported
  assert.ok(stopper.shouldStop());  // coming back to the step changes nothing until an explicit Continue
  stopper.reset();  // Continue
  const more = await runFindQueue(groups(4).filter((g) => out.remaining.includes(g.key)), async (k) => { ran.push(k); return result(k); },
    { max: 12, shouldStop: stopper.shouldStop, onUpdate: () => undefined });
  assert.deepEqual(ran, ["g0", "g1", "g2", "g3"]);
  assert.deepEqual(more.remaining, []);
});

test("found results belong to the saved search settings, not to the design version", () => {
  const prefs = { condition: "secondhand", styles: ["rustic", "warm_wood"], bed_size: "queen", fulfillment: "either", resale_sites: [],
    retailers: [], budget_cents: 350000, reserve_pct: 10, approach: "low", timing: "" };
  const k = searchKey(prefs, "New Haven, CT");
  assert.equal(searchKey({ ...prefs, styles: ["warm_wood", "rustic"], approach: "use", timing: "soon" }, "New Haven, CT"), k);
  for (const change of [{ condition: "either" }, { bed_size: "king" }, { styles: ["modern"] }, { budget_cents: 200000 },
    { fulfillment: "local_pickup" }, { resale_sites: ["chairish"] }, { retailers: ["IKEA US"] }, { reserve_pct: 5 }]) {
    assert.notEqual(searchKey({ ...prefs, ...change }, "New Haven, CT"), k, JSON.stringify(change));
  }
  assert.notEqual(searchKey(prefs, "06510"), k);
});

test("a piece's options line follows the active New/Secondhand filter", () => {
  const bed = { total: 7, total_new: 7, total_used: 0 };
  assert.deepEqual(optionsLine(bed, "used"), { ready: false, text: "No checked secondhand options yet. 7 new options available under All/New." });
  assert.equal(optionsLine(bed, "all")?.text, "7 options ready. Choose one below.");
  const sofa = { total: 4, total_new: 3, total_used: 1 };
  assert.equal(optionsLine(sofa, "used")?.text, "1 secondhand option ready. Choose one below. 3 new options available under All/New.");
  assert.equal(optionsLine(sofa, "new")?.text, "3 new options ready. Choose one below. 1 secondhand option available under All/Secondhand.");
  assert.equal(optionsLine(sofa, "all")?.text, "4 options ready (3 new, 1 used). Choose one below.");
  assert.deepEqual(optionsLine({ total: 2, total_new: 0, total_used: 2 }, "new"),
    { ready: false, text: "No checked new options yet. 2 secondhand options available under All/Secondhand." });
  assert.equal(optionsLine({ total: 0, total_new: 0, total_used: 0 }, "all"), null);
  assert.equal(optionsLine(undefined, "used"), null);
});
