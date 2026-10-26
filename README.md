# Furniture AI

Furnish the apartment you actually live in. For a place (apartment), a design-first flow — **Place & floor plan →
Arrange your space → Choose furniture → Final checklist** — finds your building's public floor plans (or takes your
own plan image), reads the ONE plan you pick into a map of your whole place, lets you arrange draft furniture on it,
then fills each piece with a real, dated, sourced product (new or secondhand) and ends with one shopping checklist.
It says plainly what was read, what is approximate, and what is still missing. No account, no tape measure, no
special phone hardware. Single rooms (and the older per-room tools, kept in a collapsed section) still use the
earlier Your place → Your room → Preferences → Furnish & compare flow.

Repository context: this code is also Ken Tam's solo final project for a graduate course (MGT 409); course material
lives in `docs/` and is not shown in the product. **Status: working local MVP, frozen for submission on
2026-10-26.** See [docs/STATUS.md](docs/STATUS.md) for what is implemented, tested, and not yet done, and
[docs/LECTURE_MAPPING.md](docs/LECTURE_MAPPING.md) for how course concepts map to the code.

Built with Claude Code as the development tool. **The application runtime uses only gpt-6-luna through the course
Portkey gateway and has no Claude/Anthropic dependency** (no Claude account, no Anthropic key).

## Quick start for reviewers (fresh clone, about 5 minutes)

