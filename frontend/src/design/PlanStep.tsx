import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import PlaceStep from "../PlaceStep";
import PlanGallery from "../panels/PlanGallery";
import type { ApartmentState, Discovery, ProjectState } from "../types";
import type { DesignCtx } from "./DesignFlow";
import PlanCanvas from "./PlanCanvas";

/** Step 1, in reading order: place details and building search -> its public plans or your upload -> the selected
 *  plan's review -> one primary action at the bottom ("Read floor plan & continue"). Once a plan is chosen, the
 *  finder collapses into "Change floor plan" so no long gallery sits below the action. */
export default function PlanStep({ ctx, apt, anchor, place, onApartment, onAnchorState }: {
  ctx: DesignCtx;
  apt: ApartmentState;
  anchor: ProjectState | null;
  place: ReactNode;
  onApartment: (a: ApartmentState) => void;
  onAnchorState: (s: ProjectState) => void;
}) {
  const { aid, ds, setDs, act, busy, setMessage, go, status } = ctx;
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [discoveryNote, setDiscoveryNote] = useState<string | null>(null);
  const [localBusy, setLocalBusy] = useState<string | null>(null);
  const anchorId = anchor?.project.id ?? ds.anchor_project_id;
  const buildingKey = apt.context.building?.key ?? null;
  useEffect(() => {
    if (!anchorId) return;
    let live = true;
    api.placeDiscovery(anchorId).then((r) => { if (live) { setDiscovery(r.discovery); setDiscoveryNote(r.note); } }).catch(() => undefined);
    return () => { live = false; };
  }, [anchorId, buildingKey]);

  const v = ds.design?.version ?? 0;
  const selected = ds.selected_source;
  const suggested = ds.plan_sources.find((s) => s.id === ds.suggested_source_id) ?? null;
  const live = !!status?.live_ai_available;
  const importedUrls = new Set((anchor?.sources ?? []).flatMap((s) => [s.source_url, s.provenance?.requested_url].filter((u): u is string => !!u)));

  const use = (sourceId: string) => act("Opening this plan", () => api.designSelectPlan(aid, sourceId, v), (s) => {
    setDs(s);
    setMessage(s.plan_map ? "Plan selected; it was already read, so your furniture is shown on it." : "Plan selected. Next: “Read floor plan” maps its rooms.");
  });
  const read = (andContinue = false) => act("Reading rooms and walls from your plan", () => api.designRead(aid, v), (s) => {
    setDs(s);
    const m = s.plan_map?.data;
    setMessage(s.reused ? "This plan was already read; the saved reading was reused (no new AI call)."
      : m?.status === "mapped" ? `Read ${m.rooms.length} area${m.rooms.length === 1 ? "" : "s"} from your plan. A clean plan is drawn from this reading (approximate); the original is one click away.`
      : "No room outlines could be read from this image, so the original is shown and your pieces wait in “Not placed”. Re-read it or choose another plan image.");
    if (andContinue && m?.status === "mapped") go("arrange");  // an unreadable plan stays here, where it can be fixed
  });
  const reviewRef = useRef<HTMLDivElement>(null);
  const [changeOpen, setChangeOpen] = useState(false);
  const lastSel = useRef<string | null | undefined>(undefined);
  useEffect(() => {  // a newly selected/imported/uploaded plan: bring its review and action into view
    const id = ds.selected_source?.id ?? null;
    if (lastSel.current !== undefined && id && id !== lastSel.current) {
      setChangeOpen(false);
      setTimeout(() => reviewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }
    lastSel.current = id;
  }, [ds.selected_source?.id]);
  const importPlan = (url: string) => {
    if (!anchorId) return;
    act("Adding this plan", async () => {
      const r = await api.propertyPlanImage(anchorId, url, discovery?.id);
      onAnchorState(r.state);
      return api.designSelectPlan(aid, r.source.id, v);
    }, (s) => { setDs(s); setMessage("Plan added and selected. Next: “Read floor plan” maps its rooms."); });
  };
  const upload = (files: FileList | null) => {
    if (!files?.length || !anchorId) return;
    act("Uploading your plan", async () => {
      const r = await api.upload(anchorId, Array.from(files), "floorplan");
      onAnchorState(r.state);
      const bad = r.results.find((x) => !x.ok);
      const id = r.results.find((x) => x.ok)?.id;
      if (!id || !r.state.sources.some((s) => s.id === id && s.kind === "floorplan" && s.derivative)) {
        throw new Error(bad ? `${bad.filename}: ${bad.error}` : "That file couldn’t be used as a plan image. Try a JPEG, PNG or WebP image.");
      }
      return api.designSelectPlan(aid, id, v);
    }, (s) => { setDs(s); setMessage("Plan uploaded and selected. Next: “Read floor plan” maps its rooms."); });
  };
  const uploadBtn = (
    <label className="btn file-btn">
      Upload my own plan
      <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
    </label>
  );

  const map = ds.plan_map?.data ?? null;
  const reading = busy?.startsWith("Reading") ? "Reading rooms and walls from your plan…" : null;
  const finder = (
    <>
      {anchor && (
        <div id="find-building">
          <PlaceStep state={anchor} status={status} onState={onAnchorState} busy={busy ?? localBusy} setBusy={setLocalBusy} setMessage={setMessage}
            act={async (label, fn, ok) => act(label, fn, ok)} goto={() => undefined} context={apt.context} onApartment={onApartment} wholePlace
            building={apt.context.building ?? discovery?.building ?? null}
            onSelected={(d) => { setDiscovery(d); setDiscoveryNote(null); }} />
        </div>
      )}
      {ds.plan_sources.length > 0 && (
        <div className="card">
          <h2>Your floor plans</h2>
          <p className="small muted">One plan is used for the whole place. Switching keeps each plan’s own arrangement; nothing is drawn from one plan onto another.</p>
          <ul className="plan-grid">
            {ds.plan_sources.map((s) => (
              <li key={s.id} className={`plan-card ${selected?.id === s.id ? "plan-pick-on" : ""}`}>
                <span className="plan-img"><img src={s.preview} alt={s.name} loading="lazy" /></span>
                <div className="plan-body">
                  <strong className="plan-name">{s.name}</strong>
                  <span className="small muted">{s.read ? "Read" : "Not read yet"}{s.is_synthetic ? " · synthetic" : ""}</span>
                  {selected?.id === s.id ? <span className="fit fit-ok small">In use ✓</span>
                    : <button className="btn btn-small btn-primary" disabled={!!busy} onClick={() => use(s.id)}>Use this plan</button>}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      <PlanGallery discovery={discovery} note={discoveryNote} busy={!!busy} importedUrls={importedUrls} onUse={importPlan}
        onTryAlternative={(url) => anchorId && discovery?.id && act("Reading the listing page", () => api.discoveryAlternative(anchorId, discovery.id!, url),
          (r) => { setDiscovery(r.discovery); const n = (r.discovery.gallery?.length ?? 0) - (discovery.gallery?.length ?? 0);
            setMessage(n > 0 ? `Found ${n} plan${n === 1 ? "" : "s"} on the listing page (a third-party site).` : "That listing page gave no plans we could use."); })}
        onFindBuilding={() => document.getElementById("find-building")?.scrollIntoView({ behavior: "smooth" })} uploadSlot={uploadBtn} usedLabel="Added ✓" wholePlace />
      <div className="card">
        <h2>Have your plan as an image?</h2>
        <p className="small muted">A screenshot or saved image of your unit’s floor plan works (JPEG, PNG or WebP). No measuring needed.</p>
        {uploadBtn}
      </div>
    </>
  );
  return (
    <div className="stack">
      {place}
      {selected ? (
        <details className="card change-plan" open={changeOpen} onToggle={(e) => setChangeOpen((e.target as HTMLDetailsElement).open)}>
          <summary><strong>Change floor plan</strong> <span className="small muted">(building search, public plans, upload)</span></summary>
          <div className="stack mt">{finder}</div>
        </details>
      ) : finder}

      <div ref={reviewRef} className="stack">
        {selected ? (
          <div className="card">
            <p className="eyebrow">The plan for your whole place</p>
            <h2 style={{ margin: 0 }}>{selected.name}</h2>
            <p className="small muted">{selected.building ? `${selected.building} · ` : ""}{selected.caveat ?? "Your plan image."}{selected.is_synthetic ? " Synthetic sample image." : ""}</p>
            <PlanCanvas roomUses={ds.room_uses} imageUrl={selected.preview} imageW={selected.width} imageH={selected.height} map={map}
              items={ds.design?.data.items ?? []} products={ds.products} overlay={reading}
              caption={map ? (map.status === "mapped" ? map.scale.note : "Not mapped: the original image is shown.") : "Your plan as published. Read it to map its rooms."} />
            {map && <MapSummary ctx={ctx} />}
            {map && Object.values(ds.room_uses ?? {}).some((u) => u.status !== "confirmed") && (
              <p className="small banner banner-warn">Some areas are unsure or look misread. In Arrange your space you can set each
                room’s use under “Rooms on your plan”; unsure areas get no furniture automatically.</p>
            )}
            {map && ds.map_outdated && (
              <p className="small reread-note">Read with an older reader.{" "}
                <button className="link" disabled={!!busy || !live} onClick={() => read()}>Re-read plan</button> (one AI call; pieces and products kept)</p>
            )}
            {map && map.status !== "mapped" && (
              <div className="row wrap">
                <button className="btn btn-small" disabled={!!busy || !live} onClick={() => read()}>Try reading again</button>
                <button className="btn btn-small" disabled={!!busy} onClick={() => setChangeOpen(true)}>Choose another plan image</button>
              </div>
            )}
          </div>
        ) : suggested ? (
          <div className="card">
            <p className="eyebrow">Your floor plan</p>
            <h2>{suggested.name}</h2>
            <p className="small muted">You added this plan earlier. Use it for your whole place (you can switch later).</p>
            <img className="plan-hero" src={suggested.preview} alt={suggested.name} />
            <div className="row wrap"><button className="btn btn-primary" disabled={!!busy} onClick={() => use(suggested.id)}>Use this plan</button></div>
          </div>
        ) : null}
        {selected && !map && (
          <div className="plan-action">
            <button className="btn btn-primary" disabled={!!busy || !live} onClick={() => read(true)}>Read floor plan &amp; continue →</button>
            <span className="small muted">{live ? "One AI reading of this image finds its rooms, walls, doors, kitchen and bath, then opens Arrange your space. No measuring." : "AI is not connected right now, so the plan can’t be read yet. It stays saved."}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function MapSummary({ ctx }: { ctx: DesignCtx }) {
  const m = ctx.ds.plan_map!.data;
  const furn = m.rooms.filter((r) => r.furnishable);
  const fixed = m.rooms.filter((r) => !r.furnishable);
  return (
    <div className="stack" style={{ gap: "0.3rem" }}>
      {m.status === "mapped" ? (
        <p className="small">
          <strong>Rooms to furnish:</strong> {furn.map((r) => r.label || r.kind).join(", ")}.
          {fixed.length > 0 && <> <strong>Kept clear:</strong> {fixed.map((r) => r.label || r.kind).join(", ")}{m.fixtures.length ? " and fixtures" : ""}.</>}
          {" "}Read from your plan image by AI. A clean plan drawn from this reading is shown when the reading is usable (approximate); tick “Show original floor plan” to compare.
        </p>
      ) : (
        <p className="small">No room outlines could be read, so the original image is shown and nothing is placed on it: your pieces wait in “Not placed”. Re-read the plan or choose another plan image.</p>
      )}
      <details className="small">
        <summary>What was read and its limits</summary>
        <ul className="small">
          <li>{m.scale.note}</li>
          {m.rooms.map((r) => <li key={r.id}>{r.label || r.kind} ({r.kind}{r.furnishable ? "" : ", kept clear"}): {r.dimension_text ? `printed ${r.dimension_text}. ${r.scale_note}` : "no printed size."} Outline confidence (model-reported): {r.confidence}.</li>)}
          {m.limitations.map((l, i) => <li key={`l${i}`}>{l}</li>)}
          {m.rejected.map((l, i) => <li key={`r${i}`}>{l}</li>)}
          <li>Doors: {m.openings.filter((o) => o.kind !== "window").length} identified; door swings and walkways are approximate.</li>
          <li>Method {m.method}, model {m.model ?? "unknown"}, read {ctx.ds.plan_map!.created_at.slice(0, 16).replace("T", " ")} UTC. The original image is unchanged.</li>
          {m.untrusted_text_seen.length > 0 && <li>Text seen in the image (not followed): {m.untrusted_text_seen.join(" · ")}</li>}
        </ul>
      </details>
    </div>
  );
}
