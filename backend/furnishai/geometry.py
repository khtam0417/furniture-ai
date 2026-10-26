"""Gate a model's photo-geometry output into a stored InferredGeometry hypothesis.

Code, not the model, decides whether a room outline may be drawn. Requirements for a drawable outline:
- the model reported status "mapped" for a rectangular room;
- at least 3 of the 4 walls are seen (fully or partly) in valid photos, and at least 2 corners;
- at least 2 distinct photos support the walls, none of them flagged as showing a different room;
- a size range for walls A and B with low < high, 48-480 in, high/low <= 1.6, a non-empty reasoning, and >= 1
  described visible scale cue in a valid photo;
- wall A (the reference) is described and visible in a usable photo, and the analysis reports no contradictions.
Features without a usable cited photo are omitted (and listed), never credited to all photos.
Otherwise the result is not drawable and carries specific photo guidance. Nothing is upgraded to a trusted
dimension: the ranges are stored as weak, unverified bounds.
v2: when walls, corners and photos pass but the SIZE does not (no estimate, too wide a range, no cue), the
walls and located features are kept as an `observed_only` NOT-TO-SCALE record: shown as observations, never
used for furniture placement or fit (layout reads only drawable outlines).
"""

from __future__ import annotations

from .models import Bound, FeatureEstimate, InferredGeometry, PhotoAnalysisOutput

GEOMETRY_METHOD = "photo-geometry-v2"
MIN_WALLS_SEEN = 3
MIN_PHOTOS = 2
MIN_CORNERS = 2
MIN_LEN_IN, MAX_LEN_IN, MAX_RATIO = 48.0, 480.0, 1.6
DEFAULT_GUIDANCE = [
    "Stand in one corner and photograph the opposite corner so two walls and the floor edge are visible.",
    "Then do the same from the diagonally opposite corner, so all four walls appear across the photos.",
    "Include the door and any bed, desk or appliance fully in frame: they help estimate size.",
]


def _ft(v: float) -> str:
    return f"{int(v // 12)}′{int(round(v % 12))}″"


