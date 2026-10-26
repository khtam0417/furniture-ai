"""One "Find furniture" flow: grouped plan, per-branch search+check, previews, soft styles, one-off used listings.

MOCKED AI / FAKE NETWORK: search responses and pages are hand-written fixtures, not live results.
"""

import json

import httpx2

from furnishai.design import style_fit
from furnishai.safe_fetch import RawResponse

from conftest import product
from test_design import TWO_BED
from test_design_refine import ONE_BED, _search_body, client, setup
from test_floorplan_first import amz_page
from test_resale_trust import ld_page, prod
from test_shopping_flow import HTML, Net

AMZ = "https://www.amazon.com/dp/B000000001"
CH = "https://www.chairish.com/product/"


def _live(tmp_path, gateway_urls, pages, prefs_update, outputs=None):
    """gateway_urls(body) -> urls returned for that search request; None -> HTTP 500 for it."""
    sent = []

    def gateway(request):
        body = json.loads(request.content or b"{}")
        sent.append(body)
        urls = gateway_urls(body)
        if urls is None:
            return httpx2.Response(500, json={"error": "x"})
        return httpx2.Response(200, json=_search_body(urls))
    net = Net(pages)
    c, app, calls = client(tmp_path, outputs or [ONE_BED], live=True, gateway=gateway, net=net.fetcher())
    aid, anchor, s = setup(c)
    prefs = {**s["design"]["data"]["prefs"], **prefs_update}
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs}).json()
    return c, app, net, sent, aid, s


def _add(c, aid, s, *ops):
    return c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": list(ops)}).json()


def _is_new(body):
    return "Specific new" in body["input"] or "Product detail pages for specific new" in body["input"]


STAND_USED = CH + "31/walnut-tv-stand"
STAND_SOLD = CH + "32/oak-tv-stand"


def _pages():
    return {AMZ: RawResponse(200, HTML, amz_page().replace(b"Test Nightstand", b"Walnut TV Stand")),
            STAND_USED: RawResponse(200, HTML, ld_page([prod("Walnut TV stand", url=STAND_USED, price="120", cond="UsedCondition",
                                                             width=60, depth=16, avail="InStock")])),
            STAND_SOLD: RawResponse(200, HTML, ld_page([prod("Oak TV stand", url=STAND_SOLD, price="90", cond="UsedCondition",
                                                             width=58, depth=16, avail="SoldOut")]))}


def test_either_searches_both_branches_and_offers_both(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [AMZ] if _is_new(b) else [STAND_USED, STAND_SOLD], _pages(),
                                      {"condition": "either"})
    s = _add(c, aid, s, {"op": "add", "category": "tv_stand", "zone_id": "r2"})
    plan = c.get(f"/api/apartments/{aid}/design/find-plan").json()
    assert plan["branches"] == ["new", "used"] and any(g["key"] == "tv_stand|" for g in plan["groups"]) and sent == []
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "tv_stand|"}).json()
    new, used = r["branches"]["new"], r["branches"]["used"]
    assert new["searched"] and used["searched"] and len(sent) == 2
    assert sum(1 for b in sent if _is_new(b)) == 1 and sum(1 for b in sent if "Used tv stand listings" in b["input"]) == 1
    assert new["verified"] == 1 and used["verified"] == 1 and used["reasons"].get("sold") == 1
    assert r["options_new"] >= 1 and r["options_used"] == 1  # the sold listing is not an option
    stand = next(i for i in s["design"]["data"]["items"] if i["category"] == "tv_stand")
    pv = c.get(f"/api/apartments/{aid}/design/previews").json()["items"][stand["id"]]
    assert {x["condition"] for x in pv["candidates"]} == {"new", "secondhand"}
    assert c.get(f"/api/apartments/{aid}/design").json()["design"]["version"] == s["design"]["version"]  # never chooses
    n = len(sent)
    c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "tv_stand|"})
    assert len(sent) == n and net.requested.count(STAND_USED) == 1  # identical specs reuse searches and checks


