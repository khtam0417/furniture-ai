"""Room-use semantics, fail-closed placement, map revisions, product browsing and in-app online search.

DETERMINISTIC / MOCKED AI / FAKE NETWORK. Maps are SYNTHETIC hand-written fixtures (shaped like the kinds of readings
seen in review, e.g. a bath read as a low-confidence "bedroom"); they check code paths, not the model's vision.
"""

import json

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from furnishai import design_api
from furnishai.app import create_app
from furnishai.config import Settings
from furnishai.design import (
    Design, DesignPrefs, Floor, _back_edge, arrange, check_items, default_pieces, door_rects, footprint_in, rect_of,
    rects_overlap,
)
from furnishai.planmap import PlanMapOutput, room_uses, validate_map
from furnishai.safe_fetch import RawResponse, SafeFetcher

from conftest import make_image
from test_floorplan_first import amz_page


def P(x, y):
    return {"x": x, "y": y}


def rect(x0, y0, x1, y1):
    return [P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]


def vmap(out, w=640, h=480):
    return validate_map(PlanMapOutput.model_validate(out), source_id="src_x", derivative_sha256="d" * 64, image_w=w,
                        image_h=h, model="gpt-6-luna", synthetic=True)


# A furnished 1-bed render: bedroom left (a bed seen), living middle, bath right (read as a low-confidence "bedroom").
ONE_BED = {
    "view": "3d",
    "rooms": [
        {"label": "", "kind": "bedroom", "polygon": rect(0.11, 0.25, 0.27, 0.69), "confidence": "medium",
         "contains": ["bed", "pillows"], "use_evidence": "furniture_seen"},
        {"label": "", "kind": "living", "polygon": rect(0.29, 0.30, 0.73, 0.62), "confidence": "low", "contains": ["sofa", "table"]},
        {"label": "", "kind": "bedroom", "polygon": rect(0.74, 0.25, 0.86, 0.57), "confidence": "low",
         "contains": ["toilet", "shower", "sink"], "use_evidence": "unclear"},
    ],
    "fixtures": [{"kind": "kitchen_counter", "polygon": rect(0.31, 0.63, 0.58, 0.70)}],
}


def placed_rect(m, it, by_id=None):
    w, d, _ = footprint_in(it, by_id or {})
    return rect_of(it.x * m.image_w, it.y * m.image_h, w * m.scale.ppi, d * m.scale.ppi, it.rotation)


# ------------------------------------------------------------------ room use and seeding
def test_bath_read_as_bedroom_is_never_furnished_with_a_bed():
    m = vmap(ONE_BED)
    uses = room_uses(m)
    assert uses["r1"].status == "confirmed" and uses["r2"].status == "confirmed"
    assert uses["r3"].status == "conflict" and uses["r3"].suggested_kind == "bath"
    items = arrange(m, default_pieces(m, DesignPrefs()), "walls", {})
    assert sum(1 for i in items if i.category == "bed_frame") == 1  # one confirmed bedroom = one bed set
    assert {i.zone_id for i in items if i.category in ("bed_frame", "nightstand", "dresser")} == {"r1"}
    assert all(i.zone_id != "r3" for i in items)
    for i in items:
        if i.placed and not i.on_item:
            assert not rects_overlap(placed_rect(m, i), (0.74 * 640, 0.25 * 480, 0.86 * 640, 0.57 * 480))  # never in the bath
    # Older readings without evidence fields: a low-confidence unlabelled "bedroom" is uncertain, not seeded.
    old = {**ONE_BED, "rooms": [{k: v for k, v in r.items() if k not in ("contains", "use_evidence")} for r in ONE_BED["rooms"]]}
    old["rooms"][0]["confidence"] = "medium"
    m2 = vmap(old)
    assert room_uses(m2)["r3"].status == "uncertain"
    assert sum(1 for i in default_pieces(m2, DesignPrefs()) if i.category == "bed_frame") == 1
    # A bath fixture outline inside a "bedroom" also flags it, without any evidence list.
    fx = {**old, "fixtures": old.get("fixtures", []) + [{"kind": "bath_fixture", "polygon": rect(0.76, 0.30, 0.80, 0.36)}]}
    assert room_uses(vmap(fx))["r3"].status == "conflict"


