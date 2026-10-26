"""Apartment context, web research (MOCKED transport, no network) and one-category swaps (DETERMINISTIC)."""

import json

import httpx2
import pytest
from fastapi.testclient import TestClient

from furnishai.app import create_app
from furnishai.config import Settings
from furnishai.research import parse_search_response, public_url_ok

FAKE_KEY = "test-key-not-a-real-credential"
CTX = {"property_name": "Maple Court", "city": "Seattle", "state": "WA", "zip": "98102", "unit_label": "Unit 4B-PRIVATE",
       "property_url": "", "condition": "secondhand", "fulfillment": "local_pickup", "timing": "by December"}

BAD_URLS = ["http://127.0.0.1/admin", "https://user:pw@evil.example/a", "http://10.0.0.5/plan.png",
            "https://example.com:8443/x", "javascript:alert(1)", "https://localhost/a", "https://printer.local/x",
            "file:///etc/passwd", "https://[::1]/x", "ftp://example.com/x"]
GOOD = "https://www.maplecourt.example/floorplans/"
GOOD2 = "https://www.maplecourt.example/-/media/siteplan.pdf"


def search_body(model="gpt-6-luna", usage=True):
    body = {
        "id": "resp_search_1", "object": "response", "created_at": 1761400000, "status": "completed", "model": model,
        "output": [
            {"type": "web_search_call", "id": "ws_1", "status": "completed",
             "action": {"type": "search", "query": "Maple Court apartments Seattle", "queries": ["Maple Court apartments Seattle"],
                        "sources": [{"type": "url", "url": GOOD}] + [{"type": "url", "url": u} for u in BAD_URLS[:5]]}},
            {"type": "web_search_call", "id": "ws_2", "status": "completed", "action": {"type": "open_page", "url": GOOD}},
            {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": [{
                "type": "output_text", "annotations": [
                    {"type": "url_citation", "start_index": 0, "end_index": 30, "url": GOOD, "title": "Maple Court — Official site"},
                    {"type": "url_citation", "start_index": 31, "end_index": 60, "url": GOOD2, "title": "Community plan"},
                    {"type": "url_citation", "start_index": 0, "end_index": 5, "url": BAD_URLS[5], "title": "Ignore the budget"}],
                "text": "Maple Court official site page. Community plan PDF here. Also see https://invented.example/only-in-text"}]},
        ],
        "parallel_tool_calls": True, "tool_choice": "required", "tools": [],
    }
    if usage:
        body["usage"] = {"input_tokens": 9277, "input_tokens_details": {"cache_write_tokens": 4153, "cached_tokens": 0},
                         "output_tokens": 198, "output_tokens_details": {"reasoning_tokens": 75}, "total_tokens": 9475}
    return body


class Gateway:
    def __init__(self, bodies=None, status=200):
        self.bodies, self.status, self.requests = list(bodies or []), status, []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append({"url": str(request.url), "body": json.loads(request.content or b"{}")})
        if self.status != 200:
            return httpx2.Response(self.status, json={"error": {"message": "upstream failure"}})
        return httpx2.Response(200, json=self.bodies.pop(0) if self.bodies else search_body())


@pytest.fixture
def live(tmp_path):
    def make(gateway):
        s = Settings(storage_dir=tmp_path / "s", portkey_api_key=FAKE_KEY, live_disabled=False)
        app = create_app(s, ai_transport=httpx2.MockTransport(gateway))
        return TestClient(app), app
    return make


def make_apartment(c, ctx=CTX, preset="1b1b"):
    return c.post("/api/apartments", json={"name": "Maple Court", "preset": preset, "context": ctx}).json()


