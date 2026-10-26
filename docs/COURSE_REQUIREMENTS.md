# Verified final-project requirements

Reviewed October 24, 2026. Authority: https://zlisto.github.io/mgt_409_fa26/project_requirements.html (downloaded successfully with system HTTPS client; web search's fetch failed). Course homepage, grading, homeworks, instructions and relevant lecture exercises were also reviewed. Preserve course pages as reference; check for last-minute changes before submission.

Deadline: Monday October 26, 2026, 6:00 PM, Canvas. Solo project. Final project is 50% of course grade.

## Canvas submission (AUTHORITATIVE — supersedes the public page's "URL + files" wording)
Source: professor's Canvas announcement https://yale.instructure.com/courses/122156/announcements/872636, date
verified from its Canvas email notification: October 25, 2026, 6:30 PM Eastern (first supplied by the user as a
screenshot; verified by the root session). The Canvas assignment
https://yale.instructure.com/courses/122156/assignments/609320 (checked by root in Safari) lists the due date
Monday, October 26, 2026, 6:00 PM, 100 points, and links to the public project_requirements page; no additional
rubric was visible there.
Canvas accepts files, not a URL field. Submit ONLY these files on Canvas, nothing else:
1. report.html
2. slides.html
3. Optional demo video (2–3 minute narrated screen recording).

The GitHub repository URL must be written INSIDE BOTH report.html AND slides.html. If the repository is private,
state "private repository" in BOTH files and grant GitHub user zlisto access (to be done later by the user; nothing
is created, published or submitted by the build).

## Still-required content (from the public requirements page)
1. GitHub repository: all runnable source, clear README, .env.example without credentials. Public, or private with GitHub user zlisto added.
2. report.html: ONE HTML file, 10–15 normal printed letter pages including screenshots, ordered sections below, images embedded.
3. slides.html: ONE HTML file, at most 10 slides using reveal.js, images/diagram embedded. Course example permits CDN reveal.js; consider embedding the library too for a genuinely offline presentation.
4. Optional 2–3 minute narrated screen recording.

## Submission checklist (none of these is done yet)
- [ ] report.html: 10–15 printed letter pages, 8 sections in exact order, images embedded, repository URL (and "private" if private) stated.
- [ ] slides.html: reveal.js, ≤ 10 slides, images/diagram embedded, repository URL (and "private" if private) stated.
- [ ] Optional demo video.
- [ ] Repository: README, .env.example, sample data, compiled frontend; secrets scan clean; zlisto access if private.
- [ ] Fresh-clone rehearsal with the parent .env under 10 minutes.
- [ ] Canvas: upload ONLY report.html, slides.html and the optional video.

Report sections in exact order:
1. Title + links (project, student, repo, online app if present, one-sentence purpose).
2. Motivation (real person/problem and current cost/friction).
3. What is new (named existing alternatives and honest differences).
4. The agents (roles, tools, organization/diagram, model rationale; one REAL run with screenshots).
5. Tokenomics (measured input/cached/output tokens; per run, per user/month, 100 and 10,000 users; cost reductions and evidence of quality tradeoffs).
6. Safety (relevant attacks, malfunction and overspending; show a working defense).
7. Impact (sourced numbers, real-user test or before/after evidence).
8. Limits + next steps.

## Runtime and keys
- Course key: PORTKEY_API_KEY, gpt-6-luna only. A personal OpenAI key is named OPENAI_API_KEY if used; do not silently switch providers.
- Staff supplies .env at the parent of cloned repo. Look in repo root FIRST, then immediately above it. Test this in a disposable fresh clone; do not move or edit the user's coursework .env.
- Additional keys require hosting plus consultation with professor. Avoid additional runtime services/credentials for this MVP.
- Either keep a hosted app working until grades are posted OR provide local fresh-clone setup running in under 10 minutes. Zero of the five runnability points if setup exceeds 10 minutes.
- Include a small test dataset if the production dataset is large. Sample data must be distributable and clearly distinguished from actual-user evidence.
- Video backup can support works/look-and-feel points, but cannot recover the five staff-runnability points.

## Exact grading weights
| Item | Points | Evidence needed |
|---|---:|---|
| Novelty and real-world value | 21 | Useful differentiation, not a renamed class exercise |
| App works | 15 | Real agents/tools/data and useful end-to-end result |
| Staff can run it | 5 | Online or fresh clone, parent .env, under 10 minutes |
| App look and feel | 10 | Clear, usable, polished interaction |
| Motivation + novelty report | 8 | Named competing products |
| Agent design | 10 | Real step-by-step run and screenshots |
| Tokenomics | 8 | Actual API usage logs; estimates alone get at most half |
| Safety | 8 | Defense actually stops attack/malfunction; prose alone at most half |
| Impact + metrics | 5 | Real user tried it; guesses alone at most half |
| Report design | 2 | Readable, sharp screenshots and diagrams |
| Slides content | 6 | Whole story, diagram, screenshots, numbers |
| Slides design | 2 | Readable, consistent, visual |

No requirement says every lecture technique or many agents must be included. Use structured outputs, tools, vision, web UI, persistence, cost accounting and tested safety where they serve the product. Tier 3 depends on demonstrated difference for people, not a claimed feature count.
