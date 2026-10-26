import type { ApartmentState } from "./types";
import { money } from "./types";

/** Collapsed list of the apartment's spaces. Counts only: no sizes, positions or connections are implied. */
export default function SpacesList({ apt, selected, onSelect }: { apt: ApartmentState; selected: string | null; onSelect: (pid: string) => void }) {
  return (
    <details className="card" style={{ padding: "0.6rem 0.9rem" }}>
      <summary>Spaces in this apartment ({apt.rooms.length} to furnish, {apt.fixed_spaces.length} fixed) — a list, not a floor plan</summary>
      <div className="space-list">
        {apt.rooms.map((r) => (
          <button key={r.project_id} className={`space room-tab ${selected === r.project_id ? "room-tab-on" : ""}`} onClick={() => onSelect(r.project_id)}>
            {r.label}
            <small>{r.mapped ? "room mapped" : r.photos ? `${r.photos} photo${r.photos === 1 ? "" : "s"}, not mapped` : "no photos yet"} · {r.budget_cents != null ? money(r.budget_cents) : "no budget"}</small>
          </button>
        ))}
        {apt.fixed_spaces.map((f) => <div key={f.label} className="space space-fixed">{f.label}<br /><small>fixed · not furnished</small></div>)}
      </div>
      <p className="muted small">The apartment type tells us which rooms exist, not their sizes or how they connect. Each room is mapped from its own photos.</p>
    </details>
  );
}