def test_only_uncertain_bedrooms_put_one_bed_set_in_not_placed():
    out = {"rooms": [
        {"label": "", "kind": "bedroom", "polygon": rect(0.1, 0.1, 0.4, 0.5), "confidence": "low"},
        {"label": "", "kind": "bedroom", "polygon": rect(0.5, 0.1, 0.9, 0.5), "confidence": "low"},
        {"label": "LIVING", "kind": "living", "polygon": rect(0.1, 0.55, 0.9, 0.95), "confidence": "high"},
    ]}
    m = vmap(out, w=600, h=600)
    items = arrange(m, default_pieces(m, DesignPrefs()), "walls", {})
    beds = [i for i in items if i.category == "bed_frame"]
    assert len(beds) == 1 and not beds[0].placed and "Bedroom" in beds[0].unplaced_reason
    mattress = next(i for i in items if i.category == "mattress")
    assert mattress.on_item == beds[0].id and not mattress.placed
    assert next(i for i in items if i.category == "sofa").placed


def test_two_confirmed_bedrooms_get_two_independent_sets():
    out = {"rooms": [
        {"label": "BEDROOM 1", "kind": "bedroom", "polygon": rect(0.05, 0.05, 0.45, 0.45)},
        {"label": "BEDROOM 2", "kind": "bedroom", "polygon": rect(0.55, 0.05, 0.95, 0.45)},
        {"label": "LIVING", "kind": "living", "polygon": rect(0.05, 0.5, 0.95, 0.95)},
    ]}
    m = vmap(out, w=500, h=500)
    items = arrange(m, default_pieces(m, DesignPrefs()), "walls", {})
    beds = [i for i in items if i.category == "bed_frame"]
    assert len(beds) == 2 and len({b.id for b in beds}) == 2 and {b.zone_id for b in beds} == {"r1", "r2"}
    assert all(b.placed for b in beds) and all(not w for w in check_items(m, items, {}).values())


# ------------------------------------------------------------------ fail-closed placement
def test_a_bed_that_cannot_fit_goes_to_not_placed_instead_of_the_room_middle():
    out = {"rooms": [{"label": "BEDROOM", "kind": "bedroom", "polygon": rect(0.1, 0.1, 0.2, 0.2), "dimension_text": "6' x 6'"},
                     {"label": "LIVING", "kind": "living", "polygon": rect(0.3, 0.1, 0.9, 0.9)}]}
    m = vmap(out, w=720, h=720)  # 72 x 72 px for 6 ft: a queen bed (64 x 84 in) can't fit
    assert m.scale.kind == "printed"
    items = arrange(m, default_pieces(m, DesignPrefs()), "walls", {})
    bed = next(i for i in items if i.category == "bed_frame")
    assert not bed.placed and "No spot in BEDROOM" in bed.unplaced_reason
    assert all(i.zone_id != "r2" for i in items if i.category == "bed_frame")  # not moved into the living room
    assert bed.id not in {k for k, v in check_items(m, items, {}).items() if v}  # unplaced pieces aren't checked/drawn


def test_pieces_in_overlapping_zones_never_overlap_each_other():
    out = {"rooms": [
        {"label": "SLEEPING", "kind": "sleeping", "polygon": rect(0.1, 0.1, 0.55, 0.9), "open_plan": True},
        {"label": "LIVING", "kind": "living", "polygon": rect(0.45, 0.1, 0.9, 0.9), "open_plan": True},
    ]}
    m = vmap(out, w=400, h=400)
    for key in ("walls", "long_wall", "corners"):
        items = [i for i in arrange(m, default_pieces(m, DesignPrefs()), key, {}) if i.placed and not i.on_item]
        rs = [placed_rect(m, i) for i in items]
        assert all(not rects_overlap(a, b) for n, a in enumerate(rs) for b in rs[n + 1:]), key


