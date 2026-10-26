"""Furniture arrangements inside a fixed room (DETERMINISTIC)."""

from furnishai.layout import generate_layouts, room_frame, verify
from furnishai.models import (
    Bound, FeatureEstimate, InferredGeometry, Plan, PlanItem, Preferences, RoomFeature, RoomModel,
)


def item(pid, cat, w, d, **kw):
    return PlanItem(category=cat, product_id=pid, name=f"{pid} {cat}", price_cents=1000, width_in=w, depth_in=d, **kw)


def plan(items):
    return Plan(key="value", title="Value: t", items=items, subtotal_cents=0, reserve_cents=0, item_budget_cents=None,
                budget_cents=None, budget_status="no_budget_set", fit_summary="Fit unverified")


def b(lo, hi, label="t"):
    return Bound(lower=lo, central=(lo + hi) / 2, upper=hi, method=label, strength="weak")


def estimated(w=(130, 150), d=(140, 160), features=(), room_type="bedroom", shape="rectangular", synthetic=False):
    geo = InferredGeometry(drawable=True, reason="test", shape=shape, width=b(*w), depth=b(*d), features=list(features),
                           source_ids=["src_1", "src_2"], wall_descriptions={"A": "window wall"}, synthetic=synthetic)
    return RoomModel(room_type=room_type, method="mocked_ai", inferred_geometry=geo)


def scaled(w, d, room_type="bedroom", features=(), shape="rectangular", t=2):
    return RoomModel(room_type=room_type, scale_status="user_stated", width=b(w - t, w + t), depth=b(d - t, d + t),
                     method="manual", shape=shape, features=list(features))


P = Preferences()


def lay(items, room, prefs=P, catalog=None, rv="room_1"):
    return generate_layouts(plan(items), catalog or {}, prefs, room_frame(room, rv))


def dims(p):
    return sorted([round(p.w, 2), round(p.d, 2)])


BEDROOM = [item("bed", "bed_frame", 63, 83.125), item("mat", "mattress", 59.875, 79.5),
           item("ns", "nightstand", 18.875, 15.375), item("dr", "dresser", 30.75, 18.125)]


# ------------------------------------------------------------------ evidence gating
def test_no_room_evidence_means_no_outline_and_photo_guidance():
    for room in (None, RoomModel(room_type="bedroom", method="fixture")):
        L = lay(BEDROOM, room)
        assert L.basis == "unavailable" and L.arrangements == [] and L.envelope_width_in == 0
        assert L.missing_views and any("corner" in v for v in L.missing_views)


def test_analysis_from_before_photo_mapping_asks_for_reanalysis():
    old = RoomModel(room_type="bedroom", method="live_ai", prompt_version="room-evidence-v1")
    L = lay(BEDROOM, old)
    assert L.basis == "unavailable" and "Re-analyze" in L.notes[0]


def test_non_drawable_geometry_is_not_replaced_by_a_rectangle():
    geo = InferredGeometry(drawable=False, reason="Only 2 of 4 walls are visible", missing_views=["Add a photo showing wall C."])
    L = lay(BEDROOM, RoomModel(room_type="bedroom", method="mocked_ai", inferred_geometry=geo))
    assert L.basis == "unavailable" and L.missing_views == ["Add a photo showing wall C."]


def test_irregular_rooms_are_not_drawn_as_rectangles():
    for room in (estimated(shape="l_shaped"), scaled(150, 150, shape="l_shaped")):
        assert lay(BEDROOM, room).basis == "unavailable"


# ------------------------------------------------------------------ fixed room
def test_estimated_outline_is_fixed_and_labeled_with_separate_ranges():
    room = estimated(w=(130, 150), d=(140, 170))
    L = lay(BEDROOM, room)
    assert L.basis == "estimated_from_photos" and (L.envelope_width_in, L.envelope_depth_in) == (130, 140)
    assert L.width_range_in == [130, 150] and L.depth_range_in == [140, 170]
    assert "Estimated from your photos · dimensions unverified" in L.envelope_label
    assert L.geometry_source_ids == ["src_1", "src_2"] and L.room_version_id == "room_1"
    assert room.width is None and room.scale_status == "unknown"  # hypothesis never becomes trusted


