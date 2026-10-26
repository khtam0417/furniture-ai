"""Bounded property discovery and listing import.

Page content is untrusted evidence: it is parsed deterministically and never sent to a model as
instructions. Every fetched response is stored as an immutable source asset with URL, hash and date.

Property discovery: one start page + at most MAX_FOLLOW same-site links/iframes whose URL or anchor text
suggests floor plans. It reports floor-plan image/PDF candidates and plan-name text for the user to
choose from. It never infers a user's unit or room size from a building-wide page or unit square footage.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .adapters import adapter_for
from .catalog import snapshot_from_facts
from .html_extract import decode_html, extract, find_products, offer_price
from .safe_fetch import HTML_TYPES as _HTML, IMAGE_TYPES, PDF_TYPES, FetchBlocked, FetchFailed, FetchResult, SafeFetcher

MAX_FOLLOW = 3
MAX_CANDIDATES = 12
MAX_CONTEXT_PER_PAGE = 6
_PLAN_HINT = re.compile(r"(?i)floor[\s_-]?plans?|floorplans?|availability|/units?\b|layouts?|brochure")
_PLAN_LINK_TEXT = re.compile(r"(?i)\b(?:view|see|show|open)\s+(?:the\s+)?(?:floor\s*)?plans?\b|\bplan\s+details?\b")
_PLAN_QUERY = re.compile(r"(?i)[?&](?:fp|floorplan|floor_plan|floorplanid|plan|planid)=")
_PLAN_IMG = re.compile(r"(?i)floor[\s_-]?plan|floorplan|/fp[_-]|plan[_-]?\w*\.(?:jpe?g|png|webp)")
_PLAN_CONTEXT_URL = re.compile(r"(?i)floor[\s_-]?plans?|floorplans?|/apartments?/|/units?/|/residences?/|studio|\d-?bed|[?&]fp=")
_UNIT_TOKEN = re.compile(r"(?i)\b(?:studio|\d\s*(?:bed(?:room)?s?|br|bd)|[s\d]\s*x\s*\d|[sab]\d{1,2}|plan)\b")
_SIZE_TOKEN = re.compile(r"(?i)\d{3,4}\s*[-_ ]?\s*(?:sq\.?\s*ft|sqft|sf\b|square\s*feet)")
_NOT_PLAN = re.compile(r"(?i)logo|icon|sprite|favicon|avatar|badge|banner|social|\.svg(?:$|\?)|pixel|tracking")
# Leasing-system unit-type codes in an image's alt text, e.g. Entrata "848 | Sx1 A" (studio, 1 bath) or "1x1 Den".
_UNIT_CODE = re.compile(r"(?i)(?:^|[\s|/_(-])(?:s|[1-5])\s?x\s?[1-4](?:\.5)?(?=$|[\s|/_.),-])")
# Words that mark a photo of a space or amenity, not a plan drawing.
_PHOTO_WORDS = re.compile(r"(?i)\b(?:photo|picture|living\s*room|kitchen|bath(?:room)?\s+(?:photo|vanity)|bedroom\s+photo|pool|gym|"
                          r"fitness|lobby|lounge|rooftop|roof\s*deck|amenit|exterior|interior|courtyard|view|model\s+unit|tour|"
                          r"gallery|staged|furnished\s+photo)\b")
_RANK = {"named_floor_plan": 0, "unit_size_label": 1, "unit_code_label": 1, "plan_heading_label": 1, "plan_page_image": 2,
         "recovered_image": 2}


# Drupal image-style derivative: <prefix>/styles/<style>/public/<file>. Same prefix + file = same source asset.
_DRUPAL_STYLE = re.compile(r"^(?P<prefix>.*?/files)/styles/(?P<style>[^/]+)/public/(?P<file>[^?#]+)")


# Image-CDN transformation path (Cloudinary-style, used by many property sites):
# <prefix>/image/upload/<transform>[/<transform>…]/<file>, e.g. ".../upload/q_auto,c_limit,w_576,h_260/s3/2/1/a(1).png".
_CDN_TRANSFORM = re.compile(r"^(?P<prefix>.*?/(?:image|video)/upload)/(?P<style>(?:[a-z]{1,3}_[^/]*/)*)(?P<file>[^?#]+)$")


def _asset_key(url: str) -> tuple[str, str, str, str] | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    m = _DRUPAL_STYLE.match(parts.path)
    if m:
        return ("drupal", host, m.group("prefix"), m.group("file"))
    m = _CDN_TRANSFORM.match(parts.path)
    return ("cdn", host, m.group("prefix"), m.group("file")) if m else None


def _variant_score(url: str) -> tuple[bool, bool, int]:
    """Higher = better copy of the same file: not cropped, no height cap, then the largest width."""
    from .html_extract import _CROPPED

    path = urlsplit(url).path
    m = _DRUPAL_STYLE.match(path)
    if m:
        nums = [int(n) for n in re.findall(r"\d+", m.group("style"))]
        return (not _CROPPED.search(path), True, max(nums) if nums else 0)
    m = _CDN_TRANSFORM.match(path)
    style = m.group("style") if m else ""
    cropped = bool(re.search(r"(?:^|[,/])(?:c_(?:crop|fill|lfill|thumb|pad|fill_pad|lpad)|[xy]_\d)", style))
    widths = [int(n) for n in re.findall(r"(?:^|[,/])w_(\d+)", style)]
    return (not cropped, not re.search(r"(?:^|[,/])h_\d", style), max(widths) if widths else 10**6)


def merge_style_variants(cands: list[dict]) -> list[dict]:
    """Collapse candidates that are explicit image-style derivatives of the SAME referenced file (same host, files
    prefix and file path; only the style segment/query or CDN transformation segments differ), keeping the
    uncropped/larger referenced variant and listing the others. Anything without that explicit identity is left alone
    (never merged by alt text)."""
    out: list[dict] = []
    index: dict[tuple, int] = {}
    rank = _RANK
    for c in cands:
        key = _asset_key(c["url"])
        if key is None or key not in index:
            if key is not None:
                index[key] = len(out)
            out.append(dict(c))
            continue
        kept = out[index[key]]
        variants = kept.setdefault("variants", [kept["url"]])
        if c["url"] not in variants:
            variants.append(c["url"])
        if _variant_score(c["url"]) > _variant_score(kept["url"]):
            kept["url"], kept["alt"] = c["url"], c["alt"] or kept["alt"]
        if rank[c["kind"]] < rank[kept["kind"]]:
            kept["kind"], kept["label"] = c["kind"], c["label"]
    return out


def _classify_image(src: str, alt: str, plan_context: bool) -> tuple[str, str] | None:
    """(kind, honest label) for an image that may be a floor plan, or None. Bounded, deterministic heuristics."""
    from urllib.parse import unquote

    if not src.startswith("https://") or _NOT_PLAN.search(src) or _NOT_PLAN.search(alt):
        return None
    name = unquote(src.rsplit("/", 1)[-1].split("?", 1)[0])
    text = f"{alt} {name}"
    if _PLAN_IMG.search(src) or _PLAN_IMG.search(alt):
        return "named_floor_plan", "Named as a floor plan on the page"
    if _SIZE_TOKEN.search(text) and _UNIT_TOKEN.search(text):
        return "unit_size_label", "Image labeled with a unit type and size (likely a plan; check it)"
    if _UNIT_CODE.search(alt) and not _PHOTO_WORDS.search(alt):
        return "unit_code_label", "Labeled with a unit-type code such as 1x1 or Sx1 (likely a plan; check it)"
    if plan_context and _UNIT_TOKEN.search(text) and not _PHOTO_WORDS.search(alt):
        return "plan_page_image", "Unit-type image on a floor-plan page (may be a photo, not a plan)"
    return None
_PLAN_NAME = re.compile(r"(?i)\b(studio(?:\s+[a-z]?\d{0,2})?|[a-z]{0,2}\d\s?(?:bed(?:room)?s?|br)\b|\b[sab]\d{1,2}\b|\b[s1-5]x[1-4]\b)")
_SQFT = re.compile(r"(?i)\b(\d{3,4})\s*(?:sq\.?\s?ft|square feet|sf)\b")


def registrable(host: str) -> str:
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def same_site(a: str, b: str) -> bool:
    ha, hb = urlsplit(a).hostname or "", urlsplit(b).hostname or ""
    return registrable(ha) == registrable(hb)


@dataclass
class PageRecord:
    url: str
    status: str  # ok | blocked_by_site | blocked_by_policy | failed
    detail: str = ""
    fetch: FetchResult | None = None
    via: str = "start"  # start | linked | recovery (web-search evidence) | reader (public page reader) | third_party
    reader: dict | None = None  # public reader provenance (reader URL, the page it read, times); see reader.py


@dataclass
class Discovery:
    pages: list[PageRecord] = field(default_factory=list)
    plan_images: list[dict] = field(default_factory=list)
    plan_pdfs: list[str] = field(default_factory=list)
    plan_names: list[str] = field(default_factory=list)
    unit_area_mentions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reference: dict | None = None  # checked reference directory (offered only when live discovery gave nothing)
    website: str | None = None  # safe link the user can open in their own browser
    recovery: list[dict] = field(default_factory=list)  # alternative URLs tried, with outcome (never just listed)
    alternatives: list[dict] = field(default_factory=list)  # listing-site pages the USER may choose to read (not fetched)
    unsupported_plans: list[dict] = field(default_factory=list)  # plan drawings in formats this build can't import (SVG)


# ------------------------------------------------------------------ checked reference directories
REFS_DIR = Path(__file__).resolve().parents[2] / "data" / "property_refs"


def _load_references() -> list[dict]:
    out = []
    for f in sorted(REFS_DIR.glob("*.json")) if REFS_DIR.is_dir() else []:
        d = json.loads(f.read_text())
        # Each entry point = exact hosts + the paths supported on THOSE hosts (older files: one hosts/path_pattern).
        eps = d.get("entry_points") or [{"hosts": d["hosts"], "path_pattern": d["path_pattern"]}]
        d["_entries"] = [({h.lower() for h in e["hosts"]}, re.compile(e["path_pattern"])) for e in eps]
        d["_file"] = f.name
        out.append(d)
    return out


REFERENCES = _load_references()


def reference_directory_for(url: str) -> dict | None:
    """The checked directory for EXACTLY a known host + supported path (no lookalikes, subdomains, ports,
    credentials or non-http(s) schemes)."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.username or parts.password or port not in (None, 80, 443):
        return None
    host = (parts.hostname or "").lower()
    for d in REFERENCES:
        if any(host in hosts and pattern.match(parts.path or "/") for hosts, pattern in d["_entries"]):
            return d
    return None


