import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api";
import type { DesignState } from "../designTypes";
import type { ApartmentState, ProjectState, Status } from "../types";
import PlanStep from "./PlanStep";
import ArrangeStep from "./ArrangeStep";
import ChooseStep from "./ChooseStep";
import ChecklistStep from "./ChecklistStep";
import AssistantPanel from "./AssistantPanel";

export type Step = "plan" | "arrange" | "choose" | "list";
const STEPS: [Step, string, string][] = [
  ["plan", "Place & floor plan", "Your building and the plan you live in"],
  ["arrange", "Arrange your space", "Draft furniture on your plan"],
  ["choose", "Choose furniture", "Budget, style and real products"],
  ["list", "Final checklist", "Everything to buy, in one list"],
];

export type DesignCtx = {
  aid: string;
  ds: DesignState;
  setDs: (s: DesignState) => void;
  act: <T>(label: string, fn: () => Promise<T>, ok?: (v: T) => void) => Promise<void>;
  busy: string | null;
  setMessage: (m: string | null) => void;
  go: (s: Step) => void;
  status: Status | null;
};

/** The design-first flow for a whole place: ONE selected floor plan, shared by every step. */
export default function DesignFlow({ apt, anchor, status, place, onApartment, onAnchorState }: {
  apt: ApartmentState;
  anchor: ProjectState | null;  // storage/ownership anchor for plan images and imported listings
  status: Status | null;
  place: ReactNode;
  onApartment: (a: ApartmentState) => void;
  onAnchorState: (s: ProjectState) => void;
}) {
  const aid = apt.apartment.id;
  const stepKey = `furniture-ai-step:${aid}`;
  const [ds, setDs] = useState<DesignState | null>(null);
  const [step, setStep] = useState<Step>(() => (sessionStorage.getItem(stepKey) as Step | null) ?? "plan");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const live = useRef(true);
  const [prefsDirty, setPrefsDirty] = useState(false);
  const [finding, setFinding] = useState(false);
  const prefsSave = useRef<((then?: () => void) => void) | null>(null);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);

  const reload = useCallback(async () => {
    const s = await api.design(aid);
    if (live.current) setDs(s);
    return s;
  }, [aid]);
  useEffect(() => {
    reload().then((s) => {
      // A design without a read map can't be arranged yet: start on the plan step.
      if (!s.plan_map) setStep("plan");
    }).catch((e) => setError((e as Error).message));
  }, [reload]);
  useEffect(() => { sessionStorage.setItem(stepKey, step); window.scrollTo(0, 0); }, [step, stepKey]);

  const act: DesignCtx["act"] = async (label, fn, ok) => {
    setBusy(label);
    setError(null);
    setMessage(null);
    try {
      const v = await fn();
      if (live.current) ok?.(v);
    } catch (e) {
      if (!live.current) return;
      const err = e as Error;
      setError(err.message);
      if (e instanceof ApiError && e.status === 409) reload().catch(() => undefined);  // show the latest version
    } finally {
      if (live.current) setBusy(null);
    }
  };

  const order: Step[] = ["plan", "arrange", "choose", "list"];
  const go = (s: Step) => {
    if (busy) return;
    // Moving forward from "Choose furniture" with unsaved budget/style saves first; going back keeps the draft.
    if (step === "choose" && prefsDirty && prefsSave.current && order.indexOf(s) > order.indexOf(step)) {
      prefsSave.current(() => setStep(s));
      return;
    }
    setStep(s);
  };
  if (!ds) return <div className="card">{error ? <p role="alert">{error}</p> : <p className="muted">Opening your place…</p>}</div>;
  const ctx: DesignCtx = { aid, ds, setDs, act, busy, setMessage, go, status };
  const idx = STEPS.findIndex(([s]) => s === step);
  const hasMap = !!ds.plan_map;
  const canEnter = (s: Step) => s === "plan" || hasMap;
  const b = ds.evaluation?.budget;

  return (
    <section className="workspace">
      <ol className="stepper" aria-label="Progress">
        {STEPS.map(([s, name, hint], n) => (
          <li key={s} className={`stepper-item ${s === step ? "is-current" : n < idx ? "is-done" : ""}`}>
            <button onClick={() => go(s)} disabled={(!!busy && s !== step) || !canEnter(s)} aria-current={s === step ? "step" : undefined}
              title={!canEnter(s) ? "Choose and read a floor plan first" : undefined}>
              <span className="stepper-num">{n + 1}</span>
              <span className="stepper-text"><strong>{name}</strong><small>{hint}</small></span>
            </button>
          </li>
        ))}
      </ol>

      <div aria-live="polite">
        {busy && <div className="banner banner-info">{busy}…</div>}
        {message && <div className="banner banner-ok">{message} <button className="link" onClick={() => setMessage(null)}>OK</button></div>}
        {ds.changes.length > 0 && !message && !busy && <div className="banner banner-ok small">{ds.changes.join(" ")}</div>}
        {error && <div className="banner banner-error" role="alert">{error} <button className="link" onClick={() => setError(null)}>Dismiss</button></div>}
        {prefsDirty && step !== "choose" && (
          <div className="banner banner-warn small">
            Budget and style have unsaved changes; totals still use the saved ones.{" "}
            <button className="link" disabled={!!busy} onClick={() => go("choose")}>Return to Choose furniture</button>
          </div>
        )}
      </div>

      {/* Every step stays mounted so drafts survive Back/Next; only the current one is shown. */}
      <div hidden={step !== "plan"}>
        <PlanStep ctx={ctx} apt={apt} anchor={anchor} place={place} onApartment={onApartment} onAnchorState={onAnchorState} />
      </div>
      {hasMap && (
        <>
          <div hidden={step !== "arrange"}><ArrangeStep ctx={ctx} active={step === "arrange"} /></div>
          <div hidden={step !== "choose"}><ChooseStep ctx={ctx} active={step === "choose"} anchor={anchor} onAnchorState={onAnchorState} onDirty={setPrefsDirty} onFinding={setFinding} saveRef={prefsSave} apt={apt} onApartment={onApartment} /></div>
          <div hidden={step !== "list"}><ChecklistStep ctx={ctx} active={step === "list"} /></div>
        </>
      )}

      <nav className="step-nav" aria-label="Step navigation">
        <button className="btn" disabled={idx === 0 || !!busy} onClick={() => go(STEPS[idx - 1][0])}>← Back</button>
        <span className="small muted">
          Step {idx + 1} of {STEPS.length}
          {b && step !== "plan" ? ` · ${b.status === "complete" ? "all pieces chosen" : b.status === "incomplete" ? `${b.missing.length} piece${b.missing.length === 1 ? " still needs" : "s still need"} a product` : ""}` : ""}
        </span>
        {idx < STEPS.length - 1 ? (
          <button className="btn btn-primary" disabled={!!busy || !canEnter(STEPS[idx + 1][0])}
            title={!canEnter(STEPS[idx + 1][0]) ? "Choose and read a floor plan first" : undefined}
            onClick={() => go(STEPS[idx + 1][0])}>{step === "choose" && prefsDirty ? "Save and continue" : "Next"}: {STEPS[idx + 1][1]} →</button>
        ) : <span />}
      </nav>
      <AssistantPanel ctx={ctx} step={step} locked={finding} />
    </section>
  );
}
