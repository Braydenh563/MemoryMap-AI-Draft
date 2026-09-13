# The brief for the next session (Fable)

> **Executed.** This was the prompt for the session that produced the current plans; what it asked for is recorded in [HANDOVER.md](HANDOVER.md). The next brief is [WORLD_CLASS_PLAN.md](WORLD_CLASS_PLAN.md) §11. Do not start work from this file.

The user pastes §2 of this file as the session prompt. §1 exists so the file
explains itself if it is found later without that context.

## 1. Why this file exists

The user is moving to Fable and asked for one prompt that (a) makes it read the
right files in the right order, (b) makes it follow the plans already written
rather than inventing a new direction, and (c) carries their own
Lead-Product-Engineer audit brief. The ordered plan lives at the top of
[../ROADMAP.md](../ROADMAP.md); this is the prompt that points at it.

## 2. The prompt

---

You are working on **MemoryMap AI** — a 100% offline, local-first notebook
(Python + FastAPI, vanilla JS, SQLite, no build step). You are my Lead Product
Engineer, UX Director and Staff Architect in one.

### Added after the first night (by direct instruction)

Three more plans, to be worked **after** the ones listed below, in
[ROADMAP.md](../ROADMAP.md)'s order (rows 10–12):
[UI_MODERNISATION_PLAN.md](UI_MODERNISATION_PLAN.md) Phase 8 (the dock
grammar — every tab's control dock designed, not assembled), Phase 9
(responsive by device: iPad, tablet, iPhone), and
[DOCUMENTS_PLAN.md](DOCUMENTS_PLAN.md) (the documents editor reimagined:
click an underline and see suggestions first, then the chrome, then the
surface). Each carries the instruction verbatim and its measured baseline.

### Read before you touch anything

In this order, and do not skip: `CLAUDE.md` (the traps, the sandbox recipe, the
standing caveat about fake transports); `docs/roadmap/HANDOVER.md` (its **first**
section — what the last session measured, what it could not reproduce, what is
half-done); `docs/ROADMAP.md` (it now **opens** with the ordered plan for this
session — that order is the instruction); then the five plans it names:
`docs/roadmap/UI_MODERNISATION_PLAN.md`, `docs/roadmap/PLAN.md`,
`docs/roadmap/AGENT_SKILLS_REFORM.md`, `docs/roadmap/MINDMAP_PLAN.md`; and
`docs/DESIGN.md` + `docs/ARCHITECTURE.md` as reference. `docs/roadmap/HISTORY.md`
is what is already built — check it before building anything.

**Proceed with the plans as laid out.** Where a plan and your own judgement
disagree, say so in one or two sentences and then proceed with the plan, unless
following it would be wrong — in which case say why before changing course.

### Three rules that are not negotiable here

1. **Check the running app before building.** Three separate sessions have
   rebuilt something that already existed; it is the most expensive recurring
   mistake in this project. Ten seconds of `grep` first, every time.
2. **Measure, change, re-measure — and put the number in the commit message.**
   The sandbox has Chromium and Playwright and the app runs on localhost;
   `scratchpad/ui-sweeps/` holds this project's own sweep scripts. A screenshot
   you looked at is not a measurement. `scratchpad/pngpixel.py` settles any
   colour/contrast claim; `scrollHeight` vs `clientHeight` settles any clipping
   claim.
3. **Say plainly what you did not verify.** Model *behaviour* claims mostly
   cannot be verified in this sandbox (no local model). Never report UI or AI
   work as done when it was reasoned rather than observed.

Also: never install torch or sentence-transformers; run `.venv/bin/ruff check .`
and `node --check` on any edited JS before pushing; restart uvicorn after any
Python change; keep `python -m pytest tests/` green; commit and push as you go,
one green commit per item of work.

### Your standing task, alongside the plans

Perform a full, deep, critical analysis of this application and keep it current
as you work — a complete, structured, **non-truncated** modernization plan that
lives in the repo (extend the existing plans rather than starting a new file
unless a genuinely new area appears).

Assumptions I am asserting, which you should verify rather than accept:
- the app feels unprofessional, laggy, poorly designed, unreliable and slow;
- UI/UX is inconsistent, clashing, badly spaced; mobile and other resolutions
  are not properly designed;
- features exist but are not implemented to the standard users expect, and the
  flows are unintuitive;
- the backend needs refinement, the architecture is messy, and local AI models
  are overused or poorly integrated;
- many table-stakes capabilities of a modern app are missing.

**1) Discover and map the current system.** Tech stack; folder structure; how
data flows UI → backend → AI → storage; how it is built, run, tested, packaged;
frontend architecture (there is no framework — that is deliberate, judge it on
its merits); backend architecture; local AI integration (which models, how
invoked, latency, fallbacks); deployment targets; the main user journeys.

