"""Secondhand trust boundary, primary-item evidence binding, check cache, and TV-on-stand rules.

DETERMINISTIC / FAKE NETWORK: every page and search response is a hand-written fixture.
"""

import json

import httpx2
from fastapi.testclient import TestClient

from furnishai.resale import resale_site
from furnishai.safe_fetch import RawResponse
from furnishai.sources import import_used_listing

from test_design_refine import ONE_BED, _search_body, client, setup
from test_shopping_flow import HTML, Net, used_page

APT = "https://www.aptdeco.com/products/"


def ld_page(products, body="", title="Listing"):
    lds = "".join(f'<script type="application/ld+json">{json.dumps(p)}</script>' for p in products)
    return f"<html><head><title>{title}</title>{lds}</head><body>{body}</body></html>".encode()


def prod(name, url=None, price=None, cond=None, avail=None, width=None, depth=None):
    p = {"@context": "https://schema.org", "@type": "Product", "name": name}
    if url:
        p["url"] = url
    offer = {"@type": "Offer", "priceCurrency": "USD"}
    if price:
        offer["price"] = price
    if cond:
        offer["itemCondition"] = f"https://schema.org/{cond}"
    if avail:
        offer["availability"] = f"https://schema.org/{avail}"
    p["offers"] = offer
    if width:
        p["width"] = {"@type": "QuantitativeValue", "value": width, "unitCode": "INH"}
    if depth:
        p["depth"] = {"@type": "QuantitativeValue", "value": depth, "unitCode": "INH"}
    return p


# ------------------------------------------------------------------ the approved-marketplace boundary
def test_only_individual_listings_on_approved_marketplaces_pass():
    good = {APT + "walnut-nightstand": "aptdeco", "https://www.chairish.com/product/123/walnut-nightstand": "chairish",
            "https://www.ebay.com/itm/1234567890": "ebay", "https://www.facebook.com/marketplace/item/987654321/": "facebook",
            "https://newhaven.craigslist.org/fuo/d/new-haven-walnut-nightstand/7712345678.html": "craigslist"}
    assert {u: resale_site(u) for u in good} == good
    bad = ["https://www.ebay.com.evil.example/itm/1", "https://evilebay.com/itm/1", "https://www.ebay.com@evil.example/itm/1",
           "https://user:pw@www.ebay.com/itm/1", "http://www.ebay.com/itm/1", "https://www.ebay.com:8443/itm/1",
           "https://www.еbay.com/itm/1",  # Cyrillic "е"
           "https://www.xn--bay-qdd.com/itm/1", "https://www.ebay.com/sch/i.html?_nkw=x",
           "https://www.facebook.com/groups/123", "https://www.facebook.com/marketplace/newhaven/furniture",
           "https://craigslist.org/search/fua", "https://evil.craigslist.org.example/fuo/d/x/1.html",
           "https://www.kaiyo.com/products/x-1", "https://www.ebay.co.uk/itm/1"]
    assert [u for u in bad if resale_site(u)] == []
    assert resale_site(APT + "walnut-nightstand", ["ebay"]) is None  # the user's narrower choice is enforced


def test_a_redirect_to_an_unapproved_site_is_refused_before_connecting():
    start = APT + "walnut-nightstand"
    net = Net({start: RawResponse(302, {"location": "https://evil.example/products/walnut-nightstand"}, b""),
               "https://evil.example/products/walnut-nightstand": RawResponse(200, HTML, used_page())})
    snap, _, out = import_used_listing(net.fetcher(), start, "nightstand")
    assert snap is None and "refused" in out
    assert net.requested == [start]  # the unapproved hop was never contacted
    # Private addresses stay blocked even on an approved host.
    net2 = Net({start: RawResponse(200, HTML, used_page())}, private={"www.aptdeco.com"})
    snap, _, out = import_used_listing(net2.fetcher(), start, "nightstand")
    assert snap is None and net2.requested == []


# ------------------------------------------------------------------ evidence bound to the listing's own item
def check(page, slug="new-nightstand", category="nightstand"):
    url = APT + slug
    return import_used_listing(Net({url: RawResponse(200, HTML, page)}).fetcher(), url, category)


