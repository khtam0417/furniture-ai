"""Deterministic HTML evidence extraction (stdlib only).

Page content is untrusted evidence. Nothing here interprets page text as instructions; it only
pulls out structured data (JSON-LD, meta tags), links, images and visible text for code checks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

_SKIP_TEXT = {"script", "style", "noscript", "template", "svg"}


@dataclass
class PageEvidence:
    title: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    json_ld: list[dict] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute href, anchor text)
    images: list[tuple[str, str]] = field(default_factory=list)  # (best absolute source reference, alt)
    image_details: list[dict] = field(default_factory=list)  # url, alt and every referenced candidate URL
    iframes: list[str] = field(default_factory=list)
    text: str = ""


class _Parser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.ev = PageEvidence()
        self._stack: list[str] = []
        self._in_ld = False
        self._ld_buf: list[str] = []
        self._in_title = False
        self._anchor: str | None = None
        self._anchor_text: list[str] = []
        self._text: list[str] = []
        self._picture: list | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        self._stack.append(tag)
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self._ld_buf = []
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = a.get("property") or a.get("name") or a.get("itemprop")
            if key and "content" in a:
                self.ev.meta.setdefault(key.lower(), a["content"].strip())
        elif tag == "a" and a.get("href"):
            self._anchor = urljoin(self.base, a["href"].strip())
            self._anchor_text = []
        elif tag == "picture":
            self._picture = []
        elif tag == "source" and self._picture is not None:
            self._picture += image_candidates(a, self.base)
        elif tag == "img":
            cands = image_candidates(a, self.base) + (self._picture or [])
            best = best_image(cands)
            if best:
                alt = (a.get("alt") or a.get("title") or "").strip()
                self.ev.images.append((best, alt))
                self.ev.image_details.append({"url": best, "alt": alt, "candidates": sorted({u for u, _ in cands})[:8]})
        elif tag == "iframe" and a.get("src"):
            self.ev.iframes.append(urljoin(self.base, a["src"].strip()))
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "td", "th", "dd", "dt",
                   "footer", "header", "article", "aside", "nav", "main", "ul", "ol", "table"):
            self._text.append("\n")

    def handle_endtag(self, tag):
        if tag == "picture":
            self._picture = None
        if tag == "script" and self._in_ld:
            self._in_ld = False
            raw = "".join(self._ld_buf).strip()
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    graph = item.get("@graph")
                    if isinstance(graph, list):
                        self.ev.json_ld.extend(g for g in graph if isinstance(g, dict))
                    else:
                        self.ev.json_ld.append(item)
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._anchor:
            self.ev.links.append((self._anchor, " ".join("".join(self._anchor_text).split())))
            self._anchor = None
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        elif tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass

    def handle_data(self, data):
        if self._in_ld:
            self._ld_buf.append(data)
            return
        if self._in_title:
            self.ev.title += data
        if self._anchor is not None:
            self._anchor_text.append(data)
        if not any(t in _SKIP_TEXT for t in self._stack):
            self._text.append(data)


_CROPPED = re.compile(r"(?i)crop|thumb|/\d+_\d+_\d+(?:/|$)|[_-]\d+x\d+[_-]?c(?:rop)?\b")
_SRC_ATTRS = ("src", "data-src", "data-lazy-src", "data-original")
_SET_ATTRS = ("srcset", "data-srcset")


def unwrap_image_proxy(url: str, base: str) -> str:
    """Next.js-style `/_next/image?url=<encoded>&w=…` wrappers point at a real image: use that reference.
    Only http(s) absolute or site-relative targets are accepted; nothing is guessed or constructed."""
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(url)
    if parts.path.rstrip("/").endswith("/_next/image") and "url=" in parts.query:
        target = (parse_qs(parts.query).get("url") or [""])[0].strip()
        if target.startswith(("https://", "http://")):
            return target
        if target.startswith("/") and not target.startswith("//"):
            return urljoin(base, target)
    return url


def image_candidates(attrs: dict, base: str) -> list[tuple[str, int]]:
    """Every image URL an element references, with its srcset width (0 if none). data: URLs are ignored."""
    out: list[tuple[str, int]] = []
    for k in _SRC_ATTRS:
        v = (attrs.get(k) or "").strip()
        if v and not v.startswith("data:"):
            out.append((unwrap_image_proxy(urljoin(base, v), base), 0))
    for k in _SET_ATTRS:
        for part in (attrs.get(k) or "").split(","):
            bits = part.strip().split()
            if not bits or bits[0].startswith("data:"):
                continue
            width = 0
            if len(bits) > 1 and re.fullmatch(r"\d{1,5}w", bits[1]):
                width = int(bits[1][:-1])
            elif len(bits) > 1 and re.fullmatch(r"\d(?:\.\d)?x", bits[1]):
                width = int(float(bits[1][:-1]) * 1000)  # density descriptor: relative only
            out.append((unwrap_image_proxy(urljoin(base, bits[0]), base), width))
    return [(u, w) for u, w in out if u.startswith(("https://", "http://"))]


def best_image(cands: list[tuple[str, int]]) -> str | None:
    """Prefer an uncropped reference, then the largest declared width. Only URLs present in the page."""
    if not cands:
        return None
    return max(cands, key=lambda c: (not _CROPPED.search(c[0]), c[1], -len(c[0])))[0]


def extract(html: str, base_url: str) -> PageEvidence:
    p = _Parser(base_url)
    try:
        p.feed(html)
        p.close()
    except Exception:  # malformed markup still yields whatever was parsed
        pass
    ev = p.ev
    ev.title = " ".join(ev.title.split())
    lines = [" ".join(line.split()) for line in "".join(p._text).splitlines()]
    ev.text = "\n".join(line for line in lines if line)
    return ev


def decode_html(body: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def find_products(ev: PageEvidence) -> list[dict]:
    out = []
    for item in ev.json_ld:
        t = item.get("@type")
        types = t if isinstance(t, list) else [t]
        if "Product" in types or "ProductGroup" in types:
            out.append(item)
    return out


_PRICE_RE = re.compile(r"^\d{1,6}(\.\d{1,2})?$")


def offer_price(product: dict) -> tuple[str | None, str | None, str | None]:
    """(price string, currency, availability) from a JSON-LD Product, or Nones."""
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None, None, None
    if offers.get("@type") == "AggregateOffer":
        price = offers.get("lowPrice") if offers.get("lowPrice") == offers.get("highPrice") else None
    else:
        price = offers.get("price")
    price_s = str(price).strip() if price is not None else None
    if price_s and not _PRICE_RE.match(price_s):
        price_s = None
    avail = offers.get("availability")
    return price_s, offers.get("priceCurrency"), str(avail) if avail else None
