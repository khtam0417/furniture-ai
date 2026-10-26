"""Design-first flow: plan map validation, arrangements, edits, products, budget and checklist.

DETERMINISTIC / MOCKED AI. The plan-map outputs below are SYNTHETIC fixtures written by hand (shaped like the
Audubon studio plan and a 2-bedroom plan); they test code paths, not the model's vision accuracy.
"""

import json
import math

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from furnishai.app import create_app
from furnishai.design import (
    Design, DesignItem, DesignPrefs, arrange, auto_choose, budget_summary, check_items, checklist, default_pieces,
    rect_in_poly, missing_reasons,
)
from furnishai.planmap import PlanMapOutput, point_in_poly, validate_map

from conftest import make_image, product


def P(x, y):
    return {"x": x, "y": y}


def rect(x0, y0, x1, y1):
    return [P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]


# Synthetic studio shaped like the Audubon plan (371 x 480 px image; NOT a model reading).
STUDIO = {
    "is_floor_plan": True, "view": "2d",
    "rooms": [
        {"label": "LIVING / DINING", "kind": "living", "polygon": rect(0.07, 0.15, 0.45, 0.55), "dimension_text": "11'10\" X 15'2\"", "confidence": "medium"},
        {"label": "SLEEPING", "kind": "sleeping", "polygon": rect(0.45, 0.15, 0.82, 0.55), "dimension_text": "11'10\" X 14'2\"", "confidence": "medium"},
        {"label": "BATH", "kind": "bath", "polygon": rect(0.33, 0.62, 0.62, 0.9)},
        {"label": "CLOSET", "kind": "closet", "polygon": rect(0.75, 0.55, 0.82, 0.62)},
        {"label": "BALCONY", "kind": "balcony", "polygon": rect(0.5, 0.02, 0.82, 0.13)},
    ],
    "fixtures": [{"kind": "kitchen_counter", "polygon": rect(0.22, 0.5, 0.65, 0.55)}],
    "openings": [{"kind": "door", "a": P(0.55, 0.15), "b": P(0.75, 0.15)}],
    "walls": [{"a": P(0.07, 0.15), "b": P(0.82, 0.15)}],
    "limitations": ["Door swings unclear."],
}
TWO_BED = {
    "is_floor_plan": True,
    "rooms": [
        {"label": "BEDROOM 1", "kind": "bedroom", "polygon": rect(0.05, 0.05, 0.45, 0.45), "dimension_text": "12' x 12'"},
        {"label": "BEDROOM 2", "kind": "bedroom", "polygon": rect(0.55, 0.05, 0.95, 0.45), "dimension_text": "12' x 12'"},
        {"label": "LIVING", "kind": "living", "polygon": rect(0.05, 0.5, 0.95, 0.95), "dimension_text": "27' x 13'6\""},
        {"label": "BATH", "kind": "bath", "polygon": rect(0.45, 0.05, 0.55, 0.45)},
    ],
}


def vmap(out: dict, w=371, h=480, sid="src_a"):
    return validate_map(PlanMapOutput.model_validate(out), source_id=sid, derivative_sha256="d" * 64, image_w=w, image_h=h,
                        model="gpt-6-luna", synthetic=True)


# ------------------------------------------------------------------ map validation
def test_map_uses_source_pixels_and_printed_scale():
    m = vmap(STUDIO)
    assert m.status == "mapped" and [r.label for r in m.rooms][:2] == ["LIVING / DINING", "SLEEPING"]
    living = m.rooms[0]
    # Normalized -> pixels of the actual (non-square) image: x by width, y by height.
    assert living.polygon[0] == (pytest.approx(0.07 * 371, abs=0.01), pytest.approx(0.15 * 480, abs=0.01))
    assert living.dims_in == (142.0, 182.0) and living.furnishable and not m.room("r3").furnishable
    assert m.scale.kind == "printed" and set(m.scale.from_rooms) == {"r1", "r2"} and 0.9 < m.scale.ppi < 1.15
    # The same map on a wider image keeps its normalized meaning (aspect ratio comes from the source image).
    wide = vmap(STUDIO, w=742, h=480)
    assert wide.rooms[0].polygon[1][0] == pytest.approx(0.45 * 742, abs=0.01)


