"""Find a building -> choose it -> plan gallery (FAKE NETWORK, MOCKED gpt-6-luna transport; nothing leaves the machine)."""

import hashlib
import json
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from furnishai.app import create_app
from furnishai.config import Settings
from furnishai.safe_fetch import RawResponse, SafeFetcher
from furnishai.sources import (
    REFERENCES, _classify_image, building_candidates, discover_property, gallery, match_directories, plan_type,
    property_path_base, recovery_candidates, reference_directory_for,
)

from conftest import make_image

FAKE_KEY = "test-key-not-a-real-credential"
ARCHIVE = next(d for d in REFERENCES if d["_file"] == "thearchiveapts.json")
AUDUBON = next(d for d in REFERENCES if d["_file"] == "theaudubonapts.json")
AVAIL = "https://thearchiveapts.com/availability"
# The exact embedded snippet root observed (refuses server fetches with HTTP 403), query string included.
SNIPPET = ("https://entrata.thearchiveapts.com/new-haven/the-archive/?&is_responsive_snippet=1&snippet_type=website"
           "&occupancy_type=1")
CANONICAL = "https://entrata.thearchiveapts.com/new-haven/the-archive/conventional/"
BLOCKED = RawResponse(403, {"content-type": "text/html"}, b"challenge")
PNG = make_image("PNG", size=(300, 200))
UNIT = "Apt 5C-PRIVATE"
ARCHIVE_CTX = {"property_name": "The Archive", "city": "New Haven", "state": "CT", "zip": "", "unit_label": UNIT,
               "property_url": "", "condition": "either", "fulfillment": "either", "timing": ""}


def html(body: str) -> RawResponse:
    return RawResponse(200, {"content-type": "text/html; charset=utf-8"}, f"<html><body>{body}</body></html>".encode())


class Net:
    """Fake public network. Records every requested URL (including any query string)."""

    def __init__(self, pages, private_hosts=()):
        self.pages, self.private, self.requested = pages, set(private_hosts), []

    def resolver(self, host, port):
        return ["10.0.0.7"] if host in self.private else ["93.184.216.34"]

    def opener(self, target, headers, timeout, max_bytes):
        url = f"{target.scheme}://{target.host}{target.path}"
        self.requested.append(url)
        return self.pages.get(url, RawResponse(404, {"content-type": "text/html"}, b"nf"))

    def fetcher(self):
        return SafeFetcher(resolver=self.resolver, opener=self.opener)


ARCHIVE_PAGES = {
    AVAIL: html('<h1>The Archive</h1><img src="https://thearchiveapts.com/img/lobby.jpg" alt="Lobby photo">'
                f'<iframe src="{SNIPPET}"></iframe>'),
    SNIPPET: BLOCKED,
    CANONICAL: BLOCKED,
    ARCHIVE["plans"][0]["url"]: RawResponse(200, {"content-type": "image/png"}, PNG),
    ARCHIVE["plans"][3]["url"]: RawResponse(200, {"content-type": "image/png"}, make_image("PNG", size=(310, 210))),
}


def app_for(tmp_path, net, gateway=None):
    s = Settings(storage_dir=tmp_path / "s", portkey_api_key=FAKE_KEY if gateway else None, live_disabled=gateway is None)
    app = create_app(s, fetcher=net.fetcher(), ai_transport=httpx2.MockTransport(gateway) if gateway else None)
    return TestClient(app), app


def apartment(c, ctx=ARCHIVE_CTX, preset="2b1b"):
    return c.post("/api/apartments", json={"name": "Home", "preset": preset, "context": ctx}).json()


# ------------------------------------------------------------------ matching and exact hosts
def test_checked_buildings_match_only_on_name_and_location():
    def keys(*a):
        return [c["directory"] for c in match_directories(*a)]
    assert keys("The Archive", "New Haven", "CT", "") == ["thearchiveapts.json"]
    assert keys("archive apartments", "", "", "06510") == ["thearchiveapts.json"]
    assert keys("The Archive New Haven", "new haven", "Connecticut", "") == ["thearchiveapts.json"]
    assert keys("The Archive", "Boston", "MA", "") == []          # same name elsewhere is never assumed
    assert keys("The Archive", "New Haven", "NY", "") == []       # inconsistent state
    assert keys("The Archive", "", "CT", "") == []                # a state alone is not a location
    assert keys("The Archive Lofts", "New Haven", "CT", "") == []  # a different name
    assert keys("Audubon", "New Haven", "CT", "") == ["theaudubonapts.json"]
    arc = match_directories("The Archive", "New Haven", "CT", "")[0]
    assert arc["address"] == "848 Chapel Street, New Haven, CT 06510" and arc["plan_count"] == 19
    assert match_directories("Audubon", "New Haven", "CT", "")[0]["address"] is None  # unknown stays unknown


