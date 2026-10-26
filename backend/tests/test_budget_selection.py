"""Budget-first selection (pass 64): price feasibility outranks style, over-budget products are never offered or
accepted, earlier over-budget choices are kept but flagged for review and can be repaired one at a time, and the
"Find furniture" rounds are bounded (up to 12 pages, two at a time, stop at 3 distinct ready options).

MOCKED AI / FAKE NETWORK: search responses, listings and prices are hand-written fixtures, not live results.
"""

import json

import httpx2

from furnishai.safe_fetch import RawResponse

from conftest import product
from test_design_refine import ONE_BED, client, setup
from test_resale_trust import ld_page, prod
from test_shopping_flow import HTML, Net

CH = "https://www.chairish.com/product/"
SECONDHAND = {"condition": "secondhand", "budget_cents": 300000, "reserve_pct": 10}


def _body(results):
    """A mocked web-search response; `results` = [(url, title)]."""
    return {"id": "resp_x", "object": "response", "created_at": 1761400000, "status": "completed", "model": "gpt-6-luna",
            "output": [{"type": "web_search_call", "id": "ws", "status": "completed",
                        "action": {"type": "search", "query": "q", "sources": [{"type": "url", "url": u} for u, _ in results]}},
                       {"type": "message", "id": "m", "role": "assistant", "status": "completed", "content": [{
                           "type": "output_text", "text": "x" * 60,
                           "annotations": [{"type": "url_citation", "start_index": 0, "end_index": 5, "url": u, "title": t}
                                           for u, t in results]}]}],
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 10}}


def _two_pieces(tmp_path, results=lambda body: [], pages=None, prefs=SECONDHAND):
    """A design with exactly two pieces, a sofa and a coffee table (like the production design that started with
    only those two), and the given shopping preferences."""
    sent = []

    def gateway(request):
        body = json.loads(request.content or b"{}")
        sent.append(body)
        return httpx2.Response(200, json=_body(results(body)))
    net = Net(pages or {})
    c, app, _ = client(tmp_path, [ONE_BED], live=True, gateway=gateway, net=net.fetcher())
    aid, anchor, s = setup(c)
    v = s["design"]["version"]
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": v, "prefs": {**s["design"]["data"]["prefs"], **prefs}}).json()
    have = {i["category"] for i in s["design"]["data"]["items"]}
    add = [{"op": "add", "category": k, "zone_id": "r2"} for k in ("sofa", "coffee_table") if k not in have]
    if add:
        s = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": add}).json()
    keep = {}
    for i in s["design"]["data"]["items"]:
        if i["category"] in ("sofa", "coffee_table") and i["category"] not in keep:
            keep[i["category"]] = i["id"]
    drop = [{"op": "remove", "id": i["id"]} for i in s["design"]["data"]["items"] if i["id"] not in keep.values()]
    s = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": drop}).json()
    assert sorted(i["category"] for i in s["design"]["data"]["items"]) == ["coffee_table", "sofa"]
    return c, app, net, sent, aid, anchor, s, keep["sofa"], keep["coffee_table"]


def _used(pid, category, price, n, w, d, tags=()):
    return {**product(pid, category, price, w=w, d=d, tags=tags, condition="secondhand"), "origin": "used_listing_check",
            "url": CH + f"{n}/{category.replace('_', '-')}-{pid}", "condition_verified": True, "retailer": "Chairish",
            "condition_evidence": "test fixture"}


def _seed(app, anchor, *snaps):
    for p in snaps:
        app.state.db.upsert_snapshot(p, p["id"], anchor, None)


LUX_SOFA = ("imp-fb-sofa", "sofa", 1450000, 1, 72, 32)
OK_SOFA = ("imp-ok-sofa", "sofa", 150000, 2, 72, 32)
LUX_CT = ("imp-lux-ct", "coffee_table", 225000, 3, 36, 18)
OK_CT = ("imp-ok-ct", "coffee_table", 40000, 4, 36, 18)


def _ids(opts):
    return [o["product_id"] for o in opts]


