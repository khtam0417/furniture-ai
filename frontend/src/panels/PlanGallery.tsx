import { useEffect, useMemo, useState } from "react";
import type { Discovery, GalleryItem } from "../types";
import { failureText, foundSummary, originText, pageStatusText } from "./galleryText";

const FILTERS: [string, string][] = [["all", "All"], ["studio", "Studio"], ["1", "1 bed"], ["2", "2 bed"], ["3", "3+ bed"]];

function Card({ g, added, busy, onUse, usedLabel }: { g: GalleryItem; added: boolean; busy: boolean; onUse: () => void; usedLabel?: string }) {
  const [broken, setBroken] = useState(false);
  return (
    <li className="plan-card">
      <a className="plan-img" href={g.url} target="_blank" rel="noopener noreferrer" title="Open the full plan image">
        {broken ? <span className="small muted">Preview unavailable; open the image to check it</span>
          : <img src={g.url} alt={g.alt || g.name} loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />}
      </a>
      <div className="plan-body">
        <strong className="plan-name">{g.name}</strong>
        <span className="small muted">{originText(g)}</span>
        {g.label && g.origin !== "checked_reference" && <span className="small muted">{g.label}</span>}
        {added ? <span className="fit fit-ok small">{usedLabel ?? "Added to this room ✓"}</span>
          : <button className="btn btn-primary btn-small" disabled={busy} onClick={onUse}>Use this plan</button>}
      </div>
    </li>
  );
}

