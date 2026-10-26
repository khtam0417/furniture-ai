"""Public page reader fallback + listing alternatives (FAKE NETWORK, MOCKED search; nothing leaves the machine).

All buildings, hosts and pages here are synthetic ("Maple Court", Hartford CT); no real property's data is used."""

import hashlib
import json
from pathlib import Path

import httpx2
import pytest

from furnishai.config import get_settings
from furnishai.reader import PublicReader, reader_plans, reader_target_problem, scan_line
from furnishai.safe_fetch import FetchFailed, RawResponse
from furnishai.sources import discover_property, gallery, identity_problem, listing_alternatives, merge_style_variants

from conftest import make_image
from test_building_discovery import BLOCKED, Net, apartment, app_for, html

R = "https://r.jina.ai/"
SITE = "https://www.maplecourt-apts.example"
FP = SITE + "/floorplans"
HOME = SITE + "/"
CDN = "https://media.plancdn.example/image/upload"
S_SMALL = f"{CDN}/q_auto,f_auto,c_limit,w_576,h_260/s3/7/42/510_maple_s(1).png"
S_LARGE = f"{CDN}/q_auto,f_auto,c_limit,w_576/s3/7/42/510_maple_s(1).png"
B_SMALL = f"{CDN}/q_auto,f_auto,c_limit,w_576,h_260/s3/7/42/640_maple_b(2).png"
PRIVATE_IMG = "https://internal.maplecourt-apts.example/plans/c1-floor-plan.png"
PNG = make_image("PNG", size=(320, 220))
CTX = {"property_name": "Maple Court", "city": "Hartford", "state": "CT", "zip": "", "unit_label": "Apt 9Z-PRIVATE",
       "property_url": "", "condition": "either", "fulfillment": "either", "timing": ""}

PLANS_MD = f"""[![Image 1: logo at Maple Court, Hartford](https://media.plancdn.example/image/upload/w_82/s3/7/42/maple_logo.png)]({HOME})
*   [Resident Login](https://maplecourt.portal.example/residentservices/userlogin.aspx)
# Studio, 1 & 2-Bedroom Apartments in Downtown Hartford, CT
![Image 2: rooftop lounge photo](https://media.plancdn.example/image/upload/w_900/s3/7/42/roof.jpg)
## Studio S
*   Studio
*   510 Sq. Ft.
[![Image 3: 1 bedroom 1 bathroom A at Maple Court, Hartford]({S_SMALL}) Studio apartment. Approximately 510 square feet.](javascript:void(0))
[Availability for Studio S]({SITE}/floorplans/studio-s)
## 1 Bedroom 1 Bath B
[![Image 4: 1 bedroom 1 bathroom B at Maple Court]({B_SMALL}) One bedroom apartment.](javascript:void(0))
## 2 Bedroom 2 Bath C
![Image 5: 2 bedroom 2 bath C at Maple Court]({PRIVATE_IMG})
## Studio S
![Image 6: 1 bedroom 1 bathroom A at Maple Court, Hartford]({S_LARGE})
## Similar Properties Nearby
![Image 7: Birch Hall 2 bed floor plan](https://media.plancdn.example/image/upload/w_576/s3/9/9/birch_2bed_floor_plan.png)
"""


def reply(source, body, title="Maple Court | Apartments in Hartford, CT", extra="", published="Mon, 26 Oct 2026 10:00:00 GMT"):
    head = f"Title: {title}\n\nURL Source: {source}\n\n" + (f"Published Time: {published}\n\n" if published else "") + extra
    return RawResponse(200, {"content-type": "text/plain; charset=utf-8"}, (head + "Markdown Content:\n" + body).encode())


def reader_for(net):
    return PublicReader.from_fetcher(net.fetcher())


# ------------------------------------------------------------------ parsing
def test_markdown_urls_keep_balanced_parentheses_and_nested_image_links():
    toks = scan_line(f"[![Image 3: plan A]({S_SMALL}) Studio, approx. 510 sq ft (artist's rendering).](javascript:void(0))"
                     f' and ![x](https://cdn.example/a_(b)_(c).png "title (t)")')
    assert toks[0] == ("image", "Image 3: plan A", S_SMALL)  # not cut at "s(1"
    assert toks[1] == ("link", "Studio, approx. 510 sq ft (artist's rendering).", "javascript:void(0)")
    assert toks[2] == ("image", "x", "https://cdn.example/a_(b)_(c).png")


