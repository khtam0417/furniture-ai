import { useRef, useState } from "react";
import { api } from "../api";
import type { PanelProps } from "../Workspace";
import { CATEGORIES, label, money, sourceLabel, type Discovery } from "../types";
import PlanGallery from "./PlanGallery";

export type SourceSection = "gallery" | "sources" | "listing";

export default function PhotosPanel({
  state, status, onState, act, busy, setMessage, goto, sections = ["gallery", "sources", "listing"], discovery = null, discoveryNote,
  onFindBuilding, onAnalyzed, onDiscovery,
}: PanelProps & {
  sections?: SourceSection[];
  discovery?: Discovery | null;  // the saved building discovery shared by this place's rooms
  discoveryNote?: string | null;
  onDiscovery?: (d: Discovery) => void;  // a newer discovery version (e.g. after reading a listing page you chose)
  onFindBuilding?: () => void;
  onAnalyzed?: (drawable: boolean) => void;  // guided flow: stay in the room step and show the review
}) {
  const p = state.project;
  const photos = state.sources.filter((s) => s.kind === "photo");
  const plans = state.sources.filter((s) => s.kind === "floorplan" || s.kind === "floorplan_pdf");
  const [note, setNote] = useState("");
  const [listUrl, setListUrl] = useState("");
  const [listCat, setListCat] = useState<string>("desk");
  const [listCond, setListCond] = useState("");  // explicit choice; never assumed secondhand
  const [uploadReport, setUploadReport] = useState<string[]>([]);
  const [importFailed, setImportFailed] = useState(false);
  const [recoveredPlanId, setRecoveredPlanId] = useState<string | null>(null);
  const nextRef = useRef<HTMLDivElement>(null);

  // Image floor plans (with a derivative) can be analyzed; stored-only PDFs cannot.
  const imagePlans = state.sources.filter((s) => s.kind === "floorplan" && s.derivative);
  const isReadyPlan = (sources: typeof state.sources, id: string | undefined) =>
    !!id && sources.some((s) => s.id === id && s.kind === "floorplan" && s.derivative);
  // ONE floor plan is read at a time (never combined): the plan the current room version read, else the newest.
  const analyzedIds: string[] = (() => {
    const raw = state.room?.source_ids;
    if (Array.isArray(raw)) return raw;
    try { return raw ? (JSON.parse(raw) as string[]) : []; } catch { return []; }
  })();
  const [chosenPlan, setChosenPlan] = useState<string | null>(null);
  const activePlan = (chosenPlan && imagePlans.some((s) => s.id === chosenPlan) ? chosenPlan : null)
    ?? imagePlans.find((s) => analyzedIds.includes(s.id))?.id ?? imagePlans[imagePlans.length - 1]?.id ?? null;

  const doUpload = (files: FileList | null, kind: "photo" | "floorplan") => {
    if (!files || files.length === 0) return;
    act("Uploading", () => api.upload(p.id, Array.from(files), kind), (r) => {
      onState(r.state);
      setUploadReport([
        ...r.results.map((x) => (x.ok ? `${x.filename}: added${x.duplicate ? " (already added)" : ""}${x.warning ? ` — ${x.warning}` : ""}` : `${x.filename}: ${x.error}`)),
        ...(r.notice ? [r.notice] : []),
      ]);
      // Any successful IMAGE floor-plan upload (from any button) makes the plan ready; checked against real sources.
      const ready = r.results.filter((x) => x.ok).map((x) => x.id).find((id) => isReadyPlan(r.state.sources, id));
      if (ready) {
        setRecoveredPlanId(ready);
        setChosenPlan(ready);
        setImportFailed(false);
      }
    });
  };

  const canAnalyze = !p.is_demo && status?.live_ai_available && (photos.length > 0 || imagePlans.length > 0);
  const planOnly = photos.length === 0 && imagePlans.length > 0;

  const runAnalyze = (planId: string | null = activePlan) =>
    act(planOnly ? "Reading your floor plan" : plans.length ? "Looking at your photos and floor plan" : "Looking at your photos",
      () => api.analyze(p.id, note, planId), (r) => {
        onState(r.state);
        setRecoveredPlanId(null);
        const g = r.state.room?.data.room.inferred_geometry;
        const readings = r.state.room?.data.plan_dimension_suggestions?.length ?? 0;
        const planNote = readings ? ` ${readings} printed room size${readings === 1 ? "" : "s"} read from your floor plan: pick the one that is this room under “Review what we read” to draw it (an estimate; no measuring).` : "";
        const confirmed = r.state.room?.data.room.scale_status && r.state.room.data.room.scale_status !== "unknown";
        setMessage(r.reused ? "These sources were already analyzed; reused the saved result (no new AI call)."
          : g?.drawable ? `Room drawn from your photos (estimated from photos). See it in Furnish & compare.${planNote}`
          : confirmed ? `Your room stays drawn at its known size; these photos didn’t add a photo outline.${planNote}`
          : r.state.room?.data.room.plan_estimate ? `Your room stays drawn from the floor-plan size you picked (an estimate).${planNote}`
          : g?.observed_only ? `Walls and features were seen, but the room’s size couldn’t be estimated reliably: ${g.reason} You’ll see what was observed (not to scale); furniture is placed once there’s a size from a floor plan or one you know.${planNote}`
          : planOnly ? (readings ? `Floor plan read:${planNote}`
            : "Floor plan analyzed, but no printed room sizes could be read (marketing and 3D plan images often show none), so this room "
              + "stays unmapped and no size was assumed. To map it, add at least 2 room photos from opposite corners, or a plan image with printed dimensions.")
          : `Photos analyzed, but the room could not be mapped yet. See which photos would help.${planNote}`);
        if (onAnalyzed) onAnalyzed(!!g?.drawable);
        else goto(g?.drawable ? "plans" : "evidence");
      });

  const importPlan = (url: string) =>
    act("Adding plan", async () => {
      try {
        return await api.propertyPlanImage(p.id, url, discovery?.id);  // the real image bytes, into THIS room only
      } catch (e) {
        setImportFailed(true);
        throw e;
      }
    }, (r) => {
      onState(r.state);
      setImportFailed(false);
      const ready = isReadyPlan(r.state.sources, r.source?.id);
      setRecoveredPlanId(ready ? r.source.id : null);
      if (ready) setChosenPlan(r.source.id);
      setMessage("Floor plan added to this room only. Next: “Analyze floor plan” reads its printed room sizes; then pick the one that is this room.");
      // Bring the next step (above the gallery) into view so nobody has to scroll back past every plan.
      if (ready) setTimeout(() => { nextRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); nextRef.current?.focus({ preventScroll: true }); }, 50);
    });

  // The plan to offer next: the one just added in this visit. Never a stored-only PDF.
  const justAdded = recoveredPlanId ? imagePlans.find((s) => s.id === recoveredPlanId) ?? null : null;
  const importedUrls = new Set(state.sources.flatMap((s) => [s.source_url, s.provenance?.requested_url].filter((u): u is string => !!u)));
  const uploadPlan = (
    <label className="btn btn-primary file-btn">
      Upload my floor plan
      <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => { doUpload(e.target.files, "floorplan"); e.target.value = ""; }} />
    </label>
  );

  return (
    <div className="stack">
      {sections.includes("gallery") && !p.is_demo && (
        <>
          {/* Next step sits ABOVE the gallery (it can hold ~20 plans), and is scrolled into view after an import. */}
          {justAdded && (
            <div className="recovery recovery-ok" role="status" ref={nextRef} tabIndex={-1}>
              <p className="eyebrow">Next step</p>
              <div className="row wrap" style={{ alignItems: "flex-start" }}>
                <img className="recovery-preview" src={`/api/projects/${p.id}/sources/${justAdded.id}/preview`} alt={sourceLabel(justAdded)} />
                <div className="stack" style={{ gap: "0.4rem" }}>
                  <p>
                    <strong>{sourceLabel(justAdded)} is saved to this room.</strong> Read its printed room sizes next. You then choose
                    which printed size is this room, and it’s drawn as an estimate. No measuring needed.
                  </p>
                  <div className="row wrap">
                    <button className="btn btn-primary" disabled={!canAnalyze || !!busy} onClick={() => runAnalyze(justAdded.id)}>Analyze floor plan</button>
                  </div>
                  {!status?.live_ai_available && <p className="muted small">AI is not connected right now, so the plan can’t be read yet; it stays saved.</p>}
                  <p className="small muted">Wrong plan? Pick another below or upload your own; this one stays saved as a source.</p>
                </div>
              </div>
            </div>
          )}
          <PlanGallery discovery={discovery} note={discoveryNote} busy={!!busy} importedUrls={importedUrls} onUse={importPlan}
            onTryAlternative={onDiscovery && discovery?.id ? (url) => act("Reading the listing page", () => api.discoveryAlternative(p.id, discovery.id!, url),
              (r) => { onDiscovery(r.discovery); setMessage((r.discovery.gallery?.length ?? 0) > (discovery.gallery?.length ?? 0)
                ? "Plans found on the listing page (a third-party site). Pick yours below." : "That listing page gave no plans we could use."); }) : undefined}
            onFindBuilding={onFindBuilding ?? (() => goto("photos"))} uploadSlot={uploadPlan} />
          {importFailed && !justAdded && (
            <div className="recovery" role="alert">
              <p className="small">That plan image couldn’t be imported. Save it from the website and upload your copy instead.</p>
              {uploadPlan}
            </div>
          )}
        </>
      )}

      {sections.includes("sources") && <div className="card">
        <h2>Your own photos or floor plan</h2>
        <p className="muted">
          Photos may give an estimated room outline (kept fixed; only furniture moves) when they show enough. Add at least 2 overlapping photos
          from opposite corners, so three or more walls, two corners and the floor edges show. Keep the door and a bed, desk or
          appliance fully in frame: they are rough size cues. No measuring needed.
        </p>
        {p.is_demo ? (
          <p className="accent small">This demo already contains synthetic images. Start a new project to use your own photos.</p>
        ) : (
          <div className="row wrap">
            <label className="btn btn-primary file-btn">
              Add photos
              <input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(e) => { doUpload(e.target.files, "photo"); e.target.value = ""; }} />
            </label>
            <label className="btn file-btn">
              Add a floor plan (optional)
              <input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" onChange={(e) => { doUpload(e.target.files, "floorplan"); e.target.value = ""; }} />
            </label>
          </div>
        )}
        <p className="muted small">JPEG, PNG or WebP up to 15 MB. iPhone HEIC photos: choose “Most Compatible” in camera settings or share as JPEG.</p>
        {uploadReport.length > 0 && (
          <ul className="small report">{uploadReport.map((r, i) => <li key={i}>{r}</li>)}</ul>
        )}
        <div className="thumbs">
          {[...photos, ...plans].map((s) => (
            <figure key={s.id} className="thumb">
              {s.derivative ? (
                <img src={`/api/projects/${p.id}/sources/${s.id}/preview`} alt={sourceLabel(s)} loading="lazy" />
              ) : (
                <div className="thumb-pdf">PDF</div>
              )}
              <figcaption className="small">
                {s.kind === "photo" ? "Photo" : "Floor plan"}{s.is_synthetic ? " · synthetic" : ""}
                <br /><span className="muted">{sourceLabel(s).replace(/^(Room photo|Floor plan)(: | from )?/, "")}</span>
              </figcaption>
            </figure>
          ))}
        </div>
        {!p.is_demo && (
          <div className="analyze">
            <label className="field">
              <span>Anything we should know? (optional)</span>
              <input value={note} maxLength={300} placeholder="e.g. the radiator is under the window" onChange={(e) => setNote(e.target.value)} />
            </label>
            {imagePlans.length > 1 && (
              <fieldset className="scope">
                <legend className="small">Floor plan to read (one at a time; plans are never combined)</legend>
                <div className="plan-choice">
                  {imagePlans.map((s) => (
                    <label key={s.id} className={`plan-choice-item ${activePlan === s.id ? "reading-on" : ""}`}>
                      <input type="radio" name={`plan-${p.id}`} checked={activePlan === s.id} onChange={() => setChosenPlan(s.id)} />
                      <img src={`/api/projects/${p.id}/sources/${s.id}/preview`} alt={sourceLabel(s)} />
                      <span className="small">{sourceLabel(s)}{analyzedIds.includes(s.id) ? " · read" : ""}</span>
                    </label>
                  ))}
                </div>
                <p className="small muted">Switching plans re-reads that plan; a size picked from another plan isn’t carried over.</p>
              </fieldset>
            )}
            <button className="btn btn-primary" disabled={!canAnalyze || !!busy} onClick={() => runAnalyze()}>
              {planOnly ? "Analyze floor plan"
                : state.room && !state.room.data.room.inferred_geometry ? "Re-analyze photos to map this room" : "Analyze photos and map the room"}
            </button>
            {!status?.live_ai_available && <p className="muted small">AI is not connected, so photo analysis is unavailable. Plans still work without it.</p>}
          </div>
        )}
      </div>}

      {sections.includes("listing") && <div className="card">
        <h2>Add a specific listing (optional)</h2>
        <p className="muted">
          Paste a public product or secondhand listing. We keep the page as evidence and use only the price and size printed on it.
          If either is missing, the item is shown but never placed in a plan.
        </p>
        <form className="row wrap" onSubmit={(e) => { e.preventDefault(); act("Importing listing", () => api.listing(p.id, listUrl, listCat, listCond), (r) => { onState(r.state); setMessage(r.warning ?? (r.snapshot.status === "verified" ? "Listing added; it can now appear in plans." : `Listing saved but incomplete (missing ${r.snapshot.missing.join(", ")}); it will not be recommended.`)); }); }}>
          <input className="grow" type="url" required placeholder="https://…" value={listUrl} onChange={(e) => setListUrl(e.target.value)} aria-label="Listing URL" />
          <select value={listCat} onChange={(e) => setListCat(e.target.value)} aria-label="Listing category">
            {CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
          <select value={listCond} required onChange={(e) => setListCond(e.target.value)} aria-label="Item condition (your declaration)">
            <option value="">Condition…</option>
            <option value="new">New</option>
            <option value="secondhand">Used / secondhand</option>
          </select>
          <button className="btn" disabled={!!busy || !listCond} title={!listCond ? "Choose new or used first" : undefined}>Import</button>
        </form>
        {state.imported_listings.length > 0 && (
          <ul className="small list">
            {state.imported_listings.map((s) => (
              <li key={s.id + s.checked_at} className="list-row">
                <a href={s.url} target="_blank" rel="noopener noreferrer">{s.name ?? s.url}</a>
                <span className="muted">
                  {label(s.category)} · {money(s.price_cents)} · {s.condition}{s.condition_verified === false ? " (your declaration)" : ""} ·{" "}
                  {s.status === "verified" ? "usable in plans" : `incomplete: ${s.missing.join(", ")}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>}
    </div>
  );
}
