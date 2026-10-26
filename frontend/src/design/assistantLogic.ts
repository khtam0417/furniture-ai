// Design helper: how a reply's proposals are split for display (pure; unit-tested).
import type { AssistantProposal } from "../designTypes";

export type Indexed = AssistantProposal & { index: number };

/** Navigation buttons (go to a step, show a piece). They never change the design. */
export function navProposals(ps: AssistantProposal[]): Indexed[] {
  return ps.map((p, index) => ({ ...p, index })).filter((p) => p.nav);
}

/** Changes the user reviews and may apply; indexes refer to the server's stored list. */
export function changeProposals(ps: AssistantProposal[]): Indexed[] {
  return ps.map((p, index) => ({ ...p, index })).filter((p) => !p.nav);
}