def test_frame_identical_across_plans_products_and_strategies():
    room = estimated(features=[FeatureEstimate(kind="door", wall="C", start_frac=0.1, end_frac=0.3)])
    a = lay(BEDROOM, room)
    small = lay([item("ns", "nightstand", 15, 15)], room)
    huge = lay([item(f"w{i}", "wardrobe", 41, 22) for i in range(12)], room, Preferences(budget_cents=1))
    for L in (a, small, huge):
        assert (L.envelope_width_in, L.envelope_depth_in, L.envelope_hash) == (a.envelope_width_in, a.envelope_depth_in, a.envelope_hash)
        assert [z.model_dump() for z in L.fixed_zones] == [z.model_dump() for z in a.fixed_zones]
    other_version = generate_layouts(plan(BEDROOM), {}, P, room_frame(room, "room_2"))
    assert other_version.envelope_hash != a.envelope_hash  # hash is tied to the room version


def test_arrangements_valid_real_proportions_rotations_and_mattress():
    L = lay(BEDROOM, estimated())
    assert 2 <= len(L.arrangements) <= 3 and len({x.signature for x in L.arrangements}) == len(L.arrangements)
    want = {"bed": [63, 83.12], "ns": [15.38, 18.88], "dr": [18.12, 30.75]}
    for a in L.arrangements:
        assert verify(a.placements, L.envelope_width_in, L.envelope_depth_in, L.fixed_zones) == []
        assert {p.ref for p in a.placements} == set(want)
        assert all(dims(p) == sorted(want[p.ref]) for p in a.placements)
        assert all(p.wall in ("A", "B", "C", "D", "free") for p in a.placements)
        assert [(x.ref, x.on_ref) for x in a.associated] == [("mat", "bed")]
    walls = {a.key: next(p.wall for p in a.placements if p.ref == "bed") for a in L.arrangements}
    assert walls["alternate_wall"] != walls["open_center"]


def test_oversized_items_are_unplaced_and_room_is_never_resized():
    room = estimated(w=(60, 70), d=(60, 70))
    L = lay([item("bed", "bed_frame", 63, 83), item("ns", "nightstand", 15, 15)], room)
    assert (L.envelope_width_in, L.envelope_depth_in) == (60, 60)
    for a in L.arrangements:
        assert "Larger than the room outline" in next(u for u in a.unplaced if u.ref == "bed").reason


def test_crowded_room_lists_items_it_cannot_place():
    L = lay([item(f"w{i}", "wardrobe", 41, 22) for i in range(10)], scaled(100, 100))
    a = L.arrangements[0]
    assert a.unplaced and len(a.placements) + len(a.unplaced) == 10
    assert verify(a.placements, L.envelope_width_in, L.envelope_depth_in, L.fixed_zones) == []


def test_identical_strategies_are_deduplicated():
    L = lay([item("dr", "dresser", 41, 11)], scaled(42, 42, t=1))
    assert len({a.signature for a in L.arrangements}) == len(L.arrangements) < 3
    assert any("identical ones were merged" in n for n in L.notes)


def test_queen_headboard_on_wall():
    L = lay([item("q", "bed_frame", 63, 83)], estimated())
    for a in L.arrangements:
        p = a.placements[0]
        assert (p.w if p.wall in ("A", "C") else p.d) == 63


# ------------------------------------------------------------------ fixed features
def test_known_column_radiator_and_bathroom_door_block_furniture():
    feats = [FeatureEstimate(kind="column", wall="A", start_frac=0.4, end_frac=0.6, depth_in=20),
             FeatureEstimate(kind="radiator", wall="B", start_frac=0.2, end_frac=0.8),
             FeatureEstimate(kind="bathroom_door", wall="C", start_frac=0.1, end_frac=0.3)]
    L = lay(BEDROOM + [item("sb", "sofa_bed", 80, 35)], estimated(w=(160, 180), d=(170, 190), features=feats))
    labels = {z.label for z in L.fixed_zones}
    assert {"column", "radiator", "bathroom door keep-clear"} <= labels
    rad = next(z for z in L.fixed_zones if z.label == "radiator")
    assert rad.w == 8 and "assumed 8 in depth" in rad.assumption
    for a in L.arrangements:
        assert verify(a.placements, L.envelope_width_in, L.envelope_depth_in, L.fixed_zones) == []
        assert any("column" in c for c in a.checks_passed)


def test_kitchen_uses_located_extent_not_whole_wall():
    room = estimated(w=(150, 170), d=(190, 210), room_type="studio",
                     features=[FeatureEstimate(kind="kitchen", wall="A", start_frac=0.0, end_frac=0.4, depth_in=26)])
    L = lay([item("dk", "desk", 43, 15)], room)
    k = next(z for z in L.fixed_zones if z.label == "kitchen counters")
    assert k.d == 26 and k.w < 0.55 * L.envelope_width_in  # 40% + uncertainty, not the whole wall