def test_related_products_never_supply_condition_price_size_or_sold():
    # Root's case A: a USED related chair first, then this page's own NEW nightstand.
    page = ld_page([prod("Used chair", url=APT + "used-chair", price="20", cond="UsedCondition", width=20, depth=20),
                    prod("New nightstand", url=APT + "new-nightstand", price="90", cond="NewCondition")])
    snap, _, out = check(page)
    assert snap is None and "new condition" in out
    # This listing is used but states no price/size; a related item's price and size are never borrowed.
    page = ld_page([prod("Walnut nightstand", url=APT + "walnut-nightstand", cond="UsedCondition", avail="InStock"),
                    prod("Oak dresser", url=APT + "oak-dresser", price="150", cond="UsedCondition", width=48, depth=18,
                         avail="SoldOut")],
                   body="<p>Related: Oak dresser 48 in W x 18 in D</p>")
    snap, _, out = check(page, "walnut-nightstand")
    assert snap is not None and snap["price_cents"] is None and snap["width_in"] is None and out == "incomplete"
    assert snap.get("availability") != "SoldOut"  # the related card's SoldOut isn't this listing's
    # Several products and none is this page: abstain.
    page = ld_page([prod("Used chair", url=APT + "a", cond="UsedCondition"), prod("Used lamp", url=APT + "b", cond="UsedCondition")])
    assert check(page, "walnut-nightstand")[0] is None


def test_a_new_item_with_a_preowned_footer_is_not_used_and_vague_condition_is_not_enough():
    snap, _, out = check(b"<html><body><h1>New nightstand</h1><p>Condition: New</p><footer>Shop pre-owned items too</footer></body></html>")
    assert snap is None and "new condition" in out  # root's case B
    snap, _, out = check(b"<html><body><h1>Walnut nightstand</h1><p>Condition: Excellent</p></body></html>", "walnut-nightstand")
    assert snap is None and "used or pre-owned" in out
    snap, _, out = check(b"<html><head><title>Walnut nightstand</title></head><body><h1>Walnut nightstand</h1>"
                         b"<p>Condition: Pre-owned, light wear</p><p>Price: see listing</p></body></html>", "walnut-nightstand")
    assert snap is not None and snap["condition"] == "secondhand" and "Pre-owned" in snap["condition_evidence"]


def test_wrong_type_and_sets_are_not_verified_as_one_piece():
    page = ld_page([prod("Used dining table", url=APT + "dining-table", price="120", cond="UsedCondition", width=60, depth=36)])
    snap, _, out = check(page, "dining-table")
    assert snap is None and "nightstand" in out
    page = ld_page([prod("Pair of walnut nightstands", url=APT + "pair", price="120", cond="UsedCondition", width=20, depth=16)])
    snap, _, out = check(page, "pair")
    assert snap is None and "set, pair or bundle" in out


def test_sold_comes_from_the_listing_itself():
    ok = ld_page([prod("Walnut nightstand", url=APT + "walnut-nightstand", price="60", cond="UsedCondition", width=20, depth=16, avail="InStock")],
                 body="<h1>Walnut nightstand</h1><h2>You may also like</h2><p>Sold</p>")
    snap, _, out = check(ok, "walnut-nightstand")
    assert out == "verified" and snap["availability"] != "SoldOut"
    sold = ld_page([prod("Walnut nightstand", url=APT + "walnut-nightstand", price="60", cond="UsedCondition", width=20, depth=16)],
                   body="<h1>Walnut nightstand</h1><p>This item has been sold</p>")
    snap, _, out = check(sold, "walnut-nightstand")
    assert out.startswith("sold") and snap["availability"] == "SoldOut"


# ------------------------------------------------------------------ cache, manual check gate (API)
GOOD = APT + "walnut-nightstand"
UNKNOWN = "https://www.unknown-resale.example/products/walnut-nightstand-2"


def _api(tmp_path, pages, urls):
    sent = []

    def gateway(request):
        sent.append(json.loads(request.content or b"{}"))
        return httpx2.Response(200, json=_search_body(urls))
    net = Net(pages)
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway, net=net.fetcher())
    aid, anchor, s = setup(c)
    prefs = {**s["design"]["data"]["prefs"], "condition": "secondhand"}
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs}).json()
    return c, app, net, sent, aid, s


