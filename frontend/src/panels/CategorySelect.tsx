import { CATEGORIES, label } from "../types";

/** Category picker for furniture you own. "unmatched" stays a visible, labeled choice: it replaces no purchase. */
export default function CategorySelect({ value, onChange, ariaLabel }: { value: string; onChange: (v: string) => void; ariaLabel: string }) {
  const known = (CATEGORIES as readonly string[]).includes(value);
  return (
    <select value={known ? value : "unmatched"} onChange={(e) => onChange(e.target.value)} aria-label={ariaLabel}>
      <option value="unmatched">choose a type… (replaces nothing yet)</option>
      {CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
    </select>
  );
}
