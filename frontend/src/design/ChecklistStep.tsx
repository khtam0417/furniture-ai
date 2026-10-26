import { useEffect, useState } from "react";
import { api } from "../api";
import { cap, PIECE_NAMES, type DesignChecklist } from "../designTypes";
import { money } from "../types";
import type { DesignCtx } from "./DesignFlow";
import { exportUrls } from "./takeAway";

/** Step 4: one list for the whole design. Marks are your own record; nothing is bought or sent anywhere. */
export default function ChecklistStep({ ctx, active }: { ctx: DesignCtx; active: boolean }) {
  const { aid, ds, act, busy, go } = ctx;
  const [cl, setCl] = useState<DesignChecklist | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const v = ds.design?.version;
  useEffect(() => {
    if (!active) return;
    let live = true;
    api.designChecklist(aid).then((r) => { if (live) setCl(r); }).catch((e) => { if (live) setErr((e as Error).message); });
    return () => { live = false; };
  }, [aid, active, v]);

  if (err) return <div className="card"><p role="alert">{err}</p></div>;
  if (!cl?.checklist) return <div className="card"><p className="muted">Loading your checklist…</p></div>;
  const c = cl.checklist;
  const zone = (id: string | null) => (id && cl.zones?.[id]) || "";
  const warnCount = Object.values(ds.evaluation?.warnings ?? {}).reduce((n, w) => n + w.length, 0);
  const notPlaced = (ds.design?.data.items ?? []).filter((i) => !i.on_item && i.placed === false).length;
  return (
    <div className="stack">
      <div className={`card ${c.status === "incomplete" ? "card-warn" : ""}`}>
        <div className="row wrap" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
          <h2 style={{ margin: 0 }}>Final checklist</h2>
          <span className={`chip ${c.status === "complete" ? "chip-ok" : ""}`}>
            {c.status === "complete" ? "Complete: every piece has a product" : c.status === "empty" ? "No pieces in this design yet"
              : c.missing.length ? `Incomplete: ${c.missing.length} piece${c.missing.length === 1 ? "" : "s"} without a product`
              : `Incomplete: ${c.budget_review ?? 0} over the budget`}
          </span>
        </div>
        {(c.budget_review ?? 0) > 0 && (
          <div className="banner banner-warn small" role="alert">
            <strong>{c.budget_review} chosen product{c.budget_review === 1 ? " is" : "s are"} over your item budget</strong> and
            {c.budget_review === 1 ? " needs" : " need"} replacing; {c.budget_review === 1 ? "it stays" : "they stay"} listed below until you change {c.budget_review === 1 ? "it" : "them"}.{" "}
            <button className="btn btn-small" onClick={() => go("choose")}>See cheaper options</button>
          </div>
        )}
        <p>
          <strong>{money(c.total_cents)}</strong> for {c.units} item{c.units === 1 ? "" : "s"} chosen so far
          {cl.budget?.item_allowance_cents != null ? ` · item budget ${money(cl.budget.item_allowance_cents)} (plus ${money(cl.budget.reserve_cents)} held for delivery and tax)` : ""}.
          {" "}{c.purchased > 0 ? `${c.purchased} marked as bought.` : ""}
        </p>
        {c.missing.length > 0 && (
          <div className="banner banner-warn small">
            <strong>Still missing:</strong>
            <ul>{c.missing.map((m) => <li key={m.id}>{cap(m.name)}{zone(m.zone_id) ? ` (${zone(m.zone_id)})` : ""}: {m.reason}</li>)}</ul>
            <button className="btn btn-small" onClick={() => go("choose")}>Review missing items</button>
          </div>
        )}
        <p className="small">
          <strong>Placement:</strong>{" "}
          {notPlaced ? `${notPlaced} piece${notPlaced === 1 ? " isn’t" : "s aren’t"} placed on the plan. ` : ""}
          {warnCount ? `${warnCount} placement note${warnCount === 1 ? "" : "s"} in your arrangement. ` : "No conflicts detected in the draft arrangement. "}
          Having every product chosen doesn’t mean fit is verified: the plan map is approximate, and doors and walkways aren’t measured.
          {(notPlaced || warnCount) ? <> <button className="link" onClick={() => go("arrange")}>Review the arrangement</button></> : null}
        </p>
        <p className="small muted">Prices and sizes come from dated store pages and may have changed. Opening a link doesn’t buy anything; this app never pays, orders or contacts sellers.</p>
      </div>

      <div className="card">
        <h2>To buy</h2>
        {c.rows.length === 0 ? <p className="muted">No products chosen yet. <button className="link" onClick={() => go("choose")}>Choose furniture</button></p> : (
          <ul className="dl-list">
            {c.rows.map((r) => (
              <li key={r.product_id} className="dl-row">
                <div className="dl-body">
                  <strong className="dl-name">{r.name}</strong>
                  <span className="small muted">{PIECE_NAMES[r.category] ?? r.category} · {r.retailer} · {r.condition} · {r.width_in}″ × {r.depth_in}″ · checked {r.checked_at?.slice(0, 10) ?? "date unknown"}{r.read_via === "public_reader" ? " from a public copy of the listing page (how current it was is unknown)" : ""}{r.stale ? " (may have changed)" : ""}</span>
                  {r.url && <a className="small" href={r.url} target="_blank" rel="noopener noreferrer">Open store page ↗</a>}
                </div>
                <div className="dl-price">
                  <span className="small">{r.quantity} × {money(r.unit_price_cents)}</span>
                  <strong>{money(r.line_total_cents)}</strong>
                </div>
                <div className="dl-marks">
                  {r.instances.map((inst, n) => (
                    <label key={inst.id} className="small row" style={{ gap: "0.3rem" }}>
                      <input type="checkbox" checked={inst.purchased} disabled={!!busy || v == null}
                        onChange={(e) => act("Saving", () => api.designMark(aid, inst.id, r.product_id, e.target.checked, v!), setCl)} />
                      Bought{r.quantity > 1 ? ` #${n + 1}` : ""}{zone(inst.zone_id) ? ` (${zone(inst.zone_id)})` : ""}
                    </label>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {c.owned.length > 0 && (
        <div className="card">
          <h2>You already own</h2>
          <ul className="small">{c.owned.map((o) => <li key={o.id}>{cap(o.name)}{zone(o.zone_id) ? ` (${zone(o.zone_id)})` : ""}: no purchase needed</li>)}</ul>
        </div>
      )}
      {v != null && <TakeAway aid={aid} version={v} incomplete={c.status === "incomplete"} />}

      <div className="row wrap">
        <button className="btn" onClick={() => go("arrange")}>Back to the arrangement</button>
        <button className="btn" onClick={() => go("choose")}>Back to choosing furniture</button>
      </div>
    </div>
  );
}

/** Closing step: a printable page and a spreadsheet, both made by the server from the current design version. */
function TakeAway({ aid, version, incomplete }: { aid: string; version: number; incomplete: boolean }) {
  const urls = exportUrls(aid, version);
  return (
    <div className="card take-away">
      <h2>Take your checklist with you</h2>
      <p className="small muted">
        A printable page with your layout and store links, and a spreadsheet with every piece, price and “bought” mark.
        Both are made from your design as it is now{incomplete ? " (including what’s still missing)" : ""}. Open the
        page in your browser to print it or save it as a PDF.
      </p>
      <div className="row wrap">
        <a className="btn btn-primary" href={urls.html} download>Download printable checklist</a>
        <a className="btn" href={urls.xlsx} download>Download spreadsheet (Excel)</a>
      </div>
    </div>
  );
}