def assess_geometry(out: PhotoAnalysisOutput, photo_ids: list[str], synthetic: bool = False,
                    room_photo_count: int | None = None) -> InferredGeometry:
    """`photo_ids` lists the analysed sources in prompt order: room photos first, then floor-plan images.
    `room_photo_count` marks that boundary. Only ROOM PHOTOS can satisfy the wall/photo/corner evidence and supply
    photographed scale cues; floor plans may only be cited as the source of a located feature. The model's
    output is untrusted, so the boundary comes from our own source records, not from what the model says."""
    g = out.geometry
    n = len(photo_ids)
    n_photos = n if room_photo_count is None else max(0, min(room_photo_count, n))
    other_room = {p.photo_index for p in out.per_photo if p.appears_same_room_as_others == "no"}

    def valid(indices: list[int]) -> list[int]:  # room photos only
        return [i for i in indices if 0 <= i < n_photos and i not in other_room]

    def valid_source(indices: list[int]) -> list[int]:  # room photos or floor plans (for feature provenance)
        return [i for i in indices if 0 <= i < n and i not in other_room]

    def fail(reason: str, guidance: list[str] | None = None, **extra) -> InferredGeometry:
        views = list(guidance or [])
        if g is not None:
            views += [v for v in g.missing_views if v not in views]
        if other_room:
            views.insert(0, "Photo(s) " + ", ".join(str(i + 1) for i in sorted(other_room))
                         + " look like a different room; retake those from inside this room.")
        return InferredGeometry(method=GEOMETRY_METHOD, drawable=False, reason=reason,
                                missing_views=(views or DEFAULT_GUIDANCE)[:6], synthetic=synthetic,
                                reasoning=(g.reasoning if g else ""), **extra)

    if n_photos == 0:  # plan-only input: there are no room photos to map, which is not a photo failure
        return fail("Floor plan only (no room photos), so there’s no photo outline. Pick this room’s printed size from the plan "
                    "to draw it, or add room photos.", ["Optional: 2 or more overlapping room photos from opposite corners."])
    if g is None:
        return fail("The analysis did not map the room outline.")
    walls = {w.wall: w for w in g.walls}
    descs = {w.wall: w.description for w in g.walls}
    base = {"reference_wall_a": g.reference_wall_a, "wall_descriptions": descs, "shape": g.shape}
    if g.status != "mapped":
        return fail("The photos are not enough to map this room yet.", **base)
    if out.contradictions:
        return fail("The photos contain conflicting evidence (" + "; ".join(c[:120] for c in out.contradictions[:2])
                    + "), so the room is not mapped.", ["Retake the photos from inside this one room, from two opposite corners."], **base)
    wall_a = walls.get("A")
    if not g.reference_wall_a.strip() or wall_a is None or wall_a.visible == "not_seen" or not valid(wall_a.photo_indices):
        return fail("The reference wall (wall A) is not identified in a usable photo, so the outline has no anchor.",
                    ["Add a photo that shows one whole wall, e.g. the window wall, edge to edge."], **base)
    if g.shape in ("l_shaped", "irregular"):
        # Record which walls the photos showed, so this observed (not merely plan-level) shape keeps blocking
        # rectangular drawings, including plan-size estimates.
        observed = sorted(w for w, obs in walls.items() if obs.visible in ("fully", "partly") and valid(obs.photo_indices))
        return fail(f"The room looks {g.shape.replace('_', '-')}. This version can only draw rectangular rooms, "
                    "so no outline is drawn (a rectangle would misrepresent it).", walls_seen=observed, **base)
    if g.shape != "rectangular":
        return fail("The room's shape could not be determined from the photos.", **base)
    seen = sorted(w for w, obs in walls.items() if obs.visible in ("fully", "partly") and valid(obs.photo_indices))
    photos = sorted({i for w in seen for i in valid(walls[w].photo_indices)})
    missing_walls = [w for w in "ABCD" if w not in seen]
    if len(seen) < MIN_WALLS_SEEN:
        guide = [f"Add a photo showing wall {w}" + (f" ({descs[w]})" if descs.get(w) else "") + "." for w in missing_walls]
        return fail(f"Only {len(seen)} of 4 walls are visible in usable photos (need {MIN_WALLS_SEEN}).", guide,
                    walls_seen=seen, **base)
    if len(photos) < MIN_PHOTOS:
        return fail("The walls are supported by only one usable photo; overlapping views are needed.",
                    ["Add a second photo from the opposite corner that overlaps the first."], walls_seen=seen, **base)
    if g.corners_seen < MIN_CORNERS:
        return fail(f"Only {g.corners_seen} room corner(s) are visible (need {MIN_CORNERS}).",
                    ["Add photos that each show a corner where two walls meet the floor."], walls_seen=seen, **base)
    sources = [photo_ids[i] for i in photos]
    features, omitted = [], []
    for w in seen:
        for f in walls[w].features:
            if not (f.end_frac > f.start_frac):
                omitted.append(f"{f.kind} on wall {w} (invalid position)")
                continue
            fsrc = [photo_ids[i] for i in valid_source(f.photo_indices)]
            if not fsrc:  # no usable photo shows it: do not pretend it was observed
                omitted.append(f"{f.kind} on wall {w} (no usable photo cited)")
                continue
            depth = None
            if f.depth_in_low and f.kind in ("kitchen", "column", "radiator"):
                depth = max(f.depth_in_low, f.depth_in_high or f.depth_in_low)  # conservative: the larger depth
            features.append(FeatureEstimate(
                kind=f.kind, wall=w, start_frac=round(f.start_frac, 3), end_frac=round(f.end_frac, 3), depth_in=depth,
                source_ids=fsrc, note=f.note))

    s = g.scale
    scale_problem = None
    if s is None:
        scale_problem = "No size estimate was possible from the photos."
    else:
        for name, lo, hi in (("A", s.wall_a_length_in_low, s.wall_a_length_in_high), ("B", s.wall_b_length_in_low, s.wall_b_length_in_high)):
            if not (lo < hi) or lo < MIN_LEN_IN or hi > MAX_LEN_IN:
                scale_problem = scale_problem or "The size estimate is implausible, so the room can’t be drawn to scale."
            elif hi / lo > MAX_RATIO:
                # User-facing: the exact range and a plain why; the MAX_RATIO threshold stays in code and docs.
                scale_problem = scale_problem or (
                    f"The size estimate is too uncertain to place furniture: wall {name} could be anywhere from "
                    f"{_ft(lo)} to {_ft(hi)}, too wide a range to know what fits.")
        if not any(0 <= c.photo_index < n_photos and c.photo_index not in other_room and c.description.strip() for c in s.cues):
            scale_problem = scale_problem or "No visible scale cue (door, bed, appliance) was identified in the photos."
        if not s.reasoning.strip():
            scale_problem = scale_problem or "The size estimate came without any reasoning, so it is not used."
    if scale_problem:
        # Walls, corners and photos are good enough to describe what was seen, but not the size: keep the
        # observations, marked NOT TO SCALE, and never place furniture from them.
        return fail(scale_problem, ["Add a photo where the door, bed or a kitchen appliance is fully visible next to a wall."],
                    walls_seen=seen, features=features, omitted_features=omitted, source_ids=sources,
                    observed_only=True, **base)

    def bound(lo: float, hi: float, label: str) -> Bound:
        return Bound(lower=lo, central=round((lo + hi) / 2, 1), upper=hi,
                     method=f"{label} estimated from photos (unverified)", source_ids=sources, strength="weak")

    cues = [f"{c.description} (photo {c.photo_index + 1}; {'identified variant claimed' if c.exact_variant_identified else 'typical size, weak cue'})"
            for c in s.cues if 0 <= c.photo_index < n_photos and c.description.strip()]
    return InferredGeometry(
        method=GEOMETRY_METHOD, drawable=True,
        reason=(f"Estimated rectangular outline from {len(photos)} overlapping photos showing walls {', '.join(seen)}: "
                f"wall A about {_ft(s.wall_a_length_in_low)}–{_ft(s.wall_a_length_in_high)}, wall B about "
                f"{_ft(s.wall_b_length_in_low)}–{_ft(s.wall_b_length_in_high)}. Unverified."),
        walls_seen=seen, width=bound(s.wall_a_length_in_low, s.wall_a_length_in_high, "Wall A length"),
        depth=bound(s.wall_b_length_in_low, s.wall_b_length_in_high, "Wall B length"),
        features=features, omitted_features=omitted, scale_cues=cues, source_ids=sources,
        missing_views=[f"A photo of wall {w}" + (f" ({descs[w]})" if descs.get(w) else "") + " would confirm the outline." for w in missing_walls],
        reasoning=g.reasoning[:500] + " " + s.reasoning[:300], synthetic=synthetic, **base,
    )
