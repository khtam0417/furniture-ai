"""Typo suggestions, building-vs-source results, typed plan issues, sized furniture search and the manual shopping
checklist (DETERMINISTIC / MOCKED transport; nothing leaves the machine)."""

import json
from urllib.parse import urlsplit

import httpx2
from fastapi.testclient import TestClient

from furnishai.app import create_app
from furnishai.config import Settings
from furnishai.models import PlanSet
from furnishai.planner import build_plans
from furnishai.research import file_kind, furniture_query
from furnishai.safe_fetch import RawResponse, SafeFetcher
from furnishai.sources import building_candidates, close_token, match_directories

from conftest import product
from test_domain import prefs

FAKE_KEY = "test-key-not-a-real-credential"


# ------------------------------------------------------------------ 1. typo suggestions keep every location rule
def test_typo_suggests_a_checked_building_only_with_a_consistent_location():
    def found(*a):
        return [(c["directory"], c["suggested"]) for c in match_directories(*a)]
    assert found("Aduban", "New Haven", "CT", "") == [("theaudubonapts.json", True)]
    assert found("Audobon", "", "", "06511") == [("theaudubonapts.json", True)]
    assert found("The Audubon", "New Haven", "CT", "") == [("theaudubonapts.json", False)]  # exact, not a suggestion
    assert found("Archve", "New Haven", "CT", "") == [("thearchiveapts.json", True)]
    assert found("Aduban", "Boston", "MA", "") == []            # a typo never relaxes the location rules
    assert found("Aduban", "New Haven", "CT", "10001") == []    # contradicting ZIP
    assert found("Aduban", "New Haven", "NY", "") == []         # contradicting state
    assert found("Archer", "New Haven", "CT", "") == []         # a different word, not a typo
    assert found("Auburn", "New Haven", "CT", "") == []
    assert found("Aduban Lofts", "New Haven", "CT", "") == []   # extra name words don't match
    assert match_directories("Aduban", "New Haven", "CT", "")[0]["typed_name"] == "Aduban"
    assert not close_token("ave", "ava") and not close_token("marchive", "archive") and close_token("audabon", "audubon")


def test_a_suggested_building_is_chosen_only_by_explicit_confirmation(settings):
    page = RawResponse(200, {"content-type": "text/html"}, b"<p>Loading</p>")
    fetcher = SafeFetcher(resolver=lambda h, p: ["93.184.216.34"], opener=lambda t, h, to, mb: page)
    c = TestClient(create_app(settings, fetcher=fetcher))
    ctx = {"property_name": "Aduban", "city": "New Haven", "state": "CT", "zip": "", "unit_label": "", "property_url": "",
           "condition": "either", "fulfillment": "either", "timing": ""}
    a = c.post("/api/apartments", json={"name": "Home", "preset": "studio", "context": ctx}).json()
    pid = a["rooms"][0]["project_id"]
    f = c.post(f"/api/projects/{pid}/buildings/find", json={"property_name": "Aduban", "city": "New Haven", "state": "CT",
                                                            "include_web": False}).json()
    assert [x["suggested"] for x in f["checked"]] == [True]
    assert c.get(f"/api/apartments/{a['apartment']['id']}").json()["context"]["building"] is None  # nothing auto-selected
    r = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "checked", "key": "checked:theaudubonapts.json",
                                                              "property_name": "Aduban", "city": "New Haven", "state": "CT"})
    assert r.status_code == 200 and r.json()["apartment"]["context"]["building"]["name"] == "The Audubon"
    bad = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "checked", "key": "checked:theaudubonapts.json",
                                                                "property_name": "Aduban", "city": "Boston", "state": "MA"})
    assert bad.status_code == 422


# ------------------------------------------------------------------ 1b. buildings vs sources
def _r(url, title, cited=True):
    return {"url": url, "title": title, "domain": urlsplit(url).hostname, "cited_text": title, "file_kind": file_kind(url),
            "evidence": ["search source"] + (["citation"] if cited else []), "low_relevance": False}


