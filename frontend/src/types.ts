export type RoomType = "bedroom" | "studio" | "living_room";

export const ROOM_NAMES: Record<RoomType, string> = { bedroom: "Bedroom", studio: "Studio", living_room: "Living room" };

export interface PlacementT {
  ref: string;
  label: string;
  x: number;
  y: number;
  w: number;
  d: number;
  zone: string | null;
  category: string | null;
  kind: "product" | "existing";
  wall: "A" | "B" | "C" | "D" | "north" | "east" | "south" | "west" | "free" | null;
  rotation: number;
  clearances: number[][];
  open_extent: number[] | null;
}

export interface Arrangement {
  key: string;
  title: string;
  intent: string;
  placements: PlacementT[];
  associated: { ref: string; label: string; on_ref: string | null; note: string }[];
  unplaced: { ref: string; label: string; reason: string }[];
  checks_passed: string[];
  unresolved: string[];
  signature: string;
}

export interface LayoutSet {
  method_version: string;
  basis: "scaled_room_lower_bound" | "estimated_from_photos" | "estimated_from_plan" | "synthetic_demo" | "unavailable" | "concept_template";
  envelope_width_in: number;
  envelope_depth_in: number;
  envelope_label: string;
  width_range_in?: number[] | null;
  depth_range_in?: number[] | null;
  envelope_hash?: string | null;
  wall_descriptions?: Record<string, string>;
  geometry_source_ids?: string[];
  missing_views?: string[];
  template_name: string | null;
  template_enlarged: boolean;
  room_version_id: string | null;
  floorplan_source_ids: string[];
  fixed_zones: { label: string; x: number; y: number; w: number; d: number; assumption: string }[];
  wall_markers?: { kind: string; wall: string; x1: number; y1: number; x2: number; y2: number; label: string; caveat: string }[];
  assumptions: string[];
  arrangements: Arrangement[];
  notes: string[];
}

export interface ApartmentRoom {
  project_id: string;
  label: string;
  room_type: RoomType;
  name: string;
  photos: number;
  budget_cents: number | null;
  plan_count: number;
  has_layouts: boolean;
  mapped: boolean;
  scale_status: string;
}

export interface PlaceContext {
  property_name: string;
  city: string;
  state: string;
  zip: string;
  unit_label: string;
  property_url: string;
  condition: "new" | "secondhand" | "either";
  fulfillment: "local_pickup" | "delivery" | "either";
  timing: string;
  building?: SelectedBuilding | null;  // the building the user chose; older saved places don't have one
}

export interface SelectedBuilding {
  key: string;
  kind: "checked" | "web" | "url";
  name: string;
  address: string | null;  // null = unknown, never guessed
  site: string;
  url: string;
  directory?: string | null;
  selected_at: string;
}

export interface BuildingCandidate {
  key: string;
  kind: "checked" | "web";
  name: string;
  address: string | null;
  site: string;
  url: string;
  evidence: string[];
  // checked only
  directory?: string;
  city?: string;
  state?: string;
  zip?: string;
  observed_at?: string;
  source_page?: string;
  plan_count?: number;
  matched_on?: string[];
  also_in_search?: boolean;
  location_source?: string;
  suggested?: boolean;  // checked only: a cautious typo match ("Did you mean …?"); never auto-selected
  typed_name?: string;
  // web only
  urls?: string[];
  listing_site?: boolean;
  location_mentions?: string[];
  cited?: boolean;
  identity?: "building" | "source";  // sources (listing sites, bare site names, unnamed results) can only be viewed
  source_reason?: string | null;
}

export interface BuildingFind {
  query: { property_name: string; city: string; state: string; zip: string };
  checked: BuildingCandidate[];
  web: BuildingCandidate[];
  sources?: BuildingCandidate[];
  web_available: boolean;
  web_note: string | null;
  note: string;
  research: { searched_at: string; cached: boolean; web_search_calls: number; rejected_urls: number; query: string } | null;
}

export interface GalleryItem {
  url: string;
  name: string;
  alt: string;
  origin: "live" | "recovered" | "checked_reference" | "reader" | "third_party";
  found_on: string | null;
  seen_at: string | null;
  label: string | null;
  plan_type: "studio" | "1" | "2" | "3" | null;
  heading?: string;  // the page's own plan heading (names the plan); alt text is kept separately as provenance
  site?: string;  // third-party listing site
  method?: string;
  variants?: string[];
}