def reference_by_file(name: str) -> dict | None:
    return next((d for d in REFERENCES if d["_file"] == name), None)


def reference_for_image(url: str) -> tuple[dict, dict] | None:
    """(directory, plan) when `url` is exactly one of the checked reference image URLs."""
    for d in REFERENCES:
        for p in d["plans"]:
            if p["url"] == url:
                return d, p
    return None


def _public_reference(d: dict) -> dict:
    return {"property": d["property"], "source_page": d["source_page"], "observed_at": d["observed_at"],
            "method": d["method"], "note": d["note"], "directory": d["_file"], "address": d.get("address"),
            "plans": [{**p, "kind": "checked_reference", "label": "Previously checked official plan"} for p in d["plans"]]}


def _fetch_page(fetcher: SafeFetcher, url: str) -> PageRecord:
    try:
        res = fetcher.fetch(url, allowed_types=_HTML, max_bytes=3_000_000)
        return PageRecord(url, "ok", fetch=res)
    except FetchBlocked as exc:
        return PageRecord(url, "blocked_by_policy", str(exc))
    except FetchFailed as exc:
        msg = str(exc)
        if re.search(r"HTTP (401|403|429|444|451)", msg):
            return PageRecord(url, "blocked_by_site", msg + " — the site refuses automated access; "
                                                         "save the floor plan image yourself and upload it.")
        return PageRecord(url, "failed", msg)


_STRONG = {"named_floor_plan", "unit_size_label", "unit_code_label", "plan_heading_label"}


def has_strong_plans(d: Discovery) -> bool:
    """A real candidate: a PDF, or an image named/labeled as a plan. Unit-type images on a plan page (a photo
    heuristic) are weak and don't count."""
    return bool(d.plan_pdfs) or any(x["kind"] in _STRONG for x in d.plan_images)


def discover_property(fetcher: SafeFetcher, start_url: str, evidence: list[dict] | None = None,
                      site_url: str | None = None, building_name: str = "", reader=None) -> Discovery:
    """Live bounded discovery first. If it finds no strong candidates (empty, weak or blocked) and the address isn't
    policy-blocked, the SAME public page is read through the public page reader (`reader`, optional; see reader.py),
    following at most two floor-plan links observed in its text. Only if that also gives nothing, try a few
    alternative public URLs from the current search's evidence, scoped to the chosen building (see
    `recovery_candidates`), each fetched through the SafeFetcher. A checked reference directory for an exactly known
    host/path is offered unless live discovery found strong candidates (the reader isn't used for those); weak live
    candidates never hide it. Policy-blocked URLs never get a reader read, directory, recovery or a website link."""
    d = _discover_live(fetcher, start_url)
    policy_blocked = any(p.status == "blocked_by_policy" for p in d.pages[:1])
    if not policy_blocked:
        parts = urlsplit(start_url.strip())
        if parts.scheme in ("http", "https") and parts.hostname and not parts.username:
            d.website = start_url.strip()
        if reader is not None and not has_strong_plans(d) and reference_directory_for(start_url) is None:
            read_via_reader(reader, d, start_url, building_name)
        if evidence and not has_strong_plans(d):
            recover(fetcher, d, evidence, site_url or start_url, building_name)
        ref = reference_directory_for(start_url)
        if ref is not None and not has_strong_plans(d):
            d.reference = _public_reference(ref)
            d.notes.append(f"Automatic reading of this website found no plan images or PDFs it could rely on, so "
                           f"{len(ref['plans'])} previously checked published plan images are listed (observed on "
                           f"{ref['source_page']} on {ref['observed_at'][:10]} UTC). They are not current availability and "
                           "not every unit variant, and may not include your exact unit.")
    _note_unsupported(d)
    return d


def _note_unsupported(d: Discovery) -> None:
    n = len(d.unsupported_plans)
    if n and not any(x.startswith("Unsupported plan format") for x in d.notes):
        d.notes.append(f"Unsupported plan format: {n} floor-plan drawing{'' if n == 1 else 's'} on this site "
                       f"{'is an SVG file' if n == 1 else 'are SVG files'}, which this build can’t import or read. Open the "
                       "website to view them, or save one as a PNG/JPEG screenshot and upload it.")


def _discover_live(fetcher: SafeFetcher, start_url: str, max_follow: int = MAX_FOLLOW) -> Discovery:
    d = Discovery()
    first = _fetch_page(fetcher, start_url)
    d.pages.append(first)
    if first.status != "ok":
        d.notes.append("No property evidence retrieved. You can upload your own floor plan image instead.")
        return d
    queue: list[tuple[str, bool]] = []  # (url, reached through a plan link)
    seen = {start_url.rstrip("/")}

    def harvest(rec: PageRecord, via_plan_link: bool):
        page_url = rec.fetch.final_url
        ev = extract(decode_html(rec.fetch.body), page_url)
        plan_context = via_plan_link or bool(_PLAN_CONTEXT_URL.search(page_url))
        contextual = 0
        for src, alt in ev.images:
            if (urlsplit(src).path.lower().endswith(".svg") and _PLAN_IMG.search(alt)
                    and not re.search(r"(?i)logo|icon|sprite|badge", src + alt) and len(d.unsupported_plans) < 40
                    and all(x["url"] != src for x in d.unsupported_plans)):
                d.unsupported_plans.append({"url": src, "alt": alt[:200], "found_on": page_url})
            hit = _classify_image(src, alt, plan_context)
            if not hit or any(x["url"] == src for x in d.plan_images):
                continue
            kind, label = hit
            if kind == "plan_page_image":
                if contextual >= MAX_CONTEXT_PER_PAGE:
                    continue
                contextual += 1
            d.plan_images.append({"url": src, "alt": alt[:120], "found_on": page_url, "found_at": rec.fetch.retrieved_at,
                                  "kind": kind, "label": label})
        for href, text in ev.links:
            is_pdf = href.lower().split("?")[0].endswith(".pdf")
            if is_pdf and (_PLAN_IMG.search(href + " " + text) or _PLAN_HINT.search(href + " " + text)):
                d.plan_pdfs.append(href)
            plan_link = bool(_PLAN_LINK_TEXT.search(text) or _PLAN_QUERY.search(href))
            if (plan_link or _PLAN_HINT.search(href + " " + text)) and same_site(href, start_url):
                key = href.split("#")[0].rstrip("/")
                if key not in seen and key.startswith("https://"):
                    seen.add(key)
                    queue.append((href.split("#")[0], plan_link or bool(_PLAN_HINT.search(text))))
        for frame in ev.iframes:
            key = frame.rstrip("/")
            if same_site(frame, start_url) and key not in seen and key.startswith("https://"):
                seen.add(key)
                queue.insert(0, (frame, plan_context))
        for line in ev.text.splitlines():
            for m in _PLAN_NAME.finditer(line):
                name = " ".join(m.group(0).split())
                if name.lower() not in (n.lower() for n in d.plan_names) and len(d.plan_names) < 30:
                    d.plan_names.append(name)
            for m in _SQFT.finditer(line):
                if len(d.unit_area_mentions) < 20:
                    d.unit_area_mentions.append(line[:120])

    harvest(first, False)
    followed = 0
    while queue and followed < max_follow:
        url, via_plan = queue.pop(0)
        rec = _fetch_page(fetcher, url)
        rec.via = "linked"
        d.pages.append(rec)
        followed += 1
        if rec.status == "ok":
            harvest(rec, via_plan)
    d.plan_pdfs = list(dict.fromkeys(d.plan_pdfs))[:10]
    d.plan_images = merge_style_variants(d.plan_images)
    d.plan_images = sorted(d.plan_images, key=lambda x: _RANK[x["kind"]])[:MAX_CANDIDATES]
    if any(x["kind"] != "named_floor_plan" for x in d.plan_images):
        d.notes.append("Some candidates are matched only by their label or page; open each and pick a real floor plan.")
    d.notes.append("Property sites often show SAMPLE plans. Choose one only if it matches your unit; nothing is selected automatically.")
    if queue:
        d.notes.append(f"Stopped after {max_follow} linked pages (page budget).")
    if d.unit_area_mentions:
        d.notes.append("Unit square footage was found. It is total apartment area and is NOT used as room size.")
    if not d.plan_images and not d.plan_pdfs:
        d.notes.append("No floor-plan image or PDF links were found in server-rendered HTML (sites that load plans "
                       "with scripts or block bots cannot be read). You can upload a saved plan image instead.")
    if d.plan_pdfs:
        d.notes.append("PDF floor plans can be stored as sources, but automatic PDF plan reading is NOT implemented in this build.")
    if len(d.plan_names) > 1:
        d.notes.append("Several plan names appear; the building page does not identify YOUR unit. Pick one explicitly.")
    return d


# ------------------------------------------------------------------ plan types (gallery filters)
_STUDIO = re.compile(r"(?i)\bstudio\b|\befficiency\b|(?:^|[\s|/_(-])s\s?x\s?[1-4]\b")
_BEDS = re.compile(r"(?i)\b([1-9])\s*(?:-\s*)?(?:bed(?:room)?s?|br|bd)\b|(?:^|[\s|/_(-])([1-9])\s?x\s?[1-4](?:\.5)?\b")


def plan_type(*texts: str | None) -> str | None:
    """'studio' | '1' | '2' | '3' (3 or more bedrooms) from a plan's printed name/alt text, or None if it doesn't say.
    A label, not a measurement: it never sets a room size."""
    t = " ".join(x for x in texts if x)
    if _STUDIO.search(t):
        return "studio"
    m = _BEDS.search(t)
    if not m:
        return None
    n = int(m.group(1) or m.group(2))
    return "3" if n >= 3 else str(n)


