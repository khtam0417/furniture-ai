"""Typed contracts for rooms, preferences, plans and AI outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

RoomType = Literal["bedroom", "studio", "living_room"]
Strength = Literal["weak", "moderate", "strong"]
ClaimKind = Literal["observation", "external_fact", "hypothesis", "verified_constraint"]
Wall = Literal["north", "east", "south", "west", "unknown"]
FeatureKind = Literal["door", "window", "closet", "radiator", "outlet", "kitchen", "bathroom", "entry", "column", "other"]
Category = Literal[
    "bed_frame", "mattress", "sofa_bed", "daybed", "sofa", "desk", "desk_chair",
    "dresser", "nightstand", "wardrobe", "bookcase", "coffee_table",
    "tv", "tv_stand", "dining_table", "dining_chair", "armchair", "side_table", "ottoman", "console_table", "shoe_storage", "floor_lamp",
]
Style = Literal[
    "minimal", "scandinavian", "modern", "traditional", "rustic", "mid_century",
    "industrial", "warm_wood", "light_neutral", "dark", "soft",
]
Priority = Literal["price", "storage", "comfort", "work", "small_footprint", "style"]
Condition = Literal["new", "secondhand", "either"]
FitLabel = Literal["Fits tested assumptions", "Tight / conditional", "Fit unverified", "Does not fit"]
ScaleStatus = Literal["unknown", "plan_dimensions_user_confirmed", "user_stated"]
Method = Literal["live_ai", "fixture", "mocked_ai", "manual"]


# ---------------------------------------------------------------- room evidence
class Bound(BaseModel):
    """Heuristic plausible range in inches. Not a calibrated confidence interval."""

    lower: float = Field(gt=0, le=1200)
    central: float | None = Field(default=None, gt=0, le=1200)
    upper: float = Field(gt=0, le=1200)
    unit: Literal["in"] = "in"
    method: str
    source_ids: list[str] = Field(default_factory=list)
    strength: Strength = "weak"

    @model_validator(mode="after")
    def _ordered(self):
        c = self.central if self.central is not None else self.lower
        if not (self.lower <= c <= self.upper):
            raise ValueError("Bound must satisfy lower <= central <= upper")
        return self


class RoomFeature(BaseModel):
    id: str
    kind: FeatureKind
    wall: Wall = "unknown"
    offset_in: float | None = Field(default=None, ge=0, le=1200)  # only meaningful when scale is known
    width_in: float | None = Field(default=None, gt=0, le=600)
    depth_in: float | None = Field(default=None, gt=0, le=600)  # zone depth (kitchen/bath)
    fixed: bool = True
    description: str = ""
    source_ids: list[str] = Field(default_factory=list)


CATEGORY_NAMES = (
    "bed_frame", "mattress", "sofa_bed", "daybed", "sofa", "desk", "desk_chair",
    "dresser", "nightstand", "wardrobe", "bookcase", "coffee_table",
    "tv", "tv_stand", "dining_table", "dining_chair", "armchair", "side_table", "ottoman", "console_table", "shoe_storage", "floor_lamp",
)
UNMATCHED = "unmatched"  # detected item whose type the user has not chosen; covers no purchase category

# Only unambiguous aliases. Generic words ("chair", "table", "table/desk", "shelf unit?") stay unmatched.
CATEGORY_ALIASES = {
    "bed": "bed_frame", "bed frame": "bed_frame", "platform bed": "bed_frame",
    "mattress": "mattress",
    "sofa bed": "sofa_bed", "sleeper sofa": "sofa_bed", "sofa sleeper": "sofa_bed", "futon": "sofa_bed",
    "daybed": "daybed", "day bed": "daybed",
    "sofa": "sofa", "couch": "sofa", "loveseat": "sofa",
    "desk": "desk", "writing desk": "desk", "computer desk": "desk", "work desk": "desk", "office desk": "desk",
    "study desk": "desk",
    "desk chair": "desk_chair", "office chair": "desk_chair", "task chair": "desk_chair", "computer chair": "desk_chair",
    "dresser": "dresser", "chest of drawers": "dresser",
    "nightstand": "nightstand", "night stand": "nightstand", "bedside table": "nightstand", "night table": "nightstand",
    "wardrobe": "wardrobe", "armoire": "wardrobe",
    "bookcase": "bookcase", "bookshelf": "bookcase",
    "coffee table": "coffee_table",
    "tv": "tv", "television": "tv", "smart tv": "tv",
    "tv stand": "tv_stand", "media console": "tv_stand", "tv console": "tv_stand", "entertainment center": "tv_stand",
    "media stand": "tv_stand",
    "dining table": "dining_table", "kitchen table": "dining_table",
    "dining chair": "dining_chair", "kitchen chair": "dining_chair",
    "armchair": "armchair", "accent chair": "armchair", "lounge chair": "armchair",
    "side table": "side_table", "end table": "side_table",
    "ottoman": "ottoman", "pouf": "ottoman",
    "console table": "console_table", "sofa table": "console_table", "entryway table": "console_table",
    "shoe rack": "shoe_storage", "shoe cabinet": "shoe_storage", "shoe storage": "shoe_storage",
    "storage bench": "shoe_storage", "entryway bench": "shoe_storage",
    "floor lamp": "floor_lamp",
}


def normalize_category(raw: str) -> str:
    """Map a free-form detected label to a purchase category only when unambiguous; else 'unmatched'."""
    key = " ".join(raw.lower().replace("_", " ").replace("-", " ").split())
    if raw in CATEGORY_NAMES:
        return raw
    return CATEGORY_ALIASES.get(key, UNMATCHED)


class ExistingItem(BaseModel):
    id: str
    category: str = Field(max_length=40)
    detected_label: str = Field(default="", max_length=60)  # original text from the photo analysis, kept verbatim
    description: str = Field(default="", max_length=200)
    keep: bool = True
    width_in: float | None = Field(default=None, gt=0, le=300)
    depth_in: float | None = Field(default=None, gt=0, le=300)
    footprint_source: Literal["user_stated", "unknown"] = "unknown"
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known_category(self):
        # Free-form labels (also from older saved versions) never masquerade as a purchase category.
        if self.category not in CATEGORY_NAMES and self.category != UNMATCHED:
            if not self.detected_label:
                self.detected_label = self.category[:60]
            self.category = normalize_category(self.category)
        return self


class EvidenceClaim(BaseModel):
    kind: ClaimKind
    subject: str
    statement: str
    source_ids: list[str] = Field(default_factory=list)
    strength: Strength = "weak"


class RoomModel(BaseModel):
    room_type: RoomType
    shape: Literal["rectangular", "l_shaped", "irregular", "unknown"] = "unknown"
    scale_status: ScaleStatus = "unknown"
    width: Bound | None = None
    depth: Bound | None = None
    features: list[RoomFeature] = Field(default_factory=list)
    existing_items: list[ExistingItem] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)
    untrusted_text_seen: list[str] = Field(default_factory=list)
    method: Method
    model: str | None = None
    prompt_version: str | None = None
    # Photo-derived outline hypothesis (None on analyses made before photo mapping). Never trusted dimensions.
    inferred_geometry: InferredGeometry | None = None
    # Room size ESTIMATED from a printed floor-plan reading the user picked (user direction 2026-10-26). Kept apart
    # from width/depth: scale_status stays "unknown", so fit is never upgraded to a checked result by an estimate.
    plan_estimate: "PlanEstimate | None" = None

    @model_validator(mode="after")
    def _scale_contract(self):
        # Hard rule: without a trusted scale source there are no room dimensions at all.
        if self.scale_status == "unknown" and (self.width is not None or self.depth is not None):
            raise ValueError("Room dimensions require a trusted scale source")
        if self.scale_status != "unknown" and (self.width is None or self.depth is None):
            raise ValueError("A scaled room needs width and depth bounds")
        return self


# ---------------------------------------------------------------- AI output (photo analysis)
class AIPhotoNote(BaseModel):
    photo_index: int = Field(ge=0, le=20)
    shows: str = Field(max_length=300)
    quality_issue: str | None = Field(default=None, max_length=200)
    appears_same_room_as_others: Literal["yes", "no", "unclear"] = "unclear"


class AIFeature(BaseModel):
    kind: FeatureKind
    wall_guess: Wall = "unknown"
    photo_indices: list[int] = Field(default_factory=list, max_length=10)
    description: str = Field(max_length=200)


class AIExistingItem(BaseModel):
    category: str = Field(max_length=40)
    description: str = Field(max_length=200)
    photo_indices: list[int] = Field(default_factory=list, max_length=10)


class AIScaleCue(BaseModel):
    description: str = Field(max_length=200)
    photo_index: int = Field(ge=0, le=20)
    exact_variant_identified: bool = False


class AIDimensionGuess(BaseModel):
    width_in_low: float = Field(gt=0, le=1200)
    width_in_high: float = Field(gt=0, le=1200)
    depth_in_low: float = Field(gt=0, le=1200)
    depth_in_high: float = Field(gt=0, le=1200)
    reasoning: str = Field(max_length=400)


class AIFloorplanReading(BaseModel):
    """Text read off a dimensioned floor plan image (e.g. "11'-2\" x 12'-0\"")."""

    photo_index: int = Field(ge=0, le=20)
    plan_label: str = Field(default="", max_length=80)
    room_label: str = Field(default="", max_length=80)
    dimension_text: str = Field(max_length=60)


WallId = Literal["A", "B", "C", "D"]
GeoFeatureKind = Literal["door", "entry", "window", "closet", "radiator", "kitchen", "bathroom_door", "column", "other"]


class AIWallFeature(BaseModel):
    kind: GeoFeatureKind
    start_frac: float = Field(ge=0, le=1, description="Where it starts along the wall, 0 = left end when facing the wall from inside the room")
    end_frac: float = Field(ge=0, le=1, description="Where it ends along the wall (same direction), must be > start_frac")
    depth_in_low: float | None = Field(default=None, gt=0, le=120, description="Only for things that stick into the room (kitchen counters, column)")
    depth_in_high: float | None = Field(default=None, gt=0, le=120)
    photo_indices: list[int] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=160)


class AIWall(BaseModel):
    wall: WallId
    description: str = Field(max_length=160, description="What identifies this wall in the photos")
    visible: Literal["fully", "partly", "not_seen"]
    photo_indices: list[int] = Field(default_factory=list, max_length=10)
    features: list[AIWallFeature] = Field(default_factory=list, max_length=8)


class AIScaleEstimate(BaseModel):
    wall_a_length_in_low: float = Field(gt=0, le=1200)
    wall_a_length_in_high: float = Field(gt=0, le=1200)
    wall_b_length_in_low: float = Field(gt=0, le=1200)
    wall_b_length_in_high: float = Field(gt=0, le=1200)
    cues: list[AIScaleCue] = Field(default_factory=list, max_length=6, description="Visible objects used for scale; typical sizes are weak cues")
    reasoning: str = Field(max_length=400)


class AIGeometry(BaseModel):
    """Room outline relative to a reference wall seen in the photos. Abstain when evidence is insufficient.
    `scale`, `missing_views` and `reasoning` belong INSIDE this object (unknown keys are rejected)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["mapped", "insufficient"]
    reference_wall_a: str = Field(default="", max_length=160, description="Wall A: a clearly visible wall; B, C, D follow clockwise seen from above")
    shape: Literal["rectangular", "l_shaped", "irregular", "unknown"] = "unknown"
    corners_seen: int = Field(default=0, ge=0, le=8)
    walls: list[AIWall] = Field(default_factory=list, max_length=4)
    scale: AIScaleEstimate | None = None
    missing_views: list[str] = Field(default_factory=list, max_length=6, description="Specific extra photos that would let the room be mapped")
    reasoning: str = Field(default="", max_length=500)


