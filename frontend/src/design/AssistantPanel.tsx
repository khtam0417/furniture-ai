import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AssistantProposal, AssistantReply } from "../designTypes";
import type { DesignCtx, Step } from "./DesignFlow";
import { changeProposals, navProposals } from "./assistantLogic";

type Msg = { role: "user" | "helper"; text: string; reply?: AssistantReply; applied?: boolean; picked?: number[] };

/** "Ask for help": a small helper for the four-step workspace. Questions get answers; requested changes come back as
 *  proposals you review and apply (or not). Navigation buttons only go to steps and pieces of this design. */
export default function AssistantPanel({ ctx, step, locked = false }: { ctx: DesignCtx; step: Step; locked?: boolean }) {
  const { aid, ds, setDs, busy, go } = ctx;
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const v = ds.design?.version ?? 0;
  useEffect(() => { if (open) input.current?.focus(); }, [open]);
  useEffect(() => { log.current?.scrollTo?.({ top: log.current.scrollHeight }); }, [msgs]);
  const close = () => { setOpen(false); setTimeout(() => launcher.current?.focus(), 0); };

  const send = async () => {
    const m = text.trim();
    if (!m || sending) return;
    setText("");
    setErr(null);
    setMsgs((x) => [...x, { role: "user", text: m }]);
    setSending(true);
    try {
      const r = await api.designAssistant(aid, m, step, v);
      setMsgs((x) => [...x, { role: "helper", text: r.reply, reply: r, picked: changeProposals(r.proposals).map((p) => p.index) }]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSending(false);
    }
  };
  const nav = (p: AssistantProposal) => {
    if (p.kind === "go_to" && p.step) go(p.step as Step);
    if (p.kind === "open_piece" && p.item_id) {
      go("choose");
      setTimeout(() => document.getElementById(`piece-${p.item_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 80);
    }
  };
  const applyFor = async (n: number) => {
    const msg = msgs[n];
    if (!msg.reply?.proposal_id || !msg.picked?.length || locked) return;
    setErr(null);
    setSending(true);
    try {
      const s = await api.designAssistantApply(aid, msg.reply.proposal_id, msg.picked, v);
      setDs(s);
      setMsgs((x) => x.map((m, i) => (i === n ? { ...m, applied: true } : m)));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSending(false);
    }
  };
  const toggle = (n: number, idx: number) => setMsgs((x) => x.map((m, i) => (i !== n ? m
    : { ...m, picked: m.picked?.includes(idx) ? m.picked.filter((k) => k !== idx) : [...(m.picked ?? []), idx] })));

  return (
    <>
      {!open && (
        <button ref={launcher} type="button" className="helper-launch btn btn-primary" aria-expanded={false} aria-controls="design-helper"
          onClick={() => setOpen(true)}>Ask for help</button>
      )}
      {open && (
        <aside id="design-helper" className="helper-drawer" role="dialog" aria-modal="false" aria-labelledby="helper-title"
          onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } }}>
          <div className="helper-head">
            <h2 id="helper-title" style={{ margin: 0, fontSize: "1.05rem" }}>Design helper</h2>
            <button type="button" className="btn btn-small" onClick={close} aria-label="Close the helper">Close</button>
          </div>
          <div className="helper-log" ref={log} role="log" aria-live="polite">
            {msgs.length === 0 && (
              <p className="small muted">Ask how something works, or what to do next, e.g. “How do I find a cheaper sofa?” or
                “Add a desk and set my budget to $3,000”. Changes are only suggested: you choose what to apply.</p>
            )}
            {msgs.map((m, n) => (
              <div key={n} className={`helper-msg helper-${m.role}`}>
                <p className="small">{m.text}</p>
                {m.reply && navProposals(m.reply.proposals).length > 0 && (
                  <div className="row wrap" style={{ gap: "0.35rem" }}>
                    {navProposals(m.reply.proposals).map((p) => (
                      <button key={p.index} type="button" className="btn btn-small" disabled={!!busy} onClick={() => nav(p)}>{p.label}</button>
                    ))}
                  </div>
                )}
                {m.reply && changeProposals(m.reply.proposals).length > 0 && (
                  <fieldset className="helper-props" disabled={m.applied || sending || !!busy}>
                    <legend className="small">Suggested changes (nothing changes until you apply)</legend>
                    {changeProposals(m.reply.proposals).map((p) => (
                      <label key={p.index} className="small row" style={{ gap: "0.4rem" }}>
                        <input type="checkbox" checked={m.picked?.includes(p.index) ?? false} onChange={() => toggle(n, p.index)} />
                        {p.label}
                      </label>
                    ))}
                    {m.applied ? <p className="small fit-note" role="status">Applied.</p>
                      : m.reply.version !== v ? <p className="small warn">Your design changed since this suggestion; ask again.</p>
                      : locked ? <p className="small muted">Finding furniture is running; apply these when it finishes (or stop it).</p>
                      : (
                        <div className="row wrap" style={{ gap: "0.35rem" }}>
                          <button type="button" className="btn btn-small btn-primary" disabled={!m.picked?.length} onClick={() => applyFor(n)}>
                            Apply {m.picked?.length ?? 0} change{m.picked?.length === 1 ? "" : "s"}</button>
                          <button type="button" className="btn btn-small" onClick={() => setMsgs((x) => x.map((y, i) => (i === n ? { ...y, picked: [] } : y)))}>Not now</button>
                        </div>
                      )}
                  </fieldset>
                )}
              </div>
            ))}
            {sending && <p className="small muted" role="status">Thinking…</p>}
            {err && <p className="small warn" role="alert">{err}</p>}
          </div>
          <form className="helper-form" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <label className="sr-only" htmlFor="helper-input">Your question or request</label>
            <textarea id="helper-input" ref={input} rows={2} maxLength={600} value={text} placeholder="Ask about your design…"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <button type="submit" className="btn btn-primary btn-small" disabled={sending || !text.trim()}>Send</button>
          </form>
          <p className="small muted helper-note">Your messages are sent to the AI; your saved address and photos aren’t. The helper can’t buy anything and may be wrong, so check before you apply.</p>
        </aside>
      )}
    </>
  );
}
