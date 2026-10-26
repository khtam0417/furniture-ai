"""Name search with hostname-only search leads, operator-domain scope, and reader parser edge cases
(FAKE NETWORK, MOCKED gpt-6-luna search; synthetic buildings only; nothing leaves the machine)."""

import json

import httpx2

from furnishai.reader import PublicReader, reader_plans
from furnishai.safe_fetch import RawResponse
from furnishai.sources import (
    Discovery, _has_phrase, building_candidates, discover_property, domain_names_building, gallery, identity_problem,
    merge_style_variants, name_phrases, property_path_base,
)

from conftest import make_image
from test_building_discovery import BLOCKED, Net, apartment, app_for, html
from test_public_reader import reply

R = "https://r.jina.ai/"
SITE = "https://www.412orchardstreet.example"
FP = SITE + "/floorplans"
CDN = "https://media.plancdn.example/image/upload"
PLAN = f"{CDN}/q_auto,c_limit,w_576/s3/4/12/412_orchard_a(1).png"
LISTING = "https://www.apartments.com/412-orchard-street-hartford-ct/q9z/"
GENERIC = "https://www.rentportal-hub.example/apartments/ct/hartford/412-orchard-street/"
PRIVATE = "https://www.412orchard.example/"
INVENTED = SITE + "/secret-offer"
WRONG_CITY = "https://www.412orchardst.example/"
PNG = make_image("PNG", size=(300, 220))
CTX = {"property_name": "412 Orchard Street", "city": "Hartford", "state": "CT", "zip": "", "unit_label": "Apt 3Q-PRIVATE",
       "property_url": "", "condition": "either", "fulfillment": "either", "timing": ""}
OFFICIAL_MD = (f"[![Image 1: logo at 412 Orchard Street, Hartford, 06103](https://media.plancdn.example/image/upload/w_80/logo.png)]({SITE}/)\n"
               "# Studio & 1-Bed Apartments in Downtown Hartford, CT\n"
               f"## Studio A\n*   Studio\n![Image 2: 1 bedroom 1 bathroom at 412 Orchard Street]({PLAN})\n")


