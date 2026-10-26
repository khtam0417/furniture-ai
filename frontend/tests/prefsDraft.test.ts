// Run: npm --prefix frontend test
import { test } from "node:test";
import assert from "node:assert/strict";
import { budgetTextOf, mergeBudgetText, mergeDraft } from "../src/design/prefsDraft.ts";

const saved = { budget_cents: 350000, reserve_pct: 10, styles: ["modern"], condition: "secondhand", bed_size: "queen" };

test("a budget the helper saved reaches the form, and the next search uses it", () => {
  const helperSaved = { ...saved, budget_cents: 300000 };
  const draft = mergeDraft(saved, helperSaved, { ...saved });  // the user hadn't touched anything
  const text = mergeBudgetText(saved.budget_cents, helperSaved.budget_cents, budgetTextOf(saved.budget_cents));
  assert.equal(text, "3000");
  assert.deepEqual(draft, helperSaved);  // nothing left "unsaved": no stale banner, nothing to overwrite
  // What "Save & find" would send now (form text -> cents) is the helper's $3,000, not the old $3,500.
  assert.equal(Math.round(Number(text)) * 100, 300000);
});

test("the user's own unsaved edits are kept and stay unsaved", () => {
  const helperSaved = { ...saved, budget_cents: 300000 };
  const draft = mergeDraft(saved, helperSaved, { ...saved, styles: ["modern", "rustic"] });  // an intentional pending edit
  assert.deepEqual(draft.styles, ["modern", "rustic"]);
  assert.equal(draft.budget_cents, 300000);
  assert.notEqual(JSON.stringify(draft), JSON.stringify(helperSaved));  // still visibly unsaved: only the style
  // A budget the user had typed but not saved is never replaced.
  assert.equal(mergeBudgetText(350000, 300000, "4200"), "4200");
  assert.equal(mergeBudgetText(null, 300000, ""), "3000");
});
