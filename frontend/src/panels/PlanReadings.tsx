import { api } from "../api";
import type { Act } from "../Workspace";
import { sourceLabel, type PlanSuggestion, type ProjectState } from "../types";

const ROOM_WORDS: Record<string, RegExp> = {
  bedroom: /\b(bed\s*room|bedroom|bdrm|br|master|primary)\b/i,
  studio: /\b(studio|living|main|great\s*room)\b/i,
  living_room: /\b(living|lounge|family|great\s*room|lr)\b/i,
};
const ft = (inch: number) => `${Math.floor(inch / 12)}′${Math.round(inch % 12)}″`;

/** The floor plan(s) in this room and their printed room sizes, as cards. Picking one draws the room at that size as
 *  an ESTIMATE (no measuring, no exact-unit certification; fit stays unverified). A single unambiguous room-type
 *  match is suggested, never chosen; two bedrooms are never picked between. A plan with no readable sizes is shown
 *  as a reference only, never as a fake room. */
export default function PlanReadings({ state, act, onState, setMessage, busy, roomName, onAddPhotos }: {
  state: ProjectState;
  act: Act;
  onState: (s: ProjectState) => void;
  setMessage: (m: string | null) => void;
  busy: boolean;
  roomName: string;
  onAddPhotos?: () => void;
}) {
  const p = state.project;
  const row = state.room;
  const room = row?.data.room;
  const est = room?.plan_estimate ?? null;
  const suggestions: PlanSuggestion[] = row?.data.plan_dimension_suggestions ?? [];
  const plans = state.sources.filter((s) => s.kind === "floorplan" && s.derivative);
  if (plans.length === 0 && !est) return null;
  const words = ROOM_WORDS[p.room_type];
  const matches = suggestions.map((s, i) => [i, s] as const).filter(([, s]) => words?.test(`${s.room_label} ${s.plan_label}`));
  const suggested = matches.length === 1 ? matches[0][0] : null;
  // Identity = this reading's position AND text AND source (two same-size bedrooms are different readings).
  const inUse = (s: PlanSuggestion, i: number) =>
    !!est && est.suggestion_index === i && est.dimension_text === s.dimension_text && s.source_ids.includes(est.source_id);
  const sourceName = (id: string) => { const s = state.sources.find((x) => x.id === id); return s ? sourceLabel(s) : "a floor plan"; };
  const estSource = est ? state.sources.find((s) => s.id === est.source_id) : null;
  const analyzed: string[] = (() => {
    const raw = row?.source_ids;
    if (Array.isArray(raw)) return raw;
    try { return raw ? JSON.parse(raw) as string[] : []; } catch { return []; }
  })();
  // One plan is read at a time: the reference message applies once the plan that was read gave no sizes.
  const analyzedAfterPlans = !!row && plans.some((pl) => analyzed.includes(pl.id));

  const choose = (i: number, s: PlanSuggestion) => {
    if (!row) return;
    act("Drawing your room from the plan", () => api.planEstimate(p.id, row.id, i, s.source_ids[0]), (st) => {
      onState(st);
      setMessage(`Drawn from the plan: ${s.room_label || roomName} ${s.dimension_text} (an estimate; your unit may differ). Other rooms aren’t changed.`);
    });
  };

  return (
    <div className="plan-readings">
      {est ? (
        <div className="plan-in-use">
          {estSource?.derivative && <img className="plan-large" src={`/api/projects/${p.id}/sources/${estSource.id}/preview`} alt={sourceLabel(estSource)} />}
          <div>
            <p className="eyebrow">Plan in use · estimate</p>
            <p><strong>{est.room_label || roomName} {est.dimension_text}</strong> from {est.source_label || (estSource ? sourceLabel(estSource) : "your floor plan")}.</p>
            <p className="small muted">Drawn at about {ft(est.width.lower)} × {ft(est.depth.lower)} (the smaller end of ±{est.tolerance_in}″).
              Printed plan sizes are nominal and your unit may differ. Door and window positions aren’t known from the plan.</p>
          </div>
        </div>
      ) : (
        <div className="row wrap" style={{ alignItems: "center" }}>
          <p className="eyebrow" style={{ width: "100%", margin: 0 }}>{plans.length > 1 ? "Your floor plans (reference)" : "Your floor plan (reference)"}</p>
          {plans.map((pl) => (
            <a key={pl.id} className="plan-ref" href={`/api/projects/${p.id}/sources/${pl.id}/preview`} target="_blank" rel="noopener noreferrer">
              <img className={plans.length === 1 || analyzed.includes(pl.id) ? "plan-large" : undefined}
                src={`/api/projects/${p.id}/sources/${pl.id}/preview`} alt={sourceLabel(pl)} />
              <span className="small">{sourceLabel(pl)} ↗</span>
            </a>
          ))}
        </div>
      )}
      {suggestions.length > 0 ? (
        <>
          <p className="small"><strong>Printed room sizes on your plan.</strong> Pick the one that is {roomName}; we’ll draw it at that size.
            No measuring needed{matches.length > 1 ? `; ${matches.length} rooms look like a ${p.room_type.replace("_", " ")}, so choose which one is yours` : ""}.</p>
          <ul className="reading-grid">
            {suggestions.map((s, i) => (
              <li key={i} className={`reading-card ${inUse(s, i) ? "reading-on" : ""} ${suggested === i && !est ? "reading-suggested" : ""}`}>
                {suggested === i && !est && <span className="chip chip-ok">Looks like this room</span>}
                <strong>{s.room_label || "A room"}</strong>
                <span>{s.dimension_text} <span className="muted small">(about {ft(s.width_in)} × {ft(s.depth_in)})</span></span>
                {s.plan_label && <span className="small muted">on plan {s.plan_label}</span>}
                {plans.length > 1 && <span className="small muted">from {sourceName(s.source_ids[0])}</span>}
                {inUse(s, i) ? <span className="fit fit-ok small">In use ✓</span>
                  : <button className="btn btn-small btn-primary" disabled={busy} onClick={() => choose(i, s)}>Use for {roomName}</button>}
              </li>
            ))}
          </ul>
          <p className="small muted">Text read from the plan image; check it against the plan. A building’s full apartment plan is a
            reference: pick only this room’s printed size, never the whole apartment.</p>
        </>
      ) : analyzedAfterPlans && !est ? (
        <div className="small">
          <p><strong>Plan reference: size unavailable.</strong> We couldn’t read printed room sizes on this plan (marketing and 3D
            plans often show none), so it’s kept as a reference only and no furniture is placed from it.</p>
          {onAddPhotos && <button className="btn btn-small" onClick={onAddPhotos}>Add room photos</button>}
        </div>
      ) : !est ? (
        <p className="small muted">Read this plan’s printed room sizes with “Analyze floor plan” in Your room.</p>
      ) : null}
    </div>
  );
}
