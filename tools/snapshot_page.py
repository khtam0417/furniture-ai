"""Snapshot one public retailer page for human-reviewed catalog curation.

Usage: .venv/bin/python -I tools/snapshot_page.py URL [URL ...]

Fetches through FurnishAI's SafeFetcher, stores raw bytes under data/catalog_raw/<sha256>.html with a
JSON sidecar (url, final url, retrieval time, hash), and prints the structured evidence found
(JSON-LD product name/sku/price/availability plus dimension-looking text lines) for a human to check.
It never writes catalog entries itself: data/catalog/products.json is curated from these snapshots.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from furnishai.html_extract import decode_html, extract, find_products, offer_price  # noqa: E402
from furnishai.safe_fetch import FetchBlocked, FetchFailed, SafeFetcher  # noqa: E402

RAW_DIR = ROOT / "data" / "catalog_raw"
DIM_RE = re.compile(
    r"(?i)\b(width|length|depth|height|dimensions?|mattress|overall|seat|bed|footprint|assembled|"
    r"product size|measurements?|includes?|slats?|sold separately)\b"
)
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def snapshot(url: str, ua: str | None, link_pattern: str | None = None) -> None:
    fetcher = SafeFetcher(timeout_s=20)
    try:
        res = fetcher.fetch(url, max_bytes=6_000_000, **({"user_agent": ua} if ua else {}))
    except (FetchBlocked, FetchFailed) as exc:
        print(json.dumps({"url": url, "status": "failed", "error": str(exc)}))
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{res.sha256}.html").write_bytes(res.body)
    meta = {
        "requested_url": res.requested_url,
        "final_url": res.final_url,
        "retrieved_at": res.retrieved_at,
        "sha256": res.sha256,
        "content_type": res.content_type,
        "bytes": len(res.body),
        "redirect_chain": res.redirect_chain,
    }
    (RAW_DIR / f"{res.sha256}.json").write_text(json.dumps(meta, indent=2))
    ev = extract(decode_html(res.body), res.final_url)
    if link_pattern:
        rx = re.compile(link_pattern)
        seen = sorted({href.split("?")[0] for href, _ in ev.links if rx.search(href)})
        print(json.dumps({"url": url, "sha256": res.sha256, "links": seen}, indent=1))
        return
    products = []
    for p in find_products(ev):
        price, cur, avail = offer_price(p)
        products.append({"name": p.get("name"), "sku": p.get("sku"), "price": price, "currency": cur,
                         "availability": avail, "brand": (p.get("brand") or {}).get("name") if isinstance(p.get("brand"), dict) else p.get("brand")})
    dim_lines = [line for line in ev.text.splitlines() if DIM_RE.search(line) and len(line) < 160][:80]
    print(json.dumps({**meta, "title": ev.title, "json_ld_products": products,
                      "og_price": ev.meta.get("product:price:amount"), "dimension_lines": dim_lines}, indent=1))


if __name__ == "__main__":
    args = sys.argv[1:]
    ua = pattern = None
    if args and args[0] == "--browser-ua":
        ua, args = BROWSER_UA, args[1:]
    if args and args[0] == "--links":
        pattern, args = args[1], args[2:]
    for u in args:
        snapshot(u, ua, pattern)