def test_plan_names_come_from_the_nearest_plan_heading_and_variants_merge():
    imgs, _, unsupported = reader_plans(PLANS_MD, FP)
    assert unsupported == []
    merged = merge_style_variants(imgs)
    names = [m["name"] for m in merged]
    assert names == ["Studio S", "1 Bedroom 1 Bath B", "2 Bedroom 2 Bath C"]  # no logo, photo or other building
    studio = merged[0]
    assert studio["url"] == S_LARGE and studio["variants"] == [S_SMALL, S_LARGE]  # larger, uncropped copy kept
    assert studio["alt"] == "1 bedroom 1 bathroom A at Maple Court, Hartford"  # raw alt kept as provenance
    assert "disagrees; the heading is used" in studio["label"]
    from furnishai.sources import Discovery
    g = gallery(Discovery(plan_images=[{**m, "via": "reader"} for m in merged]), None)
    assert [x["plan_type"] for x in g] == ["studio", "1", "2"]  # a studio never becomes a 1-bed from bad alt text
    assert not any(k in x for x in g for k in ("width_in", "depth_in", "area", "sqft", "size"))  # no geometry from sq ft


def test_reader_targets_are_only_plain_public_building_pages():
    net = Net({}, private_hosts={"intranet.maplecourt-apts.example"})
    ok = lambda u: reader_target_problem(u, net.resolver) is None  # noqa: E731
    assert ok(FP) and ok(HOME) and ok(SITE + "/floorplans/studio-s")
    for bad in ("https://intranet.maplecourt-apts.example/floorplans", "http://localhost/floorplans", "https://169.254.169.254/latest",
                "https://user:pw@www.maplecourt-apts.example/", "https://www.maplecourt-apts.example:8443/floorplans",
                FP + "?token=abc", FP + "?session=1", FP + "?unit=1204", SITE + "/units/1204", SITE + "/apply",
                SITE + "/residents/pay", "https://maplecourt.portal.example/floorplans", SITE + "/account/login",
                "ftp://www.maplecourt-apts.example/", R + FP):
        assert not ok(bad), bad
    assert net.requested == []  # validation never connects


# ------------------------------------------------------------------ discovery with the reader
def test_direct_success_never_uses_the_reader():
    net = Net({FP: html('<img src="https://cdn.example/maple-a1-floorplan.png" alt="A1 floor plan">')})
    d = discover_property(net.fetcher(), FP, building_name="Maple Court", reader=reader_for(net))
    assert d.plan_images and not any(u.startswith(R) for u in net.requested)


def test_homepage_without_plans_follows_one_observed_plan_link_only():
    home_md = (f"# Maple Court\n[Floor Plans]({SITE}/floor-plans) [Apply now]({SITE}/apply) [Pay rent](https://pay.maplecourt-apts.example/)"
               f" [About]({SITE}/about) [Elsewhere](https://other.example/floorplans)\nWelcome to Maple Court in Hartford.")
    net = Net({HOME: BLOCKED, R + HOME: reply(HOME, home_md), R + SITE + "/floor-plans": reply(SITE + "/floor-plans", PLANS_MD)})
    d = discover_property(net.fetcher(), HOME, building_name="Maple Court", reader=reader_for(net))
    assert net.requested == [HOME, R + HOME, R + SITE + "/floor-plans"]  # no guessed paths, apply/pay/about never read
    assert [p.via for p in d.pages] == ["start", "reader", "reader"] and len(d.plan_images) == 3


def test_reader_without_plans_is_honest_and_429_or_timeouts_stop_it():
    net = Net({FP: BLOCKED, R + FP: reply(FP, "# Maple Court\nLuxury living in Hartford. Call us today.")})
    d = discover_property(net.fetcher(), FP, building_name="Maple Court", reader=reader_for(net))
    assert d.plan_images == [] and any("public page reader was also tried and found no plans" in n for n in d.notes)
    net = Net({FP: BLOCKED, R + FP: RawResponse(429, {"content-type": "text/plain"}, b"rate limited")})
    d = discover_property(net.fetcher(), FP, building_name="Maple Court", reader=reader_for(net))
    assert d.pages[-1].status == "rate_limited" and net.requested.count(R + FP) == 1

    class Slow(Net):
        def opener(self, target, headers, timeout, max_bytes):
            if target.host == "r.jina.ai":
                self.requested.append("reader")
                raise FetchFailed("Network error: TimeoutError")
            return super().opener(target, headers, timeout, max_bytes)
    slow = Slow({HOME: BLOCKED})
    d = discover_property(slow.fetcher(), HOME, building_name="Maple Court", reader=reader_for(slow))
    assert d.pages[-1].status == "failed" and "TimeoutError" in d.pages[-1].detail and slow.requested.count("reader") == 1


