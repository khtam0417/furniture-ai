"""Deterministic plan generation from stored product snapshots.

Code, not the model, owns every hard constraint: budget arithmetic (integer cents), condition,
exclusions, pinned items, required categories and fit labels. Product facts come only from
snapshots; only status == 'verified' snapshots can enter a plan.
"""

from __future__ import annotations

import itertools

from . import fit
from .catalog import SLEEP_CATEGORIES, _parse_size_text, is_stale, mattress_compatibility
from .models import IssueAction, Plan, PlanIssue, PlanItem, PlanSet, Preferences, RoomModel

# Stable keys (saved history uses them); plain titles. "priority" now means "closer to my budget" when a budget
# is set (older saved versions keep their own stored titles, e.g. "Priority-led: ...").
STRATEGIES = {
    "value": "Save money",
    "balanced": "Match my style",
    "priority": "Closer to my budget",
}
NO_BUDGET_PRIORITY_TITLE = "Top priority first"
TARGET_LOW_SHARE = 0.85  # "Closer to my budget" aims for 85-100% of the item allowance
CANDIDATES_PER_CATEGORY = 4  # minimum shortlist per category; grows when few categories are requested
MAX_SHORTLIST = 8
MAX_COMBINATIONS = 20000
# Balanced/Priority-led: how much one extra preference match (a style tag or a priority) may cost, as a share of the
# item allowance. "save" only takes very cheap gains; "use_for_preferences" takes any gain the cap allows. Ties
# always go to the cheaper option, so money is never spent just to spend it, and price is never read as quality.
POINT_SHARE = {"save": 0.03, "balanced": 0.12, "use_for_preferences": 1.0}
PRIORITY_WEIGHTS = (1.0, 0.6, 0.3)
UNAVAILABLE = {"OutOfStock", "SoldOut", "Discontinued"}
APPROACH_TEXT = {
    "save": "Budget approach: save as much as possible. A pricier option is chosen only when it adds a match for "
            "very little extra.",
    "balanced": "Budget approach: balanced. It spends more only where an option matches more of your style or "
                "priorities, and only up to a modest amount per extra match.",
    "use_for_preferences": "Budget approach: use more for preferences. It picks the best matches your allowance "
                           "allows; when options match equally, the cheaper one wins.",
}
PRICE_NEUTRAL = "A higher price doesn’t mean better quality; compare what changes for the extra spend."


def money(cents: int | None) -> str:
    return "unknown" if cents is None else f"${cents // 100:,}.{cents % 100:02d}"


def required_categories(prefs: Preferences, room_type: str) -> tuple[list[str], list[str]]:
    """Categories to buy, after removing ones covered by kept existing furniture, plus notes."""
    notes: list[str] = []
    cats = list(prefs.categories)
    kept = {e.category for e in prefs.existing_items if e.keep}
    if prefs.sofa_bed == "prefer" and "bed_frame" in cats and "sofa_bed" not in cats:
        cats = ["sofa_bed" if c == "bed_frame" else c for c in cats]
        cats = [c for c in cats if c != "mattress"]
        notes.append("Sofa bed preferred: replaced the bed frame + mattress with a sofa bed.")
    if prefs.sofa_bed == "no" and "sofa_bed" in cats:
        cats.remove("sofa_bed")
        notes.append("Sofa beds excluded by your setting.")
    covered = [c for c in cats if c in kept or (c in SLEEP_CATEGORIES and kept & set(SLEEP_CATEGORIES + ("bed",)))]
    for c in covered:
        notes.append(f"Keeping your existing {c.replace('_', ' ')}; not buying a new one.")
    cats = [c for c in cats if c not in covered]
    if room_type == "studio":
        has_sleep = any(c in SLEEP_CATEGORIES for c in cats) or bool(kept & set(SLEEP_CATEGORIES + ("bed",)))
        if not has_sleep:
            notes.append("A studio needs a sleep zone, but no bed, daybed or sofa bed is selected or kept.")
        served = {z for c in list(cats) + list(kept) for z in zones_for(c)}
        for z in prefs.studio_zones:
            if z not in served:
                notes.append(f"You want a {z} zone, but nothing selected or kept serves it "
                             f"(add {ZONE_HINT[z]} under What to buy, or keep one you own).")
    return cats, notes


ZONE_HINT = {"sleep": "a bed frame, daybed or sofa bed", "work": "a desk", "lounge": "a sofa, sofa bed or coffee table",
             "storage": "a dresser, wardrobe or bookcase"}
SHARED_MIN_SLEEP_WIDTH_IN = 53.0  # a full-size sleeping surface is about 53-54 in wide


def zones_for(category: str) -> list[str]:
    if category in ("sofa_bed", "daybed"):
        return ["sleep", "lounge"]  # one piece serving two zones
    if category in ("bed_frame", "mattress", "nightstand", "bed"):
        return ["sleep"]
    if category in ("desk", "desk_chair"):
        return ["work"]
    if category in ("sofa", "coffee_table"):
        return ["lounge"]
    if category in ("dresser", "wardrobe", "bookcase"):
        return ["storage"]
    return []  # unmatched / unknown types serve no zone


