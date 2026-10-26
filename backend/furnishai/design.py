"""Design-first apartment furnishing on ONE selected floor-plan map (deterministic; no AI call).

Order: plan map (fixed) -> concept furniture arranged on it -> real products per piece -> final checklist.
- Concept pieces are typical-size placeholders by category and bed size (CONCEPT_IN), clearly labelled as such
  until a real product is chosen. They are sized with the map's scale (printed room sizes) or, without one, a
  relative drawing scale that never yields fit claims.
- Arrangements are deterministic placements on the SAME fixed map. Walls, rooms and fixtures are never moved or
  resized by furniture edits. Kitchen/bath/closet/balcony areas, fixtures and rooms whose read use is contradicted
  by what was seen in them are not furnishable; identified door areas and each piece's access space are kept clear.
  Big pieces are backed against a credible wall (never an open split between zones). A piece with no valid spot goes
  to the "Not placed" tray with its reason; nothing is ever shrunk or drawn at an impossible spot. Manual moves are
  free and get warnings.
- A real product replaces the concept footprint with its listed width x depth at the same position/rotation, and
  is re-checked; a larger product shows a conflict, never a smaller drawing.
- Totals count only chosen products. A piece without a product (e.g. no verified king bed saved) stays visible as
  missing, and the design is "incomplete" until every purchasable piece has a product or is marked as owned.
"""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from .catalog import is_stale, mattress_compatibility
from .planmap import PlanMap, SLEEP_KINDS, area, bbox, point_in_poly, room_uses, segments_cross, usable
from .planner import UNAVAILABLE, _filtered
from .resale import listing_key, resale_site, retailer_site
from .models import Preferences

DESIGN_METHOD = "design-v1"
Rotation = Literal[0, 90, 180, 270]
BedSize = Literal["twin", "full", "queen", "king"]

# Typical footprints (width x depth, inches) for DRAFT pieces. Not product facts; replaced by a chosen product's
# listed dimensions.
BED_IN = {"twin": (41.0, 80.0), "full": (56.0, 80.0), "queen": (64.0, 84.0), "king": (80.0, 84.0)}
CONCEPT_IN = {
    "nightstand": (20.0, 16.0), "dresser": (48.0, 18.0), "desk": (48.0, 24.0), "desk_chair": (0.0, 0.0),
    "sofa": (84.0, 36.0), "sofa_bed": (80.0, 38.0), "daybed": (41.0, 80.0), "coffee_table": (40.0, 20.0),
    "bookcase": (32.0, 14.0), "wardrobe": (40.0, 24.0), "mattress": (0.0, 0.0),
    # Added types (typical draft sizes; a chosen product's listed width x depth replaces them).
    "tv": (0.0, 0.0),  # sits on its TV stand: no floor footprint of its own
    "tv_stand": (60.0, 16.0), "dining_table": (48.0, 30.0), "dining_chair": (18.0, 20.0), "armchair": (32.0, 32.0),
    "side_table": (20.0, 20.0), "ottoman": (24.0, 18.0), "console_table": (42.0, 14.0), "shoe_storage": (36.0, 14.0),
    "floor_lamp": (14.0, 14.0),
}
SLEEP_SET = ("bed_frame", "mattress", "nightstand")
STORAGE = ("dresser", "wardrobe")
LIVING = ("sofa", "sofa_bed", "daybed", "coffee_table", "bookcase", "desk", "desk_chair")
ATTACHED = {"mattress": "bed_frame", "desk_chair": "desk", "tv": "tv_stand"}  # no footprint: on the bed / at the desk / on the stand
NEEDS_HOST = {"tv": "Needs a TV stand: add one (or choose which stand) — a TV isn’t placed on the floor by itself."}
DINING = ("dining_table", "dining_chair")
CATEGORY_NAME = {"bed_frame": "bed frame", "mattress": "mattress", "nightstand": "nightstand", "dresser": "dresser",
                 "desk": "desk", "desk_chair": "desk chair", "sofa": "sofa", "sofa_bed": "sofa bed", "daybed": "daybed",
                 "coffee_table": "coffee table", "bookcase": "bookcase", "wardrobe": "wardrobe", "tv": "TV",
                 "tv_stand": "TV stand", "dining_table": "dining table", "dining_chair": "dining chair",
                 "armchair": "armchair", "side_table": "side table", "ottoman": "ottoman", "console_table": "console table",
                 "shoe_storage": "shoe rack / storage bench", "floor_lamp": "floor lamp"}
GAP_IN = 2.0
DOOR_CLEAR_MAX_IN = 40.0
ARRANGEMENTS = [
    ("walls", "Against the walls", "Big pieces backed onto walls, away from doors; the middle stays open."),
    ("long_wall", "Along the long walls", "Beds, sofas and storage line each room’s longest wall."),
    ("corners", "Tucked into corners", "Pieces sit in corners, leaving one side of each room clear."),
]


def piece_name(category: str, size: str | None = None) -> str:
    base = CATEGORY_NAME.get(category, category.replace("_", " "))
    return f"{size} {base}" if size and category in ("bed_frame", "mattress") else base


# ------------------------------------------------------------------ design model
class DesignPrefs(BaseModel):
    budget_cents: int | None = Field(default=None, ge=0, le=5_000_000)
    reserve_pct: int = Field(default=10, ge=0, le=40)
    approach: Literal["low", "use"] = "use"  # keep costs low / use my budget for better matches
    styles: list[str] = Field(default_factory=list, max_length=6)
    condition: Literal["new", "secondhand", "either"] = "either"
    bed_size: BedSize = "queen"
    retailers: list[str] = Field(default_factory=list, max_length=8)
    categories: list[str] = Field(default_factory=list, max_length=12)
    # Shopping scope lives HERE (one source of truth for the design flow): how you'll get it and when you'd like it.
    # Timing is a preference, never a promised delivery date.
    fulfillment: Literal["either", "local_pickup", "delivery"] = "either"
    timing: str = Field(default="", max_length=60)
    # Approved resale marketplaces to search/check for secondhand (empty = all approved; see resale.py).
    resale_sites: list[Literal["aptdeco", "chairish", "ebay", "facebook", "craigslist"]] = Field(default_factory=list, max_length=5)


class DesignItem(BaseModel):
    id: str
    category: str
    zone_id: str | None = None
    x: float = Field(ge=0, le=1)  # piece center, normalized to the plan image
    y: float = Field(ge=0, le=1)
    rotation: Rotation = 0
    size: BedSize | None = None  # bed frames/mattresses
    on_item: str | None = None  # mattress -> its bed, desk chair -> its desk
    product_id: str | None = None
    owned: bool = False  # the user already has this piece: no purchase
    placed: bool = True  # False: in the "Not placed" tray (not drawn, not checked; still in the design and lists)
    unplaced_reason: str | None = Field(default=None, max_length=200)


class Design(BaseModel):
    plan_source_id: str
    plan_map_id: str | None = None
    arrangement: str | None = None
    items: list[DesignItem] = Field(default_factory=list, max_length=60)
    prefs: DesignPrefs = Field(default_factory=DesignPrefs)


def new_item_id() -> str:
    return "pc_" + uuid.uuid4().hex[:12]


def prefs_from_room(p: Preferences) -> DesignPrefs:
    return DesignPrefs(budget_cents=p.budget_cents, reserve_pct=p.reserve_pct,
                       approach="low" if p.budget_approach == "save" else "use", styles=list(p.styles),
                       condition=p.condition, bed_size=p.bed_size if p.bed_size != "any" else "queen",
                       retailers=list(p.retailers), categories=[])
    # categories stay empty: a whole-place design starts from a starter set per observed space, not from one old
    # room's shopping list (that room's preferences and history are unchanged).


def as_preferences(dp: DesignPrefs, size: str | None) -> Preferences:
    return Preferences(budget_cents=dp.budget_cents, reserve_pct=dp.reserve_pct, styles=[s for s in dp.styles if s in _STYLES],
                       condition=dp.condition, bed_size=size or "any", retailers=dp.retailers)


_STYLES = {"minimal", "scandinavian", "modern", "traditional", "rustic", "mid_century", "industrial", "warm_wood",
           "light_neutral", "dark", "soft"}


# ------------------------------------------------------------------ footprints
def concept_in(item: DesignItem) -> tuple[float, float]:
    if item.category == "bed_frame":
        return BED_IN[item.size or "queen"]
    if item.category == "mattress" and item.on_item is None:
        w, d = BED_IN[item.size or "queen"]
        return w - 4, d - 4
    return CONCEPT_IN.get(item.category, (30.0, 20.0))


def footprint_in(item: DesignItem, by_id: dict) -> tuple[float, float, bool]:
    """(width, depth, is_actual). A chosen product's listed size, else the draft size. Never shrunk."""
    p = by_id.get(item.product_id) if item.product_id else None
    if p and p.get("width_in") and p.get("depth_in") and item.on_item is None:
        return float(p["width_in"]), float(p["depth_in"]), True
    w, d = concept_in(item)
    return w, d, False


Rect = tuple[float, float, float, float]


def rect_of(cx: float, cy: float, w_px: float, d_px: float, rot: int) -> Rect:
    a, b = (w_px, d_px) if rot in (0, 180) else (d_px, w_px)
    return cx - a / 2, cy - b / 2, cx + a / 2, cy + b / 2


def _corners(r: Rect) -> list[tuple[float, float]]:
    return [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]


def _edges(poly) -> list:
    return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]


def rect_in_poly(r: Rect, poly) -> bool:
    """All corners inside and no polygon edge crosses the rectangle (works for non-convex rooms)."""
    e = min(0.5, (r[2] - r[0]) / 4, (r[3] - r[1]) / 4)  # touching a wall counts as inside (sub-pixel tolerance)
    r = (r[0] + e, r[1] + e, r[2] - e, r[3] - e)
    if not all(point_in_poly(c, poly) for c in _corners(r)):
        return False
    re_ = _edges(_corners(r))
    for a, b in _edges(poly):
        if any(segments_cross(a, b, c, d) for c, d in re_):
            return False
        if r[0] + 1e-6 < a[0] < r[2] - 1e-6 and r[1] + 1e-6 < a[1] < r[3] - 1e-6:
            return False  # a reflex vertex pokes into the piece
    return True


TOUCH_EPS = 1e-6  # px: touching a shared boundary is not an overlap (far below any meaningful penetration)