def test_archive_directory_has_only_observed_fields():
    assert len(ARCHIVE["plans"]) == 19 and len({p["url"] for p in ARCHIVE["plans"]}) == 19
    assert all(p["url"].startswith("https://medialibrarycfo.entrata.com/") for p in ARCHIVE["plans"])
    assert all(set(p) == {"name", "alt", "url"} for p in ARCHIVE["plans"])
    assert ARCHIVE["source_page"] == CANONICAL and ARCHIVE["observed_at"].startswith("2026-10-26")
    assert len(AUDUBON["plans"]) == 22  # existing directory unchanged


@pytest.mark.parametrize("url,ok", [
    (AVAIL, True), ("https://www.thearchiveapts.com/", True), ("https://thearchiveapts.com/availability/", True),
    (CANONICAL, True), ("https://entrata.thearchiveapts.com/new-haven/the-archive", True), (SNIPPET, True),
    ("https://entrata.thearchiveapts.com/new-haven/the-archive/floorplans/", True),
    # Paths root never observed are not supported (earlier guesses removed).
    ("https://entrata.thearchiveapts.com/Apartments/module/widgets/floorplans", False),
    ("https://entrata.thearchiveapts.com/snippets/floorplans", False),
    ("https://entrata.thearchiveapts.com/new-haven/the-archive/../admin", False),
    ("https://entrata.thearchiveapts.com/new-haven/the-archive/residents", False),
    ("https://thearchiveapts.com/faq", False), ("https://entrata.thearchiveapts.com/availability", False),
    ("https://thearchiveapts.com/new-haven/the-archive/conventional/", False),  # canonical path only on the Entrata host
    ("https://evil-thearchiveapts.com/availability", False), ("https://thearchiveapts.com.evil.example/availability", False),
    ("https://portal.thearchiveapts.com/availability", False), ("https://thearchiveapts.com:8443/availability", False),
    ("https://www.theaudubonapts.com/floorplans", True),  # Audubon still matched
])
def test_archive_entry_points_are_exact(url, ok):
    assert (reference_directory_for(url) is not None) is ok


def test_entrata_codes_are_plans_and_photos_are_not():
    assert _classify_image("https://cdn.example/a.png", "848 | Sx1 A", False)[0] == "unit_code_label"
    assert _classify_image("https://cdn.example/a.png", "848 | 2x2 Balcony Select A", False)[0] == "unit_code_label"
    assert _classify_image("https://cdn.example/a.png", "1x1 living room photo", False) is None
    assert _classify_image("https://cdn.example/a.png", "Rooftop lounge", True) is None
    assert [plan_type(p["name"]) for p in ARCHIVE["plans"]].count("studio") == 3
    assert [plan_type(p["name"]) for p in ARCHIVE["plans"]].count("1") == 8
    assert [plan_type(p["name"]) for p in ARCHIVE["plans"]].count("2") == 6
    assert [plan_type(p["name"]) for p in ARCHIVE["plans"]].count("3") == 2
    assert plan_type("1 Bed/1 Bath-A1 335 Orange") == "1" and plan_type("Studio-S2") == "studio" and plan_type("Penthouse") is None


