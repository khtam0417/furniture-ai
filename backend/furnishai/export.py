"""Take-away copies of the final checklist: a self-contained printable HTML page and an Excel (.xlsx) workbook.

Everything comes from the server's own current design version, catalog and plan map (never from the client).
- HTML: no scripts, no external fonts, images or styles (a strict Content-Security-Policy is embedded). The plan is
  drawn from the stored map and each piece's footprint (its chosen product's listed size, else the draft size) at
  its saved position and rotation; an unmapped plan gets NO drawing, never a stand-in rectangle. The source plan
  image, the unit label and the street address are not included.
- XLSX: written with the standard library (zip + XML). Every text value is an explicit inline-string cell with the
  "quote prefix" style, so nothing is ever evaluated as a formula; there are no formula cells at all. Store links are
  real hyperlinks, only for URLs that pass the furniture source rules (approved stores / resale listings).
Exports never change the design or the "bought" marks.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

from .design import Design, footprint_in, piece_name
from .planmap import PlanMap
from .resale import resale_site, retailer_site

EXPORT_METHOD = "checklist-export-v1"


@dataclass
class ExportData:
    version: int
    design: Design
    checklist: dict
    budget: dict
    plan_map: PlanMap | None
    by_id: dict
    zones: dict[str, str]
    room_status: dict[str, str]  # room id -> confirmed | uncertain | conflict
    warnings: dict[str, list[str]] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


def safe_link(url: str | None) -> str | None:
    """A purchase link only when it is an approved furniture source (an established store, or an individual listing on
    an approved resale marketplace); anything else is shown as text-free "no link"."""
    if not isinstance(url, str) or len(url) > 2048:
        return None
    return url if (retailer_site(url) or resale_site(url)) else None


def money(cents: int | None) -> str:
    if cents is None:
        return "price unknown"
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def file_name(kind: str, generated_at: str) -> str:
    """ASCII-only, no user text: furniture-checklist-2026-10-26.html"""
    day = re.sub(r"[^0-9-]", "", generated_at[:10]) or "export"
    return f"furniture-checklist-{day}.{kind}"


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(s) -> str:
    return _CTRL.sub("", "" if s is None else str(s))


def _e(s) -> str:
    return html.escape(clean(s), quote=True)


def _zone(d: ExportData, zid: str | None) -> str:
    return (zid and d.zones.get(zid)) or ""


def _size(row: dict) -> str:
    w, dd = row.get("width_in"), row.get("depth_in")
    return f"{w:g}″ W × {dd:g}″ D" if isinstance(w, (int, float)) and isinstance(dd, (int, float)) else "size not listed"


def _checked(row: dict) -> str:
    c = (row.get("checked_at") or "")[:10]
    via = " from a public copy of the listing page (freshness unknown)" if row.get("read_via") == "public_reader" else ""
    return (f"checked {c}" if c else "check date unknown") + via + (" (may have changed)" if row.get("stale") else "")


def status_text(c: dict) -> str:
    if c["status"] == "empty":
        return "No pieces in this design yet"
    if c["status"] == "complete":
        return "Complete: every piece has a product"
    n = len(c["missing"])
    return f"Incomplete: {n} piece{'' if n == 1 else 's'} without a product"


# ------------------------------------------------------------------ plan drawing (server-owned geometry only)
def plan_status(d: ExportData) -> str:
    m = d.plan_map
    if m is None:
        return "not_read"
    if m.status != "mapped" or not m.rooms:
        return "unmapped"
    # Same rule as the app's clean plan: only when at least one usable room's use is confirmed.
    if not any(r.furnishable and d.room_status.get(r.id, "confirmed") == "confirmed" for r in m.rooms):
        return "unsure"
    return "mapped"


def _pts(poly) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in poly)


def plan_svg(d: ExportData) -> str | None:
    """The clean plan with furniture as SVG (the same elements the app draws), or None when the plan's rooms weren't
    mapped or no usable room is confirmed (nothing is invented). Piece centres, sizes and rotations are the saved
    values, written without rounding."""
    if plan_status(d) != "mapped":
        return None
    m = d.plan_map
    W, H = m.image_w, m.image_h
    line = max(1.0, min(W, H) / 400)
    font = max(7.0, min(W, H) / 38)
    ppi = m.scale.ppi
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Floor plan with furniture">',
           '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           '<line x1="0" y1="0" x2="0" y2="6" stroke="#9aa3b2" stroke-width="1.2"/></pattern></defs>',
           f'<rect x="0" y="0" width="{W}" height="{H}" fill="#eef0f3"/>']
    if len(m.outline) > 2:
        out.append(f'<polygon points="{_pts(m.outline)}" fill="#ffffff" stroke="#3a4352" stroke-width="{line * 2:.2f}"/>')
    for r in m.rooms:
        st = d.room_status.get(r.id, "confirmed")
        fill = "url(#hatch)" if not r.furnishable else ("#ffffff" if st == "confirmed" else "#fbf3df")
        dash = f' stroke-dasharray="{line * 4:.1f} {line * 3:.1f}"' if (st != "confirmed" or r.open_plan) else ""
        out.append(f'<polygon points="{_pts(r.polygon)}" fill="{fill}" stroke="{"#b07d1a" if st != "confirmed" else "#6b7585"}" '
                   f'stroke-width="{line:.2f}"{dash}/>')
    for f in m.fixtures:
        out.append(f'<polygon points="{_pts(f.polygon)}" fill="#dfe3ea" stroke="#55606b" stroke-width="{line:.2f}"/>')
    for a, b in m.walls:
        out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#1e262d" '
                   f'stroke-width="{line * 3.2:.2f}" stroke-linecap="square"/>')
    for o in m.openings:
        color, wd = ("#8cc7c0", 3) if o.kind == "window" else ("#ffffff", 4)
        out.append(f'<line x1="{o.a[0]:.1f}" y1="{o.a[1]:.1f}" x2="{o.b[0]:.1f}" y2="{o.b[1]:.1f}" stroke="{color}" stroke-width="{line * wd:.2f}"/>')
    for o in m.openings:  # doors and openings: the dashed marker the app shows
        if o.kind != "window":
            out.append(f'<line class="door" x1="{o.a[0]:.1f}" y1="{o.a[1]:.1f}" x2="{o.b[0]:.1f}" y2="{o.b[1]:.1f}" stroke="#0f766e" '
                       f'stroke-width="{line:.2f}" stroke-dasharray="{line * 2:.1f} {line * 2:.1f}"/>')
    for r in m.rooms:
        xs, ys = [p[0] for p in r.polygon], [p[1] for p in r.polygon]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        st = d.room_status.get(r.id, "confirmed")
        tag = " (unsure)" if st == "uncertain" else " (check)" if st == "conflict" else ""
        label = _e((r.label or r.kind.replace("_", " ").capitalize()) + tag)
        dims = f'<tspan x="{cx:.1f}" dy="{font * 1.1:.1f}" font-size="{font * 0.8:.1f}">{_e(r.dimension_text)} (printed)</tspan>' if r.dimension_text else ""
        out.append(f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" font-size="{font:.1f}" fill="#3a4352">'
                   f'<tspan x="{cx:.1f}" dy="0">{label}</tspan>{dims}</text>')
    on_top: dict[str, list[str]] = {}
    for it in d.design.items:
        if it.on_item:
            on_top.setdefault(it.on_item, []).append(it.category)
    for it in d.design.items:
        if it.on_item or it.placed is False:
            continue
        w, dep, actual = footprint_in(it, d.by_id)
        a, b = w * ppi, dep * ppi
        cx, cy = it.x * W, it.y * H
        dash = "" if actual else ' stroke-dasharray="4 3"'
        warn = bool(d.warnings.get(it.id))
        extra = ""
        if "mattress" in on_top.get(it.id, []):
            extra += f'<rect x="{-a / 2 + a * 0.06:.1f}" y="{-b / 2 + b * 0.18:.1f}" width="{a * 0.88:.1f}" height="{b * 0.78:.1f}" fill="#fff" stroke="#9aa3b2"/>'
        if "tv" in on_top.get(it.id, []):  # a TV sits on its stand
            extra += f'<rect class="tv" x="{-a * 0.4:.1f}" y="{-b / 2 + b * 0.12:.1f}" width="{a * 0.8:.1f}" height="{max(2.0, b * 0.18):.1f}" fill="#1e262d"/>'
        name = piece_name(it.category, it.size)
        fs = min(font, max(5.0, min(a, b) / 3))
        out.append(
            f'<g class="piece" data-piece="{_e(it.id)}" data-x="{it.x!r}" data-y="{it.y!r}" data-w-in="{w!r}" data-d-in="{dep!r}" '
            f'data-rotation="{it.rotation}" data-size="{"listed" if actual else "draft"}" '
            f'transform="translate({cx!r} {cy!r}) rotate({it.rotation})">'
            f'<rect x="{-a / 2!r}" y="{-b / 2!r}" width="{a!r}" height="{b!r}" fill="{"#d4ece8" if actual else "#f1f8f7"}" '
            f'stroke="{"#9b1c1c" if warn else "#0f766e"}" stroke-width="1.5"{dash}/>{extra}'
            f'<line x1="{-a / 2:.1f}" y1="{-b / 2:.1f}" x2="{a / 2:.1f}" y2="{-b / 2:.1f}" stroke="#25313a" stroke-width="3"/>'
            f'<text x="0" y="0" text-anchor="middle" dominant-baseline="middle" font-size="{fs:.1f}" fill="#25313a" '
            f'transform="rotate({-it.rotation})">{_e(name)}</text></g>')
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------------------------ HTML
_CSS = """
:root{--charcoal:#25313a;--ivory:#f5f7f8;--ink:#1d2433;--muted:#5b6475;--rule:#d7dde2;--teal:#0f766e;--warn:#8a5a00}
*{box-sizing:border-box}body{margin:0;background:var(--ivory);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 20px 48px}
h1,h2{font-family:Georgia,"Times New Roman",serif;color:var(--charcoal);font-weight:normal;margin:0 0 .4em}
h1{font-size:28px;border-bottom:1px solid var(--rule);padding-bottom:.3em}h2{font-size:20px;margin-top:1.6em}
.card{background:#fff;border:1px solid var(--rule);border-radius:6px;padding:14px 16px;margin:12px 0}
.muted{color:var(--muted)}.small{font-size:13px}.warn{color:var(--warn)}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--rule)}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--rule);vertical-align:top;font-size:14px;overflow-wrap:anywhere}
th{background:#e6f4f2;color:var(--charcoal);font-weight:600}td.num,th.num{text-align:right;white-space:nowrap}
tfoot td{font-weight:600}a{color:var(--teal)}
figure{margin:0}figure svg{width:100%;height:auto;background:#fff;border:1px solid var(--rule);border-radius:6px}
.summary{display:flex;flex-wrap:wrap;gap:6px 24px}.summary div{min-width:180px}
.chip{display:inline-block;border:1px solid var(--rule);border-radius:999px;padding:1px 10px;font-size:13px;background:#fff}
@media (max-width:640px){main{padding:16px 10px}h1{font-size:24px}
table.buy,table.buy tbody,table.buy tfoot,table.buy tr,table.buy td{display:block;width:100%}
table.buy thead{display:none}table.buy tr{border-bottom:1px solid var(--rule);padding:6px 0}
table.buy td{border:0;padding:2px 12px}table.buy td.num{text-align:left;white-space:normal}
table.buy td[data-label]::before{content:attr(data-label) ": ";color:var(--muted);font-size:12px;font-weight:normal}
table.buy tfoot tr{display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:0}
table.buy tfoot td{width:auto}table.buy tfoot td::before{content:none}table.buy td.foot-empty{display:none}}
@media print{body{background:#fff}.card{break-inside:avoid}a{color:var(--ink)}a::after{content:" (" attr(href) ")";font-size:10px;color:var(--muted);word-break:break-all}}
"""


def checklist_html(d: ExportData) -> str:
    c, b = d.checklist, d.budget
    day = d.generated_at[:10]
    rows = []
    for r in c["rows"]:
        link = safe_link(r.get("url"))
        name = _e(r.get("name") or piece_name(r["category"]))
        product = (f'<a href="{_e(link)}" target="_blank" rel="noopener noreferrer">{name}</a>' if link
                   else f'{name} <span class="muted small">(no approved store link)</span>')
        rooms = ", ".join(sorted({_zone(d, i["zone_id"]) for i in r["instances"] if _zone(d, i["zone_id"])}))
        rows.append(
            f"<tr><td>{_e(piece_name(r['category']).capitalize())}<div class='muted small'>{_e(rooms)}</div></td>"
            f"<td>{product}<div class='muted small'>{_e(r.get('retailer') or '')} · {_e(r.get('condition') or 'condition unknown')} · "
            f"{_e(_size(r))} · {_e(_checked(r))}</div></td>"
            f"<td class='num' data-label='Qty'>{r['quantity']}</td>"
            f"<td class='num' data-label='Each'>{_e(money(r.get('unit_price_cents')))}</td>"
            f"<td class='num' data-label='Total'>{_e(money(r['line_total_cents']))}</td>"
            f"<td data-label='Bought'>{r['purchased_count']} of {r['quantity']}</td></tr>")
    # A table on wide screens; at 640px and below each row becomes a labelled card (no sideways scrolling).
    to_buy = ("<table class='buy'><thead><tr><th>Piece</th><th>Product</th><th class='num'>Qty</th><th class='num'>Each</th>"
              "<th class='num'>Total</th><th>Bought</th></tr></thead><tbody>" + "".join(rows) +
              f"</tbody><tfoot><tr><td colspan='4'>Chosen so far</td><td class='num'>{_e(money(c['total_cents']))}</td>"
              "<td class='foot-empty'></td></tr></tfoot></table>"
              if rows else "<p class='muted'>No products chosen yet.</p>")
    missing = "".join(f"<li><strong>{_e(m['name'].capitalize())}</strong>{(' (' + _e(_zone(d, m['zone_id'])) + ')') if _zone(d, m['zone_id']) else ''}: "
                      f"{_e(m['reason'])}</li>" for m in c["missing"])
    owned = "".join(f"<li>{_e(o['name'].capitalize())}{(' (' + _e(_zone(d, o['zone_id'])) + ')') if _zone(d, o['zone_id']) else ''}</li>"
                    for o in c["owned"])
    budget = ""
    if b.get("item_allowance_cents") is not None:
        left = b.get("remaining_cents")
        budget = (f"<div><span class='muted small'>Item budget</span><br>{_e(money(b['item_allowance_cents']))} "
                  f"<span class='muted small'>(your {_e(money(b.get('budget_cents')))} minus {_e(money(b.get('reserve_cents')))} held for delivery and tax)</span></div>"
                  f"<div><span class='muted small'>{'Over the item budget by' if b.get('over_allowance') else 'Left'}</span><br>"
                  f"{_e(money(abs(left)) if left is not None else 'unknown')}</div>")
    else:
        budget = "<div><span class='muted small'>Budget</span><br>not set</div>"
    status = status_text(c)
    svg = plan_svg(d)
    ps = plan_status(d)
    not_placed = [i for i in d.design.items if not i.on_item and i.placed is False]
    if svg:
        scale_note = ("Furniture is drawn at the plan’s printed scale." if d.plan_map.scale.kind == "printed"
                      else "The plan has no usable printed sizes, so furniture is drawn relative to it, not to scale.")
        plan = (f"<figure>{svg}</figure><p class='small muted'>Drawn from the reading of your floor plan (approximate). Solid dark "
                "lines are walls read from the plan; dashed outlines are open or unsure areas; hatched areas are kept clear. "
                f"Solid pieces use the chosen product’s listed size; dashed pieces use a typical draft size. {scale_note} "
                "Fit isn’t verified: doors, walkways and delivery access aren’t measured.</p>")
    else:
        plan = ("<p class='muted'>" + {
            "unmapped": "The floor plan’s rooms couldn’t be mapped, so no drawing is included; your pieces are listed above.",
            "unsure": "The plan reading is too unsure for a clean drawing (no usable room’s use is confirmed), so no drawing "
                      "is included. Check the room uses in the app, or read the plan again.",
        }.get(ps, "The floor plan hasn’t been read yet, so no drawing is included.") + "</p>")
    if not_placed:
        plan += ("<p class='small'><strong>Not placed on the plan:</strong> " +
                 ", ".join(_e(piece_name(i.category, i.size)) + (f" ({_e(i.unplaced_reason)})" if i.unplaced_reason else "")
                           for i in not_placed) + "</p>")
    notes = [(piece_name(it.category, it.size), w) for it in d.design.items for w in d.warnings.get(it.id, [])]
    warn_html = ("<ul class='small'>" + "".join(f"<li><strong>{_e(n.capitalize())}:</strong> {_e(w)}</li>" for n, w in notes[:12]) +
                 (f"<li>…and {len(notes) - 12} more</li>" if len(notes) > 12 else "") + "</ul>") if notes else (
                 "<p class='small muted'>No placement notes in the draft arrangement.</p>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Your furniture checklist · {_e(day)}</title><style>{_CSS}</style></head>
<body><main>
<h1>Your furniture checklist</h1>
<p class="muted small">Made with Furniture AI on {_e(day)} (design version {d.version}). <span class="chip">{_e(status)}</span></p>
<div class="card summary">
<div><span class="muted small">Chosen so far</span><br><strong>{_e(money(c['total_cents']))}</strong> for {c['units']} item{'' if c['units'] == 1 else 's'}</div>
{budget}
<div><span class="muted small">Marked as bought</span><br>{c['purchased']} of {c['units']}</div>
</div>
<h2>To buy</h2>{to_buy}
{f"<h2>Still missing</h2><ul>{missing}</ul>" if missing else ""}
{f"<h2>You already own</h2><ul>{owned}</ul>" if owned else ""}
<h2>Your layout</h2>{plan}
<h2>Placement notes</h2>{warn_html}
<p class="small muted">Prices, sizes, condition and availability come from dated store or listing pages and may have changed;
check each page before buying. Opening a link doesn’t buy anything, and this app never pays, orders or contacts sellers.
“Bought” marks are your own notes.</p>
</main></body></html>"""


# ------------------------------------------------------------------ XLSX (standard library only)
def _x(s) -> str:
    return _xml_escape(clean(s), {'"': "&quot;"})


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class _Sheet:
    def __init__(self, name: str, widths: list[int]):
        self.name, self.widths, self.rows, self.links = name, widths, [], []

    def add(self, cells: list, header: bool = False, links: dict[int, str] | None = None):
        self.rows.append((cells, header))
        for col, url in (links or {}).items():
            self.links.append((f"{_col(col)}{len(self.rows)}", url))

    def xml(self) -> str:
        out = []
        for ri, (cells, header) in enumerate(self.rows, start=1):
            cs = []
            for ci, v in enumerate(cells):
                ref = f"{_col(ci)}{ri}"
                if isinstance(v, bool) or v is None:
                    v = "" if v is None else ("Yes" if v else "No")
                if isinstance(v, Money):
                    cs.append(f'<c r="{ref}" s="2"><v>{v.cents / 100:.2f}</v></c>')
                elif isinstance(v, (int, float)):
                    cs.append(f'<c r="{ref}" s="5"><v>{v:g}</v></c>')
                else:
                    style = 3 if header else (4 if any(ref == r for r, _ in self.links) else 1)
                    cs.append(f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{_x(v)}</t></is></c>')
            out.append(f'<row r="{ri}">{"".join(cs)}</row>')
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(self.widths))
        links = ("<hyperlinks>" + "".join(f'<hyperlink ref="{r}" r:id="rId{n + 1}"/>' for n, (r, _) in enumerate(self.links))
                 + "</hyperlinks>") if self.links else ""
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                f'<cols>{cols}</cols><sheetData>{"".join(out)}</sheetData>{links}'
                '<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/></worksheet>')

    def rels(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
                "".join(f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                        f'Target="{_x(u)}" TargetMode="External"/>' for n, (_, u) in enumerate(self.links)) + "</Relationships>")


@dataclass(frozen=True)
class Money:
    cents: int


_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0.00"/></numFmts>'
           '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FF00356B"/><name val="Calibri"/></font>'
           '<font><u/><sz val="11"/><color rgb="FF286DC0"/><name val="Calibri"/></font></fonts>'
           '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
           '<fill><patternFill patternType="solid"><fgColor rgb="FFEEF2F8"/><bgColor indexed="64"/></patternFill></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" quotePrefix="1"><alignment wrapText="1" vertical="top"/></xf>'
           '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"><alignment vertical="top"/></xf>'
           '<xf numFmtId="49" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" quotePrefix="1"/>'
           '<xf numFmtId="49" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" quotePrefix="1"><alignment vertical="top"/></xf>'
           '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top"/></xf></cellXfs>'
           '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def checklist_xlsx(d: ExportData) -> bytes:
    c = d.checklist
    buy = _Sheet("To buy", [16, 18, 42, 12, 12, 10, 10, 13, 6, 12, 12, 10, 34])
    buy.add(["Piece", "Room", "Product", "Store", "Condition", "Width (in)", "Depth (in)", "Checked on", "Qty", "Each",
             "Line total", "Bought", "Store page"], header=True)
    for r in c["rows"]:
        link = safe_link(r.get("url"))
        rooms = ", ".join(sorted({_zone(d, i["zone_id"]) for i in r["instances"] if _zone(d, i["zone_id"])}))
        bought = "Yes" if r["purchased_count"] == r["quantity"] else ("No" if not r["purchased_count"] else f"{r['purchased_count']} of {r['quantity']}")
        checked = (r.get("checked_at") or "")[:10] + (" (may have changed)" if r.get("stale") else "")
        buy.add([piece_name(r["category"]), rooms, r.get("name") or "", r.get("retailer") or "", r.get("condition") or "",
                 r.get("width_in"), r.get("depth_in"), checked or "unknown", r["quantity"],
                 Money(r["unit_price_cents"]) if r.get("unit_price_cents") is not None else "unknown",
                 Money(r["line_total_cents"]), bought, link or "no approved store link"],
                links={12: link} if link else None)
    buy.add(["Chosen so far", "", "", "", "", None, None, "", c["units"], "", Money(c["total_cents"]), f"{c['purchased']} of {c['units']}", ""])
    other = _Sheet("Missing and owned", [14, 26, 18, 70])
    other.add(["Status", "Piece", "Room", "Note"], header=True)
    for m in c["missing"]:
        other.add(["Missing", m["name"], _zone(d, m["zone_id"]), m["reason"]])
    for o in c["owned"]:
        other.add(["You own it", o["name"], _zone(d, o["zone_id"]), "No purchase needed"])
    for it in d.design.items:
        if not it.on_item and it.placed is False:
            other.add(["Not placed", piece_name(it.category, it.size), _zone(d, it.zone_id), it.unplaced_reason or "Waiting for a spot on the plan"])
    summary = _Sheet("Summary", [30, 70])
    summary.add(["Item", "Value"], header=True)
    b = d.budget
    plan_line = {"mapped": "Approximate map read from your floor plan (fit not verified)",
                 "unmapped": "The floor plan's rooms couldn't be mapped; no drawing",
                 "unsure": "Plan reading too unsure for a drawing (no usable room confirmed)",
                 "not_read": "Floor plan not read yet"}[plan_status(d)]
    for k, v in [("Made on", d.generated_at[:10]), ("Design version", str(d.version)),
                 ("Status", status_text(c)),
                 ("Chosen so far", Money(c["total_cents"])),
                 ("Item budget", Money(b["item_allowance_cents"]) if b.get("item_allowance_cents") is not None else "not set"),
                 ("Held for delivery and tax", Money(b.get("reserve_cents") or 0) if b.get("budget_cents") is not None else "not set"),
                 ("Marked as bought", f"{c['purchased']} of {c['units']}"), ("Plan", plan_line),
                 ("Placement notes", str(sum(len(w) for w in d.warnings.values()))),
                 ("Note", "Prices and sizes come from dated pages and may have changed. Opening a link doesn't buy anything.")]:
        summary.add([k, v])
    sheets = [buy, other, summary]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, data: str):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data.encode("utf-8"))
        put("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(sheets)))
            + "</Types>")
        put("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>")
        put("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + "".join(f'<sheet name="{_x(s.name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, s in enumerate(sheets))
            + "</sheets></workbook>")
        put("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>")
        put("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets):
            put(f"xl/worksheets/sheet{i + 1}.xml", s.xml())
            if s.links:
                put(f"xl/worksheets/_rels/sheet{i + 1}.xml.rels", s.rels())
    return buf.getvalue()