def test_doors_stay_clear_and_headboards_avoid_open_splits():
    out = {"rooms": [
        {"label": "SLEEPING", "kind": "sleeping", "polygon": rect(0.1, 0.1, 0.5, 0.9), "open_plan": True},
        {"label": "LIVING", "kind": "living", "polygon": rect(0.5, 0.1, 0.9, 0.9), "open_plan": True},
    ], "openings": [{"kind": "door", "a": P(0.2, 0.9), "b": P(0.32, 0.9)}]}
    m = vmap(out, w=500, h=500)
    doors = [d for _, d in door_rects(m)]
    for key in ("walls", "long_wall", "corners"):
        items = arrange(m, default_pieces(m, DesignPrefs()), key, {})
        bed = next(i for i in items if i.category == "bed_frame")
        assert bed.placed
        r = placed_rect(m, bed)
        assert not any(rects_overlap(r, d) for d in doors)
        (ax, ay), (bx, by) = _back_edge(r, bed.rotation)
        assert not (abs(ax - 250) < 3 and abs(bx - 250) < 3), key  # headboard not on the open SLEEPING/LIVING split
    fl = Floor(m)
    assert all(not (abs(a[0] - 250) < 1 and abs(b[0] - 250) < 1) for a, b in fl.walls["r1"])


# ------------------------------------------------------------------ API: revisions, re-read, browsing, online search
def client(tmp_path, outputs, *, live=False, gateway=None, net=None):
    calls = []

    def fn(messages, info):
        calls.append(1)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(outputs[min(len(calls), len(outputs)) - 1]))])
    s = Settings(storage_dir=tmp_path / "s", portkey_api_key="test-key-not-a-real-credential" if live else None,
                 live_disabled=not live)
    app = create_app(s, test_model=FunctionModel(fn), ai_transport=httpx2.MockTransport(gateway) if gateway else None,
                     fetcher=net)
    return TestClient(app), app, calls


def setup(c, unit="7C"):
    a = c.post("/api/apartments", json={"name": "Flat", "preset": "1b1b", "context": {
        "property_name": "The Example", "city": "New Haven", "state": "CT", "zip": "06511", "unit_label": unit,
        "property_url": "", "condition": "either", "fulfillment": "either", "timing": ""}}).json()
    aid, anchor = a["apartment"]["id"], a["rooms"][0]["project_id"]
    up = c.post(f"/api/projects/{anchor}/uploads", data={"kind": "floorplan"},
                files=[("files", ("plan.png", make_image("PNG", size=(640, 480)), "image/png"))]).json()
    src = next(r["id"] for r in up["results"] if r["ok"])
    s = c.post(f"/api/apartments/{aid}/design/plan", json={"source_id": src}).json()
    s = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": s["design"]["version"]}).json()
    return aid, anchor, s