# ------------------------------------------------------------------ Archive: choose -> crawl -> snippet 403 -> checked list
def test_archive_select_reports_snippet_403_offers_checked_plans_and_imports_real_bytes(tmp_path):
    net = Net(dict(ARCHIVE_PAGES))
    c, app = app_for(tmp_path, net)
    a = apartment(c)
    room1, room2 = a["rooms"][0]["project_id"], a["rooms"][1]["project_id"]
    found = c.post(f"/api/projects/{room1}/buildings/find", json={"property_name": "The Archive", "city": "New Haven",
                                                                  "state": "CT", "include_web": False}).json()
    assert [x["key"] for x in found["checked"]] == ["checked:thearchiveapts.json"] and found["web"] == []
    assert net.requested == []  # finding is free: nothing fetched, nothing searched
    r = c.post(f"/api/projects/{room1}/buildings/select", json={"kind": "checked", "key": "checked:thearchiveapts.json",
                                                                "property_name": "The Archive", "city": "New Haven", "state": "CT"})
    assert r.status_code == 200, r.text
    disc = r.json()["discovery"]
    assert [(p["url"], p["status"], p["via"]) for p in disc["pages"]] == [
        (AVAIL, "ok", "start"), (SNIPPET, "blocked_by_site", "linked")]  # the blocked snippet stays visible
    assert disc["plan_images"] == [] and disc["reference"]["directory"] == "thearchiveapts.json"
    assert len(disc["gallery"]) == 19 and all(g["origin"] == "checked_reference" for g in disc["gallery"])
    assert all(g["seen_at"] == ARCHIVE["observed_at"] and g["found_on"] == CANONICAL for g in disc["gallery"])
    assert disc["building"]["address"] == "848 Chapel Street, New Haven, CT 06510"
    assert net.requested == [AVAIL, SNIPPET]  # no plan image fetched until the user picks one
    # The shared place details now name the building (appended); the private unit label is kept and never fetched.
    ctx = r.json()["apartment"]["context"]
    assert ctx["building"]["key"] == "checked:thearchiveapts.json" and ctx["unit_label"] == UNIT
    assert r.json()["apartment"]["context_version"] == 2
    # The page that was read is stored as an immutable source of room 1 only.
    assert [s["source_url"] for s in r.json()["state"]["sources"]] == [AVAIL]
    # "Use this plan" imports the actual image bytes into THIS room, with provenance from our records.
    plan = ARCHIVE["plans"][0]
    imp = c.post(f"/api/projects/{room2}/property/plan-image", json={"url": plan["url"], "discovery_id": disc["id"]})
    assert imp.status_code == 200, imp.text
    prov = imp.json()["provenance"]
    assert prov["via"] == "checked reference directory" and prov["reference_plan_name"] == "848 | Sx1 A"
    assert prov["reference_observed_at"] == ARCHIVE["observed_at"] and prov["image_sha256"] == hashlib.sha256(PNG).hexdigest()
    assert prov["discovery_id"] == disc["id"] and prov["gallery_origin"] == "checked_reference" and prov["plan_type_label"] == "studio"
    src = next(s for s in imp.json()["state"]["sources"] if s["kind"] == "floorplan")
    assert src["source_url"] == plan["url"] and src["sha256"] == hashlib.sha256(PNG).hexdigest()
    stored = app.state.db.one("SELECT storage_path FROM source_assets WHERE id=?", (src["id"],))
    assert Path(stored["storage_path"]).read_bytes() == PNG  # raw bytes kept as fetched
    assert all(UNIT not in u for u in net.requested)
    # Room 1 got no plan image; its room versions are untouched (no geometry written by any of this).
    s1 = c.get(f"/api/projects/{room1}").json()
    assert [s["kind"] for s in s1["sources"]] == ["property_page"] and s1["room"] is None


def test_direct_snippet_or_canonical_url_403_falls_back_to_the_checked_list(tmp_path):
    for url in (SNIPPET, CANONICAL):
        net = Net(dict(ARCHIVE_PAGES))
        c, _ = app_for(tmp_path / url[-8:].strip("/"), net)
        pid = apartment(c)["rooms"][0]["project_id"]
        d = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "url", "url": url}).json()["discovery"]
        assert d["pages"][0]["status"] == "blocked_by_site" and d["reference"]["directory"] == "thearchiveapts.json"
        assert len(d["gallery"]) == 19 and net.requested == [url]  # one request; no evasion, no retries


def test_checked_choice_must_match_what_was_entered(tmp_path):
    net = Net(dict(ARCHIVE_PAGES))
    c, _ = app_for(tmp_path, net)
    pid = apartment(c)["rooms"][0]["project_id"]
    r = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "checked", "key": "checked:thearchiveapts.json",
                                                              "property_name": "The Archive", "city": "Boston", "state": "MA"})
    assert r.status_code == 422 and net.requested == []


