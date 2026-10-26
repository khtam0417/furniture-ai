"""Secondhand supply (diverse sources, bounded second pass) and explicit review of a chosen piece that doesn't fit
(FAKE NETWORK, MOCKED gpt-6-luna search; nothing leaves the machine)."""

import json

from conftest import product
from test_find_furniture import _live
from test_resale_trust import ld_page, prod
from test_shopping_flow import HTML

from furnishai.safe_fetch import RawResponse

AD, CH, EB = "https://www.aptdeco.com/product/", "https://www.chairish.com/product/", "https://www.ebay.com/itm/"


def listing(name, url, price, w, d):
    return RawResponse(200, HTML, ld_page([prod(name, url=url, price=str(price), cond="UsedCondition", width=w, depth=d,
                                                avail="InStock")]))


NS_AD, NS_CH = AD + "walnut-nightstand-2", CH + "901/vintage-nightstand"
NS_EB = [EB + "4001", EB + "4002", EB + "4003"]
DR_AD, DR_CH, DR_EB = AD + "six-drawer-dresser", CH + "902/teak-dresser", EB + "4004"
CT_EB, CT_AD = EB + "4005", AD + "round-oak-coffee-table"


def leads_for(body):
    q = body["input"]
    if "Affordable used coffee table" in q:
        return [CT_AD]
    if "Used coffee table" in q:
        return [CT_EB]
    if "Used nightstand" in q:
        return [NS_EB[0], NS_EB[1], NS_CH, NS_EB[2], NS_AD]
    if "Used dresser" in q:
        return [DR_EB, DR_CH, DR_AD]
    return []


def pages():
    return {NS_AD: listing("Walnut nightstand", NS_AD, 60, 18, 15), NS_CH: listing("Vintage nightstand", NS_CH, 900, 18, 15),
            DR_AD: listing("Six drawer dresser", DR_AD, 180, 40, 18), DR_CH: listing("Teak dresser", DR_CH, 1500, 40, 18),
            CT_AD: listing("Round oak coffee table", CT_AD, 90, 36, 20),
            **{u: RawResponse(403, HTML, b"denied") for u in NS_EB + [DR_EB, CT_EB]}}  # eBay refuses automated reading


def test_checks_spread_across_marketplaces_refusing_sites_go_last_and_a_bounded_second_pass_helps(tmp_path):
    net_pages = pages()
    c, app, net, sent, aid, s = _live(tmp_path, leads_for, net_pages,
                                      {"condition": "secondhand", "budget_cents": 300000, "styles": ["modern"]})
    # The marketplaces' order in the search result was eBay, eBay, Chairish, eBay, AptDeco: checks go round-robin.
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|"}).json()
    used = r["branches"]["used"]
    assert [u for u in net.requested if "4001" in u or "901" in u or "walnut-nightstand" in u][:3] == [NS_EB[0], NS_CH, NS_AD]
    assert used["target_cents"] and "under $" in sent[-1]["input"] and f"under ${used['target_cents'] // 100}" in sent[-1]["input"]
    assert r["options_used"] == 2 and used["good"] == 1  # the $900 Chairish piece is verified but over this piece's target
    # The first batch's eBay page refused automated reading: the rest of eBay's pages in this round are skipped (never
    # bypassed), while the other marketplaces' pages are still checked.
    assert used["checked"] == 3 and NS_EB[1] not in net.requested and NS_EB[2] not in net.requested
    assert used["skipped_refusing"] == 2 and used["unavailable_sites"] == ["eBay"] and "Further checks skipped for eBay" in used["source_note"]
    assert "other marketplaces" not in used["source_note"]  # no claim about other sites without evidence
    # For the next piece type the search itself asks only for the marketplaces that are still eligible.
    n = len(sent)
    rd = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "dresser|"}).json()
    q = sent[n]["input"]
    assert len(sent) == n + 1 and "eBay" not in q and "Chairish" in q and "AptDeco" in q
    dr = [u for u in net.requested if u in (DR_EB, DR_CH, DR_AD)]
    assert dr == [DR_CH, DR_AD] and rd["branches"]["used"]["skipped_refusing"] == 1  # returned anyway: counted, unchecked
    # A piece whose first pass found nothing usable is flagged; the second pass runs ONE alternate search.
    first = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "coffee_table|"}).json()
    assert first["needs_refine"] is True and first["options_used"] == 0
    n = len(sent)
    again = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "coffee_table|", "refine": True}).json()
    assert len(sent) == n + 1 and "Affordable used coffee table listings" in sent[-1]["input"]
    assert "several different designs" in sent[-1]["input"] and "Apt 7C" not in sent[-1]["input"]
    assert again["options_used"] == 1 and again["branches"]["used"]["refined"] is True
    assert again["needs_refine"] is False
    # Nothing new is ever substituted under secondhand-only, and nothing was chosen by searching.
    assert all(i["product_id"] is None for i in c.get(f"/api/apartments/{aid}/design").json()["design"]["data"]["items"])


