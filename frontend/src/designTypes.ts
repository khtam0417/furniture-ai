// Whole-apartment design (design-first flow). Mirrors backend/furnishai/design.py and planmap.py.
export type Pt = [number, number];
export type BedSize = "twin" | "full" | "queen" | "king";

export type MapRoom = {
  id: string; label: string; kind: string; polygon: Pt[]; furnishable: boolean;
  dimension_text: string | null; dims_in: [number, number] | null; confidence: "low" | "medium" | "high";
  scale_ppi: number | null; scale_note: string; area_px: number;
  open_plan?: boolean; contains?: string[]; use_evidence?: string; user_set?: boolean;
};
export type RoomUse = { status: "confirmed" | "uncertain" | "conflict"; note: string; suggested_kind: string | null };
export const ROOM_KINDS = ["bedroom", "living", "dining", "studio", "kitchen", "bath", "closet", "laundry", "hall", "balcony", "other"] as const;
export const FURNISHABLE_KINDS = new Set(["bedroom", "living", "sleeping", "dining", "studio"]);
export type PlanMap = {
  method: string; prompt_version: string; model: string | null; source_id: string; derivative_sha256: string;
  image_w: number; image_h: number; status: "mapped" | "fallback"; view: string;
  rooms: MapRoom[]; walls: [Pt, Pt][]; openings: { id: string; kind: string; a: Pt; b: Pt }[];
  fixtures: { id: string; kind: string; polygon: Pt[] }[]; outline: Pt[];
  scale: { kind: "printed" | "relative"; ppi: number; from_rooms: string[]; note: string };
  rejected: string[]; limitations: string[]; untrusted_text_seen: string[]; synthetic: boolean;
  parent_map_id?: string | null; corrections?: { room_id: string; from: string; to: string; at: string }[];
};
export type DesignPrefs = {
  budget_cents: number | null; reserve_pct: number; approach: "low" | "use"; styles: string[];
  condition: "new" | "secondhand" | "either"; bed_size: BedSize; retailers: string[]; categories: string[];
  fulfillment?: "either" | "local_pickup" | "delivery"; timing?: string;
  resale_sites?: string[];  // approved resale marketplaces for secondhand (empty = all approved)
};
export type DesignItem = {
  id: string; category: string; zone_id: string | null; x: number; y: number; rotation: 0 | 90 | 180 | 270;
  size: BedSize | null; on_item: string | null; product_id: string | null; owned: boolean;
  placed?: boolean; unplaced_reason?: string | null;
};
export type Design = { plan_source_id: string; plan_map_id: string | null; arrangement: string | null; items: DesignItem[]; prefs: DesignPrefs };
export type PlanSource = {
  id: string; project_id: string; name: string; source_url: string | null; width: number; height: number;
  is_synthetic: boolean; created_at: string; preview: string; building: string | null; caveat: string | null; read: boolean;
};
export type ProductView = {
  id: string; name: string | null; retailer: string | null; url: string | null; price_cents: number | null;
  width_in: number | null; depth_in: number | null; height_in: number | null; condition: string | null;
  nominal_size: string | null; availability: string | null; checked_at: string | null; origin: string | null;
};
export type Missing = { id: string; category: string; name: string; zone_id: string | null; reason: string };
export type BudgetSummary = {
  subtotal_cents: number; reserve_cents: number; item_allowance_cents: number | null; budget_cents: number | null;
  remaining_cents: number | null; over_allowance: boolean; status: "empty" | "complete" | "incomplete";
  chosen: number; to_buy: number; owned: number; missing: Missing[]; note: string;
  // Chosen products the item budget can't hold: kept and counted in the subtotal, but not done (replace or remove).
  budget_review?: BudgetReview[];
};
export type BudgetReview = { id: string; category: string; name: string; price_cents: number; share_cents: number;
  over_whole_budget: boolean; message: string };
