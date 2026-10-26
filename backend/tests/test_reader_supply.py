"""Approved resale listings through the public page reader, listing identity, challenges, honest targets, style cues and
design identity (FAKE NETWORK; DETERMINISTIC). The AptDeco fixture is a sanitized, trimmed copy of a real public page
structure (seller name, notes and contact links removed)."""

from datetime import date

from conftest import product
from test_design_refine import ONE_BED, vmap
from test_public_reader import reply
from test_resale_trust import ld_page, prod
from test_shopping_flow import HTML, Net

from furnishai.design import (
    Design, DesignPrefs, arrange, default_pieces, design_key, planning_targets, style_fit,
)
from furnishai.reader import PublicReader
from furnishai.safe_fetch import RawResponse
from furnishai.sources import import_used_listing, parse_aptdeco_copy

R = "https://r.jina.ai/"
URL = "https://www.aptdeco.com/product/white-wood-queen-bed-frame"
WAF = RawResponse(200, HTML, b"<html><head><script>window.awsWafCookieDomainList=['www.aptdeco.com'];window.gokuProps={}"
                              b"</script></head><body><div id='challenge-container'></div><noscript>we need to verify that "
                              b"you're not a robot</noscript></body></html>")


def copy(sold=True, until="6/28/2026", price="$399", heading="### White Wood Queen Bed Frame", extra_heading=""):
    return f"""[Home](https://www.aptdeco.com/) / [Beds](https://www.aptdeco.com/catalog/furniture/beds)
Sold by [a seller](https://www.aptdeco.com/seller/1)

{heading}

Est. retail: $1,200|67% off|Qty: 1|

{price}

 or pay over time with Affirm
{"Sold / Expired" if sold else ""}

Have a similar item?[List it now](https://www.aptdeco.com/sell)

Shop similar items

[EQ3 Salema Leather Sleeper Sofa](https://www.aptdeco.com/product/eq3-salema-leather-sleeper-sofa)

$2,295$2,700•Qty: 1

Est retail: $5,000|54% off

[CB2 Tenon Wood Queen Bed](https://www.aptdeco.com/product/cb2-tenon-wood-queen-bed)

$550•Qty: 1
{extra_heading}
### Product details

Brand:[Other](https://www.aptdeco.com/brands/other)

Condition:Used - Satisfactory: Moderate wear and tear, but still has many good years left

Overall Dimensions: Width: 66 inches, Height: 63 inches, Depth: 88 inches

#### Sustainability Impact

Availability: Until {until}
"""


def net_with(md, source=URL, direct=WAF):
    return Net({URL: direct, R + URL: reply(source, md, title="AptDeco - Used Furniture")})


TODAY = date(2026, 10, 26)