def rects_overlap(a: Rect, b: Rect, gap: float = 0.0) -> bool:
    g = gap - TOUCH_EPS
    return a[0] < b[2] + g and b[0] < a[2] + g and a[1] < b[3] + g and b[1] < a[3] + g


def rect_poly_overlap(r: Rect, poly) -> bool:
    r = (r[0] + TOUCH_EPS, r[1] + TOUCH_EPS, r[2] - TOUCH_EPS, r[3] - TOUCH_EPS)
    if any(point_in_poly(c, poly) for c in _corners(r)):
        return True
    if any(r[0] < p[0] < r[2] and r[1] < p[1] < r[3] for p in poly):
        return True
    re_ = _edges(_corners(r))
    return any(segments_cross(a, b, c, d) for a, b in _edges(poly) for c, d in re_)


def door_rects(m: PlanMap) -> list[tuple[str, Rect]]:
    """Clear area in front of/behind each identified door or opening (swing side unknown, so both sides)."""
    out = []
    cap = DOOR_CLEAR_MAX_IN * m.scale.ppi
    for o in m.openings:
        if o.kind == "window":
            continue
        (x1, y1), (x2, y2) = o.a, o.b
        L = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        e = min(L, cap)
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        x0, y0, xa, ya = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
        if dx >= 2 * dy:
            out.append((o.id, (x0, y0 - e, xa, ya + e)))
        elif dy >= 2 * dx:
            out.append((o.id, (x0 - e, y0, xa + e, ya)))
        else:
            out.append((o.id, (x0 - e / 2, y0 - e / 2, xa + e / 2, ya + e / 2)))
    return out


def blocked_areas(m: PlanMap) -> list[tuple[str, list]]:
    """Fixed, non-furnishable areas: fixtures, rooms such as kitchen, bath, closet, balcony, and rooms whose read use is
    contradicted by what was seen in them (e.g. a "bedroom" with a toilet and shower)."""
    out = [(f"{f.kind.replace('_', ' ')}", f.polygon) for f in m.fixtures]
    out += [(r.label or r.kind, r.polygon) for r in m.rooms if not usable(m, r)]
    return out


# ------------------------------------------------------------------ checks
HARD, SOFT = "hard", "soft"


def check_items(m: PlanMap, items: list[DesignItem], by_id: dict) -> dict[str, list[str]]:
    """Warnings per PLACED piece (never auto-fixed). Pieces in the "Not placed" tray aren't drawn or checked."""
    return {k: [msg for _, msg in v] for k, v in check_tagged(m, items, by_id).items()}


def hard_conflicts(m: PlanMap, items: list[DesignItem], by_id: dict) -> dict[str, list[str]]:
    """Only the PHYSICAL problems: outside its room or the map, on a fixed area (kitchen, bath, closet...), in a door's
    clear area, overlapping another piece, or a mattress that doesn't fit its frame. Soft notes (larger than the draft,
    room use unconfirmed, TV wider than its stand) are not here."""
    return {k: [msg for kind, msg in v if kind == HARD] for k, v in check_tagged(m, items, by_id).items()}


def check_tagged(m: PlanMap, items: list[DesignItem], by_id: dict) -> dict[str, list[tuple[str, str]]]:
    """(kind, message) per piece; kind is HARD (a physical conflict) or SOFT (a note to check)."""
    W, H, ppi = m.image_w, m.image_h, m.scale.ppi
    rects: dict[str, Rect] = {}
    out: dict[str, list[tuple[str, str]]] = {}
    uses = room_uses(m) if m.status == "mapped" else {}
    for it in items:
        out[it.id] = []
        if it.on_item or not it.placed:
            continue
        w, d, _ = footprint_in(it, by_id)
        if w <= 0 or d <= 0:
            continue
        rects[it.id] = rect_of(it.x * W, it.y * H, w * ppi, d * ppi, it.rotation)
    doors = door_rects(m)
    blocks = blocked_areas(m)
    ids = list(rects)
    for i, iid in enumerate(ids):
        r = rects[iid]
        it = next(x for x in items if x.id == iid)
        zone = m.room(it.zone_id)
        if m.status == "mapped":
            if zone is None:
                out[iid].append((HARD, "Not in a room on the map."))
            elif not rect_in_poly(r, zone.polygon):
                out[iid].append((HARD, f"Extends outside {zone.label or 'its room'}."))
            if zone is not None and uses.get(zone.id) and uses[zone.id].status == "uncertain":
                out[iid].append((SOFT, "This room’s use isn’t confirmed yet."))
            for name, poly in blocks:
                if rect_poly_overlap(r, poly):
                    out[iid].append((HARD, f"Overlaps the {name.lower()} (a fixed area)."))
                    break
            if any(rects_overlap(r, dr) for _, dr in doors):
                out[iid].append((HARD, "Sits in a door’s clear area."))
        elif not (0 <= r[0] and 0 <= r[1] and r[2] <= W and r[3] <= H):
            out[iid].append((HARD, "Extends past the plan image."))
        for jid in ids[i + 1:]:
            if rects_overlap(r, rects[jid]):
                other = next(x for x in items if x.id == jid)
                out[iid].append((HARD, f"Overlaps the {piece_name(other.category)}."))
                out[jid].append((HARD, f"Overlaps the {piece_name(it.category)}."))
    for it in items:
        p = by_id.get(it.product_id) if it.product_id else None
        if p and it.on_item is None and it.placed:
            cw, cd = concept_in(it)
            if (p.get("width_in") or 0) > cw + 0.5 or (p.get("depth_in") or 0) > cd + 0.5:
                out[it.id].append((SOFT, "The chosen product is larger than the draft piece; check the space around it."))
        if it.category == "mattress" and p and it.on_item:
            bed = next((x for x in items if x.id == it.on_item), None)
            frame = by_id.get(bed.product_id) if bed and bed.product_id else None
            if frame and mattress_compatibility(p, frame) == "incompatible":
                out[it.id].append((HARD, "This mattress’s listed size doesn’t match the chosen bed frame."))
        if it.category == "tv" and it.on_item:
            stand = next((x for x in items if x.id == it.on_item), None)
            sp = by_id.get(stand.product_id) if stand and stand.product_id else None
            sw = (sp or {}).get("width_in") or (concept_in(stand)[0] if stand else None)
            tw = (p or {}).get("width_in")  # the TV's LISTED overall width, never its diagonal screen size
            if tw and sw and tw > sw + 0.5:
                out[it.id].append((SOFT, f"This TV ({tw:g} in wide) is wider than its stand ({sw:g} in"
                                  f"{'' if sp else ', draft size'}); check it’s stable or choose a wider stand."))
    return out


# ------------------------------------------------------------------ starter pieces
BED_SET = ("bed_frame", "mattress", "nightstand", "dresser")


def default_pieces(m: PlanMap, prefs: DesignPrefs) -> list[DesignItem]:
    """Starter concept pieces per observed space (positions are set by `arrange`).
    - ONE bed set per CONFIRMED bedroom/sleeping zone (2 confirmed bedrooms = 2 sets, distinct instance ids). A zone
      whose use is uncertain or contradicted (e.g. a low-confidence unlabelled "bedroom", or one with bath fixtures)
      is never seeded. With no confirmed sleep zone, an open studio space gets ONE set; if the only sleep zones are
      uncertain, one set is added to the "Not placed" tray until the user sets a room's use.
    - A sofa + coffee table in the largest usable living/dining/studio zone.
    Explicit categories restrict the set. The user can add or remove pieces afterwards."""
    uses = room_uses(m)
    furn = sorted([r for r in m.rooms if usable(m, r)], key=lambda r: -r.area_px)
    cats = list(dict.fromkeys(prefs.categories))
    sleep = [r for r in furn if r.kind in SLEEP_KINDS and uses[r.id].status == "confirmed"]
    unsure_sleep = [r for r in furn if r.kind in SLEEP_KINDS and uses[r.id].status != "confirmed"]
    living = [r for r in furn if r.kind not in SLEEP_KINDS and uses[r.id].status == "confirmed"]
    studio = [r for r in living if r.kind == "studio"]
    if not cats:
        cats = (list(BED_SET) if (sleep or studio or unsure_sleep or not living) else []) + (
            ["sofa", "coffee_table"] if living else [])
    main_living = living[0] if living else None
    tray = False
    if sleep:
        bed_zones = sleep
    elif studio:
        bed_zones = studio[:1]
    elif unsure_sleep or not main_living:
        bed_zones, tray = [None], True
    else:
        bed_zones = [main_living]
    items: list[DesignItem] = []

    def add(cat: str, zone, **kw) -> DesignItem:
        it = DesignItem(id=new_item_id(), category=cat, zone_id=zone.id if zone else None, x=0.5, y=0.5,
                        placed=False, unplaced_reason=None, **kw)
        items.append(it)
        return it

    for z in bed_zones:
        bed = add("bed_frame", z, size=prefs.bed_size) if "bed_frame" in cats else None
        if "mattress" in cats:
            add("mattress", z, size=prefs.bed_size, on_item=bed.id if bed else None)
        if "nightstand" in cats:
            add("nightstand", z)
        for c in STORAGE:
            if c in cats:
                add(c, z)
    for c in LIVING:
        if c in cats and (main_living or c not in ("sofa", "coffee_table")):
            if c == "desk_chair":
                desk = next((i for i in items if i.category == "desk"), None)
                add(c, main_living, on_item=desk.id if desk else None)
                continue
            add(c, main_living)
    # Added types only when explicitly requested (never in the automatic starter set).
    dining = next((r for r in furn if r.kind == "dining"), None) or main_living
    for c in cats:
        if c in BED_SET or c in STORAGE or c in LIVING or c not in CONCEPT_IN:
            continue
        if c == "tv":  # on a free TV stand, else waiting in Not placed (never a floor footprint)
            free = [i for i in items if i.category == "tv_stand" and not any(t.on_item == i.id for t in items)]
            stand = free[0] if len(free) == 1 else None  # several free stands: the user picks one
            if stand:
                add(c, None, on_item=stand.id)
                items[-1] = items[-1].model_copy(update={"zone_id": stand.zone_id})
            else:
                add(c, None)
                items[-1] = items[-1].model_copy(update={"unplaced_reason": NEEDS_HOST["tv"]})
            continue
        add(c, dining if c in DINING else main_living)
    if tray:
        for i, it in enumerate(items):
            if it.zone_id is None:
                items[i] = it.model_copy(update={"unplaced_reason": "No confirmed bedroom on this plan yet: set a room’s "
                                                 "use to Bedroom, or place it yourself."})
    return items