export interface ReaderMeta {
  service: string; reader_url: string; target_url: string; url_source: string; title: string;
  published_time: string | null; retrieved_at: string; cache_age: "unknown";
}

export const EMPTY_PLACE: PlaceContext = {
  property_name: "", city: "", state: "", zip: "", unit_label: "", property_url: "", condition: "either", fulfillment: "either", timing: "",
};

export interface Alternative {
  product_id: string;
  name: string | null;
  retailer: string | null;
  url: string | null;
  price_cents: number | null;
  width_in: number | null;
  depth_in: number | null;
  condition: string | null;
  condition_verified: boolean;
  checked_at: string | null;
  stale: boolean;
  availability: string | null;
  image_url: string | null;
  status: "verified" | "incomplete";
  origin: string | null;
  current: boolean;
  can_swap: boolean;
  reason: string | null;
  delta_cents: number | null;
  subtotal_after_cents: number | null;
  fit_note: string;
  delivery_note: string;
  style_match?: number;
  pref_points?: number;
  available?: boolean;  // false = out of stock when checked, or facts not verified
  recommended?: boolean;
  nominal_size?: string | null;
}

export interface ResearchResult {
  url: string;
  title: string;
  domain: string;
  evidence: string[];
  cited_text: string;
  primary?: boolean;
  low_relevance?: boolean;
  file_kind?: "pdf" | "image" | "file" | "page";
}

/** Friendly name for a stored source: never a bare number like "768" from a URL. */
export function sourceLabel(s: { kind: string; original_filename: string | null; source_url: string | null;
  provenance?: { reference_plan_name?: string } | null }): string {
  const base = s.kind === "photo" ? "Room photo" : s.kind.startsWith("floorplan") ? "Floor plan" : "Source";
  if (s.provenance?.reference_plan_name) return `${base}: ${s.provenance.reference_plan_name}`;
  const name = (s.original_filename || "").trim();
  const meaningful = name && !/^[\d_-]+(\.[a-z0-9]{2,5})?$/i.test(name) && !/^image(\.[a-z0-9]{2,5})?$/i.test(name);
  if (meaningful) return `${base}: ${name.slice(0, 40)}`;
  if (s.source_url) {
    try { return `${base} from ${new URL(s.source_url).hostname.replace(/^www\./, "")}`; } catch { /* fall through */ }
  }
  return base;
}

export interface Research {
  results: ResearchResult[];
  rejected_urls: number;
  web_search_calls: number;
  query: string;
  kind: string;
  searched_at: string;
  cached: boolean;
  note: string;
  summary: string;
  external_search_links?: { label: string; url: string; note: string; kind?: "store" | "secondhand" }[];
}

export interface ApartmentState {
  apartment: { id: string; name: string; preset: string; bedrooms: number; bathrooms: number; label: string; created_at: string };
  rooms: ApartmentRoom[];
  context: PlaceContext;
  context_version: number | null;
  fixed_spaces: { kind: "bathroom" | "kitchen"; label: string }[];
  notes: string[];
}

export interface ApartmentSummary {
  id: string;
  name: string;
  preset: string;
  bedrooms: number;
  bathrooms: number;
  label: string;
  rooms: number;
  created_at: string;
}
export type FitLabel = "Fits tested assumptions" | "Tight / conditional" | "Fit unverified" | "Does not fit";

export interface Project {
  id: string;
  name: string;
  room_type: RoomType;
  mode: "live" | "demo";
  is_demo: number;
  created_at: string;
  apartment_id?: string | null;
  apartment_room_label?: string | null;
}

export interface Source {
  id: string;
  kind: "photo" | "floorplan" | "floorplan_pdf" | "property_page" | "listing_page";
  sha256: string;
  media_type: string;
  original_filename: string | null;
  byte_size: number;
  source_url: string | null;
  retrieved_at: string | null;
  width: number | null;
  height: number | null;
  is_synthetic: number;
  created_at: string;
  derivative: { id: string; sha256: string; method_version: string; width: number; height: number } | null;
  provenance?: SourceProvenance | null;
}