def test_an_expired_listing_read_through_the_reader_is_kept_as_evidence_but_never_offered():
    net = net_with(copy())
    snap, res, out = import_used_listing(net.fetcher(), URL, "bed_frame", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert out == "sold or no longer available" and snap["availability"] == "SoldOut" and "Sold / Expired" in snap["sold_evidence"]
    assert snap["price_cents"] == 39900 and (snap["width_in"], snap["depth_in"]) == (66.0, 88.0)  # its OWN price, not $2,295
    assert snap["read_via"] == "public_reader" and snap["reader"]["url_source"] == URL and snap["reader"]["cache_age"] == "unknown"
    assert net.requested == [URL, R + URL]  # one direct try (robot check), one reader read; nothing solved or retried
    # A past "Until" date alone also ends it.
    net = net_with(copy(sold=False, until="6/28/2026"))
    snap, _, out = import_used_listing(net.fetcher(), URL, "bed_frame", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert out.startswith("sold") and "ended 2026-06-28" in snap["sold_evidence"]


def test_a_current_listing_copy_is_verified_from_its_own_section_only():
    net = net_with(copy(sold=False, until="12/31/2026"))
    snap, res, out = import_used_listing(net.fetcher(), URL, "bed_frame", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert out == "verified" and snap["condition"] == "secondhand" and snap["condition_verified"] is True
    assert snap["price_cents"] == 39900 and "Used - Satisfactory" in snap["condition_evidence"]
    assert snap["freshness"].startswith("unknown")
    # Its own price is missing: the related cards' prices ($2,295, $550) are NEVER used.
    net = net_with(copy(sold=False, until="12/31/2026", price="Price on request"))
    snap, _, out = import_used_listing(net.fetcher(), URL, "bed_frame", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert snap["price_cents"] is None and out == "incomplete"
    # Two listing headings before the details: ambiguous, so it abstains.
    md = copy(sold=False, until="12/31/2026", extra_heading="### Another Bed Frame\n\n$120\n")
    assert parse_aptdeco_copy(md, TODAY) is None


ACTIVE = """Sold by [a seller](https://www.aptdeco.com/seller/2)

# Round Oak Coffee Table

Est. retail: $499|54% off|Qty: 1|

$231$272

#### Nationwide delivery available

#### Free - Local pickup available

### Product details

Condition:{cond}

Overall Dimensions: Width: 37.5 inches, Height: 12 inches, Depth: 37.5 inches

#### Sustainability Impact

Availability: Until 12/10/2026

### You might also like:

[Another table](https://www.aptdeco.com/product/another-table)

$800•Qty: 3
"""


def test_the_active_listing_layout_reads_its_own_sale_price_and_stated_delivery():
    url = "https://www.aptdeco.com/product/round-oak-coffee-table"
    net = Net({url: WAF, R + url: reply(url, ACTIVE.format(cond="Used - Good: Minor signs of use"), title="AptDeco")})
    snap, _, out = import_used_listing(net.fetcher(), url, "coffee_table", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert out == "verified" and snap["price_cents"] == 23100  # the current price, not $272 or the related $800
    assert snap["delivery_text"] == ["Nationwide delivery available", "Free - Local pickup available"]
    assert (snap["width_in"], snap["depth_in"]) == (37.5, 37.5)
    net = Net({url: WAF, R + url: reply(url, ACTIVE.format(cond="Floor model: Has been used as a display model"), title="AptDeco")})
    snap, _, out = import_used_listing(net.fetcher(), url, "coffee_table", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert snap is None and "used or pre-owned" in out  # a floor model isn't relabelled as used


def test_the_reader_copy_must_be_this_listing_and_challenges_are_never_read_past():
    other = "https://www.aptdeco.com/product/cb2-tenon-wood-queen-bed"
    net = net_with(copy(sold=False, until="12/31/2026"), source=other)
    snap, _, out = import_used_listing(net.fetcher(), URL, "bed_frame", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert snap is None and "different page than this listing" in out
    anubis = ("Loading...\n\nYou are seeing this because the administrator of this website has set up Anubis to protect the "
              "server. Anubis uses a Proof-of-Work scheme.")
    net = Net({URL: WAF, R + URL: reply(URL, anubis, title="Making sure you're not a bot!")})
    snap, _, out = import_used_listing(net.fetcher(), URL, "bed_frame", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert snap is None and "couldn’t be read" in out and "bot" in out.lower()
    # Reader turned off (FURNISHAI_PUBLIC_READER=off -> no reader): the robot check is reported, no reader request.
    net = net_with(copy(sold=False, until="12/31/2026"))
    snap, _, out = import_used_listing(net.fetcher(), URL, "bed_frame", reader=None, today=TODAY)
    assert snap is None and "robot check" in out and net.requested == [URL]
    # Only approved marketplaces in the reader list: a Chairish robot check is reported, not read through the reader.
    ch = "https://www.chairish.com/product/35546333/curved-deco-style-sofa"
    net = Net({ch: WAF})
    snap, _, out = import_used_listing(net.fetcher(), ch, "sofa", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert snap is None and "robot check" in out and net.requested == [ch]
    # Damaged/refurbished stays distinct from used.
    net = net_with(copy(sold=False, until="12/31/2026").replace("Used - Satisfactory", "Refurbished"))
    snap, _, out = import_used_listing(net.fetcher(), URL, "bed_frame", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    assert snap is None and "refurbished or damaged" in out


def test_a_normal_listing_with_recaptcha_settings_is_not_a_robot_check_and_reader_facts_are_labelled():
    from furnishai.sources import robot_check
    url = "https://www.chairish.com/product/36879977/short-vintage-wooden-dresser"
    cfg = "<script>var C={RECAPTCHA_JS_URL:'https://www.google.com/recaptcha/api.js',RECAPTCHA_SITE_KEY:'x'};</script>"
    own = prod("Short Vintage Wooden Dresser", url=url, price="350", cond="UsedCondition", width=40, depth=18, avail="InStock")
    page = ld_page([own], body=cfg + "<p>" + "x" * 40000 + "</p>")
    assert robot_check(200, page.decode()) is False  # login-form reCAPTCHA settings are not a challenge
    snap, _, out = import_used_listing(Net({url: RawResponse(200, HTML, page)}).fetcher(), url, "dresser")
    assert out == "verified" and snap["price_cents"] == 35000 and snap.get("read_via") is None
    assert robot_check(200, "<html><body><div class='g-recaptcha'></div>Please complete the captcha</body></html>") is True
    # Facts from a reader copy carry that provenance into every option and checklist row.
    net = net_with(copy(sold=False, until="12/31/2026"))
    snap, _, _ = import_used_listing(net.fetcher(), URL, "bed_frame", reader=PublicReader.from_fetcher(net.fetcher()), today=TODAY)
    from furnishai.design import candidates_for, checklist
    prefs = DesignPrefs(condition="secondhand", categories=["bed_frame"])
    m, d = _design(prefs)
    bed = next(i for i in d.items if i.category == "bed_frame")
    c = candidates_for(bed, d, m, [snap], {snap["id"]: snap})[0][0]
    assert c["read_via"] == "public_reader" and c["freshness"].startswith("unknown")
    d2 = d.model_copy(update={"items": [i.model_copy(update={"product_id": snap["id"]}) if i.id == bed.id else i for i in d.items]})
    row = checklist(d2, {snap["id"]: snap}, {}, {})["rows"][0]
    assert row["read_via"] == "public_reader"
    from furnishai.export import _checked
    assert "public copy of the listing page (freshness unknown)" in _checked(row)


def test_listing_identity_survives_a_changed_slug_and_a_redirect_to_a_category_is_gone():
    url = "https://www.chairish.com/product/35546333/curved-deco-style-sofa"
    own = prod("Curved Deco Style Sofa", url="https://www.chairish.com/product/35546333/curved-deco-sofa-renamed", price="900",
               cond="UsedCondition", width=84, depth=36, avail="InStock")
    related = prod("Another sofa", url="https://www.chairish.com/product/111/another-sofa", price="400", cond="UsedCondition",
                   width=80, depth=34, avail="InStock")
    net = Net({url: RawResponse(200, HTML, ld_page([related, own]))})
    snap, _, out = import_used_listing(net.fetcher(), url, "sofa")
    assert out == "verified" and snap["price_cents"] == 90000  # the product with THIS listing's id, never "the first"
    gone = "https://www.chairish.com/product/36524183/sleigh-bed"
    net = Net({gone: RawResponse(301, {"location": "https://www.chairish.com/collection/sofa-sets"}, b""),
               "https://www.chairish.com/collection/sofa-sets": RawResponse(200, HTML, ld_page([related, own]))})
    snap, _, out = import_used_listing(net.fetcher(), gone, "bed_frame")
    assert snap is None and out.startswith("no longer online")


def _design(prefs):
    m = vmap(ONE_BED)
    return m, Design(plan_source_id="s", items=arrange(m, default_pieces(m, prefs), "walls", {}), prefs=prefs)


def used(pid, cat, cents, w, d, n, **kw):
    return {**product(pid, cat, cents, w=w, d=d, condition="secondhand", **kw), "origin": "used_listing_check",
            "condition_verified": True, "retailer": "Chairish", "url": f"https://www.chairish.com/product/{n}/{pid}"}


def test_targets_stay_an_affordable_complete_set_when_known_listings_are_luxury_priced():
    # The root's real case: known cheapest bed $2,495, coffee table $2,140, nightstand $379, dresser $600; no mattress or
    # sofa known. $3,500 budget, 10% reserve -> $3,150 for six pieces.
    prefs = DesignPrefs(budget_cents=350000, reserve_pct=10, styles=["modern"], condition="secondhand")
    cat = [used("bed", "bed_frame", 249500, 64, 80, 1, nominal_size="queen"), used("ct", "coffee_table", 214000, 40, 20, 2),
           used("ns", "nightstand", 37900, 18, 15, 3), used("dr", "dresser", 60000, 40, 18, 4)]
    m, d = _design(prefs)
    by = {p["id"]: p for p in cat}
    t = planning_targets(d, cat, by, m)
    assert len(t) == 6 and all(v["target_cents"] > 0 for v in t.values())  # mattress and sofa keep a real share
    assert sum(v["target_cents"] for v in t.values()) <= 315000
    bed = next(i.id for i in d.items if i.category == "bed_frame")
    assert t[bed]["target_cents"] < 100000 and t[bed]["basis"] == "share" and "above this piece’s share" in t[bed]["note"]
    # A modest known price may rebalance ONLY when the whole plan stays affordable.
    cat2 = [used("ns2", "nightstand", 20000, 18, 15, 5)]  # share ~$158; $200 is within 1.5x and everything else is unknown
    t2 = planning_targets(d, cat2, {p["id"]: p for p in cat2}, m)
    ns = next(i.id for i in d.items if i.category == "nightstand")
    assert t2[ns]["target_cents"] == 20000 and sum(v["target_cents"] for v in t2.values()) <= 315000
    # A geometry-impossible bargain doesn't count as the cheapest known option.
    cat3 = [used("tiny", "bed_frame", 10000, 200, 200, 6, nominal_size="queen")]
    t3 = planning_targets(d, cat3, {p["id"]: p for p in cat3}, m)
    assert t3[bed]["cheapest_known_cents"] is None


def test_title_style_cues_are_labelled_and_distinct_designs_stay_separate():
    p = {"name": "Mid-Century Modern Teak Dresser", "curator_tags": []}
    score, exact, label = style_fit(p, ["mid_century"])
    assert score == 1 and "a cue from the listing title" in label
    assert style_fit({"name": "Dresser", "curator_tags": []}, ["modern"])[2] == "Style not classified"
    a = product("a", "bed_frame", 30000, w=60, d=80, name="MALM storage bed - oak veneer", retailer="IKEA US")
    b = product("b", "bed_frame", 30000, w=60, d=80, name="MALM bed - oak veneer", retailer="IKEA US")
    c = product("c", "bed_frame", 30000, w=60, d=80, name="MALM storage bed - white", retailer="IKEA US")
    e = product("e", "bed_frame", 30000, w=60, d=80, name="MALM storage bed - walnut", retailer="IKEA US")
    f = product("f", "bed_frame", 30000, w=64, d=84, name="MALM storage bed - white", retailer="IKEA US")
    assert design_key(a) != design_key(b)  # storage vs plain: different designs
    assert design_key(a) != design_key(e)  # oak vs walnut: a material, not just a colour
    assert design_key(c) != design_key(f)  # same model, different size = a different fit
    w = product("w", "bed_frame", 30000, w=60, d=80, name="MALM storage bed - black", retailer="IKEA US")
    assert design_key(c) == design_key(w)  # only the colour differs
    assert design_key(product("g", "nightstand", 1, name="Nightstand - white")) != design_key(product("h", "nightstand", 1, name="Nightstand - black"))
