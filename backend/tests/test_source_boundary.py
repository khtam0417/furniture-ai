"""One furniture-source boundary for search, display, checks and manual imports (user direction: no unknown websites).

DETERMINISTIC / FAKE NETWORK: hand-written pages and search responses.
"""

import json

import httpx2

from furnishai.design import Design, DesignItem, DesignPrefs, candidates_for
from furnishai.safe_fetch import RawResponse
from furnishai.sources import import_listing

from conftest import product
from test_design_refine import ONE_BED, _search_body, client, setup, vmap
from test_floorplan_first import amz_page
from test_resale_trust import ld_page, prod
from test_shopping_flow import HTML, Net, used_page

AMZ = "https://www.amazon.com/dp/B000000001"
UNKNOWN = "https://www.shop.example/products/oak-nightstand-1"
CH = "https://www.chairish.com/product/"


def test_unknown_sites_are_refused_without_any_network_access():
    net = Net({UNKNOWN: RawResponse(200, HTML, used_page())})
    for cond in ("new", "secondhand"):
        snap, res, msg = import_listing(net.fetcher(), UNKNOWN, "nightstand", cond)
        assert snap is None and res is None and ("approved" in msg)
    assert net.requested == []


def test_a_store_redirect_to_an_unknown_site_is_never_contacted():
    net = Net({AMZ: RawResponse(302, {"location": "https://tracker.example/r?u=1"}, b""),
               "https://tracker.example/r": RawResponse(200, HTML, amz_page())})
    snap, _, msg = import_listing(net.fetcher(), AMZ, "nightstand", "new")
    assert snap is None and "refused" in msg and net.requested == [AMZ]


def test_store_filter_and_old_records_are_respected():
    m = vmap(ONE_BED)
    it = DesignItem(id="pc_n", category="nightstand", zone_id="r1", x=0.2, y=0.4)
    old_declared = {**product("imp-old1", "nightstand", 3000, w=18, d=15, condition="secondhand"),
                    "origin": "user_import", "url": CH + "9/old-nightstand", "condition_verified": False}
    old_unknown = {**product("imp-old2", "nightstand", 3500, w=18, d=15), "origin": "user_import", "url": UNKNOWN}
    verified = {**product("imp-ok", "nightstand", 4000, w=18, d=15, condition="secondhand"), "origin": "used_listing_check",
                "url": CH + "10/walnut-nightstand", "condition_verified": True}
    cat = [old_declared, old_unknown, verified]
    by_id = {p["id"]: p for p in cat}
    for cond in ("secondhand", "either"):
        d = Design(plan_source_id="s", items=[it], prefs=DesignPrefs(condition=cond))
        ids = [c["product_id"] for c in candidates_for(it, d, m, cat, by_id)[0]]
        assert ids == ["imp-ok"]  # declared-only used and unknown-site records stay stored but aren't offered
    assert old_declared["condition_verified"] is False  # nothing rewritten


def _live(tmp_path, urls, pages, condition="secondhand", retailers=()):
    sent = []

    def gateway(request):
        sent.append(json.loads(request.content or b"{}"))
        return httpx2.Response(200, json=_search_body(urls))
    net = Net(pages)
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway, net=net.fetcher())
    aid, anchor, s = setup(c)
    prefs = {**s["design"]["data"]["prefs"], "condition": condition, "retailers": list(retailers)}
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs}).json()
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    return c, net, sent, aid, s["design"]["version"], ns


def test_generic_search_hides_unknown_sites_even_when_the_model_returns_them(tmp_path):
    urls = [UNKNOWN, AMZ, CH + "5/walnut-nightstand", "https://www.wayfair.com/furniture/pdp/x-w000123.html"]
    c, net, sent, aid, v, ns = _live(tmp_path, urls, {}, condition="secondhand")
    r = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-online", json={"expected_version": v}).json()
    assert [l["url"] for l in r["online"]["leads"]] == [CH + "5/walnut-nightstand"] and r["online"]["hidden_unapproved"] == 3
    view = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()
    assert all(UNKNOWN != l["url"] for l in view["online"]["leads"]) and net.requested == []
    assert all("wayfair" not in l["url"] for l in view["search_links"])


def test_new_search_honours_the_chosen_stores_and_the_condition_pick_cannot_bypass(tmp_path):
    ikea = "https://www.ikea.com/us/en/p/hemnes-nightstand-80357805/"
    c, net, sent, aid, v, ns = _live(tmp_path, [AMZ, ikea, UNKNOWN], {AMZ: RawResponse(200, HTML, amz_page())},
                                     condition="new", retailers=["IKEA US"])
    r = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-online", json={"expected_version": v}).json()
    assert [l["url"] for l in r["online"]["leads"]] == [ikea] and "IKEA US" in sent[-1]["input"] and "Amazon" not in sent[-1]["input"]
    bad = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v, "url": AMZ, "condition": "new"})
    assert bad.status_code == 422 and net.requested == []  # Amazon isn't among the chosen stores: not read
    # "Secondhand only": a "new" pick in the request can't turn the check into a plain store import.
    c2, net2, _, aid2, v2, ns2 = _live(tmp_path / "b", [AMZ], {AMZ: RawResponse(200, HTML, amz_page())}, condition="secondhand")
    c2.post(f"/api/apartments/{aid2}/design/items/{ns2['id']}/find-online", json={"expected_version": v2})
    r = c2.post(f"/api/apartments/{aid2}/design/items/{ns2['id']}/check-lead", json={"expected_version": v2, "url": AMZ, "condition": "new"})
    assert r.status_code == 422 and "approved resale" in r.json()["detail"] and net2.requested == []


