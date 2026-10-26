import type { Arrangement, LayoutSet, PlacementT } from "../types";
import { label } from "../types";

const CHARCOAL = "#25313a";
const TEAL = "#0f766e";

const SHORT: Record<string, string> = {
  bed_frame: "Bed", daybed: "Daybed", sofa_bed: "Sofa bed", sofa: "Sofa", desk: "Desk", dresser: "Dresser",
  nightstand: "Night", wardrobe: "Wardrobe", bookcase: "Books", coffee_table: "Table", unmatched: "Item",
};
const SIDE: Record<string, string> = { A: "north", B: "east", C: "south", D: "west" };
const side = (p: PlacementT) => (p.wall && SIDE[p.wall] ? SIDE[p.wall] : p.wall);

function backEdge(p: PlacementT): [number, number, number, number] | null {
  switch (side(p)) {
    case "north": return [p.x, p.y, p.x + p.w, p.y];
    case "south": return [p.x, p.y + p.d, p.x + p.w, p.y + p.d];
    case "west": return [p.x, p.y, p.x, p.y + p.d];
    case "east": return [p.x + p.w, p.y, p.x + p.w, p.y + p.d];
    default: return null;
  }
}

/** Local drawing frame for a placement: u runs along its back (wall) edge, v from the back toward its front.
 *  Returns the SVG transform and the local length (L, along the wall) and depth (T). Free-standing items use the
 *  unrotated frame. The footprint itself (x, y, w, d) is never changed. */
function frame(p: PlacementT): { t: string; L: number; T: number } {
  switch (side(p)) {
    case "south": return { t: `translate(${p.x + p.w} ${p.y + p.d}) rotate(180)`, L: p.w, T: p.d };
    case "east": return { t: `translate(${p.x + p.w} ${p.y}) rotate(90)`, L: p.d, T: p.w };
    case "west": return { t: `translate(${p.x} ${p.y + p.d}) rotate(-90)`, L: p.d, T: p.w };
    default: return { t: `translate(${p.x} ${p.y})`, L: p.w, T: p.d };
  }
}
const angle = (p: PlacementT) => ({ south: 180, east: 90, west: -90 } as Record<string, number>)[side(p) ?? ""] ?? 0;

/** Simplified top-down silhouette inside the product's real footprint (L × T in local inches). Illustrative only:
 *  the shape says what kind of furniture it is, not how the actual product looks. */
