"""FastAPI app: API routes + the compiled React frontend from frontend/dist (one local server)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, fixtures
from .apartments import ApartmentContext, CreateApartment, fixed_spaces, label_for, rooms_for
from .planner import SwapRejected, alternatives_for, swap_plan
from .research import (
    CACHE_TTL_S, external_search_links, furniture_query, property_query, query_key, web_research,
)
from .catalog import CATEGORIES, is_stale, load_catalog
from .layout import LAYOUT_METHOD, generate_layouts, room_frame
from .config import MODEL, REPO_ROOT, Settings, get_settings
from .db import DB, new_id, now
from .models import Bound, EvidenceClaim, Plan, PlanEstimate, PlanSet, Preferences, RoomModel, default_preferences
from .planner import bed_size_coverage, build_plans
from .preferences import apply_patch, rule_based_patch
from .safe_fetch import FetchBlocked, FetchFailed, SafeFetcher
from .apartments import SelectedBuilding
from .research import public_url_ok
from starlette.concurrency import run_in_threadpool

from .sources import (
    _public_reference, building_candidates, checked_candidate, discover_property, fetch_plan_image, gallery,
    listing_alternatives, read_alternative, leads_to_check, check_lead_page,
    has_strong_plans, import_listing, match_directories, recover, reference_by_file, reference_for_image,
)
from .storage import DERIVATIVE_METHOD, SourceStore, UploadRejected, validate_image, validate_pdf
from .usage import Ledger
from .design_api import register_design_routes

COOKIE = "furnishai_session"
CATALOG_PATH = REPO_ROOT / "data" / "catalog" / "products.json"
DIST = REPO_ROOT / "frontend" / "dist"
MAX_FLOORPLANS = 2


class CreateProject(BaseModel):
    name: str = Field(default="My room", min_length=1, max_length=80)
    room_type: Literal["bedroom", "studio", "living_room"]
    mode: Literal["live", "demo"] = "live"


class DemoRequest(BaseModel):
    room_type: Literal["bedroom", "studio"]


class AnalyzeRequest(BaseModel):
    note: str = Field(default="", max_length=300)
    # The ONE floor plan to read with the room photos. Optional when the room has a single plan; required when it
    # has several (plans are never combined).
    floorplan_source_id: str | None = Field(default=None, max_length=80)


class SwapRequest(BaseModel):
    plan_key: Literal["value", "balanced", "priority"]
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    product_id: str = Field(min_length=1, max_length=80)
    # Optimistic concurrency: the plan version the user was looking at. If plans changed since, refuse (409).
    expected_plan_version: int | None = Field(default=None, ge=1)


class PropertyResearchRequest(BaseModel):
    property_name: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=40)
    zip: str = Field(default="", max_length=10)


class FurnitureResearchRequest(BaseModel):
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    condition: Literal["new", "secondhand", "either"] | None = None
    fulfillment: Literal["local_pickup", "delivery", "either"] | None = None
    budget_usd: int | None = Field(default=None, ge=1, le=50_000)
    # Bed frames/mattresses: the size to search for (default: the room's chosen bed size, if any).
    size: Literal["twin", "full", "queen", "king"] | None = None
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=40)
    zip: str = Field(default="", max_length=10)


class PlanSelectRequest(BaseModel):
    plan_key: Literal["value", "balanced", "priority"]
    expected_plan_version: int = Field(ge=1)


class PurchaseMarkRequest(BaseModel):
    plan_key: Literal["value", "balanced", "priority"]
    product_id: str = Field(min_length=1, max_length=80)
    purchased: bool
    expected_plan_version: int = Field(ge=1)


class PlanEstimateRequest(BaseModel):
    """Pick one printed reading of the CURRENT room version as this room's estimated size (no certification)."""
    room_version_id: str = Field(min_length=1, max_length=80)
    suggestion_index: int = Field(ge=0, le=50)
    source_id: str = Field(min_length=1, max_length=80)


class ScaleRequest(BaseModel):
    width_in: float = Field(gt=24, le=1200)
    depth_in: float = Field(gt=24, le=1200)
    basis: Literal["plan_confirmed", "user_stated"]
    # Required for plan_confirmed: the user states the plan is EXACTLY their unit's plan (not a similar layout).
    exact_unit_confirmed: bool = False
    tolerance_in: float = Field(default=3.0, ge=0.5, le=48)
    source_ids: list[str] = Field(default_factory=list, max_length=4)
    label: str = Field(default="", max_length=120)


class EditRequest(BaseModel):
    message: str = Field(min_length=1, max_length=800)


class RevertRequest(BaseModel):
    kind: Literal["plan", "preferences"]
    version_id: str


class UrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class PlanImageRequest(UrlRequest):
    # Optional: the saved building discovery this plan was chosen from (provenance is read from OUR record).
    discovery_id: str | None = Field(default=None, max_length=60)


class BuildingFindRequest(BaseModel):
    property_name: str = Field(min_length=1, max_length=120)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=40)
    zip: str = Field(default="", max_length=10)
    include_web: bool = True  # False = only the free, instant checked-directory match


class BuildingSelectRequest(BaseModel):
    kind: Literal["checked", "web", "url"]
    key: str = Field(default="", max_length=80)
    url: str = Field(default="", max_length=2048)
    property_name: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=40)
    zip: str = Field(default="", max_length=10)


class ListingRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    condition: Literal["new", "secondhand"] = "secondhand"
    # False = check-only import (compare/search): store the snapshot but keep the current plans exactly as they are,
    # so earlier swaps are never undone. Default True keeps the original "import and rebuild plans" behavior.
    rebuild_plans: bool = True


