import { useEffect, useState } from "react";
import { api } from "../api";
import {
  FURNISHABLE_KINDS, PIECE_GROUPS, PIECE_NAMES, ROOM_KINDS, cap, footprint, pieceName, type Arrangement, type DesignItem, type ItemOp,
} from "../designTypes";
import type { DesignCtx } from "./DesignFlow";
import { bedroomInfo } from "./findQueue";
import PlanCanvas from "./PlanCanvas";

// Grouped add menu: PIECE_GROUPS (designTypes).

/** Step 2: one workspace. Main column: arrangement thumbnails + the plan canvas (original plan as background).
 *  Side panel: the selected piece, the synced piece list (with the "Not placed" tray), adding pieces and room uses.
 *  Only furniture moves; the plan never changes. */
export default function ArrangeStep({ ctx, active }: { ctx: DesignCtx; active: boolean }) {
  const { aid, ds, setDs, act, busy, status } = ctx;
  const d = ds.design!.data;
  const v = ds.design!.version;
  const m = ds.plan_map!.data;
  const src = ds.selected_source;
  const [sel, setSel] = useState<string | null>(null);
  const [options, setOptions] = useState<Arrangement[] | null>(null);
  const [addCat, setAddCat] = useState("nightstand");
  const [addZone, setAddZone] = useState<string>("");
  const uses = ds.room_uses ?? {};
  // Where an unlabelled room is on the plan, so it can be told apart in lists (e.g. "Unlabelled, right").
  const where = (r: (typeof m.rooms)[number]) => {
    const xs = r.polygon.map((p) => p[0]), ys = r.polygon.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2 / m.image_w, cy = (Math.min(...ys) + Math.max(...ys)) / 2 / m.image_h;
    const h = cx < 0.36 ? "left" : cx > 0.64 ? "right" : "middle", vv = cy < 0.36 ? "top " : cy > 0.64 ? "bottom " : "";
    return `${vv}${h}`;
  };
  // Numbered when two distinct rooms share a printed label (e.g. "BEDROOM 1", "BEDROOM 2"); position for unlabelled.
  const roomName = (r: (typeof m.rooms)[number]) => (r.label ? ds.zone_names?.[r.id] ?? r.label : `${cap(r.kind)} (${where(r)})`);
  const usable = m.rooms.filter((r) => r.furnishable && uses[r.id]?.status !== "conflict");

  useEffect(() => {  // thumbnails follow every change; stale ones are cleared while fetching
    if (!active) return;
    let live = true;
    setOptions(null);
    api.designArrangements(aid).then((r) => { if (live) setOptions(r.options); }).catch(() => { if (live) setOptions([]); });
    return () => { live = false; };
  }, [aid, active, v]);
  useEffect(() => { if (sel && !d.items.some((i) => i.id === sel)) setSel(null); }, [d.items, sel]);

  const edit = (ops: ItemOp[], label = "Saving") => act(label, () => api.designItems(aid, ops, v), setDs);
  const item = d.items.find((i) => i.id === sel) ?? null;
  const warnings = ds.evaluation?.warnings ?? {};
  const nudge = (id: string, dxIn: number, dyIn: number) => {
    const it = d.items.find((i) => i.id === id);
    if (!it) return;
    const x = Math.min(1, Math.max(0, it.x + (dxIn * m.scale.ppi) / m.image_w));
    const y = Math.min(1, Math.max(0, it.y + (dyIn * m.scale.ppi) / m.image_h));
    edit([{ op: "move", id, x, y }], "Moving");
  };
  const rotate = (id: string) => {
    const it = d.items.find((i) => i.id === id);
    if (it) edit([{ op: "rotate", id, rotation: (((it.rotation + 90) % 360) as DesignItem["rotation"]) }], "Rotating");
  };
  const printed = m.scale.kind === "printed" && m.status === "mapped";
  const allWarn = Object.values(warnings).reduce((n, w) => n + w.length, 0);
  const tops = d.items.filter((i) => !i.on_item);
  const onIt = (id: string) => d.items.filter((i) => i.on_item === id);
  const unplaced = tops.filter((i) => i.placed === false);
  const placed = tops.filter((i) => i.placed !== false);
  const elsewhere = placed.filter((i) => !usable.some((r) => r.id === i.zone_id));
  const productName = (it: DesignItem) => (it.owned ? "You own this" : it.product_id && ds.products[it.product_id] ? (ds.products[it.product_id].name ?? "Chosen product") : "Draft");
  const live = !!status?.live_ai_available;
  const rooms = bedroomInfo(m.rooms, uses, m.status === "mapped");
  const hasBed = d.items.some((i) => ["bed_frame", "sofa_bed", "daybed"].includes(i.category));

  const pieceRow = (it: DesignItem) => {
    const w = warnings[it.id] ?? [];
    return (
      <li key={it.id} className={`inv-row ${sel === it.id ? "inv-on" : ""}`}>
        <button className="inv-btn" aria-pressed={sel === it.id} onClick={() => setSel(it.id)}>
          <span className="inv-name">{pieceName(it)}</span>
          <span className="inv-meta" title={productName(it)}>{productName(it)}</span>
          {w.length > 0 && <span className="inv-note">{w.length} placement note{w.length === 1 ? "" : "s"}</span>}
          {onIt(it.id).map((a) => <span key={a.id} className="inv-sub" title={productName(a)}>+ {pieceName(a)} · {productName(a)}</span>)}
        </button>
      </li>
    );
  };

  return (
    <div className="card arrange">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0 }}>Arrange your space</h2>
          <p className="small muted">
            Drag a piece, or select it and use the controls (arrow keys and R work too). Dashed pieces are draft sizes, not products.
            {" "}{printed ? "Sizes follow your plan’s printed room sizes: approximate." : "Drawn at an approximate relative size: good for arranging, not for checking fit."}
          </p>
        </div>
        <span className={`chip ${allWarn ? "" : "chip-ok"}`}>{allWarn ? `${allWarn} placement note${allWarn === 1 ? "" : "s"}` : "No conflicts detected in this draft"}</span>
      </div>
      {ds.map_outdated && (
        <p className="small reread-note">
          Read with an older reader.{" "}
          <button className="link" disabled={!!busy || !live} title="One AI call; your pieces and chosen products are kept"
            onClick={() => act("Re-reading your plan", () => api.designRead(aid, v), setDs)}>Re-read plan</button>
          {live ? " (one AI call; pieces and products kept)" : " (AI isn’t connected right now)"}
        </p>
      )}

      <div className="arrange-grid">
        <div className="arrange-main">
          <div className="thumb-strip" role="group" aria-label="Suggested arrangements">
            {options === null ? <span className="small muted thumb-wait">Updating suggestions…</span>
              : options.length === 0 ? <span className="small muted thumb-wait">{m.status === "mapped" ? "No suggestions right now." : "No suggested arrangements: this plan’s room boundaries couldn’t be read. Re-read the plan or choose another plan image; your pieces wait in “Not placed”."}</span>
              : options.map((o) => {
                const on = d.arrangement === o.key;
                return (
                  <button key={o.key} className={`thumb-opt ${on ? "thumb-on" : ""}`} aria-pressed={on} disabled={!!busy}
                    title={o.description} onClick={() => { if (!on) act("Applying arrangement", () => api.designApplyArrangement(aid, o.key, v), setDs); }}>
                    {src && <PlanCanvas roomUses={ds.room_uses} compact imageUrl={src.preview} imageW={src.width} imageH={src.height} map={m} items={o.items} products={ds.products} />}
                    <span className="thumb-title">{o.title}{on ? " ✓" : ""}</span>
                    <span className="thumb-note">{o.unplaced ? `${o.unplaced} not placed` : o.warnings ? `${o.warnings} note${o.warnings === 1 ? "" : "s"}` : "No conflicts"}</span>
                  </button>
                );
              })}
          </div>
          {src && (
            <PlanCanvas roomUses={ds.room_uses} imageUrl={src.preview} imageW={src.width} imageH={src.height} map={m} items={d.items} products={ds.products}
              warnings={warnings} selected={sel} onSelect={setSel} editable={!busy}
              onMove={(id, x, y) => edit([{ op: "move", id, x, y }], "Moving")} onNudge={nudge} onRotate={rotate}
              caption={`${m.scale.note} Doors and walkways are approximate.`} />
          )}
        </div>

        <aside className="arrange-side" aria-label="Pieces and rooms">
          {item ? (
            <div className="piece-toolbar">
              <div className="pt-head">
                <strong>{pieceName(item)}</strong>
                <span className="small muted">
                  {productName(item)}{item.placed === false ? " · Not placed" : ""}
                  {printed && !item.on_item && item.placed !== false ? ` · about ${Math.round(footprint(item, ds.products).w)} × ${Math.round(footprint(item, ds.products).d)} in` : ""}
                </span>
              </div>
              {item.category === "tv" ? (() => {
                const stands = d.items.filter((i) => i.category === "tv_stand" && !d.items.some((t) => t.on_item === i.id && t.id !== item.id));
                return (
                  <div className="stack" style={{ gap: "0.3rem" }}>
                    <p className="small muted">{item.on_item ? "Sits on its TV stand and moves with it." : item.unplaced_reason}</p>
                    {stands.length > 0 ? (
                      <label className="field pt-room"><span className="small">On which TV stand</span>
                        <select value={item.on_item ?? ""} disabled={!!busy}
                          onChange={(e) => e.target.value && edit([{ op: "attach", id: item.id, host_id: e.target.value }], "Moving the TV")}>
                          {!item.on_item && <option value="">Choose a stand…</option>}
                          {stands.map((st) => <option key={st.id} value={st.id}>TV stand in {ds.zone_names?.[st.zone_id ?? ""] ?? "your plan"}</option>)}
                        </select>
                      </label>
                    ) : <p className="small">Add a TV stand first (Add pieces → Living → TV stand / media console).</p>}
                  </div>
                );
              })() : item.on_item ? (
                <p className="small muted">Sits on the {pieceName(d.items.find((i) => i.id === item.on_item) ?? { category: "bed_frame" })}; it moves with it.</p>
              ) : item.placed === false ? (
                <p className="small">{item.unplaced_reason ?? "Not placed yet."} It stays in your design and lists.</p>
              ) : (
                <div className="pt-move">
                  <div className="nudge" role="group" aria-label="Move the selected piece">
                    <button className="btn btn-small" disabled={!!busy} aria-label="Move left" onClick={() => nudge(item.id, -6, 0)}>◀</button>
                    <button className="btn btn-small" disabled={!!busy} aria-label="Move up" onClick={() => nudge(item.id, 0, -6)}>▲</button>
                    <button className="btn btn-small" disabled={!!busy} aria-label="Move down" onClick={() => nudge(item.id, 0, 6)}>▼</button>
                    <button className="btn btn-small" disabled={!!busy} aria-label="Move right" onClick={() => nudge(item.id, 6, 0)}>▶</button>
                  </div>
                  <button className="btn btn-small" disabled={!!busy} onClick={() => rotate(item.id)}>Rotate 90°</button>
                </div>
              )}
              {!item.on_item && item.category !== "tv" && m.status === "mapped" && (
                <label className="field pt-room"><span className="small">{item.placed === false ? "Place it in" : "Room"}</span>
                  <select value={item.placed === false ? "" : item.zone_id ?? ""} disabled={!!busy}
                    onChange={(e) => e.target.value && edit([{ op: "zone", id: item.id, zone_id: e.target.value }], "Placing")}>
                    <option value="">{item.placed === false ? "Choose a room…" : "No room"}</option>
                    {usable.map((r) => <option key={r.id} value={r.id}>{roomName(r)}</option>)}
                  </select>
                </label>
              )}
              <div className="pt-own">
                <label className="small row" style={{ gap: "0.3rem" }}>
                  <input type="checkbox" checked={item.owned} disabled={!!busy} onChange={(e) => edit([{ op: "owned", id: item.id, owned: e.target.checked }])} />
                  I already own this
                </label>
                <button className="btn btn-small btn-danger" disabled={!!busy} onClick={() => { edit([{ op: "remove", id: item.id }], "Removing"); setSel(null); }}>Remove</button>
              </div>
              {(warnings[item.id] ?? []).length > 0 && <ul className="small warn-list">{warnings[item.id].map((w, i) => <li key={i}>{w}</li>)}</ul>}
            </div>
          ) : <p className="small muted">Select a piece on the plan or in the list.</p>}

          <p className="small" role="status">
            {d.items.length} piece{d.items.length === 1 ? "" : "s"} in your layout: each is one thing to shop for in Choose furniture.
          </p>
          {!rooms.bedroomRecognized && rooms.unsureAreas && !hasBed && (
            <div className="banner banner-warn small" role="status">
              No bedroom was recognized on this floor plan: some areas couldn’t be read clearly, so no bed was added (a bedroom
              is never guessed from the apartment type). If one of them is a bedroom, set its use under “Rooms on your plan”
              below, or add a bed or bed set to a room yourself.
            </div>
          )}
          <form className="side-form" onSubmit={(e) => { e.preventDefault(); edit([{ op: "add", category: addCat, zone_id: addZone || null }], "Adding"); }}>
            <h3 className="side-h">Add pieces</h3>
            <div className="row wrap">
              <select aria-label="Piece type" value={addCat} onChange={(e) => setAddCat(e.target.value)}>
                {PIECE_GROUPS.map(([g, cats]) => (
                  <optgroup key={g} label={g}>{cats.map((c) => <option key={c} value={c}>{PIECE_NAMES[c]}</option>)}</optgroup>
                ))}
              </select>
              {m.status === "mapped" && (
                <select aria-label="Room" value={addZone} onChange={(e) => setAddZone(e.target.value)}>
                  <option value="">Largest room</option>
                  {usable.map((r) => <option key={r.id} value={r.id}>{roomName(r)}</option>)}
                </select>
              )}
              <button className="btn btn-small" disabled={!!busy}>Add</button>
            </div>
            {m.status === "mapped" && addZone && (
              <button type="button" className="link small" disabled={!!busy} onClick={() => edit([{ op: "add_set", zone_id: addZone }], "Adding a bed set")}>
                Add a bed set to this room
              </button>
            )}
          </form>
          <h3 className="side-h">Pieces</h3>
          {usable.map((r) => {
            const here = placed.filter((i) => i.zone_id === r.id);
            return here.length ? (
              <div key={r.id}>
                <p className="inv-room">{roomName(r)}</p>
                <ul className="inv-list">{here.map(pieceRow)}</ul>
              </div>
            ) : null;
          })}
          {elsewhere.length > 0 && (
            <div><p className="inv-room">Elsewhere on the plan</p><ul className="inv-list">{elsewhere.map(pieceRow)}</ul></div>
          )}
          {unplaced.length > 0 && (
            <div className="tray">
              <p className="inv-room">Not placed ({unplaced.length})</p>
              <p className="small muted">Still in your design and lists; not drawn. Select one to place it.</p>
              <ul className="inv-list">{unplaced.map(pieceRow)}</ul>
            </div>
          )}


          {m.status === "mapped" && (
            <details className="side-rooms" open={Object.values(uses).some((u) => u.status !== "confirmed")}>
              <summary><strong>Rooms on your plan</strong> <span className="small muted">(fix a room’s use)</span></summary>
              <ul className="inv-list">
                {m.rooms.map((r) => {
                  const u = uses[r.id];
                  const kinds: string[] = [...ROOM_KINDS];
                  if (!kinds.includes(r.kind)) kinds.push(r.kind);
                  return (
                    <li key={r.id} className="room-use">
                      <span>{r.label || `Unlabelled, ${where(r)}`}{" "}
                        <span className={`chip ${u?.status === "confirmed" ? "" : "chip-warn"}`}>
                          {u?.status === "conflict" ? "Check" : u?.status === "uncertain" ? "Unsure" : r.user_set ? "Set by you" : "Read"}
                        </span>
                      </span>
                      {u?.note && u.status !== "confirmed" && <span className="small muted">{u.note}</span>}
                      <select aria-label={`Use of ${r.label || "this room"}`} value={r.kind} disabled={!!busy}
                        onChange={(e) => act("Saving room use", () => api.designRoomUse(aid, r.id, e.target.value, v), setDs)}>
                        {kinds.map((k) => <option key={k} value={k}>{cap(k)}{FURNISHABLE_KINDS.has(k) ? "" : " (kept clear)"}</option>)}
                      </select>
                    </li>
                  );
                })}
              </ul>
              <p className="small muted">Changing a room’s use saves a corrected copy of the map (the AI reading is kept). Pieces in a room that becomes a bath, kitchen or closet go to “Not placed”.</p>
            </details>
          )}
        </aside>
      </div>
    </div>
  );
}