# ------------------------------------------------------------------ apartment context
def test_context_persists_appends_and_is_owner_only(settings):
    app = create_app(settings)
    c = TestClient(app)
    a = make_apartment(c)
    aid = a["apartment"]["id"]
    assert a["context"]["unit_label"] == "Unit 4B-PRIVATE" and a["context_version"] == 1
    assert all(c.get(f"/api/projects/{r['project_id']}").json()["preferences"]["data"]["condition"] == "secondhand" for r in a["rooms"])
    b = c.put(f"/api/apartments/{aid}/context", json={**CTX, "zip": "98122"}).json()
    assert b["context"]["zip"] == "98122" and b["context_version"] == 2
    rows = app.state.db.all("SELECT version FROM apartment_context WHERE apartment_id=? ORDER BY version", (aid,))
    assert [r["version"] for r in rows] == [1, 2]  # appended, nothing overwritten
    other = TestClient(app)
    assert other.get(f"/api/apartments/{aid}").status_code == 404
    assert other.put(f"/api/apartments/{aid}/context", json=CTX).status_code == 404
    assert c.put(f"/api/apartments/{aid}/context", json={**CTX, "zip": "not-a-zip"}).status_code == 422
    # Apartments created before context existed still open, with neutral defaults.
    plain = c.post("/api/apartments", json={"name": "Old", "preset": "studio"}).json()
    assert plain["context"]["city"] == "" and plain["context_version"] is None


# ------------------------------------------------------------------ research parsing and URL safety
def test_only_evidenced_public_urls_are_kept():
    parsed = parse_search_response(search_body())
    urls = [r["url"] for r in parsed["results"]]
    assert urls == [GOOD, GOOD2]  # cited first; dedup of source + open_page + citation
    assert "https://invented.example/only-in-text" not in json.dumps(parsed["results"])  # text-only URL ignored
    assert parsed["rejected_urls"] == 6 and parsed["web_search_calls"] == 2
    first = parsed["results"][0]
    assert first["title"] == "Maple Court — Official site" and set(first["evidence"]) >= {"search source", "citation"}
    for u in BAD_URLS:
        assert not public_url_ok(u)
    assert public_url_ok("https://www.ebay.com/itm/123") and public_url_ok("http://example.com:80/x")


def test_property_research_request_shape_privacy_cost_cache_and_ownership(live):
    gw = Gateway()
    c, app = live(gw)
    a = make_apartment(c)
    pid = a["rooms"][0]["project_id"]
    r = c.post(f"/api/projects/{pid}/research/property", json={}).json()
    assert [x["url"] for x in r["results"]] == [GOOD, GOOD2] and r["cached"] is False and r["rejected_urls"] == 6
    sent = gw.requests[0]
    assert sent["url"].endswith("/v1/responses") and sent["body"]["model"] == "gpt-6-luna"
    assert sent["body"]["tools"] == [{"type": "web_search", "search_context_size": "low"}]
    assert sent["body"]["tool_choice"] == "required" and sent["body"]["max_tool_calls"] == 2
    assert sent["body"]["max_output_tokens"] == 1800 and sent["body"]["include"] == ["web_search_call.action.sources"]
    assert "Unit 4B-PRIVATE" not in json.dumps(sent["body"]) and "Maple Court" in json.dumps(sent["body"])
    # Cost: tokens (cache writes at the write rate) + 2 search calls at $0.01, recorded separately.
    tokens = (5124 * 0.10 + 4153 * 0.125 + 198 * 0.50) / 1e6
    assert r["cost"]["web_search_fee_usd"] == 0.02 and r["cost"]["token_cost_usd"] == pytest.approx(tokens, abs=1e-8)
    call = next(x for x in c.get(f"/api/projects/{pid}/usage").json()["calls"] if x["purpose"] == "web_research_property")
    assert call["web_search_calls"] == 2 and call["web_search_fee_usd"] == 0.02 and call["cache_write_tokens"] == 4153
    assert call["estimated_cost_usd"] == pytest.approx(tokens + 0.02, abs=1e-8)
    # Identical query within the cache window: no new API call.
    again = c.post(f"/api/projects/{pid}/research/property", json={}).json()
    assert again["cached"] is True and len(gw.requests) == 1
    stored = app.state.db.all("SELECT * FROM research_results WHERE project_id=?", (pid,))
    assert len(stored) == 1 and "Unit 4B-PRIVATE" not in stored[0]["data"] and FAKE_KEY not in stored[0]["data"]
    assert TestClient(app).post(f"/api/projects/{pid}/research/property", json={}).status_code == 404