SEARCH = [_r("https://www.theaudubonapts.example/", "The Audubon Apartments | New Haven, CT"),
          _r("https://www.point2homes.com/US/Apartment-For-Rent/CT/New-Haven/x.html", "point2homes.com"),
          _r("https://www.spinrep.com/ct/new-haven", "spinrep.com"),
          _r("https://www.zillow.com/b/the-audubon-new-haven-ct/", "Zillow"),
          _r("https://www.otherplace.example/", "Maple Court Apartments | New Haven, CT")]


def test_only_results_that_name_the_building_are_buildings():
    cards, _ = building_candidates(SEARCH, "Aduban", "New Haven", "CT", "", [])
    buildings = [c["site"] for c in cards if c["identity"] == "building"]
    sources = {c["site"]: c["source_reason"] for c in cards if c["identity"] == "source"}
    assert buildings == ["www.theaudubonapts.example"]  # named (a cautious typo allowed); never a bare .com
    assert set(sources) == {"www.point2homes.com", "www.spinrep.com", "www.zillow.com", "www.otherplace.example"}
    assert "Listing or directory" in sources["www.point2homes.com"] and "Listing or directory" in sources["www.zillow.com"]
    assert "Only a website name" in sources["www.spinrep.com"]  # no official claim without evidence
    assert "doesn’t name your building" in sources["www.otherplace.example"]


def _search_body(results):
    return {"id": "resp_x", "object": "response", "created_at": 1761400000, "status": "completed", "model": "gpt-6-luna",
            "output": [{"type": "web_search_call", "id": "ws", "status": "completed",
                        "action": {"type": "search", "query": "q", "sources": [{"type": "url", "url": r["url"]} for r in results]}},
                       {"type": "message", "id": "m", "role": "assistant", "status": "completed", "content": [{
                           "type": "output_text", "text": "x" * 60,
                           "annotations": [{"type": "url_citation", "start_index": 0, "end_index": 5, "url": r["url"],
                                            "title": r["title"]} for r in results]}]}],
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 10}}


def _live(tmp_path, body_for):
    sent = []

    def gw(request):
        sent.append(json.loads(request.content or b"{}"))
        return httpx2.Response(200, json=body_for(sent[-1]))
    s = Settings(storage_dir=tmp_path / "s", portkey_api_key=FAKE_KEY, live_disabled=False)
    return TestClient(create_app(s, ai_transport=httpx2.MockTransport(gw))), sent


def test_sources_are_listed_apart_and_cannot_be_chosen_as_a_building(tmp_path):
    c, _ = _live(tmp_path, lambda body: _search_body(SEARCH))
    pid = c.post("/api/apartments", json={"name": "H", "preset": "studio", "context": {
        "property_name": "Aduban", "city": "New Haven", "state": "CT", "zip": "", "unit_label": "", "property_url": "",
        "condition": "either", "fulfillment": "either", "timing": ""}}).json()["rooms"][0]["project_id"]
    f = c.post(f"/api/projects/{pid}/buildings/find", json={"property_name": "Aduban", "city": "New Haven", "state": "CT"}).json()
    assert [w["site"] for w in f["web"]] == ["www.theaudubonapts.example"]
    assert {s["site"] for s in f["sources"]} >= {"www.point2homes.com", "www.spinrep.com", "www.zillow.com"}
    r = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "url": "https://www.spinrep.com/ct/new-haven",
                                                              "property_name": "Aduban", "city": "New Haven", "state": "CT"})
    assert r.status_code == 422 and "source" in r.json()["detail"]


# ------------------------------------------------------------------ 2. catalog gap vs room fit vs budget
def test_missing_twin_is_a_catalog_gap_with_sized_actions_not_a_fit_problem():
    cat = [product("qf", "bed_frame", 20000, nominal_size="queen"), product("ff", "bed_frame", 15000, nominal_size="full"),
           product("qm", "mattress", 30000, w=60, d=80, nominal_size="queen")]
    p = prefs(categories=["bed_frame", "mattress"], bed_size="twin", budget_cents=50000)
    ps = build_plans(p, cat, None, "bedroom")
    assert p.bed_size == "twin" and p.budget_cents == 50000  # never changed for the user
    assert len(ps.conflicts) == 3  # the plain texts are still there for exports/older readers
    [issue] = ps.issues
    assert issue.kind == "catalog_gap" and issue.size == "twin" and issue.categories == ["bed_frame", "mattress"]
    assert issue.title == "We still need two items for your twin bed"
    assert "doesn’t mean a twin won’t fit" in issue.detail and "full, queen" in issue.detail
    assert [(a.kind, a.category, a.size) for a in issue.actions] == [
        ("find", "bed_frame", "twin"), ("find", "mattress", "twin"), ("edit_preferences", None, None)]


