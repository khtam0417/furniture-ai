"""Shopping preferences in Choose furniture, the secondhand flow, and added furniture types.

DETERMINISTIC / MOCKED AI / FAKE NETWORK: pages and search responses are hand-written fixtures; nothing here says
anything about real retailers or real listings.
"""

import json

import httpx2
from fastapi.testclient import TestClient

from furnishai.design import (
    Design, DesignItem, DesignPrefs, arrange, candidates_for, check_items, checklist, default_pieces,
)
from furnishai.models import normalize_category
from furnishai.safe_fetch import RawResponse, SafeFetcher
from furnishai.sources import import_used_listing, used_condition_evidence

from conftest import product
from test_design_refine import ONE_BED, P, _search_body, client, rect, setup, vmap


def used_page(name="Walnut nightstand", price="45.00", cond="https://schema.org/UsedCondition",
              avail="https://schema.org/InStock", dims="18 in W x 15 in D", extra=""):
    offer = {"@type": "Offer", "price": price, "priceCurrency": "USD", "availability": avail}
    if cond:
        offer["itemCondition"] = cond
    ld = {"@context": "https://schema.org", "@type": "Product", "name": name, "offers": offer}
    return (f'<html><head><title>{name}</title><script type="application/ld+json">{json.dumps(ld)}</script></head>'
            f"<body><h1>{name}</h1><p>{dims}</p>{extra}</body></html>").encode()


class Net:
    def __init__(self, pages, private=()):
        self.pages, self.private, self.requested = pages, set(private), []

    def resolver(self, host, port):
        return ["10.0.0.7"] if host in self.private else ["93.184.216.34"]

    def opener(self, target, headers, timeout, max_bytes):
        url = f"{target.scheme}://{target.host}{target.path}"
        self.requested.append(url)
        return self.pages.get(url, RawResponse(404, {"content-type": "text/html"}, b"nf"))

    def fetcher(self):
        return SafeFetcher(resolver=self.resolver, opener=self.opener)


HTML = {"content-type": "text/html"}


# ------------------------------------------------------------------ used-condition evidence
def test_used_evidence_comes_only_from_the_page():
    assert used_condition_evidence(used_page(), "https://x.example/p/1")[0] == "used"
    assert used_condition_evidence(used_page(cond="https://schema.org/NewCondition"), "https://x.example/p/1")[0] == "new"
    assert used_condition_evidence(used_page(cond=None, extra="<p>Condition: Pre-owned, light wear</p>"), "https://x.example/p/1")[0] == "used"
    assert used_condition_evidence(used_page(cond=None), "https://x.example/p/1")[0] is None  # a used-sounding domain or query isn't evidence


def test_new_retailer_pages_never_become_used_and_sold_listings_cannot_be_chosen():
    net = Net({"https://www.aptdeco.com/products/walnut-nightstand": RawResponse(200, HTML, used_page()),
               "https://www.aptdeco.com/products/new-nightstand": RawResponse(200, HTML, used_page(cond="https://schema.org/NewCondition")),
               "https://www.aptdeco.com/products/sold-nightstand": RawResponse(200, HTML, used_page(avail="https://schema.org/SoldOut"))})
    f = net.fetcher()
    snap, _, out = import_used_listing(f, "https://www.amazon.com/Some-Bed/dp/B000000001", "nightstand")
    assert snap is None and "approved resale" in out and net.requested == []  # never even fetched
    snap, _, out = import_used_listing(f, "https://www.aptdeco.com/products/new-nightstand", "nightstand")
    assert snap is None and "new condition" in out
    snap, _, out = import_used_listing(f, "https://www.aptdeco.com/products/walnut-nightstand", "nightstand")
    assert out == "verified" and snap["condition"] == "secondhand" and snap["condition_verified"] is True
    assert snap["price_cents"] == 4500 and (snap["width_in"], snap["depth_in"]) == (18.0, 15.0)
    assert "UsedCondition" in snap["condition_evidence"]
    sold, _, out = import_used_listing(f, "https://www.aptdeco.com/products/sold-nightstand", "nightstand")
    assert out.startswith("sold") and sold["availability"] == "SoldOut"
    prefs = DesignPrefs(condition="secondhand")
    m = vmap(ONE_BED)
    it = DesignItem(id="pc_n", category="nightstand", zone_id="r1", x=0.2, y=0.4)
    d = Design(plan_source_id="s", items=[it], prefs=prefs)
    cat = [snap, sold]
    ids = {c["product_id"] for c in candidates_for(it, d, m, cat, {p["id"]: p for p in cat})[0]}
    assert snap["id"] in ids and sold["id"] not in ids


