"""Applying typed preference patches, plus the offline rule-based parser used in demo mode.

The patch (from the AI agent or the rule parser) can only touch fields defined in PreferencePatch.
Code applies it; unrelated constraints are untouched by construction.
"""

from __future__ import annotations

import re

from .models import Category, PlanSet, PreferencePatch, Preferences, Style

STYLE_WORDS: dict[str, Style] = {
    "minimal": "minimal", "minimalist": "minimal", "scandinavian": "scandinavian", "scandi": "scandinavian",
    "modern": "modern", "traditional": "traditional", "classic": "traditional", "rustic": "rustic",
    "mid-century": "mid_century", "mid century": "mid_century", "midcentury": "mid_century",
    "industrial": "industrial", "wood": "warm_wood", "wooden": "warm_wood", "warm": "warm_wood",
    "light": "light_neutral", "white": "light_neutral", "neutral": "light_neutral", "dark": "dark", "black": "dark",
    "soft": "soft", "cozy": "soft", "upholstered": "soft",
}
CATEGORY_WORDS: dict[str, Category] = {
    "desk chair": "desk_chair", "office chair": "desk_chair", "work desk": "desk", "desk": "desk",
    "sofa bed": "sofa_bed", "sleeper": "sofa_bed", "futon": "sofa_bed", "daybed": "daybed", "sofa": "sofa",
    "couch": "sofa", "mattress": "mattress", "bed frame": "bed_frame", "bed": "bed_frame", "dresser": "dresser",
    "drawers": "dresser", "nightstand": "nightstand", "bedside": "nightstand", "wardrobe": "wardrobe",
    "closet": "wardrobe", "bookcase": "bookcase", "bookshelf": "bookcase", "shelf": "bookcase",
    "coffee table": "coffee_table",
}


# Stores whose products are in the saved collection (retailer names exactly as stored).
KNOWN_RETAILERS = ("IKEA US", "Article", "Target", "Amazon")
STORE_WORDS = {"ikea": "IKEA US", "article": "Article", "target": "Target", "amazon": "Amazon"}


def apply_patch(prefs: Preferences, patch: PreferencePatch, current: PlanSet | None) -> tuple[Preferences, list[str]]:
    p = prefs.model_copy(deep=True)
    changes: list[str] = []
    if patch.set_budget_usd is not None:
        p.budget_cents = patch.set_budget_usd * 100
        changes.append(f"Budget set to ${patch.set_budget_usd:,}.")
    if patch.set_condition:
        p.condition = patch.set_condition
        changes.append(f"Condition: {patch.set_condition}.")
    if patch.set_styles is not None:
        p.styles = list(dict.fromkeys(patch.set_styles + patch.add_styles))
        changes.append("Styles replaced with " + (", ".join(p.styles) or "none") + ".")
    else:
        for s in patch.add_styles:
            if s not in p.styles:
                p.styles.append(s)
                changes.append(f"Added style {s}.")
    for s in patch.remove_styles:
        if s in p.styles:
            p.styles.remove(s)
            changes.append(f"Removed style {s}.")
    for c in patch.add_categories:
        if c not in p.categories:
            p.categories.append(c)
            changes.append(f"Added {c.replace('_', ' ')}.")
    for c in patch.remove_categories:
        if c in p.categories:
            p.categories.remove(c)
            p.pinned_product_ids.pop(c, None)
            changes.append(f"Removed {c.replace('_', ' ')}.")
    for pr in patch.add_priorities:
        if pr in p.priorities:
            p.priorities.remove(pr)
        p.priorities.insert(0, pr)
        changes.append(f"Top priority: {pr.replace('_', ' ')}.")
    if patch.set_bed_size:
        p.bed_size = patch.set_bed_size
        changes.append(f"Bed size: {patch.set_bed_size}.")
    if patch.set_sofa_bed:
        p.sofa_bed = patch.set_sofa_bed
        changes.append(f"Sofa bed: {patch.set_sofa_bed}.")
    if patch.set_budget_approach:
        p.budget_approach = patch.set_budget_approach
        changes.append("Budget approach: " + {"save": "save as much as possible", "balanced": "balanced",
                                               "use_for_preferences": "use more of the budget for better matches"}[patch.set_budget_approach] + ".")
    if patch.set_retailers is not None:
        known = [r for r in patch.set_retailers if r in KNOWN_RETAILERS]
        unknown = [r for r in patch.set_retailers if r not in KNOWN_RETAILERS]
        if unknown:
            changes.append("Not supported, not applied: only " + ", ".join(KNOWN_RETAILERS) + " are in the saved collection ("
                           + ", ".join(unknown) + " can’t be filtered; import a listing from there instead).")
        if known or not patch.set_retailers:
            p.retailers = known
            changes.append(("Stores: " + ", ".join(known) + " only.") if known else "Stores: any.")
    balanced = next((pl for pl in (current.plans if current else []) if pl.key == "balanced"), None) or (
        current.plans[0] if current and current.plans else None)
    for c in patch.keep_current_categories:
        item = next((i for i in (balanced.items if balanced else []) if i.category == c and i.product_id), None)
        if item:
            p.pinned_product_ids[c] = item.product_id
            changes.append(f"Keeping {item.name}.")
        else:
            changes.append(f"No current {c.replace('_', ' ')} to keep.")
    for c in patch.replace_current_categories:
        # Replace in every alternative: exclude each plan's current product in this category.
        replaced = {i.product_id for pl in (current.plans if current else []) for i in pl.items if i.category == c and i.product_id}
        p.pinned_product_ids.pop(c, None)
        for pid in sorted(replaced):
            if pid not in p.excluded_product_ids:
                p.excluded_product_ids.append(pid)
        changes.append(f"Replacing current {c.replace('_', ' ')}." if replaced else f"No current {c.replace('_', ' ')} to replace.")
    for t in patch.add_excluded_terms:
        t = t.strip()[:60]
        if t and t not in p.excluded_terms:
            p.excluded_terms.append(t)
            changes.append(f"Excluding '{t}'.")
    for cat in patch.keep_existing_item_categories:
        for e in p.existing_items:
            if e.category == cat:
                e.keep = True
                changes.append(f"Keeping your existing {cat}.")
    if patch.note:
        p.notes.append(patch.note)
    for u in patch.unsupported_requests:
        changes.append(f"Not supported, not applied: {u}")
    return Preferences.model_validate(p.model_dump()), changes