# ------------------------------------------------------------------ unknown building: web candidates + recovery
ELM = "https://www.elmrow.example/"
ELM_PLANS = "https://www.elmrow.example/floor-plans/"
ELM_APPLY = "https://www.elmrow.example/apply/"
ELM_PRIVACY = "https://www.elmrow.example/privacy"
ELM_CDN = "https://cdn.elmrow-media.example/plans/elm-1x1-floor-plan.png"
ELM_LISTING = "https://www.apartments.com/elm-row-denver-co/abc123/"
ELM_INLINE = "https://www.elmrow.example/img/a1-floorplan.png"


def elm_search_body():
    return {
        "id": "resp_elm", "object": "response", "created_at": 1761400000, "status": "completed", "model": "gpt-6-luna",
        "output": [
            {"type": "web_search_call", "id": "ws_1", "status": "completed",
             "action": {"type": "search", "query": "Elm Row apartments Denver CO",
                        "sources": [{"type": "url", "url": u} for u in (ELM, ELM_PLANS, ELM_APPLY, ELM_PRIVACY, ELM_LISTING)]}},
            {"type": "message", "id": "m", "role": "assistant", "status": "completed", "content": [{
                "type": "output_text", "text": "Elm Row Apartments in Denver, CO. Elm Row 1x1 floor plan.",
                "annotations": [
                    {"type": "url_citation", "start_index": 0, "end_index": 32, "url": ELM, "title": "Elm Row Apartments | Denver, CO"},
                    {"type": "url_citation", "start_index": 34, "end_index": 57, "url": ELM_CDN, "title": "Elm Row 1x1 floor plan"},
                    {"type": "url_citation", "start_index": 0, "end_index": 10, "url": ELM_LISTING, "title": "Elm Row - Denver, CO"}]}]},
        ],
        "usage": {"input_tokens": 3000, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 100},
    }


class Gateway:
    """Mocked Portkey Responses endpoint. `bodies` maps a word in the query to the search body to return."""

    def __init__(self, bodies=None):
        self.requests, self.bodies = [], bodies or {}

    def __call__(self, request):
        sent = json.loads(request.content or b"{}")
        self.requests.append(sent)
        body = next((b for word, b in self.bodies.items() if word in json.dumps(sent)), None)
        return httpx2.Response(200, json=body or elm_search_body())


ELM_CTX = {**ARCHIVE_CTX, "property_name": "Elm Row", "city": "Denver", "state": "CO"}


def test_unknown_building_candidates_then_blocked_site_recovers_from_search_evidence(tmp_path):
    net = Net({ELM: BLOCKED,
               ELM_PLANS: html(f'<img src="{ELM_INLINE}" alt="Elm Row A1 1 Bed floor plan"><img src="https://www.elmrow.example/pool.jpg" alt="Pool photo">'),
               ELM_INLINE: RawResponse(200, {"content-type": "image/png"}, PNG),
               ELM_CDN: RawResponse(200, {"content-type": "image/png"}, PNG)})
    gw = Gateway()
    c, app = app_for(tmp_path, net, gw)
    a = apartment(c, ELM_CTX)
    room1, room2 = a["rooms"][0]["project_id"], a["rooms"][1]["project_id"]
    f = c.post(f"/api/projects/{room1}/buildings/find", json={"property_name": "Elm Row", "city": "Denver", "state": "CO"}).json()
    assert f["checked"] == [] and len(gw.requests) == 1 and UNIT not in json.dumps(gw.requests)
    sites = [(w["site"], w["listing_site"]) for w in f["web"]]
    assert sites == [("www.elmrow.example", False)]  # one card per building
    assert [(s["site"], s["identity"]) for s in f["sources"]] == [("www.apartments.com", "source")]  # listing: a source only
    official = f["web"][0]
    assert official["url"] == ELM and official["address"] is None and "Denver" in official["location_mentions"]
    assert ELM_APPLY not in official["urls"] and ELM_PRIVACY not in official["urls"]
    # The same search from another room of the place is reused (no second paid call).
    again = c.post(f"/api/projects/{room2}/buildings/find", json={"property_name": "Elm Row", "city": "Denver", "state": "CO"}).json()
    assert again["research"]["cached"] is True and len(gw.requests) == 1
    d = c.post(f"/api/projects/{room1}/buildings/select", json={"kind": "web", "key": official["key"], "url": ELM}).json()["discovery"]
    assert d["pages"][0] == {**d["pages"][0], "url": ELM, "status": "blocked_by_site", "via": "start"}  # failure kept visible
    assert [(x["url"], x["status"]) for x in d["recovery"]] == [(ELM_PLANS, "ok"), (ELM_CDN, "ok")]
    assert {g["url"] for g in d["gallery"]} == {ELM_INLINE, ELM_CDN} and all(g["origin"] == "recovered" for g in d["gallery"])
    assert next(g for g in d["gallery"] if g["url"] == ELM_INLINE)["plan_type"] == "1"
    assert ELM_APPLY not in net.requested and ELM_PRIVACY not in net.requested and ELM_LISTING not in net.requested
    # The public page reader is tried once for the refused page (it fails here), before the search's alternatives.
    assert net.requested == [ELM, "https://r.jina.ai/" + ELM, ELM_PLANS, ELM_CDN] and d["reference"] is None
    assert any("other public page" in n for n in d["notes"])
    imp = c.post(f"/api/projects/{room1}/property/plan-image", json={"url": ELM_CDN, "discovery_id": d["id"]}).json()
    assert imp["provenance"]["via"] == "web search recovery" and imp["provenance"]["gallery_origin"] == "recovered"