def test_a_14500_sofa_on_a_3000_budget_is_never_recommended_selectable_or_accepted(tmp_path):
    c, app, net, sent, aid, anchor, s, sofa, ct = _two_pieces(tmp_path)
    _seed(app, anchor, _used(*LUX_SOFA), _used(*OK_SOFA), _used(*LUX_CT), _used(*OK_CT))
    t = c.get(f"/api/apartments/{aid}/design").json()["evaluation"]["targets"]
    # $3,000 minus 10% = $2,700 for items, split sofa 26 : coffee table 6.
    assert t[sofa]["target_cents"] == 270000 * 26 // 32 and t[ct]["target_cents"] == 270000 * 6 // 32 == 50625
    pv = c.get(f"/api/apartments/{aid}/design/previews").json()["items"]
    assert "imp-fb-sofa" not in _ids(pv[sofa]["candidates"]) and pv[sofa]["held_back"].get("over_budget") == 1
    assert "above the item budget left" in pv[sofa]["held_text"]
    assert pv[sofa]["total"] == len([x for x in pv[sofa]["candidates"]])  # "N options ready" counts only these
    for scope in ("recommended", "within_budget"):  # never offered, not even when browsing more broadly
        full = c.get(f"/api/apartments/{aid}/design/items/{sofa}/products?scope={scope}&limit=48").json()
        assert "imp-fb-sofa" not in _ids(full["candidates"])
    v = s["design"]["version"]
    r = c.post(f"/api/apartments/{aid}/design/items/{sofa}/product", json={"expected_version": v, "product_id": "imp-fb-sofa"})
    assert r.status_code == 422 and "$14,500.00" in r.json()["detail"] and "$2,700.00" in r.json()["detail"]
    assert "unchanged" in r.json()["detail"]
    assert c.get(f"/api/apartments/{aid}/design").json()["design"]["version"] == v  # nothing saved
    # The $2,250 coffee table fits the WHOLE budget but not its ~$506 share: not a default recommendation, the
    # $400 one is; broader browsing shows it flagged (choosable on purpose, with the share warning).
    assert "imp-lux-ct" not in _ids(pv[ct]["candidates"]) and _ids(pv[ct]["candidates"])[0] == "imp-ok-ct"
    assert pv[ct]["held_back"].get("over_share") == 1
    broad = c.get(f"/api/apartments/{aid}/design/items/{ct}/products?scope=within_budget&limit=48").json()["candidates"]
    lux = next(o for o in broad if o["product_id"] == "imp-lux-ct")
    assert lux["affordable"] is False and lux["within_budget"] is True and lux["blocked"] is None
    assert _ids(broad).index("imp-ok-ct") < _ids(broad).index("imp-lux-ct")


def test_a_cheaper_close_style_ranks_before_an_expensive_exact_match(tmp_path):
    c, app, net, sent, aid, anchor, s, sofa, ct = _two_pieces(tmp_path, prefs={**SECONDHAND, "styles": ["minimal"]})
    _seed(app, anchor, _used("imp-exact", "coffee_table", 225000, 5, 36, 18, tags=["minimal"]),
          _used("imp-near", "coffee_table", 40000, 6, 36, 18, tags=["scandinavian"]))
    pv = c.get(f"/api/apartments/{aid}/design/previews").json()["items"][ct]
    assert _ids(pv["candidates"])[:1] == ["imp-near"] and "imp-exact" not in _ids(pv["candidates"])
    broad = c.get(f"/api/apartments/{aid}/design/items/{ct}/products?scope=within_budget&limit=48").json()["candidates"]
    assert _ids(broad).index("imp-near") < _ids(broad).index("imp-exact")


def _force_choices(app, aid, choices):
    """Simulate choices saved BEFORE the budget guard existed (as in production): a new design version written
    directly, the way an older build saved it."""
    db = app.state.db
    head = db.design_head(aid)
    data = json.loads(json.dumps(head["data"]))
    for it in data["items"]:
        if it["id"] in choices:
            it["product_id"] = choices[it["id"]]
    assert db.add_design_version(aid, data, head["plan_map_id"], "Older choices", head["version"]) is not None