1. **Python 3.12** (`python3 --version`; other versions aren't tested). Node.js is NOT needed: the compiled
   frontend is in `frontend/dist`.
2. **Key (optional for the offline demo):** put the `.env` with `PORTKEY_API_KEY` either in this repository's folder
   or in the folder directly above it (e.g. `submissions/.env` next to `submissions/<this-repo>/`). The app reads the
   process environment first, then `./.env`, then `../.env` for anything still missing, and never looks higher. The
   key is never shown or logged; the start-up line prints only where it was found (`key source=…`).
3. **Start:** `./run.sh` (creates `.venv`, installs the pinned `requirements.txt`, serves the UI and API from one
   server). Open **http://127.0.0.1:8000**. If port 8000 is busy: `./run.sh --port 8080`. Without the script:
   `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python serve.py`
   (Windows: `py -3.12 -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`, `.venv\Scripts\python serve.py`).
4. **Deterministic demo (no key, no network, no AI):** on the home page press **Example bedroom** or **Example
   studio**. These use drawn sample images and a hand-written room description; they are clearly labelled synthetic
   and are not real rooms or AI output. `./run.sh --no-live` guarantees that no AI call is made.
5. **Live flow (needs the key and internet; results depend on live websites and aren't guaranteed):**
   - Create a **1 bedroom** place for **The Archive, New Haven, CT 06510** and pick the building from the checked
     list (free: no search).
   - Use one of its published 1-bedroom plan images, then press **Read floor plan** (one gpt-6-luna call). Arrange
     the draft furniture.
   - In **Choose furniture**, set **New only** and a **$3,000** budget, then press **Find furniture for my plan** (a
     few bounded web searches) or **Choose for me** (saved checked catalog only, no AI).
   - Finish in **Final checklist** and use the two downloads (printable HTML and Excel).
   - AI use is capped per session and per day (see "AI allowances" below); the app says plainly when a cap pauses
     it.
6. **Tests (offline):** `.venv/bin/python -m pytest -q backend/tests`. Frontend unit tests need Node 22.6+:
   `npm --prefix frontend ci && npm --prefix frontend test`.

**Data in this repository:**
- `data/catalog/products.json`: product snapshots checked from the stores' own pages, with dates and evidence
  snippets. Prices and stock may have changed since.
- `data/property_refs/`: lists of public plan-image URLs observed on two buildings' official pages (no image bytes).
- **Not included:** raw page snapshots (`data/catalog_raw/`), so the catalog-rebuild tools are for reference only.
- No user data, uploads, databases or keys are included.

**Known limits that affect a live run:**
- Secondhand marketplaces often refuse automated reading: eBay listing pages answer HTTP 403, and AptDeco often shows
  robot checks. The app never bypasses these; a refusing marketplace is skipped and named.
- Affordable used supply is thin, so the live demo uses **New only**.
- A floor-plan reading is an AI reading of a picture, not a survey.

## Run it locally

Prerequisites:
- **Python 3.12** (`python3 --version`). Dependencies are pinned in `requirements.txt` and installed into `./.venv`.
- No Node.js needed: the compiled frontend is included in `frontend/dist` (Node is only needed to rebuild it).
- Optional: `PORTKEY_API_KEY` in `./.env` or in the parent folder's `.env` (e.g. a fresh clone placed inside the
  folder that holds the course `.env`). Without it, live AI is off and everything else works.

```bash
./run.sh                 # creates .venv, installs pinned deps, serves UI + API on http://127.0.0.1:8000
./run.sh --no-live       # never call the AI model (demo / offline)
./run.sh --port 8080
```

Equivalent without the script: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python serve.py`.

AI photo analysis and AI free-text edits need `PORTKEY_API_KEY` (course Portkey key). It is read from the process
environment, then `./.env`, then `../.env` (the parent folder) for anything missing. The key is never displayed or
logged. Without a key the app still works: preferences, plans, listing/property URLs, history, export, and a
**synthetic demo** (drawn images + a hand-written room description, clearly labeled, never presented as AI).

## AI allowances and search cost

Every AI call reserves an ESTIMATED cost before it runs, and the actual estimate replaces it afterwards. A call whose
usage wasn't returned keeps its full reservation. Reservations are atomic, and existing usage rows are never reset.
Three limits apply; each can be changed in `.env` (see `.env.example`) and is validated at start-up:

| Setting | Default | Allowed | Resets |
|---|---|---|---|
| `FURNISHAI_SESSION_AI_BUDGET_USD` | 2.00 | > 0 and ≤ 20 | never: it's a lifetime allowance for a browser session |
| `FURNISHAI_DAILY_AI_BUDGET_USD` | 3.00 | > 0 and ≤ 100 | at the start of each UTC day (app-wide) |
| `FURNISHAI_AI_REQUESTS_PER_10MIN` | 12 | 1–120 | as the rolling ten-minute window passes |

When a limit stops a search, the app says which one in plain language and pauses "Find furniture"; options found
so far stay. In the app, the session limit reads "the app owner can increase it"; the exact keys are only here.

"Find furniture" costs:
- **One click:** every needed piece type is searched once (price ceiling first, then style). Up to 12 of that
  search's approved pages are checked, two at a time, stopping at 3 distinct options that fit and are affordable.
  Pieces of the same type and size share one search, but each piece is its own choice.
- **Search more:** for types with fewer than 3 such options, an explicit "Search more for N piece types" button makes
  one more online search per type. It never runs by itself, and earlier results stay.
- **Budget:** only options within a piece's share and the whole remaining item budget are recommended. An option over
  the whole remaining budget is never offered, and the server refuses it.
- **Page checks:** independent listing and product pages are checked at most two at a time, with the same limits,
  evidence rules and short-lived check cache.
- **Duplicate searches:** identical concurrent searches in the same session and place share one in-flight search, so
  they're never paid twice; a failure isn't cached.

## Appearance and the design helper

- **Light / Dark / System**: a toggle in the top bar. "System" (the default) follows the device setting, also when it
  changes; the choice is remembered in this browser only. The clean floor plan has its own light and dark colours;
  older drawings and published plan images keep a light background so they stay readable. The downloads are always
  light.
- **Ask for help** (bottom-right in the apartment workspace) is a small helper for the four steps. Each message is one
  bounded gpt-6-luna call with the same usage limits as the other AI features.
  - **Answers:** questions get a short answer from an accurate guide to the app plus this design's settings and
    pieces, with buttons to the right step or piece. A question never changes anything.
  - **Changes:** a request to change something comes back as typed suggestions (add or remove a piece, budget,
    reserve, styles, new/secondhand, bed size, pickup/delivery, approach). Code checks them, and nothing changes
    until you tick them and press Apply. They're applied once, as one new design version; if the design changed in
    between, they're refused and you ask again.
  - **What the helper sees:** never your address, unit, building, photos, plan images, pages or links. Its replies
    can't contain links.
  - **Without AI:** if AI isn't connected, it only points to the right step.

## Taking the checklist with you (two downloads)

The last step of an apartment design, **Final checklist**, ends with **Take your checklist with you**:
- **Download printable checklist**: one self-contained HTML file (no scripts, no outside fonts or images) with:
  - what to buy, with quantities, prices and total, condition, sizes, check dates and "bought" marks;
  - missing and owned pieces;
  - the budget and the amount held for delivery and tax;
  - placement notes;
  - your layout, drawn from the plan reading, with pieces at their saved positions and rotations and the chosen
    product's listed size (or a dashed draft size), plus the doors and a TV on its stand.

  If the plan's rooms couldn't be mapped, or no usable room's use is confirmed, no drawing is included. Pieces
  that aren't placed are listed. Store links are clickable only for approved sources (Amazon, Article, IKEA,
  Target, approved resale listings). Your unit label, address and the original plan image are not included.

  On phones (640 px and narrower) the shopping table becomes one labelled card per product. Print the page or save
  it as a PDF from the browser.
- **Download spreadsheet (Excel)**: an `.xlsx` with three sheets (To buy, Missing and owned, Summary), real
  hyperlinks, and every text value stored as plain text (no formulas).
- Both are made by the server from the current design version (an older version is refused), and making them never
  changes the design or the bought marks. No email account or other setup is needed.

## Tests

```bash
.venv/bin/python -m pytest -q backend/tests      # offline: no network, no AI (mocked models / fake network)
npm --prefix frontend ci && npm --prefix frontend run build   # typecheck + production build into frontend/dist
npm --prefix frontend test                        # small frontend unit tests (Node's built-in runner; Node 22.6+)
.venv/bin/python -I tools/http_smoke.py http://127.0.0.1:8000   # against a running server; demo projects only
```

## How it works

```
Browser (React + TypeScript, compiled into frontend/dist)
   │ same-origin JSON API, per-browser session cookie
FastAPI (backend/furnishai/app.py) — a plain-Python orchestrator
   ├─ Plan Map agent       (PydanticAI, gpt-6-luna; reads ONE floor-plan image + two crops) → typed PlanMapOutput
   │     → code validates polygons/walls/openings/fixtures and decides each room's use
   ├─ Room Evidence agent  (PydanticAI, gpt-6-luna via Portkey Responses API; looks at photo pixels)
   │     → typed PhotoAnalysisOutput → code gates it into a room model; photo geometry is stored as an
   │       unverified hypothesis and never promoted to a confirmed size
   ├─ Preference Edit agent (PydanticAI, gpt-6-luna) → typed PreferencePatch → code applies it
   ├─ Design Helper agent  (PydanticAI, gpt-6-luna) → typed answer + proposals → code validates; user ticks + applies
   ├─ Web research call    (gpt-6-luna Responses API with the built-in web_search tool, ≤ 2 tool calls)
   │     → only cited URLs on approved sources; every page is then read and verified by code
   ├─ Deterministic code: catalog filtering, integer-cent budget, condition/exclusions/keeps,
   │     distinct alternatives, conservative fit labels, photo-geometry gate, fixed-room arrangements, versions
   ├─ SafeFetcher: bounded public-web fetch with private-network defenses (property pages, listings)
   │     └─ optional public page reader (r.jina.ai) for refused property pages, through a SafeFetcher too
   └─ SQLite (append-only versions) + per-project content-addressed original files
```

- **Four typed agents (plan map, room evidence, preference edit, design helper) with no model-callable app tools,
  one bounded call each, plus a bounded web-research call whose only tool is the provider's built-in web search.** The code orchestrator calls the
  deterministic functions (fetching, catalog, budget, layout) itself. The model cannot set prices, product facts,
  confirmed room size, budget outside the patch schema, or tool powers. Usage is reserved against per-session/app
  limits before each call and settled from the usage the API actually returns (missing numbers stay empty).
- **Room size.** The photo model may *estimate* wall-length ranges (used only to draw an estimated room, labeled
  "dimensions unverified"); those estimates are never promoted to a confirmed size. Fit labels stay
  "Fit unverified" unless the user optionally confirms a floor-plan reading (from a floor plan they added) or
  states a size they already know. Even then the best label is "Tight / conditional": door swings and walkways
  are not verified.
- **Products** come from `data/catalog/products.json`: 35 snapshots fetched on 2026-10-24 from IKEA US and Target
  product pages (32 with sourced price + size). Every fact carries the evidence snippet it came from; missing facts
  are null and such items never enter a plan. Plan cards show the retailer's own product photo (loaded from the
  retailer, no referrer) with a fallback. Style tags are AI-assisted editorial judgments, not retailer facts.
  Size coverage is limited: bed frames in full/queen, mattresses in queen, one twin daybed; other sizes are
  reported as unavailable.
- **Studio zones and shared beds.** Chosen studio zones (sleep/work/lounge/storage) are checked for coverage by
  bought or kept items; a sofa bed counts for sleep and lounge. A shared bed requires a documented sleeping width
  of at least 53 in. These are shopping-plan checks; placing furniture happens in the arrangement step below, and
  only inside a mapped room.
- **Free-text edits** (`preference-patch-v3`; v3 adds budget approach and store choice, not yet live-tested): "switch the style to X" replaces styles (`set_styles`); "also add X"
  adds (`add_styles`). v1 merged styles on a live "switch" request; v2 passed two live runs (see STATUS).
  Rebuild with `tools/build_catalog.py` (raw pages are kept locally in `data/catalog_raw/`, not committed).
- **Your place** (apartment context, append-only `apartment_context` versions): building name, city/state/ZIP,
  optional private unit label (never searched or fetched), early shopping scope (new/secondhand, pickup/delivery,
  timing) and the **chosen building** (`building`: key, name, address or `null` if unknown, site). Location and
  building are shared by the apartment; each room's geometry is its own. A website address is optional (advanced).
- **Find my building**: name + city/state or ZIP → candidate buildings. Checked directories (`data/property_refs/`)
  match instantly and free only when the name (ignoring words like "the"/"apartments") matches AND every location
  field supplied is consistent (city, ZIP, state; e.g. New Haven + ZIP 10001 matches nothing) with the city or ZIP
  positively matching. Then one bounded, cached web search (the same `research.py` call) lists other candidates:
  one card per property, keyed by domain AND property path (`/…/ava-capitol-hill/floor-plans` and
  `/…/ava-capitol-hill` are one card; `/…/ava-ballard` is another; an operator domain with several properties is
  flagged), listing sites such as apartments.com labeled and kept per page, with what the search result says about
  the location. Street addresses are not read from search results, so they show as unknown. The user must pick;
  nothing is assumed from a same-name building or a shared domain.
- **Choosing a building** (`/buildings/select`) saves it to the place details, runs the bounded SafeFetcher crawl of
  its site and saves the result (`place_discovery`, append-only, shared by the place's rooms) so a refresh or room
  switch shows it without fetching or searching again. If the crawl finds no plans it can rely on, or is refused, it
  **recovers** by fetching up to 3 alternative public URLs returned by the saved search for THIS building name +
  location only (earlier searches for other buildings are never used), scoped to the chosen building: same-site
  pages inside its property path (or naming it), and images the search cited as its floor plans (named for it or in
  its path). Never model prose-only URLs, guessed paths/CDNs, listing sites, sign-in/apply/portal/policy/tour pages,
  or retries that evade a refusal. With the advanced website address and no saved search, ONE bounded web search for
  the entered public name + city/ZIP (never the unit) supplies those alternatives; with no name/location the result
  says so. Policy-blocked (private-network) addresses get no search, no recovery, no checked list and no link. A
  checked building's list is offered without any paid search, and weak live finds (unit-type images on a plan page)
  never hide it. A blocked page stays visible in "What we read".
- **Public page reader fallback** (`reader.py`; on by default, no API key; `FURNISHAI_PUBLIC_READER=off` turns it
  off). When the chosen building's own page gives no usable plans and isn't policy-blocked, and no checked list
  covers it, the SAME public page is read through Jina Reader's default anonymous route
  (`GET https://r.jina.ai/<public page URL>`, deterministic page-to-Markdown; no captions/OCR/model, no cookies,
  proxies, custom agents or CAPTCHA solving). It runs before the web-search alternatives, so a reader success needs no
  AI search and makes no further requests to the refusing site. If that page has no plans, at most two floor-plan
  links actually present in its text are read (never guessed paths). Only a plain public page is sent: URL + DNS
  checked first; never private/metadata hosts, credentials, sign-in/applicant/resident/payment/auth pages,
  unit-specific pages or secret-looking query parameters; the unit label never. Every reader hop must stay on
  r.jina.ai; bytes/time/reads are capped; the reply must be the reader's format for the same site and must name the
  building; challenge/login/error copies are rejected; 429/timeouts stop it. The raw reply is stored immutably
  (`property_reader_page`, its URL is the reader's; the page it read, retrieval time and the reported publish time
  are in its provenance; cache age unknown). Plan names come from the page's own plan headings (the image alt text
  is kept as provenance and never overrides a "Studio" heading); CDN size variants of one file are merged. Images
  are then imported only through the normal SafeFetcher plan-image path.