def test_invalid_geometry_is_dropped_and_never_replaced_by_a_rectangle():
    bad = {"rooms": [
        {"label": "Bow", "kind": "living", "polygon": [P(0.1, 0.1), P(0.9, 0.9), P(0.9, 0.1), P(0.3, 0.9)]},  # self-crossing
        {"label": "Far", "kind": "bedroom", "polygon": rect(0.2, 0.2, 1.4, 0.6)},  # outside the image
        {"label": "Tiny", "kind": "bedroom", "polygon": rect(0.5, 0.5, 0.505, 0.505)},
        {"label": "NaN", "kind": "bedroom", "polygon": [P(math.nan, 0.1), P(0.5, 0.1), P(0.5, 0.5)]},
        {"label": "Edge", "kind": "bedroom", "polygon": rect(-0.01, 0.0, 0.4, 1.015)},  # within tolerance: clamped
    ]}
    m = vmap(bad, w=400, h=300)
    assert [r.label for r in m.rooms] == ["Edge"] and m.rooms[0].polygon[0] == (0.0, 0.0) and m.rooms[0].polygon[2] == (160.0, 300.0)
    assert sum("crosses itself" in x for x in m.rejected) == 1 and any("outside the image" in x for x in m.rejected)
    none = vmap({"rooms": [{"label": "x", "kind": "living", "polygon": [P(0.1, 0.1), P(0.2, 0.2)]}]})
    assert none.status == "fallback" and none.rooms == [] and none.outline == []  # no default apartment shape
    assert vmap({"is_floor_plan": False, "rooms": STUDIO["rooms"]}).status == "fallback"


def test_mismatched_printed_size_is_not_a_scale_and_no_size_means_relative():
    odd = {"rooms": [{"label": "Bed", "kind": "bedroom", "polygon": rect(0.1, 0.1, 0.9, 0.3), "dimension_text": "10' x 10'"}]}
    m = vmap(odd, w=400, h=400)
    assert m.rooms[0].scale_ppi is None and "doesn’t match" in m.rooms[0].scale_note and m.scale.kind == "relative"
    sq = vmap({"rooms": [{"label": "", "kind": "living", "polygon": rect(0.1, 0.1, 0.6, 0.6), "dimension_text": "450 sq ft"}]})
    assert sq.scale.kind == "relative" and sq.rooms[0].dims_in is None  # square footage never becomes a size


def test_non_convex_room_boundary():
    L = [(0, 0), (100, 0), (100, 40), (40, 40), (40, 100), (0, 100)]
    assert point_in_poly((20, 80), L) and not point_in_poly((80, 80), L)
    assert rect_in_poly((5, 5, 35, 95), L)
    assert not rect_in_poly((30, 30, 60, 60), L)  # corners partly in the notch
    assert not rect_in_poly((20, 20, 60, 35), [(0, 0), (100, 0), (100, 30), (50, 30), (50, 40), (0, 40)])  # reflex corner pokes in


