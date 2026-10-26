"""Floor-plan-first estimate path, plan references, and the Amazon parser (DETERMINISTIC / MOCKED AI; no network)."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from furnishai.adapters import adapter_for, amazon
from furnishai.app import create_app

from conftest import make_image


def plan_output(readings, shape="unknown"):
    return {"room_type_seen": "unclear", "shape_guess": shape,
            "per_photo": [{"photo_index": 0, "shows": "a floor plan drawing", "appears_same_room_as_others": "yes"}],
            "floorplan_readings": [{"photo_index": 0, "room_label": lbl, "dimension_text": txt} for lbl, txt in readings]}


def client_with(settings, readings, shape="unknown"):
    def fn(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(plan_output(readings, shape)))])
    app = create_app(settings, test_model=FunctionModel(fn))
    c = TestClient(app)
    s = c.post("/api/projects", json={"name": "Plan only", "room_type": "bedroom", "mode": "live"}).json()
    pid = s["project"]["id"]
    up = c.post(f"/api/projects/{pid}/uploads", data={"kind": "floorplan"},
                files=[("files", ("plan.png", make_image("PNG", size=(400, 300)), "image/png"))]).json()
    plan_id = next(r["id"] for r in up["results"] if r["ok"])
    # A plan-only upload gets a plan notice, not a "2–8 photos" coverage warning.
    assert "Analyze floor plan" in up["notice"] and "optional" in up["notice"] and "2–8" not in up["notice"]
    st = c.post(f"/api/projects/{pid}/analyze", json={}).json()["state"]
    return c, app, pid, plan_id, st


def _layouts(st):
    return [p["layouts"] for p in st["plans"]["data"]["plans"]]


def test_no_photo_floor_plan_reading_becomes_an_estimated_2d_room(settings):
    c, app, pid, plan_id, st = client_with(settings, [("Bedroom", "10'-0\" x 12'-0\"")])
    assert st["room"]["data"]["room"]["plan_estimate"] is None  # never chosen automatically
    assert all(l["basis"] == "unavailable" for l in _layouts(st))
    r = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": st["room"]["id"], "suggestion_index": 0, "source_id": plan_id})
    assert r.status_code == 200, r.text
    st2 = r.json()
    room = st2["room"]["data"]["room"]
    est = room["plan_estimate"]
    assert est["dimension_text"] == "10'-0\" x 12'-0\"" and est["source_id"] == plan_id and est["room_version_id"] == st["room"]["id"]
    assert room["scale_status"] == "unknown" and room["width"] is None and room["depth"] is None  # an estimate, not a known size
    for lay in _layouts(st2):
        assert lay["basis"] == "estimated_from_plan" and (lay["envelope_width_in"], lay["envelope_depth_in"]) == (114.0, 138.0)
        assert "your unit may differ" in lay["envelope_label"] and lay["arrangements"]
    for pl in st2["plans"]["data"]["plans"]:  # no automatic fit upgrade
        assert pl["fit_summary"] == "Fit unverified" and pl["fit_overview"]["room_size"] == "estimated_plan"
        assert all(i["fit_label"] == "Fit unverified" and i["fit_checks"]["room_size"] == "estimated_plan" for i in pl["items"])
    # Original plan bytes and earlier versions untouched; the estimate is a new appended room version.
    assert len(st2["versions"]["room"]) == len(st["versions"]["room"]) + 1
    assert app.state.db.one("SELECT sha256 FROM source_assets WHERE id=?", (plan_id,))["sha256"] == next(
        s["sha256"] for s in st["sources"] if s["id"] == plan_id)


def test_room_frame_is_stable_across_budget_and_swap(settings):
    c, _, pid, plan_id, st = client_with(settings, [("Bedroom", "11'-0\" x 13'-0\"")])
    st = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": st["room"]["id"], "suggestion_index": 0, "source_id": plan_id}).json()
    frame = {l["envelope_hash"] for l in _layouts(st)}
    assert len(frame) == 1
    st2 = c.put(f"/api/projects/{pid}/preferences", json={**st["preferences"]["data"], "budget_cents": 350000}).json()
    assert {l["envelope_hash"] for l in _layouts(st2)} == frame
    plan = next(p for p in st2["plans"]["data"]["plans"] if p["key"] == "value")
    alt = next((a for a in c.get(f"/api/projects/{pid}/alternatives", params={"plan_key": "value", "category": "dresser"}).json()["alternatives"]
                if a["can_swap"] and not a["current"]), None)
    if alt:
        st3 = c.post(f"/api/projects/{pid}/swap", json={"plan_key": "value", "category": "dresser", "product_id": alt["product_id"],
                                                        "expected_plan_version": st2["plans"]["version"]}).json()
        assert {l["envelope_hash"] for l in _layouts(st3)} == frame and plan["key"] == "value"


def test_two_bedrooms_are_never_chosen_between_automatically(settings):
    c, _, pid, plan_id, st = client_with(settings, [("Bedroom 1", "10'-0\" x 11'-0\""), ("Bedroom 2", "12'-0\" x 13'-6\"")])
    assert st["room"]["data"]["room"]["plan_estimate"] is None and len(st["room"]["data"]["plan_dimension_suggestions"]) == 2
    st2 = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": st["room"]["id"], "suggestion_index": 1, "source_id": plan_id}).json()
    est = st2["room"]["data"]["room"]["plan_estimate"]
    assert est["room_label"] == "Bedroom 2" and est["suggestion_index"] == 1


def test_estimate_requests_are_validated(settings):
    c, app, pid, plan_id, st = client_with(settings, [("Bedroom", "10'-0\" x 12'-0\""), ("Closet", "2'-0\" x 3'-0\"")])
    rv = st["room"]["id"]
    def post(**kw):
        return c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": rv, "suggestion_index": 0, "source_id": plan_id, **kw})
    assert post(suggestion_index=9).status_code == 422
    assert post(source_id="src_not_this_plan").status_code == 422
    assert post(suggestion_index=1).status_code == 422  # 2' x 3' is not a plausible room size
    assert TestClient(app).post(f"/api/projects/{pid}/plan-estimate",
                                json={"room_version_id": rv, "suggestion_index": 0, "source_id": plan_id}).status_code == 404
    assert post().status_code == 200
    stale = post()  # the room version changed: the old id is now stale
    assert stale.status_code == 409


def custom_client(settings, output, n_photos):
    def fn(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(output))])
    c = TestClient(create_app(settings, test_model=FunctionModel(fn)))
    pid = c.post("/api/projects", json={"name": "Mixed", "room_type": "bedroom", "mode": "live"}).json()["project"]["id"]
    if n_photos:
        c.post(f"/api/projects/{pid}/uploads", data={"kind": "photo"},
               files=[("files", (f"p{i}.jpg", make_image(color=(40 * i, 90, 90)), "image/jpeg")) for i in range(n_photos)])
    up = c.post(f"/api/projects/{pid}/uploads", data={"kind": "floorplan"},
                files=[("files", ("plan.png", make_image("PNG", size=(400, 300)), "image/png"))]).json()
    plan_id = next(r["id"] for r in up["results"] if r["ok"])
    return c, pid, plan_id, c.post(f"/api/projects/{pid}/analyze", json={}).json()["state"]


def test_apartment_shape_does_not_block_a_bedroom_but_an_observed_irregular_room_does(settings):
    # Plan only: the model's L-shape describes the whole apartment drawing, not this bedroom.
    c, _, pid, plan_id, st = client_with(settings, [("Bedroom", "10'-0\" x 12'-0\"")], shape="l_shaped")
    r = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": st["room"]["id"], "suggestion_index": 0, "source_id": plan_id})
    assert r.status_code == 200
    lay = _layouts(r.json())[0]
    assert lay["basis"] == "estimated_from_plan" and any("real shape isn’t known" in a for a in lay["assumptions"])
    # Room PHOTOS that show an L-shaped room keep the rectangle refused.
    walls = [{"wall": w, "description": f"wall {w}", "visible": "fully", "photo_indices": [0, 1]} for w in "ABC"]
    out = {"room_type_seen": "bedroom", "shape_guess": "l_shaped",
           "per_photo": [{"photo_index": i, "shows": "room", "appears_same_room_as_others": "yes"} for i in range(2)],
           "floorplan_readings": [{"photo_index": 2, "room_label": "Bedroom", "dimension_text": "10'-0\" x 12'-0\""}],
           "geometry": {"status": "mapped", "reference_wall_a": "window wall", "shape": "l_shaped", "corners_seen": 4, "walls": walls}}
    c2, pid2, plan2, st2 = custom_client(settings, out, 2)
    assert st2["room"]["data"]["room"]["inferred_geometry"]["walls_seen"] == ["A", "B", "C"]
    r2 = c2.post(f"/api/projects/{pid2}/plan-estimate", json={"room_version_id": st2["room"]["id"], "suggestion_index": 0, "source_id": plan2})
    assert r2.status_code == 422 and "irregular" in r2.json()["detail"]


def test_analysis_reads_one_chosen_plan_and_never_redraws_a_stale_estimate(settings):
    c, app, pid, plan_a, st = client_with(settings, [("Bedroom", "10'-0\" x 12'-0\"")])
    st = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": st["room"]["id"], "suggestion_index": 0, "source_id": plan_a}).json()
    up = c.post(f"/api/projects/{pid}/uploads", data={"kind": "floorplan"},
                files=[("files", ("plan-b.png", make_image("PNG", size=(410, 310), color=(5, 5, 200)), "image/png"))]).json()
    plan_b = next(r["id"] for r in up["results"] if r["ok"])
    two = c.post(f"/api/projects/{pid}/analyze", json={})
    assert two.status_code == 422 and "Choose which one" in two.json()["detail"]  # two plans: never combined
    assert c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": "src_not_mine"}).status_code == 422
    other = TestClient(app).post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_b})
    assert other.status_code == 404
    st_b = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_b}).json()["state"]
    assert json.loads(st_b["room"]["source_ids"]) == [plan_b]  # only the chosen plan was read
    assert st_b["room"]["data"]["room"]["plan_estimate"] is None  # plan A's estimate is not drawn under plan B
    assert all(l["basis"] == "unavailable" for l in _layouts(st_b))
    back = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_a}).json()  # same inputs as before: reused
    assert back["reused"] is True and json.loads(back["state"]["room"]["source_ids"]) == [plan_a]  # A is current, not B


def sequenced_client(settings, outputs):
    """Each model call returns the next output, so plan A and plan B read different printed sizes."""
    calls = []
    def fn(messages, info):
        calls.append(1)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(outputs[len(calls) - 1]))])
    app = create_app(settings, test_model=FunctionModel(fn))
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "Two plans", "room_type": "bedroom", "mode": "live"}).json()["project"]["id"]
    return c, app, pid, calls


def add_plan(c, pid, name, color, size=(400, 300)):
    up = c.post(f"/api/projects/{pid}/uploads", data={"kind": "floorplan"},
                files=[("files", (name, make_image("PNG", size=size, color=color), "image/png"))]).json()
    return next(r["id"] for r in up["results"] if r["ok"])


def _readings(st):
    return [(s["dimension_text"], s["source_ids"]) for s in st["room"]["data"]["plan_dimension_suggestions"]]


def test_cached_plan_a_is_restored_after_plan_b_with_its_own_provenance(settings):
    A, B = "10'-0\" x 12'-0\"", "13'-0\" x 15'-0\""
    c, app, pid, calls = sequenced_client(settings, [plan_output([("Bedroom", A)]), plan_output([("Bedroom", B)])])
    plan_a = add_plan(c, pid, "a.png", (200, 200, 200))
    st = c.post(f"/api/projects/{pid}/analyze", json={}).json()["state"]
    st = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": st["room"]["id"], "suggestion_index": 0, "source_id": plan_a}).json()
    # Same plan again while its estimate is current: idempotent, the chosen estimate stays, no new room version.
    n_before = len(st["versions"]["room"])
    again = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_a}).json()
    assert again["reused"] is True and len(again["state"]["versions"]["room"]) == n_before and len(calls) == 1
    assert again["state"]["room"]["id"] == st["room"]["id"] and again["state"]["room"]["data"]["room"]["plan_estimate"]["dimension_text"] == A
    plan_b = add_plan(c, pid, "b.png", (5, 5, 200), size=(410, 310))
    st_b = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_b}).json()["state"]
    assert _readings(st_b) == [(B, [plan_b])] and len(calls) == 2
    # Plan B's estimate, then back to A.
    st_b = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": st_b["room"]["id"], "suggestion_index": 0, "source_id": plan_b}).json()
    history = {v["id"]: v for v in st_b["versions"]["room"]}
    stored = {r["id"]: r["data"] for r in app.state.db.all("SELECT id, data FROM room_versions WHERE project_id=?", (pid,))}
    back = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_a}).json()
    s = back["state"]
    assert back["reused"] is True and len(calls) == 2  # no extra model call
    assert json.loads(s["room"]["source_ids"]) == [plan_a] and _readings(s) == [(A, [plan_a])]
    room = s["room"]["data"]["room"]
    assert room["plan_estimate"] is None and room["scale_status"] == "unknown" and room["width"] is None  # B's estimate not carried
    assert all(plan_b not in c_["source_ids"] for c_ in room["claims"])
    assert s["room"]["data"]["call"]["method"] == "reused" and s["room"]["data"]["call"]["new_ai_call"] is False
    assert all(l["basis"] == "unavailable" for l in _layouts(s))  # room frame: nothing drawn until A's reading is picked
    assert all(p["room_version_id"] == s["room"]["id"] for p in [s["plans"]])  # plans rebuilt on the restored room
    # Prior versions unchanged; the restore is one appended version.
    assert len(s["versions"]["room"]) == len(history) + 1
    assert {r["id"]: r["data"] for r in app.state.db.all("SELECT id, data FROM room_versions WHERE project_id=?", (pid,))
            if r["id"] in stored} == stored
    # The restored A can take its estimate again, and repeating A is then idempotent.
    s2 = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": s["room"]["id"], "suggestion_index": 0, "source_id": plan_a}).json()
    assert [l["envelope_width_in"] for l in _layouts(s2)][0] == 114.0
    rep = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_a}).json()
    assert rep["state"]["room"]["id"] == s2["room"]["id"] and len(calls) == 2


def test_identical_plan_bytes_under_another_source_never_reuse_its_citations(settings):
    out = plan_output([("Bedroom", "10'-0\" x 12'-0\"")])
    c, app, pid, calls = sequenced_client(settings, [out, out])
    import io
    from PIL import Image
    img = Image.new("RGB", (400, 300), (200, 200, 200))
    files = []
    for level in (1, 9):  # same pixels, different original bytes: two sources, identical analysis derivatives
        b = io.BytesIO(); img.save(b, "PNG", compress_level=level); files.append(b.getvalue())
    assert files[0] != files[1]
    ids = []
    for i, data in enumerate(files):
        up = c.post(f"/api/projects/{pid}/uploads", data={"kind": "floorplan"}, files=[("files", (f"p{i}.png", data, "image/png"))]).json()
        ids.append(next(r["id"] for r in up["results"] if r["ok"]))
    shas = [app.state.db.one("SELECT sha256 FROM derivatives WHERE parent_source_id=?", (i,))["sha256"] for i in ids]
    assert ids[0] != ids[1] and shas[0] == shas[1]  # identical analysis input bytes under two source identities
    st1 = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": ids[0]}).json()
    assert st1["reused"] is False and _readings(st1["state"]) == [("10'-0\" x 12'-0\"", [ids[0]])]
    st2 = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": ids[1]}).json()
    # Not a cache hit on the first source: its own analysis, citing its own source.
    assert st2["reused"] is False and len(calls) == 2 and _readings(st2["state"]) == [("10'-0\" x 12'-0\"", [ids[1]])]
    assert json.loads(st2["state"]["room"]["source_ids"]) == [ids[1]]


def test_a_plan_confirmed_size_does_not_follow_into_another_plan_but_a_stated_size_does(settings):
    outs = [plan_output([("Bedroom", "10'-0\" x 12'-0\"")]), plan_output([("Bedroom", "13'-0\" x 15'-0\"")]),
            plan_output([("Bedroom", "13'-0\" x 15'-0\"")])]
    c, _, pid, calls = sequenced_client(settings, outs)
    plan_a = add_plan(c, pid, "a.png", (200, 200, 200))
    c.post(f"/api/projects/{pid}/analyze", json={})
    r = c.post(f"/api/projects/{pid}/scale", json={"basis": "plan_confirmed", "width_in": 120, "depth_in": 144, "source_ids": [plan_a],
                                                  "exact_unit_confirmed": True, "label": "plan A"})
    assert r.status_code == 200 and r.json()["room"]["data"]["room"]["scale_status"] == "plan_dimensions_user_confirmed"
    plan_b = add_plan(c, pid, "b.png", (5, 5, 200), size=(410, 310))
    room_b = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_b}).json()["state"]["room"]["data"]["room"]
    assert room_b["scale_status"] == "unknown" and room_b["width"] is None  # fresh path: plan A's known size isn't carried
    assert not any(cl["kind"] == "verified_constraint" for cl in room_b["claims"])
    back = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_a}).json()["state"]["room"]["data"]["room"]
    assert back["scale_status"] == "unknown" and len(calls) == 2  # cached A from B: B had no known size to carry
    # A size the user states has no plan provenance and carries to whichever plan is read.
    c.post(f"/api/projects/{pid}/scale", json={"basis": "user_stated", "width_in": 130, "depth_in": 150, "source_ids": []})
    room_b2 = c.post(f"/api/projects/{pid}/analyze", json={"floorplan_source_id": plan_b}).json()["state"]["room"]["data"]["room"]
    assert room_b2["scale_status"] == "user_stated" and room_b2["width"]["central"] == 130
    assert [cl["statement"] for cl in room_b2["claims"] if cl["kind"] == "verified_constraint"] == [
        next(cl["statement"] for cl in room_b2["claims"] if cl["kind"] == "verified_constraint")]  # only the current one


def test_reanalysing_the_same_plan_keeps_the_estimate_pointed_at_its_reading(settings):
    c, _, pid, plan_id, st = client_with(settings, [("Bedroom 1", "10'-0\" x 11'-0\""), ("Bedroom 2", "12'-0\" x 13'-6\"")])
    st = c.post(f"/api/projects/{pid}/plan-estimate", json={"room_version_id": st["room"]["id"], "suggestion_index": 1, "source_id": plan_id}).json()
    est = st["room"]["data"]["room"]["plan_estimate"]
    assert est["suggestion_index"] == 1 and est["room_label"] == "Bedroom 2"


def test_unreadable_plan_stays_a_reference(settings):
    c2, _, pid2, _, st2 = client_with(settings, [])  # e.g. a marketing plan with no printed sizes
    assert st2["room"]["data"]["plan_dimension_suggestions"] == [] and st2["room"]["data"]["room"]["plan_estimate"] is None
    for lay in _layouts(st2):
        assert lay["basis"] == "unavailable" and lay["arrangements"] == []  # no fake furniture on an unscaled plan


# ------------------------------------------------------------------ Amazon parser (synthetic page with the observed fields)
def amz_page(asin="B000000001", price_asin=None, prices=("35.99",), dwh='11.8"D x 15.7"W x 23.6"H', width="15.7 inches",
             depth="11.8 inches", package_only=False):
    blocks = "".join(
        f'<div data-csa-c-asin="{price_asin or asin}" data-x="1"><div class="a-section aok-hidden twister-plus-buying-options-price-data">'
        f'{{"desktop_buybox_group_1":[{{"displayPrice":"${p}","priceAmount":{p},"currencySymbol":"$"}}]}}</div></div>' for p in prices)
    rows = (f"<tr><th>Package Dimensions</th><td>{dwh}</td></tr>" if package_only else
            f"<tr><th>Item Dimensions D x W x H</th><td>{dwh}</td></tr><tr><th>Item Width</th><td>{width}</td></tr>"
            f"<tr><th>Item Depth</th><td>{depth}</td></tr>")
    return (f'<input type="hidden" id="ASIN" name="ASIN" value="{asin}"><span id="productTitle" class="t"> Test Nightstand </span>'
            f'{blocks}<div id="availability" class="a"> <span>In Stock</span></div>'
            f"<a id='sellerProfileTriggerId' class='x'>Some Store</a><table>{rows}</table>").encode()


def test_amazon_selected_variant_price_and_product_dimensions():
    u = "https://www.amazon.com/Some-Slug/dp/B000000001/ref=sr_1_2"
    assert adapter_for(u) is amazon
    f = amazon(u, amz_page())
    assert (f.sku.value, f.price_usd.value, f.availability.value) == ("B000000001", "35.99", "InStock")
    assert (f.width_in.value, f.depth_in.value, f.height_in.value) == (15.7, 11.8, 23.6)
    assert any("sold by Some Store" in n for n in f.notes)


def test_amazon_bed_with_length_width_height_row():
    page = amz_page(dwh='80"L x 60"W x 14"H', width="", depth="14 inches")  # Amazon's "Item Depth" is the height here
    f = amazon("https://www.amazon.com/dp/B000000001", page)
    assert (f.width_in.value, f.depth_in.value, f.height_in.value) == (60.0, 80.0, 14.0)


REAL = __import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "catalog_raw"


def test_real_amazon_snapshot_if_present():
    """Root's real fetch (2026-10-26) stored as catalog evidence; raw pages are git-ignored, so a clone skips this."""
    raw = REAL / "28deef20b634a20a4ae6f5e2450fc61e9c04efb9e9cd3b0dc1006cc0aaf99c48.html"
    if not raw.is_file():
        pytest.skip("raw Amazon snapshot not present (git-ignored)")
    f = amazon("https://www.amazon.com/dp/B006MIUM20", raw.read_bytes())
    assert (f.sku.value, f.price_usd.value, f.availability.value) == ("B006MIUM20", "154.55", "InStock")
    assert (f.width_in.value, f.depth_in.value) == (60.0, 80.0) and "Queen" in f.name.value
    assert any("condition: new" in n for n in f.notes) and f.images[0].startswith("https://m.media-amazon.com/images/I/")