export interface Bound {
  lower: number;
  central: number | null;
  upper: number;
  method: string;
  source_ids: string[];
  strength: string;
}

export interface Claim {
  kind: "observation" | "external_fact" | "hypothesis" | "verified_constraint";
  subject: string;
  statement: string;
  source_ids: string[];
  strength: string;
}

export interface ExistingItem {
  id: string;
  category: string; // a purchase category, or "unmatched" until the user chooses
  detected_label?: string; // original text from photo analysis
  description: string;
  keep: boolean;
  width_in: number | null;
  depth_in: number | null;
  footprint_source: "user_stated" | "unknown";
  source_ids: string[];
}

export interface RoomModel {
  room_type: RoomType;
  shape: string;
  scale_status: "unknown" | "plan_dimensions_user_confirmed" | "user_stated";
  width: Bound | null;
  depth: Bound | null;
  features: { id: string; kind: string; wall: string; description: string; source_ids: string[] }[];
  existing_items: ExistingItem[];
  claims: Claim[];
  contradictions: string[];
  coverage_notes: string[];
  untrusted_text_seen: string[];
  method: "live_ai" | "fixture" | "mocked_ai" | "manual";
  model: string | null;
  prompt_version: string | null;
  inferred_geometry?: InferredGeometry | null;
  // Size ESTIMATED from a printed floor-plan reading you picked (never a measurement; fit stays unverified).
  plan_estimate?: PlanEstimate | null;
}

export interface PlanEstimate {
  method: string;
  width: Bound;
  depth: Bound;
  source_id: string;
  source_label: string;
  room_version_id: string;
  suggestion_index: number;
  dimension_text: string;
  room_label: string;
  plan_label: string;
  tolerance_in: number;
  note: string;
}

export interface PlanSuggestion {
  dimension_text: string;
  room_label: string;
  plan_label: string;
  width_in: number;
  depth_in: number;
  source_ids: string[];
}

export interface Version<T> {
  id: string;
  version: number;
  parent_id: string | null;
  summary: string | null;
  method?: string;
  created_at: string;
  data: T;
  room_version_id?: string | null;
  preference_version_id?: string;
  source_ids?: string | string[];  // room versions: the analyzed sources (stored as a JSON string)
}

export interface Preferences {
  budget_cents: number | null;
  reserve_pct: number;
  location: string;
  styles: string[];
  condition: "new" | "secondhand" | "either";
  categories: string[];
  priorities: string[];
  bed_size: "twin" | "full" | "queen" | "king" | "any";
  shared_use: boolean;
  studio_zones: string[];
  sofa_bed: "no" | "ok" | "prefer";
  budget_approach?: "save" | "balanced" | "use_for_preferences";  // older saved versions lack it (= balanced)
  retailers?: string[];  // empty/absent = any store
  pinned_product_ids: Record<string, string>;
  excluded_product_ids: string[];
  excluded_terms: string[];
  existing_items: ExistingItem[];
  notes: string[];
}

export interface PlanItem {
  category: string;
  product_id: string | null;
  existing_item_id: string | null;
  name: string;
  retailer: string | null;
  url: string | null;
  price_cents: number | null;
  width_in: number | null;
  depth_in: number | null;
  condition: string | null;
  checked_at: string | null;
  stale: boolean;
  availability: string | null;
  fit_label: FitLabel;
  // What the label rests on (newer versions only).
  fit_checks?: { product_size: "known" | "unknown"; room_size: RoomSizeSource;
    size_check: "passed" | "upper_bound_only" | "failed" | "not_run" | "with_other_item"; doors_paths: "not_checked" } | null;
  zone: string | null;
  zones: string[];
  image_url: string | null;
  origin: string | null;
  notes: string[];
}

