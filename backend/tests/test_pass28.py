"""Photo-analysis output shape repair, not-to-scale observations, "Closer to my budget" on the REAL catalog, Article
fail-closed SKUs and the new living-room default (DETERMINISTIC / MOCKED AI; nothing leaves the machine)."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from furnishai import ai
from furnishai.adapters import article
from furnishai.app import create_app
from furnishai.catalog import load_catalog
from furnishai.config import REPO_ROOT
from furnishai.geometry import assess_geometry
from furnishai.layout import generate_layouts, room_frame
from furnishai.models import PhotoAnalysisOutput, default_preferences
from furnishai.planner import build_plans

from conftest import make_image, product
from test_domain import prefs, scaled_room

SHIPPED = load_catalog(REPO_ROOT / "data" / "catalog" / "products.json")


def misplaced_output(**top) -> dict:
    """The shape a live model produced: scale/missing_views/reasoning BESIDE geometry (whose keys end at walls)."""
    walls = [{"wall": w, "description": f"wall {w}", "visible": "partly", "photo_indices": idx,
              "features": [{"kind": k, "start_frac": 0.2, "end_frac": 0.6, "photo_indices": idx}] if k else []}
             for w, idx, k in (("A", [0, 1], "window"), ("B", [1, 2], "door"), ("C", [2, 3], None), ("D", [3], None))]
    out = {"room_type_seen": "bedroom",
           "per_photo": [{"photo_index": i, "shows": "empty room", "appears_same_room_as_others": "yes"} for i in range(4)],
           "geometry": {"status": "mapped", "reference_wall_a": "window wall", "shape": "rectangular", "corners_seen": 3,
                        "walls": walls},
           "scale": {"wall_a_length_in_low": 120, "wall_a_length_in_high": 216, "wall_b_length_in_low": 108,
                     "wall_b_length_in_high": 180,
                     "cues": [{"description": "ordinary hinged door", "photo_index": 1, "exact_variant_identified": False}],
                     "reasoning": "broad unverified ranges from an ordinary door"},
           "missing_views": [], "reasoning": "four views of one rectangular room"}
    out.update(top)
    return out


# ------------------------------------------------------------------ output shape
def test_misplaced_geometry_keys_are_moved_recorded_and_still_gated():
    o = PhotoAnalysisOutput.model_validate(misplaced_output())
    assert o.geometry.scale.wall_a_length_in_high == 216 and o.geometry.reasoning.startswith("four views")
    assert o.schema_repairs == ["moved top-level scale, missing_views, reasoning into geometry (nested values were absent)"]
    g = assess_geometry(o, ["p1", "p2", "p3", "p4"], room_photo_count=4)
    # The recovered range is honest but too wide (216/120 > 1.6): NOT drawable, kept as a not-to-scale observation.
    assert g.drawable is False and g.observed_only is True and "too uncertain" in g.reason and "10′0″ to 18′0″" in g.reason
    assert "1.6" not in g.reason and "×" not in g.reason  # plain why, no gate threshold in user-facing copy
    assert {(f.kind, f.wall) for f in g.features} == {("window", "A"), ("door", "B")} and g.width is None and g.depth is None


def test_conflicts_unknown_keys_and_forged_repairs_are_refused():
    both = misplaced_output()
    both["geometry"]["reasoning"] = "a different nested explanation"
    with pytest.raises(ValidationError, match="both inside `geometry` and at the top level"):
        PhotoAnalysisOutput.model_validate(both)
    same = misplaced_output()
    same["geometry"]["reasoning"] = same["reasoning"]  # identical duplicate: fine, nothing to move for that key
    assert "reasoning" not in PhotoAnalysisOutput.model_validate(same).schema_repairs[0].split("moved top-level ")[1].split(" into")[0]
    with pytest.raises(ValidationError):
        PhotoAnalysisOutput.model_validate(misplaced_output(surprise_field=1))  # unknown keys are never silently dropped
    no_geo = misplaced_output()
    del no_geo["geometry"]
    with pytest.raises(ValidationError):
        PhotoAnalysisOutput.model_validate(no_geo)  # strays without a geometry object are rejected, not guessed
    clean = misplaced_output()
    clean["geometry"].update(scale=clean.pop("scale"), missing_views=clean.pop("missing_views"), reasoning=clean.pop("reasoning"))
    forged = PhotoAnalysisOutput.model_validate({**clean, "schema_repairs": ["model says it was repaired"]})
    assert forged.schema_repairs == []  # only the app records repairs; a correctly nested output needs none
    schema = PhotoAnalysisOutput.model_json_schema()
    assert schema.get("additionalProperties") is False and "schema_repairs" not in json.dumps(schema)
    assert "go INSIDE `geometry`" in ai.ROOM_INSTRUCTIONS and ai.ROOM_PROMPT_VERSION == "room-evidence-v5-geometry-shape"


def test_analysis_route_repairs_shape_records_provenance_and_places_nothing(settings):
    def fn(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(misplaced_output()))])
    app = create_app(settings, test_model=FunctionModel(fn))
    c = TestClient(app)
    s = c.post("/api/projects", json={"name": "Real photos", "room_type": "bedroom", "mode": "live"}).json()
    pid = s["project"]["id"]
    files = [("files", (f"v{i}.jpg", make_image(color=(30 * i, 90, 120)), "image/jpeg")) for i in range(4)]
    assert c.post(f"/api/projects/{pid}/uploads", data={"kind": "photo"}, files=files).status_code == 200
    r = c.post(f"/api/projects/{pid}/analyze", json={})
    assert r.status_code == 200, r.text
    st = r.json()["state"]
    room = st["room"]["data"]["room"]
    geo = room["inferred_geometry"]
    assert geo["observed_only"] is True and geo["drawable"] is False and room["scale_status"] == "unknown"
    assert st["room"]["data"]["call"]["schema_repairs"] and st["room"]["prompt_version"] == "room-evidence-v5-geometry-shape"
    for pl in st["plans"]["data"]["plans"]:  # nothing placed, no fit claim from the observation
        assert pl["layouts"]["basis"] == "unavailable" and pl["layouts"]["arrangements"] == []
        assert all(i["fit_label"] == "Fit unverified" for i in pl["items"])


# ------------------------------------------------------------------ "Closer to my budget" on the real catalog
@pytest.mark.parametrize("styles,approach", [([], "balanced"), (["mid_century", "warm_wood"], "balanced"),
                                             (["mid_century", "warm_wood"], "use_for_preferences")])
def test_real_3500_queen_bedroom_offers_a_plan_near_the_allowance(styles, approach):
    pr = default_preferences("bedroom")  # default priorities ["price", "storage"]: must not cap "use more"
    pr.budget_cents, pr.bed_size, pr.styles, pr.budget_approach = 350000, "queen", styles, approach
    ps = build_plans(pr, SHIPPED, None, "bedroom")
    by = {p.key: p for p in ps.plans}
    assert [p.title for p in ps.plans] == ["Save money", "Match my style", "Closer to my budget"]
    allowance = 315000  # $3,500 minus 10% reserve
    assert all(p.item_allowance_cents == allowance and p.subtotal_cents <= allowance for p in ps.plans)
    assert 0.85 * allowance <= by["priority"].subtotal_cents <= allowance  # actually near the budget
    assert by["value"].subtotal_cents == min(p.subtotal_cents for p in ps.plans)
    for p in ps.plans:  # only the chosen furniture types, never extra categories to spend more
        assert sorted(i.category for i in p.items if i.product_id) == sorted(pr.categories)
        assert all(i.availability != "OutOfStock" and i.name and "Queen" in i.name for i in p.items if i.category in ("bed_frame", "mattress"))
    text = " ".join(by["priority"].explanation)
    assert "85–100%" in text and "doesn’t mean better quality" in text and "bounded search" in text
    if approach == "use_for_preferences":
        plain = default_preferences("bedroom")
        plain.budget_cents, plain.bed_size, plain.styles = 350000, "queen", styles
        assert by["balanced"].subtotal_cents > _plan_total(build_plans(plain, SHIPPED, None, "bedroom"), "balanced")


def _plan_total(ps, key):
    return next(p.subtotal_cents for p in ps.plans if p.key == key)


def test_target_plan_keeps_the_room_and_explains_a_shortfall():
    room = scaled_room(150, 170)
    pr = default_preferences("bedroom")
    pr.budget_cents, pr.bed_size = 350000, "queen"
    ps = build_plans(pr, SHIPPED, room, "bedroom")
    by_id = {p["id"]: p for p in SHIPPED}
    frame = room_frame(room, "rv", [])
    hashes = {generate_layouts(p, by_id, pr, frame).envelope_hash for p in ps.plans}
    assert len(hashes) == 1  # every plan, including the near-budget one, uses the same fixed room frame
    small = [product("d1", "desk", 10000), product("d2", "desk", 20000), product("d3", "desk", 40000)]
    short = build_plans(prefs(categories=["desk"], budget_cents=350000, reserve_pct=10), small, None, "bedroom")
    tgt = next(p for p in short.plans if p.key == "priority")
    joined = " ".join(tgt.explanation)
    assert tgt.subtotal_cents == 40000  # as close as the catalog allows, even though far below the band
    assert "Gets to 13%" in joined and "won’t add furniture you didn’t ask for" in joined
    assert all(p.subtotal_cents <= 315000 for p in short.plans)


def test_no_budget_keeps_a_top_priority_third_plan():
    pr = default_preferences("bedroom")
    pr.bed_size = "queen"
    ps = build_plans(pr, SHIPPED, None, "bedroom")
    third = next((p for p in ps.plans if p.key == "priority"), None)
    assert third is None or (third.title == "Top priority first" and third.item_allowance_cents is None)


# ------------------------------------------------------------------ plan-level fit evidence
def _confirmed_10x12():
    from furnishai.models import Bound, RoomModel, RoomFeature
    b = lambda v: Bound(lower=v - 3, central=v, upper=v + 3, method="printed plan, confirmed", strength="strong")  # noqa: E731
    room = RoomModel(room_type="bedroom", scale_status="plan_dimensions_user_confirmed", width=b(120), depth=b(144), method="manual")
    return room, RoomFeature


def test_confirmed_room_plan_overview_never_says_room_unconfirmed():
    room, RoomFeature = _confirmed_10x12()
    pr = default_preferences("bedroom")
    pr.budget_cents, pr.bed_size = 350000, "queen"
    clean = build_plans(pr, SHIPPED, room, "bedroom")
    for p in clean.plans:  # mattress is an accessory of the bed: no footprint of its own, not a failure
        ov = p.fit_overview
        assert ov["room_size"] == "confirmed" and ov["size_checked"] == 3 and ov["size_failed"] == 0 and ov["doors_paths"] == "not_checked"
        assert p.fit_summary == "Tight / conditional"
        assert {i.category: i.fit_checks["size_check"] for i in p.items}["mattress"] == "with_other_item"
    # The same confirmed room with a bathroom area of unknown size: overall fit can't be verified, but the room IS
    # confirmed and every item size check still passed. The reason is named, never "room size not confirmed".
    bath = room.model_copy(update={"features": [RoomFeature(id="f1", kind="bathroom")]})
    ps = build_plans(pr, SHIPPED, bath, "bedroom")
    for p in ps.plans:
        ov = p.fit_overview
        assert p.fit_summary == "Fit unverified" and ov["room_size"] == "confirmed" and ov["size_checked"] == 3
        assert any("bathroom area" in r for r in ov["review_reasons"])
        assert all(i.fit_checks["size_check"] in ("passed", "with_other_item") for i in p.items)


def test_unconfirmed_room_plan_overview_says_so():
    pr = default_preferences("bedroom")
    pr.budget_cents, pr.bed_size = 350000, "queen"
    for p in build_plans(pr, SHIPPED, None, "bedroom").plans:
        assert p.fit_summary == "Fit unverified" and p.fit_overview["room_size"] == "unknown" and p.fit_overview["size_checked"] == 0


# ------------------------------------------------------------------ store filter applies to earlier imports
def test_only_from_article_stops_using_an_earlier_amazon_import_without_deleting_it(settings):
    from furnishai.safe_fetch import RawResponse, SafeFetcher
    page = ('<script type="application/ld+json">{"@type":"Product","name":"Imported Oak Desk","sku":"X1",'
            '"offers":{"@type":"Offer","url":"https://www.amazon.com/dp/X1","price":"45","priceCurrency":"USD"}}</script>'
            '<p>Dimensions: 40 in wide x 20 in deep</p>').encode()
    fetcher = SafeFetcher(resolver=lambda h, p: ["93.184.216.34"],
                          opener=lambda t, h, to, mb: RawResponse(200, {"content-type": "text/html"}, page))
    c = TestClient(create_app(settings, fetcher=fetcher))
    s = c.post("/api/projects", json={"name": "Office", "room_type": "bedroom"}).json()
    pid = s["project"]["id"]
    base = {**s["preferences"]["data"], "categories": ["desk"]}
    c.put(f"/api/projects/{pid}/preferences", json=base)
    imp = c.post(f"/api/projects/{pid}/listings", json={"url": "https://www.amazon.com/dp/X1", "category": "desk", "condition": "new"}).json()
    assert imp["snapshot"]["status"] == "verified" and imp["snapshot"]["retailer"] == "www.amazon.com"
    used = lambda st: {i["product_id"] for pl in st["plans"]["data"]["plans"] for i in pl["items"] if i["product_id"]}  # noqa: E731
    imp_id = imp["snapshot"]["id"]
    assert imp_id in used(imp["state"])  # cheapest desk: Save money uses it
    only = c.put(f"/api/projects/{pid}/preferences", json={**base, "retailers": ["Article"]}).json()
    assert imp_id not in used(only) and all(i["retailer"] == "Article" for pl in only["plans"]["data"]["plans"] for i in pl["items"])
    assert any(x["id"] == imp_id for x in only["imported_listings"])  # the import record is kept, not deleted
    plan = only["plans"]["data"]["plans"][0]
    alts = {a["product_id"]: a for a in c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": plan["key"], "category": "desk"}).json()["alternatives"]}
    assert alts[imp_id]["can_swap"] is False and "allow only Article" in alts[imp_id]["reason"]
    again = c.put(f"/api/projects/{pid}/preferences", json={**base, "retailers": []}).json()
    assert imp_id in used(again)  # any store: allowed again


# ------------------------------------------------------------------ Article fail-closed + defaults
def _art_page(json_sku: str | None, spec_sku: str | None) -> bytes:
    ld = {"@type": "Product", "name": "Test Sofa", "offers": {"@type": "Offer", "url": "https://www.article.com/product/1/t",
                                                             "price": 999, "priceCurrency": "USD"}}
    if json_sku:
        ld["sku"] = json_sku
    spec = f'<div>SKU No.</div><div>{spec_sku}</div>' if spec_sku else ""
    return (f'<script type="application/ld+json">{json.dumps(ld)}</script><div>General Dimensions</div>'
            f'<div>30"H x 80"W x 35"D</div>{spec}<div>Box Dimensions</div><div>20"H x 30"W x 90"L</div>').encode()


@pytest.mark.parametrize("json_sku,spec_sku,priced", [("SKU1", "SKU1", True), ("SKU1", "SKU2", False),
                                                      ("SKU1", None, False), (None, "SKU1", False)])
def test_article_price_needs_both_skus_to_agree(json_sku, spec_sku, priced):
    f = article("https://www.article.com/product/1/t", _art_page(json_sku, spec_sku))
    assert (f.price_usd is not None) is priced and (f.width_in.value, f.depth_in.value) == (80.0, 35.0)


def test_new_living_rooms_start_with_a_plain_sofa_and_old_ones_keep_theirs(settings):
    assert default_preferences("living_room").categories == ["sofa", "coffee_table", "bookcase"]
    c = TestClient(create_app(settings))
    s = c.post("/api/projects", json={"name": "Lounge", "room_type": "living_room"}).json()
    assert "sofa" in s["preferences"]["data"]["categories"]
    old = {**s["preferences"]["data"], "categories": ["sofa_bed", "coffee_table", "bookcase"]}  # an older saved version
    s2 = c.put(f"/api/projects/{s['project']['id']}/preferences", json=old).json()
    assert s2["preferences"]["data"]["categories"] == ["sofa_bed", "coffee_table", "bookcase"]