@pytest.mark.parametrize("bad,why", [
    (reply("https://www.other-property.example/floorplans", PLANS_MD), "different website"),
    (reply(FP, PLANS_MD.replace("Maple Court", "Birch Hall"), title="Birch Hall"), "doesn’t name your building"),
    (reply(FP, "Checking your browser before accessing", title="Just a moment..."), "bot-check"),
    (reply(FP, PLANS_MD, extra="Warning: Target URL returned error 403: Forbidden\n\n"), "couldn't read the page either"),
    (RawResponse(302, {"location": "https://evil.example/x"}, b""), "redirected outside r.jina.ai"),
    (RawResponse(200, {"content-type": "text/html"}, b"<html>not the reader format</html>"), "not allowed"),
])
def test_wrong_or_challenge_reader_replies_are_rejected(bad, why):
    net = Net({FP: BLOCKED, R + FP: bad})
    d = discover_property(net.fetcher(), FP, building_name="Maple Court", reader=reader_for(net))
    assert d.plan_images == [] and why in d.pages[-1].detail and "https://evil.example/x" not in net.requested


def test_policy_blocked_or_private_query_urls_never_reach_the_reader():
    net = Net({}, private_hosts={"www.maplecourt-apts.example"})
    d = discover_property(net.fetcher(), FP, building_name="Maple Court", reader=reader_for(net))
    assert d.pages[0].status == "blocked_by_policy" and net.requested == []
    net = Net({FP + "?token=s3cret": BLOCKED})
    discover_property(net.fetcher(), FP + "?token=s3cret", building_name="Maple Court", reader=reader_for(net))
    assert not any(u.startswith(R) for u in net.requested)


def test_reader_is_on_by_default_without_any_key_and_can_be_turned_off(tmp_path):
    assert get_settings(tmp_path, environ={}).public_reader is True and get_settings(tmp_path, environ={}).portkey_api_key is None
    off = get_settings(tmp_path, environ={"FURNISHAI_PUBLIC_READER": "off"})
    assert off.public_reader is False and off.public_status()["public_reader"] is False
    off.storage_dir = tmp_path / "s"
    from fastapi.testclient import TestClient

    from furnishai.app import create_app
    net = Net({FP: BLOCKED})
    c = TestClient(create_app(off, fetcher=net.fetcher()))
    pid = c.post("/api/projects", json={"name": "x", "room_type": "studio"}).json()["project"]["id"]
    c.post(f"/api/projects/{pid}/property", json={"url": FP})
    assert net.requested == [FP]  # off: no reader request at all