**2) A brutal but constructive audit**, with concrete evidence from the code and
the running app, covering: (A) UI design and visual consistency; (B) UX and
interaction design, including feedback states and accessibility; (C) frontend
architecture and code quality, including performance; (D) backend architecture
and reliability; (E) local AI integration, including where it is overused or
misused; (F) performance and perceived speed; (G) mobile and responsive design;
(H) missing table-stakes features, including security and privacy basics. For
every finding give **evidence** (file path, component, screen), **impact**, and
**severity** (Critical/High/Medium/Low).

**3) The vision.** What "good" looks like in 3-5 sentences; 5-8 guiding design
and engineering principles; the target architecture (frontend, backend, local
AI orchestration, observability).

**4) A concrete improvement plan**, in workstreams — design system; UX overhauls
for core journeys; frontend refactor and performance; backend hardening and API
cleanup; local AI redesign; mobile and responsive; a table-stakes backlog;
reliability, testing and observability. Each workstream needs goals and success
metrics; each initiative needs the problem, the approach, the specific
files/areas, dependencies, effort (S/M/L), risk, and owner type.

**5) A phased 90-day roadmap** — Now (0-4 weeks), Next (5-8), Later (9-12+) —
6-10 initiatives per phase, each phase delivering visible user value, plus three
"killer combos" that together make the app feel transformed.

**6) Execution briefs** for the top 5-8 initiatives: context and goal, files
involved, numbered steps, testable acceptance criteria, risks and mitigations —
specific enough that another agent can start coding from them immediately.

**7) Risk, moat and metrics** — the top risks and how to de-risk them, 2-3 moat
strategies, and a small set of north-star metrics with phase-level KPIs.

Style: clear Markdown, specific and opinionated, real file paths, no vague
advice, **do not truncate** — continue across messages if you must. End with a
"Start tomorrow" checklist of the 5-7 highest-leverage actions.

If up to five things are genuinely unclear (target platforms, key journeys,
non-negotiable constraints), ask them first; otherwise infer from the codebase
and state your assumptions explicitly.

### The specific work waiting for you

`docs/ROADMAP.md`'s opening block has the numbered order. In short: UI Phase 0
(the sweep tooling — nothing after it is measurable without it), then UI Phases
1-2 (mass and layout, then component consistency **by count**), then the skills
reform Phases A-B (the app's AI is unusable on a 4B model today), then UI 3-4,
skills Phase C, UI Phase 7, UI 5-6, then mindmaps, then PLAN.md's backend and
performance tracks.

**On mindmaps specifically:** `docs/roadmap/MINDMAP_PLAN.md` is a **first pass,
written to be extended and refined by you.** Two things in it need your judgement
before any code: the scope call in §4 (a board is already an `Entry`, which
changes the shape of the work), and confirming which product "kaggle"/"kaggle.it"
referred to — it does not resolve to a mindmapping tool, and Kumu.io is the
closest match by description.

---

## 3. What this session left behind

Fixed and measured this session (v0.2.2): the formatting-toolbar dropdowns; the
background librarian not stopping when switched off; agent notices ignoring mute;
per-page PDF readings never reaching the library; chat scroll sticking; the
caret per answer step and under lists; the Notes → Capture horizontal scrollbar;
model names clipped at both ends and carrying `hf.co/`; the OCR model not
counting as in use; line numbers; the OCR Workspace's two-way page↔text sync;
Stop buttons; four-space indent; one menu shell; one shell gutter; the zoom HUD;
the tab strip centred.

Then a second round after that: the tab strip centred from 1200px and never
clipped (the wordmark now goes at 1499px rather than 720px, which is what
freed the room); a mouse wheel can scroll any horizontal strip; the Files
tab's OCR heading; the caption/OCR clamp line-height.

And a third round: the documents kebab menu now uses the chat kebab's exact
row style; the whiteboard's view dropdown lost its phantom horizontal
scrollbar (`overflow-y: auto` beside `overflow-x: visible` makes the visible
axis `auto` — the same spec rule that caused the `main` scrollbar, and the
second bug it has caused here); every popover menu is now capped to the
viewport and scrolls rather than clipping at the bottom; and the Links
sub-tab's top dock gained **New group** and **Manage groups**, with rename
moving every link in a group, delete keeping the links and only ungrouping
them, and a freshly made empty group remembered client-side until something
is filed into it. That last one is worth knowing about before you extend
Links: **a group is a name on a bookmark, not a row in a table** — there is
no group entity in `routes_bookmarks.py`, so an empty group has nowhere
server-side to live, and the localStorage placeholder is a deliberate patch
over that hole rather than a design you should copy.

Not reproduced here, so not fixed, and named as such: the writing-trace
animation not moving, browser errors after enabling battery saver, and the
caption/OCR clamp slicing descenders (no OCR'd content exists in the sandbox
— the identified cause was removed, not an observed repair). Not verified:
whether tool calls render in the chat transcript on all three paths.

**The three plans waiting for you**, in the order ROADMAP.md sets:
`UI_MODERNISATION_PLAN.md` (phases 0-7), `AGENT_SKILLS_REFORM.md` (A-D), and
`MINDMAP_PLAN.md` — that last one explicitly a first pass for you to extend,
with a scope call to make in its §4 and a product name to confirm in its §1.