# ------------------------------------------------------------------ matching buildings (checked directories)
_GENERIC = {"the", "apartments", "apartment", "apts", "apt", "residences", "residence", "homes", "at", "of", "and", "llc"}
US_STATES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california", "co": "colorado",
    "ct": "connecticut", "de": "delaware", "dc": "district of columbia", "fl": "florida", "ga": "georgia", "hi": "hawaii",
    "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa", "ks": "kansas", "ky": "kentucky", "la": "louisiana",
    "me": "maine", "md": "maryland", "ma": "massachusetts", "mi": "michigan", "mn": "minnesota", "ms": "mississippi",
    "mo": "missouri", "mt": "montana", "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey",
    "nm": "new mexico", "ny": "new york", "nc": "north carolina", "nd": "north dakota", "oh": "ohio", "ok": "oklahoma",
    "or": "oregon", "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina", "sd": "south dakota",
    "tn": "tennessee", "tx": "texas", "ut": "utah", "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming", "pr": "puerto rico",
}


def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _state_code(s: str) -> str:
    t = " ".join(_tokens(s))
    if t in US_STATES:
        return t
    return next((k for k, v in US_STATES.items() if v == t), t)


def _core_name(s: str, drop: set[str]) -> str:
    return " ".join(t for t in _tokens(s) if t not in _GENERIC and t not in drop)


def _edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance (insert, delete, substitute, swap two neighbors)."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def close_token(typed: str, known: str) -> bool:
    """Cautious typo match for one name word: identical, or both at least 5 letters, same first letter, and at most
    1 edit (2 for words of 7+ letters). "aduban"/"audobon" ~ "audubon" and "archve" ~ "archive", but "archer",
    "auburn" or "marchive" are not."""
    if typed == known:
        return True
    if min(len(typed), len(known)) < 5 or typed[0] != known[0]:
        return False
    return _edit_distance(typed, known) <= (2 if max(len(typed), len(known)) >= 7 else 1)


def _similar_name(q: str, known: str) -> bool:
    qt, kt = q.split(), known.split()
    return len(qt) == len(kt) and qt != kt and all(close_token(a, b) for a, b in zip(qt, kt))


def _location_verdict(supplied: str, known: str | None, same) -> bool | None:
    """True = consistent, False = contradicts, None = not supplied or not known (can't confirm either way)."""
    if not supplied.strip() or not known:
        return None
    return bool(same(supplied, known))


def match_directories(name: str, city: str = "", state: str = "", zip_: str = "") -> list[dict]:
    """Checked directories whose NAME matches (generic words like "the"/"apartments" and the directory's own city
    words ignored) AND whose location is consistent with EVERY location field the user supplied: none may
    contradict (e.g. New Haven + ZIP 10001 matches nothing), and the city or ZIP must positively match. A state alone
    is not a location. Same-name buildings elsewhere never match; nothing is selected for the user."""
    out = []
    for d in REFERENCES:
        if not d.get("aliases"):
            continue
        drop = set(_tokens(d.get("city", ""))) | set(_tokens(d.get("state", "")))
        q = _core_name(name, drop)
        known = {_core_name(a, drop) for a in [*d["aliases"], d.get("name", "")]} - {""}
        exact = bool(q) and q in known
        # A cautious typo suggestion ("Did you mean …?"), never a silent match; the location rules below are the same.
        suggested = bool(q) and not exact and any(_similar_name(q, k) for k in known)
        if not (exact or suggested):
            continue
        city_v = _location_verdict(city, d.get("city"), lambda a, b: _tokens(a) == _tokens(b))
        zip_v = _location_verdict(zip_, d.get("zip"), lambda a, b: a.strip()[:5] == b)
        state_v = _location_verdict(state, d.get("state"), lambda a, b: _state_code(a) == _state_code(b))
        if False in (city_v, zip_v, state_v) or not (city_v or zip_v):
            continue
        c = checked_candidate(d, matched_on=[x for x, v in (("city", city_v), ("ZIP", zip_v), ("state", state_v)) if v])
        c["suggested"] = suggested
        if suggested:
            c["typed_name"] = name.strip()[:120]
        out.append(c)
    return out


def checked_candidate(d: dict, matched_on: list[str] | None = None) -> dict:
    return {"key": f"checked:{d['_file']}", "kind": "checked", "directory": d["_file"], "name": d.get("name") or d["property"],
            "address": d.get("address"), "city": d.get("city"), "state": d.get("state"), "zip": d.get("zip"),
            "location_source": d.get("location_source"), "site": urlsplit(d["website"]).hostname, "url": d["website"],
            "source_page": d["source_page"], "observed_at": d["observed_at"], "plan_count": len(d["plans"]),
            "matched_on": matched_on or [],
            "evidence": [f"Checked official plan list for {d['property']}, observed in a browser on {d['observed_at'][:10]} UTC."]}


# ------------------------------------------------------------------ building candidates from web search evidence
_LISTING_SITES = {
    "apartments.com", "zillow.com", "trulia.com", "realtor.com", "hotpads.com", "redfin.com", "padmapper.com", "zumper.com",
    "apartmentlist.com", "rent.com", "forrent.com", "apartmentfinder.com", "apartmentguide.com", "rentals.com",
    "yelp.com", "facebook.com", "instagram.com", "linkedin.com", "craigslist.org", "streeteasy.com", "rentcafe.com",
    "apartmentratings.com", "google.com", "tripadvisor.com", "wikipedia.org", "youtube.com", "x.com", "twitter.com",
    "apartmenthomeliving.com", "forrentuniversity.com", "homes.com", "prospectportal.com", "rentable.co", "rentpath.com",
    "point2homes.com",
}
MAX_BUILDING_CANDIDATES = 6
# Trailing path segments that name a section of ONE building's site, not a different building.
_SECTION_SEG = re.compile(
    r"(?i)^(?:apartments?|floor-?plans?|plans?|availability|available|amenities|gallery|photos?|neighborhood|"
    r"location|contact(?:-us)?|units?|pricing|residences?|studios?|\d-?bed(?:room)?s?|[a-z]{0,2}\d{1,2}[a-z]?(?:-\d)?|"
    r"[s\d]x\d|index(?:\.\w+)?|home|overview|features|virtual-tours?|specials)$")


_PLAN_SECTION = re.compile(r"(?i)^(?:floor-?plans?|featured-?floor-?plans?|available-?units|availability|floorplan-?details?)$")
_UNIT_SECTION = re.compile(r"(?i)^(?:apartment|units?)$")


def property_path_base(url: str) -> str:
    """The part of a URL path that identifies a property: the path with trailing section segments removed
    ("/wa/seattle/ava-capitol-hill/floor-plans/" -> "/wa/seattle/ava-capitol-hill"; "/floorplans" -> "/").
    Two pages on one domain with different bases are treated as possibly different buildings."""
    segs = [s for s in urlsplit(url).path.split("/") if s]
    # Everything under a floor-plan/availability section is that property's plan or unit detail
    # ("/floorplans/studio-s", "/featuredfloorplans/1-bed…", "/ava-north-point/apartment/MA502-…").
    for i, seg in enumerate(segs):
        if _PLAN_SECTION.match(seg) or (i >= 1 and _UNIT_SECTION.match(seg)):
            segs = segs[:i]
            break
    while segs and _SECTION_SEG.match(segs[-1]):
        segs.pop()
    return "/" + "/".join(segs)


def _within(base: str, page_base: str) -> bool:
    return page_base == base or (base != "/" and page_base.startswith(base.rstrip("/") + "/"))


def _name_tokens(name: str, drop: set[str] = frozenset()) -> list[str]:
    return [t for t in _tokens(name) if t not in _GENERIC and t not in drop and len(t) >= 2]


