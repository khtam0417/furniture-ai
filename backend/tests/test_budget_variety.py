"""Budget-aware variety, store filter, out-of-stock handling, fit-check details, Article adapter and the shipped
multi-retailer catalog (DETERMINISTIC; no network, no AI)."""

import json

from fastapi.testclient import TestClient

from furnishai.adapters import article
from furnishai.app import create_app
from furnishai.catalog import load_catalog, mattress_compatibility
from furnishai.config import REPO_ROOT
from furnishai.models import Preferences
from furnishai.planner import alternatives_for, build_plans, check_swap, SwapRejected
from furnishai.preferences import apply_patch, rule_based_patch

from conftest import product
from test_domain import prefs, scaled_room

SHIPPED = load_catalog(REPO_ROOT / "data" / "catalog" / "products.json")
BED = ["bed_frame", "mattress", "nightstand", "dresser"]


def p(pid, cat, dollars, tags=(), retailer="Store A", **kw):
    return product(pid, cat, dollars * 100, tags=tags, retailer=retailer, **kw)


def diverse():
    """Deliberately diverse prices and styles across two stores."""
    return [
        p("bed_cheap", "bed_frame", 150, nominal_size="queen", mattress_size_text='60 " x 80 "'),
        p("bed_wood", "bed_frame", 900, ("warm_wood", "mid_century"), "Store B", nominal_size="queen", mattress_size_text='60 " x 80 "'),
        p("bed_lux_untagged", "bed_frame", 2500, (), "Store B", nominal_size="queen", mattress_size_text='60 " x 80 "'),
        p("mat_cheap", "mattress", 200, ("comfort",), nominal_size="queen", w=60, d=80),
        p("mat_spring", "mattress", 700, ("comfort",), "Store B", nominal_size="queen", w=60, d=80),
        p("ns_cheap", "nightstand", 50),
        p("ns_wood", "nightstand", 300, ("warm_wood", "mid_century"), "Store B"),
        p("dr_cheap", "dresser", 80, ("storage",)),
        p("dr_wood", "dresser", 1000, ("warm_wood", "mid_century", "storage"), "Store B"),
    ]


def _plan(ps, key):
    return next(x for x in ps.plans if x.key == key)


def _ids(plan):
    return {i.category: i.product_id for i in plan.items if i.product_id}


# ------------------------------------------------------------------ 1. budget approach
def test_value_stays_cheapest_and_preferences_can_use_more_of_a_3500_budget():
    base = dict(categories=BED, bed_size="queen", budget_cents=350000, reserve_pct=10, styles=["warm_wood", "mid_century"],
                priorities=["price", "storage"])
    rich = build_plans(prefs(**base, budget_approach="use_for_preferences"), diverse(), None, "bedroom")
    value, bal = _plan(rich, "value"), _plan(rich, "balanced")
    assert _ids(value) == {"bed_frame": "bed_cheap", "mattress": "mat_cheap", "nightstand": "ns_cheap", "dresser": "dr_cheap"}
    assert _ids(bal)["bed_frame"] == "bed_wood" and _ids(bal)["dresser"] == "dr_wood" and _ids(bal)["nightstand"] == "ns_wood"
    assert "bed_lux_untagged" not in _ids(bal).values()  # a higher price alone never wins
    assert _ids(bal)["mattress"] == "mat_cheap"  # equal matches: the cheaper one
    for pl in rich.plans:  # hard cap and clear accounting
        assert pl.subtotal_cents <= pl.item_budget_cents == 315000
        assert pl.item_allowance_cents == 315000 and pl.unused_cents == 315000 - pl.subtotal_cents
    assert any("vs Save money" in d for d in bal.differences) and "Bed frame: " in bal.differences[0]
    assert any("use more for preferences" in e for e in bal.explanation)
    assert any("lowest-priced verified option" in e for e in value.explanation)
    assert {pl.key for pl in rich.plans} <= {"value", "balanced", "priority"}  # stable saved-history keys
    save = _plan(build_plans(prefs(**base, budget_approach="save"), diverse(), None, "bedroom"), "balanced")
    assert save.subtotal_cents < bal.subtotal_cents and "dr_wood" not in _ids(save).values()  # +$920 for one match: no


