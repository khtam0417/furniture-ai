"""Recovery when a property website blocks automated reading (FAKE NETWORK, MOCKED AI; nothing leaves the machine)."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from furnishai.app import create_app
from furnishai.safe_fetch import RawResponse, SafeFetcher
from furnishai.sources import REFERENCES, discover_property, reference_directory_for

from conftest import make_image

AUDUBON = next(d for d in REFERENCES if d["_file"] == "theaudubonapts.json")
REF_URLS = [p["url"] for p in AUDUBON["plans"]]


class Net:
    """Fake public network. Records every requested URL."""

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


BLOCKED = RawResponse(403, {"content-type": "text/html"}, b"challenge")


def test_reference_directory_is_complete_and_has_no_invented_fields():
    assert len(AUDUBON["plans"]) == 22 and len(set(REF_URLS)) == 22
    assert all(u.startswith("https://resource.rentcafe.com/") for u in REF_URLS)
    assert all(set(p) == {"name", "alt", "url"} for p in AUDUBON["plans"])  # no prices, sizes or availability
    assert AUDUBON["source_page"] == "https://www.theaudubonapts.com/floorplans" and AUDUBON["observed_at"].startswith("2026-10-26")


def test_known_host_403_offers_all_checked_plans_and_keeps_failure_honest():
    net = Net({"https://www.theaudubonapts.com/floorplans": BLOCKED})
    d = discover_property(net.fetcher(), "https://www.theaudubonapts.com/floorplans")
    assert d.pages[0].status == "blocked_by_site"  # the live failure is still reported
    assert d.plan_images == [] and d.reference is not None
    assert len(d.reference["plans"]) == 22 and [p["url"] for p in d.reference["plans"]] == REF_URLS  # not truncated
    assert all(p["label"] == "Previously checked official plan" for p in d.reference["plans"])
    assert "not current availability" in d.notes[-1] and d.website == "https://www.theaudubonapts.com/floorplans"
    assert net.requested == ["https://www.theaudubonapts.com/floorplans"]  # no image or other requests made


@pytest.mark.parametrize("url,ok", [
    ("https://www.theaudubonapts.com/", True), ("https://theaudubonapts.com/floorplans/", True),
    ("https://www.theaudubonapts.com/floorplans/studio-s1", True), ("https://www.theaudubonapts.com/about", False),
    ("https://theaudubonapts.com.evil.example/floorplans", False), ("https://evil-theaudubonapts.com/floorplans", False),
    ("https://portal.theaudubonapts.com/floorplans", False), ("https://www.theaudubonapts.com:8080/floorplans", False),
    ("https://user:pw@www.theaudubonapts.com/floorplans", False), ("ftp://www.theaudubonapts.com/floorplans", False),
    ("https://www.theaudubonapts.com/floorplans/../admin", False),
])
def test_reference_matching_is_exact(url, ok):
    assert (reference_directory_for(url) is not None) is ok


def test_unrelated_blocked_site_gets_no_directory():
    net = Net({"https://www.other-apts.example/floorplans": BLOCKED})
    d = discover_property(net.fetcher(), "https://www.other-apts.example/floorplans")
    assert d.reference is None and d.website == "https://www.other-apts.example/floorplans"


def test_policy_blocked_known_host_gets_no_directory_or_link():
    net = Net({}, private_hosts={"www.theaudubonapts.com"})  # DNS points at a private address
    d = discover_property(net.fetcher(), "https://www.theaudubonapts.com/floorplans")
    assert d.pages[0].status == "blocked_by_policy" and d.reference is None and d.website is None


def test_live_success_is_preferred_over_the_directory():
    page = b'<html><body><img src="https://cdn.example/a1-floorplan.png" alt="A1 floor plan"></body></html>'
    net = Net({"https://www.theaudubonapts.com/floorplans": RawResponse(200, {"content-type": "text/html"}, page)})
    d = discover_property(net.fetcher(), "https://www.theaudubonapts.com/floorplans")
    assert d.plan_images and d.reference is None


def test_live_pdf_candidate_is_not_treated_as_no_plans():
    page = b'<html><body><a href="/files/audubon-floor-plans.pdf">Floor plans (PDF)</a></body></html>'
    net = Net({"https://www.theaudubonapts.com/floorplans": RawResponse(200, {"content-type": "text/html"}, page)})
    d = discover_property(net.fetcher(), "https://www.theaudubonapts.com/floorplans")
    assert d.plan_pdfs == ["https://www.theaudubonapts.com/files/audubon-floor-plans.pdf"] and d.reference is None
    assert any("PDF plan reading is NOT implemented" in n for n in d.notes)  # the honest PDF limit stays


def test_live_page_without_candidates_falls_back_to_directory():
    net = Net({"https://www.theaudubonapts.com/floorplans": RawResponse(200, {"content-type": "text/html"}, b"<p>Loading...</p>")})
    d = discover_property(net.fetcher(), "https://www.theaudubonapts.com/floorplans")
    assert d.pages[0].status == "ok" and d.reference and len(d.reference["plans"]) == 22


def _client(settings, net, model=None):
    return TestClient(create_app(settings, fetcher=net.fetcher(), test_model=model))


def test_importing_a_checked_reference_records_separate_provenance(settings):
    png = make_image("PNG", size=(400, 300))
    net = Net({"https://www.theaudubonapts.com/floorplans": BLOCKED,
               REF_URLS[3]: RawResponse(200, {"content-type": "image/png"}, png)})
    c = _client(settings, net)
    pid = c.post("/api/projects", json={"name": "A", "room_type": "studio"}).json()["project"]["id"]
    d = c.post(f"/api/projects/{pid}/property", json={"url": "https://www.theaudubonapts.com/floorplans"}).json()["discovery"]
    assert d["reference"]["plans"][3]["url"] == REF_URLS[3] and d["live_ok"] is False
    r = c.post(f"/api/projects/{pid}/property/plan-image", json={"url": REF_URLS[3]}).json()
    src = next(s for s in r["state"]["sources"] if s["kind"] == "floorplan")
    prov = src["provenance"]
    assert prov["via"] == "checked reference directory" and prov["reference_plan_name"] == AUDUBON["plans"][3]["name"]
    assert prov["reference_source_page"] == AUDUBON["source_page"] and prov["reference_observed_at"] == AUDUBON["observed_at"]
    assert prov["image_retrieved_at"] == src["retrieved_at"] != AUDUBON["observed_at"]  # retrieval date kept separate
    assert src["source_url"] == REF_URLS[3] and "not proof" in prov["caveat"]
    assert r["state"]["room"] is None  # nothing auto-selected or analyzed


def test_ordinary_import_does_not_claim_reference_provenance(settings):
    url = "https://cdn.example/plans/b2.png"
    net = Net({url: RawResponse(200, {"content-type": "image/png"}, make_image("PNG"))})
    c = _client(settings, net)
    pid = c.post("/api/projects", json={"name": "B", "room_type": "bedroom"}).json()["project"]["id"]
    src = next(s for s in c.post(f"/api/projects/{pid}/property/plan-image", json={"url": url}).json()["state"]["sources"]
               if s["kind"] == "floorplan")
    assert src["provenance"]["via"] == "property discovery" and "reference_source_page" not in src["provenance"]


def test_blocked_lookup_then_own_upload_and_analysis_continue_without_more_website_requests(settings):
    net = Net({"https://www.theaudubonapts.com/floorplans": BLOCKED})
    analysis = {"room_type_seen": "bedroom",
                "floorplan_readings": [{"photo_index": 0, "room_label": "Bedroom", "dimension_text": "10' x 12'"}]}
    c = _client(settings, net, TestModel(custom_output_args=analysis))
    pid = c.post("/api/projects", json={"name": "Mine", "room_type": "bedroom"}).json()["project"]["id"]
    c.post(f"/api/projects/{pid}/property", json={"url": "https://www.theaudubonapts.com/floorplans"})
    before = list(net.requested)
    up = c.post(f"/api/projects/{pid}/uploads", data={"kind": "floorplan"},
                files=[("files", ("my-plan-screenshot.png", make_image("PNG", size=(500, 400)), "image/png"))]).json()
    assert up["results"][0]["ok"] and any(s["kind"] == "floorplan" and s["derivative"] for s in up["state"]["sources"])
    st = c.post(f"/api/projects/{pid}/analyze", json={}).json()["state"]
    sugg = st["room"]["data"]["plan_dimension_suggestions"]
    assert [s["dimension_text"] for s in sugg] == ["10' x 12'"]
    assert st["room"]["data"]["room"]["scale_status"] == "unknown"  # nothing auto-selected
    assert net.requested == before  # no further website requests after the blocked lookup