def test_room_fit_and_budget_are_their_own_kinds():
    from test_domain import scaled_room
    room = scaled_room(60, 60)
    big = [product("big", "desk", 9000, w=90, d=90)]
    ps = build_plans(prefs(categories=["desk"]), big, room, "bedroom")
    assert [i.kind for i in ps.issues] == ["room_fit"] and "fit your known room size" in ps.issues[0].title
    ps2 = build_plans(prefs(categories=["desk"], budget_cents=1000, reserve_pct=0), [product("d", "desk", 9000)], None, "bedroom")
    assert [i.kind for i in ps2.issues] == ["budget"] and ps2.issues[0].actions[0].kind == "edit_preferences"
    old = PlanSet.model_validate({"plans": [], "conflicts": ["legacy text"]})  # a version saved before typed issues
    assert old.issues == [] and old.conflicts == ["legacy text"]


def test_bed_searches_carry_the_requested_size(tmp_path):
    assert "twin size mattress" in furniture_query("mattress", "New Haven CT", "either", "either", None, "twin")
    assert "twin" not in furniture_query("desk", "", "either", "either", None, "twin")  # size only for beds
    c, sent = _live(tmp_path, lambda body: _search_body([]))
    s = c.post("/api/projects", json={"name": "B", "room_type": "bedroom"}).json()
    pid = s["project"]["id"]
    c.put(f"/api/projects/{pid}/preferences", json={**s["preferences"]["data"], "bed_size": "twin"})
    r = c.post(f"/api/projects/{pid}/research/furniture", json={"category": "bed_frame"}).json()
    assert r["size"] == "twin" and "twin size bed frame" in json.dumps(sent[-1])
    c.post(f"/api/projects/{pid}/research/furniture", json={"category": "mattress", "size": "full"})
    assert "full size mattress" in json.dumps(sent[-1])  # an explicit action size wins
    assert c.get(f"/api/projects/{pid}").json()["preferences"]["data"]["bed_size"] == "twin"  # unchanged


# ------------------------------------------------------------------ 4. shopping checklist
def _demo(c):
    s = c.post("/api/demo", json={"room_type": "bedroom"}).json()
    return s["project"]["id"], s


def _plan(state, key):
    return next(p for p in state["plans"]["data"]["plans"] if p["key"] == key)


def test_checklist_defaults_marks_totals_and_owned_items(settings):
    c = TestClient(create_app(settings))
    pid, s = _demo(c)
    cl = c.get(f"/api/projects/{pid}/checklist").json()
    plans = s["plans"]["data"]["plans"]
    # Default = Balanced (the plans view's default) when it exists, else the first plan.
    first = next((p for p in plans if p["key"] == "balanced"), plans[0])
    assert cl["plan_key"] == first["key"] and cl["plan_version"] == s["plans"]["version"]
    buy = [i for i in cl["items"] if not i["owned"]]
    owned = [i for i in cl["items"] if i["owned"]]
    assert owned and all(i["purchased"] is None and i["product_id"] is None for i in owned)  # already owned: no charge
    assert cl["subtotal_cents"] == sum(i["price_cents"] for i in buy) == first["subtotal_cents"]
    assert cl["counts"] == {"to_buy": len(buy), "purchased": 0, "remaining": len(buy), "owned": len(owned), "price_unknown": 0}
    target = buy[0]
    body = {"plan_key": cl["plan_key"], "product_id": target["product_id"], "purchased": True, "expected_plan_version": cl["plan_version"]}
    after = c.post(f"/api/projects/{pid}/checklist/mark", json=body).json()
    assert after["counts"]["purchased"] == 1 and after["purchased_cents"] == target["price_cents"]
    assert after["remaining_cents"] == after["subtotal_cents"] - target["price_cents"]
    again = c.get(f"/api/projects/{pid}/checklist").json()  # survives a refresh
    assert next(i for i in again["items"] if i["product_id"] == target["product_id"])["purchased"] is True
    undo = c.post(f"/api/projects/{pid}/checklist/mark", json={**body, "purchased": False}).json()
    assert undo["counts"]["purchased"] == 0
    rows = c.app.state.db.all("SELECT purchased FROM purchase_marks WHERE project_id=? ORDER BY rowid", (pid,))
    assert [r["purchased"] for r in rows] == [1, 0]  # append-only history