def building_candidates(results: list[dict], name: str, city: str, state: str, zip_: str,
                        checked: list[dict], page_checks: dict[str, dict] | None = None) -> tuple[list[dict], list[str]]:
    """Candidate buildings from web-search results (evidence-backed URLs only, already public-URL checked).
    One card per property: same registrable domain AND same property path base (so an operator's "AVA Capitol Hill"
    and "AVA Ballard" pages stay separate cards); listing sites one card per page. Results on a checked
    directory's own hosts are folded into that checked card. Street addresses are not read from search results, so
    they stay unknown. Returns (cards, keys of checked cards also seen in search)."""
    from .research import file_kind

    checked_hosts = {}
    for c in checked:
        d = reference_by_file(c["directory"])
        for h in (d or {}).get("hosts", []):
            checked_hosts[registrable(h)] = c["key"]
    name_toks = _name_tokens(name)
    loc_terms = [x for x in (city.strip(), zip_.strip()[:5]) if x]
    st = state.strip()
    groups: dict[str, dict] = {}
    seen_checked: list[str] = []
    bases_by_domain: dict[str, set[str]] = {}
    for r in results:
        url, host = r.get("url") or "", (r.get("domain") or "").lower()
        if not url or r.get("low_relevance") or _NO_CRAWL.search(url):
            continue
        reg = registrable(host)
        if reg in checked_hosts:
            if checked_hosts[reg] not in seen_checked:
                seen_checked.append(checked_hosts[reg])
            continue
        listing = reg in _LISTING_SITES
        is_file = file_kind(url) != "page"
        base = property_path_base(url)
        if not listing and not is_file:
            bases_by_domain.setdefault(reg, set()).add(base)
        identity = url if listing else f"{reg}{base}"
        key = f"web:{hashlib.sha256(identity.encode()).hexdigest()[:16]}"
        text = f"{r.get('title', '')} {r.get('cited_text', '')}"
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"key": key, "kind": "web", "name": (r.get("title") or host)[:120], "address": None,
                               "site": host, "url": url, "urls": [], "listing_site": listing, "cited": False,
                               "path_base": None if listing else base, "registrable": reg,
                               "location_mentions": [], "name_in_site": bool(name_toks) and any(t in reg for t in name_toks),
                               "name_in_page": False, "evidence": []}
        if _names_building(name_toks, f"{url} {r.get('title', '')}"):
            g["name_in_page"] = True
        if url not in g["urls"] and len(g["urls"]) < 5:
            g["urls"].append(url)
        if "citation" in (r.get("evidence") or []):
            if not g["cited"] and r.get("file_kind", "page") == "page":
                g["url"], g["name"] = url, (r.get("title") or g["name"])[:120]
            g["cited"] = True
        for term in loc_terms + ([st] if st else []):
            if term and re.search(rf"(?i)\b{re.escape(term)}\b", text) and term not in g["location_mentions"]:
                g["location_mentions"].append(term)
    cards = []
    for g in groups.values():
        if any(urlsplit(u).path.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp")) for u in [g["url"]]) and len(g["urls"]) == 1:
            continue  # a lone file is a plan lead, not a building website
        where = (f"Search result mentions {', '.join(g['location_mentions'])}" if g["location_mentions"]
                 else "The search result doesn’t confirm the location; check it")
        multi = not g["listing_site"] and len(bases_by_domain.get(g["registrable"], ())) > 1
        g["multi_property_site"] = multi
        g["evidence"] = [where + ".", "Listing site, not the building’s own website." if g["listing_site"]
                         else (f"{g['registrable']} has pages for more than one property; this card is only the page at "
                               f"{g['path_base']}." if multi
                               else "Site name contains your building name." if g["name_in_site"]
                               else "Website found by web search; check it’s the official one.")]
        # Identity: only a result that actually names the building is offered as a building to choose. Listing or
        # directory pages, bare website names ("spinrep.com", "Zillow") and results that don't name it are sources.
        if g["listing_site"]:
            g["identity"], g["source_reason"] = "source", "Listing or directory site: a source about buildings, not the building itself."
        elif _domain_only(g["name"], g["site"], g["registrable"]):
            g["identity"], g["source_reason"] = "source", "Only a website name; this result doesn’t identify a building."
        elif not (g["name_in_page"] or g["name_in_site"]) or (multi and not g["name_in_page"]):
            g["identity"], g["source_reason"] = "source", "This result doesn’t name your building."
        else:
            g["identity"], g["source_reason"] = "building", None
        chk = (page_checks or {}).get(g["key"])
        if chk and g["identity"] == "source" and not g["listing_site"]:
            if chk.get("ok"):  # the lead's own page (read by us) names the building and its city/ZIP
                g["identity"], g["source_reason"], g["name"] = "building", None, chk["display_name"][:120]
                g["location_mentions"] = g["location_mentions"] or [x for x in (city.strip(), zip_.strip()[:5]) if x]
                g["evidence"] = [f"We read this page ({'via a public page reader' if chk.get('read_via') == 'public_reader' else 'directly'}, "
                                 f"{chk['retrieved_at'][:10]}): it names {name} and {city or zip_}.",
                                 "The site’s own name spells your building’s name; check it’s the official one."]
                g["page_check"] = {k: chk.get(k) for k in ("title", "final_url", "read_via", "retrieved_at")}
            else:
                g["source_reason"] = f"We read its page, but {chk.get('problem') or 'it didn’t confirm this building'}."
        cards.append(g)
    cards.sort(key=lambda g: (g["identity"] != "building", g["listing_site"], not g["name_in_page"] and not g["name_in_site"],
                              not g["location_mentions"], not g["cited"]))
    buildings = [g for g in cards if g["identity"] == "building"][:MAX_BUILDING_CANDIDATES]
    return buildings + [g for g in cards if g["identity"] == "source"][:MAX_BUILDING_CANDIDATES], seen_checked


def _names_building(name_toks: list[str], text: str) -> bool:
    """Every word of the building's name appears in the text (a cautious typo allowed, see `close_token`)."""
    words = _tokens(text)
    return bool(name_toks) and all(any(close_token(t, w) for w in words) for t in name_toks)


_LISTING_BRANDS = {reg.split(".")[0] for reg in _LISTING_SITES}


def _domain_only(title: str, host: str, reg: str) -> bool:
    """The title is only a website name: it is empty, contains the literal hostname/domain ("spinrep.com",
    "www.maplecourt.example"), or is just a known listing brand ("Zillow"). A real name that merely matches the
    site's name ("Maple Court" on maplecourt.example, "The Audubon" on theaudubonapts.com) is NOT domain-only; whether
    it names the user's building is decided separately."""
    low = title.lower()
    words = [w for w in _tokens(title) if w not in _GENERIC]
    if not words:
        return True
    if any(d and re.search(rf"(?<![a-z0-9-]){re.escape(d)}(?![a-z0-9-])", low) for d in {host.lower(), reg.lower()}):
        return True
    return "".join(words) in _LISTING_BRANDS


# ------------------------------------------------------------------ hostname-only search leads: read the page itself
MAX_LEAD_CHECKS = 2
LEAD_CHECK_METHOD = "lead-page-check-v1"


def leads_to_check(cards: list[dict], name: str, done: set[str]) -> list[dict]:
    """Search leads that are "sources" only because the search gave no usable title (just a hostname) or no page
    naming the building, on a site whose OWN domain spells the building's name. At most MAX_LEAD_CHECKS, leading
    results first. Listing sites and other domains stay "Other sources" untouched (never fetched here)."""
    out = []
    for c in cards:
        if (c["identity"] == "source" and not c["listing_site"] and c["key"] not in done
                and not c.get("multi_property_site") and domain_names_building(c["site"], name)):
            out.append(c)
        if len(out) >= MAX_LEAD_CHECKS:
            break
    return out


def check_lead_page(fetcher: SafeFetcher, reader, card: dict, name: str, city: str, state: str, zip_: str
                    ) -> tuple[dict, FetchResult | None]:
    """Read ONE search lead's own page (direct SafeFetcher read; if the site refuses, the public page reader) and check
    that the page itself names the building AND the city/ZIP (no other state), staying inside the lead's property
    path. Returns (check, raw fetch to store). Never selects anything; a failure leaves the lead as a source."""
    from .reader import ReaderRateLimited, ReaderRejected

    url = card["url"]
    base = {"card_key": card["key"], "url": url, "method": LEAD_CHECK_METHOD}
    try:
        res = fetcher.fetch(url, allowed_types=_HTML, max_bytes=3_000_000)
        ev = extract(decode_html(res.body), res.final_url)
        title = (ev.title or ev.meta.get("og:title") or "").strip()
        text, final, via = f"{ev.meta.get('og:site_name', '')} {ev.text[:20_000]}", res.final_url, "direct"
    except FetchBlocked as exc:
        return {**base, "ok": False, "problem": f"not a public address ({exc})"}, None
    except FetchFailed as exc:
        if reader is None:
            return {**base, "ok": False, "problem": f"couldn’t be read ({exc})"}, None
        try:
            page = reader.read(url)
        except (FetchBlocked, FetchFailed, ReaderRejected, ReaderRateLimited) as exc2:
            return {**base, "ok": False, "problem": f"couldn’t be read ({exc}; public page reader: {exc2})"}, None
        res, title, text, final, via = page.fetch, page.title.strip(), page_top(page.markdown), page.url_source, "public_reader"
    if not in_property(final, url):
        problem = f"the page moved to {final}, outside this property"
    else:
        problem = identity_problem(title, text, final, name, city, state, zip_)
    host = urlsplit(url).hostname or card["site"]
    shown = re.sub(r"\s+", " ", title)[:110] or host
    return {**base, "ok": problem is None, "problem": problem, "final_url": final, "title": title[:200], "read_via": via,
            "display_name": f"{shown} · {host}" if shown != host else host,
            "retrieved_at": res.retrieved_at, "sha256": res.sha256}, res


# ------------------------------------------------------------------ recovery from web-search evidence
MAX_RECOVERY = 3
# Never crawled during recovery: sign-in, application, resident portals, payments, policies, tours, contact forms.
_NO_CRAWL = re.compile(
    r"(?i)/(?:log-?in|sign-?in|sign-?up|register|apply|application|applicants?|portal|residents?|account|my-account|"
    r"payments?|pay|policy|policies|privacy|terms|legal|careers|jobs|cookies?|contact(?:-us)?|schedule|tours?|book)"
    r"(?:[/?#._-]|$)|[?&](?:login|redirect|return_?url|token|session)=|//(?:portal|login|account|residents?|my|pay)\.")
_PLAN_WORDS = re.compile(r"(?i)floor\s*-?\s*plans?|floorplans?|\blayouts?\b|studio|\d\s*-?\s*bed|\b[s\d]x\d\b|/fp[/_-]")


def recovery_candidates(evidence: list[dict], site_url: str, tried: set[str], building_name: str = "") -> list[dict]:
    """Bounded alternative URLs, ONLY from stored web-search evidence for the CURRENT search (search sources /
    citations; never model prose, never guessed paths or CDNs), scoped to the chosen building:
    - pages on the same site AND inside the chosen page's property path (so another building on an operator's or
      aggregator's domain is never crawled), or same-site pages whose URL/title name the building;
    - images the search cited as floor plans whose URL/title/citation name the building (or sit in its path).
    Listing sites, sign-in, application, portal, policy and similar pages are never included."""
    from .research import file_kind, public_url_ok

    sel_base = property_path_base(site_url)
    toks = _name_tokens(building_name)
    out: list[dict] = []
    for r in evidence:
        url = r.get("url")
        if not isinstance(url, str) or url.rstrip("/") in tried or not url.startswith("https://") or not public_url_ok(url):
            continue
        if r.get("low_relevance") or _NO_CRAWL.search(url) or registrable(urlsplit(url).hostname or "") in _LISTING_SITES:
            continue
        kind = r.get("file_kind") or file_kind(url)
        text = f"{url} {r.get('title', '')} {r.get('cited_text', '')}"
        named = bool(toks) and all(t in text.lower() for t in toks)
        same = same_site(url, site_url)
        in_path = same and _within(sel_base, property_path_base(url))
        if kind == "page" and (in_path or (same and named)):
            out.append({"url": url, "kind": "page", "why": "same building’s website, found by your web search"})
        elif (kind == "image" and "citation" in (r.get("evidence") or []) and (named or in_path)
              and _PLAN_WORDS.search(text) and not _PHOTO_WORDS.search(text)):
            out.append({"url": url, "kind": "image", "why": "image your web search cited as this building’s floor plan"})
        tried.add(url.rstrip("/"))
    # Plan-looking pages first, then images; keep evidence order otherwise.
    out.sort(key=lambda c: (c["kind"] != "page" or not _PLAN_WORDS.search(c["url"]), c["kind"] == "image"))
    return out[:MAX_RECOVERY]


def recover(fetcher: SafeFetcher, d: Discovery, evidence: list[dict], site_url: str, building_name: str = "") -> None:
    """Try the scoped alternatives (see `recovery_candidates`), each through the SafeFetcher; outcomes recorded."""
    tried = {p.url.rstrip("/") for p in d.pages} | {p.fetch.final_url.rstrip("/") for p in d.pages if p.fetch}
    for c in recovery_candidates(evidence, site_url, tried, building_name):
        if c["kind"] == "page":
            sub = _discover_live(fetcher, c["url"], max_follow=1)
            for rec in sub.pages:
                rec.via = "recovery"
            d.pages.extend(sub.pages)
            new = [{**im, "via": "recovery"} for im in sub.plan_images if all(im["url"] != x["url"] for x in d.plan_images)]
            d.plan_images.extend(new)
            d.plan_pdfs = list(dict.fromkeys(d.plan_pdfs + sub.plan_pdfs))[:10]
            for n in sub.plan_names:
                if n.lower() not in (x.lower() for x in d.plan_names) and len(d.plan_names) < 30:
                    d.plan_names.append(n)
            ok = sub.pages[0].status == "ok"
            d.recovery.append({**c, "status": sub.pages[0].status, "found": len(new) + len(sub.plan_pdfs),
                               "detail": "" if ok else sub.pages[0].detail[:200]})
        else:
            try:
                res = fetch_plan_image(fetcher, c["url"])
            except (FetchBlocked, FetchFailed) as exc:
                d.recovery.append({**c, "status": "failed", "found": 0, "detail": str(exc)[:200]})
                continue
            if res.content_type not in IMAGE_TYPES:
                d.recovery.append({**c, "status": "not_an_image", "found": 0, "detail": res.content_type})
                continue
            d.plan_images.append({"url": res.final_url, "alt": "", "found_on": "web search citation", "found_at": res.retrieved_at,
                                  "kind": "recovered_image", "image_sha256": res.sha256, "via": "recovery",
                                  "label": "Image cited by web search; fetched just now and it is an image. Check that it is a floor plan."})
            d.recovery.append({**c, "status": "ok", "found": 1, "detail": ""})
    if d.recovery:
        found = sum(r["found"] for r in d.recovery)
        d.notes.append(f"The first website gave no plans, so {len(d.recovery)} other public page(s) or image(s) from your web "
                       f"search were tried: {found} plan candidate(s) found." + ("" if found else " Upload your own plan instead."))


# ------------------------------------------------------------------ public page reader fallback (see reader.py)
_STALE_FAILURE_NOTES = ("No property evidence retrieved", "No floor-plan image or PDF links were found in server-rendered HTML")


def page_top(markdown: str, limit: int = 20_000) -> str:
    """The main part of a reader page: before any "similar/nearby properties" section, capped. Identity checks use
    only this, so a related-properties footer that mentions the building can't vouch for a page."""
    from .reader import _OTHER_PROPS

    m = _OTHER_PROPS.search(markdown[:limit])
    return markdown[: m.start()] if m else markdown[:limit]


def in_property(url: str, start_url: str) -> bool:
    """`url` is on the same site AND inside the chosen page's property path (an operator's other buildings are not;
    a chosen homepage or own /floorplans page covers its whole site)."""
    return same_site(url, start_url) and _within(property_path_base(start_url), property_path_base(url))


def _read_pages(reader, d: Discovery, start_url: str, check, via: str) -> list[dict]:
    """Read `start_url` (then at most two floor-plan links observed in its reader text, only if it had no plans)
    through the reader. `check(page) -> problem | None` validates identity; the reader's "URL Source" and followed
    links must stay inside the chosen property's path. Returns the new plan images (variants merged). Every attempt
    is recorded in d.pages with via=`via`."""
    from .reader import (MAX_READER_PAGES, MAX_READER_PLANS, READER_METHOD, ReaderRateLimited, ReaderRejected, plan_links,
                         reader_plans)

    queue, seen, reads, found = [start_url], {start_url.split("#")[0].rstrip("/")}, 0, []
    while queue and reads < MAX_READER_PAGES:
        target = queue.pop(0)
        reads += 1
        try:
            page = reader.read(target)
        except ReaderRateLimited as exc:
            d.pages.append(PageRecord(target, "rate_limited", f"public page reader: {exc}", via=via))
            break
        except FetchBlocked as exc:
            d.pages.append(PageRecord(target, "blocked_by_policy", f"not sent to the public page reader: {exc}", via=via))
            continue
        except (FetchFailed, ReaderRejected) as exc:
            d.pages.append(PageRecord(target, "failed", f"public page reader: {exc}", via=via))
            if reads == 1:
                break  # the reader can't read this site's page: don't keep asking it
            continue
        problem = (None if in_property(page.url_source, start_url) else
                   f"its copy is of {page.url_source}, a different property’s page than the one chosen") or check(page)
        if problem:
            d.pages.append(PageRecord(target, "rejected", f"public page reader: {problem}", fetch=page.fetch, via=via,
                                      reader=page.meta()))
            continue
        imgs, links, unsupported = reader_plans(page.markdown, page.url_source)
        d.pages.append(PageRecord(target, "ok", fetch=page.fetch, via=via, reader=page.meta()))
        for u in unsupported:
            if all(u["url"] != x["url"] for x in d.unsupported_plans) and len(d.unsupported_plans) < 40:
                d.unsupported_plans.append({**u, "found_on": page.url_source})
        new = [{**im, "via": via, "found_at": page.fetch.retrieved_at, "method": READER_METHOD,
                "published_time": page.published_time}
               for im in imgs if all(im["url"] != x["url"] for x in d.plan_images + found)]
        found.extend(new)
        if new:
            break
        if reads == 1:
            queue = plan_links(links, page.url_source, seen, reader.resolver, in_scope=lambda u: in_property(u, start_url))
    return merge_style_variants(found)[:MAX_READER_PLANS]


def read_via_reader(reader, d: Discovery, start_url: str, building_name: str = "") -> None:
    """The building's own public page through the public reader (bounded; see reader.py). When a building name is
    known, the reader's copy must name it (so a different property's page is never used)."""
    from .reader import READER_NAME

    phrases = name_phrases(building_name)

    def check(page):
        if phrases and not _has_phrase(phrases, f"{page.title} {page_top(page.markdown)}"):
            return "its copy of the page doesn’t name your building (outside any related-properties section)"
        return None
    first = d.pages[0] if d.pages else None
    new = _read_pages(reader, d, start_url, check, "reader")
    host = urlsplit(start_url).hostname or start_url
    why = (f"{host} refused automated reading" if first and first.status == "blocked_by_site"
           else f"{host} gave no plan images we could read directly (many sites load plans with scripts)")
    if new:
        d.plan_images.extend(new)
        d.notes = [n for n in d.notes if not n.startswith(_STALE_FAILURE_NOTES)]
        page = next(p for p in reversed(d.pages) if p.via == "reader" and p.status == "ok")
        pt = (page.reader or {}).get("published_time")
        d.notes.insert(0, f"{why}, so the same public page was read through {READER_NAME}: {len(new)} published floor "
                          f"plan{'' if len(new) == 1 else 's'} found on {page.reader['url_source']}. The reader is an outside "
                          "service that fetches public pages; whether its copy was fresh or cached is unknown"
                          + (f" (it reports the page time as {pt})" if pt else "") + ". Plan names come from the page’s "
                          "own plan headings. Sample plans; pick one only if it is your layout.")
    elif any(p.via == "reader" for p in d.pages):
        last = next(p for p in reversed(d.pages) if p.via == "reader")
        d.notes.append(f"{why}; a public page reader was also tried and found no plans it can import"
                       + (f" ({last.detail[:160]})." if last.detail else "."))
    _note_unsupported(d)


# ------------------------------------------------------------------ listing-site alternatives (explicit user choice)
# Established property-listing sites. Their pages are third-party sources ABOUT a building, never its official site.
_PROPERTY_LISTINGS = {
    "apartments.com", "zillow.com", "trulia.com", "realtor.com", "hotpads.com", "redfin.com", "padmapper.com", "zumper.com",
    "apartmentlist.com", "rent.com", "forrent.com", "apartmentfinder.com", "apartmentguide.com", "rentals.com",
    "streeteasy.com", "rentcafe.com", "apartmenthomeliving.com", "homes.com", "point2homes.com",
}
MAX_ALTERNATIVES = 2


_STREET_TYPES = {"street": "st", "avenue": "ave", "road": "rd", "boulevard": "blvd", "drive": "dr", "lane": "ln",
                 "place": "pl", "terrace": "ter", "parkway": "pkwy", "highway": "hwy"}


def _canon(t: str) -> str:
    return _STREET_TYPES.get(t, t)


def name_phrases(name: str) -> list[list[str]]:
    """The building name as word phrases to look for, generic words ("the", "apartments") ignored and street types
    abbreviated ("Street" = "St"). A 3+ word name ending in a street type may also appear without it ("360 State
    Street" -> "360 State"), the common official short form; "360 Market Square" never matches "360 State"."""
    full = [_canon(t) for t in _name_tokens(name)]
    if not full:
        return []
    out = [full]
    if len(full) >= 3 and full[-1] in _STREET_TYPES.values():
        out.append(full[:-1])
    return out


def _has_phrase(phrases: list[list[str]], text: str) -> bool:
    """One of `phrases` appears as consecutive words (generic words skipped; a cautious typo allowed per word)."""
    words = [_canon(w) for w in _tokens(text) if w not in _GENERIC]
    for ph in phrases:
        n = len(ph)
        for i in range(len(words) - n + 1):
            if words[i] == ph[0] or close_token(ph[0], words[i]):
                if all(words[i + j] == a or close_token(a, words[i + j]) for j, a in enumerate(ph)):
                    return True
    return False


def domain_names_building(host: str, name: str) -> bool:
    """The site's own domain name spells the building's name ("360statestreet.com" for "360 State Street",
    "maplecourt-apts.com" for "Maple Court"). Only such domains get their page checked from a hostname-only lead."""
    label = registrable(host or "").split(".")[0].replace("-", "")
    for ph in name_phrases(name):
        joined = "".join(ph)
        raw = "".join(_name_tokens(name)) if ph is name_phrases(name)[0] else joined
        if (len(joined) >= 5 and joined in label) or (len(raw) >= 5 and raw in label):
            return True
    return False


def _words(s: str) -> str:
    return " " + " ".join(_tokens(s)) + " "


def identity_problem(title: str, text: str, url: str, name: str, city: str, state: str, zip_: str) -> str | None:
    """None when a page is about THIS building: it names every word of the building's name AND the user's city or
    ZIP, and its title/address doesn't name a different state. Same-name buildings elsewhere are refused."""
    phrases = name_phrases(name)
    if not phrases:
        return "no building name to check the page against"
    if not _has_phrase(phrases, f"{url} {title} {text[:20_000]}"):
        return f"it doesn’t name {name}"
    near = _words(f"{url} {title} {text[:6_000]}")
    if not ((zip_.strip() and f" {zip_.strip()[:5]} " in near) or (city.strip() and _words(city) in near)):
        return f"it doesn’t mention {city or zip_}, so it may be a same-name building elsewhere"
    code = _state_code(state) if state.strip() else ""
    if code in US_STATES:
        for m in re.finditer(r"(?:,|\s-)\s*([A-Z]{2})\b", f"{title} {url.replace('-', ' ')}"):
            other = m.group(1).lower()
            if other in US_STATES and other != code:
                return f"it names another state ({m.group(1)})"
    return None


def listing_alternatives(evidence: list[dict], name: str, city: str, state: str, zip_: str) -> list[dict]:
    """At most two listing-site pages from the CURRENT search's evidence whose own URL/title/citation name the building
    and its city or ZIP. Offered for the user to choose; nothing is fetched here."""
    from .research import file_kind, public_url_ok

    out: list[dict] = []
    for r in evidence or []:
        url = r.get("url")
        if not isinstance(url, str) or not url.startswith("https://") or not public_url_ok(url) or r.get("low_relevance"):
            continue
        reg = registrable(urlsplit(url).hostname or "")
        if reg not in _PROPERTY_LISTINGS or _NO_CRAWL.search(url) or (r.get("file_kind") or file_kind(url)) != "page":
            continue
        if any(a["url"] == url for a in out):
            continue
        if identity_problem(r.get("title") or "", r.get("cited_text") or "", url, name, city, state, zip_) is None:
            out.append({"url": url, "site": reg, "title": (r.get("title") or reg)[:160],
                        "why": f"Listing page on {reg} from your web search that names {name} and {city or zip_}. It is a "
                               "third-party listing site, not the building’s own website."})
        if len(out) >= MAX_ALTERNATIVES:
            break
    return out


def read_alternative(fetcher: SafeFetcher, reader, url: str, name: str, city: str, state: str, zip_: str) -> Discovery:
    """The user's explicit choice of ONE listing-site page: direct SafeFetcher read first, then (if it gives no plans
    and isn't policy-blocked) the public page reader. The page must name the building and its city/ZIP; plans from it
    are labelled as coming from that third-party site."""
    from .html_extract import decode_html as _dec

    reg = registrable(urlsplit(url).hostname or "")
    sub = _discover_live(fetcher, url, max_follow=0)
    for rec in sub.pages:
        rec.via = "third_party"
    sub.notes = []
    first = sub.pages[0]
    if first.status == "ok":
        ev = extract(_dec(first.fetch.body), first.fetch.final_url)
        problem = identity_problem(ev.title or "", ev.text or "", first.fetch.final_url, name, city, state, zip_)
        if problem:
            first.status, first.detail = "rejected", problem
            sub.plan_images, sub.plan_pdfs = [], []
    sub.plan_images = [{**im, "via": "third_party"} for im in sub.plan_images if im["kind"] in _STRONG]
    if not sub.plan_images and first.status != "blocked_by_policy" and reader is not None:
        def check(page):
            return identity_problem(page.title, page.markdown, page.url_source, name, city, state, zip_)
        sub.plan_images = _read_pages(reader, sub, url, check, "third_party")
    for im in sub.plan_images:
        im["site"] = reg
        im["label"] = f"From {reg}, a listing site (not the building’s own website). " + (im.get("label") or "")
    n = len(sub.plan_images)
    sub.notes.append(f"You chose to read a listing page on {reg}: {n} plan{'' if n == 1 else 's'} found. Third-party "
                     "listing plans can be outdated or belong to a different unit; pick one only if it is your layout."
                     if n else f"The listing page on {reg} gave no plans we could use"
                     + (f" ({sub.pages[-1].detail[:160]})." if sub.pages[-1].detail else "."))
    return sub


# ------------------------------------------------------------------ plan gallery
def _image_name(url: str) -> str:
    from .reader import _file_stem

    stem = _file_stem(url)
    return "" if re.fullmatch(r"[\d._-]*|image|img", stem, re.I) or len(stem) > 60 else stem.replace("_", " ").replace("-", " ")


def gallery(d: Discovery, reference: dict | None) -> list[dict]:
    """Every plan choice the user can import, newest evidence first: live finds, recovered finds, then the checked
    directory (if any). Dates say when each was seen. Nothing is pre-selected."""
    items: list[dict] = []
    seen: set[str] = set()
    origins = {"recovery": "recovered", "reader": "reader", "third_party": "third_party"}
    for im in d.plan_images:
        if im["url"] in seen:
            continue
        name = im.get("name") or im.get("alt") or _image_name(im["url"]) or "Untitled plan image"
        item = {"url": im["url"], "name": name[:120], "alt": im.get("alt", ""), "origin": origins.get(im.get("via"), "live"),
                "found_on": im.get("found_on"), "seen_at": im.get("found_at"), "label": im.get("label"),
                # The nearest plan heading names the type when it says one; the image's alt text is only a fallback.
                "plan_type": (plan_type(im.get("heading")) or plan_type(im.get("alt"), _image_name(im["url"]))
                              or plan_type(im.get("type_hint")))}
        for k in ("heading", "method", "site", "evidence_source_id", "published_time", "variants", "type_hint"):
            if im.get(k):
                item[k] = im[k]
        items.append(item)
        seen.add(im["url"])
    for p in (reference or {}).get("plans", []):
        if p["url"] in seen:
            continue
        items.append({"url": p["url"], "name": p["name"], "alt": p.get("alt", ""), "origin": "checked_reference",
                      "found_on": reference["source_page"], "seen_at": reference["observed_at"],
                      "label": "Published plan type from a checked official list (not every unit variant; not a current vacancy)",
                      "plan_type": plan_type(p["name"], p.get("alt"))})
    return items


def fetch_plan_image(fetcher: SafeFetcher, url: str) -> FetchResult:
    return fetcher.fetch(url, allowed_types=IMAGE_TYPES + PDF_TYPES, max_bytes=12_000_000)


FIRST_PARTY_RETAILERS = ("IKEA US", "Target")


def import_listing(fetcher: SafeFetcher, url: str, category: str, declared_condition: str, stores: list[str] | None = None,
                   resale: list[str] | None = None) -> tuple[dict | None, FetchResult | None, str]:
    """Fetch ONE product page from an approved furniture source and build an evidence-backed snapshot.

    New items: only pages on the approved stores (Amazon US, Article, IKEA, Target; `stores` narrows them); first-party
    store pages are always recorded as new. "secondhand": the page must be an individual listing on an approved resale
    marketplace AND state used/pre-owned condition for its own item (`import_used_listing`); a user's declaration alone
    is no longer accepted. Any other website is refused before a request; every redirect hop is checked first."""
    # Furniture source boundary (user direction: no unknown or risky websites). A secondhand import must pass the same
    # approved-marketplace and used-evidence check as the automatic secondhand search; a new item must be on an
    # established store. Anything else is refused BEFORE any network access, and every redirect hop is checked.
    from .resale import furniture_guard, product_source
    if declared_condition == "secondhand":
        snap, res, outcome = import_used_listing(fetcher, url, category, resale)
        if snap is None:
            return None, None, outcome
        return snap, res, ("ok" if outcome in ("verified", "incomplete") else outcome)
    if product_source(url, "new", stores) is None:
        return None, None, ("not a product page on an approved store (Amazon, Article, IKEA or Target); other websites "
                            "aren’t read")
    try:
        res = fetcher.fetch(url, allowed_types=_HTML, max_bytes=4_000_000, url_guard=furniture_guard("new", stores))
    except (FetchBlocked, FetchFailed) as exc:
        return None, None, str(exc)
    facts = adapter_for(res.final_url)(res.final_url, res.body)
    first_party = facts.retailer in FIRST_PARTY_RETAILERS
    warning = "ok"
    if first_party:
        condition, evidence, verified = "new", "First-party retailer product page (new merchandise)", True
        if declared_condition == "secondhand":
            warning = (f"{facts.retailer} product pages sell new items, so this was imported as NEW, not secondhand. "
                       "For used furniture, import the secondhand listing's own page.")
    else:
        condition, evidence, verified = declared_condition, "Declared by you when importing; not verified", False
    snap = snapshot_from_facts(facts, category, res.sha256, res.retrieved_at, curator_tags=[],
                               condition=condition, condition_evidence=evidence, origin="user_import")
    snap["condition_verified"] = verified
    snap["id"] = "imp-" + res.sha256[:12]
    return snap, res, warning


# ------------------------------------------------------------------ automated USED-listing check (page evidence only)
USED_CHECK_VERSION = "used-check-v2-primary"
_RELATED_MARKER = re.compile(r"(?im)^\s*(you may also like|related\b|similar (items|listings|products)|"
                             r"more from this seller|recently viewed|people also (viewed|bought)|customers also|"
                             r"sponsored|more like this|other items|explore more)\b")
_COND_LINE = re.compile(r"(?im)^\s*(?:item\s+)?condition\s*[:\-–]\s*(.{1,80})$")
# A condition VALUE is judged by how it starts ("New…" / "Pre-owned, light wear"), so text that runs on after it
# (e.g. a footer glued to the line) can't change it.
_NEW_WORDS = re.compile(r"(?i)^\s*(brand[- ]new|new|unused|never used)")
_USED_WORDS = re.compile(r"(?i)^\s*(used|pre-?owned|previously owned|second-?hand|gently used)")
_SOLD_LINE = re.compile(r"(?im)^\s*(this item (?:has been|is|was) sold|sold|sold out|no longer available|"
                        r"listing (?:has )?ended|this listing is (?:closed|no longer available))\.?\s*$")
_SET_WORDS = re.compile(r"(?i)\b(set of|pair of|sets?\b|bundle|lot of|\d+\s*-?\s*(?:pc|pcs|piece)s?\b|with \d+ chairs|and \d+ chairs)")
# Words that name each type in a listing title (longest phrases are matched first so "sofa bed" isn't a "bed").
CATEGORY_WORDS = {
    "bed_frame": ["bed frame", "platform bed", "bed"], "mattress": ["mattress"], "sofa_bed": ["sofa bed", "sleeper sofa", "futon"],
    "daybed": ["daybed", "day bed"], "sofa": ["sofa", "couch", "loveseat"], "desk": ["desk"], "desk_chair": ["desk chair", "office chair", "task chair"],
    "dresser": ["dresser", "chest of drawers"], "nightstand": ["nightstand", "night stand", "bedside table", "night table"],
    "wardrobe": ["wardrobe", "armoire"], "bookcase": ["bookcase", "bookshelf"], "coffee_table": ["coffee table"],
    "tv": ["television", "smart tv", "tv"], "tv_stand": ["tv stand", "media console", "tv console", "entertainment center", "media stand"],
    "dining_table": ["dining table", "kitchen table"], "dining_chair": ["dining chair", "kitchen chair"],
    "armchair": ["armchair", "accent chair", "lounge chair", "club chair"], "side_table": ["side table", "end table"],
    "ottoman": ["ottoman", "pouf"], "console_table": ["console table", "sofa table", "entryway table"],
    "shoe_storage": ["shoe rack", "shoe cabinet", "shoe storage", "storage bench", "entryway bench"], "floor_lamp": ["floor lamp"],
}


def _norm_url(u: str) -> str:
    sp = urlsplit(u or "")
    return (sp.hostname or "").lower().removeprefix("www.") + sp.path.rstrip("/").lower()


def _canonicals(html: str, ev, url: str) -> set[str]:
    out = {_norm_url(url)}
    for m in re.finditer(r"""<link[^>]+rel=["']canonical["'][^>]*href=["']([^"']+)["']""", html, re.I):
        out.add(_norm_url(m.group(1)))
    if ev.meta.get("og:url"):
        out.add(_norm_url(ev.meta["og:url"]))
    return out


# Explicit challenge markers (AWS WAF, Anubis proof-of-work, "verify you're not a robot" ...). A bare "captcha" word is
# NOT enough: normal listing pages ship reCAPTCHA settings for their login and checkout forms (seen on Chairish).
_ROBOT = re.compile(r"(?i)verify (?:that )?you(?:'|’)?re not a robot|verify you are (?:a )?human|challenge-container|"
                    r"are you a robot|checking your browser|enable javascript and (?:cookies|then reload)|"
                    r"awsWafCookieDomainList|AwsWafIntegration|gokuProps|not a bot|\banubis\b|proof[- ]of[- ]work")


def robot_check(status: int, html: str) -> bool:
    """A bot-challenge or script-only shell served instead of the page (e.g. HTTP 202 + "verify you're not a robot").
    Such pages are never "read past"; the listing simply couldn't be checked. A page that carries product data is a
    real page, and a CAPTCHA mention counts only on a small page without any (a challenge shell)."""
    head = html[:20_000]
    if _ROBOT.search(head):
        return True
    small = len(html) < 30_000 and "ld+json" not in html
    return small and (status == 202 or bool(re.search(r"(?i)captcha", head)))


def primary_product(html: str, ev, url: str) -> tuple[dict | None, str]:
    """The page's OWN product (not related/recommended ones): the JSON-LD Product whose url/@id is this page (or its
    canonical/og:url); or the only Product on the page if it doesn't point elsewhere. Several products with no match:
    None (we abstain rather than guess)."""
    prods = find_products(ev)
    if not prods:
        return None, "no structured product on the page"
    targets = _canonicals(html, ev, url)
    match = [p for p in prods if _norm_url(str(p.get("url") or p.get("@id") or "")) in targets]
    if len(match) == 1:
        return match[0], "the product whose URL is this page"
    from .resale import listing_id
    own = listing_id(url)
    if own and not match:  # same marketplace listing id (a changed slug); exactly one, never "the first"
        same = [p for p in prods if listing_id(str(p.get("url") or p.get("@id") or "")) == own]
        if len(same) == 1:
            return same[0], "the product with this listing’s own id"
    if len(prods) == 1:
        own = str(prods[0].get("url") or prods[0].get("@id") or "")
        if not own or _norm_url(own) in targets or not own.startswith("http"):
            return prods[0], "the only product on the page"
    return None, "several products on the page and none is clearly this listing"


def _main_text(ev) -> str:
    """Page text before any related/recommended section (sitewide footers usually follow those too)."""
    t = ev.text or ""
    m = _RELATED_MARKER.search(t)
    return t[: m.start()] if m else t


def _offers(prod: dict) -> list[dict]:
    o = prod.get("offers")
    return [x for x in (o if isinstance(o, list) else [o]) if isinstance(x, dict)]


def _condition(prod: dict | None, main: str) -> tuple[str | None, str]:
    conds = [str(o.get("itemCondition") or "") for o in _offers(prod or {})] + [str((prod or {}).get("itemCondition") or "")]
    conds = [c for c in conds if c]
    if any("NewCondition" in c for c in conds):
        return "new", f'JSON-LD itemCondition = "{next(c for c in conds if "NewCondition" in c)}"'
    if any("UsedCondition" in c for c in conds):
        return "used", f'JSON-LD itemCondition = "{next(c for c in conds if "UsedCondition" in c)}"'
    if any("Refurbished" in c or "Damaged" in c for c in conds):
        return None, "the listing is refurbished or damaged, not plain used"
    lines = [m.group(1).strip() for m in _COND_LINE.finditer(main)]
    if any(_NEW_WORDS.search(v) and not _USED_WORDS.search(v) for v in lines):
        return "new", f'Item detail "Condition: {lines[0]}"'
    used = [v for v in lines if _USED_WORDS.search(v)]
    if used:
        return "used", f'Item detail "Condition: {used[0]}"'
    if lines:
        return None, f'the condition shown ("{lines[0]}") doesn’t say used or pre-owned'
    return None, "the page doesn’t state a used or pre-owned condition"


def used_condition_evidence(body: bytes, url: str) -> tuple[str | None, str]:
    """("used"|"new"|None, evidence or reason) for the page's PRIMARY item only (see `primary_product`)."""
    html = decode_html(body)
    ev = extract(html, url)
    prod, _ = primary_product(html, ev, url)
    if prod is None and find_products(ev):
        return None, "several products on the page and none is clearly this listing"
    return _condition(prod, _main_text(ev))


def _category_matches(name: str, category: str) -> tuple[bool, str]:
    t = " " + re.sub(r"[^a-z0-9]+", " ", (name or "").lower()) + " "
    if _SET_WORDS.search(name or ""):
        return False, "it’s a set, pair or bundle, not one piece"
    found = set()
    for cat, words in sorted(CATEGORY_WORDS.items(), key=lambda kv: -max(len(w) for w in kv[1])):
        for w in sorted(words, key=len, reverse=True):
            if f" {w} " in t:
                found.add(cat)
                t = t.replace(f" {w} ", " ")
    if category not in found:
        return False, f"its title doesn’t say it’s a {category.replace('_', ' ')}"
    others = found - {category} - {"bed_frame"} if category in ("nightstand", "mattress") else found - {category}
    if others:
        return False, f"its title names other furniture too ({', '.join(sorted(o.replace('_', ' ') for o in others))})"
    return True, ""


def _qv_inches(v) -> float | None:
    if isinstance(v, dict):
        num, unit = v.get("value"), str(v.get("unitCode") or v.get("unitText") or "").lower()
    else:
        num, unit = v, ""
    try:
        x = float(num)
    except (TypeError, ValueError):
        return None
    if unit in ("cmt", "cm", "centimeter", "centimeters"):
        return round(x / 2.54, 3)
    if unit in ("inh", "in", "inch", "inches", ""):
        return x if unit else None  # a bare number has no unit: unknown
    return None


# ------------------------------------------------------------------ public page reader copy of ONE approved listing
# Marketplaces whose individual listing pages may be read through the public page reader (the same anonymous
# page-to-text route used for property pages) when the direct fetch only gets a robot check. Never a bypass: the
# reader's own challenge pages are rejected, nothing is solved, retried with other headers or proxied.
READER_RESALE_SITES = {"aptdeco"}
_PRICE_LINE = re.compile(r"^\$([\d,]+(?:\.\d{2})?)(?:\$[\d,]+(?:\.\d{2})?)?\s*$")
_UNTIL = re.compile(r"(?i)until\s+(\d{1,2})/(\d{1,2})/(\d{4})")
_DIMS = re.compile(r"(?i)^overall dimensions:\s*width:\s*([\d.]+)\s*in(?:ches)?\s*,\s*height:\s*([\d.]+)\s*in(?:ches)?\s*,"
                   r"\s*depth:\s*([\d.]+)\s*in(?:ches)?")


def parse_aptdeco_copy(md: str, today=None) -> dict | None:
    """Deterministic reading of an AptDeco listing's public page copy: ONLY the listing's own heading block (title,
    price, sold/expired) and its own "Product details" section (condition, overall dimensions) plus its availability
    line. Related/recommended cards (which come BEFORE the details on these pages, with their own prices) are never
    read. Returns None when the page has no clear single listing section."""
    from datetime import date

    today = today or date.today()
    lines = [x.strip() for x in md.splitlines()]
    try:
        pd = lines.index("### Product details")
    except ValueError:
        return None
    # The listing's own heading is a level 1-3 heading before its details (active listings use "# Title", sold ones
    # "### Title"); there must be exactly one, or we abstain. Level-4+ lines are delivery/pickup notes, not headings.
    heads = [i for i in range(pd) if re.match(r"^#{1,3} \S", lines[i]) and lines[i] != "### Product details"]
    if len(heads) != 1:
        return None
    h = heads[0]
    stop = next((i for i in range(h + 1, pd) if lines[i].startswith("#") or lines[i] in ("Shop similar items", "Have a similar item?")
                 or lines[i].startswith("Have a similar item?")), pd)
    region = lines[h + 1:stop]
    price = None
    for x in region:
        if "retail" in x.lower() or "off delivery" in x.lower():
            continue
        m = _PRICE_LINE.match(x)
        if m:
            price = m.group(1).replace(",", "")
            break
    sold = any(re.fullmatch(r"(?i)sold(?:\s*/\s*expired)?|expired", x) for x in region)
    end = next((i for i in range(pd + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    details = lines[pd + 1:end]
    cond = next((re.sub(r"(?i)^condition:\s*", "", x) for x in details if x.lower().startswith("condition:")), None)
    dims = next((_DIMS.match(x) for x in details if _DIMS.match(x)), None)
    avail = next((x for x in lines[pd + 1:] if x.lower().startswith("availability:")), None)
    until = None
    if avail and _UNTIL.search(avail):
        mo, dd, yy = (int(g) for g in _UNTIL.search(avail).groups())
        try:
            until = date(yy, mo, dd)
        except ValueError:
            until = None
    expired = bool(until and until < today)
    delivery = [re.sub(r"^#+\s*", "", x) for x in lines[h + 1:pd]
                if re.match(r"(?i)^#{4,}\s*.*\b(delivery|pick ?up)\b", x)][:3]
    return {"title": re.sub(r"^#+\s*", "", lines[h]).strip(), "price": price, "sold": sold, "expired": expired, "condition": cond,
            "delivery": delivery,
            "width": float(dims.group(1)) if dims else None, "height": float(dims.group(2)) if dims else None,
            "depth": float(dims.group(3)) if dims else None, "availability": avail, "until": until.isoformat() if until else None}


def read_listing_copy(reader, url: str, category: str, site: str, today=None) -> tuple[dict | None, FetchResult | None, str]:
    """ONE approved listing through the public page reader, under the same evidence gate as a direct check: the copy
    must be of THIS listing (same marketplace listing id; the reader's challenge pages are rejected), its own section
    must state used condition (refurbished/damaged stay distinct), name the requested type, and give price and overall
    size. "Sold / Expired" or a past availability date makes it unavailable. Freshness of the copy is unknown."""
    from .adapters import ExtractedFacts, Fact
    from .reader import ReaderRateLimited, ReaderRejected
    from .resale import RESALE_SITES, listing_id, listing_key

    try:
        page = reader.read(url)
    except ReaderRateLimited:
        return None, None, "couldn’t be read (robot check; the public page reader is busy right now)"
    except (FetchBlocked, FetchFailed, ReaderRejected) as exc:
        return None, None, f"couldn’t be read (robot check; public page reader: {exc})"
    if listing_id(page.url_source) != listing_id(url) or (urlsplit(page.url_source).hostname or "").removeprefix("www.") != \
            (urlsplit(url).hostname or "").removeprefix("www."):
        return None, None, "couldn’t be read (the public page reader returned a different page than this listing)"
    f = parse_aptdeco_copy(page.markdown, today)
    if f is None:
        return None, page.fetch, "the page copy has no single clear listing section"
    cond = f["condition"] or ""
    if re.search(r"(?i)refurbished|damaged|for parts", cond):
        return None, page.fetch, "the listing is refurbished or damaged, not plain used"
    if not _USED_WORDS.search(cond):
        return None, page.fetch, "the page doesn’t state a used or pre-owned condition"
    ok, reason = _category_matches(f["title"], category)
    if not ok:
        return None, page.fetch, reason
    facts = ExtractedFacts(retailer=RESALE_SITES[site][0], url=url)
    facts.name = Fact(f["title"][:160], "Listing heading (public page reader copy)")
    if f["price"]:
        facts.price_usd = Fact(f["price"], f'Listing price "${f["price"]}" under its own heading (public page reader copy)')
    if f["width"] and f["depth"]:
        snippet = f'Overall Dimensions: Width {f["width"]:g} in, Height {f["height"]:g} in, Depth {f["depth"]:g} in'
        facts.width_in, facts.depth_in = Fact(f["width"], snippet), Fact(f["depth"], snippet)
        facts.height_in = Fact(f["height"], snippet) if f["height"] else None
    snap = snapshot_from_facts(facts, category, page.fetch.sha256, page.fetch.retrieved_at, curator_tags=[],
                               condition="secondhand", condition_evidence=f'Item detail "Condition: {cond[:80]}" (public page reader copy)',
                               origin="used_listing_check")
    snap.update(condition_verified=True, resale_site=site, listing_key=listing_key(url), image_url=None,
                id="imp-" + page.fetch.sha256[:12], read_via="public_reader", reader=page.meta(),
                availability_text=f["availability"], freshness="unknown (public page reader copy)",
                delivery_text=f["delivery"] or None)  # as stated on the listing; not verified
    if f["sold"] or f["expired"]:
        snap["availability"] = "SoldOut"
        snap["sold_evidence"] = ("Listing shows “Sold / Expired”" if f["sold"] else f'Availability ended {f["until"]}')
        return snap, page.fetch, "sold or no longer available"
    return snap, page.fetch, "verified" if snap["status"] == "verified" else "incomplete"


def import_used_listing(fetcher: SafeFetcher, url: str, category: str, allowed_sites: list[str] | None = None,
                        reader=None, today=None) -> tuple[dict | None, FetchResult | None, str]:
    """Automated check of ONE secondhand lead on an APPROVED resale marketplace. Every redirect hop is checked against
    the approved sites before connecting. All facts come from the page's primary item: its condition must be stated as
    used/pre-owned, its title must name the requested type (no sets/bundles), and price, size and availability are read
    from that same item. Sold/unavailable listings are kept as evidence but can't be chosen."""
    from .adapters import ExtractedFacts, Fact
    from .resale import RESALE_SITES, redirect_guard, resale_site
    site = resale_site(url, allowed_sites)
    if site is None:
        return None, None, "not an individual listing on an approved resale marketplace"
    try:
        res = fetcher.fetch(url, allowed_types=_HTML, max_bytes=4_000_000, url_guard=redirect_guard(allowed_sites))
    except (FetchBlocked, FetchFailed) as exc:
        if re.search(r"HTTP (404|410)\b", str(exc)):
            return None, None, "no longer online (the listing page is gone)"
        return None, None, f"couldn’t be read ({exc})"
    if resale_site(res.final_url, allowed_sites) is None:  # e.g. a sold Chairish listing now redirects to a collection
        return None, None, "no longer online (the listing now redirects to a category or other page)"
    html = decode_html(res.body)
    if robot_check(res.status, html):  # a bot challenge, not the listing: never bypassed, reported as such
        if reader is not None and site in READER_RESALE_SITES:
            return read_listing_copy(reader, url, category, site, today)
        return None, None, f"couldn’t be read (the marketplace showed a robot check instead of the listing, HTTP {res.status})"
    ev = extract(html, res.final_url)
    prod, why = primary_product(html, ev, res.final_url)
    main = _main_text(ev)
    verdict, evidence = _condition(prod, main)
    if prod is None and find_products(ev):
        return None, res, why
    if verdict == "new":
        return None, res, "the listing states new condition"
    if verdict != "used":
        return None, res, evidence
    name = str((prod or {}).get("name") or ev.meta.get("og:title") or ev.title or "").strip()
    ok, reason = _category_matches(name, category)
    if not ok:
        return None, res, reason
    facts = ExtractedFacts(retailer=RESALE_SITES[site][0], url=res.final_url)
    facts.name = Fact(name[:160], "Listing title" + (" (JSON-LD Product.name)" if prod else ""))
    if prod:
        price, cur, avail = offer_price(prod)
        if price and (cur or "USD").upper() == "USD":
            facts.price_usd = Fact(price, f'JSON-LD Offer.price = "{price}" {cur or ""}'.strip())
        if avail:
            facts.availability = Fact(avail.rsplit("/", 1)[-1], f'JSON-LD Offer.availability = "{avail}"')
        w, d = _qv_inches(prod.get("width")), _qv_inches(prod.get("depth"))
        if w and d:
            facts.width_in, facts.depth_in = Fact(w, "JSON-LD Product.width"), Fact(d, "JSON-LD Product.depth")
    if facts.width_in is None:  # the listing's own text only (cut before any related section), one size or none
        from .adapters import _WXD_RE, parse_wxd
        hits = {(m.group(1), m.group(3)) for m in _WXD_RE.finditer(main)}
        if len(hits) == 1:  # exactly one size in the listing's own text; several (e.g. related items) = unknown
            w, d, snippet = parse_wxd(main)
            facts.width_in, facts.depth_in = Fact(w, snippet), Fact(d, snippet)
    snap = snapshot_from_facts(facts, category, res.sha256, res.retrieved_at, curator_tags=[], condition="secondhand",
                               condition_evidence=evidence, origin="used_listing_check")
    snap["condition_verified"] = True
    snap["resale_site"] = site
    from .resale import listing_key
    snap["listing_key"] = listing_key(res.final_url) or listing_key(url)
    snap["image_url"] = None  # no remote listing images are auto-loaded
    snap["id"] = "imp-" + res.sha256[:12]
    sold = None
    if snap.get("availability") in ("SoldOut", "OutOfStock", "Discontinued"):
        sold = f"Listed as {snap['availability']}"
    else:
        m = _SOLD_LINE.search(main)
        if m:
            sold = f'Listing text: "{m.group(1)}"'
    if sold:
        snap["availability"] = "SoldOut"
        snap["sold_evidence"] = sold
        return snap, res, "sold or no longer available"
    return snap, res, "verified" if snap["status"] == "verified" else "incomplete"