def test_earlier_over_budget_choices_are_kept_flagged_searchable_and_repairable_one_at_a_time(tmp_path):
    c, app, net, sent, aid, anchor, s, sofa, ct = _two_pieces(tmp_path)
    _seed(app, anchor, _used(*LUX_SOFA), _used(*OK_SOFA), _used(*LUX_CT), _used(*OK_CT))
    _force_choices(app, aid, {sofa: "imp-fb-sofa", ct: "imp-lux-ct"})
    st = c.get(f"/api/apartments/{aid}/design").json()
    b = st["evaluation"]["budget"]
    assert {x["id"] for x in b["budget_review"]} == {sofa, ct} and b["status"] == "incomplete" and b["over_allowance"]
    sofa_review = next(x for x in b["budget_review"] if x["id"] == sofa)
    assert sofa_review["over_whole_budget"] is True and "more than your whole $2,700.00 item budget" in sofa_review["message"]
    assert {i["id"]: i["product_id"] for i in st["design"]["data"]["items"]} == {sofa: "imp-fb-sofa", ct: "imp-lux-ct"}  # kept
    assert len(st["design"]["data"]["items"]) == 2  # both requested pieces stay; nothing is seeded
    # Replacement planning ignores the flagged choices, so each piece gets its plain share back.
    assert st["evaluation"]["targets"][sofa]["target_cents"] == 219375 and st["evaluation"]["targets"][ct]["target_cents"] == 50625
    keys = {g["key"] for g in c.get(f"/api/apartments/{aid}/design/find-plan").json()["groups"]}
    assert keys == {"sofa|", "coffee_table|"}  # both can be searched again
    cl = c.get(f"/api/apartments/{aid}/design/checklist").json()["checklist"]
    assert cl["status"] == "incomplete" and cl["budget_review"] == 2
    pv = c.get(f"/api/apartments/{aid}/design/previews").json()["items"]
    assert "imp-ok-sofa" in _ids(pv[sofa]["candidates"])
    # Repair one at a time: the flagged coffee table doesn't block a cheaper sofa.
    v = st["design"]["version"]
    r = c.post(f"/api/apartments/{aid}/design/items/{sofa}/product", json={"expected_version": v, "product_id": "imp-ok-sofa"})
    assert r.status_code == 200, r.text
    b = r.json()["evaluation"]["budget"]
    assert {x["id"] for x in b["budget_review"]} == {ct}  # $1,500 + $2,250 is still over: the coffee table is flagged
    v = r.json()["design"]["version"]
    # $2,700 - $1,500 = $1,200 left for the coffee table: the $2,250 one is refused, the $400 one is accepted.
    bad = c.post(f"/api/apartments/{aid}/design/items/{ct}/product", json={"expected_version": v, "product_id": "imp-lux-ct"})
    assert bad.status_code == 422 and "$1,200.00" in bad.json()["detail"]
    ok = c.post(f"/api/apartments/{aid}/design/items/{ct}/product", json={"expected_version": v, "product_id": "imp-ok-ct"}).json()
    assert ok["evaluation"]["budget"]["budget_review"] == [] and ok["evaluation"]["budget"]["status"] == "complete"
    # Clearing stays possible at any time.
    _force_choices(app, aid, {sofa: "imp-fb-sofa"})
    v = c.get(f"/api/apartments/{aid}/design").json()["design"]["version"]
    clr = c.post(f"/api/apartments/{aid}/design/items/{sofa}/product", json={"expected_version": v, "product_id": None})
    assert clr.status_code == 200 and len(clr.json()["design"]["data"]["items"]) == 2


def test_choose_for_me_never_exceeds_the_item_budget_and_keeps_flagged_choices(tmp_path):
    c, app, net, sent, aid, anchor, s, sofa, ct = _two_pieces(tmp_path)
    _seed(app, anchor, _used(*LUX_SOFA), _used(*OK_SOFA), _used(*LUX_CT), _used(*OK_CT))
    _force_choices(app, aid, {sofa: "imp-fb-sofa"})
    v = c.get(f"/api/apartments/{aid}/design").json()["design"]["version"]
    r = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": v}).json()
    items = {i["id"]: i["product_id"] for i in r["design"]["data"]["items"]}
    assert items[sofa] == "imp-fb-sofa"  # a flagged choice is never changed automatically
    assert items[ct] in (None, "imp-ok-ct")  # and the share kept for the sofa's replacement isn't spent


def _listing(name, url, price, cond="UsedCondition", avail="InStock", w=36, d=18):
    return RawResponse(200, HTML, ld_page([prod(name, url=url, price=str(price), cond=cond, width=w, depth=d, avail=avail)]))


