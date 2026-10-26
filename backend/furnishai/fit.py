"""Deterministic fit checks (deliberately conservative for this build).

- No trusted scale -> every item is 'Fit unverified'. No dimensions are invented.
- Trusted scale (user-stated or user-confirmed plan dimensions) -> dimension and floor-area checks
  against the LOWER plausible room bounds with explicit clearance assumptions.
- This build does not test exact positions, door swings, windows or circulation paths, so it never
  awards 'Fits tested assumptions'. Best possible label is 'Tight / conditional'.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import RoomModel

# Clearance assumptions in inches (front/access zone depth), shown to users.
CLEARANCE_IN = {
    "bed_frame": 24, "daybed": 24, "sofa_bed": 30, "sofa": 30, "desk": 30, "desk_chair": 0,
    "dresser": 30, "nightstand": 0, "wardrobe": 24, "bookcase": 18, "coffee_table": 14, "mattress": 0,
}
CIRCULATION_SHARE = 0.30  # fraction of free floor reserved for walking paths
NO_FOOTPRINT = {"mattress", "desk_chair", "tv"}  # sits on the frame / tucks into the desk clearance

ASSUMPTIONS = [
    "Clearances: 24 in beside beds, 30 in in front of dressers/desks/sofas, 24 in for wardrobes, 18 in for bookcases.",
    f"{int(CIRCULATION_SHARE * 100)}% of the remaining floor is reserved for walking paths.",
    "Room checks use the LOWER plausible bound of each room dimension.",
    "Door swings, windows, radiators and exact positions are NOT tested in this build.",
]


@dataclass
class FitItem:
    ref: str
    category: str
    width_in: float | None
    depth_in: float | None
    open_depth_upper_in: float | None = None  # sofa beds/daybeds when used for sleeping
    open_along_in: float | None = None


@dataclass
class FitResult:
    labels: dict[str, str]
    plan_label: str
    notes: list[str] = field(default_factory=list)
    # Per item: what the label rests on, in plain terms the UI can show. Doors and walking paths are never checked.
    checks: dict[str, dict[str, str]] = field(default_factory=dict)
    # Whole plan, separately from the room: was the room size known, how many item size checks passed/failed/
    # couldn't run, and the specific reasons overall placement still needs review (never a fit guarantee).
    overview: dict = field(default_factory=dict)


def _fits(w: float, d: float, c: float, Wr: float, Dr: float) -> bool:
    """Item against any wall, either rotation, with its clearance in front."""
    return any(a <= along and b + c <= into for a, b in ((w, d), (d, w)) for along, into in ((Wr, Dr), (Dr, Wr)))


def individually_impossible(room: RoomModel | None, product: dict) -> bool:
    """True only when the item's own footprint (with its clearance, either rotation) exceeds the room's
    UPPER bounds: a definite physical conflict, independent of other furniture."""
    if room is None or room.scale_status == "unknown" or room.width is None or room.depth is None:
        return False
    w, d = product.get("width_in"), product.get("depth_in")
    if w is None or d is None or product.get("category") in NO_FOOTPRINT:
        return False
    c = CLEARANCE_IN.get(product.get("category"), 24)
    return not _fits(w, d, c, room.width.upper, room.depth.upper)


def _rank(label: str) -> int:
    return {"Fits tested assumptions": 0, "Tight / conditional": 1, "Fit unverified": 2, "Does not fit": 3}[label]


def worst(labels) -> str:
    labels = list(labels)
    return max(labels, key=_rank) if labels else "Fit unverified"


def evaluate(room: RoomModel | None, items: list[FitItem], unknown_kept_items: int = 0, sleeping_on: str | None = None) -> FitResult:
    if room is None or room.scale_status == "unknown" or room.width is None or room.depth is None:
        # An estimate (from a plan reading or photos) never upgrades fit; it only says where the drawn size came from.
        est = ("estimated_plan" if room is not None and room.plan_estimate is not None
               else "estimated_photos" if room is not None and room.inferred_geometry is not None and room.inferred_geometry.drawable
               else "unknown")
        return FitResult(
            labels={i.ref: "Fit unverified" for i in items},
            plan_label="Fit unverified",
            notes=["This room has no known size (an estimate from a plan or photos doesn’t count), so fit isn’t assessed; "
                   "we haven’t checked whether "
                   "furniture fits. A room drawn from photos is an approximate rectangle at estimated scale, not your "
                   "exact walls."],
            checks={i.ref: {"product_size": "known" if i.width_in and i.depth_in else "unknown", "room_size": est,
                            "size_check": "not_run", "doors_paths": "not_checked"} for i in items},
            overview={"room_size": est, "size_checked": 0, "size_failed": 0, "size_not_run": len(items),
                      "review_reasons": [], "doors_paths": "not_checked"},
        )
    W_lo, D_lo = room.width.lower, room.depth.lower
    W_hi, D_hi = room.width.upper, room.depth.upper
    labels: dict[str, str] = {}
    notes: list[str] = []
    used_area = 0.0
    checks: dict[str, dict[str, str]] = {}
    for it in items:
        base = {"product_size": "known" if it.width_in and it.depth_in else "unknown", "room_size": "confirmed",
                "doors_paths": "not_checked"}
        if it.category in NO_FOOTPRINT:
            labels[it.ref] = "Tight / conditional"
            checks[it.ref] = {**base, "size_check": "with_other_item"}  # sits on the bed / tucks into the desk
            continue
        if it.width_in is None or it.depth_in is None:
            labels[it.ref] = "Fit unverified"
            checks[it.ref] = {**base, "size_check": "not_run"}
            notes.append(f"{it.ref}: footprint unknown.")
            continue
        c = CLEARANCE_IN.get(it.category, 24)
        w, d = it.width_in, it.depth_in
        if it.ref == sleeping_on and it.open_depth_upper_in:
            w, d = max(w, it.open_along_in or w), it.open_depth_upper_in
            notes.append(f"{it.ref}: checked in its OPEN sleeping position using the conservative upper open-depth bound.")

        if _fits(w, d, c, W_lo, D_lo):
            labels[it.ref] = "Tight / conditional"
            checks[it.ref] = {**base, "size_check": "passed"}
        elif _fits(w, d, c, W_hi, D_hi):
            labels[it.ref] = "Tight / conditional"
            checks[it.ref] = {**base, "size_check": "upper_bound_only"}
            notes.append(f"{it.ref}: only fits toward the upper room bound.")
        else:
            labels[it.ref] = "Does not fit"
            checks[it.ref] = {**base, "size_check": "failed"}
        used_area += w * (d + c)

    fixed_area = 0.0
    unknown_fixed = []
    for f in room.features:
        if f.kind in ("kitchen", "bathroom") and f.width_in and f.depth_in:
            fixed_area += f.width_in * f.depth_in
        elif f.kind in ("kitchen", "bathroom"):
            unknown_fixed.append(f.kind)
    usable_lo = max(W_lo * D_lo - fixed_area, 0) * (1 - CIRCULATION_SHARE)
    usable_hi = max(W_hi * D_hi - fixed_area, 0) * (1 - CIRCULATION_SHARE)
    plan_label = worst(labels.values()) if labels else "Fit unverified"
    # The area screen sums independent clearances, which can overlap in real layouts. It is a
    # conservative warning, never proof that a set is geometrically impossible.
    if used_area > usable_lo:
        plan_label = worst([plan_label, "Tight / conditional"])
        where = "even at the upper room bound" if used_area > usable_hi else "at the lower room bound"
        notes.append(f"Space warning: footprints plus assumed clearances (~{used_area / 144:.0f} sq ft) exceed the "
                     f"estimated usable floor {where}. This rough screen is not a layout test; some clearances overlap in practice.")
    review: list[str] = []
    if used_area > usable_lo:
        review.append("Together, the furniture and the space in front of it may crowd the floor.")
    if unknown_fixed:
        review.append(f"The {' and '.join(sorted(set(unknown_fixed)))} area’s size isn’t known, so the free floor is unknown.")
    if unknown_kept_items:
        review.append(f"{unknown_kept_items} item(s) you’re keeping have no size, so they couldn’t be counted.")
    if any(c["size_check"] == "not_run" for c in checks.values()):
        review.append("Some items have no listed size, so their fit couldn’t be checked.")
    if unknown_fixed or unknown_kept_items:
        plan_label = "Fit unverified" if plan_label != "Does not fit" else plan_label
        if unknown_fixed:
            notes.append(f"The {' and '.join(sorted(set(unknown_fixed)))} area has no known size, so the space left for "
                         "furniture is unknown; overall fit stays unverified.")
        if unknown_kept_items:
            notes.append(f"{unknown_kept_items} kept item(s) have unknown size, so overall fit stays unverified.")
    notes.append("Not checked: exact positions, door swings, windows, collisions and walking paths.")
    if plan_label == "Fits tested assumptions":  # unreachable by design in this build
        plan_label = "Tight / conditional"
    overview = {"room_size": "confirmed",
                "size_checked": sum(c["size_check"] in ("passed", "upper_bound_only") for c in checks.values()),
                "size_failed": sum(c["size_check"] == "failed" for c in checks.values()),
                "size_not_run": sum(c["size_check"] == "not_run" for c in checks.values()),
                "review_reasons": review, "doors_paths": "not_checked"}
    return FitResult(labels=labels, plan_label=plan_label, notes=notes, checks=checks, overview=overview)
