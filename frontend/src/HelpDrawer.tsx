import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Act } from "./Workspace";
import type { ProjectState } from "./types";
import { classifyIntent } from "./intent";

export type HelpTarget = "place" | "room" | "prefs" | "furnish" | "list";

type Topic = { id: string; title: string; words: RegExp; body: string[]; go?: [HelpTarget, string] };

const TOPICS: Topic[] = [
  {
    id: "fit", title: "How fit works", words: /\b(fit|fits|size|big|small|door|path)/i,
    body: [
      "No tape measure needed. Your room can be drawn from a printed size on your floor plan (“Estimated from floor plan”) or from photos (“Estimated from photos”). Estimates are for seeing an arrangement; they don’t check fit. Only a size you know (your exact plan or a size you state) runs item size checks.",
      "Three different things: product size (from the store page), room size (an estimate from your plan or photos, or a size you know), and doors and walking paths (not checked). “Size check passed” means the item’s listed size plus the space in front of it fits the room size. It is not a promise.",
      "For the whole plan, “Placement needs review” means the room has a known size but something couldn’t be counted, for example a bathroom area or a kept item with no size. Hover it for the reasons.",
      "“Too big for this room” means it can’t fit even at the larger room estimate. A missing size in our saved collection is a different thing from a fit problem.",
    ],
    go: ["room", "Go to Your room"],
  },
  {
    id: "list", title: "Where is my shopping list?", words: /\b(list|shopping|purchas|bought|buy|checklist)/i,
    body: [
      "In “Furnish & compare”, switch from “Your room in 2D” to “Shopping list”. It shows the plan you chose (Save money, Match my style or Closer to my budget): the same furniture as that plan.",
      "Tick “Mark purchased” yourself after you buy something. Opening a store link never marks anything, and this app never buys or pays for anything.",
    ],
    go: ["list", "Open my shopping list"],
  },
  {
    id: "map", title: "How to map my room", words: /\b(map|photo|picture|floor ?plan|draw|2d|room)/i,
    body: [
      "Add your building’s floor plan (from “Your place”) or your own plan image, then “Analyze floor plan” and pick the printed size that is this room. It’s drawn as an estimate; your unit may differ. A plan with no printed sizes stays a reference.",
      "Or add 2 or more overlapping photos from opposite corners. If they show enough of the walls, corners and a size cue (like a door), they may give an estimated outline: an approximate rectangle, not exact walls. If the size can’t be estimated, you’ll see what was observed, not to scale, and no furniture is placed. No measuring needed.",
    ],
    go: ["room", "Go to Your room"],
  },
  {
    id: "budget", title: "How the budget is used", words: /\b(budget|spend|cheap|expensive|price|cost|money)/i,
    body: [
      "Save money is always the cheapest checked set. Match my style follows your budget setting in Preferences (save as much as possible, balanced, or use more for my preferences): it spends more only where an option matches more of your styles or priorities.",
      "Closer to my budget aims for 85–100% of your item allowance (your budget minus what’s held for delivery and tax) using only the furniture types you chose, so you can see what the extra money would buy. A higher price doesn’t mean better quality, and nothing goes over your allowance. It’s a choice to compare, not a purchase.",
    ],
    go: ["prefs", "Change budget approach"],
  },
  {
    id: "stores", title: "Stores and other retailers", words: /\b(store|amazon|wayfair|target|ikea|article|retailer|shop)/i,
    body: [
      "Our saved collection has checked products from IKEA and Article, one from Amazon, plus one incomplete Target listing. You can limit plans to some of these stores in Preferences; the limit also applies to listings you imported.",
      "Amazon, Target, Wayfair and marketplaces open as search links from “Compare options”. They are leads we haven’t checked: paste a product link back to check it. For an Amazon product page we read the selected variant’s price and its product dimensions (not the package size); if the page is unclear or contradicts itself, that fact stays unknown and the item isn’t placed. Our saved collection has only one checked Amazon product so far; other sellers’ prices may differ.",
    ],
    go: ["prefs", "Choose stores"],
  },
];

const EXAMPLES = ["Use more of my budget for better matches", "Save as much as possible", "Could you add a desk?", "Only from Article", "Any store",
  "Switch the style to warm wood", "Add a desk", "Remove the nightstand"];

/** Compact help panel: plain-English preference changes (the same versioned edit pipeline as elsewhere) plus short
 *  how-to topics. Questions never change preferences; it is not a general chat assistant. */
export default function HelpDrawer({ state, act, busy, onState, onGo, onClose }: {
  state: ProjectState;
  act: Act;
  busy: string | null;
  onState: (s: ProjectState) => void;
  onGo: (t: HelpTarget) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [result, setResult] = useState<{ kind: "applied" | "question"; lines: string[] } | null>(null);
  const head = useRef<HTMLHeadingElement>(null);
  useEffect(() => { head.current?.focus(); }, []);
  const demo = !!state.project.is_demo;

  const submit = () => {
    const msg = text.trim();
    if (!msg) return;
    if (classifyIntent(msg) === "question") {  // a question: show help, change nothing
      const t = TOPICS.find((x) => x.words.test(msg));
      setOpen(t?.id ?? null);
      setResult({ kind: "question", lines: [t ? `That looks like a question, so nothing was changed. See “${t.title}” below.`
        : "That looks like a question, so nothing was changed. This box only changes your preferences; see the topics below."] });
      return;
    }
    act("Applying your change", () => api.edit(state.project.id, msg), (r) => {
      onState(r.state);
      setText("");
      setResult({ kind: "applied", lines: r.changes.length ? [...r.changes, ...r.plan_changes.slice(0, 4)] : ["Nothing changed."] });
    });
  };

  return (
    <aside className="help-drawer card" role="complementary" aria-labelledby="help-title"
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h2 id="help-title" ref={head} tabIndex={-1} style={{ margin: 0 }}>Help & quick changes</h2>
        <button className="btn btn-small" onClick={onClose}>Close</button>
      </div>
      <form className="stack" style={{ gap: "0.4rem" }} onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label className="field"><span>Change your plan in plain English</span>
          <input value={text} maxLength={800} onChange={(e) => setText(e.target.value)} placeholder="e.g. use more of my budget, only from Article" />
        </label>
        <div className="row wrap">
          <button className="btn btn-primary btn-small" disabled={!!busy || !text.trim()}>{busy ? `${busy}…` : "Apply change"}</button>
          <span className="small muted">{demo ? "Read by a simple offline rule reader (not AI) in this demo." : "Read by the AI, then checked by the app."}
            {" "}It only changes your preferences (saved as a new version); it can’t chat or answer general questions.</span>
        </div>
        <div className="chips" aria-label="Examples">
          {EXAMPLES.map((ex) => <button type="button" key={ex} className="chip chip-btn" disabled={!!busy} onClick={() => setText(ex)}>{ex}</button>)}
        </div>
      </form>
      {result && (
        <div className={`banner small ${result.kind === "applied" ? "banner-ok" : "banner-info"}`} aria-live="polite">
          <ul>{result.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </div>
      )}
      <ul className="help-topics">
        {TOPICS.map((t) => (
          <li key={t.id}>
            <button className="link help-topic" aria-expanded={open === t.id} onClick={() => setOpen(open === t.id ? null : t.id)}>{t.title}</button>
            {open === t.id && (
              <div className="small">
                {t.body.map((b, i) => <p key={i}>{b}</p>)}
                {t.go && <button className="btn btn-small" onClick={() => onGo(t.go![0])}>{t.go[1]}</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}