def test_when_every_selected_marketplace_refuses_nothing_is_searched_or_checked(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, leads_for, pages(), {"condition": "secondhand", "resale_sites": ["ebay"]})
    c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "coffee_table|"})  # eBay refuses its listing page
    n_sent, n_req = len(sent), len(net.requested)
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|"}).json()
    used = r["branches"]["used"]
    assert len(sent) == n_sent and len(net.requested) == n_req  # no AI search, no page check
    assert used["status"] == "unavailable" and used["searched"] is False and used["unavailable_sites"] == ["eBay"]
    assert "Shopping preferences" in used["message"] and "minutes" not in used["message"]
    assert r["needs_refine"] is False and r["options"] == 0  # no "Search more" into a refused-only pool
    # Search more never retries it either, and the per-piece search says why instead of searching.
    again = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|", "refine": True}).json()
    assert len(sent) == n_sent and again["branches"]["used"]["status"] == "unavailable"
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    one = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-secondhand", json={"expected_version": s["design"]["version"]})
    assert one.status_code == 409 and "eBay" in one.json()["detail"] and len(sent) == n_sent
    # Never silently broadened: no other marketplace and no new item was searched in its place.
    assert all("Chairish" not in b["input"] and "Specific new" not in b["input"] for b in sent)


def test_expired_sold_and_wrong_pages_never_mark_a_marketplace_as_refusing(tmp_path):
    gone, sold = CH + "903/oak-dresser", CH + "904/pine-dresser"
    pg = {sold: RawResponse(200, HTML, ld_page([prod("Pine dresser", url=sold, price="150", cond="UsedCondition",
                                                     width=40, depth=18, avail="SoldOut")]))}  # `gone` -> HTTP 404

    def leads(body):
        return [gone, sold] if "Used dresser" in body["input"] else []
    c, app, net, sent, aid, s = _live(tmp_path, leads, pg, {"condition": "secondhand", "resale_sites": ["chairish"]})
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "dresser|"}).json()
    assert gone in net.requested and sold in net.requested and r["branches"]["used"]["refusing"] == []
    n = len(sent)
    r2 = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|"}).json()
    assert len(sent) == n + 1 and "Chairish" in sent[-1]["input"] and r2["branches"]["used"]["status"] == "ok"


def test_used_searches_stay_inside_the_selected_marketplaces(tmp_path):
    def leads(body):  # the search may still return an unselected marketplace's listing: never checked
        return [NS_EB[0], NS_AD] if "Used nightstand" in body["input"] else []
    c, app, net, sent, aid, s = _live(tmp_path, leads, pages(), {"condition": "secondhand", "resale_sites": ["aptdeco", "chairish"]})
    c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|"})
    q = sent[-1]["input"]
    assert "AptDeco" in q and "Chairish" in q and "eBay" not in q and "Craigslist" not in q
    assert NS_EB[0] not in net.requested and NS_AD in net.requested


def test_a_mattress_search_asks_for_the_mattress_only(tmp_path):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "either"})
    key = next(g["key"] for g in c.get(f"/api/apartments/{aid}/design/find-plan").json()["groups"] if g["category"] == "mattress")
    c.post(f"/api/apartments/{aid}/design/find-group", json={"key": key})
    qs = [b["input"] for b in sent]
    assert qs and all("the mattress only: not bed frames, bases" in q and " size mattress" in q for q in qs)
    size = key.split("|")[1]
    assert any(f"Used {size} size mattress listings" in q for q in qs)  # used mattresses still searched when allowed


def _with_bed(tmp_path, w, d, price=50000):
    c, app, net, sent, aid, s = _live(tmp_path, lambda b: [], {}, {"condition": "secondhand", "budget_cents": None})
    anchor = c.get(f"/api/apartments/{aid}/design").json()["anchor_project_id"]
    snap = {**product("bigbed", "bed_frame", price, w=w, d=d, condition="secondhand", nominal_size="queen"),
            "origin": "used_listing_check", "url": CH + "77/oak-queen-bed", "condition_verified": True, "retailer": "Chairish"}
    app.state.db.upsert_snapshot(snap, snap["id"], anchor, None)
    bed = next(i for i in s["design"]["data"]["items"] if i["category"] == "bed_frame")
    return c, app, aid, s, bed