class FeatureEstimate(BaseModel):
    """A fixed feature located on the estimated outline (fractions along a wall; hypothesis, never verified)."""

    kind: GeoFeatureKind
    wall: WallId
    start_frac: float
    end_frac: float
    uncertainty_frac: float = 0.08
    depth_in: float | None = None
    source_ids: list[str] = Field(default_factory=list)
    note: str = ""


class InferredGeometry(BaseModel):
    """Photo-derived room outline hypothesis. Kept separate from trusted RoomModel.width/depth."""

    method: str = "photo-geometry-v1"
    drawable: bool
    reason: str
    reference_wall_a: str = ""
    wall_descriptions: dict[str, str] = Field(default_factory=dict)
    walls_seen: list[str] = Field(default_factory=list)
    shape: str = "unknown"
    width: Bound | None = None  # along wall A
    depth: Bound | None = None  # along wall B
    features: list[FeatureEstimate] = Field(default_factory=list)
    omitted_features: list[str] = Field(default_factory=list)  # reported by the model but not supported by a usable photo
    scale_cues: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    missing_views: list[str] = Field(default_factory=list)
    reasoning: str = ""
    synthetic: bool = False
    # True = walls/features were observed but the size could not be estimated: a NOT-TO-SCALE record of what was
    # seen. Never drawable, never used to place furniture or check fit.
    observed_only: bool = False