def test_secondhand_only_never_searches_new_and_a_failing_branch_keeps_the_other(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [STAND_USED], _pages(), {"condition": "secondhand"})
    s = _add(c, aid, s, {"op": "add", "category": "tv_stand", "zone_id": "r2"})
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "tv_stand|"}).json()
    assert list(r["branches"]) == ["used"] and not any(_is_new(b) for b in sent) and AMZ not in net.requested
    # Either, with the used search failing: the new branch still runs and reports; the used one says so.
    c2, app2, net2, sent2, aid2, s2 = _live(tmp_path / "b", lambda b: [AMZ] if _is_new(b) else None, _pages(), {"condition": "either"})
    s2 = _add(c2, aid2, s2, {"op": "add", "category": "tv_stand", "zone_id": "r2"})
    r2 = c2.post(f"/api/apartments/{aid2}/design/find-group", json={"key": "tv_stand|"}).json()
    assert r2["branches"]["new"]["status"] == "ok" and r2["branches"]["new"]["verified"] == 1
    assert r2["branches"]["used"]["status"] == "error" and r2["options_new"] >= 1


def test_saved_catalog_is_enough_for_new_and_reads_cost_nothing(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "new"})
    c.get(f"/api/apartments/{aid}/design/find-plan")
    c.get(f"/api/apartments/{aid}/design/previews")
    c.get(f"/api/apartments/{aid}/design")
    assert sent == [] and net.requested == []  # no search, AI or fetch on reads
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|"}).json()
    assert r["branches"]["new"]["searched"] is False and r["branches"]["new"]["existing"] >= 3 and sent == []
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    assert len(c.get(f"/api/apartments/{aid}/design/previews").json()["items"][ns["id"]]["candidates"]) >= 3
    assert c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "sofa_bed|"}).status_code == 404


def test_two_bedrooms_share_one_search_group(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "new"}, outputs=[TWO_BED])
    plan = c.get(f"/api/apartments/{aid}/design/find-plan").json()
    beds = [g for g in plan["groups"] if g["category"] == "bed_frame"]
    assert len(beds) == 1 and len(beds[0]["item_ids"]) == 2 and plan["max_per_run"] == 12


def test_a_used_listing_can_be_picked_for_one_piece_only(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "secondhand"})
    anchor = c.get(f"/api/apartments/{aid}/design").json()["anchor_project_id"]
    snap = {**product("imp-one", "nightstand", 5000, w=18, d=15, condition="secondhand"), "origin": "used_listing_check",
            "url": CH + "40/walnut-nightstand", "condition_verified": True, "retailer": "Chairish"}
    app.state.db.upsert_snapshot(snap, snap["id"], anchor, None)
    ns1 = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    s = _add(c, aid, s, {"op": "add", "category": "nightstand", "zone_id": "r1"})
    ns2 = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand" and i["id"] != ns1["id"])
    s = c.post(f"/api/apartments/{aid}/design/items/{ns1['id']}/product", json={"expected_version": s["design"]["version"], "product_id": "imp-one"}).json()
    # Not a recommendation for the second piece (counted as held back); broader browsing shows it, blocked.
    view = c.get(f"/api/apartments/{aid}/design/items/{ns2['id']}/products").json()
    assert "imp-one" not in [o["product_id"] for o in view["candidates"]] and view["held_back"].get("picked_elsewhere") == 1
    pv = c.get(f"/api/apartments/{aid}/design/previews").json()["items"][ns2["id"]]
    assert "imp-one" not in [o["product_id"] for o in pv["candidates"]]
    opts = c.get(f"/api/apartments/{aid}/design/items/{ns2['id']}/products?scope=within_budget").json()["candidates"]
    one = next(o for o in opts if o["product_id"] == "imp-one")
    assert one["picked_elsewhere"] is True and "another piece" in one["blocked"]
    assert c.post(f"/api/apartments/{aid}/design/items/{ns2['id']}/product",
                  json={"expected_version": s["design"]["version"], "product_id": "imp-one"}).status_code == 422
    r = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": s["design"]["version"]}).json()
    assert next(i for i in r["design"]["data"]["items"] if i["id"] == ns2["id"])["product_id"] != "imp-one"


