"""Take-away checklist: printable HTML + Excel (.xlsx) downloads."""

import html
import io
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from furnishai.design import Design, DesignItem, DesignPrefs
from furnishai.export import ExportData, checklist_html, checklist_xlsx, file_name, plan_svg, safe_link
from furnishai.planmap import room_uses

from test_design_refine import ONE_BED, client, setup, vmap

UNIT = "Apt 9Z-PRIVATE"
IKEA = "https://www.ikea.com/us/en/p/hemnes-nightstand-white-60200456/"


def _designed(tmp_path, **kw):
    c, app, _ = client(tmp_path, [ONE_BED], **kw)
    aid, anchor, s = setup(c, unit=UNIT)
    s = c.post(f"/api/apartments/{aid}/design/auto-products", json={"expected_version": s["design"]["version"]}).json()
    return c, app, aid, s


# ------------------------------------------------------------------ downloads through the API
def test_downloads_match_the_current_checklist_and_change_nothing(tmp_path):
    c, app, aid, s = _designed(tmp_path)
    v = s["design"]["version"]
    cl = c.get(f"/api/apartments/{aid}/design/checklist").json()
    row = cl["checklist"]["rows"][0]
    cl = c.post(f"/api/apartments/{aid}/design/checklist/mark", json={"expected_version": v, "instance_id": row["instances"][0]["id"],
                                                                     "product_id": row["product_id"], "purchased": True}).json()
    marks = app.state.db.all("SELECT * FROM design_marks")
    h = c.get(f"/api/apartments/{aid}/design/export.html?version={v}")
    assert h.status_code == 200 and h.headers["content-type"].startswith("text/html")
    assert re.fullmatch(r'attachment; filename="furniture-checklist-\d{4}-\d{2}-\d{2}\.html"', h.headers["content-disposition"])
    assert "default-src 'none'" in h.headers["content-security-policy"] and h.headers["x-content-type-options"] == "nosniff"
    page = h.text
    c_ = cl["checklist"]
    for r in c_["rows"]:
        assert html.escape(r["name"], quote=True) in page
        dollars = f"${r['line_total_cents'] // 100:,}.{r['line_total_cents'] % 100:02d}"
        assert dollars in page and f"<td data-label='Bought'>{r['purchased_count']} of {r['quantity']}</td>" in page
        if safe_link(r["url"]):
            assert f'href="{r["url"]}"' in page
    total = c_["total_cents"]
    assert f"${total // 100:,}.{total % 100:02d}" in page and "1 of" in page
    for m in c_["missing"]:
        assert m["name"].capitalize() in page
    assert "<script" not in page and " src=" not in page and "<img" not in page and "@import" not in page
    assert "PRIVATE" not in page and "The Example" not in page and "06511" not in page  # no unit, building or ZIP
    assert page.count('class="piece"') == sum(1 for i in s["design"]["data"]["items"] if not i["on_item"] and i["placed"])
    # XLSX: a real package with hyperlinks to the same approved product pages.
    x = c.get(f"/api/apartments/{aid}/design/export.xlsx?version={v}")
    assert x.status_code == 200 and x.headers["content-disposition"].endswith('.xlsx"')
    z = zipfile.ZipFile(io.BytesIO(x.content))
    assert {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml", "xl/worksheets/sheet1.xml"} <= set(z.namelist())
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    rels = z.read("xl/worksheets/_rels/sheet1.xml.rels").decode()
    links = [r["url"] for r in c_["rows"] if safe_link(r["url"])]
    assert links and all(f'Target="{u}" TargetMode="External"' in rels for u in links)
    assert sheet.count("<hyperlink ") == len(links) and "<f>" not in sheet
    assert f"<v>{total / 100:.2f}</v>" in sheet  # the total is a plain value, not a formula
    # Nothing changed: same design version, same bought marks; stale versions and other sessions are refused.
    assert c.get(f"/api/apartments/{aid}/design").json()["design"]["version"] == v
    assert app.state.db.all("SELECT * FROM design_marks") == marks
    assert c.get(f"/api/apartments/{aid}/design/export.html?version={v - 1}").status_code == 409
    assert c.get(f"/api/apartments/{aid}/design/export.xlsx?version={v + 5}").status_code == 409
    other = TestClient(app)
    assert other.get(f"/api/apartments/{aid}/design/export.html?version={v}").status_code == 404
    assert other.get(f"/api/apartments/{aid}/design/export.xlsx?version={v}").status_code == 404


# ------------------------------------------------------------------ layout from the server's own geometry
def _data(items, by_id=None, m=None, rows=None, zones=None):
    m = m if m is not None else vmap(ONE_BED)
    d = Design(plan_source_id="src_x", items=items, prefs=DesignPrefs())
    cl = {"rows": rows or [], "owned": [], "missing": [], "total_cents": sum(r["line_total_cents"] for r in rows or []),
          "status": "complete", "purchased": 0, "units": sum(r["quantity"] for r in rows or [])}
    return ExportData(version=7, design=d, checklist=cl, budget={"item_allowance_cents": None}, plan_map=m, by_id=by_id or {},
                      zones=zones or {}, room_status={k: v.status for k, v in room_uses(m).items()} if m.rooms else {})


def test_layout_uses_actual_positions_sizes_and_rotation_and_lists_unplaced_pieces():
    m = vmap(ONE_BED)
    prod = {"p1": {"id": "p1", "width_in": 21.0, "depth_in": 17.5}}
    items = [DesignItem(id="pc_a", category="nightstand", zone_id="r1", x=0.2, y=0.4, rotation=90, product_id="p1"),
             DesignItem(id="pc_b", category="dresser", zone_id="r2", x=0.5, y=0.45, rotation=0),
             DesignItem(id="pc_c", category="desk", zone_id="r2", x=0.5, y=0.5, placed=False, unplaced_reason="No free wall")]
    x = _data(items, prod, m)
    svg = plan_svg(x)
    a = re.search(r'<g class="piece" data-piece="pc_a" data-x="0.2" data-y="0.4" data-w-in="21.0" data-d-in="17.5" data-rotation="90" '
                  r'data-size="listed" transform="translate\(([\d.]+) ([\d.]+)\) rotate\(90\)"><rect x="([-\d.]+)" y="([-\d.]+)" '
                  r'width="([\d.]+)" height="([\d.]+)"', svg)
    assert a and float(a[1]) == 0.2 * m.image_w and float(a[2]) == 0.4 * m.image_h  # exact, not rounded
    assert float(a[5]) == 21 * m.scale.ppi and float(a[6]) == 17.5 * m.scale.ppi
    assert 'data-piece="pc_b"' in svg and 'data-size="draft"' in svg and 'stroke-dasharray="4 3"' in svg  # draft size shown as such
    assert 'data-piece="pc_c"' not in svg
    page = checklist_html(x)
    assert "Not placed on the plan:</strong> desk (No free wall)" in page and "approximate" in page
    assert "Fit isn’t verified" in page


def test_unmapped_plan_gets_no_drawing_and_no_invented_rectangle():
    m = vmap(ONE_BED).model_copy(update={"status": "fallback", "rooms": [], "walls": [], "fixtures": [], "outline": []})
    x = _data([DesignItem(id="pc_a", category="nightstand", x=0.5, y=0.5, placed=False, unplaced_reason="Room boundaries could not be read")], m=m)
    assert plan_svg(x) is None
    page = checklist_html(x)
    assert "<svg" not in page and "couldn’t be mapped, so no drawing is included" in page
    assert "Room boundaries could not be read" in page
    sheet = zipfile.ZipFile(io.BytesIO(checklist_xlsx(x))).read("xl/worksheets/sheet3.xml").decode()
    assert "couldn&apos;t be mapped" in sheet or "couldn't be mapped" in sheet


# ------------------------------------------------------------------ escaping, links and formulas
EVIL_ROWS = [
    {"product_id": "x1", "name": '<script>alert(1)</script> Nightstand', "category": "nightstand",
     "retailer": '"><img src=x onerror=alert(1)>', "url": "javascript:alert(1)", "unit_price_cents": 1000, "condition": "new",
     "width_in": 20, "depth_in": 16, "checked_at": "2026-10-24T05:00:00+00:00", "stale": False, "quantity": 1,
     "instances": [{"id": "pc_1", "zone_id": "r1", "purchased": False}], "line_total_cents": 1000, "purchased_count": 0},
    {"product_id": "x2", "name": '=HYPERLINK("https://evil.example","click")', "category": "dresser", "retailer": "+cmd|' /C calc'!A0",
     "url": "https://evil.example/dresser", "unit_price_cents": 2050, "condition": "new", "width_in": 30, "depth_in": 18,
     "checked_at": None, "stale": True, "quantity": 2, "instances": [{"id": "pc_2", "zone_id": "r2", "purchased": True},
                                                                       {"id": "pc_3", "zone_id": "r2", "purchased": False}],
     "line_total_cents": 4100, "purchased_count": 1},
    {"product_id": "x3", "name": "Hemnes nightstand", "category": "nightstand", "retailer": "IKEA US", "url": IKEA,
     "unit_price_cents": 9999, "condition": "new", "width_in": 18.125, "depth_in": 15.0, "checked_at": "2026-10-24T05:00:00+00:00",
     "stale": False, "quantity": 1, "instances": [{"id": "pc_4", "zone_id": "r1", "purchased": True}], "line_total_cents": 9999,
     "purchased_count": 1},
]


def test_malicious_product_text_urls_and_formulas_are_inert():
    x = _data([], rows=EVIL_ROWS, zones={"r1": "<b>Bedroom</b>", "r2": "@SUM(A1)"})
    page = checklist_html(x)
    assert "<script>alert" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<img" not in page and "javascript:" not in page and 'href="https://evil.example' not in page
    assert f'href="{IKEA}"' in page and page.count("href=") == 1  # only the approved store link
    assert "<b>Bedroom</b>" not in page and "&lt;b&gt;Bedroom&lt;/b&gt;" in page
    assert "$41.00" in page and "1 of 2" in page and "$150.99" in page  # totals: 10.00 + 41.00 + 99.99
    z = zipfile.ZipFile(io.BytesIO(checklist_xlsx(x)))
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    rels = z.read("xl/worksheets/_rels/sheet1.xml.rels").decode()
    assert "<f>" not in sheet and "<f " not in sheet  # no formula cells at all
    cell = re.search(r'<c r="C3" t="inlineStr" s="1"><is><t xml:space="preserve">(.*?)</t>', sheet)
    assert cell and cell[1] == '=HYPERLINK(&quot;https://evil.example&quot;,&quot;click&quot;)'  # stored as quoted text
    assert 'quotePrefix="1"' in z.read("xl/styles.xml").decode()
    assert "&lt;script&gt;" in sheet and "<script>" not in sheet
    assert rels.count("<Relationship ") == 1 and f'Target="{IKEA}"' in rels and "evil.example" not in rels
    assert "no approved store link" in sheet and "1 of 2" in sheet and "<v>41.00</v>" in sheet and "<v>150.99</v>" in sheet
    assert "may have changed" in sheet
    assert file_name("xlsx", "2026-10-26T12:00:00+00:00") == "furniture-checklist-2026-10-26.xlsx"
    assert file_name("html", '../../"evil') == "furniture-checklist-export.html"


# ------------------------------------------------------------------ download-only ending: parity and small screens
def test_export_pieces_match_the_saved_design_exactly(tmp_path):
    c, app, aid, s = _designed(tmp_path)
    v = s["design"]["version"]
    page = c.get(f"/api/apartments/{aid}/design/export.html?version={v}").text
    m = s["plan_map"]["data"]
    from furnishai.design import footprint_in
    prods = s["products"]  # the chosen products' listed sizes, as the app state shows them
    for it in s["design"]["data"]["items"]:
        g = re.search(rf'data-piece="{it["id"]}" data-x="([^"]+)" data-y="([^"]+)" data-w-in="([^"]+)" data-d-in="([^"]+)" '
                      rf'data-rotation="(\d+)"[^>]*transform="translate\(([^ ]+) ([^)]+)\) rotate\((\d+)\)"', page)
        if it["on_item"] or not it["placed"]:
            assert g is None
            continue
        assert g, it["id"]
        assert float(g[1]) == it["x"] and float(g[2]) == it["y"] and int(g[5]) == it["rotation"] == int(g[8])
        assert float(g[6]) == it["x"] * m["image_w"] and float(g[7]) == it["y"] * m["image_h"]
        w, d, _ = footprint_in(DesignItem.model_validate(it), {k: v_ for k, v_ in prods.items()})
        assert float(g[3]) == w and float(g[4]) == d


def test_doors_and_a_tv_on_its_stand_are_drawn_like_the_app():
    from furnishai.planmap import MapOpening
    m = vmap(ONE_BED)
    m = m.model_copy(update={"openings": [MapOpening(id="o1", kind="door", a=(100.0, 150.0), b=(100.0, 190.0)),
                                          MapOpening(id="o2", kind="window", a=(300.0, 140.0), b=(340.0, 140.0))]})
    items = [DesignItem(id="pc_s", category="tv_stand", zone_id="r2", x=0.5, y=0.45),
             DesignItem(id="pc_t", category="tv", zone_id="r2", x=0.5, y=0.45, on_item="pc_s")]
    svg = plan_svg(_data(items, m=m))
    assert svg.count('class="door"') == 1 and 'class="tv"' in svg.split('data-piece="pc_s"')[1].split("</g>")[0]
    assert 'data-piece="pc_t"' not in svg  # the TV is drawn on its stand, not as its own box


def test_unsure_reading_gets_no_clean_drawing_like_the_app():
    m = vmap(ONE_BED)
    x = _data([DesignItem(id="pc_a", category="nightstand", zone_id="r1", x=0.2, y=0.4)], m=m)
    x.room_status = {r.id: "uncertain" for r in m.rooms}  # no usable room confirmed
    assert plan_svg(x) is None
    page = checklist_html(x)
    assert "<svg" not in page and "too unsure for a clean drawing" in page
    sheet = zipfile.ZipFile(io.BytesIO(checklist_xlsx(x))).read("xl/worksheets/sheet3.xml").decode()
    assert "too unsure for a drawing" in sheet


def test_empty_design_says_so_instead_of_incomplete():
    x = _data([])
    x.checklist["status"] = "empty"
    page = checklist_html(x)
    assert "No pieces in this design yet" in page and "Incomplete" not in page
    sheet = zipfile.ZipFile(io.BytesIO(checklist_xlsx(x))).read("xl/worksheets/sheet3.xml").decode()
    assert "No pieces in this design yet" in sheet


def test_small_screens_get_labelled_cards_with_the_total_kept_aligned():
    page = checklist_html(_data([], rows=EVIL_ROWS))
    assert "hide-sm" not in page  # no column is hidden: Each price stays visible as a labelled line
    css = page.split("<style>")[1].split("</style>")[0]
    small = css.split("@media (max-width:640px)")[1]
    assert "table.buy thead{display:none}" in small and "content:attr(data-label)" in small
    assert "overflow-wrap:anywhere" in css  # long product names wrap instead of widening the page
    for label in ("Qty", "Each", "Total", "Bought"):
        assert page.count(f"data-label='{label}'") == len(EVIL_ROWS)
    foot = page.split("<tfoot>")[1].split("</tfoot>")[0]
    assert "<td colspan='4'>Chosen so far</td><td class='num'>$150.99</td><td class='foot-empty'></td>" in foot

