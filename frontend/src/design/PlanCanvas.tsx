import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { cap, footprint, pieceName, type DesignItem, type MapRoom, type PlanMap, type Pt, type ProductView, type RoomUse } from "../designTypes";

const FIXED_KINDS = new Set(["kitchen", "bath", "closet", "balcony", "laundry", "hall"]);

function centroid(poly: Pt[]): Pt {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    const f = x1 * y2 - x2 * y1;
    a += f; cx += (x1 + x2) * f; cy += (y1 + y2) * f;
  }
  if (Math.abs(a) < 1e-9) return [poly.reduce((s, p) => s + p[0], 0) / poly.length, poly.reduce((s, p) => s + p[1], 0) / poly.length];
  return [cx / (3 * a), cy / (3 * a)];
}

const pts = (poly: Pt[]) => poly.map(([x, y]) => `${x},${y}`).join(" ");

function inPoly([x, y]: Pt, poly: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Each room edge is either an "edge" (approximate room boundary) or "open" (a split between zones of one open space,
 *  never drawn like a wall). */
function roomEdges(r: MapRoom, rooms: MapRoom[]): { a: Pt; b: Pt; open: boolean }[] {
  const out = [];
  for (let i = 0; i < r.polygon.length; i++) {
    const a = r.polygon[i], b = r.polygon[(i + 1) % r.polygon.length];
    const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    const nx = -(b[1] - a[1]) / L, ny = (b[0] - a[0]) / L;
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    const p1: Pt = [mx + nx * 3, my + ny * 3], p2: Pt = [mx - nx * 3, my - ny * 3];
    const outward = inPoly(p1, r.polygon) ? p2 : p1;
    const other = rooms.find((o) => o.id !== r.id && inPoly(outward, o.polygon));
    out.push({ a, b, open: !!other && (!!r.open_plan || !!other.open_plan) });
  }
  return out;
}

/** Two views of the selected plan, both with the same movable pieces:
 *  - Clean plan (default when the reading has at least one confirmed usable room): drawn in code from the AI map, no
 *    source image, so no watermark, floor texture or marketing furniture. Walls read as walls are solid; the outline
 *    and room edges are thin approximate lines; open splits and unsure rooms are dashed and labelled; kitchen, bath and
 *    closets are hatched; doors and windows are marked. It is a derived drawing, never a survey.
 *  - Original plan: the source image exactly as published (always one click away). When the rooms couldn't be read,
 *    only the original is shown and nothing is drawn on it (no tidy rectangle). */
export default function PlanCanvas({
  imageUrl, imageW, imageH, map, items = [], products = {}, warnings = {}, selected = null, onSelect, onMove, onNudge,
  onRotate, editable = false, overlay, caption, compact = false, roomUses,
}: {
  compact?: boolean;  // thumbnail: no caption or toggles
  roomUses?: Record<string, RoomUse>;
  imageUrl: string;
  imageW: number;
  imageH: number;
  map: PlanMap | null;
  items?: DesignItem[];
  products?: Record<string, ProductView>;
  warnings?: Record<string, string[]>;
  selected?: string | null;
  onSelect?: (id: string | null) => void;
  onMove?: (id: string, x: number, y: number) => void;
  onNudge?: (id: string, dx: number, dy: number) => void;
  onRotate?: (id: string) => void;
  editable?: boolean;
  overlay?: string | null;  // e.g. "Reading rooms and walls…": shown over the image, never a blank canvas
  caption?: React.ReactNode;
}) {
  const W = map?.image_w ?? imageW;
  const H = map?.image_h ?? imageH;
  const mapped = map?.status === "mapped";
  // The clean plan is the default only when the reading is usable (a confirmed room you can furnish).
  const cleanOK = !!map && mapped && map.rooms.some((r) => r.furnishable && (!roomUses || roomUses[r.id]?.status === "confirmed"));
  const [showOriginal, setShowOriginal] = useState(!cleanOK);
  useEffect(() => { setShowOriginal(!cleanOK); }, [cleanOK, map?.source_id]);
  const line = Math.max(1, Math.min(W, H) / 400);
  const [showFurniture, setShowFurniture] = useState(true);
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number; x: number; y: number; moved: boolean } | null>(null);
  const ppi = map?.scale.ppi ?? 1;
  const font = Math.max(7, Math.min(W, H) / 38);

  const toSvg = (e: PointerEvent): [number, number] => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const m = svg.getScreenCTM();
    if (!m) return [0, 0];
    const p = pt.matrixTransform(m.inverse());
    return [p.x, p.y];
  };

  const down = (e: PointerEvent<SVGGElement>, it: DesignItem) => {
    onSelect?.(it.id);
    if (!editable || it.on_item || e.button > 0) return;
    const [px, py] = toSvg(e);
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    setDrag({ id: it.id, dx: px - it.x * W, dy: py - it.y * H, x: it.x * W, y: it.y * H, moved: false });
  };
  const move = (e: PointerEvent<SVGSVGElement>) => {
    if (!drag) return;
    const [px, py] = toSvg(e);
    const x = Math.min(W, Math.max(0, px - drag.dx));
    const y = Math.min(H, Math.max(0, py - drag.dy));
    setDrag({ ...drag, x, y, moved: drag.moved || Math.hypot(x - drag.x, y - drag.y) > 1 });
  };
  const up = () => {
    if (drag && drag.moved && editable) onMove?.(drag.id, drag.x / W, drag.y / H);
    setDrag(null);
  };
  const cancel = () => setDrag(null);  // pointercancel (e.g. a system gesture): nothing is saved
  const key = (e: KeyboardEvent<SVGGElement>, it: DesignItem) => {
    if (!editable || it.on_item) return;
    const step = e.shiftKey ? 12 : 3;  // inches at the map's scale
    const map_: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (map_[e.key]) { e.preventDefault(); onNudge?.(it.id, map_[e.key][0], map_[e.key][1]); }
    else if (e.key === "r" || e.key === "R") { e.preventDefault(); onRotate?.(it.id); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect?.(it.id); }
  };

  const onTop = new Map<string, string[]>();
  items.filter((i) => i.on_item).forEach((i) => onTop.set(i.on_item!, [...(onTop.get(i.on_item!) ?? []), i.category]));
  return (
    <figure className={`plan-canvas ${compact ? "plan-canvas-compact" : ""}`}>
      <div className="plan-canvas-frame">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Your floor plan with furniture"
          onPointerMove={move} onPointerUp={up} onPointerCancel={cancel}
          onPointerDown={(e) => { if (e.target === svgRef.current) onSelect?.(null); }}>
          <defs>
            <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" style={{ stroke: "var(--plan-hatch)" }} strokeWidth="1.2" />
            </pattern>
          </defs>
          {(showOriginal || !mapped) && <image href={imageUrl} x={0} y={0} width={W} height={H} preserveAspectRatio="none" />}
          {mapped && map && !showOriginal && (
            <g aria-hidden className="clean-plan">
              <rect x={0} y={0} width={W} height={H} style={{ fill: "var(--plan-bg)" }} />
              {map.outline.length > 2 && <polygon points={pts(map.outline)} style={{ fill: "var(--plan-room)", stroke: "var(--plan-outline)" }} strokeWidth={line * 2} />}
              {map.rooms.map((r) => {
                const u = roomUses?.[r.id]?.status ?? "confirmed";
                const fill = !r.furnishable ? (FIXED_KINDS.has(r.kind) ? "url(#hatch)" : "var(--plan-other)") : u === "confirmed" ? "var(--plan-room)" : "var(--plan-unsure)";
                return <polygon key={r.id} points={pts(r.polygon)} style={{ fill }} stroke="none" />;
              })}
              {map.rooms.flatMap((r) => {
                const u = roomUses?.[r.id]?.status ?? "confirmed";
                return roomEdges(r, map.rooms).map((e, i) => (
                  <line key={`${r.id}-${i}`} x1={e.a[0]} y1={e.a[1]} x2={e.b[0]} y2={e.b[1]}
                    style={{ stroke: u !== "confirmed" ? "var(--plan-edge-unsure)" : e.open ? "var(--plan-edge-open)" : "var(--plan-edge)" }} strokeWidth={line}
                    strokeDasharray={u !== "confirmed" || e.open ? `${line * 4} ${line * 3}` : undefined} />
                ));
              })}
              {map.fixtures.map((f) => <polygon key={f.id} points={pts(f.polygon)} style={{ fill: "var(--plan-fixture)", stroke: "var(--plan-fixture-line)" }} strokeWidth={line} />)}
              {map.walls.map(([a, b], i) => <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} style={{ stroke: "var(--plan-wall)" }} strokeWidth={line * 3.2} strokeLinecap="square" />)}
              {map.openings.map((o) => (
                <line key={o.id} x1={o.a[0]} y1={o.a[1]} x2={o.b[0]} y2={o.b[1]} style={{ stroke: o.kind === "window" ? "var(--plan-window)" : "var(--plan-room)" }}
                  strokeWidth={line * (o.kind === "window" ? 3 : 4)} />
              ))}
              {map.openings.filter((o) => o.kind !== "window").map((o) => (
                <line key={`${o.id}-m`} x1={o.a[0]} y1={o.a[1]} x2={o.b[0]} y2={o.b[1]} style={{ stroke: "var(--plan-door)" }} strokeWidth={line} strokeDasharray={`${line * 2} ${line * 2}`} />
              ))}
              {map.rooms.map((r) => {
                const [cx, cy] = centroid(r.polygon);
                const u = roomUses?.[r.id]?.status ?? "confirmed";
                return (
                  <text key={r.id} x={cx} y={cy} textAnchor="middle" fontSize={font} className="pc-label">
                    <tspan x={cx} dy={0}>{r.label || cap(r.kind)}{u === "uncertain" ? " (unsure)" : u === "conflict" ? " (check)" : ""}</tspan>
                    {r.dimension_text && <tspan x={cx} dy={font * 1.1} fontSize={font * 0.8}>{r.dimension_text} (printed)</tspan>}
                  </text>
                );
              })}
            </g>
          )}
          {(showFurniture || !showOriginal) && items.filter((i) => !i.on_item && i.placed !== false).map((it) => {
            const live = drag?.id === it.id ? drag : null;
            const cx = live ? live.x : it.x * W;
            const cy = live ? live.y : it.y * H;
            const f = footprint(it, products);
            const a = f.w * ppi, b = f.d * ppi;
            const warn = (warnings[it.id] ?? []).length > 0;
            const on = selected === it.id;
            const mattress = (onTop.get(it.id) ?? []).includes("mattress");
            const tv = (onTop.get(it.id) ?? []).includes("tv");
            return (
              <g key={it.id} transform={`translate(${cx} ${cy}) rotate(${it.rotation})`} className={`pc-piece ${on ? "pc-on" : ""} ${editable ? "pc-drag" : ""}`}
                tabIndex={compact ? -1 : 0} role={compact ? undefined : "button"} aria-pressed={compact ? undefined : on}
                aria-label={`${pieceName(it)}${f.actual ? "" : " (draft size)"}${warn ? ", has a warning" : ""}. Arrow keys move it, R rotates.`}
                onPointerDown={(e) => down(e, it)} onKeyDown={(e) => key(e, it)} style={{ cursor: editable ? "grab" : "pointer" }}>
                <rect x={-a / 2} y={-b / 2} width={a} height={b} rx={Math.min(a, b) * 0.06}
                  style={{ fill: f.actual ? "var(--plan-piece)" : "var(--plan-piece-draft)", stroke: warn ? "var(--plan-piece-warn)" : on ? "var(--plan-piece-on)" : "var(--plan-piece-line)" }}
                  strokeWidth={on ? 2.5 : 1.5} strokeDasharray={f.actual ? undefined : "4 3"} />
                {mattress && <rect x={-a / 2 + a * 0.06} y={-b / 2 + b * 0.18} width={a * 0.88} height={b * 0.78} style={{ fill: "var(--plan-mattress)", stroke: "var(--plan-hatch)" }} strokeWidth={1} />}
                {tv && <rect x={-a * 0.4} y={-b / 2 + b * 0.12} width={a * 0.8} height={Math.max(2, b * 0.18)} style={{ fill: "var(--plan-wall)" }} />}
                <line x1={-a / 2} y1={-b / 2} x2={a / 2} y2={-b / 2} style={{ stroke: "var(--plan-piece-on)" }} strokeWidth={3} />
                <text x={0} y={0} textAnchor="middle" dominantBaseline="middle" fontSize={Math.min(font, Math.max(5, Math.min(a, b) / 3))}
                  transform={`rotate(${-it.rotation})`} className="pc-piece-label">{pieceName(it)}</text>
              </g>
            );
          })}
        </svg>
        {!compact && map && !mapped && <div className="plan-canvas-tag">We couldn’t map this plan’s rooms, so nothing is drawn on it. This is the original as published.</div>}
        {!compact && mapped && showOriginal && !cleanOK && <div className="plan-canvas-tag">The reading is too unsure for a clean plan: check room uses, or re-read the plan.</div>}
        {overlay && <div className="plan-canvas-overlay" role="status">{overlay}</div>}
      </div>
      {!compact && <figcaption className="small muted row wrap" style={{ justifyContent: "space-between" }}>
        <span>
          {mapped && !showOriginal && <>Clean plan drawn from the AI reading (approximate): solid dark lines are walls read from the plan, thin lines are approximate room edges, dashed lines are open or unsure boundaries, hatched areas are kept clear. </>}
          {caption}
        </span>
        {mapped && (
          <span className="row wrap small" style={{ gap: "0.8rem" }}>
            <label className="row" style={{ gap: "0.3rem" }}>
              <input type="checkbox" checked={showOriginal} onChange={(e) => setShowOriginal(e.target.checked)} /> Show original floor plan
            </label>
            {showOriginal && items.length > 0 && (
              <label className="row" style={{ gap: "0.3rem" }}>
                <input type="checkbox" checked={showFurniture} onChange={(e) => setShowFurniture(e.target.checked)} /> Show furniture
              </label>
            )}
          </span>
        )}
      </figcaption>}
    </figure>
  );
}
