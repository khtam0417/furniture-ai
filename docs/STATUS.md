# Actual status

Updated 2026-10-26 (fortieth pass, through addendum 14: submission prep in progress). **Working local MVP; not submission-ready.** Source of the early validation figures below:
`docs/INDEPENDENT_VALIDATION.json` (recorded by the project owner's root session). Evidence labels: DETERMINISTIC
(offline unit/API tests), MOCKED AI (pydantic-ai TestModel/FunctionModel), FAKE NETWORK (injected resolver/opener),
REAL FETCH (public pages), HTTP SMOKE (real local server, demo data), ROOT LIVE (live gpt-6-luna calls by root),
ROOT BROWSER (root's browser checks). All are development checks, **not** human-pilot evidence.

## Still pending
Course deliverables: report.html and slides.html (each must state the GitHub URL, and "private" if private); the
GitHub repository (with zlisto access if private) and a clone from that remote; the real-user (friend) pilot. The
older "root's live and browser QA" items are superseded by the root evidence below where it covers them.

## Current ROOT evidence, passes 53–57 (root's live/browser runs, not Claude Code's; not a human pilot)
- **Name search and plan recovery**:
  - 360 State Street, New Haven: the homepage, the short name and the /floorplans path each recover 15 published
    plans (reader after a 403), and the name search passed in a browser.
  - AVA North Point, Cambridge MA: 6 plans from direct HTML; a plan image imports at 921×768.
  - Imported raw source hashes were unchanged and no room was invented.
- **End-to-end browser QA** on an isolated AVA North Point design:
  - Plan and layout: the first of the 6 plans was selected, and the live gpt-6-luna reading mapped 5 areas, with
    one bed only and no furniture in the bath. All 3 layout choices switch, and keyboard moves work.
  - Shopping: New + secondhand search found 4 usable used products (a bed, 2 sofas, a coffee table). The
    Secondhand filter showed them and hid the new ones.
  - Budget: with a modern style, $3,500 budget and 10% reserve, "Choose for me" filled 6 of 6 pieces for
    $2,726.97 (87% of the $3,150 item budget). The bought checkbox persisted.
- **Downloads** (pass 57): both download controls worked in the app.
  - Root read the downloaded `.xlsx` with openpyxl: all 3 sheets, six purchase hyperlinks matching the HTML, total
    $2,726.97, one bought flag kept, no formulas.
  - The HTML had no scripts or external images and showed five placed pieces (the mattress drawn on its bed).
  - Not verified: the root's browser couldn't open `file://` pages (browser policy; not circumvented), and its
    viewport override stayed at 1280 px. So the downloaded page, and the app at phone width, were not
    browser-checked in this run. The app's card looked right on desktop.

## ROOT development checks of the twentieth pass (root's runs, not Claude Code's; not a human pilot)
Real-catalog twin plans (3); checklist selection, mark and undo persisted, including across a server restart;
other-session and other-room isolation; non-member and stale-version marks rejected; swaps don't inherit purchase
status; totals exclude retired items and owned furniture; room, source, envelope and fixed features unchanged during
swaps. Live gpt-6-luna furniture search (twin size, New Haven CT, $200): 12 sources in 10.87 s, cache reused. The
typo matrix passed: Aduban/Audobon (New Haven), Archve; conflicting city/ZIP and unrelated Auburn/Archer rejected.

## ROOT checks after the twenty-eighth pass (root's runs, not Claude Code's; not a human pilot)
- ROOT BROWSER (pass31): Whitehall floor plan only → "Analyze floor plan" → two Bedroom reading cards → chose 10x12
  → estimated 2D room 114 × 138 in. Succeeded with no exact-unit confirmation and no photos.
- ROOT independent Amazon QA (artifact `work/fresh-start/amazon-integration-results.json`, root's folder):
  - Black selected ASIN: $154.55, 60 W / 80 D in.
  - White variant: price null despite carousel prices.
  - The current catalog includes Amazon in Save money and Match my style at $503.53; the near-budget plan is $3,096.
  - A REAL FETCH API import verified the same price and footprint; the original raw source was saved at
    2026-10-26T05:13:36Z.
- An existing Archive plan with no printed dimensions is visible with an honest "reference" status.
- **Still root-pending:** the final browser recheck of this twenty-ninth pass, and the reset. Not all browser QA is done.

## ROOT live check of the design-first map (root's run, not Claude Code's; not browser QA)
Root's live first-pass whole-map read (real gpt-6-luna, plan-map-v1 prompt, 1 request, 21.41 s, input 1149 / output
2823 tokens, cached 0; isolated storage; results in root's `work/apartment-canvas/live-map-results.json`): living,
sleeping, kitchen, bath, closets and balcony detected; both printed sizes read; move/rotate persisted with the map
unchanged; stale edit 409; other session 404; repeated read reused and kept the arrangement; original hash unchanged.
Limits root saw: the sleeping zone was too narrow (its printed ratio was rejected) and the living zone partly overlapped
the kitchen; the map is approximate. Browser QA of the new UI is still pending.

## Thirty-second pass (2026-10-26): root review fixes for the design-first flow
**341 backend tests passed** (5 new regressions, 1 updated); 8 frontend unit tests passed; frontend typecheck +
build passed. No live AI, no server restart, no git, no reset. Not browser-checked by Claude Code; no physical
touch-device test.
- **Scale crash fixed**: conflicting printed sizes (root's case: two 10'x10' rooms drawn 120 px and 360 px on a
  1000 px image) crashed `validate_map` (median of an empty list). Now a printed scale comes only from one consistent
  printed room or the unique largest agreeing group (2+, within 25%); otherwise a relative drawing scale with a
  visible "printed sizes disagree" note, also when no furnishable room survives.
- **Polygon validation**: repeated non-adjacent vertices, a vertex touching a non-adjacent edge, collinear overlaps
  and retraced spikes are rejected; L- and U-shaped rooms are still accepted.
- **Prompt v2** (`plan-map-v2-open-zones`): open-plan zones are flagged `open_plan` and are never walls; walls are
  only physical wall lines; printed sizes are cross-checked against outline proportions. v1 maps are not reused (the
  cache key includes the prompt version), so the next read is a new call. No plan-specific fixture is hard-coded.
- **Canvas**: zone outlines are thin dashed areas, not navy walls; walls come only from `map.walls`. "Compare with
  the original plan" hides the vector map and shows the image as is (furniture optional). Draggable pieces use
  `touch-action: none` from pointerdown; pointercancel cancels without saving; leaving the canvas no longer commits;
  drags are ignored while busy.
- **Budget**: "Choose for me" now honors the whole-design item allowance, counting products already chosen and every
  instance (root's case: two nightstands, one $80 product, $100 budget, no reserve: one chosen, the other missing
  with "the cheapest match ($80.00) would go over your item budget ($20.00 left)", status incomplete, not over).
  "Use my budget" now prefers more style matches, then steps pieces up toward 85–100% of the item budget where pricier
  options that keep their style matches exist; unused budget is reported with the reason; no padding, no quality
  claims. The reserve is "set aside for delivery and tax; actual checkout costs may differ".
- **Starter set**: a new whole-place design no longer inherits the first room's categories: a bed set in every
  bedroom/sleeping zone and a sofa + coffee table in the main living zone (old room preferences unchanged).
- **Unsaved budget/style**: Next and forward step clicks on "Choose furniture" save first ("Save and continue");
  Back keeps the draft and shows an unsaved banner.

### Fortieth pass, addendum 14: submission prep (IN PROGRESS; version frozen, no feature work)
**Latest validation (passes 67/68, run by root through approved tools):**
- Backend: 46 focused cases passed cumulatively.
- Frontend: 39 unit tests passed; typecheck and production build passed.
- No full-suite rerun is claimed here.

**Added or changed in this pass** (file edits only; nothing was run, copied or published by this session):
- **`tools/package_submission.py`:** a deterministic, ALLOWLIST-ONLY staging export (`--dest <new empty folder>`,
  `--dry-run`).
  - **Copies:** app source, backend tests, frontend source + `frontend/dist`, `requirements.txt`, `run.sh`,
    `serve.py`, `.env.example`, `.gitignore`, the README, `data/catalog/{products,curation}.json`,
    `data/property_refs/*.json` (both read at runtime and by tests), submission-relevant docs and small tools.
  - **Never copies:** `.env*` (except `.env.example`), `.venv`, `node_modules`, `storage`, SQLite databases, uploads,
    `data/catalog_raw`, `prompts`, `output` (private backups), `.scratch`, caches or `.DS_Store`.
  - **Safeguards:** refuses a destination inside the repo or a non-empty one, and scans staged text for
    credential-looking strings (reporting the file and kind, never the value). It writes `MANIFEST.sha256`.
  - **Not included:** the raw catalog snapshots (git-ignored, not redistributed). The test that reads one skips when
    it's absent.
- **README:** a reviewer quick start covering Python 3.12, the parent `.env`, `./run.sh`, port, the synthetic
  Example bedroom/studio demo, the live Archive 1-bedroom New-only $3,000 flow (needs network, not guaranteed),
  offline tests, what data is and isn't included, and the secondhand 403/robot-check limits. The architecture
  section now lists all four typed agents and the web-research call.
- **`.gitignore`:** also ignores `.scratch/`, `prompts/`, `*.sqlite3` and `.claude/`.
- **`docs/LECTURE_MAPPING.md`:** re-audited. It now lists four agents (plan map, room evidence, preference edit,
  design helper) and web research, with tests named.
- **`docs/submission_outline.json`:** a 12-page report outline (8 sections in the required order) and 9 slides.
  Every real-run screenshot, token count, cost, pilot result, sourced number and the GitHub URL is a
  `NEED_ROOT_EVIDENCE` placeholder. No final HTML is built yet.

**Still to do (root):**
- Run the packaging script into a new folder and do a fresh-clone rehearsal with the parent `.env`.
- Create the GitHub repository (zlisto access if private).
- The live Archive demo, with screenshots and ledger numbers.
- The pilot user.
- Build `report.html` and `slides.html` from the outline and evidence.

### Fortieth pass, addendum 13: marketplace circuit breaker (refusing sites skipped, not retried)
**Why:** in production, "Find furniture" showed queen bed frame: 5 blocked and mattress: 4 blocked. eBay listing pages
returned HTTP 403 again and again, AptDeco (and the public page reader's copies) showed robot checks. Chairish is
readable but often not affordable. This fix stops spending searches and checks on refusing marketplaces. It does
NOT create affordable supply or solve stock: with every selected marketplace refusing, nothing can be found.

**Checks (root):**
- **First run:** backend 35 passed, 1 failed; frontend 39 passed. The failure was the mattress test checking that the
  query text started with "Used ", but the gateway input carries a wrapper prefix. That test now checks the query
  substring "Used <size> size mattress listings".
- **Partial-skip message:** it no longer claims other marketplaces were searched. It now reads "Further checks
  skipped for eBay (listing pages refused automated access)."
- **Final focused rerun:** pending.

File edits only here. No production data, sessions, ledger rows or saved designs changed; no live paid calls.

**Changes** (`design_api.py`; prompt version `furniture-products-v4-eligible-sites`, so older cached searches aren't
reused):
- **Search query:** the first used search AND "Search more" both name ONLY the user's selected marketplaces that are
  currently eligible. Eligible means none of their pages refused automated reading in this session and place within
  24 h, for any piece type. The selection is never broadened, and no site is banned globally.
- **No retry:** the old "retry the refusing sites when nothing else came back" is removed. A refusing site's results
  are counted (`skipped_refusing`), never checked.
- **All selected sites refusing:** no AI search and no page check. The branch reports status `unavailable`, naming the
  sites and pointing to Shopping preferences (other marketplaces, or new items). There's no Search more, the per-piece
  search answers 409 with the reason, and new items are never substituted automatically.
- **Within a round:** after a batch, a page that refused automated reading stops further checks on that marketplace;
  other marketplaces' pages go on. The bounds are unchanged: 2 at a time, up to 12 pages, stop at 3 ready, price and
  fit gates.
- **What counts as a refusal:** HTTP 403/429/401, sign-in, robot check, "blocked". Expired (404/410), sold, wrong-type,
  incomplete pages, and the app's own refusals (off-site redirect, compressed response) never mark a site.
- **Messages:** the queue and per-piece lines name the skipped marketplaces ("further checks skipped for eBay: listing
  pages refused automated access"), with no claim about other sites. When results came back only from refusing sites, they say so instead of
  "no product pages found". Nothing suggests waiting a few minutes.
- **Mattress searches:** they ask for "the mattress only: not bed frames, bases, foundations, box springs or bed sets".
  Used mattresses aren't excluded by policy, and the category gate is unchanged.

**Tests (pending root run):**
- `backend/tests/test_supply_and_review.py`:
  - the first test is updated on purpose: eBay's later pages are skipped within the round (3 checked, was 5), and the
    next search excludes eBay;
  - new: all selected refusing (no AI search, no check, no Search more, 409 per piece, never broadened); 404/sold never
    mark a site; strict selected-site boundary; mattress-only query.
- `frontend/tests/findQueue.test.ts`: new describeGroup test (named unavailable sites, no fake "no product pages
  found", no "minutes").

**Limitation:** a site's refusal lasts the 24 h window for this session and place. Remove that marketplace from the
selection, or choose new items, to search elsewhere sooner. Supply on the readable marketplaces (Chairish) stays
thin and often above budget.

### Fortieth pass, addendum 12: budget-first selection, recoverable over-budget choices, bounded affordable search
**Why:** a user saw a $14,500 used Chairish sofa offered as a ready, choosable recommendation on a $3,000 budget, plus a
$2,250 coffee table. Style ranked ahead of price, and Choose stayed enabled.

**Checks (run by the root through approved tools; this pass itself used file edits only):**
- **Frontend:** 38 unit tests passed and the production build passed.
- **Backend:** 59 passed, 3 failed. All 3 failures came from an invalid test-fixture URL: `_used` in
  `test_budget_selection.py` put `coffee_table` (underscore) into a Chairish slug, which the strict allowlist rejects
  (it accepts hyphens only). The fixture now uses hyphens; the allowlist is unchanged. The final backend rerun is
  pending.
- The $14,500 sofa exclusion and the 422 refusal already passed.

No live paid calls; no production data, sessions, ledger rows or saved designs changed; nothing restarted. Tests:
- **Backend:** `test_budget_selection.py` (new) and the updated `test_find_furniture.py`, then `test_supply_and_review.py`,
  `test_source_boundary.py`, `test_selection_logic.py`, `test_budget_variety.py`, `test_design.py`,
  `test_shopping_flow.py`, `test_checklist_export.py` and `test_limits_and_speed.py`.
- **Frontend:** the unit tests (2 new tests in `findQueue.test.ts`), typecheck and build.

**Changes:**
- **Price feasibility outranks style** (`design.candidates_for`). Each option carries `within_budget` (within the whole
  remaining item budget; with a budget set, the price must be KNOWN), `affordable` (also within this piece's planning
  share) and `blocked` (why it can't be chosen). The sort is: fits first, then affordable, then within the whole
  budget, then style (or price for "Keep costs low").
- **Recommendations** (`recommendable`): only options that fit or aren't placed yet, are available, aren't picked for
  another piece, and are within the share AND the whole budget.
  - `GET /design/previews` shows only these. `total*` count them, and `total_all`, `held_back` and `held_text` explain
    what was held back (e.g. "1 checked option not recommended: 1 was above the item budget left. Looking for
    affordable options that fit."). An excluded luxury listing never produces "1 option ready".
  - `GET …/products` defaults to `scope=recommended`.
  - The explicit `scope=within_budget` also lists options above the share, flagged ("Choose anyway (above its share)"),
    and ones that don't fit (not choosable in the UI). It NEVER lists an option over the whole remaining item budget.
- **Server-side guard** (`POST …/product`): a product over the whole remaining item budget is refused with 422 and the
  exact figures, e.g. "Not chosen: it costs $14,500.00, but only $2,700.00 of your item budget is left for this piece
  ($2,700.00 after 10% held for delivery and tax). Your design is unchanged…". "Choose for me" already had a hard
  ceiling and now also keeps the share reserved for any piece under budget review. The helper never chooses products.
  The used-listing-is-one-item and source/condition gates are unchanged.
- **Earlier over-budget choices** (`design.budget_review`):
  - When the chosen products TOGETHER exceed the item budget, each one priced above its plain share of the whole item
    budget is flagged. It is never removed or changed.
  - Flagged products are left out of `committed`, the spend that planning targets, search price ceilings and the
    choose guard are based on. So the pieces can be repaired one at a time.
  - Planning treats them as open pieces, so they get a replacement share and are searched again by `find-plan` and
    `find-group`.
  - The budget summary has `budget_review` and status "incomplete" (never "complete"). The checklist has
    `budget_review` and status "incomplete".
  - UI: a budget-box banner with "See cheaper options"; a piece-row chip "Needs replacing: over budget" with "See
    cheaper options" and "Remove this product (keep the piece)".
  - There is no automatic "replace": with the flagged product cleared, a recalculation could leave the piece with
    nothing, so the user picks the replacement.
  - Production case, as tested with fixture products: $3,000 with 10% held = $2,700. Shares: sofa $2,193.75, coffee
    table $506.25.
    - Both chosen products ($14,500 and $2,250) are flagged.
    - A $1,500 sofa can then be chosen. After that, a $2,250 coffee table is refused ($1,200 left), a $400 one is
      accepted, and the review clears.
- **Search** (`online_query`, `research.FURNITURE_PROMPT_VERSION = furniture-products-v3-affordable`):
  - The price ceiling comes FIRST in the query, with "affordable everyday pieces at or below $X; skip designer, antique
    or collectible listings above that price". Style stays secondary. Results come from several sellers/stores (approved
    sources only). The new prompt version means v2 cached results aren't reused.
  - **One search result per round:** up to `MAX_LEADS = 12` approved product/listing pages are checked, at most two at
    a time and never more than still needed. The round stops once `need` distinct ready options exist (design key; a
    used listing is always its own). `need` is 3, or one per piece in the group.
  - **Check order:** results whose untrusted search text clearly states a price above the target, and colour-only
    duplicate titles, are checked after the rest. Each page is still verified, and no price is ever taken from search
    text.
  - **New branch:** it skips the web only when 3+ distinct saved new options fit and are affordable (`ready_existing`),
    not just any 3 saved products.
  - **Search more:** "Search more" (`needs_refine`) is offered while fewer than 3 ready options exist (so also with 1–2).
    It is explicit, at most once per type, and works for new items too.
  - **Results:** `find-group` returns `options_ready`, `pieces`, `held_back` and `held_text`. A verified page above the
    budget counts under the reason `over_budget`, not "verified".
- **Pieces vs options** (Choose):
  - "Shopping for 2 pieces in your layout. Missing a bed or another piece? Add furniture in Arrange your space." Each
    row is one design piece, not one search; pieces of the same type and size share one search but keep their own
    choices.
  - An "Add furniture / review rooms" button goes to Arrange (existing step navigation).
  - When no confirmed bedroom exists and some areas are unread or unsure, Choose and Arrange say so plainly. A bedroom
    is never guessed from a "1 bedroom" label, and no bed is auto-seeded; the user can set a room's use or add a bed
    or bed set.
  - Removals and existing designs are kept.
- **Tests:**
  - Two intentional behaviour updates in `test_find_furniture.py`: a $900 option against $800 left is no longer
    choosable (422) or listed; a used listing picked for another piece is held back by default and shown blocked in
    the broader view.
  - New `test_budget_selection.py`:
    - exact 3000/10% sofa and coffee table;
    - cheaper close style before an expensive exact match;
    - flagged/searchable/one-at-a-time repair;
    - Choose for me keeps flagged choices;
    - the 12-page bound, stopping at 3, sold and NEW-condition pages not counted;
    - price-hint ordering;
    - Search more with 2 options, and pieces retained;
    - the new branch searches when saved options are unaffordable.

**Remaining limits:** affordable secondhand supply is still thin (see addendum 11). A price stated in search text is
only an ordering hint. Fit on plans without printed sizes is relative. The production design keeps its two flagged
products until the user replaces or removes them.

### Fortieth pass, addendum 11: honest AI allowances, cheaper "Find furniture", bounded parallel checks
**Checks:**
- **Backend:** 468 tests passed, 7 new in `test_limits_and_speed.py`. Each run used a 50 s faulthandler guard and
  unfiltered output.
  - The concurrent-request tests run on ONE event loop through `httpx2.AsyncClient` + `ASGITransport`, not threads
    with separate loops (the pass-62 hang).
- **Frontend:** 36 unit tests passed, 3 new; typecheck and build passed.
- No live paid calls. No production data, sessions or ledger rows changed; nothing restarted.

**Changes:**
- **Allowances** (`config.py`, `usage.py`):
  - Defaults: an estimated $2.00 lifetime allowance per browser session (was $0.50), $3.00 per UTC day app-wide,
    and 12 AI requests per session per rolling ten minutes. The production session at about $0.50 can continue.
  - Overrides: `FURNISHAI_SESSION_AI_BUDGET_USD` (> 0, ≤ 20), `FURNISHAI_DAILY_AI_BUDGET_USD` (> 0, ≤ 100) and
    `FURNISHAI_AI_REQUESTS_PER_10MIN` (1–120). Values are validated; an invalid one raises `ConfigError`, which names
    the key.
  - Reservations stay atomic, and settled actual costs plus unsettled reservations both count.
  - `LimitExceeded` now has a kind. Plain-language messages:
    - session: "would be exceeded … doesn't reset by waiting; the app owner can increase it", with no setting names;
    - daily: resets at the next UTC day;
    - rate: clears as the rolling ten-minute window passes.
  - Stable prefixes (`is_limit_message`) keep queue pauses reliable, and limit failures are never generic retries.
    The misleading "continue in a few minutes" text is gone.
- **Cost:**
  - One "Find furniture" click searches every needed type once; the automatic second paid sweep is removed.
  - "Search more for N piece types" is explicit: only for types with nothing usable, never re-offered once refined,
    and it explains the extra cost.
  - Continue keeps "searching more" only when the search settings are unchanged. Saving changed settings (also via
    "Save & find", "Search more" or Continue) clears old results and runs a fresh first pass, with a short message.
    While settings are unsaved, those buttons are replaced by a one-line explanation.
- **Speed without extra requests:**
  - Page checks within a group run at most 2 at a time: an app-wide thread semaphore, results in round-robin order
    (`checked_urls`), each failure isolated, and the short-lived check cache reused.
  - Content-addressed storage now writes through a per-thread temp file name.
  - `cached_research` shares ONE in-flight task per session + place + kind + query:
    - Waiters share the result or the error.
    - Each waiter is shielded, so a disconnect doesn't cancel the others.
    - The entry is removed only when the task is done, and failures are never cached; a later explicit attempt
      retries.
- **Offline benchmark** (`docs/evidence/offline_search_benchmark.md`; SIMULATED, equal mocked 80 ms per page, same
  mocked result, not a live measurement):
  - Median time: 0.594 s with 1 check slot vs 0.372 s with 2.
  - Same 6 page requests and identical decisions (5 verified, 1 blocked); peak concurrency 2.
  - Two concurrent identical searches plus a cached repeat made 1 mocked AI search request.
  - Tests also cover a shared failure (both waiters get 502, one request, nothing cached, a later retry works),
    waiter cancellation, cache expiry, one failed fetch, cache hits and ordering.

**Remaining resale limits (unchanged, from the live runs in addendum 9):**
- eBay refuses automated reading.
- AptDeco listings found by search were mostly sold, expired or challenged.
- Craigslist posts often expire.
- Chairish is readable but designer-priced.
- Parallel checks make a run faster but don't create more affordable supply.

### Fortieth pass, addendum 10: helper/form sync, completion pass, small accuracy fixes
**Checks:**
- **Backend:** 461 tests passed. 2 are new in `test_selection_logic.py`; `test_design_assistant.py` adds a check that
  the saved budget drives the planning targets.
- **Frontend:** 33 unit tests passed, 2 new in `prefsDraft.test.ts`. Build passed.
- No network run: these are local state/allocator fixes, and addendum 9's live evidence stands.
- No production data or servers touched.

**Changes:**
- **Helper/form sync** (root's release-blocking repro: helper sets $3,000, but the Choose form kept its stale $3,500
  draft and showed "unsaved changes", which could overwrite the helper's save on the next search):
  - Settings saved elsewhere now flow into the form field by field (`prefsDraft.ts`). A field the user hadn't
    touched follows the saved value. A field the user changed keeps their edit and stays visibly unsaved, and a
    typed budget is never replaced.
  - The helper's Apply is locked while "Find furniture" runs (the finding state is shared with the workspace).
- **Allocator:**
  - A bounded completion pass runs after the first pass and before any upgrade. It retries a piece skipped above
    its initial share once the others' real prices are known, keeping a reserve for every piece still missing (its
    cheapest fitting option capped at its target, or its full target when it has none).
  - Root's example: a $1,000 bed plus five pieces totalling $500 now fills all six ($1,500 of $3,150), with the fit
    gate unchanged.
  - Notes quote the true cheapest fitting option, not the style-ranked first one.
  - A fully spent budget gives open pieces a $0 target, not an invented 1 cent.
- **Copy:** the helper's footer now reads "Your messages are sent to the AI; your saved address and photos aren't."

### Fortieth pass, addendum 9: light/dark theme, design helper, honest supply fixes, live six-category result
**Checks:**
- **Backend:** 459 tests passed. 12 are new: 8 in `test_reader_supply.py` and 4 in `test_design_assistant.py`. One
  expectation in `test_supply_and_review.py` was updated, because a refusing marketplace is now skipped instead of
  checked last.
- **Frontend:** 31 unit tests passed, 5 of them new (theme, helper, source line, queue text, affordable coverage).
  Typecheck and build passed.
- No production data touched, no server started or restarted, `.env` untouched, no email.
- The root's browser verification of the dark `.pc-label` halo is the root's; not redone here.

**Changes:**
- **Selection:**
  - `planning_targets` keeps an affordable complete-set split. Shares sum to at most what's left, and every open
    piece, known or not, gets a positive share.
  - A known cheapest price can rebalance a target only when the whole plan stays affordable: all known minimums fit
    and every other piece keeps at least half its share.
  - Known minimums count only options that fit the plan.
  - Regression for the root's case: known bed $2,495, coffee table $2,140, nightstand $379 and dresser $600 keep
    the plain $3,150 split, with the bed at $630.
- **Listing identity and challenges:**
  - Primary product matching falls back to the marketplace's own listing id (`resale.listing_id`), never "the
    first". A sold Chairish listing that redirects to a collection page is reported as "no longer online" instead
    of "several products".
  - Robot-check detection adds AWS WAF and Anubis/proof-of-work markers, in both the direct fetch and the reader.
  - A real false positive was fixed (found in live run 1): Chairish listing pages carry reCAPTCHA settings for their
    login forms, and the bare word "captcha" wrongly marked them as robot checks. Now only explicit challenge
    markers count, or a captcha mention on a small page with no product data.
- **AptDeco public-reader evidence path:** `READER_RESALE_SITES = {"aptdeco"}`, used only after a direct robot
  check, and only when the reader is enabled.
  - **Identity:** the reader copy must be the same listing id.
  - **Parser:** `parse_aptdeco_copy` reads the listing's own heading (levels 1–3, exactly one), its current price
    (not Est. retail, not related cards), "Sold / Expired", Product details (condition, overall W/H/D) and the
    availability date. A past date or "Sold / Expired" means unavailable. The listing's stated delivery/pickup lines
    are kept as text.
  - **Gates:** refurbished, damaged and floor-model items stay distinct from used.
  - **Evidence:** the raw reader reply is stored immutably with its reader provenance; snapshots carry
    `read_via="public_reader"` and freshness "unknown".
  - **Display:** cards and checklist rows show "from a public copy of the listing page read on <date> … how current
    that copy was is unknown" with "Open the listing". The export says the same.
  - **Not extended to HTTP 403:** an explicit refusal is reported, not routed around.
- **Supply:**
  - Leads on a marketplace that refused reading in the last 24 h are skipped (counted as `skipped_refusing`) while
    others exist.
  - Expired listings (404/410, or a redirect to a category) are reported as "no longer online".
  - Searches ask for currently listed items with a shown price and, in the second pass, to skip designer/antique
    pieces far above the piece's share.
- **Style and variety:**
  - Used listings get style cues from their own title, labelled "a cue from the listing title".
  - `design_key` keeps materials, structure and size: it merges only colour variants of the same store model at the
    same footprint, and never generic names or used listings.
- **Choose step:**
  - Piece rows show the queue's live state.
  - Choose, per-piece searches, checks and review actions are locked while finding runs.
  - Coverage separates "fits the plan and its share" from "fits but costs more".
  - Fit text says it's an estimate, and the "same spot" copy is corrected.
- **Theme:** Light / Dark / System toggle (`theme.ts`, `ThemeToggle.tsx`), saved in localStorage and applied before
  first paint. "System" follows the device live. Dark CSS variables include the clean plan (`--plan-*`), and text on
  strong fills uses `--on-strong`/`--on-teal`. All dark pairs are ≥ 7:1 (computed). The downloads stay light.
- **Design helper** (`assistant.py`, `AssistantPanel.tsx`):
  - **Call:** one bounded gpt-6-luna call per message through `run_agent` (ledger and limits), with a typed
    `AssistantOutput` and an accurate guide to the four steps. The legacy HelpDrawer topics aren't used.
  - **Answers:** questions return answers and navigation only.
  - **Changes:** requests return code-validated proposals. They're stored per session, apartment and version, and
    applied once via `/assistant/apply` (re-read from the server copy; an old version gets 409; other sessions
    get 404).
  - **Privacy:** the model never sees the address, unit, building, images, pages or links. Links are stripped from
    replies.
  - **Offline:** a step pointer only. The drawer is keyboard-accessible (Esc closes and returns focus) and becomes
    a bottom sheet on phones.
- **APIs:**
  - New `POST /api/apartments/{id}/design/assistant` (`{message, step, expected_version}`) →
    `{reply, intent, proposals, dropped, proposal_id, version, mode}`.
  - New `POST /api/apartments/{id}/design/assistant/apply` (`{expected_version, proposal_id, accept[]}`) → design
    state.
  - `GET /design/previews` adds `fitting_affordable`.
  - Candidates and checklist rows add `read_via` and `freshness`.
  - The find-group used branch adds `skipped_refusing`.

**LIVE six-category secondhand retrieval:**
- **Setup:** Claude Code, real gpt-6-luna web search, real page checks and the public reader, on copies of the
  root's QA storage restored to design v5 ($3,500, 10% reserve, modern, queen, secondhand only, either). Each run
  used its own fresh test session; the root's copy was opened read-only.
- **Targets:** $630 bed, $709 mattress, $158 nightstand, $394 dresser, $1,024 sofa, $236 coffee table, summing to
  $3,150.
- **Evidence:** kept in `.scratch/iso_partial_run1.json` (+ its DB), `.scratch/iso_results_run2.json` and
  `.scratch/iso_results_run3.json`.

| Run | AI searches / spend | Page checks (reader reads) | Pieces with an option that fits the plan | …and within its share |
|---|---|---|---|---|
| 1 (interrupted) | 5 / $0.181 | 27 | n/a. Every Chairish check was wrongly a "robot check" (the reCAPTCHA false positive, fixed) | n/a |
| 2 | 11 / $0.347 | 46 (13 AptDeco reads, all sold/expired or challenged); eBay 403 ×13 | 5 of 6 (mattress none) | **1 of 6** (dresser $350, auto-chosen) |
| 3 (eBay skip + new wording) | 12 / $0.370 | 40 (eBay only 3; Chairish 24, 9 verified) | 5 of 6 (mattress none) | **0 of 6** |

Per piece in run 3:
- **Bed:** Chairish $2,495 and $2,835 (both fit only if moved within the room).
- **Mattress:** none. Chairish results were beds or sets, and the Craigslist post had expired.
- **Nightstand:** $379, $490, $585.
- **Dresser:** $600–$1,976.
- **Sofa:** $1,800, $2,750, $3,397.
- **Coffee table:** $1,895–$2,250.

"Choose for me" chose nothing rather than spend the set on one piece, and gave a specific reason for every piece.
Nothing was placed outside a room, no new item was substituted, and nothing was invented.

Honest conclusion:
- With "secondhand only" and these approved marketplaces, current, machine-readable listings within an affordable
  share are scarce.
  - **eBay** (the broadest affordable supply) refuses automated reading.
  - **AptDeco** pages need the reader, and the copies found were mostly sold/expired or challenged.
  - **Craigslist** posts in search results were often expired.
  - **Chairish** is readable but skews designer/antique.
- The app now reports this per piece. The user's levers are a higher budget, "New + secondhand", marking owned
  pieces, or choosing per piece.

**Limits:**
- The live outcome depends on what web search returns in that minute; runs 2 and 3 differed (the $350 dresser
  appeared only in run 2).
- AptDeco is the only marketplace read through the reader, and its own challenge sometimes blocks the reader too.
- Delivery/stock of used listings is never verified.
- The helper can be wrong, and only its proposals of the listed kinds can be applied.

### Fortieth pass, addendum 8: complete-set selection, physical fit, secondhand supply, charcoal/teal look
User direction 2026-10-26: every requested piece must stay represented and get searched, with real choices, no
colour-only alternatives, and a palette refresh. The reported failure: $3,500 budget, 10% reserve, modern, queen,
secondhand only, New Haven CT 06510, either fulfillment. A $2,495 Chairish Mission oak queen bed (64×87.25 in) was
auto-chosen, extended outside the bedroom, and left 5 pieces empty while the queue was still running.

**Checks:**
- Backend: 447 tests passed.
  - 11 new: 7 in `test_selection_logic.py` and 4 in `test_supply_and_review.py`.
  - 4 updated to the new rules: 3 in `test_design.py` that encoded the removed 85–100% price step-up, and 1 in
    `test_shopping_flow.py` for the bounded extra batch.
- Frontend: 26 unit tests passed, 3 new; typecheck and build passed.
- No production server restart; production data was only read.

**Changes:**
- **Selection** (`design.py`):
  - Physical problems are now hard or soft. Hard: outside its room or the map, on a fixed or door area,
    overlapping a piece, a mattress that doesn't fit its frame. Soft: larger than the draft, room use unconfirmed,
    TV wider than its stand.
  - `fit_for` judges a candidate in the CURRENT arrangement, regardless of any earlier baseline: fits / moved (a
    conflict-free spot in the SAME confirmed room, same size, nothing else moves) / conflict / not_placed.
  - `planning_targets` gives every open piece a share of the item budget left, the attached mattress included
    (`PLAN_WEIGHT`). A known cheapest price can raise a target up to 1.5× its share, no further.
  - `auto_choose` fills the whole set first, under a hard ceiling. It never takes a conflicting option and checks
    picks together as it goes. Other open pieces' targets are reserved, and nothing is upgraded while any piece is
    missing. "Use my budget" only swaps for more style matches; the 85–100% price step-up is removed.
  - `collapse_variants` / `design_key` merge colour/finish variants of one store design; used listings are never
    merged.
- **Secondhand supply** (`design_api.py`, one shared `used_round` for "Find furniture" and the per-piece button):
  - **Query:** the piece's planning target as the price; local pickup + US delivery when "either"; public
    city/ZIP only.
  - **Checks:** round-robin across the chosen marketplaces, with marketplaces that refused reading in the last
    24 h tried last (never bypassed). Up to 3 checks, then up to 3 more from the SAME result when fewer than 2
    usable options (verified, fitting, within target).
  - **Second pass:** after ALL piece types, ONE alternate search ("affordable … several different designs",
    preferring marketplaces that didn't refuse) for a type whose first pass found nothing usable. It stops on the
    existing AI limits.
  - **Allowlist:** AptDeco listings appear as `/product/<slug>` in real results, so the strict AptDeco listing path
    now accepts the singular as well as the plural.
  - **Honest reasons:** robot-check pages are reported as "couldn't be read (robot check)" instead of "condition
    not shown", and expired 404/410 listings as "no longer online".
  - **Evidence gates unchanged.**
- **API changes** (exact):
  - `POST /design/find-group` takes `{key, refine?}` and returns `options_fitting`, `needs_refine` and `refine`.
    Its used branch adds `target_cents`, `leads`, `good`, `sites`, `refusing`, `refined` and `needs_refine`.
  - `GET /design/find-plan` groups now include pieces whose chosen product doesn't fit.
  - `POST /design/auto-products` takes `{expected_version, replace_ids?}`: products are cleared and re-chosen, but
    owned and bought pieces are kept and nothing is deleted.
  - New `POST /design/items/{id}/fit` ("Move it inside the room").
  - `GET /design` adds `evaluation.review` (chosen pieces that don't fit, with `can_move`) and
    `evaluation.targets`.
  - `GET /design/previews` and `GET /design/items/{id}/products`: candidates add `placement`,
    `budget_target_cents`, `over_target_by_cents`, `open_pieces`, `design_key` and `variants`; previews add
    `fitting` and `target`.
  - `POST /design/items/{id}/product`: a pick that would conflict but fits elsewhere in the room is moved there (and
    said so); a still-conflicting manual pick is allowed, with the problem stated.
- **UI:**
  - "Choose for me" is disabled while finding runs, with the reason.
  - The queue runs a second pass ("(second search)").
  - Coverage reads "N of M pieces have an option that fits".
  - Review banners offer explicit move/replace actions, plus a "Replace the pieces that don't fit" button.
  - Option cards show fit and budget on separate lines. The misleading "Fits the $3,150 left for this piece" is
    gone; cards now read e.g. "$1,865 over this piece's share ($630 of $3,150 for 6 open pieces)".
  - Palette refresh across the app and the printable checklist: cool charcoal #25313a, soft white #f5f7f8, teal
    #0f766e (WCAG ≥ 4.5:1, computed), with CLAUDE.md's visual direction updated.

**REAL bounded retrieval (Claude Code, live gpt-6-luna web search + real page checks) on an ISOLATED COPY of the
user's data**, made with the sqlite backup API into a temp folder:
- **Setup:** in the copy only, products were cleared and the reported settings applied. Production storage was
  opened read-only.
- **Runs:** 11 AI web searches (6 first passes, 5 second passes). The 6th second pass stopped at the existing
  session AI budget ($0.50), as designed.
- **Planning targets** with $3,150 for 6 open pieces: bed $630, mattress $709, nightstand $158, dresser $394,
  sofa $1,024, coffee table $236.

| Piece | Checked (first / second) | Outcome |
|---|---|---|
| Queen bed frame | 6 / 1 | 2 verified, both Chairish ($2,495 Mission oak; $2,835 Henredon), both fit only if moved within the bedroom. Others: eBay 403 ×2, AptDeco robot check ×3, Craigslist expired ×1. Not auto-chosen: far over its $630 share. |
| Queen mattress | 3 / 2 | No usable used mattress: eBay 403 ×3; the second pass found a Chairish bed (wrong type) and an AptDeco robot check. Stays missing with the reason; nothing new is substituted. |
| Sofa | 6 / 3 | 1 verified: a $10,000 Kagan sofa. AptDeco robot checks, eBay 403s. Not chosen. |
| Dresser | 6 | 3 verified (Chairish $350, $600, $1,150). **Auto-chosen: $350 "Short Vintage Wooden Dresser"**, within its $394 share. |
| Coffee table | 6 / 3 | 6 verified, all Chairish, $795–$2,895. None within its $236 share, so none auto-chosen; all shown with fit and budget lines. |
| Nightstand | 6 / 0 | 2 verified (Chairish $379, $585), over the $158 share. The second pass was stopped by the session AI budget. |

"Choose for me" result in the copy:
- 1 of 6 pieces chosen, for $350 (11%). The other five each name their reason: over their share given the others,
  or no verified option.
- No piece was placed outside its room, and the review list was empty.

What this shows:
- With "secondhand only" and these approved marketplaces, affordable, *machine-readable* used supply is genuinely
  thin. AptDeco listings return a robot check (HTTP 202), eBay returns 403, and the Craigslist leads in the search
  had expired. Chairish is readable but skews to designer/antique prices.
- The app now says this honestly instead of filling the set with one $2,495 bed.
- Raising the budget, allowing "New + secondhand", or choosing per piece are the user's levers.

**Limits:**
- The live retrieval ran on the copy only; the root's own QA is still to come.
- Robot-checked or refusing marketplaces are never bypassed, so their listings can't be verified automatically.
- Planning weights are a transparent heuristic, not market prices.
- "Fits" on plans without printed sizes is relative (labelled "estimated").
- Remote/delivery availability of used listings isn't verified; the trust note stays.
- Variant collapsing uses store + name, so oddly named variants may stay separate.

### Fortieth pass, addendum 7: final download-only ending (email removed by user direction)
User direction 2026-10-26: "skip the email, just offer a download way, both html and excel". The email/SMTP
feature from addendum 6 (`mailer.py`, its route, settings, `.env.example` keys, README setup, UI form and tests) is
removed entirely. No email code, configuration or notice remains, and `.env` was not touched.

**Checks:** 436 backend tests passed, including 9 in `test_checklist_export.py` (5 new for this pass); 24 frontend
unit tests passed; typecheck and build passed. No server start/stop, no git, no user data change.

**Fixes since addendum 6**:
- **Small screens:** at 640 px and below, the printable table becomes one labelled card per product (Qty, Each,
  Total and Bought each labelled). No column is hidden, so the earlier colspan mismatch is gone. The "Chosen so
  far" total stays on one line with its label. Long names wrap instead of widening the page.
- **Same rule as the app's clean plan:** no drawing unless at least one usable room's use is confirmed (an unsure
  reading says so). Door markers and the TV-on-stand bar are drawn as in the app.
- **Exact positions:** piece centres, sizes and rotations are written unrounded, and a test checks them against
  the app's own design state.
- **Empty design:** an empty design says "No pieces in this design yet" (in the export and in the app's checklist
  chip), not "Incomplete: 0".

**Final user path:** apartment → Final checklist → "Take your checklist with you" → **Download printable
checklist** (HTML) and **Download spreadsheet (Excel)**.

**Limits:**
- The printable page's narrow-screen layout is tested from its HTML/CSS only (see the root evidence above).
- Downloads are plain links: a design changed in another tab gives a 409 instead of a file until the page refreshes.
- The drawing is approximate and can't be edited in the export.

### Fortieth pass, addendum 6 (superseded by addendum 7): checklist downloads, with an email option since removed
Downloads as described in addendum 7. The optional SMTP email that was built and tested here (mocked only) was
removed at the user's request; no email was ever sent.

### Fortieth pass, addendum 5: hostname-only name search, operator-domain scope, reader parser edge cases
**427 backend tests passed** (8 new in `test_building_leads.py`; 2 updates in `test_public_reader.py` for the
parser's new return value and the reader cache); **23 frontend unit tests passed** (the SVG wording added to an
existing test); typecheck and build passed. FAKE NETWORK / MOCKED search with synthetic buildings ("412 Orchard
Street", Hartford; "Willow Point"; "Cedar Square"). No live call, no server restart, no git, no data change.
The root's LIVE API smoke results for addendum 4 are the root's (360 State: 15 plans via the reader after a 403;
AVA North Point: 6 plans via direct HTML), not re-run here.

Local check of the parser and identity rules against the root's three saved reader replies (read-only, outside
the repo, not copied in):
- 360 State: 15 plans, unchanged.
- AVA North Point: exactly the 6 real `/floorplans/…jpg/1024/768` plans, including `s8-628sf-apt264` and
  `s3-469sf(1)`, with no marketing photos; types from the card text (studio × 4, 1-bed × 2).
- 360 Market Square: 0 importable plans; 27 SVG plan drawings reported as unsupported; the "floorplan_banner"
  photo is not a plan.
- Identity: the 360 State reply passes "360 State Street, New Haven, CT"; the 360 Market Square reply fails it.

**Changes:**
- **Name search** (the root's blocker: "360 State Street" gave only "Other sources"):
  - Which leads are checked: at most 2 leading search leads that are sources only because of a hostname-only or
    unnamed title, on a non-listing site whose own domain spells the building name.
  - How they're checked: each page is read once (direct, then the public reader). It becomes a building card only
    if the page's own title and top text (never a related-properties section) name the building as a phrase AND
    the city or ZIP, with no other state, and the page stays in the lead's property path.
  - What stays a source: unrelated generic domains (e.g. a rent-portal host), listing sites, private or unsafe
    hosts, wrong-city pages, and leads beyond the cap. Their reason is shown.
  - Model-summary-only URLs are never used.
  - Saving and reuse: checks are saved append-only and reused by both find and select, so validation is
    deterministic and nothing is selected automatically. A repeated find makes no new requests, and select reuses
    the reader's cached copy (one reader request in total).
  - Display: the card shows "<page title> · <hostname>".
- **Same property**: plan/unit sub-pages group into one property path (floorplans, featured floor plans,
  available units, unit pages below a building path).
- **Scope**:
  - The reader's "URL Source" and any followed plan links must stay inside the chosen page's property path, so on
    operator domains another building's page is rejected even if its footer names ours.
  - The reader's name check now uses only the title and the top of the page, before any related-properties
    section, instead of the first 400k characters.
- **Parser**:
  - Type/price category headings ("2 bedroom From", "Studio") no longer count as plan headings; an individual plan
    needs its own designator ("Studio S", "1 Bed 1 Bath R", "Plan B2").
  - Images named as floor plans always count, even past the per-heading cap.
  - Generic "Floorplan" images get a name and type from the listing-card text right after them (type words only)
    plus the file name, read even when the URL continues after `.jpg`. Import still confirms the real media type
    through the SafeFetcher.
  - SVG plan drawings are listed as unsupported, with an honest note in "What we read" and the empty-gallery
    message; importing an SVG is refused.
- **Limits**:
  - Only domains that spell the building's name are checked from hostname-only leads, so an official site on an
    unrelated domain still needs a search result that names the building.
  - SVG plans can't be imported or read; listing-card layouts other than these may still be missed.

### Fortieth pass, addendum 4: general property-plan recovery (public page reader + listing alternatives)
**419 backend tests passed** (17 new in `test_public_reader.py`; 1 expectation in `test_building_discovery.py` now
records the reader attempt made before web-search recovery); **23 frontend unit tests passed** (4 new in
`gallery.test.ts`); typecheck and build passed. All results are FAKE NETWORK / MOCKED search, using synthetic buildings
("Maple Court", Hartford, plus a same-name Maple Court in Springfield MA and "Birch Hall"); no real property's page
is a fixture. A new autouse conftest guard makes real DNS lookups and sockets fail in tests, so no hidden network
use is possible. Offline only: no live call, no server restart, no git, no data change. One local check: the
parser was run against the root's saved reader reply for a real building (read-only, outside the repo, not copied
in). It gave 15 plans from 30 image references, used heading-based names (the three "Studio" plans typed as studio
although their alt text says "1 bedroom"), kept the uncropped variants, kept parenthesised URLs whole and skipped
the logo. Whether this works against the live reader and live sites is for the root's live QA. No building is
hardcoded.
- **Reader fallback** (`reader.py`; on by default, no key; `FURNISHAI_PUBLIC_READER=off`):
  - When to use it: the direct SafeFetcher read comes first. If it gives no strong plans, the address isn't
    policy-blocked and no checked list covers the building, the same public page is read via
    `https://r.jina.ai/<url>`. If that page has no plans, at most 2 floor-plan links that actually appear in its
    text are read (3 reader reads at most).
  - Order: the reader runs before the web-search alternatives, so a success needs no AI search and makes no
    further requests to the site that refused.
  - What it can be sent: the target's URL and DNS are validated first. Private/metadata hosts, credentials, odd
    ports, sign-in/applicant/resident/payment/auth pages and hosts, unit-specific paths and secret-looking query
    keys are never sent.
  - Limits: every hop must stay on r.jina.ai (2 MB, 25 s socket timeout).
  - Rejected replies: a reader reply is refused if it's the wrong format, a different site in "URL Source", a page
    that doesn't name the building, a challenge or login page, or carries a reader "Warning: … 403".
  - 429 or a timeout records the reason and stops the reader.
- **Evidence:**
  - The raw reply is stored immutably as `property_reader_page`. Its `source_url` is the reader's address; its
    provenance holds the page it read, the target, the retrieval time, the reported "Published Time" and cache age
    `unknown`.
  - Each plan candidate keeps its parent page, method (`public-reader-v1`), heading, raw alt text and
    `evidence_source_id`.
  - Imports keep their own image URL, time and hash, plus `via: "public page reader"`, `plan_heading`,
    `plan_alt_text` and `reader_source_id`.
  - Reader-found image URLs are fetched only through the unchanged SafeFetcher plan-image path (a private host is
    refused before connecting).
- **Parsing:**
  - Balanced parentheses and brackets, including link-wrapped images.
  - The plan name and type come from the nearest heading that names a single plan; page H1s, "Floor Plans",
    "Unit Video" and similar headings don't count. Alt text disagreeing with the heading is noted on the card.
  - Logos, icons, photos and anything after a "similar/nearby properties" heading are skipped. Square footage
    never becomes geometry.
  - CDN transformation variants of one file (Cloudinary-style `/image/upload/<transforms>/<file>`) are merged by
    `merge_style_variants`, keeping the uncropped, larger copy.
- **Listing alternatives** (explicit choice; new endpoint `POST /api/projects/{id}/place-discovery/{discovery_id}/alternative`):
  - What is offered: if everything automatic finds nothing, at most 2 pages on established property-listing
    sites from THIS search's evidence. Each must name the building AND the city or ZIP, with no other state in its
    title. A same-name building in another city is never offered or used.
  - Reading: nothing is fetched until the user clicks. Only an offered URL is accepted; the read goes direct first,
    then through the reader, and the page must again pass the identity check.
  - Results: plans are labelled "From <site>, a listing site (not the building's own website)" and their import
    caveat says so. A new discovery version is appended (the earlier one is unchanged), with no extra AI search.
- **UI:**
  - When plans are recovered, the gallery leads with "Found N published floor plans" and how they were found
    (reader or listing site, freshness unknown). The original 403 stays in "What we read".
  - The stale "No property evidence retrieved" note is removed after a recovery.
  - When every route fails, the message is honest, offers upload, and offers listing pages when available.
  - A short public-reader disclosure sits in "What we read".
  - Checked Audubon/Archive lists don't use the reader and are unchanged (their exact-request tests still pass).
- **Limits:**
  - The reader is a free, rate-limited outside service with unknown cache freshness; it may be unavailable, or
    blocked by some sites.
  - Plans loaded only as interactive widgets, PDFs or images without plan headings or plan names may still not be
    found.
  - Listing-site layouts differ, and only plans under plan headings or named as plans are used.
  - Not every website can be read.

### Fortieth pass, addendum 3: find-queue lifecycle, stale progress, filter-aware row copy
Frontend only. **19 frontend unit tests passed** (3 new: leave/return/Continue on the queue helper, the
saved-settings key, and the row-copy helper); typecheck + build passed; the backend is unchanged (402 passed). No
live call, no server restart, no git, no data change. The live checks behind this report (secondhand run, Either
with both branches, Stop then Continue, 390/1280 widths) are the root's, not re-run here.
- The Choose step stays mounted while hidden, so cleanup on unmount never fired on Next/Back. It now receives
  `active`. Leaving the step stops the queue after the current piece type: that group's checks and evidence are
  kept, and the remaining groups stay under "Continue". Coming back never resumes a run; only Continue or a new find
  does. A short note says why the run stopped ("…because you left this step" or "Stopped after the current piece
  type").
- Find results (progress, per-piece messages, Continue list) are tied to the SAVED search-relevant settings:
  condition, styles, bed size, pickup/delivery, resale sites, stores, budget, reserve and the place's location. A
  saved change clears them, so no stale "No options yet: used …" remains after switching to Either. Choosing a
  product (a design version bump) doesn't clear them. The "Save & find" path clears before the run starts, never
  during it.
- A piece's row line follows the active All/New/Secondhand filter. For example: "No checked secondhand options yet. 7
  new options available under All/New." or "1 secondhand option ready. Choose one below. 3 new options available
  under All/New." It never says "Choose one below" when no cards show. The filter applies only when New + secondhand
  is saved.

### Fortieth pass, addendum 2: final live-QA corrections (style in queries, budget on option cards)
**402 backend tests passed** (3 new in `test_find_furniture.py`); **16 frontend unit tests passed** (1 new);
typecheck + build passed. Fixtures only; no live call, no server restart, no git, no data change. The live findings
that prompted this (rustic used-only $3,500 run: no rustic mattress, a $3,495 sofa shown inline against $2,344 left)
come from the root's live UI test, not re-run here.
- Search queries treat style as a preference, not a requirement: "ideally rustic style (closely related styles like
  warm wood, traditional, industrial or other styles are fine if those are scarce)" in the new, refined and used
  queries. Mattress and TV queries carry no style. Hard terms are unchanged: new/used, nominal bed size, allowed
  stores/resale sites, remaining-budget price, location. The number of queries and their caching are unchanged.
- Options list: the `max_price_cents` hard limit now runs before the soft style fallback. Before this fix, an
  unaffordable exact style match could empty the list instead of falling back to affordable related styles.
- Every option (inline cards and full options) carries `budget_left_cents` (the item budget minus the other pieces'
  chosen products, which is the same figure the online query uses) and `over_budget_by_cents`. Cards show "$1,151
  over the $2,344 left for this piece" or "Fits the $X left for this piece" before Choose. They never claim the
  design is within budget, and they show nothing when no budget is set. Choosing over budget stays possible, with
  the existing budget-box warning, and "Choose for me" still respects the budget. No options are hidden.

### Fortieth pass, addendum: root review fixes before live QA
**399 backend tests passed** (4 new in `test_find_furniture.py`; 2 fixtures corrected); **15 frontend unit tests
passed** (1 new); typecheck + build passed. Fixtures only; no live call, no server restart, no git, no data change.
- Automated new checks now verify the page's own product: its title must name the requested type and not be a
  set/bundle (`_category_matches`), else nothing is stored ("different item"). Sold/out-of-stock store pages are
  "sold or unavailable", never counted as verified; a page whose size doesn't match (e.g. a king frame for a queen
  piece) is "a different size". Branch counts now count only actual options for the piece.
- Used listings have a canonical identity (`resale.listing_key`: platform + host without www./m. + path, query
  ignored). Only the newest check of a listing is offered (a newer SOLD check withdraws it); the one-listing-one-piece
  guard (manual choice, "Choose for me" incl. upgrades) uses the identity, not the content-hash id. A chosen listing
  whose newer check is sold keeps its choice with a warning; all stored records are unchanged.
- The existing 12-requests-per-10-minutes AI limit (unchanged) now pauses a find run: `find-group` stops spending on
  the rate-limited group (`limited`, branches "paused") and the queue stops with the message; the remaining groups
  (including the paused one) stay in "Continue"; options found so far stay visible.
- Settings are locked while a find run is in progress (they're saved first); leaving the page stops the queue after
  the current group; GET previews/plan still make no AI or web call.

## Fortieth pass (2026-10-26): one "Find furniture" action, both branches, inline options, soft styles
**395 backend tests passed** (6 new in `test_find_furniture.py`); **14 frontend unit tests passed** (4 new for the
find queue helper); frontend typecheck + build passed. All search/page results in these tests are MOCKED fixtures, not
live results. No live call, no server restart (the static build was rebuilt), no git, no data change. Not
browser-checked by Claude Code.
- Root's finding: the real user's place had saved secondhand preferences but no furniture search had ever run, so
  every piece showed "No verified used…" with a per-piece button to find options.
- New endpoints: `GET /design/find-plan` (type+size groups of unowned pieces without a product; no cost),
  `POST /design/find-group` (per group: branches by condition — new uses the saved checked catalog and, only if fewer
  than 3 options, one approved-store search with up to 2 page checks; used runs one approved-marketplace search with
  up to 3 listing checks; either runs both independently; an error in one branch is reported and doesn't remove the
  other; classified reasons: verified, sold, missing price/size, page blocked, different item, condition not shown;
  existing guards, evidence checks and caches are reused; never chooses a product), `GET /design/previews` (up to 6
  saved options per piece, balanced new/used; no cost).
- Choose furniture: "Save & find furniture" / "Find furniture for my plan" saves dirty settings first, then runs a
  bounded queue (max 12 groups per run, Continue for more, Stop after the current group) with per-group progress;
  options appear as compact previews with Choose on every piece (All/New/Secondhand filter for "New + secondhand");
  rows say "Ready to find options" before a search and the specific outcome after; the missing-piece wall became a
  short collapsed summary. Condition labels: "New + secondhand / New only / Secondhand only".
- Styles: soft ranking with a small taxonomy of related styles; "Only my styles" falls back to the closest styles (or
  all, with a notice) instead of an empty list; "Use my budget" uses the same style score; hard limits unchanged.
- A used listing (one item) can't be chosen for two pieces: shown as "Picked for another piece", refused by the
  choose endpoint and skipped by "Choose for me".
- Limits: whether live searches return checkable product pages varies (root's earlier live run verified 2 Chairish
  nightstands); many pages refuse automated reading; the queue runs in the open browser tab (closing it stops it).

### Thirty-ninth pass, addendum: store vs marketplace choices in the design pool
**389 backend tests passed** (3 new endpoint-level tests); 10 frontend unit tests; frontend typecheck + build passed.
No live call, no server restart, no git, no data change.
- Root's finding: with "Secondhand only" and an old store choice (Amazon), the store filter still applied and hid every
  verified used listing (the store chips are hidden for used, so the user couldn't fix it); the chosen resale
  marketplaces only constrained the search, not the options.
- Fix (`design.design_pool`, used by options, "Choose for me", manual choice and missing-item reasons): store choices
  apply only to new items; chosen resale marketplaces apply only to verified used items; "either" is the union.
  Switching condition keeps both choices. A chosen product that no longer fits the current preferences stays chosen
  with the warning "Chosen under different shopping preferences…" (no silent swap). The legacy per-room planner is
  unchanged.
- Wording: the source note now says recommendations and page checks use only the approved sources and that the web
  search itself may look at other sites, which the app doesn't show, open or read; the `import_listing` docstring now
  describes the current gate (no declared-only used imports).

## ROOT live check after the thirty-eighth pass (root's run, not Claude Code's)
ROOT LIVE UI (pass 46): two Chairish used nightstands ($806 and $1,316) with dimensions were checked and imported;
an eBay page answered 403 and was reported honestly; 3 unapproved or non-listing results were hidden.

## Thirty-ninth pass (2026-10-26): one furniture-source boundary for every search, check and import
**386 backend tests passed** (7 new in `test_source_boundary.py`; 5 older tests updated from unknown example
hosts/declared-used imports to approved sources, keeping their intent); **10 frontend unit tests passed**; frontend
typecheck + build passed. No live AI or web call, no server restart (only the static build was rebuilt), no git, no
data change. Not browser-checked by Claude Code.
- `resale.py` now also holds the approved NEW-item stores (Amazon US, Article, IKEA, Target; exact hosts, same strict
  https/port/credential/ASCII checks) and `product_source()`/`furniture_guard()` for the shopping condition.
- Search results (design "Find more online", saved leads in the products view, legacy furniture research) are filtered
  server-side: new → chosen stores; secondhand → approved resale listings; either → both. Others are counted
  (`hidden_unapproved`), never listed with Open or Check. The UI hides the generic online block when shopping
  "Secondhand only" and shows the source note otherwise; browse links drop non-approved stores (Wayfair).
- Manual imports (`import_listing`, used by the legacy listing endpoint and the design "Check this option"): unknown
  sites are refused before any request; new items need an approved store; a "secondhand" import goes through
  `import_used_listing` (approved marketplace + listing evidence) — a declared condition alone no longer creates a
  used option. With "Secondhand only" a "new" pick in the request can't bypass the used gate. Every redirect hop is
  checked before connecting (tested: an Amazon redirect to an unknown tracker is never contacted).
- Older records are untouched; imports from other websites and declared-only used items are simply not offered as
  fresh options (`design.offered`).
- Every approved used listing has its own "Check this option" (one page per request, same check, cache and evidence),
  so a 4th listing can be checked and chosen in the app; "Check listings again" still re-reads only the first 3.
- Limits: the store list is the saved catalog's four stores; other reputable stores aren't readable until added to
  the allowlist. Used checks still fail closed on pages that hide their item behind scripts or logins.

## Thirty-eighth pass (2026-10-26): approved resale marketplaces, primary-item evidence, TV-on-stand rules
**379 backend tests passed** (9 new in `test_resale_trust.py`, 2 secondhand tests updated to approved hosts); **10
frontend unit tests passed**; frontend typecheck + build passed. No live AI or web call, no server restart, no git, no
data change. Not browser-checked by Claude Code; root will test the secondhand flow.
- **Trust boundary** (user direction: credible marketplaces only): `resale.py` allowlists AptDeco, Chairish, eBay (US),
  Facebook Marketplace item pages and Craigslist regional posts (OfferUp and Kaiyo are NOT included: not confirmed in
  this pass). Exact hosts, https, default port, no userinfo, ASCII hosts (no punycode/confusables), listing-path shape.
  Tested refusals: `ebay.com.evil.example`, `evilebay.com`, `ebay.com@evil.example`, credentials, http, :8443, a Cyrillic
  "е", punycode, search/group/browse paths, Kaiyo, ebay.co.uk. The used search names only the chosen sites; results
  from other sites are hidden and counted; only approved listings are fetched; `SafeFetcher.fetch(url_guard=…)` checks
  EVERY redirect hop before connecting (tested: the unapproved hop is never requested); private addresses stay blocked.
  Preferences: "Resale marketplaces" chips (all approved by default) when secondhand is allowed; store chips are for new
  items. No remote listing images are auto-loaded for checked used listings.
- **Primary-item evidence** (root's proven false positives fixed): condition, price, size, availability and name come from
  the listing's own item — the JSON-LD Product whose url is the page (or canonical/og:url), or the only product; several
  unmatched products → abstain. (A) a related USED chair before the page's NEW nightstand → "new condition", not used;
  a related item's price/size/SoldOut are never borrowed. (B) "Condition: New" with a "Shop pre-owned" footer → new
  (condition values are judged by how they start; footer/section tags now break lines in the text extractor). A bare
  "Condition: Excellent" is not enough. Text after "You may also like"/"Related"/"Similar…" markers is ignored; a text
  size is used only if the listing text has exactly one. The title must name the requested type: a used dining table in
  a nightstand check, or "Pair of nightstands", abstain. Sold comes from the item's offer or a whole-line statement in
  the listing text, not a related card.
- **Check cache**: keyed by checker version + piece type + URL, reused for 10 minutes, then re-read; "Check listings
  again" re-reads explicitly (still ≤3 pages). A check for a different type never reuses another type's result.
- **Manual check**: "Check this option" as used goes through the same approved-site and evidence gate (an unapproved
  link is refused with "approved resale marketplaces"); with "Secondhand only" the check is always the used check (no
  "new" default); the separate manual link import keeps its "your declaration, not verified" label.
- **TV rules** (root review): removing a TV's stand keeps the TV (product, owned mark) but puts it in Not placed with
  the reason; an orphan TV can't be moved onto the floor (422); with several free stands, adding a TV no longer picks
  one ("choose which one it sits on"); rotating the stand or marking the TV owned keeps the relationship.
- **Limits**: used checks depend on listings exposing their item in structured data or clear item-detail text; many
  marketplace pages load with scripts or refuse automated reading (Facebook Marketplace usually requires login), so
  checks will often fail closed. Type matching is by title words.

## Thirty-seventh pass (2026-10-26): shopping preferences, plan-page order, secondhand, more furniture types
**370 backend tests passed** (10 new in `test_shopping_flow.py`); **10 frontend unit tests passed** (2 new); frontend
typecheck + build passed. No live AI or web call, no server restart, no git, no data change (a read-only check on the
local database shows the two bedrooms of apt_1030… as "BEDROOM 1" / "BEDROOM 2"). Not browser-checked by Claude Code;
root will run the live secondhand search.
- **Preferences** (one source of truth): `DesignPrefs` gained `fulfillment` (either / local_pickup / delivery) and
  `timing` (a preference, not a delivery promise). The home form and place details no longer show new/secondhand,
  pickup/delivery or timing; Choose furniture has them with one "Save preferences" and the place's public location
  ("Searches use New Haven, CT 06511"). Pickup without a location shows inline city/state/ZIP fields that save to the
  place (a new context version). New designs seed these from the place's earlier setting; designs saved before this
  pass READ that setting as a fallback on GET without writing a version (tested). Queries now honour the choice:
  "for local pickup near …", "with delivery in the US" or both (previously the query silently used the place's old
  setting); a pickup search without a location returns 422 asking for one. The unit is never in a query (tested).
- **Plan page**: place details and building search → public plans / your plans / upload → the selected plan's review
  → one bottom "Read floor plan & continue" (sticky on narrow screens). After choosing, importing or uploading a plan,
  the review scrolls into view and the finder collapses into "Change floor plan". Read & continue reads (or reuses the
  saved reading, said honestly) and opens Arrange only if the reading is usable; an unreadable plan stays with "Try
  reading again" / "Choose another plan image". The duplicate middle Next button is gone; copy now matches the clean
  plan default and the Not placed fallback.
- **Secondhand**: condition-aware empty states (no "change bed size" when the condition is the filter); row-level
  "Find secondhand options": ONE bounded search for individual used listings (resale sites, city/ZIP, pickup/delivery),
  then at most 3 automatic page checks (`import_used_listing`): first-party/new-retail hosts are refused without a
  fetch; a page must itself state used/pre-owned (JSON-LD itemCondition or item-detail text) — the query, domain or
  a dropdown never count; pages stating new are refused; sold/unavailable listings are kept as evidence but can't be
  chosen; missing price/size stays incomplete. Each check is cached; a failing page (e.g. a private address refused by
  the safe fetcher) doesn't stop the others. Tests cover the new-retail false positive, an accepted used listing with
  price, size and source evidence, sold, the 3-check cap, caching (no repeat search or fetch), stale 409, other session
  404 and SSRF. Options label condition as "stated on the listing page" vs "your declaration, not verified".
- **Room names**: repeated printed labels are numbered ("BEDROOM 1", "BEDROOM 2"); rooms and their pieces are never
  merged or removed.
- **Furniture types**: tv, tv_stand, dining_table, dining_chair, armchair, side_table, ottoman, console_table,
  shoe_storage, floor_lamp across the category list, aliases ("TV stand", "media console", "end table", "shoe rack"...),
  imports, research, draft sizes (typical), placement (wall-backed where sensible; chairs beside the dining table; dining
  pieces prefer a dining area; never the bath), choosing and the checklist; grouped in the Add menu. Not auto-added.
  A TV sits on a TV stand (explicit `attach` op and "On which TV stand" picker); without a free stand it waits in Not
  placed; its listed width is checked against the stand's (never a diagonal). No catalog rows were added for these
  types: they rely on Find more online / imports.
- **Limits**: the automatic used check depends on pages exposing condition in structured data or plain text; many
  resale sites load listings with scripts or refuse automated reading, so checks may fail closed. Lead classification
  is by URL shape. The new types have no checked products until imported. Placement rules for new types are simple.

## ROOT live and browser checks after the thirty-sixth pass (root's runs, not Claude Code's; not a human pilot)
- ROOT LIVE + BROWSER, furniture-specific "Find more online" (`furniture-products-v2`): returned 5 direct product
  leads (Target, Amazon) and 7 category/store sources (collapsed under More sources). Checking the Target product
  page: price missing, correctly not choosable. Checking Amazon SunnyFurn platform bed frame
  (https://www.amazon.com/SunnyFurn-Platform-Floor-Standing-Minimalist-Assembly/dp/B0F28NYZFQ): verified $134,
  61.42 × 81.1 × 7.68 in; it appeared as the 8th option with a Choose button. This shows one retailer page worked; it
  is not a claim that every retailer can be read.
- ROOT harness `finish_live_v4.py` passed: all 3 arrangement alternatives with no warnings; one bed on the left, bath
  on the right, kitchen counter kept clear; saved edit with the map unchanged; stale edit 409; cached read preserves
  the design; other session 404; source bytes unchanged.
- ROOT preservation check: the old 7 files, 71 records and 1,043 coursework files unchanged.
- Copy fix after this (Claude Code; build, typecheck, 8 frontend tests and 36 design backend tests passed): the
  product-check messages and lead summaries now name missing facts readably ("missing price", width, depth,
  condition, product type) instead of field names like `price_cents`; the stored missing-field lists are unchanged.

## Thirty-sixth pass (2026-10-26): saved positions now pass the same checks as placement
**360 backend tests passed** (1 new); 8 frontend unit tests passed; frontend build passed. No live AI or web call, no
server restart, no git, no data changes.
- **Root's live finding**: on the saved live v4 map (one left bedroom, right bath, protected kitchen counter),
  `GET /arrangements` returned a sofa that `check_items` flagged "Overlaps the other (a fixed area)".
- **Exact cause**: the sofa was backed flush against the shared edge x = 344.96 px between the living zone and an
  "other" (not furnishable) room. Placement validated the unrounded centre: the sofa's left edge was exactly 344.96, a
  point ON the polygon edge, which the ray-casting test treats as outside, so the spot passed. The position is saved
  normalized to 5 decimals (x = 0.566); re-deriving it gives 0.566 × 640 = 362.23999999999995, so the left edge became
  344.95999999999995, a hair inside the fixed room, and `check_items` (which reads the saved value) flagged it.
- **Fix** (`design.py`): every candidate centre is quantized to the exact saved value BEFORE validation, scoring,
  access checks and later collisions (`_q`, used by the wall/grid search, nightstands-beside-bed and the coffee table),
  so what is checked is what is persisted; and touching a shared boundary is consistently not an overlap
  (`TOUCH_EPS` = 1e-6 px in `rect_poly_overlap`/`rects_overlap`, far below any meaningful penetration). The same
  engine serves added pieces (`place_new`).
- **Regression** (`test_returned_arrangements_are_valid_after_rounding`, using the live reading's geometry as a test
  fixture): it failed before the fix with exactly root's warning; now every returned option and added piece passes
  `check_items` (fixed areas, doors, other furniture) with 5-decimal coordinates, and pushing the sofa 6 px into the
  fixed room still warns (no real overlap is hidden).
- A read-only run of the harness's arrangement assertions on the saved live map (no database writes): no fixed-area,
  door or furniture warnings in any option, the bed placed on the left, the sofa placed. Root's own harness
  (`finish_live_v4.py`) was not run by Claude Code (it writes to root's isolated QA database and results file from
  root's workspace); root should run it.

## Thirty-fifth pass (2026-10-26): product-focused online search, compact Arrange workspace
**359 backend tests passed** (2 new); **8 frontend unit tests passed**; frontend typecheck + build passed. No live AI
or web call, no server restart, no git, no reset. Not browser-checked by Claude Code.
- **Root's live finding**: "Find more online" (queen bed, minimal, $3,500) returned 12 leads that were ALL store/search/
  category pages (Amazon search, Wayfair sb1/sb2 category pages, a Facebook Marketplace category for an unrelated
  town, eBay search, a catalog), and several were wrongly offered "Check this option".
- **Fixes**:
  - furniture searches use their own instructions (`furniture-products-v2`): individual product detail pages, about
    6 products from several retailers, price/dimensions only if the page states them, no search/category/browse
    pages; the query asks for specific products of that type/size/style/condition, the remaining budget, and US
    delivery when there is no location (never the unit). URLs still come only from the response's own citations
    and sources.
  - `lead_kind` treats `/sb1/`, `/sb2/` … and `-c<digits>-a…` category URLs and Facebook Marketplace browse pages as
    store pages; only product pages get "Check this option".
  - product pages are the main lead cards; store/search/category pages sit under a collapsed "More sources".
  - if a search returns no product pages, ONE refined product search is offered (refused before a first search and
    when product pages exist; cached, so repeating it never makes another call).
  - citation-only text such as "([amazon.com](https://…))" is no longer shown; supporting text is shown only when
    something meaningful remains.
  - Whether the new instructions actually yield product pages is untested live; root will run one fresh search.
- **Arrange workspace** (browser finding at 1280x900): "Add pieces" is now at the top of the side panel (after the
  selected piece's controls), before the piece list; product names in the list are clamped to 2 lines with the full
  title on hover; arrangement previews are compact (about 80 px tall, whole plan visible, title and note kept as a
  click target); the old-reader notice is one short inline line with a "Re-read plan" link.

## ROOT live check after the thirty-third pass (root's run, not Claude Code's)
ROOT LIVE (19.34 s, real gpt-6-luna, v3 prompt, the watermarked Archive 1-bed image; no app user data edited): one bed
set only and the bed marked Not placed, but the geometry was still inaccurate: view 3d; r1 bedroom included the
bottom-left closet; r2 "living" spanned the middle AND the right bath; r3 "bath" was actually a utility closet; scale
1.6436 came from the oversized living region, so the bed couldn't fit the narrow bedroom polygon. This re-read did
NOT fix the bath boundary or place a valid bed.

## Thirty-fourth pass (2026-10-26): no placement on unreadable plans, clean plan default, reader v4
**357 backend tests passed** (4 new); **8 frontend unit tests passed**; frontend typecheck + build passed. No live AI,
no server restart, no git, no reset. Not browser-checked by Claude Code; the v4 reader has NOT been run live.
- **Proven defect fixed**: `arrange()` on an unmapped/fallback map lined pieces up across the source image and marked
  them placed (and `place_new` centred them). Now every piece stays in Not placed with "Room boundaries could not be
  read; re-read or identify a usable room first." (ids, products, owned flags and the mattress link kept), no
  arrangement alternatives are offered, moves are refused on such a plan, and nothing is drawn on the source. The
  same holds when a mapped reading has no usable room.
- **Ambiguous zones stay out of automatic placement** (all piece types, not only beds): a living/dining outline with
  bath fixtures is a conflict (kept clear); a bedroom outline with a bed AND bath fixtures is unsure; an unlabelled
  low-confidence area on a 3D/photo plan with nothing confirming its use is unsure. Starter sofas go only to a
  confirmed living area. A re-read keeps the existing pieces (including the user's manual removals) and never reseeds.
- **Clean plan default** (user direction): after a usable reading (a confirmed furnishable room) the canvas is a code-drawn
  SVG plan from the map — no source image (no watermark/"spaces remaining" banner, floor texture or illustrative
  furniture); walls read as walls solid; outline and room edges thin and approximate; open splits and unsure/conflict
  rooms dashed and labelled "(unsure)"/"(check)"; kitchen/bath/closets hatched; doors and windows marked; a caption
  says it is approximate. "Show original floor plan" shows the source as published. Unsure readings default to the
  original with a note; unreadable plans show only the original with "We couldn’t map this plan’s rooms". The clean
  plan is only as good as the reading: on maps like root's v3 Archive result it would still show merged zones, but
  they are labelled unsure/check and get no automatic furniture.
- **Reader v4** (`plan-map-v4-crops`): one call with the full analysed image plus two overlapping (58%) zoomed crops of
  the same image along its long side, made in memory (stored originals and derivatives untouched); the prompt states
  each crop's full-image offsets and requires full-image coordinates; it also tells the model to trace bathrooms
  separately and not to call a closet a bath without a toilet/shower/tub. Reservation counts 3 images. Untested live;
  whether it improves boundaries is for root to check once.

## Thirty-third pass (2026-10-26): room-use semantics, fail-closed placement, Arrange workspace, more products
**353 backend tests passed** (12 new in `test_design_refine.py`); **8 frontend unit tests passed**; frontend typecheck +
build passed. A TestClient smoke on a temporary COPY of the local database (original opened read-only, copy deleted;
no AI call) loaded the user's newest 1-bed design. No live AI or web call, no server restart, no git, no reset. Not
browser-checked by Claude Code; root's live/browser QA is pending.
- **Root cause of "2 beds incl. bathroom"**: the stored v2 map read the bath as a low-confidence unlabelled bedroom,
  and the starter set seeded a bed set in every sleep zone. Now:
  - prompt `plan-map-v3-room-evidence` asks for typed evidence per room (bed/pillows vs toilet/shower/tub/sink ...),
    how the use was decided, "3d" for furnished renders, and no guessing under watermarks;
  - code assigns each room a use status (generic rules, also for older maps): user-set → confirmed; bath fixtures
    (seen, or a bath-fixture outline inside) in a bedroom/living room with no bed → conflict (kept clear); an
    unlabelled low-confidence bedroom with no bed seen → uncertain;
  - bed sets only in confirmed bedrooms (one each; one for a studio; uncertain-only → one set in "Not placed").
  - On the copy: r4 (the bath) is "uncertain"; the existing nightstand there shows "This room’s use isn’t
    confirmed yet"; applying an arrangement moves it to Not placed; marking r4 as Bath saves a derived revision.
- **Fixes and repair actions**: room-use correction (`POST /design/rooms/{id}/use`) appends a derived map revision
  (parent id + corrections; the AI reading row is unchanged); pieces in a room that becomes non-furnishable go to Not
  placed. "Re-read plan" is offered when the map came from an older prompt (one AI call; ids, products and owned
  marks kept; positions re-derived; corrections on the old reading don't carry over and the user is told). Re-selecting
  a plan restores its latest design including corrections. "Add a bed set to this room" is explicit.
- **Placement engine** (`design.py`): no centroid fallback and no relaxed doors; pieces only inside usable rooms of the
  right kind; collision checks across ALL rooms (footprints and access space); big pieces backed flush to a wall-like
  edge (physical wall or a non-open boundary; open zone splits excluded); access clearance (bed foot 18 in + one side
  24 in; sofa/dresser/desk front 30 in); otherwise "Not placed" with the reason. Manual rotation and moves stay free
  and get warnings. Unplaced pieces aren't drawn or checked; mattresses follow their bed.
- **Arrange UI**: one workspace — desktop two columns (canvas ~70% with the thumbnail strip right above it; compact
  side panel with selected-piece controls, synced piece list by room with product name/Draft/Not placed/owned,
  mattress grouped under its bed, add pieces/bed set, rooms with use status and a use selector); stacks on narrow
  screens. Thumbnails are cleared while refreshing and applying one updates the main canvas.
- **More products**: paged options (8 at a time, all matching shown on request), sort by price, "Only my styles",
  browse other bed sizes (explicit size switch when chosen). "Find more online" (one bounded gpt-6-luna web search via
  the existing research cache and ledger; query = piece type + bed size, condition, styles, remaining whole-design
  budget, public city/ZIP; never the unit) shows cited lead cards; product pages can be checked in the app with the
  existing safe fetcher (page kept as evidence; verified + matching products join the options; incomplete stays
  unselectable; store/search pages stay leads). Tests: unit label excluded from the query; bed size and remaining
  budget in it; leads not in this place's results refused; stale 409; other session 404; search failure leaves the
  design unchanged.
- **Checklist**: dedicated card layout (`dl-*`), wrapping titles, quantity × price, link, per-piece ticks; stacks on
  phones; shows placement notes and that a complete list is not a fit check.
- **Limits**: room-use rules are heuristics over an AI reading; the 1-bed map's zones are still approximate (e.g. r1
  includes part of the closet); lead classification is by URL shape; many stores refuse automated reading, so some
  checks will fail closed; the web search and v3 re-read need live AI and have not been run by Claude Code.

### Thirty-second pass, addendum 3: the original plan is the default canvas
Frontend only (no AI call, no record changes); typecheck + build passed; 8 frontend unit tests passed; not
browser-checked by Claude Code.
- **Limitation (root's inspection of the live v2 Audubon map):** the reader finds the right areas but misplaces some
  zone boundaries (the sleeping polygon is too narrow, the bath starts too low) and returned no wall segments. The AI
  outline is therefore NOT the actual walls, and the app makes no claim of accurate walls or calibrated shape.
- So the canvas now shows the ORIGINAL plan image by default, with movable furniture on top, in every step and in
  the arrangement thumbnails ("Show original floor plan", on by default; "Show furniture" optional). Unticking it
  shows the clean AI outline, labelled "Approximate AI outline — compare with the original plan". The map is kept:
  it still drives placement, zone names, fixed-area/door checks and size estimates, with the existing caveats. Because
  those checks use the approximate zones, a piece can look fine on the original yet get a warning (or the reverse).

### ROOT checks after the thirty-second pass (root's runs, not Claude Code's; not a human pilot)
- ROOT LIVE: prompt v2 (`plan-map-v2-open-zones`) on the Audubon studio plan: 7 areas, printed-size strings read,
  approximate scale 1.0356 px/in from the living zone, bed set + sofa starter pieces; map unchanged under move/rotate;
  stale edit 409, other session 404; original bytes intact.
- ROOT BROWSER: drag, keyboard move/rotate; Next saved a $3,500 budget and a queen bed-size change; a final-checklist
  purchase tick persisted and could be undone; an Amazon queen frame was chosen; the original-plan comparison is now
  legible; the preset-label fix (pass 37) verified.
- Still pending: root's phone-width recheck of the final appearance after the toolbar fix below.

### Thirty-second pass, addendum 2: narrow-screen toolbar and wording
Frontend only; typecheck + build passed; 8 frontend unit tests passed; not browser-checked by Claude Code. The
selected-piece toolbar in Arrange your space now stacks: name + status on one full-width row (normal word wrapping),
move arrows + Rotate (44 px touch targets), room picker, then "I already own this" + Remove; it no longer reuses the
legacy horizontal `.sel-card`, whose `overflow-wrap: anywhere` split words like "Sofa" at 390 px. The green badge now
says "No conflicts detected in this draft" (not a fit check; the scale text is unchanged), and the step summary says
"1 piece still needs a product".

### Thirty-second pass, addendum: root browser finding 1 (preset label)
Copy only; frontend typecheck + build and unit tests passed; not browser-checked by Claude Code. The old apartment
preset (e.g. "1 bed · 1 bath") no longer appears in the normal flow: the place header eyebrow says "Your place", the
place details drop the preset and say one budget and style cover the whole design (set in Choose furniture), and the
home "Your places" list shows "Saved place" and its date instead of preset and room count. The preset is named only
inside the collapsed "Older room-by-room tools", stating that it doesn't describe the chosen floor plan. Stored
apartment rows are unchanged.

## Thirty-first pass (2026-10-26): design-first apartment flow (user direction)
**336 backend tests passed** (12 new in `test_design.py`); **8 frontend unit tests passed** (2 new); frontend
typecheck + build passed; offline demo smoke ran; a TestClient smoke on a temporary COPY of the local database
(original opened read-only, copy deleted) opened the user's existing Adubon place on the new path. No live AI call, no
server restart, no git, no reset. **Not browser-checked and not live-checked by Claude Code**: root's live/browser QA
(the Audubon public image and the Whitehall fixture) is pending.
- **New flow for apartments**: Place & floor plan → Arrange your space → Choose furniture → Final checklist, with Next/Back
  (every step stays mounted, so drafts survive) and the current step remembered per place for a reload. No room tabs
  while finding or choosing a plan. The old per-room Workspace (room tabs, three plan tabs, per-room checklist) is
  kept unchanged in a collapsed "Older room-by-room tools" section; single-room projects keep the old flow.
- **Whole-plan map** (`backend/furnishai/planmap.py`, prompt `plan-map-v1`): one bounded gpt-6-luna call through
  the existing `run_agent` + usage ledger (purpose `plan_map`). Normalized coordinates of the analysed image; code
  checks finite in-image values (2% clamped), simple 3-40-point polygons (non-convex allowed), minimum area, bounded
  counts, code ids; printed sizes are parsed only from exact text (never square footage). Scale = median px/inch of
  printed rooms whose outline proportions agree within 25%, else a relative drawing scale that never yields inches or
  fit claims. No furnishable outline (3D/marketing/non-plan image) → `fallback`: original image + conceptual pieces.
  Stored append-only in `plan_maps` (source id, derivative hash, model, prompt, call record); cache key includes the
  source id. The selected image shows immediately; "Read floor plan" overlays a status on it, never a blank canvas;
  a toggle shows the original under the vector map.
- **Design** (`design.py`, `design_api.py`, tables `design_versions`, `design_marks`; additive, no existing table
  changed): draft pieces by category and bed size (typical sizes, dashed, labelled draft) per room zone (each
  bedroom/sleeping zone gets its own bed set with distinct instance ids; living pieces to the largest living zone);
  three deterministic arrangements on the same map; drag (mouse/touch), arrow buttons/keys, rotate, change room, add,
  remove, "I already own this". Kitchen/bath/closet/balcony rooms and fixtures are not furnishable; door areas are
  kept clear where identified; overlap/outside/fixed-area/door problems are warnings; nothing is shrunk; edits never
  touch the map. Every edit needs `expected_version` (409 if stale); another session gets 404; ids, rooms, products
  and plan sources are validated against this place.
- **Products and budget**: per-piece real options (catalog + imports from this place's rooms; category, bed size,
  condition, stores) with price, size, condition, store link, style matches and a placement re-check using the
  product's listed size (a larger product shows a conflict). "Choose for me": "Keep costs low" = cheapest without new
  placement problems; "Use my budget" = upgrades only for more style matches within the item allowance (ties and
  price-only upgrades never). One whole-design budget with the delivery/tax reserve. The three plan price tabs are not
  in the new flow.
- **Honest incompleteness**: smoke on the copy: the user's existing preferences (king, $3,000, minimal, new,
  bed frame/mattress/nightstand/dresser) carried over; with a synthetic studio map the king bed frame and king
  mattress stay as **missing** ("No verified king … Search stores and import one, or choose another bed size"),
  the subtotal is $159.98 for the nightstand + dresser only, status "Incomplete: 2 pieces without a product". King is
  never downgraded; a bed-size change is an explicit user action.
- **Final checklist**: one list with quantities/line totals, store links, per-piece "Bought" marks tied to the
  current product (a swap never inherits a mark), owned pieces, missing pieces with "Review missing items".
- **Limits**: the map is an AI reading of an image; door swings, walkways and wall positions are approximate; the
  synthetic test maps don't measure vision accuracy; arrangements are simple heuristics (wall/corner/long-wall
  scoring, nightstands beside beds, coffee table before the sofa); draft sizes are typical, not product facts;
  computing three arrangement options takes about 0.5 s per request.
- **Root should exercise**: Audubon (`Use this plan` → `Read floor plan` live; check the rooms/kitchen/bath against
  the original toggle; whether LIVING/SLEEPING come back as separate zones); Whitehall (two bedrooms → two bed sets);
  drag on touch and mouse; reload mid-flow; Back/Next drafts; a 3D/marketing plan (fallback); stale tab (409).

## Thirtieth pass (2026-10-26): analysis cache returns the plan that was asked for
**324 backend tests passed** (3 new regressions, 1 strengthened). Backend only; frontend unchanged (it already shows
the returned room's plan and readings), so the twenty-ninth pass's 6 frontend tests and build still apply. No live AI,
no server restart, no git, no reset. Not browser-checked by Claude Code.
- Bug (found in root review): reading plan A, then B, then A again hit A's cache but returned the current head,
  i.e. plan B's room. Now:
  - If the current room already comes from that analysis (e.g. A plus its chosen estimate), nothing changes: no new
    version, and the chosen estimate is kept.
  - Otherwise the cached analysis is restored as a NEW room version with its own sources and readings, and the plans
    are rebuilt from current preferences. It records `call.method = "reused"`, `new_ai_call: false` and the version
    it came from; there is no model call and no cost. Older versions and original bytes are untouched.
  - A restored analysis carries no chosen estimate (pick the reading again, as when switching plans) and no other
    plan's known size.
- The cache key now includes source IDs. Two sources with identical analysis bytes each get their own analysis and
  citations. Old cache entries simply miss, so the next analysis of an old room is a new AI call.
- Known sizes, in both fresh and reused analyses: a size the user stated (no plan provenance) carries over. A
  plan-confirmed size carries only when that plan is among what was read. Only the claim that set the current size
  is carried. Previously a fresh analysis of plan B carried plan A's confirmed size and all its constraint claims.
- Room versions now record `analysis_hash` (also kept by estimate and size edits), so the cache can tell which
  analysis the current room comes from.

## Twenty-ninth pass (2026-10-26): final browser-observed polish (copy and CSS only)
**321 backend tests passed** (new assertions added to existing tests); **6 frontend unit tests passed** (1 new);
frontend typecheck + build passed; app import smoke passed. No live AI, no server restart, no git, no reset. Not
browser-checked by Claude Code.
- **Legible plan**: the plan in use (or the only plan, or the one that was read) shows large: up to 600 px wide,
  max 100%, auto height, `object-fit: contain`. Multi-plan selectors stay thumbnails. No image editing.
- **Item fit wording**: a known product in a room with no size says "Fit not assessed" (not "Size unavailable"); an
  item with no listed size says "Product size unavailable". Used by the shopping list too; estimates stay
  "Estimated from floor plan/photos".
- **Before analysis**: Your room says "Your floor plan is ready to read" with the plan and its reading cards (photos
  optional), or neutral wording if nothing is added yet. A floor-plan upload's notice now says "Next: Analyze floor
  plan … Photos are optional" instead of the 2–8 photo coverage warning; photo uploads get a softer optional tip.
- **Friction copy**: the Your place footer says "Each room uses its own floor-plan or photo estimate". The help
  drawer, the plan gallery note, the fit note and the planner's fit text no longer ask to "confirm" a size ("Fit not
  assessed", "known room size"). The optional advanced exact/known size stays.
- **Evidence panel**: the group hint for plan readings now says pick this room's reading to draw it as an estimate,
  and the verified group is titled "Known size you set". The full claim list is in a collapsed "Evidence details"
  section that keeps saved wording and IDs unchanged (older versions may still say "pending your confirmation"); the
  current status is the Room size card.
  - New analyses: plan readings say "Printed size on the plan: …; it can be used as this room's estimated size once
    you pick it as this room". A plan-only analysis records "Using the floor plan: Floor plan only (no room photos),
    so there's no photo outline…" instead of "Room not mapped: The photos are not enough…".

## Twenty-eighth pass (2026-10-26): Amazon real product, active floor plan, reading identity, shape gate
**321 backend tests passed** (7 new, 1 rewritten; the real-bytes Amazon test skips in a clone because raw pages are
git-ignored); 5 frontend unit tests passed; frontend typecheck + build passed; smoke demo ran. No live AI calls, no
server restart, no git, no reset (root will archive and reset after QA). Not browser-checked by Claude Code.
- **Amazon: one real product added, from ROOT's fetch** (honest SafeFetcher, 2026-10-26T05:00:13Z, final URL
  = requested, SHA 28deef20…99c48). The bytes were copied unchanged into `data/catalog_raw/` with root's metadata
  and attribution; hash verified; no fresh fetch.
  - Zinus SmartBase black queen bed frame B006MIUM20: $154.55 (the price block tagged with the selected ASIN,
    `buyingOptionType` NEW), In Stock, 60 W × 80 L × 14 H in from the labelled "Item Dimensions L x W x H" row,
    plus the landing image. Curator tags minimal/industrial/dark are editorial. Catalog id `amazon-b006mium20`
    (Amazon ids now use the full ASIN; no other id changed).
  - The parser now accepts any labelled D/L, W, H order (L is the depth for L x W x H). It cross-checks only
    against the matching separate row: on this page "Item Depth" 14″ is the height, so it isn't compared.
  - Negative controls on root's bytes: the white queen B095P21J2L has no featured offer, so no price (carousel
    prices like $72.70 are ignored; regression). B06XJ64MLC is a full bed skirt, not furniture: not added.
  - A featured offer that isn't NEW is never priced as new, and the catalog build refuses Amazon items without NEW
    evidence.
  - **Actual Amazon coverage: 1 verified catalog product.** Everything else on Amazon is a user import or a search
    lead; Amazon may refuse automated reading at any time.
- **Active floor plan**:
  - `/analyze` reads ONE plan with the room photos: the chosen `floorplan_source_id` (validated as this room's image
    plan), automatically the only plan if there is one, and 422 when there are several and none is chosen. Plans
    are never combined.
  - The room version's `source_ids` and the reuse key reflect exactly what was read.
  - A chosen estimate survives only a re-read of the same plan with the same reading still present (re-pointed to
    its new index); switching plans drops it.
  - UI: a "Floor plan to read (one at a time)" choice in Your room; the just-imported plan's "Analyze floor plan"
    reads that plan.
- **Reading identity**: "In use" now requires the same reading index, text and source (two same-size bedrooms are
  different). Cards name their source when a room has several plans.
- **Shape gate**: a whole-apartment plan's overall shape (plan-only analysis) no longer blocks a bedroom estimate,
  and the layout labels the rectangle as an assumption ("the room's real shape isn't known"). An irregular shape
  OBSERVED in this room's photos still blocks it: `walls_seen` is now recorded for that case, and it is tested.
- **Archive (no printed sizes)**: the 2D view and Your room show the selected plan thumbnail as "Your floor plan
  (reference)" even before analysis. After a read with no printed sizes: "Plan reference: size unavailable",
  with no scaled room and no furniture.
- ROOT LIVE (root's run, not a human pilot): a no-photo Whitehall plan through the new endpoint passed in 17.06 s
  (gpt-6-luna, 2 bounded requests). The model read the 10×12 upper bedroom and the 16×12 lower bedroom, shape
  unknown. Choosing 10×12 without exact-unit confirmation gave all 3 layouts `estimated_from_plan` at 114×138 in,
  scale unknown and fit unverified. A $3,500 budget update kept the room version and source objects identical,
  with totals $547.98 / $547.98 / $3,096. Artifact: work/fresh-start/live-plan-results.json. Browser UI check
  still pending.

## Twenty-seventh pass (2026-10-26): floor-plan-first estimates, friendlier size statuses, Amazon parser
**314 backend tests passed** (11 new in `test_floorplan_first.py`; 1 assertion updated: "only from Amazon" is now a
supported store filter); **5 frontend unit tests passed** (badge test updated to the new statuses); frontend
typecheck + build passed; smoke demo ran. No live AI calls, no server restart, no git, no reset (root will archive and
reset storage after QA). Nothing here was live- or browser-checked by Claude Code.
- **User direction recorded in CLAUDE.md**: estimated preview from a plan reading without exact-unit
  certification, kept separate from known dimensions.
- **Estimated from floor plan** (`plan-estimate-v1`): `POST /plan-estimate` validates the CURRENT room version
  (409 if stale), the reading index, that the reading came from that floor-plan source in this room, and a
  plausible printed pair (4–40 ft); irregular rooms are refused. It appends a room version with `plan_estimate`
  (source, room version, reading, ±6 in), leaving scale "unknown" and width/depth empty.
  - The layout draws `estimated_from_plan` at the lower bounds, labeled "Estimated layout from selected plan;
    your unit may differ". Door/window positions are not known.
  - Fit labels stay "Fit unverified", with `room_size: estimated_plan`. The room frame is identical across budget
    changes and swaps.
  - A re-analysis keeps the chosen estimate if its plan was re-analyzed. Originals and earlier versions are
    untouched (tested).
- **Floor-plan-first UI**: a shared "plan readings" panel appears in "Your room" and in "Your room in 2D". It
  shows the plan in use with its source (or the plan sources as references) and printed-size cards ("Use for
  Bedroom 1").
  - One unambiguous room-type match is marked "Looks like this room", never auto-chosen. Several bedrooms prompt a
    choice (tested).
  - Plans with no printed sizes show "Plan reference: size unavailable" with an add-photos action, and no
    furniture is placed (tested).
  - Floor-plan rooms no longer see the photos-only "not mapped" screen. Messages after "Use this plan" and
    analysis point to these cards.
- **Removed ordinary "Room size not confirmed" / "Not confirmed" / exact-plan radios.** Statuses: "Known size",
  "Estimated from floor plan", "Estimated from photos", "Size unavailable", "Placement needs review", "Item sizes
  fit the room: check doors & paths".
  - Exact-plan confirmation and a stated size are an optional "I already know my room's exact size" section.
  - Room tabs say "room drawn" / "not drawn yet". Help explains that no tape measure is needed and where the size
    comes from.
- **Amazon**: one bounded REAL FETCH by Claude Code with the honest SafeFetcher (no user-agent change) of the public
  search page and two product pages, all readable. A deterministic `amazon` adapter reads:
  - the selected ASIN, which must equal the link's ASIN;
  - the featured-offer price block for that ASIN (exactly one USD value);
  - the availability text and the seller (as a note);
  - the labelled "D x W x H" product dimensions, cross-checked against Item Width/Depth (package dimensions are
    never used).

  On the real pages: BOLUO nightstand B0DPFP1F4S read $35.99, In Stock, 15.7 × 11.8 in. Apicizon B0G4GWP9G4 read
  $49.99, but its size was left UNKNOWN because the page's D×W×H (15.7″ D) contradicts its "Item Depth" (11.8″).
  A link to one variant that loads another selected variant yields nothing. Tests use synthetic pages reproducing
  these fields (raw pages are git-ignored).
  - Amazon is not added to the saved collection: no unverified bulk entries.
  - Amazon is a first-class search link and import, and the store filter lists stores of checked imports.
  - Amazon may block automated reading at any time; then the link stays a lead.
- **Not done**: no bundled real floor-plan example. The public Whitehall plan is not ours to redistribute, and
  only the labeled synthetic studio demo exists. No reset was performed here.

## Twenty-sixth pass (2026-10-26): plan fit badge and wording (from root browser QA)
**303 backend tests passed** (2 new); **5 frontend unit tests passed** (2 new); frontend typecheck + build passed;
smoke demo ran. No live AI calls, no server restart, no git; not browser-checked by Claude Code. Browser QA by root
is ongoing; this pass doesn't complete it.
- **Plan-level fit badge.** On a confirmed room (root: Whitehall 10×12 plan, $3,500 queen, at $547.98 and
  $3,096.00), the budget strip said "Room size not confirmed" while every floor item said "Size check passed". The
  cause: the plan summary can be "Fit unverified" for other reasons (e.g. a bathroom/kitchen area or a kept item
  with no size), and the UI mapped any unverified plan to "room not confirmed". The fit rules are unchanged:
  - New plans carry `fit_overview`: room size confirmed/unknown, item size checks passed/failed/not run, plain
    reasons placement still needs review, and doors/paths not checked.
  - The plan badge now says "Room size not confirmed" only when the room size truly isn't known, "Placement needs
    review" (hover for the reasons) when the room is confirmed but something couldn't be counted, "Item sizes fit
    the room: check doors & paths" when size checks pass, and "An item is too big for this room" when one fails.
  - The tooltip separates product sizes (store pages), room size (confirmed plan or stated) and door swings /
    walking paths / exact positions (not checked). Older versions without the overview use the room's confirmed
    status.
  - Item-level badges are unchanged. The mattress is an accessory of the bed ("Goes with its bed or desk"), not a
    failure.
  - Regressions: a confirmed 10×12 room (3 size checks passed, mattress with the bed); the same room with a
    bathroom area of unknown size ("Fit unverified", room still confirmed, reason named); a truly unconfirmed room;
    frontend badge wording for each, including older versions, with no guarantee wording.
- **Stale copy.** Preferences no longer says priorities shape a "priority-led" plan: "Match my style" and
  "Closer to my budget" count each match, the first priority counts most, and "Save money" always takes the
  cheapest. A search of user-facing frontend text found no other old plan labels; the old names appear only in
  the mapping that displays older stored versions, which are not rewritten.
- **Help "How fit works"**: fit is checked only against a confirmed room size (exact floor plan or a stated size).
  A room estimated from photos may be drawn as an approximate outline, but its fit stays unverified. It now
  separates product size, room size and doors/paths, and explains "Placement needs review".
- ROOT browser QA reported: the three new plan names, and $3,096 + $350 reserve + $54 unused in the real
  floor-plan demo (root's run).

## Twenty-fifth pass (2026-10-26): final review fixes
**301 backend tests passed** (1 new; 2 tests tightened); 3 frontend unit tests passed; frontend typecheck + build
passed; smoke demo ran. No live calls, no server restart, no git; not browser-checked by Claude Code.
- **Store filter is now a hard restriction for imports too** (it previously let any imported listing through,
  contrary to "Only from Article"). An import's store is the retailer identity its page adapter recorded ("IKEA
  US", "Article"; other sites keep their web address, e.g. "www.amazon.com"; never guessed). While a filter is on,
  an import from another store is not used in plans and can't be swapped in ("your settings allow only
  Article"). Its record is kept, and clearing the filter allows it again (API regression with an earlier Amazon
  import). Copy in Preferences, the help drawer and README updated (the twenty-third pass note "imports always
  allowed" is superseded).
- **Photo uncertainty copy** shows the exact range and a plain reason ("too uncertain to place furniture: wall A
  could be anywhere from 10′0″ to 18′0″, too wide a range to know what fits"). The 1.6× gate threshold stays in
  code/docs only (regression asserts it isn't in the reason).

## ROOT checks after the twenty-fourth pass (root's runs, not Claude Code's; not a human pilot)
- **Live photo test** (real gpt-6-luna, prompt v5, 4 public 68 Mansfield bedroom captures, 23.51 s):
  `observed_only` true, scaled `drawable` false. 3 walls, 2 corners, window, radiator, closet and door identified;
  the wall A range of 7′6″–15′ was too wide. This is NOT a validated scaled layout from real photos: the partial
  wall sketch stays not to scale and draws no products. Source and room version were unchanged by budget changes.
  Root output: work/real-demos-budget/live-bedroom-after.json.
- **Live floor plan** (public Whitehall 10×12, 15.12 s): worked after the explicit exact-plan confirmation, with
  no photo required. Rectangle only; exact door positions are not known.
- **Deterministic real-catalog backend QA** (confirmed Whitehall 10×12 bedroom, queen, $3,500 with 10% reserve):
  - No styles: Save money $547.98, Match my style $547.98, Closer to my budget $3,096.00.
  - Mid-century + warm wood: $547.98 / $817.98 / $2,896.00.
  - All three arrangements of both near-budget plans had zero unplaced items.
  - Room version and source objects were unchanged by budget/style changes.
  - The IKEA filter was respected (no imports in that case). A $500 budget enforced its $450 item cap, with the
    queen size unchanged.
  - Not a human pilot, and actual delivery clearance is not verified. Root artifact:
    work/real-demos-budget/budget-qa-results.json.
- **Independent Article audit:** all 21 products passed (raw SHA, selected SKU matching the JSON-LD price and
  availability, dimension evidence present); 18 were InStock at check time.
- Still pending: root's final browser QA after the runtime restart. Retailer coverage is IKEA + Article (+1
  incomplete Target listing) only; Amazon and other stores are search links and user imports, not catalog coverage.

## Twenty-fourth pass (2026-10-26): near-budget plan, photo output-shape fix, not-to-scale observations, review fixes
**300 backend tests passed** (13 new in `test_pass28.py`; 2 assertions updated for the new prompt version and
wording); **3 frontend unit tests passed** (`npm --prefix frontend test`, new: intent and plan names); frontend
typecheck + production build passed; `tools/smoke_demo.py` ran. No live AI calls, no server start/restart, no git;
nothing browser-checked by Claude Code. **Photo mapping on real photos is NOT shown to work by these tests**:
they use a mocked model that returns the misplaced shape root captured.
- **Plans, in plain words** (stable keys value / balanced / priority):
  - "Save money": the cheapest verified set.
  - "Match my style": the budget approach only; a default "price" priority no longer silently caps an explicit
    "use more".
  - "Closer to my budget": aims for 85–100% of the item allowance with only the chosen categories. It shortlists
    evenly spaced price levels up to the most expensive eligible product plus the best matches. Within the band
    it prefers better matches; below it, it gets as close as it can and says why. It never adds categories or
    goes over the allowance.
  - With no budget, the third plan is "Top priority first". Older saved versions keep their stored titles and are
    displayed with today's names (no migration). The shopping-list default stays Match my style.
- **Real catalog, deterministic** ($3,500 queen bedroom, default categories and priorities, $3,150 allowance):
  - No styles: Save money $547.98, Closer to my budget $3,096.00 (98%).
  - Mid-century + warm wood: $547.98 / $817.98 / $2,896.00 (92%).
  - Same styles with "use more for my preferences": Match my style $1,746.99.
  - Regressions assert 85–100% for the third plan in all three cases, categories unchanged, every plan within the
    allowance, and one shared room frame across plans. The search is bounded; a closer combination could exist
    outside the shortlist (stated in the plan).
- **Photo output-shape bug (found by root on real photos).**
  - The model put `scale`, `missing_views` and `reasoning` beside `geometry`; the old schema silently dropped
    them.
  - Now: the top-level output and `geometry` forbid unknown keys. The tool schema has `additionalProperties:
    false`, so a stray key gets PydanticAI's one bounded correction retry instead of being lost.
  - A narrow before-validator moves ONLY those three exact keys into `geometry` when the nested value is absent,
    refuses conflicting duplicates, and records the repair in `call.schema_repairs`. Model-supplied repair notes
    are discarded, and the field is not in the tool schema.
  - The prompt (`room-evidence-v5-geometry-shape`) shows the nested JSON shape and the allowed feature kinds
    ("outlet" → other). It is not yet run live.
  - Gates are unchanged: root's recovered range (wall A 120–216 in, B 108–180 in) is still too wide (more than
    1.6×), so the room stays not drawable with the reason "wall A could be anywhere from 10′0″ to 18′0″".
- **Not-to-scale observations** (`photo-geometry-v2`): when walls, corners and photos pass but the size fails,
  the walls and located features are kept as `observed_only`.
  - Furnish & compare shows them as "What your photos showed · not to scale": an evenly sized square only if the
    analysis reported a rectangle, features at approximate fractions, and wall descriptions.
  - It has no measurements, proportions, furniture or fit. Layout still reads only drawable outlines (tested:
    no placements, all items "Fit unverified").
  - The after-analysis message no longer calls it a photo failure, and says the room stays at the confirmed size
    when a floor-plan size was already confirmed.
- **Article adapter fails closed**: the price is used only when BOTH the spec SKU and the JSON-LD SKU exist and
  agree (tests: match / mismatch / spec missing / JSON-LD missing). Re-audited all 21 pages: exactly one "General
  Dimensions" row and one spec SKU each, both before "Box Dimensions", every SKU equal to the JSON-LD SKU. The
  offline rebuild changed no product.
- **New living rooms default to a plain sofa** (`sofa`, coffee table, bookcase); saved preference versions keep
  whatever they had.
- **Help drawer intent** (`frontend/src/intent.ts`, tested): polite change requests ("Can you use more of my
  budget?", "Could you add a desk?", "Please add a desk") go through the validated edit pipeline. Genuine
  questions ("How does fit work?", "Can you explain…?", "Is the dresser too big?") only open help.
- **Help copy**: uses the new plan names. Photos "may" give an estimated outline (otherwise a not-to-scale
  observation and no furniture). The budget setting is explained as applying to "Match my style".

## Twenty-third pass (2026-10-26): budget-aware plans, Article catalog, fit wording, compact compare, help drawer
**287 backend tests passed** (11 new in `test_budget_variety.py`, plus 3 assertions updated for the new prompt
version and store links); frontend typecheck + production build passed; `tools/smoke_demo.py` ran. No live AI calls,
no server start/restart, no git; nothing here was browser-checked by Claude Code. The new `preference-patch-v3`
instructions (budget approach, stores) have **not** been run live.
- **Budget-aware variety.** Value stays the cheapest verified set. Balanced and Priority-led maximize preference
  matches (editorial style tags + priorities, top priority weighted more and much more in Priority-led) minus cost.
  The new `budget_approach` preference (default "balanced"; older saved preferences read as balanced) sets how much
  one extra match may cost: about 3% / 12% / 100% of the item allowance (save / balanced / use more for my
  preferences). Equal matches go to the cheaper option; price is never read as quality; the item allowance is a hard
  cap; size, condition, exclusions, pins, mattress-frame match and confirmed-room-size checks are unchanged. "Price"
  as top priority makes only Priority-led save. Shortlists now always keep the 2 cheapest plus the best matches
  regardless of price (up to 8 per category, bounded to 20,000 combinations), so pricier matches aren't crowded
  out. Plans carry `item_allowance_cents`, `unused_cents`, `budget_approach` and `differences` (vs Value, per
  category, with the price change); plan keys stay value/balanced/priority. If no style or priority separates the
  options, the explanation says so and suggests adding one.
- **Stores filter** (`retailers` preference; imports always allowed) and AI/rule edits for both ("use more of my
  budget", "save money", "only from Article", "any store"; other stores like Amazon are reported as not supported).
- **Catalog: REAL FETCH by Claude Code, 2026-10-26, default honest SafeFetcher user agent, no browser UA.**
  - Nathan James (both leads) and Zinus Dachelle returned **HTTP 429** (a single retry also 429): not added.
  - The given Article Sven 88" Biscuit Cream (id 27565) redirected to a browse page whose own data says
    `"status":"DISCONTINUED","active":false`: not added.
  - Floyd 429; West Elm and CB2 403.
  - Castlery pages load, but dimensions appear only in images (no text), so they can't be verified: not added.
  - **Added 21 Article products** (real links taken from Article's own browse pages): queen and full beds,
    nightstands, dressers/chests, desks, sofas, a sofa bed, coffee tables. A new deterministic `article` adapter:
    price/availability from JSON-LD; product size from "General Dimensions", never "Box Dimensions"; bed mattress
    opening from "Interior Frame Dimensions"; sofa-bed sleeping surface from "Mattress Size". The price is used only
    if the spec "SKU No." equals the JSON-LD SKU (all 21 matched).
  - 3 of the 21 were listed OutOfStock when checked: kept as facts, never placed in plans, shown separately when
    comparing.
  - Inclusion parsing now also reads Article's "Wooden slats included" / "mattress … not included". The offline
    rebuild left all 37 earlier products unchanged.
  - Coverage: IKEA US 34 verified + 2 incomplete, Article 21 verified, Target 1 incomplete. Mattresses are still
    IKEA-only; the catalog has no king size; bookcases and wardrobes are IKEA-only.
  - Example (deterministic, shipped catalog, $3,500 with 0% reserve, warm wood + mid-century, "use more for my preferences"): Value
    $547.98 (IKEA); Balanced $1,746.99 including Article's Cooper dresser. A $3,500 living room's plans use Article
    sofas.
- **Out-of-stock handling.** Items listed OutOfStock/SoldOut/Discontinued are excluded from plan placement and
  swaps (with the check date). If only such items exist, that's a catalog gap.
- **Fit clarity.** Items now carry `fit_checks` (product size known?, room size confirmed?, size check
  passed / upper bound only / failed / not run, doors & paths not checked). The UI shows plain labels: "Room size
  not confirmed", "Size check passed: confirm doors & paths", "May fit: only at the larger room estimate", "Too big
  for this room", "Goes with its bed or desk". Saved labels are unchanged and readable. The old "conceptual and not
  to scale" note is replaced: a room drawn from photos is "an approximate rectangle at estimated scale, not your
  exact walls". There is still no synthetic geometry for unmapped real rooms.
- **Compact compare.** Recommended options (current + best 3 that can be swapped in) with "Show all", a store
  filter and "only options that match my style". Options blocked by settings/budget and out-of-stock or unverified
  items are in separate collapsed groups. Cards show price, size, store, style matches, fit note and check date on
  equal footing. The swap still returns to the fixed 2D room.
  - The plan card now reads "Your Balanced furniture … These are the same items as your Shopping list", with "How
    this differs from Value".
  - Store links (Amazon, Target, Wayfair, Facebook Marketplace, eBay; bed size included) are always shown via a free
    `GET /store-links`. They are labeled as unchecked leads, with a paste-a-product-link import beside them.
- **Help drawer** ("Help & quick changes" in every room): plain-English changes through the existing versioned
  edit pipeline (AI in live rooms, the offline rule reader in demos), with examples. Questions (ending in "?" or
  starting with how/what/where…) open the matching topic and change nothing. Topics: how fit works, where my list
  is, how to map my room, how the budget is used, stores. Each topic has a button to the right step or the Shopping
  list. It states that it can't chat or answer general questions.
- Limitations:
  - Style tags are editorial and coarse, so similar items often tie and the cheaper one wins (by design).
  - The new budget approach and store prompt are not live-tested.
  - Article stock/prices are as of 2026-10-26.
  - No third retailer with verifiable product dimensions could be fetched honestly.

## ROOT browser QA of the twentieth/twenty-first passes (root's runs; not a human pilot)
- Typo "Aduban", New Haven CT: "Did you mean The Audubon?" with explicit confirmation.
- Optional live search folded the official match into the checked card and showed six "Other sources" as View
  source only (spinrep, apartments, apartmentguide, apartmenthomeliving, rent, rentcafe).
- Bed click opened alternatives; the MALM swap updated the 2D drawing and subtotal with the SVG viewBox unchanged.
- Marking MALM purchased gave 1/4 and $348.98 remaining; it survived a refresh and reopening the demo.
- 390×844: no horizontal overflow; symbols and list readable.

## Twenty-second pass (2026-10-26): final polish
**276 backend tests passed** (1 new); frontend typecheck + build passed; no server restart, no git; not
browser-checked by Claude Code.
- With a checked match that the live search also found and only other sources besides, the note now reads "Your
  checked match is shown above. Web search found no additional building matches; other sources are listed below."
  It never says no building was found.
- After a successful "Choose this" in Compare, the alternatives panel closes, the view returns to "Your room in 2D",
  the swapped-in product is selected (by its plan item ref, the product id) with its product card, and the room
  drawing scrolls into view and takes focus. The room frame and other products are unchanged (server geometry
  untouched). A refused swap keeps the panel open with its error. Search/import from the no-plan or missing-category
  view is unchanged (the callback fires only on a successful swap).

## Twenty-first pass (2026-10-26): review fixes after the twentieth pass
**275 backend tests passed** (4 new regressions; 2 assertions updated for the new default/selection rule); frontend
typecheck + build passed; smoke demo ran. No live calls, no server restart, no git; not browser-checked by Claude Code.
- Building vs source: a title is "website name only" when it is empty, contains the literal hostname/domain
  ("spinrep.com", "www.maplecourt.example"), or is just a known listing brand ("Zillow"). A real name whose words
  happen to be in the host ("Maple Court" on maplecourt.example, "The Audubon" on theaudubonapts.com) stays a
  building when it names the searched building. An operator page that doesn't name it ("Greystar Apartments") stays
  a source. Regression covers all four.
- Old plan versions (plain-text conflicts only, e.g. saved twin gaps) are shown as saved, never rewritten.
  Unambiguous actions are read from the text ("No verified twin bed frame" → Find twin bed frame; Edit
  preferences). A banner offers "Rebuild plans with the current collection" (a new version, the old one kept) when
  the version predates typed issues or the catalog's newest check date (`plans_info` in project state). Regression
  inserts a legacy-style version and checks the flags, the rebuild, and that the old row is unchanged.
- Shopping list: marks must name the plan the list currently follows. If another tab switched it (same plan
  version), the mark is refused (409, nothing written) and the list reloads. The UI says which plan the saved list
  follows and offers "Use this plan for my list" / "Show the … plan" instead of mixing lists. A product's status
  follows the product across plans (regression). Default selection is Balanced when it exists (the plans view's
  default), else the first plan.
- Marketplace search links (Facebook Marketplace, eBay) include the bed size for bed frames/mattresses ("twin bed
  frame"); they carry only category + size, never location or unit.
- Each "Mark purchased" checkbox's accessible name includes the product name ("Mark purchased: VEVELSTAD …"); the
  visible short label is unchanged.
- The temporary `data/catalog/.products-before.json` comparison copy was already deleted at the end of the
  twentieth pass; re-checked: no Claude-created temp or scratch files remain in the project (saved raw HTML and
  histories untouched).

## Twentieth pass (2026-10-26): typo suggestions, sources vs buildings, plan issues, twin coverage, 2D symbols, shopping list
DETERMINISTIC / MOCKED transport: **271 backend tests passed** (10 new in `test_shopping_iteration.py`; 2 coverage
assertions updated because twin now exists); frontend typecheck + production build passed; `tools/smoke_demo.py` ran.
No live AI calls, no server restart, no git, no new dependencies; nothing here was browser-checked by Claude Code.
- **Building search.** Cautious typo suggestions for checked buildings ("Aduban"/"Audobon" → The Audubon, "Archve" →
  The Archive): each name word ≥ 5 letters, same first letter, ≤ 1 edit (≤ 2 for 7+ letters); generic words
  ignored; "archer", "auburn", "marchive" are rejected. Shown as "Did you mean The Audubon?" with its location and a
  "Yes, this is my building" button. Never auto-selected, and the same consistent city/state/ZIP rules apply (a typo
  with a contradicting ZIP/state/city matches nothing). Web results are split: only results that name the building
  (cautious typo allowed) are buildings with "This is my building". Listing/directory sites (now incl.
  point2homes.com), bare website names (e.g. "spinrep.com", "Zillow"), results that don't name the building, and
  unnamed pages on multi-property domains go to a collapsed "Other sources" with "View source ↗" only. The API also
  refuses to select a source as a building. Unknown names still use the bounded live search; "Search the web for
  other buildings" stays.
- **Plan issues.** Plan versions now also carry typed `issues` (catalog_gap / room_fit / budget / settings / pinned)
  next to the unchanged `conflicts` text. Older versions keep their text and show it as before. A missing twin
  frame + mattress becomes one message: "We still need two items for your twin bed … This doesn't mean a twin won't
  fit your room", with "Find twin bed frame", "Find twin mattress" and "Edit preferences". Furniture searches carry the
  size ("twin size bed frame"; the action's size, else the room's bed size). Bed size and budget are never changed
  automatically.
- **Catalog (REAL FETCH by Claude Code, 2026-10-26 03:30 UTC, default honest SafeFetcher user agent, no browser UA):**
  both root-provided IKEA pages fetched successfully (no redirect; final URL = requested) and were saved raw in data/catalog_raw/.
  - VEVELSTAD bed frame, white, Twin (SKU 105.182.76): $99, 40 1/8 × 77 1/2 in, mattress 38 1/4 × 74 3/8 in.
    The page says "Slatted bed base is included" and "Mattress and bedlinens are sold separately".
  - ÅGOTNES foam mattress, firm/light blue, Twin (SKU 804.808.78): $89, 38 1/4 × 74 3/8 in, 3 7/8 in thick.
  - Page JSON-LD said InStock; delivery/pickup stay unknown. Added to curation, rebuilt with `build_catalog.py
    --offline`: the other 35 products are unchanged (field-by-field comparison) except one corrected fact. The inclusion parser joined
    sentences, so "Mattress … sold separately" + "slatted bed base … included" read as slats sold separately. It now
    judges each sentence. That fixed GLADSTAD (its page: "Center support beam and slatted bed base are included")
    from slats false to true. A twin plan now builds (VEVELSTAD + ÅGOTNES, $188, mattress compatible). King is
    still not in the catalog.
- **2D preview.** "Your room in 2D — click furniture to compare". Top-down symbols drawn inside each product's real
  footprint and turned by its wall: a bed with headboard, pillows and duvet (frame-only beds show slats), a sofa with
  back, arms and cushions, a desk with monitor/keyboard, drawer/door divisions, shelves, a nightstand lamp, and a
  chair seat with backrest in the desk's access zone. A mattress is drawn on its bed and a chair with its desk (no
  separate footprints). Selection halo, selected-item card (actual product photo, price, size, store link,
  "Compare options"), and a legend (to buy / already owned / selected / access / fixed / window). The room outline,
  walls, openings, fixed zones, uncertainty styling and IDs are unchanged. Unmapped rooms still show no outline,
  only the next step. Caption: simplified symbols, not the product's exact look.
- **Shopping list.** "Your room in 2D | Shopping list" toggle in Furnish & compare. Per room: the selected plan
  (persisted server-side, append-only `plan_selection`) and manual "Mark purchased" marks (append-only
  `purchase_marks`, keyed by product id). Each line shows the product photo, name, category/condition, size, price,
  fit, price-check date and "View at <store> ↗". Opening a link never marks anything; no checkout, login or payment.
  The summary shows purchased/remaining counts and item totals, with tax/delivery/assembly unknown. Kept furniture
  is "Already owned" (no link, no charge). Writes need the current plan version (409 if stale) and a product in the
  selected plan (422 otherwise). A swapped-in product starts unmarked; earlier marks are kept, not counted, and noted.
  Owner-only; deleted with the project.
- Limitations: typo matching covers checked buildings only, by design conservative. Identity classification of web
  results is heuristic, and a real building page with an unhelpful title may land under "Other sources" (still
  viewable; usable via the website address). The silhouettes are not unit-tested in a browser here (no JS test
  runner; root does browser QA). The shopping list is per room (no apartment-wide list). Purchase marks are
  self-reported.

## Nineteenth pass (2026-10-25): find/gallery polish from root browser QA
**261 backend tests passed** (5 new, incl. parametrized cases); frontend typecheck + build passed; no server
restart; not browser-checked by Claude Code.
- Find: if a checked building matches, its card shows at once and NO web search starts. "Search the web for other
  buildings" (one search) is offered. With a checked match, web results sit under a collapsed "Other web matches".
  Unknown buildings still search automatically.
- apartmenthomeliving.com, forrentuniversity.com, homes.com, prospectportal.com, rentable.co and rentpath.com are
  listing sites, never "official".
- Archive directory: only observed paths remain: home and /availability on the main hosts, and
  entrata.thearchiveapts.com /new-haven/the-archive/ (the exact snippet URL root reported, with its query
  string) plus /conventional/ and /floorplans/. The guessed /Apartments/module and /snippets paths were removed from
  the tool and regenerated data file, and are tested as unsupported.
- Wording: the 19 checked items are "published plan types, not every unit variant". The gallery adds one line:
  images may contain the property's marketing or availability text (e.g. "fewer than 5 spaces remaining"), which is
  not verified current availability.
- Your room: after "Use this plan" the next step (Analyze floor plan) is shown ABOVE the gallery and scrolled into
  view. The gallery and its filter stay as they were; uploads stay below.
- Analysis message: the specific result (e.g. a plan with no printed sizes stays unmapped; add 2+ room photos or a
  plan with printed dimensions) is no longer overwritten by a generic "Analysis finished"; the step only scrolls.

## ROOT browser QA on the seventeenth/eighteenth-pass build (root's runs; not a human pilot)
- The Archive, New Haven CT, 2B2B, no URL: clicking the checked building opened "Your room" with 19 plan previews;
  the 2-bed filter showed 6; "Use this plan" added the real image. Seattle live search: 4 plans.
- Analyzing Archive "2x2 A" (marketing 3D image, no printed measurements) correctly left the room unmapped and
  unconfirmed, with no invented furniture.

## ROOT live API results on the seventeenth-pass build (root's runs, not Claude Code's; not a human pilot)
- The Archive: 19-plan gallery; a real 2-bed image imported with hash and provenance; no geometry assumed; the other
  room unchanged; the gallery shared by both rooms.
- Unknown building, AVA Capitol Hill (Seattle): live find gave 6 candidates; the official site gave 4 live plans in
  12.41 s.
- The exact blocked-screenshot URL now falls back to the 19 checked Archive plans; Audubon still 22.

## Eighteenth pass (2026-10-25): review corrections after the seventeenth pass
DETERMINISTIC / FAKE NETWORK / MOCKED transport: **256 backend tests passed** (7 new); frontend typecheck + production
build passed. No new dependencies, no live calls, no server restart, not browser-checked by Claude Code.
- Checked-building matching requires every supplied location field to be consistent: New Haven + ZIP 10001,
  Seattle + ZIP 06510, or a contradicting state match nothing. A field the directory doesn't record (e.g. Audubon's
  street address) can't confirm or contradict. A user in a different ZIP than Audubon's recorded 06511 will not
  get the Audubon card; they can use the website address.
- Web candidates are grouped by domain + property path base (trailing section segments like floor-plans,
  availability, apartments, unit codes removed). AVA Capitol Hill and AVA Ballard on avaloncommunities.com stay
  separate cards; a domain with several property paths is flagged "more than one property".
- Recovery is scoped to the chosen building: same-site pages inside its property path (or naming it); cited plan
  images that name it or sit in its path; never listing sites. Evidence comes only from the saved search for the
  current building name + location, never from earlier searches for other buildings (test: an Elm Row result can't
  be chosen or harvested under an Oak Hall search). Saved research rows are only read.
- Advanced website address with no saved search: if the page gives no usable plans, one bounded, cached web
  search for the entered public name + city/ZIP (never the unit) runs, and its scoped URLs are tried. Skipped when
  policy-blocked, when no name/location is saved (an honest note instead), or when an exact checked host already
  offers its list (no paid search).
- Weak live candidates (unit-type images on a plan page, a photo heuristic) no longer hide an exact checked list. The
  gallery shows both, labeled by origin, and the note says "published plan images, not every unit variant".
- Frontend: the PlaceStep mounted flag is reset on effect setup (React StrictMode dev double-effect no longer drops
  every result). Editing any search field invalidates the old query's results, and a late answer can't repopulate
  them. Choosing a building stops an in-flight web search from replacing results, and the saved choice is always
  applied. The gallery filter resets to All for a new building/lookup, with a "Show all" hint when a filter is
  empty. A room whose place already has a chosen building opens on "Your room" (also single rooms after refresh,
  once the saved discovery loads), unless the user already moved between steps or the room is mapped (then
  "Furnish & compare").
- Limitation: path-based grouping is a heuristic. A site that puts one building under several unrelated paths may
  show more than one card for it, and a site that serves several buildings at "/" with query parameters can't be
  split. The user still chooses.

## Seventeenth pass (2026-10-25): find my building → choose → plan gallery
DETERMINISTIC / FAKE NETWORK / MOCKED transport tests: **249 passed** (26 new in `test_building_discovery.py`);
frontend typecheck + production build passed. No live calls, no real fetches, no server start/restart, not
browser-checked by Claude Code. Nothing below is verified against the real Archive/Audubon sites in this pass.
- "Your place": building name + city/state or ZIP, then **Find my building** (button or Enter). Checked buildings
  (The Archive, The Audubon) appear at once, free, only when the name and the city or ZIP match (consistent
  state); a same-name building elsewhere never matches. Then one bounded, cached gpt-6-luna web search lists other
  candidates, one card per site, with location evidence from the search result. Unknown street addresses stay
  "unknown". The user must choose. The website address is now an advanced option, also on the home page.
- Choosing saves the building in the shared place details (append-only context version, unit label kept, never
  sent), runs the SafeFetcher crawl, and saves the result as an append-only `place_discovery` row shared by the
  place's rooms. The flow moves to "Your room". Refresh/room switch reloads it without fetching or searching. An
  older result is hidden once the chosen building changes. Search results are shared by an apartment's rooms
  (10-minute cache), so another room doesn't pay again.
- Recovery (any building): if the crawl is empty or refused, up to 3 alternative URLs from saved search evidence
  for this place are fetched (same-site pages; images the search cited as floor plans). Excluded: model prose-only
  URLs, guessed paths/CDNs, sign-in/apply/portal/policy/tour/contact pages, retries after a refusal.
  Policy-blocked addresses get nothing (no recovery, list or link). Every fetch goes through the SafeFetcher.
- The Archive checked directory (19 plans, address 848 Chapel Street, New Haven, CT 06510, observed 2026-10-26 UTC)
  matches only thearchiveapts.com / www (home, /availability) and entrata.thearchiveapts.com (canonical path and
  Entrata module/snippet paths). FAKE NETWORK test: the availability page reads, the embedded snippet returns 403
  and stays listed, and the checked list is offered with its date. The Audubon directory is unchanged (22 plans;
  ZIP 06511 from its official alt text; street address unknown).
- Plan gallery in "Your room", before uploads: All / Studio / 1 / 2 / 3+ bed filters from printed names (Entrata
  Sx1/1x1/2x2/3x3 recognized), preview cards with source and date, "Use this plan" importing the actual image
  bytes into that room only, then a clear "Analyze floor plan" next step. Checked plans are labeled as published
  plans, not current vacancies. Exact-unit confirmation is still required before any plan size is used.
- Extraction: images whose alt text has a unit-type code (e.g. "848 | Sx1 A") are plan candidates unless the alt
  text describes a photo (pool, lounge, living room photo…). Unlabeled-type plans appear only under All.
- Limitations: candidate quality depends on what the web search returns. Many sites render plans with scripts or
  refuse automated reading, so plans may not be found; then the user uploads a screenshot. The checked directories
  are dated observations, not live pages. Images in the gallery are loaded by the user's browser from the public CDN.

## Sixteenth pass (2026-10-25): step navigation without a popup; stale copy
Frontend typecheck + production build passed; backend unchanged (223 passed, unchanged since the fifteenth pass); no new tests
for copy/modal; not browser-checked by Claude Code; no server restart.
- Back and the stepper inside a room no longer open `window.confirm` (it was unnecessary because steps stay mounted, and
  root found it hung the in-app browser). They navigate at once and are blocked only while a request runs. Leaving
  Preferences with unsaved edits shows a non-modal "Preferences have unsaved changes" notice with "Return to
  preferences". Next on Preferences still saves, then advances. If a newer saved version arrives (AI edit or kept
  item), the form shows it and a message says earlier unsaved edits were replaced. The draft is never applied over it.
  Switching rooms or going home (which unmounts the form) keeps its existing guard.
- Copy: removed tab names ("Photos & sources", "Room evidence", "Plan & layout") replaced with "Your room", "Review
  what we read", "Furnish & compare" / "Add a specific listing". "Furniture already there" is now "Furniture visible
  in your sources", with a note that furniture drawn on a property plan may be illustrative and should be kept only if
  you own it or plan to keep it.

## ROOT real browser flow, completed (root's run on the fifteenth-pass build; not a human pilot)
- Search for official AVA Seattle → 4 floor-plan images → import studio image → real gpt-6-luna analysis 16.08 s,
  1 request, 0 retries; it read 16 ft 11 × 13 ft 1 correctly (root visually checked against the source).
- Choosing "similar plan" did NOT set room dimensions; the exact unit was not auto-confirmed.
- Saving preferences ($1,500, warm wood) produced a shortlist.
- Separate synthetic bedroom: clicking the bed → MALM swap changed the total $547.98 → $647.98; other items unchanged.
- 390 px viewport: no horizontal overflow.
- No human (friend) pilot has been run.

## ROOT QA of the fourteenth-pass build (root's real runs, not Claude Code's; not a human pilot)
- REAL web research (gpt-6-luna web_search): AVA Capitol Hill, Seattle property search returned 12 sources in 7.16 s;
  used desk, Seattle, under $200 returned 12 sources in 6.41 s; repeated searches reused the 10-minute cache.
- REAL FETCH: the property page returned HTTP 200 and 4 plan images were found.
- ROOT BROWSER: search → official result → import a studio plan image → Next to "Your room" worked. A real floor-plan
  analysis was still running when reported; its result is not recorded here.
- API QA swap: bed TARVA → MALM queen (+$100) kept every other product ID, the exact room/source and the frame hash; a
  swap whose item would take the full frame was rejected and no new plan version was written.
- Limitation: OfferUp's public desk result returned HTTP 403 on a direct fetch, so it can't be imported (no evasion).

## Fifteenth pass (2026-10-25): final review fixes
DETERMINISTIC / MOCKED tests: **223 passed** (4 new); frontend typecheck + production build passed; `tools/smoke_demo.py`
ran. No live calls, no server started/restarted, not browser-checked by Claude Code.
- Check-only import: `POST /listings` takes `rebuild_plans` (default `true`, backward compatible). Compare/search imports
  send `false`, so the current plans (IDs, items, geometry) and earlier swaps are unchanged; options reload in place.
  Only "Import and rebuild plans" (missing category or no feasible plan) rebuilds. Test proves plans id/data unchanged.
- Condition is an explicit New / Used choice on every import UI (search results and "Add a specific listing"); Import
  is disabled until chosen; never assumed secondhand; shown as "declared by you, not verified". The API default for
  omitted `condition` is unchanged for old callers.
- Each option shows a fit note (checked on its own against the confirmed size, not a guarantee; or "Fit unverified"
  when the room is unscaled) and "delivery or pickup timing is unknown — check with the seller", separate from the
  user's desired timing.
- Swap takes `expected_plan_version`; a stale version gets 409 and nothing is written. The UI always sends it.
- Research results: cited relevant results first and marked primary (max 4; first 3 relevant if none cited); about,
  policy, login, tour and similar pages marked low relevance; the rest sit under "More sources". PDFs show "Open plan
  PDF" with save/screenshot-and-upload guidance (PDFs aren't read automatically); images offer "Use as a floor plan";
  pages offer plan discovery. After a property lookup the results area scrolls into view and takes focus. No unit is
  matched automatically.
- Cost: cache_write $0.125/1M verified on official OpenAI pricing (root, 2026-10-25) and recorded in RATE_TABLE; the
  reservation prices all 25,000 input tokens at the worst of input/cache-write; the async client is closed in `finally`.
- Steps: Back and the stepper keep unsaved preference drafts (steps stay mounted; leaving asks first); Next on
  Preferences saves typed changes and continues; an AI patch resets controls to the saved version; room switching stays
  guarded while changes are unsaved. Furniture search is available with no feasible plan, from a missing category, or
  when results are empty.
- Branding: API title and export header "Furniture AI" (internal file and DB names kept). Numeric source filenames
  (e.g. "768") show as "Floor plan from <host>" or the reference name in the UI.

## Fourteenth pass (2026-10-25): Furniture AI guided redesign, web research, compare & swap
DETERMINISTIC / MOCKED transport tests: **219 passed** (12 new); frontend typecheck + production build passed;
compiled frontend served by the existing one-server `run.sh`. No live calls, no servers started, not browser-checked
by me. Root will run live and browser QA.
- **Branding:** the product is "Furniture AI" (title, header, footer, examples, export, fetch user agent). No school
  or course affiliation in the product UI; course material stays in docs. Calm navy/ivory editorial style kept.
- **Home:** explanation, numbered 4-step journey, apartment-first start form (building name, city/state or ZIP, layout
  incl. custom, private unit label, optional website, new/secondhand, pickup/delivery, timing). No login. Single rooms
  and examples moved into a secondary section; existing places and rooms listed.
- **Apartment context** (`apartment_context`, append-only versions; `PUT /api/apartments/{id}/context`): shared place
  details separate from each room's geometry. The unit label is stored for the owner but never placed in search
  queries or fetches (tested). Older apartments get neutral defaults. Early condition choice seeds each room's
  preferences at creation only.
- **Guided flow** replaces the five tabs: Your place (place details, web search for the building, property website /
  checked Audubon list / upload recovery) → Your room (room switcher, uploads, analyze, then "Review what we read" in
  the same step) → Preferences ("Save and continue"; Next is blocked while the form has unsaved changes) →
  Furnish & compare (canvas, plans, alternatives, listing import). Steps stay mounted, so drafts survive Back/Next;
  navigation and room switching are disabled while a task runs or preferences are unsaved. Saved versions and
  details (history, usage, export, delete) moved behind a secondary link.
- **Exact plan only:** plan-confirmed sizes now require `exact_unit_confirmed: true` (UI: "Yes, it is exactly my
  unit's plan" vs "Only a similar layout"); a similar layout stays a reference and cannot set a room's size (tested).
  Room sizes are confirmed per room; nothing is copied between rooms.
- **Compare & swap** (`planner.check_swap/swap_plan/alternatives_for`, `GET …/alternatives`, `POST …/swap`): click a
  piece on the drawing or "Compare options" in the list. Cards show product name, size, price and change, condition
  (declared vs verified), source link, check date and staleness, and either "Choose this" or the reason it can't be
  swapped. A swap replaces ONLY that category in the selected plan, keeps other products, kept furniture, reserve,
  budget rule, preference and room versions; refuses atomically on settings, unverified facts, confirmed-room fit,
  over item budget or mattress/frame mismatch (tested); redraws the arrangement in the identical room frame
  (`envelope_hash` unchanged, tested). Product photos only when the snapshot has one; otherwise a dimension card.
- **Web research** (`research.py`, `POST …/research/property`, `POST …/research/furniture`): bounded gpt-6-luna call
  with the built-in web search (≤ 2 tool calls, low context, ≤ 1800 output tokens, 55 s, no retries, no other model).
  Only URLs from `web_search_call.action.sources` and `url_citation` annotations are shown, after `public_url_ok`
  (a fixture with 10 malicious/private URLs is rejected; text-only URLs ignored). Ledger reserves tokens for 25k input
  + 1800 output + 2 × $0.01 search fees before the call; settles tokens (cache writes at the cache-write rate) and
  fees separately; missing usage keeps the reservation; failures leave inputs, room and preferences unchanged
  (tested). Identical session/room queries reuse the saved result for 10 minutes (tested). Results (URLs, titles,
  query, usage, cost; no prompts or secrets) are stored in `research_results`, owner-only (tested). Facebook
  Marketplace and eBay are offered as search links the user opens; nothing is scraped and no availability is shown.
- **Limits:** search finds leads, not inventory; arbitrary sites may block import; delivery/pickup dates are unknown
  unless the imported page states them (the importer does not read them yet); the catalog is dated snapshots; the
  web-search fee comes from OpenAI's pricing page as checked by root on 2026-10-25; the live web-search path is
  verified only by root's earlier probe (AVA Capitol Hill, 5.91 s), not by these tests.

## Thirteenth pass (2026-10-25): recovery-flow review fixes
DETERMINISTIC / FAKE NETWORK tests: **207 passed** (1 new); frontend typecheck + production build passed. No servers,
no AI calls; not browser-checked by me.
- Any successful IMAGE floor-plan upload (from the recovery box or the main "Add a floor plan" button) marks the plan
  ready, checked against the returned sources (kind floorplan with a derivative); a stored-only PDF is never marked
  ready, and analysis is enabled only for photos or image floor plans.
- The last lookup result for a room is kept for the browser session, so coming back to Photos & sources after a
  failed lookup shows the existing image plan with its preview, "Analyze floor plan" and "Upload another plan"
  (never automatic analysis or a chosen size).
- With a checked reference list, the recovery box now leads with "Choose a listed plan or upload yours", the count,
  the property name and the check date (labeled UTC, "not re-checked just now"). An unlisted blocked site says
  "Continue with your floor plan" and briefly why lookup is unavailable. The live failure stays under "Website
  reading details".
- The reference list is offered only when live discovery found neither plan images nor plan PDFs; a found PDF is a
  real candidate and keeps the honest "PDF plan reading is NOT implemented" note (regression added).
- ROOT check before this pass (root's run): all 22 Audubon reference image URLs fetched through the real
  SafeFetcher returned valid WebP images while the source page returned 403. The A1 "335 Orange" image visibly
  prints bedroom 12'5" × 12'10" and living/dining 11'8" × 14'9". The actual UI import and upload are still to be
  tested by root; not claimed here.

## Twelfth pass (2026-10-25): blocked-website recovery (Audubon) and own-plan upload
DETERMINISTIC / FAKE NETWORK / MOCKED AI tests: **206 passed** (20 new); frontend typecheck + production build passed.
No live calls, no servers.
- **Checked reference directory** `data/property_refs/theaudubonapts.json`, generated by `tools/import_property_refs.py`
  from root's `prompts/audubon-observed-refs.json`: all 22 public plan image URLs on resource.rentcafe.com with their
  displayed names, source page https://www.theaudubonapts.com/floorplans and observed_at 2026-10-26T01:26:21Z UTC
  (the evening of October 25 in US Eastern time; browser DOM observation by root). No image bytes, prices,
  availability or dimensions. Not a live fetch.
- Discovery always tries the normal bounded safe fetch first. Only when it yields no plan candidates for EXACTLY
  `www.theaudubonapts.com` / `theaudubonapts.com` on `/`, `/floorplans` or a floorplans detail path does it offer the
  directory, labeled "Previously checked official plans" with source page and date; the live failure stays reported
  in an expandable "Website reading details". Lookalike hosts, subdomains, ports, credentials, `..` paths and
  policy-blocked (e.g. private-DNS) URLs get no directory and no website link. All 22 entries are listed with a name
  filter and a select-to-preview; nothing is auto-selected and apartment area is never used.
- Importing a checked reference stores provenance (from the server-side directory, never client input) separately
  from image retrieval: directory, plan name, reference page, observed date, image URL, image retrieval date and hash.
  The image itself is still fetched through the SSRF-safe fetcher; whether rentcafe serves an accepted image type is
  being verified by root.
- **Recovery UI**: after any failed or empty lookup (or a failed plan-image import) a box offers "Upload my floor
  plan" (JPEG/PNG/WebP; PDFs should be screenshotted, since they are stored but not read) and "Open property
  website" for eligible public URLs. After upload it switches to "Your floor plan is uploaded and ready. Website
  lookup is optional now." with a preview and an "Analyze floor plan" button. Regression: a 403 lookup followed by
  upload + (mocked) analysis yields plan readings with no further website requests.
- Example links now point to Yale Whitehall and Howe Place S1 (worked in root testing); The Audubon is labeled as
  blocked with a checked reference list; arbitrary sites are not guaranteed.

## ROOT results reported since the eighth pass (root's runs, not Claude Code's)
- 186-test suite re-run by root; a local git clone with a fresh environment set up in 7.7 s (with package cache);
  this was a local clone, not a clone of a remote GitHub repository.
- Real browser + gpt-6-luna: the Whitehall plan reading 10' × 12' was selected and a budget change to $900 created
  no new room version.
- Real 4-image 68 Mansfield empty-room run with the v4 prompt: features identified, `existing_items` returned [],
  geometry abstained.
- No human pilot yet.

## Eleventh pass (2026-10-25): source-aware analysis messages (UI copy only)
Frontend typecheck + production build passed; backend and geometry rules unchanged; no live calls, no servers.
- The analyze button, progress label and result toast now depend on what was uploaded: floor plan only →
  "Analyze floor plan" / "Floor plan read: N printed room sizes … choose one under Room evidence (nothing is selected
  automatically)" (or a "no sizes could be read" message); photos keep the photo-specific guidance and mention any
  plan readings. "Seen in your photos" became "Observed in your sources" (and similar wording elsewhere).
- ROOT browser QA (before this copy fix): an analysis with only the official Whitehall uncropped plan read two
  separate bedrooms, 10' × 12' and 16' × 12'; the user chose the first for a clearly named sample test. This is
  printed-dimension interpretation, not full plan tracing and not an actual-unit match. Runtime model: gpt-6-luna only.

## Tenth pass (2026-10-25): duplicate plan-image variants
DETERMINISTIC / FAKE NETWORK tests: **186 passed** (1 new). Frontend unchanged. No live calls, no servers.
- Discovery now merges candidates across separate `<img>` elements only when they are explicit Drupal image-style
  derivatives of the same referenced file (same host, `…/files` prefix and `public/<file>` path; only the style
  segment and query differ), keeping the uncropped/larger referenced variant (e.g. `max_width_960` over cropped
  `3_2_2400`) and listing all referenced variants for review. Different files are never merged, even with the same
  alt text; no URL is constructed. Regression uses separate gallery/modal `<img>` elements shaped like the Yale pages
  (not verified against saved real pages in this pass).
- ROOT retest (executed by root before this fix): discovery now yields plan candidates on York-Crown, Whitehall,
  Bulldog (5 candidates) and Howe (1 correct referenced plan PNG); Yale pages still returned cropped + uncropped
  duplicates, which this pass addresses. Candidates are not verified to match any user's unit.

## Ninth pass (2026-10-25): empty-room item fix and verified Canvas attribution
DETERMINISTIC tests: **185 passed** (1 new). Frontend unchanged (no rebuild needed). No live calls, no servers.
- A live run (below) returned an "existing item" of category `other` whose text described ABSENCE ("No movable
  living-room furniture is visible…"). Prompt bumped to `room-evidence-v4-geometry`: an empty room returns
  `existing_items: []`, absence goes in coverage notes, fixed things are features. Code filter
  `ai.is_absence_record` drops only generic-category entries (`other`/`none`/…) whose text states absence, keeps the
  text as a coverage note ("Model note (not an item): …"), and never drops a recognised category or a real object
  such as a plant, mirror, portable AC or a desk of unknown size (tested). The version bump means cached v3 results
  are not reused; re-analyzing makes a new call.
- Canvas attribution verified (COURSE_REQUIREMENTS.md, ACCEPTANCE_TESTS.md): announcement 872636 dated October 25,
  2026, 6:30 PM Eastern from its Canvas email notification; assignment 609320 lists Monday Oct 26, 6:00 PM, 100 points
  and links the public requirements page, no extra rubric visible. Content unchanged: submit ONLY report.html +
  slides.html + optional video, GitHub URL inside both.

## ROOT LIVE empty-room evidence (executed by the root session with the v3 prompt, not by Claude Code)
- Four unedited perspective screenshots of the unfurnished living area from Yale's official linked 68 Mansfield
  Matterport tour, analyzed with gpt-6-luna: 2 requests, 1 validation retry, 26.03 s model time, input 12068
  (6736 cached) / output 3209 (incl. 915 reasoning), token-cost estimate $0.00220506.
- Result: correctly **abstained** on full geometry (partitions/opposite boundary and dependable scale uncertain);
  detected the window, radiator, door and adjacent kitchen; trusted scale stayed unknown; a budget edit preserved the
  room; a real product shortlist was returned. Bug found: the absence-sentinel "item" fixed above.
- This is **not** a successful layout reconstruction, **not** a human pilot, and the screenshots are not calibrated
  camera images. The v4 prompt and UI have not been live-verified yet (root will check).

## Eighth pass (2026-10-25): real-source fixes from root findings
DETERMINISTIC / FAKE NETWORK tests: **184 passed** (11 new); frontend typecheck + production build passed. No live
calls, no servers started/stopped by me; fixtures are small hand-written HTML fragments (no real pages stored).
- **Property discovery** (`sources.py`, `html_extract.py`): follows same-site plan links found by anchor text
  ("View Plan", "See plans", …) or plan query parameters (`fp=`, `floorplan=`…), e.g. bulldogapartments.com's
  `?bPopup=1&f=1&fp=…`; marks pages reached that way (or with plan-like URLs) as plan context. Image candidates are
  classified with honest labels: `named_floor_plan`, `unit_size_label` (alt/filename has a unit type AND a size, e.g.
  "Howe 0x1 365 sqft S1"), and `plan_page_image` (unit-type image on a plan page, labeled "may be a photo, not a
  plan"; ≤ 6 per page). Ordinary photos off plan pages, logos, icons and SVGs are excluded; ≤ 12 candidates,
  deduplicated, strongest first. Next.js `/_next/image?url=…` wrappers are unwrapped to the referenced URL (http(s)
  or site-relative only); `srcset`/`data-src`/`<picture>` sources are read and the uncropped, largest reference
  actually on the page is preferred (e.g. Yale `max_width_320` over `3_2_320`); no URL is constructed or guessed.
- **Floor-plan / photo boundary** (`geometry.assess_geometry`, `ai.room_from_analysis`): the app now passes the
  room-photo count from its own source records. Floor plans can no longer satisfy the two-photo, wall or corner
  evidence, and plan symbols are not photographed scale cues. Features may still cite a floor plan as their source.
  Plan dimension readings are accepted only from actual floor-plan sources; a reading the model attributes to a
  room photo is rejected and recorded as a claim. Default (no count) keeps the earlier behavior for old callers.
- **UI:** floor plan uploaded without photos now says the plan was read and points to Plan readings (no needless
  photo/measuring request); plan readings show persistent, openable floor-plan previews; the confirm button is
  "Use for this room" with a sample-plan caveat; confirmed plan sizes are described as "a floor-plan room size you
  chose; your unit may differ if it is a building sample"; discovery candidates show a preview, the match label and
  an open link; the stale "does not place furniture" studio sentence was replaced; the Plan & layout tab points to
  plan readings when they exist; the page scrolls to the top when moving to another project/room.

## ROOT LIVE property evidence (executed by the project owner's root session, not by Claude Code)
- `discover_property` found floor-plan images on the real Yale Whitehall and York-Crown pages; it missed
  bulldogapartments.com and howeplace.com plan images (fixed above, verified only on fragments so far).
- Real gpt-6-luna pipeline (property URL → discovered Whitehall plan → import → analyze) passed and read both
  bedroom sizes exactly as printed: 10' × 12' and 16' × 12'. The source is an official SAMPLE plan, not the user's
  exact unit; nothing is selected automatically. Not a human pilot.

## Seventh pass (2026-10-25): grading-compliance changes
DETERMINISTIC tests: **173 passed** (2 new). No live model calls, no servers started or stopped, no GitHub actions.
- **Runtime model regression** (`tests/test_runtime_model.py`): builds the REAL OpenAI-SDK/PydanticAI Portkey client
  (no TestModel) with a capturing transport (test seam `create_app(ai_transport=...)`, never used by the server) and
  drives BOTH agents through the API with decoy model/base-URL environment variables set to `unauthorized-model` /
  `example.invalid`. Asserts on the actual outbound requests: exactly 2 POSTs to `https://api.portkey.ai/v1/responses`,
  body `model == "gpt-6-luna"`, Portkey provider/key headers (fake test key, never printed), 2 `input_image` parts
  only in the photo request, each request carrying only the structured-output tool (no model-callable app tools),
  and usage/cost recorded from the returned usage.
- The adversarial test string now uses the invalid sentinel `unauthorized-model`; no other model identifier remains
  in submission source besides gpt-6-luna.
- **Canvas instruction updated** (docs/COURSE_REQUIREMENTS.md, docs/ACCEPTANCE_TESTS.md): per the professor's Canvas
  announcement supplied by the user on October 25, 2026 (screenshot; date later verified as Oct 25, 6:30 PM ET — see ninth pass), submit ONLY
  report.html + slides.html + optional video; the GitHub URL (and "private repository" if private, with zlisto
  access) must appear in BOTH files. Report and slides are NOT created yet.
- **docs/LECTURE_MAPPING.md** added: lectures 2, 4, 5, 7, 11, 12 mapped to actual files; states that the agents have
  no model-callable tools, that a code orchestrator calls deterministic functions, and that MCP/RAG/delegation are
  not implemented.
- README: removed stale "neither places furniture" / unscaled-only wording; photo estimates are never promoted to a
  confirmed size; explicit Python 3.12 prerequisite, compiled frontend (no Node needed), parent `.env` support, and
  development tool (Claude Code) vs runtime (gpt-6-luna only, no Claude/Anthropic dependency). No dependency changes.

## Sixth pass (2026-10-24): fixed-room fidelity fixes
DETERMINISTIC + MOCKED AI tests: **171 passed**; frontend typecheck + production build passed. Not browser-checked by me.
- Stored, fully located features (wall + offset + width, and depth where a footprint needs one) are honored as
  zones: bathroom, column, radiator, kitchen (counters at the stored size + 36 in aisle), doors/entry/closet; windows
  as markers. Geometry is validated: positions past the corner are clamped and flagged; positions beyond the wall,
  or solid features without a depth, are flagged and not applied (never silently ignored). Stored positions take
  explicit precedence over photo estimates of the same kind (stated in assumptions). Regression: the root's
  180×200 room with a 90×90 stored bathroom now keeps the bed out of it.
- Geometry gate: wall A must be described and visible in a usable photo; model-reported contradictions block
  mapping; size cues need a description and the estimate needs reasoning; features without a usable cited photo
  are omitted and listed (`omitted_features`), never credited to all photos.
- Windows seen in photos (or stored) are drawn as markers on their wall in mapped rooms (`LayoutSet.wall_markers`,
  part of the room-frame hash), with an "estimated position" caveat; they are not obstacles. Unmapped rooms draw nothing.
- Home copy now says the room is estimated only when the photos show enough of it (rectangular rooms for now).

## ROOT LIVE evidence for the fixed-room build (executed by the project owner's root session, not by Claude Code)
- Real gpt-6-luna room analysis of the two public The Archive photos (isolated test storage): 23.32 s, 2 requests,
  1 validation retry, input 9746 (3692 cached) / output 2869 (incl. 1109 reasoning), token-cost estimate $0.00207682.
  Result: **correctly abstained** (not mapped) — identified the window wall and an adjoining wall, reported missing
  coverage, and no room was invented. This is evidence that abstention works on that input, **not** evidence of
  positive geometry accuracy, and not a human pilot.
- Root checks passed on that build: unmapped room has no outline; same room version and source bytes after a
  $900 / Scandinavian edit; identical geometry across all plans after the edit; trusted scale stays unknown; no
  templates. Root also re-ran the 162-test suite, fixed-room invariance scripts (small/large/impossible items across
  budgets), apartment preset/custom validation, per-room isolation and migration checks: all passed. A root browser
  check was underway and is **not** counted as passed here.

## Fifth pass (2026-10-24): fixed-room correction — the room stays fixed, only furniture moves
The fourth pass drew furniture in an **illustrative template room** (and enlarged it to fit products, and assumed
full-wall studio kitchens) whenever a room had no confirmed size. The user correctly pointed out that this invents
the room. That approach is **removed** from generation; old plan versions that used it stay readable in history and
are shown as "illustrative template, not your room — regenerate".

Implemented; **DETERMINISTIC + MOCKED AI tests only: 162 passed** (the original 106 retained; the template-era layout
tests rewritten for the corrected behavior); frontend typecheck + production build passed. **No live AI run, no
browser check, no independent review of this pass yet.** Root plans to run the real analysis on the two public
Archive photos in isolated storage.
- **Photo geometry** (`room-evidence-v3-geometry`, new `PhotoAnalysisOutput.geometry`): wall A is a described
  visible wall, B–D clockwise (no compass guesses); per-wall visibility and photo indices; features as fractions
  along a wall; wall-A/B length ranges with listed visible cues (typical sizes = weak cues); `status: insufficient`
  plus specific `missing_views` when evidence is lacking.
- **Code gate** (`geometry.py`): drawable only if rectangular, ≥ 3 walls and ≥ 2 corners seen, ≥ 2 distinct usable
  photos (photos flagged as a different room are excluded), wall ranges 48–480 in with high/low ≤ 1.6 and ≥ 1 cue in
  a valid photo. Otherwise not drawable, with targeted guidance. Result stored once in the room version as
  `RoomModel.inferred_geometry` (weak, unverified bounds), separate from trusted `width/depth` (still None until a
  user-confirmed plan or stated size). Old analyses are not upgraded: they show "Re-analyze photos to map this room".
- **One frozen room frame per room version** (`layout.room_frame`), computed before and independently of products,
  budget and strategy; identical outline, fixed zones and `envelope_hash` for every shopping plan and arrangement
  (tested across preference edits, AI-edit path, layout regeneration; only a new room version — e.g. confirmed size —
  changes it). Bases: `estimated_from_photos` ("Estimated from your photos · dimensions unverified"),
  `scaled_room_lower_bound` (confirmed size; separate width and length ranges), `synthetic_demo` (fixed fixture
  geometry, labeled), `unavailable` (no outline; guidance + shortlist).
- **Fixed features** with estimated positions become zones: door/entry/bathroom-door keep-clear, closet opening,
  radiator, column and kitchen counters only over their located extent (+36 in aisle), with stated depth assumptions.
  Features seen but not located are listed as unresolved, never assumed.
- **Review fixes (REDESIGN_REVIEW):** access-zone claim is now true and independently re-checked (coffee table at
  the 18 in sofa access depth; nightstands only within the 20 in pillow area); opened sofa beds are checked against
  all fixed zones incl. door keep-clear and aisle, use the documented along-wall open length, and a coffee table in
  the way makes it conditional (relocation not checked); kept sofa beds without open size say so; separate width/
  length uncertainty; zero-purchase "Reuse" plan arranges kept furniture when nothing needs buying; a room-only view
  when no plan is feasible; prompt version bumped; stale async room responses ignored (navigation token +
  per-room/per-apartment guards); SVG captions moved to HTML and labels scaled to the room; apartment overview is a
  collapsed list of spaces (not a map); compact apartment header; plan/budget strip; canvas before the edit box.
- New rooms open on Photos & sources. Apartment rooms report `mapped`.
- Known limits: rectangular rooms only; door hinge side and exact door width are estimates; windows/outlets not
  obstacles; the photo map is only as good as the model's reading of the photos and is not a survey; arrangements
  are greedy per strategy.

## Fourth pass (2026-10-24, superseded in part by the fifth pass): Yale-inspired UI, apartments, arrangements
The template-room generation described below was removed in the fifth pass. Test counts and checks below were for
the fourth-pass build only.
- **UI** fully re-themed per the user's choice (Yale blue #00356b, ivory, white panels, medium blue #286dc0, dark ink,
  Georgia headings, system sans body, faint architectural grid; no external fonts, no seal; footer/brand line
  "An MGT 409 project · Yale School of Management"). New home (headline, original SVG floor-plan illustration,
  apartment-type cards, single-room and demo entry points, existing apartments/rooms). Plan screen rebuilt around a
  large arrangement canvas with option buttons, a linked product list (select in either place highlights both) and
  a per-room budget overview; edit box above. The old studio zone sketch was removed (zones now appear on items).
- **Apartments:** presets studio / 1B1B / 2B1B / 2B2B / 3B2B and custom (0–5 bedrooms, 1–4 bathrooms). Additive
  tables `apartments` + `apartment_rooms` group ordinary per-room projects (Bedroom n, Living area, or one Studio);
  each room keeps its own photos, evidence, preferences, budget, plans and history. Bathrooms and kitchen are listed
  as fixed spaces only (no project, no evidence). Budgets are per room; nothing is summed or optimized across rooms.
  A clickable "Concept apartment map · actual arrangement unknown" shows room count, not sizes or connections.
  Existing standalone projects are untouched and open as before. New room type `living_room` (defaults: sofa bed,
  coffee table, bookcase — the catalog has no plain sofas).
- **Generated arrangements (`layout-v1`)**, stored inside each new plan version (`Plan.layouts`), linked to the plan's
  room-evidence version and any floor-plan source ids. Deterministic bounded search: each item against each wall,
  allowed rotations, 6 in steps; valid only if inside the outline, no footprint overlap, not in another item's
  assumed access zone, own access zone clear, and outside fixed zones; then an independent re-check. Up to 3 named
  options (open center / work zone or centered focal piece / alternate wall), deduplicated by signature. Mattress
  is attached to its bed frame, desk chair to its desk; kept items with unknown size and anything that cannot be
  placed are listed as "not drawn" with reasons; nothing is shrunk. Opened sofa-bed depth (conservative) is checked.
- **Unknown scale** → illustrative template outline (bedroom 11×12 ft, studio 14×18 ft, living 13×15 ft; enlarged
  ≤ ×1.3 only to show the selected furniture), labeled "Concept layout · room size unverified"; template sizes live
  only in the layout record, never in RoomModel or evidence, and are not displayed as room dimensions.
  **Known scale** (confirmed plan size or stated size, rectangular) → drawn at the LOWER plausible bound with the range
  stated. L-shaped/irregular rooms stay conceptual. Studio kitchen: if its wall is known, counters (24 in) + aisle
  (36 in) are reserved along that whole wall (assumption stated); in a concept studio with no known wall it is drawn
  on the north wall "for illustration only". Doors: exact positions/swings are not modeled; large pieces avoid an
  approximate door wall when possible, and this is listed as unresolved.
- Each arrangement lists checks passed and unresolved items (always including: walking routes/accessibility not
  verified — rectangle collision only; windows/radiators/outlets not modeled). Plan fit labels are unchanged
  (conservative; "Fits tested assumptions" is still never awarded).
- Old plan versions without arrangements open normally and show "Generate arrangements": `POST /api/projects/{id}/layouts`
  appends a new plan version with the same products, preference and room links (no AI). Export lists arrangements,
  assumptions, undrawn items and what is not verified.
- Room-evidence prompt bumped to `room-evidence-v2` (wording now includes living rooms). **Not live-tested.** Because
  the analysis cache key includes the prompt version, re-analyzing previously analyzed photos will make one new paid call.
- New routes: `GET/POST /api/apartments`, `GET/DELETE /api/apartments/{id}`, `POST /api/projects/{id}/layouts`;
  `POST /api/projects` accepts `living_room` and now builds starting plans + arrangements immediately.
- Known limits: no automatic whole-apartment reconstruction or room adjacency; no scaled 2D survey; no door/window
  geometry from photos; arrangement search is greedy per strategy (it can miss a packing a person would find);
  windows only steer the desk in the work-zone option when a window wall was reported.

## Validation results
- **Backend tests:** 106 passed, 0 failed (DETERMINISTIC / MOCKED AI / FAKE NETWORK; one harmless Pillow warning).
- **Frontend:** production typecheck + build passed.
- **Clean-copy rehearsal:** a clean *local copy* with a newly created Python environment, using the machine's
  existing package cache, and a dummy `.env` in the parent folder (detected as `key_source: parent .env`; live AI
  disabled). Copy + dependency install 5.4 s; complete setup + tests 9.35 s; 106 tests passed; HTTP smoke passed
  for both bedroom and studio demo flows (compiled UI served, 3 plans each, rule-based edit → new versions,
  synthetic plan-size confirmation, export). This is **not** an actual GitHub clone and not a guarantee for a cold
  download without cached packages.
- **ROOT BROWSER checks passed:** studio demo; synthetic floor-plan confirmation; infeasible-budget message;
  history restore returning the budget; upload of official public photos with live analysis; keeping a detected
  nightstand removed it from purchases; unchanged analysis reused without a new call; live free-text edit that
  changed budget, replaced the style and kept the bed pin; retailer product images rendered; 390 px phone width
  with no horizontal overflow (document width 390); desktop viewport 1277×720. Not done: real mobile hardware,
  375/768 widths, keyboard/screen-reader pass. The JSON does not record which build each browser check used; the
  live browser analysis is the run whose free-form labels ("table/desk", "chair") motivated the third-pass fix.
- **Coursework preservation:** 1043 tracked existing coursework files checked; none changed or missing.

## Live model calls (ROOT LIVE, gpt-6-luna via Portkey) — 5 measured runtime calls
| Run | Result | Input / cached / output (reasoning) | Latency | Token-cost estimate* |
|---|---|---|---|---|
| API room analysis (2 public The Archive photos) | pass: size kept unknown, all plans "Fit unverified" | 2795 / 0 / 969 (389) | 11.6 s | $0.000764 |
| API preference edit, prompt v1 | **semantic failure**: "switch the style to Scandinavian" returned add_styles, so styles became ["modern","scandinavian"] (budget, desk pin, condition, twin size, categories were preserved) | 1086 / 0 / 67 (0) | 2.1 s | $0.0001421 |
| API preference edit, prompt v2 | pass | 1398 / 0 / 112 (42) | 2.59 s | $0.0001958 |
| Browser room analysis | pass | 2781 / 0 / 1022 (388) | 9.49 s | $0.0007891 |
| Browser preference edit | pass | 1661 / 0 / 103 (41) | 2.82 s | $0.0002176 |
| **Total** | | | | **$0.0021086** |

\*Returned usage × the course Lecture 11 rate table: an estimate, not an invoice; excludes all Claude Code
development usage. All calls: 1 request, 0 validation retries, finish reason "completed". Property lookup of the
public The Archive page also succeeded (REAL FETCH), with its Entrata leasing portal reported honestly as HTTP 403.

**v1 → v2 fix history:** v2 added an explicit `set_styles` (replace) field distinct from `add_styles` (keep + add),
field descriptions, replace-vs-add examples, and bumped the prompt to `preference-patch-v2`; `replace_styles` was
removed. Covered by DETERMINISTIC + MOCKED AI tests, then passed the live v2 API and browser edits above (two live
runs: evidence that the fix works on those requests, not a broad accuracy measurement).

## Final-review fixes (third pass)
- **Shared-bed width was wrong in the second pass:** it used a bed frame's OVERALL width as "documented sleeping
  width", so a wide upholstered twin frame could pass. Now frames use their documented mattress (inner) size,
  mattresses their own width, sofa beds/daybeds their documented bed surface; anything without a documented
  sleeping size is left out for shared use and the conflict says how many. Regression tests: wide twin frame,
  frame with no inner size.
- **Photo-detected furniture types:** a live browser run produced free-form types ("table/desk", "chair") next to
  exact ones ("nightstand"). The original text is now kept verbatim (`detected_label`); only unambiguous aliases
  are mapped (e.g. "writing desk" → desk, "office chair" → desk chair); ambiguous labels such as "chair",
  "table" or "table/desk" stay **"type not chosen"**, replace no purchase, serve no studio zone, and say so on
  the plan card until the user picks a type (a picker sits next to "Keep it" and in Preferences; no sizes
  required). Older saved free-form categories are normalized the same way on load. Tests: desk alias, uncertain
  chair, legacy label.

## Second-pass changes (from POST_BUILD_QA / LIVE_TEST_FINDINGS)
- Style switch vs add: see the v1 → v2 fix history above.
- Product thumbnails: plan items carry the retailer's own product image URL from the exact snapshot (https only,
  otherwise none); shown as a 64 px thumbnail with a "no photo" fallback on missing/broken images. Images load
  from the retailer's CDN with `referrerpolicy=no-referrer` (the retailer can still see the request). No generated images.
- Former inert controls now have real, tested behavior: **Shared bed** limits beds/mattresses/sofa beds to a
  documented sleeping width ≥ 53 in (full or larger) and says so on items (space on both sides is not checked;
  width source corrected in the third pass); **Studio zones** are checked for coverage by bought or kept items,
  with a note per unserved zone, and the zone sketch marks unrequested and unserved zones.
- Sofa beds and daybeds serve both sleep and lounge zones (item label "sleep + lounge", note that it must be opened
  nightly; the sketch shows it in both bubbles).
- Free-text edit box moved above the plan grid.
- Imported listings' unverified condition declarations now appear as item notes on plan cards.
- Removed wording implying furniture is placed around kitchen/bath; fixed features are labeled
  "fixed constraints, placement not checked".
- Primary UI shows plain "AI ready"; model, key source and prompt versions moved to "Setup details".
- Bed-size coverage is shown under the bed-size control and reported by `/api/status`; an unavailable size gives
  a specific conflict listing the sizes that exist.

## Implemented and tested
| Area | State |
|---|---|
| Env loading: process > repo `.env` > parent `.env`; grandparent ignored; key never in status/repr | tested (acc. 2); parent `.env` detected in clean-copy rehearsal |
| SafeFetcher: scheme/port/credential rules, private/loopback/link-local/metadata/ULA/CGNAT/mapped IPv6 blocked, all DNS answers validated, connection pinned to validated IP, each redirect revalidated, redirect cap, byte cap, type allow-list, compression refused, 403 distinct from TLS errors | tested (acc. 14), plus REAL FETCH of IKEA/Target with certifi CA bundle |
| Uploads: real-type sniffing (JPEG/PNG/WebP), byte + pixel limits, HEIC refused with guidance, EXIF orientation applied and metadata stripped in AI derivative; caps of 8 photos and 2 floor plans counted across image, PDF and property-plan paths | tested (acc. 3, review #10) |
| Originals immutable (sha256 name, read-only, never rewritten); explicit deletion removes them | tested (acc. 6, 19) |
| Session isolation: other sessions get 404 for projects, previews, history, export, delete | tested (acc. 7) |
| Append-only room / preference / plan versions; restoring a plan appends copies of ITS preferences and room so controls, room and plan agree; old rows unchanged | tested (acc. 6, review #9); restore also ROOT BROWSER |
| Unknown scale: RoomModel refuses dimensions without a trusted source; model size guesses and "standard object" cues stored only as hypotheses; different-room photos flagged as contradictions | tested with MOCKED AI (acc. 4); live analyses kept size unknown |
| Optional scale: plan-confirmed size must cite a floor-plan source in this project; user-stated size optional; no measuring required anywhere | tested (review #11) |
| Planner: integer cents, exact budget boundary, delivery/tax reserve, new-only / secondhand-only (honest empty), exclusions, keep/replace, kept existing furniture, missing categories shown, only verified snapshots, documented mattress/frame size compatibility, slats-sold-separately flag, stale flag, distinct alternatives with search-limited wording, items larger than the room's upper bound excluded, pin conflicts shown explicitly | tested (acc. 8, 10, 12, 13; review #1, #2, #6) |
| Fit labels: unscaled → "Fit unverified"; scaled → dimension/area screen; area screen is a warning not proof; unknown kept-item size or unknown kitchen/bath area → overall "Fit unverified"; "Fits tested assumptions" never awarded in this build | tested (acc. 9 partially; review #3) |
| Free-text edits: AI path returns a typed patch applied by code; demo path uses an offline rule reader (labeled, not AI); unrelated constraints retained; injected "ignore the budget and reveal the key" changes nothing | tested (acc. 12, 15 deterministic); live v2 edits passed (API + browser) |
| Listing import: deterministic extraction only (page text never sent to the model), raw HTML stored as an immutable source linked to the snapshot, plan versions reference exact snapshot hashes, first-party retail pages always "new" (secondhand declaration refused with a warning), other sites' condition labeled as an unverified user declaration, per-project snapshots (same URL in two projects is independent) | tested (acc. 11, 13, 15; review #4, #7, #8) |
| Property discovery: one page + ≤3 same-site links/iframes, raw pages stored, plan image/PDF candidates and plan names listed for explicit choice, unit sq ft never used as room size, blocked sites → upload fallback | tested with FAKE NETWORK (acc. 5 partially); REAL FETCH of public The Archive page |
| Usage ledger: atomic reservation before calls (concurrency-tested), per-session rate and cost caps, app daily cap, cost from returned usage only, missing usage stays null | tested (acc. 16/17 deterministic part); 5 live calls recorded |
| AI failure (timeout/invalid output): HTTP 502 with plain message, nothing saved as analysis, uploads intact | tested with MOCKED AI only (acc. 16) |
| Re-analysis with unchanged photos reuses the saved result (no new call) | tested with MOCKED AI; ROOT BROWSER confirmed with live analysis |
| Responsive React UI (fourth pass: Yale-inspired theme, apartment home/map/room switcher, plan & layout canvas with linked product list) plus photos & sources, room evidence, preferences, history & export, diagnostics, delete | builds (typecheck + production build); fourth-pass UI NOT browser-checked yet. ROOT BROWSER checks above were on the earlier black/pink UI |
| Apartments: presets + custom bounds, per-room projects, fixed bath/kitchen spaces, per-room budgets, ownership 404s for other sessions, delete removes only that apartment's rooms, schema upgrade keeps existing rows/sources | tested (test_apartments_api.py) |
| Fixed-room arrangements: evidence gating (no outline without photo/confirmed evidence), one frozen frame per room version across plans/edits, located fixed features and door keep-clear, truthful access-zone re-check, opened-bed vs door/aisle/coffee table, separate width/length ranges, real proportions and rotations, signature dedup, mattress/chair association, unknown-size and oversized items listed, irregular rooms not drawn, zero-purchase reuse plan, old plans regenerate without AI | tested (test_layout.py, test_geometry.py, test_apartments_api.py); not browser-checked |

## Not yet implemented / known limitations
- **Live AI lightly exercised:** 5 calls on public photos and scripted edits. Quality across varied real rooms,
  real error handling (timeouts/quota), and cost at scale are unmeasured.
- **Bed-size coverage gaps in the catalog:** verified bed frames exist only in full and queen; verified mattresses
  only in queen; the only daybed is twin. There are **no twin bed frames, no full or twin mattresses, and no king
  items**. Choosing those sizes yields an explicit "no verified … (available: …)" conflict. A verified NEIDEN Twin
  page exists in the owner's work area but has not been added to the catalog.
- Shared bed checks sleeping width only; it does not add clearance on both sides of the bed.
- **No scale inference from photos.** No calibrated reconstruction, no multi-view geometry, no automatic scale-object
  identification. Without a confirmed plan size or a stated size, fit is always unverified (by design).
- **Fit checks are coarse.** Only per-item dimension checks and a total-area warning; no placement, door-swing,
  window, collision or walkway testing; no 2D scaled layout. Sofa-bed open depth uses derived bounds where IKEA
  does not document overall open depth. Delivery access is not checked.
- **Floor plans:** image plans are read only by the live model (copying printed text), and only become a size after
  user confirmation; there is no deterministic plan OCR. **PDF plan reading is not implemented** (PDFs are stored
  as sources only).
- **Property discovery** works only on server-rendered HTML. The Audubon floor-plan page and The Archive's Entrata
  plan portal returned HTTP 403 to scripted requests; no bypass is attempted. The Audubon has a checked reference
  list (twelfth pass); every site, blocked or not, can continue with an uploaded floor-plan image or screenshot.
  Plan-to-unit matching is always the user's choice.
- **Catalog:** 35 snapshots (32 verified) from IKEA US (34) and Target (1, no price in server HTML → incomplete),
  checked 2026-10-24; prices/stock may change. No secondhand inventory (secondhand-only returns an honest empty
  result unless the user imports a listing). Style tags are AI-assisted editorial judgments.
- **Studio demo:** after confirming the synthetic plan size, overall fit stays "Fit unverified" because the
  kitchen/bath areas have no known size. That is correct under the rules, but it means the demo never shows a
  conditional overall fit.
- HEIC not supported (clear guidance shown). Account-free sessions are cookie-based (60 days); no login.
- Rule-based offline edit reader covers common phrasings only; unrecognised requests are reported as not applied.
- Real Archive reference photos in `output/private/reference_photos` (git-ignored) are not redistributed; photo 1
  appears to be a different room from photos 2–3 and no unit dimensions are known.