# ------------------------------------------------------------------ arrangements and checks
def test_arrangements_avoid_fixed_areas_and_keep_ids():
    m = vmap(STUDIO)
    prefs = DesignPrefs(categories=["bed_frame", "mattress", "nightstand", "dresser"], bed_size="queen")
    items = default_pieces(m, prefs)
    assert {i.zone_id for i in items} == {"r2"}  # the sleeping zone, not the kitchen/bath/closet/balcony
    for key in ("walls", "long_wall", "corners"):
        placed = arrange(m, items, key, {})
        assert [i.id for i in placed] == [i.id for i in items]
        assert all(not w for w in check_items(m, placed, {}).values()), key
        mattress = next(i for i in placed if i.category == "mattress")
        bed = next(i for i in placed if i.category == "bed_frame")
        assert (mattress.x, mattress.y) == (bed.x, bed.y)
    # Moving a piece into the bath is allowed but warned; nothing moves it back or shrinks it.
    moved = [i.model_copy(update={"x": 0.47, "y": 0.75}) if i.category == "dresser" else i for i in placed]
    w = check_items(m, moved, {})
    assert any("outside" in x.lower() or "bath" in x.lower() for x in w[next(i.id for i in moved if i.category == "dresser")])


def test_two_bedrooms_get_their_own_pieces_and_quantities_add_up():
    m = vmap(TWO_BED, w=500, h=500)
    prefs = DesignPrefs(categories=["bed_frame", "nightstand"], bed_size="full")
    items = arrange(m, default_pieces(m, prefs), "walls", {})
    beds = [i for i in items if i.category == "bed_frame"]
    assert len(beds) == 2 and beds[0].id != beds[1].id and {b.zone_id for b in beds} == {"r1", "r2"}
    by_id = {"frame": product("frame", "bed_frame", 15000, w=56, d=80, nominal_size="full")}
    d = Design(plan_source_id="s", items=[i.model_copy(update={"product_id": "frame"}) if i.category == "bed_frame" else i for i in items],
               prefs=DesignPrefs(budget_cents=100000))
    cl = checklist(d, by_id, {}, {})
    row = cl["rows"][0]
    assert row["quantity"] == 2 and row["line_total_cents"] == 30000 and cl["status"] == "incomplete"  # nightstands missing
    # A mark is per piece and per product: after a swap the old mark does not carry over.
    marks = {beds[0].id: {"product_id": "frame", "purchased": 1}}
    assert checklist(d, by_id, marks, {})["rows"][0]["purchased_count"] == 1
    by_id["frame2"] = product("frame2", "bed_frame", 17000, w=56, d=80, nominal_size="full")
    d2 = Design(plan_source_id="s", items=[i.model_copy(update={"product_id": "frame2"}) if i.id == beds[0].id else i for i in d.items], prefs=d.prefs)
    assert sum(r["purchased_count"] for r in checklist(d2, by_id, marks, {})["rows"]) == 0


def test_missing_king_is_incomplete_and_never_downgraded():
    m = vmap(STUDIO)
    cat = [product("ns", "nightstand", 5000, w=18, d=15, tags=("minimal",)), product("ns2", "nightstand", 9000, w=18, d=15),
           product("dr", "dresser", 20000, w=40, d=18), product("qb", "bed_frame", 30000, w=64, d=84, nominal_size="queen")]
    by_id = {p["id"]: p for p in cat}
    prefs = DesignPrefs(budget_cents=300000, styles=["minimal"], bed_size="king", categories=["bed_frame", "mattress", "nightstand", "dresser"])
    d = Design(plan_source_id="s", items=arrange(m, default_pieces(m, prefs), "walls", by_id), prefs=prefs)
    items, notes = auto_choose(d, m, cat, by_id)
    d = d.model_copy(update={"items": items})
    bed = next(i for i in d.items if i.category == "bed_frame")
    assert bed.size == "king" and bed.product_id is None  # the queen frame is never used for a king piece
    assert any("king" in n for n in notes)
    b = budget_summary(d, by_id, missing_reasons(d, cat))
    assert b["status"] == "incomplete" and b["subtotal_cents"] == 5000 + 20000 and b["reserve_cents"] == 30000
    assert {x["name"] for x in b["missing"]} == {"king bed frame", "king mattress"}
    assert all("king" in x["reason"] for x in b["missing"])


