"""Apartments, per-room isolation, layouts through the API, and backward compatibility (DETERMINISTIC)."""

import json

import pytest
from fastapi.testclient import TestClient

from furnishai.app import create_app
from furnishai.db import DB

from conftest import make_image


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def c(app):
    return TestClient(app)


@pytest.mark.parametrize("preset,bedrooms,baths,rooms", [
    ("studio", 0, 1, ["Studio"]), ("1b1b", 1, 1, ["Bedroom 1", "Living area"]),
    ("2b1b", 2, 1, ["Bedroom 1", "Bedroom 2", "Living area"]), ("2b2b", 2, 2, ["Bedroom 1", "Bedroom 2", "Living area"]),
    ("3b2b", 3, 2, ["Bedroom 1", "Bedroom 2", "Bedroom 3", "Living area"]),
])
def test_presets_create_furnished_rooms_and_fixed_spaces(c, preset, bedrooms, baths, rooms):
    a = c.post("/api/apartments", json={"name": "Flat", "preset": preset}).json()
    assert (a["apartment"]["bedrooms"], a["apartment"]["bathrooms"]) == (bedrooms, baths)
    assert [r["label"] for r in a["rooms"]] == rooms
    assert sum(1 for f in a["fixed_spaces"] if f["kind"] == "bathroom") == baths
    assert all(f["kind"] in ("bathroom", "kitchen") for f in a["fixed_spaces"])  # never furnished rooms
    assert all(r["plan_count"] >= 1 and r["has_layouts"] for r in a["rooms"])
    assert any("per room" in n for n in a["notes"]) and any("says nothing about room sizes" in n for n in a["notes"])
    types = {r["room_type"] for r in a["rooms"]}
    assert types == ({"studio"} if bedrooms == 0 else {"bedroom", "living_room"})


@pytest.mark.parametrize("body", [
    {"preset": "custom"}, {"preset": "custom", "bedrooms": 6, "bathrooms": 1}, {"preset": "custom", "bedrooms": 2, "bathrooms": 0},
    {"preset": "2b1b", "bedrooms": 3}, {"preset": "4b3b"}, {"preset": "custom", "bedrooms": -1, "bathrooms": 1},
])
def test_apartment_validation(c, body):
    assert c.post("/api/apartments", json={"name": "x", **body}).status_code == 422


def test_custom_apartment(c):
    a = c.post("/api/apartments", json={"name": "Big", "preset": "custom", "bedrooms": 4, "bathrooms": 3}).json()
    assert len(a["rooms"]) == 5 and a["apartment"]["label"] == "4 bed · 3 bath"


def test_apartment_ownership_isolation(app, c):
    a = c.post("/api/apartments", json={"name": "Mine", "preset": "2b1b"}).json()
    aid, pid = a["apartment"]["id"], a["rooms"][0]["project_id"]
    other = TestClient(app)
    assert other.get(f"/api/apartments/{aid}").status_code == 404
    assert other.delete(f"/api/apartments/{aid}").status_code == 404
    assert other.get("/api/apartments").json() == []
    assert other.get(f"/api/projects/{pid}").status_code == 404
    assert other.post(f"/api/projects/{pid}/layouts").status_code == 404
    assert c.get(f"/api/apartments/{aid}").status_code == 200


def test_rooms_keep_separate_photos_budgets_and_history(c):
    a = c.post("/api/apartments", json={"name": "Two", "preset": "2b1b"}).json()
    b1, b2 = a["rooms"][0]["project_id"], a["rooms"][1]["project_id"]
    c.post(f"/api/projects/{b1}/uploads", data={"kind": "photo"}, files=[("files", ("p.jpg", make_image(), "image/jpeg"))])
    prefs = c.get(f"/api/projects/{b1}").json()["preferences"]["data"]
    prefs["budget_cents"] = 90000
    c.put(f"/api/projects/{b1}/preferences", json=prefs)
    s1, s2 = c.get(f"/api/projects/{b1}").json(), c.get(f"/api/projects/{b2}").json()
    assert len(s1["sources"]) == 1 and s2["sources"] == []
    assert s1["preferences"]["data"]["budget_cents"] == 90000 and s2["preferences"]["data"]["budget_cents"] is None
    assert len(s1["versions"]["plans"]) == 2 and len(s2["versions"]["plans"]) == 1
    assert s1["apartment"]["label"] == "Bedroom 1" and s2["apartment"]["label"] == "Bedroom 2"
    overview = c.get(f"/api/apartments/{a['apartment']['id']}").json()
    assert [r["budget_cents"] for r in overview["rooms"]] == [90000, None, None]  # never summed or spread


