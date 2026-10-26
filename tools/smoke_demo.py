"""Offline smoke run of the synthetic demo flow (no network, no AI). Uses a temporary storage dir."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["FURNISHAI_DISABLE_LIVE"] = "1"
os.environ["FURNISHAI_STORAGE_DIR"] = tempfile.mkdtemp(prefix="furnishai_smoke_")

from fastapi.testclient import TestClient  # noqa: E402

from furnishai.app import create_app  # noqa: E402

c = TestClient(create_app())
print(c.get("/api/status").json())
for rt in ("bedroom", "studio"):
    s = c.post("/api/demo", json={"room_type": rt}).json()
    ps = s["plans"]["data"]
    print(rt, "scale:", s["room"]["data"]["room"]["scale_status"])
    for p in ps["plans"]:
        print("  ", p["key"], p["subtotal_cents"], p["fit_summary"], [i["name"][:28] for i in p["items"]])
    print("  conflicts:", ps["conflicts"], "\n  notes:", ps["notes"])
    print("  suggestions:", s["room"]["data"]["plan_dimension_suggestions"])
    pid = s["project"]["id"]
    if rt == "studio":
        sug = s["room"]["data"]["plan_dimension_suggestions"][0]
        s2 = c.post(f"/api/projects/{pid}/scale", json={"width_in": sug["width_in"], "depth_in": sug["depth_in"],
                                                         "basis": "plan_confirmed", "source_ids": sug["source_ids"],
                                                         "exact_unit_confirmed": True}).json()
        for p in s2["plans"]["data"]["plans"]:
            print("  scaled:", p["key"], p["fit_summary"], [(i["category"], i["fit_label"]) for i in p["items"]])
    r = c.post(f"/api/projects/{pid}/edit", json={"message": "Lower the budget to $700, keep the dresser and add a bookcase"}).json()
    print("  edit:", r["changes"])
    print("  plan changes:", r["plan_changes"][:5], r["state"]["plans"]["data"]["conflicts"])
print(c.get(f"/api/projects/{pid}/export").json()["markdown"][:600])
