"""Rebuild data/catalog/products.json from data/catalog/curation.json.

Usage: .venv/bin/python -I tools/build_catalog.py [--offline]

Each URL is fetched through SafeFetcher (honest user agent, no bot-bypass), the raw bytes are kept in
data/catalog_raw/<sha256>.html, and a deterministic adapter extracts facts with evidence snippets.
Failed fetches keep the previous snapshot (if any) with retrieval_status 'refresh_failed' and the old
checked_at date, so stale facts stay visibly dated. --offline re-extracts from saved raw files only.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from furnishai.adapters import adapter_for  # noqa: E402
from furnishai.catalog import snapshot_from_facts  # noqa: E402
from furnishai.safe_fetch import FetchBlocked, FetchFailed, SafeFetcher  # noqa: E402

CURATION = ROOT / "data" / "catalog" / "curation.json"
OUT = ROOT / "data" / "catalog" / "products.json"
RAW = ROOT / "data" / "catalog_raw"


def main(offline: bool) -> None:
    items = json.loads(CURATION.read_text())["items"]
    previous = {p["url"]: p for p in json.loads(OUT.read_text())["products"]} if OUT.is_file() else {}
    raw_index = {}
    for meta_file in RAW.glob("*.json"):
        meta = json.loads(meta_file.read_text())
        if "requested_url" in meta:
            prev = raw_index.get(meta["requested_url"])
            if prev is None or meta["retrieved_at"] > prev["retrieved_at"]:
                raw_index[meta["requested_url"]] = meta
    fetcher = SafeFetcher(timeout_s=20)
    products, failures = [], []
    for item in items:
        url, category = item["url"], item["category"]
        meta = None
        if not offline:
            try:
                res = fetcher.fetch(url, max_bytes=6_000_000)
                RAW.mkdir(parents=True, exist_ok=True)
                (RAW / f"{res.sha256}.html").write_bytes(res.body)
                meta = {"requested_url": url, "final_url": res.final_url, "retrieved_at": res.retrieved_at,
                        "sha256": res.sha256, "content_type": res.content_type, "bytes": len(res.body),
                        "redirect_chain": res.redirect_chain}
                (RAW / f"{res.sha256}.json").write_text(json.dumps(meta, indent=2))
            except (FetchBlocked, FetchFailed) as exc:
                failures.append({"url": url, "error": str(exc)})
            time.sleep(1.0)  # polite pacing
        else:
            meta = raw_index.get(url)
        if meta is None:
            if url in previous:
                old = dict(previous[url])
                old["retrieval_status"] = "refresh_failed"
                products.append(old)
            continue
        if meta.get("final_url", url).rstrip("/") != url.rstrip("/"):
            failures.append({"url": url, "error": f"redirected to {meta['final_url']}; exact variant not confirmed"})
            continue
        body = (RAW / f"{meta['sha256']}.html").read_bytes()
        facts = adapter_for(url)(url, body)
        extra = {}
        if facts.retailer == "Amazon":  # a marketplace: condition only from the selected offer's own evidence
            new = any(n.startswith("Featured offer condition: new") for n in facts.notes)
            if not new:
                failures.append({"url": url, "error": "Amazon featured offer is not documented as new; not added"})
                continue
            extra = {"condition": "new", "condition_evidence": "Amazon featured offer for the selected ASIN is NEW (page buyingOptionType)"}
        snap = snapshot_from_facts(facts, category, meta["sha256"], meta["retrieved_at"], item.get("curator_tags"), **extra)
        if meta.get("fetched_by"):
            snap["fetched_by"] = meta["fetched_by"]
        products.append(snap)
    ids = [p["id"] for p in products]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SystemExit(f"Duplicate product ids: {dupes}")
    OUT.write_text(json.dumps({
        "about": "FurnishAI product snapshots. Facts come only from the linked retailer pages on checked_at; "
                 "null means not found on the page. curator_tags are AI-assisted editorial judgments (not retailer facts, not "
                 "all human-reviewed). Prices/stock may have changed since.",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "products": products,
        "fetch_failures": failures,
    }, indent=1, ensure_ascii=False))
    verified = sum(1 for p in products if p["status"] == "verified")
    print(json.dumps({"products": len(products), "verified": verified, "incomplete": len(products) - verified,
                      "failures": failures,
                      "summary": [(p["id"], p["category"], p["name"], p["price_cents"], p["width_in"], p["depth_in"],
                                   p["open_depth_in"], p["nominal_size"], p["includes"], p["status"], p["missing"])
                                  for p in products]}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main("--offline" in sys.argv)
