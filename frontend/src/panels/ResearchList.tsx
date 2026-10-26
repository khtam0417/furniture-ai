import type { ReactNode } from "react";
import type { Research, ResearchResult } from "../types";

/** Web-search leads: cited, relevant results first (up to 4); everything else under "More sources". */
export default function ResearchList({ research, action }: { research: Research; action: (r: ResearchResult) => ReactNode }) {
  const primary = research.results.filter((r) => r.primary);
  const more = research.results.filter((r) => !r.primary);
  const card = (r: ResearchResult) => (
    <li key={r.url} className="research-card">
      <a href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a>
      <span className="small muted">
        {r.domain} · {r.evidence.includes("citation") ? "cited by the search" : "search source"}, not verified
        {r.file_kind === "pdf" ? " · PDF file" : r.file_kind === "image" ? " · image file" : r.file_kind === "file" ? " · file (opens directly)" : ""}
      </span>
      <div className="row wrap">{action(r)}</div>
    </li>
  );
  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <p className="small muted">
        Searched {research.searched_at.slice(0, 16).replace("T", " ")} UTC{research.cached ? " (saved result from a few minutes ago)" : ""}.
        {" "}{research.note}{research.rejected_urls ? ` ${research.rejected_urls} unsafe or private link(s) were hidden.` : ""}
      </p>
      {research.results.length === 0 && <p className="small">No public pages were found for this search.</p>}
      {primary.length > 0 && <ul className="research-list">{primary.map(card)}</ul>}
      {more.length > 0 && (
        <details>
          <summary className="small">More sources ({more.length})</summary>
          <ul className="research-list mt">{more.map(card)}</ul>
        </details>
      )}
    </div>
  );
}