export interface Plan {
  key: "value" | "balanced" | "priority";
  title: string;
  items: PlanItem[];
  subtotal_cents: number;
  reserve_cents: number;
  item_budget_cents: number | null;
  budget_cents: number | null;
  budget_status: "within_item_budget_total_unverified" | "over_budget" | "no_budget_set";
  fit_summary: FitLabel;
  missing_required: string[];
  explanation: string[];
  item_allowance_cents?: number | null;
  unused_cents?: number | null;
  budget_approach?: string | null;
  differences?: string[];
  // Plan-level fit evidence (newer versions only).
  fit_overview?: { room_size: RoomSizeSource; size_checked: number; size_failed: number; size_not_run: number;
    review_reasons: string[]; doors_paths: "not_checked" } | null;
  layouts?: LayoutSet | null;
}

export interface IssueAction {
  kind: "find" | "edit_preferences";
  label: string;
  category: string | null;
  size: "twin" | "full" | "queen" | "king" | null;
}

/** Typed plan issue (newer plan versions). catalog_gap = nothing saved matches; it says nothing about room fit. */
export interface PlanIssue {
  kind: "catalog_gap" | "room_fit" | "budget" | "settings" | "pinned" | "other";
  title: string;
  detail: string;
  categories: string[];
  size: string | null;
  actions: IssueAction[];
}

export interface PlanSet {
  plans: Plan[];
  notes: string[];
  conflicts: string[];  // plain text; the only explanation on versions saved before typed issues
  issues?: PlanIssue[];
  changes: string[];
  room_scale_status: string;
  room_layout?: LayoutSet | null;
}

export interface ChecklistItem {
  product_id: string | null;  // null = furniture you already own
  owned: boolean;
  purchased: boolean | null;
  marked_at: string | null;
  category: string;
  name: string;
  retailer: string | null;
  url: string | null;
  image_url: string | null;
  price_cents: number | null;
  width_in: number | null;
  depth_in: number | null;
  condition: string | null;
  fit_label: FitLabel;
  fit_checks?: PlanItem["fit_checks"];
  checked_at: string | null;
  stale: boolean;
  availability: string | null;
}

export interface Checklist {
  plan_version: number | null;
  plan_key: string | null;
  plan_title: string | null;
  available_plans: { key: string; title: string }[];
  items: ChecklistItem[];
  counts: { to_buy: number; purchased: number; remaining: number; owned: number; price_unknown: number };
  subtotal_cents: number;
  purchased_cents: number;
  remaining_cents: number;
  retired_purchased: number;
  notes: string[];
}

export interface InferredGeometry {
  method: string;
  drawable: boolean;
  reason: string;
  reference_wall_a: string;
  wall_descriptions: Record<string, string>;
  walls_seen: string[];
  shape: string;
  width: Bound | null;
  depth: Bound | null;
  features: { kind: string; wall: string; start_frac: number; end_frac: number; uncertainty_frac: number; depth_in: number | null; source_ids: string[]; note: string }[];
  omitted_features?: string[];
  scale_cues: string[];
  source_ids: string[];
  missing_views: string[];
  reasoning: string;
  synthetic: boolean;
  observed_only?: boolean;  // walls/features seen but size unknown: NOT to scale, never used to place furniture
}

export const MAPPED_BASES = ["estimated_from_photos", "estimated_from_plan", "scaled_room_lower_bound", "synthetic_demo"];

export interface Snapshot {
  id: string;
  retailer: string;
  url: string;
  category: string;
  name: string | null;
  price_cents: number | null;
  width_in: number | null;
  depth_in: number | null;
  condition: string;
  condition_evidence: string;
  condition_verified?: boolean;
  checked_at: string;
  status: "verified" | "incomplete";
  missing: string[];
}

export interface ProjectState {
  project: Project;
  sources: Source[];
  room: (Version<{ room: RoomModel; plan_dimension_suggestions: PlanSuggestion[]; call: Record<string, unknown> | null }> & { method: string }) | null;
  preferences: Version<Preferences> | null;
  plans: Version<PlanSet> | null;
  versions: {
    room: { id: string; version: number; method: string; summary: string; created_at: string }[];
    preferences: { id: string; version: number; method: string; summary: string; created_at: string }[];
    plans: { id: string; version: number; summary: string; created_at: string; parent_id: string | null }[];
  };
  imported_listings: Snapshot[];
  apartment: { id: string; name: string; label: string } | null;
  layout_method: string;
  // typed_issues false = a version saved before typed issues; catalog_updated_after = products were added since.
  plans_info?: { typed_issues: boolean; catalog_updated_after: boolean; catalog_checked_max: string | null } | null;
}

