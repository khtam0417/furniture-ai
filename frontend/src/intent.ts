/** Is a typed message a request to CHANGE preferences, or a QUESTION that should only show help?
 *  Polite requests that name an action ("Can you use more of my budget?", "Could you add a desk?", "Please add a
 *  desk") are changes and go through the validated edit pipeline. Genuine questions ("How does fit work?",
 *  "Where is my list?", "Can you explain the budget?") never change anything. When unsure, it is a question:
 *  showing help is harmless, an unwanted change is not. */
export type Intent = "change" | "question";

const POLITE_START = /^\s*(?:please\s+)?(?:can|could|would|will)\s+(?:you|we|u|i)\b|^\s*(?:may|might)\s+i\b|^\s*please\b/i;
const ACTION = /\b(use|spend|save|add|remove|drop|keep|replace|swap|change|switch|make|set|lower|raise|increase|reduce|cut|only|exclude|avoid|include|stick|go|try)\b/i;
const ASKS_FOR_INFO = /^\s*(?:please\s+)?(?:can|could|would|will)\s+(?:you|we|u)\s+(?:explain|tell|describe|show|help me understand|say)\b/i;
const QUESTION = /\?\s*$|^\s*(?:how|what|where|why|when|which|who|whose|is|are|does|do|did|can|could|should|would|will|may|might)\b/i;

export function classifyIntent(text: string): Intent {
  const t = text.trim();
  if (!t) return "question";
  if (ASKS_FOR_INFO.test(t)) return "question";
  if (POLITE_START.test(t) && ACTION.test(t)) return "change";
  if (QUESTION.test(t)) return "question";
  return "change";
}
