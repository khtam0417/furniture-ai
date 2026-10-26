import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { inches, label, money, planName, type Alternative, type Plan, type ProjectState, type Research } from "../types";
import ResearchList from "./ResearchList";

function DimensionCard({ w, d }: { w: number | null; d: number | null }) {
  return (
    <div className="dim-card" aria-hidden>
      {w && d ? (
        <svg viewBox="0 0 100 100">
          {(() => {
            const s = 80 / Math.max(w, d);
            const rw = w * s, rd = d * s;
            return <rect x={(100 - rw) / 2} y={(100 - rd) / 2} width={rw} height={rd} fill="#e6f4f2" stroke="#25313a" strokeWidth="1.5" />;
          })()}
        </svg>
      ) : <span>size unknown</span>}
      <span className="dim-text">{inches(w)} × {inches(d)} in</span>
    </div>
  );
}

function Thumb({ src, alt, w, d }: { src: string | null; alt: string; w: number | null; d: number | null }) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) return <DimensionCard w={w} d={d} />;
  return <img className="alt-img" src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />;
}

/** Compare alternatives for ONE category in the selected plan and swap just that piece.
 *  `missing` = the plan has no item in this category yet: search/import only (adding it rebuilds plans on request). */
export default function AlternativesPanel({ state, plan, category, onClose, onState, busy, setBusy, setMessage, desiredTiming, missing = false, size, onSwapped }: {
  state: ProjectState;
  plan: Plan | null;  // null when no shopping plan is feasible yet: search/import only
  category: string;
  onClose: () => void;
  onState: (s: ProjectState) => void;
  busy: boolean;
  setBusy: (b: string | null) => void;
  setMessage: (m: string | null) => void;
  desiredTiming?: string;
  missing?: boolean;
  size?: string | null;  // bed size to search for (from a plan issue action); defaults to the room's bed size
  onSwapped?: (productId: string, category: string) => void;  // called only after a SUCCESSFUL swap
}) {
  const pid = state.project.id;
  const [alts, setAlts] = useState<Alternative[] | null>(null);
  const [planVersion, setPlanVersion] = useState<number | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [rejected, setRejected] = useState<string | null>(null);
  const [research, setResearch] = useState<Research | null>(null);
  const [condition, setCondition] = useState<Record<string, "new" | "secondhand" | "">>({});
  const [imported, setImported] = useState<Record<string, string>>({});
  const [showAll, setShowAll] = useState(false);
  const [store, setStore] = useState("all");
  const [styleOnly, setStyleOnly] = useState(false);
  const [pasteUrl, setPasteUrl] = useState("");
  const [pasteCond, setPasteCond] = useState<"new" | "secondhand" | "">("");
  const head = useRef<HTMLHeadingElement>(null);

  const planKey = plan?.key ?? null;
  const bedSize = size ?? (state.preferences?.data.bed_size !== "any" ? state.preferences?.data.bed_size : null);
  const sized = bedSize && (category === "bed_frame" || category === "mattress") ? `${bedSize} ${label(category)}` : label(category);
  const searchOnly = missing || !plan;
  useEffect(() => {
    let live = true;
    setError(null);
    if (!planKey) {
      setAlts([]);
      return () => { live = false; };
    }
    api.alternatives(pid, planKey, category)
      .then((r) => { if (live) { setAlts(r.alternatives); setPlanVersion(r.plan_version); } })
      .catch((e) => { if (live) setError((e as Error).message); });
    return () => { live = false; };
  }, [pid, planKey, category, state.plans?.id, reload]);
  useEffect(() => {
    setRejected(null); setResearch(null); setImported({}); setShowAll(false); setStore("all"); setStyleOnly(false);
    head.current?.focus();
  }, [category, planKey]);
  // Store search links (Amazon, Target, Wayfair, marketplaces): plain links, no AI call, no cost.
  const [storeLinks, setStoreLinks] = useState<{ label: string; url: string; note: string; kind?: string }[]>([]);
  useEffect(() => {
    let live = true;
    api.storeLinks(pid, category, size ?? undefined).then((r) => { if (live) setStoreLinks(r.links); }).catch(() => undefined);
    return () => { live = false; };
  }, [pid, category, size]);

  const run = async <T,>(what: string, fn: () => Promise<T>): Promise<T | null> => {
    setBusy(what);
    try {
      return await fn();
    } finally {
      setBusy(null);
    }
  };

  const choose = async (a: Alternative) => {
    setRejected(null);
    if (planVersion == null || !plan) return;
    try {
      const s = await run("Swapping", () => api.swap(pid, plan.key, category, a.product_id, planVersion));
      if (s) {
        onState(s);
        const np = s.plans?.data.plans.find((p) => p.key === plan.key);
        const drawn = np?.layouts?.arrangements?.[0]?.placements.some((x) => x.ref === a.product_id);
        const mapped = !!np?.layouts?.arrangements?.length;
        setMessage(`${label(category)} swapped to ${a.name}. Item total ${money(np?.subtotal_cents)} (was ${money(plan.subtotal_cents)}). `
          + "Other items are unchanged and the room is the same."
          + (mapped && !drawn ? " It couldn’t be placed in the current arrangement; see “Not drawn”." : ""));
        onSwapped?.(a.product_id, category);
      }
    } catch (e) {
      setRejected((e as Error).message);  // refused on the server: nothing was changed
      setReload((n) => n + 1);
    }
  };

  const search = async () => {
    setError(null);
    try {
      const r = await run("Searching the web", () => api.researchFurniture(pid, { category, ...(size ? { size } : {}) }));
      if (r) setResearch(r);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const importResult = async (url: string, given?: "new" | "secondhand") => {
    const cond = given ?? condition[url];
    if (!cond) return;
    try {
      // Check-only import keeps the current plans exactly as they are (earlier swaps stay). Adding a missing
      // category is a deliberate rebuild that the button says it does.
      const r = await run("Checking the listing", () => api.listing(pid, url, category, cond, searchOnly));
      if (r) {
        onState(r.state);
        setReload((n) => n + 1);
        const ok = r.snapshot.status === "verified";
        setImported({ ...imported, [url]: (ok ? (searchOnly ? "Checked and plans rebuilt with it where it fits your budget and settings."
          : "Checked: price and size were found; it’s now in the options above.")
          : `Saved, but ${r.snapshot.missing.join(", ")} couldn’t be read from the page, so it can’t be placed.`)
          + (r.snapshot.condition_verified === false ? ` Condition “${r.snapshot.condition}” is your declaration, not verified.` : "")
          + (r.warning ? ` ${r.warning}` : "") });
      }
    } catch (e) {
      setImported({ ...imported, [url]: `Couldn’t import this page: ${(e as Error).message} Try opening it, or paste a different listing link.` });
    }
  };

  const card = (a: Alternative) => (
    <li key={a.product_id} className={`alt-card ${a.current ? "alt-current" : ""}`}>
      <Thumb src={a.image_url} alt={`${a.retailer ?? "Retailer"} photo of ${a.name}`} w={a.width_in} d={a.depth_in} />
      <div className="alt-body">
        <div className="product-name">{a.name ?? "Unnamed listing"}</div>
        <div className="product-meta">
          <strong>{money(a.price_cents)}</strong>
          {a.delta_cents != null && !a.current && <> · {a.delta_cents >= 0 ? "+" : "−"}{money(Math.abs(a.delta_cents))}</>}
          {" · "}{inches(a.width_in)} × {inches(a.depth_in)} in
        </div>
        <div className="product-meta">
          {a.retailer ?? "source"}{(a.style_match ?? 0) > 0 ? ` · matches ${a.style_match} of your styles` : ""} ·{" "}
          {a.condition ?? "condition unknown"}{a.condition_verified ? "" : " (declared by you, not verified)"}
        </div>
        <div className="product-meta">
          {a.url ? <a href={a.url} target="_blank" rel="noopener noreferrer">View at {a.retailer ?? "source"} ↗</a> : "no source link"}
          {a.checked_at && <> · checked {a.checked_at.slice(0, 10)}</>}{a.stale && <span className="stale"> · may be outdated</span>}
        </div>
        <div className="product-meta small">{a.fit_note}</div>
        <div className="product-meta small">{a.delivery_note}</div>
        {a.current ? <span className="fit fit-unknown">Current choice</span>
          : a.can_swap ? (
            <>
              <span className="small muted">Item total after swap {money(a.subtotal_after_cents)}</span>
              <button className="btn btn-primary btn-small" disabled={busy} onClick={() => choose(a)}>Choose this</button>
            </>
          ) : <span className="small alt-why">Can’t swap: {a.reason}</span>}
      </div>
    </li>
  );

  const others = alts?.filter((a) => !a.current) ?? [];
  return (
    <section className="alt-panel card" aria-labelledby="alt-title" onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h2 id="alt-title" ref={head} tabIndex={-1} style={{ margin: 0 }}>{searchOnly ? `Find a ${sized}` : `Compare ${label(category)} options`}</h2>
        <button className="btn btn-small" onClick={onClose}>Close</button>
      </div>
      <p className="small muted">
        {searchOnly ? (plan ? `This plan has no ${label(category)} yet. Search or import one below.`
          : `No shopping plan fits your settings yet. Search or import a ${label(category)} below; importing rebuilds the plans with it.`)
          : `Choosing one swaps only the ${label(category)} in your “${planName(plan!.title)}” plan (and its Shopping list). Your room, other items and budget rules stay the same.`}
        {" "}Prices come from dated pages and may have changed. “Can be swapped” means it passed your settings, budget and
        size-on-its-own checks; it is not a guarantee that it fits or is available.
        {desiredTiming ? ` You want it: ${desiredTiming}.` : ""}
      </p>
      {rejected && <div className="banner banner-warn small" role="alert"><strong>Not swapped.</strong> {rejected}</div>}
      {error && <div className="banner banner-error small" role="alert">{error}</div>}
      {!alts && !error && <p className="small muted">Loading options…</p>}
      {alts && !searchOnly && (() => {
        const usable = alts.filter((a) => a.current || a.can_swap);
        const blocked = alts.filter((a) => !a.current && !a.can_swap && a.available !== false);
        const unavailable = alts.filter((a) => !a.current && !a.can_swap && a.available === false);
        const stores = [...new Set(usable.map((a) => a.retailer ?? "other"))];
        const filtered = usable.filter((a) => (store === "all" || (a.retailer ?? "other") === store) && (!styleOnly || a.current || (a.style_match ?? 0) > 0));
        const shown = showAll || store !== "all" || styleOnly ? filtered : filtered.filter((a) => a.recommended || a.current);
        return (
          <>
            <div className="row wrap alt-filters">
              <label className="field" style={{ minWidth: 150 }}><span>Store</span>
                <select value={store} onChange={(e) => setStore(e.target.value)}>
                  <option value="all">All stores ({usable.length})</option>
                  {stores.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <label className="check small"><input type="checkbox" checked={styleOnly} onChange={(e) => setStyleOnly(e.target.checked)} /> only options that match my style</label>
            </div>
            <ul className="alt-grid">{shown.map(card)}</ul>
            {filtered.length > shown.length && (
              <button className="btn btn-small" onClick={() => setShowAll(true)}>Show all {filtered.length} options that can be swapped in</button>
            )}
            {shown.length === 0 && <p className="small">No options match these filters.</p>}
            {blocked.length > 0 && (
              <details className="small mt">
                <summary>Not allowed by your settings or budget ({blocked.length})</summary>
                <ul className="alt-grid">{blocked.map(card)}</ul>
              </details>
            )}
            {unavailable.length > 0 && (
              <details className="small mt">
                <summary>Out of stock or missing facts ({unavailable.length})</summary>
                <ul className="alt-grid">{unavailable.map(card)}</ul>
              </details>
            )}
          </>
        );
      })()}
      {alts && !searchOnly && others.length === 0 && <p className="small">No other {label(category)} options in the catalog yet. Search the web below or import a listing.</p>}

      <div className="alt-research">
        <h3>Find more on the web</h3>
        <p className="small muted">
          Searches public stores and listing sites using your city/ZIP, condition and budget (never your unit number). Results are
          leads: import one to check its real price and size before it can be placed. Delivery or pickup timing is not known until
          you check with the seller.
        </p>
        <button className="btn btn-small" disabled={busy} onClick={search}>Search the web for {sized}</button>
        {storeLinks.length > 0 && (
          <div className="mt">
            <p className="small"><strong>Browse other stores yourself</strong> (opens their own search for “{sized}”):</p>
            <div className="row wrap">
              {storeLinks.map((l) => (
                <a key={l.url} className="btn btn-small" href={l.url} target="_blank" rel="noopener noreferrer" title={l.note}>{l.label} ↗</a>
              ))}
            </div>
            <p className="small muted">These are leads, not recommendations: we haven’t checked anything there, and some sites need a
              login or block automated reading. Found something? Paste its product link below to check its price and size.</p>
            <form className="row wrap" onSubmit={(e) => { e.preventDefault(); if (pasteUrl.trim() && pasteCond) importResult(pasteUrl.trim(), pasteCond); }}>
              <input className="grow" type="url" required placeholder="https://… product page" value={pasteUrl} onChange={(e) => setPasteUrl(e.target.value)}
                aria-label={`Product link for a ${sized}`} />
              <select value={pasteCond} onChange={(e) => setPasteCond(e.target.value as "new" | "secondhand" | "")} aria-label="Item condition (your declaration)">
                <option value="">Condition…</option>
                <option value="new">New</option>
                <option value="secondhand">Used / secondhand</option>
              </select>
              <button className="btn btn-small" disabled={busy || !pasteUrl.trim() || !pasteCond}>{searchOnly ? "Import and rebuild plans" : "Import and check"}</button>
            </form>
            {imported[pasteUrl.trim()] && <p className="small">{imported[pasteUrl.trim()]}</p>}
          </div>
        )}
        {research && (
          <div className="mt">
            <ResearchList research={research} action={(r) => (
              <>
                <label className="field" style={{ minWidth: 150 }}>
                  <span>Item condition</span>
                  <select value={condition[r.url] ?? ""} onChange={(e) => setCondition({ ...condition, [r.url]: e.target.value as "new" | "secondhand" | "" })}>
                    <option value="">Choose…</option>
                    <option value="new">New</option>
                    <option value="secondhand">Used / secondhand</option>
                  </select>
                </label>
                <button className="btn btn-small" disabled={busy || !condition[r.url]} onClick={() => importResult(r.url)}
                  title={!condition[r.url] ? "Choose new or used first" : undefined}>
                  {searchOnly ? "Import and rebuild plans" : "Import and check"}
                </button>
                {imported[r.url] && <span className="small">{imported[r.url]}</span>}
              </>
            )} />
          </div>
        )}
      </div>
    </section>
  );
}