def search_body():
    """Only `sources` (titles are bare hostnames, as observed) and a summary with markdown links but NO citations."""
    srcs = [FP, SITE + "/", SITE + "/availableunits", SITE + "/floorplans/studio-a", SITE + "/featuredfloorplans/1-bed-featured",
            LISTING, GENERIC, WRONG_CITY, PRIVATE]
    text = (f"- **[Studio & 1-Bed Apartments | 412 Orchard]({FP})**: official floor plans.\n"
            f"- **[412 Orchard | Move-in offer]({INVENTED})**: a page only the summary mentions.")
    return {"id": "resp_orchard", "object": "response", "created_at": 1761400000, "status": "completed", "model": "gpt-6-luna",
            "output": [{"type": "web_search_call", "id": "ws", "status": "completed",
                        "action": {"type": "search", "query": "412 Orchard Street Hartford CT", "sources": [{"type": "url", "url": u} for u in srcs]}},
                       {"type": "message", "id": "m", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 50}}


def test_hostname_only_official_lead_is_confirmed_from_its_own_page_and_selectable(tmp_path):
    net = Net({FP: BLOCKED, R + FP: reply(FP, OFFICIAL_MD, title="Studio & 1-Bed Apartments in Downtown Hartford, CT"),
               WRONG_CITY: html("<title>412 Orchard St Apartments - Springfield, MA</title><h1>412 Orchard St</h1>"),
               PLAN: RawResponse(200, {"content-type": "image/png"}, PNG)},
              private_hosts={"www.412orchard.example"})
    calls = []

    def gateway(request):
        calls.append(1)
        return httpx2.Response(200, json=search_body())
    c, app = app_for(tmp_path, net, gateway)
    pid = apartment(c, CTX)["rooms"][0]["project_id"]
    q = {"property_name": "412 Orchard Street", "city": "Hartford", "state": "CT"}
    f = c.post(f"/api/projects/{pid}/buildings/find", json=q).json()
    assert len(f["web"]) == 1, f
    card = f["web"][0]
    assert card["name"] == "Studio & 1-Bed Apartments in Downtown Hartford, CT · www.412orchardstreet.example"
    assert card["page_check"]["read_via"] == "public_reader" and "names 412 Orchard Street and Hartford" in card["evidence"][0]
    assert set(card["urls"]) >= {FP, SITE + "/", SITE + "/availableunits", SITE + "/floorplans/studio-a"}  # one card per property
    srcs = {s["url"]: s for s in f["sources"]}
    assert LISTING in srcs and GENERIC in srcs  # listing and unrelated generic domains stay sources, never fetched
    assert srcs[WRONG_CITY]["source_reason"].startswith("We read its page, but it doesn’t mention Hartford")
    assert srcs[PRIVATE]["source_reason"] == "Only a website name; this result doesn’t identify a building."  # beyond the 2-lead cap
    assert INVENTED not in json.dumps(f) and INVENTED not in net.requested  # summary-only URLs are never used
    assert GENERIC not in net.requested and LISTING not in net.requested and PRIVATE not in net.requested
    assert net.requested == [FP, R + FP, WRONG_CITY] and all("PRIVATE" not in u for u in net.requested)
    # Asking again reuses the saved search and our saved page checks: no new requests of any kind.
    c.post(f"/api/projects/{pid}/buildings/find", json=q)
    assert len(calls) == 1 and net.requested == [FP, R + FP, WRONG_CITY]
    # The user picks it; validation accepts it deterministically, and the plan lookup reuses the reader's copy.
    r = c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "key": card["key"], "url": card["url"], **q})
    assert r.status_code == 200, r.text
    d = r.json()["discovery"]
    assert d["building"]["name"] == card["name"] and [g["name"] for g in d["gallery"]] == ["Studio A"]
    assert net.requested.count(R + FP) == 1 and net.requested[-1] == FP  # one direct retry (403), no second reader call
    # A source card (listing) still can't be selected as a building.
    assert c.post(f"/api/projects/{pid}/buildings/select", json={"kind": "web", "url": LISTING, **q}).status_code == 422


def test_private_or_unsafe_search_lead_is_refused_before_any_request():
    from furnishai.sources import check_lead_page
    net = Net({}, private_hosts={"www.412orchard.example"})
    card = {"key": "web:x", "url": PRIVATE, "site": "www.412orchard.example"}
    chk, raw = check_lead_page(net.fetcher(), PublicReader.from_fetcher(net.fetcher()), card, "412 Orchard Street", "Hartford", "CT", "")
    assert chk["ok"] is False and "not a public address" in chk["problem"] and raw is None and net.requested == []


def test_name_phrases_allow_the_short_official_form_but_not_another_building():
    ph = name_phrases("412 Orchard Street")
    assert _has_phrase(ph, "Welcome to 412 Orchard, Hartford") and _has_phrase(ph, "412 Orchard St")
    assert _has_phrase(ph, "412 Orchard Square, Indianapolis")  # the short form matches "412 Orchard" here…
    assert identity_problem("412 Orchard Square | Indianapolis, IN", "Studios at 412 Orchard Square", "https://412orchardsquare.example/",
                            "412 Orchard Street", "Hartford", "CT", "")  # …but the city/state never do
    assert not _has_phrase(name_phrases("360 State Street"), "Apartments at 360 Market Square in Indianapolis")
    assert not _has_phrase(name_phrases("Elm Street"), "Elm Hall")  # a 2-word name keeps its street type
    assert domain_names_building("www.412orchardstreet.example", "412 Orchard Street")
    assert not domain_names_building("www.rentportal-hub.example", "412 Orchard Street")
    assert not domain_names_building("360marketsquare.com", "360 State Street")


def test_plan_and_unit_subpages_belong_to_one_property():
    assert {property_path_base(SITE + p) for p in ("/floorplans", "/", "/availableunits", "/floorplans/studio-a",
                                                   "/featuredfloorplans/1-bed-featured", "/amenities/floorplans")} == {"/"}
    op = "https://www.oprealty.example/ct/hartford/412-orchard/"
    assert property_path_base(op + "apartment/U-0042/") == property_path_base(op + "floor-plans/") == "/ct/hartford/412-orchard"
    assert property_path_base("https://www.oprealty.example/ma/springfield/birch-hall/") != property_path_base(op)


