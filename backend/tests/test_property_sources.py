"""Property floor-plan discovery on small HTML fragments shaped like real sites (FAKE NETWORK; no real pages stored)."""

from furnishai.html_extract import best_image, extract, image_candidates, unwrap_image_proxy
from furnishai.safe_fetch import RawResponse, SafeFetcher
from furnishai.sources import discover_property


def fetcher(pages):
    def opener(target, headers, timeout, max_bytes):
        url = f"{target.scheme}://{target.host}{target.path}"
        body = pages.get(url)
        return RawResponse(200, {"content-type": "text/html"}, body) if body else RawResponse(404, {"content-type": "text/html"}, b"nf")
    return SafeFetcher(resolver=lambda h, p: ["93.184.216.34"], opener=opener)


def test_view_plan_query_link_is_followed_and_plan_page_image_found():
    """Shape of bulldogapartments.com: anchor 'View Plan' -> '?bPopup=1&f=1&fp=…'; child image alt 'Small Studio Image'."""
    home = b"""<html><body><img src="https://cdn.example/pool.jpg" alt="Pool deck">
      <img src="https://cdn.example/logo.png" alt="Bulldog logo">
      <a href="?bPopup=1&f=1&fp=mgpfmdoju">View Plan</a><a href="/contact">Contact</a></body></html>"""
    child = b"""<html><body><img src="https://cdn.example/plans/mgpfmdoju.jpg" alt="Small Studio Image">
      <img src="https://cdn.example/icons/close.svg" alt="close"></body></html>"""
    pages = {"https://www.bulldog.example/": home, "https://www.bulldog.example/?bPopup=1&f=1&fp=mgpfmdoju": child}
    d = discover_property(fetcher(pages), "https://www.bulldog.example/")
    urls = [p.url for p in d.pages]
    assert "https://www.bulldog.example/?bPopup=1&f=1&fp=mgpfmdoju" in urls
    (c,) = d.plan_images
    assert c["url"] == "https://cdn.example/plans/mgpfmdoju.jpg" and c["kind"] == "plan_page_image"
    assert "may be a photo" in c["label"]  # honest: matched by page context, not proven a plan
    assert any("SAMPLE plans" in n for n in d.notes)


def test_next_image_wrapper_with_unit_size_label_is_detected_and_unwrapped():
    """Shape of howeplace.com/apartments/studio/s1/: Next.js image proxy around a wp.propertyjs.app PNG."""
    inner = "https%3A%2F%2Fwp.propertyjs.app%2Fwp-content%2Fuploads%2FHowe-0x1-365-sqft-S1.png"
    page = f"""<html><body>
      <img alt="Howe 0x1 365 sqft S1" src="/_next/image?url={inner}&w=1080&q=75"
           srcset="/_next/image?url={inner}&w=640&q=75 640w, /_next/image?url={inner}&w=1080&q=75 1080w">
      <img alt="Lobby" src="https://cdn.example/lobby.jpg"><img alt="" src="https://cdn.example/icon-wifi.svg">
    </body></html>""".encode()
    d = discover_property(fetcher({"https://www.howe.example/apartments/studio/s1/": page}),
                          "https://www.howe.example/apartments/studio/s1/")
    assert [c["url"] for c in d.plan_images] == ["https://wp.propertyjs.app/wp-content/uploads/Howe-0x1-365-sqft-S1.png"]
    assert d.plan_images[0]["kind"] == "unit_size_label"


def test_ordinary_apartment_photos_are_not_plans_off_plan_pages():
    page = b"""<html><body><img src="https://cdn.example/studio-living.jpg" alt="Studio living room">
      <img src="https://cdn.example/gym.jpg" alt="Fitness center"></body></html>"""
    d = discover_property(fetcher({"https://www.site.example/": page}), "https://www.site.example/")
    assert d.plan_images == []


