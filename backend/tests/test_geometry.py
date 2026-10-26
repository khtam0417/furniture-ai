"""Photo-geometry gate: drawable outlines need real overlapping evidence; otherwise abstain with guidance."""

from furnishai import ai
from furnishai.geometry import assess_geometry
from furnishai.models import (
    AIGeometry, AIPhotoNote, AIScaleCue, AIScaleEstimate, AIWall, AIWallFeature, PhotoAnalysisOutput, RoomModel,
)

IDS = ["src_a", "src_b", "src_c"]


def geo(**kw):
    base = dict(
        status="mapped", reference_wall_a="wall with two windows", shape="rectangular", corners_seen=3,
        walls=[AIWall(wall="A", description="window wall", visible="fully", photo_indices=[0],
                      features=[AIWallFeature(kind="window", start_frac=0.2, end_frac=0.5, photo_indices=[0]),
                                AIWallFeature(kind="door", start_frac=0.7, end_frac=0.6)]),  # invalid order: dropped
               AIWall(wall="B", description="bed wall", visible="partly", photo_indices=[0, 1]),
               AIWall(wall="C", description="door wall", visible="fully", photo_indices=[1]),
               AIWall(wall="D", description="unseen", visible="not_seen")],
        scale=AIScaleEstimate(wall_a_length_in_low=120, wall_a_length_in_high=150, wall_b_length_in_low=130,
                              wall_b_length_in_high=160, reasoning="door and queen bed",
                              cues=[AIScaleCue(description="door", photo_index=1)]),
    )
    base.update(kw)
    return AIGeometry(**base)


def out(g, notes=()):
    return PhotoAnalysisOutput(room_type_seen="bedroom", geometry=g, per_photo=list(notes))


def test_valid_overlapping_evidence_gives_weak_unverified_outline():
    g = assess_geometry(out(geo()), IDS)
    assert g.drawable and g.walls_seen == ["A", "B", "C"] and g.source_ids == ["src_a", "src_b"]
    assert (g.width.lower, g.width.upper, g.depth.lower, g.depth.upper) == (120, 150, 130, 160)
    assert g.width.strength == "weak" and "unverified" in g.width.method
    assert [f.kind for f in g.features] == ["window"]  # malformed feature dropped
    assert any("wall D" in v for v in g.missing_views)


def test_abstention_and_missing_walls_give_specific_guidance():
    g = assess_geometry(out(geo(status="insufficient", missing_views=["Photo of the closet wall from the window"])), IDS)
    assert not g.drawable and "Photo of the closet wall from the window" in g.missing_views
    two = geo(walls=[AIWall(wall="A", description="window wall", visible="fully", photo_indices=[0]),
                     AIWall(wall="B", description="bed wall", visible="partly", photo_indices=[1]),
                     AIWall(wall="C", description="closet wall", visible="not_seen")])
    g2 = assess_geometry(out(two), IDS)
    assert not g2.drawable and any("wall C (closet wall)" in v for v in g2.missing_views)


def test_single_photo_or_too_few_corners_is_not_enough():
    one = geo(walls=[AIWall(wall=w, description=w, visible="partly", photo_indices=[0]) for w in "ABC"])
    assert not assess_geometry(out(one), IDS).drawable
    assert not assess_geometry(out(geo(corners_seen=1)), IDS).drawable


def test_different_room_photo_is_excluded():
    notes = [AIPhotoNote(photo_index=1, shows="a different bedroom", appears_same_room_as_others="no")]
    g = assess_geometry(out(geo(), notes), IDS)
    assert not g.drawable and "different room" in g.missing_views[0]


def test_implausible_or_uncued_scale_abstains():
    wide = geo(scale=AIScaleEstimate(wall_a_length_in_low=80, wall_a_length_in_high=200, wall_b_length_in_low=130,
                                     wall_b_length_in_high=160, reasoning="?", cues=[AIScaleCue(description="door", photo_index=1)]))
    nocue = geo(scale=AIScaleEstimate(wall_a_length_in_low=120, wall_a_length_in_high=150, wall_b_length_in_low=130,
                                      wall_b_length_in_high=160, reasoning="?", cues=[]))
    for g in (wide, nocue, geo(scale=None)):
        r = assess_geometry(out(g), IDS)
        assert not r.drawable and r.width is None and any("fully visible" in v for v in r.missing_views)


