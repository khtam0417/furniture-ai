import { useState } from "react";
import { api } from "../api";
import type { PanelProps } from "../Workspace";
import { label, type Claim, type ExistingItem, type Preferences } from "../types";
import CategorySelect from "./CategorySelect";
import PlanReadings from "./PlanReadings";

const GROUPS: [Claim["kind"], string, string][] = [
  ["observation", "Observed in your sources", "From the photos and/or floor plan you added."],
  ["external_fact", "Read from a floor plan", "Printed text from your plan. Pick this room’s reading under Room size to draw it as an estimate."],
  ["verified_constraint", "Known size you set", ""],
  ["hypothesis", "Guesses (not measured)", "Shown for context only. Never used to check fit."],
];

const ft = (inch: number) => `${Math.floor(inch / 12)}′ ${Math.round(inch % 12)}″`;

export default function EvidencePanel({ state, onState, act, busy, setMessage, goto }: PanelProps) {
  const p = state.project;
  const roomRow = state.room;
  const room = roomRow?.data.room;
  const suggestions = roomRow?.data.plan_dimension_suggestions ?? [];
  const [w, setW] = useState("");
  const [d, setD] = useState("");
  const [choice, setChoice] = useState<Record<string, string>>({});

  if (!room) {
    const plans = state.sources.filter((s) => s.kind === "floorplan" && s.derivative);
    const anySources = state.sources.some((s) => s.kind === "photo" || s.kind === "floorplan" || s.kind === "floorplan_pdf");
    return (
      <div className="card">
        <h2>What we read about your room</h2>
        {plans.length > 0 ? (
          <>
            <p>Your floor plan is ready to read. “Analyze floor plan” above reads its printed room sizes; then you pick the one that
              is this room. Photos are optional.</p>
            <PlanReadings state={state} act={act} onState={onState} setMessage={setMessage} busy={!!busy}
              roomName={state.apartment?.label ?? "this room"} />
          </>
        ) : anySources ? (
          <p className="muted">Your sources are saved and haven’t been read yet. Use “Analyze” above when you’re ready.</p>
        ) : (
          <p className="muted">Nothing to read yet. Add a floor plan or a few room photos above; both are optional, and plans
            still work without them (fit isn’t assessed until the room has a size).</p>
        )}
        <div className="row"><button className="btn" onClick={() => goto("prefs")}>Set preferences</button></div>
      </div>
    );
  }

  const prefs = state.preferences?.data;
  const saved = (id: string) => prefs?.existing_items.find((e) => e.id === id);
  const categoryOf = (item: ExistingItem) => choice[item.id] ?? saved(item.id)?.category ?? item.category;
  const savePrefs = (next: Preferences, msg: string) =>
    act("Updating", () => api.savePreferences(p.id, next), (s) => { onState(s); setMessage(msg); });
  const keepItem = (item: ExistingItem) => {
    if (!prefs) return;
    const category = categoryOf(item);
    const next: Preferences = {
      ...prefs,
      existing_items: saved(item.id)
        ? prefs.existing_items.map((e) => (e.id === item.id ? { ...e, keep: !e.keep, category } : e))
        : [...prefs.existing_items, { ...item, category, keep: true }],
    };
    savePrefs(next, "Your furniture list was updated and plans were refreshed.");
  };
  const chooseType = (item: ExistingItem, category: string) => {
    setChoice({ ...choice, [item.id]: category });
    if (prefs && saved(item.id)) {
      savePrefs({ ...prefs, existing_items: prefs.existing_items.map((e) => (e.id === item.id ? { ...e, category } : e)) },
        "Item type updated and plans refreshed.");
    }
  };
  const isKept = (id: string) => prefs?.existing_items.some((e) => e.id === id && e.keep) ?? false;

  const scaleKnown = room.scale_status !== "unknown" && room.width && room.depth;
  const methodText = { live_ai: "AI photo analysis (gpt-6-luna)", mocked_ai: "Test model (not real AI)", fixture: "Synthetic fixture (not AI)", manual: "Entered by you" }[room.method];

  const geo = room.inferred_geometry;
  const hasPhotos = state.sources.some((s) => s.kind === "photo");
  const hasPlan = state.sources.some((s) => s.kind === "floorplan" || s.kind === "floorplan_pdf");
  const sizeStatus = scaleKnown
    ? { title: "Known size", line: `About ${ft(room.width!.central ?? room.width!.lower)} × ${ft(room.depth!.central ?? room.depth!.lower)} (${room.scale_status === "plan_dimensions_user_confirmed" ? "from your exact plan" : "as you stated"}). Item sizes are checked against it; doors and walking paths aren’t.` }
    : room.plan_estimate
      ? { title: "Estimated from floor plan", line: "Drawn from the printed size you picked. Your unit may differ, so fit isn’t checked; no measuring needed." }
      : geo?.drawable
        ? { title: geo.synthetic ? "Synthetic demo room" : "Estimated from photos", line: "Drawn at an approximate size from your photos (not exact walls), so fit isn’t checked." }
        : suggestions.length > 0
          ? { title: "Pick your room on the plan", line: "Your floor plan lists printed room sizes. Choose the one that is this room to draw it; no measuring needed." }
          : { title: "Size unavailable", line: hasPlan ? "Your floor plan is kept as a reference. Add room photos, or tell us the size if you know it." : "Add your floor plan or a few room photos to draw this room. No measuring needed." };
  const roomName = state.apartment?.label ?? "this room";
  const srcThumb = (id: string) => {
    const s = state.sources.find((x) => x.id === id);
    return s?.derivative ? <img key={id} src={`/api/projects/${p.id}/sources/${id}/preview`} alt="Photo used for the room map" /> : null;
  };

  return (
    <div className="stack">
      <div className="card">
        <p className="eyebrow">Room size</p>
        <h2>{sizeStatus.title}</h2>
        <p className="small">{sizeStatus.line}</p>
        <PlanReadings state={state} act={act} onState={onState} setMessage={setMessage} busy={!!busy} roomName={roomName}
          onAddPhotos={() => goto("photos")} />
        {geo && !geo.drawable && hasPhotos && (
          <details className="small">
            <summary>What the photos showed</summary>
            <p>{geo.reason}</p>
            {geo.missing_views.length > 0 && <ul>{geo.missing_views.map((v, i) => <li key={i}>{v}</li>)}</ul>}
          </details>
        )}
        {geo?.drawable && (
          <details className="small">
            <summary>{geo.synthetic ? "About the synthetic demo room" : "About the estimate from your photos"}</summary>
            <p>{geo.reason}</p>
            <ul>
              {Object.entries(geo.wall_descriptions).map(([wl, desc]) => (
                <li key={wl}><strong>Wall {wl}</strong>: {desc}{geo.walls_seen.includes(wl) ? "" : " — not seen"}</li>
              ))}
            </ul>
            {geo.features.length > 0 && (
              <p>Located features: {geo.features.map((f) => `${label(f.kind)} on wall ${f.wall} (~${Math.round(f.start_frac * 100)}–${Math.round(f.end_frac * 100)}%)`).join("; ")}.</p>
            )}
            {geo.scale_cues.length > 0 && <p className="muted">Size cues: {geo.scale_cues.join("; ")}.</p>}
            {(geo.omitted_features ?? []).length > 0 && <p className="muted">Not used (no usable photo showed them): {geo.omitted_features!.join("; ")}.</p>}
            <div className="source-strip">{geo.source_ids.map(srcThumb)}</div>
            {geo.missing_views.length > 0 && <p>To improve it: {geo.missing_views.join(" ")}</p>}
          </details>
        )}
        {!hasPhotos && !room.plan_estimate && !scaleKnown && (
          <p className="small muted">Photos are optional: 2 or more overlapping room photos may add an estimated outline and door/window positions.{" "}
            <button className="link" onClick={() => goto("photos")}>Add photos</button></p>
        )}
        <details className="small mt">
          <summary>I already know my room’s exact size (optional)</summary>
          {suggestions.length > 0 && (
            <div className="suggest">
              <p>If a plan is <strong>exactly</strong> your unit’s plan, you can use a printed size as a known size instead of an estimate.</p>
              {suggestions.map((sg, i) => (
                <div key={i} className="suggest-row">
                  <span>{sg.room_label ? `“${sg.room_label}”` : "A room"} <strong>{sg.dimension_text}</strong></span>
                  <button className="btn btn-small" disabled={!!busy}
                    onClick={() => act("Using plan size", () => api.setScale(p.id, { width_in: sg.width_in, depth_in: sg.depth_in, basis: "plan_confirmed", source_ids: sg.source_ids, label: sg.dimension_text, exact_unit_confirmed: true }), (st) => { onState(st); setMessage(`Known size set for ${roomName} from your exact plan. Other rooms aren’t changed.`); })}>
                    This is exactly my unit: use as known size
                  </button>
                </div>
              ))}
            </div>
          )}
          <form className="row wrap" onSubmit={(e) => { e.preventDefault(); act("Saving size", () => api.setScale(p.id, { width_in: Number(w), depth_in: Number(d), basis: "user_stated", source_ids: [], tolerance_in: 4 }), (st) => { onState(st); setMessage("Size saved; plans re-checked."); }); }}>
            <label className="field"><span>Width (inches)</span><input type="number" min={25} max={1200} required value={w} onChange={(e) => setW(e.target.value)} /></label>
            <label className="field"><span>Length (inches)</span><input type="number" min={25} max={1200} required value={d} onChange={(e) => setD(e.target.value)} /></label>
            <button className="btn">Save size</button>
          </form>
          <p className="muted">Only if you already know it; no measuring needed. A known size lets us check item sizes against the room
            (doors and walking paths still aren’t checked).</p>
        </details>
      </div>

      {room.contradictions.length > 0 && (
        <div className="card card-warn">
          <h2>Please check</h2>
          <ul>{room.contradictions.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h2>Fixed features</h2>
          {room.features.length === 0 ? <p className="muted">None noted.</p> : (
            <ul className="list">
              {room.features.map((f) => (
                <li key={f.id} className="list-row"><strong>{label(f.kind)}</strong><span className="muted small">{f.description}{f.wall !== "unknown" ? ` · ${f.wall} wall (approx.)` : ""}</span></li>
              ))}
            </ul>
          )}
          {p.room_type === "studio" && <p className="muted small">The kitchen, bathroom and entry are fixed. Arrangements keep furniture out of them only where their position is located on the room map; anything seen but not located is listed as unchecked, and door swings are estimates.</p>}
        </div>
        <div className="card">
          <h2>Furniture visible in your sources</h2>
          <p className="muted small">
            Furniture drawn on a property floor plan may be illustrative, not what’s in your unit. Choose “Keep it” only for pieces you
            actually own or plan to keep.
          </p>
          {room.existing_items.length === 0 ? <p className="muted">None noted.</p> : (
            <ul className="list">
              {room.existing_items.map((e) => (
                <li key={e.id} className="list-row">
                  <span>
                    <strong>“{e.detected_label || label(e.category)}”</strong> <span className="muted small">{e.description}</span>
                  </span>
                  <span className="row wrap">
                    <CategorySelect value={categoryOf(e)} onChange={(v) => chooseType(e, v)} ariaLabel={`Type of ${e.detected_label || "item"}`} />
                    <button className="btn btn-small" disabled={!!busy || !prefs} onClick={() => keepItem(e)}>{isKept(e.id) ? "Keeping ✓" : "Keep it"}</button>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">
            Quoted names are what the analysis of your sources saw. A kept item replaces a purchase only when its type is set; we pre-fill a type
            only when the name is unambiguous. Sizes stay unknown unless you add them in Preferences.
          </p>
        </div>
      </div>

      <details className="card">
        <summary><strong>Evidence details</strong> <span className="small muted">(everything read, observed and guessed, as recorded)</span></summary>
        {GROUPS.map(([kind, title, hint]) => {
          const items = room.claims.filter((c) => c.kind === kind);
          if (!items.length) return null;
          return (
            <div key={kind} className={`claims claims-${kind}`}>
              <h3>{title}</h3>
              {hint && <p className="muted small">{hint}</p>}
              <ul>{items.map((c, i) => <li key={i}>{c.statement} <span className="muted small">({c.source_ids.length} source{c.source_ids.length === 1 ? "" : "s"})</span></li>)}</ul>
            </div>
          );
        })}
        {room.coverage_notes.length > 0 && (
          <details>
            <summary>Source coverage notes</summary>
            <ul className="small">{room.coverage_notes.map((c, i) => <li key={i}>{c}</li>)}</ul>
          </details>
        )}
        <p className="small muted">Older entries keep the wording they were saved with. The current status is under Room size above.</p>
      </details>

      <details className="card diag">
        <summary>Diagnostics</summary>
        <p className="small">Method: {methodText}{room.prompt_version ? ` · prompt ${room.prompt_version}` : ""} · room evidence version {roomRow!.version}</p>
        {roomRow!.data.call && <pre className="small pre">{JSON.stringify(roomRow!.data.call, null, 1)}</pre>}
        {room.untrusted_text_seen.length > 0 && <p className="small">Text visible in images (treated as untrusted, never followed): {room.untrusted_text_seen.join(" | ")}</p>}
      </details>
    </div>
  );
}