def _find_categories(text: str) -> list[Category]:
    found: list[Category] = []
    t = text
    for word in sorted(CATEGORY_WORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}s?\b", t):
            cat = CATEGORY_WORDS[word]
            if cat not in found:
                found.append(cat)
            t = re.sub(rf"\b{re.escape(word)}s?\b", " ", t)
    return found


def rule_based_patch(message: str) -> PreferencePatch:
    """Offline, deterministic interpretation of common edits. Not AI; used for demo mode and tests."""
    text = message.lower().strip()
    patch = PreferencePatch(summary="Rule-based parser (offline, not AI)")
    m = re.search(r"\$\s?(\d[\d,]*)|(\d[\d,]*)\s*(?:dollars|usd|bucks)\b|budget\D{0,20}(\d[\d,]{2,})", text)
    if m:
        value = next(g for g in m.groups() if g)
        patch.set_budget_usd = int(value.replace(",", ""))
    if re.search(r"\b(new only|only new|brand new)\b", text):
        patch.set_condition = "new"
    elif re.search(r"\b(secondhand|second-hand|used|pre-owned|thrift)\b", text):
        patch.set_condition = "secondhand"
    elif re.search(r"\b(either|any condition)\b", text):
        patch.set_condition = "either"
    styles: list = []
    for word, style in STYLE_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", text) and style not in styles:
            styles.append(style)
    if styles and re.search(r"\b(change|switch|swap)\b.*\b(style|look)\b|\b(style|look) to\b|\binstead\b|\bonly\b", text):
        patch.set_styles = styles
    else:
        patch.add_styles = styles
    for size in ("twin", "full", "queen", "king"):
        if re.search(rf"\b{size}\b", text):
            patch.set_bed_size = size
    if re.search(r"\b(no sofa ?bed|without (a )?sofa ?bed)\b", text):
        patch.set_sofa_bed = "no"
    clauses = re.split(r"[,.;]| and | but ", text)
    for clause in clauses:
        cats = _find_categories(clause)
        if not cats:
            continue
        if re.search(r"\b(keep|keeping|stick with)\b", clause):
            if re.search(r"\b(my|existing|own|already have)\b", clause):
                patch.keep_existing_item_categories.extend(c for c in cats)
            else:
                patch.keep_current_categories.extend(cats)
        elif re.search(r"\b(replace|swap|different|another|change)\b", clause):
            patch.replace_current_categories.extend(cats)
        elif re.search(r"\b(remove|drop|no|without|skip|don't need|do not need)\b", clause):
            patch.remove_categories.extend(cats)
        elif re.search(r"\b(add|need|want|include|plus|also)\b", clause):
            patch.add_categories.extend(cats)
    if re.search(r"\b(storage)\b", text) and re.search(r"\b(more|priorit|need|focus)\w*", text):
        patch.add_priorities.append("storage")
    if re.search(r"\b(cheaper|cheapest|save money|lower cost)\b", text):
        patch.add_priorities.append("price")
        patch.set_budget_approach = "save"
    if re.search(r"\b(spend more|use (?:more of )?(?:my |the )?budget|use more of (?:my|the) budget|splurge)\b", text):
        patch.set_budget_approach = "use_for_preferences"
    elif re.search(r"\bbalanced? (?:budget|spending)\b", text):
        patch.set_budget_approach = "balanced"
    m_store = re.search(r"\bonly (?:from |at |shop (?:at )?)?([a-z][a-z .&'-]{1,30}?)(?:\s+(?:stores?|furniture|items?)|[,.;]|$)", text)
    if re.search(r"\b(any|all) stores?\b", text):
        patch.set_retailers = []
    elif m_store and m_store.group(1).strip() in set(STORE_WORDS) | {"amazon", "wayfair", "west elm", "walmart"}:
        name = m_store.group(1).strip()
        patch.set_retailers = [STORE_WORDS.get(name, name.title())]
    if re.search(r"\b(small|compact|space-saving|tiny)\b", text):
        patch.add_priorities.append("small_footprint")
    if re.search(r"\b(lower|reduce|cut)\b.*\bbudget\b", text) and patch.set_budget_usd is None:
        patch.unsupported_requests.append("lower the budget without an amount (please give a dollar figure)")
    if patch == PreferencePatch(summary=patch.summary):
        patch.unsupported_requests.append(message[:120])
    patch.note = message[:200]
    return patch