def _sleep_width(p: dict) -> float | None:
    """Documented width of the SLEEPING SURFACE, or None if not documented.

    Bed frames: the frame's documented mattress size (never the overall frame width: a wide upholstered twin
    frame can exceed 53 in). Mattresses: their own width. Sofa beds/daybeds: the documented bed surface.
    """
    cat = p["category"]
    if cat in ("sofa_bed", "daybed"):
        s = p.get("bed_surface_in")
        return min(s) if s else None
    if cat == "bed_frame":
        size = _parse_size_text(p.get("mattress_size_text"))
        return size[0] if size else None
    if cat == "mattress":
        return p.get("width_in")
    return None


def bed_size_coverage(catalog: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for cat in ("bed_frame", "mattress", "daybed"):
        out[cat] = sorted({p["nominal_size"] for p in catalog
                           if p.get("category") == cat and p.get("status") == "verified" and p.get("nominal_size")})
    return out


def _candidates(cat: str, prefs: Preferences, catalog: list[dict], room: RoomModel | None = None
                ) -> tuple[list[dict], str | None, str | None, str | None]:
    """(pool, note, conflict, kind). A conflict is shown prominently to the user; `kind` says what kind of problem
    it is (catalog_gap, settings, room_fit, pinned) so a missing product is never presented as a room-fit failure."""
    pool, note, kind = _filtered(cat, prefs, catalog)
    if pool and room is not None:
        fitting = [p for p in pool if not fit.individually_impossible(room, p)]
        if len(fitting) < len(pool):
            dropped = len(pool) - len(fitting)
            note = (note + " " if note else "") + (
                f"{dropped} {cat.replace('_', ' ')} option(s) are larger than the room's upper size bound and were excluded.")
        if not fitting:
            return [], None, f"No verified {cat.replace('_', ' ')} can physically fit the known room size.", "room_fit"
        pool = fitting
    pinned = prefs.pinned_product_ids.get(cat)
    if pinned and pool:
        kept = [p for p in pool if p["id"] == pinned]
        if kept:
            return kept, note, None, None
        name = next((p.get("name") for p in catalog if p["id"] == pinned), pinned)
        return pool, note, (f"You asked to keep {name}, but it no longer meets your current settings (size, condition, "
                            f"exclusions or room fit). The plans below substitute another {cat.replace('_', ' ')}; "
                            "change the settings or un-keep it to resolve this."), "pinned"
    if not pool and note is None:
        note, kind = f"No {cat.replace('_', ' ')} available.", "catalog_gap"
    return pool, (note if pool else None), (None if pool else note), (None if pool else kind)


def _filtered(cat: str, prefs: Preferences, catalog: list[dict]) -> tuple[list[dict], str | None, str | None]:
    """(pool, note, kind): kind is "catalog_gap" when the saved collection lacks a matching verified product, or
    "settings" when the user's own exclusions rule every option out."""
    pool = [p for p in catalog if p.get("category") == cat]
    if not pool:
        return [], f"No {cat.replace('_', ' ')} exists in the stored catalog.", "catalog_gap"
    pool = [p for p in pool if p.get("status") == "verified"]
    if not pool:
        return [], f"No {cat.replace('_', ' ')} has verified price and dimensions.", "catalog_gap"
    # Listed as out of stock / discontinued when last checked: never placed (shown separately when comparing).
    in_stock = [p for p in pool if p.get("availability") not in UNAVAILABLE]
    if not in_stock:
        return [], (f"Every verified {cat.replace('_', ' ')} we have was listed as out of stock when last checked."), "catalog_gap"
    pool = in_stock
    if prefs.retailers:
        # A hard restriction, for saved AND imported products alike. The store is the retailer identity the adapter
        # recorded from the page (e.g. "IKEA US", "Article"; other sites keep their web address), never a guess, so
        # an import from an unlisted store is simply not allowed while the filter is on.
        chosen = [p for p in pool if p.get("retailer") in prefs.retailers]
        if not chosen:
            return [], (f"No verified {cat.replace('_', ' ')} from {', '.join(prefs.retailers)} in our saved collection "
                        "or your imports. Allow more stores, or import a listing from one of these stores."), "settings"
        pool = chosen
    if prefs.condition != "either":
        pool = [p for p in pool if p.get("condition") == prefs.condition]
        if not pool:
            return [], f"No verified {prefs.condition} {cat.replace('_', ' ')} in the catalog.", "catalog_gap"
    terms = [t.lower() for t in prefs.excluded_terms if t.strip()]
    pool = [p for p in pool if p["id"] not in prefs.excluded_product_ids
            and not any(t in (p.get("name") or "").lower() or t in (p.get("retailer") or "").lower() for t in terms)]
    if prefs.bed_size != "any" and cat in ("bed_frame", "mattress"):
        sized = [p for p in pool if p.get("nominal_size") == prefs.bed_size]
        if not sized:
            have = sorted({p["nominal_size"] for p in pool if p.get("nominal_size")})
            return [], (f"No verified {prefs.bed_size} {cat.replace('_', ' ')} in the catalog"
                        + (f" (available: {', '.join(have)})." if have else ".")
                        + " Change the bed size or import a listing for that size."), "catalog_gap"
        pool = sized
    if prefs.shared_use and cat in ("bed_frame", "mattress", "sofa_bed", "daybed"):
        wide = [p for p in pool if (_sleep_width(p) or 0) >= SHARED_MIN_SLEEP_WIDTH_IN]
        if not wide:
            unknown = sum(1 for p in pool if _sleep_width(p) is None)
            return [], (f"Shared bed: no verified {cat.replace('_', ' ')} has a documented sleeping width of at least "
                        f"{SHARED_MIN_SLEEP_WIDTH_IN:.0f} in (full size or larger)"
                        + (f"; {unknown} option(s) don't document their sleeping size and were left out." if unknown else ".")), "catalog_gap"
        pool = wide
    if not pool:
        return [], f"Every verified {cat.replace('_', ' ')} is excluded by your size, exclusion or replacement settings.", "settings"
    return pool, None, None


_BED_CATS = ("bed_frame", "mattress")


def _cat_label(c: str) -> str:
    return c.replace("_", " ")


def plan_issues(raw: list[tuple[str, str, str]], prefs: Preferences, catalog: list[dict]) -> list[PlanIssue]:
    """Human, typed explanations for the plain `conflicts` texts. A catalog gap (nothing saved matches) is never
    worded as a room-fit problem; actions search for exactly the requested category and bed size. Settings are
    never changed here."""
    size = prefs.bed_size if prefs.bed_size != "any" else None
    edit = IssueAction(kind="edit_preferences", label="Edit preferences")
    sized = [c for k, c, t in raw if k == "catalog_gap" and size and c in _BED_CATS and t.startswith(f"No verified {size} ")]
    out: list[PlanIssue] = []
    if sized:
        have = sorted({p["nominal_size"] for p in catalog if p.get("category") in sized and p.get("status") == "verified"
                       and p.get("nominal_size") and p["nominal_size"] != size})
        what = " or ".join(f"{size} {_cat_label(c)}" for c in sized)
        out.append(PlanIssue(
            kind="catalog_gap", categories=sized, size=size,
            title=f"We still need {'two items' if len(sized) == 2 else 'one item'} for your {size} bed",
            detail=(f"Our saved collection doesn’t have a verified {what} yet"
                    + (f" (it has {', '.join(have)} sizes)" if have else "")
                    + f". This doesn’t mean a {size} won’t fit your room. Search for one, import a listing you like, "
                      "or change the bed size in Preferences."),
            actions=[IssueAction(kind="find", label=f"Find {size} {_cat_label(c)}", category=c, size=size) for c in sized] + [edit]))
    for kind, c, text in raw:
        if c and c in sized:
            continue
        name = _cat_label(c) if c else ""
        find = ([IssueAction(kind="find", label=f"Find {name}", category=c, size=size if c in _BED_CATS else None)]
                if c else [])
        if kind == "catalog_gap":
            out.append(PlanIssue(kind=kind, categories=[c] if c else [],
                                 title=f"No matching {name} in our saved collection yet" if c else "Nothing in our saved collection matches yet",
                                 detail=text + " This is about what we have saved, not about your room.", actions=find + [edit]))
        elif kind == "room_fit":
            out.append(PlanIssue(kind=kind, categories=[c], title=f"None of our {name} options fit your known room size",
                                 detail=text + " Search for a smaller one, or check the room size you set.", actions=find + [edit]))
        elif kind == "budget":
            out.append(PlanIssue(kind=kind, title="Nothing fits your item budget yet", detail=text, actions=[edit]))
        elif kind == "settings":
            out.append(PlanIssue(kind=kind, categories=[c], title=f"Your settings rule out every {name}", detail=text, actions=[edit]))
        elif kind == "pinned":
            out.append(PlanIssue(kind=kind, categories=[c], title=f"Your kept {name} no longer qualifies", detail=text, actions=[edit]))
        else:
            out.append(PlanIssue(kind="other", categories=[c] if c else [], title="Needs your attention", detail=text, actions=[edit]))
    return out


def _style(p: dict, prefs: Preferences) -> int:
    return len(set(p.get("curator_tags", [])) & set(prefs.styles))


def _area(p: dict) -> float:
    return (p.get("width_in") or 0) * (p.get("depth_in") or 0)


def _priority_match(p: dict, pr: str, max_area: float) -> float:
    """1.0 when the product clearly serves this priority (editorial tags or documented size), else 0..1."""
    tags = set(p.get("curator_tags", []))
    if pr == "storage":
        return 1.0 if "storage" in tags else 0.0
    if pr == "comfort":
        return 1.0 if ("comfort" in tags or "soft" in tags) else 0.0
    if pr == "small_footprint":
        return 1.0 if "compact" in tags else max(0.0, 1.0 - _area(p) / max_area) if max_area else 0.0
    if pr == "work":
        return 1.0 if p["category"] == "desk" and (p.get("width_in") or 0) >= 47 else 0.0
    return 0.0  # "price" is handled by the budget approach; "style" by the style tags


def pref_points(p: dict, prefs: Preferences, strategy: str = "balanced", max_area: float = 0.0) -> float:
    """Preference matches of one product: style-tag matches plus weighted priorities (top priority counts more,
    and much more in the Priority-led plan). Editorial judgments, never price."""
    pts = float(_style(p, prefs))
    for i, pr in enumerate(prefs.priorities[:3]):
        w = PRIORITY_WEIGHTS[i] * (2.5 if strategy == "priority" and i == 0 else 1.0)
        pts += w * _priority_match(p, pr, max_area)
    return pts


def _point_value_cents(prefs: Preferences, item_budget: int | None, pools: dict[str, list[dict]],
                       strategy: str = "balanced") -> float:
    """What one extra preference match may cost (cents) in "Match my style": set ONLY by the budget-approach
    setting (a default "price" priority never overrides an explicit "use more"). With no budget, a typical set price
    is the reference."""
    share = POINT_SHARE[prefs.budget_approach]
    if item_budget:
        ref = item_budget
    else:
        ref = sum(sorted(x["price_cents"] for x in pool)[len(pool) // 2] for pool in pools.values() if pool)
    return max(share * ref, 1.0)


def _mattress_ok(combo: tuple[dict, ...]) -> bool:
    frames = [p for p in combo if p["category"] == "bed_frame"]
    mats = [p for p in combo if p["category"] == "mattress"]
    if not frames or not mats:
        return True
    return mattress_compatibility(mats[0], frames[0]) != "incompatible"


def build_plans(
    prefs: Preferences,
    catalog: list[dict],
    room: RoomModel | None,
    room_type: str,
    previous: PlanSet | None = None,
) -> PlanSet:
    cats, notes = required_categories(prefs, room_type)
    conflicts: list[str] = []
    raw_issues: list[tuple[str, str, str]] = []  # (kind, category, conflict text)
    pools: dict[str, list[dict]] = {}
    missing: list[str] = []
    scaled_room = room if room is not None and room.scale_status != "unknown" else None
    for c in cats:
        pool, note, conflict, kind = _candidates(c, prefs, catalog, scaled_room)
        if note:
            notes.append(note)
        if conflict:
            conflicts.append(conflict)
            raw_issues.append((kind or "other", c, conflict))
        if pool:
            pools[c] = pool
        else:
            missing.append(c)
    if prefs.condition == "secondhand":
        notes.append("Secondhand-only: the stored catalog holds only new retail items. Import a public secondhand "
                     "listing URL to consider it; no resale stock is invented.")

    item_budget = None
    reserve = 0
    if prefs.budget_cents is not None:
        reserve = prefs.budget_cents * prefs.reserve_pct // 100
        item_budget = prefs.budget_cents - reserve

    plans: list[Plan] = []
    seen_sets: set[tuple] = set()
    search_truncated = False
    if pools:
        cat_order = list(pools)
        max_area = {c: max((_area(p) for p in pools[c]), default=0.0) for c in cat_order}
        point_value = {k: _point_value_cents(prefs, item_budget, pools, k) for k in STRATEGIES}
        per_cat = max(CANDIDATES_PER_CATEGORY, min(MAX_SHORTLIST, int(MAX_COMBINATIONS ** (1 / max(len(cat_order), 1)))))
        target = item_budget is not None  # "Closer to my budget" needs an allowance to aim at
        for strategy in STRATEGIES:
            # Shortlist = the 2 cheapest (feasibility) + the best preference matches regardless of price, so a
            # pricier, better-matching product is never crowded out by many cheap ones. "Closer to my budget" also
            # takes evenly spaced PRICE LEVELS up to the most expensive eligible product.
            shortlists = []
            for c in cat_order:
                cheapest = sorted(pools[c], key=lambda p: (p["price_cents"], -_style(p, prefs)))
                if strategy == "value":
                    ranked = cheapest[:per_cat]
                elif strategy == "priority" and target:
                    k = max(per_cat - 2, 1)
                    levels = [cheapest[round(i * (len(cheapest) - 1) / max(k - 1, 1))] for i in range(k)] if cheapest else []
                    best = sorted(pools[c], key=lambda p: (-pref_points(p, prefs, "balanced", max_area[c]), p["price_cents"]))[:2]
                    ranked = levels + best
                else:
                    ranked = sorted(pools[c], key=lambda p: (-pref_points(p, prefs, strategy, max_area[c]), p["price_cents"]))
                    ranked = ranked[:max(per_cat - 2, 1)]
                shortlists.append(list({p["id"]: p for p in cheapest[:2] + ranked}.values()))
            feasible = []
            for n, combo in enumerate(itertools.product(*shortlists)):
                if n >= MAX_COMBINATIONS:
                    search_truncated = True
                    break
                total = sum(p["price_cents"] for p in combo)
                if item_budget is not None and total > item_budget:  # hard cap: item allowance
                    continue
                if not _mattress_ok(combo):
                    continue
                if strategy == "value":
                    score = (total, -sum(_style(p, prefs) for p in combo))
                elif strategy == "priority" and target:
                    # Within 85-100% of the allowance: best preference matches, then closest to the allowance.
                    # Below the band: as close to it as possible. Never above the allowance (hard cap above).
                    pts = sum(pref_points(p, prefs, "balanced", max_area[p["category"]]) for p in combo)
                    in_band = total >= TARGET_LOW_SHARE * item_budget
                    score = (0, -pts, -total) if in_band else (1, -total, -pts)
                else:
                    pts = sum(pref_points(p, prefs, strategy, max_area[p["category"]]) for p in combo)
                    score = (-(pts - total / point_value[strategy]), total)
                feasible.append((score, combo))
            feasible.sort(key=lambda x: x[0])
            # Best combination this strategy has not already produced (diversified alternatives).
            for _, combo in feasible:
                sig = tuple(sorted(p["id"] for p in combo))
                if sig not in seen_sets:
                    seen_sets.add(sig)
                    plan = _make_plan(strategy, combo, prefs, room, room_type, missing, item_budget, reserve)
                    if strategy == "priority":
                        _explain_target(plan, prefs, pools, item_budget, truncated=search_truncated)
                    plans.append(plan)
                    break

        if not plans:
            cheapest_total = sum(min(p["price_cents"] for p in pools[c]) for c in cat_order)
            text = (f"No combination fits the item budget of {money(item_budget)} (budget {money(prefs.budget_cents)} minus "
                    f"{prefs.reserve_pct}% delivery/tax reserve). The cheapest verified set costs {money(cheapest_total)}. "
                    "Raise the budget, lower the reserve, keep existing furniture, or remove a category.")
            conflicts.append(text)
            raw_issues.append(("budget", "", text))
    elif cats:
        text = "No verified products are available for any requested category."
        conflicts.append(text)
        if not raw_issues:  # otherwise each category already has its own, more specific issue
            raw_issues.append(("catalog_gap", "", text))
    else:
        notes.append("No categories to buy: everything requested is covered by existing furniture.")
    if not cats and any(e.keep for e in prefs.existing_items):
        # Reuse goal: arrange what the user already owns, with zero purchases.
        reuse = _make_plan("value", (), prefs, room, room_type, [], item_budget, reserve)
        reuse.title = "Reuse: arrange what you own (no purchases)"
        plans = [reuse]

    _add_differences(plans, prefs)
    if 0 < len(plans) < 3 and pools:
        scope = (f"the shortlisted candidates per category" if not search_truncated
                 else "a truncated search")
        notes.append(f"Found {len(plans)} distinct plan(s) within budget among {scope}; no more distinct "
                     "combinations were found there (duplicates are never shown as alternatives).")
    if missing and plans:
        notes.append("Plans are incomplete: " + ", ".join(m.replace("_", " ") for m in missing) + " could not be filled from verified products.")

    ps = PlanSet(plans=plans, notes=notes, conflicts=conflicts, issues=plan_issues(raw_issues, prefs, catalog),
                 room_scale_status=room.scale_status if room else "unknown")
    ps.changes = diff_plans(previous, ps) if previous else []
    return ps


def _make_plan(strategy, combo, prefs: Preferences, room, room_type, missing, item_budget, reserve) -> Plan:
    items: list[PlanItem] = []
    explanation: list[str] = []
    for p in combo:
        notes = []
        if p["category"] == "bed_frame":
            inc = p.get("includes") or {}
            if inc.get("slats") is False:
                notes.append("Slatted base sold separately (not in this subtotal; cost not verified).")
            if inc.get("mattress") is False and not any(x["category"] == "mattress" for x in combo):
                notes.append("Mattress not included and not in your categories.")
        if p["category"] == "mattress":
            frame = next((x for x in combo if x["category"] == "bed_frame"), None)
            if frame:
                compat = mattress_compatibility(p, frame)
                notes.append("Mattress size matches the frame's documented mattress size."
                             if compat == "compatible" else "Mattress/frame compatibility unverified.")
        if p["category"] in ("sofa_bed", "daybed") and p.get("open_depth_bounds_in"):
            b = p["open_depth_bounds_in"]
            notes.append(f"Open sleeping depth not fully documented: assumed {b['lower']:.0f}–{b['upper']:.0f} in.")
        if p["category"] == "daybed" and (p.get("includes") or {}).get("mattress") is False:
            notes.append("Mattress(es) sold separately; none in the verified catalog.")
        pinned = prefs.pinned_product_ids.get(p["category"])
        if pinned == p["id"]:
            notes.append("Kept from the previous plan at your request.")
        elif pinned:
            notes.append("Substitutes the item you asked to keep (see conflict above).")
        stale = is_stale(p)
        if stale:
            notes.append("Price/stock last checked more than 14 days ago.")
        if p.get("origin") == "user_import":
            notes.append("From a listing you imported.")
            if p.get("condition_verified") is False:
                notes.append(f"{(p.get('condition') or 'Condition').capitalize()} condition declared by you, not independently verified.")
        if p["category"] in ("sofa_bed", "daybed") and room_type == "studio":
            notes.append("Serves both the sleep and lounge zones: it must be opened each night.")
        if prefs.shared_use and p["category"] in ("bed_frame", "mattress", "sofa_bed", "daybed"):
            notes.append("Shared bed: documented sleeping width is at least full size. Space on both sides is not checked.")
        items.append(PlanItem(
            category=p["category"], product_id=p["id"], name=p["name"], retailer=p.get("retailer"), url=p.get("url"),
            price_cents=p["price_cents"], width_in=p.get("width_in"), depth_in=p.get("depth_in"),
            condition=p.get("condition"), checked_at=p.get("checked_at"), stale=stale,
            availability=p.get("availability"),
            zone=zone_for(p["category"]) if room_type == "studio" else None,
            zones=zones_for(p["category"]) if room_type == "studio" else [],
            image_url=_safe_image(p.get("image_url")), origin=p.get("origin"),
            notes=notes,
        ))
    for e in prefs.existing_items:
        if e.keep:
            enotes = [] if e.width_in and e.depth_in else ["Footprint unknown; space not counted."]
            if e.category == "unmatched":
                enotes.insert(0, f"Seen in your photos as “{e.detected_label or 'item'}”. Choose what type it is in "
                                 "Preferences if it should replace a purchase; until then it replaces nothing.")
            items.append(PlanItem(
                category=e.category, existing_item_id=e.id,
                name=f"Your {e.description or e.detected_label or e.category} (kept)",
                price_cents=0, width_in=e.width_in, depth_in=e.depth_in,
                zone=zone_for(e.category) if room_type == "studio" else None,
                zones=zones_for(e.category) if room_type == "studio" else [],
                notes=enotes,
            ))
    subtotal = sum(p["price_cents"] for p in combo)
    unknown_kept = sum(1 for e in prefs.existing_items if e.keep and not (e.width_in and e.depth_in))
    sleep = next((p for p in combo if p["category"] in ("sofa_bed", "daybed")), None)
    sleeping_on = sleep["id"] if sleep and not any(p["category"] == "bed_frame" for p in combo) else None
    fit_items = [fit.FitItem(p["id"], p["category"], p.get("width_in"), p.get("depth_in"),
                             (p.get("open_depth_bounds_in") or {}).get("upper"),
                             (p.get("open_depth_bounds_in") or {}).get("along_wall")) for p in combo]
    fit_items += [fit.FitItem(e.id, e.category, e.width_in, e.depth_in) for e in prefs.existing_items if e.keep and e.width_in and e.depth_in]
    fr = fit.evaluate(room, fit_items, unknown_kept, sleeping_on)
    for it in items:
        ref = it.product_id or it.existing_item_id
        it.fit_label = fr.labels.get(ref, "Fit unverified")
    if prefs.budget_cents is None:
        status = "no_budget_set"
    elif subtotal <= item_budget:
        status = "within_item_budget_total_unverified"
    else:
        status = "over_budget"
    unused = (item_budget - subtotal) if item_budget is not None else None
    if item_budget is not None:
        explanation.append(f"Item allowance {money(item_budget)} (your {money(prefs.budget_cents)} budget minus "
                           f"{prefs.reserve_pct}% held for delivery/tax). This plan’s items total {money(subtotal)}, "
                           f"leaving {money(unused)} unused. Checkout total is not verified.")
    else:
        explanation.append(f"Item total {money(subtotal)}; no budget set.")
    if strategy == "value":
        explanation.append("Save money takes the lowest-priced verified option in each category; your style tags don’t steer it.")
    elif strategy == "priority" and item_budget is not None:
        explanation.append(f"Closer to my budget aims for {money(int(TARGET_LOW_SHARE * item_budget))}–{money(item_budget)} "
                           f"(85–100% of your item allowance) using only the categories you chose; within that range it "
                           f"prefers better style and priority matches. {PRICE_NEUTRAL}")
    else:
        explanation.append(APPROACH_TEXT[prefs.budget_approach])
        if combo and not any(pref_points(p, prefs, strategy) for p in combo):
            explanation.append("None of your styles or priorities tell these options apart, so the cheaper ones were "
                               "kept. Add a style (for example warm wood) or a priority to give the budget something to "
                               "work for.")
    if prefs.styles:
        matched = sum(_style(p, prefs) for p in combo)
        explanation.append(f"{matched} editorial style-tag match(es) with {', '.join(prefs.styles)} (tags are judgments, "
                           "not retailer facts; a higher price is never treated as better quality).")
    if strategy == "priority" and item_budget is None and prefs.priorities:
        explanation.append(f"Puts your top priority first: {prefs.priorities[0].replace('_', ' ')}.")
    explanation.extend(fr.notes)
    for it in items:
        ref = it.product_id or it.existing_item_id
        it.fit_checks = fr.checks.get(ref)
    return Plan(
        key=strategy, title=STRATEGIES[strategy] if not (strategy == "priority" and item_budget is None) else NO_BUDGET_PRIORITY_TITLE,
        items=items, subtotal_cents=subtotal, reserve_cents=reserve,
        item_budget_cents=item_budget, budget_cents=prefs.budget_cents, budget_status=status,
        fit_summary=fr.plan_label, missing_required=list(missing), explanation=explanation,
        item_allowance_cents=item_budget, unused_cents=unused, fit_overview=fr.overview,
        budget_approach=None if strategy == "value" else prefs.budget_approach,
        layout=None, layout_is_conceptual=True,
    )


def _explain_target(plan: Plan, prefs: Preferences, pools: dict[str, list[dict]], item_budget: int | None,
                    truncated: bool) -> None:
    """Say how close "Closer to my budget" got and, if short, exactly why (no furniture is added to spend more)."""
    if item_budget is None:
        return
    reach = sum(max(p["price_cents"] for p in pool) for pool in pools.values() if pool)
    share = plan.subtotal_cents / item_budget if item_budget else 0
    if share >= TARGET_LOW_SHARE:
        plan.explanation.insert(1, f"Uses {share:.0%} of your item allowance.")
    else:
        plan.explanation.insert(1, (
            f"Gets to {share:.0%} of your item allowance. The most the {len(pools)} categories you chose can reach with "
            f"eligible saved products is about {money(min(reach, item_budget) if reach <= item_budget else reach)}"
            + (" (before checking combinations)" if reach > item_budget else "")
            + ". To get closer, add a category you actually want, allow more stores or sizes, or import a listing; "
              "we won’t add furniture you didn’t ask for."))
    plan.explanation.append("Found by a bounded search over shortlisted price levels per category; a combination "
                            "outside the shortlist could come closer." + (" The search was cut short." if truncated else ""))


def _add_differences(plans: list[Plan], prefs: Preferences) -> None:
    """For Balanced/Priority-led: what differs from the Value plan, per category, with the price change and why."""
    value = next((p for p in plans if p.key == "value"), None)
    if value is None:
        return
    base = {i.category: i for i in value.items if i.product_id}
    for pl in plans:
        if pl is value:
            continue
        diffs = []
        for it in pl.items:
            b = base.get(it.category)
            if not it.product_id or b is None or b.product_id == it.product_id:
                continue
            delta = (it.price_cents or 0) - (b.price_cents or 0)
            diffs.append(f"{it.category.replace('_', ' ').capitalize()}: {it.name} instead of {b.name} "
                         f"({'+' if delta >= 0 else '−'}{money(abs(delta))} vs Save money).")
        pl.differences = diffs or ["Same items as Save money."]


# ------------------------------------------------------------------ one-category swaps
class SwapRejected(Exception):
    """A requested swap was refused; nothing was changed. `reason` is safe to show."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _item_budget(prefs: Preferences) -> tuple[int | None, int]:
    if prefs.budget_cents is None:
        return None, 0
    reserve = prefs.budget_cents * prefs.reserve_pct // 100
    return prefs.budget_cents - reserve, reserve


def _settings_reason(cand: dict, prefs: Preferences) -> str | None:
    """Why this product breaks the saved settings, or None."""
    cat = cand["category"]
    if prefs.condition != "either" and cand.get("condition") != prefs.condition:
        return f"It is {cand.get('condition')}, but your settings ask for {prefs.condition} only."
    if cand["id"] in prefs.excluded_product_ids:
        return "You chose to replace this item earlier."
    name = (cand.get("name") or "").lower()
    retailer = (cand.get("retailer") or "").lower()
    hit = next((t for t in prefs.excluded_terms if t.strip() and (t.lower() in name or t.lower() in retailer)), None)
    if hit:
        return f"It matches a word you asked to avoid (“{hit}”)."
    if prefs.retailers and cand.get("retailer") not in prefs.retailers:
        return f"It’s from {cand.get('retailer')}, and your settings allow only {', '.join(prefs.retailers)}."
    if prefs.bed_size != "any" and cat in ("bed_frame", "mattress") and cand.get("nominal_size") != prefs.bed_size:
        return f"It is {cand.get('nominal_size') or 'an unknown size'}, but your bed size is {prefs.bed_size}."
    if prefs.shared_use and cat in ("bed_frame", "mattress", "sofa_bed", "daybed") and (_sleep_width(cand) or 0) < SHARED_MIN_SLEEP_WIDTH_IN:
        return "Its documented sleeping width is under full size, but the bed is shared."
    return None


def check_swap(plan: Plan, category: str, cand: dict, prefs: Preferences, by_id: dict, room: RoomModel | None) -> tuple[list[dict], int]:
    """Validate replacing `category` in `plan` with `cand`. Returns (new product combo, new subtotal) or raises."""
    current = [i for i in plan.items if i.product_id and i.category == category]
    if not current:
        raise SwapRejected(f"This plan has no {category.replace('_', ' ')} to swap.")
    if cand.get("category") != category:
        raise SwapRejected("That product is a different kind of furniture.")
    if cand["id"] == current[0].product_id:
        raise SwapRejected("That is already the chosen item.")
    if cand.get("status") != "verified":
        missing = ", ".join(m.replace("_cents", "").replace("_in", "") for m in cand.get("missing", [])) or "facts"
        raise SwapRejected(f"Its {missing} could not be verified from the source page, so it can’t be placed.")
    if cand.get("availability") in UNAVAILABLE:
        raise SwapRejected(f"Listed as out of stock when checked on {str(cand.get('checked_at', ''))[:10]}.")
    reason = _settings_reason(cand, prefs)
    if reason:
        raise SwapRejected(reason)
    if room is not None and room.scale_status != "unknown" and fit.individually_impossible(room, cand):
        raise SwapRejected("It is larger than your room’s known size allows.")
    others = []
    for i in plan.items:
        if i.product_id and i.category != category:
            p = by_id.get(i.product_id)
            if p is None:
                raise SwapRejected("A product in this plan is no longer in the catalog; rebuild the plan first.")
            others.append(p)
    combo = others + [cand]
    if not _mattress_ok(tuple(combo)):
        raise SwapRejected("The mattress size doesn’t match the bed frame’s documented mattress size.")
    total = sum(p["price_cents"] for p in combo)
    item_budget, _ = _item_budget(prefs)
    if item_budget is not None and total > item_budget:
        raise SwapRejected(f"The plan would cost {money(total)}, over this room’s item budget of {money(item_budget)} by {money(total - item_budget)}.")
    return combo, total


def swap_plan(plan: Plan, category: str, cand: dict, prefs: Preferences, by_id: dict, room: RoomModel | None, room_type: str) -> Plan:
    """New plan with ONLY `category` replaced; other products, kept furniture, budget and title are preserved."""
    combo, _ = check_swap(plan, category, cand, prefs, by_id, room)
    item_budget, reserve = _item_budget(prefs)
    old = next(i for i in plan.items if i.product_id and i.category == category)
    new = _make_plan(plan.key, tuple(combo), prefs, room, room_type, plan.missing_required, item_budget, reserve)
    new.title = plan.title
    new.explanation.insert(0, f"You swapped the {category.replace('_', ' ')}: {old.name} → {cand['name']} "
                              f"({'+' if cand['price_cents'] >= (old.price_cents or 0) else '−'}{money(abs(cand['price_cents'] - (old.price_cents or 0)))}).")
    return new


def alternatives_for(plan: Plan, category: str, prefs: Preferences, catalog: list[dict], room: RoomModel | None,
                     limit: int = 24) -> list[dict]:
    """Every catalog/imported product of this category with whether it can be swapped in, and why not."""
    by_id = {p["id"]: p for p in catalog}
    current = next((i for i in plan.items if i.product_id and i.category == category), None)
    scaled = room is not None and room.scale_status != "unknown"
    fit_note = ("Checked on its own against your known room size only; whether it fits with the rest of the furniture "
                "is checked in the drawing after you choose. Not a guarantee." if scaled else
                "Fit not assessed: this room has no known size, so only price and your settings were checked.")
    out = []
    for cand in catalog:
        if cand.get("category") != category:
            continue
        try:
            _, total = check_swap(plan, category, cand, prefs, by_id, room)
            ok, reason = True, None
        except SwapRejected as exc:
            ok, reason, total = False, exc.reason, None
            if current and cand["id"] == current.product_id:
                reason = "Currently chosen."
        out.append({
            "product_id": cand["id"], "name": cand.get("name"), "retailer": cand.get("retailer"), "url": cand.get("url"),
            "price_cents": cand.get("price_cents"), "width_in": cand.get("width_in"), "depth_in": cand.get("depth_in"),
            "condition": cand.get("condition"), "condition_verified": cand.get("condition_verified", cand.get("origin") != "user_import"),
            "checked_at": cand.get("checked_at"), "stale": is_stale(cand), "availability": cand.get("availability"),
            "image_url": _safe_image(cand.get("image_url")), "status": cand.get("status"), "origin": cand.get("origin"),
            "current": bool(current and cand["id"] == current.product_id), "can_swap": ok, "reason": reason,
            "delta_cents": (cand["price_cents"] - (current.price_cents or 0)) if current and cand.get("price_cents") is not None else None,
            "subtotal_after_cents": total, "style_match": _style(cand, prefs) if cand.get("status") == "verified" else 0,
            "pref_points": round(pref_points(cand, prefs), 2) if cand.get("status") == "verified" else 0,
            "available": cand.get("status") == "verified" and cand.get("availability") not in UNAVAILABLE,
            "nominal_size": cand.get("nominal_size"),
            "fit_note": fit_note,
            "delivery_note": ((f"Listed as {str(cand['availability']).lower()} when checked on {str(cand.get('checked_at', ''))[:10]}; "
                               if cand.get("availability") else "")
                              + "delivery or pickup timing is unknown — check with the seller."),
        })
    out.sort(key=lambda a: (not a["current"], not a["can_swap"], -a["pref_points"], a["price_cents"] if a["price_cents"] is not None else 10**9))
    # "Recommended": the current item plus the best few swappable ones (preference matches, then price).
    rec = [a for a in out if a["can_swap"]][:3]
    for a in out:
        a["recommended"] = a["current"] or a in rec
    return out[:limit]


def zone_for(category: str) -> str | None:
    z = zones_for(category)
    return z[0] if z else None


def _safe_image(url: object) -> str | None:
    return url if isinstance(url, str) and url.startswith("https://") and len(url) < 600 else None


def diff_plans(old: PlanSet, new: PlanSet) -> list[str]:
    changes = []
    old_by = {p.key: p for p in old.plans}
    for p in new.plans:
        o = old_by.get(p.key)
        if not o:
            changes.append(f"{p.title}: new alternative.")
            continue
        ob = {i.category: i for i in o.items if i.product_id}
        nb = {i.category: i for i in p.items if i.product_id}
        for cat in sorted(set(ob) | set(nb)):
            a, b = ob.get(cat), nb.get(cat)
            if a and b and a.product_id != b.product_id:
                changes.append(f"{p.key}: {cat.replace('_', ' ')} changed from {a.name} to {b.name}.")
            elif a and not b:
                changes.append(f"{p.key}: removed {cat.replace('_', ' ')} ({a.name}).")
            elif b and not a:
                changes.append(f"{p.key}: added {cat.replace('_', ' ')} ({b.name}).")
        if o.subtotal_cents != p.subtotal_cents:
            changes.append(f"{p.key}: subtotal {money(o.subtotal_cents)} → {money(p.subtotal_cents)}.")
    for k in old_by.keys() - {p.key for p in new.plans}:
        changes.append(f"{old_by[k].title}: no longer feasible.")
    return changes
