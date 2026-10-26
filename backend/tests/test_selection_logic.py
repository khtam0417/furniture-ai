"""Complete-set-first selection, physical fit, reservations and distinct designs (DETERMINISTIC; no network)."""

from conftest import product
from test_design_refine import ONE_BED, vmap

from furnishai.design import (
    Design, DesignPrefs, arrange, auto_choose, candidates_for, collapse_variants, default_pieces, fit_for, hard_conflicts,
    planning_targets,
)

CH = "https://www.chairish.com/product/"


def used(pid, category, cents, w, d, n, **kw):
    return {**product(pid, category, cents, w=w, d=d, condition="secondhand", **kw), "origin": "used_listing_check",
            "condition_verified": True, "retailer": "Chairish", "url": f"{CH}{n}/{pid}"}


def setup(prefs, cat):
    m = vmap(ONE_BED)
    by_id = {p["id"]: p for p in cat}
    items = arrange(m, default_pieces(m, prefs), "walls", by_id)
    return m, Design(plan_source_id="s", items=items, prefs=prefs), by_id


CASE = DesignPrefs(budget_cents=350000, reserve_pct=10, styles=["modern"], bed_size="queen", condition="secondhand",
                   fulfillment="either")  # the user's failing settings: $3,500, 10% reserve, modern, queen, used only


def test_the_reported_case_never_spends_the_set_on_one_expensive_bed():
    # Only one verified used option exists: the $2,495 Mission oak queen (64 x 87.25 in). Five other pieces are open.
    bed = used("mission", "bed_frame", 249500, 64, 87.25, 35450953, nominal_size="queen")
    m, d, by_id = setup(CASE, [bed])
    items, notes = auto_choose(d, m, [bed], by_id)
    assert all(i.product_id is None for i in items)  # the other five pieces' targets stay reserved
    assert any("Queen bed frame" in n and "too little for the other open pieces" in n for n in notes)
    t = planning_targets(d, [bed], by_id)
    assert len(t) == 6 and set(t) == {i.id for i in d.items}  # every piece has a target, the mattress included
    assert sum(v["target_cents"] for v in t.values()) <= 315000  # never more than the $3,150 item budget
    bed_id = next(i.id for i in d.items if i.category == "bed_frame")
    assert t[bed_id]["target_cents"] < 249500 and t[bed_id]["open_pieces"] == 6


def test_an_option_that_cannot_fit_in_its_room_is_never_auto_chosen_even_if_affordable():
    huge = used("huge", "bed_frame", 30000, 110, 110, 1, nominal_size="queen")  # wider than the bedroom
    ok = used("ok", "bed_frame", 40000, 60, 80, 2, nominal_size="queen")
    prefs = CASE.model_copy(update={"budget_cents": None, "categories": ["bed_frame"]})
    m, d, by_id = setup(prefs, [huge])
    bed = next(i for i in d.items if i.category == "bed_frame")
    assert fit_for(bed, "huge", d.items, m, by_id)["status"] == "conflict"
    items, notes = auto_choose(d, m, [huge], by_id)
    assert next(i for i in items if i.id == bed.id).product_id is None  # no fallback to an impossible pick
    assert any("none of its options fits" in n for n in notes)
    m, d, by_id = setup(prefs, [huge, ok])
    items, _ = auto_choose(d, m, [huge, ok], by_id)
    assert next(i for i in items if i.category == "bed_frame").product_id == "ok"  # the pricier one that fits
    assert not any(hard_conflicts(m, items, by_id).values())


def test_an_existing_bad_spot_doesnt_hide_a_physical_conflict():
    prefs = DesignPrefs(categories=["nightstand"], condition="new")
    ns = product("ns", "nightstand", 5000, w=18, d=15)
    m, d, by_id = setup(prefs, [ns])
    it = d.items[0]
    off = it.model_copy(update={"x": 0.5, "y": 0.66})  # dragged onto the kitchen counter (a fixed area)
    d = d.model_copy(update={"items": [off]})
    cands, _ = candidates_for(off, d, m, [ns], by_id)
    c = cands[0]
    assert c["new_warnings"] == [] or all("Overlaps the" not in w for w in c["new_warnings"])  # same as the baseline...
    assert c["placement"]["status"] in ("moved", "conflict") and c["placement"]["hard"]  # ...but still a hard conflict
    items, _ = auto_choose(d, m, [ns], by_id)
    picked = items[0]
    assert picked.product_id == "ns" and not hard_conflicts(m, items, by_id)[picked.id]  # chosen only at a spot that fits
    assert (picked.x, picked.y) != (off.x, off.y) and picked.zone_id == off.zone_id


def test_picks_are_checked_together_so_two_choices_cant_collide():
    prefs = DesignPrefs(categories=["nightstand"], condition="new")
    big = product("wide", "nightstand", 5000, w=40, d=20)
    m, d, by_id = setup(prefs, [big])
    first = d.items[0]
    second = first.model_copy(update={"id": "pc_twin", "x": first.x + 0.02})  # right next to the first one
    d = d.model_copy(update={"items": [first, second]})
    items, _ = auto_choose(d, m, [big], by_id)
    chosen = [i for i in items if i.product_id]
    assert chosen and not any(hard_conflicts(m, items, by_id)[i.id] for i in chosen)


