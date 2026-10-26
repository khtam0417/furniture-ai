import { useState } from "react";
import { fitPlain, inches, label, money, type Checklist, type ChecklistItem } from "../types";

function Photo({ src, alt }: { src: string | null; alt: string }) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) return <div className="item-thumb item-thumb-none" aria-hidden>no photo</div>;
  return <img className="item-thumb" src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />;
}

/** Shopping list for the selected plan. "Mark purchased" is the user's own note: opening a store link never marks
 *  anything, and nothing is bought, paid or ordered here. */
export default function ShoppingList({ list, busy, onMark }: {
  list: Checklist | null;
  busy: boolean;
  onMark: (item: ChecklistItem, purchased: boolean) => void;
}) {
  if (!list) return <p className="small muted">Loading your shopping list…</p>;
  if (!list.plan_key) return <p className="small">No shopping plan yet, so there’s nothing to buy. See the message above.</p>;
  const c = list.counts;
  return (
    <div className="stack">
      <div className="shop-summary" aria-live="polite">
        <strong>{c.purchased} of {c.to_buy} marked purchased</strong>
        <span>{c.remaining} left · {money(list.remaining_cents)} remaining of {money(list.subtotal_cents)}</span>
        <span className="small muted">Items only: tax, delivery and assembly are not included and unknown.{c.price_unknown ? ` ${c.price_unknown} price(s) unknown.` : ""}</span>
      </div>
      <ul className="shop-list">
        {list.items.map((it) => (
          <li key={it.product_id ?? `owned-${it.category}-${it.name}`} className={`shop-row ${it.purchased ? "shop-done" : ""}`}>
            {it.owned ? <div className="item-thumb item-thumb-none">owned</div> : <Photo src={it.image_url} alt={`${it.retailer ?? "Retailer"} photo of ${it.name}`} />}
            <div className="shop-body">
              <div className="product-cat">{label(it.category)}{it.condition && !it.owned ? ` · ${it.condition}` : ""}</div>
              <div className="product-name">{it.name}</div>
              {it.owned ? (
                <div className="product-meta">Already owned: nothing to buy, no charge.</div>
              ) : (
                <>
                  <div className="product-meta">
                    <strong>{money(it.price_cents)}</strong> · {inches(it.width_in)} × {inches(it.depth_in)} in · <span title={fitPlain(it.fit_label, it.fit_checks).help}>{fitPlain(it.fit_label, it.fit_checks).text}</span>
                  </div>
                  <div className="product-meta">
                    {it.url ? <a href={it.url} target="_blank" rel="noopener noreferrer">View at {it.retailer ?? "store"} ↗</a> : "no store link"}
                    {it.checked_at && <> · price checked {it.checked_at.slice(0, 10)}</>}{it.stale && <span className="stale"> · may be outdated</span>}
                    {" · delivery/pickup unknown"}
                  </div>
                </>
              )}
            </div>
            {!it.owned && it.product_id && (
              <label className="shop-check">
                <input type="checkbox" checked={!!it.purchased} disabled={busy}
                  aria-label={`${it.purchased ? "Purchased" : "Mark purchased"}: ${it.name}`}
                  onChange={(e) => onMark(it, e.target.checked)} />
                <span>{it.purchased ? "Purchased" : "Mark purchased"}</span>
              </label>
            )}
          </li>
        ))}
      </ul>
      {list.retired_purchased > 0 && (
        <p className="small muted">{list.retired_purchased} item(s) you marked purchased are no longer in this plan (swapped or
          a different plan), so they aren’t counted here. Their marks are kept.</p>
      )}
      {list.notes.map((n, i) => <p key={i} className="small muted">{n}</p>)}
    </div>
  );
}