export type DesignState = {
  apartment: { id: string; name: string };
  design: { id: string; version: number; data: Design; created_at: string; summary: string } | null;
  plan_map: { id: string; data: PlanMap; method: string; model: string | null; prompt_version: string;
    call: Record<string, unknown> | null; created_at: string } | null;
  selected_source: PlanSource | null;
  plan_sources: PlanSource[];
  suggested_source_id: string | null;
  evaluation: { warnings: Record<string, string[]>; budget: BudgetSummary;
    review?: Record<string, { problems: string[]; can_move: boolean }>; targets?: Record<string, PlanTarget> } | null;
  products: Record<string, ProductView>;
  rooms: { project_id: string; label: string; room_type: string }[];
  anchor_project_id: string | null;
  versions: number;
  changes: string[];
  reused?: boolean;
  room_uses: Record<string, RoomUse>;
  current_prompt_version: string;
  map_outdated: boolean;
  zone_names?: Record<string, string>;  // display names; repeated labels are numbered ("BEDROOM 1", "BEDROOM 2")
  location?: string;  // the place's public city/state/ZIP (never the unit)
};
export type Arrangement = { key: string; title: string; description: string; items: DesignItem[]; warnings: number; unplaced: number };
export type Candidate = {
  product_id: string; name: string | null; retailer: string | null; url: string | null; price_cents: number | null;
  condition: string | null; availability: string | null; width_in: number | null; depth_in: number | null; height_in: number | null;
  nominal_size: string | null; image: string | null; checked_at: string | null; stale: boolean; style_matches: string[];
  origin: string | null; warnings: string[]; new_warnings: string[]; fit_basis: "printed" | "relative";
  size_mismatch?: boolean;
  condition_verified?: boolean; condition_evidence?: string | null;
  style_score?: number; style_label?: string; picked_elsewhere?: boolean;
  budget_left_cents?: number | null; over_budget_by_cents?: number | null;
  budget_target_cents?: number | null; over_target_by_cents?: number | null; open_pieces?: number | null;
  placement?: { status: "fits" | "moved" | "conflict" | "not_placed"; hard: string[]; soft: string[] };
  variants?: number; variant_names?: (string | null)[];
  read_via?: string | null; freshness?: string | null;  // "public_reader": facts from a public page copy, freshness unknown
  // within_budget: price within the whole remaining item budget; affordable: also within this piece's share.
  within_budget?: boolean; affordable?: boolean; blocked?: string | null;  // blocked: why it can't be chosen
};
/** Counts of checked options that aren't recommended (never offered as ready choices). */
export type HeldBack = { over_budget?: number; over_share?: number; doesnt_fit?: number; picked_elsewhere?: number; unavailable?: number };
/** `total*` count only ready recommendations (fit, affordable, not taken); `total_all` every matching option. */
export type Preview = { candidates: Candidate[]; total: number; total_new: number; total_used: number; reason: string | null; group: string;
  fitting?: number; fitting_affordable?: number; target?: PlanTarget | null;
  total_all?: number; held_back?: HeldBack; held_text?: string | null };
export type AssistantProposal = { kind: string; label: string; nav?: boolean; step?: string; item_id?: string };
export type AssistantReply = { reply: string; intent: "answer" | "change" | "navigate" | "unsupported"; proposals: AssistantProposal[];
  dropped: string[]; proposal_id: string | null; version: number; mode: "live" | "mocked" | "offline" };
export type PlanTarget = { target_cents: number; basis: string; note?: string | null; cheapest_known_cents: number | null;
  open_pieces: number; left_cents: number };
export type UsedCheck = { outcome: string; product_id: string | null; status: string | null; missing: string[];
  evidence: string | null; price_cents?: number | null; sold?: boolean };
export type Lead = {
  url: string; title: string | null; domain: string | null; cited_text: string; kind: "product" | "store";
  checked: null | { status: string; missing: string[]; product_id: string; price_cents: number | null };
  used_check?: UsedCheck | null;
  resale_site?: string | null;  // an individual listing on an approved resale marketplace (else null)
};
/** Approved resale marketplaces (mirrors backend/furnishai/resale.py). */
export const RESALE_SITES: [string, string, string][] = [
  ["aptdeco", "AptDeco", "aptdeco.com"], ["chairish", "Chairish", "chairish.com"], ["ebay", "eBay", "ebay.com"],
  ["facebook", "Facebook Marketplace", "facebook.com/marketplace"], ["craigslist", "Craigslist", "craigslist.org"],
];
export type OnlineLeads = { leads: Lead[]; query: string | null; searched_at: string | null; cached: boolean; summary_note: string;
  refined?: boolean; product_leads?: number; hidden_unapproved?: number; trust_note?: string; source_note?: string };
export type ItemProducts = {
  item: DesignItem; candidates: Candidate[]; reason: string | null; version: number; size: string | null;
  search_links: { label: string; url: string; note: string; kind?: string }[];
  total: number; offset: number; limit: number; browse_size: string | null;
  online: OnlineLeads | null; online_available: boolean; refine_available?: boolean;
  reason_kind?: "condition" | "size" | "other" | null; needs_location?: boolean; condition?: string;
  secondhand?: OnlineLeads | null; trust_note?: string; style_fallback?: string | null;
  scope?: "recommended" | "within_budget"; held_back?: HeldBack; held_text?: string | null; total_all?: number;
  broader?: number;  // options within the whole budget that aren't recommended (above the share, or not fitting)
};
export type ProductQuery = { offset?: number; limit?: number; sort?: "recommended" | "price_low" | "price_high"; styles_only?: boolean;
  max_price_cents?: number | null; size?: string | null; scope?: "recommended" | "within_budget" };