def test_one_search_checks_at_most_12_pages_two_at_a_time_and_stops_at_3_ready_options(tmp_path):
    urls = [CH + f"{100 + n}/oak-coffee-table-{n}" for n in range(14)]
    # Two sold, one stating NEW condition (never counted as used), then affordable used listings.
    pages = {urls[0]: _listing("Oak coffee table", urls[0], 60, avail="SoldOut"),
             urls[1]: _listing("Oak coffee table", urls[1], 60, cond="NewCondition"),
             **{u: _listing(f"Oak coffee table {n}", u, 50 + n) for n, u in enumerate(urls) if n >= 2}}
    c, app, net, sent, aid, anchor, s, sofa, ct = _two_pieces(tmp_path, lambda b: [(u, "Oak coffee table") for u in urls], pages)
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "coffee_table|"}).json()
    used = r["branches"]["used"]
    assert len(sent) == 1  # one web search
    assert used["good"] == 3 and r["options_ready"] == 3 and r["needs_refine"] is False
    assert used["checked"] == 5 and len([u for u in net.requested if u in urls]) == 5  # stopped once 3 were ready
    assert app.state.check_stats["max_running"] <= 2
    # Every page above this piece's share: the bound is 12 pages from the same result, never more.
    c2, app2, net2, sent2, aid2, anchor2, s2, sofa2, ct2 = _two_pieces(
        tmp_path / "b", lambda b: [(u, "Oak coffee table") for u in urls],
        {u: _listing(f"Oak coffee table {n}", u, 900 + n) for n, u in enumerate(urls)})
    r2 = c2.post(f"/api/apartments/{aid2}/design/find-group", json={"key": "coffee_table|"}).json()
    u2 = r2["branches"]["used"]
    assert u2["checked"] == 12 and len([u for u in net2.requested if u in urls]) == 12 and len(sent2) == 1
    assert u2["good"] == 0 and r2["options_ready"] == 0 and u2["reasons"].get("over_budget") == 12
    assert r2["held_back"].get("over_share", 0) >= 12 and "not recommended" in r2["held_text"]
    assert r2["needs_refine"] is True  # an explicit "Search more" is offered; nothing ran by itself
    assert len(sent2) == 1


def test_results_whose_search_text_states_a_price_above_the_target_are_checked_last(tmp_path):
    urls = [CH + f"{200 + n}/coffee-table-{n}" for n in range(4)]
    results = [(urls[0], "Designer marble coffee table $1,800"), (urls[1], "Collectible coffee table $2,400"),
               (urls[2], "Oak coffee table $60"), (urls[3], "Pine coffee table")]
    pages = {u: _listing(f"Coffee table {n}", u, 40 + n) for n, u in enumerate(urls)}
    c, app, net, sent, aid, anchor, s, sofa, ct = _two_pieces(tmp_path, lambda b: results, pages)
    c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "coffee_table|"})
    checked = [u for u in net.requested if u in urls]
    assert checked[:2] == [urls[2], urls[3]]  # within-target / unknown first (search text is only a hint)


def test_one_or_two_ready_options_offer_search_more_which_is_explicit(tmp_path):
    urls = [CH + f"{300 + n}/coffee-table-{n}" for n in range(2)]
    pages = {u: _listing(f"Oak coffee table {n}", u, 45 + n) for n, u in enumerate(urls)}
    c, app, net, sent, aid, anchor, s, sofa, ct = _two_pieces(tmp_path, lambda b: [(u, "T") for u in urls], pages)
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "coffee_table|"}).json()
    assert r["options_ready"] == 2 and r["needs_refine"] is True and len(sent) == 1
    n = len(sent)
    again = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "coffee_table|", "refine": True}).json()
    assert len(sent) == n + 1 and again["refine"] is True and again["needs_refine"] is False  # one extra search, once
    assert sorted(i["category"] for i in c.get(f"/api/apartments/{aid}/design").json()["design"]["data"]["items"]) \
        == ["coffee_table", "sofa"]  # searching never adds or removes pieces


def test_the_new_branch_searches_when_saved_options_are_unaffordable(tmp_path):
    c, app, net, sent, aid, anchor, s, sofa, ct = _two_pieces(
        tmp_path, prefs={"condition": "new", "budget_cents": 10000, "reserve_pct": 10})
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "coffee_table|"}).json()
    new = r["branches"]["new"]
    # Saved new coffee tables may exist, but none is within a ~$17 share: the web is searched (not skipped).
    assert new["ready_existing"] == 0 and new["searched"] is True and len(sent) == 1
