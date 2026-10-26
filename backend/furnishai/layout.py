"""Furniture arrangements inside a FIXED room (derived layouts, never source evidence).

The room is not designed here. `room_frame()` derives one frozen outline and fixed-feature zones from a room
version ONLY (trusted confirmed size, or a gated photo-estimated outline, or labeled synthetic demo geometry),
before any products are considered. If the room has not been mapped, there is no outline and no arrangement:
the result says which photos are needed. Products, budget and strategy can never change the frame; items that
do not fit are listed as not drawn. Nothing is resized.

Placement: deterministic bounded search. Each item is tried against each wall in allowed rotations, sliding in
6 in steps. A candidate is valid only if its footprint is inside the outline, overlaps no other footprint, no
fixed zone and no other item's access zone, and its own access zone is inside the outline and clear of
footprints and solid fixed zones. A finished arrangement is re-checked independently (`verify`), so the
"checks passed" statements are true for every returned arrangement. Door swings are only as good as the
estimated door positions; walking routes and accessibility are not verified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .geometry import DEFAULT_GUIDANCE
from .models import (
    Arrangement, Associated, FixedZone, LayoutSet, Placement, Plan, Preferences, RoomModel, Unplaced, WallMarker,
)

LAYOUT_METHOD = "layout-v2-fixed-room"
STEP_IN = 6.0
EPS = 0.01
WALLS = ("north", "east", "south", "west")  # internal frame: wall A = north edge, then clockwise
WALL_ID = {"north": "A", "east": "B", "south": "C", "west": "D"}
INTERNAL = {v: k for k, v in WALL_ID.items()}
ROTATION = {"north": 0, "east": 90, "south": 180, "west": 270}

ACCESS_IN = {
    "bed_frame": 24, "daybed": 24, "sofa_bed": 18, "sofa": 18, "desk": 30, "dresser": 30, "wardrobe": 24,
    "bookcase": 18, "nightstand": 0, "coffee_table": 0,
}
BED_HEAD_ZONE_IN = 20  # bed side access starts below the pillow area, leaving room for nightstands
COFFEE_GAP_IN = 18  # equals the sofa access depth, so the table never sits in it
FREE_CLEAR_IN = 18
SINGLE_SLEEPER_MAX_W_IN = 57.0
DOOR_SWING_MIN_IN, DOOR_SWING_MAX_IN = 30.0, 42.0
ASSUMED_DEPTH = {"kitchen": 24.0, "radiator": 8.0, "column": 12.0}
KITCHEN_AISLE_IN = 36.0

PRIORITY = ["bed_frame", "daybed", "sofa_bed", "sofa", "wardrobe", "dresser", "desk", "bookcase", "nightstand", "coffee_table"]
ASSUMPTIONS = [
    "Access zones assumed: 24 in beside beds (below the pillow area), 30 in in front of desks and dressers, "
    "24 in for wardrobes, 18 in in front of sofas and bookcases. Access zones may overlap each other (shared walking space).",
    "Footprints are the retailer's overall width × depth; nothing is shrunk to fit and the room is never resized.",
    "Mattresses rest on their bed frame and desk chairs tuck into the desk's access zone; neither is separate floor furniture.",
]

Rect = tuple[float, float, float, float]


def _overlap(a: Rect, b: Rect) -> bool:
    return a[0] < b[0] + b[2] - EPS and b[0] < a[0] + a[2] - EPS and a[1] < b[1] + b[3] - EPS and b[1] < a[1] + a[3] - EPS


def _inside(r: Rect, W: float, D: float) -> bool:
    return r[0] >= -EPS and r[1] >= -EPS and r[0] + r[2] <= W + EPS and r[1] + r[3] <= D + EPS


def _grow(r: Rect, m: float) -> Rect:
    return (r[0] - m, r[1] - m, r[2] + 2 * m, r[3] + 2 * m)


def _clip(r: Rect, W: float, D: float) -> Rect:
    x0, y0 = max(r[0], 0.0), max(r[1], 0.0)
    x1, y1 = min(r[0] + r[2], W), min(r[1] + r[3], D)
    return (x0, y0, max(x1 - x0, 0.0), max(y1 - y0, 0.0))


def _ft(inches: float) -> str:
    return f"{int(inches // 12)}′{int(round(inches % 12))}″"


# ------------------------------------------------------------------ frozen room frame
@dataclass
class Zone:
    rect: Rect
    label: str
    solid: bool  # solid zones also block access zones; keep-clear zones block footprints and opened beds
    assumption: str


@dataclass
class RoomFrame:
    basis: str  # scaled_room_lower_bound | estimated_from_photos | estimated_from_plan | synthetic_demo | unavailable
    W: float = 0.0
    D: float = 0.0
    label: str = ""
    width_range: tuple[float, float] | None = None
    depth_range: tuple[float, float] | None = None
    zones: list[Zone] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    window_walls: set[str] = field(default_factory=set)
    wall_descriptions: dict[str, str] = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    missing_views: list[str] = field(default_factory=list)
    reason: str = ""
    room_version_id: str | None = None
    floorplan_source_ids: list[str] = field(default_factory=list)
    markers: list[dict] = field(default_factory=list)  # wall markers (windows): drawn, not obstacles

    @property
    def hash(self) -> str:
        payload = {"basis": self.basis, "W": self.W, "D": self.D, "room": self.room_version_id,
                   "zones": [[round(v, 2) for v in z.rect] + [z.label, z.solid] for z in self.zones],
                   "markers": self.markers}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _wall_rect(wall: str, t: float, a: float, b: float, W: float, D: float) -> Rect:
    if wall == "north":
        return (t, 0.0, a, b)
    if wall == "south":
        return (t, D - b, a, b)
    if wall == "west":
        return (0.0, t, b, a)
    return (W - b, t, b, a)  # east


def _wall_len(wall: str, W: float, D: float) -> float:
    return W if wall in ("north", "south") else D


def _segment(wall_id: str, s: float, e: float, unc: float, W: float, D: float) -> tuple[str, float, float]:
    """Fractions measured from the left end when facing the wall from inside -> internal (wall, t0, t1)."""
    wall = INTERNAL[wall_id]
    L = _wall_len(wall, W, D)
    s, e = max(0.0, s - unc), min(1.0, e + unc)
    if wall in ("north", "east"):  # left end is the low coordinate
        return wall, s * L, e * L
    return wall, (1 - e) * L, (1 - s) * L  # south / west run the other way


def _zones_from_geometry(geo, W: float, D: float, skip_kinds: set[str] = frozenset()) -> tuple[list[Zone], list[str], set[str], list[dict]]:
    zones, notes, windows, markers = [], [], set(), []
    for f in geo.features:
        if f.kind in skip_kinds:
            continue  # a stored exact position for this kind takes precedence
        wall, t0, t1 = _segment(f.wall, f.start_frac, f.end_frac, f.uncertainty_frac, W, D)
        length = t1 - t0
        where = f"wall {f.wall}, about {f.start_frac:.0%}–{f.end_frac:.0%} along (±{f.uncertainty_frac:.0%})"
        if f.kind == "window":
            windows.add(wall)
            _, s0, s1 = _segment(f.wall, f.start_frac, f.end_frac, 0.0, W, D)  # drawn at the estimate itself
            markers.append(_marker(wall, s0, s1, W, D, "window",
                                   f"Seen in {len(f.source_ids)} photo(s); position estimated (±{f.uncertainty_frac:.0%} of the wall)."))
            continue
        if f.kind in ("door", "entry", "bathroom_door"):
            depth = min(max(length, DOOR_SWING_MIN_IN), DOOR_SWING_MAX_IN)
            zones.append(Zone(_clip(_wall_rect(wall, t0, length, depth, W, D), W, D), f"{f.kind.replace('_', ' ')} keep-clear", False,
                              f"Door position estimated from photos ({where}); swing area kept clear, hinge side unknown."))
        elif f.kind == "closet":
            zones.append(Zone(_clip(_wall_rect(wall, t0, length, 24.0, W, D), W, D), "closet opening keep-clear", False,
                              f"Closet estimated at {where}; 24 in in front kept clear."))
        elif f.kind in ASSUMED_DEPTH:
            depth = f.depth_in or ASSUMED_DEPTH[f.kind]
            src = "estimated depth" if f.depth_in else f"assumed {ASSUMED_DEPTH[f.kind]:.0f} in depth"
            label = {"kitchen": "kitchen counters", "radiator": "radiator", "column": "column"}[f.kind]
            r = _clip(_wall_rect(wall, t0, length, depth, W, D), W, D)
            zones.append(Zone(r, label, True, f"{label.capitalize()} at {where}, {src}."))
            if f.kind == "kitchen":
                aisle = _clip(_front(wall, r, KITCHEN_AISLE_IN), W, D)
                zones.append(Zone(aisle, "kitchen work aisle", False, "36 in in front of the counters kept free of furniture (walking allowed)."))
        else:
            notes.append(f"{f.kind.replace('_', ' ')} on {where}: not modeled as an obstacle.")
    return zones, notes, windows, markers


def room_frame(room: RoomModel | None, room_version_id: str | None = None,
               floorplan_source_ids: list[str] | None = None) -> RoomFrame:
    """One frozen outline + fixed zones per room version. Never depends on products, budget or strategy."""
    fp = list(floorplan_source_ids or [])
    if room is None:
        return RoomFrame("unavailable", reason="No photos have been analyzed for this room yet.",
                         missing_views=list(DEFAULT_GUIDANCE), floorplan_source_ids=fp)
    geo = room.inferred_geometry
    trusted = room.scale_status != "unknown" and room.width is not None and room.depth is not None
    shape = geo.shape if geo is not None and geo.shape != "unknown" else room.shape
    if not trusted and room.plan_estimate is not None:
        # Plan estimate: only a shape observed in THIS room's photos counts (a whole-apartment plan's outline is not
        # the room's); otherwise the rectangle is an assumption, labeled as such.
        shape = geo.shape if geo is not None and geo.walls_seen and geo.shape != "unknown" else "unknown"
    if shape in ("l_shaped", "irregular"):
        return RoomFrame("unavailable", reason=f"The room looks {shape.replace('_', '-')}; this version only draws rectangular rooms.",
                         missing_views=(geo.missing_views if geo else []), room_version_id=room_version_id, floorplan_source_ids=fp)
    assumptions: list[str] = []
    if trusted:
        W, D = room.width.lower, room.depth.lower
        basis = "scaled_room_lower_bound"
        wr, dr = (room.width.lower, room.width.upper), (room.depth.lower, room.depth.upper)
        how = "a floor plan you confirmed" if room.scale_status == "plan_dimensions_user_confirmed" else "the size you entered"
        label = (f"Size from {how}: drawn at the lower bound {_ft(W)} × {_ft(D)} "
                 f"(width up to {_ft(wr[1])}, length up to {_ft(dr[1])})")
        if not (geo and geo.drawable):
            assumptions.append("Rectangular outline assumed from the confirmed size; wall shape and feature positions were not mapped from photos.")
        else:
            assumptions.append("The first confirmed dimension is assumed to run along wall A of the photo map.")
    elif room.plan_estimate is not None:
        # An ESTIMATE from a printed plan reading the user chose: conservative lower bounds, clearly labeled.
        pe = room.plan_estimate
        W, D = pe.width.lower, pe.depth.lower
        basis = "estimated_from_plan"
        wr, dr = (pe.width.lower, pe.width.upper), (pe.depth.lower, pe.depth.upper)
        what = " ".join(x for x in (pe.room_label, pe.dimension_text) if x)
        label = (f"Estimated layout from selected plan ({what}); your unit may differ: drawn at {_ft(W)} × {_ft(D)}, "
                 f"the smaller end of ±{pe.tolerance_in:g} in")
        assumptions.append("Rectangle assumed from the printed plan reading (the room’s real shape isn’t known); the first "
                           "number is assumed to run along wall A.")
        if not (geo and geo.drawable):
            assumptions.append("Door, window and closet positions are not known from the plan reading, so they aren't reserved.")
    elif geo is not None and geo.drawable:
        W, D = geo.width.lower, geo.depth.lower
        basis = "synthetic_demo" if geo.synthetic else "estimated_from_photos"
        wr, dr = (geo.width.lower, geo.width.upper), (geo.depth.lower, geo.depth.upper)
        label = (("Synthetic demo room (fixture geometry, not a real room)" if geo.synthetic else
                  "Estimated from your photos · dimensions unverified")
                 + f": wall A {_ft(wr[0])}–{_ft(wr[1])}, wall B {_ft(dr[0])}–{_ft(dr[1])}; drawn at the smaller size")
        assumptions.append("Outline and feature positions are estimates from the photos, not measurements.")
    else:
        if geo is None:
            reason = ("This room was analyzed before photo mapping existed. Re-analyze the photos to map this room."
                      if room.method in ("live_ai", "mocked_ai") else "This room has no photo map yet.")
            views = list(DEFAULT_GUIDANCE)
        else:
            reason, views = geo.reason, list(geo.missing_views)
        return RoomFrame("unavailable", reason=reason, missing_views=views, room_version_id=room_version_id,
                         wall_descriptions=(geo.wall_descriptions if geo else {}), floorplan_source_ids=fp)

    # 1) Stored, fully located features take precedence over photo estimates of the same kind.
    zones, stored_notes, stored_kinds, markers, windows = _zones_from_stored(room, W, D)
    notes: list[str] = list(stored_notes)
    if geo is not None and geo.drawable:
        g_zones, g_notes, g_windows, g_markers = _zones_from_geometry(geo, W, D, skip_kinds=stored_kinds)
        zones += g_zones
        notes += g_notes
        windows |= g_windows
        markers += g_markers
        overridden = sorted(stored_kinds & {f.kind for f in geo.features})
        if overridden:
            assumptions.append("Stored exact positions used instead of the photo estimates for: " + ", ".join(overridden) + ".")
    located = set(stored_kinds) | {f.kind for f in (geo.features if geo and geo.drawable else [])}
    located |= {"bathroom"} if "bathroom_door" in located else set()
    unresolved = list(notes)
    for f in room.features:
        if f.kind in ("door", "entry", "closet", "radiator", "kitchen", "bathroom", "column") and f.kind not in located:
            unresolved.append(f"{f.kind.capitalize()} seen in the photos but not located on the outline: not reserved — check it stays clear.")
    if not any(z.label.endswith("keep-clear") and ("door" in z.label or "entry" in z.label) for z in zones):
        unresolved.append("No door position is located on the outline, so door swing and the entry path are not checked.")
    src = list(geo.source_ids) if geo is not None and geo.drawable else []
    return RoomFrame(basis, W, D, label, wr, dr, zones, sorted(set(unresolved), key=unresolved.index), assumptions, windows,
                     (geo.wall_descriptions if geo else {}), src, (geo.missing_views if geo else []), "",
                     room_version_id, fp, markers)


STORED_SOLID = {"bathroom": "bathroom", "column": "column", "radiator": "radiator", "kitchen": "kitchen counters"}


def _zones_from_stored(room: RoomModel, W: float, D: float) -> tuple[list[Zone], list[str], set[str], list[dict], set[str]]:
    """Features with an exact stored wall/offset/width (offset from the wall's low-coordinate end: x for the A/C
    walls, y for B/D). Geometry is validated: out-of-range positions are clamped to the wall and flagged, positions
    beyond the wall or solid features without a depth are flagged and not applied (never silently dropped)."""
    zones: list[Zone] = []
    notes: list[str] = []
    kinds: set[str] = set()
    markers: list[dict] = []
    windows: set[str] = set()
    for f in room.features:
        if f.wall not in WALLS or f.offset_in is None or not f.width_in:
            continue  # not fully located: handled as "seen but not located"
        name = STORED_SOLID.get(f.kind, f.kind)
        wid = WALL_ID[f.wall]
        L = _wall_len(f.wall, W, D)
        into = D if f.wall in ("north", "south") else W
        if f.offset_in >= L - EPS:
            notes.append(f"Stored {name} on wall {wid} starts beyond the wall's length ({_ft(L)}); not applied — check its position.")
            kinds.add(f.kind)
            continue
        width = f.width_in
        if f.offset_in + width > L + EPS:
            width = L - f.offset_in
            notes.append(f"Stored {name} on wall {wid} ran past the corner; clamped to the wall ({width:.0f} in).")
        where = f"wall {wid}, {f.offset_in:g}–{f.offset_in + width:g} in (stored position)"
        if f.kind == "window":
            windows.add(f.wall)
            markers.append(_marker(f.wall, f.offset_in, f.offset_in + width, W, D, "window", "Stored position."))
        elif f.kind in ("door", "entry", "closet"):
            depth = min(width, into) if f.kind != "closet" else min(24.0, into)
            zones.append(Zone(_clip(_wall_rect(f.wall, f.offset_in, width, depth, W, D), W, D), f"{f.kind} keep-clear", False,
                              f"{f.kind.title()} at {where}."))
        elif f.kind in STORED_SOLID:
            if f.depth_in:
                depth, how = f.depth_in, "stored depth"
            elif f.kind in ASSUMED_DEPTH:
                depth, how = ASSUMED_DEPTH[f.kind], f"assumed {ASSUMED_DEPTH[f.kind]:.0f} in depth (none stored)"
            else:
                notes.append(f"Stored {name} on wall {wid} has no depth, so its footprint is unknown; not applied — check it stays clear.")
                kinds.add(f.kind)
                continue
            if depth > into + EPS:
                notes.append(f"Stored {name} depth ({depth:g} in) exceeds the room; clamped.")
                depth = into
            r = _clip(_wall_rect(f.wall, f.offset_in, width, depth, W, D), W, D)
            zones.append(Zone(r, name, True, f"{name.capitalize()} at {where}, {how}."))
            if f.kind == "kitchen":
                zones.append(Zone(_clip(_front(f.wall, r, KITCHEN_AISLE_IN), W, D), "kitchen work aisle", False,
                                  "36 in in front of the counters kept free of furniture (walking allowed)."))
        else:
            continue
        kinds.add(f.kind)
    return zones, notes, kinds, markers, windows


def _marker(wall: str, t0: float, t1: float, W: float, D: float, kind: str, caveat: str) -> dict:
    if wall == "north":
        x1, y1, x2, y2 = t0, 0.0, t1, 0.0
    elif wall == "south":
        x1, y1, x2, y2 = t0, D, t1, D
    elif wall == "west":
        x1, y1, x2, y2 = 0.0, t0, 0.0, t1
    else:
        x1, y1, x2, y2 = W, t0, W, t1
    return {"kind": kind, "wall": WALL_ID[wall], "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
            "label": kind, "caveat": caveat}


# ------------------------------------------------------------------ items
@dataclass
class Item:
    ref: str
    label: str
    category: str
    kind: str
    width: float
    depth: float
    zone: str | None = None
    open_upper: float | None = None
    open_along: float | None = None
    open_known: bool = True
    shared: bool = False


@dataclass
class Placed:
    item: Item
    rect: Rect
    wall: str
    clear: list[Rect] = field(default_factory=list)
    open_rect: Rect | None = None
    along: float = 0.0
    along_len: float = 0.0


def _items_from_plan(plan: Plan, catalog_by_id: dict, prefs: Preferences) -> tuple[list[Item], list[Associated], list[Unplaced]]:
    items: list[Item] = []
    assoc: list[Associated] = []
    unplaced: list[Unplaced] = []
    cats = {i.category for i in plan.items}
    kept_cats = {e.category for e in prefs.existing_items if e.keep}
    bed_ref = next((i.product_id or i.existing_item_id for i in plan.items if i.category == "bed_frame" and i.width_in and i.depth_in), None)
    desk_ref = next((i.product_id or i.existing_item_id for i in plan.items if i.category == "desk" and i.width_in and i.depth_in), None)
    for it in plan.items:
        ref = it.product_id or it.existing_item_id or it.name
        kind = "existing" if it.existing_item_id else "product"
        if it.category == "mattress":
            if bed_ref:
                assoc.append(Associated(ref=ref, label=it.name, on_ref=bed_ref, note="Rests on the bed frame; not separate floor furniture."))
            elif "daybed" in cats or "bed_frame" in kept_cats or "bed_frame" in cats:
                assoc.append(Associated(ref=ref, label=it.name, on_ref=None, note="Rests on your bed/daybed; not separate floor furniture."))
            else:
                unplaced.append(Unplaced(ref=ref, label=it.name, reason="A mattress needs a frame; none is in this plan, so it is not drawn."))
            continue
        if it.category == "desk_chair":
            if desk_ref:
                assoc.append(Associated(ref=ref, label=it.name, on_ref=desk_ref, note="Tucks into the desk's 30 in access zone."))
            else:
                unplaced.append(Unplaced(ref=ref, label=it.name, reason="No desk with a known size to pair it with."))
            continue
        if not it.width_in or not it.depth_in:
            unplaced.append(Unplaced(ref=ref, label=it.name, reason="Size unknown — add its width and depth in Preferences to place it."))
            continue
        snap = catalog_by_id.get(it.product_id or "", {})
        bounds = snap.get("open_depth_bounds_in") or {}
        sleeper = it.category in ("sofa_bed", "daybed")
        items.append(Item(ref=ref, label=it.name, category=it.category, kind=kind, width=float(it.width_in), depth=float(it.depth_in),
                          zone=it.zone, open_upper=bounds.get("upper") if sleeper else None,
                          open_along=bounds.get("along_wall") if sleeper else None,
                          open_known=(not sleeper) or bool(bounds.get("upper")), shared=prefs.shared_use))
    rank = {c: n for n, c in enumerate(PRIORITY)}
    items.sort(key=lambda i: (rank.get(i.category, len(PRIORITY)), -i.width * i.depth, i.ref))
    return items, assoc, unplaced


def _orientations(item: Item) -> list[tuple[float, float, str]]:
    w, d = item.width, item.depth
    if item.category == "bed_frame":
        opts = [(w, d, "head")]
        if not item.shared and w <= SINGLE_SLEEPER_MAX_W_IN:
            opts.append((d, w, "long_side"))
        return opts
    return [(max(w, d), min(w, d), "front")]


def _front(wall: str, r: Rect, c: float) -> Rect | None:
    if c <= 0:
        return None
    x, y, w, d = r
    return {"north": (x, y + d, w, c), "south": (x, y - c, w, c), "west": (x + w, y, c, d), "east": (x - c, y, c, d)}[wall]


def _sides(wall: str, r: Rect, c: float, head: float) -> tuple[Rect, Rect]:
    x, y, w, d = r
    if wall == "north":
        return (x - c, y + head, c, d - head), (x + w, y + head, c, d - head)
    if wall == "south":
        return (x - c, y, c, d - head), (x + w, y, c, d - head)
    if wall == "west":
        return (x + head, y - c, w - head, c), (x + head, y + d, w - head, c)
    return (x, y - c, w - head, c), (x, y + d, w - head, c)


def _positions(L: float, a: float) -> list[float]:
    if a > L + EPS:
        return []
    n = int((L - a) // STEP_IN)
    pos = [i * STEP_IN for i in range(n + 1)]
    if L - a - pos[-1] > EPS:
        pos.append(L - a)
    return pos


def _valid(rect: Rect, clears: list[Rect], frame: RoomFrame, placed: list[Placed]) -> bool:
    if not _inside(rect, frame.W, frame.D):
        return False
    if any(_overlap(rect, z.rect) for z in frame.zones):
        return False
    for p in placed:
        if _overlap(rect, p.rect) or any(_overlap(rect, c) for c in p.clear):
            return False
    for c in clears:
        if not _inside(c, frame.W, frame.D):
            return False
        if any(_overlap(c, p.rect) for p in placed) or any(z.solid and _overlap(c, z.rect) for z in frame.zones):
            return False
    return True


def _open_rect(item: Item, wall: str, rect: Rect, t: float, a: float, b: float, frame: RoomFrame) -> Rect | None:
    """Opened sleeping extent in front of the closed piece, using the documented along-wall length when larger."""
    if not item.open_upper or item.open_upper <= b:
        return None
    along = max(a, item.open_along or a)
    L = _wall_len(wall, frame.W, frame.D)
    t2 = min(t, max(L - along, 0.0))
    base = _wall_rect(wall, t2, along, b, frame.W, frame.D)
    return _front(wall, base, item.open_upper - b)


def _open_blockers(o: Rect, frame: RoomFrame, others: list[Placed]) -> tuple[bool, list[str]]:
    """(blocked by structure or furniture other than coffee tables, coffee tables in the way)."""
    if not _inside(o, frame.W, frame.D) or any(_overlap(o, z.rect) for z in frame.zones):
        return True, []
    blocked = any(_overlap(o, q.rect) for q in others if q.item.category != "coffee_table")
    tables = [q.item.label for q in others if q.item.category == "coffee_table" and _overlap(o, q.rect)]
    return blocked, tables


# ------------------------------------------------------------------ strategies
@dataclass
class Strategy:
    key: str
    title: str
    intent: str


def strategies_for(items: list[Item]) -> list[Strategy]:
    out = [Strategy("open_center", "Open center", "Large pieces in corners and along walls to keep the middle of the room open.")]
    if any(i.category == "desk" for i in items):
        out.append(Strategy("work_zone", "Work zone", "The desk gets its own wall (by a window when one is located), apart from the sleeping or seating area."))
    else:
        out.append(Strategy("centered", "Centered focal piece", "The main piece is centered on its wall, with storage pushed to the corners."))
    out.append(Strategy("alternate_wall", "Alternate wall", "The main piece moves to a different wall to open up another part of the room."))
    return out


def _corner_dist(t: float, a: float, L: float) -> float:
    return min(t, max(L - a - t, 0.0))


def _opposite(wall: str) -> str:
    return {"north": "south", "south": "north", "east": "west", "west": "east"}[wall]


def _score(strategy: Strategy, item: Item, wall: str, t: float, a: float, frame: RoomFrame, ctx: dict) -> float:
    L = _wall_len(wall, frame.W, frame.D)
    primary = item.ref == ctx.get("primary_ref")
    if strategy.key == "open_center":
        return _corner_dist(t, a, L)
    if strategy.key == "centered":
        return abs((t + a / 2) - L / 2) if primary else _corner_dist(t, a, L)
    if strategy.key == "work_zone":
        s = 0.0
        if item.category == "desk":
            if frame.window_walls:
                s += 0 if wall in frame.window_walls else 120
            elif ctx.get("primary_wall"):
                s += 0 if wall == _opposite(ctx["primary_wall"]) else (60 if wall != ctx["primary_wall"] else 400)
            return s + _corner_dist(t, a, L) * 0.3
        if primary and frame.window_walls:
            s += 80 if wall in frame.window_walls else 0
        return s + _corner_dist(t, a, L)
    s = 1000.0 if (primary and wall == ctx.get("baseline_primary_wall")) else 0.0  # alternate_wall
    return s + _corner_dist(t, a, L) + WALLS[::-1].index(wall) * 0.01


def _place_on_wall(strategy, item, frame, placed, ctx) -> Placed | None:
    best = None
    for wall in WALLS:
        L = _wall_len(wall, frame.W, frame.D)
        for a, b, mode in _orientations(item):
            for t in _positions(L, a):
                rect = _wall_rect(wall, t, a, b, frame.W, frame.D)
                if mode == "head":
                    left, right = _sides(wall, rect, ACCESS_IN["bed_frame"], BED_HEAD_ZONE_IN)
                    options = [[left, right]] if item.shared else [[left], [right], [left, right]]
                else:
                    f = _front(wall, rect, ACCESS_IN.get(item.category, 24))
                    options = [[f] if f else []]
                open_rect = _open_rect(item, wall, rect, t, a, b, frame)
                for clears in options:
                    if not _valid(rect, clears, frame, placed):
                        continue
                    sc = _score(strategy, item, wall, t, a, frame, ctx) + len(clears) * 0.001
                    if open_rect is not None and _open_blockers(open_rect, frame, placed)[0]:
                        sc += 500  # prefer spots where it can actually open
                    key = (sc, WALLS.index(wall), t, mode)
                    if best is None or key < best[0]:
                        best = (key, Placed(item, rect, wall, list(clears), open_rect, t, a))
    return best[1] if best else None


def _place_nightstand(item, frame, placed) -> Placed | None:
    bed = next((p for p in placed if p.item.category == "bed_frame" and abs(p.along_len - p.item.width) < EPS), None)
    if not bed:
        return None
    a, b = max(item.width, item.depth), min(item.width, item.depth)
    if b > BED_HEAD_ZONE_IN:  # would intrude into the bed's side access zone
        return None
    L = _wall_len(bed.wall, frame.W, frame.D)
    for t in (bed.along - a, bed.along + bed.along_len):
        if t < -EPS or t + a > L + EPS:
            continue
        rect = _wall_rect(bed.wall, t, a, b, frame.W, frame.D)
        if _valid(rect, [], frame, placed):
            return Placed(item, rect, bed.wall, [], None, t, a)
    return None


def _place_coffee_table(item, frame, placed) -> Placed | None:
    sofa = next((p for p in placed if p.item.category in ("sofa", "sofa_bed")), None)
    a, b = max(item.width, item.depth), min(item.width, item.depth)
    if sofa:
        x, y, w, d = sofa.rect
        for shift in (0.0, -12.0, 12.0):
            if sofa.wall in ("north", "south"):
                rect = (x + (w - a) / 2 + shift, y + d + COFFEE_GAP_IN if sofa.wall == "north" else y - COFFEE_GAP_IN - b, a, b)
            else:
                rect = (x + w + COFFEE_GAP_IN if sofa.wall == "west" else x - COFFEE_GAP_IN - b, y + (d - a) / 2 + shift, b, a)
            if _valid(rect, [], frame, placed):
                return Placed(item, rect, "free", [], None)
    for yy in _positions(frame.D, b):
        for xx in _positions(frame.W, a):
            rect = (xx, yy, a, b)
            g = _grow(rect, FREE_CLEAR_IN)
            if not _inside(g, frame.W, frame.D) or any(_overlap(g, p.rect) for p in placed):
                continue
            if _valid(rect, [], frame, placed):
                return Placed(item, rect, "free", [], None)
    return None


def _place_all(strategy: Strategy, items: list[Item], frame: RoomFrame, ctx: dict) -> tuple[list[Placed], list[Unplaced]]:
    placed: list[Placed] = []
    unplaced: list[Unplaced] = []
    for item in items:
        p = None
        if item.category == "nightstand":
            p = _place_nightstand(item, frame, placed)
        if item.category == "coffee_table":
            p = _place_coffee_table(item, frame, placed)
        elif p is None:
            p = _place_on_wall(strategy, item, frame, placed, ctx)
        if p is None:
            fits = any((o[0] <= frame.W + EPS and o[1] <= frame.D + EPS) or (o[0] <= frame.D + EPS and o[1] <= frame.W + EPS)
                       for o in _orientations(item))
            reason = ("Larger than the room outline in every orientation." if not fits else
                      "No position found that avoids other footprints, access zones and fixed zones.")
            unplaced.append(Unplaced(ref=item.ref, label=item.label, reason=reason))
        else:
            placed.append(p)
            if item.ref == ctx.get("primary_ref"):
                ctx["primary_wall"] = p.wall
    return placed, unplaced


# ------------------------------------------------------------------ independent re-check
def verify(placements: list[Placement], env_w: float, env_d: float, zones: list[FixedZone]) -> list[str]:
    problems = []
    rects = [(p.ref, (p.x, p.y, p.w, p.d)) for p in placements]
    for p in placements:
        r = (p.x, p.y, p.w, p.d)
        if not _inside(r, env_w, env_d):
            problems.append(f"{p.ref} outside outline")
        for z in zones:
            if _overlap(r, (z.x, z.y, z.w, z.d)):
                problems.append(f"{p.ref} overlaps fixed zone {z.label}")
        for c in p.clearances:
            if not _inside(tuple(c), env_w, env_d):
                problems.append(f"{p.ref} access zone outside outline")
    for i in range(len(rects)):
        for j in range(len(rects)):
            if i == j:
                continue
            if i < j and _overlap(rects[i][1], rects[j][1]):
                problems.append(f"{rects[i][0]} overlaps {rects[j][0]}")
            if any(_overlap(rects[i][1], tuple(c)) for c in placements[j].clearances):
                problems.append(f"{rects[i][0]} sits in the access zone of {rects[j][0]}")
    return problems


# ------------------------------------------------------------------ public entry point
def generate_layouts(plan: Plan, catalog_by_id: dict, prefs: Preferences, frame: RoomFrame) -> LayoutSet:
    common = dict(method_version=LAYOUT_METHOD, room_version_id=frame.room_version_id,
                  floorplan_source_ids=frame.floorplan_source_ids, wall_descriptions=frame.wall_descriptions,
                  geometry_source_ids=frame.source_ids, missing_views=frame.missing_views)
    if frame.basis == "unavailable":
        return LayoutSet(basis="unavailable", envelope_width_in=0, envelope_depth_in=0,
                         envelope_label="Room not mapped yet", notes=[frame.reason], **common)
    items, assoc, pre_unplaced = _items_from_plan(plan, catalog_by_id, prefs)
    fixed = [FixedZone(label=z.label, x=round(z.rect[0], 2), y=round(z.rect[1], 2), w=round(z.rect[2], 2),
                       d=round(z.rect[3], 2), assumption=z.assumption) for z in frame.zones]
    results, baseline_wall = [], None
    for strat in strategies_for(items):
        ctx = {"primary_ref": items[0].ref if items else None, "baseline_primary_wall": baseline_wall}
        placed, unplaced = _place_all(strat, items, frame, ctx)
        if strat.key == "open_center":
            baseline_wall = next((p.wall for p in placed if p.item.ref == ctx["primary_ref"]), None)
        results.append((strat, placed, unplaced))

    outline_name = {"scaled_room_lower_bound": "confirmed-size outline (lower bound)",
                    "estimated_from_photos": "photo-estimated outline", "estimated_from_plan": "plan-estimated outline",
                    "synthetic_demo": "synthetic demo outline"}[frame.basis]
    arrangements, seen, notes = [], set(), []
    for strat, placed, unplaced in results:
        pl = [Placement(ref=p.item.ref, label=p.item.label, category=p.item.category, kind=p.item.kind,
                        x=round(p.rect[0], 2), y=round(p.rect[1], 2), w=round(p.rect[2], 2), d=round(p.rect[3], 2),
                        zone=p.item.zone, wall=WALL_ID.get(p.wall, "free"), rotation=ROTATION.get(p.wall, 0),
                        clearances=[[round(v, 2) for v in c] for c in p.clear],
                        open_extent=[round(v, 2) for v in p.open_rect] if p.open_rect else None) for p in placed]
        sig = "|".join(sorted(f"{p.ref}:{p.wall}:{round(p.x / 12)}:{round(p.y / 12)}:{round(p.w)}x{round(p.d)}" for p in pl))
        if sig in seen:
            continue
        problems = verify(pl, frame.W, frame.D, fixed)
        if problems:
            notes.append(f"{strat.title} was discarded by the safety re-check ({problems[0]}).")
            continue
        seen.add(sig)
        checks, unresolved = [], []
        if pl:
            checks += [f"All {len(pl)} drawn footprints lie inside the {outline_name}.",
                       "No drawn footprints overlap each other.",
                       "No footprint sits in another item's assumed access zone (re-checked)."]
            if fixed:
                checks.append("Footprints stay out of the " + ", ".join(sorted({z.label for z in fixed})) + ".")
        unresolved.append({"scaled_room_lower_bound": "Drawn at the lower bound of the confirmed size; exact wall lengths may be larger.",
                           "estimated_from_photos": "Room outline and feature positions are estimated from photos: dimensions unverified.",
                           "estimated_from_plan": "Room size estimated from a printed floor-plan reading: your unit may differ.",
                           "synthetic_demo": "Synthetic demo room: fixture geometry, not a real room."}[frame.basis])
        unresolved += frame.unresolved
        for p in placed:
            if p.item.category in ("sofa_bed", "daybed"):
                if not p.item.open_known:
                    unresolved.append(f"{p.item.label}: opened sleeping size not documented, so its open extent is unverified.")
                elif p.open_rect is not None:
                    blocked, tables = _open_blockers(p.open_rect, frame, [q for q in placed if q is not p])
                    if blocked:
                        unresolved.append(f"{p.item.label}: opened (conservative depth) it would hit a wall, fixed zone or furniture here.")
                    elif tables:
                        unresolved.append(f"{p.item.label}: opens clear of walls and fixed zones only if the {', '.join(tables)} is moved; "
                                          "where it goes is not checked.")
                    else:
                        checks.append(f"{p.item.label}: opened (conservative depth) stays clear of walls, fixed zones and furniture.")
        all_unplaced = pre_unplaced + unplaced
        if all_unplaced:
            unresolved.append(f"{len(all_unplaced)} item(s) not drawn — see the list.")
        unresolved += ["Walking routes and accessibility are not verified: this is a rectangle collision check only.",
                       "Windows, outlets and vents are not modeled as obstacles."]
        arrangements.append(Arrangement(key=strat.key, title=strat.title, intent=strat.intent, placements=pl, associated=assoc,
                                        unplaced=all_unplaced, checks_passed=checks, unresolved=unresolved, signature=sig))
    if len(arrangements) < len(results):
        notes.append(f"{len(arrangements)} distinct arrangement(s) found; identical ones were merged.")
    return LayoutSet(
        basis=frame.basis, envelope_width_in=frame.W, envelope_depth_in=frame.D, envelope_label=frame.label,
        width_range_in=list(frame.width_range) if frame.width_range else None,
        depth_range_in=list(frame.depth_range) if frame.depth_range else None,
        envelope_hash=frame.hash, fixed_zones=fixed, wall_markers=[WallMarker(**m) for m in frame.markers],
        assumptions=frame.assumptions + ASSUMPTIONS,
        arrangements=arrangements, notes=notes, **common,
    )
