import { useState } from "react";
import { api } from "../api";
import type { PanelProps } from "../Workspace";

const EXAMPLES = ["Lower the budget to $800", "Keep the bed", "Replace the desk", "Add a bookcase", "Change style to mid-century", "New only"];

export default function EditBox({ state, onState, act, busy, setMessage }: Pick<PanelProps, "state" | "onState" | "act" | "busy" | "setMessage">) {
  const [text, setText] = useState("");
  const [last, setLast] = useState<{ method: string; changes: string[]; plan_changes: string[] } | null>(null);
  const demo = !!state.project.is_demo;
  const submit = (msg: string) =>
    act("Applying your request", () => api.edit(state.project.id, msg), (r) => {
      onState(r.state);
      setLast(r);
      setText("");
      setMessage(r.changes.length ? "Saved as a new version." : "Nothing changed.");
    });

  return (
    <div className="card edit-box">
      <h2>Tell us what to change</h2>
      <form className="row wrap" onSubmit={(e) => { e.preventDefault(); if (text.trim()) submit(text.trim()); }}>
        <input className="grow" value={text} maxLength={800} placeholder="e.g. keep the bed, add a work desk, and stay under $900"
          onChange={(e) => setText(e.target.value)} aria-label="Describe a change" />
        <button className="btn btn-primary" disabled={!!busy || !text.trim()}>Update plans</button>
      </form>
      <div className="chips">
        {EXAMPLES.map((ex) => <button key={ex} className="chip chip-btn" disabled={!!busy} onClick={() => setText(ex)}>{ex}</button>)}
      </div>
      <p className="muted small">
        {demo ? "Demo projects use a simple offline rule reader (not AI)." : "Your request is read by the AI and turned into specific setting changes; the app itself enforces budget and product facts."}
        {" "}Everything you didn’t mention stays the same.
      </p>
      {last && (
        <div className="small">
          <strong>Applied ({last.method === "rule_based" ? "offline rule reader" : last.method === "live_ai" ? "AI" : "test model"}):</strong>
          <ul>{last.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
          {last.plan_changes.length > 0 && (<><strong>What changed in the plans:</strong><ul>{last.plan_changes.map((c, i) => <li key={i}>{c}</li>)}</ul></>)}
        </div>
      )}
    </div>
  );
}