def test_room_use_correction_is_a_revision_and_keeps_pieces(tmp_path):
    old = {**ONE_BED, "rooms": [{k: v for k, v in r.items() if k not in ("contains", "use_evidence")} for r in ONE_BED["rooms"]]}
    c, app, calls = client(tmp_path, [old])
    aid, anchor, s = setup(c)
    assert s["room_uses"]["r3"]["status"] == "uncertain"
    # Simulate an earlier bad suggestion: a nightstand placed in the uncertain room by hand.
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    s = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [
        {"op": "move", "id": ns["id"], "x": 0.8, "y": 0.4}]}).json()
    assert next(i for i in s["design"]["data"]["items"] if i["id"] == ns["id"])["zone_id"] == "r3"
    ai_map = s["plan_map"]
    r = c.post(f"/api/apartments/{aid}/design/rooms/r3/use", json={"expected_version": s["design"]["version"], "kind": "bath"}).json()
    assert r["plan_map"]["id"] != ai_map["id"] and r["plan_map"]["data"]["parent_map_id"] == ai_map["id"]
    assert r["plan_map"]["data"]["corrections"][0]["to"] == "bath" and r["room_uses"]["r3"]["status"] == "confirmed"
    moved = next(i for i in r["design"]["data"]["items"] if i["id"] == ns["id"])
    assert not moved["placed"] and "bath" in moved["unplaced_reason"] and moved["category"] == "nightstand"
    db = app.state.db
    assert json.loads(db.one("SELECT data FROM plan_maps WHERE id=?", (ai_map["id"],))["data"]) == ai_map["data"]  # AI reading kept
    # Reading again reuses (no AI call), and re-selecting the plan restores the corrected revision.
    again = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": r["design"]["version"]}).json()
    assert again["reused"] is True and len(calls) == 1 and again["plan_map"]["id"] == r["plan_map"]["id"]
    assert c.post(f"/api/apartments/{aid}/design/rooms/r9/use", json={"expected_version": r["design"]["version"], "kind": "bath"}).status_code == 404
    assert TestClient(app).post(f"/api/apartments/{aid}/design/rooms/r3/use", json={"expected_version": r["design"]["version"], "kind": "bath"}).status_code == 404
    assert c.post(f"/api/apartments/{aid}/design/rooms/r3/use", json={"expected_version": 1, "kind": "bath"}).status_code == 409
    # Add a bed set to a confirmed room on request.
    s2 = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": r["design"]["version"], "ops": [
        {"op": "add_set", "zone_id": "r1"}]}).json()
    assert sum(1 for i in s2["design"]["data"]["items"] if i["category"] == "bed_frame") == 2
    assert len({i["id"] for i in s2["design"]["data"]["items"]}) == len(s2["design"]["data"]["items"])


def test_re_read_with_a_newer_reader_keeps_pieces_and_products(tmp_path, monkeypatch):
    c, app, calls = client(tmp_path, [ONE_BED, ONE_BED])
    monkeypatch.setattr(design_api, "PLANMAP_PROMPT_VERSION", "plan-map-v0-test")
    aid, anchor, s = setup(c)
    monkeypatch.undo()
    s = c.get(f"/api/apartments/{aid}/design").json()
    assert s["map_outdated"] is True
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    opts = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()["candidates"]
    s = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/product", json={"expected_version": s["design"]["version"],
                                                                                "product_id": opts[0]["product_id"]}).json()
    before = {i["id"]: (i["category"], i["product_id"]) for i in s["design"]["data"]["items"]}
    r = c.post(f"/api/apartments/{aid}/design/read", json={"expected_version": s["design"]["version"]}).json()
    assert len(calls) == 2 and r["reused"] is False and r["map_outdated"] is False
    assert {i["id"]: (i["category"], i["product_id"]) for i in r["design"]["data"]["items"]} == before


def test_products_page_filter_and_browse_other_sizes(tmp_path):
    c, app, calls = client(tmp_path, [ONE_BED])
    aid, anchor, s = setup(c)
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    first = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?limit=2").json()
    assert len(first["candidates"]) == 2 and first["total"] > 2 and len(calls) == 1
    more = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?offset=2&limit=2").json()
    assert {x["product_id"] for x in more["candidates"]}.isdisjoint({x["product_id"] for x in first["candidates"]})
    cheap = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?sort=price_low&limit=48").json()["candidates"]
    assert [x["price_cents"] for x in cheap] == sorted(x["price_cents"] for x in cheap)
    bed = next(i for i in s["design"]["data"]["items"] if i["category"] == "bed_frame")
    full = c.get(f"/api/apartments/{aid}/design/items/{bed['id']}/products?size=full").json()
    assert full["candidates"] and all(x["nominal_size"] == "full" and x["size_mismatch"] for x in full["candidates"])
    # A product of another size can't be chosen for a queen piece without changing its size first.
    assert c.post(f"/api/apartments/{aid}/design/items/{bed['id']}/product", json={
        "expected_version": s["design"]["version"], "product_id": full["candidates"][0]["product_id"]}).status_code == 422