def create_app(settings: Settings | None = None, fetcher: SafeFetcher | None = None, test_model: Any = None,
               ai_transport: Any = None) -> FastAPI:
    """`test_model` and `ai_transport` are test seams. With `ai_transport` the REAL gpt-6-luna Portkey client is
    built and its outbound HTTP requests go to that transport instead of the network (the server never sets it)."""
    settings = settings or get_settings()
    db = DB(settings.storage_dir / "furnishai.sqlite3")
    store = SourceStore(settings.storage_dir)
    ledger = Ledger(db, settings.max_ai_calls_per_session_per_10min, settings.max_session_cost_usd, settings.max_app_daily_cost_usd)
    fetcher = fetcher or SafeFetcher()
    # The public page reader uses the SAME resolver/opener (so tests' fake networks cover it too). Optional.
    from .reader import PublicReader
    reader = PublicReader.from_fetcher(fetcher) if settings.public_reader else None
    catalog = load_catalog(CATALOG_PATH)

    def snap_hash(snap: dict) -> str:
        return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()

    for snap in catalog:
        db.upsert_snapshot(snap, snap_hash(snap), None)
    # Newest product check date in the shipped catalog (UTC ISO strings compare in time order).
    CATALOG_CHECKED_MAX = max((p.get("checked_at") or "" for p in catalog), default="") or None

    app = FastAPI(title="Furniture AI", version="0.2.0")
    app.state.db, app.state.settings, app.state.ledger = db, settings, ledger
    app.state.reader = reader

    # ------------------------------------------------------------ helpers
    def session(request: Request, response: Response) -> str:
        token = request.cookies.get(COOKIE)
        if not token or len(token) < 30:
            token = secrets.token_urlsafe(32)
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 60)
        return db.get_or_create_session(hashlib.sha256(token.encode()).hexdigest())

    def owned(project_id: str, sid: str) -> dict:
        p = db.project_for(project_id, sid)
        if not p:
            raise HTTPException(404, "Project not found.")
        return p

    def model_for_live():
        if test_model is not None:
            return test_model, True
        try:
            return ai.build_model(settings, transport=ai_transport), False
        except ai.AIError as exc:
            raise HTTPException(503, exc.public)

    def full_catalog(project_id: str) -> list[dict]:
        imported = {s["id"]: s for s in db.project_snapshots(project_id)}  # latest import of a page wins
        return catalog + list(imported.values())

    def head_room(project_id: str) -> RoomModel | None:
        h = db.head("room_versions", project_id)
        return RoomModel.model_validate(h["data"]["room"]) if h else None

    def head_prefs(project: dict) -> Preferences:
        h = db.head("preference_versions", project["id"])
        return Preferences.model_validate(h["data"]) if h else default_preferences(project["room_type"])

    def head_plans(project_id: str) -> PlanSet | None:
        h = db.head("plan_versions", project_id)
        return PlanSet.model_validate(h["data"]) if h else None

    def replan(project: dict, summary: str) -> dict:
        pid = project["id"]
        prefs_row = db.head("preference_versions", pid)
        if not prefs_row:
            prefs_row = db.add_preference_version(pid, default_preferences(project["room_type"]).model_dump(), "Defaults", "manual")
        prefs = Preferences.model_validate(prefs_row["data"])
        room_row = db.head("room_versions", pid)
        room = RoomModel.model_validate(room_row["data"]["room"]) if room_row else None
        cat = full_catalog(pid)
        ps = build_plans(prefs, cat, room, project["room_type"], head_plans(pid))
        by_id = {p["id"]: p for p in cat}
        attach_layouts(ps, by_id, prefs, room, project, room_row["id"] if room_row else None)
        used = sorted({i.product_id for pl in ps.plans for i in pl.items if i.product_id})
        refs = [{"product_id": u, "snapshot_hash": snap_hash(by_id[u]), "checked_at": by_id[u].get("checked_at"),
                 "source_sha256": by_id[u].get("source_sha256")} for u in used]
        row = db.add_plan_version(pid, ps.model_dump(), room_row["id"] if room_row else None, prefs_row["id"], refs, summary)
        db.event("plans_built", {"plan_version": row["version"], "plans": len(ps.plans), "conflicts": ps.conflicts}, pid)
        return row

    def attach_layouts(ps: PlanSet, by_id: dict, prefs: Preferences, room: RoomModel | None, project: dict,
                       room_version_id: str | None) -> None:
        """Derived arrangements for every plan; no AI call. The room frame is computed ONCE from the room version
        (before and independent of any products) and shared by every plan and arrangement."""
        fp_ids = [r["id"] for r in db.all("SELECT id FROM source_assets WHERE project_id=? AND kind IN "
                                          "('floorplan','floorplan_pdf') ORDER BY created_at", (project["id"],))]
        frame = room_frame(room, room_version_id, fp_ids)
        for pl in ps.plans:
            pl.layouts = generate_layouts(pl, by_id, prefs, frame)
        if not ps.plans:
            empty = Plan(key="value", title="Room only", items=[], subtotal_cents=0, reserve_cents=0, item_budget_cents=None,
                         budget_cents=None, budget_status="no_budget_set", fit_summary="Fit unverified")
            ps.room_layout = generate_layouts(empty, by_id, prefs, frame)

    def sources_public(project_id: str) -> list[dict]:
        rows = db.all("SELECT id, kind, sha256, media_type, original_filename, byte_size, source_url, retrieved_at, "
                      "width, height, is_synthetic, created_at FROM source_assets WHERE project_id=? ORDER BY created_at",
                      (project_id,))
        for r in rows:
            d = db.one("SELECT id, sha256, method_version, width, height FROM derivatives WHERE parent_source_id=?", (r["id"],))
            r["derivative"] = d
            prov = db.one("SELECT data FROM source_provenance WHERE source_id=?", (r["id"],))
            r["provenance"] = json.loads(prov["data"]) if prov else None
        return rows

    def add_image_source(pid: str, data: bytes, filename: str, kind: str, synthetic: bool = False,
                         source_url: str | None = None, retrieved_at: str | None = None) -> dict:
        img = validate_image(data, settings.max_upload_bytes, settings.max_pixels)
        sha, path = store.save_original(pid, data, img.media_type)
        existing = db.one("SELECT id FROM source_assets WHERE project_id=? AND sha256=?", (pid, sha))
        if existing:
            return {"id": existing["id"], "duplicate": True}
        sid = new_id("src")
        db.exec("INSERT INTO source_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, pid, kind, sha, img.media_type, (filename or "")[:120], len(data), str(path), source_url,
                 retrieved_at, img.width, img.height, int(synthetic), now()))
        dsha, dpath, w, h, _ = store.make_derivative(pid, data)
        db.exec("INSERT INTO derivatives VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("drv"), pid, sid, "ai_input_jpeg", dsha, "image/jpeg", DERIVATIVE_METHOD, w, h, str(dpath), now()))
        return {"id": sid, "duplicate": False}

    def store_html_source(pid: str, res, kind: str) -> str:
        sha, path = store.save_original(pid, res.body, "text/html")
        src_id = new_id("src")
        db.exec("INSERT INTO source_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (src_id, pid, kind, sha, "text/html", None, len(res.body), str(path), res.final_url,
                 res.retrieved_at, None, None, 0, now()))
        return src_id

    def store_reader_source(pid: str, rec) -> str:
        """The public reader's raw reply, stored immutably as fetched (text/plain). Its URL is the READER's address;
        the public page it read and the times are kept separately in its provenance (never as the official source)."""
        sha, path = store.save_original(pid, rec.fetch.body, "text/plain")
        src_id = new_id("src")
        db.exec("INSERT INTO source_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (src_id, pid, "property_reader_page", sha, "text/plain", None, len(rec.fetch.body), str(path),
                 rec.fetch.final_url, rec.fetch.retrieved_at, None, None, 0, now()))
        db.exec("INSERT OR IGNORE INTO source_provenance VALUES (?,?,?,?)",
                (src_id, pid, json.dumps({"via": "public page reader", **rec.reader, "status": rec.status}), now()))
        return src_id

    def floorplan_count(pid: str) -> int:
        return db.one("SELECT COUNT(*) n FROM source_assets WHERE project_id=? AND kind IN ('floorplan','floorplan_pdf')",
                      (pid,))["n"]

    def derivative_bytes(source_id: str) -> tuple[str, bytes]:
        d = db.one("SELECT sha256, storage_path FROM derivatives WHERE parent_source_id=?", (source_id,))
        return d["sha256"], Path(d["storage_path"]).read_bytes()

    def save_room(pid: str, room: RoomModel, suggestions: list[dict], source_ids: list[str], input_hash: str | None,
                  summary: str, call: dict | None = None, analysis_hash: str | None = None) -> dict:
        # analysis_hash names the analysis this version's evidence comes from (derived edits keep their head's), so a
        # cached analysis can tell whether the current head already derives from it.
        data = {"room": room.model_dump(), "plan_dimension_suggestions": suggestions, "call": call,
                "analysis_hash": analysis_hash}
        return db.add_room_version(pid, data, source_ids, room.method, room.model, room.prompt_version, input_hash, summary)

    def carry_known_size(old: RoomModel | None, room: RoomModel, read_ids: list[str]) -> RoomModel:
        """Carry a KNOWN size onto a newly analysed/restored room only when its provenance still holds: a size the user
        stated cites no source and carries; a plan-confirmed size carries only if its plan is among what was read.
        Only the claim that set the current size is carried, never a superseded or other plan's constraint."""
        if old is None or old.scale_status == "unknown" or old.width is None or old.depth is None:
            return room
        cited = set(old.width.source_ids) | set(old.depth.source_ids)
        if old.scale_status == "plan_dimensions_user_confirmed" and not (cited and cited <= set(read_ids)):
            return room
        claim = next((c for c in reversed(old.claims) if c.kind == "verified_constraint" and c.subject == "room scale"), None)
        return room.model_copy(update={"scale_status": old.scale_status, "width": old.width, "depth": old.depth,
                                       "claims": room.claims + ([claim] if claim else [])})

    def state(project: dict) -> dict:
        pid = project["id"]
        room_row = db.head("room_versions", pid)
        prefs_row = db.head("preference_versions", pid)
        plan_row = db.head("plan_versions", pid)
        return {
            "project": project,
            "sources": sources_public(pid),
            "room": room_row,
            "preferences": prefs_row,
            "plans": plan_row,
            "versions": {
                "room": [{k: r[k] for k in ("id", "version", "method", "summary", "created_at")} for r in db.versions("room_versions", pid)],
                "preferences": [{k: r[k] for k in ("id", "version", "method", "summary", "created_at")} for r in db.versions("preference_versions", pid)],
                "plans": [{k: r[k] for k in ("id", "version", "summary", "created_at", "parent_id")} for r in db.versions("plan_versions", pid)],
            },
            "imported_listings": db.project_snapshots(pid),
            "apartment": db.apartment_of_project(pid),
            "layout_method": LAYOUT_METHOD,
            # Saved plan versions are never rewritten. These flags let the UI offer a rebuild: older versions have
            # only plain-text conflicts, and the catalog may have gained products (e.g. twin) since they were built.
            "plans_info": None if not plan_row else {
                "typed_issues": "issues" in plan_row["data"],
                "catalog_updated_after": bool(CATALOG_CHECKED_MAX and CATALOG_CHECKED_MAX > plan_row["created_at"]),
                "catalog_checked_max": CATALOG_CHECKED_MAX,
            },
        }

    def owned_apartment(apartment_id: str, sid: str) -> dict:
        a = db.apartment_for(apartment_id, sid)
        if not a:
            raise HTTPException(404, "Apartment not found.")
        return a

    def apartment_state(a: dict) -> dict:
        rooms = []
        for r in db.apartment_rooms(a["id"]):
            pid = r["project_id"]
            prefs_row = db.head("preference_versions", pid)
            plan_row = db.head("plan_versions", pid)
            room_row = db.head("room_versions", pid)
            n_photos = db.one("SELECT COUNT(*) n FROM source_assets WHERE project_id=? AND kind='photo'", (pid,))["n"]
            plans = (plan_row or {}).get("data", {}).get("plans", [])
            rooms.append({
                "project_id": pid, "label": r["label"], "room_type": r["room_type"], "name": r["name"],
                "photos": n_photos,
                "budget_cents": (prefs_row or {}).get("data", {}).get("budget_cents"),
                "plan_count": len(plans),
                "has_layouts": bool(plans) and all(p.get("layouts") for p in plans),
                "mapped": bool(plans) and all((p.get("layouts") or {}).get("basis") in
                                              ("estimated_from_photos", "estimated_from_plan", "scaled_room_lower_bound", "synthetic_demo") for p in plans),
                "scale_status": (room_row or {}).get("data", {}).get("room", {}).get("scale_status", "unknown"),
            })
        ctx = db.apartment_context(a["id"])
        return {"apartment": {**a, "label": label_for(a["bedrooms"], a["bathrooms"])}, "rooms": rooms,
                "context": (ctx or {}).get("data") or ApartmentContext().model_dump(),
                "context_version": (ctx or {}).get("version"),
                "fixed_spaces": fixed_spaces(a["bedrooms"], a["bathrooms"]),
                "notes": ["Budgets are set per room. There is no combined or whole-apartment budget optimization.",
                          "The apartment type lists rooms only; it says nothing about room sizes or how rooms connect."]}

    # ------------------------------------------------------------ routes
    @app.get("/api/status")
    def status():
        return {**settings.public_status(), "catalog_products": len(catalog),
                "catalog_verified": sum(1 for p in catalog if p["status"] == "verified"),
                "heic_supported": False, "pdf_plan_reading": False,
                "bed_size_coverage": bed_size_coverage(catalog),
                # Stores with verified products in the saved collection (what the store filter can choose from).
                "catalog_retailers": {r: sum(1 for p in catalog if p.get("retailer") == r and p["status"] == "verified")
                                      for r in sorted({p.get("retailer") for p in catalog if p.get("retailer")})},
                "prompt_versions": {"room": ai.ROOM_PROMPT_VERSION, "preferences": ai.PREF_PROMPT_VERSION}}

    @app.get("/api/catalog")
    def get_catalog():
        return {"products": [{**p, "stale": is_stale(p)} for p in catalog]}

    @app.get("/api/projects")
    def list_projects(sid: str = Depends(session)):
        return db.all("SELECT p.*, ar.apartment_id, ar.label AS apartment_room_label FROM projects p "
                      "LEFT JOIN apartment_rooms ar ON ar.project_id = p.id WHERE p.session_id=? ORDER BY p.created_at DESC", (sid,))

    @app.post("/api/projects")
    def create_project(body: CreateProject, sid: str = Depends(session)):
        pid = db.create_project(sid, body.name, body.room_type, body.mode, False)
        db.add_preference_version(pid, default_preferences(body.room_type).model_dump(), "Starting defaults", "manual")
        project = db.project_for(pid, sid)
        replan(project, "Starting plans")
        return state(project)

    # ------------------------------------------------------------ apartments
    @app.get("/api/apartments")
    def list_apartments(sid: str = Depends(session)):
        out = []
        for a in db.all("SELECT * FROM apartments WHERE session_id=? ORDER BY created_at DESC", (sid,)):
            out.append({**a, "label": label_for(a["bedrooms"], a["bathrooms"]),
                        "rooms": len(db.apartment_rooms(a["id"]))})
        return out

    @app.post("/api/apartments")
    def create_apartment(body: CreateApartment, sid: str = Depends(session)):
        rooms = rooms_for(body.name, body.bedrooms)
        aid = db.create_apartment(sid, body.name, body.preset, body.bedrooms, body.bathrooms, rooms)
        if body.context is not None:
            db.add_apartment_context(aid, body.context.model_dump())
        for r in db.apartment_rooms(aid):
            prefs = default_preferences(r["room_type"])
            if body.context is not None:
                prefs.condition = body.context.condition  # early shopping scope; refined per room later
                prefs.location = body.context.public_location()[:80] or prefs.location
            db.add_preference_version(r["project_id"], prefs.model_dump(), "Starting defaults", "manual")
            replan(db.project_for(r["project_id"], sid), "Starting plans")
        db.event("apartment_created", {"apartment_id": aid, "preset": body.preset, "bedrooms": body.bedrooms,
                                       "bathrooms": body.bathrooms}, None, sid)
        return apartment_state(owned_apartment(aid, sid))

    @app.get("/api/apartments/{apartment_id}")
    def get_apartment(apartment_id: str, sid: str = Depends(session)):
        return apartment_state(owned_apartment(apartment_id, sid))

    @app.put("/api/apartments/{apartment_id}/context")
    def put_apartment_context(apartment_id: str, body: ApartmentContext, sid: str = Depends(session)):
        """Shared place details (location, building, shopping scope). Appends a version; never room geometry."""
        a = owned_apartment(apartment_id, sid)
        db.add_apartment_context(apartment_id, body.model_dump())
        db.event("apartment_context_saved", {"apartment_id": apartment_id}, None, sid)  # values not logged
        return apartment_state(a)

    @app.delete("/api/apartments/{apartment_id}")
    def delete_apartment(apartment_id: str, sid: str = Depends(session)):
        owned_apartment(apartment_id, sid)
        removed = 0
        for pid in db.delete_apartment_links(apartment_id, sid):
            paths = db.delete_project(pid, sid)
            store.remove_paths(paths)
            removed += len(paths)
        return {"deleted": apartment_id, "files_removed": removed}

    @app.post("/api/demo")
    def create_demo(body: DemoRequest, sid: str = Depends(session)):
        rt = body.room_type
        pid = db.create_project(sid, f"Synthetic demo {rt}", rt, "demo", True)
        images = fixtures.bedroom_images() if rt == "bedroom" else fixtures.studio_images()
        ids = [add_image_source(pid, data, name, "photo", synthetic=True)["id"] for name, data in images]
        if rt == "studio":
            name, data = fixtures.studio_floorplan()
            ids.append(add_image_source(pid, data, name, "floorplan", synthetic=True)["id"])
        out = fixtures.bedroom_analysis() if rt == "bedroom" else fixtures.studio_analysis()
        room, suggestions = ai.room_from_analysis(out, rt, ids, "fixture", None, room_photo_count=len(images))
        save_room(pid, room, suggestions, ids, None, "Synthetic fixture analysis (not AI)")
        prefs = default_preferences(rt)
        prefs.budget_cents = 120000 if rt == "bedroom" else 150000
        prefs.styles = ["minimal", "warm_wood"]
        if rt == "bedroom":
            prefs.bed_size = "queen"
            prefs.priorities = ["storage", "price"]
            prefs.existing_items = [e.model_copy(update={"keep": True}) for e in room.existing_items]
        db.add_preference_version(pid, prefs.model_dump(), "Demo preferences", "manual")
        replan(db.project_for(pid, sid), "Initial demo plans")
        db.event("demo_created", {"room_type": rt}, pid, sid)
        return state(db.project_for(pid, sid))

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str, sid: str = Depends(session)):
        return state(owned(project_id, sid))

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str, sid: str = Depends(session)):
        owned(project_id, sid)
        paths = db.delete_project(project_id, sid)
        store.remove_paths(paths)
        return {"deleted": project_id, "files_removed": len(paths)}

    @app.post("/api/projects/{project_id}/uploads")
    async def upload(project_id: str, files: list[UploadFile] = File(...), kind: str = Form("photo"),
                     sid: str = Depends(session)):
        project = owned(project_id, sid)
        if kind not in ("photo", "floorplan"):
            raise HTTPException(400, "kind must be photo or floorplan")
        limit = settings.max_photos if kind == "photo" else MAX_FLOORPLANS
        results = []
        if len(files) > 12:
            raise HTTPException(400, "Too many files in one upload (max 12).")
        for f in files:
            name = (f.filename or "upload")[:120]
            used = (db.one("SELECT COUNT(*) n FROM source_assets WHERE project_id=? AND kind='photo'", (project_id,))["n"]
                    if kind == "photo" else floorplan_count(project_id))
            if used >= limit:
                results.append({"filename": name, "ok": False,
                                "error": f"At most {limit} {'photos' if kind == 'photo' else 'floor plans (images or PDFs)'} per project."})
                continue
            data = await f.read(settings.max_upload_bytes + 1)
            try:
                if kind == "floorplan" and data.startswith(b"%PDF-"):
                    validate_pdf(data, settings.max_upload_bytes)
                    sha, path = store.save_original(project_id, data, "application/pdf")
                    sid_ = new_id("src")
                    db.exec("INSERT INTO source_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sid_, project_id, "floorplan_pdf", sha, "application/pdf", name, len(data), str(path),
                             None, None, None, None, 0, now()))
                    results.append({"filename": name, "ok": True, "id": sid_,
                                    "warning": "PDF stored. Automatic PDF plan reading is not implemented; enter the plan's printed dimensions to confirm scale."})
                else:
                    r = add_image_source(project_id, data, name, kind)
                    results.append({"filename": name, "ok": True, **r})
            except UploadRejected as exc:
                results.append({"filename": name, "ok": False, "error": str(exc)})
        n_photos = db.one("SELECT COUNT(*) n FROM source_assets WHERE project_id=? AND kind='photo'", (project_id,))["n"]
        notice = None
        if kind == "floorplan":
            notice = "Floor plan saved. Next: “Analyze floor plan” reads its printed room sizes. Photos are optional."
        elif n_photos < 2:
            notice = ("Tip: 2 or more overlapping photos (opposite corners, floor/wall edges, the door) may give an estimated "
                      "outline. Photos are optional if you have a floor plan.")
        db.event("upload", {"results": [{k: v for k, v in r.items() if k != "id"} for r in results]}, project_id, sid)
        return {"results": results, "notice": notice, "state": state(project)}

    @app.get("/api/projects/{project_id}/sources/{source_id}/preview")
    def preview(project_id: str, source_id: str, sid: str = Depends(session)):
        owned(project_id, sid)
        d = db.one("SELECT storage_path FROM derivatives WHERE parent_source_id=? AND project_id=?", (source_id, project_id))
        if not d:
            raise HTTPException(404, "No preview")
        return FileResponse(d["storage_path"], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})

    @app.post("/api/projects/{project_id}/analyze")
    async def analyze(project_id: str, body: AnalyzeRequest, sid: str = Depends(session)):
        project = owned(project_id, sid)
        rt = project["room_type"]
        photos = db.all("SELECT id FROM source_assets WHERE project_id=? AND kind='photo' ORDER BY created_at", (project_id,))
        plans_ = db.all("SELECT id FROM source_assets WHERE project_id=? AND kind='floorplan' ORDER BY created_at", (project_id,))
        if not photos and not plans_:
            raise HTTPException(400, "Upload at least one photo first.")
        if body.floorplan_source_id:
            plans_ = [p for p in plans_ if p["id"] == body.floorplan_source_id]
            if not plans_:
                raise HTTPException(422, "That floor plan isn’t an image plan of this room.")
        elif len(plans_) > 1:
            raise HTTPException(422, f"This room has {len(plans_)} floor plans. Choose which one to read; plans are never combined.")
        photo_ids = [p["id"] for p in photos] + [p["id"] for p in plans_]
        if project["mode"] == "demo":
            raise HTTPException(400, "Demo projects use synthetic fixture analysis; create a live project to run AI analysis.")
        derivs = [derivative_bytes(i) for i in photo_ids]
        # Source identities are part of the key: identical bytes under another source must not reuse its citations.
        input_hash = hashlib.sha256(json.dumps({"src": photo_ids, "d": [h for h, _ in derivs], "rt": rt, "model": MODEL,
                                                "prompt": ai.ROOM_PROMPT_VERSION, "note": body.note}).encode()).hexdigest()
        prev = db.one("SELECT * FROM room_versions WHERE project_id=? AND input_hash=? AND method IN ('live_ai','mocked_ai') "
                      "ORDER BY version DESC LIMIT 1", (project_id, input_hash))
        if prev:
            head_row = db.head("room_versions", project_id)
            if head_row and head_row["data"].get("analysis_hash") == input_hash:
                # The current room already derives from this analysis (e.g. plus a chosen estimate): nothing to do.
                db.event("analysis_reused", {"room_version": prev["version"], "current": True}, project_id, sid)
                return {"reused": True, "state": state(project)}
            # Another analysis is current (e.g. a different plan): restore this cached one as a NEW derived version.
            # Only its own evidence and readings: no chosen estimate, and a known size only if its provenance holds.
            prev_data = json.loads(prev["data"]) if isinstance(prev["data"], str) else prev["data"]
            base = RoomModel.model_validate(prev_data["room"])
            base = base.model_copy(update={"plan_estimate": None, "scale_status": "unknown", "width": None, "depth": None,
                                           "claims": [c for c in base.claims if c.kind != "verified_constraint"]})
            room = RoomModel.model_validate(carry_known_size(head_room(project_id), base, photo_ids).model_dump())
            call = {"method": "reused", "new_ai_call": False, "reused_from_room_version": prev["version"],
                    "reused_from_id": prev["id"]}
            row = save_room(project_id, room, prev_data.get("plan_dimension_suggestions") or [], photo_ids, None,
                            f"Reused saved analysis v{prev['version']} of {len(photo_ids)} image(s) (no new AI call)", call,
                            analysis_hash=input_hash)
            db.event("analysis_reused", {"room_version": prev["version"], "restored_as": row["version"]}, project_id, sid)
            replan(project, f"Plans after reusing room analysis v{prev['version']}")
            return {"reused": True, "state": state(project)}
        model, is_mock = model_for_live()
        n_photos = len(photos)
        prompt = ai.room_prompt(rt, [(photo_ids[i], derivs[i][1]) for i in range(n_photos)],
                                [(photo_ids[i], derivs[i][1]) for i in range(n_photos, len(photo_ids))], body.note)
        try:
            out, rec = await ai.run_agent(ai.room_agent, prompt, model=model, is_mock=is_mock, settings=settings,
                                          ledger=ledger, session_id=sid, project_id=project_id, purpose="room_analysis",
                                          text_chars=len(ai.ROOM_INSTRUCTIONS) + len(body.note), images=len(derivs))
        except ai.AIError as exc:
            db.event("analysis_failed", {"error": exc.public}, project_id, sid)
            raise HTTPException(502, exc.public)
        room, suggestions = ai.room_from_analysis(out, rt, photo_ids, rec.method, MODEL, room_photo_count=n_photos)
        old = head_room(project_id)
        room = carry_known_size(old, room, photo_ids)  # a stated size carries; another plan's confirmed size doesn't
        if old and old.plan_estimate is not None and old.plan_estimate.source_id in photo_ids:
            # Keep the chosen estimate only if the SAME plan was re-read and the SAME reading is still there
            # (re-pointed to its new position); otherwise it is dropped, never redrawn under another plan.
            pe = old.plan_estimate
            j = next((k for k, sg in enumerate(suggestions) if sg.get("dimension_text") == pe.dimension_text
                      and (sg.get("room_label") or "") == pe.room_label and pe.source_id in (sg.get("source_ids") or [])), None)
            if j is not None:
                room = room.model_copy(update={"plan_estimate": pe.model_copy(update={"suggestion_index": j})})
        call = {"method": rec.method, "latency_s": round(rec.latency_s, 2), "requests": rec.requests, **rec.usage,
                "estimated_cost_usd": rec.estimated_cost_usd, "response_ids": rec.response_ids,
                # Output-shape repairs the app made (e.g. top-level scale moved into geometry); [] if none.
                "schema_repairs": list(out.schema_repairs)}
        row = save_room(project_id, room, suggestions, photo_ids, input_hash,
                        f"{'Live gpt-6-luna' if rec.method == 'live_ai' else 'Mocked AI'} analysis of {len(photo_ids)} image(s)", call,
                        analysis_hash=input_hash)
        db.event("analysis_done", {"room_version": row["version"], **call}, project_id, sid)
        replan(project, f"Plans after room analysis v{row['version']}")
        return {"reused": False, "state": state(project)}

    @app.post("/api/projects/{project_id}/plan-estimate")
    def plan_estimate(project_id: str, body: PlanEstimateRequest, sid: str = Depends(session)):
        """Estimated room size from a printed plan reading the user picked. Validated against the CURRENT room version,
        the reading's own floor-plan source in THIS room, and a plausible printed pair. Appends a room version; scale
        stays unknown (fit is never upgraded); originals and older versions are untouched."""
        project = owned(project_id, sid)
        head = db.head("room_versions", project_id)
        if head is None or head["id"] != body.room_version_id:
            raise HTTPException(409, "Your room was re-analyzed since these readings were shown. Nothing was changed; "
                                     "choose a reading from the current list.")
        sugg = head["data"].get("plan_dimension_suggestions") or []
        if body.suggestion_index >= len(sugg):
            raise HTTPException(422, "That plan reading isn’t in the current list.")
        s = sugg[body.suggestion_index]
        if body.source_id not in (s.get("source_ids") or []):
            raise HTTPException(422, "That reading didn’t come from that floor plan.")
        src = db.one("SELECT id, original_filename, source_url FROM source_assets WHERE id=? AND project_id=? AND kind='floorplan'",
                     (body.source_id, project_id))
        if src is None:
            raise HTTPException(422, "That floor plan isn’t one of this room’s sources.")
        w, d = s.get("width_in"), s.get("depth_in")
        if not (isinstance(w, (int, float)) and isinstance(d, (int, float)) and 48 <= w <= 480 and 48 <= d <= 480):
            raise HTTPException(422, f"“{s.get('dimension_text')}” doesn’t read as a plausible room size, so it isn’t used.")
        room = RoomModel.model_validate(head["data"]["room"])
        geo = room.inferred_geometry
        # Only a shape OBSERVED in this room's photos counts: an apartment plan's overall shape is not this room's.
        if geo is not None and geo.walls_seen and geo.shape in ("l_shaped", "irregular"):
            raise HTTPException(422, "Your room photos show an irregular room, so a rectangle from one printed size would "
                                     "misrepresent it. The plan stays a reference.")
        tol = 6.0
        how = f"Estimated from floor-plan reading “{s.get('dimension_text')}” (unverified, ±{tol:g} in)"

        def bound(v: float) -> Bound:
            return Bound(lower=max(v - tol, 1), central=v, upper=v + tol, method=how, source_ids=[body.source_id], strength="weak")

        prov = db.one("SELECT data FROM source_provenance WHERE source_id=?", (body.source_id,))
        plan_name = (json.loads(prov["data"]).get("reference_plan_name") if prov else None) or src["original_filename"] or src["source_url"] or ""
        est = PlanEstimate(width=bound(w), depth=bound(d), source_id=body.source_id, source_label=str(plan_name)[:120],
                           room_version_id=head["id"], suggestion_index=body.suggestion_index,
                           dimension_text=str(s.get("dimension_text"))[:60], room_label=str(s.get("room_label") or "")[:80],
                           plan_label=str(s.get("plan_label") or "")[:80], tolerance_in=tol)
        claims = list(room.claims) + [EvidenceClaim(
            kind="hypothesis", subject="room size estimate",
            statement=f"{how} for {s.get('room_label') or 'this room'}; your unit may differ.",
            source_ids=[body.source_id], strength="weak")]
        room = RoomModel.model_validate(room.model_copy(update={"plan_estimate": est, "claims": claims}).model_dump())
        save_room(project_id, room, sugg, json.loads(head["source_ids"]), None,
                  f"Estimated size from plan reading {s.get('dimension_text')} ({s.get('room_label') or 'room'})",
                  analysis_hash=head["data"].get("analysis_hash"))
        replan(project, "Plans after choosing a plan reading (estimate)")
        return state(project)

    @app.post("/api/projects/{project_id}/scale")
    def set_scale(project_id: str, body: ScaleRequest, sid: str = Depends(session)):
        project = owned(project_id, sid)
        plan_ids = {r["id"] for r in db.all(
            "SELECT id FROM source_assets WHERE project_id=? AND kind IN ('floorplan','floorplan_pdf')", (project_id,))}
        src = [s for s in body.source_ids if s in plan_ids]
        if body.basis == "plan_confirmed" and (not src or len(src) != len(body.source_ids)):
            raise HTTPException(400, "Plan-confirmed size must cite a floor plan you added to this project "
                                     "(photos and web pages are not floor plans).")
        if body.basis == "plan_confirmed" and not body.exact_unit_confirmed:
            raise HTTPException(400, "A plan's room size can be used only if you confirm it is your unit's exact plan. "
                                     "A similar layout stays a reference and can't set your room's size.")
        if body.basis == "user_stated":
            src = []
        old = head_room(project_id) or RoomModel(room_type=project["room_type"], method="manual")
        method = ("Floor-plan dimensions confirmed by user" if body.basis == "plan_confirmed" else "Dimensions stated by user")
        strength = "moderate"
        t = body.tolerance_in

        def bound(v: float) -> Bound:
            return Bound(lower=max(v - t, 1), central=v, upper=v + t, method=f"{method} ±{t:g} in (heuristic)",
                         source_ids=src, strength=strength)

        claims = list(old.claims) + [EvidenceClaim(
            kind="verified_constraint", subject="room scale",
            statement=f"{method}: {body.width_in:g} x {body.depth_in:g} in (±{t:g} in). {body.label}".strip(),
            source_ids=src, strength=strength)]
        room = old.model_copy(update={
            "scale_status": "plan_dimensions_user_confirmed" if body.basis == "plan_confirmed" else "user_stated",
            "width": bound(body.width_in), "depth": bound(body.depth_in), "claims": claims, "shape": "rectangular"
            if old.shape == "unknown" else old.shape})
        room = RoomModel.model_validate(room.model_dump())
        prev = db.head("room_versions", project_id)
        save_room(project_id, room, (prev or {}).get("data", {}).get("plan_dimension_suggestions", []),
                  json.loads(prev["source_ids"]) if prev else src, None, f"Scale set: {method}",
                  analysis_hash=(prev or {}).get("data", {}).get("analysis_hash"))
        replan(project, "Plans after scale update")
        return state(project)

    @app.put("/api/projects/{project_id}/preferences")
    def put_prefs(project_id: str, body: Preferences, sid: str = Depends(session)):
        project = owned(project_id, sid)
        db.add_preference_version(project_id, body.model_dump(), "Edited with controls", "manual")
        replan(project, "Plans after preference controls")
        return state(project)

    @app.post("/api/projects/{project_id}/edit")
    async def edit(project_id: str, body: EditRequest, sid: str = Depends(session)):
        project = owned(project_id, sid)
        prefs = head_prefs(project)
        current = head_plans(project_id)
        if project["mode"] == "demo":
            patch, method, call = rule_based_patch(body.message), "rule_based", None
        else:
            model, is_mock = model_for_live()
            summary = [f"{pl.key}: " + "; ".join(f"{i.category}={i.name}" for i in pl.items) for pl in (current.plans if current else [])]
            try:
                patch, rec = await ai.run_agent(ai.pref_agent, ai.pref_prompt(prefs, summary, body.message), model=model,
                                                is_mock=is_mock, settings=settings, ledger=ledger, session_id=sid,
                                                project_id=project_id, purpose="preference_edit",
                                                text_chars=len(body.message) + 6000, images=0)
            except ai.AIError as exc:
                db.event("edit_failed", {"error": exc.public}, project_id, sid)
                raise HTTPException(502, exc.public)
            method = rec.method
            call = {"method": rec.method, "prompt_version": ai.PREF_PROMPT_VERSION, **rec.usage,
                    "estimated_cost_usd": rec.estimated_cost_usd, "response_ids": rec.response_ids,
                    "latency_s": round(rec.latency_s, 2)}
        new_prefs, changes = apply_patch(prefs, patch, current)
        db.add_preference_version(project_id, new_prefs.model_dump(), ("; ".join(changes) or "No change")[:300], method)
        row = replan(project, f"Edit: {body.message[:80]}")
        db.event("edit", {"message": body.message[:200], "method": method, "changes": changes, "call": call}, project_id, sid)
        return {"method": method, "patch": patch.model_dump(), "changes": changes,
                "plan_changes": row["data"].get("changes", []), "state": state(project)}

    @app.post("/api/projects/{project_id}/plans")
    def regenerate(project_id: str, sid: str = Depends(session)):
        project = owned(project_id, sid)
        replan(project, "Regenerated")
        return state(project)

    # ------------------------------------------------------------ compare & swap one piece of furniture
    def head_bundle(project_id: str):
        head = db.head("plan_versions", project_id)
        if not head:
            raise HTTPException(409, "No plans yet; build plans first.")
        ps = PlanSet.model_validate(head["data"])
        prefs_row = db.version_by_id("preference_versions", project_id, head["preference_version_id"])
        prefs = Preferences.model_validate(prefs_row["data"])
        room_row = db.version_by_id("room_versions", project_id, head["room_version_id"]) if head["room_version_id"] else None
        room = RoomModel.model_validate(room_row["data"]["room"]) if room_row else None
        return head, ps, prefs, room

    @app.get("/api/projects/{project_id}/alternatives")
    def alternatives(project_id: str, plan_key: str, category: str, sid: str = Depends(session)):
        owned(project_id, sid)
        head, ps, prefs, room = head_bundle(project_id)
        plan = next((p for p in ps.plans if p.key == plan_key), None)
        if plan is None:
            raise HTTPException(404, "Plan not found.")
        return {"plan_key": plan_key, "category": category, "plan_version": head["version"],
                "subtotal_cents": plan.subtotal_cents, "item_budget_cents": plan.item_budget_cents,
                "alternatives": alternatives_for(plan, category, prefs, full_catalog(project_id), room),
                "note": "Products come from dated catalog snapshots and listings you imported; prices and stock may have changed."}

    @app.post("/api/projects/{project_id}/swap")
    def swap(project_id: str, body: SwapRequest, sid: str = Depends(session)):
        """Replace ONE category in ONE plan. All checks run before anything is written; a refusal changes nothing.
        The new plan version keeps the same room and preference versions, so the room frame is identical."""
        project = owned(project_id, sid)
        head, ps, prefs, room = head_bundle(project_id)
        if body.expected_plan_version is not None and body.expected_plan_version != head["version"]:
            raise HTTPException(409, "Your plans changed since you opened these options (for example in another tab). "
                                     "Nothing was swapped; reopen the options to see the current plan.")
        idx = next((n for n, p in enumerate(ps.plans) if p.key == body.plan_key), None)
        if idx is None:
            raise HTTPException(404, "Plan not found.")
        cat = full_catalog(project_id)
        by_id = {p["id"]: p for p in cat}
        cand = by_id.get(body.product_id)
        if cand is None:
            raise HTTPException(404, "Product not found in the catalog or your imported listings.")
        old_plan = ps.plans[idx]
        try:
            new_plan = swap_plan(old_plan, body.category, cand, prefs, by_id, room, project["room_type"])
        except SwapRejected as exc:
            db.event("swap_rejected", {"plan": body.plan_key, "category": body.category, "product": body.product_id,
                                       "reason": exc.reason}, project_id, sid)
            raise HTTPException(422, exc.reason)
        fp_ids = [r["id"] for r in db.all("SELECT id FROM source_assets WHERE project_id=? AND kind IN "
                                          "('floorplan','floorplan_pdf') ORDER BY created_at", (project_id,))]
        new_plan.layouts = generate_layouts(new_plan, by_id, prefs, room_frame(room, head["room_version_id"], fp_ids))
        old_item = next(i for i in old_plan.items if i.product_id and i.category == body.category)
        ps.plans[idx] = new_plan
        ps.changes = [f"{body.plan_key}: {body.category.replace('_', ' ')} changed from {old_item.name} to {cand['name']}; "
                      f"subtotal {old_plan.subtotal_cents / 100:,.2f} → {new_plan.subtotal_cents / 100:,.2f}. Other items unchanged."]
        used = sorted({i.product_id for pl in ps.plans for i in pl.items if i.product_id})
        refs = [{"product_id": u, "snapshot_hash": snap_hash(by_id[u]), "checked_at": by_id[u].get("checked_at"),
                 "source_sha256": by_id[u].get("source_sha256")} for u in used]
        row = db.add_plan_version(project_id, ps.model_dump(), head["room_version_id"], head["preference_version_id"], refs,
                                  f"Swapped {body.category.replace('_', ' ')} in {body.plan_key} plan")
        db.event("swap", {"plan": body.plan_key, "category": body.category, "from": old_item.product_id, "to": cand["id"],
                          "plan_version": row["version"]}, project_id, sid)
        return state(project)

    # ------------------------------------------------------------ shopping checklist (manual; no checkout)
    def current_plan_or_409(project_id: str, plan_key: str, expected_version: int) -> tuple[dict, Plan]:
        head = db.head("plan_versions", project_id)
        if head is None:
            raise HTTPException(409, "There are no plans yet.")
        if expected_version != head["version"]:
            raise HTTPException(409, "Your plans changed since this list was shown. Nothing was saved; the list has been "
                                     "refreshed, please try again.")
        plan = next((p for p in PlanSet.model_validate(head["data"]).plans if p.key == plan_key), None)
        if plan is None:
            raise HTTPException(422, "That shopping plan isn’t in your current plans.")
        return head, plan

    def selected_plan_key(project_id: str, plans: list[Plan]) -> str | None:
        """The saved selection if it is still a current plan; else Balanced (the plans view's default), else the first."""
        keys = [p.key for p in plans]
        sel = db.plan_selection(project_id)
        if sel and sel["plan_key"] in keys:
            return sel["plan_key"]
        return "balanced" if "balanced" in keys else (keys[0] if keys else None)

    def checklist(project_id: str) -> dict:
        """The shopping list for the SELECTED plan of the current plan version. Purchase marks are keyed by product
        id, so a swapped-in product never inherits the old one's mark. Totals cover only the current list."""
        head = db.head("plan_versions", project_id)
        plans = PlanSet.model_validate(head["data"]).plans if head else []
        key = selected_plan_key(project_id, plans)
        plan = next((p for p in plans if p.key == key), None)
        marks = db.purchase_status(project_id)
        items, current_ids = [], set()
        for it in (plan.items if plan else []):
            row = {"category": it.category, "name": it.name, "retailer": it.retailer, "url": it.url,
                   "image_url": it.image_url, "price_cents": it.price_cents, "width_in": it.width_in, "depth_in": it.depth_in,
                   "condition": it.condition, "fit_label": it.fit_label, "fit_checks": it.fit_checks,
                   "checked_at": it.checked_at, "stale": it.stale,
                   "availability": it.availability}
            if it.existing_item_id or not it.product_id:
                items.append({**row, "product_id": None, "owned": True, "purchased": None, "marked_at": None})
                continue
            current_ids.add(it.product_id)
            m = marks.get(it.product_id)
            items.append({**row, "product_id": it.product_id, "owned": False,
                          "purchased": bool(m and m["purchased"]), "marked_at": m["created_at"] if m else None})
        buy = [i for i in items if not i["owned"]]
        done = [i for i in buy if i["purchased"]]

        def total(rows):
            return sum(i["price_cents"] for i in rows if i["price_cents"] is not None)
        retired = [m["product_id"] for pid, m in marks.items() if m["purchased"] and pid not in current_ids]
        return {"plan_version": head["version"] if head else None, "plan_key": key, "plan_title": plan.title if plan else None,
                "available_plans": [{"key": p.key, "title": p.title} for p in plans], "items": items,
                "counts": {"to_buy": len(buy), "purchased": len(done), "remaining": len(buy) - len(done),
                           "owned": len(items) - len(buy), "price_unknown": sum(1 for i in buy if i["price_cents"] is None)},
                "subtotal_cents": total(buy), "purchased_cents": total(done), "remaining_cents": total(buy) - total(done),
                "retired_purchased": len(retired),
                "notes": ["Item prices only, from dated pages; tax, delivery and assembly are not included and unknown.",
                          "“Mark purchased” is your own note. Opening a store link never marks anything, and nothing is "
                          "bought, paid or ordered by this app."]}

    @app.get("/api/projects/{project_id}/checklist")
    def get_checklist(project_id: str, sid: str = Depends(session)):
        owned(project_id, sid)
        return checklist(project_id)

    @app.put("/api/projects/{project_id}/checklist/plan")
    def select_plan(project_id: str, body: PlanSelectRequest, sid: str = Depends(session)):
        """Remember which shopping plan the user is following (append-only)."""
        owned(project_id, sid)
        head, _ = current_plan_or_409(project_id, body.plan_key, body.expected_plan_version)
        db.add_plan_selection(project_id, body.plan_key, head["version"])
        return checklist(project_id)

    @app.post("/api/projects/{project_id}/checklist/mark")
    def mark_purchased(project_id: str, body: PurchaseMarkRequest, sid: str = Depends(session)):
        """Manual "Mark purchased" / undo for a product that is in the selected current plan. Refused (nothing
        written) for a stale plan version, a product not in that plan, or furniture the user already owns."""
        owned(project_id, sid)
        head, plan = current_plan_or_409(project_id, body.plan_key, body.expected_plan_version)
        current_key = selected_plan_key(project_id, PlanSet.model_validate(head["data"]).plans)
        if body.plan_key != current_key:  # e.g. another tab switched the list to a different plan
            raise HTTPException(409, "Your shopping list now follows a different plan (changed in another tab or window). "
                                     "Nothing was saved; the list has been refreshed.")
        item = next((i for i in plan.items if i.product_id == body.product_id and not i.existing_item_id), None)
        if item is None:
            raise HTTPException(422, "That product isn’t in this shopping plan (it may have been swapped). Nothing was saved.")
        db.add_purchase_mark(project_id, body.product_id, item.category, body.purchased, plan.key, head["version"])
        db.event("purchase_marked", {"product_id": body.product_id, "purchased": body.purchased, "plan_key": plan.key,
                                     "plan_version": head["version"]}, project_id, sid)
        return checklist(project_id)

    # ------------------------------------------------------------ web research (discovery only)
    def place_context(project_id: str, body_city: str = "", body_state: str = "", body_zip: str = "") -> ApartmentContext:
        apt = db.apartment_of_project(project_id)
        ctx = db.apartment_context(apt["id"]) if apt else None
        base = ApartmentContext.model_validate(ctx["data"]) if ctx else ApartmentContext()
        upd = {k: v for k, v in (("city", body_city), ("state", body_state), ("zip", body_zip)) if v.strip()}
        return base.model_copy(update=upd) if upd else base

    research_flights: dict[tuple, asyncio.Task] = {}  # in-flight identical searches (session + place + kind + query)

    async def cached_research(project_id: str, sid: str, kind: str, query: str) -> dict:
        """The saved result of the same search in this session and place (within the cache TTL), else ONE live search.
        Concurrent identical requests share ONE in-flight search task: they all get its result or its error, so they
        never pay twice within that flight. A waiter that disconnects doesn't cancel it for the others (shielded). The
        entry is removed when the search is done; a failure is never cached, so a later attempt may search again."""
        qk = query_key(kind, query)
        scope_sql, scope_val = research_scope(project_id)

        def saved():
            since = datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_S)
            return db.one(f"SELECT data FROM research_results WHERE session_id=? AND {scope_sql} AND kind=? AND query_key=? "
                          "AND status='ok' AND created_at>=? ORDER BY created_at DESC LIMIT 1",
                          (sid, scope_val, kind, qk, since.isoformat(timespec="seconds")))
        hit = saved()
        if hit:
            return {**json.loads(hit["data"]), "cached": True}

        async def search() -> dict:
            again = saved()  # finished just before this flight started
            if again:
                return {**json.loads(again["data"]), "cached": True}
            try:
                data = await web_research(settings, ledger, sid, project_id, kind, query, transport=ai_transport)
            except ai.AIError as exc:
                db.event("research_failed", {"kind": kind, "error": exc.public}, project_id, sid)
                raise HTTPException(502 if "failed" in exc.public else 503, exc.public)
            apt = db.apartment_of_project(project_id)
            db.exec("INSERT INTO research_results VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_id("res"), sid, apt["id"] if apt else None, project_id, kind, qk, "ok", json.dumps(data), now()))
            db.event("research", {"kind": kind, "query": query, "results": len(data["results"]), "rejected": data["rejected_urls"],
                                  "web_search_calls": data["web_search_calls"], "cost": data["cost"]}, project_id, sid)
            return {**data, "cached": False}

        key = (sid, scope_sql, scope_val, kind, qk)
        loop = asyncio.get_running_loop()
        task = research_flights.get(key)
        if task is None or task.done() or task.get_loop() is not loop:
            task = loop.create_task(search())
            research_flights[key] = task

            def done(t: asyncio.Task, key=key) -> None:
                if research_flights.get(key) is t:
                    research_flights.pop(key, None)
                if not t.cancelled():
                    t.exception()  # retrieved here, so an error nobody awaits any more is never left unobserved
            task.add_done_callback(done)
        return await asyncio.shield(task)

    @app.post("/api/projects/{project_id}/research/property")
    async def research_property(project_id: str, body: PropertyResearchRequest, sid: str = Depends(session)):
        owned(project_id, sid)
        ctx = place_context(project_id, body.city, body.state, body.zip)
        name = (body.property_name or ctx.property_name).strip()
        location = ctx.public_location()
        if not name or not location:
            raise HTTPException(400, "Add the building or apartment name and a city/state or ZIP to search.")
        data = await cached_research(project_id, sid, "property", property_query(name, location))
        data["note"] = ("Search results are leads, not verified facts. Choose the official page to look for plans; "
                        "it may not match your exact unit. Your unit number is never searched.")
        return data

    # ------------------------------------------------------------ find and choose a building
    def research_scope(project_id: str) -> tuple[str, str]:
        """Research is shared by the rooms of one apartment (same query = same public result); a single room keeps its own."""
        apt_ = db.apartment_of_project(project_id)
        return ("apartment_id=?", apt_["id"]) if apt_ else ("project_id=? AND apartment_id IS NULL", project_id)

    def query_evidence(project_id: str, sid: str, name: str, location: str) -> list[dict] | None:
        """Evidence-backed results of the saved search for THIS building name + location only (the latest saved row
        for that exact query in this place). Earlier searches for other buildings are never mixed in. None = this
        query was never searched here. Saved rows are read, never changed."""
        if not name or not location:
            return None
        scope_sql, scope_val = research_scope(project_id)
        row = db.one(f"SELECT data FROM research_results WHERE session_id=? AND {scope_sql} AND kind='property' AND status='ok' "
                     "AND query_key=? ORDER BY created_at DESC LIMIT 1",
                     (sid, scope_val, query_key("property", property_query(name, location))))
        return json.loads(row["data"]).get("results", []) if row else None

    def saved_lead_checks(project_id: str, sid: str, qk: str) -> dict[str, dict]:
        """Our own earlier reads of hostname-only search leads for THIS query in this place (latest per card)."""
        scope_sql, scope_val = research_scope(project_id)
        rows = db.all(f"SELECT data FROM research_results WHERE session_id=? AND {scope_sql} AND kind='lead_check' "
                      "AND query_key LIKE ? ORDER BY created_at", (sid, scope_val, qk + "|%"))
        out: dict[str, dict] = {}
        for r in rows:
            d = json.loads(r["data"])
            out[d["card_key"]] = d
        return out

    async def check_leads(project_id: str, sid: str, qk: str, cards: list[dict], name: str, city: str, st: str,
                          zip_: str) -> dict[str, dict]:
        """Read at most two leading hostname-only leads whose domain spells the building's name (direct read, then the
        public page reader), once per query: results are saved append-only and reused. Raw pages are kept
        content-addressed. Nothing is selected."""
        checks = saved_lead_checks(project_id, sid, qk)
        apt_ = db.apartment_of_project(project_id)
        for card in leads_to_check(cards, name, set(checks)):
            chk, raw = await run_in_threadpool(check_lead_page, fetcher, reader, card, name, city, st, zip_)
            if raw is not None:
                chk["stored_sha256"], _ = store.save_original(
                    project_id, raw.body, "text/plain" if chk.get("read_via") == "public_reader" else "text/html")
            db.exec("INSERT INTO research_results VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_id("res"), sid, apt_["id"] if apt_ else None, project_id, "lead_check", f"{qk}|{card['key']}",
                     "ok", json.dumps(chk), now()))
            db.event("building_lead_checked", {k: chk.get(k) for k in ("url", "ok", "problem", "read_via")}, project_id, sid)
            checks[card["key"]] = chk
        return checks

    def saved_gallery_item(discovery_id: str, project_id: str, sid: str, url: str) -> tuple[dict | None, dict | None]:
        """The gallery entry for `url` in a saved discovery of THIS place (same session, same apartment or room)."""
        row = db.place_discovery_by_id(discovery_id)
        if not row or row["session_id"] != sid:
            return None, None
        apt_ = db.apartment_of_project(project_id)
        in_scope = row["apartment_id"] == apt_["id"] if apt_ else (row["apartment_id"] is None and row["project_id"] == project_id)
        if not in_scope:
            return None, None
        return next((g for g in row["data"].get("gallery", []) if g["url"] == url), None), row

    def search_fields(project_id: str, name: str, city: str, st: str, zip_: str) -> tuple[str, str, str, str]:
        ctx = place_context(project_id)
        if not (city.strip() or st.strip() or zip_.strip()):
            city, st, zip_ = ctx.city, ctx.state, ctx.zip
        return (name.strip() or ctx.property_name).strip(), city.strip(), st.strip(), zip_.strip()

    @app.post("/api/projects/{project_id}/buildings/find")
    async def find_buildings(project_id: str, body: BuildingFindRequest, sid: str = Depends(session)):
        """Candidate buildings for a name + city/state or ZIP. Checked directories match instantly (no cost); the
        live web search (one bounded, cached call) runs only when asked. The private unit label is never used."""
        owned(project_id, sid)
        name, city, st, zip_ = search_fields(project_id, body.property_name, body.city, body.state, body.zip)
        if not name or not (city or zip_):
            raise HTTPException(400, "Add the building name and a city (with state) or a ZIP code.")
        checked = match_directories(name, city, st, zip_)
        out: dict[str, Any] = {
            "query": {"property_name": name, "city": city, "state": st, "zip": zip_}, "checked": checked, "web": [],
            "web_available": settings.live_available, "research": None, "web_note": None,
            "note": "Pick your building. Nothing is chosen for you, and same-name buildings elsewhere are not assumed to be yours."}
        if body.include_web:
            if not settings.live_available:
                out["web_note"] = "Web search needs the AI connection, which isn’t available right now."
            else:
                location = " ".join(x for x in (city, st, zip_) if x)
                data = await cached_research(project_id, sid, "property", property_query(name, location))
                qk = query_key("property", property_query(name, location))
                cards, seen = building_candidates(data["results"], name, city, st, zip_, checked,
                                                  saved_lead_checks(project_id, sid, qk))
                # Hostname-only leads on a site named for the building: read the page itself (bounded, once).
                checks = await check_leads(project_id, sid, qk, cards, name, city, st, zip_)
                cards, seen = building_candidates(data["results"], name, city, st, zip_, checked, checks)
                for c in checked:
                    c["also_in_search"] = c["key"] in seen
                # Results that name a building can be chosen; listing/directory pages, bare site names and results
                # that don't name it are "Other sources" to inspect only.
                out["web"] = [c for c in cards if c["identity"] == "building"]
                out["sources"] = [c for c in cards if c["identity"] == "source"]
                out["research"] = {k: data.get(k) for k in ("searched_at", "cached", "web_search_calls", "rejected_urls", "query")}
                if not out["web"]:
                    if checked:  # the checked match above IS the building; don't imply nothing was found
                        out["web_note"] = ("Your checked match is shown above. Web search found no additional building matches"
                                           + ("; other sources are listed below." if out["sources"] else "."))
                    else:
                        out["web_note"] = ("Web search found no result that clearly names this building"
                                           + (" (only other sources, listed below)." if out["sources"] else "."))
        out.setdefault("sources", [])
        return out

    @app.post("/api/projects/{project_id}/buildings/select")
    async def select_building(project_id: str, body: BuildingSelectRequest, sid: str = Depends(session)):
        """The user's explicit choice. Saves the building identity to the shared place details (append-only), looks
        for its public plans (bounded SafeFetcher crawl, then recovery scoped to this building from THIS search's
        evidence), and saves the result for every room of the place. Room sizes are never set here.
        Advanced website address with no saved search: if the page gives no usable plans, ONE bounded web search for
        the entered building name + city/ZIP (never the unit) supplies the alternatives. Checked buildings never wait
        on a paid search."""
        project = owned(project_id, sid)
        apt_ = db.apartment_of_project(project_id)
        name, city, st, zip_ = search_fields(project_id, body.property_name, body.city, body.state, body.zip)
        location = " ".join(x for x in (city, st, zip_) if x)
        evidence = query_evidence(project_id, sid, name, location)
        directory = None
        url = body.url.strip()
        if body.kind == "checked":
            directory = reference_by_file(body.key.removeprefix("checked:"))
            if directory is None or all(c["directory"] != directory["_file"] for c in match_directories(name, city, st, zip_)):
                raise HTTPException(422, "That checked building doesn’t match the name and location you entered.")
            cand = checked_candidate(directory)
            start = directory["website"]
        elif body.kind == "web":
            item = next((r for r in evidence or [] if r["url"] == url), None)
            if item is None or not public_url_ok(url):
                raise HTTPException(422, "That website wasn’t in the saved search results for this building name and location. "
                                         "Search again, or enter the website address.")
            checks = saved_lead_checks(project_id, sid, query_key("property", property_query(name, location)))
            cards, _ = building_candidates(evidence or [], name, city, st, zip_, match_directories(name, city, st, zip_), checks)
            card = next((c for c in cards if c["identity"] == "building" and (url in c["urls"] or url == c["url"])), None)
            if card is None:
                raise HTTPException(422, "That result is a source (a listing site or a page that doesn’t name the building), "
                                         "not an identified building. Open it to check, or use the website address option.")
            cand = {"key": body.key or "web:" + hashlib.sha256(url.encode()).hexdigest()[:16], "kind": "web",
                    "name": (card["name"] if card.get("page_check") else (item.get("title") or item.get("domain") or ""))[:160],
                    "address": None,
                    "site": item.get("domain") or "", "url": url}
            start = url
        else:
            if not public_url_ok(url):
                raise HTTPException(422, "Enter a public http(s) website address.")
            host = urlsplit(url).hostname or ""
            cand = {"key": "url:" + hashlib.sha256(url.encode()).hexdigest()[:16], "kind": "url", "name": name or host,
                    "address": None, "site": host, "url": url}
            start = url
        bname = directory["name"] if directory else name
        # A checked building already has its checked list; the public reader is for buildings we don't know.
        d = await run_in_threadpool(discover_property, fetcher, start, evidence, start, bname,
                                    reader if directory is None else None)
        policy_blocked = bool(d.pages) and d.pages[0].status == "blocked_by_policy"
        searched_for_recovery = False
        if (body.kind == "url" and evidence is None and not policy_blocked and not has_strong_plans(d) and d.reference is None
                and name and (city or zip_) and settings.live_available):
            try:  # one bounded, cached search; the query has the public name + location only
                data = await cached_research(project_id, sid, "property", property_query(name, location))
                searched_for_recovery = True
                await run_in_threadpool(recover, fetcher, d, data["results"], start, name)
            except HTTPException as exc:
                d.notes.append(f"A web search for other public pages of this building failed: {exc.detail}")
        elif body.kind == "url" and evidence is None and not policy_blocked and not has_strong_plans(d) and not (name and (city or zip_)):
            d.notes.append("Add the building name and city or ZIP in “Your place” to let us search for other public pages of it.")
        if not policy_blocked and not has_strong_plans(d) and d.reference is None and directory is None:
            # Still nothing: listing-site pages that name this building AND its city/ZIP, for the user to choose.
            d.alternatives = listing_alternatives(evidence if evidence is not None else (data["results"] if searched_for_recovery else []),
                                                  name, city, st, zip_)
        if directory is not None and d.reference is None and not policy_blocked:
            d.reference = _public_reference(directory)  # a checked building always offers its checked list
            d.notes.append(f"Also listed: {len(directory['plans'])} previously checked published plan types (observed on "
                           f"{directory['source_page']} on {directory['observed_at'][:10]} UTC). Not current availability "
                           "and not every unit variant.")
        result = discovery_payload(project_id, d)
        building = {k: cand.get(k) for k in ("key", "kind", "name", "address", "site", "url", "directory", "city", "state",
                                             "zip", "observed_at", "source_page")}
        result.update(building=building, gallery=gallery(d, d.reference), searched_at=now(),
                      searched_for_recovery=searched_for_recovery,
                      identity={"name": bname, "city": city, "state": st, "zip": zip_})
        if apt_:
            ctx = place_context(project_id)
            chosen = SelectedBuilding(key=cand["key"], kind=cand["kind"], name=cand["name"][:160], address=cand.get("address"),
                                      site=(cand.get("site") or "")[:255], url=start, directory=cand.get("directory"),
                                      selected_at=now())
            new_ctx = ctx.model_copy(update={"property_name": (name or ctx.property_name)[:120], "city": city or ctx.city,
                                             "state": st or ctx.state, "zip": zip_ or ctx.zip, "property_url": start,
                                             "building": chosen})
            db.add_apartment_context(apt_["id"], ApartmentContext.model_validate(new_ctx.model_dump()).model_dump())
        row = db.add_place_discovery(sid, apt_["id"] if apt_ else None, project_id, cand["key"], result)
        db.event("building_selected", {"kind": cand["kind"], "key": cand["key"], "site": cand.get("site"),
                                       "gallery": len(result["gallery"]), "recovery": len(d.recovery),
                                       "pages": [{k: p[k] for k in ("url", "status", "via")} for p in result["pages"]]},
                 project_id, sid)
        return {"discovery": {**result, "id": row["id"], "version": row["version"], "created_at": row["created_at"]},
                "state": state(project), "apartment": apartment_state(owned_apartment(apt_["id"], sid)) if apt_ else None}

    @app.get("/api/projects/{project_id}/place-discovery")
    def get_place_discovery(project_id: str, sid: str = Depends(session)):
        """The saved building discovery for this place (shared by its rooms). No fetch, no search, no cost.
        If the place's chosen building changed since, the older result is not returned as current."""
        owned(project_id, sid)
        apt_ = db.apartment_of_project(project_id)
        row = db.latest_place_discovery(sid, apt_["id"] if apt_ else None, project_id)
        if row is None:
            return {"discovery": None, "note": None}
        if apt_:
            current = place_context(project_id).building
            if current is None or current.key != row["building_key"]:
                return {"discovery": None, "note": "Your chosen building changed; look up its plans again."}
        return {"discovery": {**row["data"], "id": row["id"], "version": row["version"], "created_at": row["created_at"]},
                "note": None}

    @app.post("/api/projects/{project_id}/place-discovery/{discovery_id}/alternative")
    async def read_listing_alternative(project_id: str, discovery_id: str, body: UrlRequest, sid: str = Depends(session)):
        """The user's explicit choice to read ONE listing-site page offered in this place's saved discovery (never an
        arbitrary URL). Direct SafeFetcher read, then the public page reader; the page must name the building and its
        city/ZIP. Appends a NEW discovery version (the earlier one is unchanged); nothing is selected or imported."""
        owned(project_id, sid)
        row = db.place_discovery_by_id(discovery_id)
        apt_ = db.apartment_of_project(project_id)
        in_scope = bool(row) and row["session_id"] == sid and (
            row["apartment_id"] == apt_["id"] if apt_ else (row["apartment_id"] is None and row["project_id"] == project_id))
        if not in_scope:
            raise HTTPException(404, "Discovery not found.")
        data = row["data"]
        alt = next((a for a in data.get("alternatives") or [] if a["url"] == body.url), None)
        if alt is None:
            raise HTTPException(422, "Only a listing page offered for this building can be read here.")
        if alt.get("tried"):
            raise HTTPException(409, "That listing page was already read for this building.")
        ident = data.get("identity") or {}
        sub = await run_in_threadpool(read_alternative, fetcher, reader, body.url, ident.get("name") or "",
                                      ident.get("city") or "", ident.get("state") or "", ident.get("zip") or "")
        part = discovery_payload(project_id, sub)
        new_items = [g for g in gallery(sub, None) if all(g["url"] != x["url"] for x in data.get("gallery") or [])]
        merged = {**data, "pages": [*data.get("pages", []), *part["pages"]],
                  "plan_images": [*data.get("plan_images", []), *[im for im in sub.plan_images if any(g["url"] == im["url"] for g in new_items)]],
                  "gallery": [*(data.get("gallery") or []), *new_items], "notes": [*data.get("notes", []), *sub.notes],
                  "alternatives": [{**a, "tried": True, "found": len(new_items)} if a["url"] == body.url else a
                                   for a in data.get("alternatives") or []],
                  "recovery": [*(data.get("recovery") or []), {"url": body.url, "kind": "listing", "why": alt["why"],
                                                                "status": "ok" if new_items else "no_plans",
                                                                "found": len(new_items), "detail": part["pages"][-1]["detail"][:200]}]}
        new = db.add_place_discovery(sid, row["apartment_id"], project_id, row["building_key"], merged)
        db.event("listing_alternative_read", {"url": body.url, "site": alt["site"], "found": len(new_items),
                                              "pages": [{k: p[k] for k in ("url", "status", "via")} for p in part["pages"]]},
                 project_id, sid)
        return {"discovery": {**merged, "id": new["id"], "version": new["version"], "created_at": new["created_at"]}}

    @app.get("/api/projects/{project_id}/store-links")
    def store_links(project_id: str, category: Literal[CATEGORIES],  # type: ignore[valid-type]
                    size: Literal["twin", "full", "queen", "king"] | None = None, sid: str = Depends(session)):
        """Store and marketplace search links for the user to open (no AI call, no fetch, no cost). Leads only:
        nothing behind them is checked until the user imports a specific product page."""
        owned(project_id, sid)
        prefs = Preferences.model_validate((db.head("preference_versions", project_id) or {}).get("data") or {})
        sz = size or (prefs.bed_size if prefs.bed_size != "any" and category in ("bed_frame", "mattress") else None)
        return {"links": external_search_links(category, "", sz), "size": sz if category in ("bed_frame", "mattress") else None}

    @app.post("/api/projects/{project_id}/research/furniture")
    async def research_furniture(project_id: str, body: FurnitureResearchRequest, sid: str = Depends(session)):
        owned(project_id, sid)
        ctx = place_context(project_id, body.city, body.state, body.zip)
        prefs = Preferences.model_validate((db.head("preference_versions", project_id) or {}).get("data") or {})
        condition = body.condition or (prefs.condition if prefs.condition else ctx.condition)
        fulfillment = body.fulfillment or ctx.fulfillment
        budget = body.budget_usd or (prefs.budget_cents // 100 if prefs.budget_cents else None)
        size = body.size or (prefs.bed_size if prefs.bed_size != "any" and body.category in ("bed_frame", "mattress") else None)
        query = furniture_query(body.category, ctx.public_location(), condition, fulfillment, budget, size)
        data = await cached_research(project_id, sid, "furniture", query)
        # Furniture results only from approved sources (established stores; approved resale listings). Other websites
        # are counted, never listed as links (property/building research is a separate, unfiltered workflow).
        from .resale import _host_site, retailer_site, resale_site
        results = data.get("results", [])
        kept = [r for r in results if retailer_site(r.get("url", "")) or resale_site(r.get("url", "")) or
                _host_site(r.get("url", ""))]
        data = {**data, "results": kept, "hidden_unapproved": len(results) - len(kept)}
        data["size"] = size if body.category in ("bed_frame", "mattress") else None
        data["external_search_links"] = external_search_links(body.category, ctx.public_location(), size)
        data["note"] = ("Found by web search: price, size, condition, availability and pickup/delivery are unknown until you "
                        "import a listing and its page shows them. Listings change; check with the seller.")
        return data

    @app.post("/api/projects/{project_id}/layouts")
    def regenerate_layouts(project_id: str, sid: str = Depends(session)):
        """Add furniture arrangements to the CURRENT plan without changing its products (no AI call).
        Appends a new plan version linked to the same preference and room versions; old versions stay as saved."""
        project = owned(project_id, sid)
        head = db.head("plan_versions", project_id)
        if not head:
            replan(project, "Plans with furniture arrangements")
            return state(project)
        ps = PlanSet.model_validate(head["data"])
        prefs_row = db.version_by_id("preference_versions", project_id, head["preference_version_id"])
        prefs = Preferences.model_validate(prefs_row["data"]) if prefs_row else default_preferences(project["room_type"])
        room_row = db.version_by_id("room_versions", project_id, head["room_version_id"]) if head["room_version_id"] else None
        room = RoomModel.model_validate(room_row["data"]["room"]) if room_row else None
        by_id = {p["id"]: p for p in full_catalog(project_id)}
        attach_layouts(ps, by_id, prefs, room, project, head["room_version_id"])
        ps.changes = [f"Furniture arrangements generated ({LAYOUT_METHOD}); products and prices unchanged."]
        row = db.add_plan_version(project_id, ps.model_dump(), head["room_version_id"], head["preference_version_id"],
                                  json.loads(head["product_refs"]), f"Arrangements generated for plan v{head['version']} ({LAYOUT_METHOD})")
        db.event("layouts_generated", {"plan_version": row["version"], "from_version": head["version"]}, project_id, sid)
        return state(project)

    @app.post("/api/projects/{project_id}/revert")
    def revert(project_id: str, body: RevertRequest, sid: str = Depends(session)):
        project = owned(project_id, sid)
        table = "plan_versions" if body.kind == "plan" else "preference_versions"
        old = db.version_by_id(table, project_id, body.version_id)
        if not old:
            raise HTTPException(404, "Version not found.")
        if body.kind == "preferences":
            db.add_preference_version(project_id, old["data"], f"Reverted to preferences v{old['version']}", "manual")
            replan(project, f"Plans after reverting preferences to v{old['version']}")
            return state(project)
        # Restore a consistent bundle: append copies of the plan's own preferences and room evidence,
        # then the plan, so active controls, room and displayed plan agree. Old rows are untouched.
        pref_old = db.version_by_id("preference_versions", project_id, old["preference_version_id"])
        new_pref = db.add_preference_version(project_id, pref_old["data"],
                                             f"Restored with plan v{old['version']} (from preferences v{pref_old['version']})", "manual")
        new_room_id = None
        if old["room_version_id"]:
            room_old = db.version_by_id("room_versions", project_id, old["room_version_id"])
            new_room = db.add_room_version(project_id, room_old["data"], json.loads(room_old["source_ids"]),
                                           room_old["method"], room_old["model"], room_old["prompt_version"], None,
                                           f"Restored with plan v{old['version']} (from room v{room_old['version']})")
            new_room_id = new_room["id"]
        db.add_plan_version(project_id, old["data"], new_room_id, new_pref["id"], json.loads(old["product_refs"]),
                            f"Restored plan v{old['version']} with its preferences and room evidence")
        return state(project)

    @app.get("/api/projects/{project_id}/history")
    def history(project_id: str, sid: str = Depends(session)):
        owned(project_id, sid)
        return {"room": db.versions("room_versions", project_id),
                "preferences": db.versions("preference_versions", project_id),
                "plans": db.versions("plan_versions", project_id),
                "events": db.events(project_id)}

    def discovery_payload(project_id: str, d) -> dict:
        """Public discovery result; every fetched page (and every public reader reply) is stored immutably as a source
        of THIS room. Plan candidates found through the reader point at the stored reply they came from."""
        pages = []
        for rec in d.pages:
            entry = {"url": rec.url, "status": rec.status, "detail": rec.detail, "via": rec.via}
            if rec.fetch and rec.reader:
                src_id = store_reader_source(project_id, rec)
                entry.update(source_id=src_id, sha256=rec.fetch.sha256, retrieved_at=rec.fetch.retrieved_at,
                             final_url=rec.reader["url_source"], reader=rec.reader)
                for im in d.plan_images:
                    if im.get("found_on") == rec.reader["url_source"] and im.get("via") in ("reader", "third_party"):
                        im.setdefault("evidence_source_id", src_id)
            elif rec.fetch:
                src_id = store_html_source(project_id, rec.fetch, "property_page")
                entry.update(source_id=src_id, sha256=rec.fetch.sha256, retrieved_at=rec.fetch.retrieved_at,
                             final_url=rec.fetch.final_url)
            pages.append(entry)
        return {"pages": pages, "plan_images": d.plan_images, "plan_pdfs": d.plan_pdfs, "plan_names": d.plan_names,
                "unit_area_mentions": d.unit_area_mentions, "notes": d.notes, "reference": d.reference,
                "website": d.website, "live_ok": any(p["status"] == "ok" and p["via"] in ("start", "linked", "recovery") for p in pages),
                "recovery": d.recovery, "alternatives": d.alternatives, "unsupported_plans": d.unsupported_plans}

    @app.post("/api/projects/{project_id}/property")
    def property_lookup(project_id: str, body: UrlRequest, sid: str = Depends(session)):
        project = owned(project_id, sid)
        d = discover_property(fetcher, body.url, reader=reader)
        result = discovery_payload(project_id, d)
        pages = result["pages"]
        db.event("property_lookup", {"url": body.url, "pages": [{k: p[k] for k in ("url", "status")} for p in pages],
                                     "plan_images": len(d.plan_images),
                                     "reference_offered": (d.reference or {}).get("directory"),
                                     "reference_count": len((d.reference or {}).get("plans", []))}, project_id, sid)
        return {"discovery": result, "state": state(project)}

    @app.post("/api/projects/{project_id}/property/plan-image")
    def property_plan_image(project_id: str, body: PlanImageRequest, sid: str = Depends(session)):
        project = owned(project_id, sid)
        if floorplan_count(project_id) >= MAX_FLOORPLANS:
            raise HTTPException(409, f"At most {MAX_FLOORPLANS} floor plans (images or PDFs) per project.")
        try:
            res = fetch_plan_image(fetcher, body.url)
        except (FetchBlocked, FetchFailed) as exc:
            raise HTTPException(422, f"Could not retrieve that plan: {exc}")
        if res.content_type == "application/pdf":
            raise HTTPException(422, "That plan is a PDF. Automatic PDF plan reading is not implemented; "
                                     "upload it as a source and enter its printed dimensions.")
        try:
            r = add_image_source(project_id, res.body, Path(res.final_url).name[:80], "floorplan",
                                 source_url=res.final_url, retrieved_at=res.retrieved_at)
        except UploadRejected as exc:
            raise HTTPException(422, str(exc))
        ref = reference_for_image(body.url)  # provenance from OUR directory, never from client input
        prov = {"via": "property discovery", "requested_url": body.url, "image_url": res.final_url,
                "image_retrieved_at": res.retrieved_at, "image_sha256": res.sha256}
        if ref:
            directory, plan = ref
            prov.update(via="checked reference directory", reference_directory=directory["_file"],
                        reference_property=directory["property"], reference_source_page=directory["source_page"],
                        reference_observed_at=directory["observed_at"], reference_plan_name=plan["name"],
                        caveat="Official public plan image; not proof that it matches your exact unit.")
        if body.discovery_id:
            item, row = saved_gallery_item(body.discovery_id, project_id, sid, body.url)
            if item and item["origin"] in ("reader", "third_party"):
                prov.update(via="public page reader" if item["origin"] == "reader" else "third-party listing page",
                            plan_page_url=item.get("found_on"), read_method=item.get("method"),
                            reader_source_id=item.get("evidence_source_id"), plan_heading=item.get("heading"),
                            plan_alt_text=item.get("alt") or None, third_party_site=item.get("site"),
                            page_published_time=item.get("published_time"))
                if item["origin"] == "third_party":
                    prov["caveat"] = (f"Plan image from a listing page on {item.get('site')}, not the building’s own "
                                      "website; not proof that it matches your exact unit.")
            if item:  # recorded from OUR saved discovery, never from client claims
                b = row["data"].get("building") or {}
                prov.update(discovery_id=row["id"], discovery_version=row["version"], building_key=b.get("key"),
                            building_name=b.get("name"), gallery_origin=item["origin"], plan_found_on=item.get("found_on"),
                            plan_seen_at=item.get("seen_at"), plan_type_label=item.get("plan_type"))
                if not ref:
                    prov["reference_plan_name"] = item["name"]
                    if item["origin"] == "recovered":
                        prov["via"] = "web search recovery"
                prov = {k: v for k, v in prov.items() if v is not None}
                prov.setdefault("caveat", "Public plan image; not proof that it matches your exact unit.")
        if not r["duplicate"]:
            db.exec("INSERT OR IGNORE INTO source_provenance VALUES (?,?,?,?)", (r["id"], project_id, json.dumps(prov), now()))
        db.event("plan_image_imported", prov, project_id, sid)
        return {"source": r, "provenance": prov, "state": state(project)}

    @app.post("/api/projects/{project_id}/listings")
    def add_listing(project_id: str, body: ListingRequest, sid: str = Depends(session)):
        project = owned(project_id, sid)
        snap, res, msg = import_listing(fetcher, body.url, body.category, body.condition)  # approved sources only
        if snap is None:
            db.event("listing_failed", {"url": body.url, "error": msg}, project_id, sid)
            raise HTTPException(422, f"Listing import failed: {msg}. Nothing was added to your plans.")
        src_id = store_html_source(project_id, res, "listing_page")  # raw page kept immutably as evidence
        snap["source_asset_id"] = src_id
        db.upsert_snapshot(snap, snap_hash(snap), project_id, src_id)
        db.event("listing_imported", {"url": body.url, "status": snap["status"], "missing": snap["missing"],
                                      "warning": None if msg == "ok" else msg}, project_id, sid)
        if body.rebuild_plans:
            replan(project, "Plans after listing import")
        return {"snapshot": snap, "warning": None if msg == "ok" else msg, "plans_rebuilt": body.rebuild_plans,
                "state": state(project)}

    register_design_routes(app, db=db, session=session, owned_apartment=owned_apartment, model_for_live=model_for_live,
                           full_catalog=full_catalog, ledger=ledger, settings=settings, research=cached_research,
                           place_context=place_context, fetcher=fetcher, store_html_source=store_html_source,
                           snap_hash=snap_hash, reader=reader, store_reader_source=store_reader_source)

    @app.get("/api/projects/{project_id}/usage")
    def usage(project_id: str, sid: str = Depends(session)):
        owned(project_id, sid)
        return ledger.summary(project_id=project_id)

    @app.get("/api/projects/{project_id}/export")
    def export(project_id: str, sid: str = Depends(session)):
        project = owned(project_id, sid)
        ps = head_plans(project_id)
        room = head_room(project_id)
        lines = [f"# Furniture AI shopping plan — {project['name']} ({project['room_type']})", ""]
        if project["is_demo"]:
            lines += ["**SYNTHETIC DEMO — fixture data, not a real room and not AI output.**", ""]
        lines.append(f"Room scale: {room.scale_status if room else 'unknown'}. Fit labels are not guarantees; delivery "
                     "access (stairs, doors, elevator) is not checked.")
        for pl in (ps.plans if ps else []):
            lines += ["", f"## {pl.title}", f"Item subtotal: ${pl.subtotal_cents / 100:,.2f} — fit: {pl.fit_summary}"]
            for i in pl.items:
                price = "kept" if i.existing_item_id else (f"${i.price_cents / 100:,.2f}" if i.price_cents is not None else "price unknown")
                lines.append(f"- {i.name} — {price} — {i.retailer or ''} {i.url or ''} (checked {i.checked_at or 'n/a'}) [{i.fit_label}]")
            if pl.missing_required:
                lines.append("- Missing: " + ", ".join(pl.missing_required))
            lay = pl.layouts
            if lay and lay.basis == "unavailable":
                lines.append("- No furniture arrangement: the room is not mapped yet. " + " ".join(lay.notes[:1]))
            elif lay and lay.basis == "concept_template":
                lines.append("- This saved version used an illustrative template outline (not your room); regenerate arrangements.")
            elif lay and lay.arrangements:
                kind = lay.envelope_label
                lines.append(f"- Arrangements ({lay.method_version}; {kind}): "
                             + "; ".join(f"{a.title} — {a.intent}" for a in lay.arrangements))
                lines.append("  - Assumptions: " + " ".join(lay.assumptions[:2]))
                first = lay.arrangements[0]
                if first.unplaced:
                    lines.append("  - Not drawn: " + "; ".join(f"{u.label} ({u.reason})" for u in first.unplaced))
                lines.append("  - Not verified: door swings, walking routes, accessibility.")
            elif lay is None:
                lines.append("- No furniture arrangements saved for this plan version.")
        for c in (ps.conflicts if ps else []):
            lines.append(f"> Conflict: {c}")
        return JSONResponse({"markdown": "\n".join(lines),
                             "note": "Export contains no photos, credentials or session tokens."})

    # ------------------------------------------------------------ frontend
    if DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = DIST / path
            if path and f.is_file() and f.resolve().is_relative_to(DIST.resolve()):
                return FileResponse(f)
            return FileResponse(DIST / "index.html")
    else:
        @app.get("/")
        def no_frontend():
            return JSONResponse({"message": "Frontend not built. Run ./run.sh (it builds frontend/dist)."})

    return app