def test_web_choice_must_come_from_saved_search_evidence(tmp_path):
    net = Net({})
    c, _ = app_for(tmp_path, net, Gateway())
    pid = apartment(c, ELM_CTX)["rooms"][0]["project_id"]
    r = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "url": "https://www.not-searched.example/"})
    assert r.status_code == 422 and net.requested == []


def test_policy_blocked_choice_gets_no_recovery_directory_or_link(tmp_path):
    net = Net({ELM_CDN: RawResponse(200, {"content-type": "image/png"}, PNG)}, private_hosts={"www.elmrow.example"})
    c, _ = app_for(tmp_path, net, Gateway())
    pid = apartment(c, ELM_CTX)["rooms"][0]["project_id"]
    c.post(f"/api/projects/{pid}/buildings/find", json={"property_name": "Elm Row", "city": "Denver", "state": "CO"})
    d = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "url": ELM}).json()["discovery"]
    assert d["pages"][0]["status"] == "blocked_by_policy" and d["recovery"] == [] and d["gallery"] == []
    assert d["reference"] is None and d["website"] is None and net.requested == []  # nothing fetched at all
    # A checked building whose host resolves privately gets no checked list either.
    net2 = Net({}, private_hosts={"thearchiveapts.com"})
    c2, _ = app_for(tmp_path / "b", net2)
    pid2 = apartment(c2)["rooms"][0]["project_id"]
    d2 = c2.post(f"/api/projects/{pid2}/buildings/select", json={"kind": "checked", "key": "checked:thearchiveapts.json"}).json()["discovery"]
    assert d2["pages"][0]["status"] == "blocked_by_policy" and d2["reference"] is None and d2["gallery"] == []