def test_styles_rank_softly_and_never_relax_hard_limits(tmp_path):
    assert style_fit({"curator_tags": ["minimal"]}, ["minimal"])[0] == 1
    near = style_fit({"curator_tags": ["scandinavian"]}, ["minimal"])
    assert near[0] == 0.5 and "Closest available to minimal: tagged scandinavian" in near[2]
    assert style_fit({}, ["minimal"])[2] == "Style not classified"
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "new", "styles": ["traditional"], "bed_size": "king"})
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    v = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?styles_only=true&limit=48").json()
    assert v["candidates"]  # never an empty list just because of style
    if not any(x["style_matches"] for x in v["candidates"]):
        assert v["style_fallback"]
    scores = [x["style_score"] for x in v["candidates"]]
    assert scores == sorted(scores, reverse=True) or v["style_fallback"]
    bed = next(i for i in s["design"]["data"]["items"] if i["category"] == "bed_frame")
    assert c.get(f"/api/apartments/{aid}/design/items/{bed['id']}/products?styles_only=true").json()["candidates"] == []  # no king: size never relaxed



# ------------------------------------------------------------------ root review regressions
def _amz(title, avail=None, asin="B000000001"):
    page = amz_page(asin=asin).replace(b"Test Nightstand", title.encode())
    if avail:
        page = page.replace(b"In Stock", avail.encode())
    return RawResponse(200, HTML, page)


def test_automated_new_checks_verify_type_bundles_and_availability(tmp_path):
    urls = {"https://www.amazon.com/dp/B000000001": _amz("Modern 3-Seat Sofa"),          # wrong type
            "https://www.amazon.com/dp/B000000002": _amz("Set of 2 TV Stands", asin="B000000002"),  # bundle
            }
    order = list(urls)
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: order if _is_new(b) else [], {
        **{u: urls[u] for u in order}}, {"condition": "new"})
    s = _add(c, aid, s, {"op": "add", "category": "tv_stand", "zone_id": "r2"})
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "tv_stand|"}).json()
    new = r["branches"]["new"]
    assert new["checked"] == 2 and new["verified"] == 0 and new["reasons"] == {"wrong_type": 2} and r["options_new"] == 0
    snaps = app.state.db.all("SELECT data FROM product_snapshots WHERE scope!=''")
    assert not any(json.loads(x["data"]).get("category") == "tv_stand" for x in snaps)  # nothing stored under the wrong type
    # The right type works; an out-of-stock one is "sold", not a usable verified option.
    c2, app2, net2, sent2, aid2, s2 = _live(tmp_path / "b", lambda b: ["https://www.amazon.com/dp/B000000001",
                                                                      "https://www.amazon.com/dp/B000000002"] if _is_new(b) else [], {
        "https://www.amazon.com/dp/B000000001": _amz("Walnut TV Stand"),
        "https://www.amazon.com/dp/B000000002": _amz("Oak TV Stand", avail="Currently unavailable", asin="B000000002")}, {"condition": "new"})
    s2 = _add(c2, aid2, s2, {"op": "add", "category": "tv_stand", "zone_id": "r2"})
    r2 = c2.post(f"/api/apartments/{aid2}/design/find-group", json={"key": "tv_stand|"}).json()
    n2 = r2["branches"]["new"]
    assert n2["verified"] == 1 and r2["options_new"] == 1
    assert n2["reasons"] == {"verified": 1, "sold": 1}  # an out-of-stock page is never counted as a usable option


def test_a_queen_search_doesnt_count_a_king_page_as_verified(tmp_path):
    king = "https://www.amazon.com/dp/B000000001"
    page = amz_page(dwh='84"L x 80"W x 14"H', width="", depth="14 inches").replace(b"Test Nightstand", b"King Platform Bed Frame")
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [king] if _is_new(b) else [],
                                      {king: RawResponse(200, HTML, page)}, {"condition": "new", "bed_size": "queen", "retailers": ["Amazon"]})
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "bed_frame|queen"}).json()
    new = r["branches"]["new"]
    assert new["verified"] == 0 and new["reasons"].get("wrong_size") == 1