def _search_body(urls):
    return {"id": "resp_x", "object": "response", "created_at": 1761400000, "status": "completed", "model": "gpt-6-luna",
            "output": [{"type": "web_search_call", "id": "ws", "status": "completed",
                        "action": {"type": "search", "query": "q", "sources": [{"type": "url", "url": u} for u in urls]}},
                       {"type": "message", "id": "m", "role": "assistant", "status": "completed", "content": [{
                           "type": "output_text", "text": "x" * 60,
                           "annotations": [{"type": "url_citation", "start_index": 0, "end_index": 5, "url": u, "title": "T"}
                                           for u in urls]}]}],
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 10}}


class Net:
    def __init__(self, pages):
        self.pages = pages

    def resolver(self, host, port):
        return ["93.184.216.34"]

    def opener(self, target, headers, timeout, max_bytes):
        return self.pages.get(f"{target.scheme}://{target.host}{target.path}", RawResponse(404, {"content-type": "text/html"}, b"nf"))


GOOD = "https://www.amazon.com/dp/B000000001"
BAD = "https://www.amazon.com/dp/B000000002"
STORE = "https://www.wayfair.com/furniture/sb0/nightstands-c1780384.html"


def test_find_more_online_and_check_a_lead(tmp_path):
    sent = []

    def gateway(request):
        body = json.loads(request.content or b"{}")
        sent.append(body)
        return httpx2.Response(200, json=_search_body([GOOD, BAD, STORE]))
    pages = {GOOD: RawResponse(200, {"content-type": "text/html"}, amz_page()),
             BAD: RawResponse(200, {"content-type": "text/html"}, amz_page(asin="B000000002", prices=()))}
    net = Net(pages)
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway, net=SafeFetcher(resolver=net.resolver, opener=net.opener))
    aid, anchor, s = setup(c, unit="7C")
    v = s["design"]["version"]
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    s = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": v}).json()
    chosen_before = {i["id"]: i["product_id"] for i in s["design"]["data"]["items"]}
    v = s["design"]["version"]
    # Checking before any search: not one of this place's results.
    assert c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v, "url": GOOD}).status_code == 422
    r = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-online", json={"expected_version": v}).json()
    query = sent[-1]["input"]
    assert "nightstand" in query and "New Haven" in query and "7C" not in query
    assert "7C" not in json.dumps(sent)
    kinds = {l["url"]: l["kind"] for l in r["online"]["leads"]}
    assert kinds[GOOD] == "product" and STORE not in kinds  # Wayfair isn't an approved source: hidden server-side
    assert r["online"]["hidden_unapproved"] >= 1
    # Saved: the products view shows the leads again without a new search.
    n = len(sent)
    view = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()
    assert view["online"] and len(sent) == n
    assert c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v, "url": STORE}).status_code == 422
    assert c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v - 1, "url": GOOD}).status_code == 409
    assert TestClient(app).post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v, "url": GOOD}).status_code == 404
    bad = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v, "url": BAD}).json()
    assert bad["status"] == "incomplete" and not bad["matches"]
    assert "price_cents" in bad["missing"] and "missing price" in bad["message"] and "price_cents" not in bad["message"]
    assert c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/product", json={"expected_version": v, "product_id": bad["product_id"]}).status_code == 422
    good = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/check-lead", json={"expected_version": v, "url": GOOD}).json()
    assert good["status"] == "verified" and good["matches"]
    opts = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products?limit=48").json()["candidates"]
    assert any(o["product_id"] == good["product_id"] for o in opts)
    # The search and checks changed nothing in the design.
    s = c.get(f"/api/apartments/{aid}/design").json()
    assert s["design"]["version"] == v and {i["id"]: i["product_id"] for i in s["design"]["data"]["items"]} == chosen_before


def test_search_failure_keeps_chosen_products(tmp_path):
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=lambda req: httpx2.Response(500, json={"error": "x"}))
    aid, anchor, s = setup(c)
    s = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": s["design"]["version"]}).json()
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    before = s["design"]
    r = c.post(f"/api/apartments/{aid}/design/items/{ns['id']}/find-online", json={"expected_version": before["version"]})
    assert r.status_code in (502, 503)
    after = c.get(f"/api/apartments/{aid}/design").json()["design"]
    assert after["version"] == before["version"] and after["data"] == before["data"]


