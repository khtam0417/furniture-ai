// Plain-language text for the plan gallery (pure; unit-tested). Never claims every website can be read.
import type { Discovery, GalleryItem } from "../types";

const day = (s: string | null | undefined) => (s ? s.slice(0, 10) : "date unknown");
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

export function originText(g: GalleryItem): string {
  if (g.origin === "checked_reference") return `Published plan, checked ${day(g.seen_at)} UTC · not a current vacancy`;
  if (g.origin === "recovered") return `Found via your web search, read ${day(g.seen_at)} UTC`;
  if (g.origin === "reader") return `From the building’s public page via a public page reader, read ${day(g.seen_at)} UTC`;
  if (g.origin === "third_party") return `From ${g.site ?? "a listing site"} (a listing site, not the building’s own website), read ${day(g.seen_at)} UTC`;
  return `Found on the building’s website, read ${day(g.seen_at)} UTC`;
}

/** Headline + how the plans were found, when there are plans. The original refusal stays in "What we read". */
export function foundSummary(d: Discovery): { headline: string; detail: string[] } | null {
  const items = d.gallery ?? [];
  if (!items.length) return null;
  const count = (o: GalleryItem["origin"]) => items.filter((g) => g.origin === o).length;
  const site = d.building?.site || "The building’s website";
  const refused = d.pages[0]?.status === "blocked_by_site";
  const detail: string[] = [];
  const reader = d.pages.find((p) => p.via === "reader" && p.status === "ok");
  if (count("reader")) {
    detail.push(`${refused ? `${site} refused automated reading, so its` : "Its"} public page${reader?.reader?.url_source ? ` (${reader.reader.url_source})` : ""} was read through a public page reader (Jina Reader, an outside service). Whether that copy was current or cached is unknown${reader?.reader?.published_time ? `; it reports ${reader.reader.published_time}` : ""}. Plan names come from the page’s own plan headings.`);
  }
  if (count("third_party")) {
    const sites = [...new Set(items.filter((g) => g.origin === "third_party").map((g) => g.site).filter(Boolean))].join(", ");
    detail.push(`${plural(count("third_party"), "plan")} from a listing site you chose (${sites}), not the building’s own website; it can be outdated.`);
  }
  if (count("recovered")) detail.push(`${refused ? `${site} refused automated reading, so ` : ""}other public pages from your web search were used.`);
  if (count("checked_reference")) {
    detail.push(`${refused ? `${site} refused automated reading, so a` : "A"} checked list of its published plan images (not every unit variant) is included.`);
  }
  const published = items.filter((g) => g.origin !== "live").length === items.length ? "published " : "";
  return { headline: `Found ${plural(items.length, `${published}floor plan`)}`, detail };
}

/** Why nothing usable was found (only shown when the gallery is empty). */
export function failureText(d: Discovery): string {
  const site = d.building?.site || "The website";
  const first = d.pages[0]?.status;
  if (first === "blocked_by_policy") return "That address can’t be fetched safely, so nothing was read.";
  const readerTried = d.pages.some((p) => p.via === "reader");
  const recovered = (d.recovery?.length ?? 0) > 0;
  const parts = [first === "blocked_by_site" ? `${site} refuses automated reading` : "No floor-plan images were found on the pages we could read (many sites load plans with scripts)"];
  if (readerTried) parts.push("a public page reader couldn’t find plans there either");
  if (recovered) parts.push("the other public pages from your search had no plans");
  const svg = d.unsupported_plans?.length ?? 0;
  return parts.join(", and ") + "." + (svg ? ` The site shows ${svg} plan drawing${svg === 1 ? " as an SVG file" : "s as SVG files"}, which this version can’t import yet.` : "");
}

export function pageStatusText(pg: Discovery["pages"][number]): string {
  if (pg.status === "ok") return pg.via === "reader" || pg.reader ? "read through the public page reader; its copy is saved as a source" : "read and saved as a source";
  if (pg.status === "blocked_by_site") return "the site refused automated access";
  if (pg.status === "blocked_by_policy") return pg.via === "reader" ? "not sent to the reader (not a plain public page)" : "blocked for safety";
  if (pg.status === "rate_limited") return "the public page reader is busy (rate limit); try again later";
  if (pg.status === "rejected") return pg.detail || "not used";
  return pg.detail ? `could not be read (${pg.detail.slice(0, 140)})` : "could not be read";
}