def test_srcset_prefers_uncropped_reference_actually_on_the_page():
    """Shape of Yale housing pages: cropped 3_2_320 thumbnail first, uncropped max_width_320 later in srcset."""
    html = """<img alt="Whitehall floor plan" src="https://housing.example/files/styles/3_2_320/public/whitehall.jpg"
      srcset="https://housing.example/files/styles/3_2_320/public/whitehall.jpg 320w,
              https://housing.example/files/styles/max_width_320/public/whitehall.jpg 320w">"""
    ev = extract(html, "https://housing.example/")
    assert ev.images[0][0] == "https://housing.example/files/styles/max_width_320/public/whitehall.jpg"
    assert len(ev.image_details[0]["candidates"]) == 2  # nothing invented beyond what the page references
    assert best_image([("https://a.example/s/640.jpg", 640), ("https://a.example/s/1280.jpg", 1280)]).endswith("1280.jpg")


def test_repeated_drupal_style_variants_across_elements_merge_to_uncropped():
    """Shape of the real Yale housing pages: a cropped gallery thumbnail and a separate uncropped modal image of the
    same public file, plus a different room plan that must NOT be merged even with a similar alt."""
    page = b"""<html><body><h2>Floor plans</h2>
      <img alt="Whitehall floor plan" src="https://housing.example/sites/default/files/styles/3_2_2400/public/2026-06/whitehall_floor.jpg?itok=AbC1">
      <div class="modal"><img alt="Whitehall floor plan" src="https://housing.example/sites/default/files/styles/max_width_960/public/2026-06/whitehall_floor.jpg?itok=XyZ9"></div>
      <img alt="Whitehall floor plan" src="https://housing.example/sites/default/files/styles/3_2_2400/public/2026-06/whitehall_floor_b.jpg?itok=Q1">
      <img alt="York-Crown floor plan" src="https://cdn.other.example/plans/york_crown_floor.jpg">
    </body></html>"""
    d = discover_property(fetcher({"https://housing.example/floorplans/": page}), "https://housing.example/floorplans/")
    urls = [c["url"] for c in d.plan_images]
    assert "https://housing.example/sites/default/files/styles/max_width_960/public/2026-06/whitehall_floor.jpg?itok=XyZ9" in urls
    assert not any("3_2_2400/public/2026-06/whitehall_floor.jpg" in u for u in urls)  # cropped twin merged away
    merged = next(c for c in d.plan_images if "whitehall_floor.jpg" in c["url"])
    assert len(merged["variants"]) == 2  # both referenced URLs kept for review; none constructed
    assert any("whitehall_floor_b.jpg" in u for u in urls)  # different file, same alt: kept separately
    assert any("york_crown_floor.jpg" in u for u in urls) and len(urls) == 3


def test_picture_sources_are_considered_with_the_img_alt():
    html = """<picture><source srcset="https://a.example/plan-1600.webp 1600w"><img src="https://a.example/plan-400.jpg" alt="S2 floor plan"></picture>"""
    assert extract(html, "https://a.example/").images == [("https://a.example/plan-1600.webp", "S2 floor plan")]


def test_unsafe_or_inline_references_are_never_candidates():
    assert unwrap_image_proxy("https://x.example/_next/image?url=javascript%3Aalert(1)&w=10", "https://x.example/") == \
        "https://x.example/_next/image?url=javascript%3Aalert(1)&w=10"
    assert unwrap_image_proxy("https://x.example/_next/image?url=%2F%2Fevil.example%2Fa.png", "https://x.example/").startswith("https://x.example/")
    cands = image_candidates({"src": "data:image/png;base64,AAAA", "srcset": "javascript:alert(1) 2x, /ok-plan.png 1x"}, "https://x.example/")
    assert cands == [("https://x.example/ok-plan.png", 1000)]


def test_candidates_are_bounded_and_deduplicated():
    imgs = "".join(f'<img src="https://cdn.example/u{i}.jpg" alt="Studio {i}">' for i in range(30))
    dup = '<img src="https://cdn.example/fp-a.png" alt="A1 floor plan">' * 5
    page = f"<html><body>{dup}{imgs}</body></html>".encode()
    d = discover_property(fetcher({"https://www.site.example/floorplans/": page}), "https://www.site.example/floorplans/")
    kinds = [c["kind"] for c in d.plan_images]
    assert kinds.count("named_floor_plan") == 1 and kinds.count("plan_page_image") <= 6 and len(d.plan_images) <= 12
    assert kinds[0] == "named_floor_plan"  # strongest evidence first
