import type { InferredGeometry } from "../types";

const CHARCOAL = "#25313a";
const TEAL = "#0f766e";

/** What the photos showed when the room's SIZE could not be estimated: walls A–D and the features seen on them,
 *  NOT TO SCALE. Drawn as an evenly sized square only when the analysis reported a rectangular room; it never
 *  shows furniture, measurements or proportions. Feature positions are approximate fractions along each wall. */
export default function ObservedWalls({ geo }: { geo: InferredGeometry }) {
  const S = 100;
  const rect = geo.shape === "rectangular";
  const seen = new Set(geo.walls_seen);
  // Wall segments clockwise from above: A top, B right, C bottom, D left (left-to-right as seen from inside).
  const seg: Record<string, [number, number, number, number]> = {
    A: [0, 0, S, 0], B: [S, 0, S, S], C: [S, S, 0, S], D: [0, S, 0, 0],
  };
  const at = (w: string, f: number): [number, number] => {
    const [x1, y1, x2, y2] = seg[w];
    return [x1 + (x2 - x1) * f, y1 + (y2 - y1) * f];
  };
  return (
    <div className="observed">
      <p className="eyebrow">What your photos showed · not to scale</p>
      {rect ? (
        <svg viewBox="-14 -14 128 128" role="img" aria-label="Observed walls and features, not to scale; no furniture placed">
          {(["A", "B", "C", "D"] as const).map((w) => {
            const [x1, y1, x2, y2] = seg[w];
            return <line key={w} x1={x1} y1={y1} x2={x2} y2={y2} stroke={CHARCOAL} strokeWidth={seen.has(w) ? 1.6 : 0.6}
              strokeDasharray={seen.has(w) ? undefined : "3 2"} />;
          })}
          {geo.features.map((f, i) => {
            const [ax, ay] = at(f.wall, f.start_frac);
            const [bx, by] = at(f.wall, f.end_frac);
            return (
              <g key={i}>
                <title>{`${f.kind} on wall ${f.wall} (approximate position)`}</title>
                <line x1={ax} y1={ay} x2={bx} y2={by} stroke={f.kind === "window" ? TEAL : "#8a5a00"} strokeWidth="4" strokeOpacity="0.6" />
              </g>
            );
          })}
          <g fontFamily="system-ui, sans-serif" fontSize="6" fontWeight="700" fill="#55606b" textAnchor="middle">
            <text x={S / 2} y={-5}>A</text><text x={S + 8} y={S / 2}>B</text><text x={S / 2} y={S + 10}>C</text><text x={-8} y={S / 2}>D</text>
          </g>
          <text x={S / 2} y={S / 2} textAnchor="middle" fontFamily="Georgia, serif" fontSize="7" fill="#6b7280">size unknown</text>
        </svg>
      ) : (
        <p className="small">The room’s shape wasn’t clear enough to sketch, so only the observations are listed.</p>
      )}
      <ul className="small">
        {(["A", "B", "C", "D"] as const).map((w) => (
          <li key={w}><strong>Wall {w}</strong>{seen.has(w) ? "" : " (not seen)"}: {geo.wall_descriptions[w] ?? "no description"}
            {geo.features.filter((f) => f.wall === w).length > 0 && <> · {geo.features.filter((f) => f.wall === w).map((f) => f.kind.replace("_", " ")).join(", ")}</>}
          </li>
        ))}
      </ul>
      <p className="small muted">
        Not to scale: the photos didn’t give a size we can rely on ({geo.reason}) Walls aren’t drawn to their real lengths or
        proportions, feature positions are approximate, and no furniture is placed or fit-checked from this view.
        Pick a printed size on your floor plan, or tell us the size, to get a drawing you can furnish.
      </p>
    </div>
  );
}
