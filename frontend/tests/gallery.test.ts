// Run: npm --prefix frontend test
import { test } from "node:test";
import assert from "node:assert/strict";
import { failureText, foundSummary, originText, pageStatusText } from "../src/panels/galleryText.ts";
import type { Discovery, GalleryItem } from "../src/types.ts";

const FP = "https://www.maplecourt-apts.example/floorplans";
const reader = { service: "Jina Reader (r.jina.ai), public anonymous route", reader_url: "https://r.jina.ai/" + FP, target_url: FP,
  url_source: FP, title: "Maple Court", published_time: "Mon, 26 Oct 2026 10:00:00 GMT", retrieved_at: "2026-10-26T10:00:05+00:00", cache_age: "unknown" as const };
const plan = (name: string, origin: GalleryItem["origin"], extra: Partial<GalleryItem> = {}): GalleryItem =>
  ({ url: `https://cdn.example/${name}.png`, name, alt: "", origin, found_on: FP, seen_at: "2026-10-26T10:00:05+00:00", label: null, plan_type: null, ...extra });
const disc = (gallery: GalleryItem[], pages: Discovery["pages"], extra: Partial<Discovery> = {}): Discovery => ({
  pages, gallery, plan_images: [], plan_pdfs: [], plan_names: [], unit_area_mentions: [], notes: [],
  building: { key: "url:x", kind: "url", name: "Maple Court", address: null, site: "www.maplecourt-apts.example", url: FP }, ...extra });
const blocked = { url: FP, status: "blocked_by_site", detail: "HTTP 403", via: "start" };

test("a reader recovery leads with what was found; the refusal is context, not the headline", () => {
  const d = disc([plan("Studio S", "reader"), plan("1 Bedroom 1 Bath B", "reader")],
    [blocked, { url: FP, status: "ok", detail: "", via: "reader", reader }]);
  const s = foundSummary(d)!;
  assert.equal(s.headline, "Found 2 published floor plans");
  assert.match(s.detail[0], /refused automated reading, so its public page \(https:\/\/www\.maplecourt-apts\.example\/floorplans\) was read through a public page reader \(Jina Reader/);
  assert.match(s.detail[0], /current or cached is unknown; it reports Mon, 26 Oct 2026/);
  assert.ok(!s.detail.join(" ").includes("upload"));  // no contradictory "upload instead" when plans were found
  assert.equal(pageStatusText(d.pages[1]), "read through the public page reader; its copy is saved as a source");
  assert.match(originText(d.gallery![0]), /^From the building’s public page via a public page reader, read 2026-10-26 UTC$/);
});

test("third-party listing plans are never presented as official", () => {
  const g = plan("Studio S", "third_party", { site: "apartments.com" });
  assert.equal(originText(g), "From apartments.com (a listing site, not the building’s own website), read 2026-10-26 UTC");
  assert.match(foundSummary(disc([g], [blocked]))!.detail.join(" "), /listing site you chose \(apartments\.com\), not the building’s own website/);
});

test("when every route fails the explanation is honest and names what was tried", () => {
  const d = disc([], [blocked, { url: FP, status: "rate_limited", detail: "", via: "reader" }], { recovery: [{ url: "x", kind: "page", why: "", status: "failed", found: 0, detail: "" }] });
  assert.equal(foundSummary(d), null);
  assert.equal(failureText(d), "www.maplecourt-apts.example refuses automated reading, and a public page reader couldn’t find plans there either, and the other public pages from your search had no plans.");
  assert.equal(pageStatusText(d.pages[1]), "the public page reader is busy (rate limit); try again later");
  assert.equal(failureText(disc([], [{ url: FP, status: "blocked_by_policy", detail: "", via: "start" }])), "That address can’t be fetched safely, so nothing was read.");
  const svg = disc([], [blocked, { url: FP, status: "ok", detail: "", via: "reader", reader }], { unsupported_plans: [{ url: "https://x.example/1S.svg", alt: "1S floorplan" }] });
  assert.match(failureText(svg), /found no plans|couldn’t find plans/);
  assert.match(failureText(svg), /shows 1 plan drawing as an SVG file, which this version can’t import yet\.$/);
});

test("checked and live origins keep their existing wording", () => {
  assert.equal(originText(plan("A", "checked_reference")), "Published plan, checked 2026-10-26 UTC · not a current vacancy");
  assert.equal(originText(plan("A", "live")), "Found on the building’s website, read 2026-10-26 UTC");
  assert.equal(foundSummary(disc([plan("A", "live")], [{ url: FP, status: "ok", detail: "", via: "start" }]))!.headline, "Found 1 floor plan");
});