def test_checklist_refuses_stale_invalid_owned_and_other_sessions(settings):
    app = create_app(settings)
    c = TestClient(app)
    pid, s = _demo(c)
    cl = c.get(f"/api/projects/{pid}/checklist").json()
    pid_buy = next(i for i in cl["items"] if not i["owned"])["product_id"]
    base = {"plan_key": cl["plan_key"], "product_id": pid_buy, "purchased": True, "expected_plan_version": cl["plan_version"]}
    assert c.post(f"/api/projects/{pid}/checklist/mark", json={**base, "expected_plan_version": cl["plan_version"] + 5}).status_code == 409
    assert c.post(f"/api/projects/{pid}/checklist/mark", json={**base, "product_id": "not-in-plan"}).status_code == 422
    other_plan = next((p for p in s["plans"]["data"]["plans"] if p["key"] != cl["plan_key"]), None)
    if other_plan:  # a product of plan A can't be marked under plan B unless B has it too
        only_a = next((i["product_id"] for i in cl["items"] if i["product_id"]
                       and i["product_id"] not in {x.get("product_id") for x in other_plan["items"]}), None)
        if only_a:
            r = c.post(f"/api/projects/{pid}/checklist/mark", json={**base, "plan_key": other_plan["key"], "product_id": only_a})
            assert r.status_code == 409  # not the selected plan; refused before membership is even considered
    assert app.state.db.all("SELECT * FROM purchase_marks WHERE project_id=?", (pid,)) == []  # nothing written
    other = TestClient(app)
    assert other.get(f"/api/projects/{pid}/checklist").status_code == 404
    assert other.post(f"/api/projects/{pid}/checklist/mark", json=base).status_code == 404
    c.post(f"/api/projects/{pid}/checklist/mark", json=base)
    c.delete(f"/api/projects/{pid}")
    assert app.state.db.all("SELECT * FROM purchase_marks WHERE project_id=?", (pid,)) == []
    assert app.state.db.all("SELECT * FROM plan_selection WHERE project_id=?", (pid,)) == []