def test_robot_checks_and_expired_listings_are_reported_honestly_never_read_past():
    from furnishai.sources import import_used_listing
    from test_shopping_flow import Net
    shell = b"<html><body><div id='challenge-container'></div><noscript>we need to verify that you're not a robot</noscript></body></html>"
    gone = "https://newhaven.craigslist.org/fuo/d/milford-dresser/7892491233.html"
    net = Net({DR_AD: RawResponse(202, HTML, shell)})
    snap, res, out = import_used_listing(net.fetcher(), DR_AD, "dresser")
    assert snap is None and "robot check" in out and "couldn’t be read" in out  # not "condition not shown"
    snap, res, out = import_used_listing(net.fetcher(), gone, "dresser")
    assert snap is None and out.startswith("no longer online")


def test_a_chosen_bed_that_doesnt_fit_is_flagged_searched_and_replaced_only_on_request(tmp_path):
    c, app, aid, s, bed = _with_bed(tmp_path, 110, 110)
    r = c.post(f"/api/apartments/{aid}/design/items/{bed['id']}/product",
               json={"expected_version": s["design"]["version"], "product_id": "bigbed"}).json()
    assert any("doesn’t fit where it can go" in ch for ch in r["changes"])  # a manual pick is allowed, but said plainly
    review = r["evaluation"]["review"]
    assert bed["id"] in review and review[bed["id"]]["can_move"] is False and review[bed["id"]]["problems"]
    keys = [g["key"] for g in c.get(f"/api/apartments/{aid}/design/find-plan").json()["groups"]]
    assert "bed_frame|queen" in keys  # it still gets searched for alternatives
    v = r["design"]["version"]
    # Marked as bought: "replace" keeps it.
    c.post(f"/api/apartments/{aid}/design/checklist/mark", json={"expected_version": v, "instance_id": bed["id"],
                                                                "product_id": "bigbed", "purchased": True})
    kept = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": v, "replace_ids": [bed["id"]]}).json()
    assert next(i for i in kept["design"]["data"]["items"] if i["id"] == bed["id"])["product_id"] == "bigbed"
    assert any("marked as bought" in ch for ch in kept["changes"])
    v = kept["design"]["version"]
    c.post(f"/api/apartments/{aid}/design/checklist/mark", json={"expected_version": v, "instance_id": bed["id"],
                                                                "product_id": "bigbed", "purchased": False})
    out = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": v, "replace_ids": [bed["id"]]}).json()
    after = next(i for i in out["design"]["data"]["items"] if i["id"] == bed["id"])
    assert after["product_id"] is None and (after["x"], after["y"]) == (bed["x"], bed["y"])  # piece and spot stay
    assert len(out["design"]["data"]["items"]) == len(s["design"]["data"]["items"])  # nothing deleted
    assert c.post(f"/api/apartments/{aid}/design/auto-products",
                  json={"expected_version": out["design"]["version"], "replace_ids": ["pc_nope"]}).status_code == 404


def test_move_it_inside_the_room_keeps_its_real_size(tmp_path):
    c, app, aid, s, bed = _with_bed(tmp_path, 60, 80)
    v = s["design"]["version"]
    s = c.post(f"/api/apartments/{aid}/design/items/{bed['id']}/product", json={"expected_version": v, "product_id": "bigbed"}).json()
    moved = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [
        {"op": "move", "id": bed["id"], "x": 0.13, "y": 0.62}]}).json()  # pushed against the bedroom wall: half outside
    review = moved["evaluation"]["review"]
    assert bed["id"] in review, review  # a drag never auto-repairs: the conflict is shown for an explicit choice
    assert review[bed["id"]]["can_move"] is True
    f = c.post(f"/api/apartments/{aid}/design/items/{bed['id']}/fit", json={"expected_version": moved["design"]["version"]}).json()
    assert bed["id"] not in f["evaluation"]["review"]
    it = next(i for i in f["design"]["data"]["items"] if i["id"] == bed["id"])
    assert it["product_id"] == "bigbed" and it["zone_id"] == bed["zone_id"]
    mat = next(i for i in f["design"]["data"]["items"] if i.get("on_item") == bed["id"])
    assert (mat["x"], mat["y"]) == (it["x"], it["y"])  # the mattress follows its bed
    assert json.loads(app.state.db.one("SELECT data FROM design_versions WHERE apartment_id=? ORDER BY version DESC LIMIT 1",
                                       (aid,))["data"])["items"]