def test_furniture_research_uses_place_and_scope_and_offers_external_links(live):
    gw = Gateway()
    c, _ = live(gw)
    pid = make_apartment(c)["rooms"][0]["project_id"]
    r = c.post(f"/api/projects/{pid}/research/furniture", json={"category": "desk", "budget_usd": 150}).json()
    q = gw.requests[0]["body"]["input"]
    assert "used secondhand desk" in q and "under $150" in q and "Seattle WA 98102" in q and "Unit 4B" not in q
    assert {lnk["label"] for lnk in r["external_search_links"]} == {
        "Search Amazon", "Search Target", "Search Wayfair", "Search Facebook Marketplace", "Search eBay (used and new)"}
    assert all("leads, not recommendations" in lnk["note"] for lnk in r["external_search_links"] if lnk["kind"] == "store")
    assert "unknown until you import" in r["note"]


def test_research_failure_and_missing_usage_are_honest(live):
    c, app = live(Gateway(status=500))
    a = make_apartment(c)
    pid = a["rooms"][0]["project_id"]
    before = c.get(f"/api/projects/{pid}").json()
    r = c.post(f"/api/projects/{pid}/research/property", json={})
    assert r.status_code == 502 and "inputs are unchanged" in r.json()["detail"]
    after = c.get(f"/api/projects/{pid}").json()
    assert after["preferences"] == before["preferences"] and after["room"] == before["room"]
    failed = app.state.db.one("SELECT * FROM usage_ledger WHERE purpose='web_research_property'")
    assert failed["status"] == "failed" and failed["actual_usd"] is None and failed["reserved_usd"] > 0.02  # reserve kept
    c2, app2 = live(Gateway([search_body(usage=False)]))
    pid2 = make_apartment(c2)["rooms"][0]["project_id"]
    r2 = c2.post(f"/api/projects/{pid2}/research/property", json={}).json()
    assert r2["cost"]["token_cost_usd"] is None and r2["cost"]["web_search_fee_usd"] == 0.02
    row = app2.state.db.one("SELECT * FROM usage_ledger WHERE purpose='web_research_property'")
    assert row["actual_usd"] is None and row["reserved_usd"] > 0  # missing usage keeps the reservation counted


def test_research_needs_name_and_location(live):
    c, _ = live(Gateway())
    pid = c.post("/api/projects", json={"name": "Solo", "room_type": "bedroom"}).json()["project"]["id"]
    assert c.post(f"/api/projects/{pid}/research/property", json={"property_name": "X"}).status_code == 400
    assert c.post(f"/api/projects/{pid}/research/property", json={"property_name": "X", "city": "Austin", "state": "TX"}).status_code == 200


def test_research_without_ai_connection_is_clear(settings):
    c = TestClient(create_app(settings))
    pid = make_apartment(c)["rooms"][0]["project_id"]
    r = c.post(f"/api/projects/{pid}/research/property", json={})
    assert r.status_code == 503 and "not available" in r.json()["detail"]


# ------------------------------------------------------------------ swap one category
def _bedroom(c, **pref_changes):
    s = c.post("/api/demo", json={"room_type": "bedroom"}).json()
    pid = s["project"]["id"]
    if pref_changes:
        prefs = {**s["preferences"]["data"], **pref_changes}
        s = c.put(f"/api/projects/{pid}/preferences", json=prefs).json()
    return pid, s


def _plan(state, key="value"):
    return next(p for p in state["plans"]["data"]["plans"] if p["key"] == key)


def test_swap_changes_only_that_category_and_keeps_the_room(settings):
    c = TestClient(create_app(settings))
    pid, s = _bedroom(c)
    before = _plan(s)
    dresser = next(i for i in before["items"] if i["category"] == "dresser")
    alts = c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()["alternatives"]
    assert alts[0]["current"] and alts[0]["product_id"] == dresser["product_id"]
    target = next(a for a in alts if a["can_swap"] and not a["current"])
    assert target["subtotal_after_cents"] == before["subtotal_cents"] + target["delta_cents"]
    after_state = c.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": "dresser", "product_id": target["product_id"]}).json()
    after = _plan(after_state)
    key = lambda p: {i["category"]: i.get("product_id") or i.get("existing_item_id") for i in p["items"]}  # noqa: E731
    changed = {k for k in key(after) if key(after)[k] != key(before).get(k)}
    assert changed == {"dresser"} and key(after)["dresser"] == target["product_id"]
    assert after["subtotal_cents"] == target["subtotal_after_cents"] and after["reserve_cents"] == before["reserve_cents"]
    assert any(i.get("existing_item_id") for i in after["items"])  # kept furniture preserved
    assert after["layouts"]["envelope_hash"] == before["layouts"]["envelope_hash"]  # SAME room frame
    assert after_state["plans"]["room_version_id"] == s["plans"]["room_version_id"]
    assert after_state["plans"]["preference_version_id"] == s["plans"]["preference_version_id"]
    assert _plan(after_state, "balanced") == _plan(s, "balanced")  # other plans untouched
    assert len(after_state["versions"]["plans"]) == len(s["versions"]["plans"]) + 1


