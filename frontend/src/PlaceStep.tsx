import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { api } from "./api";
import type { PanelProps } from "./Workspace";
import type { ApartmentState, BuildingCandidate, BuildingFind, Discovery, PlaceContext } from "./types";

/** A search result that doesn't identify a building (listing/directory site, bare site name, or a page that doesn't
 *  name it): something to look at, never "This is my building". */
function OtherSources({ sources }: { sources: BuildingCandidate[] }) {
  if (!sources.length) return null;
  return (
    <details className="small mt">
      <summary>Other sources ({sources.length})</summary>
      <p className="small muted">Listing sites and pages that don’t clearly name a building. Open one to check details; to use a
        page anyway, paste its address under “Have the building’s website address?”.</p>
      <ul className="list">
        {sources.map((s) => (
          <li key={s.key} className="list-row">
            <span>{s.site}<span className="muted"> · {s.source_reason}</span></span>
            <a className="btn btn-small" href={s.url} target="_blank" rel="noopener noreferrer">View source ↗</a>
          </li>
        ))}
      </ul>
    </details>
  );
}

function CandidateCard({ c, busy, onChoose }: { c: BuildingCandidate; busy: boolean; onChoose: () => void }) {
  return (
    <li className={`bld-card ${c.kind === "checked" ? "bld-checked" : ""}`}>
      {c.suggested && <p className="eyebrow">You typed “{c.typed_name}”</p>}
      <div className="bld-head">
        <strong className="bld-name">{c.suggested ? `Did you mean ${c.name}?` : c.name}</strong>
        {c.kind === "checked" && <span className="chip chip-ok">Checked plan list</span>}
        {c.listing_site && <span className="chip">Listing site</span>}
      </div>
      <p className="small">
        {c.address ? c.address : <span className="muted">Street address unknown</span>}
        {c.kind === "checked" && !c.address && c.city ? ` · ${c.city}, ${c.state}` : ""}
      </p>
      <p className="small muted">
        {c.kind === "checked"
          ? <>Matched your {(c.matched_on ?? []).join(" and ") || "details"}. {c.plan_count} published plan types observed on {c.site} on {c.observed_at?.slice(0, 10)} UTC (not every unit variant, not current vacancies).{c.also_in_search ? " Also found by web search." : ""}</>
          : c.evidence.join(" ")}
      </p>
      <div className="row wrap">
        <button className="btn btn-primary btn-small" disabled={busy} onClick={onChoose}>{c.suggested ? "Yes, this is my building" : "This is my building"}</button>
        <a className="small" href={c.url} target="_blank" rel="noopener noreferrer">{c.site} ↗</a>
      </div>
    </li>
  );
}