/** Public plan choices for the chosen building. Filters are labels from plan names, never sizes; nothing is pre-selected. */
export default function PlanGallery({ discovery, note, busy, importedUrls, onUse, onFindBuilding, uploadSlot, usedLabel, wholePlace, onTryAlternative }: {
  usedLabel?: string;
  onTryAlternative?: (url: string) => void;  // read ONE offered listing-site page (explicit choice)
  wholePlace?: boolean;  // design-first flow: one plan for the whole place
  discovery: Discovery | null;
  note?: string | null;
  busy: boolean;
  importedUrls: Set<string>;
  onUse: (url: string) => void;
  onFindBuilding: () => void;
  uploadSlot: React.ReactNode;  // "upload my own plan" control, shown when nothing usable was found
}) {
  const [filter, setFilter] = useState("all");
  // A new building or a new lookup starts on "All", so an old filter can't hide the new plans.
  useEffect(() => { setFilter("all"); }, [discovery?.id, discovery?.building?.key]);
  const items = useMemo(() => discovery?.gallery ?? [], [discovery]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map(([k]) => [k, k === "all" ? items.length : items.filter((g) => g.plan_type === k).length])), [items]);
  const shown = filter === "all" ? items : items.filter((g) => g.plan_type === filter);

  if (!discovery?.building) {
    return (
      <div className="card">
        <h2>Floor plans for your building</h2>
        <p className="muted">{note ?? "No building chosen yet."} Find your building {wholePlace ? "above" : "in “Your place”"} to see its public floor plans here, or upload your own plan.</p>
        <button className="btn btn-small" onClick={onFindBuilding}>Find my building</button>
      </div>
    );
  }
  const b = discovery.building;
  const hasChecked = items.some((g) => g.origin === "checked_reference");
  const found = foundSummary(discovery);
  const alternatives = (discovery.alternatives ?? []).filter((a) => !a.tried);
  return (
    <div className="card">
      <h2>Floor plans for {b.name}</h2>
      <p className="small muted">
        {b.address ?? "Street address unknown"}{b.site ? ` · ${b.site}` : ""}. Building plans are samples: pick one only if it is your
        layout. {wholePlace ? "It’s read into a map of your whole place; your unit may differ."
          : "After reading it, pick this room’s printed size in “Review what we read”; it’s drawn as an estimate (your unit may differ)."}
      </p>
      {found && (
        <div className="small note" role="status">
          <strong>{found.headline}.</strong>{found.detail.map((t, i) => <span key={i}> {t}</span>)}
        </div>
      )}
      {hasChecked && (
        <p className="small muted">
          These are the building’s published plan types, not every unit variant. The images may contain the property’s
          marketing or availability text; this is not verified current availability.
        </p>
      )}
      {items.length > 0 ? (
        <>
          <div className="seg plan-filters" role="group" aria-label="Filter plans by type">
            {FILTERS.map(([k, label]) => (
              <button key={k} type="button" className={`seg-btn ${filter === k ? "seg-on" : ""}`} aria-pressed={filter === k}
                disabled={k !== "all" && counts[k] === 0} onClick={() => setFilter(k)}>{label} ({counts[k]})</button>
            ))}
          </div>
          {shown.length === 0 ? (
            <p className="small">No plans of this type here. <button className="link" onClick={() => setFilter("all")}>Show all {items.length} plans</button></p>
          ) : (
            <ul className="plan-grid">
              {shown.map((g) => <Card key={g.url} g={g} added={importedUrls.has(g.url)} busy={busy} onUse={() => onUse(g.url)} usedLabel={usedLabel} />)}
            </ul>
          )}
          {filter === "all" && items.some((g) => !g.plan_type) && <p className="small muted">Some plans don’t say their type, so they appear only under All.</p>}
        </>
      ) : (
        <div className="recovery">
          <h3 style={{ marginTop: 0 }}>No public plans could be read automatically</h3>
          <p className="small">
            {failureText(discovery)}{" "}
            Save or screenshot your plan from the website and upload it here. Not every website can be read.
          </p>
          {onTryAlternative && alternatives.length > 0 && (
            <div className="stack" style={{ gap: "0.3rem" }}>
              <p className="small">Your web search also found a listing page for this building. It’s a third-party site, not the building’s own website; read it only if you want to:</p>
              {alternatives.map((a) => (
                <div key={a.url} className="row wrap">
                  <button className="btn btn-small" disabled={busy} onClick={() => onTryAlternative(a.url)}>Read plans from {a.site}</button>
                  <a className="small" href={a.url} target="_blank" rel="noopener noreferrer">{a.title} ↗</a>
                </div>
              ))}
            </div>
          )}
          <div className="row wrap">
            {uploadSlot}
            {discovery.website && <a className="btn" href={discovery.website} target="_blank" rel="noopener noreferrer">Open the website ↗</a>}
          </div>
        </div>
      )}
      {(discovery.plan_pdfs?.length ?? 0) > 0 && (
        <p className="small">
          PDF plans found (not read automatically; open, screenshot and upload):{" "}
          {discovery.plan_pdfs.map((u, i) => <span key={u}>{i ? " · " : ""}<a href={u} target="_blank" rel="noopener noreferrer">Open plan PDF {i + 1} ↗</a></span>)}
        </p>
      )}
      <details className="small mt">
        <summary>What we read ({discovery.pages.length} page{discovery.pages.length === 1 ? "" : "s"}{discovery.recovery?.length ? `, ${discovery.recovery.length} alternative${discovery.recovery.length === 1 ? "" : "s"} tried` : ""})</summary>
        <ul className="small">
          {discovery.pages.map((pg, i) => (
            <li key={pg.url + i}>
              <span className={`dot ${pg.status === "ok" ? "dot-ok" : "dot-bad"}`} aria-hidden /> {pg.url} —{" "}
              {pageStatusText(pg)}
              {pg.via === "recovery" ? " (alternative from your web search)" : pg.via === "linked" ? " (linked page)"
                : pg.via === "reader" ? " (public page reader)" : pg.via === "third_party" ? " (listing page you chose)" : ""}
            </li>
          ))}
          {(discovery.recovery ?? []).filter((r) => r.kind === "image").map((r) => (
            <li key={r.url}><span className={`dot ${r.status === "ok" ? "dot-ok" : "dot-bad"}`} aria-hidden /> {r.url} — {r.why}: {r.status === "ok" ? "fetched, it is an image" : r.detail || r.status}</li>
          ))}
        </ul>
        {discovery.notes.map((n, i) => <p key={i} className="muted small">{n}</p>)}
        {discovery.pages.some((pg) => pg.via === "reader" || pg.via === "third_party") && (
          <p className="muted small">
            Public page reader: when a site refuses automated reading, only its public page address (never your unit, photos,
            cookies or sign-in pages) is sent to Jina Reader (r.jina.ai), an outside service that returns the page as text. Its
            reply is saved as evidence; plan images are then fetched from their own addresses. Whether its copy is current is unknown.
          </p>
        )}
        {discovery.created_at && <p className="muted small">Looked up {discovery.created_at.slice(0, 16).replace("T", " ")} UTC and saved for every room of this place.</p>}
      </details>
    </div>
  );
}