def test_living_room_flow_without_photos_has_shortlist_but_no_fake_room(c):
    s = c.post("/api/projects", json={"name": "Lounge", "room_type": "living_room"}).json()
    assert s["project"]["room_type"] == "living_room"
    plans = s["plans"]["data"]["plans"]
    cats = {i["category"] for i in plans[0]["items"]}
    assert "coffee_table" in cats and not any(i["category"] == "bed_frame" for i in plans[0]["items"])
    for p in plans:  # shopping shortlist exists; no outline or arrangement is invented
        assert p["layouts"]["basis"] == "unavailable" and p["layouts"]["arrangements"] == []
        assert p["layouts"]["missing_views"]


def test_new_apartment_rooms_are_not_mapped_until_photos(c):
    a = c.post("/api/apartments", json={"name": "Flat", "preset": "2b1b"}).json()
    assert all(not r["mapped"] for r in a["rooms"])


def test_demo_uses_fixed_synthetic_geometry_never_trusted(c):
    s = c.post("/api/demo", json={"room_type": "bedroom"}).json()
    lay = s["plans"]["data"]["plans"][0]["layouts"]
    assert lay["basis"] == "synthetic_demo" and (lay["envelope_width_in"], lay["envelope_depth_in"]) == (126, 132)
    assert "Synthetic demo room" in lay["envelope_label"]
    room = s["room"]["data"]["room"]
    assert room["scale_status"] == "unknown" and room["width"] is None and room["inferred_geometry"]["synthetic"]
    assert lay["room_version_id"] == s["room"]["id"] == s["plans"]["room_version_id"]


def test_geometry_frozen_across_preference_edits_and_only_new_room_versions_change_it(c):
    s = c.post("/api/demo", json={"room_type": "studio"}).json()
    pid = s["project"]["id"]

    def frames(state):
        return {(p["layouts"]["envelope_hash"], p["layouts"]["envelope_width_in"], p["layouts"]["envelope_depth_in"],
                 json.dumps(p["layouts"]["fixed_zones"], sort_keys=True)) for p in state["plans"]["data"]["plans"]}

    first = frames(s)
    assert len(first) == 1  # identical frame for every shopping plan
    prefs = s["preferences"]["data"]
    for change in ({"budget_cents": 400000}, {"styles": ["dark"]}, {"categories": ["sofa_bed", "desk", "bookcase", "wardrobe"]}):
        st = c.put(f"/api/projects/{pid}/preferences", json={**prefs, **change}).json()
        assert frames(st) == first and len(st["versions"]["room"]) == 1
    st = c.post(f"/api/projects/{pid}/edit", json={"message": "budget $3000 and switch the style to modern"}).json()["state"]
    assert frames(st) == first
    st = c.post(f"/api/projects/{pid}/layouts").json()
    assert frames(st) == first
    sug = s["room"]["data"]["plan_dimension_suggestions"][0]
    st = c.post(f"/api/projects/{pid}/scale", json={"width_in": sug["width_in"], "depth_in": sug["depth_in"],
                                                     "basis": "plan_confirmed", "source_ids": sug["source_ids"],
                                                     "exact_unit_confirmed": True}).json()
    assert len(st["versions"]["room"]) == 2 and frames(st) != first  # new evidence -> new room version -> new frame
    assert st["versions"]["room"][0]["summary"].startswith("Scale set")
    lay = st["plans"]["data"]["plans"][0]["layouts"]
    assert lay["basis"] == "scaled_room_lower_bound" and lay["envelope_width_in"] == 159
    st = c.post(f"/api/projects/{pid}/edit", json={"message": "budget $100"}).json()["state"]
    assert st["plans"]["data"]["plans"] == []  # infeasible budget: no plans, but the mapped room is still shown
    room_only = st["plans"]["data"]["room_layout"]
    assert room_only["envelope_hash"] == lay["envelope_hash"] and room_only["arrangements"][0]["placements"] == []


