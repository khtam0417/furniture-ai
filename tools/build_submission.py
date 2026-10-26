"""Build the two course deliverables, report.html and slides.html, as single self-contained files.

Usage (standard-library Python 3.10+; no network, no database, no secrets):
  python3 -I tools/build_submission.py --evidence <dir> --vendor <dir> --output <dir>

--evidence must contain: 01-archive-plans.jpg ... 06-downloads.jpg, measured-usage.json, safety-runtime-tests.txt,
download-verification.json, and research-and-pilot.json (here or in the evidence folder's parent).
--vendor must contain the official reveal.js build: reveal.js and reveal.css (inlined into slides.html).

Every number below is either read from those evidence files at build time (token/cost table, test excerpt, links)
or is a fact of the recorded October 26, 2026 run, written out by hand and checked against the evidence where the
evidence contains it. The builder refuses to run if the evidence totals differ from the figures the text quotes.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

REPO_URL = "https://github.com/khtam0417/furniture-ai"
AUTHOR = "Ken Tam"
PRODUCT = "Furniture AI"
PAGES = 12

SHOTS = {
    "01": "01-archive-plans.jpg", "02": "02-selected-plan.jpg", "03": "03-arrange-map.jpg",
    "04": "04-mattress-alternative.jpg", "05": "05-complete-checklist.jpg", "06": "06-downloads.jpg",
    "07": "07-reviewed-map.jpg", "08": "08-fresh-clone-example.jpg",
}
EXTRA_JSON = ["fresh-clone-verification.json", "manual-review.json", "repository-access.json"]
# Figures the prose quotes; the build stops if the evidence says otherwise.
EXPECT = {"input_tokens": 67608, "cached_input_tokens": 14255, "output_tokens": 4751, "cache_write_tokens": 325,
          "web_search_calls": 9, "web_search_fee_usd": 0.09, "estimated_cost_usd": 0.09786147,
          "all_token_cost_usd": 0.00786147, "latency_s": 62.21}
RUNS_PER_USER_MONTH = 4  # stated assumption, not a measurement


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def money(x: float, places: int = 2) -> str:
    return f"${x:,.{places}f}"


# --------------------------------------------------------------------------- evidence
def load_evidence(ev: Path) -> dict:
    missing = [n for n in list(SHOTS.values()) + ["measured-usage.json", "safety-runtime-tests.txt",
                                                  "download-verification.json"] + EXTRA_JSON if not (ev / n).is_file()]
    rp = ev / "research-and-pilot.json"
    if not rp.is_file():
        rp = ev.parent / "research-and-pilot.json"
    if not rp.is_file():
        missing.append("research-and-pilot.json")
    if missing:
        sys.exit("missing evidence: " + ", ".join(missing))
    usage = json.loads((ev / "measured-usage.json").read_text())
    t = usage["totals"]
    for k, v in EXPECT.items():
        if abs(float(t[k]) - v) > 1e-9:
            sys.exit(f"evidence mismatch for {k}: evidence {t[k]} vs text {v}")
    tests = (ev / "safety-runtime-tests.txt").read_text()
    m = re.search(r"=+ (\d+) passed in ([\d.]+)s =+", tests)
    if not m or m.group(1) != "37" or "failed" in tests.split("collected", 1)[-1].split("====")[-1]:
        sys.exit("safety test evidence must show 37 passed and no failures")
    dl = json.loads((ev / "download-verification.json").read_text())
    if dl.get("xlsx_link_count") != 6 or not dl.get("html_has_total"):
        sys.exit("download verification evidence does not match the text (6 links, total present)")
    fresh = json.loads((ev / "fresh-clone-verification.json").read_text())
    review = json.loads((ev / "manual-review.json").read_text())
    access = json.loads((ev / "repository-access.json").read_text())
    if not fresh.get("fresh_clone") or "479 passed" not in fresh.get("backend_tests", "").replace(",", ", "):
        sys.exit("fresh-clone evidence does not show the 479-passed backend run quoted in the text")
    if len(review.get("ui_actions", [])) != 3 or access.get("invitation") != "pending acceptance":
        sys.exit("manual-review / repository-access evidence does not match the text (3 fixes; invitation pending)")
    images = {}
    for k, n in SHOTS.items():
        b = (ev / n).read_bytes()
        if b[:2] != b"\xff\xd8":
            sys.exit(f"{n} is not a JPEG")
        images[k] = "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")
    return {"usage": usage, "tests": tests, "tests_summary": m.group(0).strip("= "), "downloads": dl,
            "research": json.loads(rp.read_text()), "img": images, "fresh": fresh}


# --------------------------------------------------------------------------- shared pieces
def diagram_svg(compact: bool = False) -> str:
    """Editable native SVG architecture diagram (no decorative UI). `compact`: the short report version (1000x300,
    large labels only; the agent table below it carries the details)."""
    if compact:
        ink, teal, line, soft = "#25313a", "#0f766e", "#94a3ab", "#e7f3f1"

        def cbox(x, y, bw, bh, title, sub=None, stroke=line, fill="#ffffff"):
            ty = y + (bh / 2 + 7 if not sub else bh / 2 - 4)
            out = (f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="9" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
                   f'<text x="{x + bw / 2}" y="{ty}" text-anchor="middle" font-size="21" font-weight="700" fill="{ink}">{esc(title)}</text>')
            if sub:
                out += f'<text x="{x + bw / 2}" y="{ty + 23}" text-anchor="middle" font-size="18" fill="#46545e">{esc(sub)}</text>'
            return out

        def seg(points, head=False):
            return (f'<polyline points="{points}" fill="none" stroke="{ink}" stroke-width="2"'
                    + (' marker-end="url(#ahc)"/>' if head else "/>"))
        xs = [110, 305, 500, 695, 890]
        names = [("Plan Map", "typed agent"), ("Room Evidence", "typed agent"), ("Preferences", "typed agent"),
                 ("Design Helper", "typed agent"), ("Web research", "web_search only")]
        used = {0, 4}
        parts = [
            '<svg viewBox="0 0 1000 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="dgc" '
            'class="diagram" style="display:block;width:100%;height:auto" font-family="Helvetica, Arial, sans-serif">',
            '<title id="dgc">Browser to orchestrator to storage; the orchestrator calls four typed gpt-6-luna agents and a '
            'web-research call; every output goes to deterministic code</title>',
            f'<defs><marker id="ahc" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{ink}"/></marker></defs>',
            cbox(20, 10, 230, 60, "Browser (React)"),
            cbox(330, 10, 340, 60, "Orchestrator (Python)", stroke=teal, fill=soft),
            cbox(750, 10, 230, 60, "SQLite + originals"),
            seg("250,40 328,40", True), seg("670,40 748,40", True),
            seg("500,70 500,95"), seg(f"{xs[0]},95 {xs[-1]},95"),
            *(seg(f"{x},95 {x},118", True) for x in xs),
        ]
        for i, (x, (t, s)) in enumerate(zip(xs, names)):
            parts.append(cbox(x - 90, 120, 180, 70, t, s, stroke=teal if i in used else line))
        parts += [
            *(seg(f"{x},190 {x},215") for x in xs), seg(f"{xs[0]},215 {xs[-1]},215"), seg("500,215 500,238", True),
            cbox(20, 240, 960, 55, "Deterministic code: validation · placement · budget · checklist", stroke=ink),
            "</svg>",
        ]
        return "".join(parts)
    w, h = 1000, 472
    teal, ink, line, soft = "#0f766e", "#25313a", "#94a3ab", "#e7f3f1"

    def box(x, y, bw, bh, title, sub, fill="#ffffff", stroke=line, tcol=ink, bold=True):
        return (f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
                f'<text x="{x + bw / 2}" y="{y + 24}" text-anchor="middle" font-size="17" font-weight="{700 if bold else 400}" fill="{tcol}">{esc(title)}</text>'
                + "".join(f'<text x="{x + bw / 2}" y="{y + 46 + 19 * i}" text-anchor="middle" font-size="13.5" fill="#46545e">{esc(s)}</text>'
                          for i, s in enumerate(sub)))

    def arrow(x1, y1, x2, y2, label=""):
        mid = ((x1 + x2) / 2, (y1 + y2) / 2)
        lab = (f'<text x="{mid[0] + 6}" y="{mid[1] - 6}" font-size="12.5" fill="#46545e">{esc(label)}</text>' if label else "")
        return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{ink}" stroke-width="1.6" marker-end="url(#ah)"/>{lab}'

    parts = [
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="dgt" class="diagram" font-family="Helvetica, Arial, sans-serif">',
        '<title id="dgt">Furniture AI architecture: a code orchestrator calls typed gpt-6-luna agents and deterministic code</title>',
        f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{ink}"/></marker></defs>',
        box(30, 20, 200, 100, "Browser (React)", ["4 steps: plan, arrange,", "choose, checklist"]),
        box(300, 20, 400, 100, "Orchestrator (FastAPI, plain Python)", ["decides every call; validates every output;", "versions, budget, usage ledger, limits"],
            fill=soft, stroke=teal),
        box(770, 20, 200, 100, "SQLite + originals", ["append-only versions;", "immutable source files"]),
        arrow(230, 70, 298, 70), arrow(700, 70, 768, 70),
        # Orthogonal bus in the empty band between the rows; side routes run outside every box.
        f'<polyline points="500,120 500,142" fill="none" stroke="{ink}" stroke-width="1.6"/>',
        f'<polyline points="12,142 990,142" fill="none" stroke="{ink}" stroke-width="1.6"/>',
        arrow(137, 142, 137, 170), arrow(372, 142, 372, 170), arrow(612, 142, 612, 170), arrow(855, 142, 855, 170),
        box(30, 172, 215, 108, "Plan Map agent", ["1 plan image + 2 crops", "→ typed rooms, walls,", "doors, fixtures"], stroke=teal),
        box(260, 172, 225, 108, "Room Evidence agent", ["room photos → typed", "evidence; geometry stays", "an unverified estimate"]),
        box(500, 172, 225, 108, "Preference Edit agent", ["free text → typed", "patch applied by code"]),
        box(740, 172, 230, 108, "Design Helper agent", ["answers + typed proposals;", "nothing changes until", "the user ticks Apply"]),
        f'<text x="30" y="303" font-size="14" font-weight="700" fill="{teal}">Four typed agents above: gpt-6-luna via Portkey (Responses API), typed outputs, no app tools</text>',
        box(30, 320, 290, 140, "Web research call", ["built-in web_search tool only", "(observed 3 searches per call)", "→ cited URLs = leads, filtered", "to approved stores/marketplaces"], stroke=teal),
        box(350, 320, 620, 140, "Deterministic code (no model)", [
            "SafeFetcher: public-IP DNS check, pinned connection, every redirect hop checked",
            "Page parsers: price, size, condition, stock read from the page itself",
            "Room use, placement, fit notes; budget shares and whole-budget refusal",
            "Checklist HTML + Excel downloads; usage reservations and caps"]),
        arrow(320, 390, 348, 390),
        f'<polyline points="12,142 12,390 28,390" fill="none" stroke="{ink}" stroke-width="1.6" marker-end="url(#ah)"/>',
        f'<polyline points="990,142 990,390 972,390" fill="none" stroke="{ink}" stroke-width="1.6" marker-end="url(#ah)"/>',
        "</svg>",
    ]
    return "".join(parts)


AGENTS = [
    ("Plan Map agent", "plan-map-v4-crops", "One floor-plan image plus two framed crops of the same image in one call",
     "Typed map: room polygons, labels, printed sizes, walls, openings, fixtures", "Used in this run (1 call)"),
    ("Room Evidence agent", "room-evidence-v5-geometry-shape","EXIF-stripped room photos", "Typed evidence; photo geometry stays an unverified estimate",
     "Not used in this run (no photos)"),
    ("Preference Edit agent", "preference-patch-v3", "A free-text request", "Typed preference patch that code applies", "Not used in this run"),
    ("Design Helper agent", "design-assistant-v1", "A question plus the design's settings and pieces (never address, unit, images or links)",
     "Answer + typed proposals; applied only after the user ticks them", "Not used in this run"),
    ("Web research call", "furniture-products-v4-eligible-sites","Search text: piece type, price ceiling, condition, stores, public city/ZIP",
     "Cited URLs only, filtered to approved sources, then each page is read by code", "Used in this run (3 calls)"),
]

CSS_BASE = """
:root{--ink:#1f2a32;--head:#25313a;--teal:#0f766e;--teal-d:#0b5e58;--paper:#fbfaf7;--rule:#d9dee1;--muted:#56636c;--tint:#e7f3f1}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
h1,h2,h3{font-family:Georgia,"Times New Roman",serif;color:var(--head);font-weight:600}
a{color:var(--teal-d)}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.diagram{width:100%;height:auto;display:block}
"""

REPORT_CSS = CSS_BASE + """
@page{size:Letter;margin:0.55in}
html{background:#e9ecee}
body{font-size:11pt;line-height:1.42}
.page{background:var(--paper);width:8.5in;min-height:11in;margin:0.35in auto;padding:0.55in;box-shadow:0 2px 14px rgba(0,0,0,.12);
 display:flex;flex-direction:column;position:relative}
.page::before{content:"";position:absolute;inset:0;pointer-events:none;
 background-image:linear-gradient(rgba(15,118,110,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(15,118,110,.035) 1px,transparent 1px);background-size:24px 24px}
.page>*{position:relative}
.runhead{display:flex;justify-content:space-between;font-size:8.5pt;color:var(--muted);border-bottom:1px solid var(--rule);padding-bottom:4px;margin-bottom:12px;letter-spacing:.02em}
.runfoot{margin-top:auto;display:flex;justify-content:space-between;font-size:8.5pt;color:var(--muted);border-top:1px solid var(--rule);padding-top:4px}
.kicker{font-size:8.5pt;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--teal);margin:0 0 2px}
h1{font-size:30pt;margin:0 0 6px;line-height:1.1}
h2{font-size:17pt;margin:0 0 8px}
h3{font-size:12pt;margin:12px 0 4px}
p{margin:0 0 8px}
ul,ol{margin:0 0 8px;padding-left:18px}
li{margin:0 0 3px}
.lead{font-size:12.5pt;line-height:1.45;color:var(--head)}
.callout{border-left:3px solid var(--teal);background:var(--tint);padding:8px 12px;margin:8px 0;border-radius:0 6px 6px 0}
.repo{border:1.5px solid var(--teal);border-radius:8px;padding:10px 14px;margin:10px 0;background:#fff}
.repo strong{color:var(--teal-d)}
.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.fact{border:1px solid var(--rule);border-radius:8px;padding:8px 10px;background:#fff}
.fact b{display:block;font-family:Georgia,serif;font-size:16pt;color:var(--teal-d)}
.fact span{font-size:9pt;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:9.5pt;margin:6px 0 10px;background:#fff}
th,td{border:1px solid var(--rule);padding:4px 6px;text-align:left;vertical-align:top}
th{background:#f1f4f5;color:var(--head)}
td.n,th.n{text-align:right;white-space:nowrap}
.shotrow{display:grid;grid-template-columns:1.6in 1fr;gap:16px;align-items:start;margin:4px 0 8px}
.shotpair{display:grid;grid-template-columns:1.5in 1.5in 1fr;gap:12px;align-items:start;margin:4px 0}
.tight .shotrow{grid-template-columns:1.42in 1fr}
.tight .shotpair{grid-template-columns:1.4in 1.4in 1fr}
.cover-clone{display:grid;grid-template-columns:2.9in 1fr;gap:14px;align-items:start;margin-top:8px}
.dense{font-size:10.4pt;line-height:1.38}
.dense li{margin-bottom:2px}
.figdiagram{width:100%;max-width:7.4in;margin:2px 0 8px;align-self:stretch}
figure{margin:0}
figure img{width:100%;height:auto;display:block;border:1px solid var(--rule);border-radius:6px;background:#fff}
figcaption{font-size:8.5pt;color:var(--muted);margin-top:3px;line-height:1.3}
pre.tests{font-size:7.6pt;line-height:1.3;background:#1f2a32;color:#e9f1ef;padding:8px 10px;border-radius:6px;white-space:pre-wrap;margin:6px 0}
.label{font-size:8pt;font-weight:700;color:var(--teal-d);text-transform:uppercase;letter-spacing:.08em}
.small{font-size:9pt;color:var(--muted)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.ref{font-size:8.5pt;color:var(--muted)}
@media print{
 html,body{background:none}
 .page{margin:0;width:auto;min-height:9.9in;padding:0;box-shadow:none;break-after:page;page-break-after:always}
 .page:last-child{break-after:auto;page-break-after:auto}
 .page::before{display:none}
 a{color:var(--teal-d);text-decoration:none}
}
@media screen and (max-width:900px){
 .page{width:auto;min-height:0;margin:10px;padding:18px}
 .shotrow,.shotpair,.two,.facts{grid-template-columns:1fr}
 .shotrow figure,.shotpair figure{max-width:320px}
}
"""


# --------------------------------------------------------------------------- report
def page(n: int, section: str, body: str, cls: str = "") -> str:
    return (f'<section class="page {cls}" id="p{n}"><div class="runhead"><span>{PRODUCT} · {AUTHOR}</span><span>{esc(section)}</span></div>'
            f'{body}<div class="runfoot"><span>Private repository: {REPO_URL}</span><span>Page {n} of {PAGES}</span></div></section>')


def fig(src: str, cap: str, alt: str) -> str:
    return f'<figure><img src="{src}" alt="{esc(alt)}"><figcaption>{cap}</figcaption></figure>'


def usage_table(u: dict) -> str:
    rows = []
    searches = 0
    for c in u["calls"]:
        if c["purpose"] == "plan_map":
            name = "Plan map"
        else:
            searches += 1
            name = f"Search {searches}"
        cw = "n/r" if c["cache_write_tokens"] is None else f'{c["cache_write_tokens"]:,}'
        ws = "—" if c["web_search_calls"] is None else str(c["web_search_calls"])
        rows.append(f'<tr><td style="white-space:nowrap">{name}<br><span class="small">{c["created_at"][11:19]}</span></td>'
                    f'<td class="n">{c["input_tokens"]:,}</td><td class="n">{c["cached_input_tokens"]:,}</td><td class="n">{cw}</td>'
                    f'<td class="n">{c["output_tokens"]:,}</td><td class="n">{ws}</td><td class="n">{c["latency_s"]:.2f} s</td>'
                    f'<td class="n">{money(c["actual_usd"], 5)}</td></tr>')
    t = u["totals"]
    rows.append(f'<tr><th>Total (4 calls)</th><th class="n">{t["input_tokens"]:,}</th><th class="n">{t["cached_input_tokens"]:,}</th>'
                f'<th class="n">{t["cache_write_tokens"]:,}*</th><th class="n">{t["output_tokens"]:,}</th><th class="n">{t["web_search_calls"]}</th>'
                f'<th class="n">{t["latency_s"]:.2f} s</th><th class="n">{money(t["estimated_cost_usd"], 5)}</th></tr>')
    return ('<table><tr><th>Call</th><th class="n">Input tokens</th><th class="n">Cached input<br>(part of input)</th>'
            '<th class="n">Cache write</th><th class="n">Output</th><th class="n">Web searches</th><th class="n">Model latency</th>'
            '<th class="n">Estimated cost</th></tr>' + "".join(rows) + "</table>"
            '<p class="small">Times are UTC on October 26, 2026. "Search 1–3" are the three web-research calls. * Cache-write tokens '
            'were reported only by the research calls; the plan-map call did not report them (n/r), so that value is unknown, '
            'not zero. Latency is the sum of model request times, not the end-to-end task time.</p>')


def tests_excerpt(text: str) -> str:
    keep = []
    for ln in text.splitlines():
        if ("test_a_14500_sofa" in ln or "injected_instruction" in ln or "unknown_sites_are_refused" in ln
                or "169.254.169.254" in ln or "redirect_to_metadata" in ln or "rebinding" in ln
                or "parent_env_used" in ln or "public_status_never_contains_key" in ln
                or "send_gpt_6_luna" in ln or "collected" in ln or re.search(r"\d+ passed in", ln)):
            ln = re.sub(r"^backend/tests/", "", ln)
            ln = re.sub(r"\s+\[\s*\d+%\]$", "", ln)
            keep.append(ln.strip())
    return "\n".join(esc(x) for x in keep)


def build_report(E: dict) -> str:
    img, u, t, R = E["img"], E["usage"], E["usage"]["totals"], E["research"]
    comp = {}
    for c in R["competitors"]:
        comp.setdefault(c["name"], []).append(c["url"])
    per_user = t["estimated_cost_usd"] * RUNS_PER_USER_MONTH
    fee_share = t["web_search_fee_usd"] / t["estimated_cost_usd"]
    pages = []

    # 1. Title + links ------------------------------------------------------
    pages.append(page(1, "1. Title + links", f"""
<p class="kicker">Final project report · October 26, 2026</p>
<h1>{PRODUCT}</h1>
<p class="lead">Furniture AI reads an apartment's published floor plan, lays out draft furniture in the rooms it finds,
and fills each piece with a real, dated product from a checked store page within one budget, ending in a printable
checklist and a spreadsheet.</p>
<p><b>Author:</b> {AUTHOR} (solo project)</p>
<div class="repo"><strong>PRIVATE REPOSITORY</strong> · <a href="{REPO_URL}">{REPO_URL}</a><br>
GitHub user <b>zlisto</b> was invited as a collaborator on October 26, 2026; the invitation is pending
acceptance.<br>
<b>App link:</b> none. Furniture AI is not publicly hosted; it runs locally from the repository. Start it with
<code>PYTHON=python3.12 ./run.sh --port 8000</code>, with <code>PORTKEY_API_KEY</code> in the repository folder or the
folder directly above it. <code>./run.sh --no-live</code> gives labelled synthetic examples that make no AI call. The
README provides the step-by-step setup.</div>
<div class="facts">
 <div class="fact"><b>6 of 6</b><span>furniture slots in the recorded run filled with checked products from 2 retailers</span></div>
 <div class="fact"><b>{money(2156.97)}</b><span>chosen total, inside a {money(2700)} item allowance ({money(3000)} budget minus 10% held back)</span></div>
 <div class="fact"><b>~{t["estimated_cost_usd"] * 100:.1f}¢</b><span>estimated model + search cost of that run (4 calls, from returned usage)</span></div>
</div>
<p style="margin-top:8px"><b>Evidence.</b> Every number comes from one of four labelled sources: the <b>recorded run</b>
(October 26, 2026, The Archive, New Haven), its <b>usage ledger</b>, <b>offline automated tests</b>, and one
<b>informal pilot</b>. No market statistics are used. The runtime model is <b>gpt-6-luna only</b>, through the course Portkey gateway; Claude
Code was the development tool only.</p>
<div class="cover-clone">{fig(img["08"], "Figure 0. Fresh clone, offline mode: the labelled synthetic Example bedroom.", "Synthetic example bedroom in a fresh clone")}
<div><p class="label">Fresh-clone check (no-live)</p>
<p class="small" style="color:var(--ink)">The private GitHub repository was cloned fresh and started with
<code>PYTHON=python3.12 ./run.sh --no-live --port 4092</code>. A harmless placeholder key sat in the parent folder's
<code>.env</code>, and the app found it there. The first HTTP response was confirmed within about 7.4 minutes of the
start (an upper bound, not a measured startup time). The UI loaded and the synthetic Example bedroom opened.</p>
<p class="small" style="color:var(--ink)">In that clone, <b>479 backend tests passed, 1 was skipped</b> (22.08 s; the
one warning is the expected image-guard warning). Separately, the 39 frontend unit tests, the typecheck and the
production build passed. This clone made no model request; the paid gpt-6-luna demo in Section 4 ran separately on the development machine.</p></div></div>
"""))

    # 2. Motivation ----------------------------------------------------------
    pages.append(page(2, "2. Motivation", """
<h2>2. Motivation</h2>
<p class="lead">Someone renting an unfurnished apartment has to buy a bed, a sofa and storage for rooms they may have
seen once, often from a marketing floor plan with no measurements they trust.</p>
<h3>Who has the problem</h3>
<p>The person I designed for is a renter moving into a new apartment with a fixed amount to spend. They usually have
three things: the building's published floor plan (an image on the leasing website, often a 3D marketing render), a
budget, and a rough idea of a style. They usually do not have a tape measure reading of every wall, a designer, or
time to keep twenty store tabs consistent.</p>
<h3>How it is handled today</h3>
<ul>
<li><b>Tab sprawl.</b> Each store has its own site, sizes and prices. Comparing a bed frame from one store with a sofa
from another means copying numbers into a list by hand, and the list goes stale as prices change.</li>
<li><b>Guessing the room.</b> A marketing render may omit dimensions or obscure boundaries; fixtures and openings
still need review. Measuring before moving in is often not possible, so people guess.</li>
<li><b>Budget drift.</b> It is easy to fall in love with one expensive piece and discover later that the rest of the
apartment no longer fits the budget.</li>
<li><b>Unclear sources.</b> General web search mixes official product pages with marketplaces, resellers and stale
listings; it is hard to tell what was actually checked and when.</li>
</ul>
<h3>Why it matters</h3>
<p>The cost is uncertainty rather than one dramatic failure: time spent re-checking, pieces that turn out too large,
and money spent before the whole set is known. I have not measured these costs for renters in general, so this report
makes no claim about how large they are. The aim of Furniture AI is narrower and testable: turn the plan the renter
already has into one consistent, budgeted, sourced shopping list, and say plainly what is approximate.</p>
<div class="callout"><b>Design principle.</b> The app should never pretend to know more than it does. Missing facts
stay missing, the plan reading is labelled as an estimate, every product carries the date its page was checked, and
the budget is enforced by code rather than by the model's judgement.</div>
<h3>What a good outcome looks like</h3>
<p>For the renter, success is a list they can act on: every piece they asked for has a real product with a price, a
size and a link; the total is inside the budget with money held back for delivery and tax; and anything uncertain
(a room the plan reader mislabelled, a product larger than its draft outline) is visible rather than hidden.</p>
"""))

    # 3. What is new ---------------------------------------------------------
    k, p5d, cona = comp.get("IKEA Kreativ", []), comp.get("Planner 5D", []), comp.get("Cona", [])
    pages.append(page(3, "3. What is new here", f"""
<h2>3. What is new here</h2>
<p>AI room planners already exist, and some overlap closely with parts of Furniture AI. I checked three on their own
official pages on October 26, 2026. I did not run a hands-on comparison, so the table below describes what each
product says it does, not a benchmark.</p>
<table>
<tr><th style="width:18%">Product</th><th>What its official pages describe</th><th style="width:30%">Overlap and difference</th></tr>
<tr><td><b>IKEA Kreativ</b></td><td>A free room designer that works from room photos, scans, manual dimensions or prebuilt
rooms; it can erase existing furniture and place or swap IKEA furnishings in a lifelike view of the real room.</td>
<td>Strong visualisation of one room; the catalogue is IKEA's own. Furniture AI is plan-first, covers the whole
apartment and mixes stores.</td></tr>
<tr><td><b>Planner 5D</b></td><td>AI recognition turns an uploaded 2D floor plan into an editable 3D project (paid plans).
Its documentation recommends a bird's-eye plan with dimensions and warns that renders or elevations cannot be
properly recreated.</td><td>Offers 3D editing. Furniture AI also works from the building's published plan, and
labels renders as approximate instead of rejecting them.</td></tr>
<tr><td><b>Cona</b></td><td>A room planner with drawing, upload and scanning, real brands (IKEA, CB2, Herman Miller) with prices
and purchase links, 2D/3D in the browser, AI auto-furnish, and one real measurement for scale.</td>
<td><b>The closest overlap</b>, including real priced products. I claim no advantage over it without a test.</td></tr>
</table>
<h3>What Furniture AI combines</h3>
<ol>
<li><b>Starts from the building, not a blank room.</b> For a known building it lists the leasing site's published plans
(19 for The Archive, filterable by bedroom count), so the renter picks a plan rather than drawing one.</li>
<li><b>Explicit uncertainty and provenance.</b> The plan reading is labelled approximate, rooms whose use is uncertain
get no automatic furniture, the original image is kept unchanged, and every product shows the date its page was
checked.</li>
<li><b>Budget-aware choices across several retailers.</b> One budget for the whole apartment, a share held back for
delivery and tax, a planning share per piece, and a server-side refusal of anything over what is left.</li>
<li><b>Editable arrangement and a portable result.</b> Pieces can be moved, removed or added; the result leaves the
app as a printable HTML checklist and an Excel file with working store links.</li>
</ol>
<p>This is a useful combination for renters, not a claim to be the first AI room planner or the best one. Competing
products do more in 3D, and Cona overlaps closely on priced products.</p>
<p class="ref">Sources (official pages, accessed October 26, 2026): IKEA Kreativ: {" ; ".join(esc(x) for x in k)}.
Planner 5D: {" ; ".join(esc(x) for x in p5d)}. Cona: {" ; ".join(esc(x) for x in cona)}.</p>
"""))

    # 4. Agents: roles, tools, diagram -------------------------------------------
    rows = "".join(f"<tr><td><b>{esc(a)}</b><br><span class='small'>{esc(v)}</span></td><td>{esc(i)}</td><td>{esc(o)}</td><td>{esc(r)}</td></tr>"
                   for a, v, i, o, r in AGENTS)
    pages.append(page(4, "4. The agents", f"""
<h2>4. The agents</h2>
<p>Furniture AI is a single orchestrator written in plain Python. It decides when to call a model and checks
everything a model returns. There are four typed agents built with PydanticAI and one bounded web-research call, all
on <b>gpt-6-luna</b> through the course Portkey Responses API.</p>
<div class="figdiagram">{diagram_svg(compact=True)}</div>
<table><tr><th style="width:21%">Agent (prompt version)</th><th>Input</th><th>Typed output</th><th style="width:17%">This run</th></tr>{rows}</table>
<p><b>Tools.</b> The four agents have no app tools: each request carries only the structured-output schema, so a model
cannot fetch a page, change a price or write to the database. The web-research call's only tool is the provider's
built-in web search; it returns cited URLs, which code treats as leads.</p>
<p><b>Model choice.</b> gpt-6-luna is the only model allowed on the course key. It can read images and return
structured output, which covers what the plan, photo, preference and helper agents need. I did not benchmark it
against other models. The model name is fixed in code, and tests check that requests go out with it.</p>
"""))

    # 5. Agents: run part 1 -----------------------------------------------------
    pages.append(page(5, "4. The agents: one real run (1/2)", f"""
<h2>One real run, step by step</h2>
<p>The demo was recorded in a real browser on October 26, 2026, about 16:06–16:12 EDT, with a room-use review
afterwards (16:23–16:25). Setup: a new place for <b>The Archive, 848 Chapel Street, New Haven, CT 06510</b>, used as
a public example building. Settings: <b>new items only</b>, modern style, delivery, and a <b>{money(3000, 0)}</b> budget
with 10% held back. No photos were uploaded.</p>
<div class="shotrow">{fig(img["01"], "Figure 1. The Archive's 19 published plans, filtered to 1 bed (8). The banner is the property's own marketing.", "Floor plan gallery for The Archive with the 1 bed filter")}
<div><p class="label">Step 1 · Find the building's plans (no AI)</p>
<p>The building comes from a checked list, so no search or model call is needed. The app shows the leasing site's 19
published plan types and filters them by bedroom count. It says these are plan types, not every unit variant, and that
banner text is the property's marketing, not verified availability.</p>
<p>I chose the published plan named <b>848 | 1x1 A</b>, one of the 8 one-bedroom plans. The app takes no size or area
from a plan's name. The public image is stored unchanged as the original; later steps work on versioned
derivatives.</p>
<p class="ref">Plan source: The Archive's official floor-plan page,
<a href="https://entrata.thearchiveapts.com/new-haven/the-archive/conventional/">entrata.thearchiveapts.com/new-haven/the-archive/conventional/</a>;
<a href="https://medialibrarycfo.entrata.com/10364/MLv3/4/22/2025/02/12/040525/67ad2935627c91.05890816574.png">public
plan image</a> (accessed October 26, 2026). Plan image © its owner; shown for academic illustration.</p></div></div>
<div class="shotrow">{fig(img["02"], "Figure 2. The selected plan as published, with the one action that calls the model.", "Selected plan with the Read floor plan button")}
<div><p class="label">Step 2 · Read the floor plan (Plan Map agent, 1 call)</p>
<p>"Read floor plan &amp; continue" sends the image plus two framed crops of it in one vision call. The model returns a
typed map; code validates the coordinates and decides each area's use from the evidence.</p>
<p><b>Result:</b> 7 areas. The plan has no printed room dimensions, so everything is drawn at an approximate relative
scale. The call used {u["calls"][0]["input_tokens"]:,} input tokens ({u["calls"][0]["cached_input_tokens"]:,} cached) and
{u["calls"][0]["output_tokens"]:,} output tokens, with {u["calls"][0]["latency_s"]} s of model time.</p></div></div>
""", "tight"))

    # 6. Agents: run part 2 -----------------------------------------------------
    pages.append(page(6, "4. The agents: one real run (2/2)", f"""
<div class="shotrow">{fig(img["07"], "Figure 3. The clean plan drawn by code after the room-use review (Living, Closet, Laundry corrected), with the six chosen pieces.", "Reviewed clean plan with the chosen furniture")}
<div><p class="label">Step 3 · Arrange your space (code only), then a human review</p>
<p>Code draws a clean plan from the map and places six draft pieces: a queen bed frame, queen mattress, nightstand,
dresser, sofa and coffee table. Kitchen, bath and closet areas are kept clear.</p>
<p><b>The model mislabelled three areas.</b> It called the living area Dining, a closet Balcony, and a utility space a
second Bath. After the first pass, I reviewed the map against the published plan and fixed all three with the app's
own room-use control: Dining to Living, Balcony to Closet, second Bath to Laundry.</p>
<p>Each fix is saved as a new map revision, the original AI reading is kept, and all six chosen products stayed
selected. This was a room-use review only. No geometry was measured or validated, the kitchen and circulation area
stays one kept-clear "Hall", and fit is not verified. 3D marketing renders like this need that review.</p></div></div>
<div class="shotrow">{fig(img["04"], "Figure 4. Mattress options with fit and budget lines; the user's own choice is marked Chosen.", "Mattress alternatives with budget lines")}
<div><p class="label">Step 4 · Choose furniture (3 web-research calls + code)</p>
<p>"Find furniture" handled the six piece types. Three already had enough saved options that fit the budget, so they
were not searched. The other three each got one web-research call (9 web searches in total, 3 per call). Only cited
pages from approved stores were kept as leads, and code reads a page before it can become an option.</p>
<p>"Choose for me" then filled all six slots for <b>{money(1956.97)}</b>. In the interface I swapped the mattress from
the $199 ÅSVANG to the $399 VALEVÅG; every option line shows its fit estimate and the remaining budget.</p>
<p class="label">Step 5 · Final checklist (code only)</p>
<p>The final list totals <b>{money(2156.97)}</b> for six items, all chosen, against a {money(2700)} item allowance.
The six pieces are listed with their prices in Section 7 (Figures 5–6). Both downloads were saved through the browser
and checked as files (see Section 7).</p></div></div>
"""))

    # 7. Tokenomics measured ----------------------------------------------------
    pages.append(page(7, "5. Tokenomics", f"""
<h2>5. Tokenomics</h2>
<p>These are the token counts the API returned for the recorded run, as stored in the app's usage ledger. Cost is an
<b>estimate</b>: returned usage priced with a dated local rate card in <code>usage.py</code>. That card uses
$0.10 per 1M input tokens, $0.01 cached input and $0.50 output, from the course pricing checked October 6, 2026. It adds
$0.125 per 1M cache-write tokens and a $0.01 fee per web search, both checked October 25, 2026. It is not an
invoice.</p>
{usage_table(u)}
<h3>What one run cost</h3>
<ul>
<li><b>Total estimated cost: {money(t["estimated_cost_usd"], 5)} (about {t["estimated_cost_usd"] * 100:.1f}¢)</b> for 4 model calls: 1 plan reading and 3 web-research calls.</li>
<li><b>Web search dominates.</b> The 9 searches cost {money(t["web_search_fee_usd"])}, about {fee_share * 100:.0f}% of the total. All tokens together cost only {money(t["all_token_cost_usd"], 5)}.</li>
<li><b>The plan reading was cheap.</b> It cost {money(u["calls"][0]["actual_usd"], 5)} (3,775 input, 2,908 output tokens).</li>
<li><b>Searches exceeded the request.</b> Each research call asked for at most 2 web searches, but the API reported 3 per call. I report the observed 9, not the requested 6; the per-call fee cap is not strictly enforced by the provider.</li>
<li><b>Cache hits were real but minor.</b> {t["cached_input_tokens"]:,} of the {t["input_tokens"]:,} input tokens ({t["cached_input_tokens"] / t["input_tokens"] * 100:.0f}%) were served from the cache.</li>
</ul>
<div class="callout"><b>How representative this is.</b> It is one illustrative run, not a typical sample. The app
already had a saved catalogue of dated products, so three of the six piece types needed no search. A first run with an
empty catalogue, or a secondhand search, would make more research calls.</div>
"""))

    # 8. Tokenomics scale + controls --------------------------------------------
    pages.append(page(8, "5. Tokenomics: scale and cost controls", f"""
<h3>Per user and at scale (stated assumption)</h3>
<p>Assume a renter runs the full flow <b>{RUNS_PER_USER_MONTH} times a month</b> while furnishing. This is an
assumption, not a measurement. Multiplying the measured run cost:</p>
<table><tr><th>Scale</th><th class="n">Monthly estimated model + search cost</th></tr>
<tr><td>1 user ({RUNS_PER_USER_MONTH} runs)</td><td class="n">{money(per_user)}</td></tr>
<tr><td>100 users</td><td class="n">{money(per_user * 100)}</td></tr>
<tr><td>10,000 users</td><td class="n">{money(per_user * 10000)}</td></tr></table>
<p class="small">Formula: {money(t["estimated_cost_usd"], 8)} per run × {RUNS_PER_USER_MONTH} runs × users. This excludes
hosting, storage, support and payment fees, and uses today's rates as written in the code.</p>
<h3>What keeps the cost down (all built and in the code)</h3>
<ul>
<li><b>Saved catalogue first.</b> If a piece type already has 3 or more distinct saved options that fit and are
affordable, no web search runs; three of the six types were skipped this way in this run.</li>
<li><b>One search per piece type and size.</b> Two identical beds share one search, and repeat searches reuse a saved
result for 10 minutes.</li>
<li><b>Shared in-flight requests.</b> Identical searches that arrive at the same time share one request, so they are
never paid twice; a failure is not cached.</li>
<li><b>Bounded checks.</b> At most 12 pages per search are read, two at a time, stopping at 3 ready options. A
marketplace that refuses automated reading is skipped without spending a search.</li>
<li><b>Nothing extra runs by itself.</b> "Search more" is an explicit button.</li>
<li><b>Limits.</b> Estimated cost is reserved before every call against a per-session allowance ($2.00), a daily
allowance ($3.00) and 12 requests per 10 minutes; a limit pauses the search with a plain message.</li>
</ul>
<h3>Did cutting cost hurt quality?</h3>
<p>There is a real risk, though I have not measured it. Relying on a small saved catalogue keeps cost near 10 cents,
but it narrows the choice. All six products in this run came from two retailers, five of them from IKEA pages checked
on October 24, and saved prices can be stale until rechecked. The pilot user's feedback about finding pieces she liked
(Section 7) is consistent with that risk, but it does not prove the cost controls caused it.</p>
<p>An offline benchmark (<code>docs/evidence/offline_search_benchmark.md</code>) measured two concurrent page checks
against one at a time, on a fake network with an equal 80 ms per page: median 0.372 s versus 0.594 s, with identical
decisions. That is a simulation on a fixture, not live speed, and it says nothing about quality beyond that fixture.</p>
"""))

    # 9. Safety risks -------------------------------------------------------------
    pages.append(page(9, "6. Safety", """
<h2>6. Safety</h2>
<p>The risks that matter here are untrusted web content, the app being used to reach private networks, a model
inventing facts or taking the wrong action, and money: both the user's furniture budget and the token budget.</p>
<h3>Attacks</h3>
<ul>
<li><b>Prompt injection from pages, listings and images.</b> Product pages are parsed by deterministic code and are
never sent to a model. Text the model sees in images is evidence, not instruction. Model outputs can only fill typed
schemas, which code validates: a model cannot set a price, choose a product, change the budget or call a tool.</li>
<li><b>Server-side request forgery.</b> Every fetch goes through a SafeFetcher. It allows only https/http on default
ports with no credentials in the URL, resolves DNS and refuses private, loopback, link-local and metadata addresses,
pins the connection to the checked IP, checks every redirect hop before connecting, and caps size, type and
redirects.</li>
<li><b>Untrustworthy sources.</b> Product results are kept only from an allowlist: Amazon, Article, IKEA and Target
for new items, and individual listings on five named resale marketplaces for used ones. The allowlist does not make a
seller trustworthy: an approved marketplace does not verify sellers, condition, stock or delivery, and the app says
so.</li>
<li><b>Key leakage.</b> The key is read from the environment or a <code>.env</code> file (the repository folder, then the
one above it, never higher). It is never shown, logged or sent to the browser.</li>
</ul>
<h3>Malfunction</h3>
<ul>
<li><b>Invented facts.</b> Prices, sizes and stock come only from checked pages; missing facts stay unknown and those
products are not offered. Plan readings are validated and labelled approximate.</li>
<li><b>Wrong actions.</b> The design helper can only propose typed changes; nothing changes until the user ticks
them and presses Apply, and they apply once, to one version. Designs are append-only versions with conflict checks.</li>
<li><b>Loops.</b> One model call per request with at most one validation retry, a bounded number of page checks, and no
automatic second search.</li>
</ul>
<h3>Overspending</h3>
<ul>
<li><b>The user's money.</b> Options over a piece's share or the whole remaining budget are not recommended, and the
server refuses any choice that exceeds what is left, with the exact figures. Earlier over-budget choices are flagged
for replacement, never silently deleted.</li>
<li><b>The token budget.</b> Estimated cost is reserved atomically before each call against session, daily and rate
limits. These are estimates from a rate card, not a guarantee of the provider's invoice; the observed extra web
searches (Section 5) show why the margin matters.</li>
</ul>
""", "dense"))

    # 10. Safety shown working -------------------------------------------------
    pages.append(page(10, "6. Safety: defenses shown working", f"""
<h3>Defenses shown working (offline automated tests)</h3>
<p>The excerpt below is generated program output, not a screenshot. It comes from a run of <b>37 safety and runtime
tests on the submitted code: {esc(E["tests_summary"])}</b>. The tests use mocked models and a fake network, so they
show the defenses in code; they are not a live attack.</p>
<pre class="tests">{tests_excerpt(E["tests"])}</pre>
<div class="two"><div>
<p class="label">Regression: a $14,500 sofa on a $3,000 budget</p>
<p>This test rebuilds a real failure. Before it was fixed, a $14,500 used sofa appeared as a choosable recommendation
on a $3,000 budget. With $2,700 available for items, the test checks four things:</p>
<ul>
<li>the sofa is not recommended;</li>
<li>it is not listed even in the broader within-budget view;</li>
<li>the server refuses to choose it with HTTP 422 and the figures ($14,500.00 against $2,700.00 left);</li>
<li>the design is unchanged.</li>
</ul>
</div><div>
<p class="label">Other defenses in the run</p>
<ul>
<li><b>Prompt injection:</b> an injected "ignore the budget" instruction cannot change budget or policy.</li>
<li><b>SSRF:</b> localhost, private ranges, the cloud metadata address, non-http schemes, credentials in URLs, DNS
answers pointing to private hosts, and redirects to metadata or rebinding hosts are all refused, and the connection is
pinned to the checked IP.</li>
<li><b>Sources:</b> unknown sites and redirects to unknown sites are refused before any network access.</li>
<li><b>Configuration:</b> the parent-folder <code>.env</code> is found while a grandparent is ignored, the status page
never contains the key, and requests go out with gpt-6-luna only.</li>
</ul>
</div></div>
"""))

    # 11. Impact -------------------------------------------------------------
    p = R["pilot"]
    pages.append(page(11, "7. Impact", f"""
<h2>7. Impact</h2>
<p>The evidence is small and I report it at face value: <b>one recorded demo run</b> and <b>one informal external
pilot</b>. I have no measured time savings or purchases.</p>
<div class="two"><div>
<p class="label">Recorded run (measured)</p>
<ul>
<li>6 of 6 requested furniture slots filled with checked products, from 2 retailers. All six slots are filled, but
that is not every item a household needs.</li>
<li>Total {money(2156.97)}, inside the {money(2700)} item allowance, with {money(300, 0)} held for delivery and tax.</li>
<li>About {t["estimated_cost_usd"] * 100:.1f}¢ estimated model and search cost; {u["totals"]["latency_s"]:.2f} s of model request time.</li>
<li>Both downloads were saved through the browser and checked as files, and again after the room-use review (design
version 8, the same six products and total). The spreadsheet is a valid workbook with
{E["downloads"]["xlsx_link_count"]} clickable external store hyperlinks, one per product. The printable page contains the total and
both retailers. The files were checked, not opened in Excel.</li>
<li>2 placement notes remain: two chosen products are larger than their draft outlines. These are approximate notes,
not a hard fit failure, and fit is not verified.</li>
</ul></div><div>
<p class="label">Pilot user (reported, informal)</p>
<p>{esc(p["name"])} ({esc(p["cohort"])}) tried Furniture AI on her own house, using a 2D floor plan with dimensions.
She found furniture with the app. Some recommendations were useful, but she had trouble finding specific pieces she
liked and preferred outside alternatives for some items.</p>
<p class="small">My informal, paraphrased report; no recording, timing, purchase or saving.</p>
</div></div>
<div class="shotpair">{fig(img["05"], "Figure 5. Final checklist: complete, $2,156.97 for 6 items against $2,700, with 2 placement notes.", "Final checklist summary")}
{fig(img["06"], "Figure 6. The sofa row and the two downloads: printable checklist and Excel spreadsheet.", "Checklist downloads")}
<div><p class="label">The six chosen products</p>
<table><tr><th>Piece</th><th class="n">Price</th></tr>
<tr><td>GLADSTAD queen bed frame (IKEA)</td><td class="n">$249.00</td></tr>
<tr><td>VALEVÅG queen mattress (IKEA)</td><td class="n">$399.00</td></tr>
<tr><td>BRIMNES nightstand (IKEA)</td><td class="n">$79.99</td></tr>
<tr><td>LILLBERGET dresser (IKEA)</td><td class="n">$79.99</td></tr>
<tr><td>LACK coffee table (IKEA)</td><td class="n">$49.99</td></tr>
<tr><td>Timber 90" sofa (Article)</td><td class="n">$1,299.00</td></tr>
<tr><th>Total</th><th class="n">$2,156.97</th></tr></table>
<p class="small">IKEA pages checked October 24, Article October 26. Prices and stock may have changed; checkout is
not guaranteed. Nothing was bought, and the app never buys or contacts sellers.</p></div></div>
""", "tight"))

    # 12. Limits + next steps -----------------------------------------------------
    pages.append(page(12, "8. Limits + next steps", """
<h2>8. Limits + next steps</h2>
<h3>What does not work well yet</h3>
<ul>
<li><b>Plan reading needs review.</b> On the 3D marketing render in this run, the reader mislabelled three areas
(living as Dining, a closet as Balcony, a utility space as Bath). A manual review in the app fixed them, but it took
a person to notice. Shapes and scale are approximate, and fit is never verified, especially without printed dimensions.</li>
<li><b>Tiny catalogue, manual adapters.</b> Checked products come from a small saved set built with page-specific
adapters (IKEA, Article, one Amazon item). Prices go stale until rechecked, and taste variety is limited, as the pilot
user found.</li>
<li><b>Secondhand is unreliable.</b> In practice eBay listing pages refuse automated reading (HTTP 403), AptDeco often
shows robot checks, and Chairish is readable but often above budget. The app never bypasses these: it skips a
refusing marketplace and says so, which can leave little or no affordable used supply.</li>
<li><b>Buildings.</b> Plan discovery works for buildings whose sites publish plans or that are in the checked list; it
is not a universal apartment database. The user can always upload a plan image.</li>
<li><b>Local only.</b> No public hosting and no accounts; cost caps are estimates rather than an invoice guarantee.
Evidence of impact is one demo and one informal pilot.</li>
</ul>
<h3>Next month, in priority order</h3>
<ol>
<li><b>Taste and variety.</b> More stores and more styles per piece type, so the first recommendations match what people
actually like.</li>
<li><b>Approved data feeds.</b> Replace scraped pages with retailer or marketplace feeds and APIs where allowed, so prices
and stock are current and secondhand supply does not depend on pages that block automated reading.</li>
<li><b>Better plan review and geometry calibration.</b> Ask the user to confirm room uses before placing furniture, and
let one known wall length calibrate the scale.</li>
<li><b>Independent task timing.</b> A small study with several renters, timing the app against their usual method, with
their consent.</li>
</ol>
<h3>Longer term (not built)</h3>
<p>Reusing a renter's existing furniture inventory between moves, and peer resale when they leave, would extend the
same plan-first list.</p>
<div class="callout">Repository: <b>PRIVATE REPOSITORY</b> · <a href="https://github.com/khtam0417/furniture-ai">https://github.com/khtam0417/furniture-ai</a>
(GitHub user zlisto invited as a collaborator; invitation pending acceptance). It runs locally; the README covers setup, the parent-folder
<code>.env</code> and the offline synthetic examples.</div>
"""))

    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{PRODUCT}: final report ({AUTHOR})</title><style>{REPORT_CSS}</style></head><body>"
            + "".join(pages) + "</body></html>")


# --------------------------------------------------------------------------- slides
SLIDE_CSS = CSS_BASE + """
.reveal{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;font-size:27px;color:var(--ink)}
.reveal-viewport{background:#f5f7f8}
.reveal .slides section{text-align:left;height:100%}
.reveal h1,.reveal h2{font-family:Georgia,"Times New Roman",serif;color:var(--head);text-transform:none;letter-spacing:0;margin:0 0 18px}
.reveal h1{font-size:72px;line-height:1.05}
.reveal h2{font-size:46px;line-height:1.1}
.reveal p,.reveal li{font-size:27px;line-height:1.35}
.reveal ul{margin:0 0 0 1em}
.reveal li{margin-bottom:10px}
.reveal .kick{font-size:20px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--teal);margin:0 0 8px}
.reveal .row{display:flex;gap:28px;align-items:flex-start}
.reveal .grow{flex:1}
.reveal .shot{height:560px;width:auto;border:1px solid var(--rule);border-radius:8px;background:#fff;margin:0;box-shadow:0 2px 10px rgba(0,0,0,.08)}
.reveal .shot.sm{height:520px}
.reveal .cap{font-size:20px;color:var(--muted);margin-top:6px}
.reveal .big{font-family:Georgia,serif;font-size:58px;color:var(--teal-d);line-height:1}
.reveal .stat{border:1.5px solid var(--rule);border-radius:12px;padding:16px 20px;background:#fff;flex:1}
.reveal .stat span{display:block;font-size:22px;color:var(--muted);margin-top:6px;line-height:1.3}
.reveal .repo{border:2px solid var(--teal);border-radius:12px;padding:16px 22px;background:#fff;font-size:26px;margin-top:22px}
.reveal .note{font-size:21px;color:var(--muted)}
.reveal table{font-size:22px;border-collapse:collapse}
.reveal th,.reveal td{border:1px solid var(--rule);padding:6px 12px;text-align:left}
.reveal th{background:#eef2f3}
.reveal pre{box-shadow:none;width:100%;margin:10px 0}
.reveal pre code{font-size:17px;line-height:1.35;background:#1f2a32;color:#e9f1ef;padding:12px 14px;border-radius:8px;max-height:none;white-space:pre-wrap}
.reveal .footer{position:absolute;left:0;bottom:0;font-size:16px;color:var(--muted);width:60%}
.reveal .checks{width:500px;background:#1f2a32;color:#e9f1ef;border-radius:12px;padding:18px 22px;box-sizing:border-box}
.reveal .checks-h{font-size:20px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#7fd6cb;margin:0 0 10px}
.reveal .ck{display:flex;justify-content:space-between;gap:16px;font-size:23px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.15)}
.reveal .ck b{color:#7fd6cb;white-space:nowrap}
.reveal .ck.total{border-bottom:none;font-weight:700}
.reveal .checks .note{color:#b9c6c4;font-size:18px}
.reveal .progress{color:var(--teal)}
.reveal .controls{color:var(--teal)}
"""


def build_slides(E: dict, reveal_js: str, reveal_css: str) -> str:
    img, t = E["img"], E["usage"]["totals"]
    per_user = t["estimated_cost_usd"] * RUNS_PER_USER_MONTH
    foot = f'<div class="footer">{PRODUCT} · {AUTHOR}</div>'  # the right side stays clear for the counter and arrows

    def s(body: str, notes: str) -> str:
        return f"<section>{body}{foot}<aside class=\"notes\">{esc(notes)}</aside></section>"

    slides = [
        s(f"""<p class="kick">Final project · {AUTHOR}</p><h1>{PRODUCT}</h1>
<p style="font-size:32px;max-width:1050px">From the floor plan your building already publishes to one checked, budgeted shopping list.</p>
<div class="repo"><b style="color:var(--teal-d)">PRIVATE REPOSITORY</b> · <a href="{REPO_URL}">{REPO_URL}</a><br>
GitHub user zlisto invited as a collaborator (invitation pending acceptance) · runs locally, not publicly hosted</div>""",
          "Furniture AI reads a published floor plan, lays out draft furniture, fills each piece with a dated product from a checked page within one budget, and exports a checklist and spreadsheet. Runtime model: gpt-6-luna only, via Portkey."),
        s("""<p class="kick">The problem</p><h2>Furnishing a rented apartment you've barely seen</h2>
<ul><li>You have a marketing floor plan, a budget and a style, but no trusted measurements.</li>
<li>Prices and sizes are spread across many store tabs and go stale quickly.</li>
<li>One expensive piece quietly breaks the budget for the rest of the apartment.</li>
<li>It's hard to tell which facts were actually checked, and when.</li></ul>""",
          "No market statistics are claimed. The motivation is the renter's uncertainty and tab sprawl; the app aims for one consistent, budgeted, sourced list that says what is approximate."),
        s("""<p class="kick">What is new</p><h2>A plan-first, budget-honest combination</h2>
<ul><li><b>IKEA Kreativ</b>, <b>Planner 5D</b> and <b>Cona</b> already plan rooms; Cona overlaps closely, with priced products.</li>
<li><b>Furniture AI starts from the building's published plans</b> (19 at The Archive) and covers the whole apartment.</li>
<li>Uncertainty is shown, products carry check dates, and code enforces one budget across stores.</li></ul>
<p class="note">Comparison from official pages (Oct 26, 2026); no hands-on benchmark.</p>""",
          "Sources: IKEA Kreativ help and Ingka newsroom pages; Planner 5D upload-a-floor-plan help article; Cona room planner page. Not first, not proven better: a useful combination for renters."),
        s(f"""<p class="kick">How the agents work</p><h2 style="margin-bottom:6px">Agents and deterministic code</h2>
<div style="width:1120px">{diagram_svg()}</div>""",
          "Four typed PydanticAI agents (plan map, room evidence, preference edit, design helper) plus a web-research call, all gpt-6-luna. No app tools for the agents. Only the plan map and web research ran in the demo."),
        s(f"""<p class="kick">Demo · The Archive 848 | 1x1 A · new only · $3,000</p>
<div class="row"><img class="shot" src="{img["02"]}" alt="Selected published plan"><img class="shot" src="{img["07"]}" alt="Reviewed clean plan drawn by code">
<img class="shot" src="{img["05"]}" alt="Final checklist"><div class="grow"><p>Published plan → AI map (7 areas, approximate scale) → 6 draft pieces → 6 checked products.</p>
<p><b>$2,156.97</b> of a $2,700 item allowance.</p><p class="note">The model mislabelled 3 areas; a review afterwards fixed them in the app (Living, Closet, Laundry). The AI reading is kept, and no geometry was measured.</p></div></div>""",
          "Recorded Oct 26 around 16:06 to 16:12 EDT. Choose for me filled six slots for $1,956.97; I then swapped the mattress from $199 to $399. Two placement notes remain; fit is not verified. Room-use review 16:23 to 16:25: Dining to Living, Balcony to Closet, second Bath to Laundry; the products were kept. Downloads were saved and checked as files at design version 8: 6 store links."),
        s(f"""<p class="kick">Cost to run (measured, estimated from returned usage)</p><h2>About {t["estimated_cost_usd"] * 100:.1f}¢ for the whole run</h2>
<div class="row"><div class="stat"><div class="big">{t["input_tokens"]:,}</div><span>input tokens ({t["cached_input_tokens"]:,} cached) · {t["output_tokens"]:,} output</span></div>
<div class="stat"><div class="big">9</div><span>web searches = {money(t["web_search_fee_usd"])}, about 92% of the cost</span></div>
<div class="stat"><div class="big">{money(per_user * 10000, 0)}</div><span>per month for 10,000 users at an assumed 4 runs each</span></div></div>
<p class="note" style="margin-top:18px">4 calls: 1 plan reading + 3 research calls. Each asked for at most 2 searches; 3 were observed. Saved catalogue and caches skipped 3 of 6 searches.</p>""",
          f"Per user per month {money(per_user, 4)}, 100 users {money(per_user * 100, 2)}. One illustrative run with a pre-seeded catalogue; rate card in usage.py; not an invoice. Excludes hosting and support."),
        s(f"""<p class="kick">Safety</p><h2>Defenses enforced in code, tested</h2>
<div class="row"><div class="grow"><ul><li>Pages are untrusted; models only fill typed schemas.</li><li>SSRF guard: public DNS only, pinned connection, every redirect checked.</li>
<li>Source allowlist (not a seller guarantee).</li><li>Server refuses choices over budget; token caps.</li></ul></div>
<div class="checks"><p class="checks-h">Automated regression checks</p>
<div class="ck"><span>$14,500 sofa / $3,000 budget</span><b>rejected</b></div>
<div class="ck"><span>Injected instruction</span><b>blocked</b></div>
<div class="ck"><span>Metadata redirect</span><b>blocked</b></div>
<div class="ck total"><span>{esc(E["tests_summary"].split()[0])} tests passed</span><b>({esc(E["tests_summary"].split(" in ")[1])})</b></div>
<p class="note" style="margin:10px 0 0">Summary of offline tests (mocked model, fake network), not a live attack. Raw output: report page 10.</p></div></div>""",
          "37 safety and runtime tests passed on the submitted code; the full backend suite in a fresh clone: 479 passed, 1 skipped. The $14,500 sofa regression comes from a real earlier failure: now not recommended, not listed, refused by the server with HTTP 422, design unchanged."),
        s(f"""<p class="kick">Impact</p><h2>Small, real evidence</h2>
<div class="row"><img class="shot sm" src="{img["06"]}" alt="Checklist downloads"><div class="grow">
<ul><li><b>Recorded run:</b> 6 of 6 slots filled from 2 retailers; $2,156.97 within the budget; two checked downloads.</li>
<li><b>Pilot:</b> Shirley Xu (Blue cohort) used her own house's 2D plan and found furniture; she wanted more variety and preferred outside options for some pieces.</li></ul>
<p class="note">An informal report of her feedback (paraphrased); no measured time or savings.</p></div></div>""",
          "Counts: one external pilot reported, one observed demo. The paraphrase is not a quotation."),
        s("""<p class="kick">Limits and next steps</p><h2>What's next</h2>
<div class="row"><div class="grow"><p><b>Limits</b></p><ul><li>Plan readings need review (3D renders).</li><li>Tiny catalogue; prices go stale.</li>
<li>Secondhand often blocked (eBay 403, robot checks); never bypassed.</li></ul></div>
<div class="grow"><p><b>Next month</b></p><ul><li>Taste variety and more stores.</li><li>Approved data feeds.</li><li>Room review and scale calibration.</li><li>Independent task timing.</li></ul></div></div>
<p class="note" style="margin-top:14px">PRIVATE REPOSITORY · <a href="https://github.com/khtam0417/furniture-ai">https://github.com/khtam0417/furniture-ai</a></p>""",
          "Longer term, not built: reuse of a renter's existing inventory between moves and peer resale. Repository private; zlisto invited as a collaborator, invitation pending."),
    ]
    reveal_js = reveal_js.replace("</script", "<\\/script")
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{PRODUCT}: slides ({AUTHOR})</title><style>{reveal_css}</style><style>{SLIDE_CSS}</style></head><body>"
            f"<div class=\"reveal\"><div class=\"slides\">{''.join(slides)}</div></div>"
            f"<script>{reveal_js}</script>"
            "<script>Reveal.initialize({width:1280,height:720,margin:0.05,minScale:0.2,maxScale:2,hash:true,controls:true,"
            "progress:true,slideNumber:'c/t',center:false,transition:'fade',keyboard:true});</script></body></html>")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build report.html and slides.html (self-contained).")
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    ev, vd, out = Path(a.evidence), Path(a.vendor), Path(a.output)
    for n in ("reveal.js", "reveal.css"):
        if not (vd / n).is_file():
            sys.exit(f"missing vendor file: {vd / n}")
    E = load_evidence(ev)
    out.mkdir(parents=True, exist_ok=True)
    report = build_report(E)
    rjs, rcss = (vd / "reveal.js").read_text(encoding="utf-8"), (vd / "reveal.css").read_text(encoding="utf-8")
    slides = build_slides(E, rjs, rcss)
    authored = build_slides(E, "", "")  # the same deck without the vendored runtime, for the content checks
    for name, doc, check in (("report.html", report, report), ("slides.html", slides, authored)):
        bad = [m for m in ("NEED_ROOT_EVIDENCE", "TODO", "http://cdn", "https://cdn", "<link ", "<script src") if m in check]
        if bad:
            sys.exit(f"{name} contains {bad}")
        if REPO_URL not in check or "PRIVATE REPOSITORY" not in check:
            sys.exit(f"{name} must show the repository URL and PRIVATE REPOSITORY")
        (out / name).write_text(doc, encoding="utf-8")
    words = len(re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script|svg)[\s\S]*?</\1>", " ", report)).split())
    print(f"report.html: {PAGES} page sections, about {words} words, {len(report) / 1e6:.2f} MB")
    print(f"slides.html: 9 slides, {len(slides) / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