def test_one_used_listing_is_one_item_across_rechecks(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "secondhand"})
    db = app.state.db
    anchor = c.get(f"/api/apartments/{aid}/design").json()["anchor_project_id"]
    base = {**product("x", "nightstand", 5000, w=18, d=15, condition="secondhand"), "origin": "used_listing_check",
            "condition_verified": True, "retailer": "Chairish"}
    first = {**base, "id": "imp-aaa", "url": CH + "50/walnut-nightstand", "checked_at": "2026-10-26T10:00:00+00:00"}
    again = {**base, "id": "imp-bbb", "url": "https://chairish.com/product/50/walnut-nightstand/?utm=x",
             "checked_at": "2026-10-26T11:00:00+00:00", "price_cents": 5500}
    for p in (first, again):
        db.upsert_snapshot(p, p["id"], anchor, None)
    ns1 = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    s = _add(c, aid, s, {"op": "add", "category": "nightstand", "zone_id": "r1"})
    ns2 = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand" and i["id"] != ns1["id"])
    opts = c.get(f"/api/apartments/{aid}/design/items/{ns1['id']}/products").json()["candidates"]
    assert [o["product_id"] for o in opts] == ["imp-bbb"]  # the same listing appears once (newest check)
    s = c.post(f"/api/apartments/{aid}/design/items/{ns1['id']}/product", json={"expected_version": s["design"]["version"], "product_id": "imp-bbb"}).json()
    # The older record of the SAME listing can't be chosen for another piece (identity, not id).
    assert c.post(f"/api/apartments/{aid}/design/items/{ns2['id']}/product",
                  json={"expected_version": s["design"]["version"], "product_id": "imp-aaa"}).status_code == 422
    r = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": s["design"]["version"]}).json()
    assert next(i for i in r["design"]["data"]["items"] if i["id"] == ns2["id"])["product_id"] not in ("imp-aaa", "imp-bbb")
    # A newer check says it's sold: no longer offered; the chosen piece keeps it with a warning (nothing removed).
    sold = {**base, "id": "imp-ccc", "url": CH + "50/walnut-nightstand", "checked_at": "2026-10-26T12:00:00+00:00",
            "availability": "SoldOut"}
    db.upsert_snapshot(sold, sold["id"], anchor, None)
    st = c.get(f"/api/apartments/{aid}/design").json()
    assert next(i for i in st["design"]["data"]["items"] if i["id"] == ns1["id"])["product_id"] == "imp-bbb"
    assert any("newer check" in w for w in st["evaluation"]["warnings"][ns1["id"]])
    assert c.get(f"/api/apartments/{aid}/design/items/{ns2['id']}/products").json()["candidates"] == []
    assert json.loads(db.one("SELECT data FROM product_snapshots WHERE id='imp-aaa'")["data"])["price_cents"] == 5000  # unchanged


def test_rate_limit_pauses_the_group_with_a_clear_message(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "either"})
    s = _add(c, aid, s, {"op": "add", "category": "tv_stand", "zone_id": "r2"})
    from furnishai.usage import LimitExceeded
    app.state.ledger.reserve = lambda *a, **k: (_ for _ in ()).throw(LimitExceeded(
        "Rate limit: at most 12 AI requests per 10 minutes per session."))
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "tv_stand|"}).json()
    assert r["limited"] and "Rate limit" in r["limited"]
    assert r["branches"]["new"]["status"] == "paused" and r["branches"]["used"]["status"] == "paused"
    assert len(sent) == 0  # no second request after the limit


# ------------------------------------------------------------------ final live-QA corrections
def test_style_is_soft_in_queries_and_omitted_for_mattress_and_tv(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "either", "styles": ["rustic"]})
    s = _add(c, aid, s, {"op": "add", "category": "tv_stand", "zone_id": "r2"}, {"op": "add", "category": "tv", "zone_id": "r2"})
    keys = [g["key"] for g in c.get(f"/api/apartments/{aid}/design/find-plan").json()["groups"]]
    for cat in ("tv_stand", "mattress", "tv"):
        key = next(k for k in keys if k.startswith(cat + "|"))
        n = len(sent)
        c.post(f"/api/apartments/{aid}/design/find-group", json={"key": key})
        qs = [b["input"] for b in sent[n:]]
        new = [q for q in qs if "Specific new" in q or "Product detail pages for specific new" in q]
        used = [q for q in qs if "Used " in q]
        assert used, (cat, qs)  # hard condition terms kept
        assert all("individual secondhand listing pages" in q and "Chairish" in q for q in used)
        assert all("Amazon" in q and "Chairish" not in q for q in new)  # sources never relaxed
        if cat == "mattress":
            assert all(" size mattress" in q for q in qs)  # nominal bed size stays hard
        for q in qs:
            if cat in ("mattress", "tv"):
                assert "rustic" not in q and "style" not in q, q  # no aesthetic style for these types
            else:
                assert "ideally rustic style" in q and "warm wood" in q and "other styles are fine" in q, q
                assert "rustic style)" not in q and ", rustic style" not in q  # never a hard style term