# ------------------------------------------------------------------ sharing, ownership, staleness
def test_discovery_is_shared_by_rooms_owner_only_and_never_stale(tmp_path):
    net = Net(dict(ARCHIVE_PAGES))
    c, app = app_for(tmp_path, net)
    a = apartment(c)
    aid, room1, room2 = a["apartment"]["id"], a["rooms"][0]["project_id"], a["rooms"][1]["project_id"]
    assert c.get(f"/api/projects/{room1}/place-discovery").json()["discovery"] is None
    d = c.post(f"/api/projects/{room1}/buildings/select", json={"kind": "checked", "key": "checked:thearchiveapts.json"}).json()["discovery"]
    n = len(net.requested)
    shared = c.get(f"/api/projects/{room2}/place-discovery").json()["discovery"]
    assert shared["id"] == d["id"] and len(shared["gallery"]) == 19 and len(net.requested) == n  # saved: no refetch
    # Another browser session can't read it, or borrow its provenance for its own room.
    other = TestClient(app)
    assert other.get(f"/api/projects/{room2}/place-discovery").status_code == 404
    mine = other.post("/api/projects", json={"name": "x", "room_type": "bedroom"}).json()["project"]["id"]
    p = other.post(f"/api/projects/{mine}/property/plan-image", json={"url": ARCHIVE["plans"][3]["url"], "discovery_id": d["id"]}).json()
    assert "discovery_id" not in p["provenance"] and p["provenance"]["via"] == "checked reference directory"
    assert other.post(f"/api/projects/{room1}/buildings/select", json={"kind": "url", "url": AVAIL}).status_code == 404
    # Importing a plan into room 2 never touches room 1.
    c.post(f"/api/projects/{room2}/property/plan-image", json={"url": ARCHIVE["plans"][3]["url"], "discovery_id": d["id"]})
    assert not [s for s in c.get(f"/api/projects/{room1}").json()["sources"] if s["kind"] == "floorplan"]
    # Clearing/changing the chosen building hides the older result instead of showing it as current.
    ctx = c.get(f"/api/apartments/{aid}").json()["context"]
    c.put(f"/api/apartments/{aid}/context", json={**ctx, "building": None})
    stale = c.get(f"/api/projects/{room2}/place-discovery").json()
    assert stale["discovery"] is None and "changed" in stale["note"]
    rows = app.state.db.all("SELECT version FROM apartment_context WHERE apartment_id=? ORDER BY version", (aid,))
    assert [r["version"] for r in rows] == [1, 2, 3]  # append-only


def test_single_room_project_keeps_its_own_discovery_and_old_lookup_still_works(tmp_path):
    net = Net(dict(ARCHIVE_PAGES))
    c, _ = app_for(tmp_path, net)
    pid = c.post("/api/projects", json={"name": "Solo", "room_type": "studio"}).json()["project"]["id"]
    d = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "url", "url": AVAIL}).json()["discovery"]
    assert d["reference"]["directory"] == "thearchiveapts.json"  # exact known host, live crawl found nothing
    assert c.get(f"/api/projects/{pid}/place-discovery").json()["discovery"]["id"] == d["id"]
    old = c.post(f"/api/projects/{pid}/property", json={"url": AVAIL}).json()["discovery"]  # URL mode unchanged
    assert old["reference"]["directory"] == "thearchiveapts.json" and old["pages"][0]["status"] == "ok"


# ------------------------------------------------------------------ pass-22 review corrections
def test_contradictory_location_fields_never_match_a_checked_building():
    def keys(*a):
        return [c["directory"] for c in match_directories(*a)]
    assert keys("The Archive", "New Haven", "CT", "10001") == []   # city matches, ZIP contradicts
    assert keys("The Archive", "Seattle", "", "06510") == []        # ZIP matches, city contradicts
    assert keys("The Archive", "New Haven", "WA", "06510") == []    # state contradicts
    assert keys("Audubon", "New Haven", "CT", "06510") == []        # Audubon's known ZIP is 06511
    both = match_directories("The Archive", "New Haven", "CT", "06510")
    assert [c["directory"] for c in both] == ["thearchiveapts.json"] and both[0]["matched_on"] == ["city", "ZIP", "state"]


AVA = "https://www.avaloncommunities.com/washington/seattle-apartments/"
CAP, CAP_FP = AVA + "ava-capitol-hill/", AVA + "ava-capitol-hill/floor-plans/"
BAL, BAL_FP = AVA + "ava-ballard/", AVA + "ava-ballard/floor-plans/"
CAP_IMG = "https://cdn.avalon.example/ava-capitol-hill-studio-floor-plan.png"
BAL_IMG = "https://cdn.avalon.example/ava-ballard-1-bed-floor-plan.png"


def _r(url, title="", cited=False):
    from urllib.parse import urlsplit

    from furnishai.research import file_kind
    return {"url": url, "title": title, "domain": urlsplit(url).hostname, "cited_text": title, "file_kind": file_kind(url),
            "evidence": ["search source"] + (["citation"] if cited else []), "low_relevance": False}


AVA_RESULTS = [_r(CAP, "AVA Capitol Hill | Seattle, WA Apartments", True), _r(CAP_FP, "Floor plans | AVA Capitol Hill"),
               _r(BAL, "AVA Ballard | Seattle, WA", True), _r(BAL_FP, "Floor plans | AVA Ballard"),
               _r("https://www.avaloncommunities.com/", "Avalon Communities"),
               _r(CAP_IMG, "AVA Capitol Hill studio floor plan", True), _r(BAL_IMG, "AVA Ballard 1 bed floor plan", True)]