# ------------------------------------------------------------------ secondhand batch through the API
LEADS = ["https://www.aptdeco.com/products/walnut-nightstand-1",
         "https://www.unknown-resale.example/products/cheap-nightstand-9",  # not an approved marketplace: hidden, never fetched
         "https://www.chairish.com/product/22/new-nightstand",
         "https://www.ebay.com/itm/33",  # approved host that resolves to a private address: refused by the safe fetcher
         "https://newhaven.craigslist.org/fuo/d/new-haven-fourth-nightstand/7712345678.html",
         "https://www.ebay.com/sch/i.html?_nkw=nightstand"]


def test_find_secondhand_checks_a_bounded_batch_across_sources_and_caches(tmp_path):
    sent = []

    def gateway(request):
        sent.append(json.loads(request.content or b"{}"))
        return httpx2.Response(200, json=_search_body(LEADS))
    net = Net({LEADS[0]: RawResponse(200, HTML, used_page()),
               LEADS[1]: RawResponse(200, HTML, used_page(name="Cheap nightstand")),
               LEADS[2]: RawResponse(200, HTML, used_page(cond="https://schema.org/NewCondition")),
               LEADS[4]: RawResponse(200, HTML, used_page(name="Fourth nightstand"))}, private={"www.ebay.com"})
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway, net=net.fetcher())
    aid, anchor, s = setup(c)
    prefs = {**s["design"]["data"]["prefs"], "condition": "secondhand"}
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs}).json()
    v = s["design"]["version"]
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    view = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()
    assert view["candidates"] == [] and view["reason_kind"] == "condition" and "bed size" not in (view["reason"] or "")
    reason = next(m for m in s["evaluation"]["budget"]["missing"] if m["id"] == ns["id"])["reason"]
    assert "Find secondhand options" in reason and "bed size" not in reason
    url = f"/api/apartments/{aid}/design/items/{ns['id']}/find-secondhand"
    assert c.post(url, json={"expected_version": v - 1}).status_code == 409
    assert TestClient(app).post(url, json={"expected_version": v}).status_code == 404
    r = c.post(url, json={"expected_version": v}).json()
    q = sent[-1]["input"]
    assert "Used nightstand listings" in q and "New Haven" in q and "7C" not in q
    assert "AptDeco" in q and "Kaiyo" not in q
    # 3 checks, one per marketplace; only 1 usable, so up to 3 more from the SAME search (here the last approved one).
    assert r["checked"] == 4 and r["verified_matches"] == 2
    outcomes = {l["url"]: (l.get("used_check") or {}).get("outcome") for l in r["secondhand"]["leads"]}
    assert LEADS[1] not in outcomes and LEADS[1] not in net.requested and r["secondhand"]["hidden_unapproved"] >= 2
    assert outcomes[LEADS[0]] == "verified" and "new condition" in outcomes[LEADS[2]]
    assert "couldn’t be read" in outcomes[LEADS[3]]  # private address refused by the safe fetcher; batch continued
    assert outcomes[LEADS[4]] == "verified" and LEADS[5] not in net.requested  # a search page is never fetched
    opts = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()
    assert len(opts["candidates"]) == 2 and {c_["condition"] for c_ in opts["candidates"]} == {"secondhand"}
    assert opts["secondhand"]["leads"][0]["used_check"]["outcome"] == "verified"
    n_req, n_sent = len(net.requested), len(sent)
    c.post(url, json={"expected_version": v})
    assert len(net.requested) == n_req and len(sent) == n_sent  # cached search and cached checks
    assert c.get(f"/api/apartments/{aid}/design").json()["design"]["version"] == v  # searching never edits the design


# ------------------------------------------------------------------ preferences moved to Choose furniture
def test_pickup_delivery_and_timing_live_in_the_design_preferences(tmp_path):
    sent = []

    def gateway(request):
        sent.append(json.loads(request.content or b"{}"))
        return httpx2.Response(200, json=_search_body(["https://www.example.com/products/x-1"]))
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway)
    aid, anchor, s = setup(c)
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    prefs = {**s["design"]["data"]["prefs"], "fulfillment": "local_pickup", "timing": "before Dec 1"}
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs}).json()
    got = c.get(f"/api/apartments/{aid}/design").json()["design"]["data"]["prefs"]
    assert (got["fulfillment"], got["timing"]) == ("local_pickup", "before Dec 1")
    c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-online", json={"expected_version": s["design"]["version"]})
    assert "for local pickup near New Haven" in sent[-1]["input"] and "delivery" not in sent[-1]["input"] and "7C" not in sent[-1]["input"]
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"],
                                                           "prefs": {**prefs, "fulfillment": "delivery"}}).json()
    c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-online", json={"expected_version": s["design"]["version"]})
    assert "with delivery in the US" in sent[-1]["input"] and "pickup" not in sent[-1]["input"]