def _used(pid, price, tags, n):
    return {**product(pid, "nightstand", price, w=18, d=15, tags=tags, condition="secondhand"), "origin": "used_listing_check",
            "url": CH + f"{n}/nightstand-{pid}", "condition_verified": True, "retailer": "Chairish"}


def test_price_limit_applies_before_the_soft_style_fallback(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "secondhand", "styles": ["rustic"]})
    anchor = c.get(f"/api/apartments/{aid}/design").json()["anchor_project_id"]
    for snap in (_used("imp-rus", 90000, ["rustic"], 61), _used("imp-wood", 10000, ["warm_wood"], 62)):
        app.state.db.upsert_snapshot(snap, snap["id"], anchor, None)
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    v = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?styles_only=true&max_price_cents=20000").json()
    assert [x["product_id"] for x in v["candidates"]] == ["imp-wood"]  # the unaffordable exact match doesn't hide it
    assert "closest available styles" in v["style_fallback"]
    v = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?styles_only=true").json()
    assert [x["product_id"] for x in v["candidates"]] == ["imp-rus"]  # without a price limit, exact still wins


def test_options_show_the_remaining_item_budget_before_choosing(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "secondhand", "budget_cents": 100000,
                                                                   "reserve_pct": 10})
    anchor = c.get(f"/api/apartments/{aid}/design").json()["anchor_project_id"]
    for snap in (_used("imp-big", 90000, [], 71), _used("imp-small", 10000, [], 72)):
        app.state.db.upsert_snapshot(snap, snap["id"], anchor, None)
    ns1 = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    s = _add(c, aid, s, {"op": "add", "category": "nightstand", "zone_id": "r1"})
    ns2 = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand" and i["id"] != ns1["id"])
    s = c.post(f"/api/apartments/{aid}/design/items/{ns1['id']}/product", json={"expected_version": s["design"]["version"], "product_id": "imp-small"}).json()
    pv = c.get(f"/api/apartments/{aid}/design/previews").json()["items"][ns2["id"]]
    full = c.get(f"/api/apartments/{aid}/design/items/{ns2['id']}/products").json()
    broad = c.get(f"/api/apartments/{aid}/design/items/{ns2['id']}/products?scope=within_budget").json()
    # $900 vs $1000-10%-$100 = $800 left: over the WHOLE remaining item budget, so never offered (only counted).
    for view in (pv, full, broad):
        assert "imp-big" not in [o["product_id"] for o in view["candidates"]]
    assert pv["held_back"].get("over_budget") == 1 and full["held_back"].get("over_budget") == 1
    # The other piece's own option is compared without counting its own current choice.
    own = next(o for o in c.get(f"/api/apartments/{aid}/design/items/{ns1['id']}/products").json()["candidates"] if o["product_id"] == "imp-big")
    assert own["budget_left_cents"] == 90000 and own["over_budget_by_cents"] is None
    # The auto chooser doesn't pick it, and the API refuses it with the exact figures (nothing saved).
    r = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": s["design"]["version"]}).json()
    assert next(i for i in r["design"]["data"]["items"] if i["id"] == ns2["id"])["product_id"] != "imp-big"
    v = r["design"]["version"]
    r = c.post(f"/api/apartments/{aid}/design/items/{ns2['id']}/product", json={"expected_version": v, "product_id": "imp-big"})
    assert r.status_code == 422 and "$900.00" in r.json()["detail"] and "item budget is left" in r.json()["detail"]
    assert c.get(f"/api/apartments/{aid}/design").json()["design"]["version"] == v