def test_listing_and_portal_sites_are_never_called_official():
    hosts = ["https://www.prospectportal.com/archive", "https://www.apartmenthomeliving.com/new-haven-ct/the-archive",
             "https://www.forrentuniversity.com/the-archive", "https://www.homes.com/property/848-chapel-st/",
             "https://www.apartments.com/the-archive-new-haven-ct/x1/", "https://www.apartmentfinder.com/the-archive"]
    cards, _ = building_candidates([_r(u, "The Archive | New Haven, CT", True) for u in hosts], "The Archive", "New Haven", "CT", "", [])
    assert len(cards) == 6 and all(c["listing_site"] for c in cards)
    assert all("not the building’s own website" in c["evidence"][1] for c in cards)


def test_operator_domain_keeps_each_building_separate():
    assert property_path_base(CAP_FP) == "/washington/seattle-apartments/ava-capitol-hill"
    assert property_path_base(CAP) == property_path_base(CAP_FP) != property_path_base(BAL)
    assert property_path_base("https://www.maplecourt.example/floorplans/") == "/"
    assert property_path_base("https://www.howeplace.com/apartments/studio/s1/") == "/"
    cards, _ = building_candidates(AVA_RESULTS, "AVA Capitol Hill", "Seattle", "WA", "", [])
    by_base = {c["path_base"]: c for c in cards}
    cap = by_base["/washington/seattle-apartments/ava-capitol-hill"]
    assert cards[0] is cap and cap["urls"] == [CAP, CAP_FP] and cap["multi_property_site"] is True
    assert "/washington/seattle-apartments/ava-ballard" in by_base and "/" in by_base  # never merged into one card
    assert BAL not in cap["urls"] and "more than one property" in cap["evidence"][1]


def test_recovery_stays_inside_the_chosen_building():
    picked = [c["url"] for c in recovery_candidates(AVA_RESULTS, CAP, {CAP.rstrip("/")}, "AVA Capitol Hill")]
    assert picked == [CAP_FP, CAP_IMG]  # Ballard's pages and plan image are never harvested
    # Chose the operator's home page: only pages/images that name the building qualify.
    home = [c["url"] for c in recovery_candidates(AVA_RESULTS, "https://www.avaloncommunities.com/", set(), "AVA Capitol Hill")]
    assert BAL_FP not in home and BAL_IMG not in home and CAP_FP in home
    # No building name: a cited image off the site needs the building's path, so nothing is taken.
    assert [c["url"] for c in recovery_candidates(AVA_RESULTS, CAP, {CAP.rstrip("/")}, "")] == [CAP_FP]


def test_weak_live_candidate_does_not_hide_the_checked_list():
    page = html('<img src="https://www.theaudubonapts.com/img/studio-living.jpg" alt="Studio">')
    net = Net({"https://www.theaudubonapts.com/floorplans": page})
    d = discover_property(net.fetcher(), "https://www.theaudubonapts.com/floorplans")
    assert [x["kind"] for x in d.plan_images] == ["plan_page_image"] and d.reference and len(d.reference["plans"]) == 22
    items = gallery(d, d.reference)
    assert items[0]["origin"] == "live" and sum(g["origin"] == "checked_reference" for g in items) == 22
    assert "not every unit variant" in d.notes[-1]


OAK = "https://www.oakhall.example/"
OAK_FP = "https://www.oakhall.example/floorplans/"
OAK_IMG = "https://www.oakhall.example/media/oak-hall-2x2-floor-plan.png"


def oak_search_body():
    body = elm_search_body()
    body["id"] = "resp_oak"
    body["output"][0]["action"]["sources"] = [{"type": "url", "url": u} for u in (OAK, OAK_FP)]
    msg = body["output"][1]["content"][0]
    msg["text"] = "Oak Hall in Denver. Oak Hall 2x2 floor plan."
    msg["annotations"] = [
        {"type": "url_citation", "start_index": 0, "end_index": 18, "url": OAK, "title": "Oak Hall Apartments | Denver, CO"},
        {"type": "url_citation", "start_index": 19, "end_index": 44, "url": OAK_IMG, "title": "Oak Hall 2x2 floor plan"}]
    return body