def test_pricier_matches_are_not_crowded_out_by_many_cheap_products():
    cat = [p(f"desk_cheap{i}", "desk", 60 + i) for i in range(12)] + [p("desk_oak", "desk", 700, ("warm_wood",), "Store B")]
    ps = build_plans(prefs(categories=["desk"], budget_cents=200000, styles=["warm_wood"], priorities=[],
                           budget_approach="use_for_preferences"), cat, None, "bedroom")
    assert _ids(_plan(ps, "value"))["desk"] == "desk_cheap0" and _ids(_plan(ps, "balanced"))["desk"] == "desk_oak"


def test_low_budget_pins_mattress_match_and_condition_still_hold():
    low = build_plans(prefs(categories=BED, bed_size="queen", budget_cents=60000, styles=["warm_wood"], priorities=[],
                            budget_approach="use_for_preferences"), diverse(), None, "bedroom")
    assert low.plans and all(pl.subtotal_cents <= pl.item_budget_cents for pl in low.plans)
    pinned = build_plans(prefs(categories=BED, bed_size="queen", budget_cents=350000, styles=["warm_wood", "mid_century"],
                               budget_approach="use_for_preferences", pinned_product_ids={"bed_frame": "bed_cheap"}),
                         diverse(), None, "bedroom")
    assert all(_ids(pl)["bed_frame"] == "bed_cheap" for pl in pinned.plans)
    bad_mat = p("mat_twin_size", "mattress", 900, ("comfort", "warm_wood", "mid_century"), "Store B", nominal_size="queen", w=38, d=75)
    frame = diverse()[0]
    assert mattress_compatibility(bad_mat, frame) == "incompatible"
    mm = build_plans(prefs(categories=["bed_frame", "mattress"], bed_size="queen", budget_cents=350000,
                           styles=["warm_wood", "mid_century"], budget_approach="use_for_preferences"),
                     diverse() + [bad_mat], None, "bedroom")
    assert all(_ids(pl).get("mattress") != "mat_twin_size" for pl in mm.plans)
    used = [p("ns_used", "nightstand", 40, condition="secondhand"), p("ns_used_wood", "nightstand", 120, ("warm_wood",), condition="secondhand")]
    sh = build_plans(prefs(categories=["nightstand"], condition="secondhand", styles=["warm_wood"], budget_approach="use_for_preferences"),
                     diverse() + used, None, "bedroom")
    assert all(i.condition == "secondhand" for pl in sh.plans for i in pl.items)


def test_out_of_stock_is_never_placed_and_shown_separately():
    oos = p("ns_gone", "nightstand", 200, ("warm_wood", "mid_century"), "Store B", availability="OutOfStock")
    ps = build_plans(prefs(categories=["nightstand"], styles=["warm_wood", "mid_century"], budget_approach="use_for_preferences"),
                     [diverse()[5], oos], None, "bedroom")
    assert all(_ids(pl)["nightstand"] != "ns_gone" for pl in ps.plans)
    plan = ps.plans[0]
    by_id = {x["id"]: x for x in [diverse()[5], oos]}
    try:
        check_swap(plan, "nightstand", oos, prefs(categories=["nightstand"]), by_id, None)
        raise AssertionError("expected a refusal")
    except SwapRejected as exc:
        assert "out of stock" in exc.reason
    alts = {a["product_id"]: a for a in alternatives_for(plan, "nightstand", prefs(categories=["nightstand"]), [diverse()[5], oos], None)}
    assert alts["ns_gone"]["available"] is False and alts["ns_gone"]["can_swap"] is False and alts["ns_cheap"]["recommended"]
    only = build_plans(prefs(categories=["nightstand"]), [oos], None, "bedroom")
    assert not only.plans and only.issues[0].kind == "catalog_gap" and "out of stock" in only.issues[0].detail