# ------------------------------------------------------------------ end to end: blocked site -> reader -> gallery -> import
def test_blocked_unknown_building_reads_through_reader_then_imports_real_bytes(tmp_path):
    net = Net({FP: BLOCKED, R + FP: reply(FP, PLANS_MD), S_LARGE: RawResponse(200, {"content-type": "image/png"}, PNG)},
              private_hosts={"internal.maplecourt-apts.example"})

    def gateway(request):
        raise AssertionError("no AI search is needed when the reader found plans")
    c, app = app_for(tmp_path, net, gateway)
    a = apartment(c, CTX)
    room1, room2 = a["rooms"][0]["project_id"], a["rooms"][1]["project_id"]
    r = c.post(f"/api/projects/{room1}/buildings/select", json={"kind": "url", "url": FP})
    assert r.status_code == 200, r.text
    d = r.json()["discovery"]
    assert [(p["url"], p["status"], p["via"]) for p in d["pages"]] == [(FP, "blocked_by_site", "start"), (FP, "ok", "reader")]
    rp = d["pages"][1]
    assert rp["final_url"] == FP and rp["reader"]["reader_url"] == R + FP and rp["reader"]["cache_age"] == "unknown"
    assert rp["reader"]["published_time"] == "Mon, 26 Oct 2026 10:00:00 GMT" and d["searched_for_recovery"] is False
    assert [(g["name"], g["plan_type"], g["origin"]) for g in d["gallery"]] == [
        ("Studio S", "studio", "reader"), ("1 Bedroom 1 Bath B", "1", "reader"), ("2 Bedroom 2 Bath C", "2", "reader")]
    assert all(g["evidence_source_id"] == rp["source_id"] for g in d["gallery"]) and d["alternatives"] == []
    assert "Jina Reader" in d["notes"][0] and "refused automated reading" in d["notes"][0]
    assert not any(n.startswith("No property evidence retrieved") for n in d["notes"])
    assert net.requested == [FP, R + FP]  # no image fetched yet, no same-host retries, unit label never sent
    # The reader's raw reply is an immutable source; its URL is the reader's, the page it read is in provenance.
    row = app.state.db.one("SELECT * FROM source_assets WHERE id=?", (rp["source_id"],))
    assert row["kind"] == "property_reader_page" and row["source_url"] == R + FP
    raw = Path(row["storage_path"]).read_bytes()
    assert raw == net.pages[R + FP].body and row["sha256"] == hashlib.sha256(raw).hexdigest()
    prov = json.loads(app.state.db.one("SELECT data FROM source_provenance WHERE source_id=?", (rp["source_id"],))["data"])
    assert prov["url_source"] == FP and prov["target_url"] == FP and prov["service"].startswith("Jina Reader")
    # Import: real image bytes through the SafeFetcher, provenance linked to the reader evidence.
    imp = c.post(f"/api/projects/{room2}/property/plan-image", json={"url": S_LARGE, "discovery_id": d["id"]})
    assert imp.status_code == 200, imp.text
    p = imp.json()["provenance"]
    assert p["via"] == "public page reader" and p["plan_heading"] == "Studio S" and p["reference_plan_name"] == "Studio S"
    assert p["plan_alt_text"] == "1 bedroom 1 bathroom A at Maple Court, Hartford" and p["reader_source_id"] == rp["source_id"]
    assert p["plan_page_url"] == FP and p["image_sha256"] == hashlib.sha256(PNG).hexdigest() and p["plan_type_label"] == "studio"
    src = next(s for s in imp.json()["state"]["sources"] if s["kind"] == "floorplan")
    assert src["source_url"] == S_LARGE and imp.json()["state"]["room"] is None  # nothing auto-read or selected
    assert Path(row["storage_path"]).read_bytes() == raw  # the reader evidence is unchanged
    # A reader-found image on a private host can't be fetched (SafeFetcher refuses before connecting).
    bad = c.post(f"/api/projects/{room2}/property/plan-image", json={"url": PRIVATE_IMG, "discovery_id": d["id"]})
    assert bad.status_code == 422 and PRIVATE_IMG not in net.requested
    assert all("PRIVATE" not in u for u in net.requested)


# ------------------------------------------------------------------ listing-site alternatives
LISTING = "https://www.apartments.com/maple-court-hartford-ct/x7k2/"
OTHER_CITY = "https://www.zillow.com/b/maple-court-springfield-ma/"


def _ev(url, title, cited=""):
    from urllib.parse import urlsplit
    return {"url": url, "title": title, "domain": urlsplit(url).hostname, "cited_text": cited, "file_kind": "page",
            "evidence": ["search source", "citation"], "low_relevance": False}


def test_identity_needs_name_and_location_and_same_name_elsewhere_is_refused():
    args = ("Maple Court", "Hartford", "CT", "")
    assert identity_problem("Maple Court Apartments - Hartford, CT | Apartments.com", "", LISTING, *args) is None
    assert "Hartford" in identity_problem("Maple Court - Springfield, MA", "", OTHER_CITY, *args)
    assert "another state" in identity_problem("Maple Court - Hartford, WI", "Hartford", "https://www.zillow.com/x/", *args)
    assert "doesn’t name" in identity_problem("Birch Hall - Hartford, CT", "", "https://www.zillow.com/y/", *args)
    alts = listing_alternatives([_ev(LISTING, "Maple Court Apartments - Hartford, CT"), _ev(OTHER_CITY, "Maple Court - Springfield, MA"),
                                 _ev("https://www.yelp.com/biz/maple-court-hartford", "Maple Court - Hartford, CT"),
                                 _ev("https://www.apartments.com/maple-court-hartford-ct/x7k2/apply", "Maple Court Hartford CT"),
                                 _ev(SITE + "/", "Maple Court | Hartford, CT")], *args)
    assert [a["url"] for a in alts] == [LISTING] and "not the building’s own website" in alts[0]["why"]