def test_larger_product_shows_a_conflict_and_keeps_its_real_size():
    m = vmap(STUDIO)
    prefs = DesignPrefs(categories=["dresser"])
    items = arrange(m, default_pieces(m, prefs), "walls", {})
    big = product("big", "dresser", 40000, w=70, d=22)
    d = Design(plan_source_id="s", items=[items[0].model_copy(update={"product_id": "big"})], prefs=prefs)
    w = check_items(m, d.items, {"big": big})[items[0].id]
    assert any("larger than the draft" in x for x in w)
    from furnishai.design import footprint_in
    assert footprint_in(d.items[0], {"big": big})[:2] == (70.0, 22.0)


def test_use_my_budget_upgrades_only_for_more_matches():
    m = vmap(STUDIO)
    cat = [product("cheap", "nightstand", 5000, w=18, d=15), product("same", "nightstand", 9000, w=18, d=15),
           product("styled", "nightstand", 12000, w=18, d=15, tags=("minimal",))]
    by_id = {p["id"]: p for p in cat}
    base = DesignPrefs(budget_cents=50000, styles=["minimal"], categories=["nightstand"])
    items = arrange(m, default_pieces(m, base), "walls", by_id)
    use, _ = auto_choose(Design(plan_source_id="s", items=items, prefs=base), m, cat, by_id)
    low, _ = auto_choose(Design(plan_source_id="s", items=items, prefs=base.model_copy(update={"approach": "low"})), m, cat, by_id)
    assert use[0].product_id == "styled" and low[0].product_id == "cheap"
    tight = base.model_copy(update={"budget_cents": 12000})  # allowance 10800: the styled one doesn't fit
    t, notes = auto_choose(Design(plan_source_id="s", items=items, prefs=tight), m, cat, by_id)
    # No style gain fits under the ceiling, so the cheaper of two equal matches is taken (no price-driven step-up).
    assert t[0].product_id == "cheap" and any("isn’t higher quality" in n for n in notes)
    tl, _ = auto_choose(Design(plan_source_id="s", items=items, prefs=tight.model_copy(update={"approach": "low"})), m, cat, by_id)
    assert tl[0].product_id == "cheap"


# ------------------------------------------------------------------ review regressions
def test_conflicting_printed_scales_fall_back_to_relative_without_crashing():
    # Root's exact case: two 10' x 10' rooms drawn 120 px and 360 px wide on a 1000 x 1000 image (scales 1 and 3).
    out = {"rooms": [
        {"label": "A", "kind": "bedroom", "polygon": rect(0.1, 0.1, 0.22, 0.22), "dimension_text": "10' x 10'"},
        {"label": "B", "kind": "bedroom", "polygon": rect(0.4, 0.4, 0.76, 0.76), "dimension_text": "10' x 10'"},
    ]}
    m = vmap(out, w=1000, h=1000)
    assert m.status == "mapped" and m.scale.kind == "relative" and "disagree" in m.scale.note and m.scale.from_rooms == []
    assert all("disagrees" in r.scale_note for r in m.rooms)
    # The same conflict with no furnishable room: fallback, still no crash.
    out2 = {"rooms": [{**r, "kind": "bath"} for r in out["rooms"]]}
    m2 = vmap(out2, w=1000, h=1000)
    assert m2.status == "fallback" and m2.scale.kind == "relative"
    # Two agreeing rooms + one outlier: the agreeing pair sets the scale and the outlier is named.
    out3 = {"rooms": out["rooms"] + [{"label": "C", "kind": "living", "polygon": rect(0.8, 0.1, 0.92, 0.22), "dimension_text": "10' x 10'"}]}
    m3 = vmap(out3, w=1000, h=1000)
    assert m3.scale.kind == "printed" and sorted(m3.scale.from_rooms) == ["r1", "r3"] and "isn’t used" in m3.room("r2").scale_note


