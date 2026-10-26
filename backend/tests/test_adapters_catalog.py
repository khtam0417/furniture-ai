"""Acceptance 11 (snapshot facts, never generated) plus the independent-review regressions."""

import json
from datetime import date

import pytest

from furnishai import adapters
from furnishai.catalog import is_stale, load_catalog, mattress_compatibility, price_to_cents, snapshot_from_facts
from furnishai.config import REPO_ROOT


def page(products, text="", extra=""):
    ld = "".join(f'<script type="application/ld+json">{json.dumps(p)}</script>' for p in products)
    return f"<html><head><title>T</title>{ld}</head><body><p>{text}</p>{extra}</body></html>".encode()


def test_unitless_dimensions_stay_unknown():
    f = adapters.generic("https://shop.example/p", page([], "Desk 150 W x 60 D, great deal"))
    assert f.width_in is None and f.depth_in is None


def test_centimeters_converted_and_inches_kept():
    f = adapters.generic("https://shop.example/p", page([], "Size: 150 cm W x 60 cm D"))
    assert f.width_in.value == pytest.approx(59.055, abs=0.01) and f.depth_in.value == pytest.approx(23.622, abs=0.01)
    g = adapters.generic("https://shop.example/q", page([], 'Size: 40" W x 20" D'))
    assert (g.width_in.value, g.depth_in.value) == (40.0, 20.0)


@pytest.mark.parametrize("url", ["https://evil-ikea.com/us/en/p/x/", "https://ikea.com.evil.example/us/en/p/x/",
                                 "https://notikea.com/us/en/p/x/", "https://www.ikea.com/gb/en/p/x/"])
def test_lookalike_or_non_us_hosts_do_not_get_retailer_adapter(url):
    assert adapters.adapter_for(url) is adapters.generic


def test_real_hosts_get_adapters():
    assert adapters.adapter_for("https://www.ikea.com/us/en/p/micke-desk-white-80213074/") is adapters.ikea
    assert adapters.adapter_for("https://www.target.com/p/x/-/A-1") is adapters.target
    assert adapters.adapter_for("https://faketarget.com/p/x") is adapters.generic


def test_imageobject_and_mpn_extracted():
    url = "https://shop.example/p/1"
    prod = {"@type": "Product", "name": "Desk", "mpn": "123.456.78", "url": url,
            "image": [{"@type": "ImageObject", "contentUrl": "https://img.example/a.jpg"}],
            "offers": {"@type": "Offer", "price": "99.00", "priceCurrency": "USD"}}
    f = adapters.generic(url, page([prod]))
    assert f.images == ["https://img.example/a.jpg"] and f.sku.value == "123.456.78" and f.price_usd.value == "99.00"


def test_product_identity_must_match_page():
    a = {"@type": "Product", "name": "Other A", "url": "https://shop.example/p/a", "offers": {"price": "10", "priceCurrency": "USD"}}
    b = {"@type": "Product", "name": "Other B", "url": "https://shop.example/p/b", "offers": {"price": "20", "priceCurrency": "USD"}}
    f = adapters.generic("https://shop.example/p/c", page([a, b]))
    assert f.price_usd is None and any("identity not confirmed" in n for n in f.notes)


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "1e9", "1E+400", "-5", "12.345", "", "abc", True, "99999999"])
def test_bad_prices_rejected_without_exceptions(raw):
    assert price_to_cents(raw) is None


def test_exact_cents():
    assert price_to_cents("219") == 21900 and price_to_cents("109.99") == 10999 and price_to_cents("0.10") == 10


def test_nonfinite_price_in_page_is_ignored():
    prod = {"@type": "Product", "name": "X", "url": "https://shop.example/p", "offers": {"price": "NaN", "priceCurrency": "USD"}}
    f = adapters.generic("https://shop.example/p", page([prod]))
    snap = snapshot_from_facts(f, "desk", "0" * 64, "2026-10-24T00:00:00+00:00")
    assert snap["price_cents"] is None and snap["status"] == "incomplete"


def test_ikea_measurements_use_overall_not_package_size():
    html = ('<script type="application/ld+json">{"@type":"Product","name":"MALM Bed frame - white Queen","sku":"1",'
            '"url":"https://www.ikea.com/us/en/p/malm-1/","offers":{"price":"249","priceCurrency":"USD"}}</script>'
            '"measurements":[{"measure":"83 1/8 \\"","name":"Length"},{"measure":"65 \\"","name":"Width"},'
            '{"measure":"79 1/2 \\"","name":"Mattress length"},{"measure":"59 7/8 \\"","name":"Mattress width"}]'
            ',"packaging":{"measurements":[{"label":"Width","text":"30 ½ \\""}]}'
            '<p>Slatted bed base and mattress sold separately.</p>')
    f = adapters.ikea("https://www.ikea.com/us/en/p/malm-1/", html.encode())
    snap = snapshot_from_facts(f, "bed_frame", "0" * 64, "2026-10-24T00:00:00+00:00")
    assert (snap["width_in"], snap["depth_in"]) == (65.0, 83.125)
    assert snap["includes"] == {"slats": False, "mattress": False}
    assert snap["nominal_size"] == "queen" and snap["status"] == "verified"


def test_mattress_compatibility_needs_documented_dimensions():
    frame = {"mattress_size_text": '59 7/8 " x 79 1/2 "', "nominal_size": "queen"}
    good = {"width_in": 59.875, "depth_in": 79.5, "nominal_size": "queen"}
    other_brand = {"width_in": 60.0, "depth_in": 80.0, "nominal_size": "queen"}
    wrong = {"width_in": 53.0, "depth_in": 75.0, "nominal_size": "queen"}  # same label, different size
    assert mattress_compatibility(good, frame) == "compatible"
    assert mattress_compatibility(other_brand, frame) == "compatible"  # within 1 in tolerance
    assert mattress_compatibility(wrong, frame) == "incompatible"
    assert mattress_compatibility(good, {"nominal_size": "queen"}) == "unverified"  # label alone is not proof


def test_stale_flag():
    assert is_stale({"checked_at": "2026-09-01T00:00:00+00:00"}, today=date(2026, 10, 24))
    assert not is_stale({"checked_at": "2026-10-24T00:00:00+00:00"}, today=date(2026, 10, 24))
    assert is_stale({"checked_at": None})


def test_shipped_catalog_contract():
    products = load_catalog(REPO_ROOT / "data" / "catalog" / "products.json")
    assert len(products) >= 30
    for p in products:
        assert p["url"].startswith("https://") and p["checked_at"] and p["source_sha256"]
        if p["status"] == "verified":
            assert p["price_cents"] is not None and p["width_in"] and p["depth_in"]
            assert "price_usd" in p["evidence"] and "width_in" in p["evidence"]
        else:
            assert p["missing"]
    assert any(p["status"] == "incomplete" for p in products)
