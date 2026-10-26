"""Stage a clean, clone-ready copy of Furniture AI for the submission repository (ALLOWLIST ONLY).

Usage (run from anywhere; nothing is uploaded, committed or published):
  python3 -I tools/package_submission.py --dest /path/to/new/empty/folder [--dry-run]

What it does, deterministically:
- copies ONLY the explicit allowlist below (app source, backend tests, frontend source + compiled build, pinned
  requirements, run.sh, serve.py, .env.example, README, the shipped product catalog and checked property-reference
  lists the app reads at runtime, and the submission-relevant docs);
- never copies anything under a denied path or name (.env files, .venv, node_modules, storage, SQLite databases,
  uploads, raw page snapshots, build prompts, private output, scratch files, caches, .DS_Store), even if a future
  allowlist rule would match it;
- refuses a destination inside this repository, or one that already has files in it;
- scans every staged text file for credential-looking strings and fails (removing nothing, printing only the file
  name and pattern kind, never the match) if one is found;
- writes MANIFEST.sha256 (sorted relative paths with their SHA-256) so the staged tree can be checked.
It never reads .env values: .env files are excluded by name before any file is opened.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Exact files (relative to the repository root).
FILES = [
    "README.md", "requirements.txt", "run.sh", "serve.py", ".env.example", ".gitignore",
    "frontend/package.json", "frontend/package-lock.json", "frontend/tsconfig.json", "frontend/vite.config.ts",
    "frontend/index.html",
    # Data the app and its tests read at runtime (small, distributable): the checked product catalog and its curation
    # list, and the browser-observed public plan-reference lists (URLs and names only, no image bytes).
    "data/catalog/products.json", "data/catalog/curation.json",
    "data/property_refs/theaudubonapts.json", "data/property_refs/thearchiveapts.json",
    # Docs a reviewer needs (course deliverables report.html / slides.html are submitted on Canvas, not here).
    "docs/STATUS.md", "docs/LECTURE_MAPPING.md", "docs/COURSE_REQUIREMENTS.md", "docs/ACCEPTANCE_TESTS.md",
    "docs/evidence/offline_search_benchmark.md", "docs/submission_outline.json",
    # Small tools documented in the README (the catalog tools need raw snapshots that are NOT distributed).
    "tools/package_submission.py", "tools/http_smoke.py", "tools/smoke_demo.py", "tools/build_catalog.py",
    "tools/snapshot_page.py", "tools/import_property_refs.py",
]
# Directory rules: (directory, allowed suffixes, recursive).
TREES = [
    ("backend/furnishai", {".py"}, False),
    ("backend/tests", {".py"}, False),
    ("frontend/src", {".ts", ".tsx", ".css"}, True),
    ("frontend/tests", {".ts"}, False),
    ("frontend/dist", {".html", ".js", ".css", ".svg", ".png", ".ico", ".webp", ".woff2"}, True),
]
REQUIRED = ["frontend/dist/index.html", "data/catalog/products.json", ".env.example", "requirements.txt", "run.sh"]
EXECUTABLE = {"run.sh"}

# Never staged, whatever the rules say.
DENY_PARTS = {".venv", "venv", "node_modules", "storage", "__pycache__", ".pytest_cache", ".mypy_cache", "output",
              ".scratch", "prompts", "catalog_raw", ".git", ".claude", "uploads"}
DENY_SUFFIX = {".sqlite3", ".sqlite", ".db", ".pyc", ".log", ".jsonl", ".key", ".pem"}


def denied(rel: Path) -> str | None:
    if any(p in DENY_PARTS for p in rel.parts):
        return "denied folder"
    name = rel.name
    if name == ".DS_Store":
        return ".DS_Store"
    if name.startswith(".env") and name != ".env.example":
        return "environment file"
    if rel.suffix.lower() in DENY_SUFFIX:
        return "denied file type"
    return None


# Credential-looking strings (reported by file and kind only; the match itself is never printed).
SECRET_PATTERNS = {
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "Portkey-style key": re.compile(r"\bpk-[A-Za-z0-9_\-]{20,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "assigned API key": re.compile(r"(?m)^\s*(?:PORTKEY_API_KEY|OPENAI_API_KEY)\s*=\s*[^\s#]+"),
    "bearer token": re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._\-]{20,}"),
}
TEXT_SUFFIX = {".py", ".ts", ".tsx", ".css", ".js", ".html", ".json", ".md", ".txt", ".sh", ".example", ".toml", ""}


def collect() -> tuple[list[Path], list[str]]:
    picked: set[Path] = set()
    problems: list[str] = []
    for f in FILES:
        p = ROOT / f
        if p.is_file():
            picked.add(Path(f))
        elif f in REQUIRED:
            problems.append(f"required file missing: {f}")
        else:
            print(f"note: optional file not found, skipped: {f}")
    for d, suffixes, recursive in TREES:
        base = ROOT / d
        if not base.is_dir():
            problems.append(f"directory missing: {d}")
            continue
        for p in (base.rglob("*") if recursive else base.glob("*")):
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in suffixes:
                picked.add(p.relative_to(ROOT))
    for r in REQUIRED:
        if Path(r) not in picked and not any(x.startswith(f"required file missing: {r}") for x in problems):
            problems.append(f"required file missing: {r}")
    out = []
    for rel in sorted(picked, key=lambda x: x.as_posix()):
        why = denied(rel)
        if why:
            print(f"excluded ({why}): {rel.as_posix()}")
            continue
        out.append(rel)
    return out, problems


def scan(rel: Path) -> list[str]:
    if rel.suffix.lower() not in TEXT_SUFFIX:
        return []
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    hits = []
    for kind, pat in SECRET_PATTERNS.items():
        if kind == "assigned API key" and not (rel.name == ".env.example" or rel.suffix in (".sh", ".md")):
            continue  # code/tests name the keys (tests use obvious fakes); env-style files and docs must not assign them
        if pat.search(text):
            hits.append(kind)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", required=True, help="a NEW or empty folder outside this repository")
    ap.add_argument("--dry-run", action="store_true", help="list what would be staged; copy nothing")
    args = ap.parse_args()
    dest = Path(args.dest).expanduser().resolve()
    if dest == ROOT or ROOT in dest.parents:
        print("refused: the destination must be outside this repository", file=sys.stderr)
        return 2
    if dest.exists() and any(dest.iterdir()):
        print("refused: the destination already has files in it (use a new empty folder)", file=sys.stderr)
        return 2
    files, problems = collect()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    flagged = [(rel, k) for rel in files for k in scan(rel)]
    if flagged:
        for rel, k in flagged:
            print(f"refused: possible credential ({k}) in {rel.as_posix()}", file=sys.stderr)
        return 1
    total = sum((ROOT / r).stat().st_size for r in files)
    if args.dry_run:
        for r in files:
            print(r.as_posix())
        print(f"{len(files)} files, {total / 1e6:.2f} MB (dry run: nothing copied)")
        return 0
    lines = []
    for rel in files:
        src, dst = ROOT / rel, dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)  # content only: no timestamps, owners or extended attributes
        dst.chmod(0o755 if rel.as_posix() in EXECUTABLE else 0o644)
        lines.append(f"{hashlib.sha256(dst.read_bytes()).hexdigest()}  {rel.as_posix()}")
    (dest / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    print(f"staged {len(files)} files ({total / 1e6:.2f} MB) into {dest}; MANIFEST.sha256 written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