def test_shipped_catalog_has_the_verified_amazon_bed():
    from furnishai.catalog import load_catalog
    from furnishai.config import REPO_ROOT
    cat = {p["id"]: p for p in load_catalog(REPO_ROOT / "data" / "catalog" / "products.json")}
    p = cat["amazon-b006mium20"]
    assert (p["price_cents"], p["width_in"], p["depth_in"], p["nominal_size"], p["status"]) == (15455, 60.0, 80.0, "queen", "verified")
    assert p["checked_at"] == "2026-10-26T05:00:13+00:00" and p["source_sha256"].startswith("28deef20")
    assert "buyingOptionType" in p["condition_evidence"] and sum(1 for x in cat.values() if x["retailer"] == "Amazon") == 1


def test_amazon_no_featured_offer_ignores_carousel_prices():
    # Like the real white queen page: no featured offer for the selected ASIN, other products' prices elsewhere.
    page = amz_page(prices=()) + b'<span class="a-offscreen">$72.70</span><div data-csa-c-asin="B0OTHER001">x</div>'
    f = amazon("https://www.amazon.com/dp/B000000001", page)
    assert f.price_usd is None and any("No featured-offer price" in n for n in f.notes)


@pytest.mark.parametrize("kw,expect", [
    (dict(asin="B000000002"), "different variant"),            # link and selected variant differ: nothing used
    (dict(prices=("35.99", "39.99")), "different prices"),     # ambiguous price
    (dict(price_asin="B000000009"), "No featured-offer price"),  # price block belongs to another variant
    (dict(depth="15.7 inches"), "conflicting product dimensions"),
    (dict(package_only=True), "No product dimensions labelled"),  # package size is never a product size
])
def test_amazon_ambiguity_fails_closed(kw, expect):
    f = amazon("https://www.amazon.com/dp/B000000001", amz_page(**kw))
    assert any(expect in n for n in f.notes)
    if "variant" in expect:
        assert f.price_usd is None and f.width_in is None
    if "price" in expect.lower():
        assert f.price_usd is None
    if "dimensions" in expect.lower():
        assert f.width_in is None and f.depth_in is None