function Silhouette({ cat, L, T, unit, on, mattress }: { cat: string; L: number; T: number; unit: number; on: boolean; mattress: boolean }) {
  const line = on ? "#cfe0f5" : CHARCOAL;
  const fill = on ? "#1d4f8a" : "#ffffff";
  const sw = unit * 0.28;
  const common = { stroke: line, strokeWidth: sw, strokeOpacity: on ? 0.9 : 0.55 };
  const r = (x: number, y: number, w: number, h: number, rx = 1.5, f = fill) =>
    w > 0 && h > 0 ? <rect x={x} y={y} width={w} height={h} rx={rx} fill={f} {...common} /> : null;
  const m = Math.min(2, L / 20, T / 20);
  switch (cat) {
    case "bed_frame": {
      const hb = Math.min(T * 0.07, 4);
      if (!mattress) {  // frame only: show the slats, no mattress drawn
        return (
          <g>
            {r(0, 0, L, hb, 0.5, line)}
            {Array.from({ length: Math.max(0, Math.floor((T - hb) / 7)) }, (_, i) => (
              <line key={i} x1={m * 2} x2={L - m * 2} y1={hb + 4 + i * 7} y2={hb + 4 + i * 7} {...common} />
            ))}
          </g>
        );
      }
      const pw = L > 48 ? (L - 3 * m - 4) / 2 : L - 2 * m - 4;
      const ph = Math.min(T * 0.13, 12);
      const duvetY = hb + m + ph + 4;
      return (
        <g>
          {r(0, 0, L, hb, 0.5, line)}
          {r(m, hb + m * 0.5, L - 2 * m, T - hb - m * 1.5, 2.5)}
          {r(m + 2, hb + m + 1, pw, ph, 3)}
          {L > 48 && r(L - m - 2 - pw, hb + m + 1, pw, ph, 3)}
          {r(m + 0.5, duvetY, L - 2 * m - 1, T - duvetY - m, 2.5, on ? "#2a64a6" : "#dfe8f5")}
          <line x1={m + 1} x2={L - m - 1} y1={duvetY + Math.min(8, T * 0.08)} y2={duvetY + Math.min(8, T * 0.08)} {...common} />
        </g>
      );
    }
    case "daybed": {
      const back = Math.min(T * 0.2, 8);
      return <g>{r(0, 0, L, back, 1, line)}{r(m, back + m, L - 2 * m, T - back - 2 * m, 2.5)}{r(m + 2, back + m + 2, Math.min(18, L * 0.25), Math.min(10, T * 0.3), 3)}</g>;
    }
    case "sofa":
    case "sofa_bed": {
      const back = Math.min(T * 0.3, 10);
      const arm = Math.min(8, L * 0.1);
      const n = L - 2 * arm > 70 ? 3 : 2;
      const cw = (L - 2 * arm) / n;
      return (
        <g>
          {r(0, 0, L, back, 2.5)}
          {r(0, 0, arm, T, 2.5)}
          {r(L - arm, 0, arm, T, 2.5)}
          {Array.from({ length: n }, (_, i) => <g key={i}>{r(arm + i * cw + 0.8, back + 0.8, cw - 1.6, T - back - 2, 2.5)}</g>)}
        </g>
      );
    }
    case "desk": {
      const mw = Math.min(L * 0.4, 24);
      return <g>{r(m, m, L - 2 * m, T - 2 * m, 1)}{r((L - mw) / 2, T * 0.12, mw, Math.max(1.5, T * 0.06), 0.5, line)}{r((L - mw * 0.75) / 2, T * 0.45, mw * 0.75, Math.max(2, T * 0.12), 0.8)}</g>;
    }
    case "dresser":
    case "wardrobe": {
      const parts = cat === "wardrobe" ? 2 : Math.max(2, Math.min(4, Math.round(L / 18)));
      return (
        <g>
          {r(m, m, L - 2 * m, T - 2 * m, 1)}
          {Array.from({ length: parts - 1 }, (_, i) => <line key={i} x1={(L * (i + 1)) / parts} x2={(L * (i + 1)) / parts} y1={m} y2={T - m} {...common} />)}
          {Array.from({ length: parts }, (_, i) => <circle key={`k${i}`} cx={(L * (i + 0.5)) / parts} cy={T - m - 1.5} r={Math.min(1.2, T / 12)} fill={line} />)}
        </g>
      );
    }
    case "nightstand":
      return <g>{r(m, m, L - 2 * m, T - 2 * m, 1)}<circle cx={L / 2} cy={T / 2} r={Math.min(L, T) * 0.22} fill={fill} {...common} /></g>;
    case "bookcase":
      return (
        <g>
          {r(m, m, L - 2 * m, T - 2 * m, 0.5)}
          {Array.from({ length: Math.max(1, Math.floor(L / 10)) }, (_, i) => <line key={i} x1={(i + 1) * (L / (Math.floor(L / 10) + 1))} x2={(i + 1) * (L / (Math.floor(L / 10) + 1))} y1={m} y2={T - m} {...common} />)}
        </g>
      );
    case "coffee_table":
      return r(m * 1.5, m * 1.5, L - 3 * m, T - 3 * m, Math.min(L, T) * 0.15);
    case "rug":
      return <rect x={m} y={m} width={L - 2 * m} height={T - 2 * m} fill="none" {...common} strokeDasharray={`${unit} ${unit * 0.6}`} />;
    default:
      return r(m * 1.5, m * 1.5, L - 3 * m, T - 3 * m, 1);
  }
}

