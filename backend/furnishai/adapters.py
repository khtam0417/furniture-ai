"""Deterministic retailer page adapters.

Each adapter turns one fetched product page into ExtractedFacts. Every fact carries the exact
evidence snippet it came from; a fact without evidence is None. Adapters never guess: a
nominal size ("Queen") is not an overall footprint, a package size is not a product size,
and a missing price stays missing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from fractions import Fraction
from urllib.parse import urlsplit

from .html_extract import PageEvidence, decode_html, extract, find_products, offer_price

_VULGAR = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅓": "1/3", "⅔": "2/3"}


def parse_inches(text: str) -> float | None:
    """'78 3/8 "' -> 78.375, '30 ½ "' -> 30.5, '39.17 inches' -> 39.17. Returns None if not inches."""
    s = text.strip()
    for k, v in _VULGAR.items():
        s = s.replace(k, " " + v)
    m = re.match(r'^\s*(\d+(?:\.\d+)?)(?:\s+(\d+)/(\d+))?\s*(?:"|”|in\b|inch|inches)', s)
    if not m:
        return None
    value = Fraction(m.group(1))
    if m.group(2):
        value += Fraction(int(m.group(2)), int(m.group(3)))
    return round(float(value), 3)


@dataclass
class Fact:
    value: object
    evidence: str


@dataclass
class ExtractedFacts:
    retailer: str
    url: str
    name: Fact | None = None
    sku: Fact | None = None
    price_usd: Fact | None = None  # decimal string, e.g. "219" or "219.99"
    availability: Fact | None = None
    width_in: Fact | None = None
    depth_in: Fact | None = None  # "length" for beds
    height_in: Fact | None = None
    open_depth_in: Fact | None = None  # only when the page documents overall open depth
    bed_surface_in: Fact | None = None  # (width, length) of the sleeping surface
    mattress_size_text: Fact | None = None
    inclusions_text: list[Fact] = field(default_factory=list)  # e.g. "Slatted bed base and mattress sold separately."
    images: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        def f(x: Fact | None):
            return None if x is None else {"value": x.value, "evidence": x.evidence}

        return {
            "retailer": self.retailer,
            "url": self.url,
            "name": f(self.name),
            "sku": f(self.sku),
            "price_usd": f(self.price_usd),
            "availability": f(self.availability),
            "width_in": f(self.width_in),
            "depth_in": f(self.depth_in),
            "height_in": f(self.height_in),
            "open_depth_in": f(self.open_depth_in),
            "bed_surface_in": f(self.bed_surface_in),
            "mattress_size_text": f(self.mattress_size_text),
            "inclusions_text": [f(x) for x in self.inclusions_text],
            "images": self.images[:3],
            "notes": self.notes,
        }


def _norm_url(u: str) -> str:
    parts = urlsplit(u or "")
    return f"{(parts.hostname or '').lower()}{parts.path.rstrip('/')}"


def _select_product(products: list[dict], page_url: str) -> dict | None:
    """The Product describing THIS page: canonical URL match, else the only Product on the page."""
    target_url = _norm_url(page_url)
    for p in products:
        offers = p.get("offers")
        offer_urls = [o.get("url") for o in (offers if isinstance(offers, list) else [offers]) if isinstance(o, dict)]
        if any(_norm_url(str(u)) == target_url for u in [p.get("url"), *offer_urls] if u):
            return p
    return products[0] if len(products) == 1 else None


def _image_urls(img) -> list[str]:
    items = img if isinstance(img, list) else [img]
    out = []
    for i in items:
        if isinstance(i, str):
            out.append(i)
        elif isinstance(i, dict):
            u = i.get("contentUrl") or i.get("url")
            if isinstance(u, str):
                out.append(u)
    return [u for u in out if u.startswith("https://")][:3]


def _jsonld_basics(ev: PageEvidence, facts: ExtractedFacts) -> None:
    products = find_products(ev)
    if not products:
        facts.notes.append("No schema.org Product data on page")
        return
    p = _select_product(products, facts.url)
    if p is None:
        facts.notes.append(f"{len(products)} Product records on page and none matches this URL; identity not confirmed")
        return
    if p.get("name"):
        facts.name = Fact(str(p["name"]), f'JSON-LD Product.name = "{p["name"]}"')
    if p.get("sku"):
        facts.sku = Fact(str(p["sku"]), f'JSON-LD Product.sku = "{p["sku"]}"')
    elif p.get("mpn"):
        facts.sku = Fact(str(p["mpn"]), f'JSON-LD Product.mpn = "{p["mpn"]}"')
    price, currency, avail = offer_price(p)
    if price and (currency or "").upper() == "USD":
        facts.price_usd = Fact(price, f'JSON-LD Offer.price = "{price}", priceCurrency = "{currency}"')
    elif price:
        facts.notes.append(f"Price present but currency is {currency!r}; not used")
    if avail:
        facts.availability = Fact(avail.rsplit("/", 1)[-1], f'JSON-LD Offer.availability = "{avail}"')
    facts.images.extend(_image_urls(p.get("image")))


_IKEA_MEAS = re.compile(r'"measurements":\[(\{"measure":.*?)\]')


def ikea(url: str, body: bytes) -> ExtractedFacts:
    html = decode_html(body)
    ev = extract(html, url)
    facts = ExtractedFacts(retailer="IKEA US", url=url)
    _jsonld_basics(ev, facts)
    m = _IKEA_MEAS.search(html)
    if m:
        try:
            rows = json.loads("[" + m.group(1) + "]")
        except ValueError:
            rows = []
        by_name = {str(r.get("name", "")).lower(): str(r.get("measure", "")) for r in rows if isinstance(r, dict)}
        evidence = "IKEA product measurements: " + "; ".join(f"{r.get('name')} {r.get('measure')}" for r in rows if isinstance(r, dict))
        # Overall product size, never package or mattress size.
        width = by_name.get("width")
        length = by_name.get("length") or by_name.get("depth")
        height = by_name.get("height") or by_name.get("max. height")
        if width and parse_inches(width) is not None:
            facts.width_in = Fact(parse_inches(width), evidence)
        if length and parse_inches(length) is not None:
            facts.depth_in = Fact(parse_inches(length), evidence)
        if height and parse_inches(height) is not None:
            facts.height_in = Fact(parse_inches(height), evidence)
        bw, bl = by_name.get("bed width"), by_name.get("bed length")
        if bw and bl and parse_inches(bw) is not None and parse_inches(bl) is not None:
            # Sleeping-surface size of a sofa bed/daybed, NOT the overall open footprint.
            facts.bed_surface_in = Fact((parse_inches(bw), parse_inches(bl)), evidence)
        for key in ("depth when open", "depth (open)", "open depth"):
            if by_name.get(key) and parse_inches(by_name[key]) is not None:
                facts.open_depth_in = Fact(parse_inches(by_name[key]), evidence)
                break
        mw, ml = by_name.get("mattress width"), by_name.get("mattress length")
        if mw and ml:
            facts.mattress_size_text = Fact(f"{mw.strip()} x {ml.strip()}", evidence)
    else:
        facts.notes.append("IKEA measurements block not found")
    for line in ev.text.splitlines():
        low = line.lower()
        if ("sold separately" in low or "included" in low or "includes" in low) and len(line) < 200:
            if not any(x.evidence == line for x in facts.inclusions_text):
                facts.inclusions_text.append(Fact(line, line))
    return facts


_DIM_OVERALL = re.compile(
    r"Dimensions \(Overall\):\s*(?:\\u003c/B\\u003e|</B>)?\s*([\d.]+) inches \(H\) x ([\d.]+) inches \(W\) x ([\d.]+) inches \(D\)"
)


def target(url: str, body: bytes) -> ExtractedFacts:
    html = decode_html(body)
    ev = extract(html, url)
    facts = ExtractedFacts(retailer="Target", url=url)
    _jsonld_basics(ev, facts)
    if facts.name is None and ev.title:
        title = ev.title.replace(" : Target", "").strip()
        facts.name = Fact(title, f'Page <title> "{ev.title}"')
    m = _DIM_OVERALL.search(html)
    if m:
        snippet = f"Dimensions (Overall): {m.group(1)} inches (H) x {m.group(2)} inches (W) x {m.group(3)} inches (D)"
        facts.height_in = Fact(float(m.group(1)), snippet)
        facts.width_in = Fact(float(m.group(2)), snippet)
        facts.depth_in = Fact(float(m.group(3)), snippet)
    if facts.price_usd is None:
        facts.notes.append("Price is not present in the server-rendered page; left unknown")
    return facts


_Q = '["\u201d]'  # straight or typographic inch mark
_ART_HWD = re.compile(rf'^\s*([\d.]+){_Q}\s*H\s*x\s*([\d.]+){_Q}\s*W\s*x\s*([\d.]+){_Q}\s*[DL]\s*$')
_ART_WD = re.compile(rf'^\s*([\d.]+){_Q}\s*W\s*x\s*([\d.]+){_Q}\s*[DL]\s*$')
_ART_LABELS = ("General Dimensions", "Interior Frame Dimensions", "Mattress Size", "SKU No.")


def article(url: str, body: bytes) -> ExtractedFacts:
    """article.com product page. Price/availability from the page's own JSON-LD Product; the PRODUCT size from the
    spec row "General Dimensions" (H x W x D), never "Box Dimensions" (shipping cartons). The spec "SKU No." must
    equal the JSON-LD SKU, so the price and the dimensions describe the same variant; otherwise the price is dropped."""
    html = decode_html(body)
    ev = extract(html, url)
    facts = ExtractedFacts(retailer="Article", url=url)
    _jsonld_basics(ev, facts)
    lines = [ln.strip() for ln in ev.text.splitlines()]
    spec: dict[str, str] = {}
    for i, ln in enumerate(lines[:-1]):
        if ln in _ART_LABELS and ln not in spec:
            spec[ln] = lines[i + 1]
        if ln == "Box Dimensions":
            break  # everything after this is shipping/care text
    gd = spec.get("General Dimensions")
    m = _ART_HWD.match(gd or "")
    if m:
        snippet = f'Article spec "General Dimensions" = {gd}'
        facts.height_in = Fact(float(m.group(1)), snippet)
        facts.width_in = Fact(float(m.group(2)), snippet)
        facts.depth_in = Fact(float(m.group(3)), snippet)
    else:
        facts.notes.append("General Dimensions row not found or not in H x W x D form; size left unknown")
    inner = _ART_WD.match(spec.get("Interior Frame Dimensions") or "")
    if inner:  # the mattress opening of a bed frame
        facts.mattress_size_text = Fact(f'{inner.group(1)} " x {inner.group(2)} "',
                                        f'Article spec "Interior Frame Dimensions" = {spec["Interior Frame Dimensions"]}')
    ms = _ART_HWD.match(spec.get("Mattress Size") or "")
    if ms:  # sofa bed: its own mattress = the sleeping surface (not the open footprint)
        facts.bed_surface_in = Fact((float(ms.group(2)), float(ms.group(3))), f'Article spec "Mattress Size" = {spec["Mattress Size"]}')
    # Fail closed: without BOTH SKUs agreeing, the price can't be tied to the variant whose size we read.
    spec_sku = spec.get("SKU No.")
    if not facts.sku or not spec_sku:
        if facts.price_usd is not None:
            facts.notes.append("Spec SKU or JSON-LD SKU missing; price not used (variant not confirmed)")
        facts.price_usd = None
    elif spec_sku != facts.sku.value:
        facts.notes.append(f"Spec SKU {spec_sku} differs from JSON-LD SKU {facts.sku.value}; price not used (variant not confirmed)")
        facts.price_usd = None
    for line in lines:
        low = line.lower()
        if ("included" in low or "sold separately" in low) and len(line) < 200 and "warranty" not in low:
            if not any(x.evidence == line for x in facts.inclusions_text):
                facts.inclusions_text.append(Fact(line, line))
    return facts


_AMZ_URL_ASIN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?=[/?]|$)")
_AMZ_PAGE_ASIN = re.compile(r'<input[^>]*\bid="ASIN"[^>]*\bvalue="([A-Z0-9]{10})"')
_AMZ_PRICE_BLOCK = re.compile(r'data-csa-c-asin="([A-Z0-9]{10})"[^>]*>\s*<div class="a-section aok-hidden '
                              r'twister-plus-buying-options-price-data">(\{.*?\})</div>', re.S)
# A dimension triple where EVERY number carries its own letter (e.g. 80"L x 60"W x 14"H or 11.8"D x 15.7"W x 23.6"H).
_AMZ_TRIPLE = re.compile(rf'^\s*([\d.]+){_Q}?\s*([LWDH])\s*x\s*([\d.]+){_Q}?\s*([LWDH])\s*x\s*([\d.]+){_Q}?\s*([LWDH])\s*$', re.I)
_AMZ_DIM_ROW = re.compile(r"^(?:Item Dimensions(?: [LWDH] x [LWDH] x [LWDH])?|Product Dimensions)$")
_AMZ_IMG = re.compile(r'id="landingImage"[^>]*data-a-dynamic-image="([^"]+)"')
_AMZ_IN = re.compile(r'^\s*([\d.]+)\s*(?:inches|in|")\s*$', re.I)


def amazon(url: str, body: bytes) -> ExtractedFacts:
    """amazon.com product page (public HTML, no API). Facts only for the SELECTED variant: the page's selected ASIN
    must equal the URL's ASIN; the price is the featured offer's price block tagged with that ASIN (exactly one
    value, USD); the size is the labelled "D x W x H" product-dimension row, cross-checked against any separate Item
    Width/Depth rows (a contradiction leaves the size unknown). Package dimensions are never used. The seller of the
    featured offer is recorded as a note: other sellers may charge differently."""
    html = decode_html(body)
    ev = extract(html, url)
    facts = ExtractedFacts(retailer="Amazon", url=url)
    page_asin = (_AMZ_PAGE_ASIN.search(html) or [None, None])[1]
    url_asin = (_AMZ_URL_ASIN.search(urlsplit(url).path) or [None, None])[1]
    if not page_asin:
        facts.notes.append("No selected product (ASIN) on the page; nothing used")
        return facts
    if url_asin and url_asin != page_asin:
        facts.notes.append(f"The page shows a different variant ({page_asin}), not {url_asin} from the link; nothing used")
        return facts
    facts.sku = Fact(page_asin, f'Page field ASIN = "{page_asin}"')
    t = re.search(r'id="productTitle"[^>]*>\s*([^<]{3,400}?)\s*</span>', html)
    if t:
        facts.name = Fact(" ".join(t.group(1).split()), "Page productTitle")
    prices = set()
    for asin, block in _AMZ_PRICE_BLOCK.findall(html):
        if asin != page_asin:
            continue
        try:
            offers = json.loads(block).get("desktop_buybox_group_1") or []
        except ValueError:
            continue
        for o in offers:
            if not (isinstance(o, dict) and o.get("currencySymbol") == "$" and isinstance(o.get("priceAmount"), (int, float))):
                continue
            kind = o.get("buyingOptionType")
            if kind not in (None, "NEW"):  # a used/renewed featured offer is never priced as a new item
                facts.notes.append(f"Featured offer is {str(kind).lower()}, not new; its price is not used")
                continue
            if kind == "NEW":
                facts.notes.append("Featured offer condition: new (page buyingOptionType NEW for this ASIN)")
            prices.add((f"{o['priceAmount']:.2f}", o.get("displayPrice")))
    if len(prices) == 1:
        amount, shown = next(iter(prices))
        facts.price_usd = Fact(amount, f'Featured-offer price block for ASIN {page_asin}: priceAmount {amount} ({shown})')
    elif prices:
        facts.notes.append(f"{len(prices)} different prices for this ASIN on the page; price left unknown")
    else:
        facts.notes.append("No featured-offer price for the selected ASIN; price left unknown")
    av = re.search(r'id="availability"[^>]*>\s*(?:<[^>]+>\s*)*([A-Za-z][A-Za-z .]{2,40})', html)
    if av:
        text = " ".join(av.group(1).split())
        state = "InStock" if text.lower().startswith("in stock") else "OutOfStock" if "unavailable" in text.lower() else None
        if state:
            facts.availability = Fact(state, f'Page availability text "{text}"')
    seller = re.search(r"sellerProfileTriggerId'[^>]*>([^<]{1,80})<", html)
    if seller:
        facts.notes.append(f"Featured offer sold by {seller.group(1).strip()}; other sellers' prices may differ")
    lines = [ln.strip() for ln in ev.text.splitlines()]
    rows: dict[str, str] = {}
    triples: list[tuple[str, dict[str, float]]] = []
    for i, ln in enumerate(lines[:-1]):
        if ln in ("Item Width", "Item Depth", "Item Length") and ln not in rows:
            rows[ln] = lines[i + 1]
        if _AMZ_DIM_ROW.match(ln):
            m = _AMZ_TRIPLE.match(lines[i + 1])
            if m:
                vals = {m.group(k + 1).upper(): float(m.group(k)) for k in (1, 3, 5)}
                if set(vals) in ({"D", "W", "H"}, {"L", "W", "H"}):
                    triples.append((ln, vals))
    if not triples:
        facts.notes.append("No product dimensions labelled with D/L, W and H on the page; size left unknown")
        return _amz_image(html, facts)
    # Every labelled row must agree (a "Product Dimensions" row vs an "Item Dimensions" row can't differ).
    sizes = {(v["W"], v.get("D", v.get("L")), v["H"]) for _, v in triples}
    first_label, vals = triples[0]
    long_key = "D" if "D" in vals else "L"
    w, d, h = vals["W"], vals[long_key], vals["H"]
    conflicts = [] if len(sizes) == 1 else ["labelled dimension rows disagree"]
    # Cross-check only against the separate row that names the SAME letter (Amazon's "Item Depth" can mean height
    # on L x W x H pages, so it is not compared there).
    for key, letter, val in (("Item Width", "W", w), ("Item Depth", "D", d), ("Item Length", "L", d)):
        m = _AMZ_IN.match(rows.get(key, ""))
        if m and letter in vals and abs(float(m.group(1)) - val) > 0.25:
            conflicts.append(f"{key} {m.group(1)} in vs {val:g} in")
    if conflicts:
        facts.notes.append("The page gives conflicting product dimensions (" + "; ".join(conflicts) + "); size left unknown")
    else:
        snippet = f'Amazon product details "{first_label}" = ' + " x ".join(f"{vals[k]:g}\"{k}" for k in (long_key, "W", "H"))
        facts.width_in, facts.depth_in, facts.height_in = Fact(w, snippet), Fact(d, snippet), Fact(h, snippet)
    return _amz_image(html, facts)


def _amz_image(html: str, facts: ExtractedFacts) -> ExtractedFacts:
    """The page's main product image (the selected variant's landing image), Amazon's own image host only."""
    m = _AMZ_IMG.search(html)
    if m:
        try:
            urls = json.loads(m.group(1).replace("&quot;", '"'))
        except ValueError:
            urls = {}
        ok = [(u, sz) for u, sz in urls.items() if isinstance(u, str) and u.startswith("https://m.media-amazon.com/images/I/")]
        if ok:
            facts.images.append(max(ok, key=lambda x: (x[1][0] if isinstance(x[1], list) and x[1] else 0))[0])
    return facts