def test_online_query_uses_bed_size_and_remaining_budget(tmp_path):
    sent = []

    def gateway(request):
        sent.append(json.loads(request.content or b"{}"))
        return httpx2.Response(200, json=_search_body([GOOD]))
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway)
    aid, anchor, s = setup(c)
    prefs = {**s["design"]["data"]["prefs"], "budget_cents": 100000, "reserve_pct": 10, "bed_size": "king", "styles": ["minimal"]}
    s = c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs}).json()
    bed = next(i for i in s["design"]["data"]["items"] if i["category"] == "bed_frame")
    c.post(f"/api/apartments/{aid}/design/items/{bed['id']}/find-online", json={"expected_version": s["design"]["version"]})
    q = sent[-1]["input"]
    assert "king size bed frame" in q and "under $900" in q and "minimal style" in q and "06511" in q and "7C" not in q


# ------------------------------------------------------------------ unreadable maps and ambiguous zones
def test_unreadable_or_unusable_maps_never_paint_furniture_on_the_source():
    from furnishai.design import arrangement_options, place_new, DesignItem
    fallback = vmap({"is_floor_plan": True, "view": "3d", "rooms": []})
    assert fallback.status == "fallback"
    items = default_pieces(fallback, DesignPrefs())
    bed = next(i for i in items if i.category == "bed_frame")
    items = [i.model_copy(update={"product_id": "p1"}) if i.id == bed.id else i for i in items]
    out = arrange(fallback, items, "walls", {})
    assert [i.id for i in out] == [i.id for i in items] and all(not i.placed for i in out)
    assert all("could not be read" in i.unplaced_reason for i in out)
    assert next(i for i in out if i.id == bed.id).product_id == "p1"
    assert next(i for i in out if i.category == "mattress").on_item == bed.id
    assert arrangement_options(fallback, items, {}) == []
    assert not place_new(fallback, items, DesignItem(id="pc_x", category="sofa", x=0.5, y=0.5), {}).placed
    # A mapped reading whose only furnishable rooms are contradicted (bath fixtures seen): nothing usable either.
    bad = vmap({"rooms": [{"label": "", "kind": "bedroom", "polygon": rect(0.1, 0.1, 0.5, 0.5), "contains": ["toilet", "shower"]},
                          {"label": "", "kind": "living", "polygon": rect(0.5, 0.1, 0.9, 0.5), "contains": ["bathtub"]}]})
    assert bad.status == "mapped"
    out2 = arrange(bad, default_pieces(bad, DesignPrefs()), "walls", {})
    assert all(not i.placed for i in out2)


def test_merged_and_ambiguous_3d_zones_stay_out_of_automatic_placement():
    m = vmap({"view": "3d", "rooms": [
        {"label": "", "kind": "bedroom", "polygon": rect(0.05, 0.25, 0.27, 0.7), "confidence": "medium", "contains": ["bed", "pillows"]},
        # A huge "living" outline that also swallowed the bath (sofa AND toilet/shower seen in it).
        {"label": "", "kind": "living", "polygon": rect(0.29, 0.25, 0.94, 0.7), "confidence": "low", "contains": ["sofa", "toilet", "shower"]},
        {"label": "", "kind": "dining", "polygon": rect(0.29, 0.72, 0.6, 0.9), "confidence": "low"},
    ]})
    uses = room_uses(m)
    assert uses["r2"].status == "conflict" and uses["r3"].status == "uncertain"
    items = arrange(m, default_pieces(m, DesignPrefs()), "walls", {})
    assert all(i.zone_id not in ("r2", "r3") for i in items if i.placed)
    assert sum(1 for i in items if i.category == "bed_frame") == 1


def test_moves_are_refused_on_an_unreadable_plan(tmp_path):
    c, app, calls = client(tmp_path, [{"is_floor_plan": True, "view": "3d", "rooms": []}])
    aid, anchor, s = setup(c)
    assert all(not i["placed"] for i in s["design"]["data"]["items"])
    it = s["design"]["data"]["items"][0]
    r = c.post(f"/api/apartments/{aid}/design/items", json={"expected_version": s["design"]["version"], "ops": [
        {"op": "move", "id": it["id"], "x": 0.5, "y": 0.5}]})
    assert r.status_code == 422
    assert c.get(f"/api/apartments/{aid}/design/arrangements").json()["options"] == []