/** Draws the FIXED room (from the room version) and one furniture arrangement inside it. Captions live in HTML. */
export default function LayoutCanvas({ layout, arrangement, selected, onSelect, showAccess }: {
  layout: LayoutSet;
  arrangement: Arrangement | null;
  selected: string | null;
  onSelect: (ref: string | null) => void;
  showAccess: boolean;
}) {
  const W = layout.envelope_width_in;
  const D = layout.envelope_depth_in;
  const unit = Math.max(W, D) / 100; // ~1% of the room: keeps labels proportional at any size
  const m = unit * 7;
  const estimated = layout.basis !== "scaled_room_lower_bound";
  const placements = arrangement?.placements ?? [];
  const assoc = arrangement?.associated ?? [];
  // A mattress or chair is "associated" with its bed/desk: drawn as part of it, never as its own footprint.
  const mattressOn = new Set(assoc.filter((a) => a.on_ref && placements.some((p) => p.ref === a.on_ref && p.category === "bed_frame")).map((a) => a.on_ref!));
  const chairOn = new Set(assoc.filter((a) => a.on_ref && placements.some((p) => p.ref === a.on_ref && p.category === "desk")).map((a) => a.on_ref!));
  const sel = (ref: string) => selected === ref || assoc.some((a) => a.ref === selected && a.on_ref === ref);
  const wallFont = unit * 3.2;

  return (
    <svg viewBox={`${-m} ${-m} ${W + 2 * m} ${D + 2 * m}`} role="group"
      aria-label={`${layout.envelope_label}${arrangement ? `: ${arrangement.title}` : ""}`}>
      <defs>
        <pattern id="g12" width="12" height="12" patternUnits="userSpaceOnUse">
          <path d="M12 0H0V12" fill="none" stroke={CHARCOAL} strokeOpacity="0.07" strokeWidth={unit * 0.15} />
        </pattern>
        <pattern id="hatch" width={unit * 2} height={unit * 2} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2={unit * 2} stroke="#7c8690" strokeWidth={unit * 0.45} />
        </pattern>
      </defs>
      <rect x="0" y="0" width={W} height={D} fill="#fff" />
      <rect x="0" y="0" width={W} height={D} fill="url(#g12)" />
      <rect x="0" y="0" width={W} height={D} fill="none" stroke={CHARCOAL} strokeWidth={unit * (estimated ? 0.9 : 1.6)}
        strokeDasharray={estimated ? `${unit * 3} ${unit * 1.6}` : undefined} />

      <g fontFamily="system-ui, sans-serif" fontSize={wallFont} fill="#55606b" fontWeight="700">
        <text x={W / 2} y={-unit * 2} textAnchor="middle">A</text>
        <text x={W + unit * 3.5} y={D / 2} textAnchor="middle">B</text>
        <text x={W / 2} y={D + unit * 4.8} textAnchor="middle">C</text>
        <text x={-unit * 3.5} y={D / 2} textAnchor="middle">D</text>
      </g>

      {layout.fixed_zones.map((z, i) => {
        const keepClear = z.label.includes("keep-clear") || z.label.includes("aisle");
        return (
          <g key={i}>
            <title>{`${z.label}: ${z.assumption}`}</title>
            <rect x={z.x} y={z.y} width={z.w} height={z.d} fill={keepClear ? "#f4f1e8" : "url(#hatch)"} stroke="#7c8690"
              strokeWidth={unit * 0.3} strokeDasharray={keepClear ? `${unit * 1.2} ${unit}` : undefined} />
            <text x={z.x + unit} y={z.y + unit * 3} fontFamily="system-ui, sans-serif" fontSize={unit * 2.4} fill="#5b5446">{z.label}</text>
          </g>
        );
      })}

      {(layout.wall_markers ?? []).map((mk, i) => {
        const horizontal = mk.y1 === mk.y2;
        const lx = (mk.x1 + mk.x2) / 2 + (horizontal ? 0 : mk.x1 === 0 ? unit * 2.2 : -unit * 2.2);
        const ly = (mk.y1 + mk.y2) / 2 + (horizontal ? (mk.y1 === 0 ? unit * 3.6 : -unit * 1.6) : 0);
        return (
          <g key={`m${i}`}>
            <title>{`${mk.label} on wall ${mk.wall}: ${mk.caveat}`}</title>
            <line x1={mk.x1} y1={mk.y1} x2={mk.x2} y2={mk.y2} stroke="#fff" strokeWidth={unit * 2.2} />
            <line x1={mk.x1} y1={mk.y1} x2={mk.x2} y2={mk.y2} stroke={TEAL} strokeWidth={unit * 0.6} />
            <line x1={mk.x1} y1={mk.y1} x2={mk.x2} y2={mk.y2} stroke={TEAL} strokeWidth={unit * 1.8} strokeOpacity="0.25" />
            <text x={lx} y={ly} textAnchor="middle" fontFamily="system-ui, sans-serif" fontSize={unit * 2.3} fill={TEAL}
              transform={horizontal ? undefined : `rotate(-90 ${lx} ${ly})`}>{mk.label}</text>
          </g>
        );
      })}

      {showAccess && placements.flatMap((p) => p.clearances.map((c, i) => (
        <rect key={`${p.ref}-c${i}`} x={c[0]} y={c[1]} width={c[2]} height={c[3]} fill={TEAL} fillOpacity="0.05" stroke={TEAL}
          strokeDasharray={`${unit * 1.2} ${unit}`} strokeWidth={unit * 0.25} />
      )))}

      {placements.map((p) => {
        const on = sel(p.ref);
        const edge = backEdge(p);
        const f = frame(p);
        const fontSize = Math.max(unit * 2.2, Math.min(unit * 3.6, Math.min(p.w, p.d) / 3.4));
        const name = SHORT[p.category ?? ""] ?? label(p.category ?? "item");
        const chair = p.category === "desk" && chairOn.has(p.ref) ? p.clearances[0] : null;
        const seat = chair ? Math.min(20, Math.min(chair[2], chair[3]) * 0.6) : 0;
        return (
          <g key={p.ref} role="button" tabIndex={0} aria-pressed={on}
            aria-label={`${p.label}, ${Math.round(p.w)} by ${Math.round(p.d)} inches${on ? ", selected" : ""}`}
            style={{ cursor: "pointer" }} onClick={() => onSelect(selected === p.ref ? null : p.ref)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(p.ref); } }}>
            <title>{`${p.label} (${Math.round(p.w)}″ × ${Math.round(p.d)}″)`}</title>
            {p.open_extent && on && (
              <rect x={p.open_extent[0]} y={p.open_extent[1]} width={p.open_extent[2]} height={p.open_extent[3]}
                fill="none" stroke={CHARCOAL} strokeDasharray={`${unit * 0.6} ${unit}`} strokeWidth={unit * 0.35} />
            )}
            {on && <rect x={p.x - unit} y={p.y - unit} width={p.w + 2 * unit} height={p.d + 2 * unit} rx={unit} fill="none"
              stroke={TEAL} strokeOpacity="0.45" strokeWidth={unit * 1.1} />}
            <rect x={p.x} y={p.y} width={p.w} height={p.d} rx={unit * 0.4}
              fill={on ? CHARCOAL : p.kind === "existing" ? "#eef1f3" : "#e6f4f2"} stroke={CHARCOAL} strokeWidth={unit * (on ? 0.7 : 0.35)}
              strokeDasharray={p.kind === "existing" ? `${unit * 1.4} ${unit * 0.8}` : undefined} />
            <g transform={f.t} pointerEvents="none">
              <Silhouette cat={p.category ?? ""} L={f.L} T={f.T} unit={unit} on={on} mattress={mattressOn.has(p.ref)} />
            </g>
            {edge && <line x1={edge[0]} y1={edge[1]} x2={edge[2]} y2={edge[3]} stroke={on ? "#9fc0e8" : CHARCOAL} strokeWidth={unit * 0.9} />}
            {chair && (
              <g transform={`translate(${chair[0] + chair[2] / 2} ${chair[1] + chair[3] / 2}) rotate(${angle(p)})`} pointerEvents="none">
                <rect x={-seat / 2} y={-seat / 2} width={seat} height={seat} rx={seat * 0.2} fill="#fff" stroke={CHARCOAL} strokeWidth={unit * 0.3} />
                <rect x={-seat / 2} y={seat / 2 - seat * 0.18} width={seat} height={seat * 0.18} rx={seat * 0.08} fill={CHARCOAL} fillOpacity="0.6" />
              </g>
            )}
            <text x={p.x + p.w / 2} y={p.y + p.d / 2 + fontSize / 3} textAnchor="middle" fontFamily="Georgia, serif" fontSize={fontSize}
              fill={on ? "#fff" : CHARCOAL} stroke={on ? CHARCOAL : "#fff"} strokeWidth={unit * 0.6} paintOrder="stroke" pointerEvents="none">{name}</text>
          </g>
        );
      })}
    </svg>
  );
}
