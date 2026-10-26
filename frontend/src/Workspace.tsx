import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { ROOM_NAMES, type ApartmentState, type Discovery, type PlaceContext, type ProjectState, type Status } from "./types";
import PhotosPanel from "./panels/PhotosPanel";
import EvidencePanel from "./panels/EvidencePanel";
import PreferencesPanel from "./panels/PreferencesPanel";
import PlansPanel from "./panels/PlansPanel";
import HistoryPanel from "./panels/HistoryPanel";
import PlaceStep from "./PlaceStep";
import HelpDrawer, { type HelpTarget } from "./HelpDrawer";

export type Act = <T>(label: string, fn: () => Promise<T>, onOk?: (v: T) => void) => Promise<void>;

// Panels still navigate with these names; the guide maps them onto its steps.
type Tab = "photos" | "evidence" | "prefs" | "plans" | "history";
type Step = "place" | "room" | "prefs" | "furnish";
const STEPS: [Step, string, string][] = [
  ["place", "Your place", "Find your building and its floor plans"],
  ["room", "Your room", "Photos or a floor plan, then check what we read"],
  ["prefs", "Preferences", "Budget, style and what to buy"],
  ["furnish", "Furnish & compare", "See it in your room and swap pieces"],
];
const TAB_TO_STEP: Record<Tab, Step> = { photos: "room", evidence: "room", prefs: "prefs", plans: "furnish", history: "furnish" };

