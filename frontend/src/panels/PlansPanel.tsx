import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { PanelProps } from "../Workspace";
import {
  fitPlain, inches, label, money, MAPPED_BASES, PLAN_BLURB, planFitPlain, planName, type Arrangement, type Checklist, type ChecklistItem, type FitLabel, type IssueAction,
  type LayoutSet, type Plan, type PlanItem, type Preferences,
} from "../types";
import EditBox from "./EditBox";
import AlternativesPanel from "./AlternativesPanel";
import LayoutCanvas from "./LayoutCanvas";
import ShoppingList from "./ShoppingList";
import ObservedWalls from "./ObservedWalls";
import PlanReadings from "./PlanReadings";

const FIT_CLASS: Record<FitLabel, string> = {
  "Fits tested assumptions": "fit-ok",
  "Tight / conditional": "fit-tight",
  "Fit unverified": "fit-unknown",
  "Does not fit": "fit-bad",
};
const ft = (v: number) => `${Math.floor(v / 12)}′${Math.round(v % 12)}″`;

function FitBadge({ v, checks }: { v: FitLabel; checks?: PlanItem["fit_checks"] }) {
  const f = fitPlain(v, checks);
  return <span className={`fit ${FIT_CLASS[v]}`} title={`${f.help} (Saved label: ${v}.)`}>{f.text}</span>;
}

function Thumb({ src, alt }: { src: string | null; alt: string }) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) return <div className="item-thumb item-thumb-none" aria-hidden>no photo</div>;
  return <img className="item-thumb" src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />;
}

const refOf = (i: PlanItem) => i.product_id ?? i.existing_item_id ?? i.name;

/** Actions for plain-text conflicts saved before typed issues: only what the text says unambiguously
 *  ("No verified twin bed frame …" → Find twin bed frame), plus Edit preferences. The saved text is not changed. */
function legacyActions(conflicts: string[]): IssueAction[] {
  const out: IssueAction[] = [];
  for (const c of conflicts) {
    const m = /^No verified (twin|full|queen|king) (bed frame|mattress)\b/.exec(c);
    if (m) {
      const category = m[2] === "bed frame" ? "bed_frame" : "mattress";
      if (!out.some((a) => a.category === category)) {
        out.push({ kind: "find", label: `Find ${m[1]} ${m[2]}`, category, size: m[1] as IssueAction["size"] });
      }
    }
  }
  out.push({ kind: "edit_preferences", label: "Edit preferences", category: null, size: null });
  return out;
}