def test_pickup_without_a_location_asks_for_one_and_old_designs_read_the_old_place_setting(tmp_path):
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=lambda r: httpx2.Response(200, json=_search_body([])))
    a = c.post("/api/apartments", json={"name": "NoLoc", "preset": "1b1b", "context": {
        "property_name": "", "city": "", "state": "", "zip": "", "unit_label": "9A", "property_url": "",
        "condition": "secondhand", "fulfillment": "local_pickup", "timing": "this week"}}).json()
    aid, anchor = a["apartment"]["id"], a["rooms"][0]["project_id"]
    from conftest import make_image
    up = c.post(f"/api/projects/{anchor}/uploads", data={"kind": "floorplan"},
                files=[("files", ("plan.png", make_image("PNG", size=(640, 480)), "image/png"))]).json()
    src = next(r["id"] for r in up["results"] if r["ok"])
    s = c.post(f"/api/apartments/{aid}/design/plan", json={"source_id": src}).json()
    p = s["design"]["data"]["prefs"]
    assert (p["fulfillment"], p["timing"], p["condition"]) == ("local_pickup", "this week", "secondhand")  # carried forward
    s = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": s["design"]["version"]}).json()
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    r = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-online", json={"expected_version": s["design"]["version"]})
    assert r.status_code == 422 and "city" in r.json()["detail"]
    assert c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()["needs_location"] is True
    # A design saved before the move (no fulfillment in its stored prefs) reads the place's old setting, without writing.
    db = app.state.db
    head = db.design_head(aid)
    data = head["data"]
    data["prefs"] = {k: v for k, v in data["prefs"].items() if k not in ("fulfillment", "timing")}
    db.add_design_version(aid, data, head["plan_map_id"], "pre-migration copy (test)", head["version"])
    n = db.one("SELECT COUNT(*) n FROM design_versions WHERE apartment_id=?", (aid,))["n"]
    got = c.get(f"/api/apartments/{aid}/design").json()["design"]["data"]["prefs"]
    assert got["fulfillment"] == "local_pickup" and got["timing"] == "this week"
    assert db.one("SELECT COUNT(*) n FROM design_versions WHERE apartment_id=?", (aid,))["n"] == n


# ------------------------------------------------------------------ added furniture types
def test_new_types_are_recognised_and_never_auto_added():
    assert normalize_category("TV stand") == "tv_stand" and normalize_category("television") == "tv"
    assert normalize_category("End table") == "side_table" and normalize_category("shoe rack") == "shoe_storage"
    assert normalize_category("dining chair") == "dining_chair" and normalize_category("floor lamp") == "floor_lamp"
    m = vmap(ONE_BED)
    cats = {i.category for i in default_pieces(m, DesignPrefs())}
    assert cats.isdisjoint({"tv", "tv_stand", "dining_table", "dining_chair", "armchair", "side_table", "ottoman",
                            "console_table", "shoe_storage", "floor_lamp"})


def test_tv_needs_a_stand_and_its_listed_width_is_checked(tmp_path):
    c, app, calls = client(tmp_path, [ONE_BED])
    aid, anchor, s = setup(c)
    s = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [
        {"op": "add", "category": "tv"}]}).json()
    tv = next(i for i in s["design"]["data"]["items"] if i["category"] == "tv")
    assert not tv["placed"] and "TV stand" in tv["unplaced_reason"] and tv["on_item"] is None
    s = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [
        {"op": "add", "category": "tv_stand", "zone_id": "r2"}]}).json()
    stand = next(i for i in s["design"]["data"]["items"] if i["category"] == "tv_stand")
    assert stand["placed"] and stand["zone_id"] == "r2"
    s = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [
        {"op": "attach", "id": tv["id"], "host_id": stand["id"]}]}).json()
    tv = next(i for i in s["design"]["data"]["items"] if i["id"] == tv["id"])
    assert tv["on_item"] == stand["id"] and tv["placed"]
    s2 = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [
        {"op": "add", "category": "tv"}]}).json()  # a second TV: the only stand is taken
    assert not next(i for i in s2["design"]["data"]["items"] if i["category"] == "tv" and i["id"] != tv["id"])["placed"]
    bad = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s2["design"]["version"], "ops": [
        {"op": "attach", "id": tv["id"], "host_id": next(i for i in s2["design"]["data"]["items"] if i["category"] == "sofa")["id"]}]})
    assert bad.status_code == 422
    # Width check uses listed widths, never a diagonal.
    m = vmap(ONE_BED)
    items = [DesignItem.model_validate(i) for i in s["design"]["data"]["items"]]
    by_id = {"tv65": product("tv65", "tv", 50000, w=57.0, d=3.0), "st40": product("st40", "tv_stand", 9000, w=40.0, d=16.0)}
    items = [i.model_copy(update={"product_id": "tv65"}) if i.category == "tv" else
             i.model_copy(update={"product_id": "st40"}) if i.category == "tv_stand" else i for i in items]
    assert any("wider than its stand" in w for w in check_items(m, items, by_id)[tv["id"]])