def test_unlocated_features_are_reported_not_assumed():
    room = estimated(room_type="studio")
    room.features.append(RoomFeature(id="k", kind="kitchen", wall="north"))
    L = lay([item("dk", "desk", 43, 15)], room)
    assert not any("kitchen" in z.label for z in L.fixed_zones)  # no invented full-wall kitchen
    assert any("Kitchen seen in the photos but not located" in u for u in L.arrangements[0].unresolved)
    assert any("door swing" in u for u in L.arrangements[0].unresolved)


def test_stored_bathroom_footprint_blocks_furniture():
    """Root's regression: 180x200 room, bathroom on wall A at offset 0, 90 wide x 90 deep; a 64x84 bed must not enter it."""
    room = scaled(180, 200, t=0.5, features=[RoomFeature(id="b", kind="bathroom", wall="north", offset_in=0, width_in=90, depth_in=90)])
    L = lay([item("bed", "bed_frame", 64, 84), item("dr", "dresser", 30, 18)], room)
    bath = next(z for z in L.fixed_zones if z.label == "bathroom")
    assert (bath.x, bath.y, bath.w, bath.d) == (0, 0, 90, 90) and "stored depth" in bath.assumption
    for a in L.arrangements:
        assert verify(a.placements, L.envelope_width_in, L.envelope_depth_in, L.fixed_zones) == []
        for p in a.placements:
            assert not (p.x < 90 and p.y < 90)  # nothing inside the bathroom footprint


def test_stored_column_and_kitchen_use_stored_dimensions():
    feats = [RoomFeature(id="c", kind="column", wall="east", offset_in=40, width_in=18, depth_in=18),
             RoomFeature(id="k", kind="kitchen", wall="north", offset_in=0, width_in=96, depth_in=25)]
    L = lay(BEDROOM, scaled(160, 190, room_type="studio", t=0.5, features=feats))
    col = next(z for z in L.fixed_zones if z.label == "column")
    kit = next(z for z in L.fixed_zones if z.label == "kitchen counters")
    assert (col.w, col.d) == (18, 18) and col.x == L.envelope_width_in - 18
    assert (kit.w, kit.d) == (96, 25) and any(z.label == "kitchen work aisle" for z in L.fixed_zones)
    for a in L.arrangements:
        assert verify(a.placements, L.envelope_width_in, L.envelope_depth_in, L.fixed_zones) == []


def test_invalid_stored_geometry_is_flagged_not_ignored():
    feats = [RoomFeature(id="x", kind="column", wall="north", offset_in=500, width_in=10, depth_in=10),
             RoomFeature(id="y", kind="bathroom", wall="south", offset_in=10, width_in=60),  # no depth
             RoomFeature(id="z", kind="radiator", wall="west", offset_in=150, width_in=80)]  # runs past the corner
    L = lay(BEDROOM, scaled(160, 190, t=0.5, features=feats))
    u = " ".join(L.arrangements[0].unresolved)
    assert "starts beyond the wall's length" in u and "has no depth" in u and "clamped to the wall" in u
    assert not any(z.label == "bathroom" for z in L.fixed_zones)
    rad = next(z for z in L.fixed_zones if z.label == "radiator")
    assert rad.y + rad.d <= L.envelope_depth_in + 0.01


def test_stored_position_takes_precedence_over_photo_estimate():
    room = estimated(w=(160, 180), d=(170, 190), features=[FeatureEstimate(kind="column", wall="A", start_frac=0.4, end_frac=0.6, depth_in=20)])
    room.features.append(RoomFeature(id="c", kind="column", wall="north", offset_in=10, width_in=12, depth_in=12))
    L = lay(BEDROOM, room)
    cols = [z for z in L.fixed_zones if z.label == "column"]
    assert len(cols) == 1 and (cols[0].x, cols[0].w) == (10, 12)
    assert any("Stored exact positions used instead" in a for a in L.assumptions)


def test_photo_windows_are_drawn_as_markers_not_obstacles():
    room = estimated(w=(150, 150.5), d=(160, 161), features=[FeatureEstimate(kind="window", wall="A", start_frac=0.25, end_frac=0.75, source_ids=["src_1"])])
    L = lay(BEDROOM, room)
    (m,) = L.wall_markers
    assert (m.kind, m.wall, m.x1, m.y1, m.x2, m.y2) == ("window", "A", 37.5, 0, 112.5, 0)
    assert "estimated" in m.caveat and not any("window" in z.label for z in L.fixed_zones)
    assert lay(BEDROOM, None).wall_markers == []  # nothing drawn for an unmapped room