class PlanEstimate(BaseModel):
    """A room size ESTIMATED from one printed floor-plan reading the user selected (no exact-unit certification).
    Never a verified constraint: drawn at the conservative lower bounds, labeled "Estimated from floor plan",
    and the room's scale_status stays "unknown" so fit is never claimed as checked."""

    method: str = "plan-estimate-v1"
    width: Bound  # along wall A (assumption: the first printed number)
    depth: Bound
    source_id: str
    source_label: str = ""
    room_version_id: str  # the room version whose reading was chosen
    suggestion_index: int
    dimension_text: str
    room_label: str = ""
    plan_label: str = ""
    tolerance_in: float = 6.0
    note: str = ("Printed plan sizes are nominal and building plans can differ from your unit; this is an estimate, "
                 "not a measurement.")


RoomModel.model_rebuild()


# Keys that exist ONLY on AIGeometry. A live model put them beside `geometry` instead of inside it, and the old
# schema silently dropped them (real size ranges and reasoning lost).
GEOMETRY_ONLY_KEYS = ("scale", "missing_views", "reasoning")


class PhotoAnalysisOutput(BaseModel):
    """Top level of the room-evidence tool output. Unknown keys are rejected (so nothing is silently dropped and the
    model gets one bounded correction retry), except the exact GEOMETRY_ONLY_KEYS misplaced beside a present
    `geometry` object: those are moved inside it when the nested field is absent, and refused if they conflict."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _nest_misplaced_geometry_keys(cls, data):
        if not isinstance(data, dict):
            return data
        data = {k: v for k, v in data.items() if k != "schema_repairs"}  # only the app records repairs
        stray = [k for k in GEOMETRY_ONLY_KEYS if k in data]
        geo = data.get("geometry")
        if not stray or not isinstance(geo, dict):
            return data  # no geometry object: stray keys stay and are rejected as unknown fields
        geo = dict(geo)
        moved = []
        for k in stray:
            top = data.pop(k)
            nested = geo.get(k)
            if nested in (None, "", []):
                geo[k] = top
                moved.append(k)
            elif nested != top:
                raise ValueError(f"`{k}` given both inside `geometry` and at the top level with different values; "
                                 f"put it only inside `geometry`.")
        data["geometry"] = geo
        if moved:
            data["schema_repairs"] = [f"moved top-level {', '.join(moved)} into geometry (nested values were absent)"]
        return data

    # Set only by the validator above (recorded as provenance); the model is told not to fill it.
    schema_repairs: SkipJsonSchema[list[str]] = Field(default_factory=list, max_length=5)  # not in the tool schema
    room_type_seen: Literal["bedroom", "studio", "living_room", "other", "unclear"]
    per_photo: list[AIPhotoNote] = Field(default_factory=list, max_length=12)
    shape_guess: Literal["rectangular", "l_shaped", "irregular", "unknown"] = "unknown"
    features: list[AIFeature] = Field(default_factory=list, max_length=30)
    existing_items: list[AIExistingItem] = Field(default_factory=list, max_length=20)
    scale_cues: list[AIScaleCue] = Field(default_factory=list, max_length=10)
    dimension_guess: AIDimensionGuess | None = None
    floorplan_readings: list[AIFloorplanReading] = Field(default_factory=list, max_length=10)
    contradictions: list[str] = Field(default_factory=list, max_length=10)
    coverage_gaps: list[str] = Field(default_factory=list, max_length=10)
    untrusted_text_seen: list[str] = Field(default_factory=list, max_length=10)
    geometry: AIGeometry | None = None


# ---------------------------------------------------------------- preferences
class Preferences(BaseModel):
    budget_cents: int | None = Field(default=None, ge=0, le=5_000_000)
    reserve_pct: int = Field(default=10, ge=0, le=40)
    location: str = Field(default="New Haven, CT", max_length=80)
    styles: list[Style] = Field(default_factory=list)
    condition: Condition = "either"
    categories: list[Category] = Field(default_factory=list)
    priorities: list[Priority] = Field(default_factory=list)
    bed_size: Literal["twin", "full", "queen", "king", "any"] = "any"
    shared_use: bool = False
    studio_zones: list[Literal["sleep", "work", "lounge", "storage"]] = Field(default_factory=list)
    sofa_bed: Literal["no", "ok", "prefer"] = "ok"
    # How Balanced/Priority-led trade money for preference matches: "save" (only very cheap gains), "balanced",
    # "use_for_preferences" (spend within the cap when an option matches more of your style/priorities). Value is
    # always the cheapest verified set. Never "spend for spending's sake": ties always go to the cheaper option.
    budget_approach: Literal["save", "balanced", "use_for_preferences"] = "balanced"
    # Stores to choose from (retailer names as shown, e.g. "IKEA US", "Article"); empty = any store. Applies to
    # imported listings too (their store is the retailer the page adapter recorded; imports are kept, just not used).
    retailers: list[str] = Field(default_factory=list, max_length=8)
    pinned_product_ids: dict[str, str] = Field(default_factory=dict)  # category -> product id kept
    excluded_product_ids: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    existing_items: list[ExistingItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("styles", "categories", "priorities", "studio_zones", "excluded_product_ids", "excluded_terms", "retailers")
    @classmethod
    def _dedupe(cls, v):
        seen, out = set(), []
        for x in v:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    @field_validator("excluded_terms", "notes")
    @classmethod
    def _short_strings(cls, v):
        return [s[:120] for s in v][:30]


def default_preferences(room_type: str) -> Preferences:
    if room_type == "living_room":
        # Plain sofas are now in the verified catalog (Article), so new living rooms start with a sofa. Living rooms
        # created earlier keep their saved preference versions (sofa bed) unchanged.
        return Preferences(categories=["sofa", "coffee_table", "bookcase"], priorities=["style", "price"],
                           sofa_bed="ok")
    if room_type == "studio":
        return Preferences(
            categories=["sofa_bed", "desk", "desk_chair", "dresser", "coffee_table"],
            studio_zones=["sleep", "work", "lounge", "storage"],
            priorities=["small_footprint", "price"],
        )
    return Preferences(categories=["bed_frame", "mattress", "nightstand", "dresser"], priorities=["price", "storage"])


# ---------------------------------------------------------------- AI output (preference edits)
class PreferencePatch(BaseModel):
    """A typed edit proposed by the preference agent. Code validates and applies it."""

    set_budget_usd: int | None = Field(default=None, ge=0, le=50_000)
    set_condition: Condition | None = None
    set_styles: list[Style] | None = Field(
        default=None,
        description="REPLACE the whole style list with exactly these styles. Use for 'switch/change the style to X', "
                    "'make it X instead', 'only X'. Previous styles are dropped. Leave null if styles should not be replaced.",
    )
    add_styles: list[Style] = Field(
        default_factory=list,
        description="ADD styles while keeping the current ones. Use only for 'also X', 'add X', 'mix in X'. "
                    "Never use this for 'switch/change to X' (that is set_styles).",
    )
    remove_styles: list[Style] = Field(default_factory=list, description="Drop these styles, keeping the rest.")
    add_categories: list[Category] = Field(default_factory=list)
    remove_categories: list[Category] = Field(default_factory=list)
    add_priorities: list[Priority] = Field(default_factory=list)
    set_bed_size: Literal["twin", "full", "queen", "king", "any"] | None = None
    set_sofa_bed: Literal["no", "ok", "prefer"] | None = None
    set_budget_approach: Literal["save", "balanced", "use_for_preferences"] | None = Field(
        default=None, description="save = keep spending low; use_for_preferences = spend more of the budget on better matches")
    set_retailers: list[str] | None = Field(
        default=None, max_length=8, description="Only these stores (names as shown, e.g. 'IKEA US', 'Article'); [] = any store")
    keep_current_categories: list[Category] = Field(default_factory=list)  # pin the current plan's item
    replace_current_categories: list[Category] = Field(default_factory=list)  # exclude current item, pick another
    add_excluded_terms: list[str] = Field(default_factory=list, max_length=10)
    keep_existing_item_categories: list[str] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=200)
    unsupported_requests: list[str] = Field(default_factory=list, max_length=5)
    summary: str = Field(default="", max_length=300)


# ---------------------------------------------------------------- plans
class Placement(BaseModel):
    """An axis-aligned footprint in room coordinates (inches; origin = north-west corner, x east, y south)."""

    ref: str  # product_id or existing_item_id
    label: str
    x: float
    y: float
    w: float  # extent along x as drawn (already rotated)
    d: float  # extent along y as drawn
    zone: str | None = None
    category: str | None = None
    kind: Literal["product", "existing"] = "product"
    # Wall its back rests on: A-D relative to the photo reference wall (legacy versions used compass names).
    wall: Literal["A", "B", "C", "D", "north", "east", "south", "west", "free"] | None = None
    rotation: int = 0  # 0/90/180/270: direction the front faces (0 = faces south / into room from north wall)
    clearances: list[list[float]] = Field(default_factory=list)  # [x, y, w, d] assumed access zones
    open_extent: list[float] | None = None  # sofa bed/daybed opened: [x, y, w, d] (conservative upper bound)


class Associated(BaseModel):
    ref: str
    label: str
    on_ref: str | None  # item it belongs to (mattress -> bed frame, chair -> desk)
    note: str


class Unplaced(BaseModel):
    ref: str
    label: str
    reason: str


class FixedZone(BaseModel):
    label: str
    x: float
    y: float
    w: float
    d: float
    assumption: str  # why this zone exists and how it was positioned


class WallMarker(BaseModel):
    """A feature drawn ON a wall (e.g. a window). Not an obstacle; position from the room version."""

    kind: str
    wall: str
    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    caveat: str


class Arrangement(BaseModel):
    key: str
    title: str
    intent: str
    placements: list[Placement] = Field(default_factory=list)
    associated: list[Associated] = Field(default_factory=list)
    unplaced: list[Unplaced] = Field(default_factory=list)
    checks_passed: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    signature: str = ""


class LayoutSet(BaseModel):
    """Derived furniture arrangements for one shopping plan. Never source evidence."""

    method_version: str
    # concept_template is legacy (layout-v1 only; no longer generated). "unavailable" = room not mapped yet.
    basis: Literal["scaled_room_lower_bound", "estimated_from_photos", "estimated_from_plan", "synthetic_demo", "unavailable",
                   "concept_template"]
    envelope_width_in: float
    envelope_depth_in: float
    envelope_label: str
    width_range_in: list[float] | None = None  # [low, high] along wall A
    depth_range_in: list[float] | None = None  # [low, high] along wall B
    envelope_hash: str | None = None  # identical for every plan/arrangement built on the same room version
    wall_descriptions: dict[str, str] = Field(default_factory=dict)
    geometry_source_ids: list[str] = Field(default_factory=list)
    missing_views: list[str] = Field(default_factory=list)
    template_name: str | None = None  # legacy
    template_enlarged: bool = False  # legacy
    room_version_id: str | None = None
    floorplan_source_ids: list[str] = Field(default_factory=list)
    fixed_zones: list[FixedZone] = Field(default_factory=list)
    wall_markers: list[WallMarker] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    arrangements: list[Arrangement] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PlanItem(BaseModel):
    category: str
    product_id: str | None = None
    existing_item_id: str | None = None
    name: str
    retailer: str | None = None
    url: str | None = None
    price_cents: int | None = None
    width_in: float | None = None
    depth_in: float | None = None
    condition: str | None = None
    checked_at: str | None = None
    stale: bool = False
    availability: str | None = None
    fit_label: FitLabel = "Fit unverified"
    # What the fit label rests on (newer versions): {"product_size": known|unknown, "room_size": confirmed|unknown,
    # "size_check": passed|upper_bound_only|failed|not_run, "doors_paths": "not_checked"}. None on older versions.
    fit_checks: dict[str, str] | None = None
    zone: str | None = None  # primary studio zone
    zones: list[str] = Field(default_factory=list)  # every zone it serves (a sofa bed: sleep + lounge)
    image_url: str | None = None  # retailer's own product image from the exact snapshot (https only)
    origin: str | None = None
    notes: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    key: Literal["value", "balanced", "priority"]
    title: str
    items: list[PlanItem]
    subtotal_cents: int
    reserve_cents: int
    item_budget_cents: int | None
    budget_cents: int | None
    budget_status: Literal["within_item_budget_total_unverified", "over_budget", "no_budget_set"]
    fit_summary: FitLabel
    missing_required: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    # Budget use (newer versions; None/[] on older saved versions)
    item_allowance_cents: int | None = None  # budget minus delivery/tax reserve
    unused_cents: int | None = None
    budget_approach: str | None = None
    differences: list[str] = Field(default_factory=list)  # vs the Value plan, per category, with the reason
    # Plan-level fit evidence (newer versions; None on older ones): room size known?, item size checks
    # passed/failed/not run, reasons placement still needs review; doors and paths are never checked.
    fit_overview: dict | None = None
    layout: list[Placement] | None = None  # legacy field (always empty); see `layouts`
    layout_is_conceptual: bool = True
    layouts: LayoutSet | None = None  # None on plan versions saved before layout-v1


class IssueAction(BaseModel):
    """A direct next step for an issue. `find` searches for that category (and bed size); nothing changes settings."""

    kind: Literal["find", "edit_preferences"]
    label: str
    category: str | None = None
    size: Literal["twin", "full", "queen", "king"] | None = None


class PlanIssue(BaseModel):
    """Typed explanation of something that blocks or limits plans. Kinds are kept apart on purpose:
    catalog_gap = the saved collection lacks a matching verified product (says nothing about room fit);
    room_fit = verified options exist but none fits the confirmed room size; budget = nothing fits the item budget;
    settings = the user's own exclusions/settings rule every option out; pinned = a kept product no longer qualifies."""

    kind: Literal["catalog_gap", "room_fit", "budget", "settings", "pinned", "other"]
    title: str
    detail: str = ""
    categories: list[str] = Field(default_factory=list)
    size: str | None = None
    actions: list[IssueAction] = Field(default_factory=list)


class PlanSet(BaseModel):
    plans: list[Plan]
    notes: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)  # plain text, kept for every saved version (old ones only have this)
    issues: list[PlanIssue] = Field(default_factory=list)  # typed, newer versions only; [] on older saved versions
    changes: list[str] = Field(default_factory=list)
    room_scale_status: ScaleStatus = "unknown"
    room_layout: LayoutSet | None = None  # the mapped room with no furniture, when no shopping plan is feasible