export default function Workspace({ state, status, onState, onDeleted, roomLabel, roomSwitcher, place, context, onNavLock, onApartment }: {
  context?: PlaceContext | null;
  onApartment?: (a: ApartmentState) => void;  // the shared place details changed (building chosen)
  state: ProjectState;
  status: Status | null;
  onState: (s: ProjectState) => void;
  onDeleted: () => void;
  roomLabel?: string;
  roomSwitcher?: ReactNode;  // apartment rooms, shown in context from step 2 on
  place?: ReactNode;  // apartment-level place details (step 1)
  onNavLock?: (locked: boolean) => void;  // tell the parent to block room switching (busy / unsaved draft)
}) {
  const room = state.room?.data.room;
  const mapped = !!room && (room.scale_status !== "unknown" || !!room.inferred_geometry?.drawable);
  const hasSources = state.sources.some((s) => s.kind === "photo" || s.kind === "floorplan" || s.kind === "floorplan_pdf");
  // A place whose building is already chosen opens on "Your room", where its plan gallery is.
  const [step, setStep] = useState<Step>(state.project.is_demo || mapped ? "furnish" : hasSources || context?.building ? "room" : "place");
  const [showDetails, setShowDetails] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [prefsDirty, setPrefsDirty] = useState(false);
  // The building discovery saved for this place (shared by its rooms): loaded from the server, never re-searched here.
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [discoveryNote, setDiscoveryNote] = useState<string | null>(null);
  const [autoFind] = useState(() => step === "place" && !context?.building && !!context?.property_name);
  const reviewRef = useRef<HTMLDivElement>(null);
  const prefsSave = useRef<(() => void) | null>(null);
  const p = state.project;
  const locked = !!busy || prefsDirty;
  const buildingKey = context?.building?.key ?? null;

  useEffect(() => { onNavLock?.(locked); }, [locked]); // eslint-disable-line react-hooks/exhaustive-deps
  const navigated = useRef(false);  // the user moved between steps themselves: never move them automatically
  useEffect(() => {
    let live = true;  // this room is keyed by project; a late answer after a switch or building change is dropped
    api.placeDiscovery(p.id).then((r) => {
      if (!live) return;
      setDiscovery(r.discovery);
      setDiscoveryNote(r.note);
      // A building is already chosen for this place (e.g. in another room, or a single room after refresh):
      // open on "Your room" with its shared gallery instead of sending the user back to "Your place".
      if (r.discovery?.building && !navigated.current) setStep((s) => (s === "place" ? "room" : s));
    }).catch(() => undefined);
    return () => { live = false; };
  }, [p.id, buildingKey]);
  useEffect(() => { window.scrollTo(0, 0); }, [step]);

  const act: Act = async (label, fn, onOk) => {
    setBusy(label);
    setError(null);
    setMessage(null);
    try {
      const v = await fn();
      onOk?.(v);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const go = (s: Step) => {
    if (busy) return;
    navigated.current = true;
    setStep(s);  // no popup: every step stays mounted, so an unsaved preferences draft stays in its form
  };
  const goto = (t: Tab) => {
    if (t === "history") setShowDetails(true);
    go(TAB_TO_STEP[t]);
  };
  const idx = STEPS.findIndex(([s]) => s === step);
  const common = { state, status, onState, act, busy, setBusy, setMessage, goto };
  const [helpOpen, setHelpOpen] = useState(false);
  const [listRequest, setListRequest] = useState(0);  // ask Furnish & compare to show the Shopping list
  const helpGo = (t: HelpTarget) => {
    if (t === "list") { go("furnish"); setListRequest((n) => n + 1); }
    else go(t);
  };

  return (
    <section className="workspace">
      <div className="ws-head">
        <div>
          <p className="eyebrow">{ROOM_NAMES[p.room_type] ?? p.room_type}{roomLabel ? ` · ${roomLabel}` : ""}</p>
          <h2 className="ws-title">{roomLabel ?? p.name}</h2>
          {p.is_demo ? <p className="small accent"><strong>Demo:</strong> drawn sample images and a hand-written room description, not a real room.</p> : null}
        </div>
        <button className="btn btn-small help-btn" onClick={() => setHelpOpen(!helpOpen)} aria-expanded={helpOpen}>
          {helpOpen ? "Close help" : "Help & quick changes"}
        </button>
        <button className="link small" onClick={() => setShowDetails(!showDetails)} aria-expanded={showDetails}>
          {showDetails ? "Hide saved versions & details" : "Saved versions & details"}
        </button>
      </div>

      <ol className="stepper" aria-label="Progress">
        {STEPS.map(([s, name, hint], n) => (
          <li key={s} className={`stepper-item ${s === step ? "is-current" : n < idx ? "is-done" : ""}`}>
            <button onClick={() => go(s)} disabled={!!busy && s !== step} aria-current={s === step ? "step" : undefined}>
              <span className="stepper-num">{n + 1}</span>
              <span className="stepper-text"><strong>{name}</strong><small>{hint}</small></span>
            </button>
          </li>
        ))}
      </ol>

      {roomSwitcher && step !== "place" && <div className="room-switch">{roomSwitcher}</div>}

      <div aria-live="polite">
        {busy && <div className="banner banner-info">{busy}…</div>}
        {message && <div className="banner banner-ok">{message} <button className="link" onClick={() => setMessage(null)}>OK</button></div>}
        {error && <div className="banner banner-error" role="alert">{error} <button className="link" onClick={() => setError(null)}>Dismiss</button></div>}
        {prefsDirty && step !== "prefs" && (
          <div className="banner banner-warn small">
            Preferences have unsaved changes; they’re kept in the form but not used in plans yet.{" "}
            <button className="link" disabled={!!busy} onClick={() => go("prefs")}>Return to preferences</button>
          </div>
        )}
      </div>

      {helpOpen && <HelpDrawer state={state} act={act} busy={busy} onState={onState} onGo={helpGo} onClose={() => setHelpOpen(false)} />}

      {/* Every step stays mounted so drafts survive Back/Next; only the current one is shown. */}
      <div hidden={step !== "place"}>
        <PlaceStep {...common} place={place} context={context} roomLabel={roomLabel} autoFind={autoFind} onApartment={onApartment}
          building={context?.building ?? discovery?.building ?? null}
          onSelected={(d) => {
            setDiscovery(d);
            setDiscoveryNote(null);
            setStep("room");
            const n = d.gallery?.length ?? 0;
            setMessage(n ? `${n} public floor plan${n === 1 ? "" : "s"} found for ${d.building?.name}. Pick yours below, or upload your own.`
              : `No public plans could be read for ${d.building?.name}. Upload your own plan below.`);
          }} />
      </div>
      <div hidden={step !== "room"}>
        <PhotosPanel {...common} sections={["gallery", "sources"]} discovery={discovery} discoveryNote={discoveryNote} onDiscovery={setDiscovery}
          onFindBuilding={() => go("place")}
          // Scroll only: the panel already set the specific result message (e.g. "no printed room sizes…").
          onAnalyzed={() => { reviewRef.current?.scrollIntoView({ behavior: "smooth" }); }} />
        <div ref={reviewRef} className="mt">
          <h2 className="step-sub">Review what we read</h2>
          <EvidencePanel {...common} />
        </div>
      </div>
      <div hidden={step !== "prefs"}>
        <PreferencesPanel {...common} onDirty={setPrefsDirty} saveRef={prefsSave} afterSave={() => setStep("furnish")} />
      </div>
      <div hidden={step !== "furnish"}>
        <PlansPanel {...common} desiredTiming={context?.timing || undefined} listRequest={listRequest} />
        <div className="mt"><PhotosPanel {...common} sections={["listing"]} /></div>
      </div>

      <nav className="step-nav" aria-label="Step navigation">
        <button className="btn" disabled={idx === 0 || !!busy} onClick={() => go(STEPS[idx - 1][0])}>← Back</button>
        <span className="small muted">Step {idx + 1} of {STEPS.length}</span>
        {idx < STEPS.length - 1 ? (
          <button className="btn btn-primary" disabled={!!busy}
            onClick={() => (step === "prefs" && prefsDirty && prefsSave.current ? prefsSave.current() : go(STEPS[idx + 1][0]))}>
            {step === "prefs" && prefsDirty ? `Save and continue: ${STEPS[idx + 1][1]} →` : `Next: ${STEPS[idx + 1][1]} →`}
          </button>
        ) : <span />}
      </nav>

      {showDetails && (
        <div className="mt">
          <HistoryPanel {...common} onDeleted={onDeleted} />
        </div>
      )}
    </section>
  );
}

export type PanelProps = {
  state: ProjectState;
  status: Status | null;
  onState: (s: ProjectState) => void;
  act: Act;
  busy: string | null;
  setBusy: (b: string | null) => void;
  setMessage: (m: string | null) => void;
  goto: (t: Tab) => void;
};