- **Hostname-only search leads**: web search often returns the official site with only its hostname as a title
  and no citation, which used to leave the building under "Other sources". Now at most 2 leading such leads whose
  OWN domain spells the building's name (e.g. `360statestreet.com` for "360 State Street"; listing sites and other
  domains are never fetched here) get their page read once (direct SafeFetcher, then the public reader). The lead
  becomes a selectable building card only if that page itself names the building (as a phrase; a 3+ word name may
  drop its street type, "360 State" for "360 State Street"; "360 Market Square" never matches) AND the city or ZIP,
  with no other state, inside the lead's property path. The card shows the page's real title plus the hostname. The
  check is saved append-only (`research_results`, kind `lead_check`) and reused, so selecting the card validates
  deterministically; the reader keeps replies for 15 minutes in memory, so the later plan lookup reuses it. URLs
  that appear only in the model's summary prose are never used. Plan/unit sub-pages (`/floorplans/…`,
  `/availableunits`, `/featuredfloorplans/…`, `…/apartment/<unit>`) group into one property card.
- **Secondhand listings behind a robot check**: when an approved AptDeco listing shows a robot check to the direct
  fetch, the SAME public listing page may be read through the public page reader (`FURNISHAI_PUBLIC_READER=off`
  turns this off).
  - **Identity:** the copy must be of that exact listing (same listing id).
  - **What is read:** a fixed parser reads only the listing's own heading block (title, current price, "Sold /
    Expired") and its "Product details" (condition, overall dimensions, availability). Related items are never read.
  - **Unavailable:** sold, expired or past-dated listings are kept as evidence but never offered.
  - **Gates:** refurbished, damaged and floor-model items stay distinct from used. The reader's own challenge pages
    (including Anubis proof-of-work) are rejected and never solved.
  - **Labelling:** options from such a copy say so on their cards and checklist rows, with the date read, "how
    current the copy was is unknown" and a link to the listing.
  - **Not extended to refusals:** an explicit refusal (HTTP 403, e.g. eBay) is not routed around; it is reported,
    and that marketplace isn't spent from the check budget again for 24 hours.