def test_store_filter_is_hard_for_imports_too_and_explains_a_settings_gap():
    imp_other = p("imp-desk", "desk", 90, retailer="www.example-shop.com", origin="user_import")
    imp_b = p("imp-desk-b", "desk", 95, retailer="Store B", origin="user_import")
    cat = diverse() + [p("desk_a", "desk", 100), imp_other, imp_b]
    ps = build_plans(prefs(categories=["nightstand", "desk"], retailers=["Store B"]), cat, None, "bedroom")
    assert all(i.retailer == "Store B" for pl in ps.plans for i in pl.items)  # imports from other stores are not used
    assert any(i.product_id == "imp-desk-b" for pl in ps.plans for i in pl.items)  # an import from an allowed store is
    anystore = build_plans(prefs(categories=["desk"], retailers=[]), cat, None, "bedroom")
    assert any(i.product_id == "imp-desk" for pl in anystore.plans for i in pl.items)  # any store: allowed again
    none = build_plans(prefs(categories=["mattress"], bed_size="queen", retailers=["Nowhere"]), cat, None, "bedroom")
    assert none.issues[0].kind == "settings" and "Nowhere" in none.issues[0].detail


def test_budget_approach_and_store_edits_and_old_preferences_stay_readable():
    assert rule_based_patch("Use more of my budget for better matches").set_budget_approach == "use_for_preferences"
    assert rule_based_patch("save money please").set_budget_approach == "save"
    assert rule_based_patch("Only from Article").set_retailers == ["Article"]
    assert rule_based_patch("any store is fine").set_retailers == []
    old = Preferences.model_validate({"budget_cents": 100000, "categories": ["desk"]})  # saved before these fields
    assert old.budget_approach == "balanced" and old.retailers == []
    new, changes = apply_patch(old, rule_based_patch("only from wayfair"), None)  # not a store with checked products
    assert new.retailers == [] and any("Not supported" in c and "Wayfair" in c for c in changes)
    amz, _ = apply_patch(old, rule_based_patch("only from amazon"), None)  # Amazon: a store of imported listings
    assert amz.retailers == ["Amazon"]
    new, changes = apply_patch(old, rule_based_patch("Use more of my budget, only from Article"), None)
    assert new.budget_approach == "use_for_preferences" and new.retailers == ["Article"]
    # A question (the help drawer never sends one, but if it arrives) changes no setting.
    q, qchanges = apply_patch(old, rule_based_patch("Where is my shopping list?"), None)
    assert q.model_dump(exclude={"notes"}) == old.model_dump(exclude={"notes"}) and all(c.startswith("Not supported") for c in qchanges)


# ------------------------------------------------------------------ 2. shipped catalog
def test_shipped_catalog_has_verified_article_products_with_product_not_box_dimensions():
    art = [x for x in SHIPPED if x["retailer"] == "Article"]
    assert len(art) == 21 and all(x["status"] == "verified" for x in art)
    assert {x["category"] for x in art} >= {"bed_frame", "nightstand", "dresser", "desk", "sofa", "sofa_bed", "coffee_table"}
    ceni = next(x for x in art if x["name"].startswith("Ceni 83"))
    assert (ceni["width_in"], ceni["depth_in"], ceni["price_cents"]) == (83.0, 35.0, 109900)  # not the 39 x 86 box
    assert sum(x["availability"] == "OutOfStock" for x in art) == 3
    assert all(x["evidence"]["width_in"].startswith('Article spec "General Dimensions"') for x in art)