export default function PlansPanel(props: PanelProps & { desiredTiming?: string; listRequest?: number }) {
  const { state, onState, act, busy, setMessage, goto, desiredTiming } = props;
  const ps = state.plans?.data;
  const prefs = state.preferences?.data;
  const [planKey, setPlanKey] = useState<string | null>(null);  // null = follow the saved selection
  const [arrKey, setArrKey] = useState<string>("");
  const [selected, setSelected] = useState<string | null>(null);
  const [showAccess, setShowAccess] = useState(true);
  const [altCat, setAltCat] = useState<string | null>(null);
  const [altSize, setAltSize] = useState<string | null>(null);
  const [searchCat, setSearchCat] = useState<string>(state.preferences?.data.categories[0] ?? "desk");
  const [view, setView] = useState<"room" | "list">("room");
  const [list, setList] = useState<Checklist | null>(null);
  const [listBusy, setListBusy] = useState(false);
  const pid = state.project.id;
  useEffect(() => { if (props.listRequest) setView("list"); }, [props.listRequest]);

  // The saved shopping list (selected plan + manual purchase marks) for the current plan version.
  const loadList = () => api.checklist(pid).then(setList).catch(() => setList(null));
  useEffect(() => { loadList(); }, [pid, state.plans?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const effectiveKey = planKey ?? list?.plan_key ?? "balanced";
  const plan: Plan | undefined = ps?.plans.find((p) => p.key === effectiveKey) ?? ps?.plans[0];
  const pickPlan = (key: string) => {
    setPlanKey(key);
    setArrKey("");
    if (state.plans) api.selectPlan(pid, key, state.plans.version).then(setList).catch(() => loadList());
  };
  const mark = (it: ChecklistItem, purchased: boolean) => {
    if (!list?.plan_key || !list.plan_version || !it.product_id) return;
    setListBusy(true);
    api.markPurchased(pid, list.plan_key, it.product_id, purchased, list.plan_version)
      .then(setList)
      .catch((e) => { setMessage(`Not saved: ${(e as Error).message}`); loadList(); })
      .finally(() => setListBusy(false));
  };
  const runAction = (a: IssueAction) => {
    if (a.kind === "edit_preferences") { goto("prefs"); return; }
    if (a.category) { setAltSize(a.size); setAltCat(a.category); }
  };
  const layouts: LayoutSet | null = plan?.layouts ?? ps?.room_layout ?? null;
  const mapped = !!layouts && MAPPED_BASES.includes(layouts.basis);
  const arrangement: Arrangement | null = mapped ? (layouts!.arrangements.find((a) => a.key === arrKey) ?? layouts!.arrangements[0] ?? null) : null;
  // After a successful swap the new plan version arrives; select the swapped-in product (instead of clearing the
  // selection) and bring the fixed-room drawing into view so the change is visible at once.
  const pendingSelect = useRef<string | null>(null);
  const roomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const next = pendingSelect.current;
    pendingSelect.current = null;
    setSelected(next);
    if (next) {
      setTimeout(() => {
        roomRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        roomRef.current?.focus({ preventScroll: true });
      }, 60);
    }
  }, [planKey, arrKey, state.plans?.id]);
  const onSwapped = (productId: string) => {
    pendingSelect.current = productId;  // the plan item ref of the new product (its product id)
    setAltCat(null);
    setView("room");
  };

  // The product behind the selected drawing (a mattress/chair selects its bed/desk's own row, too).
  const selItem = plan?.items.find((i) => refOf(i) === selected) ?? null;
  const placedRefs = useMemo(() => new Set(arrangement?.placements.map((p) => p.ref) ?? []), [arrangement]);
  const assocOf = (ref: string) => arrangement?.associated.find((a) => a.ref === ref);
  const unplacedOf = (ref: string) => arrangement?.unplaced.find((u) => u.ref === ref);
  const hasPhotos = state.sources.some((s) => s.kind === "photo");

  const updatePrefs = (fn: (p: Preferences) => Preferences, msg: string) => {
    if (!prefs) return;
    act("Updating plans", () => api.savePreferences(state.project.id, fn(prefs)), (s) => { onState(s); setMessage(msg); });
  };
  const keep = (it: PlanItem) =>
    updatePrefs((p) => ({ ...p, pinned_product_ids: { ...p.pinned_product_ids, [it.category]: it.product_id! } }), `Keeping ${it.name} in every plan.`);
  const regenerate = () => act("Generating arrangements", () => api.generateLayouts(state.project.id), (s) => { onState(s); setMessage("Arrangements regenerated as a new plan version; products unchanged."); });

  if (!ps) {
    return (
      <div className="card">
        <h2>Plan & layout</h2>
        <p className="muted">No plans yet.</p>
        <button className="btn btn-primary" disabled={!!busy} onClick={regenerate}>Build plans</button>
      </div>
    );
  }

  const geoSources = (layouts?.geometry_source_ids ?? []).map((id) => state.sources.find((s) => s.id === id)).filter((s) => s?.derivative);
  const floorplan = layouts?.floorplan_source_ids.map((id) => state.sources.find((s) => s.id === id)).find((s) => s?.derivative);

  const roomCard = (() => {
    if (!layouts) {
      return (
        <div className="stack">
          <h2>Furniture arrangement</h2>
          <p className="muted">This plan version was saved before arrangements existed. Regenerate them: products stay the same and no AI is used.</p>
          <button className="btn btn-primary" disabled={!!busy} onClick={regenerate}>Generate arrangements</button>
        </div>
      );
    }
    if (layouts.basis === "concept_template") {
      return (
        <div className="stack">
          <h2>Furniture arrangement</h2>
          <p className="muted">This saved version drew furniture in an illustrative template room, not your room. It stays in history, but it isn’t shown as a layout.</p>
          <button className="btn btn-primary" disabled={!!busy} onClick={regenerate}>Regenerate from your room evidence</button>
        </div>
      );
    }
    if (layouts.basis === "unavailable") {
      const old = !!state.room && !state.room.data.room.inferred_geometry && hasPhotos;
      const hasPlan = state.sources.some((s) => s.kind === "floorplan" && s.derivative);
      if (hasPlan) {
        // Floor-plan users: show THEIR plan and its printed sizes here, never a photos-only empty screen.
        return (
          <div className="stack map-needed">
            <p className="eyebrow">Your room in 2D</p>
            <h2>{(state.room?.data.plan_dimension_suggestions ?? []).length ? "Pick this room on your floor plan" : "Your floor plan"}</h2>
            <PlanReadings state={state} act={act} onState={onState} setMessage={setMessage} busy={!!busy}
              roomName={state.apartment?.label ?? "this room"} onAddPhotos={() => goto("photos")} />
            {state.room?.data.room.inferred_geometry?.observed_only && <ObservedWalls geo={state.room.data.room.inferred_geometry} />}
            <p className="muted small">The products here are a shopping shortlist until the room is drawn. No room outline is guessed.</p>
          </div>
        );
      }
      return (
        <div className="stack map-needed">
          <p className="eyebrow">Your room in 2D</p>
          <h2>{old ? "Re-analyze photos to draw this room" : hasPhotos ? "Size unavailable from these photos" : "Add a floor plan or photos to draw your room"}</h2>
          <p>{layouts.notes[0]}</p>
          <p className="muted small">We draw furniture only inside a room we have a size for (from a floor plan, photos or a size you know).
            Until then, the products here are a shopping shortlist; no room outline is guessed. No measuring needed.</p>
          {state.room?.data.room.inferred_geometry?.observed_only && <ObservedWalls geo={state.room.data.room.inferred_geometry} />}
          {layouts.missing_views && layouts.missing_views.length > 0 && (
            <details className="small">
              <summary>Photos that would help</summary>
              <ul>{layouts.missing_views.map((v, i) => <li key={i}>{v}</li>)}</ul>
            </details>
          )}
          <div className="row wrap">
            <button className="btn btn-primary" onClick={() => goto("photos")}>{old ? "Go to photos and re-analyze" : "Add a floor plan or photos"}</button>
            <button className="btn" onClick={() => goto("evidence")}>See what we read</button>
          </div>
        </div>
      );
    }
    return (
      <>
        <div className="row wrap" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Your room in 2D{plan ? " — click furniture to compare" : ""}</h2>
          <span className={`canvas-tag ${layouts.basis === "scaled_room_lower_bound" ? "tag-scaled" : "tag-concept"}`}>
            {layouts.basis === "estimated_from_photos" ? "Estimated from photos · not exact walls"
              : layouts.basis === "estimated_from_plan" ? "Estimated layout from selected plan · your unit may differ"
              : layouts.basis === "synthetic_demo" ? "Synthetic demo room" : "Known size · lower bound"}
          </span>
        </div>
        {plan && layouts.arrangements.length > 0 && (
          <div className="arr-picker" role="radiogroup" aria-label="Arrangement option">
            {layouts.arrangements.map((a) => (
              <button key={a.key} role="radio" aria-checked={arrangement?.key === a.key}
                className={`arr-btn ${arrangement?.key === a.key ? "arr-btn-on" : ""}`} onClick={() => setArrKey(a.key)}>{a.title}</button>
            ))}
          </div>
        )}
        {plan && <p className="hint small">Click (or tab to) a piece to see the actual product and compare options; swapping redraws it here while the room stays the same.</p>}
        <div className="canvas-wrap">
          <LayoutCanvas layout={layouts} arrangement={plan ? arrangement : null} selected={selected} showAccess={showAccess}
            onSelect={(ref) => {
              setSelected(ref);
              const pl = ref ? arrangement?.placements.find((x) => x.ref === ref) : null;
              if (pl && pl.kind === "product" && pl.category) { setAltSize(null); setAltCat(pl.category); }
            }} />
        </div>
        {selItem && (
          <div className="sel-card" aria-live="polite">
            {selItem.product_id ? <Thumb src={selItem.image_url} alt={`${selItem.retailer ?? "Retailer"} photo of ${selItem.name}`} /> : <div className="item-thumb item-thumb-none">owned</div>}
            <div>
              <div className="product-cat">{label(selItem.category)}</div>
              <div className="product-name">{selItem.name}</div>
              <div className="product-meta">
                {selItem.existing_item_id ? "You already own this" : <><strong>{money(selItem.price_cents)}</strong> · {inches(selItem.width_in)} × {inches(selItem.depth_in)} in</>}
                {selItem.url && <> · <a href={selItem.url} target="_blank" rel="noopener noreferrer">{selItem.retailer} page ↗</a></>}
              </div>
              {selItem.product_id && (
                <button className="btn btn-small btn-primary" disabled={!!busy} onClick={() => { setAltSize(null); setAltCat(selItem.category); }}>Compare {label(selItem.category)} options</button>
              )}
            </div>
          </div>
        )}
        <p className="canvas-caption small">
          {layouts.envelope_label}.{layouts.basis === "estimated_from_photos" ? " Drawn as an approximate rectangle at the estimated scale, not your exact walls."
            : layouts.basis === "estimated_from_plan" ? ` Estimated from ${state.room?.data.room.plan_estimate?.source_label || "your floor plan"} (${state.room?.data.room.plan_estimate?.room_label ?? ""} ${state.room?.data.room.plan_estimate?.dimension_text ?? ""}); door and window positions aren’t known from the plan.` : ""} The room stays the same in every option; only furniture moves. Shapes are simplified
          top-down symbols at each product’s listed width × depth, not its exact look.
          {plan && arrangement ? ` ${arrangement.intent}` : " No shopping plan is feasible right now, so the room is shown empty."}
        </p>
        {layouts.wall_descriptions && Object.keys(layouts.wall_descriptions).length > 0 && (
          <p className="small muted">{Object.entries(layouts.wall_descriptions).map(([w, d]) => `Wall ${w}: ${d}`).join(" · ")}</p>
        )}
        {(geoSources.length > 0 || floorplan) && (
          <div className="source-strip">
            {geoSources.map((s) => <img key={s!.id} src={`/api/projects/${state.project.id}/sources/${s!.id}/preview`} alt="Photo used to map the room" />)}
            {floorplan && <img src={`/api/projects/${state.project.id}/sources/${floorplan.id}/preview`} alt="Your floor plan source" />}
            <span className="small muted">Mapped from these {state.project.is_demo ? "sample images" : "sources"}{floorplan ? " (the drawing is Furniture AI’s interpretation, not the original plan)" : ""}.</span>
          </div>
        )}
        <div className="legend">
          <span><i className="lg-item" />furniture to buy (thick edge = against wall)</span>
          <span><i className="lg-owned" />already owned</span>
          <span><i className="lg-sel" />selected</span>
          <span><i className="lg-access" />assumed access zone</span>
          {layouts.fixed_zones.length > 0 && <span><i className="lg-fixed" />fixed feature / keep-clear (estimated)</span>}
          {(layouts.wall_markers ?? []).length > 0 && <span><i className="lg-window" />window seen in photos (position estimated)</span>}
          <label className="check small"><input type="checkbox" checked={showAccess} onChange={(e) => setShowAccess(e.target.checked)} /> show access zones</label>
        </div>
        {arrangement && arrangement.unplaced.length > 0 && (
          <div className="banner banner-warn small mt">
            <strong>Not drawn ({arrangement.unplaced.length})</strong>
            <ul>{arrangement.unplaced.map((u) => <li key={u.ref}>{u.label}: {u.reason}</li>)}</ul>
          </div>
        )}
        <details className="mt">
          <summary>What was checked, and what wasn’t</summary>
          {arrangement && <ul className="checklist check-ok">{arrangement.checks_passed.map((c, i) => <li key={i}>{c}</li>)}</ul>}
          {arrangement && <ul className="checklist check-open">{arrangement.unresolved.map((c, i) => <li key={i}>{c}</li>)}</ul>}
          <h3>Assumptions</h3>
          <ul className="small muted">{layouts.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
          {layouts.fixed_zones.map((z, i) => <p key={i} className="small muted">{z.label}: {z.assumption}</p>)}
          {(layouts.wall_markers ?? []).map((mk, i) => <p key={`w${i}`} className="small muted">{mk.label} on wall {mk.wall}: {mk.caveat}</p>)}
          {layouts.notes.map((n, i) => <p key={i} className="note small">{n}</p>)}
          <p className="small muted mono">room version {layouts.room_version_id ?? "—"} · room frame {layouts.envelope_hash?.slice(0, 12) ?? "—"} · {layouts.method_version}</p>
        </details>
      </>
    );
  })();

  return (
    <div className="stack">
      {(ps.issues?.length ?? 0) > 0 ? (
        <div className="stack" role="alert">
          {ps.issues!.map((iss, i) => (
            <div key={i} className={`banner ${iss.kind === "catalog_gap" ? "banner-info" : "banner-warn"} issue`}>
              <strong>{iss.title}</strong>
              <p className="small">{iss.detail}</p>
              <div className="row wrap">
                {iss.actions.map((a, j) => (
                  <button key={j} className={`btn btn-small ${a.kind === "find" ? "btn-primary" : ""}`} disabled={!!busy} onClick={() => runAction(a)}>{a.label}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : ps.conflicts.length > 0 && (
        // A plan version saved before typed issues: show its own text (never rewritten), with the actions we can
        // read unambiguously from it.
        <div className="banner banner-warn" role="alert">
          <strong>Needs your attention</strong>
          <ul>{ps.conflicts.map((c, i) => <li key={i}>{c}</li>)}</ul>
          <div className="row wrap">
            {legacyActions(ps.conflicts).map((a, j) => (
              <button key={j} className={`btn btn-small ${a.kind === "find" ? "btn-primary" : ""}`} disabled={!!busy} onClick={() => runAction(a)}>{a.label}</button>
            ))}
          </div>
        </div>
      )}
      {state.plans_info && (!state.plans_info.typed_issues || state.plans_info.catalog_updated_after) && (
        <div className="banner banner-info small">
          {state.plans_info.catalog_updated_after
            ? "Our saved collection has changed since these plans were made (for example, new sizes were added). "
            : "These plans were saved by an earlier version of Furniture AI. "}
          Rebuilding makes a new plan version from your current settings; the current one stays in history.{" "}
          <button className="btn btn-small" disabled={!!busy}
            onClick={() => act("Rebuilding plans", () => api.rebuildPlans(pid), (s) => { onState(s); setMessage("Plans rebuilt as a new version; the previous version is in history."); })}>
            Rebuild plans with the current collection
          </button>
        </div>
      )}

      <div className="plan-strip">
        <div className="plan-picker" role="radiogroup" aria-label="Shopping plan">
          {ps.plans.map((p) => {
            const on = plan?.key === p.key;
            return (
              <button key={p.key} role="radio" aria-checked={on} className={`plan-pick ${on ? "plan-pick-on" : ""}`}
                onClick={() => pickPlan(p.key)}>
                <span className="pp-name">{planName(p.title)}</span>
                <span className="small">{money(p.subtotal_cents)}</span>
              </button>
            );
          })}
        </div>
        {plan && (
          <div className="budget-strip" aria-label="Budget for this room">
            <span><strong>{money(plan.subtotal_cents)}</strong> items</span>
            {plan.item_allowance_cents != null ? (
              <span className="muted">of a {money(plan.item_allowance_cents)} item allowance · {money(plan.unused_cents ?? null)} unused
                {plan.reserve_cents ? ` · ${money(plan.reserve_cents)} held for delivery/tax` : ""}</span>
            ) : (
              <span className="muted">room budget {plan.budget_cents != null ? money(plan.budget_cents) : "not set"}{plan.reserve_cents ? ` (${money(plan.reserve_cents)} held for delivery/tax)` : ""}</span>
            )}
            {(() => {
              const f = planFitPlain(plan, !!state.room && state.room.data.room.scale_status !== "unknown");
              return <span className={`fit ${FIT_CLASS[plan.fit_summary]}`} title={f.help}>{f.text}</span>;
            })()}
          </div>
        )}
      </div>
      {ps.plans.length === 0 && <p className="small">No shopping plan meets all your settings right now; see the message above.</p>}

      {plan && (
        <div className="seg view-toggle" role="tablist" aria-label="Show">
          <button role="tab" aria-selected={view === "room"} className={`seg-btn ${view === "room" ? "seg-on" : ""}`} onClick={() => setView("room")}>Your room in 2D</button>
          <button role="tab" aria-selected={view === "list"} className={`seg-btn ${view === "list" ? "seg-on" : ""}`} onClick={() => setView("list")}>
            Shopping list{list?.plan_key === plan.key && list.counts.to_buy ? ` (${list.counts.purchased}/${list.counts.to_buy})` : ""}
          </button>
        </div>
      )}

      {plan && view === "list" && (
        <div className="card">
          <h2>Shopping list: {planName(plan.title)}</h2>
          {list && list.plan_key && list.plan_key !== plan.key ? (
            // The saved list follows another plan (e.g. changed in another tab): say so instead of mixing the two.
            <div className="banner banner-info small">
              Your saved shopping list follows the <strong>{planName(list.plan_title ?? list.plan_key)}</strong> plan, not this one.{" "}
              <button className="btn btn-small btn-primary" disabled={!!busy} onClick={() => pickPlan(plan.key)}>Use this plan for my list</button>{" "}
              <button className="btn btn-small" onClick={() => setPlanKey(list.plan_key)}>Show the {planName(list.plan_title ?? "saved")} plan</button>
            </div>
          ) : (
            <ShoppingList list={list} busy={listBusy || !!busy} onMark={mark} />
          )}
        </div>
      )}

      <div className="workbench" hidden={!!plan && view === "list"}>
        <div className="card canvas-card" ref={roomRef} tabIndex={-1} aria-label="Your room in 2D">{roomCard}</div>
        {plan && (
          <div className="card" style={{ padding: "0.6rem" }}>
            <div className="row wrap" style={{ justifyContent: "space-between", padding: "0.3rem 0.4rem" }}>
              <h2 style={{ margin: 0 }}>Your furniture: {planName(plan.title)}</h2>
              {!mapped && <span className="small muted">shortlist only</span>}
            </div>
            <p className="small muted" style={{ padding: "0 0.4rem" }}>
              {plan.title.includes(":") ? plan.title.split(":")[1].trim() + "." : PLAN_BLURB[plan.key] ?? ""} {list?.plan_key === plan.key
                ? "These are the same items as your Shopping list."
                : "Your Shopping list follows a different plan; switch it from the Shopping list tab."}
            </p>
            {(plan.differences?.length ?? 0) > 0 && plan.key !== "value" && (
              <details className="small" style={{ padding: "0 0.4rem" }}>
                <summary>What changes vs Save money</summary>
                <ul>{plan.differences!.map((d, i) => <li key={i}>{d}</li>)}</ul>
              </details>
            )}
            {plan.missing_required.length > 0 && (
              <div className="small accent" style={{ padding: "0 0.4rem" }}>
                Missing (no verified option yet):{" "}
                {plan.missing_required.map((m) => (
                  <button key={m} className="link" disabled={!!busy} onClick={() => { setAltSize(null); setAltCat(m); }}>find a {label(m)}</button>
                )).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, ", ", el] : [el]), [])}
              </div>
            )}
            <ul className="products">
              {plan.items.map((it, n) => {
                const ref = refOf(it);
                const assoc = assocOf(ref);
                const on = selected === ref || (assoc?.on_ref != null && selected === assoc.on_ref);
                const unp = unplacedOf(ref);
                return (
                  <li key={n}>
                    <div className={`product ${on ? "product-on" : ""}`} role="button" tabIndex={0} aria-pressed={on}
                      onClick={() => setSelected(on ? null : ref)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(on ? null : ref); } }}>
                      {it.product_id ? <Thumb src={it.image_url} alt={`${it.retailer ?? "Retailer"} photo of ${it.name}`} /> : <div className="item-thumb item-thumb-none">owned</div>}
                      <div>
                        <div className="product-cat">{label(it.category)}{it.zones.length ? ` · ${it.zones.join(" + ")}` : ""}</div>
                        <div className="product-name">{it.name}</div>
                        <div className="product-meta">
                          {it.existing_item_id ? "You already own this" : <><strong>{money(it.price_cents)}</strong> · {inches(it.width_in)} × {inches(it.depth_in)} in{it.condition ? ` · ${it.condition}` : ""}</>}
                          {" · "}<FitBadge v={it.fit_label} checks={it.fit_checks} />
                        </div>
                        {mapped && (
                          <div className="product-meta">
                            {placedRefs.has(ref) ? "Drawn in this arrangement" : assoc ? assoc.note : unp ? `Not drawn: ${unp.reason}` : "Not drawn"}
                          </div>
                        )}
                        {it.url && (
                          <div className="product-meta">
                            <a href={it.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>{it.retailer} page ↗</a>
                            {" · checked "}{it.checked_at?.slice(0, 10)}{it.stale && <span className="stale"> · may be outdated</span>}
                          </div>
                        )}
                        {on && it.notes.length > 0 && <ul className="item-notes">{it.notes.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                        {it.product_id && (
                          <div className="product-actions">
                            <button className="btn btn-small btn-primary" disabled={!!busy}
                              onClick={(e) => { e.stopPropagation(); setSelected(ref); setAltSize(null); setAltCat(it.category); }}>Compare options</button>
                            {on && (
                              <button className="btn btn-small" disabled={!!busy || prefs?.pinned_product_ids[it.category] === it.product_id}
                                onClick={(e) => { e.stopPropagation(); keep(it); }}>
                                {prefs?.pinned_product_ids[it.category] === it.product_id ? "Kept in future plans ✓" : "Keep in future plans"}
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
            <details style={{ padding: "0.4rem" }}>
              <summary>Why this plan?</summary>
              <ul className="small explain">{plan.explanation.map((e, i) => <li key={i}>{e}</li>)}</ul>
            </details>
          </div>
        )}
      </div>

      {ps.plans.length === 0 && (
        <div className="card">
          <h2>Search for furniture anyway</h2>
          <p className="small muted">No plan fits your settings yet (for example, secondhand only with nothing imported). You can still search
            public stores and listing sites, then import what you find.</p>
          <div className="row wrap">
            <select value={searchCat} onChange={(e) => setSearchCat(e.target.value)} aria-label="What to search for">
              {(prefs?.categories.length ? prefs.categories : ["bed_frame", "desk", "dresser", "sofa_bed"]).map((c) => <option key={c} value={c}>{label(c)}</option>)}
            </select>
            <button className="btn btn-small" disabled={!!busy || !searchCat} onClick={() => setAltCat(searchCat)}>Search</button>
          </div>
        </div>
      )}

      {altCat && (plan || ps.plans.length === 0) && (
        <AlternativesPanel state={state} plan={plan ?? null} category={altCat} size={altSize} onClose={() => setAltCat(null)} onState={onState} onSwapped={onSwapped}
          busy={!!busy} setBusy={props.setBusy} setMessage={setMessage} desiredTiming={desiredTiming}
          missing={!plan || !plan.items.some((i) => i.product_id && i.category === altCat)} />
      )}

      <EditBox {...props} />

      {(ps.notes.length > 0 || ps.changes.length > 0) && (
        <details className="card">
          <summary>Plan notes{ps.changes.length ? ` and changes since the previous version (${ps.changes.length})` : ""}</summary>
          {ps.notes.map((n, i) => <p key={i} className="note small">{n}</p>)}
          {ps.changes.length > 0 && <ul className="small">{ps.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>}
        </details>
      )}
      {mapped && layouts?.width_range_in && layouts?.depth_range_in && (
        <p className="small muted">
          Wall A {ft(layouts.width_range_in[0])}–{ft(layouts.width_range_in[1])} · wall B {ft(layouts.depth_range_in[0])}–{ft(layouts.depth_range_in[1])}
          {layouts.basis === "estimated_from_photos" ? " (estimated from photos, unverified)" : ""}. Drawn at the smaller size.{" "}
          <button className="link" onClick={() => goto("evidence")}>Review in Your room</button>
        </p>
      )}
    </div>
  );
}