- **Listing-site alternatives** (explicit choice): if every automatic route still finds nothing, up to two pages on
  established property-listing sites from THIS search's evidence whose URL/title name the building AND its city or
  ZIP (and no other state) are offered as "Read plans from …". Nothing is fetched until the user clicks; the page
  (direct read, then the reader) must again name the building and city/ZIP, and its plans are labelled as coming from
  that third-party site, never as official. Each read appends a new discovery version.
- **Plan gallery** ("Your room", shown before uploads): live finds, recovered finds and the checked list, with
  All/Studio/1/2/3+ bed filters (from the printed plan names, e.g. Entrata "Sx1" = studio, "2x2" = 2 bed), source and
  date. "Use this plan" fetches the actual image bytes into **that room only** (immutable original + provenance from
  our saved discovery). It never sets a room size: the exact-unit confirmation is still required.
- **Web research** (`research.py`): one bounded gpt-6-luna Responses call with the built-in `web_search` tool
  (≤ 2 calls, low context, ≤ 1800 output tokens, 55 s timeout) to find a building's official page or furniture
  listings. Only URLs evidenced by the response's search sources or `url_citation` annotations are shown, after a
  public-URL check (no private/loopback IPs, credentials, odd ports or local hostnames). Results are leads: a
  property page goes to the normal plan discovery; a listing must be imported (price/size read from the page)
  before it can be placed. Reserved and recorded in the usage ledger as tokens + $0.01 per search call; identical
  queries reuse a saved result for 10 minutes. No login bypass; Facebook Marketplace/eBay are offered as search
  links the user opens.
- **Compare & swap**: clicking a piece (or "Compare options") lists every catalog/imported product of that
  category with price, size, condition, source link, check date and whether it can be swapped. Choosing one
  replaces only that category in the selected plan after checking settings, verified facts, confirmed-room fit,
  item budget and bed/mattress compatibility; otherwise nothing changes and the reason is shown. The room frame
  (outline, fixed zones) is unchanged; the arrangement is redrawn deterministically.
- **Apartments** group ordinary per-room projects (Bedroom 1…n + Living area, or one Studio). Each room has its own
  photos, evidence, budget, plans and history; bathrooms and the kitchen are listed as fixed spaces and never
  furnished. The apartment type lists rooms only — never sizes or how rooms connect — and budgets are per room.
- **The room is fixed; only furniture moves.** The photo analysis (`room-evidence-v5-geometry-shape`; v5 makes the nested output shape explicit, not yet live-tested) maps the room
  relative to a visible reference wall (walls A–D), places the doors, windows, closets, radiators, columns and
  kitchen it can see, and estimates wall-length ranges from visible cues. Code (`geometry.py`) accepts an outline only
  with ≥ 2 overlapping photos, ≥ 3 walls and ≥ 2 corners seen, and a bounded, cued size range; otherwise it asks for
  specific photos. The estimate is stored once per room version as `inferred_geometry`, separate from confirmed size.
  Rooms without enough evidence get **no outline** — just a shopping shortlist and photo guidance.
- **Arrangements** (`layout.py`, `layout-v2-fixed-room`): one frozen room frame per room version (photo estimate,
  confirmed size, or labeled synthetic demo), chosen before any products and shared by every plan and option. Real
  footprints are placed with bounded deterministic search and rectangle collision checks (footprints, access zones,
  located fixed features, door keep-clear areas, opened sofa beds), re-checked independently. Oversized items are
  listed as not drawn; the room is never resized. Door swings are only as good as the estimated door positions;
  walkways and accessibility are not verified.
- **Originals** are stored once under `storage/projects/<id>/originals/<sha256>` read-only; the AI sees only
  EXIF-stripped, downscaled derivatives. Explicit project deletion removes a project and its originals.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | model, whether live AI is available, key presence/source (never the value), catalog counts |