def test_degenerate_polygons_are_rejected_but_concave_rooms_are_kept():
    def one(poly, w=400, h=400):
        return vmap({"rooms": [{"label": "X", "kind": "living", "polygon": [P(x, y) for x, y in poly]}]}, w=w, h=h)
    # Figure-eight through a repeated (non-adjacent) vertex.
    assert one([(0.1, 0.1), (0.5, 0.5), (0.9, 0.1), (0.9, 0.9), (0.5, 0.5), (0.1, 0.9)]).rooms == []
    # Retraced edge (a spike that doubles back).
    assert one([(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.9), (0.5, 0.95), (0.5, 0.9), (0.1, 0.9)]).rooms == []
    # A vertex touching a non-adjacent edge.
    assert one([(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.1), (0.1, 0.9)]).rooms == []
    # Collinear overlap of two non-adjacent edges.
    assert one([(0.1, 0.1), (0.9, 0.1), (0.9, 0.5), (0.3, 0.5), (0.3, 0.1), (0.2, 0.1), (0.2, 0.9), (0.1, 0.9)]).rooms == []
    # Legitimate concave shapes stay.
    assert len(one([(0.1, 0.1), (0.9, 0.1), (0.9, 0.4), (0.4, 0.4), (0.4, 0.9), (0.1, 0.9)]).rooms) == 1  # L
    assert len(one([(0.1, 0.1), (0.3, 0.1), (0.3, 0.6), (0.7, 0.6), (0.7, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]).rooms) == 1  # U


def test_auto_choose_respects_the_whole_design_allowance():
    # Root's case: two nightstands, one eligible $80 product, budget $100 with no reserve, keep costs low.
    m = vmap(STUDIO)
    cat = [product("ns80", "nightstand", 8000, w=18, d=15)]
    by_id = {p["id"]: p for p in cat}
    prefs = DesignPrefs(budget_cents=10000, reserve_pct=0, approach="low", categories=["nightstand"])
    one = arrange(m, default_pieces(m, prefs), "walls", by_id)
    two = one + [one[0].model_copy(update={"id": "pc_second", "x": 0.7, "y": 0.25})]
    d = Design(plan_source_id="s", items=two, prefs=prefs)
    items, notes = auto_choose(d, m, cat, by_id)
    d = d.model_copy(update={"items": items})
    # Complete set first: the second nightstand's cheapest option ($80) stays reserved, so the first can't take it.
    assert sum(1 for i in items if i.product_id) == 0 and any("too little for the other open pieces" in n for n in notes)
    b = budget_summary(d, by_id, missing_reasons(d, cat))
    assert b["status"] == "incomplete" and b["subtotal_cents"] == 0 and not b["over_allowance"]
    # Existing selections count too: with one already chosen (by the user), the other would go over: nothing is added.
    chosen = d.model_copy(update={"items": [items[0].model_copy(update={"product_id": "ns80"}), items[1]]})
    again, notes = auto_choose(chosen, m, cat, by_id)
    assert [i.product_id for i in again] == ["ns80", None]
    b = budget_summary(chosen, by_id, missing_reasons(chosen, cat))
    assert "over your item budget" in b["missing"][0]["reason"]
    assert "actual checkout costs may differ" in b["note"] and "covered" not in b["note"]


def test_use_my_budget_never_pads_the_price_and_explains_unused_money():
    m = vmap(STUDIO)
    cat = [product("n50", "nightstand", 5000, w=18, d=15), product("n90", "nightstand", 9000, w=18, d=15),
           product("n120", "nightstand", 12000, w=18, d=15)]
    by_id = {p["id"]: p for p in cat}
    prefs = DesignPrefs(budget_cents=12000, reserve_pct=0, approach="use", categories=["nightstand"])
    items = arrange(m, default_pieces(m, prefs), "walls", by_id)
    picked, notes = auto_choose(Design(plan_source_id="s", items=items, prefs=prefs), m, cat, by_id)
    # Three equal (unstyled) designs: the cheapest is taken; a pricier one isn't "better".
    assert picked[0].product_id == "n50" and any("(42%)" in n and "isn’t higher quality" in n for n in notes)
    roomy = prefs.model_copy(update={"budget_cents": 100000})
    picked, notes = auto_choose(Design(plan_source_id="s", items=items, prefs=roomy), m, cat, by_id)
    assert picked[0].product_id == "n50" and any("(5%)" in n for n in notes)


def test_whole_place_starter_set_covers_every_space():
    m = vmap(STUDIO)
    items = default_pieces(m, DesignPrefs())  # no categories: a whole-place starter set
    by_zone = {}
    for i in items:
        by_zone.setdefault(i.zone_id, []).append(i.category)
    assert sorted(by_zone["r2"]) == ["bed_frame", "dresser", "mattress", "nightstand"]  # sleeping
    assert sorted(by_zone["r1"]) == ["coffee_table", "sofa"]  # living/dining
    two = default_pieces(vmap(TWO_BED, w=500, h=500), DesignPrefs())
    assert sum(1 for i in two if i.category == "bed_frame") == 2 and sum(1 for i in two if i.category == "sofa") == 1
    from furnishai.design import prefs_from_room
    from furnishai.models import Preferences
    assert prefs_from_room(Preferences(categories=["bed_frame", "mattress"], bed_size="king")).categories == []


# ------------------------------------------------------------------ API
def client(settings, outputs):
    calls = []

    def fn(messages, info):
        calls.append(1)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(outputs[min(len(calls), len(outputs)) - 1]))])
    app = create_app(settings, test_model=FunctionModel(fn))
    return TestClient(app), app, calls