# ------------------------------------------------------------------ truthful clearances and opened beds
def test_access_zone_claim_is_true_including_coffee_table_and_nightstand():
    items = [item("sb", "sofa_bed", 81, 34), item("ct", "coffee_table", 46, 30), item("bed", "bed_frame", 41, 79),
             item("ns", "nightstand", 18, 15)]
    L = lay(items, estimated(w=(170, 190), d=(180, 200)))
    for a in L.arrangements:
        assert any("access zone" in c for c in a.checks_passed)
        assert verify(a.placements, L.envelope_width_in, L.envelope_depth_in, L.fixed_zones) == []


def test_verify_catches_access_zone_intrusion():
    L = lay([item("dr", "dresser", 30, 18)], estimated())
    p = L.arrangements[0].placements[0].model_copy()
    c = p.clearances[0]
    intruder = p.model_copy(update={"ref": "x", "x": c[0], "y": c[1], "w": 10, "d": 10, "clearances": []})
    assert any("access zone" in m for m in verify([p, intruder], L.envelope_width_in, L.envelope_depth_in, []))


def test_opened_sofa_bed_never_claims_clear_when_it_hits_a_door():
    """Root's reproduction: 160x100 room, sofa 80x40 opening to 90, door on wall C at offset 0, width 36."""
    room = scaled(160, 100, t=0.5, features=[RoomFeature(id="d", kind="door", wall="south", offset_in=0, width_in=36)])
    cat = {"sb": {"open_depth_bounds_in": {"along_wall": 80, "lower": 40, "upper": 90}}}
    L = lay([item("sb", "sofa_bed", 80, 40)], room, catalog=cat)
    door = next(z for z in L.fixed_zones if "door" in z.label)
    for a in L.arrangements:
        p = a.placements[0]
        o = p.open_extent
        hits = o[0] < door.x + door.w and door.x < o[0] + o[2] and o[1] < door.y + door.d and door.y < o[1] + o[3]
        claimed = any("stays clear" in c for c in a.checks_passed)
        assert not (hits and claimed)
        if hits:
            assert any("would hit" in u for u in a.unresolved)


def test_opened_sofa_bed_with_coffee_table_is_conditional():
    cat = {"sb": {"open_depth_bounds_in": {"along_wall": 81, "lower": 34, "upper": 90}}}
    L = lay([item("sb", "sofa_bed", 81, 34), item("ct", "coffee_table", 46, 30)], estimated(w=(170, 190), d=(180, 200)), catalog=cat)
    a = L.arrangements[0]
    assert not any("stays clear" in c for c in a.checks_passed)
    assert any("only if the" in u and "moved" in u for u in a.unresolved)


def test_opened_extent_uses_documented_along_wall_length():
    cat = {"sb": {"open_depth_bounds_in": {"along_wall": 92, "lower": 34, "upper": 70}}}
    L = lay([item("sb", "sofa_bed", 81, 34)], estimated(w=(170, 190), d=(180, 200)), catalog=cat)
    o = L.arrangements[0].placements[0].open_extent
    assert max(o[2], o[3]) == 92  # not narrowed to the closed width


def test_kept_sofa_bed_without_open_size_is_unverified():
    pl = [PlanItem(category="sofa_bed", existing_item_id="e1", name="Your sofa bed (kept)", price_cents=0, width_in=80, depth_in=36)]
    L = generate_layouts(plan(pl), {}, P, room_frame(estimated()))
    assert any("open extent is unverified" in u for u in L.arrangements[0].unresolved)


# ------------------------------------------------------------------ other items
def test_unknown_size_kept_item_listed_and_known_size_placed():
    pl = [PlanItem(category="desk", existing_item_id="e1", name="Your old desk (kept)", price_cents=0),
          PlanItem(category="dresser", existing_item_id="e2", name="Your dresser (kept)", price_cents=0, width_in=40, depth_in=20)]
    L = generate_layouts(plan(pl), {}, P, room_frame(estimated()))
    a = L.arrangements[0]
    assert "Size unknown" in next(u for u in a.unplaced if u.ref == "e1").reason
    assert a.placements[0].ref == "e2" and a.placements[0].kind == "existing"


def test_shared_bed_gets_both_side_access_zones():
    L = lay([item("q", "bed_frame", 63, 83)], estimated(), Preferences(shared_use=True))
    assert all(len(a.placements[0].clearances) == 2 for a in L.arrangements)


def test_trusted_size_labels_width_and_length_separately():
    room = RoomModel(room_type="bedroom", scale_status="user_stated", width=b(118, 126), depth=b(140, 160), method="manual")
    L = lay(BEDROOM, room)
    assert L.basis == "scaled_room_lower_bound" and L.width_range_in == [118, 126] and L.depth_range_in == [140, 160]
    assert "width up to 10′6″" in L.envelope_label and "length up to 13′4″" in L.envelope_label
    assert any("Rectangular outline assumed" in a for a in L.assumptions)