def test_check_cache_is_short_lived_per_type_and_rechecks_on_request(tmp_path):
    page = ld_page([prod("Walnut nightstand", url=GOOD, price="60", cond="UsedCondition", width=20, depth=16, avail="InStock")])
    c, app, net, sent, aid, s = _api(tmp_path, {GOOD: RawResponse(200, HTML, page)}, [GOOD])
    v = s["design"]["version"]
    items = s["design"]["data"]["items"]
    ns = next(i for i in items if i["category"] == "nightstand")
    dr = next(i for i in items if i["category"] == "dresser")
    url = f"/api/apartments/{aid}/design/items/{ns['id']}/find-secondhand"
    c.post(url, json={"expected_version": v})
    assert net.requested.count(GOOD) == 1
    c.post(url, json={"expected_version": v})
    assert net.requested.count(GOOD) == 1  # reused within 10 minutes
    c.post(url, json={"expected_version": v, "recheck": True})
    assert net.requested.count(GOOD) == 2  # an explicit "check again" re-reads (still capped)
    # The same page checked for a DIFFERENT type is its own check (never reused across types).
    r = c.post(f"/api/apartments/{aid}/design/items/{dr['id']}/check-lead", json={"expected_version": v, "url": GOOD, "condition": "secondhand"}).json()
    assert net.requested.count(GOOD) == 3 and not r["matches"] and "dresser" in r["message"]
    # Expired entries are not reused.
    app.state.db.exec("UPDATE research_results SET created_at='2000-01-01T00:00:00+00:00' WHERE kind='used_check'")
    c.post(url, json={"expected_version": v})
    assert net.requested.count(GOOD) == 4


def test_manual_secondhand_check_uses_the_same_gate(tmp_path):
    page = used_page(name="Walnut nightstand")
    c, app, net, sent, aid, s = _api(tmp_path, {UNKNOWN: RawResponse(200, HTML, page), GOOD: RawResponse(200, HTML, page)},
                                     [UNKNOWN, GOOD])
    v = s["design"]["version"]
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-online", json={"expected_version": v})
    r = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v, "url": UNKNOWN, "condition": "secondhand"})
    assert r.status_code == 422 and "approved resale" in r.json()["detail"] and UNKNOWN not in net.requested
    view = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()
    assert UNKNOWN not in {l["url"] for l in view["online"]["leads"]}  # unknown websites are never listed
    ok = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v, "url": GOOD, "condition": "secondhand"}).json()
    assert ok["matches"] and ok["status"] == "verified"
    opt = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()["candidates"][0]
    assert opt["condition_verified"] is True and opt["image"] is None  # no remote listing image is auto-loaded


# ------------------------------------------------------------------ TV and its stand
def test_tv_never_floats_without_a_stand(tmp_path):
    c, app, net, sent, aid, s = _api(tmp_path, {}, [])
    def ops(s, *o):
        r = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": list(o)})
        return r
    s = ops(s, {"op": "add", "category": "tv_stand", "zone_id": "r2"}, {"op": "add", "category": "tv_stand", "zone_id": "r2"}).json()
    stands = [i for i in s["design"]["data"]["items"] if i["category"] == "tv_stand"]
    s = ops(s, {"op": "add", "category": "tv"}).json()
    tv = next(i for i in s["design"]["data"]["items"] if i["category"] == "tv")
    assert tv["on_item"] is None and not tv["placed"] and "choose which" in tv["unplaced_reason"]  # no silent pick
    assert ops(s, {"op": "move", "id": tv["id"], "x": 0.5, "y": 0.5}).status_code == 422  # an orphan TV can't be dropped on the floor
    s = ops(s, {"op": "attach", "id": tv["id"], "host_id": stands[1]["id"]}).json()
    s = ops(s, {"op": "rotate", "id": stands[1]["id"], "rotation": 90}, {"op": "owned", "id": tv["id"], "owned": True}).json()
    tv = next(i for i in s["design"]["data"]["items"] if i["id"] == tv["id"])
    assert tv["on_item"] == stands[1]["id"] and tv["placed"] and tv["owned"]
    s = ops(s, {"op": "remove", "id": stands[1]["id"]}).json()
    tv = next(i for i in s["design"]["data"]["items"] if i["id"] == tv["id"])
    assert tv["on_item"] is None and not tv["placed"] and "TV stand" in tv["unplaced_reason"] and tv["owned"]
    assert any(i["id"] == stands[0]["id"] for i in s["design"]["data"]["items"])
    s = ops(s, {"op": "attach", "id": tv["id"], "host_id": stands[0]["id"]}).json()
    assert next(i for i in s["design"]["data"]["items"] if i["id"] == tv["id"])["placed"]
