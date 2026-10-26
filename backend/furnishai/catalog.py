"""Product snapshots: normalized, evidence-backed furniture facts.

A snapshot is 'verified' only when name, price (USD), overall width and depth all have source
evidence (and sofa beds also have an open footprint). Anything missing stays null and the record
is 'incomplete': shown for discovery, never placed in a verified plan.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .adapters import ExtractedFacts

CATEGORIES = (
    "bed_frame",
    "mattress",
    "sofa_bed",
    "daybed",
    "sofa",
    "desk",
    "desk_chair",
    "dresser",
    "nightstand",
    "wardrobe",
    "bookcase",
    "coffee_table",
    "tv",
    "tv_stand",
    "dining_table",
    "dining_chair",
    "armchair",
    "side_table",
    "ottoman",
    "console_table",
    "shoe_storage",
    "floor_lamp",
)
SLEEP_CATEGORIES = ("bed_frame", "sofa_bed", "daybed")
STALE_AFTER_DAYS = 14

_SIZE_RE = re.compile(r"(?i)\b(twin xl|twin|full|queen|king)\b")


MAX_PRICE_CENTS = 5_000_000  # $50,000: anything larger from page metadata is treated as invalid
_PRICE_TEXT = re.compile(r"^\d{1,6}(\.\d{1,2})?$")


def price_to_cents(price: object) -> int | None:
    """Exact cents from a plain decimal string; None for NaN/Infinity/exponents/negatives/huge values."""
    if price is None or isinstance(price, bool):
        return None
    text = str(price).strip()
    if not _PRICE_TEXT.match(text):
        return None
    try:
        cents = int(Decimal(text) * 100)
    except InvalidOperation:
        return None
    return cents if 0 <= cents <= MAX_PRICE_CENTS else None


def nominal_size(name: str | None) -> str | None:
    m = _SIZE_RE.search(name or "")
    return m.group(1).lower() if m else None


def _includes(facts: ExtractedFacts, category: str) -> dict:
    name = (facts.name.value if facts.name else "") or ""
    low_name = name.lower()
    sentences = [str(f.value).lower() for f in facts.inclusions_text]
    texts = " ".join(sentences)

    def says(subject: str, verdict: str) -> bool:
        # Judge each page sentence on its own: "Mattress … sold separately." + "Slatted bed base is included."
        # must not read as "slatted bed base … sold separately".
        return any(subject in s and re.search(verdict, s) for s in sentences)

    slats = mattress = None
    if category == "bed_frame":
        if ("luröy" in low_name or "luroy" in low_name or "luroey" in low_name or "slatted bed base" in low_name
                or says("slatted bed base", r"\b(?:is|are) included")
                or says("slat", r"^(?!.*\bnot included).*\bincluded")):  # Article: "Wooden slats included"
            slats = True
        elif says("slatted bed base", r"sold separately|not included"):
            slats = False
        if "with mattress" in low_name:
            mattress = True
        elif says("mattress", r"sold separately|not included"):  # "mattress and bedding not included"
            mattress = False
    elif category == "daybed":
        mattress = True if "mattress" in low_name and "with" in low_name else (False if "mattress" in texts and "sold separately" in texts else None)
        slats = True if "slatted bed base is included" in texts else None
    return {"slats": slats, "mattress": mattress}


def snapshot_from_facts(
    facts: ExtractedFacts,
    category: str,
    source_sha256: str,
    retrieved_at: str,
    curator_tags: list[str] | None = None,
    condition: str = "new",
    condition_evidence: str = "First-party retailer product page (new merchandise)",
    origin: str = "curated_catalog",
) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category {category}")
    name = facts.name.value if facts.name else None
    sku = facts.sku.value if facts.sku else None
    digits = re.sub(r"\D", "", str(sku or "")) or source_sha256[:10]
    if facts.retailer == "Amazon" and sku:  # ASINs are alphanumeric: digits alone could collide
        digits = re.sub(r"[^a-z0-9]", "", str(sku).lower())
    pid = f"{re.sub(r'[^a-z0-9]+', '-', facts.retailer.lower()).strip('-')}-{digits}"
    evidence = {}
    for key in ("name", "sku", "price_usd", "availability", "width_in", "depth_in", "height_in", "open_depth_in",
                "bed_surface_in", "mattress_size_text"):
        f = getattr(facts, key)
        if f is not None:
            evidence[key] = f.evidence
    snap = {
        "id": pid,
        "origin": origin,
        "retailer": facts.retailer,
        "url": facts.url,
        "category": category,
        "name": name,
        "variant_sku": sku,
        "nominal_size": nominal_size(name) if category in ("bed_frame", "mattress", "daybed") else None,
        "price_cents": price_to_cents(facts.price_usd.value) if facts.price_usd else None,
        "currency": "USD" if facts.price_usd else None,
        "availability": facts.availability.value if facts.availability else None,
        "condition": condition,
        "condition_evidence": condition_evidence,
        "width_in": facts.width_in.value if facts.width_in else None,
        "depth_in": facts.depth_in.value if facts.depth_in else None,
        "height_in": facts.height_in.value if facts.height_in else None,
        "open_depth_in": facts.open_depth_in.value if facts.open_depth_in else None,
        "bed_surface_in": list(facts.bed_surface_in.value) if facts.bed_surface_in else None,
        "mattress_size_text": facts.mattress_size_text.value if facts.mattress_size_text else None,
        "includes": _includes(facts, category),
        "inclusion_evidence": [f.evidence for f in facts.inclusions_text][:6],
        "evidence": evidence,
        "image_url": facts.images[0] if facts.images else None,
        "source_sha256": source_sha256,
        "checked_at": retrieved_at,
        "retrieval_status": "ok",
        "curator_tags": curator_tags or [],
        "adapter_notes": facts.notes,
    }
    snap["open_depth_bounds_in"] = open_depth_bounds(snap)
    snap["missing"] = missing_facts(snap)
    snap["status"] = "verified" if not snap["missing"] else "incomplete"
    return snap


def open_depth_bounds(s: dict) -> dict | None:
    """Open (sleeping) depth of a sofa bed/daybed.

    Documented overall open depth wins. Otherwise derive heuristic bounds from documented facts:
    lower = max(closed depth, shorter bed-surface side); upper = closed depth + shorter bed-surface
    side (as if the whole surface pulled out in front). These are assumptions, shown as such.
    """
    if s.get("category") not in ("sofa_bed", "daybed"):
        return None
    w, d = s.get("width_in"), s.get("depth_in")
    if w is None or d is None:
        return None
    along, closed_depth = max(w, d), min(w, d)  # long side sits along the wall
    if s.get("open_depth_in") is not None:
        v = s["open_depth_in"]
        return {"along_wall": along, "lower": v, "upper": v, "method": "documented open depth"}
    surface = s.get("bed_surface_in")
    if not surface:
        return None
    short = min(surface)
    return {
        "along_wall": round(max(along, max(surface)), 3),
        "lower": round(max(closed_depth, short), 3),
        "upper": round(closed_depth + short, 3),
        "method": "derived: overall open depth not documented; bounds from closed depth and documented bed surface",
    }


def missing_facts(s: dict) -> list[str]:
    missing = [k for k in ("name", "price_cents", "width_in", "depth_in") if s.get(k) is None]
    if s.get("category") in ("sofa_bed", "daybed") and s.get("open_depth_bounds_in") is None:
        missing.append("open footprint")
    return missing


def is_stale(snap: dict, today: date | None = None) -> bool:
    today = today or datetime.now(timezone.utc).date()
    try:
        checked = datetime.fromisoformat(snap["checked_at"]).date()
    except (KeyError, ValueError, TypeError):
        return True
    return (today - checked).days > STALE_AFTER_DAYS


def load_catalog(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text())
    return list(data.get("products", []))


MATTRESS_TOLERANCE_IN = 1.0


def _parse_size_text(text: str | None) -> tuple[float, float] | None:
    from .adapters import parse_inches

    if not text or " x " not in text:
        return None
    a, b = text.split(" x ", 1)
    wa, lb = parse_inches(a), parse_inches(b)
    return (wa, lb) if wa is not None and lb is not None else None


def mattress_compatibility(mattress: dict, frame: dict) -> str:
    """'compatible' only when the frame documents its mattress size and the mattress's documented
    width/length match within tolerance; 'incompatible' when documented sizes clearly differ;
    otherwise 'unverified'. A shared nominal label ('Queen') alone is not proof."""
    frame_size = _parse_size_text(frame.get("mattress_size_text"))
    mw, ml = mattress.get("width_in"), mattress.get("depth_in")
    if frame_size is None or mw is None or ml is None:
        return "unverified"
    fw, fl = frame_size
    if abs(fw - mw) <= MATTRESS_TOLERANCE_IN and abs(fl - ml) <= MATTRESS_TOLERANCE_IN:
        return "compatible"
    return "incompatible"