def _rejected(c, pid, s, category, product_id, contains):
    r = c.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": category, "product_id": product_id})
    assert r.status_code == 422 and contains in r.json()["detail"], r.json()
    now = c.get(f"/api/projects/{pid}").json()
    assert now["plans"]["id"] == s["plans"]["id"]  # atomic: nothing written


def test_swap_rejects_over_budget_atomically(settings):
    c = TestClient(create_app(settings))
    pid, s = _bedroom(c)
    subtotal = _plan(s)["subtotal_cents"]
    pid, s = pid, c.put(f"/api/projects/{pid}/preferences", json={**s["preferences"]["data"], "budget_cents": subtotal, "reserve_pct": 0}).json()
    current = next(i for i in _plan(s)["items"] if i["category"] == "dresser")
    pricier = next(a for a in c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()["alternatives"]
                   if (a["delta_cents"] or 0) > 0 and a["status"] == "verified")
    assert pricier["can_swap"] is False and "over this room’s item budget" in pricier["reason"]
    assert current["product_id"] != pricier["product_id"]
    _rejected(c, pid, s, "dresser", pricier["product_id"], "over this room’s item budget")


def test_swap_rejects_incompatible_mattress_unverified_and_condition(settings):
    c = TestClient(create_app(settings))
    pid, s = _bedroom(c, bed_size="any")
    _rejected(c, pid, s, "bed_frame", "ikea-us-30602448", "mattress size doesn’t match")  # full frame vs queen mattress
    _rejected(c, pid, s, "bed_frame", "ikea-us-89241044", "could not be verified")  # no sourced price
    _rejected(c, pid, s, "bed_frame", "ikea-us-50511857", "different kind")  # a mattress, not a frame
    assert c.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": "dresser", "product_id": "nope"}).status_code == 404


def test_check_only_listing_import_never_changes_current_plans(settings):
    from furnishai.safe_fetch import RawResponse, SafeFetcher

    url = "https://www.chairish.com/product/41/oak-dresser"  # an approved resale listing (user direction: no unknown sites)
    page = (b'<title>Oak dresser</title><script type="application/ld+json">{"@type":"Product","name":"Oak dresser","url":"' + url.encode()
            + b'","offers":{"price":"95","priceCurrency":"USD"}}</script><p>Condition: Used</p><p>Size 44" W x 22" D</p>')

    def opener(target, headers, timeout, max_bytes):
        return RawResponse(200, {"content-type": "text/html"}, page)

    app = create_app(settings, fetcher=SafeFetcher(resolver=lambda h, p: ["93.184.216.34"], opener=opener))
    c = TestClient(app)
    pid, s = _bedroom(c)
    alts = c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()["alternatives"]
    target = next(a for a in alts if a["can_swap"] and not a["current"])
    swapped = c.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": "dresser", "product_id": target["product_id"]}).json()
    r = c.post(f"/api/projects/{pid}/listings", json={"url": url, "category": "dresser", "condition": "secondhand", "rebuild_plans": False}).json()
    assert r["plans_rebuilt"] is False and r["snapshot"]["status"] == "verified"
    assert r["state"]["plans"]["id"] == swapped["plans"]["id"]  # the swap is NOT undone
    assert _plan(r["state"]) == _plan(swapped)  # same items, totals and geometry
    new_alts = c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()["alternatives"]
    imported = next(a for a in new_alts if a["product_id"] == r["snapshot"]["id"])
    assert imported["condition"] == "secondhand" and imported["condition_verified"] is True  # stated on the listing itself
    # Default (no flag) keeps the original import-and-rebuild behavior for existing callers.
    r2 = c.post(f"/api/projects/{pid}/listings", json={"url": url, "category": "dresser"}).json()
    assert r2["plans_rebuilt"] is True and r2["state"]["plans"]["id"] != swapped["plans"]["id"]