def test_reader_prompt_has_full_image_and_two_framed_crops():
    from furnishai.planmap import crop_frames, planmap_prompt
    from pydantic_ai import BinaryContent
    img = make_image("JPEG", size=(640, 480))
    parts = planmap_prompt("src_1", img, 640, 480)
    images = [x for x in parts if isinstance(x, BinaryContent)]
    texts = [x for x in parts if isinstance(x, str)]
    assert len(images) == 3 and images[0].data == img  # the full image first, unchanged
    assert "FULL image" in texts[0] and "x = 0.00 + u * 0.58" in texts[1] and "x = 0.42 + u * 0.58" in texts[2]
    assert [f[0][0] for f in crop_frames(400, 900)] == ["A", "B"] and crop_frames(400, 900)[1][2] == pytest.approx(0.42)


# ------------------------------------------------------------------ product-focused online search
def test_lead_kind_and_citation_cleanup():
    from furnishai.design_api import clean_cited, lead_kind
    store = [
        "https://www.wayfair.com/furniture/sb2/low-profile-queen-bed-frames-c296865-a5896~16900-a149879~488909.html",
        "https://www.wayfair.com/furniture/sb1/queen-bed-frames-c296865-a5896~16900.html",
        "https://www.wayfair.com/furniture/sb0/nightstands-c1780384.html",
        "https://www.facebook.com/marketplace/randallstown/furniture/",
        "https://www.amazon.com/s?k=queen+bed+frame",
        "https://www.ebay.com/sch/i.html?_nkw=queen+bed+frame",
    ]
    assert all(lead_kind(u) == "store" for u in store)
    product = ["https://www.amazon.com/Zinus-SmartBase/dp/B006MIUM20", "https://www.ikea.com/us/en/p/malm-bed-frame-s19316201/",
               "https://www.facebook.com/marketplace/item/123456789/", "https://www.wayfair.com/furniture/pdp/x-w000123.html"]
    assert all(lead_kind(u) == "product" for u in product)
    assert clean_cited("([amazon.com](https://www.amazon.com/s?k=x))") == ""
    assert clean_cited("Low-profile queen platform bed in walnut, 63 in wide ([ikea.com](https://ikea.com/x))") == \
        "Low-profile queen platform bed in walnut, 63 in wide"


def test_store_only_results_offer_one_refined_product_search(tmp_path):
    sent = []

    def gateway(request):
        body = json.loads(request.content or b"{}")
        sent.append(body)
        urls = ([GOOD] if "Product detail pages for specific" in body["input"] else
                ["https://www.amazon.com/s?k=nightstand", STORE])
        return httpx2.Response(200, json=_search_body(urls))
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway)
    aid, anchor, s = setup(c)
    v = s["design"]["version"]
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    url = f"/api/apartments/{aid}/design/items/{ns['id']}/find-online"
    assert c.post(url, json={"expected_version": v, "refine": True}).status_code == 409  # no first search yet
    r = c.post(url, json={"expected_version": v}).json()
    assert r["online"]["product_leads"] == 0 and r["refine_available"] is True
    assert "FURNITURE" not in sent[0]["instructions"] and "PRODUCT" in sent[0]["instructions"]
    assert "individual product pages" in sent[0]["input"] and "7C" not in sent[0]["input"]
    view = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()
    assert view["refine_available"] is True
    r2 = c.post(url, json={"expected_version": v, "refine": True}).json()
    assert len(sent) == 2 and r2["online"]["refined"] and r2["online"]["leads"][0]["kind"] == "product"
    assert r2["refine_available"] is False
    c.post(url, json={"expected_version": v, "refine": True})
    assert len(sent) == 2  # the same refined search is reused, never repeated
    view = c.get(f"/api/apartments/{aid}/design/items/{ns['id']}/products").json()
    assert view["online"]["refined"] and view["refine_available"] is False


