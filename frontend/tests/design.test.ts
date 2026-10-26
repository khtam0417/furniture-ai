// Run: npm --prefix frontend test
import { test } from "node:test";
import assert from "node:assert/strict";
import { CONCEPT_IN, PIECE_GROUPS, PIECE_NAMES, footprint, pieceName, readableMissing, type DesignItem } from "../src/designTypes.ts";

const piece = (over: Partial<DesignItem>): DesignItem => ({
  id: "pc_1", category: "bed_frame", zone_id: "r1", x: 0.5, y: 0.5, rotation: 0, size: "king", on_item: null,
  product_id: null, owned: false, ...over,
});

test("draft beds use the bed size; a chosen product uses its listed size and is never shrunk", () => {
  assert.deepEqual(footprint(piece({}), {}), { w: 80, d: 84, actual: false });
  const products = { p1: { width_in: 86, depth_in: 90 } };
  assert.deepEqual(footprint(piece({ product_id: "p1" }), products), { w: 86, d: 90, actual: true });
  // A product with no listed size keeps the draft size (and stays marked as draft).
  assert.deepEqual(footprint(piece({ product_id: "p2" }), { p2: { width_in: null, depth_in: null } }), { w: 80, d: 84, actual: false });
});

test("piece names say the bed size only for beds and mattresses", () => {
  assert.equal(pieceName({ category: "bed_frame", size: "king" }), "King bed frame");
  assert.equal(pieceName({ category: "mattress", size: "queen" }), "Queen mattress");
  assert.equal(pieceName({ category: "nightstand", size: "king" }), "Nightstand");
});

test("every piece type is in exactly one add-menu group, with a name and a typical draft size", () => {
  const grouped = PIECE_GROUPS.flatMap(([, cats]) => cats);
  assert.equal(new Set(grouped).size, grouped.length);
  for (const c of grouped) {
    assert.ok(PIECE_NAMES[c], c);
    assert.ok(c === "bed_frame" || CONCEPT_IN[c] !== undefined, c);
  }
  for (const c of ["tv", "tv_stand", "dining_table", "dining_chair", "armchair", "side_table", "ottoman", "console_table",
    "shoe_storage", "floor_lamp"]) {
    assert.ok(grouped.includes(c), c);
  }
  // A TV has no floor footprint (it sits on its stand).
  assert.deepEqual(footprint(piece({ category: "tv", size: null, on_item: "pc_stand" }), {}), { w: 0, d: 0, actual: false });
});

test("missing product facts read in plain words", () => {
  assert.equal(readableMissing(["price_cents", "width_in", "depth_in"]), "price, width, depth");
});
