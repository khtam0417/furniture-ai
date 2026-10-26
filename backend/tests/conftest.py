import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"

from furnishai.config import Settings  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Tests never leave the machine: real DNS lookups and TCP connections fail (as if offline). Fake openers and
    mocked AI transports don't use sockets, so they are unaffected."""
    import socket

    def refuse(*a, **k):
        raise OSError("real network access is disabled in tests")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("disabled in tests")))


@pytest.fixture
def settings(tmp_path):
    # Never uses a real key: tests are offline. Live calls are replaced by pydantic-ai test models.
    return Settings(storage_dir=tmp_path / "storage", portkey_api_key=None, live_disabled=True)


def make_image(fmt="JPEG", size=(320, 240), color=(200, 100, 150), exif_orientation=None) -> bytes:
    im = Image.new("RGB", size, color)
    out = io.BytesIO()
    kwargs = {}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        exif[0x010F] = "TestCamera"  # Make
        kwargs["exif"] = exif.tobytes()
    im.save(out, format=fmt, **kwargs)
    return out.getvalue()


def product(pid, category, price_cents, w=30.0, d=20.0, tags=(), status="verified", condition="new", **extra):
    p = {
        "id": pid, "origin": "curated_catalog", "retailer": "Test Retailer", "url": f"https://example.com/{pid}",
        "category": category, "name": f"{pid} {category}", "variant_sku": pid, "nominal_size": extra.pop("nominal_size", None),
        "price_cents": price_cents, "currency": "USD", "availability": "InStock", "condition": condition,
        "width_in": w, "depth_in": d, "height_in": 30.0, "open_depth_in": None, "bed_surface_in": None,
        "mattress_size_text": extra.pop("mattress_size_text", None), "includes": {"slats": None, "mattress": None},
        "evidence": {}, "checked_at": extra.pop("checked_at", "2026-10-24T05:00:00+00:00"), "retrieval_status": "ok",
        "curator_tags": list(tags), "status": status, "missing": [] if status == "verified" else ["price_cents"],
        "open_depth_bounds_in": extra.pop("open_depth_bounds_in", None),
    }
    p.update(extra)
    return p