def test_no_upgrade_while_pieces_are_missing_and_targets_cover_the_attached_mattress():
    prefs = DesignPrefs(budget_cents=200000, reserve_pct=10, styles=["modern"], categories=["bed_frame", "mattress"])
    cheap = product("bed_a", "bed_frame", 30000, w=60, d=80, nominal_size="queen")
    styled = product("bed_b", "bed_frame", 150000, w=60, d=80, nominal_size="queen", tags=("modern",))
    m, d, by_id = setup(prefs, [cheap, styled])  # no mattress options at all
    t = planning_targets(d, [cheap, styled], by_id)
    mat = next(i for i in d.items if i.category == "mattress")
    assert mat.on_item and t[mat.id]["target_cents"] > 0  # the mattress on the bed has its own reserved target
    items, notes = auto_choose(d, m, [cheap, styled], by_id)
    bed = next(i for i in items if i.category == "bed_frame")
    assert bed.product_id == "bed_a"  # the $1,500 styled frame would eat the mattress's share
    assert any("still needs a product, so nothing was upgraded" in n for n in notes)


def test_colour_variants_collapse_but_distinct_designs_stay():
    prefs = DesignPrefs(categories=["nightstand"], condition="new", styles=["modern"])
    cat = [product("h1", "nightstand", 7999, w=18, d=16, name="HEMNES Nightstand - white 18x16", retailer="IKEA US"),
           product("h2", "nightstand", 7999, w=18, d=16, name="HEMNES Nightstand - black-brown 18x16", retailer="IKEA US"),
           product("t1", "nightstand", 4999, w=18, d=15, name="TARVA Nightstand - pine", retailer="IKEA US"),
           product("k1", "nightstand", 9999, w=20, d=16, name="Kast Nightstand - walnut", retailer="Article", tags=("modern",))]
    m, d, by_id = setup(prefs, cat)
    cands, _ = candidates_for(d.items[0], d, m, cat, by_id)
    shown = collapse_variants(cands)
    assert len(cands) == 4 and len(shown) == 3
    hemnes = next(c for c in shown if c["product_id"] in ("h1", "h2"))
    assert hemnes["variants"] == 2 and shown[0]["product_id"] == "k1"  # the style match first, then distinct designs
    a = used("a", "nightstand", 3000, 18, 15, 11, name="Walnut nightstand")
    b = used("b", "nightstand", 3000, 18, 15, 12, name="Walnut nightstand")
    assert len(collapse_variants([{**c, "design_key": None} for c in []])) == 0
    from furnishai.design import design_key
    assert design_key(a) != design_key(b)  # two used listings are two real items, never merged


def test_budget_and_fit_are_reported_separately_on_every_option():
    prefs = CASE.model_copy(update={"condition": "secondhand"})
    bed = used("mission", "bed_frame", 249500, 64, 87.25, 35450953, nominal_size="queen")
    m, d, by_id = setup(prefs, [bed])
    it = next(i for i in d.items if i.category == "bed_frame")
    t = planning_targets(d, [bed], by_id)
    c = candidates_for(it, d, m, [bed], by_id, t)[0][0]
    assert c["budget_left_cents"] == 315000 and c["budget_target_cents"] == t[it.id]["target_cents"]
    assert c["over_target_by_cents"] == 249500 - t[it.id]["target_cents"] and c["open_pieces"] == 6
    assert c["placement"]["status"] in ("fits", "moved", "conflict")


def test_a_piece_skipped_above_its_share_is_completed_once_the_rest_proves_cheap():
    # Root's example: the bed costs $1,000 (above 1.5x its ~$630 share); the other five need $500 together; $1,500 fits
    # the $3,150 item budget, so all six must be chosen, not the bed left empty.
    prefs = DesignPrefs(budget_cents=350000, reserve_pct=10, condition="new")
    cat = [product("bed", "bed_frame", 100000, w=60, d=80, nominal_size="queen"),
           product("mat", "mattress", 15000, w=60, d=80, nominal_size="queen"),
           product("ns", "nightstand", 5000, w=18, d=15), product("dr", "dresser", 10000, w=40, d=18),
           product("so", "sofa", 15000, w=80, d=34), product("ct", "coffee_table", 5000, w=36, d=20)]
    m, d, by_id = setup(prefs, cat)
    items, notes = auto_choose(d, m, cat, by_id)
    assert all(i.product_id for i in items), notes
    assert sum(by_id[i.product_id]["price_cents"] for i in items) == 150000
    assert not any(hard_conflicts(m, items, by_id).values())  # fit is still a hard gate
    assert not any("left without a product" in n for n in notes)


def test_notes_quote_the_true_cheapest_option_and_spent_budgets_get_zero_targets():
    prefs = DesignPrefs(budget_cents=60000, reserve_pct=0, styles=["modern"], condition="new")
    cat = [product("styled", "bed_frame", 200000, w=60, d=80, nominal_size="queen", tags=("modern",)),
           product("plain", "bed_frame", 150000, w=60, d=80, nominal_size="queen")]
    m, d, by_id = setup(prefs, cat)
    items, notes = auto_choose(d, m, cat, by_id)
    bed_note = next(n for n in notes if n.startswith("Queen bed frame"))
    assert "($1,500.00)" in bed_note and "$2,000.00" not in bed_note  # the minimum, not the style-ranked first
    # Everything already chosen uses the whole budget: the open pieces get 0, not an invented cent each.
    full = d.model_copy(update={"prefs": prefs.model_copy(update={"budget_cents": 150000}),
                                "items": [i.model_copy(update={"product_id": "plain"}) if i.category == "bed_frame" else i
                                          for i in d.items]})
    t = planning_targets(full, cat, by_id, m)
    assert t and all(v["target_cents"] == 0 for v in t.values())
