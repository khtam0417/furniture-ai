"""Approved furniture product sources: established retailers for NEW items and resale marketplaces for USED items.

Approved resale marketplaces for automated secondhand search and checks (user direction 2026-10-26: established,
named platforms only; no unknown or risky sites).

An approved platform is NOT an endorsement of any seller, item condition, stock, price or delivery: the platform is
established, the individual listing is not verified by us beyond the page evidence we read.

`resale_site()` is a hard boundary used before any connection (every redirect hop included): exact hosts (plus
Craigslist's one-label regional subdomains), https only, default port, no credentials in the URL, ASCII-only host names
(no punycode/confusables), and the platform's individual-listing path shape. Anything else is "not approved".
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# key -> (display name, exact hosts, host pattern or None, individual-listing path pattern)
RESALE_SITES: dict[str, tuple[str, tuple[str, ...], str | None, str]] = {
    # Individual AptDeco listings appear as /product/<slug> (observed in real search results) and /products/<slug>.
    "aptdeco": ("AptDeco", ("www.aptdeco.com", "aptdeco.com"), None, r"^/products?/[a-z0-9][a-z0-9-]*/?$"),
    "chairish": ("Chairish", ("www.chairish.com", "chairish.com"), None, r"^/product/\d+(/[a-z0-9-]*)?/?$"),
    "ebay": ("eBay", ("www.ebay.com", "ebay.com"), None, r"^/itm/(?:[a-z0-9-]+/)?\d+/?$"),
    "facebook": ("Facebook Marketplace", ("www.facebook.com", "facebook.com", "m.facebook.com"), None,
                 r"^/marketplace/item/\d+/?$"),
    "craigslist": ("Craigslist", (), r"^[a-z]{2,24}\.craigslist\.org$", r"^/(?:[a-z]{3}/){1,2}d/[a-z0-9-]+/\d+\.html$"),
}
DOMAINS = {"aptdeco": "aptdeco.com", "chairish": "chairish.com", "ebay": "ebay.com",
           "facebook": "facebook.com/marketplace", "craigslist": "craigslist.org"}
TRUST_NOTE = ("Used results are shown and checked only from established resale marketplaces: " +
              ", ".join(f"{v[0]} ({DOMAINS[k]})" for k, v in RESALE_SITES.items()) +
              ". An approved marketplace doesn’t verify individual sellers, condition, stock or delivery.")


# Established retailers for NEW furniture (the saved catalog's stores). Exact hosts only.
RETAILERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "amazon": ("Amazon", ("www.amazon.com", "amazon.com")),
    "article": ("Article", ("www.article.com", "article.com")),
    "ikea": ("IKEA US", ("www.ikea.com", "ikea.com")),
    "target": ("Target", ("www.target.com", "target.com")),
}
RETAILER_BY_STORE = {v[0]: k for k, v in RETAILERS.items()}  # "IKEA US" -> "ikea" (store names used in preferences)
SOURCE_NOTE = ("Recommendations and page checks use only established stores (Amazon, Article, IKEA, Target) for new items "
               "and approved resale marketplaces for used items. The web search itself may look at other sites, but this "
               "app doesn’t show, open or read results from them.")


def _strict_host(url: str) -> str | None:
    """Lower-case host of a strictly well-formed public https URL (no credentials, default port, ASCII, no punycode),
    else None."""
    if not isinstance(url, str) or not url.isascii() or any(c in url for c in "\\ \t\r\n"):
        return None
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        return None
    if p.scheme != "https" or p.username is not None or p.password is not None or "@" in p.netloc or port not in (None, 443):
        return None
    host = (p.hostname or "").lower()
    if not host or host.endswith(".") or "xn--" in host:
        return None
    return host


def retailer_site(url: str, stores: list[str] | None = None) -> str | None:
    """The established retailer for this URL's host (any page on it), limited to the chosen store names (empty = all)."""
    host = _strict_host(url)
    if host is None:
        return None
    for key, (name, hosts) in RETAILERS.items():
        if host in hosts and (not stores or name in stores):
            return key
    return None


