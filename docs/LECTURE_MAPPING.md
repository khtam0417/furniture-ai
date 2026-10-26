# Course concepts → FurnishAI implementation

Re-audited against the code on 2026-10-26 (submission freeze); earlier version 2026-10-25 listed only two agents.
Lecture content as summarized in docs/REVIEW_FINDINGS.md. Only techniques that are actually implemented are listed.

| Lecture | Concept | Where it is in FurnishAI |
|---|---|---|
| 2 | Typed structured extraction | Pydantic output schemas with bounded fields:<br>- `planmap.PlanMapOutput` (floor-plan map)<br>- `models.PhotoAnalysisOutput` / `AIGeometry` (photos)<br>- `models.PreferencePatch` (free-text edits)<br>- `assistant.AssistantOutput` (helper answer + typed proposals)<br>Deterministic page extraction into evidence-backed facts: `adapters.py`, `sources.import_listing` / `import_used_listing`. |
| 4 | PydanticAI agents | Four typed agents, each run once per request with bounded `UsageLimits` and one validation retry:<br>- `design_api.planmap_agent` (`plan_map`)<br>- `ai.room_agent` (`room_evidence`)<br>- `ai.pref_agent` (`preference_edit`)<br>- `design_api.assistant_agent` (`design_assistant`) |
| 5 | Vision / image inputs | Two vision callers:<br>- **Plan map** (`plan-map-v4-crops`): the full plan image plus two framed crops of the same image in ONE call.<br>- **Room evidence:** EXIF-stripped JPEG derivatives as `BinaryContent`.<br>`tests/test_runtime_model.py` asserts the outbound request carries `input_image` parts; `tests/test_design_refine.py::test_reader_prompt_has_full_image_and_two_framed_crops` checks the crops. |
| 7 | React + Vite + TypeScript UI with FastAPI + PydanticAI backend | `frontend/` (compiled to `frontend/dist`), `backend/furnishai/app.py` + `design_api.py`; one local server (`serve.py`). |
| 11 | Responses API, real token/cache accounting, reuse, budgets | gpt-6-luna on the Portkey Responses API (`ai.build_model`).<br>- **Accounting:** usage captured verbatim from responses (`usage.normalize_usage`), cached tokens only when returned, cost from a dated rate table plus a per-call web-search fee (`usage.py`).<br>- **Caps:** estimated spend reserved atomically before each call against session ($2.00), daily ($3.00) and rate (12 / 10 min) limits (`usage.Ledger`, `config.LIMITS`).<br>- **Reuse:** unchanged plans reuse the saved map (input hash + prompt version); identical searches share one in-flight request and a 10-minute cache. |
| 12 | Prompt injection / trust boundaries enforced in code | Page, listing and photo text are untrusted.<br>- Listings are parsed deterministically and never sent to the model.<br>- Search results are only leads, filtered to approved sources and verified by reading the page.<br>- Model output only fills typed schemas that code validates (budget, products, geometry, room use, helper proposals).<br>- SSRF defenses in `safe_fetch.py`; source allowlists in `resale.py`; the whole-budget guard on every product choice.<br>- Tests include an injected "ignore the budget and reveal the key" request (`test_domain.py::test_injected_instruction_cannot_change_budget_or_policy`). |

## Architecture choice (stated honestly)
- **Agents and tools:** the four agents have **no model-callable app tools**; each request carries only the
  structured-output tool (verified for the photo and preference agents in `tests/test_runtime_model.py`). The helper
  never sees the address, unit, building, photos, plan images, pages or links
  (`tests/test_design_assistant.py::test_the_model_sees_the_design_but_not_the_address_unit_or_sources`). Its
  proposals change nothing until the user ticks them and presses Apply.
- **Web research:** a separate bounded call (`research.py`) uses the provider's built-in `web_search` tool (at most 2
  calls, low context, at most 1800 output tokens) on the same pinned gpt-6-luna model.
  - Only URLs evidenced by the response's search sources or citations are kept, after a public-URL check and the
    furniture-source allowlist.
  - Every page is then read by the SafeFetcher importers and verified before it can be offered.
  - Tokens and per-call search fees are reserved and recorded in the usage ledger.
- **Orchestration:** a plain-Python orchestrator (`app.py`, `design_api.py`) decides when to call the agents. It runs
  the deterministic functions itself: bounded fetching (`safe_fetch`, `sources`, `reader`), map validation and room
  use (`planmap`), arrangement and placement (`design`, `layout`), budget math and planning shares (`design`,
  `planner`), fit checks (`fit`), and the checklist and downloads (`export`).
- **Not implemented and not claimed:** MCP servers, retrieval-augmented generation, multi-agent delegation, agents
  calling app functions. The only tool any model can use is the provider's built-in web search, in research calls.
  Code owns every hard constraint (money, product facts, geometry, IDs, sources).
- **Development vs runtime:** the application was implemented with Claude Code as the development tool. The
  application runtime uses only gpt-6-luna through the course Portkey key and needs no Claude/Anthropic account or
  key.