def _search(results):
    return {"id": "resp_maple", "object": "response", "created_at": 1761400000, "status": "completed", "model": "gpt-6-luna",
            "output": [{"type": "web_search_call", "id": "ws", "status": "completed",
                        "action": {"type": "search", "query": "Maple Court Hartford CT", "sources": [{"type": "url", "url": u} for u, _ in results]}},
                       {"type": "message", "id": "m", "role": "assistant", "status": "completed", "content": [{
                           "type": "output_text", "text": "Maple Court in Hartford, CT.",
                           "annotations": [{"type": "url_citation", "start_index": 0, "end_index": 10, "url": u, "title": t}
                                           for u, t in results]}]}],
            "usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 50}}


def test_listing_alternative_is_offered_read_only_on_choice_and_labelled_third_party(tmp_path):
    body = _search([(HOME, "Maple Court Apartments | Hartford, CT"), (LISTING, "Maple Court Apartments - Hartford, CT | Apartments.com"),
                    (OTHER_CITY, "Maple Court - Springfield, MA | Zillow")])
    listing_md = f"# Maple Court Apartments - Hartford, CT\n## Studio S\n![Image 1: Maple Court studio]({S_LARGE})"
    net = Net({HOME: BLOCKED, LISTING: BLOCKED, R + LISTING: reply(LISTING, listing_md, title="Maple Court Apartments - Hartford, CT"),
               S_LARGE: RawResponse(200, {"content-type": "image/png"}, PNG)})
    calls = []

    def gateway(request):
        calls.append(1)
        return httpx2.Response(200, json=body)
    c, app = app_for(tmp_path, net, gateway)
    pid = apartment(c, CTX)["rooms"][0]["project_id"]
    f = c.post(f"/api/projects/{pid}/buildings/find", json={"property_name": "Maple Court", "city": "Hartford", "state": "CT"}).json()
    card = next(w for w in f["web"] if w["url"] == HOME)
    d = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "key": card["key"], "url": HOME}).json()["discovery"]
    assert d["gallery"] == [] and [a["url"] for a in d["alternatives"]] == [LISTING]  # Springfield's same-name page isn't offered
    assert LISTING not in net.requested and R + LISTING not in net.requested  # offered, not fetched
    n_calls = len(calls)
    assert c.post(f"/api/projects/{pid}/place-discovery/{d['id']}/alternative", json={"url": OTHER_CITY}).status_code == 422
    r = c.post(f"/api/projects/{pid}/place-discovery/{d['id']}/alternative", json={"url": LISTING})
    assert r.status_code == 200, r.text
    d2 = r.json()["discovery"]
    assert d2["version"] == d["version"] + 1 and len(calls) == n_calls  # a new version; no extra AI search
    g = d2["gallery"][0]
    assert (g["name"], g["origin"], g["site"], g["plan_type"]) == ("Studio S", "third_party", "apartments.com", "studio")
    assert g["label"].startswith("From apartments.com, a listing site (not the building’s own website)")
    assert net.requested[-2:] == [LISTING, R + LISTING]  # direct first, then the reader; only this page
    old = app.state.db.place_discovery_by_id(d["id"])["data"]
    assert old["gallery"] == [] and old["alternatives"][0].get("tried") is None  # the earlier version is unchanged
    assert c.post(f"/api/projects/{pid}/place-discovery/{d2['id']}/alternative", json={"url": LISTING}).status_code == 409
    imp = c.post(f"/api/projects/{pid}/property/plan-image", json={"url": S_LARGE, "discovery_id": d2["id"]}).json()["provenance"]
    assert imp["via"] == "third-party listing page" and imp["third_party_site"] == "apartments.com"
    assert "not the building’s own website" in imp["caveat"]
    # The read page must be about THIS building in THIS city, or nothing is used.
    net.pages[R + LISTING] = reply(LISTING, listing_md.replace("Hartford, CT", "Springfield, MA"), title="Maple Court - Springfield, MA")
    app.state.reader._cache.clear()  # the reader reuses replies for a few minutes; this simulates a later, different reply
    d3 = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "key": card["key"], "url": HOME}).json()["discovery"]
    r3 = c.post(f"/api/projects/{pid}/place-discovery/{d3['id']}/alternative", json={"url": LISTING}).json()["discovery"]
    assert r3["gallery"] == [] and "another state (MA)" in r3["pages"][-1]["detail"]
    assert any("gave no plans we could use" in n for n in r3["notes"])