# ------------------------------------------------------------------ placement engine
ACCESS_IN = {"tv_stand": 24.0, "dining_table": 30.0, "armchair": 18.0, "console_table": 18.0, "shoe_storage": 18.0,
             "bed_frame": 24.0, "daybed": 24.0, "sofa": 30.0, "sofa_bed": 30.0, "dresser": 30.0, "wardrobe": 30.0,
             "desk": 30.0, "bookcase": 24.0}
BED_FOOT_IN, BED_HEAD_IN = 18.0, 20.0
BACKED = {"bed_frame", "daybed", "sofa", "sofa_bed", "dresser", "wardrobe", "bookcase", "desk", "nightstand",
          "tv_stand", "console_table", "shoe_storage", "armchair", "side_table", "floor_lamp"}
SLEEP_PIECES = {"bed_frame", "mattress", "nightstand", "daybed"}


def _seg_dist(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return ((p[0] - ax - t * dx) ** 2 + (p[1] - ay - t * dy) ** 2) ** 0.5


class Floor:
    """Fixed geometry for one map: usable rooms, blocked areas, door areas and each room's wall-like edges."""

    def __init__(self, m: PlanMap):
        self.m, self.ppi = m, m.scale.ppi
        self.W, self.H = m.image_w, m.image_h
        self.uses = room_uses(m)
        self.rooms = [r for r in m.rooms if usable(m, r)]
        self.doors = [d for _, d in door_rects(m)]
        self.blocks = [p for _, p in blocked_areas(m)]
        self.walls: dict[str, list] = {r.id: self._wall_edges(r) for r in self.rooms}

    def _wall_edges(self, zone) -> list:
        """Edges a headboard/sofa back can credibly stand against: physical walls, or a room boundary that isn't an
        OPEN split between zones of one open space."""
        out = []
        off = max(2.0, 3 * self.ppi)
        for a, b in _edges(zone.polygon):
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            L = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            if L < 1e-6:
                continue
            nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
            p1, p2 = (mx + nx * off, my + ny * off), (mx - nx * off, my - ny * off)
            outward = p2 if point_in_poly(p1, zone.polygon) else p1
            other = next((r for r in self.rooms if r.id != zone.id and point_in_poly(outward, r.polygon)), None)
            physical = any(_seg_dist((mx, my), w0, w1) <= off for w0, w1 in self.m.walls)
            if physical or other is None or not (zone.open_plan or other.open_plan):
                out.append((a, b))
        return out

    def on_floor(self, r: Rect) -> bool:
        """Circulation space: on some usable room's floor and clear of fixed areas."""
        e = min(0.5, (r[2] - r[0]) / 4, (r[3] - r[1]) / 4)
        cs = _corners((r[0] + e, r[1] + e, r[2] - e, r[3] - e))
        if not all(any(point_in_poly(c, z.polygon) for z in self.rooms) for c in cs):
            return False
        return not any(rect_poly_overlap(r, p) for p in self.blocks)


def _front(r: Rect, rot: int, d: float) -> Rect:
    x0, y0, x1, y1 = r
    return {0: (x0, y1, x1, y1 + d), 90: (x0 - d, y0, x0, y1), 180: (x0, y0 - d, x1, y0), 270: (x1, y0, x1 + d, y1)}[rot]


def _bed_sides(r: Rect, rot: int, s: float, head: float) -> list[Rect]:
    x0, y0, x1, y1 = r
    return {0: [(x0 - s, y0 + head, x0, y1), (x1, y0 + head, x1 + s, y1)],
            180: [(x0 - s, y0, x0, y1 - head), (x1, y0, x1 + s, y1 - head)],
            90: [(x0, y0 - s, x1 - head, y0), (x0, y1, x1 - head, y1 + s)],
            270: [(x0 + head, y0 - s, x1, y0), (x0 + head, y1, x1, y1 + s)]}[rot]


def _back_edge(r: Rect, rot: int):
    x0, y0, x1, y1 = r
    return {0: ((x0, y0), (x1, y0)), 90: ((x1, y0), (x1, y1)), 180: ((x0, y1), (x1, y1)), 270: ((x0, y0), (x0, y1))}[rot]


def _q(fl: "Floor", cx: float, cy: float) -> tuple[float, float]:
    """The exact pixel centre that will be saved (normalized to 5 decimals). Candidates are validated, scored and
    collided at THIS position, so what is checked is what is persisted."""
    return round(cx / fl.W, 5) * fl.W, round(cy / fl.H, 5) * fl.H


class _Placed:
    def __init__(self, item: DesignItem, rect: Rect, access: list[Rect]):
        self.item, self.rect, self.access = item, rect, access


def _try(fl: Floor, zone, cat: str, r: Rect, rot: int, placed: list[_Placed]) -> list[Rect] | None:
    """The access areas this spot keeps clear, or None if the spot is not acceptable."""
    ppi = fl.ppi
    gap = GAP_IN * ppi
    if not rect_in_poly(r, zone.polygon):
        return None
    if any(rect_poly_overlap(r, p) for p in fl.blocks) or any(rects_overlap(r, d) for d in fl.doors):
        return None
    for p in placed:
        if rects_overlap(r, p.rect, gap) or any(rects_overlap(r, a) for a in p.access):
            return None
    acc: list[Rect] = []
    need = ACCESS_IN.get(cat, 0.0) * ppi

    def free(a: Rect) -> bool:
        return fl.on_floor(a) and not any(rects_overlap(a, p.rect) for p in placed)

    if cat in ("bed_frame", "daybed"):
        foot = _front(r, rot, BED_FOOT_IN * ppi)
        sides = [s for s in _bed_sides(r, rot, need, BED_HEAD_IN * ppi) if free(s)]
        if not free(foot) or not sides:
            return None
        acc = [foot, sides[0]]
    elif need:
        f = _front(r, rot, need)
        if not free(f):
            return None
        acc = [f]
    return acc


def _wall_spots(fl: Floor, zone, wp: float, dp: float, step: float):
    """Positions with the piece's back flush against one of the zone's wall-like, axis-aligned edges."""
    for (a, b) in fl.walls.get(zone.id, []):
        horiz, vert = abs(a[1] - b[1]) <= 1.0, abs(a[0] - b[0]) <= 1.0
        if not (horiz or vert):
            continue
        if horiz:
            ey, lo, hi = (a[1] + b[1]) / 2, min(a[0], b[0]), max(a[0], b[0])
            inward = 1 if point_in_poly(((lo + hi) / 2, ey + 1.5), zone.polygon) else -1
            rot, cy = (0, ey + dp / 2) if inward > 0 else (180, ey - dp / 2)
            half = wp / 2
            t = lo + half
            while t <= hi - half + 1e-6:
                yield rot, t, cy, hi - lo, abs(t - (lo + hi) / 2)
                t += step
        else:
            ex, lo, hi = (a[0] + b[0]) / 2, min(a[1], b[1]), max(a[1], b[1])
            inward = 1 if point_in_poly((ex + 1.5, (lo + hi) / 2), zone.polygon) else -1
            rot, cx = (270, ex + dp / 2) if inward > 0 else (90, ex - dp / 2)
            half = wp / 2
            t = lo + half
            while t <= hi - half + 1e-6:
                yield rot, cx, t, hi - lo, abs(t - (lo + hi) / 2)
                t += step


def _grid_spots(zone, wp: float, dp: float, step: float):
    x0, y0, x1, y1 = bbox(zone.polygon)
    for rot in (0, 90, 180, 270):
        a, b = (wp, dp) if rot in (0, 180) else (dp, wp)
        yy = y0 + b / 2
        while yy <= y1 - b / 2 + 1e-6:
            xx = x0 + a / 2
            while xx <= x1 - a / 2 + 1e-6:
                yield rot, xx, yy, 0.0, 0.0
                xx += step
            yy += step


def _score(fl: Floor, strategy: str, zone, cat: str, r: Rect, rot: int, wall_len: float, off_center: float,
           acc: list[Rect]) -> float:
    ppi = fl.ppi
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    door_d = min((((cx - (d[0] + d[2]) / 2) ** 2 + (cy - (d[1] + d[3]) / 2) ** 2) ** 0.5 for d in fl.doors), default=1e9)
    s = 400.0 / (1 + door_d / ppi / 12)  # keep big pieces away from doors
    if cat in ("bed_frame", "daybed"):
        free_sides = sum(1 for a in _bed_sides(r, rot, ACCESS_IN[cat] * ppi, BED_HEAD_IN * ppi) if fl.on_floor(a))
        s -= 60.0 * free_sides  # a bed you can reach from both sides
    if strategy == "walls":
        s += off_center / ppi * 0.5
    elif strategy == "long_wall":
        s -= wall_len / ppi * 1.0
    else:  # corners
        s += min(min(abs(c[0] - v[0]) + abs(c[1] - v[1]) for v in zone.polygon) for c in _corners(r)) / ppi
    return s


def _place_one(fl: Floor, strategy: str, it: DesignItem, zone, by_id: dict, placed: list[_Placed]
               ) -> tuple[float, float, int, list[Rect]] | None:
    ppi = fl.ppi
    w, d, _ = footprint_in(it, by_id)
    wp, dp = w * ppi, d * ppi
    x0, y0, x1, y1 = bbox(zone.polygon)
    step = max(min(x1 - x0, y1 - y0) / 24, 2 * ppi)
    cat = it.category
    if cat == "nightstand":
        hit = _beside_bed(fl, zone, placed, wp, dp)
        if hit:
            return hit
    if cat == "dining_chair":
        hit = _beside_table(fl, zone, placed, wp, dp)
        if hit:
            return hit
    if cat == "coffee_table":
        hit = _before_sofa(fl, zone, placed, wp, dp)
        if hit:
            return hit
    spots = _wall_spots(fl, zone, wp, dp, step) if cat in BACKED else _grid_spots(zone, wp, dp, step)
    best = None
    for rot, cx, cy, wall_len, off in spots:
        cx, cy = _q(fl, cx, cy)
        r = rect_of(cx, cy, wp, dp, rot)
        acc = _try(fl, zone, cat, r, rot, placed)
        if acc is None:
            continue
        key = (round(_score(fl, strategy, zone, cat, r, rot, wall_len, off, acc), 3), rot, round(cx, 2), round(cy, 2))
        if best is None or key < best[0]:
            best = (key, (cx, cy, rot, acc))
    return best[1] if best else None


def _beside_bed(fl: Floor, zone, placed: list[_Placed], wp: float, dp: float):
    taken = sum(1 for p in placed if p.item.category == "nightstand" and p.item.zone_id == zone.id)
    for p in placed:
        if p.item.category not in ("bed_frame", "daybed") or p.item.zone_id != zone.id:
            continue
        x0, y0, x1, y1 = p.rect
        rot = p.item.rotation
        g = GAP_IN * fl.ppi + 0.5
        if rot in (0, 180):
            yy = y0 + dp / 2 if rot == 0 else y1 - dp / 2
            spots = [(x0 - g - wp / 2, yy), (x1 + g + wp / 2, yy)]
        else:
            xx = x1 - dp / 2 if rot == 90 else x0 + dp / 2
            spots = [(xx, y0 - g - wp / 2), (xx, y1 + g + wp / 2)]
        for cx, cy in spots[taken % 2:] + spots[:taken % 2]:
            cx, cy = _q(fl, cx, cy)
            r = rect_of(cx, cy, wp, dp, rot)
            others = [q for q in placed if q is not p] + [_Placed(p.item, p.rect, [a for a in p.access if not rects_overlap(a, r)])]
            if _try(fl, zone, "nightstand", r, rot, others) is not None:
                return cx, cy, rot, []
    return None


def _before_sofa(fl: Floor, zone, placed: list[_Placed], wp: float, dp: float):
    for p in placed:
        if p.item.category not in ("sofa", "sofa_bed") or p.item.zone_id != zone.id:
            continue
        x0, y0, x1, y1 = p.rect
        g = 18 * fl.ppi
        rot = p.item.rotation
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        a, b = (wp, dp) if rot in (0, 180) else (dp, wp)
        sx, sy = {0: (cx, y1 + g + b / 2), 180: (cx, y0 - g - b / 2), 90: (x0 - g - a / 2, cy), 270: (x1 + g + a / 2, cy)}[rot]
        sx, sy = _q(fl, sx, sy)
        r = rect_of(sx, sy, wp, dp, rot)
        others = [q for q in placed if q is not p] + [_Placed(p.item, p.rect, [])]  # the table sits in the sofa's front space
        if _try(fl, zone, "coffee_table", r, rot, others) is not None:
            return sx, sy, rot, []
    return None


def _beside_table(fl: Floor, zone, placed: list[_Placed], wp: float, dp: float):
    """A dining chair at the next free side of a dining table in the same room (pulled in, facing the table)."""
    g = 2 * fl.ppi
    for p in placed:
        if p.item.category != "dining_table" or p.item.zone_id != zone.id:
            continue
        x0, y0, x1, y1 = p.rect
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for sx, sy, rot in ((cx, y1 + g + dp / 2, 180), (cx, y0 - g - dp / 2, 0), (x1 + g + dp / 2, cy, 90),
                            (x0 - g - dp / 2, cy, 270)):
            sx, sy = _q(fl, sx, sy)
            r = rect_of(sx, sy, wp, dp, rot)
            others = [q for q in placed if q is not p] + [_Placed(p.item, p.rect, [])]  # chairs sit in the table's access
            if _try(fl, zone, "dining_chair", r, rot, others) is not None:
                return sx, sy, rot, []
    return None


def _auto_zone(fl: Floor, it: DesignItem, placed_items: list[DesignItem]):
    """A room for a piece without a usable one: a confirmed bedroom without a bed for sleep pieces, else the largest
    living area. None if there's no credible room."""
    rooms = sorted(fl.rooms, key=lambda r: -r.area_px)
    if it.category in SLEEP_PIECES or it.category in STORAGE:
        sleep = [r for r in rooms if r.kind in SLEEP_KINDS and fl.uses[r.id].status == "confirmed"]
        beds = {i.zone_id for i in placed_items if i.category == "bed_frame"}
        pick = next((r for r in sleep if r.id not in beds), sleep[0] if sleep else None)
        if pick or it.category in SLEEP_PIECES:
            return pick
    if it.category in DINING:
        dining = next((r for r in rooms if r.kind == "dining"), None)
        if dining:
            return dining
    return next((r for r in rooms if r.kind not in SLEEP_KINDS), None)


def arrange(m: PlanMap, items: list[DesignItem], strategy: str, by_id: dict) -> list[DesignItem]:
    """Deterministic positions for the given pieces on the fixed map (same instance ids, products, owned flags).
    A piece is placed only inside a usable room of the right kind, clear of fixed areas, door areas, other pieces and
    their access space (across ALL rooms), with big pieces backed against a credible wall. A piece with no such spot,
    or whose room's use isn't confirmed, goes to the "Not placed" tray with the reason; it is never drawn at an
    impossible spot. What sits on a piece (mattress, desk chair) follows it."""
    if m.status != "mapped":
        return unplace_all(items)
    fl = Floor(m)
    order = {"bed_frame": 0, "daybed": 1, "sofa_bed": 1, "sofa": 2, "dining_table": 2, "wardrobe": 3, "dresser": 4,
             "tv_stand": 4, "desk": 5, "bookcase": 6, "armchair": 6, "console_table": 6, "shoe_storage": 6, "nightstand": 7,
             "coffee_table": 8, "dining_chair": 8, "side_table": 8, "ottoman": 9, "floor_lamp": 9}
    out: dict[str, DesignItem] = {}
    placed: list[_Placed] = []
    for it in sorted((i for i in items if not i.on_item), key=lambda i: (order.get(i.category, 9), i.id)):
        zone = m.room(it.zone_id)
        reason = None
        if it.category in NEEDS_HOST:  # e.g. a TV with no stand: never a floor footprint
            out[it.id] = it.model_copy(update={"placed": False, "unplaced_reason": NEEDS_HOST[it.category]})
            continue
        if zone is None or not usable(m, zone):
            zone = _auto_zone(fl, it, [p.item for p in placed])
        if zone is None:
            reason = it.unplaced_reason or "No room on this plan suits it yet: set a room’s use, or choose a room for it."
        elif fl.uses[zone.id].status != "confirmed":
            reason = (f"{zone.label or 'This room'}’s use isn’t confirmed: set it under “Rooms on your plan”, or choose "
                      "another room.")
        hit = None if reason else _place_one(fl, strategy, it, zone, by_id, placed)
        if hit is None:
            out[it.id] = it.model_copy(update={"placed": False, "zone_id": zone.id if zone else it.zone_id,
                                               "unplaced_reason": reason or (
                                                   f"No spot in {zone.label or zone.kind} with clear access that avoids "
                                                   "fixed areas, doors and other furniture.")})
            continue
        cx, cy, rot, acc = hit
        new = it.model_copy(update={"x": round(cx / m.image_w, 5), "y": round(cy / m.image_h, 5), "rotation": rot,
                                    "zone_id": zone.id, "placed": True, "unplaced_reason": None})
        out[it.id] = new
        w, d, _ = footprint_in(new, by_id)
        placed.append(_Placed(new, rect_of(cx, cy, w * fl.ppi, d * fl.ppi, rot), acc))
    for it in items:
        if it.on_item:
            host = out.get(it.on_item)
            out[it.id] = it.model_copy(update={"x": host.x, "y": host.y, "zone_id": host.zone_id, "placed": host.placed,
                                               "unplaced_reason": host.unplaced_reason} if host else {})
    return [out.get(i.id, i) for i in items]


UNMAPPED_REASON = "Room boundaries could not be read; re-read or identify a usable room first."


def unplace_all(items: list[DesignItem]) -> list[DesignItem]:
    """Unreadable / unmapped plan: no automatic spatial suggestion at all. Every piece keeps its id, product, owned
    flag and what sits on it, and waits in "Not placed" with the reason. Nothing is painted onto the source image."""
    return [i.model_copy(update={"placed": False, "unplaced_reason": UNMAPPED_REASON}) for i in items]


def _conceptual_row(m: PlanMap, items: list[DesignItem], by_id: dict) -> list[DesignItem]:
    """Unmapped plan: pieces in a row across the image middle, for the user to drag (conceptual, no checks)."""
    out, x = [], 0.08
    for it in items:
        if it.on_item:
            continue
        w, _, _ = footprint_in(it, by_id)
        frac = min(0.3, w * m.scale.ppi / m.image_w)
        out.append(it.model_copy(update={"x": round(min(0.95, x + frac / 2), 5), "y": 0.5, "rotation": 0, "zone_id": None,
                                         "placed": True, "unplaced_reason": None}))
        x += frac + 0.03
    host = {i.id: i for i in out}
    res = []
    for it in items:
        if it.on_item:
            h = host.get(it.on_item)
            res.append(it.model_copy(update={"x": h.x, "y": h.y, "placed": True}) if h else it)
        else:
            res.append(host[it.id])
    return res


def arrangement_options(m: PlanMap, items: list[DesignItem], by_id: dict) -> list[dict]:
    opts = []
    if m.status != "mapped":
        return opts  # no alternatives to offer when the rooms couldn't be read
    for key, title, desc in ARRANGEMENTS:
        placed = arrange(m, items, key, by_id)
        warn = check_items(m, placed, by_id)
        opts.append({"key": key, "title": title if m.status == "mapped" else "Conceptual row",
                     "description": desc if m.status == "mapped" else "The plan couldn’t be mapped: pieces are lined up for you to drag onto the image.",
                     "items": [i.model_dump() for i in placed], "warnings": sum(len(v) for v in warn.values()),
                     "unplaced": sum(1 for i in placed if not i.placed and not i.on_item)})
    return opts


def zone_for_point(m: PlanMap, x: float, y: float) -> str | None:
    p = (x * m.image_w, y * m.image_h)
    hit = [r for r in m.rooms if usable(m, r) and point_in_poly(p, r.polygon)]
    return min(hit, key=lambda r: r.area_px).id if hit else None


def place_new(m: PlanMap, items: list[DesignItem], new: DesignItem, by_id: dict) -> DesignItem:
    """Find a spot for ONE piece in its room without moving any other piece; if there is none it goes to the
    "Not placed" tray with the reason (never an impossible spot)."""
    if m.status != "mapped":
        return new.model_copy(update={"placed": False, "unplaced_reason": UNMAPPED_REASON})
    if new.category in NEEDS_HOST and not new.on_item:
        return new.model_copy(update={"placed": False, "unplaced_reason": NEEDS_HOST[new.category]})
    zone = m.room(new.zone_id)
    if zone is None or not usable(m, zone):
        return new.model_copy(update={"placed": False, "unplaced_reason": "Choose a room you can furnish for it."})
    fl = Floor(m)
    placed = []
    for it in items:
        if it.on_item or not it.placed or it.id == new.id:
            continue
        w, d, _ = footprint_in(it, by_id)
        if w > 0:
            placed.append(_Placed(it, rect_of(it.x * m.image_w, it.y * m.image_h, w * fl.ppi, d * fl.ppi, it.rotation), []))
    hit = _place_one(fl, "walls", new, zone, by_id, placed)
    if hit is None:
        return new.model_copy(update={"placed": False, "unplaced_reason": (
            f"No spot in {zone.label or zone.kind} with clear access that avoids fixed areas, doors and other furniture.")})
    cx, cy, rot, _ = hit
    return new.model_copy(update={"x": round(cx / m.image_w, 5), "y": round(cy / m.image_h, 5), "rotation": rot,
                                  "placed": True, "unplaced_reason": None})


def _with_position(items: list[DesignItem], moved: DesignItem) -> list[DesignItem]:
    """`moved` replaces its piece; whatever sits on it (mattress, TV, desk chair) follows."""
    return [moved if i.id == moved.id else
            (i.model_copy(update={"x": moved.x, "y": moved.y, "zone_id": moved.zone_id}) if i.on_item == moved.id else i)
            for i in items]


def fit_for(item: DesignItem, product_id: str | None, items: list[DesignItem], m: PlanMap, by_id: dict) -> dict:
    """Would this product physically fit this piece in the CURRENT arrangement (all other pieces as they are)?
    - "fits": no hard conflict where the piece is.
    - "moved": a hard conflict there, but the same size fits at another spot in the SAME confirmed usable room
      (`move` = that spot); nothing else moves, sizes and scale are unchanged.
    - "conflict": no conflict-free spot in its room (hard conflicts listed).
    - "not_placed": the piece is in the "Not placed" tray (nothing to check yet).
    Soft notes are listed separately and never disqualify. On a plan without printed sizes the check is relative."""
    trial_item = item.model_copy(update={"product_id": product_id})
    trial = [trial_item if i.id == item.id else i for i in items]
    host = next((i for i in trial if i.id == item.on_item), None) if item.on_item else None
    if host is not None and not host.placed:
        return {"status": "not_placed", "hard": [], "soft": [], "move": None}
    tags = check_tagged(m, trial, by_id).get(item.id, []) if m.status == "mapped" else []
    hard = [x for k, x in tags if k == HARD]
    soft = [x for k, x in tags if k == SOFT]
    if not item.placed and not item.on_item:
        return {"status": "not_placed", "hard": [], "soft": soft, "move": None}
    if not hard:
        return {"status": "fits", "hard": [], "soft": soft, "move": None}
    zone = m.room(item.zone_id)
    if (m.status == "mapped" and item.on_item is None and zone is not None and usable(m, zone)
            and room_uses(m)[zone.id].status == "confirmed"):
        moved = place_new(m, trial, trial_item, by_id)
        if moved.placed:
            again = check_tagged(m, _with_position(trial, moved), by_id).get(item.id, [])
            if not any(k == HARD for k, _ in again):
                return {"status": "moved", "hard": hard, "soft": [x for k, x in again if k == SOFT],
                        "move": {"x": moved.x, "y": moved.y, "rotation": moved.rotation}}
    return {"status": "conflict", "hard": hard, "soft": soft, "move": None}


def remap_items(new: PlanMap, items: list[DesignItem], same_rooms: bool) -> list[DesignItem]:
    """Carry pieces to a NEW map of the same plan: same ids, products and owned flags. A placed piece takes the usable
    room under its position; with `same_rooms` (a room-use correction keeps room ids and outlines) an unplaced piece
    keeps its room if still usable. Others get no room and are re-placed or go to the "Not placed" tray."""
    out = []
    for it in items:
        z = zone_for_point(new, it.x, it.y) if (it.placed and new.status == "mapped") else None
        if z is None and same_rooms and it.zone_id and usable(new, new.room(it.zone_id)):
            z = it.zone_id
        out.append(it.model_copy(update={"zone_id": z}))
    return out


# ------------------------------------------------------------------ products, budget, checklist
def _style_matches(p: dict, styles: list[str]) -> list[str]:
    return sorted(set(p.get("curator_tags", [])) & set(styles))


# Small, reviewable taxonomy of CLOSELY related styles (soft ranking only; never a filter, never a product fact).
STYLE_NEAR = {
    "minimal": ["scandinavian", "modern", "light_neutral"], "scandinavian": ["minimal", "light_neutral", "warm_wood"],
    "modern": ["minimal", "mid_century", "industrial"], "mid_century": ["modern", "warm_wood", "scandinavian"],
    "industrial": ["modern", "dark", "rustic"], "rustic": ["warm_wood", "traditional", "industrial"],
    "traditional": ["rustic", "warm_wood", "soft"], "warm_wood": ["mid_century", "rustic", "scandinavian"],
    "light_neutral": ["scandinavian", "minimal", "soft"], "dark": ["industrial", "modern"], "soft": ["light_neutral", "traditional"],
}


# Conservative style CUES read from a listing's own title (used listings have no curated tags). A cue is labelled as
# coming from the title; it is never presented as a curated style or a product fact.
_STYLE_CUES = [
    ("mid_century", r"mid[\s-]?century|\bmcm\b|danish modern|eames|baughman"), ("scandinavian", r"scandinavian|danish|nordic"),
    ("industrial", r"industrial|metal and wood|\bpipe\b"), ("rustic", r"rustic|farmhouse|reclaimed|mission style|\blog\b"),
    ("traditional", r"traditional|victorian|chippendale|queen anne|french country|colonial|sleigh|four[\s-]?poster"),
    ("minimal", r"minimal(?:ist)?"), ("modern", r"\bmodern\b|contemporary"), ("warm_wood", r"\bteak\b|\bwalnut\b|solid wood"),
]


def style_cues(p: dict) -> list[str]:
    name = (p.get("name") or "").lower()
    return [k for k, rx in _STYLE_CUES if re.search(rx, name)]


def style_fit(p: dict, styles: list[str]) -> tuple[float, list[str], str]:
    """(score, exact matches, label). Exact tags score 1 each; a closely related tag scores 0.5 (once per wanted style).
    Tags come from the curated catalog (`curator_tags`); a product without them (e.g. a used listing) may get style
    CUES from its own title, labelled "a cue from the listing title". Anything else is "not classified", never guessed."""
    tags = set(p.get("curator_tags") or [])
    cue = not tags
    if cue:
        tags = set(style_cues(p))
    exact = sorted(tags & set(styles))
    if not styles:
        return 0.0, [], ""
    near = []
    for st in styles:
        if st in tags:
            continue
        hit = next((t for t in STYLE_NEAR.get(st, []) if t in tags), None)
        if hit:
            near.append((st, hit))
    score = len(exact) + 0.5 * len(near)
    src = " (a cue from the listing title)" if cue else ""
    seen = "title says" if cue else "tagged"
    if exact:
        label = "Matches " + ", ".join(x.replace("_", " ") for x in exact) + src
    elif near:
        label = "; ".join(f"Closest available to {a.replace('_', ' ')}: {seen} {b.replace('_', ' ')}" for a, b in near)
    elif not tags:
        label = "Style not classified"
    else:
        label = ("Other style" + (" from the listing title" if cue else "") + " (" +
                 ", ".join(sorted(t.replace("_", " ") for t in tags)) + ")")
    return score, exact, label


def single_unit(p: dict) -> bool:
    """A used listing is one item: it can be chosen for one piece only."""
    return p.get("condition") == "secondhand"


def identity(p: dict) -> str:
    """The physical item behind a product record: a used listing's canonical URL identity (so re-checks of the same
    listing with new content hashes are ONE item), else the product id."""
    if single_unit(p):
        return p.get("listing_key") or listing_key(p.get("url") or "") or p["id"]
    return p["id"]


def superseded(catalog: list[dict]) -> set[str]:
    """Ids of used-listing records that a NEWER check of the same listing replaces (records stay stored, unchanged)."""
    newest: dict[str, tuple[str, int, str]] = {}
    for n, p in enumerate(catalog):
        if not single_unit(p):
            continue
        key = identity(p)
        rank = (p.get("checked_at") or "", n, p["id"])
        if key not in newest or rank[:2] > newest[key][:2]:
            newest[key] = rank
    keep = {v[2] for v in newest.values()}
    return {p["id"] for p in catalog if single_unit(p) and p["id"] not in keep}


def listing_update_note(item, catalog: list[dict], by_id: dict) -> str | None:
    """A chosen used listing whose newer check says it's sold or unavailable: kept, with this warning."""
    p = by_id.get(item.product_id) if item.product_id else None
    if p is None or not single_unit(p):
        return None
    newer = [q for q in catalog if single_unit(q) and q["id"] != p["id"] and identity(q) == identity(p)
             and (q.get("checked_at") or "") >= (p.get("checked_at") or "")]
    if any(q.get("availability") in UNAVAILABLE for q in newer):
        return "A newer check of this listing says it’s sold or unavailable. It stays chosen until you change it."
    return None


def offered(p: dict) -> bool:
    """Imported pages count as options only if they come from an approved furniture source, and a used item only with
    condition evidence read from the listing itself. Older records outside this (e.g. a used condition the user declared,
    or a page from another website) are kept as they are but not offered as fresh options."""
    if p.get("origin") not in ("user_import", "used_listing_check"):
        return True  # the checked catalog
    url = p.get("url") or ""
    if p.get("condition") == "secondhand":
        return p.get("condition_verified") is True and resale_site(url) is not None
    return retailer_site(url) is not None


def design_pool(category: str, dp: DesignPrefs, size: str | None, catalog: list[dict]) -> tuple[list[dict], str | None]:
    """Products the design may offer for one piece. Store choices (`retailers`) apply ONLY to new items; the chosen
    resale marketplaces (`resale_sites`) apply ONLY to verified used items; "either" is the union. Switching condition
    keeps both choices. Size, condition, exclusions and the rest follow the usual filter."""
    old = superseded(catalog)
    items = [p for p in catalog if offered(p) and p["id"] not in old]  # only the newest check of each used listing
    pool: list[dict] = []
    notes: list[str | None] = []
    if dp.condition in ("new", "either"):
        pr = as_preferences(dp, size).model_copy(update={"condition": "new"})
        got, note, _ = _filtered(category, pr, items)
        pool += got
        notes.append(note)
    if dp.condition in ("secondhand", "either"):
        pr = as_preferences(dp, size).model_copy(update={"condition": "secondhand", "retailers": []})
        got, note, _ = _filtered(category, pr, items)
        if dp.resale_sites:
            got = [p for p in got if resale_site(p.get("url") or "", dp.resale_sites)]
            if not got and note is None:
                note = f"No verified used {piece_name(category, size)} from your chosen resale marketplaces yet."
        pool += got
        notes.append(note)
    seen: set[str] = set()
    pool = [p for p in pool if not (p["id"] in seen or seen.add(p["id"]))]
    return pool, (None if pool else next((n for n in notes if n), f"No verified {piece_name(category, size)} matches your settings."))


def preference_mismatch(item: DesignItem, dp: DesignPrefs, catalog: list[dict], by_id: dict) -> str | None:
    """A chosen product that no longer fits the CURRENT shopping preferences (condition, stores, marketplaces) is kept,
    never silently swapped; this says so."""
    p = by_id.get(item.product_id) if item.product_id else None
    if p is None or item.owned:
        return None
    size = item.size if item.category in ("bed_frame", "mattress") else None
    if any(q["id"] == p["id"] for q in design_pool(item.category, dp, size, catalog)[0]):
        return None
    return ("Chosen under different shopping preferences (condition, store or marketplace); it stays chosen until you "
            "change it.")


def candidates_for(item: DesignItem, design: Design, m: PlanMap, catalog: list[dict], by_id: dict,
                   targets: dict | None = None) -> tuple[list[dict], str | None]:
    """Real products for one piece: same category (and bed size), the design's condition/stores. Each carries
    - `placement`: would it physically fit in the CURRENT arrangement (see `fit_for`): fits / moved (fits at another
      spot in the same room) / conflict / not_placed, with the hard conflicts and soft notes listed separately;
    - budget facts kept apart from placement: the design's whole remaining item budget (`budget_left_cents`) and this
      piece's planning target (`budget_target_cents`, see `planning_targets`).
    Returns (candidates, reason when there are none)."""
    pool, note = design_pool(item.category, design.prefs, item.size if item.category in ("bed_frame", "mattress") else None,
                             catalog)
    allowance = item_allowance(design.prefs)
    spent = committed(design, by_id, exclude=item.id)  # other pieces' chosen products (not ones flagged for review)
    left = None if allowance is None else allowance - spent
    tgt = (targets or {}).get(item.id) or {}
    base = check_items(m, design.items, by_id).get(item.id, []) if item.product_id is None else []
    out = []
    for p in pool:
        trial = [i.model_copy(update={"product_id": p["id"]}) if i.id == item.id else i for i in design.items]
        warns = check_items(m, trial, by_id).get(item.id, [])
        price = p.get("price_cents")
        out.append({
            "product_id": p["id"], "name": p.get("name"), "retailer": p.get("retailer"), "url": p.get("url"),
            "price_cents": price, "condition": p.get("condition"), "availability": p.get("availability"),
            "width_in": p.get("width_in"), "depth_in": p.get("depth_in"), "height_in": p.get("height_in"),
            "nominal_size": p.get("nominal_size"), "image": _safe_image(p.get("image_url")),
            "checked_at": p.get("checked_at"), "stale": is_stale(p), "style_matches": _style_matches(p, design.prefs.styles),
            "style_score": style_fit(p, design.prefs.styles)[0], "style_label": style_fit(p, design.prefs.styles)[2],
            "identity": identity(p), "design_key": design_key(p),
            "budget_left_cents": left,
            "over_budget_by_cents": (None if left is None or price is None else max((price or 0) - max(left, 0), 0) or None),
            "budget_target_cents": tgt.get("target_cents"), "open_pieces": tgt.get("open_pieces"),
            "over_target_by_cents": (None if tgt.get("target_cents") is None or price is None
                                     else max(price - tgt["target_cents"], 0) or None),
            "picked_elsewhere": single_unit(p) and any(
                i.id != item.id and i.product_id and i.product_id in by_id and identity(by_id[i.product_id]) == identity(p)
                for i in design.items),
            "origin": p.get("origin"), "warnings": warns, "new_warnings": [w for w in warns if w not in base],
            "placement": fit_for(item, p["id"], design.items, m, by_id),
            "condition_verified": p.get("condition_verified", True), "condition_evidence": p.get("condition_evidence"),
            "fit_basis": "printed" if m.scale.kind == "printed" and m.status == "mapped" else "relative",
            # Facts read from a public page READER copy (not the page itself): shown as such, freshness unknown.
            "read_via": p.get("read_via"), "freshness": p.get("freshness"),
        })
    for c in out:
        price = c["price_cents"]
        # With a budget, a price must be KNOWN to count as within it. Without one, nothing is judged on price.
        c["within_budget"] = left is None or (price is not None and price <= max(left, 0))
        c["affordable"] = c["within_budget"] and (c["budget_target_cents"] is None
                                                  or (price is not None and price <= c["budget_target_cents"]))
        c["blocked"] = ("Already picked for another piece (a used listing is one item)." if c["picked_elsewhere"]
                        else (f"Over the {_money(max(left or 0, 0))} item budget left for this piece." if price is not None
                              else "Its price isn’t confirmed, so it can’t be checked against your budget.")
                        if not c["within_budget"] else None)
    bad = lambda c: c["placement"]["status"] == "conflict"  # noqa: E731
    # Price feasibility outranks style: options within this piece's share and the whole budget come first.
    if design.prefs.approach == "low":
        out.sort(key=lambda c: (bad(c), not c["affordable"], not c["within_budget"], c["price_cents"] or 0, c["product_id"]))
    else:
        out.sort(key=lambda c: (bad(c), not c["affordable"], not c["within_budget"], -c["style_score"],
                                c["price_cents"] or 0, c["product_id"]))
    return out, (None if out else note)


def recommendable(c: dict) -> bool:
    """Shown as a ready recommendation: fits (or isn't placed yet), not taken by another piece, and within this
    piece's share AND the whole remaining item budget (no budget set: price isn't judged)."""
    return (c["affordable"] and c["placement"]["status"] != "conflict" and not c["picked_elsewhere"]
            and c.get("availability") not in UNAVAILABLE)


def held_back(cands: list[dict]) -> dict[str, int]:
    """Why options aren't recommended (counts only; they're never shown as ready choices)."""
    out = {"over_budget": 0, "over_share": 0, "doesnt_fit": 0, "picked_elsewhere": 0, "unavailable": 0}
    for c in cands:
        if recommendable(c):
            continue
        k = ("picked_elsewhere" if c["picked_elsewhere"] else "over_budget" if not c["within_budget"]
             else "over_share" if not c["affordable"] else "unavailable" if c.get("availability") in UNAVAILABLE
             else "doesnt_fit")
        out[k] += 1
    return {k: v for k, v in out.items() if v}


# Finish/colour words: two listings that differ only in these are the same design (shown once, "N colours").
_FINISH_WORDS = {
    "black", "white", "gray", "grey", "brown", "beige", "natural", "oak", "walnut", "pine", "birch", "ash", "teak", "cherry",
    "espresso", "navy", "blue", "green", "red", "pink", "yellow", "orange", "cream", "ivory", "charcoal", "silver", "gold",
    "brass", "chrome", "tan", "taupe", "sand", "olive", "sage", "stained", "effect", "light", "dark", "medium", "matte",
    "glossy", "high", "gloss", "finish", "color", "colour", "multicolor", "smoke", "rust", "mustard", "emerald", "quarry",
    "heather", "slate", "graphite", "anthracite", "turquoise", "burgundy", "mocha", "honey", "acacia", "mahogany",
    "and", "with", "in", "the", "a", "of",
}
_FINISH_WORDS -= {"oak", "walnut", "pine", "birch", "ash", "teak", "cherry", "brass", "chrome", "silver", "gold", "acacia",
                  "mahogany"}  # materials are part of a design, not just a colour


def design_key(p: dict) -> str:
    """The same design = same store, same model/family name once ONLY colour words are removed (materials, shapes and
    words like "storage" or "platform" stay), AND the same listed footprint (a different size is a different fit).
    Names too generic to identify a model (fewer than two words left) are never merged. A used listing is always its
    own item."""
    if single_unit(p):
        return "item:" + identity(p)
    words = [w for w in re.findall(r"[a-z]+", (p.get("name") or "").lower())
             if w not in _FINISH_WORDS and len(w) > 1 and w not in ("in", "cm", "x")]
    if len(words) < 2:
        return "item:" + p["id"]
    fp = f"{round(p.get('width_in') or 0)}x{round(p.get('depth_in') or 0)}"
    return f"{(p.get('retailer') or '').lower()}|{p.get('category') or ''}|{' '.join(words)}|{fp}"


def title_key(title: str) -> str:
    """A search result's title without colour/finish words: two results with the same key are probably colour variants
    of one design (used only to order which pages to check, never to merge products)."""
    words = [w for w in re.findall(r"[a-z]+", (title or "").lower()) if w not in _FINISH_WORDS and len(w) > 1]
    return " ".join(words) if len(words) >= 2 else ""


def cited_price_cents(*texts: str) -> int | None:
    """The lowest dollar price written in a search result's title or citation text. Untrusted, unverified search text:
    used only to check likely-affordable pages first, never as a product price."""
    found = [round(float(m.replace(",", "")) * 100)
             for t in texts for m in re.findall(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", t or "")]
    return min(found) if found else None


def collapse_variants(cands: list[dict]) -> list[dict]:
    """One option per design: colour/finish variants of the same product collapse into the first (best-ranked) one,
    which lists how many variants there are. Order is otherwise kept."""
    out: list[dict] = []
    seen: dict[str, dict] = {}
    for c in cands:
        k = c.get("design_key") or c["product_id"]
        if k in seen:
            first = seen[k]
            first["variants"] = first.get("variants", 1) + 1
            if len(first.setdefault("variant_names", [])) < 4:
                first["variant_names"].append(c.get("name"))
            continue
        c = dict(c)
        seen[k] = c
        out.append(c)
    return out


def _safe_image(url: object) -> str | None:
    return url if isinstance(url, str) and url.startswith("https://") else None


def purchasable(items: list[DesignItem]) -> list[DesignItem]:
    return [i for i in items if not i.owned]


def budget_summary(design: Design, by_id: dict, missing_reasons: dict[str, str]) -> dict:
    dp = design.prefs
    reserve = (dp.budget_cents or 0) * dp.reserve_pct // 100 if dp.budget_cents is not None else 0
    allowance = dp.budget_cents - reserve if dp.budget_cents is not None else None
    chosen = [i for i in purchasable(design.items) if i.product_id and i.product_id in by_id]
    missing = [i for i in purchasable(design.items) if not (i.product_id and i.product_id in by_id)]
    subtotal = sum(by_id[i.product_id].get("price_cents") or 0 for i in chosen)
    review = budget_review(design, by_id)
    status = "empty" if not design.items else ("complete" if not missing and not review else "incomplete")
    return {
        # Chosen products the item budget can't hold: still chosen and counted in the subtotal, never "complete".
        "budget_review": [{"id": i.id, "category": i.category, "name": piece_name(i.category, i.size), **review[i.id]}
                          for i in chosen if i.id in review],
        "subtotal_cents": subtotal, "reserve_cents": reserve, "item_allowance_cents": allowance,
        "budget_cents": dp.budget_cents, "remaining_cents": None if allowance is None else allowance - subtotal,
        "over_allowance": allowance is not None and subtotal > allowance,
        "status": status, "chosen": len(chosen), "to_buy": len(purchasable(design.items)),
        "owned": sum(1 for i in design.items if i.owned),
        "missing": [{"id": i.id, "category": i.category, "name": piece_name(i.category, i.size), "zone_id": i.zone_id,
                     "reason": missing_reasons.get(i.id) or "No product chosen yet."} for i in missing],
        "note": ("Subtotal counts only the products chosen so far. "
                 f"{dp.reserve_pct}% of your budget is set aside for delivery and tax; actual checkout costs may differ."
                 if dp.budget_cents is not None else
                 "No budget set. Subtotal counts only the products chosen so far."),
    }


PIECE_PRIORITY = {"dining_table": 4, "tv_stand": 5, "tv": 6, "armchair": 7, "dining_chair": 8, "side_table": 9,
                  "console_table": 9, "shoe_storage": 9, "ottoman": 9, "floor_lamp": 9,
                  "bed_frame": 0, "mattress": 1, "sofa_bed": 2, "daybed": 2, "sofa": 3, "desk": 4, "dresser": 5,
                  "wardrobe": 5, "coffee_table": 6, "desk_chair": 7, "nightstand": 8, "bookcase": 9}
# Relative planning weights per piece type (a transparent split of the item budget, NOT a price or quality claim).
PLAN_WEIGHT = {"bed_frame": 16, "mattress": 18, "sofa": 26, "sofa_bed": 24, "daybed": 14, "dresser": 10, "wardrobe": 12,
               "nightstand": 4, "desk": 8, "desk_chair": 6, "coffee_table": 6, "dining_table": 10, "dining_chair": 3,
               "tv_stand": 6, "tv": 14, "armchair": 9, "bookcase": 5, "side_table": 3, "console_table": 5, "ottoman": 3,
               "shoe_storage": 3, "floor_lamp": 2}
TARGET_STRETCH = 1.5  # a known cheapest price may raise a piece's target up to 1.5x its share, no further


def item_allowance(dp: DesignPrefs) -> int | None:
    return None if dp.budget_cents is None else dp.budget_cents - dp.budget_cents * dp.reserve_pct // 100


def budget_review(design: Design, by_id: dict) -> dict[str, dict]:
    """Chosen products the item budget can't hold. Only when the chosen products TOGETHER are over the item budget:
    each one priced above its plain share of the whole item budget (`PLAN_WEIGHT` split over every piece to buy) needs
    review. These stay chosen and visible (never removed or changed here), aren't counted as finished, and don't use
    up the budget other pieces are planned and checked against, so they can be replaced one at a time."""
    allowance = item_allowance(design.prefs)
    if allowance is None:
        return {}
    buy = purchasable(design.items)
    chosen = [(i, by_id[i.product_id].get("price_cents")) for i in buy if i.product_id and i.product_id in by_id]
    total = sum(p or 0 for _, p in chosen)
    if total <= allowance:
        return {}
    tw = sum(PLAN_WEIGHT.get(i.category, 5) for i in buy) or 1
    out = {}
    for i, price in chosen:
        share = allowance * PLAN_WEIGHT.get(i.category, 5) // tw
        if price is None or price <= share:
            continue
        whole = price > allowance
        out[i.id] = {
            "price_cents": price, "share_cents": share, "over_whole_budget": whole,
            "message": (f"{_money(price)} is more than your whole {_money(allowance)} item budget"
                        if whole else
                        f"Your chosen products add up to {_money(total)}, over the {_money(allowance)} item budget, and "
                        f"this one ({_money(price)}) is above its share (about {_money(share)})")
            + ". It stays chosen until you replace or remove it, but it doesn’t count as done.",
        }
    return out


def committed(design: Design, by_id: dict, exclude: str | None = None) -> int:
    """What the other pieces' chosen products use of the item budget: products flagged by `budget_review` are left
    out (they're waiting to be replaced), so the rest can still be planned, searched and chosen."""
    review = budget_review(design, by_id)
    return sum(by_id[i.product_id].get("price_cents") or 0 for i in purchasable(design.items)
               if i.product_id and i.product_id in by_id and i.id != exclude and i.id not in review)


def _price(c: dict) -> int:
    return c["price_cents"] or 0


def _cheapest_known(it: DesignItem, design: Design, catalog: list[dict], m: PlanMap | None = None,
                    by_id: dict | None = None) -> int | None:
    """The cheapest matching option's price; with a map, only options that physically fit this piece's room
    (fits / moved / not placed) count, so a geometry-impossible bargain never shapes the plan."""
    pool, _ = design_pool(it.category, design.prefs, it.size if it.category in ("bed_frame", "mattress") else None, catalog)
    prices = []
    for p in pool:
        if not p.get("price_cents"):
            continue
        if m is not None and m.status == "mapped" and fit_for(it, p["id"], design.items, m, by_id or {})["status"] == "conflict":
            continue
        prices.append(p["price_cents"])
    return min(prices) if prices else None


def planning_targets(design: Design, catalog: list[dict], by_id: dict, m: PlanMap | None = None) -> dict[str, dict]:
    """A planning target for EVERY unowned piece still without a product (a mattress on its bed included).
    1. The item budget left after the products already chosen is split by `PLAN_WEIGHT`: shares sum to at most what is
       left and every open piece, known or not, gets a positive share.
    2. Known prices may REBALANCE that split only when the WHOLE plan stays affordable: pieces whose cheapest fitting
       option sits a little above their share (up to `TARGET_STRETCH`) get that price, but only if every piece with a
       known cheapest option can still be bought (the sum of those minimums fits in what is left) and each other piece
       keeps at least half its share. Otherwise the plain affordable split stands.
    A listing far above its share is evidence to search for cheaper ones, never permission to plan over budget.
    Transparent guidance for searching and choosing, not a promise that something exists at that price. Empty when no
    budget is set."""
    allowance = item_allowance(design.prefs)
    if allowance is None:
        return {}
    review = budget_review(design, by_id)  # over-budget choices are planned as open pieces (to be replaced)
    fixed = committed(design, by_id)
    open_items = [i for i in purchasable(design.items) if not (i.product_id and i.product_id in by_id) or i.id in review]
    if not open_items:
        return {}
    remaining = max(allowance - fixed, 0)
    mins = {i.id: _cheapest_known(i, design, catalog, m, by_id) for i in open_items}
    w = {i.id: PLAN_WEIGHT.get(i.category, 5) for i in open_items}

    def split(amount: int, ids: list[str]) -> dict[str, int]:
        tw = sum(w[k] for k in ids) or 1
        return {k: amount * w[k] // tw for k in ids}
    share = split(remaining, [i.id for i in open_items])
    target, basis = dict(share), {k: "share" for k in share}
    raise_ = {k: mins[k] for k in share if mins[k] is not None and share[k] < mins[k] <= share[k] * TARGET_STRETCH}
    if raise_:
        rest_ids = [k for k in share if k not in raise_]
        rest = remaining - sum(raise_.values())
        others = split(max(rest, 0), rest_ids)
        known_total = sum(v for v in mins.values() if v is not None)
        feasible = (rest > 0 or not rest_ids) and known_total <= remaining and all(
            others[k] >= share[k] // 2 and others[k] > 0 for k in rest_ids)
        if feasible:
            target.update(raise_)
            target.update(others)
            basis.update({k: "cheapest known option" for k in raise_})
    out: dict[str, dict] = {}
    for i in open_items:
        k = i.id
        far = mins[k] is not None and mins[k] > target[k]
        out[k] = {"target_cents": max(target[k], 0), "basis": basis[k],
                  "note": (f"The cheapest option found so far ({_money(mins[k])}) is above this piece’s share "
                           f"({_money(target[k])}); look for more options or adjust the budget.") if far else None,
                  "cheapest_known_cents": mins[k], "open_pieces": len(open_items), "left_cents": remaining}
    return out


def auto_choose(design: Design, m: PlanMap, catalog: list[dict], by_id: dict) -> tuple[list[DesignItem], list[str]]:
    """Fill pieces that have no product yet, complete set first, within a HARD ceiling: the item budget (budget minus
    reserve), counting products already chosen. Pieces already chosen are never changed here.
    - Every open piece (a mattress on its bed included) has a planning target (`planning_targets`); while one piece is
      chosen, the targets of all the OTHER open pieces stay reserved, so no single piece can use up the budget.
    - Only options that physically fit are taken, judged in the arrangement as it is being filled (so two picks can't
      collide): where the piece is, or at another spot in the SAME confirmed room (moved there, same size). An option
      that would extend outside the room, sit on a fixed area or door area, or overlap another piece is never chosen.
    - "Keep costs low": the cheapest fitting option. "Use my budget for better matches": the best style match within
      the piece's target (cheaper first among equals), else the cheapest fitting option the reserve allows.
    - Only when EVERY piece has a product, "Use my budget" may swap to options with MORE style matches within the
      ceiling. Price is never treated as quality and there are no price-driven step-ups.
    Pieces that can't be filled stay visible with the reason."""
    items = list(design.items)
    notes: list[str] = []
    allowance = item_allowance(design.prefs)
    total = committed(design, by_id)  # chosen products waiting for budget review are left out (and kept as they are)
    targets = planning_targets(design, catalog, by_id, m)
    open_ids = [i.id for i in sorted((i for i in items if not i.owned and not i.product_id),
                                     key=lambda i: (PIECE_PRIORITY.get(i.category, 9), i.id))]
    reserved = {iid: (targets.get(iid) or {}).get("target_cents") or 0 for iid in open_ids}
    # Pieces whose chosen product needs budget review keep their share reserved for the replacement.
    reserved_review = sum((targets.get(k) or {}).get("target_cents") or 0 for k in budget_review(design, by_id))
    pick: dict[str, dict] = {}
    moved = 0

    def current(iid: str) -> DesignItem:
        return next(i for i in items if i.id == iid)

    def options(it: DesignItem) -> list[dict]:
        snap = design.model_copy(update={"items": items})
        cands, _ = candidates_for(it, snap, m, catalog, by_id, targets)
        taken = {x["identity"] for x in pick.values() if x.get("condition") == "secondhand"}
        return [c for c in cands if not c.get("picked_elsewhere") and c["identity"] not in taken
                and c["placement"]["status"] in ("fits", "moved", "not_placed")]

    why_missing: dict[str, str] = {}
    cheapest_fit: dict[str, int | None] = {}

    def try_pick(iid: str, reserve_others: int) -> bool:
        nonlocal items, total, moved
        it = current(iid)
        name = piece_name(it.category, it.size).capitalize()
        opts = options(it)
        cheapest_fit[iid] = min((_price(c) for c in opts), default=None)
        bound = None if allowance is None else allowance - total - reserve_others - reserved_review
        if not opts:
            snap = design.model_copy(update={"items": items})
            every, why = candidates_for(it, snap, m, catalog, by_id, targets)
            why_missing[iid] = f"{name}: " + ("none of its options fits where it can go in its room (they'd extend outside "
                                              "the room or overlap a fixed area, door or other piece); review its spot or "
                                              "choose one yourself." if every else (why or "no matching product yet."))
            return False
        afford = [c for c in opts if bound is None or _price(c) <= bound]
        if not afford:
            why_missing[iid] = (f"{name}: left without a product; the cheapest option that fits ({_money(cheapest_fit[iid])}) "
                                f"would leave too little for the other open pieces (about {_money(max(bound or 0, 0))} can go "
                                "to this piece). Raise the budget, mark pieces you own, or choose one yourself.")
            return False
        target = (targets.get(iid) or {}).get("target_cents")
        if design.prefs.approach == "low":
            c = min(afford, key=lambda c: (_price(c), c["product_id"]))
        else:
            within = [c for c in afford if target is None or _price(c) <= target] or afford
            c = min(within, key=lambda c: (-c["style_score"], _price(c), c["product_id"]))
        mv = c["placement"].get("move")
        upd = {"product_id": c["product_id"]}
        if mv:
            upd.update(mv)
            moved += 1
        new = it.model_copy(update=upd)
        items = _with_position([new if i.id == iid else i for i in items], new) if mv else [new if i.id == iid else i for i in items]
        pick[iid] = c
        total += _price(c)
        why_missing.pop(iid, None)
        return True

    for iid in open_ids:  # pass 1: every other open piece keeps its planning target reserved
        try_pick(iid, sum(v for k, v in reserved.items() if k != iid and k not in pick))
    # Completion pass (before any upgrade): a piece skipped above its initial share is retried with what is actually
    # left, once the others' real prices are known. Every piece still missing keeps a reserve: its cheapest fitting
    # option (capped at its target) if it has options, else its full target. Bounded: at most one retry round per piece.
    for _ in range(len(open_ids)):
        progressed = False
        for iid in [k for k in open_ids if k not in pick and cheapest_fit.get(k) is not None]:
            others = sum((min(reserved[k], cheapest_fit[k]) if cheapest_fit.get(k) is not None else reserved[k])
                         for k in open_ids if k != iid and k not in pick)
            progressed |= try_pick(iid, others)
        if not progressed:
            break
    notes.extend(why_missing[k] for k in open_ids if k in why_missing)
    missing = [iid for iid in open_ids if iid not in pick]
    if design.prefs.approach == "use" and pick and not missing:
        for iid in list(pick):  # more style matches only; never just a pricier option
            it = current(iid).model_copy(update={"product_id": None})
            better = [c for c in options(it) if c["style_score"] > pick[iid]["style_score"] and c["product_id"] != pick[iid]["product_id"]
                      and (allowance is None or total - _price(pick[iid]) + _price(c) <= allowance - reserved_review)]
            if better:
                c = min(better, key=lambda c: (-c["style_score"], _price(c)))
                total += _price(c) - _price(pick[iid])
                upd = {"product_id": c["product_id"], **(c["placement"].get("move") or {})}
                new = current(iid).model_copy(update=upd)
                items = _with_position([new if i.id == iid else i for i in items], new)
                pick[iid] = c
    if moved:
        notes.append(f"{moved} piece{'s were' if moved != 1 else ' was'} moved to another spot in the same room so the "
                     "chosen product fits (same size; check the arrangement).")
    if allowance:
        share = round(100 * total / allowance) if allowance else 0
        notes.append(f"Uses {_money(total)} of your {_money(allowance)} item budget ({share}%)."
                     + (f" {len(missing)} piece{'s' if len(missing) != 1 else ''} still need{'s' if len(missing) == 1 else ''} "
                        "a product, so nothing was upgraded." if missing else
                        " A higher price isn’t higher quality; compare the options for each piece."))
    return items, notes


def _money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def missing_reasons(design: Design, catalog: list[dict]) -> dict[str, str]:
    out = {}
    by_id = {p["id"]: p for p in catalog}
    allowance = item_allowance(design.prefs)
    spent = committed(design, by_id)
    for it in purchasable(design.items):
        if it.product_id:
            continue
        size = it.size if it.category in ("bed_frame", "mattress") else None
        pool, note = design_pool(it.category, design.prefs, size, catalog)
        if pool:
            cheapest = min(p.get("price_cents") or 0 for p in pool)
            if allowance is not None and spent + cheapest > allowance:
                out[it.id] = (f"Not chosen: the cheapest match ({_money(cheapest)}) would go over your item budget "
                              f"({_money(max(allowance - spent, 0))} left). Raise the budget, change other pieces, or "
                              "mark one you already own.")
            else:
                out[it.id] = "Not chosen yet: pick one in Choose furniture."
        elif design.prefs.condition != "either" and design_pool(
                it.category, design.prefs.model_copy(update={"condition": "either"}), size, catalog)[0]:
            used = design.prefs.condition == "secondhand"
            out[it.id] = (f"No verified {'used' if used else 'new'} {piece_name(it.category, it.size if it.category in ('bed_frame', 'mattress') else None)} "
                          "in our checked collection yet (it has other conditions only). "
                          + ("Use “Find secondhand options” to search resale listings." if used
                             else "Use “Find more online” to search for new ones."))
        elif it.category in ("bed_frame", "mattress") and it.size:
            out[it.id] = (f"No verified {piece_name(it.category, it.size)} in our saved collection or your imports yet. "
                          "Find one online and check it, or choose another bed size.")
        else:
            out[it.id] = note or f"No verified {piece_name(it.category)} matches your settings."
    return out


def checklist(design: Design, by_id: dict, marks: dict[str, dict], reasons: dict[str, str]) -> dict:
    """One list for the whole design: products grouped with quantities (each instance keeps its own mark; a mark
    counts only for the product it was made for), plus owned pieces and pieces still missing a product."""
    groups: dict[str, dict] = {}
    for it in purchasable(design.items):
        p = by_id.get(it.product_id) if it.product_id else None
        if not p:
            continue
        m = marks.get(it.id)
        bought = bool(m and m["product_id"] == it.product_id and m["purchased"])
        g = groups.setdefault(p["id"], {
            "product_id": p["id"], "name": p.get("name"), "category": it.category, "retailer": p.get("retailer"),
            "url": p.get("url"), "unit_price_cents": p.get("price_cents"), "condition": p.get("condition"),
            "width_in": p.get("width_in"), "depth_in": p.get("depth_in"), "checked_at": p.get("checked_at"),
            "stale": is_stale(p), "quantity": 0, "instances": [], "read_via": p.get("read_via"),
        })
        g["quantity"] += 1
        g["instances"].append({"id": it.id, "zone_id": it.zone_id, "purchased": bought})
    rows = sorted(groups.values(), key=lambda g: (g["category"], g["name"] or ""))
    for g in rows:
        g["line_total_cents"] = (g["unit_price_cents"] or 0) * g["quantity"]
        g["purchased_count"] = sum(1 for i in g["instances"] if i["purchased"])
    owned = [{"id": i.id, "category": i.category, "name": piece_name(i.category, i.size), "zone_id": i.zone_id}
             for i in design.items if i.owned]
    missing = [{"id": i.id, "category": i.category, "name": piece_name(i.category, i.size), "zone_id": i.zone_id,
                "reason": reasons.get(i.id, "No product chosen yet.")}
               for i in purchasable(design.items) if not (i.product_id and i.product_id in by_id)]
    total = sum(g["line_total_cents"] for g in rows)
    review = budget_review(design, by_id)  # chosen but over the item budget: listed, never "complete"
    for g in rows:
        g["budget_review"] = [review[i["id"]]["message"] for i in g["instances"] if i["id"] in review][:1]
    return {"rows": rows, "owned": owned, "missing": missing, "total_cents": total, "budget_review": len(review),
            "status": ("complete" if design.items and not missing and not review
                       else ("empty" if not design.items else "incomplete")),
            "purchased": sum(g["purchased_count"] for g in rows), "units": sum(g["quantity"] for g in rows)}


def unavailable(p: dict) -> bool:
    return p.get("availability") in UNAVAILABLE


def zone_area_ok(m: PlanMap) -> bool:
    return any(r.furnishable and area(r.polygon) > 0 for r in m.rooms)