/** Step 1: where you live. Name + city/state or ZIP -> candidate buildings -> the user picks one -> plans in "Your room". */
export default function PlaceStep({ state, status, busy, setBusy, onState, place, context, roomLabel, onSelected, onApartment, autoFind, building, wholePlace }: PanelProps & {
  wholePlace?: boolean;  // design-first flow: one plan for the whole place
  place?: ReactNode;
  context?: PlaceContext | null;
  roomLabel?: string;
  onSelected: (d: Discovery) => void;
  onApartment?: (a: ApartmentState) => void;
  autoFind?: boolean;  // the user just entered name + location on the home page: look them up once
  building?: { key: string; kind: string; name: string; address: string | null; site: string; url: string } | null;
}) {
  const [name, setName] = useState(context?.property_name ?? "");
  const [city, setCity] = useState(context?.city ?? "");
  const [st, setSt] = useState(context?.state ?? "");
  const [zip, setZip] = useState(context?.zip ?? "");
  const [found, setFound] = useState<BuildingFind | null>(null);
  const [webState, setWebState] = useState<"idle" | "searching" | "done" | "error">("idle");
  const [err, setErr] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  const [url, setUrl] = useState("");
  const live = !!status?.live_ai_available;
  const token = useRef(0);  // newest search wins; a late answer to an older search is ignored
  const mounted = useRef(true);
  // Set on every effect setup: React StrictMode runs setup → cleanup → setup in development.
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  // Editing any search field invalidates results for the old query (an in-flight answer can't repopulate them).
  const edit = (set: (v: string) => void) => (e: ChangeEvent<HTMLInputElement>) => {
    set(e.target.value);
    token.current++;
    setFound(null);
    setWebState("idle");
  };
  const chosen = building ?? null;
  const showSearch = !chosen || changing;
  const canFind = !!name.trim() && !!(city.trim() || zip.trim());

  /** Instant checked match first (free). The paid web search runs automatically only when no checked building
   *  matched; otherwise it's the user's explicit "Search for other buildings". */
  const find = async (alsoWeb = false) => {
    if (!canFind) return;
    const t = ++token.current;
    setErr(null);
    setWebState("idle");
    const q = { property_name: name.trim(), city: city.trim(), state: st.trim(), zip: zip.trim() };
    try {
      const quick = await api.findBuildings(state.project.id, { ...q, include_web: false });  // instant, no cost
      if (!mounted.current || t !== token.current) return;
      setFound(quick);
      if (!live || (quick.checked.length > 0 && !alsoWeb)) return;
      setWebState("searching");
      const full = await api.findBuildings(state.project.id, { ...q, include_web: true });
      if (!mounted.current || t !== token.current) return;
      setFound(full);
      setWebState("done");
    } catch (e) {
      if (!mounted.current || t !== token.current) return;
      setErr((e as Error).message);
      setWebState("error");
    }
  };
  useEffect(() => {
    if (autoFind && !chosen && canFind) find();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = async (body: Parameters<typeof api.selectBuilding>[1]) => {
    setErr(null);
    setBusy("Looking for this building’s floor plans");
    token.current++;  // an in-flight web search can no longer replace results once a building is chosen
    setWebState("idle");
    try {
      const r = await api.selectBuilding(state.project.id, { ...body, property_name: name.trim(), city: city.trim(), state: st.trim(), zip: zip.trim() });
      // The choice is saved on the server: always apply it (the parent ignores it if this room is no longer shown).
      onState(r.state);
      if (r.apartment) onApartment?.(r.apartment);
      if (!mounted.current) return;
      setChanging(false);
      setFound(null);
      onSelected(r.discovery);
    } catch (e) {
      if (mounted.current) setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const nothing = found && found.checked.length === 0 && found.web.length === 0 && webState !== "searching";
  return (
    <div className="stack">
      {place}
      <div className="card">
        <h2>Find your building</h2>
        {chosen && !changing ? (
          <div className="bld-chosen">
            <p className="eyebrow">Your building</p>
            <p>
              <strong>{chosen.name}</strong>{" · "}
              {chosen.address ? chosen.address : <span className="muted">street address unknown</span>}
              {chosen.site ? <> · <a href={chosen.url} target="_blank" rel="noopener noreferrer">{chosen.site} ↗</a></> : null}
            </p>
            <p className="small muted">
              {chosen.kind === "checked" ? "Chosen from a checked plan list." : chosen.kind === "web" ? "Chosen from web search results." : "Chosen by website address."}{" "}
              {wholePlace ? "Its public plans are listed below." : "Shared by every room of this place. Its public plans are listed in “Your room”."}
            </p>
            <div className="row wrap">
              <button className="btn btn-small" disabled={!!busy} onClick={() => { setChanging(true); setFound(null); }}>Change building</button>
              <button className="btn btn-small" disabled={!!busy} onClick={() => choose(chosen.kind === "checked" ? { kind: "checked", key: chosen.key } : { kind: "url", url: chosen.url })}>
                Look for its plans again
              </button>
            </div>
          </div>
        ) : (
          <p className="muted">
            Enter your building’s name and its city (with state) or ZIP, anywhere in the US. Then pick your building from the
            matches; nothing is chosen for you. Your unit number is never searched.
          </p>
        )}
        {showSearch && (
          <>
            <form className="row wrap" onSubmit={(e) => { e.preventDefault(); find(); }}>
              <label className="field grow"><span>Building or apartment name</span><input value={name} maxLength={120} onChange={edit(setName)} placeholder="e.g. The Archive" /></label>
              <label className="field"><span>City</span><input value={city} maxLength={80} onChange={edit(setCity)} placeholder="e.g. New Haven" /></label>
              <label className="field" style={{ maxWidth: 110 }}><span>State</span><input value={st} maxLength={40} onChange={edit(setSt)} placeholder="CT" /></label>
              <label className="field" style={{ maxWidth: 120 }}><span>or ZIP</span><input value={zip} maxLength={10} inputMode="numeric" onChange={edit(setZip)} /></label>
              <button className="btn btn-primary" disabled={!!busy || !canFind || webState === "searching"}>Find my building</button>
              {changing && <button type="button" className="btn" onClick={() => { setChanging(false); setFound(null); }}>Keep current building</button>}
            </form>
            {!live && <p className="small muted">Web search needs the AI connection, which isn’t available right now. Checked buildings still match, and you can enter a website address below or upload your own plan in “Your room”.</p>}
          </>
        )}
        {err && <div className="banner banner-error small" role="alert">{err} Your details are still here; you can try again.</div>}
        {showSearch && found && (
          <div className="mt" aria-live="polite">
            {found.checked.length > 0 && (
              <>
                <h3>Checked buildings</h3>
                <ul className="bld-grid">
                  {found.checked.map((c) => <CandidateCard key={c.key} c={c} busy={!!busy} onChoose={() => choose({ kind: "checked", key: c.key })} />)}
                </ul>
              </>
            )}
            {found.checked.length > 0 && live && webState === "idle" && !found.research && (
              <p className="small muted">
                Not your building?{" "}
                <button className="link" disabled={!!busy} onClick={() => find(true)}>Search the web for other buildings</button>{" "}
                (uses one web search).
              </p>
            )}
            {webState === "searching" && <p className="small muted">Searching the web for other matches…</p>}
            {found.web.length > 0 && found.checked.length > 0 && (
              <details className="small">
                <summary>Other web matches ({found.web.length})</summary>
                <p className="small muted">Leads, not verified facts. Listing sites are not the building’s own website.</p>
                <ul className="bld-grid">
                  {found.web.map((c) => <CandidateCard key={c.key} c={c} busy={!!busy} onChoose={() => choose({ kind: "web", key: c.key, url: c.url })} />)}
                </ul>
              </details>
            )}
            {found.web.length > 0 && found.checked.length === 0 && (
              <>
                <h3>Found by web search</h3>
                <p className="small muted">
                  Leads, not verified facts. Check the site and location before choosing.
                  {found.research ? ` Searched ${found.research.searched_at.slice(0, 16).replace("T", " ")} UTC${found.research.cached ? " (reused, no new search)" : ""}.` : ""}
                </p>
                <ul className="bld-grid">
                  {found.web.map((c) => <CandidateCard key={c.key} c={c} busy={!!busy} onChoose={() => choose({ kind: "web", key: c.key, url: c.url })} />)}
                </ul>
              </>
            )}
            {found.web_note && webState !== "searching" && <p className="small muted">{found.web_note}</p>}
            <OtherSources sources={found.sources ?? []} />
            {nothing && <p className="small">No matching buildings found. Check the spelling and location, enter the website address below, or upload your own plan in “Your room”.</p>}
          </div>
        )}
        <details className="mt small">
          <summary>Have the building’s website address? (advanced)</summary>
          <form className="row wrap mt" onSubmit={(e) => { e.preventDefault(); if (url.trim()) choose({ kind: "url", url: url.trim() }); }}>
            <input className="grow" type="url" required placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Building website address" />
            <button className="btn" disabled={!!busy}>Use this website</button>
          </form>
          <p className="muted small">We read a few public pages there to look for floor plans. Sites that require a login or refuse automated reading can’t be read.</p>
        </details>
        {wholePlace ? <p className="small muted">Plans you add are saved to this place. You use one plan for the whole place.</p>
          : <p className="small muted">Plans you choose are added only to <strong>{roomLabel ?? "this room"}</strong>. Each room uses its own floor-plan or photo estimate; nothing is copied between rooms.</p>}
      </div>
    </div>
  );
}