def setup_apartment(c, n_plans=1):
    a = c.post("/api/apartments", json={"name": "Audubon", "preset": "1b1b"}).json()
    aid = a["apartment"]["id"]
    anchor = a["rooms"][0]["project_id"]
    ids = []
    for k in range(n_plans):
        up = c.post(f"/api/projects/{anchor}/uploads", data={"kind": "floorplan"},
                    files=[("files", (f"plan{k}.png", make_image("PNG", size=(371, 480), color=(250 - 40 * k, 250, 250)), "image/png"))]).json()
        ids.append(next(r["id"] for r in up["results"] if r["ok"]))
    return aid, anchor, ids


def test_design_flow_api(settings):
    c, app, calls = client(settings, [STUDIO, TWO_BED])
    aid, anchor, (plan_a, plan_b) = setup_apartment(c, 2)
    s = c.get(f"/api/apartments/{aid}/design").json()
    assert s["design"] is None and s["suggested_source_id"] is None and len(s["plan_sources"]) == 2  # two unused plans: no guess
    s = c.post(f"/api/apartments/{aid}/design/plan", json={"source_id": plan_a}).json()
    v = s["design"]["version"]
    assert s["selected_source"]["id"] == plan_a and s["plan_map"] is None and s["design"]["data"]["items"] == []
    prefs = {**s["design"]["data"]["prefs"], "budget_cents": 300000, "styles": ["minimal"], "bed_size": "king",
             "categories": ["bed_frame", "mattress", "nightstand", "dresser"], "condition": "new"}
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": v, "prefs": prefs}).json()
    s = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": s["design"]["version"]}).json()
    assert len(calls) == 1 and s["plan_map"]["data"]["status"] == "mapped" and s["plan_map"]["data"]["synthetic"] is False
    assert s["plan_map"]["data"]["source_id"] == plan_a and s["plan_map"]["call"]["method"] == "mocked_ai"
    items = s["design"]["data"]["items"]
    assert sorted(i["category"] for i in items) == ["bed_frame", "dresser", "mattress", "nightstand"]
    assert all(i["zone_id"] == "r2" for i in items)
    map_before = s["plan_map"]
    v = s["design"]["version"]
    # Arrangement options on the same map
    opts = c.get(f"/api/apartments/{aid}/design/arrangements").json()["options"]
    assert [o["key"] for o in opts] == ["walls", "long_wall", "corners"]
    # Drag + rotate persist; the map is untouched
    bed = next(i for i in items if i["category"] == "bed_frame")
    s = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": v, "ops": [
        {"op": "move", "id": bed["id"], "x": 0.6, "y": 0.33}, {"op": "rotate", "id": bed["id"], "rotation": 90}]}).json()
    nb = next(i for i in s["design"]["data"]["items"] if i["id"] == bed["id"])
    mat = next(i for i in s["design"]["data"]["items"] if i["category"] == "mattress")
    assert (nb["x"], nb["y"], nb["rotation"]) == (0.6, 0.33, 90) and (mat["x"], mat["y"]) == (0.6, 0.33)
    assert s["plan_map"] == map_before
    others_before = {i["id"]: (i["x"], i["y"]) for i in items if i["id"] not in (bed["id"], mat["id"])}
    assert {i["id"]: (i["x"], i["y"]) for i in s["design"]["data"]["items"] if i["id"] in others_before} == others_before
    # Stale version and other session
    stale = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": v, "ops": [{"op": "rotate", "id": bed["id"], "rotation": 0}]})
    assert stale.status_code == 409
    other = TestClient(app)
    assert other.get(f"/api/apartments/{aid}/design").status_code == 404
    assert other.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [{"op": "remove", "id": bed["id"]}]}).status_code == 404
    bad = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [{"op": "move", "id": "pc_nope", "x": 0.5, "y": 0.5}]})
    assert bad.status_code == 422
    assert c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"],
                                                               "ops": [{"op": "zone", "id": bed["id"], "zone_id": "r3"}]}).status_code == 422  # bath
    # Missing king: honest incomplete status; auto-choose fills what exists
    v = s["design"]["version"]
    s = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": v}).json()
    b = s["evaluation"]["budget"]
    assert b["status"] == "incomplete" and {m["category"] for m in b["missing"]} == {"bed_frame", "mattress"}
    assert b["subtotal_cents"] == sum(s["products"][i["product_id"]]["price_cents"] for i in s["design"]["data"]["items"] if i["product_id"])
    assert b["reserve_cents"] == 30000 and b["item_allowance_cents"] == 270000
    kb = c.get(f"/api/apartments/{aid}/design/items/{bed['id']}/products").json()
    assert kb["candidates"] == [] and "king" in kb["reason"] and kb["size"] == "king" and kb["search_links"]
    # Checklist: missing pieces listed, marks are per current product
    cl = c.get(f"/api/apartments/{aid}/design/checklist").json()
    assert cl["checklist"]["status"] == "incomplete" and len(cl["checklist"]["missing"]) == 2
    row = cl["checklist"]["rows"][0]
    inst = row["instances"][0]["id"]
    v = cl["version"]
    r = c.post(f"/api/apartments/{aid}/design/checklist/mark", json={"expected_version": v, "instance_id": inst, "product_id": row["product_id"], "purchased": True}).json()
    assert r["checklist"]["purchased"] == 1
    wrong = c.post(f"/api/apartments/{aid}/design/checklist/mark", json={"expected_version": v, "instance_id": inst, "product_id": "other", "purchased": True})
    assert wrong.status_code == 409
    # Explicit bed size change: beds become queen, products can now be chosen
    s = c.get(f"/api/apartments/{aid}/design").json()
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": {**s["design"]["data"]["prefs"], "bed_size": "queen"}}).json()
    assert all(i["size"] == "queen" for i in s["design"]["data"]["items"] if i["category"] in ("bed_frame", "mattress"))
    qb = c.get(f"/api/apartments/{aid}/design/items/{bed['id']}/products").json()["candidates"]
    assert qb and all(x["nominal_size"] == "queen" for x in qb)
    pick = qb[0]
    s = c.post(f"/api/apartments/{aid}/design/items/{bed['id']}/product", json={"expected_version": s["design"]["version"], "product_id": pick["product_id"]}).json()
    assert next(i for i in s["design"]["data"]["items"] if i["id"] == bed["id"])["product_id"] == pick["product_id"]
    assert c.post(f"/api/apartments/{aid}/design/items/{bed['id']}/product",
                  json={"expected_version": s["design"]["version"], "product_id": "ikea-us-not-real"}).status_code == 422
    a_design = s["design"]["data"]
    # Switch to plan B (new map, one more model call), then back to A: A's arrangement returns, no extra call.
    s = c.post(f"/api/apartments/{aid}/design/plan", json={"source_id": plan_b}).json()
    s = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": s["design"]["version"]}).json()
    assert len(calls) == 2 and s["plan_map"]["data"]["source_id"] == plan_b and len([r for r in s["plan_map"]["data"]["rooms"] if r["kind"] == "bedroom"]) == 2
    s = c.post(f"/api/apartments/{aid}/design/plan", json={"source_id": plan_a}).json()
    assert len(calls) == 2 and s["plan_map"]["id"] == map_before["id"]
    assert [(i["id"], i["x"], i["y"], i["product_id"]) for i in s["design"]["data"]["items"]] == \
        [(i["id"], i["x"], i["y"], i["product_id"]) for i in a_design["items"]]
    again = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": s["design"]["version"]}).json()
    assert again["reused"] is True and len(calls) == 2 and again["design"]["version"] == s["design"]["version"]
    # Original plan bytes untouched; versions appended
    db = app.state.db
    assert db.one("SELECT COUNT(*) n FROM design_versions WHERE apartment_id=?", (aid,))["n"] == s["versions"]