def test_plan_selection_persists_and_swaps_never_inherit_purchases(settings):
    c = TestClient(create_app(settings))
    pid, s = _demo(c)
    keys = [p["key"] for p in s["plans"]["data"]["plans"]]
    cl = c.get(f"/api/projects/{pid}/checklist").json()
    if len(keys) > 1:
        sel = c.put(f"/api/projects/{pid}/checklist/plan", json={"plan_key": keys[1], "expected_plan_version": cl["plan_version"]}).json()
        assert sel["plan_key"] == keys[1] and c.get(f"/api/projects/{pid}/checklist").json()["plan_key"] == keys[1]
        assert c.put(f"/api/projects/{pid}/checklist/plan", json={"plan_key": keys[0], "expected_plan_version": 999}).status_code == 409
        c.put(f"/api/projects/{pid}/checklist/plan", json={"plan_key": "value", "expected_plan_version": cl["plan_version"]})
    cl = c.get(f"/api/projects/{pid}/checklist").json()
    assert cl["plan_key"] == "value"
    dresser = next(i for i in cl["items"] if i["category"] == "dresser")
    c.post(f"/api/projects/{pid}/checklist/mark", json={"plan_key": "value", "product_id": dresser["product_id"],
                                                        "purchased": True, "expected_plan_version": cl["plan_version"]})
    before = _plan(c.get(f"/api/projects/{pid}").json(), "value")
    alt = next(a for a in c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()["alternatives"]
               if a["can_swap"] and not a["current"])
    st = c.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": "dresser", "product_id": alt["product_id"]}).json()
    after_cl = c.get(f"/api/projects/{pid}/checklist").json()
    new_row = next(i for i in after_cl["items"] if i["category"] == "dresser")
    assert new_row["product_id"] == alt["product_id"] and new_row["purchased"] is False  # no inherited purchase
    assert after_cl["counts"]["purchased"] == 0 and after_cl["purchased_cents"] == 0 and after_cl["retired_purchased"] == 1
    assert after_cl["subtotal_cents"] == _plan(st, "value")["subtotal_cents"]  # the retired item is not in the totals
    assert after_cl["plan_key"] == "value" and after_cl["plan_version"] == st["plans"]["version"]
    # Old list version is now stale for writes.
    r = c.post(f"/api/projects/{pid}/checklist/mark", json={"plan_key": "value", "product_id": alt["product_id"],
                                                            "purchased": True, "expected_plan_version": cl["plan_version"]})
    assert r.status_code == 409
    # Geometry invariants after the swap: same room frame, no duplicate physical footprint, mattress attached to the bed.
    after = _plan(st, "value")
    assert after["layouts"]["envelope_hash"] == before["layouts"]["envelope_hash"]
    for arr in after["layouts"]["arrangements"]:
        refs = [p["ref"] for p in arr["placements"]]
        assert len(refs) == len(set(refs))
        assert all(a["ref"] not in refs for a in arr["associated"])
        mattress = next((a for a in arr["associated"] if "mattress" in (a["label"] or "").lower()), None)
        frame = next((p for p in arr["placements"] if p.get("category") == "bed_frame"), None)
        if mattress and frame:
            assert mattress["on_ref"] == frame["ref"]


def test_checked_match_plus_only_sources_never_says_no_building_was_found(tmp_path):
    only = [_r("https://www.theaudubonapts.com/floorplans", "The Audubon | Floor plans"),
            _r("https://www.spinrep.com/ct/new-haven", "spinrep.com"), _r("https://www.rent.com/x", "Rent.com")]
    c, _ = _live(tmp_path, lambda body: _search_body(only))
    pid = c.post("/api/projects", json={"name": "S", "room_type": "studio"}).json()["project"]["id"]
    f = c.post(f"/api/projects/{pid}/buildings/find", json={"property_name": "Aduban", "city": "New Haven", "state": "CT"}).json()
    assert [x["also_in_search"] for x in f["checked"]] == [True] and f["web"] == [] and len(f["sources"]) == 2
    assert f["web_note"].startswith("Your checked match is shown above") and "no additional building matches" in f["web_note"]
    assert "clearly names" not in f["web_note"]


# ------------------------------------------------------------------ pass-24 review regressions
def test_a_real_name_matching_its_own_domain_is_still_a_building():
    results = [_r("https://www.maplecourt.example/floorplans", "Maple Court"),
               _r("https://www.maplecourt-two.example/", "www.maplecourt-two.example"),
               _r("https://www.greystar.example/", "Greystar Apartments"),
               _r("https://www.zillow.com/b/maple-court/", "Zillow")]
    cards, _ = building_candidates(results, "Maple Court", "Seattle", "WA", "", [])
    kind = {c["site"]: (c["identity"], c.get("source_reason") or "") for c in cards}
    assert kind["www.maplecourt.example"][0] == "building"            # its words being in the host is fine
    assert kind["www.maplecourt-two.example"] == ("source", "Only a website name; this result doesn’t identify a building.")
    assert kind["www.greystar.example"][0] == "source" and "doesn’t name" in kind["www.greystar.example"][1]
    assert kind["www.zillow.com"][0] == "source"
    aud, _ = building_candidates([_r("https://www.theaudubonapts.com/", "The Audubon")], "The Audubon", "New Haven", "CT", "", [])
    assert aud[0]["identity"] == "building"
    bare, _ = building_candidates([_r("https://www.spinrep.com/x", "spinrep.com")], "Spinrep", "New Haven", "CT", "", [])
    assert bare[0]["identity"] == "source"  # a literal hostname title is never a building