def test_zero_purchase_reuse_plan_arranges_owned_furniture(c, app):
    s = c.post("/api/demo", json={"room_type": "bedroom"}).json()
    pid = s["project"]["id"]
    prefs = s["preferences"]["data"]
    prefs.update(categories=[], existing_items=[
        {"id": "own1", "category": "bed_frame", "description": "my bed", "keep": True, "width_in": 60, "depth_in": 80},
        {"id": "own2", "category": "dresser", "description": "my dresser", "keep": True, "width_in": 36, "depth_in": 18}])
    st = c.put(f"/api/projects/{pid}/preferences", json=prefs).json()
    plans = st["plans"]["data"]["plans"]
    assert len(plans) == 1 and plans[0]["subtotal_cents"] == 0 and plans[0]["title"].startswith("Reuse")
    arr = plans[0]["layouts"]["arrangements"][0]
    assert {p["ref"] for p in arr["placements"]} == {"own1", "own2"} and all(p["kind"] == "existing" for p in arr["placements"])


def test_mocked_analysis_with_geometry_maps_room_and_old_analysis_asks_for_reanalysis(settings):
    from pydantic_ai.models.test import TestModel
    analysis = {
        "room_type_seen": "bedroom",
        "per_photo": [{"photo_index": 0, "shows": "window wall", "appears_same_room_as_others": "yes"},
                      {"photo_index": 1, "shows": "door wall", "appears_same_room_as_others": "yes"}],
        "geometry": {"status": "mapped", "reference_wall_a": "window wall", "shape": "rectangular", "corners_seen": 3,
                     "walls": [{"wall": "A", "description": "window wall", "visible": "fully", "photo_indices": [0]},
                               {"wall": "B", "description": "bed wall", "visible": "partly", "photo_indices": [0, 1]},
                               {"wall": "C", "description": "door wall", "visible": "fully", "photo_indices": [1],
                                "features": [{"kind": "door", "start_frac": 0.1, "end_frac": 0.3, "photo_indices": [1]}]}],
                     "scale": {"wall_a_length_in_low": 120, "wall_a_length_in_high": 150, "wall_b_length_in_low": 130,
                               "wall_b_length_in_high": 160, "reasoning": "door",
                               "cues": [{"description": "door", "photo_index": 1}]}},
    }
    app = create_app(settings, test_model=TestModel(custom_output_args=analysis))
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "B", "room_type": "bedroom"}).json()["project"]["id"]
    c.post(f"/api/projects/{pid}/uploads", data={"kind": "photo"},
           files=[("files", ("a.jpg", make_image(), "image/jpeg")), ("files", ("b.jpg", make_image(color=(1, 2, 3)), "image/jpeg"))])
    st = c.post(f"/api/projects/{pid}/analyze", json={}).json()["state"]
    lay = st["plans"]["data"]["plans"][0]["layouts"]
    assert lay["basis"] == "estimated_from_photos" and lay["envelope_width_in"] == 120
    assert any("door" in z["label"] for z in lay["fixed_zones"])
    assert len(lay["geometry_source_ids"]) == 2 and st["room"]["data"]["room"]["width"] is None
    # An analysis stored before photo mapping (no inferred_geometry) is not upgraded; it asks for re-analysis.
    old = dict(st["room"]["data"])
    old["room"] = {k: v for k, v in old["room"].items() if k != "inferred_geometry"}
    app.state.db.add_room_version(pid, old, [], "live_ai", "gpt-6-luna", "room-evidence-v1", None, "legacy")
    st2 = c.post(f"/api/projects/{pid}/plans").json()
    lay2 = st2["plans"]["data"]["plans"][0]["layouts"]
    assert lay2["basis"] == "unavailable" and "Re-analyze" in lay2["notes"][0]