def test_recovery_uses_only_the_current_search_not_earlier_buildings(tmp_path):
    net = Net({OAK: BLOCKED, OAK_FP: BLOCKED, ELM_CDN: RawResponse(200, {"content-type": "image/png"}, PNG),
               OAK_IMG: RawResponse(200, {"content-type": "image/png"}, PNG)})
    gw = Gateway({"Oak Hall": oak_search_body()})
    c, _ = app_for(tmp_path, net, gw)
    a = apartment(c, ELM_CTX)
    aid, pid = a["apartment"]["id"], a["rooms"][0]["project_id"]
    oak_q = {"property_name": "Oak Hall", "city": "Denver", "state": "CO"}
    c.post(f"/api/projects/{pid}/buildings/find", json={"property_name": "Elm Row", "city": "Denver", "state": "CO"})
    c.post(f"/api/projects/{pid}/buildings/find", json=oak_q)
    assert len(gw.requests) == 2
    # An Elm Row result can't be chosen under the Oak Hall search.
    assert c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "url": ELM, **oak_q}).status_code == 422
    d = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "url": OAK, **oak_q}).json()["discovery"]
    assert {g["url"] for g in d["gallery"]} == {OAK_IMG}  # only Oak Hall's cited plan
    assert ELM_CDN not in net.requested and ELM_PLANS not in net.requested and len(gw.requests) == 2
    assert c.get(f"/api/apartments/{aid}").json()["context"]["building"]["name"].startswith("Oak Hall")


def test_advanced_url_without_a_search_runs_one_bounded_search_then_recovers(tmp_path):
    net = Net({OAK: BLOCKED, OAK_FP: html(f'<img src="{OAK_IMG}" alt="Oak Hall 2x2 floor plan">'),
               OAK_IMG: RawResponse(200, {"content-type": "image/png"}, PNG)})
    gw = Gateway({"Oak Hall": oak_search_body()})
    c, _ = app_for(tmp_path, net, gw)
    pid = apartment(c, {**ELM_CTX, "property_name": "Oak Hall"})["rooms"][0]["project_id"]
    d = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "url", "url": OAK}).json()["discovery"]
    assert len(gw.requests) == 1 and d["searched_for_recovery"] is True
    sent = json.dumps(gw.requests[0])
    assert "Oak Hall" in sent and "Denver" in sent and UNIT not in sent  # public name + city only
    assert d["pages"][0]["status"] == "blocked_by_site" and OAK_IMG in {g["url"] for g in d["gallery"]}
    assert all(UNIT not in u for u in net.requested)
    # The same choice again reuses the saved search (no second paid call).
    c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "url", "url": OAK})
    assert len(gw.requests) == 1


def test_advanced_url_search_fallback_is_skipped_when_policy_blocked_unnamed_or_checked(tmp_path):
    gw = Gateway({"Oak Hall": oak_search_body()})
    net = Net({}, private_hosts={"www.oakhall.example"})
    c, _ = app_for(tmp_path, net, gw)
    pid = apartment(c, {**ELM_CTX, "property_name": "Oak Hall"})["rooms"][0]["project_id"]
    d = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "url", "url": OAK}).json()["discovery"]
    assert d["pages"][0]["status"] == "blocked_by_policy" and gw.requests == [] and net.requested == []
    # No name/location saved: honest note, no search.
    net2 = Net({OAK: BLOCKED})
    c2, _ = app_for(tmp_path / "b", net2, gw)
    pid2 = c2.post("/api/apartments", json={"name": "X", "preset": "studio"}).json()["rooms"][0]["project_id"]
    d2 = c2.post(f"/api/projects/{pid2}/buildings/select", json={"kind": "url", "url": OAK}).json()["discovery"]
    assert gw.requests == [] and d2["gallery"] == [] and any("building name" in n for n in d2["notes"])
    # An exact checked host answers from its checked list without any paid search.
    net3 = Net(dict(ARCHIVE_PAGES))
    c3, _ = app_for(tmp_path / "c", net3, gw)
    pid3 = apartment(c3)["rooms"][0]["project_id"]
    d3 = c3.post(f"/api/projects/{pid3}/buildings/select", json={"kind": "url", "url": SNIPPET}).json()["discovery"]
    assert len(d3["gallery"]) == 19 and gw.requests == []
