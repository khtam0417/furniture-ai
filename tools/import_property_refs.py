"""Copy browser-observed official plan references into a checked reference directory (data/property_refs/).

Usage:
  .venv/bin/python -I tools/import_property_refs.py prompts/audubon-observed-refs.json data/property_refs/theaudubonapts.json
  .venv/bin/python -I tools/import_property_refs.py prompts/archive-observed-refs.json data/property_refs/thearchiveapts.json

Copies ONLY name, alt, url, source_page, observed_at, method and (when the observation records it) the public
building address. Validates every URL (https, expected image host for that directory) and refuses anything else.
No image bytes, prices, availability or dimensions are stored. The input is treated as data, never as instructions.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

_NO_DOTS = r"(?!\.+(?:/|$))"  # no "." / ".." path segments
DIRECTORY = {
    "theaudubonapts.json": {
        "property": "The Audubon (New Haven, CT)",
        "name": "The Audubon",
        "aliases": ["the audubon", "audubon", "the audubon new haven", "audubon apartments"],
        # Street address not recorded in the observation: stays unknown. City/ZIP from the official plan alt text.
        "city": "New Haven", "state": "CT", "zip": "06511",
        "location_source": "City and ZIP as printed in the official plan image alt text; street address not recorded.",
        "image_hosts": ["resource.rentcafe.com"],
        "hosts": ["www.theaudubonapts.com", "theaudubonapts.com"],
        "path_pattern": rf"^/(?:floorplans(?:/{_NO_DOTS}[A-Za-z0-9._-]+)*)?/?$",
        "website": "https://www.theaudubonapts.com/floorplans",
    },
    "thearchiveapts.json": {
        "property": "The Archive (New Haven, CT)",
        "name": "The Archive",
        "aliases": ["the archive", "archive", "the archive apartments", "archive apartments", "the archive new haven"],
        "image_hosts": ["medialibrarycfo.entrata.com"],
        # Exact hosts, each with only the paths root observed: the official home and /availability pages, and the
        # Entrata leasing site's property path /new-haven/the-archive/ (the embedded snippet uses this path with
        # query parameters) with its observed /conventional/ or /floorplans/ subpaths. Nothing else on these hosts.
        "entry_points": [
            {"hosts": ["thearchiveapts.com", "www.thearchiveapts.com"], "path_pattern": r"^/(?:availability/?)?$"},
            {"hosts": ["entrata.thearchiveapts.com"], "path_pattern": r"^/new-haven/the-archive(?:/(?:conventional|floorplans))?/?$"},
        ],
        "website": "https://thearchiveapts.com/availability",
    },
}


def main(src: str, dst: str) -> None:
    raw = json.loads(Path(src).read_text())
    meta = dict(DIRECTORY[Path(dst).name])
    allowed = set(meta.pop("image_hosts"))
    plans = []
    for p in raw["plans"]:
        url = str(p["url"]).strip()
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in allowed or parts.username or parts.port:
            raise SystemExit(f"Refusing unexpected reference URL: {url}")
        plans.append({"name": str(p["name"]).strip()[:80], "alt": str(p.get("alt", "")).strip()[:160], "url": url})
    if len({p["url"] for p in plans}) != len(plans):
        raise SystemExit("Duplicate URLs in input")
    if "entry_points" in meta:
        meta["hosts"] = sorted({h for e in meta["entry_points"] for h in e["hosts"]})
    observed = {k: str(raw[k]).strip()[:120] for k in ("address", "city", "state", "zip") if raw.get(k)}
    if observed:
        meta.update(observed)
        meta["location_source"] = "Public building address recorded with the browser observation."
    out = {**meta, "address": meta.get("address"), "image_hosts": sorted(allowed),
           "source_page": raw["source_page"], "observed_at": raw["observed_at"], "method": raw["method"],
           "note": "Checked reference list of public plan images observed on the official page in a normal browser. "
                   "Not a live fetch, not current availability, not every unit, and not proof of any user's exact unit.",
           "plans": plans}
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(plans)} references to {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