export interface Status {
  model: string;
  live_ai_available: boolean;
  key_present: boolean;
  key_source: string | null;
  live_disabled_by_setting: boolean;
  catalog_products: number;
  catalog_verified: number;
  heic_supported: boolean;
  pdf_plan_reading: boolean;
  bed_size_coverage: Record<"bed_frame" | "mattress" | "daybed", string[]>;
  catalog_retailers?: Record<string, number>;  // store -> verified products in the saved collection
  prompt_versions: { room: string; preferences: string };
}

export interface Discovery {
  pages: { url: string; status: string; detail: string; source_id?: string; retrieved_at?: string; via?: string; reader?: ReaderMeta }[];
  // Listing-site pages from your search that name the building and its city/ZIP; read only if you choose one.
  alternatives?: { url: string; site: string; title: string; why: string; tried?: boolean; found?: number }[];
  unsupported_plans?: { url: string; alt: string; found_on?: string }[];  // SVG plan drawings this build can't import
  // Saved building discovery (from "This is my building"); absent on the older URL lookup.
  id?: string;
  version?: number;
  created_at?: string;
  building?: { key: string; kind: string; name: string; address: string | null; site: string; url: string } | null;
  gallery?: GalleryItem[];
  recovery?: { url: string; kind: string; why: string; status: string; found: number; detail: string }[];
  plan_images: { url: string; alt: string; found_on: string; kind?: string; label?: string }[];
  plan_pdfs: string[];
  plan_names: string[];
  unit_area_mentions: string[];
  notes: string[];
  reference?: ReferenceDirectory | null;
  website?: string | null;
  live_ok?: boolean;
}

export interface ReferenceDirectory {
  property: string;
  source_page: string;
  observed_at: string;
  method: string;
  note: string;
  directory: string;
  plans: { name: string; alt: string; url: string; kind: string; label: string }[];
}

export interface SourceProvenance {
  via: string;
  requested_url?: string;
  image_url?: string;
  image_retrieved_at?: string;
  reference_plan_name?: string;
  reference_source_page?: string;
  reference_observed_at?: string;
  caveat?: string;
}

export const CATEGORIES = [
  "bed_frame", "mattress", "sofa_bed", "daybed", "sofa", "desk", "desk_chair",
  "dresser", "nightstand", "wardrobe", "bookcase", "coffee_table",
] as const;
export const STYLES = [
  "minimal", "scandinavian", "modern", "traditional", "rustic", "mid_century",
  "industrial", "warm_wood", "light_neutral", "dark", "soft",
] as const;
export const PRIORITIES = ["price", "storage", "comfort", "work", "small_footprint", "style"] as const;