def test_real_3500_rooms_get_multi_store_plans_within_the_cap():
    bed = build_plans(prefs(categories=BED, bed_size="queen", budget_cents=350000, reserve_pct=10, styles=["warm_wood", "mid_century"],
                            priorities=["price", "storage"], budget_approach="use_for_preferences"), SHIPPED, None, "bedroom")
    value, bal = _plan(bed, "value"), _plan(bed, "balanced")
    assert value.subtotal_cents < bal.subtotal_cents <= bal.item_budget_cents
    assert {i.retailer for i in bal.items} - {"IKEA US"}  # at least one non-IKEA item
    assert all(i.availability != "OutOfStock" for pl in bed.plans for i in pl.items)
    living = build_plans(prefs(categories=["sofa", "coffee_table", "bookcase"], budget_cents=350000, styles=["modern", "soft"],
                               priorities=["comfort"]), SHIPPED, None, "living_room")
    assert living.plans and all(any(i.category == "sofa" and i.retailer == "Article" for i in pl.items) for pl in living.plans)


def test_article_adapter_drops_price_when_the_variant_is_not_confirmed():
    html = ('<script type="application/ld+json">{"@type":"Product","name":"Test Sofa","sku":"SKU1",'
            '"offers":{"@type":"Offer","url":"https://www.article.com/product/1/test","price":999,"priceCurrency":"USD",'
            '"availability":"https://schema.org/InStock"}}</script>'
            '<div>General Dimensions</div><div>30"H x 80"W x 35"D</div><div>SKU No.</div><div>SKU2</div>'
            '<div>Box Dimensions</div><div>20"H x 30"W x 90"L</div>').encode()
    f = article("https://www.article.com/product/1/test", html)
    assert f.price_usd is None and any("not confirmed" in n for n in f.notes)
    assert (f.width_in.value, f.depth_in.value) == (80.0, 35.0)


# ------------------------------------------------------------------ 3. fit details
def test_fit_checks_say_what_was_and_was_not_checked():
    unscaled = build_plans(prefs(categories=["desk"]), [p("d", "desk", 100)], None, "bedroom")
    it = unscaled.plans[0].items[0]
    assert it.fit_label == "Fit unverified" and it.fit_checks == {
        "product_size": "known", "room_size": "unknown", "size_check": "not_run", "doors_paths": "not_checked"}
    assert not any("not to scale" in e for e in unscaled.plans[0].explanation)
    assert any("approximate rectangle" in e for e in unscaled.plans[0].explanation)
    scaled = build_plans(prefs(categories=["desk"]), [p("d", "desk", 100)], scaled_room(120, 120), "bedroom")
    s = scaled.plans[0].items[0]
    assert s.fit_label == "Tight / conditional" and s.fit_checks["size_check"] == "passed" and s.fit_checks["doors_paths"] == "not_checked"


# ------------------------------------------------------------------ 4. store links (no AI)
def test_store_links_are_free_size_aware_leads_and_owner_only(settings):
    app = create_app(settings)
    c = TestClient(app)
    s = c.post("/api/projects", json={"name": "B", "room_type": "bedroom"}).json()
    pid = s["project"]["id"]
    c.put(f"/api/projects/{pid}/preferences", json={**s["preferences"]["data"], "bed_size": "twin"})
    r = c.get(f"/api/projects/{pid}/store-links", params={"category": "bed_frame"}).json()
    labels = [x["label"] for x in r["links"]]
    assert labels[:3] == ["Search Amazon", "Search Target", "Search Wayfair"] and r["size"] == "twin"
    assert all("twin+bed+frame" in x["url"] for x in r["links"]) and "not recommendations" in r["links"][0]["note"]
    assert TestClient(app).get(f"/api/projects/{pid}/store-links", params={"category": "desk"}).status_code == 404
    st = c.get("/api/status").json()
    assert st["catalog_retailers"]["Article"] == 21 and st["catalog_retailers"]["IKEA US"] >= 30
    assert json.dumps(st).count("gpt-6-luna") >= 1
