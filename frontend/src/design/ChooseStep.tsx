import { useEffect, useRef, useState, type MutableRefObject } from "react";
import {
  STOP_TEXT, autoChooseState, bedroomInfo, budgetNote, coverage, describeGroup, makeStopper, mergeProgress, optionsLine, pieceQueueText, placementNote,
  refineCandidates, runAfterSave, runFindQueue, searchKey, shoppingLine, sourceNote,
  type GroupResult, type GroupStatus, type StopReason,
} from "./findQueue";
import { api } from "../api";
import {
  RESALE_SITES, cap, pieceName, readableMissing, type BedSize, type Candidate, type DesignItem, type DesignPrefs, type ItemProducts, type Lead, type OnlineLeads,
  type ProductQuery, type Preview,
} from "../designTypes";
import { STYLES, label, money, type ApartmentState, type ProjectState } from "../types";
import type { DesignCtx } from "./DesignFlow";
import PlanCanvas from "./PlanCanvas";
import { budgetTextOf, mergeBudgetText, mergeDraft } from "./prefsDraft";

/** Step 3: budget and style for the whole design, then a real product for each piece. */
export default function ChooseStep({ ctx, active, anchor, onAnchorState, onDirty, onFinding, saveRef, apt, onApartment }: {
  ctx: DesignCtx; active: boolean; anchor: ProjectState | null; onAnchorState: (s: ProjectState) => void;
  onFinding?: (finding: boolean) => void;  // the workspace locks other design changes (e.g. the helper) while finding
  apt: ApartmentState; onApartment: (a: ApartmentState) => void;
  onDirty: (dirty: boolean) => void;
  saveRef: MutableRefObject<((then?: () => void) => void) | null>;  // the flow saves unsaved budget/style before moving on
}) {
  const { aid, ds, setDs, act, busy, status } = ctx;
  const d = ds.design!.data;
  const v = ds.design!.version;
  const m = ds.plan_map!.data;
  const b = ds.evaluation?.budget;
  const [draft, setDraft] = useState<DesignPrefs>(d.prefs);
  const [budgetText, setBudgetText] = useState(budgetTextOf(d.prefs.budget_cents));
  // Settings saved elsewhere (the design helper, another save) flow into the form; the user's own unsaved edits stay.
  const savedPrefs = useRef(d.prefs);
  const savedKey = JSON.stringify(d.prefs);
  useEffect(() => {
    const prev = savedPrefs.current;
    savedPrefs.current = d.prefs;
    if (JSON.stringify(prev) === savedKey) return;
    setDraft((dr) => mergeDraft(prev, d.prefs, dr));
    setBudgetText((t) => mergeBudgetText(prev.budget_cents, d.prefs.budget_cents, t));
  }, [savedKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const [open, setOpen] = useState<string | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(d.prefs) || budgetText !== (d.prefs.budget_cents != null ? String(Math.round(d.prefs.budget_cents / 100)) : "");
  const zoneName = (id: string | null) => (id && ds.zone_names?.[id]) || m.rooms.find((r) => r.id === id)?.kind || "";
  const stores = Object.keys(status?.catalog_retailers ?? {});
  const [city, setCity] = useState(apt.context.city ?? "");
  const [st, setSt] = useState(apt.context.state ?? "");
  const [zip, setZip] = useState(apt.context.zip ?? "");
  const location = ds.location ?? "";
  // The place's public location is used only for local-pickup searches (city/state/ZIP; the unit is never searched).
  const saveLocation = () => act("Saving your city or ZIP", async () => {
    const a = await api.saveContext(aid, { ...apt.context, city: city.trim(), state: st.trim(), zip: zip.trim() });
    onApartment(a);
    return api.design(aid);
  }, (s) => { setDs(s); ctx.setMessage("Location saved for local-pickup searches."); });

  const currentPrefs = (): DesignPrefs | null => {
    const n = budgetText.trim() ? Number(budgetText.replace(/[$,\s]/g, "")) : null;
    if (n != null && (!Number.isFinite(n) || n < 0 || n > 50000)) { ctx.setMessage("Enter a budget between $0 and $50,000, or leave it empty."); return null; }
    return { ...draft, budget_cents: n == null ? null : Math.round(n) * 100 };
  };
  // Saved options per piece (catalog + checked pages only; no web or AI call), refreshed as results arrive.
  const [previews, setPreviews] = useState<Record<string, Preview>>({});
  const refreshPreviews = () => api.designPreviews(aid).then((r) => setPreviews(r.items)).catch(() => undefined);
  useEffect(() => { refreshPreviews(); }, [aid, v]); // eslint-disable-line react-hooks/exhaustive-deps
  const [viewFilter, setViewFilter] = useState<"all" | "new" | "used">("all");
  const [finding, setFinding] = useState(false);
  useEffect(() => { onFinding?.(finding); }, [finding]); // eslint-disable-line react-hooks/exhaustive-deps
  const [progress, setProgress] = useState<GroupStatus[]>([]);
  const [remaining, setRemaining] = useState<string[]>([]);
  const [remainingRefine, setRemainingRefine] = useState(false);  // the paused/stopped run was a "Search more" run
  const [found, setFound] = useState<Record<string, GroupResult>>({});
  const [paused, setPaused] = useState<string | null>(null);
  const [stopped, setStopped] = useState<StopReason | null>(null);
  const stopper = useRef(makeStopper()).current;
  const mounted = useRef(true);  // unmounting stops the queue after the current piece type (no hidden searches)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  // This step stays mounted while hidden: leaving it (Next/Back/step tabs) stops the queue after the current piece
  // type. Coming back never resumes it; "Continue" does.
  useEffect(() => { if (!active) stopper.stop("left"); }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  // Found/progress results belong to the SAVED search settings they were made with; a saved change makes them stale.
  const key = searchKey(d.prefs, location);
  const resultsKey = useRef(key);
  const clearResults = () => { setProgress([]); setRemaining([]); setRemainingRefine(false); setFound({}); setPaused(null); setStopped(null); };
  useEffect(() => { if (key !== resultsKey.current) { resultsKey.current = key; clearResults(); } }, [key]);
  /** Save unsaved settings first, then search+check each piece type in this plan ONCE (bounded queue, one group at a
   *  time). With `refine`, the explicit "Search more" run: one extra search only for the given types. Only runs on a
   *  click: never on load, never automatically after another run. Never chooses products. */
  const findFurniture = async (onlyAsked?: string[], refineAsked = false) => {
    let only = onlyAsked, refine = refineAsked;
    stopper.reset();
    setStopped(null);
    setFinding(true);
    setPaused(null);
    ctx.setMessage(null);
    try {
      if (dirty) {
        const prefs = currentPrefs();
        if (!prefs) return;
        const saved = await api.designPrefs(aid, prefs, v);
        const k = searchKey(saved.design!.data.prefs, saved.location ?? "");
        const changed = k !== resultsKey.current;
        if (changed) { resultsKey.current = k; clearResults(); }  // before the run, so it's never cleared mid-run
        const next = runAfterSave(changed, only, refine);
        ({ only, refine } = next);
        if (next.restarted) ctx.setMessage("Your search settings changed, so every piece type is searched again first.");
        setDs(saved);
        setDraft(saved.design!.data.prefs);
      }
      const plan = await api.designFindPlan(aid);  // fresh state: no stale version is used
      const keys = only;
      const groups = keys ? plan.groups.filter((g) => keys.includes(g.key)) : plan.groups;
      if (!groups.length) { ctx.setMessage("Every piece already has a product (or is marked as owned): nothing to search."); return; }
      const stop = () => stopper.shouldStop() || !mounted.current;
      const before = refine || only ? progress : [];
      const run = refine ? groups.map((g) => ({ ...g, label: `${g.label} (searching more)` })) : groups;
      const res = await runFindQueue(run, async (key) => {
        const r = await api.designFindGroup(aid, key, refine);
        setFound((f) => ({ ...f, [key]: r }));
        refreshPreviews();
        return r;
      }, { max: plan.max_per_run, shouldStop: stop, onUpdate: (st) => setProgress(mergeProgress(before, st)),
           pauseOn: (r) => r.limited ?? null });
      setRemaining(res.remaining);
      setRemainingRefine(refine && res.remaining.length > 0);  // Continue resumes the same kind of run
      setPaused(res.paused);
      setStopped(res.remaining.length ? stopper.reason() : null);
      setDs(await api.design(aid));
    } catch (e) {
      ctx.setMessage((e as Error).message);
    } finally {
      setFinding(false);
    }
  };
  const save = (then?: () => void) => {
    const prefs = currentPrefs();
    if (!prefs) return;
    act("Saving preferences", () => api.designPrefs(aid, prefs, v), (s) => { setDs(s); setDraft(s.design!.data.prefs); then?.(); });
  };
  useEffect(() => { onDirty(dirty); }, [dirty]); // eslint-disable-line react-hooks/exhaustive-deps
  saveRef.current = dirty ? save : null;
  const purchasable = d.items.filter((i) => !i.owned);
  const moreKeys = refineCandidates(found, progress.map((g) => g.key));
  const reviewIds = Object.keys(ds.evaluation?.review ?? {});
  const auto = autoChooseState({ finding, dirty, open: purchasable.filter((i) => !i.product_id).length });
  const cov = coverage(purchasable.filter((i) => !i.product_id), previews);
  const rooms = bedroomInfo(m.rooms, ds.room_uses ?? {}, m.status === "mapped");
  const shopping = shoppingLine({
    pieces: purchasable.length, searches: new Set(purchasable.map(groupOf)).size, ...rooms,
    hasBed: d.items.some((i) => ["bed_frame", "sofa_bed", "daybed"].includes(i.category)),
  });

  return (
    <div className="stack">
      <div className="card">
        <h2>Shopping preferences</h2>
        <fieldset className="prefs-lock" disabled={finding} aria-busy={finding}>
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <label className="field" style={{ maxWidth: 160 }}><span>Total budget ($)</span>
            <input inputMode="numeric" value={budgetText} onChange={(e) => setBudgetText(e.target.value)} placeholder="e.g. 3000" />
          </label>
          <label className="field" style={{ maxWidth: 220 }}><span>Held for delivery and tax (%)</span>
            <input type="number" min={0} max={40} value={draft.reserve_pct} onChange={(e) => setDraft({ ...draft, reserve_pct: Math.max(0, Math.min(40, Number(e.target.value) || 0)) })} />
          </label>
          <fieldset className="scope">
            <legend className="small">How to use the budget</legend>
            <div className="seg">
              <button type="button" className={`seg-btn ${draft.approach === "low" ? "seg-on" : ""}`} aria-pressed={draft.approach === "low"} onClick={() => setDraft({ ...draft, approach: "low" })}>Keep costs low</button>
              <button type="button" className={`seg-btn ${draft.approach === "use" ? "seg-on" : ""}`} aria-pressed={draft.approach === "use"} onClick={() => setDraft({ ...draft, approach: "use" })}>Use my budget for better matches</button>
            </div>
          </fieldset>
        </div>
        <p className="small muted">
          {draft.approach === "low" ? "“Choose for me” fills every piece with the cheapest option that fits, keeping a share of your item budget for each piece still open."
            : "“Choose for me” fills every piece first, keeping a share of your item budget for each piece still open, and prefers options that match more of your styles within each piece’s share. Only options that fit your rooms are chosen. A higher price isn’t higher quality."}
        </p>
        <fieldset className="scope">
          <legend className="small">Styles (a preference, not a promise)</legend>
          <div className="chips">
            {STYLES.map((s) => {
              const on = draft.styles.includes(s);
              return <button type="button" key={s} className={`chip chip-btn ${on ? "chip-on" : ""}`} aria-pressed={on}
                onClick={() => setDraft({ ...draft, styles: on ? draft.styles.filter((x) => x !== s) : [...draft.styles, s].slice(0, 6) })}>{label(s)}</button>;
            })}
          </div>
        </fieldset>
        <div className="row wrap">
          <label className="field" style={{ maxWidth: 170 }}><span>Bed size</span>
            <select value={draft.bed_size} onChange={(e) => setDraft({ ...draft, bed_size: e.target.value as BedSize })}>
              {(["twin", "full", "queen", "king"] as BedSize[]).map((s) => <option key={s} value={s}>{cap(s)}</option>)}
            </select>
          </label>
          <label className="field" style={{ maxWidth: 210 }}><span>New or secondhand</span>
            <select value={draft.condition} onChange={(e) => setDraft({ ...draft, condition: e.target.value as DesignPrefs["condition"] })}>
              <option value="either">New + secondhand</option><option value="new">New only</option><option value="secondhand">Secondhand only</option>
            </select>
          </label>
          <fieldset className="scope">
            <legend className="small">How will you get it?</legend>
            <div className="seg">
              {(["either", "local_pickup", "delivery"] as const).map((f) => (
                <button type="button" key={f} className={`seg-btn ${(draft.fulfillment ?? "either") === f ? "seg-on" : ""}`}
                  aria-pressed={(draft.fulfillment ?? "either") === f} onClick={() => setDraft({ ...draft, fulfillment: f })}>
                  {f === "either" ? "Either" : f === "local_pickup" ? "Local pickup" : "Delivery"}</button>
              ))}
            </div>
          </fieldset>
          <label className="field" style={{ maxWidth: 220 }}><span>When do you need it? (optional)</span>
            <input value={draft.timing ?? ""} maxLength={60} placeholder="e.g. before Dec 1" onChange={(e) => setDraft({ ...draft, timing: e.target.value })} />
          </label>
          {draft.condition !== "new" && (
            <fieldset className="scope">
              <legend className="small">Resale marketplaces for secondhand (all approved = none ticked)</legend>
              <div className="chips">
                {RESALE_SITES.map(([key, name, domain]) => {
                  const on = (draft.resale_sites ?? []).includes(key);
                  return <button type="button" key={key} className={`chip chip-btn ${on ? "chip-on" : ""}`} aria-pressed={on} title={domain}
                    onClick={() => setDraft({ ...draft, resale_sites: on ? (draft.resale_sites ?? []).filter((x) => x !== key) : [...(draft.resale_sites ?? []), key] })}>{name}</button>;
                })}
              </div>
              <span className="small muted">Only these established marketplaces are searched and checked for used items. An approved marketplace doesn’t verify individual sellers, condition, stock or delivery.</span>
            </fieldset>
          )}
          {stores.length > 0 && draft.condition !== "secondhand" && (
            <fieldset className="scope">
              <legend className="small">Stores for new items (none = any)</legend>
              <div className="chips">
                {stores.map((s) => {
                  const on = draft.retailers.includes(s);
                  return <button type="button" key={s} className={`chip chip-btn ${on ? "chip-on" : ""}`} aria-pressed={on}
                    onClick={() => setDraft({ ...draft, retailers: on ? draft.retailers.filter((x) => x !== s) : [...draft.retailers, s] })}>{s}</button>;
                })}
              </div>
            </fieldset>
          )}
        </div>
        <p className="small muted">
          {location ? `Searches use ${location} (your unit is never searched).` : "No city or ZIP saved for this place."}
          {(draft.timing ?? "").trim() ? " Timing is a preference for your shopping, not a promised delivery date." : ""}
        </p>
        {(draft.fulfillment === "local_pickup" && !location) && (
          <div className="recovery small">
            <p>Local pickup needs a city and state or a ZIP to search near you.</p>
            <div className="row wrap">
              <label className="field"><span>City</span><input value={city} maxLength={80} onChange={(e) => setCity(e.target.value)} /></label>
              <label className="field" style={{ maxWidth: 100 }}><span>State</span><input value={st} maxLength={40} onChange={(e) => setSt(e.target.value)} /></label>
              <label className="field" style={{ maxWidth: 120 }}><span>or ZIP</span><input value={zip} maxLength={10} inputMode="numeric" onChange={(e) => setZip(e.target.value)} /></label>
              <button type="button" className="btn btn-small" disabled={!!busy || !(zip.trim() || (city.trim() && st.trim()))} onClick={saveLocation}>Save location</button>
            </div>
          </div>
        )}
        </fieldset>
        {finding && <p className="small muted">Settings are locked while furniture is being found (they were saved first).</p>}
        <p className="small muted">
          {draft.condition === "either" ? "New + secondhand: new items from the approved stores and used listings from the approved resale marketplaces."
            : draft.condition === "new" ? "New only: the approved stores." : "Secondhand only: the approved resale marketplaces."}
        </p>
        <div className="row wrap">
          <button className="btn btn-primary" disabled={!!busy || finding} onClick={() => findFurniture()}>
            {dirty ? "Save & find furniture" : "Find furniture for my plan"}</button>
          {finding && <button className="btn btn-small" onClick={() => stopper.stop("user")}>Stop after this piece type</button>}
          {dirty && !finding && <button className="btn btn-small" disabled={!!busy} onClick={() => save()}>Save only</button>}
          {dirty && <span className="small muted">Unsaved changes are kept here until you save.</span>}
          {draft.bed_size !== d.prefs.bed_size && <span className="small">Changing the bed size resizes the draft beds; other pieces stay where they are.</span>}
        </div>
      </div>

      {progress.length > 0 && (
        <div className="card find-progress" aria-live="polite">
          <h2 style={{ margin: 0 }}>Finding furniture {finding ? "…" : ""}</h2>
          <p className="small muted">One piece type at a time (pieces of the same type and size share a search). Options appear below as each finishes; nothing is chosen for you.</p>
          <ul className="small">
            {progress.map((g) => (
              <li key={g.key}><strong>{cap(g.label)}</strong>: {g.state === "running" ? "searching and checking…" : g.state === "waiting" ? "waiting"
                : g.state === "not_run" ? "not searched yet" : g.state === "error" ? `couldn’t search (${g.error})` : g.result ? describeGroup(g.result) : "done"}</li>
            ))}
          </ul>
          {paused && <p className="small warn">Paused: {paused} Options found so far stay below.</p>}
          {!paused && stopped && !finding && <p className="small muted">{STOP_TEXT[stopped]} Options found so far stay below.</p>}
          {!finding && dirty && (remaining.length > 0 || moreKeys.length > 0) && (
            <p className="small muted">You’ve changed your settings: “Save & find furniture” searches every piece type again with them.</p>
          )}
          {!finding && !dirty && remaining.length > 0 && (
            <button className="btn btn-small" disabled={!!busy} onClick={() => findFurniture(remaining, remainingRefine)}>
              Continue ({remaining.length} more piece type{remaining.length === 1 ? "" : "s"}{remainingRefine ? ", searching more" : ""})</button>
          )}
          {!finding && !dirty && remaining.length === 0 && moreKeys.length > 0 && (
            <div className="row wrap" style={{ alignItems: "center", gap: "0.5rem" }}>
              <button className="btn btn-small" disabled={!!busy} onClick={() => findFurniture(moreKeys, true)}>
                Search more for {moreKeys.length} piece type{moreKeys.length === 1 ? "" : "s"}</button>
              <span className="small muted">Fewer than 3 options that fit your room and budget came back for {moreKeys.length === 1 ? "this type" : "these types"}. This makes one
                more online search per type (it uses more of the AI allowance); everything found and checked so far stays.</span>
            </div>
          )}
        </div>
      )}

      {b && <BudgetBox ctx={ctx} onReview={(id) => setOpen(id)} />}

      <div className="card">
        <div className="row wrap" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Furniture for each piece</h2>
          <div className="row wrap" style={{ gap: "0.4rem" }}>
            <button className="btn btn-small" disabled={!!busy || finding} title={finding ? LOCK_TITLE : undefined}
              onClick={() => ctx.go("arrange")}>Add furniture / review rooms</button>
            {reviewIds.length > 0 && (
              <button className="btn btn-small" disabled={!!busy || finding}
                onClick={() => act("Replacing pieces that don’t fit", () => api.designAuto(aid, v, reviewIds), setDs)}>
                Replace {reviewIds.length === 1 ? "the piece" : `${reviewIds.length} pieces`} that don’t fit</button>
            )}
            <button className="btn btn-primary btn-small" disabled={!!busy || !auto.enabled} title={auto.why ?? undefined}
              onClick={() => act("Choosing products", () => api.designAuto(aid, v), setDs)}>Choose for me (pieces without a product)</button>
          </div>
        </div>
        <p className="small" role="status">{shopping}</p>
        {auto.why && purchasable.some((i) => !i.product_id) && <p className="small muted" role="status">{auto.why}</p>}
        {cov.total > 0 && Object.keys(previews).length > 0 && (
          <p className="small" role="status">
            Of {cov.total} open piece{cov.total === 1 ? "" : "s"}: {cov.affordable} {cov.affordable === 1 ? "has" : "have"} an option that fits
            the plan and its share of the budget; {cov.fitting - cov.affordable} more {cov.fitting - cov.affordable === 1 ? "has" : "have"} options
            that fit the plan but cost more than their share
            {cov.onlyBad ? `; ${cov.onlyBad} only ${cov.onlyBad === 1 ? "has" : "have"} options that don’t fit the room` : ""}
            {cov.none ? `; ${cov.none} ${cov.none === 1 ? "has" : "have"} no options yet` : ""}. Fit on the plan is an estimate.
          </p>
        )}
        <p className="small muted">Real products from our checked collection and pages checked for you. Choosing one replaces the draft with its listed size; if that size doesn’t fit where the piece is, it moves to a clear spot in the same room, or the card says it doesn’t fit.</p>
        {d.prefs.condition === "either" && (
          <div className="seg" role="group" aria-label="Show options">
            {(["all", "new", "used"] as const).map((f) => (
              <button key={f} type="button" className={`seg-btn ${viewFilter === f ? "seg-on" : ""}`} aria-pressed={viewFilter === f}
                onClick={() => setViewFilter(f)}>{f === "all" ? "All" : f === "new" ? "New" : "Secondhand"}</button>
            ))}
          </div>
        )}
        <ul className="list">
          {d.items.filter((i) => !i.on_item || !d.items.some((h) => h.id === i.on_item)).flatMap((it) => [it, ...d.items.filter((a) => a.on_item === it.id)]).map((it) => (
            <PieceRow key={it.id} ctx={ctx} it={it} zone={zoneName(it.zone_id)} open={open === it.id} onToggle={() => setOpen(open === it.id ? null : it.id)}
              anchor={anchor} onAnchorState={onAnchorState} sub={!!it.on_item} preview={previews[it.id]} viewFilter={d.prefs.condition === "either" ? viewFilter : "all"}
              found={found[previews[it.id]?.group ?? groupOf(it)]} locked={finding}
              queue={pieceQueueText(progress.find((g) => g.key === (previews[it.id]?.group ?? groupOf(it)))?.state)} />
          ))}
        </ul>
      </div>
    </div>
  );
}

export function BudgetBox({ ctx, onReview }: { ctx: DesignCtx; onReview?: (id: string) => void }) {
  const b = ctx.ds.evaluation!.budget;
  return (
    <div className={`card ${b.status === "incomplete" ? "card-warn" : ""}`} aria-live="polite">
      <div className="row wrap" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <h2 style={{ margin: 0 }}>{b.status === "complete" ? "Selected total" : "Selected so far"}: {money(b.subtotal_cents)}</h2>
        <span className={`chip ${b.status === "complete" ? "chip-ok" : ""}`}>
          {b.status === "complete" ? "Every piece has a product" : b.status === "empty" ? "No pieces yet"
            : b.missing.length ? `Incomplete: ${b.missing.length} piece${b.missing.length === 1 ? "" : "s"} without a product`
            : `Incomplete: ${(b.budget_review ?? []).length} over the budget`}
        </span>
      </div>
      <p className="small">
        {b.chosen} of {b.to_buy} piece{b.to_buy === 1 ? "" : "s"} to buy chosen{b.owned ? ` · ${b.owned} you already own` : ""}.
        {b.item_allowance_cents != null && <> Item budget {money(b.item_allowance_cents)} (your {money(b.budget_cents)} minus {money(b.reserve_cents)} held for delivery and tax). {b.over_allowance ? <strong>Over the item budget by {money(-(b.remaining_cents ?? 0))}.</strong> : <>Left: {money(b.remaining_cents)}.</>}</>}
      </p>
      {(b.budget_review ?? []).length > 0 && (
        <div className="banner banner-warn small" role="alert">
          <strong>{b.budget_review!.length} chosen product{b.budget_review!.length === 1 ? " doesn’t" : "s don’t"} fit your item budget</strong> and
          {b.budget_review!.length === 1 ? " needs" : " need"} replacing (kept as chosen until you change {b.budget_review!.length === 1 ? "it" : "them"};
          nothing is removed for you). Budgets for the other pieces and searches leave {b.budget_review!.length === 1 ? "it" : "them"} out, so you can fix one at a time.
          <ul className="small missing-list">
            {b.budget_review!.map((x) => (
              <li key={x.id}><strong>{cap(x.name)}</strong>: {money(x.price_cents)}. {x.message}{" "}
                {onReview && <button className="link" onClick={() => onReview(x.id)}>See cheaper options</button>}</li>
            ))}
          </ul>
        </div>
      )}
      {b.missing.length > 0 && (
        <details className="small">
          <summary>{b.missing.length} piece{b.missing.length === 1 ? "" : "s"} without a product</summary>
          <ul className="small missing-list">
            {b.missing.map((x) => (
              <li key={x.id}><strong>{cap(x.name)}</strong> {onReview && <button className="link" onClick={() => onReview(x.id)}>Review</button>}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="small muted">{b.note} The total isn’t final until every piece has a product.</p>
    </div>
  );
}

function previewPick(pv: Preview | undefined, filter: "all" | "new" | "used"): Candidate[] {
  const all = pv?.candidates ?? [];
  const isUsed = (c: Candidate) => c.condition === "secondhand";
  if (filter === "new") return all.filter((c) => !isUsed(c)).slice(0, 3);
  if (filter === "used") return all.filter(isUsed).slice(0, 3);
  const n = all.filter((c) => !isUsed(c)), u = all.filter(isUsed);
  const first = [n[0], u[0]].filter(Boolean) as Candidate[];  // at least one of each when both exist
  return [...first, ...all.filter((c) => !first.includes(c))].slice(0, 3);
}

/** The "Find furniture" group a piece belongs to (type + bed size), same as the server's. */
function groupOf(it: DesignItem): string {
  return `${it.category}|${it.category === "bed_frame" || it.category === "mattress" ? it.size ?? "" : ""}`;
}

function PieceRow({ ctx, it, zone, open, onToggle, anchor, onAnchorState, sub, preview, viewFilter, found, locked = false, queue = null }: {
  locked?: boolean;  // finding furniture is running: changes wait until it stops (so the design doesn't change mid-run)
  queue?: string | null;  // this piece's live queue state
  ctx: DesignCtx; it: DesignItem; zone: string; open: boolean; onToggle: () => void;
  anchor: ProjectState | null; onAnchorState: (s: ProjectState) => void; sub?: boolean;
  preview?: Preview; viewFilter: "all" | "new" | "used"; found?: GroupResult;
}) {
  const { aid, ds, setDs, act, busy } = ctx;
  const v = ds.design!.version;
  const prefs = ds.design!.data.prefs;
  const p = it.product_id ? ds.products[it.product_id] : null;
  const warn = ds.evaluation?.warnings[it.id] ?? [];
  const missing = ds.evaluation?.budget.missing.find((x) => x.id === it.id);
  const bed = it.category === "bed_frame" || it.category === "mattress";
  const line = optionsLine(preview, viewFilter);
  const review = ds.evaluation?.review?.[it.id];
  const overBudget = ds.evaluation?.budget.budget_review?.find((x) => x.id === it.id);
  // Options: ready recommendations by default; explicitly, everything within the whole remaining item budget.
  const [scope, setScope] = useState<"recommended" | "within_budget">("recommended");
  const [data, setData] = useState<ItemProducts | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [limit, setLimit] = useState(8);
  const [sort, setSort] = useState<NonNullable<ProductQuery["sort"]>>("recommended");
  const [stylesOnly, setStylesOnly] = useState(false);
  const [browseSize, setBrowseSize] = useState<string>("");
  const [online, setOnline] = useState<OnlineLeads | null>(null);
  const [leadMsg, setLeadMsg] = useState<Record<string, string>>({});
  const [leadCond, setLeadCond] = useState<"new" | "secondhand">(prefs.condition === "secondhand" ? "secondhand" : "new");
  const [url, setUrl] = useState("");
  const [cond, setCond] = useState("");
  const [reload, setReload] = useState(0);
  const [used, setUsed] = useState<OnlineLeads | null>(null);
  const [usedNote, setUsedNote] = useState<string | null>(null);
  useEffect(() => { if (data?.secondhand) setUsed(data.secondhand); }, [data]);
  const wantsUsed = prefs.condition !== "new";
  // ONE bounded search for used listings, then automatic checks of at most 3 listing pages (server-side caps).
  // One page through the same used check (approved marketplace, every redirect checked, listing evidence, cache).
  const checkUsed = (l: Lead) => act("Checking this listing", () => api.designCheckLead(aid, it.id, l.url, "secondhand", v), (r) => {
    setUsedNote(r.message);
    setReload((n) => n + 1);
  });
  const findUsed = (recheck = false) => act(recheck ? "Checking listings again" : "Searching resale listings", () => api.designFindSecondhand(aid, it.id, v, recheck), (r) => {
    setUsed(r.secondhand);
    setUsedNote(r.verified_matches ? `${r.verified_matches} used listing${r.verified_matches === 1 ? "" : "s"} verified and added to the options.`
      : `Checked ${r.checked} listing page${r.checked === 1 ? "" : "s"}; none could be verified as a used item with a price and size.`);
    setReload((n) => n + 1);
  });
  useEffect(() => {
    if (!open) return;
    let live = true;
    setErr(null);
    api.designProducts(aid, it.id, { limit, sort, styles_only: stylesOnly || undefined, size: browseSize || undefined,
      scope: scope === "within_budget" ? scope : undefined })
      .then((r) => { if (live) { setData(r); if (r.online) setOnline(r.online); } })
      .catch((e) => { if (live) setErr((e as Error).message); });
    return () => { live = false; };
  }, [open, aid, it.id, v, limit, sort, stylesOnly, browseSize, reload, scope]);

  const choose = (c: Candidate) => act("Choosing", async () => {
    if (c.size_mismatch && browseSize) {  // an explicit size switch for this bed, then the product
      const s1 = await api.designItems(aid, [{ op: "size", id: it.on_item ?? it.id, size: browseSize as BedSize }], v);
      return api.designChooseProduct(aid, it.id, c.product_id, s1.design!.version);
    }
    return api.designChooseProduct(aid, it.id, c.product_id, v);
  }, (s) => { setDs(s); setBrowseSize(""); });
  const [refineAvail, setRefineAvail] = useState(false);
  useEffect(() => { if (data) setRefineAvail(!!data.refine_available); }, [data]);
  const findOnline = (refine: boolean) => act(refine ? "Searching for specific products" : "Searching the web for this piece",
    () => api.designFindOnline(aid, it.id, v, refine), (r) => { setOnline(r.online); setRefineAvail(!!r.refine_available); });
  // Secondhand preference: always the used-listing check (same trust gate as "Find secondhand options").
  const checkCond = (l: Lead) => (prefs.condition === "secondhand" ? "secondhand" : prefs.condition === "new" ? "new" : (l.resale_site ? leadCond : "new"));
  const check = (l: Lead) => act("Checking this option", () => api.designCheckLead(aid, it.id, l.url, checkCond(l), v), (r) => {
    setLeadMsg((m) => ({ ...m, [l.url]: r.message }));
    setReload((n) => n + 1);
  });

  const src = ds.selected_source;
  return (
    <li className={`piece-row ${open ? "piece-open" : ""} ${sub ? "piece-sub" : ""}`} id={`piece-${it.id}`}>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <div className="piece-body">
          <strong>{sub ? "+ " : ""}{pieceName(it)}</strong> <span className="small muted">{zone}{it.placed === false ? " · not placed on the plan" : ""}</span>
          <div className="small">
            {it.owned ? "You already own this: nothing to buy."
              : p ? <>{p.name} · {money(p.price_cents)} · {p.width_in}″ × {p.depth_in}″ · {p.condition} · {p.retailer} {p.url && <a href={p.url} target="_blank" rel="noopener noreferrer">store page ↗</a>}
                  {overBudget && <span className="chip chip-warn">Needs replacing: over budget</span>}</>
              : queue && !(line && line.ready) ? <span className="muted" role="status">{queue}</span>
              : line ? <span className={line.ready ? "" : "muted"}>{line.text}{queue ? ` · ${queue}` : ""}</span>
              : found ? <span className="missing">No options yet: {describeGroup(found)}</span>
              : <span className="muted">Ready to find options: use “Find furniture” above. {missing && /budget/.test(missing.reason) ? missing.reason : ""}</span>}
          </div>
          {review && (
            <div className="banner banner-warn small" role="alert">
              <strong>This {pieceName(it).toLowerCase()} doesn’t fit where it is:</strong> {review.problems.join(" ")}
              <div className="row wrap mt" style={{ gap: "0.4rem" }}>
                {review.can_move && <button className="btn btn-small" disabled={!!busy || locked}
                  onClick={() => act("Moving it inside the room", () => api.designFit(aid, it.id, v), setDs)}>Move it inside the room</button>}
                <button className="btn btn-small" disabled={!!busy || locked}
                  onClick={() => act("Replacing with an option that fits", () => api.designAuto(aid, v, [it.id]), setDs)}>Replace with an option that fits</button>
                <button className="btn btn-small" onClick={onToggle}>See all options</button>
              </div>
            </div>
          )}
          {overBudget && p && (
            <div className="banner banner-warn small" role="alert">
              <strong>This {pieceName(it).toLowerCase()} is over your budget:</strong> {overBudget.message}
              {preview && preview.total > 0 ? ` ${preview.total} option${preview.total === 1 ? "" : "s"} within its share ${preview.total === 1 ? "is" : "are"} below.`
                : " Use “Find furniture” above to search for one within its share."}
              <div className="row wrap mt" style={{ gap: "0.4rem" }}>
                {!open && <button className="btn btn-small" onClick={onToggle}>See cheaper options</button>}
                <button className="btn btn-small" disabled={!!busy || locked}
                  onClick={() => act("Removing the product", () => api.designChooseProduct(aid, it.id, null, v), setDs)}>Remove this product (keep the piece)</button>
              </div>
            </div>
          )}
          {warn.length > 0 && <ul className="small warn-list">{warn.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        </div>
        <div className="row wrap" style={{ gap: "0.4rem" }}>

          {!it.owned && <button className="btn btn-small" aria-expanded={open} onClick={onToggle}>{open ? "Close" : "View all options"}</button>}
        </div>
      </div>
      {!open && !it.owned && previewPick(preview, viewFilter).length > 0 && (
        <ul className="pv-list">
          {previewPick(preview, viewFilter).map((c) => (
            <li key={c.product_id} className={`pv ${c.product_id === it.product_id ? "cand-on" : ""}`}>
              <span className="pv-name" title={c.name ?? ""}>{c.name}</span>
              <span className="small">{money(c.price_cents)} · {c.condition === "secondhand" ? "used" : "new"} · {c.retailer}</span>
              {c.style_label && <span className="small muted">{c.style_label}</span>}
              {c.variants && c.variants > 1 && <span className="small muted">{c.variants} colours or finishes</span>}
              <PlacementLine c={c} />
              <BudgetLine c={c} />
              <SourceLine c={c} />
              {c.product_id === it.product_id ? <span className="fit fit-ok small">Chosen ✓</span>
                : c.picked_elsewhere ? <span className="small muted">Picked for another piece</span>
                : c.blocked ? <span className="small warn">{c.blocked}</span>
                : <button className="btn btn-small btn-primary" disabled={!!busy || locked} title={locked ? LOCK_TITLE : undefined}
                    onClick={() => choose(c)}>Choose</button>}
            </li>
          ))}
        </ul>
      )}
      {open && (
        <div className="stack mt" style={{ gap: "0.6rem" }}>
          {src && it.placed !== false && (
            <div className="choose-canvas"><PlanCanvas roomUses={ds.room_uses} imageUrl={src.preview} imageW={src.width} imageH={src.height} map={ds.plan_map!.data}
              items={ds.design!.data.items} products={ds.products} warnings={ds.evaluation?.warnings} selected={it.on_item ?? it.id}
              caption="The selected piece is outlined." /></div>
          )}
          <div className="opt-filters row wrap">
            <label className="field"><span className="small">Sort</span>
              <select value={sort} onChange={(e) => { setSort(e.target.value as typeof sort); setLimit(8); }}>
                <option value="recommended">Recommended</option><option value="price_low">Price: low to high</option><option value="price_high">Price: high to low</option>
              </select>
            </label>
            {prefs.styles.length > 0 && (
              <label className="small row" style={{ gap: "0.3rem" }}>
                <input type="checkbox" checked={stylesOnly} onChange={(e) => { setStylesOnly(e.target.checked); setLimit(8); }} /> Only my styles
              </label>
            )}
            {bed && (
              <label className="field"><span className="small">Bed size shown</span>
                <select value={browseSize || it.size || ""} onChange={(e) => { setBrowseSize(e.target.value === it.size ? "" : e.target.value); setLimit(8); }}>
                  {(["twin", "full", "queen", "king"] as BedSize[]).map((s) => <option key={s} value={s}>{cap(s)}{s === it.size ? " (this bed)" : ""}</option>)}
                </select>
              </label>
            )}
          </div>
          {err && <p className="small" role="alert">{err}</p>}
          {!data && !err && <p className="small muted">Loading options…</p>}
          {data && (
            <div className="small">
              {scope === "recommended" ? (
                <p className="small">
                  Recommended: options that fit {it.placed === false ? "(once placed)" : "the plan"} and are within this piece’s share and your whole remaining budget, cheapest workable first.
                  {data.held_text ? ` ${data.held_text}` : ""}
                  {(data.broader ?? 0) > 0 && <>{" "}<button className="link" onClick={() => { setScope("within_budget"); setLimit(8); }}>
                    Also show {data.broader} more within your whole budget</button> (above this piece’s share, or not fitting the plan).</>}
                </p>
              ) : (
                <p className="small warn">
                  Showing every option within your whole remaining item budget, including ones above this piece’s share (choosing one leaves less
                  for the other pieces) or that don’t fit the plan (those can’t be chosen here). Options over the whole budget are never shown.{" "}
                  <button className="link" onClick={() => { setScope("recommended"); setLimit(8); }}>Back to recommended</button>
                </p>
              )}
            </div>
          )}
          {data && data.candidates.length > 0 && (
            <>
              <p className="small muted">Showing {data.candidates.length} of {data.total} option{data.total === 1 ? "" : "s"} from our checked collection and your checked imports{data.total_all != null && data.total_all > data.total ? ` (${data.total_all - data.total} more checked but not shown)` : ""}.</p>
              <ul className="cand-list">
                {data.candidates.map((c) => (
                  <li key={c.product_id} className={`cand ${c.product_id === it.product_id ? "cand-on" : ""}`}>
                    {c.image ? <img src={c.image} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <span className="cand-noimg" />}
                    <div className="stack" style={{ gap: "0.15rem" }}>
                      <strong className="small">{c.name}</strong>
                      <span className="small">{money(c.price_cents)} · {c.width_in}″ W × {c.depth_in}″ D{c.height_in ? ` × ${c.height_in}″ H` : ""} · {c.condition} · {c.retailer}</span>
                      <span className="small muted">
                        {c.condition === "secondhand" ? (c.condition_verified === false ? "Used (your declaration, not verified). " : "Used (stated on the listing page). ") : ""}
                        {c.style_matches.length ? `Matches ${c.style_matches.map(label).join(", ")}. ` : ""}Checked {c.checked_at?.slice(0, 10) ?? "date unknown"}{c.stale ? " (may have changed)" : ""}.
                        {c.origin === "user_import" ? " Checked from a page you found." : ""}
                      </span>
                      <PlacementLine c={c} />
                      <BudgetLine c={c} />
                      <SourceLine c={c} />
                      {c.new_warnings.length > 0 && <span className="small warn">At this spot: {c.new_warnings.join(" ")}</span>}
                      {c.fit_basis === "relative" && <span className="small muted">Not fit-checked: your plan has no usable printed sizes.</span>}
                      <div className="row wrap">
                        {c.product_id === it.product_id ? <span className="fit fit-ok small">Chosen ✓</span>
                          : c.blocked ? <span className="small warn">{c.blocked}</span>
                          : c.placement?.status === "conflict" ? <span className="small warn">Can’t be chosen here: it doesn’t fit its room.</span>
                          : <button className={`btn btn-small ${c.affordable === false ? "" : "btn-primary"}`} disabled={!!busy || locked} title={locked ? LOCK_TITLE : undefined} onClick={() => choose(c)}>
                            {c.size_mismatch ? `Switch this bed to ${c.nominal_size} and choose` : c.affordable === false ? "Choose anyway (above its share)" : "Choose this"}</button>}
                        {c.url && <a className="small" href={c.url} target="_blank" rel="noopener noreferrer">Store page ↗</a>}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
              {data.total > data.candidates.length && (
                <button className="btn btn-small" onClick={() => setLimit((n) => n + 8)}>See more options ({data.total - data.candidates.length} more)</button>
              )}
            </>
          )}
          {data && data.candidates.length === 0 && (
            <div className="recovery">
              <p className="small"><strong>{(data.total_all ?? 0) > 0 ? "No option within your budget that fits yet." : "No matching product saved yet."}</strong> {data.reason ?? "Nothing matches these filters."} This piece stays in your design{p ? "" : " and is listed as missing"}.</p>
              {data.reason_kind === "condition" && prefs.condition === "secondhand" && <p className="small">Use “Find secondhand options” below to search resale listings for this piece.</p>}
              {data.reason_kind === "condition" && prefs.condition === "new" && <p className="small">Use “Find more online” below to search for new ones.</p>}
              {data.reason_kind === "size" && bed && !browseSize && <p className="small">Other bed sizes are available: try “Bed size shown” above, or find one online below.</p>}
            </div>
          )}
          {data && wantsUsed && (
            <div className="online">
              <div className="row wrap" style={{ justifyContent: "space-between" }}>
                <strong className="small">Secondhand listings</strong>
                <button className="btn btn-small" disabled={!!busy || locked || !data.online_available || data.needs_location} onClick={() => findUsed(!!used)}>
                  {used ? "Check listings again" : "Find secondhand options"}</button>
              </div>
              {!used && <p className="small muted">One search for used {pieceName({ category: it.category, size: it.size }).toLowerCase()} listings on resale sites near your city or ZIP (or with delivery, per your choice); then up to 3 listing pages are checked automatically. A listing is added only if its page says it’s used or pre-owned and shows a price and size.</p>}
              <p className="small muted">{used?.trust_note ?? data.trust_note}</p>
              {usedNote && <p className="small" role="status">{usedNote}</p>}
              {!!used?.hidden_unapproved && <p className="small muted">{used.hidden_unapproved} result{used.hidden_unapproved === 1 ? "" : "s"} from other sites or non-listing pages {used.hidden_unapproved === 1 ? "was" : "were"} left out.</p>}
              {used && (
                <ul className="lead-list">
                  {used.leads.filter((l) => l.kind === "product").map((l) => (
                    <li key={l.url} className="lead">
                      <strong className="small">{l.title || l.domain}</strong>
                      <span className="small muted">{l.domain}</span>
                      <span className={`small ${l.used_check?.outcome === "verified" ? "" : "muted"}`}>
                        {!l.used_check ? "Not checked yet (the first 3 are checked automatically; check this one below)."
                          : l.used_check.outcome === "verified" ? `Verified used listing: ${money(l.used_check.price_cents ?? null)}. It’s in the options above.`
                          : l.used_check.outcome === "incomplete" ? `Used, but incomplete (missing ${readableMissing(l.used_check.missing)}), so it can’t be chosen.`
                          : `Not added: ${l.used_check.outcome}.`}
                      </span>
                      <div className="row wrap">
                        {(!l.used_check || l.used_check.outcome !== "verified") && (
                          <button className="btn btn-small" disabled={!!busy || locked} onClick={() => checkUsed(l)}>{l.used_check ? "Check again" : "Check this option"}</button>
                        )}
                        <a className="small" href={l.url} target="_blank" rel="noopener noreferrer">Open ↗</a>
                      </div>
                    </li>
                  ))}
                  {used.leads.length === 0 && <li className="small">No individual listings on the approved marketplaces came back. Try again later, or choose more marketplaces in Shopping preferences.</li>}
                </ul>
              )}
            </div>
          )}
          {data && prefs.condition !== "secondhand" && (
            <div className="online">
              <div className="row wrap" style={{ justifyContent: "space-between" }}>
                <strong className="small">More options online</strong>
                {!online && <button className="btn btn-small" disabled={!!busy || locked || !data.online_available} onClick={() => findOnline(false)}>Find more online</button>}
                {online && refineAvail && <button className="btn btn-small" disabled={!!busy || locked || !data.online_available} onClick={() => findOnline(true)}>
                  Search for specific products (one more search)</button>}
              </div>
              {!data.online_available && <p className="small muted">Web search needs the AI connection, which isn’t available right now.</p>}
              {data.needs_location && <p className="small warn">Local pickup needs your city and state or ZIP: add it under Shopping preferences above.</p>}
              {!online && <p className="small muted">One web search for specific {pieceName({ category: it.category, size: browseSize || it.size }).toLowerCase()} product pages, using your styles, condition, remaining budget and your city or ZIP (never your unit). Results are leads until checked.</p>}
              {online && (() => {
                const products = online.leads.filter((l) => l.kind === "product");
                const stores = online.leads.filter((l) => l.kind !== "product");
                const card = (l: Lead) => (
                  <li key={l.url} className="lead">
                    <strong className="small">{l.title || l.domain}</strong>
                    <span className="small muted">{l.domain}</span>
                    {l.cited_text && <span className="small muted">{l.cited_text}</span>}
                    {l.checked && <span className={`small ${l.checked.status === "verified" ? "" : "warn"}`}>
                      {l.checked.status === "verified" ? `Checked: ${money(l.checked.price_cents)}` : `Checked, incomplete (missing ${readableMissing(l.checked.missing)})`}</span>}
                    {leadMsg[l.url] && <span className="small" role="status">{leadMsg[l.url]}</span>}
                    <div className="row wrap">
                      {l.kind === "product" && (checkCond(l) === "secondhand" && !l.resale_site
                        ? <span className="small muted">Secondhand checks only read listings on the approved resale marketplaces.</span>
                        : <button className="btn btn-small" disabled={!!busy || locked} onClick={() => check(l)}>{l.checked ? "Check again" : "Check this option"}</button>)}
                      <a className="small" href={l.url} target="_blank" rel="noopener noreferrer">Open ↗</a>
                    </div>
                  </li>
                );
                return (
                  <>
                    <p className="small muted">{online.refined ? "Refined product search. " : ""}{online.summary_note} {online.searched_at ? `Searched ${online.searched_at.slice(0, 16).replace("T", " ")} UTC${online.cached ? " (saved result, no new search)" : ""}.` : ""}</p>
                    {online.source_note && <p className="small muted">{online.source_note}{online.hidden_unapproved ? ` ${online.hidden_unapproved} result${online.hidden_unapproved === 1 ? " from another website was" : "s from other websites were"} left out.` : ""}</p>}
                    {products.length === 0 ? (
                      <p className="small">No specific product pages came back{stores.length ? ", only store or category pages" : ""}.
                        {refineAvail ? " You can run one more search focused on specific products." : online.refined ? " Import a product link you have, or browse the sources below." : ""}</p>
                    ) : (
                      <>
                        {prefs.condition === "either" && (
                          <label className="small row" style={{ gap: "0.3rem" }}>Check approved resale listings as:
                            <select value={leadCond} onChange={(e) => setLeadCond(e.target.value as "new" | "secondhand")}>
                              <option value="new">New</option><option value="secondhand">Used (page must say so)</option>
                            </select>
                          </label>
                        )}
                        <ul className="lead-list">{products.map(card)}</ul>
                      </>
                    )}
                    {stores.length > 0 && (
                      <details className="small">
                        <summary>More sources ({stores.length}): store, search and category pages</summary>
                        <p className="small muted">These list many products, so they can’t be checked as one item. Open one to browse, then import a single product link.</p>
                        <ul className="lead-list">{stores.map(card)}</ul>
                      </details>
                    )}
                  </>
                );
              })()}
            </div>
          )}
          {data && anchor && (
            <details className="small">
              <summary>Import a product link you already have (Amazon, Article, IKEA, Target, or an approved resale listing)</summary>
              <form className="row wrap mt" onSubmit={(e) => {
                e.preventDefault();
                act("Importing listing", () => api.listing(anchor.project.id, url, it.category, cond, false), (r) => {
                  onAnchorState(r.state);
                  setUrl("");
                  ctx.setMessage(r.snapshot.status === "verified" ? "Listing imported. It appears in the options if it matches this piece." : `Listing saved but incomplete (missing ${readableMissing(r.snapshot.missing)}); it can’t be chosen.`);
                  setReload((n) => n + 1);
                });
              }}>
                <input className="grow" type="url" required placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Product page link" />
                <select value={cond} required onChange={(e) => setCond(e.target.value)} aria-label="Condition">
                  <option value="">Condition…</option><option value="new">New</option><option value="secondhand">Used</option>
                </select>
                <button className="btn btn-small" disabled={!!busy || !cond}>Import</button>
              </form>
              {data.search_links.length > 0 && (
                <p className="small">Or browse stores yourself: {data.search_links.map((l, i) => <span key={l.url}>{i ? " · " : ""}<a href={l.url} target="_blank" rel="noopener noreferrer">{l.label} ↗</a></span>)}</p>
              )}
            </details>
          )}
          {p && <button className="link small" disabled={!!busy} onClick={() => act("Clearing", () => api.designChooseProduct(aid, it.id, null, v), setDs)}>Remove this product (keep the draft piece)</button>}
        </div>
      )}
    </li>
  );
}

/** Shown while finding furniture runs. (Budget: an option over the whole remaining item budget can't be chosen; one
 *  above its piece's share only from the explicit broader view, with the warning visible. The server enforces both.) */
const LOCK_TITLE = "Wait until finding furniture finishes (or stop it)";

function SourceLine({ c }: { c: Candidate }) {
  const n = sourceNote(c);
  if (!n) return null;
  return (
    <span className="small muted">{n}{" "}
      {c.url && <a href={c.url} target="_blank" rel="noopener noreferrer">Open the listing ↗</a>}</span>
  );
}

function PlacementLine({ c }: { c: Candidate }) {
  const n = placementNote(c.placement, c.fit_basis);
  return n ? <span className={`small ${n.bad ? "warn" : "fit-note"}`}>{n.text}</span> : null;
}

function BudgetLine({ c }: { c: Candidate }) {
  const n = budgetNote(c);
  return n ? <span className={`small ${n.over ? "warn" : "muted"}`}>{n.text}</span> : null;
}
