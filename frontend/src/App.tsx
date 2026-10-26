import ThemeToggle from "./ThemeToggle";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { AptGlyph, BrandMark, HomeIllustration } from "./art";
import SpacesList from "./SpacesList";
import {
  EMPTY_PLACE, ROOM_NAMES, money, type ApartmentState, type ApartmentSummary, type PlaceContext, type Project, type ProjectState,
  type RoomType, type Status,
} from "./types";
import Workspace from "./Workspace";
import DesignFlow from "./design/DesignFlow";

const LAYOUTS: { id: string; name: string; bedrooms: number; bathrooms: number }[] = [
  { id: "studio", name: "Studio", bedrooms: 0, bathrooms: 1 },
  { id: "1b1b", name: "1 bed · 1 bath", bedrooms: 1, bathrooms: 1 },
  { id: "2b1b", name: "2 bed · 1 bath", bedrooms: 2, bathrooms: 1 },
  { id: "2b2b", name: "2 bed · 2 bath", bedrooms: 2, bathrooms: 2 },
  { id: "3b2b", name: "3 bed · 2 bath", bedrooms: 3, bathrooms: 2 },
  { id: "custom", name: "Custom", bedrooms: 2, bathrooms: 1 },
];

type View =
  | { kind: "home" }
  | { kind: "apartment"; apt: ApartmentState; room: ProjectState | null; anchor: ProjectState | null }
  | { kind: "project"; state: ProjectState };

function PlaceFields({ ctx, set }: { ctx: PlaceContext; set: (c: PlaceContext) => void }) {
  return (
    <>
      <div className="row wrap">
        <label className="field grow"><span>City</span><input value={ctx.city} maxLength={80} onChange={(e) => set({ ...ctx, city: e.target.value })} placeholder="e.g. New Haven" /></label>
        <label className="field" style={{ maxWidth: 120 }}><span>State</span><input value={ctx.state} maxLength={40} onChange={(e) => set({ ...ctx, state: e.target.value })} placeholder="CT" /></label>
        <label className="field" style={{ maxWidth: 130 }}><span>or ZIP</span><input value={ctx.zip} maxLength={10} inputMode="numeric" pattern="\d{5}(-\d{4})?" onChange={(e) => set({ ...ctx, zip: e.target.value })} placeholder="06511" /></label>
      </div>
      <div className="row wrap">
        <label className="field" style={{ maxWidth: 200 }}><span>Unit (optional, kept private)</span><input value={ctx.unit_label} maxLength={40} onChange={(e) => set({ ...ctx, unit_label: e.target.value })} placeholder="e.g. 4B" /></label>
      </div>
      <details className="small">
        <summary>Know the building’s website address? (advanced, optional)</summary>
        <label className="field mt"><span>Building website</span><input type="url" value={ctx.property_url} maxLength={2048} onChange={(e) => set({ ...ctx, property_url: e.target.value })} placeholder="https://…" /></label>
        <p className="muted small">Not needed: we find your building from its name and city or ZIP.</p>
      </details>
    </>
  );
}