def product_source(url: str, condition: str, stores: list[str] | None = None, resale: list[str] | None = None
                   ) -> tuple[str, str] | None:
    """("retail"|"resale", key) when this URL is an allowed furniture source for the shopping condition: new -> the
    chosen established retailers; secondhand -> individual listings on the chosen resale marketplaces; either -> both.
    Anything else (unknown, private or malformed) -> None and is never fetched."""
    if condition in ("new", "either"):
        k = retailer_site(url, stores)
        if k:
            return "retail", k
    if condition in ("secondhand", "either"):
        k = resale_site(url, resale)
        if k:
            return "resale", k
    return None


def furniture_guard(condition: str, stores: list[str] | None = None, resale: list[str] | None = None):
    """For SafeFetcher: every hop must stay on an allowed furniture source host, checked before connecting."""
    def guard(url: str) -> str | None:
        ok = ((condition in ("new", "either") and retailer_site(url, stores))
              or (condition in ("secondhand", "either") and _host_site(url) and (not resale or _host_site(url) in resale)))
        return None if ok else "a redirect to a website outside the approved furniture sources was refused"
    return guard


def _host_site(url: str) -> str | None:
    """The approved platform for this URL's HOST (any path), or None. Strict: https, default port, no userinfo,
    ASCII host, exact host match (no suffix tricks like ebay.com.evil.example or evilebay.com)."""
    if not isinstance(url, str) or not url.isascii() or any(c in url for c in "\\ \t\r\n"):
        return None
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        return None
    if p.scheme != "https" or p.username is not None or p.password is not None or "@" in p.netloc:
        return None
    if port not in (None, 443):
        return None
    host = (p.hostname or "").lower()
    if not host or host.endswith(".") or "xn--" in host:
        return None
    for key, (_, hosts, pattern, _) in RESALE_SITES.items():
        if host in hosts or (pattern and re.fullmatch(pattern, host)):
            return key
    return None


def resale_site(url: str, allowed: list[str] | None = None) -> str | None:
    """The approved platform for an INDIVIDUAL listing URL (host and listing-path shape), limited to `allowed` keys
    (None/empty = all approved platforms); else None."""
    key = _host_site(url)
    if key is None or (allowed and key not in allowed):
        return None
    path = urlsplit(url).path.lower()
    return key if re.match(RESALE_SITES[key][3], path) else None


def listing_key(url: str) -> str | None:
    """Canonical identity of ONE resale listing: platform + host (without www./m.) + path (query, fragment and a trailing
    slash ignored). Different checks of the same listing (new timestamps, price edits) share it."""
    site = _host_site(url)
    if site is None:
        return None
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    for pre in ("www.", "m."):
        host = host.removeprefix(pre)
    return f"{site}:{host}{p.path.lower().rstrip('/')}"


_LISTING_ID = {
    "chairish": r"^/product/(\d+)(?:/|$)", "ebay": r"^/itm/(?:[a-z0-9-]+/)?(\d+)/?$", "craigslist": r"/(\d+)\.html$",
    "aptdeco": r"^/products?/([a-z0-9][a-z0-9-]*)/?$", "facebook": r"^/marketplace/item/(\d+)",
}


def listing_id(url: str) -> tuple[str, str] | None:
    """(platform, the marketplace's own listing id) for an individual listing URL, e.g. ("chairish", "35546333") for
    /product/35546333/<any-slug>. A slug change keeps the identity; a different id is a different listing."""
    site = _host_site(url)
    if site is None or site not in _LISTING_ID:
        return None
    m = re.search(_LISTING_ID[site], urlsplit(url).path.lower())
    return (site, m.group(1)) if m else None


def redirect_guard(allowed: list[str] | None = None):
    """For SafeFetcher: refuse (before connecting) any hop whose host isn't an approved platform."""
    def guard(url: str) -> str | None:
        key = _host_site(url)
        if key is None or (allowed and key not in allowed):
            return "a redirect to a site outside the approved resale marketplaces was refused"
        return None
    return guard


def site_names(keys: list[str] | None) -> list[str]:
    return [RESALE_SITES[k][0] for k in (keys or list(RESALE_SITES)) if k in RESALE_SITES]