def test_a_fourth_approved_used_listing_can_be_checked_and_chosen(tmp_path):
    leads = [CH + f"{n}/walnut-nightstand-{n}" for n in range(1, 5)]
    pages = {u: RawResponse(200, HTML, ld_page([prod("Walnut nightstand", url=u, price=str(40 + n), cond="UsedCondition",
                                                     width=20, depth=16, avail="InStock")]))
             for n, u in enumerate(leads)}
    c, net, sent, aid, v, ns = _live(tmp_path, leads, pages)
    r = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-secondhand", json={"expected_version": v}).json()
    assert r["checked"] == 3 and leads[3] not in net.requested
    c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-secondhand", json={"expected_version": v, "recheck": True})
    assert leads[3] not in net.requested  # "check again" never silently reaches past the first 3
    one = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead",
                 json={"expected_version": v, "url": leads[3], "condition": "secondhand"}).json()
    assert one["matches"] and net.requested.count(leads[3]) == 1  # exactly one page for this request
    view = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?limit=48").json()
    assert one["product_id"] in {o["product_id"] for o in view["candidates"]}
    assert {l["url"]: (l.get("used_check") or {}).get("outcome") for l in view["secondhand"]["leads"]}[leads[3]] == "verified"


def test_legacy_furniture_research_lists_only_approved_sources(tmp_path):
    c, net, sent, aid, v, ns = _live(tmp_path, [UNKNOWN, AMZ, CH + "7/oak-desk"], {})
    anchor = c.get(f"/api/apartments/{aid}/design").json()["anchor_project_id"]
    r = c.post(f"/api/projects/{anchor}/research/furniture", json={"category": "desk"}).json()
    assert {x["url"] for x in r["results"]} == {AMZ, CH + "7/oak-desk"} and r["hidden_unapproved"] == 1



# ------------------------------------------------------------------ store choices apply to new only; marketplaces to used only
def _used_snap(pid, url, price):
    return {**product(pid, "nightstand", price, w=18, d=15, condition="secondhand"), "origin": "used_listing_check",
            "url": url, "condition_verified": True, "retailer": "Chairish", "condition_evidence": "test fixture"}


def _design_with_used(tmp_path, prefs_update):
    c, app, calls = client(tmp_path, [ONE_BED])
    aid, anchor, s = setup(c)
    db = app.state.db
    for snap in (_used_snap("imp-used1", CH + "21/walnut-nightstand", 9000), _used_snap("imp-used2", CH + "22/oak-nightstand", 7000)):
        db.upsert_snapshot(snap, snap["id"], anchor, None)
    prefs = {**s["design"]["data"]["prefs"], **prefs_update}
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs}).json()
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    return c, aid, s, ns


def _options(c, aid, ns):
    return c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?limit=48").json()["candidates"]


def test_a_hidden_store_choice_never_hides_used_listings(tmp_path):
    # Root's case: secondhand + an old store choice (Amazon) used to exclude every verified used listing.
    c, aid, s, ns = _design_with_used(tmp_path, {"condition": "secondhand", "retailers": ["Amazon"]})
    assert {o["product_id"] for o in _options(c, aid, ns)} == {"imp-used1", "imp-used2"}
    r = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": s["design"]["version"]}).json()
    chosen = next(i for i in r["design"]["data"]["items"] if i["id"] == ns["id"])["product_id"]
    assert chosen in {"imp-used1", "imp-used2"}
    assert r["design"]["data"]["prefs"]["retailers"] == ["Amazon"]  # the store choice is kept for new items


def test_chosen_marketplaces_limit_used_items_and_stores_limit_new_items(tmp_path):
    c, aid, s, ns = _design_with_used(tmp_path, {"condition": "secondhand", "resale_sites": ["ebay"]})
    assert _options(c, aid, ns) == []  # Chairish listings aren't from the chosen marketplace
    bad = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/product", json={"expected_version": s["design"]["version"], "product_id": "imp-used1"})
    assert bad.status_code == 422
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": {
        **s["design"]["data"]["prefs"], "condition": "either", "retailers": ["Article"], "resale_sites": ["chairish"]}}).json()
    opts = _options(c, aid, ns)
    retailers = {o["retailer"] for o in opts}
    assert retailers == {"Article", "Chairish"}  # new from the chosen store only, plus the chosen marketplace's used items
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": {
        **s["design"]["data"]["prefs"], "condition": "new"}}).json()
    assert {o["retailer"] for o in _options(c, aid, ns)} == {"Article"}
    assert s["design"]["data"]["prefs"]["resale_sites"] == ["chairish"]  # switching condition keeps both choices


def test_switching_condition_keeps_chosen_products_with_a_clear_warning(tmp_path):
    c, aid, s, ns = _design_with_used(tmp_path, {"condition": "new"})
    new_pick = _options(c, aid, ns)[0]["product_id"]
    s = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/product", json={"expected_version": s["design"]["version"], "product_id": new_pick}).json()
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": {
        **s["design"]["data"]["prefs"], "condition": "secondhand"}}).json()
    assert next(i for i in s["design"]["data"]["items"] if i["id"] == ns["id"])["product_id"] == new_pick  # not swapped
    assert any("different shopping preferences" in w for w in s["evaluation"]["warnings"][ns["id"]])
