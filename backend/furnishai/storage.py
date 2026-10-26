"""Content-addressed, per-project source storage.

Originals are written once (sha256 file name, read-only permissions) and never modified. The AI
sees only derivatives: EXIF-orientation applied, metadata stripped, downscaled JPEG. Each derivative
records its parent source id, hash and method version. Storage is per project, so nothing is shared
or cached across users.
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
import stat
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

DERIVATIVE_METHOD = "pil-exif-transpose-strip-jpeg-q85-max1024-v1"
DERIVATIVE_MAX_EDGE = 1024
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf", "text/html": "html",
       "text/plain": "txt"}


class UploadRejected(Exception):
    pass


@dataclass
class ValidatedImage:
    media_type: str
    width: int
    height: int


def sniff_heic(data: bytes) -> bool:
    return len(data) > 12 and data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heim", b"heis")


def validate_image(data: bytes, max_bytes: int, max_pixels: int) -> ValidatedImage:
    if not data:
        raise UploadRejected("The file is empty.")
    if len(data) > max_bytes:
        raise UploadRejected(f"File is larger than {max_bytes // (1024 * 1024)} MB.")
    if sniff_heic(data):
        raise UploadRejected(
            "HEIC/HEIF photos are not supported in this build (no tested converter). On iPhone choose "
            "Settings > Camera > Formats > Most Compatible, or export/share the photo as JPEG."
        )
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            w, h = im.size
            if w * h > max_pixels:
                raise UploadRejected("Image has too many pixels.")
            im.verify()
    except UploadRejected:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise UploadRejected("This file is not a readable JPEG, PNG or WebP image.")
    if fmt not in ALLOWED_FORMATS:
        raise UploadRejected(f"Image format {fmt} is not accepted; use JPEG, PNG or WebP.")
    if w < 64 or h < 64:
        raise UploadRejected("Image is too small to be useful.")
    return ValidatedImage(ALLOWED_FORMATS[fmt], w, h)


def validate_pdf(data: bytes, max_bytes: int) -> None:
    if len(data) > max_bytes:
        raise UploadRejected("PDF is too large.")
    if not data.startswith(b"%PDF-"):
        raise UploadRejected("This file is not a PDF.")


class SourceStore:
    def __init__(self, root: Path):
        self.root = root

    def _project_dir(self, project_id: str, sub: str) -> Path:
        if not project_id.replace("_", "").isalnum():
            raise ValueError("bad project id")
        d = self.root / "projects" / project_id / sub
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_original(self, project_id: str, data: bytes, media_type: str) -> tuple[str, Path]:
        sha = hashlib.sha256(data).hexdigest()
        path = self._project_dir(project_id, "originals") / f"{sha}.{EXT[media_type]}"
        if not path.exists():
            tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")  # unique per writer thread
            tmp.write_bytes(data)
            os.replace(tmp, path)
            os.chmod(path, stat.S_IRUSR | stat.S_IRGRP)  # read-only original
        return sha, path

    def make_derivative(self, project_id: str, data: bytes) -> tuple[str, Path, int, int, bytes]:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
            im.thumbnail((DERIVATIVE_MAX_EDGE, DERIVATIVE_MAX_EDGE))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=85, optimize=True)  # no exif/icc passed -> metadata stripped
            w, h = im.size
        body = out.getvalue()
        sha = hashlib.sha256(body).hexdigest()
        path = self._project_dir(project_id, "derived") / f"{sha}.jpg"
        if not path.exists():
            path.write_bytes(body)
        return sha, path, w, h, body

    def remove_paths(self, paths: list[str]) -> None:
        for p in paths:
            path = Path(p)
            try:
                path.resolve().relative_to(self.root.resolve())
            except ValueError:
                continue  # never delete outside storage root
            if path.exists():
                os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
                path.unlink()