def test_marketplace_links_carry_the_bed_size_and_nothing_private(tmp_path):
    from furnishai.research import external_search_links
    links = external_search_links("mattress", "New Haven CT", "twin")
    assert all("twin+mattress" in link["url"] for link in links)
    assert all("Haven" not in link["url"] for link in links)
    assert all("twin" not in link["url"] for link in external_search_links("desk", "", "twin"))
    c, _ = _live(tmp_path, lambda body: _search_body([]))
    s = c.post("/api/projects", json={"name": "B", "room_type": "bedroom"}).json()
    pid = s["project"]["id"]
    c.put(f"/api/projects/{pid}/preferences", json={**s["preferences"]["data"], "bed_size": "twin"})
    r = c.post(f"/api/projects/{pid}/research/furniture", json={"category": "bed_frame"}).json()
    assert all("twin+bed+frame" in link["url"] for link in r["external_search_links"])


def test_mark_refuses_a_plan_that_is_no_longer_the_selected_one(settings):
    c = TestClient(create_app(settings))
    pid, s = _demo(c)
    plans = s["plans"]["data"]["plans"]
    if len(plans) < 2:
        return
    v = s["plans"]["version"]
    a, b = plans[0], plans[1]
    shared = {i["product_id"] for i in a["items"] if i["product_id"]} & {i["product_id"] for i in b["items"] if i["product_id"]}
    c.put(f"/api/projects/{pid}/checklist/plan", json={"plan_key": a["key"], "expected_plan_version": v})
    # Another tab switches the list to plan B (same plan version) ...
    c.put(f"/api/projects/{pid}/checklist/plan", json={"plan_key": b["key"], "expected_plan_version": v})
    # ... so the first tab's mark for plan A is refused instead of silently changing B's list.
    item = next(i for i in a["items"] if i["product_id"])
    r = c.post(f"/api/projects/{pid}/checklist/mark", json={"plan_key": a["key"], "product_id": item["product_id"],
                                                            "purchased": True, "expected_plan_version": v})
    assert r.status_code == 409 and "different plan" in r.json()["detail"]
    assert c.app.state.db.all("SELECT * FROM purchase_marks WHERE project_id=?", (pid,)) == []
    if shared:  # one product in both plans: its status follows the product, whichever plan is shown
        pid_shared = sorted(shared)[0]
        c.post(f"/api/projects/{pid}/checklist/mark", json={"plan_key": b["key"], "product_id": pid_shared,
                                                            "purchased": True, "expected_plan_version": v})
        back = c.put(f"/api/projects/{pid}/checklist/plan", json={"plan_key": a["key"], "expected_plan_version": v}).json()
        assert next(i for i in back["items"] if i["product_id"] == pid_shared)["purchased"] is True


def test_old_plan_versions_are_flagged_for_rebuild_never_rewritten(settings):
    app = create_app(settings)
    c = TestClient(app)
    s = c.post("/api/projects", json={"name": "B", "room_type": "bedroom"}).json()
    pid = s["project"]["id"]
    assert s["plans_info"]["typed_issues"] is True and s["plans_info"]["catalog_updated_after"] is False
    # Simulate a version saved before typed issues and before the catalog's newest check (e.g. twin added).
    head = app.state.db.head("plan_versions", pid)
    legacy = {k: v for k, v in head["data"].items() if k != "issues"}
    legacy["conflicts"] = ["No verified twin bed frame in the catalog (available: full, queen). Change the bed size or import a listing for that size."]
    app.state.db.exec("INSERT INTO plan_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
                      ("plan_legacy", pid, head["version"] + 1, head["id"], head["room_version_id"], head["preference_version_id"],
                       "[]", json.dumps(legacy), "legacy", "2026-10-20T00:00:00+00:00"))
    st = c.get(f"/api/projects/{pid}").json()
    assert st["plans_info"] == {**st["plans_info"], "typed_issues": False, "catalog_updated_after": True}
    assert st["plans"]["data"]["conflicts"] == legacy["conflicts"]  # shown as saved, not rewritten
    rebuilt = c.post(f"/api/projects/{pid}/plans").json()
    assert rebuilt["plans"]["version"] == head["version"] + 2 and rebuilt["plans_info"]["typed_issues"] is True
    old = app.state.db.version_by_id("plan_versions", pid, "plan_legacy")
    assert old["data"] == legacy  # the old version is untouched in history