def test_dining_pieces_go_together_and_new_types_can_be_chosen_and_listed():
    m = vmap({"rooms": [
        {"label": "LIVING", "kind": "living", "polygon": rect(0.05, 0.05, 0.6, 0.95)},
        {"label": "DINING", "kind": "dining", "polygon": rect(0.62, 0.05, 0.95, 0.6)},
        {"label": "BATH", "kind": "bath", "polygon": rect(0.62, 0.62, 0.95, 0.95)},
    ]}, w=600, h=600)
    prefs = DesignPrefs(categories=["dining_table", "dining_chair", "armchair", "side_table", "floor_lamp"])
    items = arrange(m, default_pieces(m, prefs), "walls", {})
    table = next(i for i in items if i.category == "dining_table")
    chair = next(i for i in items if i.category == "dining_chair")
    assert table.placed and table.zone_id == "r2" and chair.placed and chair.zone_id == "r2"
    assert all(i.zone_id != "r3" for i in items)
    assert not any(w for w in check_items(m, items, {}).values() if any("Overlaps" in x or "fixed" in x for x in w))
    cat = [product("dt1", "dining_table", 25000, w=47.0, d=30.0), product("lamp1", "floor_lamp", 6000, w=12.0, d=12.0)]
    by_id = {p["id"]: p for p in cat}
    d = Design(plan_source_id="s", items=items, prefs=prefs)
    assert [c["product_id"] for c in candidates_for(table, d, m, cat, by_id)[0]] == ["dt1"]
    lamp = next(i for i in items if i.category == "floor_lamp")
    d = d.model_copy(update={"items": [i.model_copy(update={"product_id": "dt1"}) if i.id == table.id else
                                       i.model_copy(update={"product_id": "lamp1"}) if i.id == lamp.id else i for i in items]})
    cl = checklist(d, by_id, {}, {})
    assert {r["category"] for r in cl["rows"]} == {"dining_table", "floor_lamp"} and cl["total_cents"] == 31000


def test_requested_tv_without_a_stand_waits_and_with_one_sits_on_it():
    m = vmap(ONE_BED)
    alone = arrange(m, default_pieces(m, DesignPrefs(categories=["tv"])), "walls", {})
    assert len(alone) == 1 and not alone[0].placed and "TV stand" in alone[0].unplaced_reason
    both = arrange(m, default_pieces(m, DesignPrefs(categories=["tv_stand", "tv"])), "walls", {})
    stand = next(i for i in both if i.category == "tv_stand")
    tv = next(i for i in both if i.category == "tv")
    assert stand.placed and tv.on_item == stand.id and tv.placed and (tv.x, tv.y) == (stand.x, stand.y)


def test_two_rooms_with_the_same_label_are_numbered_not_merged():
    from furnishai.design_api import zone_names
    m = vmap({"rooms": [
        {"label": "BEDROOM", "kind": "bedroom", "polygon": rect(0.05, 0.05, 0.45, 0.45)},
        {"label": "BEDROOM", "kind": "bedroom", "polygon": rect(0.55, 0.05, 0.95, 0.45)},
        {"label": "LIVING", "kind": "living", "polygon": rect(0.05, 0.5, 0.95, 0.95)},
    ]}, w=500, h=500)
    assert zone_names(m) == {"r1": "BEDROOM 1", "r2": "BEDROOM 2", "r3": "LIVING"}
    items = arrange(m, default_pieces(m, DesignPrefs()), "walls", {})
    assert sum(1 for i in items if i.category == "bed_frame") == 2  # two distinct rooms keep two beds
