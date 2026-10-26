// Run: npm --prefix frontend test   (Node's built-in test runner; Node 22.6+ strips TypeScript types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyIntent } from "../src/intent.ts";
import { fitPlain, planFitPlain, planName, type Plan } from "../src/types.ts";

const plan = (fit_summary: Plan["fit_summary"], fit_overview?: Plan["fit_overview"]) =>
  ({ key: "value", title: "Save money", items: [], fit_summary, fit_overview } as unknown as Plan);
const confirmedOv = (reasons: string[] = []) =>
  ({ room_size: "confirmed", size_checked: 3, size_failed: 0, size_not_run: 0, review_reasons: reasons, doors_paths: "not_checked" } as const);

test("plan fit badge: confirmed room with an unverified part says placement needs review, never 'room not confirmed'", () => {
  const f = planFitPlain(plan("Fit unverified", confirmedOv(["The bathroom area’s size isn’t known, so the free floor is unknown."])), true);
  assert.equal(f.text, "Placement needs review");
  assert.match(f.help, /bathroom area/);
  assert.match(f.help, /3 item size check\(s\) passed/);
  assert.match(f.help, /Door swings, walking paths/);
  // An older saved plan without the overview, on a confirmed room: same honest wording.
  assert.equal(planFitPlain(plan("Fit unverified"), true).text, "Placement needs review");
});

test("plan fit badge: estimates and missing sizes get friendly statuses; passing sizes never claim a guaranteed fit", () => {
  const ov = (room_size: "unknown" | "estimated_plan" | "estimated_photos") =>
    ({ room_size, size_checked: 0, size_failed: 0, size_not_run: 4, review_reasons: [], doors_paths: "not_checked" } as const);
  assert.equal(planFitPlain(plan("Fit unverified", ov("unknown")), false).text, "Fit not assessed");
  assert.equal(planFitPlain(plan("Fit unverified"), false).text, "Fit not assessed");
  assert.equal(planFitPlain(plan("Fit unverified", ov("estimated_plan")), false).text, "Estimated from floor plan");
  assert.equal(planFitPlain(plan("Fit unverified", ov("estimated_photos")), false).text, "Estimated from photos");
  assert.match(planFitPlain(plan("Fit unverified", ov("estimated_plan")), false).help, /your unit may differ/i);
  for (const r of ["unknown", "estimated_plan", "estimated_photos"] as const) {
    assert.doesNotMatch(planFitPlain(plan("Fit unverified", ov(r)), false).text, /not confirmed/i);
  }
  const ok = planFitPlain(plan("Tight / conditional", confirmedOv()), true);
  assert.equal(ok.text, "Item sizes fit the room: check doors & paths");
  assert.doesNotMatch(ok.text + ok.help, /guarantee|definitely fits|will fit/i);
  assert.equal(planFitPlain(plan("Does not fit", confirmedOv()), true).text, "An item is too big for this room");
});

test("plan names are plain for new and older saved titles", () => {
  assert.equal(planName("Save money"), "Save money");
  assert.equal(planName("Closer to my budget"), "Closer to my budget");
  assert.equal(planName("Value: lowest verified item subtotal"), "Save money");
  assert.equal(planName("Balanced: style match at moderate cost"), "Match my style");
  assert.equal(planName("Priority-led: favors your top priority"), "Top priority first");  // the older third plan
  assert.equal(planName("Reuse: arrange what you own (no purchases)"), "Reuse: arrange what you own (no purchases)");
});

test("polite change requests are changes", () => {
  for (const t of ["Can you use more of my budget?", "Could you add a desk?", "Would you remove the nightstand?",
    "Please add a desk", "Can we switch the style to warm wood?", "Use more of my budget", "only from Article",
    "Add a bookcase.", "Could you keep the bed and replace the desk?"]) {
    assert.equal(classifyIntent(t), "change", t);
  }
});

test("genuine questions never change anything", () => {
  for (const t of ["How does fit work?", "Where is my shopping list?", "What does Closer to my budget mean?",
    "Why is the bed so cheap?", "Can you explain how fit works?", "Could you tell me what the budget approach does?",
    "Is the dresser too big?", "Does this include delivery?", "", "   "]) {
    assert.equal(classifyIntent(t), "question", JSON.stringify(t));
  }
});

test("item fit wording: known product in an unsized room is 'Fit not assessed'; unknown product says so", () => {
  const ck = (room_size: string, product_size: string) => ({ room_size, product_size } as unknown as Parameters<typeof fitPlain>[1]);
  assert.equal(fitPlain("Fit unverified", ck("unknown", "known")).text, "Fit not assessed");
  assert.equal(fitPlain("Fit unverified").text, "Fit not assessed");
  assert.equal(fitPlain("Fit unverified", ck("unknown", "unknown")).text, "Product size unavailable");
  assert.equal(fitPlain("Fit unverified", ck("estimated_plan", "known")).text, "Estimated from floor plan");
  for (const t of [fitPlain("Fit unverified", ck("unknown", "known")), fitPlain("Fit unverified", ck("unknown", "unknown"))])
    assert.ok(!/confirm/i.test(t.text + t.help) && t.text !== "Size unavailable");
});