def test_identical_bytes_under_two_sources_get_their_own_map(settings):
    import io
    from PIL import Image
    c, app, calls = client(settings, [STUDIO, STUDIO])
    a = c.post("/api/apartments", json={"name": "Twin", "preset": "1b1b"}).json()
    aid, anchor = a["apartment"]["id"], a["rooms"][0]["project_id"]
    img = Image.new("RGB", (371, 480), (240, 240, 240))
    ids = []
    for lvl in (1, 9):
        b = io.BytesIO(); img.save(b, "PNG", compress_level=lvl)
        up = c.post(f"/api/projects/{anchor}/uploads", data={"kind": "floorplan"}, files=[("files", (f"p{lvl}.png", b.getvalue(), "image/png"))]).json()
        ids.append(next(r["id"] for r in up["results"] if r["ok"]))
    for sid_ in ids:
        s = c.get(f"/api/apartments/{aid}/design").json()
        s = c.post(f"/api/apartments/{aid}/design/plan", json={"source_id": sid_}).json()
        s = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": s["design"]["version"]}).json()
        assert s["plan_map"]["data"]["source_id"] == sid_
    assert len(calls) == 2


def test_existing_room_plan_is_suggested_and_unmapped_plan_falls_back(settings):
    c, app, calls = client(settings, [{"is_floor_plan": True, "view": "3d", "rooms": []}])
    aid, anchor, (plan,) = setup_apartment(c, 1)
    assert c.get(f"/api/apartments/{aid}/design").json()["suggested_source_id"] == plan
    s = c.post(f"/api/apartments/{aid}/design/plan", json={"source_id": plan}).json()
    s = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": s["design"]["version"]}).json()
    m = s["plan_map"]["data"]
    assert m["status"] == "fallback" and m["rooms"] == [] and m["scale"]["kind"] == "relative"
    assert s["design"]["data"]["items"]  # conceptual pieces over the original image
    assert c.post("/api/apartments/apt_missing/design/plan", json={"source_id": plan}).status_code == 404
    other = c.post("/api/apartments", json={"name": "Other", "preset": "studio"}).json()["apartment"]["id"]
    assert c.post(f"/api/apartments/{other}/design/plan", json={"source_id": plan}).status_code == 422  # another place's plan