def test_operator_domain_reader_copy_of_another_property_is_rejected_even_if_its_footer_names_ours():
    op = "https://www.oprealty.example/ct/hartford/412-orchard/"
    other = "https://www.oprealty.example/ma/springfield/birch-hall/"
    footer = "\n## Similar Properties Nearby\n[412 Orchard Street, Hartford](" + op + ")\n"
    md = f"# Birch Hall\n## Plan B2\n![Image 1: Birch Hall B2 floor plan]({CDN}/w_576/b2_floorplan.png)" + footer
    net = Net({op: BLOCKED, R + op: reply(other, md, title="Birch Hall | Springfield, MA")})
    d = discover_property(net.fetcher(), op, building_name="412 Orchard Street", reader=PublicReader.from_fetcher(net.fetcher()))
    assert d.plan_images == [] and "a different property’s page" in d.pages[-1].detail
    # Same property path, but the building is only named in a related-properties footer: rejected as well.
    net2 = Net({op: BLOCKED, R + op: reply(op, md, title="Birch Hall | Springfield, MA")})
    d2 = discover_property(net2.fetcher(), op, building_name="412 Orchard Street", reader=PublicReader.from_fetcher(net2.fetcher()))
    assert d2.plan_images == [] and "doesn’t name your building" in d2.pages[-1].detail
    # A chosen building page whose reader copy links another building's floor plans doesn't follow that link.
    home_md = f"# 412 Orchard\nWelcome to 412 Orchard Street in Hartford.\n[Floor plans]({other}floor-plans/) [Our plans]({op}floor-plans/)"
    net3 = Net({op: BLOCKED, R + op: reply(op, home_md), R + op + "floor-plans/": reply(op + "floor-plans/", OFFICIAL_MD)})
    d3 = discover_property(net3.fetcher(), op, building_name="412 Orchard Street", reader=PublicReader.from_fetcher(net3.fetcher()))
    assert R + other + "floor-plans/" not in net3.requested and R + op + "floor-plans/" in net3.requested and d3.plan_images


# ------------------------------------------------------------------ reader parser: listing-card and SVG sites (synthetic)
CARD_IMG = "https://resource.plancdn.example//floorplans/ct77/s8-628sf-apt264.jpg/1024/768"
CARD_IMG2 = "https://resource.plancdn.example//floorplans/ct77/s3-469sf(1).jpg/1024/768"
CARD_IMG3 = "https://resource.plancdn.example//floorplans/ct77/a5-721sf-apt421.jpg/1024/768"
PHOTO = "https://photos.cdn-resizer.example/resizer/v2/ABC.jpg?auth=x&width=750&height=393"
CARDS_MD = f"""# Willow Point
##### studio From
[$2,600](#pricing)
##### 2 bedroom From
[$4,200](#pricing)
![Image 21: Chill terrace with string lights.]({PHOTO})
[![Image 22: Portrait of a young man with sunglasses.]({PHOTO}&p=2) ### Seek Neighborhood copy](https://www.willow.example/ava)
![Image 25: Floorplan]({CARD_IMG})
## [002-264 Willow Point](https://www.willow.example/ct/willow-point/apartment/WP-002-264/)
Studio • 1 bath • 628 sqft• Available Furnished
![Image 26: Floorplan]({CARD_IMG2})
## [001-138 Willow Point](https://www.willow.example/ct/willow-point/apartment/WP-001-138/)
Studio • 1 bath • 469 sqft
![Image 30: Floorplan]({CARD_IMG3})
Special
Available to Tour
## [002-561 Willow Point](https://www.willow.example/ct/willow-point/apartment/WP-002-561/)
1 bed • 1 bath • 721 sqft
"""