def test_reference_wall_must_be_described_and_visible():
    assert not assess_geometry(out(geo(reference_wall_a="  ")), IDS).drawable
    hidden_a = geo(walls=[AIWall(wall="A", description="window wall", visible="not_seen"),
                          AIWall(wall="B", description="b", visible="fully", photo_indices=[0]),
                          AIWall(wall="C", description="c", visible="fully", photo_indices=[1]),
                          AIWall(wall="D", description="d", visible="partly", photo_indices=[0, 1])])
    r = assess_geometry(out(hidden_a), IDS)
    assert not r.drawable and "wall A" in r.reason


def test_model_contradictions_block_mapping():
    o = out(geo())
    o.contradictions = ["Photo 1 shows carpet, photo 2 shows hardwood"]
    r = assess_geometry(o, IDS)
    assert not r.drawable and "conflicting evidence" in r.reason


def test_scale_needs_described_cue_and_reasoning():
    blank_cue = geo(scale=AIScaleEstimate(wall_a_length_in_low=120, wall_a_length_in_high=150, wall_b_length_in_low=130,
                                          wall_b_length_in_high=160, reasoning="door", cues=[AIScaleCue(description=" ", photo_index=1)]))
    no_reason = geo(scale=AIScaleEstimate(wall_a_length_in_low=120, wall_a_length_in_high=150, wall_b_length_in_low=130,
                                          wall_b_length_in_high=160, reasoning="", cues=[AIScaleCue(description="door", photo_index=1)]))
    assert not assess_geometry(out(blank_cue), IDS).drawable
    assert not assess_geometry(out(no_reason), IDS).drawable


def test_features_without_usable_photos_are_omitted_not_credited():
    g = geo()
    g.walls[2].features = [AIWallFeature(kind="door", start_frac=0.1, end_frac=0.3, photo_indices=[]),
                           AIWallFeature(kind="closet", start_frac=0.5, end_frac=0.8, photo_indices=[7])]
    r = assess_geometry(out(g), IDS)
    assert r.drawable and [f.kind for f in r.features] == ["window"]
    assert any("door on wall C (no usable photo cited)" in o for o in r.omitted_features)
    assert any("closet" in o for o in r.omitted_features)
    assert r.features[0].source_ids == ["src_a"]  # only the photo that actually shows it


def test_l_shaped_is_reported_not_drawn():
    r = assess_geometry(out(geo(shape="l_shaped")), IDS)
    assert not r.drawable and "l-shaped" in r.reason


def test_room_from_analysis_stores_geometry_without_trusting_it():
    room, _ = ai.room_from_analysis(out(geo()), "bedroom", IDS, "mocked_ai", "gpt-6-luna")
    assert room.inferred_geometry.drawable and room.scale_status == "unknown" and room.width is None
    assert room.prompt_version == ai.ROOM_PROMPT_VERSION == "room-evidence-v5-geometry-shape"
    assert any(c.subject == "room outline" and c.kind == "hypothesis" for c in room.claims)
    no_geo, _ = ai.room_from_analysis(PhotoAnalysisOutput(room_type_seen="bedroom"), "bedroom", IDS, "mocked_ai", None)
    assert no_geo.inferred_geometry is not None and not no_geo.inferred_geometry.drawable


def test_floor_plans_cannot_stand_in_for_room_photos():
    # Two floor-plan images only (room_photo_count=0), with geometry the model claims it mapped from them.
    r = assess_geometry(out(geo()), ["plan_1", "plan_2"], room_photo_count=0)
    assert not r.drawable and r.width is None
    # One photo + one floor plan: the plan does not count as the second overlapping photo.
    r2 = assess_geometry(out(geo()), ["photo_1", "plan_1"], room_photo_count=1)
    assert not r2.drawable and ("only one usable photo" in r2.reason or "walls are visible" in r2.reason)


def test_scale_cue_on_a_floor_plan_is_not_a_photographed_object():
    g = geo(scale=AIScaleEstimate(wall_a_length_in_low=120, wall_a_length_in_high=150, wall_b_length_in_low=130,
                                  wall_b_length_in_high=160, reasoning="printed door symbol",
                                  cues=[AIScaleCue(description="door symbol on the plan", photo_index=2)]))
    r = assess_geometry(out(g), ["photo_1", "photo_2", "plan_1"], room_photo_count=2)
    assert not r.drawable and "scale cue" in r.reason