export const label = (s: string) => (s === "unmatched" ? "type not chosen" : s.replace(/_/g, " "));
export const money = (c: number | null | undefined) =>
  c == null ? "price unknown" : `$${(c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const inches = (v: number | null | undefined) => (v == null ? "?" : `${Math.round(v * 10) / 10}`);

/** Plain-language fit wording for a plan item. The stored label (and its checks) never claim a full fit:
 *  doors, walking paths and exact positions are not checked in this build. */
/** Where a room's size comes from, as the fit check reports it. Only "confirmed" (exact plan or a stated size)
 *  runs size checks; estimates are shown and drawn but never upgrade fit. */
export type RoomSizeSource = "confirmed" | "estimated_plan" | "estimated_photos" | "unknown";

const ROOM_SIZE_TEXT: Record<Exclude<RoomSizeSource, "confirmed">, { text: string; help: string }> = {
  estimated_plan: { text: "Estimated from floor plan", help: "The room is drawn from the printed size you picked on a floor plan. Your unit may differ, so fit isn’t checked." },
  estimated_photos: { text: "Estimated from photos", help: "The room is drawn at an approximate size from your photos, so fit isn’t checked." },
  unknown: { text: "Fit not assessed", help: "This room has no size yet, so fit isn’t assessed: pick a printed size on a floor plan, add photos, or tell us the size. No measuring needed." },
};

export function fitPlain(label: FitLabel, checks?: PlanItem["fit_checks"]): { text: string; help: string; tone: "ok" | "tight" | "unknown" | "bad" } {
  const after = " Doors, walking paths and exact positions aren’t checked.";
  if (label === "Does not fit") return { text: "Too big for this room", help: "Larger than your room’s known size, even at its biggest estimate." + after, tone: "bad" };
  if (checks?.size_check === "with_other_item") return { text: "Goes with its bed or desk", help: "It has no footprint of its own (it sits on the bed or tucks under the desk)." + after, tone: "tight" };
  if (label === "Tight / conditional" || label === "Fits tested assumptions") {
    if (checks?.size_check === "upper_bound_only") return { text: "May fit: only at the larger room estimate", help: "Its size plus the space in front fits only if the room is near its larger estimate." + after, tone: "tight" };
    return { text: "Size check passed: check doors & paths", help: "Its listed size plus the space in front fits your room’s known size." + after, tone: "tight" };
  }
  if (checks?.product_size === "unknown") return { text: "Product size unavailable", help: "This item’s size isn’t listed on its page, so it can’t be checked.", tone: "unknown" };
  const rs = checks?.room_size && checks.room_size !== "confirmed" ? checks.room_size : "unknown";
  if (rs === "unknown") return { text: "Fit not assessed", help: "The product’s size is known, but this room has no size yet, so fit isn’t assessed. Pick a printed size on your floor plan, add photos, or tell us the size you know." + after, tone: "unknown" };
  const src = ROOM_SIZE_TEXT[rs];
  return { text: src.text, help: src.help + after, tone: "unknown" };
}

/** Plain plan name. New versions store plain titles ("Save money", "Match my style", "Closer to my budget").
 *  Older saved versions keep their stored "Value: …" style titles; they're shown with today's names (the third
 *  older plan was "top priority", not the budget target). Stored data is never rewritten. */
export function planName(title: string | null | undefined): string {
  const t = (title ?? "").trim();
  const head = t.split(":")[0].trim();
  const old: Record<string, string> = { Value: "Save money", Balanced: "Match my style", "Priority-led": "Top priority first" };
  return t.includes(":") && old[head] ? old[head] : t || "Plan";
}

/** One-line description for a plan key (new versions). */
export const PLAN_BLURB: Record<string, string> = {
  value: "The cheapest checked set for the furniture you chose.",
  balanced: "Spends more only where an option better matches your styles or priorities.",
  priority: "Aims for 85–100% of your item allowance with only the furniture you chose, so you can see what the extra buys.",
};

/** Plain wording for the WHOLE plan, kept apart from the room: a confirmed room whose plan still has an
 *  unverified part says "Placement needs review" (with the reasons), never "Room size not confirmed". It never
 *  claims a guaranteed fit. `roomConfirmed` is used only for older versions without `fit_overview`. */
export function planFitPlain(plan: Plan, roomConfirmed: boolean): { text: string; help: string; tone: "ok" | "tight" | "unknown" | "bad" } {
  const ov = plan.fit_overview;
  const confirmed = ov ? ov.room_size === "confirmed" : roomConfirmed;
  const how = " Product sizes come from the store pages; the room size from your exact plan or a size you stated. "
    + "Door swings, walking paths and exact positions aren’t checked.";
  if (plan.fit_summary === "Does not fit") return { text: "An item is too big for this room", help: "At least one item is larger than your room’s known size allows." + how, tone: "bad" };
  if (!confirmed) {
    const src = ROOM_SIZE_TEXT[(ov?.room_size && ov.room_size !== "confirmed" ? ov.room_size : "unknown")];
    return { text: src.text, help: src.help + how, tone: "unknown" };
  }
  if (plan.fit_summary === "Fit unverified") {
    const why = ov?.review_reasons?.length ? ov.review_reasons.join(" ") : "Not everything in this plan could be checked against the room.";
    return { text: "Placement needs review", help: `${ov ? `${ov.size_checked} item size check(s) passed. ` : ""}${why}${how}`, tone: "tight" };
  }
  return { text: "Item sizes fit the room: check doors & paths", help: `${ov ? `${ov.size_checked} item size check(s) passed against your room’s known size. ` : ""}${(ov?.review_reasons ?? []).join(" ")}${how}`, tone: "tight" };
}
