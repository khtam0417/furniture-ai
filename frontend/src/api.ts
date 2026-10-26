import type {
  Alternative, ApartmentState, ApartmentSummary, BuildingFind, Checklist, Discovery, PlaceContext, Preferences, Project, ProjectState, Research, Snapshot, Status,
} from "./types";
import type { Arrangement, AssistantReply, DesignChecklist, DesignPrefs, DesignState, ItemOp, ItemProducts, OnlineLeads, Preview, ProductQuery } from "./designTypes";
import type { FindGroup, GroupResult } from "./design/findQueue";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", ...init });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? "Some values are not valid." : `Request failed (${res.status}).`;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

export const api = {
  status: () => call<Status>("/api/status"),
  projects: () => call<Project[]>("/api/projects"),
  createProject: (name: string, room_type: string) => call<ProjectState>("/api/projects", json("POST", { name, room_type, mode: "live" })),
  createDemo: (room_type: string) => call<ProjectState>("/api/demo", json("POST", { room_type })),
  project: (id: string) => call<ProjectState>(`/api/projects/${id}`),
  deleteProject: (id: string) => call<{ deleted: string }>(`/api/projects/${id}`, { method: "DELETE" }),
  upload: (id: string, files: File[], kind: "photo" | "floorplan") => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("kind", kind);
    return call<{ results: { filename: string; ok: boolean; id?: string; error?: string; warning?: string; duplicate?: boolean }[]; notice: string | null; state: ProjectState }>(
      `/api/projects/${id}/uploads`,
      { method: "POST", body: fd },
    );
  },
  analyze: (id: string, note: string, floorplanSourceId?: string | null) =>
    call<{ reused: boolean; state: ProjectState }>(`/api/projects/${id}/analyze`,
      json("POST", { note, ...(floorplanSourceId ? { floorplan_source_id: floorplanSourceId } : {}) })),
  setScale: (id: string, body: { width_in: number; depth_in: number; basis: "plan_confirmed" | "user_stated"; source_ids: string[]; tolerance_in?: number; label?: string; exact_unit_confirmed?: boolean }) =>
    call<ProjectState>(`/api/projects/${id}/scale`, json("POST", body)),
  savePreferences: (id: string, prefs: Preferences) => call<ProjectState>(`/api/projects/${id}/preferences`, json("PUT", prefs)),
  edit: (id: string, message: string) =>
    call<{ method: string; changes: string[]; plan_changes: string[]; state: ProjectState }>(`/api/projects/${id}/edit`, json("POST", { message })),
  revert: (id: string, kind: "plan" | "preferences", version_id: string) => call<ProjectState>(`/api/projects/${id}/revert`, json("POST", { kind, version_id })),
  history: (id: string) => call<{ events: { kind: string; data: unknown; created_at: string }[] }>(`/api/projects/${id}/history`),
  property: (id: string, url: string) => call<{ discovery: Discovery; state: ProjectState }>(`/api/projects/${id}/property`, json("POST", { url })),
  propertyPlanImage: (id: string, url: string, discoveryId?: string) =>
    call<{ source: { id: string; duplicate: boolean }; state: ProjectState }>(`/api/projects/${id}/property/plan-image`,
      json("POST", { url, ...(discoveryId ? { discovery_id: discoveryId } : {}) })),
  findBuildings: (id: string, body: { property_name: string; city: string; state: string; zip: string; include_web: boolean }) =>
    call<BuildingFind>(`/api/projects/${id}/buildings/find`, json("POST", body)),
  selectBuilding: (id: string, body: { kind: "checked" | "web" | "url"; key?: string; url?: string; property_name?: string; city?: string; state?: string; zip?: string }) =>
    call<{ discovery: Discovery; state: ProjectState; apartment: ApartmentState | null }>(`/api/projects/${id}/buildings/select`, json("POST", body)),
  placeDiscovery: (id: string) => call<{ discovery: Discovery | null; note: string | null }>(`/api/projects/${id}/place-discovery`),
  discoveryAlternative: (id: string, discoveryId: string, url: string) =>
    call<{ discovery: Discovery }>(`/api/projects/${id}/place-discovery/${discoveryId}/alternative`, json("POST", { url })),
  listing: (id: string, url: string, category: string, condition: string, rebuildPlans = true) =>
    call<{ snapshot: Snapshot; warning: string | null; plans_rebuilt: boolean; state: ProjectState }>(`/api/projects/${id}/listings`,
      json("POST", { url, category, condition, rebuild_plans: rebuildPlans })),
  usage: (id: string) => call<{ rate_table: unknown; calls: Record<string, unknown>[]; estimated_cost_usd_total: number }>(`/api/projects/${id}/usage`),
  exportPlan: (id: string) => call<{ markdown: string }>(`/api/projects/${id}/export`),
  generateLayouts: (id: string) => call<ProjectState>(`/api/projects/${id}/layouts`, { method: "POST" }),
  apartments: () => call<ApartmentSummary[]>("/api/apartments"),
  apartment: (id: string) => call<ApartmentState>(`/api/apartments/${id}`),
  createApartment: (name: string, preset: string, bedrooms?: number, bathrooms?: number, context?: PlaceContext) =>
    call<ApartmentState>("/api/apartments", json("POST", { name, preset, ...(preset === "custom" ? { bedrooms, bathrooms } : {}), ...(context ? { context } : {}) })),
  saveContext: (id: string, context: PlaceContext) => call<ApartmentState>(`/api/apartments/${id}/context`, json("PUT", context)),
  alternatives: (id: string, planKey: string, category: string) =>
    call<{ alternatives: Alternative[]; plan_version: number; subtotal_cents: number; item_budget_cents: number | null; note: string }>(
      `/api/projects/${id}/alternatives?plan_key=${encodeURIComponent(planKey)}&category=${encodeURIComponent(category)}`),
  swap: (id: string, planKey: string, category: string, productId: string, expectedPlanVersion: number) =>
    call<ProjectState>(`/api/projects/${id}/swap`, json("POST", {
      plan_key: planKey, category, product_id: productId, expected_plan_version: expectedPlanVersion })),
  researchProperty: (id: string, body: { property_name?: string; city?: string; state?: string; zip?: string }) =>
    call<Research>(`/api/projects/${id}/research/property`, json("POST", body)),
  researchFurniture: (id: string, body: { category: string; budget_usd?: number; size?: string }) =>
    call<Research & { size?: string | null }>(`/api/projects/${id}/research/furniture`, json("POST", body)),
  planEstimate: (id: string, roomVersionId: string, suggestionIndex: number, sourceId: string) =>
    call<ProjectState>(`/api/projects/${id}/plan-estimate`, json("POST", {
      room_version_id: roomVersionId, suggestion_index: suggestionIndex, source_id: sourceId })),
  rebuildPlans: (id: string) => call<ProjectState>(`/api/projects/${id}/plans`, { method: "POST" }),  // appends a new version
  storeLinks: (id: string, category: string, size?: string) =>
    call<{ links: { label: string; url: string; note: string; kind?: string }[]; size: string | null }>(
      `/api/projects/${id}/store-links?category=${encodeURIComponent(category)}${size ? `&size=${encodeURIComponent(size)}` : ""}`),
  checklist: (id: string) => call<Checklist>(`/api/projects/${id}/checklist`),
  selectPlan: (id: string, planKey: string, expectedPlanVersion: number) =>
    call<Checklist>(`/api/projects/${id}/checklist/plan`, json("PUT", { plan_key: planKey, expected_plan_version: expectedPlanVersion })),
  markPurchased: (id: string, planKey: string, productId: string, purchased: boolean, expectedPlanVersion: number) =>
    call<Checklist>(`/api/projects/${id}/checklist/mark`, json("POST", {
      plan_key: planKey, product_id: productId, purchased, expected_plan_version: expectedPlanVersion })),
  // Whole-apartment design (design-first flow)
  design: (aid: string) => call<DesignState>(`/api/apartments/${aid}/design`),
  designSelectPlan: (aid: string, sourceId: string, expectedVersion?: number) =>
    call<DesignState>(`/api/apartments/${aid}/design/plan`, json("POST", { source_id: sourceId, expected_version: expectedVersion ?? null })),
  designRead: (aid: string, v: number) => call<DesignState>(`/api/apartments/${aid}/design/read`, json("POST", { expected_version: v })),
  designArrangements: (aid: string) => call<{ options: Arrangement[]; version: number }>(`/api/apartments/${aid}/design/arrangements`),
  designApplyArrangement: (aid: string, key: string, v: number) =>
    call<DesignState>(`/api/apartments/${aid}/design/arrangement`, json("POST", { key, expected_version: v })),
  designItems: (aid: string, ops: ItemOp[], v: number) => call<DesignState>(`/api/apartments/${aid}/design/items`, json("POST", { ops, expected_version: v })),
  designProducts: (aid: string, itemId: string, q: ProductQuery = {}) => {
    const qs = Object.entries(q).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
    return call<ItemProducts>(`/api/apartments/${aid}/design/items/${itemId}/products${qs ? `?${qs}` : ""}`);
  },
  designFindOnline: (aid: string, itemId: string, v: number, refine = false) =>
    call<{ online: OnlineLeads; refine_available: boolean; version: number }>(`/api/apartments/${aid}/design/items/${itemId}/find-online`,
      json("POST", { expected_version: v, refine })),
  designCheckLead: (aid: string, itemId: string, url: string, condition: string, v: number) =>
    call<{ status: string; matches: boolean; message: string; product_id: string; missing: string[] }>(
      `/api/apartments/${aid}/design/items/${itemId}/check-lead`, json("POST", { url, condition, expected_version: v })),
  designFindSecondhand: (aid: string, itemId: string, v: number, recheck = false) =>
    call<{ secondhand: OnlineLeads; verified_matches: number; checked: number; version: number }>(
      `/api/apartments/${aid}/design/items/${itemId}/find-secondhand`, json("POST", { expected_version: v, recheck })),
  // "Find furniture": the plan (no cost), one group's search+check, and saved previews (no cost)
  designFindPlan: (aid: string) => call<{ groups: FindGroup[]; branches: string[]; max_per_run: number; version: number }>(`/api/apartments/${aid}/design/find-plan`),
  designFindGroup: (aid: string, key: string, refine = false) =>
    call<GroupResult>(`/api/apartments/${aid}/design/find-group`, json("POST", { key, refine })),
  designAssistant: (aid: string, message: string, step: string, v: number) =>
    call<AssistantReply>(`/api/apartments/${aid}/design/assistant`, json("POST", { message, step, expected_version: v })),
  designAssistantApply: (aid: string, proposalId: string, accept: number[], v: number) =>
    call<DesignState>(`/api/apartments/${aid}/design/assistant/apply`, json("POST", { proposal_id: proposalId, accept, expected_version: v })),
  designFit: (aid: string, itemId: string, v: number) =>
    call<DesignState>(`/api/apartments/${aid}/design/items/${itemId}/fit`, json("POST", { expected_version: v })),
  designPreviews: (aid: string) => call<{ items: Record<string, Preview>; version: number }>(`/api/apartments/${aid}/design/previews`),
  designRoomUse: (aid: string, roomId: string, kind: string, v: number) =>
    call<DesignState>(`/api/apartments/${aid}/design/rooms/${roomId}/use`, json("POST", { kind, expected_version: v })),
  designChooseProduct: (aid: string, itemId: string, productId: string | null, v: number) =>
    call<DesignState>(`/api/apartments/${aid}/design/items/${itemId}/product`, json("POST", { product_id: productId, expected_version: v })),
  designAuto: (aid: string, v: number, replaceIds: string[] = []) =>
    call<DesignState>(`/api/apartments/${aid}/design/auto-products`, json("POST", { expected_version: v, replace_ids: replaceIds })),
  designPrefs: (aid: string, prefs: DesignPrefs, v: number) => call<DesignState>(`/api/apartments/${aid}/design/prefs`, json("PUT", { prefs, expected_version: v })),
  designChecklist: (aid: string) => call<DesignChecklist>(`/api/apartments/${aid}/design/checklist`),
  designMark: (aid: string, instanceId: string, productId: string, purchased: boolean, v: number) =>
    call<DesignChecklist>(`/api/apartments/${aid}/design/checklist/mark`, json("POST", { instance_id: instanceId, product_id: productId, purchased, expected_version: v })),
  deleteApartment: (id: string) => call<{ deleted: string }>(`/api/apartments/${id}`, { method: "DELETE" }),
};