def test_scaled_layout_links_floorplan_source_without_claiming_to_be_it(c):
    s = c.post("/api/demo", json={"room_type": "studio"}).json()
    pid = s["project"]["id"]
    sug = s["room"]["data"]["plan_dimension_suggestions"][0]
    s2 = c.post(f"/api/projects/{pid}/scale", json={"width_in": sug["width_in"], "depth_in": sug["depth_in"],
                                                     "basis": "plan_confirmed", "source_ids": sug["source_ids"],
                                                     "exact_unit_confirmed": True}).json()
    lay = s2["plans"]["data"]["plans"][0]["layouts"]
    assert lay["basis"] == "scaled_room_lower_bound" and lay["envelope_width_in"] == 159
    assert lay["floorplan_source_ids"] == sug["source_ids"]
    assert all(p["fit_summary"] != "Fits tested assumptions" for p in s2["plans"]["data"]["plans"])


def test_old_plan_without_layouts_opens_and_regenerates_without_ai(app, c):
    s = c.post("/api/demo", json={"room_type": "bedroom"}).json()
    pid = s["project"]["id"]
    head = app.state.db.head("plan_versions", pid)
    legacy = dict(head["data"])
    legacy["plans"] = [{k: v for k, v in p.items() if k != "layouts"} for p in legacy["plans"]]
    old = app.state.db.add_plan_version(pid, legacy, head["room_version_id"], head["preference_version_id"],
                                        json.loads(head["product_refs"]), "legacy (pre layout-v1)")
    got = c.get(f"/api/projects/{pid}").json()
    assert got["plans"]["id"] == old["id"] and all("layouts" not in p for p in got["plans"]["data"]["plans"])
    r = c.post(f"/api/projects/{pid}/layouts").json()
    assert r["plans"]["version"] == old["version"] + 1
    assert r["plans"]["preference_version_id"] == head["preference_version_id"]
    assert r["plans"]["room_version_id"] == head["room_version_id"]
    assert [i["product_id"] for i in r["plans"]["data"]["plans"][0]["items"]] == \
           [i["product_id"] for i in legacy["plans"][0]["items"]]  # products unchanged
    assert all(p["layouts"]["arrangements"] for p in r["plans"]["data"]["plans"])
    assert app.state.db.version_by_id("plan_versions", pid, old["id"])["data"] == legacy  # history untouched
    assert "Furniture arrangements" in c.get(f"/api/projects/{pid}/export").json()["markdown"] or \
           "Arrangements" in c.get(f"/api/projects/{pid}/export").json()["markdown"]


def test_schema_upgrade_keeps_existing_rows_and_sources(settings):
    first = create_app(settings)
    c1 = TestClient(first)
    s = c1.post("/api/demo", json={"room_type": "studio"}).json()
    pid = s["project"]["id"]
    before = first.state.db.all("SELECT * FROM source_assets WHERE project_id=?", (pid,))
    files = {r["storage_path"]: open(r["storage_path"], "rb").read() for r in before}
    db = DB(settings.storage_dir / "furnishai.sqlite3")  # schema script runs again on an existing database
    second = create_app(settings)
    assert db.one("SELECT COUNT(*) n FROM apartments")["n"] == 0
    assert second.state.db.all("SELECT * FROM source_assets WHERE project_id=?", (pid,)) == before
    assert all(open(p, "rb").read() == b for p, b in files.items())
    assert len(second.state.db.versions("plan_versions", pid)) == 1


def test_delete_apartment_removes_its_rooms_only(c):
    keep = c.post("/api/projects", json={"name": "Solo", "room_type": "bedroom"}).json()["project"]["id"]
    a = c.post("/api/apartments", json={"name": "Gone", "preset": "1b1b"}).json()
    room_ids = [r["project_id"] for r in a["rooms"]]
    assert c.delete(f"/api/apartments/{a['apartment']['id']}").status_code == 200
    assert all(c.get(f"/api/projects/{r}").status_code == 404 for r in room_ids)
    assert c.get(f"/api/projects/{keep}").status_code == 200


def test_project_list_marks_apartment_rooms(c):
    a = c.post("/api/apartments", json={"name": "Flat", "preset": "studio"}).json()
    rows = c.get("/api/projects").json()
    room = next(r for r in rows if r["id"] == a["rooms"][0]["project_id"])
    assert room["apartment_id"] == a["apartment"]["id"] and room["apartment_room_label"] == "Studio"