| GET | `/api/catalog` | product snapshots with stale flags |
| GET/POST | `/api/projects` | list / create a single room (bedroom, studio or living_room) for this browser session |
| GET/POST | `/api/apartments` | list / create an apartment (`preset` studio, 1b1b, 2b1b, 2b2b, 3b2b, or custom with counts) |
| GET/DELETE | `/api/apartments/{id}` | rooms, place context, fixed spaces, per-room status / delete the apartment and its rooms |
| PUT | `/api/apartments/{id}/context` | save place details (appends a version) |
| GET | `/api/apartments/{id}/design` | design state: plan sources, selected plan, map, pieces, warnings, budget, products |
| POST | `/api/apartments/{id}/design/plan` | use one of this place's plan images for the whole design |
| POST | `/api/apartments/{id}/design/read` | read the selected plan into a map (one gpt-6-luna call, or the saved map) |
| GET/POST | `/api/apartments/{id}/design/arrangements`, `/design/arrangement` | three suggested arrangements / apply one |
| POST | `/api/apartments/{id}/design/items` | move, rotate, change room, add, remove, mark owned, change bed size (`expected_version`) |
| GET/POST | `/api/apartments/{id}/design/items/{item}/products`, `/product` | real options for one piece / choose or clear one |
| POST/PUT | `/api/apartments/{id}/design/auto-products`, `/design/prefs` | fill pieces without a product / budget, style, bed size |
| GET/POST | `/api/apartments/{id}/design/checklist`, `/checklist/mark` | final list / mark one piece bought (your record only) |
| GET | `/api/projects/{id}/alternatives?plan_key=&category=` | products of one category with swap eligibility and reasons |
| POST | `/api/projects/{id}/swap` | replace one category in one plan (atomic; 422 with reason if refused) |
| POST | `/api/projects/{id}/research/property` | web search for the building's official pages (discovery only) |
| POST | `/api/projects/{id}/research/furniture` | web search for listings of a category (discovery only; import to verify) |
| POST | `/api/projects/{id}/scale` | (plan-confirmed sizes now require `exact_unit_confirmed: true`) |
| POST | `/api/projects/{id}/layouts` | rebuild arrangements for the current plan from its room version as a new version (no AI; products unchanged) |
| POST | `/api/demo` | create a labeled synthetic demo project |
| GET/DELETE | `/api/projects/{id}` | full project state / explicit deletion (incl. originals) |
| POST | `/api/projects/{id}/uploads` | photos or floor plans (multipart `files`, `kind=photo|floorplan`) |
| GET | `/api/projects/{id}/sources/{sid}/preview` | owner-only preview of the AI derivative |
| POST | `/api/projects/{id}/analyze` | live AI photo analysis (reused if inputs unchanged) |
| POST | `/api/projects/{id}/scale` | optional: confirm floor-plan size or state a known size |
| PUT | `/api/projects/{id}/preferences` | save controls → new preference + plan versions |
| POST | `/api/projects/{id}/edit` | free-text change (AI in live projects; offline rule reader in demos) |
| POST | `/api/projects/{id}/plans` | rebuild plans |
| POST | `/api/projects/{id}/revert` | restore a plan (with its own preferences/room) or preferences as a new version |
| GET | `/api/projects/{id}/history` | all versions and activity events |
| GET | `/api/projects/{id}/store-links?category=&size=` | Amazon/Target/Wayfair/Facebook Marketplace/eBay search links (leads only; no AI, no fetch) |
| GET | `/api/projects/{id}/checklist` | shopping list for the selected plan: items, owned items, manual purchase marks, counts, item totals |
| PUT | `/api/projects/{id}/checklist/plan` | remember the selected plan (`plan_key`, `expected_plan_version`; 409 if stale) |
| POST | `/api/projects/{id}/checklist/mark` | manual "Mark purchased"/undo for a product in the selected current plan (409 stale, 422 not in plan) |
| POST | `/api/projects/{id}/buildings/find` | candidate buildings: checked matches (`include_web: false`, free) and web-search candidates |
| POST | `/api/projects/{id}/buildings/select` | choose a building (`kind` checked/web/url): saves it, crawls + recovers, saves the gallery for the place |
| GET | `/api/projects/{id}/place-discovery` | the saved discovery for this place (no fetch, no search; hidden if the chosen building changed) |
| POST | `/api/projects/{id}/property` | (older URL mode) bounded property-page floor-plan discovery (+ checked list for known blocked sites) |
| POST | `/api/projects/{id}/property/plan-image` | add a plan image to this room as a source; optional `discovery_id` records gallery provenance |
| POST | `/api/projects/{id}/listings` | import a public listing URL (raw page kept as evidence) |
| GET | `/api/projects/{id}/usage` | AI calls, returned token usage, estimated cost |
| GET | `/api/projects/{id}/export` | markdown shopping plan (no photos, no secrets) |

## Design-first apartment flow (whole floor plan)

**Shopping preferences live in Choose furniture.** New or secondhand, local pickup / delivery / either, and timing
(a preference, not a promised date) are set once in Choose furniture with the budget and styles, and saved with the
design. The home page and place details no longer ask for them; settings saved there earlier carry into the design's
preferences. Searches honour pickup vs delivery and use only the place's public city/state/ZIP; pickup without a
location asks for a city or ZIP inline.