def test_category_headings_and_marketing_photos_never_become_plans_and_floorplan_images_always_count():
    imgs, _, unsupported = reader_plans(CARDS_MD, "https://www.willow.example/ct/willow-point/")
    plans = merge_style_variants(imgs)
    assert [p["url"] for p in plans] == [CARD_IMG, CARD_IMG2, CARD_IMG3]  # the first real plan is kept, no photos
    assert [p["name"] for p in plans] == ["Studio • 1 bath · s8-628sf-apt264", "Studio • 1 bath · s3-469sf(1)", "1 bed • 1 bath · a5-721sf-apt421"]
    g = gallery(Discovery(plan_images=[{**p, "via": "reader"} for p in plans]), None)
    assert [x["plan_type"] for x in g] == ["studio", "studio", "1"] and unsupported == []


def test_plan_image_whose_url_continues_after_the_extension_imports_by_its_real_media_type(settings):
    from fastapi.testclient import TestClient

    from furnishai.app import create_app
    jpg = make_image("JPEG", size=(400, 300))
    net = Net({CARD_IMG: RawResponse(200, {"content-type": "image/jpeg"}, jpg),
               CARD_IMG2: RawResponse(200, {"content-type": "text/html"}, b"<html>not an image</html>")})
    c = TestClient(create_app(settings, fetcher=net.fetcher()))
    pid = c.post("/api/projects", json={"name": "x", "room_type": "studio"}).json()["project"]["id"]
    ok = c.post(f"/api/projects/{pid}/property/plan-image", json={"url": CARD_IMG})
    assert ok.status_code == 200 and ok.json()["provenance"]["image_sha256"]
    bad = c.post(f"/api/projects/{pid}/property/plan-image", json={"url": CARD_IMG2})
    assert bad.status_code == 422 and "not allowed" in bad.json()["detail"]  # the ".jpg" in the path proves nothing


MARKET_FP = "https://www.cedarsquare.example/floorplans/"
MARKET_MD = f"""[![Image 1: Cedar Square](https://www.cedarsquare.example/assets/logo/logo_main.svg)](https://www.cedarsquare.example/)
![Image 2: bedroom with large windows](https://www.cedarsquare.example/assets/images/cache/floorplan_banner_cedar_3012.jpg)
## Floorplans
[![Image 3: 1S North - Studio floorplan layout with 1 bathroom](https://www.cedarsquare.example/assets/images/1S.svg) 1S North](https://www.cedarsquare.example/floorplans/1s/)
[![Image 4: 2E West - 2 bedroom floorplan layout with 2 bathrooms](https://www.cedarsquare.example/assets/images/2E.svg) 2E West](https://www.cedarsquare.example/floorplans/2e/)
"""


def test_floorplan_banner_photo_is_not_a_plan_and_svg_plans_are_reported_unsupported(settings):
    imgs, _, unsupported = reader_plans(MARKET_MD, MARKET_FP)
    assert imgs == [] and [u["url"].rsplit("/", 1)[-1] for u in unsupported] == ["1S.svg", "2E.svg"]
    net = Net({MARKET_FP: BLOCKED, R + MARKET_FP: reply(MARKET_FP, MARKET_MD, title="Cedar Square | Hartford, CT")})
    d = discover_property(net.fetcher(), MARKET_FP, building_name="Cedar Square", reader=PublicReader.from_fetcher(net.fetcher()))
    assert d.plan_images == [] and len(d.unsupported_plans) == 2
    assert any(n.startswith("Unsupported plan format: 2 floor-plan drawings") and "can’t import" in n for n in d.notes)
    assert not any("Found" in n for n in d.notes)  # never claims plans were found
    from fastapi.testclient import TestClient

    from furnishai.app import create_app
    net2 = Net({"https://www.cedarsquare.example/assets/images/1S.svg": RawResponse(200, {"content-type": "image/svg+xml"}, b"<svg/>")})
    c = TestClient(create_app(settings, fetcher=net2.fetcher()))
    pid = c.post("/api/projects", json={"name": "x", "room_type": "studio"}).json()["project"]["id"]
    assert c.post(f"/api/projects/{pid}/property/plan-image", json={"url": unsupported[0]["url"]}).status_code == 422