/** Shared place details for an apartment (location, building, shopping scope). Editing appends a new version. */
function PlaceDetails({ apt, onSaved }: { apt: ApartmentState; onSaved: (a: ApartmentState) => void }) {
  const [editing, setEditing] = useState(false);
  const [ctx, setCtx] = useState<PlaceContext>({ ...EMPTY_PLACE, ...apt.context });
  const [err, setErr] = useState<string | null>(null);
  const c = apt.context;
  const where = [c.city, c.state, c.zip].filter(Boolean).join(", ");
  return (
    <div className="card">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Your place</h2>
        {!editing && <button className="btn btn-small" onClick={() => { setCtx({ ...EMPTY_PLACE, ...apt.context }); setEditing(true); }}>Edit</button>}
      </div>
      {!editing ? (
        <p>
          <strong>{c.property_name || apt.apartment.name}</strong>{where ? ` · ${where}` : " · location not set"}
          {c.unit_label ? <> · unit {c.unit_label} <span className="muted small">(private, never searched)</span></> : null}
          <br /><span className="small muted">
            Budget, style, new or secondhand, pickup or delivery and timing are set once for your whole design in Choose furniture.
          </span>
        </p>
      ) : (
        <form className="stack" style={{ gap: "0.6rem" }} onSubmit={async (e) => {
          e.preventDefault();
          setErr(null);
          try {
            onSaved(await api.saveContext(apt.apartment.id, ctx));
            setEditing(false);
          } catch (x) {
            setErr((x as Error).message);
          }
        }}>
          <label className="field"><span>Building or apartment name</span><input value={ctx.property_name} maxLength={120} onChange={(e) => setCtx({ ...ctx, property_name: e.target.value })} /></label>
          <PlaceFields ctx={ctx} set={setCtx} />
          {err && <p className="small" role="alert">{err}</p>}
          <div className="row"><button className="btn btn-primary btn-small">Save place details</button><button type="button" className="btn btn-small" onClick={() => setEditing(false)}>Cancel</button></div>
          <p className="small muted">Saving keeps the previous details in history. Your floor plan and design are not changed.</p>
        </form>
      )}
    </div>
  );
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [apartments, setApartments] = useState<ApartmentSummary[]>([]);
  const [view, setView] = useState<View>({ kind: "home" });
  const viewRef = useRef<View>(view);
  useEffect(() => { viewRef.current = view; }, [view]);
  const navKey = view.kind === "home" ? "home" : view.kind === "project" ? `p:${view.state.project.id}`
    : `a:${view.apt.apartment.id}:${view.room?.project.id ?? ""}`;
  useEffect(() => { window.scrollTo(0, 0); }, [navKey]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [navLocked, setNavLocked] = useState(false);
  const [legacyOpen, setLegacyOpen] = useState(false);

  const [aptName, setAptName] = useState("");
  const [layout, setLayout] = useState("1b1b");
  const [custom, setCustom] = useState({ bedrooms: 2, bathrooms: 1 });
  const [ctx, setCtx] = useState<PlaceContext>({ ...EMPTY_PLACE });

  const refresh = useCallback(async () => {
    try {
      const [s, p, a] = await Promise.all([api.status(), api.projects(), api.apartments()]);
      setStatus(s);
      setProjects(p);
      setApartments(a);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const run = async <T,>(what: string, fn: () => Promise<T>, then: (v: T) => void) => {
    setBusy(what);
    setError(null);
    try {
      then(await fn());
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  // Navigation token: a response that arrives after the user switched rooms/views is ignored.
  const navToken = useRef(0);
  const openApartment = (id: string, roomId?: string) => {
    const token = ++navToken.current;
    return run("Opening", async () => {
      const apt = await api.apartment(id);
      const first = roomId ?? apt.rooms[0]?.project_id;
      const room = first ? await api.project(first) : null;
      const anchorId = apt.rooms[0]?.project_id;
      const anchor = anchorId === first ? room : anchorId ? await api.project(anchorId) : null;
      return { apt, room, anchor };
    }, ({ apt, room, anchor }) => { if (token === navToken.current) setView({ kind: "apartment", apt, room, anchor }); });
  };
  const selectRoom = (pid: string) => {
    if (view.kind !== "apartment" || navLocked || busy) return;
    const token = ++navToken.current;
    const aid = view.apt.apartment.id;
    run("Opening room", async () => ({ apt: await api.apartment(aid), room: await api.project(pid) }),
      ({ apt, room }) => { if (token === navToken.current) setView((v) => (v.kind === "apartment" ? { ...v, apt, room } : v)); });
  };
  const goHome = () => {
    if (navLocked && !window.confirm("Leave with unsaved changes or a task still running?")) return;
    navToken.current++;
    setView({ kind: "home" });
    refresh();
  };
  const openProject = (s: ProjectState) => { navToken.current++; setView({ kind: "project", state: s }); };

  /** Room updates apply only if that same room is still on screen. */
  const onRoomState = (s: ProjectState) => {
    const pid = s.project.id;
    setView((v) => {
      if (v.kind === "apartment" && (v.room?.project.id === pid || v.anchor?.project.id === pid)) {
        return { ...v, room: v.room?.project.id === pid ? s : v.room, anchor: v.anchor?.project.id === pid ? s : v.anchor };
      }
      if (v.kind === "project" && v.state.project.id === pid) return { kind: "project", state: s };
      return v;
    });
    const current = viewRef.current;
    if (current.kind === "apartment" && current.room?.project.id === pid) {
      const id = current.apt.apartment.id;
      api.apartment(id).then((apt) => setView((v) => (v.kind === "apartment" && v.apt.apartment.id === id ? { ...v, apt } : v))).catch(() => undefined);
    }
  };

  const start = () => {
    const name = aptName.trim() || "My apartment";
    run("Setting up your place", () => api.createApartment(name, layout, custom.bedrooms, custom.bathrooms,
      { ...ctx, property_name: aptName.trim() }), (apt) => openApartment(apt.apartment.id));
  };

  const standalone = projects.filter((p) => !p.apartment_id);
  const isDemo = view.kind === "project" && !!view.state.project.is_demo;

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={goHome} aria-label="Furniture AI home">
          <BrandMark /> Furniture AI
        </button>
        <div className="row wrap" style={{ gap: "0.5rem" }}>
          <ThemeToggle />
          {isDemo ? <span className="chip">Demo · sample room</span> : status ? (
            <span className={`chip ${status.live_ai_available ? "chip-live" : ""}`}>{status.live_ai_available ? "AI ready" : "AI not connected"}</span>
          ) : null}
        </div>
      </header>

      {error && <div className="banner banner-error main" role="alert">{error} <button className="link" onClick={() => setError(null)}>Dismiss</button></div>}

      <main className="main">
        {view.kind === "home" && (
          <section>
            <div className="hero">
              <div className="hero-copy">
                <p className="eyebrow">Furnish the place you actually live in</p>
                <h1>Your home stays as it is. We help you choose what goes in it.</h1>
                <p className="lead">
                  Pick your apartment’s floor plan, arrange furniture on it, then choose real pieces, new or secondhand. We show
                  what’s read from your plan, what’s approximate, and what to check before you buy.
                </p>
                <ol className="steps">
                  <li><strong>Place & floor plan:</strong> find your building and pick your plan, or upload your own.</li>
                  <li><strong>Arrange your space:</strong> drag draft furniture around your own plan, or pick a suggested arrangement.</li>
                  <li><strong>Choose furniture:</strong> budget, style, and a real product for each piece.</li>
                  <li><strong>Final checklist:</strong> everything to buy, in one list.</li>
                </ol>
              </div>
              <div className="hero-art"><HomeIllustration /></div>
            </div>

            <form className="card start-card" onSubmit={(e) => { e.preventDefault(); start(); }}>
              <h2>Start with your place</h2>
              <p className="small muted">No account needed. Your places are saved on this computer for this browser.</p>
              <label className="field"><span>Building or apartment name</span>
                <input value={aptName} maxLength={80} onChange={(e) => setAptName(e.target.value)} placeholder="e.g. The Archive" />
              </label>
              <PlaceFields ctx={ctx} set={setCtx} />
              <details className="small">
              <summary>Rooms (optional; your floor plan decides the shape)</summary>
              <fieldset className="layout-pick">
                <legend className="small">Apartment layout</legend>
                <div className="apt-grid">
                  {LAYOUTS.map((l) => (
                    <button type="button" key={l.id} className={`apt-card ${layout === l.id ? "apt-card-on" : ""}`} aria-pressed={layout === l.id} onClick={() => setLayout(l.id)}>
                      <AptGlyph bedrooms={l.id === "custom" ? custom.bedrooms : l.bedrooms} bathrooms={l.id === "custom" ? custom.bathrooms : l.bathrooms} />
                      <span className="apt-name">{l.name}</span>
                    </button>
                  ))}
                </div>
                {layout === "custom" && (
                  <div className="custom-row mt">
                    <label className="field"><span>Bedrooms (0 = studio)</span>
                      <input type="number" min={0} max={5} value={custom.bedrooms} onChange={(e) => setCustom({ ...custom, bedrooms: Math.max(0, Math.min(5, Number(e.target.value) || 0)) })} />
                    </label>
                    <label className="field"><span>Bathrooms</span>
                      <input type="number" min={1} max={4} value={custom.bathrooms} onChange={(e) => setCustom({ ...custom, bathrooms: Math.max(1, Math.min(4, Number(e.target.value) || 1)) })} />
                    </label>
                  </div>
                )}
                <p className="small muted">This only names rooms for the older room-by-room tools; it never sets their shape or size.</p>
              </fieldset>
              </details>
              <p className="small muted mt">New or secondhand, pickup or delivery, budget and style come later, in Choose furniture.</p>
              <div className="row wrap mt">
                <button className="btn btn-primary" disabled={!!busy}>Start planning →</button>
                <span className="small muted">You can change any of this later.</span>
              </div>
            </form>

            {busy && <p className="muted" aria-live="polite">{busy}…</p>}

            {(apartments.length > 0 || standalone.length > 0) && (
              <div className="grid-2 mt">
                {apartments.length > 0 && (
                  <div className="card">
                    <h2>Your places</h2>
                    <ul className="list">
                      {apartments.map((a) => (
                        <li key={a.id} className="list-row">
                          <button className="link" onClick={() => openApartment(a.id)}>{a.name}</button>
                          <span className="muted small">Saved place · {new Date(a.created_at).toLocaleDateString()}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {standalone.length > 0 && (
                  <div className="card">
                    <h2>Single rooms</h2>
                    <ul className="list">
                      {standalone.map((p) => (
                        <li key={p.id} className="list-row">
                          <button className="link" onClick={() => run("Opening", () => api.project(p.id), openProject)}>{p.name}</button>
                          <span className="muted small">{ROOM_NAMES[p.room_type] ?? p.room_type} · {p.is_demo ? "demo" : "your room"} · {new Date(p.created_at).toLocaleDateString()}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <details className="card mt">
              <summary>Just one room, or want to see an example first?</summary>
              <div className="row wrap mt">
                {(["bedroom", "studio", "living_room"] as RoomType[]).map((rt) => (
                  <button key={rt} className="btn btn-small" disabled={!!busy}
                    onClick={() => run("Creating room", () => api.createProject(`My ${ROOM_NAMES[rt].toLowerCase()}`, rt), openProject)}>
                    Plan a single {ROOM_NAMES[rt].toLowerCase()}
                  </button>
                ))}
                <button className="btn btn-small" disabled={!!busy} onClick={() => run("Opening demo", () => api.createDemo("bedroom"), openProject)}>Example bedroom</button>
                <button className="btn btn-small" disabled={!!busy} onClick={() => run("Opening demo", () => api.createDemo("studio"), openProject)}>Example studio</button>
              </div>
              <p className="small muted">Examples use drawn sample images and a hand-written room description; they are not real rooms.</p>
            </details>
          </section>
        )}

        {view.kind === "apartment" && (
          <section>
            <div className="apt-bar">
              <div>
                <p className="eyebrow">Your place</p>
                <h1 className="apt-title">{view.apt.context.property_name || view.apt.apartment.name}</h1>
              </div>
            </div>
            <DesignFlow key={view.apt.apartment.id} apt={view.apt} anchor={view.anchor} status={status}
              place={<PlaceDetails apt={view.apt} onSaved={(apt) => setView((v) => (v.kind === "apartment" && v.apt.apartment.id === apt.apartment.id ? { ...v, apt } : v))} />}
              onApartment={(apt) => setView((v) => (v.kind === "apartment" && v.apt.apartment.id === apt.apartment.id ? { ...v, apt } : v))}
              onAnchorState={onRoomState} />
            <details className="card mt" onToggle={(e) => setLegacyOpen((e.target as HTMLDetailsElement).open)}>
              <summary>Older room-by-room tools</summary>
              <p className="small muted">Your earlier per-room work (photos, room readings, saved plans and shopping lists) is kept here unchanged. The steps above use one plan for the whole place instead.
                {" "}These older tools were set up as “{view.apt.apartment.label}” with separate rooms; that setup doesn’t describe your chosen floor plan.</p>
              {legacyOpen && view.room && (
                <Workspace key={view.room.project.id} state={view.room} status={status} onState={onRoomState}
                  roomLabel={view.apt.rooms.find((r) => r.project_id === view.room!.project.id)?.label}
                  context={view.apt.context} onNavLock={setNavLocked}
                  onApartment={(apt) => setView((v) => (v.kind === "apartment" && v.apt.apartment.id === apt.apartment.id ? { ...v, apt } : v))}
                  roomSwitcher={
                    <div>
                      <div className="room-tabs" role="tablist" aria-label="Rooms">
                        {view.apt.rooms.map((r) => (
                          <button key={r.project_id} role="tab" aria-selected={view.room?.project.id === r.project_id} disabled={navLocked || !!busy}
                            title={navLocked ? "Finish or save what you’re doing in this room first" : undefined}
                            className={`room-tab ${view.room?.project.id === r.project_id ? "room-tab-on" : ""}`} onClick={() => selectRoom(r.project_id)}>
                            {r.label}
                            <small>{r.mapped ? "room drawn" : "not drawn yet"} · {r.budget_cents != null ? money(r.budget_cents) : "no budget"}</small>
                          </button>
                        ))}
                      </div>
                      <SpacesList apt={view.apt} selected={view.room?.project.id ?? null} onSelect={selectRoom} />
                    </div>
                  }
                  onDeleted={() => openApartment(view.apt.apartment.id)} />
              )}
            </details>
            <details className="card mt">
              <summary>Delete this place</summary>
              <div className="row wrap mt" style={{ justifyContent: "space-between" }}>
                <span className="small">Deletes this place, all its rooms, photos and history from this computer.</span>
                <button className="btn btn-danger btn-small" disabled={!!busy}
                  onClick={() => { if (window.confirm("Delete this place, all its rooms and their original photos? This cannot be undone.")) run("Deleting", () => api.deleteApartment(view.apt.apartment.id), () => setView({ kind: "home" })); }}>
                  Delete place
                </button>
              </div>
            </details>
          </section>
        )}

        {view.kind === "project" && (
          <Workspace key={view.state.project.id} state={view.state} status={status} onState={onRoomState} onNavLock={setNavLocked}
            onDeleted={() => { setView({ kind: "home" }); refresh(); }} />
        )}
      </main>
      <footer className="footer muted small">
        Furniture AI is a planning aid. Drawings are not guarantees: door swings, walkways and delivery access are not verified.
        Prices come from dated pages. No purchases are made for you.
      </footer>
    </div>
  );
}
