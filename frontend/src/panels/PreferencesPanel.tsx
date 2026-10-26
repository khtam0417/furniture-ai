import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { PanelProps } from "../Workspace";
import { CATEGORIES, PRIORITIES, STYLES, label, type ExistingItem, type Preferences } from "../types";
import CategorySelect from "./CategorySelect";
import EditBox from "./EditBox";

const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
const APPROACHES: ["save" | "balanced" | "use_for_preferences", string, string][] = [
  ["save", "Save as much as possible", "Picks a pricier option only when it adds a match for very little extra."],
  ["balanced", "Balanced", "Spends a moderate amount more where an option matches more of your style or priorities."],
  ["use_for_preferences", "Use more for my preferences", "Uses more of the allowance for better matches; equal matches still go to the cheaper option."],
];

export default function PreferencesPanel(props: PanelProps & { onDirty?: (dirty: boolean) => void; afterSave?: () => void; saveRef?: { current: (() => void) | null } }) {
  const { state, status, onState, act, busy, setMessage, goto, onDirty, afterSave, saveRef } = props;
  const coverage = status?.bed_size_coverage;
  // Saved-collection stores plus stores of listings you imported (e.g. Amazon), by the retailer each page recorded.
  const stores = (() => {
    const counts: Record<string, number> = { ...(status?.catalog_retailers ?? {}) };
    for (const s of state.imported_listings) if (s.status === "verified" && s.retailer) counts[s.retailer] = (counts[s.retailer] ?? 0) + 1;
    return Object.entries(counts).filter(([, n]) => n > 0);
  })();
  const p = state.project;
  const saved = state.preferences?.data;
  const [draft, setDraft] = useState<Preferences | null>(saved ?? null);
  const [budget, setBudget] = useState(saved?.budget_cents != null ? String(saved.budget_cents / 100) : "");
  const [term, setTerm] = useState("");

  const wasDirty = useRef(false);
  const ownSave = useRef(false);
  useEffect(() => {
    // A newer saved version (AI patch, kept item, save) wins over an older draft; say so rather than discard silently.
    if (ownSave.current) ownSave.current = false;
    else if (wasDirty.current && afterSave) setMessage("Your preferences were updated, so the form now shows the saved version; earlier unsaved edits were replaced.");
    setDraft(saved ?? null);
    setBudget(saved?.budget_cents != null ? String(saved.budget_cents / 100) : "");
  }, [state.preferences?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = !!draft && JSON.stringify({ ...draft, budget_cents: budget === "" ? null : Math.round(Number(budget) * 100) }) !== JSON.stringify(saved);
  useEffect(() => { wasDirty.current = dirty; onDirty?.(dirty); }, [dirty]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!draft) return <div className="card">Loading preferences…</div>;
  const set = (patch: Partial<Preferences>) => setDraft({ ...draft, ...patch });

  const save = () => {
    const b = budget.trim() === "" ? null : Math.round(Number(budget) * 100);
    if (b != null && (!Number.isFinite(b) || b < 0)) return;
    act("Saving preferences", () => api.savePreferences(p.id, { ...draft, budget_cents: b }), (s) => {
      ownSave.current = true;
      onState(s);
      setMessage("Saved. Plans were rebuilt for this room.");
      if (afterSave) afterSave();
      else goto("plans");
    });
  };
  if (saveRef) saveRef.current = dirty ? save : null;  // the step's Next button saves typed changes, then continues

  const updateItem = (id: string, patch: Partial<ExistingItem>) =>
    set({ existing_items: draft.existing_items.map((e) => (e.id === id ? { ...e, ...patch } : e)) });
  const addItem = () =>
    set({ existing_items: [...draft.existing_items, { id: `u${Date.now()}`, category: "bed_frame", description: "", keep: true, width_in: null, depth_in: null, footprint_source: "unknown", source_ids: [] }] });

  return (
    <div className="stack">
      <EditBox {...props} />

      <div className="card">
        <h2>Budget</h2>
        <div className="row wrap">
          <label className="field"><span>Total budget (USD)</span>
            <input type="number" min={0} step={1} inputMode="numeric" value={budget} placeholder="no limit" onChange={(e) => setBudget(e.target.value)} />
          </label>
          <label className="field"><span>Hold back for delivery & tax: {draft.reserve_pct}%</span>
            <input type="range" min={0} max={40} value={draft.reserve_pct} onChange={(e) => set({ reserve_pct: Number(e.target.value) })} />
          </label>
        </div>
        <p className="muted small">Items must fit within the budget minus this reserve. Real checkout totals (delivery, tax, assembly) are not verified.</p>
        <fieldset className="scope mt">
          <legend className="small">How should “Match my style” use your budget?</legend>
          <div className="seg" role="radiogroup" aria-label="Budget approach">
            {APPROACHES.map(([k, name]) => {
              const on = (draft.budget_approach ?? "balanced") === k;
              return <button type="button" key={k} role="radio" aria-checked={on} className={`seg-btn ${on ? "seg-on" : ""}`}
                onClick={() => set({ budget_approach: k })}>{name}</button>;
            })}
          </div>
          <p className="small muted">{APPROACHES.find(([k]) => k === (draft.budget_approach ?? "balanced"))![2]} You always also get
            “Save money” (the cheapest checked set) and, with a budget, “Closer to my budget” (aims for 85–100% of your item
            allowance with only the furniture you chose). A higher price doesn’t mean better quality.</p>
        </fieldset>
      </div>

      {stores.length > 1 && (
        <div className="card">
          <h2>Stores</h2>
          <p className="muted small">Choose which stores plans may use (none ticked = any store). This also applies to listings you
            imported: an import from another store stays saved but isn’t used while a filter is on. A store you’ve imported from
            (for example Amazon) appears here once you have a checked listing from it; to add one, use “Compare” → paste a product link.</p>
          <div className="chips" role="group" aria-label="Stores">
            {stores.map(([r, n]) => {
              const on = (draft.retailers ?? []).includes(r);
              return <button type="button" key={r} aria-pressed={on} className={`chip chip-btn ${on ? "chip-on" : ""}`}
                onClick={() => set({ retailers: toggle(draft.retailers ?? [], r) })}>{r} ({n})</button>;
            })}
          </div>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h2>Style</h2>
          <div className="chips">
            {STYLES.map((s) => (
              <button key={s} className={`chip chip-btn ${draft.styles.includes(s) ? "chip-on" : ""}`} aria-pressed={draft.styles.includes(s)} onClick={() => set({ styles: toggle(draft.styles, s) })}>{label(s)}</button>
            ))}
          </div>
          <p className="muted small">Style tags on products are our editorial judgment, not retailer claims.</p>
        </div>
        <div className="card">
          <h2>Condition</h2>
          <div className="seg" role="radiogroup" aria-label="Condition">
            {(["either", "new", "secondhand"] as const).map((c) => (
              <button key={c} role="radio" aria-checked={draft.condition === c} className={`seg-btn ${draft.condition === c ? "seg-on" : ""}`} onClick={() => set({ condition: c })}>{c === "either" ? "new or used" : c === "new" ? "new only" : "secondhand only"}</button>
            ))}
          </div>
          {draft.condition === "secondhand" && <p className="muted small">Our catalog has only new retail items. Import secondhand listings in step 1; we won’t invent used stock.</p>}
        </div>
      </div>

      <div className="card">
        <h2>What to buy</h2>
        <div className="chips">
          {CATEGORIES.map((c) => (
            <button key={c} className={`chip chip-btn ${draft.categories.includes(c) ? "chip-on" : ""}`} aria-pressed={draft.categories.includes(c)} onClick={() => set({ categories: toggle(draft.categories, c) })}>{label(c)}</button>
          ))}
        </div>
        {p.room_type === "living_room" && (
          <p className="small coverage">The catalog has no plain sofas yet, so living-room seating uses sofa beds (used closed as a sofa). Choosing “sofa” will show it as unavailable.</p>
        )}
        {p.room_type !== "living_room" && <>
        <div className="row wrap mt">
          <label className="field"><span>Bed size</span>
            <select value={draft.bed_size} onChange={(e) => set({ bed_size: e.target.value as Preferences["bed_size"] })}>
              {["any", "twin", "full", "queen", "king"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="check"><input type="checkbox" checked={draft.shared_use} onChange={(e) => set({ shared_use: e.target.checked })} /> Bed is shared by two people</label>
          <label className="field"><span>Sofa bed</span>
            <select value={draft.sofa_bed} onChange={(e) => set({ sofa_bed: e.target.value as Preferences["sofa_bed"] })}>
              <option value="ok">fine either way</option><option value="prefer">prefer a sofa bed</option><option value="no">no sofa bed</option>
            </select>
          </label>
        </div>
        {draft.shared_use && <p className="muted small">Shared: only beds, mattresses and sofa beds with a documented sleeping width of full size (53 in) or more are offered.</p>}
        {coverage && (
          <p className="small coverage">
            Sizes we can currently offer with verified prices: bed frames {coverage.bed_frame.join(", ") || "none"}; mattresses{" "}
            {coverage.mattress.join(", ") || "none"}; daybeds {coverage.daybed.join(", ") || "none"}. Other sizes will show as unavailable;
            you can import a listing for them in Furnish & compare, under “Add a specific listing”.
          </p>
        )}
        </>}
        {p.room_type === "studio" && (
          <>
            <h3>Studio zones</h3>
            <div className="chips">
              {["sleep", "work", "lounge", "storage"].map((z) => (
                <button key={z} className={`chip chip-btn ${draft.studio_zones.includes(z) ? "chip-on" : ""}`} aria-pressed={draft.studio_zones.includes(z)} onClick={() => set({ studio_zones: toggle(draft.studio_zones, z) })}>{z}</button>
              ))}
            </div>
            <p className="muted small">
              Pick the areas you need. Each plan is checked so every chosen zone is served by something you buy or keep (a sofa bed counts
              for both sleep and lounge), and you’ll be told if one isn’t. Zones are not placed on a floor plan.
            </p>
          </>
        )}
      </div>

      <div className="card">
        <h2>Priorities</h2>
        <p className="muted small">Tap in order of importance. “Match my style” and “Closer to my budget” count each match, and the
          first priority counts most. “Save money” always takes the cheapest checked option.</p>
        <div className="chips">
          {PRIORITIES.map((pr) => {
            const idx = draft.priorities.indexOf(pr);
            return (
              <button key={pr} className={`chip chip-btn ${idx >= 0 ? "chip-on" : ""}`} aria-pressed={idx >= 0} onClick={() => set({ priorities: toggle(draft.priorities, pr) })}>
                {idx >= 0 ? `${idx + 1}. ` : ""}{label(pr)}
              </button>
            );
          })}
        </div>
      </div>

      <div className="card">
        <h2>Furniture you already have</h2>
        {draft.existing_items.length === 0 && <p className="muted">None yet. Items spotted in your sources can be kept in the “Your room” step.</p>}
        <ul className="list">
          {draft.existing_items.map((e) => (
            <li key={e.id} className="existing">
              <CategorySelect value={e.category} onChange={(v) => updateItem(e.id, { category: v })} ariaLabel="What type is this?" />
              <input value={e.description} maxLength={200} placeholder={e.detected_label ? `seen as: ${e.detected_label}` : "description"}
                title={e.detected_label ? `Detected in your sources as “${e.detected_label}”` : undefined}
                onChange={(ev) => updateItem(e.id, { description: ev.target.value })} aria-label="Description" />
              <input type="number" min={1} max={300} placeholder="width in" value={e.width_in ?? ""} aria-label="Width in inches (optional)"
                onChange={(ev) => updateItem(e.id, { width_in: ev.target.value ? Number(ev.target.value) : null, footprint_source: ev.target.value ? "user_stated" : "unknown" })} />
              <input type="number" min={1} max={300} placeholder="depth in" value={e.depth_in ?? ""} aria-label="Depth in inches (optional)"
                onChange={(ev) => updateItem(e.id, { depth_in: ev.target.value ? Number(ev.target.value) : null, footprint_source: ev.target.value ? "user_stated" : "unknown" })} />
              <label className="check"><input type="checkbox" checked={e.keep} onChange={(ev) => updateItem(e.id, { keep: ev.target.checked })} /> keep</label>
              <button className="link" onClick={() => set({ existing_items: draft.existing_items.filter((x) => x.id !== e.id) })}>remove</button>
            </li>
          ))}
        </ul>
        <button className="btn btn-small" onClick={addItem}>Add an item I own</button>
        <p className="muted small">Sizes are optional. Without them, overall fit stays unverified. An item only replaces a purchase once its type is chosen.</p>
      </div>

      <div className="card">
        <h2>Avoid</h2>
        <form className="row wrap" onSubmit={(e) => { e.preventDefault(); if (term.trim()) { set({ excluded_terms: [...draft.excluded_terms, term.trim()] }); setTerm(""); } }}>
          <input className="grow" value={term} maxLength={60} placeholder="a word, material or retailer (e.g. glass)" onChange={(e) => setTerm(e.target.value)} aria-label="Word to avoid" />
          <button className="btn btn-small">Add</button>
        </form>
        <div className="chips">
          {draft.excluded_terms.map((t) => <button key={t} className="chip chip-btn" onClick={() => set({ excluded_terms: draft.excluded_terms.filter((x) => x !== t) })}>{t} ✕</button>)}
          {Object.keys(draft.pinned_product_ids).map((cat) => (
            <button key={cat} className="chip chip-btn chip-on" onClick={() => { const n = { ...draft.pinned_product_ids }; delete n[cat]; set({ pinned_product_ids: n }); }}>keeping {label(cat)} ✕</button>
          ))}
          {draft.excluded_product_ids.length > 0 && <button className="chip chip-btn" onClick={() => set({ excluded_product_ids: [] })}>{draft.excluded_product_ids.length} replaced item(s) hidden ✕</button>}
        </div>
      </div>

      <div className="sticky-save">
        <button className="btn btn-primary" disabled={!!busy || !dirty} onClick={save}>{dirty ? (afterSave ? "Save and continue" : "Save and rebuild plans") : "All changes saved"}</button>
      </div>
    </div>
  );
}