**Find furniture (one action).** In Choose furniture, "Save & find furniture" (or "Find furniture for my plan")
saves your settings, then works through the plan's pieces one type and size at a time (two bedrooms share one bed
search; at most 12 types per run, with Continue and Stop). For each type it runs the branches your condition allows:
new (saved checked catalog first; only if fewer than 3 options, one search on the approved stores and up to 2 product
pages checked) and/or used (one search on the approved resale marketplaces and up to 3 listings checked). "New +
secondhand" runs both independently. Results appear as compact previews on each piece (All / New / Secondhand), with
reasons when nothing qualifies (blocked page, no price/size, sold, different item). Nothing is chosen for you; nothing
is searched on page load. Styles rank softly: exact tags first, then the closest related style ("Closest available to
minimal: tagged scandinavian"), then unclassified; price, size, condition and source limits are never relaxed. A used
listing can be chosen for one piece only.

**Approved furniture sources (all paths).** Furniture search results, checks and manual product-link imports use one
boundary (`backend/furnishai/resale.py`): new items only from Amazon (US), Article, IKEA and Target (exact hosts, or
the stores you choose), used items only from individual listings on the approved resale marketplaces below. Results
from other websites are filtered out on the server (counted, no links, no Check); a manual link from another website
is refused before any request; every redirect hop is checked before connecting. A used import, automatic or manual,
must pass the same used-evidence check. Older imports from other websites, or used items whose condition was only
declared, stay stored but aren't offered as fresh options. Property/building research is not affected.

**Secondhand (approved marketplaces only).** Automated secondhand search, display and checks use only established
resale marketplaces: AptDeco, Chairish, eBay (US), Facebook Marketplace item pages and Craigslist regional posts
(`backend/furnishai/resale.py`; you can narrow the list in Choose furniture). An approved marketplace does not verify
individual sellers, condition, stock or delivery. The boundary is enforced in code: exact hosts (plus Craigslist's
regional subdomain), https, default port, no credentials, ASCII host names, and each site's individual-listing path;
results from any other site are hidden (counted, never checkable or choosable), and EVERY redirect hop is checked
before the app connects to it (the safe fetcher's private-network, type and size limits still apply). Each piece row
offers **Find secondhand options**: one bounded web search on those marketplaces near your city or with delivery,
then automatic checks of at most 3 listing pages. A listing joins the options only if the listing's OWN item (the
structured product whose URL is the page, or the only product on it; never a related or recommended item, or a
footer) states used/pre-owned condition, its title names the requested type (not a set or pair), and price, size and
availability come from that same item. Pages stating new, sold listings, wrong types and unreadable pages are
reported with the reason. Checks are cached for 10 minutes per page and piece type ("Check listings again" re-reads).
"Check this option" as used goes through the same gate; a condition you declare yourself when importing a link stays
labelled "your declaration, not verified". Remote listing images are not loaded.

**More furniture types.** TV, TV stand / media console, dining table, dining chair, armchair, side/end table,
ottoman, console table, shoe rack / storage bench and floor lamp are full categories (aliases, imports, search,
draft sizes, placement, choosing and the checklist). They're never added automatically. A TV sits on a TV stand (no
floor footprint); without a free stand it waits in Not placed, and a chosen TV's listed width (never its diagonal) is
checked against its stand. Dining chairs go beside the dining table. The checked collection has no products of these
types yet: use Find more online or import a link.

1. **Place & floor plan.** Find your building (checked directory or web search) and use one of its public plan images,
   or upload your own. One plan is used for the whole place; the plan you used before is suggested. The selected
   image is shown immediately. **Read floor plan** makes one bounded gpt-6-luna call (`plan_map` in the usage ledger)
   (prompt `plan-map-v2-open-zones`) that returns a typed map in normalized coordinates of that image: room polygons with kinds and printed labels,
   printed room sizes copied exactly, walls, doors/windows/openings, and fixed kitchen/bath/closet fixtures.
   Code validates it (finite in-image coordinates, 3-40-point simple polygons, bounded counts, code-assigned ids) and
   stores it as an append-only `plan_maps` row with source id, derivative hash, model, prompt version and call
   record. The cache key includes the source id, so identical bytes under another source are read separately. If no
   furnishable room outline survives (e.g. a 3D render), the map is a **fallback**: the original image is shown and
   furniture is conceptual. No default or rectangular apartment is ever drawn.