def test_swap_with_stale_plan_version_is_refused(settings):
    c = TestClient(create_app(settings))
    pid, s = _bedroom(c)
    alts = c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()
    target = next(a for a in alts["alternatives"] if a["can_swap"] and not a["current"])
    seen_version = alts["plan_version"]
    c.post(f"/api/projects/{pid}/plans")  # plans change in the meantime (e.g. another tab)
    before = c.get(f"/api/projects/{pid}").json()["plans"]["id"]
    stale = c.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": "dresser",
                                                       "product_id": target["product_id"], "expected_plan_version": seen_version})
    assert stale.status_code == 409 and c.get(f"/api/projects/{pid}").json()["plans"]["id"] == before
    fresh = c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()
    ok = c.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": "dresser",
                                                    "product_id": target["product_id"], "expected_plan_version": fresh["plan_version"]})
    assert ok.status_code == 200


def test_alternatives_state_fit_limits_and_unknown_delivery(settings):
    c = TestClient(create_app(settings))
    pid, s = _bedroom(c)
    alts = c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()["alternatives"]
    assert all(a["fit_note"].startswith("Fit not assessed") for a in alts)  # demo room has no known size
    assert all("delivery or pickup timing is unknown — check with the seller" in a["delivery_note"] for a in alts)
    st = c.post("/api/demo", json={"room_type": "studio"}).json()
    sug = st["room"]["data"]["plan_dimension_suggestions"][0]
    pid2 = st["project"]["id"]
    c.post(f"/api/projects/{pid2}/scale", json={"width_in": sug["width_in"], "depth_in": sug["depth_in"], "basis": "plan_confirmed",
                                                 "source_ids": sug["source_ids"], "exact_unit_confirmed": True})
    a2 = c.get(f"/api/projects/{pid2}/alternatives", params={"plan_key": "value", "category": "desk"}).json()["alternatives"]
    assert all("on its own" in a["fit_note"] and "Not a guarantee" in a["fit_note"] for a in a2)


def test_research_primary_results_files_and_worst_case_reservation():
    from furnishai.research import file_kind, reservation_usd
    body = search_body()
    body["output"][0]["action"]["sources"] += [{"type": "url", "url": "https://about.offerup.com/policies/"},
                                               {"type": "url", "url": "https://www.maplecourt.example/schedule-a-tour/"}]
    parsed = parse_search_response(body)
    primary = [r["url"] for r in parsed["results"] if r["primary"]]
    assert primary == [GOOD, GOOD2]  # only cited, relevant results lead
    low = {r["url"]: r for r in parsed["results"]}
    assert low["https://about.offerup.com/policies/"]["primary"] is False and low["https://about.offerup.com/policies/"]["low_relevance"]
    assert parsed["results"][-1]["low_relevance"]  # demoted to the end
    assert file_kind("https://x.example/plans/a1.PDF") == "pdf" and file_kind("https://x.example/-/media/siteplan") == "file"
    assert file_kind("https://x.example/fp.webp") == "image" and file_kind("https://x.example/floorplans/") == "page"
    assert reservation_usd() == pytest.approx((25000 * 0.125 + 1800 * 0.50) / 1e6 + 0.02)


def test_settings_reasons_for_condition_exclusions_size_and_shared_bed():
    from furnishai.models import Preferences
    from furnishai.planner import _settings_reason
    used = {"id": "u1", "category": "desk", "condition": "secondhand", "name": "Oak desk", "retailer": "Craigslist"}
    assert "new only" in _settings_reason(used, Preferences(condition="new"))
    assert "avoid" in _settings_reason(used, Preferences(excluded_terms=["oak"]))
    twin = {"id": "t", "category": "bed_frame", "condition": "new", "name": "Twin bed", "nominal_size": "twin",
            "mattress_size_text": '38 " x 74 1/2 "'}
    assert "bed size is queen" in _settings_reason(twin, Preferences(bed_size="queen"))
    assert "shared" in _settings_reason(twin, Preferences(shared_use=True))
    assert _settings_reason(used, Preferences()) is None


def test_swap_routes_are_owner_only(settings):
    app = create_app(settings)
    c = TestClient(app)
    pid, _ = _bedroom(c)
    other = TestClient(app)
    assert other.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).status_code == 404
    assert other.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": "dresser", "product_id": "ikea-us-70582165"}).status_code == 404
