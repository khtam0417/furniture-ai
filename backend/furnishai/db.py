"""SQLite persistence. Version tables are append-only; normal edits never UPDATE or DELETE them.

The only deletion path is an explicit user project deletion (delete_project), which removes the
project, its versions, and its stored originals.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
  name TEXT NOT NULL, room_type TEXT NOT NULL, mode TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_assets (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, sha256 TEXT NOT NULL, media_type TEXT NOT NULL, original_filename TEXT,
  byte_size INTEGER NOT NULL, storage_path TEXT NOT NULL, source_url TEXT, retrieved_at TEXT,
  width INTEGER, height INTEGER, is_synthetic INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS derivatives (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  parent_source_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, sha256 TEXT NOT NULL, media_type TEXT NOT NULL, method_version TEXT NOT NULL,
  width INTEGER, height INTEGER, storage_path TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS room_versions (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, parent_id TEXT, source_ids TEXT NOT NULL, method TEXT NOT NULL,
  model TEXT, prompt_version TEXT, input_hash TEXT, data TEXT NOT NULL, summary TEXT, created_at TEXT NOT NULL,
  UNIQUE(project_id, version)
);
CREATE TABLE IF NOT EXISTS preference_versions (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, parent_id TEXT, data TEXT NOT NULL, summary TEXT, method TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(project_id, version)
);
CREATE TABLE IF NOT EXISTS product_snapshots (
  id TEXT NOT NULL, scope TEXT NOT NULL, content_hash TEXT NOT NULL, data TEXT NOT NULL,
  checked_at TEXT, status TEXT NOT NULL, origin TEXT NOT NULL, source_asset_id TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (id, content_hash, scope)
);
CREATE TABLE IF NOT EXISTS plan_versions (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, parent_id TEXT, room_version_id TEXT, preference_version_id TEXT NOT NULL,
  product_refs TEXT NOT NULL, data TEXT NOT NULL, summary TEXT, created_at TEXT NOT NULL,
  UNIQUE(project_id, version)
);
CREATE TABLE IF NOT EXISTS run_events (
  id TEXT PRIMARY KEY, project_id TEXT, session_id TEXT, kind TEXT NOT NULL, data TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS apartments (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), name TEXT NOT NULL,
  preset TEXT NOT NULL, bedrooms INTEGER NOT NULL, bathrooms INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS apartment_rooms (
  apartment_id TEXT NOT NULL REFERENCES apartments(id), project_id TEXT NOT NULL UNIQUE REFERENCES projects(id),
  role TEXT NOT NULL, label TEXT NOT NULL, ordinal INTEGER NOT NULL, PRIMARY KEY (apartment_id, project_id)
);
CREATE TABLE IF NOT EXISTS apartment_context (
  id TEXT PRIMARY KEY, apartment_id TEXT NOT NULL REFERENCES apartments(id), version INTEGER NOT NULL,
  data TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(apartment_id, version)
);
CREATE TABLE IF NOT EXISTS research_results (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, apartment_id TEXT, project_id TEXT, kind TEXT NOT NULL,
  query_key TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS place_discovery (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, apartment_id TEXT, project_id TEXT NOT NULL, version INTEGER NOT NULL,
  building_key TEXT, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_selection (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, plan_key TEXT NOT NULL,
  plan_version INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_marks (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, product_id TEXT NOT NULL,
  category TEXT NOT NULL, purchased INTEGER NOT NULL, plan_key TEXT NOT NULL, plan_version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_provenance (
  source_id TEXT PRIMARY KEY REFERENCES source_assets(id), project_id TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_maps (
  id TEXT PRIMARY KEY, apartment_id TEXT NOT NULL REFERENCES apartments(id), source_id TEXT NOT NULL,
  input_hash TEXT NOT NULL, method TEXT NOT NULL, model TEXT, prompt_version TEXT NOT NULL, data TEXT NOT NULL,
  call TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS design_versions (
  id TEXT PRIMARY KEY, apartment_id TEXT NOT NULL REFERENCES apartments(id), version INTEGER NOT NULL, parent_id TEXT,
  plan_map_id TEXT, data TEXT NOT NULL, summary TEXT, created_at TEXT NOT NULL, UNIQUE(apartment_id, version)
);
CREATE TABLE IF NOT EXISTS design_marks (
  id TEXT PRIMARY KEY, apartment_id TEXT NOT NULL REFERENCES apartments(id), instance_id TEXT NOT NULL,
  product_id TEXT NOT NULL, purchased INTEGER NOT NULL, design_version INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_ledger (
  id TEXT PRIMARY KEY, session_id TEXT, project_id TEXT, purpose TEXT NOT NULL, status TEXT NOT NULL,
  reserved_usd REAL NOT NULL, actual_usd REAL, data TEXT, created_at TEXT NOT NULL, settled_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class DB:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def exec(self, sql: str, args: tuple = ()) -> None:
        with self.tx() as c:
            c.execute(sql, args)

    # ---------------------------------------------------------- sessions/projects
    def get_or_create_session(self, token_hash: str) -> str:
        row = self.one("SELECT id FROM sessions WHERE token_hash=?", (token_hash,))
        if row:
            return row["id"]
        sid = new_id("ses")
        self.exec("INSERT INTO sessions VALUES (?,?,?)", (sid, token_hash, now()))
        return sid

    def create_project(self, session_id: str, name: str, room_type: str, mode: str, is_demo: bool) -> str:
        pid = new_id("prj")
        self.exec(
            "INSERT INTO projects VALUES (?,?,?,?,?,?,?)",
            (pid, session_id, name, room_type, mode, int(is_demo), now()),
        )
        return pid

    def project_for(self, project_id: str, session_id: str) -> dict | None:
        """Ownership check: another session gets None (the API answers 404, not 403)."""
        return self.one("SELECT * FROM projects WHERE id=? AND session_id=?", (project_id, session_id))

    # ---------------------------------------------------------- versions (append-only)
    def _next_version(self, c, table: str, project_id: str) -> int:
        row = c.execute(f"SELECT COALESCE(MAX(version),0)+1 FROM {table} WHERE project_id=?", (project_id,)).fetchone()
        return int(row[0])

    def head(self, table: str, project_id: str) -> dict | None:
        row = self.one(f"SELECT * FROM {table} WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,))
        if row and "data" in row:
            row["data"] = json.loads(row["data"])
        return row

    def versions(self, table: str, project_id: str) -> list[dict]:
        rows = self.all(f"SELECT * FROM {table} WHERE project_id=? ORDER BY version DESC", (project_id,))
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows

    def version_by_id(self, table: str, project_id: str, vid: str) -> dict | None:
        row = self.one(f"SELECT * FROM {table} WHERE project_id=? AND id=?", (project_id, vid))
        if row:
            row["data"] = json.loads(row["data"])
        return row

    def add_room_version(self, project_id, data: dict, source_ids, method, model, prompt_version, input_hash, summary) -> dict:
        vid = new_id("room")
        with self.tx() as c:
            version = self._next_version(c, "room_versions", project_id)
            parent = c.execute(
                "SELECT id FROM room_versions WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)
            ).fetchone()
            c.execute(
                "INSERT INTO room_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (vid, project_id, version, parent[0] if parent else None, json.dumps(source_ids), method,
                 model, prompt_version, input_hash, json.dumps(data), summary, now()),
            )
        return self.version_by_id("room_versions", project_id, vid)

    def add_preference_version(self, project_id, data: dict, summary: str, method: str) -> dict:
        vid = new_id("pref")
        with self.tx() as c:
            version = self._next_version(c, "preference_versions", project_id)
            parent = c.execute(
                "SELECT id FROM preference_versions WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)
            ).fetchone()
            c.execute(
                "INSERT INTO preference_versions VALUES (?,?,?,?,?,?,?,?)",
                (vid, project_id, version, parent[0] if parent else None, json.dumps(data), summary, method, now()),
            )
        return self.version_by_id("preference_versions", project_id, vid)

    def add_plan_version(self, project_id, data: dict, room_version_id, preference_version_id, product_refs, summary) -> dict:
        vid = new_id("plan")
        with self.tx() as c:
            version = self._next_version(c, "plan_versions", project_id)
            parent = c.execute(
                "SELECT id FROM plan_versions WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)
            ).fetchone()
            c.execute(
                "INSERT INTO plan_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (vid, project_id, version, parent[0] if parent else None, room_version_id, preference_version_id,
                 json.dumps(product_refs), json.dumps(data), summary, now()),
            )
        return self.version_by_id("plan_versions", project_id, vid)

    # ---------------------------------------------------------- products
    def upsert_snapshot(self, snap: dict, content_hash: str, project_id: str | None, source_asset_id: str | None = None) -> None:
        """Global catalog rows use scope ''; imported listings are scoped to one project, so the same
        URL imported by two projects yields two independent rows (no loss, no leak)."""
        with self.tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO product_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
                (snap["id"], project_id or "", content_hash, json.dumps(snap), snap.get("checked_at"), snap["status"],
                 snap.get("origin", "curated_catalog"), source_asset_id, now()),
            )

    def project_snapshots(self, project_id: str) -> list[dict]:
        rows = self.all("SELECT data FROM product_snapshots WHERE scope=? ORDER BY created_at", (project_id,))
        return [json.loads(r["data"]) for r in rows]

    # ---------------------------------------------------------- events
    def event(self, kind: str, data: dict, project_id: str | None = None, session_id: str | None = None) -> None:
        self.exec(
            "INSERT INTO run_events VALUES (?,?,?,?,?,?)",
            (new_id("evt"), project_id, session_id, kind, json.dumps(data, default=str), now()),
        )

    def events(self, project_id: str, limit: int = 200) -> list[dict]:
        rows = self.all("SELECT * FROM run_events WHERE project_id=? ORDER BY created_at DESC LIMIT ?", (project_id, limit))
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows

    # ---------------------------------------------------------- apartments (groups of per-room projects)
    def create_apartment(self, session_id: str, name: str, preset: str, bedrooms: int, bathrooms: int,
                         rooms: list[tuple[str, str, str]]) -> str:
        """rooms: (project name, room_type/role, label). Creates one ordinary project per furnished room."""
        aid = new_id("apt")
        with self.tx() as c:
            c.execute("INSERT INTO apartments VALUES (?,?,?,?,?,?,?)",
                      (aid, session_id, name, preset, bedrooms, bathrooms, now()))
            for n, (pname, role, label) in enumerate(rooms):
                pid = new_id("prj")
                c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?)", (pid, session_id, pname, role, "live", 0, now()))
                c.execute("INSERT INTO apartment_rooms VALUES (?,?,?,?,?)", (aid, pid, role, label, n))
        return aid

    def add_apartment_context(self, apartment_id: str, data: dict) -> dict:
        """Append-only: each edit of the shared apartment context is a new version."""
        cid = new_id("ctx")
        with self.tx() as c:
            version = int(c.execute("SELECT COALESCE(MAX(version),0)+1 FROM apartment_context WHERE apartment_id=?",
                                    (apartment_id,)).fetchone()[0])
            c.execute("INSERT INTO apartment_context VALUES (?,?,?,?,?)", (cid, apartment_id, version, json.dumps(data), now()))
        return {"id": cid, "version": version, "data": data}

    def apartment_context(self, apartment_id: str) -> dict | None:
        row = self.one("SELECT * FROM apartment_context WHERE apartment_id=? ORDER BY version DESC LIMIT 1", (apartment_id,))
        if row:
            row["data"] = json.loads(row["data"])
        return row

    def apartment_for(self, apartment_id: str, session_id: str) -> dict | None:
        return self.one("SELECT * FROM apartments WHERE id=? AND session_id=?", (apartment_id, session_id))

    def apartment_rooms(self, apartment_id: str) -> list[dict]:
        return self.all("SELECT ar.*, p.name, p.room_type FROM apartment_rooms ar JOIN projects p ON p.id = ar.project_id "
                        "WHERE ar.apartment_id=? ORDER BY ar.ordinal", (apartment_id,))

    def apartment_of_project(self, project_id: str) -> dict | None:
        return self.one("SELECT a.id, a.name, ar.label FROM apartment_rooms ar JOIN apartments a ON a.id = ar.apartment_id "
                        "WHERE ar.project_id=?", (project_id,))

    def delete_apartment_links(self, apartment_id: str, session_id: str) -> list[str]:
        """Remove the apartment grouping; returns its project ids (deleted separately by the caller)."""
        with self.tx() as c:
            if not c.execute("SELECT 1 FROM apartments WHERE id=? AND session_id=?", (apartment_id, session_id)).fetchone():
                return []
            pids = [r[0] for r in c.execute("SELECT project_id FROM apartment_rooms WHERE apartment_id=?", (apartment_id,))]
            c.execute("DELETE FROM apartment_rooms WHERE apartment_id=?", (apartment_id,))
            c.execute("DELETE FROM apartment_context WHERE apartment_id=?", (apartment_id,))
            c.execute("DELETE FROM research_results WHERE apartment_id=?", (apartment_id,))
            c.execute("DELETE FROM place_discovery WHERE apartment_id=?", (apartment_id,))
            for t in ("design_marks", "design_versions", "plan_maps"):
                c.execute(f"DELETE FROM {t} WHERE apartment_id=?", (apartment_id,))
            c.execute("DELETE FROM apartments WHERE id=?", (apartment_id,))
        return pids

    # ---------------------------------------------------------- shared building discovery (append-only)
    def add_place_discovery(self, session_id: str, apartment_id: str | None, project_id: str, building_key: str | None,
                            data: dict) -> dict:
        """Scope = the apartment (shared by its rooms) or, for a single room, that project. Never room geometry."""
        did = new_id("disc")
        with self.tx() as c:
            col, val = ("apartment_id", apartment_id) if apartment_id else ("project_id", project_id)
            extra = "" if apartment_id else " AND apartment_id IS NULL"
            version = int(c.execute(f"SELECT COALESCE(MAX(version),0)+1 FROM place_discovery WHERE {col}=?{extra}",
                                    (val,)).fetchone()[0])
            c.execute("INSERT INTO place_discovery VALUES (?,?,?,?,?,?,?,?)",
                      (did, session_id, apartment_id, project_id, version, building_key, json.dumps(data), now()))
        return self.place_discovery_by_id(did)

    def place_discovery_by_id(self, did: str) -> dict | None:
        row = self.one("SELECT * FROM place_discovery WHERE id=?", (did,))
        if row:
            row["data"] = json.loads(row["data"])
        return row

    def latest_place_discovery(self, session_id: str, apartment_id: str | None, project_id: str) -> dict | None:
        if apartment_id:
            row = self.one("SELECT * FROM place_discovery WHERE session_id=? AND apartment_id=? ORDER BY version DESC LIMIT 1",
                           (session_id, apartment_id))
        else:
            row = self.one("SELECT * FROM place_discovery WHERE session_id=? AND project_id=? AND apartment_id IS NULL "
                           "ORDER BY version DESC LIMIT 1", (session_id, project_id))
        if row:
            row["data"] = json.loads(row["data"])
        return row

    # ---------------------------------------------------------- shopping checklist (append-only; latest row wins)
    def add_plan_selection(self, project_id: str, plan_key: str, plan_version: int) -> None:
        self.exec("INSERT INTO plan_selection VALUES (?,?,?,?,?)", (new_id("sel"), project_id, plan_key, plan_version, now()))

    def plan_selection(self, project_id: str) -> dict | None:
        return self.one("SELECT * FROM plan_selection WHERE project_id=? ORDER BY rowid DESC LIMIT 1", (project_id,))

    def add_purchase_mark(self, project_id: str, product_id: str, category: str, purchased: bool, plan_key: str,
                          plan_version: int) -> dict:
        mid = new_id("buy")
        self.exec("INSERT INTO purchase_marks VALUES (?,?,?,?,?,?,?,?)",
                  (mid, project_id, product_id, category, int(purchased), plan_key, plan_version, now()))
        return self.one("SELECT * FROM purchase_marks WHERE id=?", (mid,))

    def purchase_status(self, project_id: str) -> dict[str, dict]:
        """Current mark per product id (the latest row for each product)."""
        rows = self.all("SELECT * FROM purchase_marks WHERE project_id=? ORDER BY rowid", (project_id,))
        return {r["product_id"]: r for r in rows}

    # ---------------------------------------------------------- whole-apartment design (append-only)
    def add_plan_map(self, apartment_id: str, source_id: str, input_hash: str, method: str, model: str | None,
                     prompt_version: str, data: dict, call: dict | None) -> dict:
        mid = new_id("map")
        self.exec("INSERT INTO plan_maps VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (mid, apartment_id, source_id, input_hash, method, model, prompt_version, json.dumps(data),
                   json.dumps(call), now()))
        return self.plan_map(mid)

    def plan_map(self, map_id: str | None) -> dict | None:
        if not map_id:
            return None
        row = self.one("SELECT * FROM plan_maps WHERE id=?", (map_id,))
        if row:
            row["data"] = json.loads(row["data"])
            row["call"] = json.loads(row["call"]) if row["call"] else None
        return row

    def plan_map_by_hash(self, apartment_id: str, input_hash: str) -> dict | None:
        row = self.one("SELECT id FROM plan_maps WHERE apartment_id=? AND input_hash=? ORDER BY rowid DESC LIMIT 1",
                       (apartment_id, input_hash))
        return self.plan_map(row["id"]) if row else None

    def add_design_version(self, apartment_id: str, data: dict, plan_map_id: str | None, summary: str,
                           expected_version: int | None) -> dict | None:
        """Append a design version. With `expected_version`, refuses (returns None) if the head moved on."""
        did = new_id("dsg")
        with self.tx() as c:
            head = c.execute("SELECT id, version FROM design_versions WHERE apartment_id=? ORDER BY version DESC LIMIT 1",
                             (apartment_id,)).fetchone()
            if expected_version is not None and (head[1] if head else 0) != expected_version:
                return None
            c.execute("INSERT INTO design_versions VALUES (?,?,?,?,?,?,?,?)",
                      (did, apartment_id, (head[1] if head else 0) + 1, head[0] if head else None, plan_map_id,
                       json.dumps(data), summary, now()))
        return self.design_version(did)

    def design_version(self, did: str) -> dict | None:
        row = self.one("SELECT * FROM design_versions WHERE id=?", (did,))
        if row:
            row["data"] = json.loads(row["data"])
        return row

    def design_head(self, apartment_id: str) -> dict | None:
        row = self.one("SELECT id FROM design_versions WHERE apartment_id=? ORDER BY version DESC LIMIT 1", (apartment_id,))
        return self.design_version(row["id"]) if row else None

    def design_versions(self, apartment_id: str) -> list[dict]:
        return self.all("SELECT id, version, plan_map_id, summary, created_at FROM design_versions WHERE apartment_id=? "
                        "ORDER BY version DESC", (apartment_id,))

    def add_design_mark(self, apartment_id: str, instance_id: str, product_id: str, purchased: bool, version: int) -> None:
        self.exec("INSERT INTO design_marks VALUES (?,?,?,?,?,?,?)",
                  (new_id("dbuy"), apartment_id, instance_id, product_id, int(purchased), version, now()))

    def design_marks(self, apartment_id: str) -> dict[str, dict]:
        """Latest mark per piece instance."""
        rows = self.all("SELECT * FROM design_marks WHERE apartment_id=? ORDER BY rowid", (apartment_id,))
        return {r["instance_id"]: r for r in rows}

    # ---------------------------------------------------------- explicit deletion
    def delete_project(self, project_id: str, session_id: str) -> list[str]:
        """Explicit user deletion. Returns storage paths to remove."""
        with self.tx() as c:
            owned = c.execute("SELECT 1 FROM projects WHERE id=? AND session_id=?", (project_id, session_id)).fetchone()
            if not owned:
                return []
            paths = [r[0] for r in c.execute("SELECT storage_path FROM source_assets WHERE project_id=?", (project_id,))]
            paths += [r[0] for r in c.execute("SELECT storage_path FROM derivatives WHERE project_id=?", (project_id,))]
            c.execute("DELETE FROM source_provenance WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM research_results WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM place_discovery WHERE project_id=? AND apartment_id IS NULL", (project_id,))
            c.execute("DELETE FROM plan_selection WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM purchase_marks WHERE project_id=?", (project_id,))
            for table in ("derivatives", "source_assets", "room_versions", "preference_versions", "plan_versions"):
                c.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM product_snapshots WHERE scope=?", (project_id,))
            c.execute("DELETE FROM run_events WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM apartment_rooms WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM projects WHERE id=?", (project_id,))
        return paths