2. **Arrange your space.** By default the canvas is the ORIGINAL plan image with movable furniture on top ("Show
   original floor plan" is on; "Show furniture" is optional), in every step and arrangement thumbnail. Unticking it
   shows the AI map as a clean outline, labelled "Approximate AI outline — compare with the original plan": zone
   outlines are thin dashed areas, never walls, and walls are drawn only from the map's wall segments (often none).
   The map still drives placement, zone names and size estimates either way. A new design starts with a
   starter set for every observed space (a bed set in each bedroom/sleeping zone, a sofa and coffee table in the main
   living area), not one old room's shopping list. Draft pieces use typical sizes per type and bed size (dashed outlines, not products), scaled from
   printed room sizes whose proportions agree with the outline, otherwise at an approximate relative size with no
   fit claims. Three deterministic arrangements (against the walls, along the long walls, tucked into corners) use the
   same map. Drag a piece, or select it and use the arrow buttons/keys and Rotate; change its room, add or remove
   pieces, or mark one as already owned. Kitchens, baths, closets, balconies and fixtures are not furnishable;
   identified door areas are kept clear where possible. Problems are warnings; nothing is shrunk or silently moved.
   **Clean plan and reader v4.** After a usable reading the canvas defaults to a clean plan drawn in code from the
   map: no source image, so no watermark, floor texture or marketing furniture; walls read as walls are solid, the
   outline and room edges are thin approximate lines, open splits and unsure rooms are dashed and labelled, kitchen,
   bath and closets are hatched, doors and windows are marked. "Show original floor plan" switches to the source
   image (pieces optional). An unsure reading defaults to the original. An unreadable plan gets no automatic
   placement and no alternatives: pieces wait in Not placed and nothing is drawn on the source. Reader
   `plan-map-v4-crops` sends the full image plus two overlapping zoomed crops of the same image in ONE call (crops made
   in memory; coordinates always reported in the full-image frame, with the crop offsets stated in the prompt).

   **Room use and placement (v3+).** The reader (`plan-map-v3-room-evidence`) reports what it sees in each room (bed,
   pillows, toilet, shower, tub, sink, stove ...), how it decided the room's use, and "3d" for furnished/3D renders.
   Code then marks each room confirmed, uncertain (e.g. an unlabelled low-confidence "bedroom" with no bed seen) or
   conflict (e.g. bath fixtures in a "bedroom"; such a room is kept clear). Bed sets are seeded only in confirmed
   bedrooms (one per bedroom; one for a studio); if the only bedrooms are uncertain, one set waits in **Not placed**.
   Suggested arrangements place a piece only inside a usable room, clear of fixed areas, door areas, other pieces and
   their access space across all rooms, with beds, sofas and storage backed flush against a credible wall (a physical
   wall or a room boundary that isn't an open split between zones) and a bed's foot plus at least one side kept clear.
   A piece with no such spot goes to **Not placed** with the reason; it stays in the design, budget and lists. In
   the Arrange workspace you can fix a room's use (saved as a derived map revision; the AI reading is kept; pieces in a
   room that becomes a bath/kitchen/closet move to Not placed), add a bed set to a room, and re-read an older map with
   the current reader (one AI call; pieces, ids and chosen products are kept). The Arrange page is one workspace:
   arrangement thumbnails right above the canvas (click to apply), and a side panel with the selected piece, the piece
   list (grouped by room, mattress under its bed, product name or Draft, Not placed), adding pieces and room uses.
3. **Choose furniture.** One budget for the whole design with an amount set aside for delivery/tax (actual checkout
   costs may differ), "Keep costs low" (cheapest option that fits) or "Use my budget for better matches" (more style
   matches within each piece's share; price is never called quality and never padded), styles, condition, bed size
   and stores.
   - **"Choose for me"** fills the whole set first:
     - **Planning targets:** every open piece (a mattress on its bed included) gets a transparent planning target,
       its weighted share of the item budget left. A known cheapest price can raise a target up to 1.5× its share,
       no further.
     - **Reservation:** while one piece is chosen, the other open pieces' targets stay reserved, so one expensive
       piece can't use up the set. There are no upgrades while any piece is still missing.
     - **Fit:** only options that physically fit are taken, checked in the arrangement as it fills (so two picks
       can't collide). An option fits where the piece is, or at another spot in the same confirmed room, where the
       piece is moved at the same size. Nothing that extends outside the room, sits on a fixed or door area, or
       overlaps another piece is ever auto-chosen.
     - **Timing:** it waits until "Find furniture" has finished or been stopped.
   - **Review:** a chosen piece that doesn't fit is flagged, with "Move it inside the room" (when a spot exists) and
     "Replace with an option that fits". Pieces you own or marked as bought are never replaced, and nothing is
     deleted.
   - **Option cards** show fit ("Fits where it is" / "Fits at another spot in the same room" / "Doesn't fit in its
     room") separately from budget (within or over this piece's share of what's left for all open pieces).
     Colour/finish variants of one design collapse into one card.

   Each piece lists matching real products (category, bed size, condition, stores) with price,
   size, condition and store link. Pieces with no matching product (e.g. a king bed when no verified king is saved)
   stay in the design as **missing**. Each piece's options can be paged ("See more options"), sorted by price,
   limited to your styles, and browsed in other bed sizes (choosing one switches that bed's size explicitly). **Find
   more online** asks for SPECIFIC product detail pages (furniture-specific instructions `furniture-products-v2`;
   store, search and category pages are shown separately under "More sources" and can't be checked as one item; if a
   search returns only such pages, one clearly labelled refined product search is offered, then reused, never
   repeated). It runs one bounded web search (gpt-6-luna web_search, usage ledger, saved and reused) for that piece:
   its type and bed size, your condition and styles, the remaining whole-design budget, and your public city/ZIP (never
   the unit). Cited results appear as lead cards inside the app; product pages get **Check this option**, which reads
   the page with the safe fetcher, keeps it as evidence and adds the product to the piece's options only if price and
   size are verified and it matches the piece. Store/search pages stay leads; blocked or incomplete pages stay
   explicitly incomplete and can't be chosen. Searching and checking never change the design.
4. **Final checklist.** One list for the whole design (its own card layout: product, quantity × price, link, per-piece
   "Bought" ticks; stacks on phones), with placement notes (pieces not placed, warnings; a complete list is not a fit
   check): products with quantities and line totals, store links, your
   own "bought" marks per piece (a swap never inherits a mark), pieces you already own, and missing pieces with
   "Review missing items". Status says "Incomplete" until every piece has a product. Nothing is bought or sent.

Printed sizes set the drawing scale only when they agree: one printed room whose outline matches it, or the unique
largest group of printed rooms whose implied scales agree within 25%. Conflicting sizes give a relative drawing scale
with a visible note. Degenerate outlines (repeated vertices, touching or retraced edges) are rejected.

Limits: the map is an AI reading of a picture, not a survey. Door swings, walkways and exact wall positions are
approximate; a plan's printed sizes give an approximate scale only. Tests use hand-written synthetic maps, which
check the code paths but not the model's vision accuracy.

## Floor plan first (no tape measure)

- Add a floor plan (from your building in "Your place", or your own image), then "Analyze floor plan": the printed room
  sizes it reads appear as cards in "Your room" and in "Your room in 2D". Pick the one that is this room
  (`POST /api/projects/{id}/plan-estimate` with the current room version, the reading index and its plan source).
  The room is drawn as **"Estimated layout from selected plan; your unit may differ"**: a rectangle at the lower
  end of ±6 in, with the plan source shown. Scale stays unknown, so fit is never upgraded to a checked result.
- A single reading that clearly matches the room type is marked "Looks like this room", but nothing is chosen for
  you, and two bedrooms are never picked between. A whole-apartment plan is a reference: pick only this room's
  printed size. Plans with no printed sizes (marketing/3D plans) show "Plan reference: size unavailable", with
  the source and a photo action, and no furniture is placed. Irregular rooms are refused as rectangles.
- One plan is read at a time (`POST /analyze` takes an optional `floorplan_source_id`, which must be an image plan of
  this room). It is used automatically when the room has one plan and required when it has several; plans are
  never combined. Re-reading the same plan keeps a chosen estimate only if the same reading is still there.
  Switching plans drops it, so an old plan's size is never drawn under a new plan.
- A whole-apartment plan's overall shape doesn't block a bedroom estimate; the rectangle is labeled as an
  assumption. An irregular shape observed in this room's photos still blocks it.
- Optional advanced: "This is exactly my unit: use as known size", or state a size you know. Only these make a
  KNOWN size, which runs item size checks; doors and walking paths are never checked.
- Statuses shown: "Estimated from floor plan", "Estimated from photos", "Fit not assessed" (room has no size), "Product size unavailable", "Placement needs
  review", "Item sizes fit the room: check doors & paths".

## Amazon

- Amazon product pages (`amazon.com/dp/<ASIN>`) can be imported from "Compare options" (paste a product link). A
  deterministic parser reads only the SELECTED variant:
  - the page's selected ASIN must equal the link's ASIN;
  - the price is the featured offer's price block for that ASIN (one USD value);
  - the size is the labelled "D x W x H" product-dimensions row, cross-checked against Item Width/Depth;
  - package dimensions are never used;
  - the seller is noted.

  Anything ambiguous or contradictory stays unknown, and the item isn't placed.
- The parser reads labelled "D x W x H" or "L x W x H" rows (for L x W x H, L is the depth). It uses the page main image for the selected variant, and prices only a NEW featured offer. One real Amazon product is in the saved collection: the Zinus SmartBase black queen bed frame B006MIUM20 ($154.55, In Stock, 60 x 80 in, new featured offer), from root's honest SafeFetcher fetch on 2026-10-26 (raw bytes kept, hash 28deef20...). Other Amazon items are imports or leads, not catalog coverage. The white queen B095P21J2L had no featured offer (no price), and B06XJ64MLC is a bed skirt (not added). The store filter can include "Amazon".

## Saved product collection and budget use

- **Stores with checked products:** IKEA US (34 verified + 2 incomplete), Amazon (1 verified, see above), Article (21 verified, 3 of them listed out of
  stock when checked, so never placed), Target (1 incomplete listing). Every fact comes from the store's own page,
  saved raw in `data/catalog_raw/` with its hash. Article sizes come from its "General Dimensions" row, never "Box
  Dimensions", and its price is used only when the spec SKU equals the page's JSON-LD SKU. Rebuild offline with
  `.venv/bin/python -I tools/build_catalog.py --offline`.
- **Stores we could not add (2026-10-26, honest fetcher, no bypass):** Nathan James, Zinus and Floyd answered HTTP 429;
  West Elm and CB2 HTTP 403. Castlery's pages load, but product dimensions appear only in images, so sizes can't be
  verified from text. The Article Sven 88" Biscuit Cream sofa (id 27565) is marked discontinued on Article's own page.
- **Three plans** (stable keys value / balanced / priority; plain titles):
  - **Save money**: the cheapest verified set.
  - **Match my style**: scores options by preference matches (editorial style tags + weighted priorities) minus
    cost. The budget approach in Preferences sets how much one extra match may cost: about 3% ("save"), 12%
    ("balanced") or up to all ("use more for my preferences") of the item allowance. A default "price" priority
    doesn't override it.
  - **Closer to my budget** (with a budget): aims for 85–100% of the item allowance (budget minus the
    delivery/tax reserve, e.g. $3,500 → $3,150), using only the furniture types you chose. Within that band it
    prefers better matches. If the catalog can't reach the band, it says how far it got and why; it never adds
    furniture to spend more. Its search is bounded (price levels per category), not a global optimum. Without a
    budget the third plan is "Top priority first".
  - Equal matches go to the cheaper option, a higher price is never presented as better quality, and the item
    allowance is a hard cap. Plans show the allowance, the unused amount and what changes vs Save money. Older
    saved plan versions keep their stored titles and are displayed with today's names.
- **Stores filter** (Preferences → Stores): limit plans to some of the stores above. It is a hard restriction for
  imported listings too: an import's store is the retailer its page adapter recorded ("IKEA US", "Article";
  other sites keep their web address, never guessed), so an import from an unlisted store stays saved but isn't
  used until the filter allows it. Amazon, Target and Wayfair searches are offered from "Compare options" as plain
  links (leads); paste a product link back to import and check it before it can be placed.

## Example property sources

- Worked in root testing: Yale Whitehall (https://housing.yale.edu/graduate-housing/explore-housing/unfurnished-housing/whitehall)
  and Howe Place S1 (https://www.howeplace.com/apartments/studio/s1/). Arbitrary websites are not guaranteed.
- The Audubon (https://www.theaudubonapts.com/floorplans) refuses automated requests (HTTP 403). For that exact
  host and its floor-plan paths only, the app offers a **checked reference list** (`data/property_refs/theaudubonapts.json`):
  22 public plan image URLs and names observed on the official page in a normal browser on 2026-10-26 UTC (the
  evening of October 25, US Eastern), built by
  `tools/import_property_refs.py` from a browser-observed input file that is kept locally, not in this repository. It holds no image bytes, prices,
  availability or dimensions, is not a live fetch, and is not proof of anyone's exact unit. Live discovery is always
  tried first. Plan images are not redistributed in this repository.
- The Archive (848 Chapel Street, New Haven, CT 06510): https://thearchiveapts.com/availability is readable, but its
  embedded Entrata snippet and https://entrata.thearchiveapts.com/new-haven/the-archive/conventional/ refuse server
  requests (HTTP 403). `data/property_refs/thearchiveapts.json` lists 19 public plan images (Entrata media CDN) observed
  in a normal browser on 2026-10-26 UTC (from a locally kept browser-observed input file). It matches only
  thearchiveapts.com / www.thearchiveapts.com (home, /availability) and entrata.thearchiveapts.com
  `/new-haven/the-archive/` (also used by the embedded snippet, with query parameters) plus its observed
  `/conventional/` and `/floorplans/` subpaths, nothing else. Same limits as above: 19 published plan types, not every
  unit variant; not live HTML; the images' own marketing/availability text is not verified current availability.
- Any website: if lookup fails, **upload your own floor-plan image or screenshot** (JPEG/PNG/WebP) and analyze it
  directly; PDFs are stored but not read, so screenshot them.