def generic(url: str, body: bytes) -> ExtractedFacts:
    """Any other public page: JSON-LD/OpenGraph only. Used for user-imported listing URLs."""
    html = decode_html(body)
    ev = extract(html, url)
    host = urlsplit(url).hostname or "unknown"
    facts = ExtractedFacts(retailer=host, url=url)
    _jsonld_basics(ev, facts)
    if facts.name is None and (ev.meta.get("og:title") or ev.title):
        t = ev.meta.get("og:title") or ev.title
        facts.name = Fact(t, f'Page title "{t}"')
    if facts.price_usd is None:
        amount, cur = ev.meta.get("product:price:amount") or ev.meta.get("og:price:amount"), (
            ev.meta.get("product:price:currency") or ev.meta.get("og:price:currency") or ""
        )
        if amount and re.match(r"^\d{1,6}(\.\d{1,2})?$", amount.strip()) and cur.upper() == "USD":
            facts.price_usd = Fact(amount.strip(), f'meta product:price:amount = "{amount}" {cur}')
    dims = parse_wxd(ev.text)
    if dims:
        w, d, snippet = dims
        facts.width_in = Fact(w, snippet)
        facts.depth_in = Fact(d, snippet)
    return facts


# Width x depth with an EXPLICIT unit on both numbers (inches or centimeters). Unitless numbers stay unknown.
_WXD_RE = re.compile(
    r"(?i)\b(\d{1,3}(?:\.\d+)?)\s*(\"|”|in\b|inches|cm)\s*\(?w(?:ide|idth)?\)?\s*[x×]\s*"
    r"(\d{1,3}(?:\.\d+)?)\s*(\"|”|in\b|inches|cm)\s*\(?d(?:eep|epth)?\)?"
)


def parse_wxd(text: str) -> tuple[float, float, str] | None:
    m = _WXD_RE.search(text or "")
    if not m:
        return None

    def to_in(value: str, unit: str) -> float:
        v = float(value)
        return round(v / 2.54, 3) if unit.lower() == "cm" else v

    return to_in(m.group(1), m.group(2)), to_in(m.group(3), m.group(4)), m.group(0)


def _host_is(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def adapter_for(url: str):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if _host_is(host, "ikea.com") and parts.path.startswith("/us/en/"):
        return ikea
    if _host_is(host, "target.com"):
        return target
    if host == "www.article.com" and parts.path.startswith("/product/"):
        return article
    if host in ("www.amazon.com", "amazon.com") and _AMZ_URL_ASIN.search(parts.path):
        return amazon
    return generic