# ------------------------------------------------------------------ persisted coordinates stay valid
def _live_like_map():
    # Geometry copied from root's live v4 reading of a furnished 1-bed render (640 x 480): a living zone sharing its
    # left edge (x = 0.539 -> 344.96 px) with an "other" room (not furnishable) and overlapping another "other" room;
    # a protected kitchen counter and a bath fixture. A sofa backed flush on the shared edge is a boundary case where
    # rounding the saved position must not push it into the fixed area.
    def poly(pts):
        return [P(x, y) for x, y in pts]
    return vmap({"view": "3d", "rooms": [
        {"label": "", "kind": "bedroom", "confidence": "medium", "contains": ["bed"],
         "polygon": poly([(0.073, 0.271), (0.289, 0.271), (0.289, 0.508), (0.073, 0.508)])},
        {"label": "", "kind": "balcony", "confidence": "medium", "contains": ["none_visible"],
         "polygon": poly([(0.081, 0.565), (0.212, 0.565), (0.212, 0.701), (0.081, 0.701)])},
        {"label": "", "kind": "other", "confidence": "low", "contains": ["table"],
         "polygon": poly([(0.322, 0.271), (0.539, 0.271), (0.539, 0.489), (0.322, 0.489)])},
        {"label": "", "kind": "living", "confidence": "low", "contains": ["sofa", "table"], "open_plan": True,
         "polygon": poly([(0.539, 0.396), (0.737, 0.396), (0.737, 0.695), (0.539, 0.695)])},
        {"label": "", "kind": "bath", "confidence": "low", "contains": ["sink"],
         "polygon": poly([(0.741, 0.262), (0.934, 0.262), (0.934, 0.479), (0.741, 0.479)])},
        {"label": "", "kind": "other", "confidence": "low", "contains": ["none_visible"],
         "polygon": poly([(0.702, 0.493), (0.869, 0.493), (0.869, 0.695), (0.702, 0.695)])},
    ], "fixtures": [
        {"kind": "kitchen_counter", "polygon": poly([(0.309, 0.634), (0.586, 0.634), (0.586, 0.701), (0.309, 0.701)])},
        {"kind": "bath_fixture", "polygon": poly([(0.766, 0.302), (0.877, 0.302), (0.877, 0.455), (0.766, 0.455)])},
    ]})


def _bad(ws):
    return [w for w in ws if "fixed area" in w or "door" in w or w.startswith("Overlaps the")]


def test_returned_arrangements_are_valid_after_rounding():
    from furnishai.design import arrangement_options, place_new, DesignItem
    m = _live_like_map()
    items = default_pieces(m, DesignPrefs())
    for o in arrangement_options(m, items, {}):
        out = [DesignItem.model_validate(i) for i in o["items"]]
        assert sum(1 for i in out if i.placed and not i.on_item) >= 3, o["key"]
        for k, ws in check_items(m, out, {}).items():
            assert not _bad(ws), (o["key"], ws)
        assert all(round(i.x, 5) == i.x and round(i.y, 5) == i.y for i in out)
    # The tolerance never hides a real overlap: pushing the sofa 6 px into the fixed "other" room still warns.
    placed = arrange(m, items, "walls", {})
    sofa = next(i for i in placed if i.category == "sofa")
    assert sofa.placed
    pushed = [i.model_copy(update={"x": round(i.x - 6 / m.image_w, 5)}) if i.id == sofa.id else i for i in placed]
    assert any("fixed area" in w for w in check_items(m, pushed, {})[sofa.id])
    # The added-item path persists valid coordinates too.
    base = arrange(m, items, "walls", {})
    for cat in ("sofa", "bookcase", "dresser"):
        new = place_new(m, base, DesignItem(id=f"pc_{cat}", category=cat, zone_id="r4", x=0.5, y=0.5), {})
        if new.placed:
            assert not _bad(check_items(m, base + [new], {})[new.id]), cat
            base.append(new)
