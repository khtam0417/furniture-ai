"""HTTP smoke test against a RUNNING local server (default http://127.0.0.1:8000). No AI calls:
uses demo projects only. Usage: .venv/bin/python -I tools/http_smoke.py [base_url]"""

import http.cookiejar
import json
import sys
import time
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with opener.open(r, timeout=30) as resp:
        raw = resp.read()
        return resp.status, resp.headers.get("content-type", ""), raw


for _ in range(60):
    try:
        req("GET", "/api/status")
        break
    except OSError:
        time.sleep(0.5)

status, ctype, body = req("GET", "/")
assert status == 200 and "text/html" in ctype and b'<div id="root">' in body, "frontend not served"
print("GET / -> compiled frontend served")
print("status:", json.loads(req("GET", "/api/status")[2]))
for rt in ("bedroom", "studio"):
    s = json.loads(req("POST", "/api/demo", {"room_type": rt})[2])
    pid = s["project"]["id"]
    plans = s["plans"]["data"]["plans"]
    print(f"{rt}: {len(plans)} plan(s):", [(p["key"], p["subtotal_cents"] / 100, p["fit_summary"]) for p in plans])
    src = s["sources"][0]["id"]
    st, ct, img = req("GET", f"/api/projects/{pid}/sources/{src}/preview")
    assert st == 200 and ct == "image/jpeg" and img[:2] == b"\xff\xd8"
    e = json.loads(req("POST", f"/api/projects/{pid}/edit", {"message": "keep the dresser and add a bookcase"})[2])
    print("   edit:", e["method"], e["changes"])
    h = json.loads(req("GET", f"/api/projects/{pid}/history")[2])
    print("   versions: plans", [p["version"] for p in h["plans"]], "prefs", [p["version"] for p in h["preferences"]])
    if rt == "studio":
        sug = s["room"]["data"]["plan_dimension_suggestions"][0]
        s2 = json.loads(req("POST", f"/api/projects/{pid}/scale", {"width_in": sug["width_in"], "depth_in": sug["depth_in"],
                                                                 "basis": "plan_confirmed", "source_ids": sug["source_ids"],
                                                                 "exact_unit_confirmed": True})[2])
        print("   after confirming synthetic plan size:", [(p["key"], p["fit_summary"]) for p in s2["plans"]["data"]["plans"]])
    print("   export starts:", json.loads(req("GET", f"/api/projects/{pid}/export")[2])["markdown"][:70].replace("\n", " "))
print("HTTP SMOKE OK")