export type DesignChecklist = {
  version: number;
  budget?: BudgetSummary;
  zones?: Record<string, string>;
  checklist: null | {
    rows: { product_id: string; name: string | null; category: string; retailer: string | null; url: string | null;
      unit_price_cents: number | null; condition: string | null; width_in: number | null; depth_in: number | null;
      checked_at: string | null; stale: boolean; read_via?: string | null; quantity: number; line_total_cents: number; purchased_count: number;
      instances: { id: string; zone_id: string | null; purchased: boolean }[]; budget_review?: string[] }[];
    owned: { id: string; category: string; name: string; zone_id: string | null }[];
    missing: Missing[]; total_cents: number; status: "empty" | "complete" | "incomplete"; purchased: number; units: number;
    budget_review?: number;  // chosen products over the item budget (listed; the list isn't complete)
  };
};
export type ItemOp =
  | { op: "move"; id: string; x: number; y: number }
  | { op: "rotate"; id: string; rotation: 0 | 90 | 180 | 270 }
  | { op: "zone"; id: string; zone_id: string }
  | { op: "add"; category: string; zone_id?: string | null }
  | { op: "remove"; id: string }
  | { op: "owned"; id: string; owned: boolean }
  | { op: "size"; id: string; size: BedSize }
  | { op: "add_set"; zone_id: string }
  | { op: "attach"; id: string; host_id: string };

// Typical draft footprints (inches), mirrored from the backend for drawing only; never product facts.
export const BED_IN: Record<BedSize, [number, number]> = { twin: [41, 80], full: [56, 80], queen: [64, 84], king: [80, 84] };
export const CONCEPT_IN: Record<string, [number, number]> = {
  nightstand: [20, 16], dresser: [48, 18], desk: [48, 24], desk_chair: [0, 0], sofa: [84, 36], sofa_bed: [80, 38],
  daybed: [41, 80], coffee_table: [40, 20], bookcase: [32, 14], wardrobe: [40, 24], mattress: [0, 0],
  tv: [0, 0], tv_stand: [60, 16], dining_table: [48, 30], dining_chair: [18, 20], armchair: [32, 32], side_table: [20, 20],
  ottoman: [24, 18], console_table: [42, 14], shoe_storage: [36, 14], floor_lamp: [14, 14],
};
/** Grouped choices for "Add pieces". */
export const PIECE_GROUPS: [string, string[]][] = [
  ["Sleep", ["bed_frame", "mattress", "nightstand", "daybed", "sofa_bed"]],
  ["Living", ["sofa", "armchair", "coffee_table", "side_table", "ottoman", "tv_stand", "tv"]],
  ["Dining", ["dining_table", "dining_chair"]],
  ["Storage", ["dresser", "wardrobe", "bookcase", "console_table", "shoe_storage"]],
  ["Work", ["desk", "desk_chair"]],
  ["Lighting", ["floor_lamp"]],
];
export const PIECE_NAMES: Record<string, string> = {
  bed_frame: "Bed frame", mattress: "Mattress", nightstand: "Nightstand", dresser: "Dresser", desk: "Desk",
  desk_chair: "Desk chair", sofa: "Sofa", sofa_bed: "Sofa bed", daybed: "Daybed", coffee_table: "Coffee table",
  bookcase: "Bookcase", wardrobe: "Wardrobe", tv: "TV", tv_stand: "TV stand / media console", dining_table: "Dining table",
  dining_chair: "Dining chair", armchair: "Armchair", side_table: "Side / end table", ottoman: "Ottoman",
  console_table: "Console table", shoe_storage: "Shoe rack / storage bench", floor_lamp: "Floor lamp",
};

export function pieceName(it: { category: string; size?: string | null }): string {
  const base = PIECE_NAMES[it.category] ?? it.category.replace(/_/g, " ");
  return it.size && (it.category === "bed_frame" || it.category === "mattress") ? `${cap(it.size)} ${base.toLowerCase()}` : base;
}
const FIELD_NAMES: Record<string, string> = {
  name: "product name", price_cents: "price", width_in: "width", depth_in: "depth", height_in: "height",
  condition: "condition", category: "product type", "open footprint": "open size",
};
/** Display names for missing product facts (the stored field list is unchanged). */
export function readableMissing(fields: string[]): string {
  return fields.map((f) => FIELD_NAMES[f] ?? f.replace(/_/g, " ")).join(", ");
}
export function cap(s: string): string { return s.charAt(0).toUpperCase() + s.slice(1); }

/** Width x depth in inches: the chosen product's listed size, else the draft size. */
export function footprint(it: DesignItem, products: Record<string, { width_in: number | null; depth_in: number | null }>): { w: number; d: number; actual: boolean } {
  const p = it.product_id ? products[it.product_id] : undefined;
  if (p && p.width_in && p.depth_in && !it.on_item) return { w: p.width_in, d: p.depth_in, actual: true };
  if (it.category === "bed_frame") { const [w, d] = BED_IN[it.size ?? "queen"]; return { w, d, actual: false }; }
  if (it.category === "mattress" && !it.on_item) { const [w, d] = BED_IN[it.size ?? "queen"]; return { w: w - 4, d: d - 4, actual: false }; }
  const [w, d] = CONCEPT_IN[it.category] ?? [30, 20];
  return { w, d, actual: false };
}
