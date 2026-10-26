// Run: npm --prefix frontend test
import { test } from "node:test";
import assert from "node:assert/strict";
import { changeProposals, navProposals } from "../src/design/assistantLogic.ts";

test("helper replies split navigation from reviewable changes, keeping the server's indexes", () => {
  const ps = [{ kind: "go_to", step: "choose", label: "Go to Choose furniture", nav: true },
    { kind: "add_piece", label: "Add a desk" }, { kind: "set_budget", label: "Set the total budget to $2,800" },
    { kind: "open_piece", item_id: "pc_1", label: "Show the sofa’s options", nav: true }];
  assert.deepEqual(navProposals(ps).map((p) => [p.index, p.kind]), [[0, "go_to"], [3, "open_piece"]]);
  assert.deepEqual(changeProposals(ps).map((p) => [p.index, p.label]), [[1, "Add a desk"], [2, "Set the total budget to $2,800"]]);
  assert.deepEqual(changeProposals([{ kind: "go_to", label: "x", nav: true }]), []);  // a question: nothing to apply
});