def test_features_may_cite_a_floor_plan_as_their_source():
    g = geo()
    g.walls[2].features = [AIWallFeature(kind="door", start_frac=0.1, end_frac=0.3, photo_indices=[2])]
    r = assess_geometry(out(g), ["photo_1", "photo_2", "plan_1"], room_photo_count=2)
    assert r.drawable and r.source_ids == ["photo_1", "photo_2"]  # outline evidence = photos only
    assert next(f for f in r.features if f.kind == "door").source_ids == ["plan_1"]


def test_plan_readings_only_from_actual_floor_plan_sources():
    from furnishai.models import AIFloorplanReading
    o = PhotoAnalysisOutput(room_type_seen="bedroom", floorplan_readings=[
        AIFloorplanReading(photo_index=0, room_label="Bedroom", dimension_text="10' x 12'"),   # a room PHOTO
        AIFloorplanReading(photo_index=1, room_label="Bedroom", dimension_text="16' x 12'")])  # the floor plan
    room, sugg = ai.room_from_analysis(o, "bedroom", ["photo_1", "plan_1"], "mocked_ai", "gpt-6-luna", room_photo_count=1)
    assert [s["dimension_text"] for s in sugg] == ["16' x 12'"] and sugg[0]["source_ids"] == ["plan_1"]
    assert any(c.subject == "rejected plan reading" and "10' x 12'" in c.statement for c in room.claims)
    # Floor-plan-only analysis: readings kept, room not mapped (no photos), nothing promoted to confirmed size.
    room2, sugg2 = ai.room_from_analysis(o, "bedroom", ["plan_a", "plan_b"], "mocked_ai", "gpt-6-luna", room_photo_count=0)
    assert len(sugg2) == 2 and not room2.inferred_geometry.drawable and room2.width is None
    # Plan-only wording describes the plan path: no "photos are not enough", no pending confirmation.
    text = " ".join(c.statement for c in room2.claims)
    assert "photos are not enough" not in text and "pending your confirmation" not in text
    outline = next(c for c in room2.claims if c.subject == "room outline")
    assert outline.statement.startswith("Using the floor plan:") and "Floor plan only" in outline.statement
    assert all("estimated size once you pick it" in c.statement for c in room2.claims if c.kind == "external_fact")


def test_absence_sentinel_is_not_a_keepable_item_but_real_unknown_items_are_kept():
    from furnishai.models import AIExistingItem
    live_bug = ("No movable living-room furniture is visible. Kitchen appliances are visible; the low unit beneath "
                "the window may be a radiator.")
    o = PhotoAnalysisOutput(room_type_seen="living_room", existing_items=[
        AIExistingItem(category="other", description=live_bug),
        AIExistingItem(category="none", description="-"),
        AIExistingItem(category="other", description="Potted plant in the corner"),
        AIExistingItem(category="other", description="Portable AC unit by the window"),
        AIExistingItem(category="mirror", description="Tall mirror, no frame"),
        AIExistingItem(category="desk", description="Small desk, no drawers; size unknown"),
    ])
    room, _ = ai.room_from_analysis(o, "living_room", IDS, "mocked_ai", "gpt-6-luna")
    kept = [(e.category, e.detected_label) for e in room.existing_items]
    assert kept == [("unmatched", "other"), ("unmatched", "other"), ("unmatched", "mirror"), ("desk", "desk")]
    assert [e.description for e in room.existing_items][:2] == ["Potted plant in the corner", "Portable AC unit by the window"]
    assert any(c.startswith("Model note (not an item): No movable living-room furniture") for c in room.coverage_notes)
    assert not any("No movable" in c.statement for c in room.claims if c.subject.startswith("existing"))
    assert ai.ROOM_PROMPT_VERSION == "room-evidence-v5-geometry-shape" and "existing_items: []" in ai.ROOM_INSTRUCTIONS


def test_old_room_versions_without_geometry_still_load():
    old = {"room_type": "bedroom", "method": "live_ai", "prompt_version": "room-evidence-v1", "scale_status": "unknown"}
    assert RoomModel.model_validate(old).inferred_geometry is None
