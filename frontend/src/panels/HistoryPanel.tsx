import { useState } from "react";
import { api } from "../api";
import type { PanelProps } from "../Workspace";

const methodName = (m: string) =>
  ({ live_ai: "AI", mocked_ai: "test model", fixture: "synthetic fixture", manual: "you", rule_based: "offline rule reader" } as Record<string, string>)[m] ?? m;

export default function HistoryPanel({ state, onState, act, busy, setMessage, onDeleted }: PanelProps & { onDeleted: () => void }) {
  const p = state.project;
  const [exported, setExported] = useState<string | null>(null);
  const [usage, setUsage] = useState<{ calls: Record<string, unknown>[]; estimated_cost_usd_total: number } | null>(null);
  const [events, setEvents] = useState<{ kind: string; data: unknown; created_at: string }[] | null>(null);
  const v = state.versions;
  const headPlan = v.plans[0]?.id;
  const headPref = v.preferences[0]?.id;

  const download = () => {
    if (!exported) return;
    const blob = new Blob([exported], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${p.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-shopping-plan.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="stack">
      <div className="card">
        <h2>Shopping plan</h2>
        <p className="muted">A text summary with prices, links and check dates. It never includes your photos.</p>
        <div className="row wrap">
          <button className="btn btn-primary" disabled={!!busy} onClick={() => act("Preparing export", () => api.exportPlan(p.id), (r) => setExported(r.markdown))}>Prepare export</button>
          {exported && <button className="btn" onClick={download}>Download .md</button>}
        </div>
        {exported && <pre className="pre small">{exported}</pre>}
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Plan versions</h2>
          <p className="muted small">Restoring adds a new version with that plan and its own preferences and room details. Nothing is erased.</p>
          <ol className="list versions">
            {v.plans.map((x) => (
              <li key={x.id} className="list-row">
                <span><strong>v{x.version}</strong> {x.summary} <span className="muted small">{new Date(x.created_at).toLocaleString()}</span></span>
                {x.id !== headPlan && (
                  <button className="btn btn-small" disabled={!!busy} onClick={() => act("Restoring", () => api.revert(p.id, "plan", x.id), (s) => { onState(s); setMessage(`Restored plan v${x.version} as a new version.`); })}>Restore</button>
                )}
              </li>
            ))}
          </ol>
        </div>
        <div className="card">
          <h2>Preference versions</h2>
          <ol className="list versions">
            {v.preferences.map((x) => (
              <li key={x.id} className="list-row">
                <span><strong>v{x.version}</strong> {x.summary} <span className="muted small">by {methodName(x.method)}</span></span>
                {x.id !== headPref && (
                  <button className="btn btn-small" disabled={!!busy} onClick={() => act("Restoring", () => api.revert(p.id, "preferences", x.id), (s) => { onState(s); setMessage(`Restored preferences v${x.version}; plans rebuilt.`); })}>Restore</button>
                )}
              </li>
            ))}
          </ol>
          <h3>Room evidence versions</h3>
          <ol className="list versions small">
            {v.room.map((x) => <li key={x.id}><strong>v{x.version}</strong> {x.summary} <span className="muted">({methodName(x.method)})</span></li>)}
            {v.room.length === 0 && <li className="muted">None yet.</li>}
          </ol>
        </div>
      </div>

      <details className="card diag">
        <summary>Diagnostics: AI usage, sources and activity</summary>
        <div className="row wrap">
          <button className="btn btn-small" onClick={() => act("Loading usage", () => api.usage(p.id), setUsage)}>Load AI usage</button>
          <button className="btn btn-small" onClick={() => act("Loading activity", () => api.history(p.id), (h) => setEvents(h.events))}>Load activity log</button>
        </div>
        {usage && (
          <div className="small">
            <p>{usage.calls.length} AI call(s). Estimated token cost: ${usage.estimated_cost_usd_total.toFixed(6)} (estimate from returned usage, not an invoice).</p>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Purpose</th><th>Status</th><th>Input</th><th>Cached</th><th>Output</th><th>Est. $</th><th>Latency s</th></tr></thead>
                <tbody>
                  {usage.calls.map((c, i) => (
                    <tr key={i}>
                      <td>{String(c.purpose)}</td><td>{String(c.status)}</td>
                      <td>{c.input_tokens == null ? "—" : String(c.input_tokens)}</td>
                      <td>{c.cached_input_tokens == null ? "—" : String(c.cached_input_tokens)}</td>
                      <td>{c.output_tokens == null ? "—" : String(c.output_tokens)}</td>
                      <td>{c.estimated_cost_usd == null ? "—" : Number(c.estimated_cost_usd).toFixed(6)}</td>
                      <td>{c.latency_s == null ? "—" : String(c.latency_s)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">“—” means the API did not report that number; we never fill it in.</p>
          </div>
        )}
        <h3>Stored sources</h3>
        <div className="table-wrap">
          <table className="table small">
            <thead><tr><th>Kind</th><th>Name / URL</th><th>SHA-256</th><th>Retrieved</th></tr></thead>
            <tbody>
              {state.sources.map((s) => (
                <tr key={s.id}><td>{s.kind}{s.is_synthetic ? " (synthetic)" : ""}</td><td className="break">{s.original_filename || s.source_url}</td><td className="mono">{s.sha256.slice(0, 12)}…</td><td>{(s.retrieved_at || s.created_at).slice(0, 16)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        {events && <pre className="pre small">{JSON.stringify(events.slice(0, 30), null, 1)}</pre>}
      </details>

      <div className="card card-danger">
        <h2>Delete this project</h2>
        <p className="muted small">Permanently removes the project, its history and its original photos from this computer.</p>
        <button className="btn btn-danger" disabled={!!busy} onClick={() => {
          if (window.confirm("Delete this project and its original photos? This cannot be undone.")) {
            act("Deleting", () => api.deleteProject(p.id), () => onDeleted());
          }
        }}>Delete project</button>
      </div>
    </div>
  );
}
