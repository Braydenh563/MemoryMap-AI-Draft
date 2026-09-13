# The modernisation audit — the whole application, measured

> Companions, and this file **cross-links rather than repeats them**:
> [../ROADMAP.md](../ROADMAP.md) (the live list) ·
> [PLAN.md](PLAN.md) (P/W/D/B/A/S row ids) ·
> [AUDIT.md](AUDIT.md) (A/B/C/D/E/F/G row ids) ·
> [UI_MODERNISATION_PLAN.md](UI_MODERNISATION_PLAN.md) (Phases 0–7) ·
> [AGENT_SKILLS_REFORM.md](AGENT_SKILLS_REFORM.md) (Phases A–D) ·
> [MINDMAP_PLAN.md](MINDMAP_PLAN.md) · [REDESIGN.md](REDESIGN.md) (§R1–§R9) ·
> [BACKLOG.md](BACKLOG.md) · [ANALYSIS.md](ANALYSIS.md) (§114) ·
> [HISTORY.md](HISTORY.md) (**what is already built**) ·
> [HANDOVER.md](HANDOVER.md) · [../DESIGN.md](../DESIGN.md) ·
> [../ARCHITECTURE.md](../ARCHITECTURE.md)

This is the standing task in [FABLE_BRIEF.md](FABLE_BRIEF.md) §2 done in full:
discover and map, audit, vision, plan, 90-day roadmap, execution briefs, risk
and metrics. It is a **new file** because the brief asks for one complete,
structured, non-truncated plan in the repo and no existing file has that shape —
PLAN.md is a ship-ordered table, AUDIT.md is a findings list, REDESIGN.md is a
diagnosis. Where one of them already owns an initiative, this file **names its
row id and stops** rather than restating it.

## How to read the evidence in here

Three kinds of claim appear below and they are labelled, every time:

- **Measured.** A number produced this session by a script in
  [`scratchpad/audit/`](../../scratchpad/audit/) against a real Chromium and a
  real uvicorn (`--port 8791`, `MEMORYMAP_DATA_DIR=/tmp/audit-data`, fresh
  profile, 40 seeded notes). The script that produced each number is named.
- **Read.** A `file:line` in this repo.
- **Reasoned.** Inference from the code, stated as such.

**The one thing this session could not do: run a local model.** There is no
Ollama, no LM Studio, no llama.cpp in this sandbox. Every claim in §2E and
every AI-behaviour claim anywhere else is **reasoned from the code and marked
as such** — none of it was observed. CLAUDE.md's standing caveat still stands
for `chat_tools`/`chat_tools_stream` fragment parsing in particular.

### The scripts, and what each produced

| Script | Produces | Output |
| --- | --- | --- |
| `scratchpad/audit/lib.js` | boot + unlock + tab navigation, shared | — |
| `scratchpad/audit/measure.js` | boot timing, asset weight, 60s idle requests, per-tab errors / overflow / clipping / button signatures / tap targets at 1440, 1024, 390 | `results.json` |
| `scratchpad/audit/measure2.js` | the same with **40 seeded notes**, plus geometry, glass/shadow layer counts, tap-target buckets at 24/28/40px, tab-switch time | `results2.json` |
| `scratchpad/audit/probe.js` | the specific controls measure2 flagged, one by one (`elementFromPoint`, opacity, clip-path), plus the Notes chrome stack row by row | `probe.json`, screenshots |
| `scratchpad/audit/overlap.js` | whether the note card's action buttons cover the note's own text | `overlap.json` |

Run them with
`BASE=http://127.0.0.1:8791 SCRATCH=<dir> PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/audit/<x>.js`.
JSON output goes to `<dir>`, not into the repo, so a re-run is a diff of numbers
and not a diff of committed files.

---

# 1. Discover and map

## 1.1 Stack

| Layer | What | Size (measured, `wc -l`) |
| --- | --- | --- |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, uvicorn, single process (`deps.refuse_multiple_workers`) | 43,079 lines / 108 files |
| Storage | SQLite one file (`data/memorymap.db`), WAL, plus `preferences.json`, `uploads/`, `backups/` | — |
| Frontend | Vanilla HTML/CSS/JS. **No framework, no bundler, no build step**, no CDN | 47,220 lines JS + 7,178 lines `index.html` + 21,750 lines CSS |
| Vendored | d3 v7 (280 KB), p5 (1,035 KB), Phosphor icon font — all local | — |
| Local AI | Ollama HTTP, or any OpenAI-`/v1` server (LM Studio, llama.cpp, Jan, vLLM), selected at runtime | `ai/` 32 modules + `ai/tools/` 6 |
| Optional extras | Tesseract OCR, SearXNG, embeddings — each fully absent rather than broken when missing (`core/extras.py`) | — |
| Packaging | PyInstaller specs for Linux + Windows, Inno Setup installer, `start.sh` / `start.bat`, pywebview desktop shell | `packaging/`, `__main__.py` (1,305 lines) |

**Deliberately excluded:** torch and `sentence-transformers` (CLAUDE.md). The
suite passes without them; semantic search degrades to keywords.

## 1.2 Folders

```
src/memorymap/
  api/        27 routers, 267 route decorators, app.py (385 lines) wires them
  core/       database.py (1,242) · security.py · config · deps · backup
              taskhistory.py (in-memory, 40-deep) — and NO jobs.py (§D2)
  entry/      manager.py (1,659) — the note lifecycle + audit log
  ai/         provider.py + ollama_client.py + openai_client.py (the transport)
              agent.py (1,519) · skills.py · skill_runner.py · librarian.py
              janitor.py · autonomous.py · captioning.py · vision_ocr.py
              embeddings.py · entities.py · tensions.py · memory.py
              tools/__init__.py (3,565) — the agent's tool registry
  search/     search_manager.py · websearch.py · searxng_*
frontend/     index.html (7,178) · app.js (26,113) · 10 more modules · css/00..07
tests/        219 files, 2,838 test functions
tests-e2e/    1 spec, 3 Playwright tests
docs/roadmap/ 12 planning documents (this one included)
```

**The shape to notice:** `frontend/app.js` at 26,113 lines is **55% of all the
frontend JavaScript**, and larger than the twenty largest Python modules in this
project put together (23,575 lines). Everything in §2C follows from that.

## 1.3 Data flow, UI → backend → AI → storage

Two journeys, traced through the code:

**Capture a note.** `frontend/app.js` `api()` (`app.js:292`) attaches
`X-Auth-Token` and `X-Workspace-ID` → `POST /entries`
(`routes_entries.py:485`) → `entry/manager.create_entry` writes the row and an
`AuditLog` line → **the model call is not in the request**: filing is handed to
a background thread (`routes_entries.py:388`) which calls `ai/janitor.categorise`
→ janitor tries the cheap path first (embedding vs. category centroid), and only
a borderline result costs one chat round trip → the note's `filing_state` moves
`pending → filed`, and the UI learns via its poll. **Measured previously and
recorded in REDESIGN §R1.3: 971 ms → 32 ms** on the save round trip. Confirmed
still true by reading: no `janitor.` call remains on the `POST /entries` path.

**Ask the notebook.** `streamChat` → `POST /chat/stream`
(`routes_chat.py`, `chat_stream`, ruff complexity **26**) → `search/` retrieves
candidates (FTS5 + bm25 for notes, `ILIKE` for everything else) → `ai/librarian`
builds a grounded message list → `provider.Provider.chat_stream` yields NDJSON
events `status → meta → answer deltas → stats → done` → the frontend renders
them incrementally. In agent mode `ai/agent.run_agent` (ruff complexity **45**,
the highest in the codebase) loops tool call → result → repeat with
`MAX_ROUNDS = 6`, and `unsupported_claims` checks the answer's claims against
the tools that actually ran (`tests/test_claimed_work.py`).

**Storage** is one SQLite file. `core/database.py:1251-1265` sets
`foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000`,
`synchronous=NORMAL` per connection, and `_ensure_indexes` creates four
composite indexes over `entries` shaped to the list queries' own `ORDER BY`.
**PLAN P5 is therefore largely done** — do not re-do it; what is left of P5 is
`Attachment.entry_id` / `Reminder.due_at` / `EntryLink` coverage.

## 1.4 Build, run, test, package

- **Build:** none. `frontend/*` is served as-is by `RevalidatedStatic`
  (`api/app.py:80`), and every local `css`/`js` URL is version-stamped
  `?v=0.2.2` (`tests/test_asset_cache_busting.py`).
- **Run:** `PYTHONPATH=src python -m uvicorn memorymap.api.app:create_app --factory`.
  Desktop: `__main__.py` runs uvicorn in a thread behind pywebview, with a tray.
- **Test:** `pytest` — 2,838 test functions across 219 files, ~7–8 min.
  `ruff check .` in CI, plus CodeQL. Four of the tests are **lints, not
  behaviour tests** (`test_style_scale`, `test_frontend_ids`,
  `test_frontend_handlers`, `test_docs_layout`) and exist because Python cannot
  see the DOM.
- **Package:** PyInstaller onedir + Inno Setup; `release.yml` in CI.

## 1.5 Frontend architecture — judged on its merits, as the brief asks

The no-framework choice is **right for this product and should be kept.** It
buys: zero supply chain, zero build step, a file you can open in an editor and
see running one reload later, and an offline guarantee that a bundler would put
one `npm install` away from being false. Nothing in this audit argues against
it.

What the choice does **not** buy, and what has been allowed to lapse:

- **Module boundaries.** Ten `<script src>` tags in document order
  (`index.html:7088-7176`), no `type="module"`, no imports. Every top-level
  function is a global: `app.js` alone declares **765** top-level functions and
  **320** top-level `const`/`let`. Cross-file calls are name lookups resolved at
  call time, which is exactly the failure HANDOVER's headline bug describes —
  `settingsModalOpen is not defined` thrown from a parse-time `keydown` handler
  because `settings.js` is the last script on the page.
- **A component vocabulary.** There is no `Button`, no `List`, no `Popover`. A
  "component" is a CSS class plus whichever of the 765 functions builds it. That
  is why the button-signature counts in §2A are what they are.
- **Function size.** Measured this session with a brace-depth scan:
  `initWhiteboard` **1,978 lines**, `openLightbox` **1,321**, `renderGraph`
  **1,120**, `filterLibraryImagesGallery` **1,021**, `sendChatMessage` **995**,
  `entryItem` **651**, `renderWhiteboard` **575**.
- **State.** `localStorage` is the state layer: **342** references
  (app.js 128, settings.js 83, whiteboard.js 54, library.js 22, documents.js 19,
  graph.js 17, dashboard.js 14). There is no single store and no schema for it.

What is genuinely good and must survive any refactor: `api()` as the one
request wrapper (17 `fetch(` sites total, most of them inside it), the
`renderIncrementally` chunk-on-scroll windower (`app.js:7093`, 60 initial + 40
per chunk, `IntersectionObserver`, with a written-down reason for choosing it
over true virtualisation), and `createElement`/`textContent` everywhere for user
content — all 18 `innerHTML =` sites are static markup or `escapeHtml()`-wrapped.

## 1.6 Backend architecture

27 routers, all mounted behind one `Depends(require_unlock)` list except
`/auth`, `/health` and one open settings router (`app.py:309-346`). Scoping to a
workspace is **ambient**: `session.info["workspace_id"]` plus a
`do_orm_execute` event in `core/database.py`, with `impersonate_workspace()` as
the escape hatch (AUDIT B2, PLAN B7). Long work runs on **22 ad-hoc
`threading.Thread` spawn sites** across `ai/`, `api/` and `core/`; what
finished is remembered in `core/taskhistory.py`, which is a
`deque(maxlen=40)` **in memory** and says so in its own docstring. There is no
`jobs` table (AUDIT B3, PLAN B2).

Strengths worth naming because they are unusual in a project this age:
`core/security.py` derives the CSP from `index.html`'s own script hashes at
request time rather than freezing one at startup; `OriginCheckMiddleware`
refuses cross-origin outright; GZip excludes `text/event-stream` and NDJSON by
name so streaming stays byte-identical.

## 1.7 Local AI integration — read, not run

**No local model was available in this sandbox. Everything in this section is
read from the code.**

- **Transport.** `ai/provider.py` (843 lines) is an abstract `Provider` with two
  implementations: `ai/ollama_client.py` (775) and `ai/openai_client.py` (939).
  `detect_provider(base_url)` picks one. Both default `timeout = 600.0`
  (`ollama_client.py:150`, `openai_client.py:116`) with the reason written down
  — a cold model load can take minutes — and both use a **short** timeout for
  liveness probes (`/api/tags` at 2 s, `/models` at 2 s) so the UI never hangs
  on "is it running".
- **Which models.** `ai/model_manager.py` resolves five roles from saved
  preferences with defaults: `chat_model()`, `vision_model()`, `ocr_model()`,
  `embedding_model()`, and a curated catalogue ordered **smallest-first**
  because the reader is choosing against hardware they already own. Nothing else
  in the codebase may hardcode a model name.
- **Fallbacks.** Layered, and this is the strongest part of the AI design:
  no model → the note still saves as `Uncategorised` with confidence 0; no
  embeddings → keyword search; model unreachable mid-answer →
  `librarian.model_error_message` with the connection detail sanitised;
  tools unsupported by the server → `ToolsUnsupportedError` and a text-mode
  fallback that parses tool calls out of prose (`extract_text_tool_calls`,
  `provider.py:781`).
- **Latency.** Not measurable here. What the code does about it: a per-model
  context window (`known_context`, `usable_context`), a generation budget
  (`generation_budget`), a `thinking_allowance`, `SMALL_WINDOW_TOKENS = 8_192`
  switching to a `COMPACT_TOOLS_GUIDE`, and `PROSE_BUDGET_CHARS = 3_000`
  asserted by a test because every prompt sentence is resent every round.
- **Where the design is thin** (reasoned): `ai/skill_runner.py` treats a step as
  a turn rather than a goal — the whole subject of
  [AGENT_SKILLS_REFORM.md](AGENT_SKILLS_REFORM.md), whose diagnosis this audit
  agrees with and does not restate.

## 1.8 Deployment targets

1. **Windows desktop** — the primary target. Installer, tray, pywebview window
   at 1200×800 (which is why ARCHITECTURE §10 invariant 5 exists).
2. **Linux desktop** — PyInstaller spec + `start.sh`.
3. **A browser on localhost** — the development and testing path.
4. **A phone over a tunnel** — not a supported target, but `routes_auth.py:86`
   records a real public client address arriving through a proxy header, so it
   happens. §2H treats it as real.

## 1.9 The main user journeys

| # | Journey | Surfaces it crosses |
| --- | --- | --- |
| J1 | Capture a thought and let it file itself | Notes › Capture → background janitor → notification |
| J2 | Find something later | Notes › Browse filter, Library, command palette, Graph |
| J3 | Ask the notebook a grounded question | Chat (or Notes › Ask), sources strip, citations |
| J4 | Let the agent act (tag, link, remind, create) | Chat agent mode, confirm dialogs, audit log |
| J5 | Read and mine a PDF | Library › Files → lightbox → OCR Workspace → page reads |
| J6 | Write something long | Library › Documents → the editor (live/source/split/read) |
| J7 | Think spatially | Whiteboard / boards & maps |
| J8 | Keep the system honest | Settings › Models, Tasks, Data, Logs |

J1 and J3 are the product. J5, J6, J7 are where the most code and the most
inconsistency live.

---

# 2. The audit

Severity is against the bar the brief sets — *a professional application people
pay attention to* — not against "does it work".

## A. UI design and visual consistency

### A1 · One component family has up to 22 recipes on a single screen — Critical

**Evidence (measured, `measure.js`, 1440×900, both themes' default palette).**
Distinct computed-style signatures per visible button, where a signature is
height + padding + border + radius + font size/weight/tracking + background +
colour + shadow-or-not:

| Tab | Visible buttons | Distinct signatures |
| --- | ---: | ---: |
| Chat | 48 | **22** |
| Library | 52 | **18** |
| Notes | 35 | **15** |
| Graph | 38 | 14 |
| Dashboard | 43 | 13 |
| Reminders | 45 | 13 |
| Timeline | 27 | 9 |

[UI_MODERNISATION_PLAN.md](UI_MODERNISATION_PLAN.md) Phase 2's target is **4**.
Chat is at 22 — one recipe for every 2.2 buttons on the screen.

**Impact.** This is the measurable content of "feels fake, vibe coded". The eye
reads *systematic* difference as meaning and *unsystematic* difference as
assembly from parts; 22 recipes guarantees the second reading no matter how
good any individual button is.

**Owner:** UI_MODERNISATION_PLAN Phase 2. This audit adds only the current
baseline numbers, which that plan did not have for all seven tabs.

### A2 · Glass and shadow scale with content, not with structure — High

**Evidence (measured, `measure2.js`, 1440×900, 40 seeded notes).** Elements with
a non-`none` `backdrop-filter`, and elements with a non-`none` `box-shadow`,
both counted among visible elements:

| Tab | Blurred layers | Nested blurs | Box-shadows |
| --- | ---: | ---: | ---: |
| Library | **44** | 0 | **129** |
| Dashboard | **27** | 0 | 32 |
| Timeline | 3 | 0 | 47 |
| Reminders | 4 | 0 | 15 |
| Notes | 5 | 0 | 13 |
| Chat | 4 | 0 | 12 |
| Graph | 4 | **1** | 11 |

HANDOVER records this session's predecessor bringing the range to "4–13, zero
nested on six of seven tabs". **Two tabs are outside that today and Graph still
has one nested blur.** The reason is structural rather than a regression: the
counts on Library and Dashboard are *per card*, so they grow with the notebook.
A blur is a full filter pass; 44 of them on a screen that will hold hundreds of
rows is a cost that gets worse the more the app is used.

**Impact.** Compositor cost on exactly the machine that is also running a local
model, and — the reason it belongs in §A rather than §F — a page that shimmers
instead of sitting still.

**Owner:** UI_MODERNISATION_PLAN Phase 3 item 3 already says "remove
`backdrop-filter` from widgets and list cards". This adds the number to hold it
to, and one rule that plan does not state: **glass belongs to the shell, so its
count must be O(1) in the notebook's size.** That is a testable invariant.

### A3 · The design system documents a fix that never reached three named controls — Medium

**Evidence (measured, `probe.js`, both widths).**
[../DESIGN.md](../DESIGN.md) § "Hit targets" lists, by id, the violations
`--target-min: 1.75rem` (28px) was introduced to fix:
`#semantic-search-toggle`, `#library-semantic-toggle`, `#library-show-binned` —
"**32×18**". All three measure **32 × 18.4 px today**, at 1440 and at 390, with
`opacity: 1`, `pointer-events: auto`, and `elementFromPoint` at their centre
returning the control itself. They are real, hit-testable, and still 18.4px tall.

**The honest qualifier, because it changes the severity.** Each sits inside a
`label.row` measuring **142.2 × 30.4 px**, and clicking a label toggles its
checkbox — so the *effective* target clears both WCAG 2.5.8's 24px and this
project's own 28px. What is 18.4px is the switch you are aiming at. This is
Medium, not High: it is fiddly, not inaccessible. But DESIGN.md reads as though
it were fixed, and it is not.

**Impact.** A design document that is wrong about a specific id is worse than
one that is silent, because the next session greps it and moves on.

### A4 · Not a finding, recorded so the next sweep stops flagging it

**Evidence (measured, `probe.js`).** `#chat-sidebar-sort` (1×1),
`#reminders-page-size` (1×1), `#reminder-priority` and `#reminder-recurring`
(1×44) are **native `<select>`s deliberately clipped** behind a styled sibling:
`opacity: 0`, `clip-path: inset(50%)`, `position: absolute`,
`pointer-events: none`, and `elementFromPoint` at the click point returns
`button.select-opener` or `span.select-shell`. This is the pattern DESIGN.md
names as the one deliberate exception. **A naive tap-target sweep will report
all four as 1px failures every time it is run** — which is why
`scratchpad/audit/probe.js` exists and why AUDIT E11's proposed sweep needs the
`elementFromPoint` step or it will generate four false positives forever.

*One loose end, not a finding:* at 390px, `elementFromPoint` at
`#reminders-page-size`'s centre returned `null` rather than the shell. The
native is absolutely positioned so its centre need not coincide with its opener;
worth one look, not a bug report.

## B. UX, feedback states and accessibility

### B1 · Three quarters of a phone screen is chrome — Critical

**Evidence (measured, `probe.js` chrome stack + `measure2.js` geometry, 40
seeded notes, Notes › Browse).**

| Viewport | First note's top | Viewport height | Chrome | Notes fully visible | Note card |
| --- | ---: | ---: | ---: | ---: | --- |
| 1440 × 900 | 252 px | 900 | 28% | **5** | 1074 × 108 |
| 1024 × 768 | 354 px | 768 | 46% | **3** | 683 × 108 |
| 390 × 844 | **640 px** | 844 | **76%** | **1** | 324 × 157 |

The stack at 390 px, row by row: `#top-bar` 106 · `#tab-bar` 40 ·
`#sidebar` 182 (the Categories card, holding four chips) · `#notes-subtabs` 55 ·
a `div.row.space-between` 38 · `div.library-toolbar` **177** (it wraps to four
lines). Screenshot at `notes-w390.png`, and the screenshot agrees with the
measurement.

**Impact.** REDESIGN §R1.1 measured "5 notes in a 900 px viewport" and called it
the structural problem. It is still exactly 5, and the card is 108 px tall
against R1.1's 121 px — **13 px of movement after everything in between.** On a
phone the same structure degrades to one note. This is the single largest gap
between what the app is and what it claims to be.

### B2 · The note card's actions sit on top of the note's text on touch — High, and new

**Evidence (measured, `overlap.js`).** At 390 × 844 with a touch context, four
buttons on the first note card — *Add to Favourites*, *Copy this note's text*,
*Edit this entry*, *More actions* — have `opacity: 1` and overlap the card's own
text box by 650, 650, 650 and 464 px² respectively, and `elementFromPoint` in
the middle of each overlap returns **the button**, not the text. At 1440 × 900
with a mouse the overlap is **zero**.

**Impact.** On the target this most affects (a phone, or any touch laptop) the
first line of every note is covered by icons and cannot be selected. It is not
in any existing plan because a desktop screenshot cannot show it: on a
`hover: hover` device the same buttons are hidden until hover, and the CSS that
reveals them on `hover: none` does not also move them.

**Mitigation, stated because it is cheap:** the reveal rule and the layout rule
have to change together — on coarse pointers the actions want their own row
under the text, not an absolutely-positioned cluster over it.

### B3 · There is no viewport below 600 px in the entire stylesheet — High

**Evidence (read, `frontend/css/*.css`).** 111 `@media` blocks. Sorted, the
distinct **viewport** breakpoints are: 600, 640 (40rem), 700, 720, 768 (48rem),
860, 896 (56rem), 900, 940, 960 (60rem), 1080, 1100, 1200, 1499 px on
`max-width`; 721, 1024 (64rem), 1200 px on `min-width`. The 720 px block carries
25 of the 111 rules and is the de-facto "mobile" breakpoint.

**Impact.** Every phone in common use is 360–430 px wide. All of them get the
rules written for a 600 px tablet. B1's 640 px of chrome is what that produces.

### B4 · Every counted metric is identical at 1024 and 1440 — Medium

**Evidence (measured, `measure.js` + `measure2.js`).** Across all seven tabs,
button signature counts, tap-target buckets, glass/shadow counts and clipped-
element counts are **byte-identical** between a 1024 × 768 and a 1440 × 900
viewport. Only geometry moved: `main` 1132 → 741 px, chrome 252 → 354 px.

**Impact.** This is REDESIGN §R1.1's "a step function, not a response" restated
with a different instrument. Between 1024 and 1440 — the whole range a laptop
lives in — the layout changes size and nothing changes *shape*. A 46%-chrome
1024 px screen is the desktop shell's own default window (1200 × 800) and is
therefore the most common real viewport this app has.

### B5 · Accessibility — better than the codebase's reputation, with three real gaps — Medium

**Evidence (read, `frontend/index.html`; measured, `measure.js`).**
The markup carries 476 `aria-label`, 423 `aria-hidden`, 240 `role=`,
35 `aria-expanded`, 16 `aria-pressed`, 16 `aria-labelledby`, 15 `aria-live`,
26 `tabindex`, over 616 `<button>`s and 187 `<input>`s, with **zero inline
`style=` attributes** (the CSP would refuse them anyway). A skip link exists
(`#skip-link`, measured in the 390px chrome stack). This is not a project that
ignored accessibility.

The gaps that are real:

1. **`aria-pressed` on 16 of 616 buttons** while segmented controls, toggles and
   tool docks are pervasive — a toggle that does not announce its state is a
   toggle a screen reader user cannot use. (AUDIT D10 says the same for the
   documents toolbar.)
2. **Focus trapping in dialogs is unverified** — 27 modal shells in
   `index.html`, and AUDIT E5 flags this as inference. It still is: this session
   did not test it either, and says so.
3. **The canvas surfaces have no list equivalent** — Graph and Whiteboard are
   the only door to their own content (AUDIT C11, PLAN G5).

### B6 · Designed states — Medium

**Evidence (read; AUDIT E7).** Empty states are a grey line of text; loading is
mostly nothing; errors are toasts that vanish in 5 s carrying actions
("Show it", "Undo") that cannot be found again (AUDIT E3). Not re-measured this
session — the fixture had content in every list — so this is carried forward
from AUDIT rather than re-evidenced. **Owner:** UI_MODERNISATION_PLAN Phase 6.

## C. Frontend architecture and code quality

### C1 · `app.js` is the architecture, and it is 26,113 lines — Critical

**Evidence (measured, `wc -l` + a brace-depth scan, this session).**

| File | Lines | Longest function |
| --- | ---: | --- |
| `frontend/app.js` | **26,113** | `openLightbox` **1,321** |
| `frontend/whiteboard.js` | 5,916 | `initWhiteboard` **1,978** |
| `frontend/library.js` | 3,422 | `filterLibraryImagesGallery` **1,021** |
| `frontend/graph.js` | 3,404 | `renderGraph` **1,120** |
| `frontend/settings.js` | 2,820 | `renderSamplingRows` 160 |
| `frontend/dashboard.js` | 2,387 | `renderDashboard` 158 |
| `frontend/documents.js` | 2,176 | `openDocSuggest` 143 |
| `frontend/editor.js` | 890 | `editorCommands` 294 |

`app.js` holds 765 top-level functions, 320 top-level bindings and 635
`addEventListener` calls. `sendChatMessage` is 995 lines; `entryItem` — the
function that builds one note row — is 651.

**Impact.** Three concrete costs, each already paid at least once in this
repo's history: (a) a cross-file global resolved at call time throws at parse
time (HANDOVER's `settingsModalOpen`); (b) `test_frontend_ids.py` and
`test_frontend_handlers.py` exist as *lints* because nothing else can see a
duplicate id or a double-registered listener in a file this size; (c) a
1,978-line function cannot be reviewed, so changes to it are made by search and
verified by hope.

**The right shape, given no build step:** ES modules. `<script type="module">`
works in every browser this app supports and in the pywebview shell, needs no
bundler, and turns 765 globals into explicit imports. That is the one structural
change this audit argues for that no existing plan contains.

### C2 · Four kinds of state, no store — High

**Evidence (measured, `grep -c`).** 342 `localStorage` references across seven
files; the server is the second store; the DOM is the third (selection state,
open menus and filter state are read back out of classes); module-level `let` is
the fourth. There is no schema for the `localStorage` keys, which is how
CLAUDE.md's worst-bug-in-the-project happened — two keys missing from
`APPEARANCE_DEFAULTS` wrote `undefined` and `NaN` into two CSS custom properties
and every card, field and dialog in the app rendered flat and borderless on
every fresh profile, with nothing logged and nothing thrown.

**Impact.** The class of bug is not fixed, only that instance of it. Any new
appearance key can do it again.

**Mitigation:** a `settings_schema` for the client, mirroring what AUDIT B14
asks for on the server — one declaration per key with a type, a default and a
validator, and a lint that fails when a key is read that the schema does not
declare.

### C3 · Everything is loaded on every boot — Medium

**Evidence (measured, `measure.js`, and `curl`).** 12 `<script src>` and 9
stylesheets, all eager, all on the critical path. Decoded weight: **4.29 MB of
JavaScript and 1.24 MB of CSS across 4,841 rules**; 48 resources, 1.81 MB
transferred with gzip on. That includes **`p5.min.js` at 1,034,532 bytes**,
which exists for the sketch pad, and `d3.v7.min.js` at 279,706 bytes, which
exists for the graph — both loaded before the lock screen paints.

**Impact.** On localhost this costs 864 ms to first paint (see §F1), which is
survivable. It is not free on a slow disk, and it is the reason the boot is a
single monolithic step with no way to make any one screen faster.

**Mitigation:** `import()` p5 when the sketch pad opens and d3 when the Graph
tab opens. Both are already `<script src>` tags in one place; both are used
behind a single entry point. This is small work with a measurable result.

### C4 · Static assets are `no-cache`, and the version stamp cannot make them `immutable` — Medium

**Evidence (measured, `curl -I`).** Every asset returns
`cache-control: no-cache` with an ETag, so every load is a conditional GET —
21 of them minimum. The version stamp is `?v=0.2.2`, i.e. **per release**, not
per content hash, so a mid-release edit to `app.js` would not bust it, which is
precisely why `no-cache` is there (`api/app.py:80` `RevalidatedStatic`, and the
stale-`app.js` story in CLAUDE.md).

**Impact.** Low on localhost. It matters because the trade is unnecessary:
stamping with a content hash instead of the release version lets the assets be
`immutable` *and* correct, and removes the whole class of "the browser is
running yesterday's app.js" that has cost this project two sessions.

## D. Backend architecture and reliability

### D1 · Errors are not a contract, and nothing catches what falls through — High

**Evidence (read + measured).** 209 `HTTPException(` sites in `src/`. There is
**no `@app.exception_handler`** registered anywhere in `api/app.py`. A live
request to a locked route returns `{"detail":"Locked — unlock first"}` — the
FastAPI default shape, with no `code`, no `hint`, no correlation `ref`. An
unhandled exception is therefore a bare 500 with a stack trace in the log and
"Request failed" in the UI.

**Impact.** Every failure in the product is indistinguishable from every other
failure to the person using it. AUDIT B11 / PLAN B3 own the fix; this adds the
count and the confirmed absence of a global handler.

### D2 · Long work has no queue, no persistence and no resume — High

**Evidence (read).** 22 `threading.Thread(` spawn sites in `src/memorymap/`
(model_manager ×2, embeddings ×2, autonomous ×2, captioning, vision_ocr ×2,
routes_entries, routes_update ×2, app.py, ocr, embedmodels, searxng ×2, and the
desktop shell). Completion is recorded in `core/taskhistory.py`, whose own
docstring says: "**In memory, not the database** … It goes away on restart, and
that is the right lifetime for it", bounded at `MAX_ENTRIES = 40`.

**Impact.** Closing the app mid-OCR loses the work with nothing to resume from
and no record that it was ever started; the UI cannot show a queue because there
is nothing to show. **Owner:** AUDIT B3 / PLAN B2. The docstring's reasoning is
right for *what happened while the app was open* and wrong for *what is still
owed* — those are two different questions and the app only answers the first.

### D3 · FTS5 exists for notes only; everything else is still a scan — Medium

**Evidence (read).** `core/database.py:1298-1373` creates `entries_fts`
(fts5), `entries_fts_vocab` (fts5vocab) and the insert trigger;
`search/search_manager.py:125` queries it with `bm25(entries_fts, 1.0, 4.0)` and
`:188` uses the vocab table for typo correction. **PLAN B5 is half built and
HISTORY does not say so.** The other half: 15 remaining `ilike(` sites, covering
`routes_documents`, `routes_chat` (×3), `routes_conversations`,
`routes_ask_history`, `ai/tools/documents.py`, `ai/tools/__init__.py` (×4),
`ai/entities.py` and `entry/manager.py` (×3).

**Impact.** Documents, conversations and the agent's own document search are
linear in notebook size and have no typo tolerance, while notes have both. The
inconsistency is worse than either state — the same query behaves differently
depending on which box it was typed into.

### D4 · Pagination is one-third done — Medium

**Evidence (read).** `GET /entries` takes `limit`/`offset` and returns
`X-Total-Count` (`routes_entries.py:1091`), with `ENTRIES_PAGE_SIZE = 1000`.
`GET /library` takes nothing and caps at `PER_KIND_LIMIT = 200` per kind
(`routes_library.py:47`). `GET /media` takes nothing, returns every row, and
**calls `stat()` per row** to fill `size_bytes` (`routes_files.py:1055-1075`) —
AUDIT A11 / PLAN P6, still open.

**Impact.** The default page size of 1000 means a 1,000-note notebook ships
1,000 records and their previews in one JSON body before the client filters. The
DOM cost is bounded by `renderIncrementally`; the transfer and parse cost is not.

### D5 · The OpenAPI schema is served to anyone who can reach the port — Medium

> **Stale as of 2026-09-08:** `create_app` sets `docs_url`, `redoc_url` and `openapi_url` to `None` (`api/app.py` ~361), so nothing is served. Recorded in WORLD_CLASS_PLAN.md 12 S10. Kept here so the finding is not re-raised.

**Evidence (measured, `curl`).** `GET /openapi.json` and `GET /docs` return
**200 without unlocking**, listing **238 paths**. The unlock gate covers the
data routers; the schema is not behind it.

**Impact.** No note content leaks. What leaks is the complete attack surface —
every route, every parameter, every model — to a scanner that finds the port.
For an app that binds `127.0.0.1` this is minor; `routes_auth.py:86` records a
real public client address arriving through a proxy header, which is exactly the
case where it stops being minor. **Fix:** `create_app(..., openapi_url=None)` in
packaged builds, or put both behind `require_unlock`. One line.

### D6 · What is *already right*, so nobody re-does it

Recorded because CLAUDE.md's most expensive recurring mistake is rebuilding
existing work, and three of these read as missing in older plans:

- **SQLite is tuned.** `foreign_keys=ON`, `journal_mode=WAL`,
  `busy_timeout=5000`, `synchronous=NORMAL`, plus four composite indexes over
  `entries` shaped to each list query's own `ORDER BY`
  (`core/database.py:1251-1418`). PLAN P5 is mostly done.
- **Note filing is off the request thread** (`routes_entries.py:388`) —
  PLAN P7's question is answered for entries.
- **Compression is correct**: `app.js` 1,488,077 → 463,317 bytes on the wire,
  with `text/event-stream` and `application/x-ndjson` excluded by name so
  streaming is unaffected.
- **The security headers are real** (see §H1).

## E. Local AI — where it is overused or misused

**No local model ran in this sandbox. Every finding in this section is reasoned
from the code and is marked so. None of it was observed.**

### E1 · A step is a turn, not a goal — Critical (reasoned)

`ai/skill_runner.py` closes a step when the model stops emitting, not when the
step's objective is satisfied, so a small model that narrates instead of acting
is recorded as having completed the step. This is
[AGENT_SKILLS_REFORM.md](AGENT_SKILLS_REFORM.md)'s own diagnosis; this audit
agrees with it, adds nothing, and defers to Phases A–D.

### E2 · The complexity of the AI path is where the next bug will be — High (read)

**Evidence (measured, `ruff --select C901`).** 40 functions in `src/` exceed
complexity 10. The top of the list is almost entirely the AI path:
`run_agent` **45**, `_run_optimization` **31**, `chat_stream` **26**,
`run_skill` **25**, `chat_tools_stream` **20** (in both clients),
`_retrieve` **20**. AUDIT §I named the top three; the list is longer than that
and it has not moved.

**Impact.** `run_agent` at complexity 45 is the function that decides what the
agent does, and it is the least testable function in the project. Every prompt
change, every new tool and every recovery hint lands in it.

### E3 · Model calls are scattered across request handlers, background threads and module singletons — High (read)

There is no one place where "the app is about to spend the user's CPU on a
model" is decided. Captioning, vision OCR, page reads, embeddings, tensions,
the janitor, the librarian, the autonomous loop and the skill runner each start
their own work their own way (§D2's 22 thread sites). Consequences that follow
without needing a model to observe: no global concurrency limit, so two
background jobs and a chat turn can contend for the same GPU; no shared budget;
no single "stop everything" — PLAN A5's Stop cannot cancel what it does not own.

### E4 · The honest positives, so the section is not one-sided (read)

`unsupported_claims` (`agent.py:863`) checks the answer's claims against the
tools that actually ran and is backed by 14 tests — a genuine verification
mechanism most agent harnesses do not have. `PROSE_BUDGET_CHARS` is asserted.
Every fallback path (§1.7) degrades to something true rather than to a spinner.
The catalogue is ordered smallest-first for a stated reason. This is a
thoughtfully built harness with a structural gap, not a careless one.

## F. Performance and perceived speed

### F1 · Boot is ~1 s and tab switches are ~10–50 ms. The app is not slow; it is *heavy* — Medium

**Evidence (measured, `measure.js` / `measure2.js`).**

| Metric | Value |
| --- | ---: |
| First paint / first contentful paint | **864 ms** |
| DOMContentLoaded | **1,025 ms** |
| Load event | 1,047 ms |
| Resources on boot | 48, 1.81 MB transferred |
| DOM nodes at boot | 4,562 |
| Tab switch (7 tabs × 3 widths) | **10–54 ms** |

**Impact, stated against the brief's assumption.** The brief asserts the app
"feels laggy and slow". On this hardware, at this notebook size, **the
navigation is not slow** — 10–54 ms is imperceptible. What is measurable is
weight (4.29 MB of JS decoded, §C3), idle chatter (§F2) and per-card compositing
(§A2). The subjective complaint is more likely §B1 — you cannot see anything, so
the app feels like it is not responding — than latency. That reframing matters
because optimising the wrong one produces no felt change.

### F2 · Fourteen requests in sixty idle seconds, from three separate timers — High

**Evidence (measured, `measure.js`: `performance.getEntriesByType('resource')`
over exactly 60,006 ms sitting on the Dashboard, doing nothing).**

| Path | Requests in 60 s |
| --- | ---: |
| `/models/status` | 6 |
| `/tasks` | 6 |
| `/reminders` | 2 |
| **Total** | **14** |

[PLAN.md](PLAN.md) **P1**'s acceptance gate is "≤ 4 requests over 60 s idle on
the dashboard" and asks for the current number to be counted first and written
into HANDOVER. **This is that number: 14.** Eleven `setInterval` call
sites exist across the frontend (`app.js` 8 — a ninth `grep` hit at `:19562` is
a comment recording a previous duplicate-timer bug — plus `dashboard.js` 2 and
`library.js` 1); none of the three polls above backs off on `document.hidden` — the tab was foreground for
this measurement, so whether they back off is *untested here*, not disproved.

**Impact.** Every one of those wakes the Python process on the machine that is
also running the model. It is also the reason `waitUntil: "networkidle"` never
settles, which is a documented hour-costing trap for everyone who works on this
app.

### F3 · List rendering is solved; list *fetching* is not — Medium

**Evidence (read, `app.js:7093-7160`).** `renderIncrementally` paints 60 rows
then 40 per `IntersectionObserver` chunk, with the trade-off (browser Ctrl+F
cannot find unpainted rows) written down and the reason for choosing chunking
over true virtualisation written down. The recorded pre-fix number: 1,501 notes
took ~533 ms in `renderEntries()`. **This is built — PLAN N3 should not be
re-scoped as "no virtualisation exists".** What is not solved is §D4: the client
still receives up to 1,000 records to filter.

## G. Mobile and responsive

Covered by **B1** (76% chrome, one note visible), **B2** (actions over text on
touch), **B3** (no breakpoint below 600 px) and **B4** (1024 ≡ 1440). Two more:

### G1 · Primary navigation scrolls off the phone screen — High

**Evidence (measured, `measure.js`; screenshot `notes-w390.png`).** At 390 px
the document does **not** overflow horizontally (`scrollWidth === innerWidth` at
all three widths, on all seven tabs — the shell is correct). Inside it,
`#tab-btn-reminders`'s right edge lands at 630–636 px on a 390 px viewport (it
varies slightly with which tab is active), i.e. **three of the seven tabs are
off-screen inside a horizontal scroller**. The screenshot shows
the strip cut mid-word at "Timelin".

**Impact.** The app's whole navigation is a horizontal scroll gesture on a
phone, with no affordance that anything is to the right of "Library".

### G2 · The category sidebar becomes a 182 px banner — Medium

**Evidence (measured, `probe.js` chrome stack).** At 390 px the sidebar does not
collapse or become a drawer; it stacks *above* the list at 182 px tall to show
four chips ("All 40", "Drafts 0", "Favourites 0", "Uncategorised 40"). That is
22% of the phone's viewport spent on a filter that could be one row.

## H. Missing table stakes, security and privacy

### H1 · Security posture is genuinely strong — recorded as a positive

**Evidence (measured, `curl -I`).** Live response headers:

```
content-security-policy: default-src 'self'; script-src 'self'; style-src 'self';
  img-src 'self' data: blob:; font-src 'self'; media-src 'self' blob:;
  connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self';
  form-action 'self'; frame-ancestors 'none'; frame-src 'self' blob:
x-frame-options: DENY
x-content-type-options: nosniff
referrer-policy: no-referrer
permissions-policy: geolocation=(), camera=(), payment=(), usb=()
```

**No `unsafe-inline`, no `unsafe-eval`, and the policy is derived from
`index.html`'s own script hashes per request** rather than frozen at startup
(`core/security.py:119-260`). Plus: `OriginCheckMiddleware`; bcrypt with an
exponential global unlock throttle (`routes_auth.py:86-120`, 5 free tries then
2ⁿ seconds to a 300 s ceiling, cleared on success, forgiven after 15 min); no
`shell=True`, no `eval`, no `pickle`, no `yaml.load`; path traversal guarded by
`basename` + `is_relative_to`; **all 18 `innerHTML =` sites static markup or
`escapeHtml()`-wrapped** (re-checked this session, including the diff viewer at
`app.js:12733` and the audit-log list at `library.js:1722`).

### H2 · The gaps that are actually missing — High

| # | Missing | Evidence | Impact |
| --- | --- | --- | --- |
| H2a | **A crash you can report.** No error boundary, no correlation id, no "copy diagnostics" — §D1 | read | A user's only bug report is "it broke" |
| H2b | **Backups you can trust.** `_backup_if_due` exists (`app.py:129`) but there is no restore-verification, no checksum, no `sha256` on files (AUDIT B9) | read | Restore is unproven until the day it matters |
| H2c | **Notifications are `localStorage`, reminders are rows.** "Mark complete" on a reminder notification cannot complete the reminder (AUDIT A15/B13) | read | The two systems disagree and the user sees both |
| H2d | **The OpenAPI schema is public** — §D5 | measured | Full surface disclosure over a tunnel |
| H2e | **No offline-only master switch.** Web search and update checks are individually gated; there is no one control that greys every network path and says so in the status bar | read, PLAN §15 | "100% offline" is a claim the UI cannot demonstrate |
| H2f | **Three browser tests.** 2,838 Python test functions; `tests-e2e/specs/smoke.spec.js` holds **3** Playwright tests for 47,220 lines of JS | measured | Every UI regression in this project's history was found by a human |

### H3 · Privacy is a claim without an artefact — Medium

`docs/PRIVACY.md` exists and the code backs it. What does not exist is the thing
[ANALYSIS.md](ANALYSIS.md) §114 already proposes and this audit endorses: a
**privacy receipt** page generated *from the code* — every outbound-capable call
site, its current on/off state, and when it last fired. "No telemetry" asserted
in prose is a promise; the same thing rendered from a grep of the source is an
artefact, and it is the moat §7 argues is hardest to copy.

---

# 3. The vision

## 3.1 What "good" looks like, in five sentences

MemoryMap is the notebook you can *believe*: every answer shows the notes it
came from, every action the agent takes is visible, undoable and logged, and
nothing ever leaves the machine. It opens on a quiet page where the content is
the first thing you see and the chrome is the last, at every window size from a
phone to a 1440px laptop. There is one of each thing — one list, one editor, one
picker, one popover, one card — so learning any screen teaches you the rest.
The local model is a resource the app spends deliberately, with a queue you can
watch, a budget you set and a Stop that really stops. And when something fails
it says which thing failed, why, and what to do about it, in the place where it
failed.

## 3.2 The principles

1. **Content first, chrome last.** No screen spends more than 25% of its height
   on chrome before the first item. Measured per surface, per width, in CI.
2. **One recipe per component family, and the count is the test.** Four button
   signatures, two row recipes, one popover shell, one dialog. A new recipe
   needs a deleted one.
3. **Subtract before adding.** Every phase removes a rule, a border, a shadow or
   a size before it adjusts what is left. Decoration never does structure's job:
   tone and whitespace group things, hairlines mark panes.
4. **Glass is shell furniture, and its cost is O(1) in the notebook.** A blur
   count that grows with the number of rows on screen is a bug, not a style.
5. **Measure, change, re-measure — and put the number in the commit.** A
   screenshot you looked at is not a measurement. `scrollHeight` vs
   `clientHeight` settles clipping; `scratchpad/pngpixel.py` settles colour;
   `elementFromPoint` settles "can you actually click it".
6. **Say what you did not verify.** Especially anything about model behaviour:
   this sandbox has no local model, and a claim made without one is a guess.
7. **Every AI feature ships with visible reasoning, an undo and a log — or it
   does not ship.** This is the moat (§7.2); it is also the only honest way to
   sell a local model smaller than the one in the cloud.
8. **Offline is demonstrable, not asserted.** One master switch, one status-bar
   state, one receipt page generated from the code.

## 3.3 Target architecture

**Frontend.** Keep vanilla, keep no-build. Move to **ES modules**
(`<script type="module">`, native `import`) so 765 globals become explicit
edges — no bundler, no dependency, no CDN, and it works in the pywebview shell.
Four layers, in dependency order:

```
core/      api.js (the one fetch wrapper) · store.js (typed prefs, one schema)
           events.js (one pub/sub) · schedule.js (THE poll loop, W3-1)
ui/        button · list · row · card · popover · dialog · field · empty · toast
           — one module per family, the only place its CSS class is produced
features/  notes · chat · graph · library · documents · whiteboard · settings
           — each owns its screen and imports only from ui/ and core/
app.js     the shell: tabs, routing, boot order
```

Migration is incremental and provably safe: a `ui/` module is created by moving
one existing builder function out of `app.js` and importing it back, and the
existing lints (`test_frontend_ids`, `test_frontend_handlers`) catch the two
mistakes that shape of move can make.

**Backend.** Keep FastAPI, keep one process, keep synchronous SQLAlchemy —
REDESIGN §R7.7 already measured that async is not the answer and wrote the
reasoning down so nobody redoes it. Add the three missing spines:

```
core/jobs.py     one jobs table + one worker; every model call except
                 /chat/stream returns 202 {job_id}; GET /jobs/{id} for progress
core/errors.py   one exception handler; every failure is {code, detail, hint, ref}
core/search.py   one search(q, scope, k) — FTS5 ∪ embedding kNN, RRF-fused,
                 keyword-only when there is no embedding backend
```

**Local AI orchestration.** One `ai/scheduler.py` in front of every model call,
owning: a global concurrency limit (default 1 — there is one GPU), a per-turn
token and wall-clock budget, cancellation, and priority (a chat turn preempts a
background caption). `provider.py` stays exactly as it is; the scheduler sits
above it. This is what makes PLAN A5's Stop implementable at all.

**Observability without telemetry.** `/debug/health` (PLAN B9) plus a Settings ›
About panel: db size, job queue depth, model p50/p95 from `taskhistory`, the
last 20 errors by `ref`, index freshness. All local, all user-visible, nothing
transmitted — §7.3.

---

# 4. The improvement plan, in workstreams

Effort: **S** ≤ ½ session · **M** 1 session · **L** 2+ sessions.
Owner type: **FE** frontend · **BE** backend · **AI** model/agent ·
**DS** design system · **QA** test/tooling.
Rows an existing plan already owns say so and add nothing but a baseline.

## W1 — Design system (owner: DS)

*Goal:* one recipe per family, counted, in both themes.
*Success metrics:* ≤ 4 button signatures on every tab (today 9–22, §A1);
≤ 13 blurred layers on every tab **and** blur count independent of row count
(today 44 on Library, §A2); one card padding per card size; one popover shell.

| # | Initiative | Problem | Approach | Files | Deps | Effort | Risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| W1-1 | Sweep tooling + `tests/test_ui_signatures.py` | Every later count is unverifiable | Owned by **UI_MODERNISATION_PLAN Phase 0**. Addition: fold `scratchpad/audit/*.js` in as the seven-tab, three-width baseline — Phase 0's screenshot set has no signature numbers for Chat, Graph or Reminders yet | `scratchpad/ui-sweeps/`, `scratchpad/audit/`, `tests/` | — | M | Low |
| W1-2 | Button ramp to 4 signatures | §A1: 22 on Chat, 18 on Library | **UI plan Phase 2**, unchanged | `frontend/css/*` | W1-1 | L | Med |
| W1-3 | Glass as shell furniture | §A2: 44 blurred layers on Library, and the count grows with the notebook | **UI plan Phase 3.3**, plus one new invariant: assert the blur count is unchanged between a 10-note and a 200-note fixture | `00-tokens-shell.css`, `03-dashboard-widgets.css`, `library.js` | W1-1 | M | Low |
| W1-4 | The three 18.4px switches, and correct DESIGN.md | §A3: the design doc names them by id as fixed; they are not | Give the switch graphic a 28px min box; re-measure; then edit DESIGN.md's own list so it stops being wrong | `01-forms-settings.css`, `docs/DESIGN.md` | — | S | Low |
| W1-5 | One popover shell, hidden until placed | UI plan Phase 2 (menus) + Phase 4.1 | Owned by **UI plan Phases 2 and 4**; the toolbar menus are done, the other five shells are not | `frontend/css/*`, `app.js` | W1-1 | M | Med |

## W2 — UX overhauls for the core journeys (owner: FE + DS)

*Goal:* the content is the first thing on every screen at every width.
*Success metrics:* chrome ≤ 25% of viewport height on all seven tabs at 1440,
1024 **and 390** (today 28% / 46% / 76% on Notes, §B1); ≥ 12 notes visible at
1440 (today 5); ≥ 4 at 390 (today 1); zero action buttons overlapping content
text on a touch viewport (today 4, §B2).

| # | Initiative | Problem | Approach | Files | Deps | Effort | Risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| W2-1 | Collapse the chrome stack | §B1 | Merge `div.row.space-between` and `div.library-toolbar` into one 38px control row, with the overflow behind a "⋯ Filters" popover; the sub-tab strip becomes a segment inside that same row | `index.html`, `app.js` `renderEntries`, `05-sidebars-themes.css` | W1-1 | M | Med |
| W2-2 | The note row at reading density | §B1: a 108px row for two lines of text, 1074px wide | Row list becomes the default; cards stay for image-bearing notes. A `--measure` cap so the text column is ~640px, not 1074px | `app.js` `entryItem` (651 lines — split first), `02-chat-graph.css` | W2-1, W3-3 | M | Med |
| W2-3 | Touch layout for card actions | §B2 | Under `@media (hover: none)` the actions get their own row below the text instead of an absolute cluster over it | `02-chat-graph.css`, `app.js` `entryItem` | — | S | Low |
| W2-4 | Sidebar → chips → drawer | §G2: a 182px banner for four chips at 390px | The Categories card becomes a filter chip row at ≤720px and a drawer at ≤600px | `05-sidebars-themes.css`, `app.js` | W2-1 | S | Low |
| W2-5 | A tab bar that fits a phone | §G1: three of seven tabs off-screen, no affordance | Below 600px: a five-item bottom bar plus a "More" sheet, or an icon-only strip. Decide by building both and measuring reach, not by preference | `index.html`, `00-tokens-shell.css` | — | M | Med |
| W2-6 | Designed empty / loading / error states | §B6 | Owned by **UI plan Phase 6**; addition: the inline error state is the render target for §D1's `hint` field, so W4-1 and this ship together | `frontend/css/*`, every list renderer | W4-1 | M | Low |

## W3 — Frontend refactor and performance (owner: FE)

*Goal:* the frontend has boundaries, and idle costs nothing.
*Success metrics:* ≤ 4 requests in 60s idle (today **14**, §F2); no file over
4,000 lines and no function over 300 (today 26,113 and 1,978, §C1); JS decoded
on boot < 3 MB (today 4.29 MB, §C3).

| # | Initiative | Problem | Approach | Files | Deps | Effort | Risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| W3-1 | One visibility-aware scheduler | §F2: three timers, 14 requests a minute, none backing off | Owned by **PLAN P1**. This audit supplies the baseline P1 asked for and did not have: **14**, being `/models/status` ×6, `/tasks` ×6, `/reminders` ×2 | `app.js` (8 `setInterval` sites), `dashboard.js` (2), `library.js` (1) | — | M | Low |
| W3-2 | ES modules | §C1: 765 globals; a cross-file global in a parse-time listener throws | `<script type="module">`; move one builder at a time into `frontend/ui/` and import it back. `test_frontend_handlers.py` guards the half that can go wrong silently | `index.html`, all `frontend/*.js` | W1-1, W8-1 | L | **High** |
| W3-3 | Split the four giants | `initWhiteboard` 1,978 · `openLightbox` 1,321 · `renderGraph` 1,120 · `filterLibraryImagesGallery` 1,021 | Pure extraction, no behaviour change, one function per commit, with a Playwright assertion taken before and repeated after | `whiteboard.js`, `app.js`, `graph.js`, `library.js` | W3-2 | L | High |
| W3-4 | Lazy-load p5 and d3 | §C3: 1.31 MB of vendor JS parsed before the lock screen paints | `import()` p5 when the sketch pad opens, d3 when the Graph tab opens | `index.html`, `graph.js`, `app.js` | W3-2 | S | Low |
| W3-5 | A typed client settings schema | §C2: the `undefined`/`NaN` custom-property class of bug is not fixed, only that instance | One declaration per key (type, default, validator) plus a lint that fails on an undeclared read; mirrors AUDIT B14 on the server | new `frontend/core/store.js`, `settings.js` | W3-2 | M | Med |
| W3-6 | Content-hash asset stamps | §C4: `?v=0.2.2` is per release, which is why `no-cache` is mandatory | Stamp with a hash of the file's bytes, then serve `immutable`. Extends `tests/test_asset_cache_busting.py` | `api/app.py`, `index.html`, that test | — | S | Low |

## W4 — Backend hardening and API cleanup (owner: BE)

*Goal:* every failure names itself; every long job survives a restart.
*Success metrics:* zero bare 500s (`tests/test_error_contract.py` over all 267
routes); a job killed mid-run ends `failed`, never half-written; `/media` with
2,000 uploads under 50 ms.

| # | Initiative | Problem | Owner / what this audit adds | Effort | Risk |
| --- | --- | --- | --- | --- | --- |
| W4-1 | Error contract | §D1: 209 raise sites and **zero** exception handlers | **PLAN B3.** Addition: confirmed there is no `@app.exception_handler` anywhere, so this is greenfield rather than a retrofit | M | Low |
| W4-2 | Jobs table + one worker | §D2: 22 thread sites; history is a 40-deep in-memory deque | **PLAN B2 / AUDIT B3**, unchanged | L | Med |
| W4-3 | `/media` stops stat-ing the disk per row | §D4 | **PLAN P6 / AUDIT A11**, unchanged | S | Low |
| W4-4 | Finish FTS5 | §D3: notes have bm25 and typo tolerance; documents and conversations have `ILIKE` | **PLAN B5 is half built and no doc says so.** Remaining: 15 `ilike(` sites. Do documents first — it is the one users notice | M | Med |
| W4-5 | Pagination for `/library`, `/media`, `/documents` | §D4 | **PLAN B4**, narrowed: `/entries` already has `limit`/`offset` + `X-Total-Count`, so scope this to the three that do not | M | Med |
| W4-6 | Close the OpenAPI schema | §D5: 238 paths served unauthenticated | `openapi_url=None` in packaged builds, or both endpoints behind `require_unlock` | S | Low |
| W4-7 | One file model | AUDIT B1 / PLAN B1 | Unchanged, and still the riskiest backend row on the board | L | High |

## W5 — Local AI redesign (owner: AI)

*Goal:* a small model can finish a skill; the app spends CPU deliberately.
*Success metrics:* a five-step built-in skill on a 4B model completes every step
or names the contract that failed — **requires a real local model and cannot be
closed from this sandbox**; `run_agent` complexity below 25 (today 45); one
global concurrency limit.

| # | Initiative | Problem | Owner / what this audit adds | Effort | Risk |
| --- | --- | --- | --- | --- | --- |
| W5-1 | Step contracts + structured state | §E1 | **AGENT_SKILLS_REFORM Phase A**, unchanged | M | Med |
| W5-2 | Small-model mode | §E1 | **Phase B**, unchanged. Explicitly not verifiable here | M | Med |
| W5-3 | The run as a collapsible object | The "text dump in your face" report | **Phase C**, unchanged | M | Low |
| W5-4 | `ai/scheduler.py` | §E3: no global concurrency limit, no shared budget, no real Stop across 22 thread sites | One gate in front of every model call; this is what makes PLAN A5's Stop implementable rather than aspirational | M | Med |
| W5-5 | Split `run_agent` | §E2: complexity 45, the highest in the codebase, and the function every prompt change lands in | Extract the tool loop, the claim check and the message builder. Behaviour-preserving, guarded by the existing agent tests | M | Med |
| W5-6 | Eval harness | §E2, PLAN A6 | **PLAN A6**, unchanged. It is the only way W5-1 and W5-2 are ever proven rather than believed | M | Low |

## W6 — Mobile and responsive (owner: FE + DS)

*Goal:* usable one-handed on a 390px phone.
*Success metrics:* a breakpoint at ≤ 430px exists and is exercised (today the
smallest is 600px, §B3); chrome ≤ 25% at 390px (today 76%); every tab reachable
without a horizontal scroll gesture; zero content covered by controls on touch.

Initiatives: **W2-3**, **W2-4**, **W2-5**, plus **W6-1** — add 390 and 430 to
the sweep matrix so every count in W1's metrics is taken at four widths rather
than three. Effort M, risk Low, depends on W1-1.

## W7 — The table-stakes backlog (owner: BE + FE)

| # | Initiative | Evidence | Effort | Risk |
| --- | --- | --- | --- | --- |
| W7-1 | Diagnostics: an error `ref`, a "copy for a bug report" that redacts note text, and a crash boundary | §H2a | M | Low |
| W7-2 | Backup integrity: `sha256` per file, a restore that verifies, and a restore test in CI | §H2b, AUDIT B9 | M | Med |
| W7-3 | Notifications become rows, and a reminder notification's Done completes the reminder | §H2c, AUDIT A15/B13 | M | Med |
| W7-4 | One offline-only master switch, with a status-bar state | §H2e | S | Low |
| W7-5 | The privacy receipt, generated from the code | §H3, ANALYSIS §114 | M | Low |

## W8 — Reliability, testing and observability (owner: QA)

*Goal:* a UI regression is caught by CI, not by the person using the app.
*Success metrics:* ≥ 30 Playwright assertions across three widths in CI (today
**3**, §H2f); the four §W1 counts asserted as ceilings that later phases lower.

| # | Initiative | Evidence | Effort | Risk |
| --- | --- | --- | --- | --- |
| W8-1 | Promote `scratchpad/audit/*.js` into `tests/e2e/` at three widths | §H2f | M | Low |
| W8-2 | `tests/test_ui_signatures.py` as a static ceiling | §A1 | S | Low |
| W8-3 | `tests/test_error_contract.py` over all 267 routes | §D1 | M | Low |
| W8-4 | `/debug/health` + a Settings › About panel | §3.3, PLAN B9 | M | Low |
| W8-5 | An `APPEARANCE_DEFAULTS` completeness lint | §C2, and CLAUDE.md's worst-bug story | S | Low |

---

# 5. The 90-day roadmap

Each phase ends with something a user can see. Every item names its workstream
row, so nothing here is a second copy of a plan.

## Now — weeks 0–4: "the app stops hiding its own content"

| # | Item | Why now |
| --- | --- | --- |
| 1 | **W1-1** sweep tooling + signature test (UI plan Phase 0) | Nothing after it is measurable |
| 2 | **W3-1** one poll loop, 14 → ≤ 4 (PLAN P1) | Half a day; the whole app goes quiet, and `networkidle` starts settling for everyone who tests it |
| 3 | **W4-1** the error contract (PLAN B3) | Greenfield — there is no handler to retrofit; it kills "Request failed" everywhere at once |
| 4 | **W2-1** collapse the chrome stack, Notes first | 252 / 354 / 640px is the loudest number in this audit |
| 5 | **W2-3** touch actions off the note text | A real bug found this session, and it is an hour |
| 6 | **W1-4** the three 18.4px switches + correct DESIGN.md | Small, and it makes the design document true again |
| 7 | **W3-4** lazy p5 + d3 | 1.31 MB off the boot path in one afternoon |
| 8 | **W4-6** close the OpenAPI schema | One line |
| 9 | **W1-2 / W1-3** the button ramp and the glass pass (UI plan Phases 2–3) | The largest visible change; needs item 1 first |
| 10 | **W8-1** the audit scripts become `tests/e2e/` | Locks in every number above so the next session inherits them |

## Next — weeks 5–8: "a small model can finish a job, and so can the app"

| # | Item | Why here |
| --- | --- | --- |
| 1 | **W5-1** step contracts (Reform Phase A) | The functional half of "feels unprofessional" |
| 2 | **W5-2** small-model mode (Reform Phase B) | Asked for in the same breath as the UI |
| 3 | **W4-2** jobs table + worker (PLAN B2) | Everything below wants a queue to hang off |
| 4 | **W5-4** `ai/scheduler.py` | Needs the queue; makes Stop real |
| 5 | **W5-3** the run as a collapsible object (Reform Phase C) | Needs 1–2 before there is anything worth collapsing |
| 6 | **W2-4 / W2-5 / W6-1** the phone pass | Needs W1's system settled or it gets done twice |
| 7 | **W4-4** finish FTS5 for documents | Users notice this more than any other backend row |
| 8 | **W2-2** the note row at reading density | Needs W3-3's `entryItem` split |
| 9 | **W7-3** notifications as rows | Needs the jobs table's shape to copy |
| 10 | **W8-3** the error-contract test over 267 routes | Locks in Now item 3 |

## Later — weeks 9–12+: "structure that lasts"

| # | Item | Why last |
| --- | --- | --- |
| 1 | **W3-2** ES modules | High risk; needs the e2e net from Now item 10 |
| 2 | **W3-3** split the four giants | Only safe after 1 |
| 3 | **W3-5** the typed client settings schema | Needs modules |
| 4 | **W4-7** one file model (PLAN B1) | The riskiest backend row; do it behind a new router with the old ones kept |
| 5 | **W4-5** pagination for library / media / documents | Wants item 4's shape |
| 6 | **W5-5** split `run_agent`; **W5-6** the eval harness (PLAN A6) | Needs the scheduler underneath |
| 7 | **W7-1 / W7-2** diagnostics and backup integrity | Needs the error contract |
| 8 | **W7-5** the generated privacy receipt | Cheap, and it is the moat |
| 9 | **UI plan Phase 7** (lightbox, gutters, document captioning, region OCR) and **PLAN's D-series** | The editor and files long tail |
| 10 | **Mindmaps** — make MINDMAP_PLAN §4's scope call, confirm §1's product name, then its Phases 1–3 | Needs a settled design system underneath it |

## The three killer combos

**Combo 1 — "it's suddenly a real app."**
W2-1 (chrome collapses) + W1-2 (four button recipes) + W1-3 (glass leaves the
cards) + W3-1 (the app goes quiet). Together the Notes screen goes from 252px of
chrome and five visible notes to one 38px control row and twelve or more, on a
page that sits still and stops talking to the server fourteen times a minute.
Nothing else on this board changes the first ten seconds as much, and every part
of it is measurable before and after.

**Combo 2 — "the AI stopped being a demo."**
W5-1 (step contracts) + W5-4 (the scheduler) + W4-2 (the jobs table) + W5-3 (the
run as an object). A skill on a 4B model either finishes or says exactly which
contract failed; the work is a queue you can watch, budget and cancel; Stop
stops. That is the difference between an agent you show someone and an agent you
use. **It cannot be signed off from this sandbox — it needs a real local model.**

**Combo 3 — "you can trust it with the only copy."**
W4-1 (errors name themselves) + W7-1 (a bug report you can send) + W7-2 (backups
that verify) + W7-5 (the privacy receipt) + W8-4 (`/debug/health`). An offline
notebook's whole promise is that it holds the only copy; today it cannot prove a
restore works or show what it did wrong. These four turn "trust me" into
artefacts.

---

# 6. Execution briefs

Eight briefs, specific enough that another agent can start coding from them.
Each one names the measurement that closes it, because in this repo a UI claim
without a measurement is a guess.

## Brief 1 — W3-1: one visibility-aware scheduler (PLAN P1)

**Context and goal.** Measured this session: sitting on the Dashboard doing
nothing for 60,006 ms produces **14 HTTP requests** — `/models/status` ×6,
`/tasks` ×6, `/reminders` ×2 — from three independent `setInterval` timers, none
of which backs off when the tab is hidden. PLAN P1's acceptance gate is ≤ 4 and
asks for exactly this baseline first. Goal: one scheduler, ≤ 4 requests in 60s
idle, nothing polling behind the lock screen.

**Files.** `frontend/app.js` (8 `setInterval` call sites — `:11341`, `:15698`,
`:18512`, `:24218`, `:24258`, `:24953` `checkDueReminders`, `:32484`, `:32537`;
the ninth `grep` hit at `:19562` is a comment recording a previous
duplicate-timer bug), `frontend/dashboard.js` (`:342`, `:2542`),
`frontend/library.js` (`:2135`).

**Steps.**
1. Add `frontend/core/schedule.js` (or a section of `app.js` until W3-2 lands)
   exposing `every(name, ms, fn, {whenHidden})`. One `setInterval` at the
   greatest common cadence drives a task table; each task has its own period,
   its own `lastRun`, and a `whenHidden` policy of `skip` (default) or a
   multiplier.
2. Register the three *server* polls on it: model status, tasks, reminders.
   Leave the four *clock* timers (`tickClocks`, `paintChatTimer`,
   `paintStatusClockDetail`, the meeting timer) alone — they are local and cost
   no request; folding them in is scope creep with a rendering risk.
3. Add a `document.visibilitychange` listener that pauses the scheduler when
   hidden and runs every overdue task once on the way back.
4. Stop the scheduler on lock and start it on unlock — the lock screen currently
   keeps polling, which is both wasteful and a small information leak about
   whether the app is alive.
5. Re-run `scratchpad/audit/measure.js` and put the before/after in the commit.

**Acceptance.**
- `measure.js`'s `idle60s.total` ≤ 4 on the Dashboard, from 14.
- With the tab hidden for 60s, `idle60s.total` is 0.
- On the lock screen for 60s, `idle60s.total` is 0.
- A reminder that becomes due while the tab is hidden fires within one period of
  the tab becoming visible again (Playwright: set a reminder 5s out, hide, wait,
  show, assert the notification).

**Risks.** A missed catch-up on visibility change turns a live reminder into a
silent one — step 3's "run every overdue task once" is the mitigation and it
needs the test in the last bullet, not a code review. Second: `checkDueReminders`
is the timer CLAUDE.md records as having run on *two* timers once already; grep
for a second registration before assuming there is one.

## Brief 2 — W2-1: collapse the Notes chrome stack

**Context and goal.** Measured: the first note sits at y=252 of a 900px viewport
(28%), y=354 of 768 (46%) and y=640 of 844 (**76%**). The 390px stack is
`#top-bar` 106 · `#tab-bar` 40 · `#sidebar` 182 · `#notes-subtabs` 55 ·
`div.row.space-between` 38 · `div.library-toolbar` **177**. REDESIGN §R1.1
measured 5 notes visible at 900px before all of this session's predecessors'
work; it is still 5. Goal: ≤ 25% chrome at all three widths and ≥ 12 notes
visible at 1440.

**Files.** `frontend/index.html` (the Notes tab's control rows),
`frontend/app.js` `renderEntries` (`:7372`) and `entryItem` (`:` — 651 lines),
`frontend/css/05-sidebars-themes.css`, `frontend/css/02-chat-graph.css`.

**Steps.**
1. Merge `div.row.space-between` and `div.library-toolbar` into one control row
   at `--control-h`. Filter, sort, view switcher and Select stay; Semantic,
   "Show binned" and the category select move behind one "⋯" popover using
   W1-5's shell.
2. Move the sub-tab strip (`#notes-subtabs`, 55px) into that same row as a
   segmented control on the left. One row replaces three.
3. At ≤ 720px the Categories card becomes a horizontal chip row (W2-4); at
   ≤ 600px it becomes a drawer behind a filter button in the control row.
4. Re-measure with `probe.js`'s chrome stack at 1440, 1024, 390 and put all six
   numbers (before and after, each width) in the commit message.

**Acceptance.**
- `probe.js` `chrome.firstItemTop / chrome.viewportH` ≤ 0.25 at 1440, 1024, 390.
- `measure2.js` `geometry.entriesInViewport` ≥ 12 at 1440 and ≥ 4 at 390.
- Every control that was on screen before is still reachable — assert by id, not
  by eye: a Playwright test that opens the "⋯" popover and finds each moved id.
- `document.documentElement.scrollWidth === window.innerWidth` still holds at
  all three widths (it does today; this must not break it).

**Risks.** Hiding controls behind an overflow popover is how a feature becomes
undiscoverable — the acceptance test above is the guard, and the popover must be
labelled "Filters", not "⋯" alone. Second: `#notes-subtabs` is load-bearing —
ARCHITECTURE §10 invariant 1 says anything focusing or scrolling inside a Notes
section must call `showNotesSection(...)` first, and that has caused the same
bug four times. Do not change the section-switching contract while moving its
buttons.

## Brief 3 — W4-1: the error contract (PLAN B3)

**Context and goal.** 209 `HTTPException(` sites in `src/`, and **no
`@app.exception_handler` registered anywhere** — verified this session by
reading `api/app.py` end to end and by a live request, which returns FastAPI's
default `{"detail": "..."}`. Goal: every failure carries `{code, detail, hint,
ref}` and the UI renders `hint` where the action failed.

**Files.** new `src/memorymap/core/errors.py`, `src/memorymap/api/app.py`
(register the handlers), every `routes_*.py` (incrementally), `frontend/app.js`
`api()` (`:292`), new `tests/test_error_contract.py`.

**Steps.**
1. `core/errors.py`: an `AppError(code, detail, hint=None, status=400)` and a
   `to_response()` producing `{"code", "detail", "hint", "ref"}`. `ref` is a
   uuid4 hex, logged with the traceback.
2. Register three handlers in `create_app`: `AppError`, `HTTPException` (wrap
   the existing detail into the shape with `code` derived from the status), and
   `Exception` (500 `{"code": "internal", "ref": …}` with the traceback logged
   under that ref and **never** in the body).
3. `frontend/app.js` `api()`: parse the shape, throw an error object carrying
   `code`/`hint`/`ref`, and give the toast/inline renderer a `hint` slot.
4. Convert raise sites opportunistically — the handlers make every existing
   `HTTPException` conform without touching it, so this is not a 209-site edit.
   Convert the ones with a genuinely useful hint first: uploads (415), unlock
   (401/429), space delete, model unreachable.
5. Add `tests/test_error_contract.py`: walk `app.routes`, call each with
   deliberately invalid input, assert the JSON has all four keys and that a
   forced unhandled exception returns `code: "internal"` with no traceback in
   the body.

**Acceptance.**
- `tests/test_error_contract.py` green over all 267 route decorators.
- A route that raises `ZeroDivisionError` returns 500 with `{"code","ref"}`, no
  traceback in the body, and the traceback in the log under the same ref.
- The UI shows `hint` under the control that failed for at least the four
  converted cases.

**Risks.** A global `Exception` handler can swallow a `StreamingResponse` error
mid-stream and turn a broken stream into a 200 with a truncated body. Mitigation:
exclude `text/event-stream` and `application/x-ndjson` responses explicitly —
the GZip middleware in `app.py` already establishes that pattern and the exact
content types.

## Brief 4 — W1-3: glass as shell furniture, with an O(1) invariant

**Context and goal.** Measured with 40 seeded notes: Library has **44**
`backdrop-filter` layers and **129** `box-shadow`s; Dashboard has **27** and 32;
Graph has 4 with **1 nested**. HANDOVER records the previous session bringing the
range to 4–13 with zero nested on six of seven tabs. The counts on Library and
Dashboard are per-card, so they grow with the notebook — which is the actual
defect, not the absolute number. Goal: ≤ 13 blurred layers per tab **and** a
count that does not change with row count.

**Files.** `frontend/css/00-tokens-shell.css`,
`frontend/css/03-dashboard-widgets.css`, `frontend/css/07-whiteboard-misc.css`,
`frontend/library.js` (the card renderers), `docs/DESIGN.md` § Glass.

**Steps.**
1. Run `measure2.js` against a 10-note fixture and a 200-note fixture and diff
   the `glass.blurred` counts per tab. Every tab whose number moves has glass on
   a repeated element — that is the list to fix, and it is shorter than 44.
2. Remove `backdrop-filter` from every repeated element (library cards, widgets,
   list rows) and replace it with `--surface-2` tone, per UI plan Phase 3.3.
3. Find and remove the one nested blur on Graph — a blurred element inside a
   blurred ancestor is a second full filter pass for no visual gain.
4. Add the rule to DESIGN.md § Glass in one sentence: *glass is shell furniture;
   its count must not depend on how much content is on screen.*
5. Re-run both fixtures; put the four numbers in the commit.

**Acceptance.**
- `glass.blurred` ≤ 13 on all seven tabs at 1440.
- `glass.blurred` is **identical** between the 10-note and 200-note fixtures on
  all seven tabs.
- `glass.nested` is 0 on all seven tabs.
- Sampled with `scratchpad/pngpixel.py`: no surface that lost its blur dropped
  below 4.5:1 contrast against the text on it.

**Risks.** Removing a blur changes a surface's effective background, and this
project has already shipped one bug where a 96%-opaque tier read as ghost text
over dense content. The pngpixel bullet is not optional.

## Brief 5 — W2-3: the note card's actions stop covering its text on touch

**Context and goal.** Measured with `overlap.js`: at 390 × 844 with a touch
context, four buttons on the first note card — *Add to Favourites*, *Copy this
note's text*, *Edit this entry*, *More actions* — have `opacity: 1` and overlap
the card's own text box by 650, 650, 650 and 464 px², and `elementFromPoint` in
the middle of each overlap returns the button. At 1440 × 900 with a mouse the
overlap is **zero**. This is a new finding, in no existing plan, and invisible
to a desktop screenshot.

**Files.** `frontend/css/02-chat-graph.css` (the `.entry-item` action cluster),
`frontend/app.js` `entryItem`.

**Steps.**
1. Find the rule that reveals the action cluster under `@media (hover: none)` /
   `(pointer: coarse)` — the cluster is absolutely positioned and only its
   opacity changes, which is the whole bug.
2. Under coarse pointers, take the cluster out of the absolute position and give
   it its own flex row below the text, above the meta line.
3. Re-run `overlap.js` at both viewports.

**Acceptance.**
- `overlap.json` `w390_touch.overlapping` is `[]`.
- `w1440_mouse.overlapping` is still `[]` (nothing regressed on desktop).
- The card's height at 390px does not grow by more than one `--control-h`.

**Risks.** Low. The one thing to check is that the actions are still keyboard-
reachable in the new order — a Playwright tab-walk assertion over the card.

## Brief 6 — W8-1: the audit scripts become the e2e suite

**Context and goal.** 2,838 Python test functions guard the backend;
**3** Playwright tests in one spec guard 47,220 lines of JavaScript. Every UI
regression in this project's recorded history was found by a person. The four
scripts written this session already measure the right things; they just live in
a scratchpad.

**Files.** `tests-e2e/specs/` (new specs), `tests-e2e/playwright.config.js`
(projects for 1440, 1024, 390), `.github/workflows/ci.yml` (already runs
Playwright, so this is specs not infrastructure), `scratchpad/audit/*.js` (the
source).

**Steps.**
1. Move `scratchpad/audit/lib.js`'s `boot`/`goTab` into `tests-e2e/lib.js`,
   keeping the two documented traps (`domcontentloaded` not `networkidle`; one
   password field in two modes).
2. Add three viewport projects to `playwright.config.js`.
3. Write four specs, each asserting a **ceiling** rather than an exact value so
   an improvement never fails the build: `errors.spec.js` (0 page errors and 0
   console errors on all seven tabs), `overflow.spec.js`
   (`scrollWidth === innerWidth` on all seven), `chrome.spec.js`
   (`firstItemTop / innerHeight` under a ceiling that Brief 2 lowers), and
   `signatures.spec.js` (distinct button signatures under a ceiling that W1-2
   lowers).
4. Seed the fixture through `window.api` exactly as `measure2.js` does, so the
   fixture is created the way the UI creates it.

**Acceptance.**
- CI runs 7 tabs × 3 widths × 4 assertions = 84 assertions, green.
- Each ceiling is a named constant with a comment saying which brief lowers it.
- The suite runs in under three minutes (it is four page loads, not 84).

**Risks.** A flaky e2e suite is worse than none. Mitigations: no `networkidle`
anywhere; ceilings not exact values; and the seeded fixture built through the
app's own API so it cannot drift from the schema.

## Brief 7 — W5-4: `ai/scheduler.py`, one gate in front of every model call

**Context and goal (reasoned — no local model ran here).** Model work starts in
22 different places (`grep -rn "threading.Thread(" src/memorymap/`): the
janitor, the librarian, captioning, vision OCR, page reads, embeddings,
tensions, the autonomous loop, the skill runner, model pulls, the re-index.
There is no global concurrency limit, so two background jobs and a chat turn can
contend for one GPU; no shared budget; and no single place a Stop could cancel
from — which is why PLAN A5's Stop cannot currently be implemented.

**Files.** new `src/memorymap/ai/scheduler.py`, `src/memorymap/ai/provider.py`
(the call sites it wraps), `core/jobs.py` from W4-2, `routes_models.py`
(surface the queue), Settings › Tasks.

**Steps.**
1. `scheduler.submit(kind, priority, fn, budget)` returning a handle with
   `cancel()`. One worker by default, configurable; a `PRIORITY` ordering where
   an interactive chat turn preempts background work.
2. Route every call that currently reaches `Provider.chat`/`chat_stream`/
   `chat_tools` from a background thread through `submit`. Leave `/chat/stream`
   itself synchronous on the request thread — it is the one interactive path and
   it already streams.
3. Give each submission a wall-clock and token budget from Settings, defaulting
   generously; a budget breach cancels and records `failed` with a reason.
4. Wire Stop: the chat Stop cancels the handle; `ollama_client` gets the abort
   (Ollama supports it) and the partial write is rolled back through the
   existing undo stack.
5. Surface depth and the running item in Settings › Tasks, on top of W4-2's
   jobs table.

**Acceptance (what can be tested here, and what cannot).**
- Testable in this sandbox against the fake transport: two submissions with
  concurrency 1 never overlap; a cancelled submission's `fn` observes
  cancellation within 200 ms; a budget breach records `failed` with a reason; an
  interactive submission jumps a queued background one.
- **Not testable here:** that Stop actually aborts a real Ollama generation, and
  that preemption produces a felt latency improvement. Both need a real local
  model and must be recorded in HANDOVER as unverified until someone has one.

**Risks.** A scheduler in front of everything is a new single point of failure.
Mitigation: it must degrade to "run it inline" if the worker is not running,
and that fallback needs its own test — this is exactly CLAUDE.md's "features
that never ran once" shape, and the guard is a test that asserts the fallback
path executes, not that it exists.

## Brief 8 — W1-4: the three 18.4px switches, and making DESIGN.md true

**Context and goal.** `docs/DESIGN.md` § "Hit targets" names
`#semantic-search-toggle`, `#library-semantic-toggle` and
`#library-show-binned` as the **32×18** violations that `--target-min: 1.75rem`
was introduced to fix. Measured this session at both 1440 and 390: all three are
**32 × 18.4**, `opacity: 1`, `pointer-events: auto`, and `elementFromPoint` at
their centre returns the control itself. Their `label` wrapper is 142.2 × 30.4,
so the effective target does clear 24px and 28px — the switch you aim at does
not.

**Files.** `frontend/css/01-forms-settings.css` (the switch rule and its
by-name exceptions), `docs/DESIGN.md` § Hit targets.

**Steps.**
1. Give the switch a `min-height: var(--target-min)` with the visual pill drawn
   inside it, rather than exempting the input by name.
2. Re-run `probe.js` and confirm all three report `box.h ≥ 28`.
3. Edit DESIGN.md's list: either the three ids come off it, or the section says
   plainly that the label carries the target and the switch does not — but it
   must stop reading as though the switch were fixed.
4. Add the check to W8-2's static lint so it cannot silently regress.

**Acceptance.**
- `probe.js` reports `h ≥ 28` for all three at 1440 and 390.
- No other control's height changed (re-run `measure2.js`'s tap buckets and diff
  `under28` per tab — it should fall by exactly 3 and nothing else).
- DESIGN.md's Hit-targets section matches the measurement.

**Risks.** The switch rule is shared; raising its box can push a dense settings
row taller. The second acceptance bullet is what catches that, and it is a diff
of a number rather than a look at a screenshot.

---

# 7. Risk, moat and metrics

## 7.1 The top risks, and how to de-risk each

| # | Risk | Why it is real here | De-risk |
| --- | --- | --- | --- |
| R1 | **The ES-module refactor breaks the app in a way no test sees** | 765 globals, 635 listeners, and the two existing lints only catch duplicate ids and duplicate listeners | Do Brief 6 **first**. Move one builder per commit, run the 84-assertion e2e suite on each. If the suite is not in CI, the refactor does not start |
| R2 | **A UI phase is "done" on a screenshot** | Recorded four times in this repo, including one round that closed a real bug as "a capture artifact" and was wrong | Every acceptance criterion in §6 is a number from a named script. No brief closes on a look |
| R3 | **The AI reform ships unverified** | No local model in the sandbox; W5-1/W5-2's acceptance is behavioural | Split each row into "testable against the fake transport" and "needs a real model", ship the first, and record the second in HANDOVER as unverified rather than as done. Brief 7 does this explicitly |
| R4 | **Rebuilding something that exists** | Five catches so far. This audit found three more: SQLite is already tuned (P5), FTS5 already exists for notes (B5), `/entries` is already paginated (B4) | Every workstream row above names its owner plan or says "already built". The rule stands: one `grep` before one line of code |
| R5 | **The jobs table becomes a second half-built spine** | 22 thread sites is a lot to migrate, and a half-migration is worse than none — two systems, one of them invisible | Migrate by *kind*, not by call site, and delete the old path in the same commit. A `grep` assertion in the test suite: no `threading.Thread` in `ai/` outside `scheduler.py` |
| R6 | **Mobile work lands before the design system settles** | W2's rows touch the same CSS as W1's | Sequenced: W1-1 gates everything, and the phone pass is in **Next**, not **Now**, for exactly this reason |
| R7 | **Scope. This document lists ~40 initiatives** | The user's usage is finite and a session that ends mid-phase leaves nothing | One pushed, green commit per row, with the before/after number in the message. That is already this project's rule; §6's briefs are each sized to one sitting |

## 7.2 The moat, in three strategies

1. **Verifiability as architecture, not as a feature.** Sources on every answer,
   `unsupported_claims` checking what was said against what ran, the audit log,
   context accounting, and — once W7-5 lands — a privacy receipt generated from
   the code. A cloud competitor cannot show you rows it does not hold; a local
   competitor would have to build all six. Deepen it by rule: **every new AI
   feature ships with visible reasoning, an undo and a log, or it does not
   ship.**
2. **Structure you would lose by leaving.** Typed links, threads, boards,
   entities, saved views, provenance chips. Export keeps the promise that the
   notes are genuinely yours; the *structure* is what makes leaving
   unattractive. That is the only ethical version of lock-in, and it stays
   ethical only while the export stays honest.
3. **Community authority through a published benchmark.** "Which local model is
   actually good at answering over your own notes, measured" — PLAN A6's eval
   harness pointed outward. It is the only growth loop available to an app with
   no accounts, no sharing and no telemetry, and ANALYSIS §114 already costs it
   at a weekend. This audit adds one thing: the benchmark should publish the
   **abstention rate** alongside accuracy, because "knows when it doesn't know"
   is this product's actual claim.

## 7.3 Metrics — north star and phase KPIs, with no telemetry

**The rule, which is not negotiable and comes from ANALYSIS §114:** nothing is
transmitted, ever. Every number below is one of three things — public GitHub
data, a number the app shows *its own user* and never sends, or a bench run by
hand.

**North star: time-to-first-cited-answer over your own notes.** Download →
install → first grounded answer with sources, timed by hand with five people. It
is the one number that captures the whole product, it needs no telemetry, and
today it includes "install Ollama, pull a model", which is why the model-included
first run scores as the highest-leverage unbuilt thing in ANALYSIS §114.

| Phase | Local (user-visible only, never sent) | Repo / CI (observable) | Bench (run by hand) |
| --- | --- | --- | --- |
| **Now** | Idle requests/min shown in Settings › About (14 → ≤ 4); notebook health panel exists | e2e assertions in CI: 3 → ≥ 84; button signatures per tab: 22 max → ≤ 4; chrome ratio: 0.76 max → ≤ 0.25 | Five-person session: can they get a cited answer in 10 minutes? |
| **Next** | Job queue depth and model p50/p95 in Settings › Tasks; days-with-a-capture | Issue mix shifting from "how do I" to "can it also"; zero bare 500s in `test_error_contract` | Recall@10 on a fixture query set; a five-step skill on a 4B model — completed steps and named-contract failures |
| **Later** | Index freshness and embedded %; backup verified date; the privacy receipt's "last fired" column | Release downloads ÷ install-failure issues; external PRs after the benchmark page | Render time at 10k notes; abstention rate per model |

**Two anti-metrics, stated so nobody adds them.** Daily active users and
session length are unmeasurable here and would be *bad* if they were measurable
— a notebook that keeps you in it longer is a worse notebook. The honest
substitutes are in the table: time-to-value, and whether the notes you asked
about were the notes it cited.

---

# Start tomorrow

Seven actions, highest leverage first. Every one of them ends in a number.

1. **Fold `scratchpad/audit/*.js` into `tests-e2e/` and turn on the three
   viewport projects (Brief 6).** Nothing else on this list is safe without it,
   and it is the difference between 3 browser assertions and 84. Half a session.
2. **Do PLAN P1 with the baseline this audit produced: 14 → ≤ 4 requests in 60s
   idle (Brief 1).** The number now exists, so the gate is checkable the moment
   the change lands. Half a session, and the whole app gets quieter.
3. **Register the three exception handlers (Brief 3).** There are none today, so
   this is greenfield: every one of the 209 raise sites conforms without being
   touched, and "Request failed" stops being the app's most common sentence.
4. **Collapse the Notes chrome stack (Brief 2).** 252 / 354 / 640 px of chrome
   before the first note is the loudest measurement in this document, and the
   76% one is what a phone user sees.
5. **Fix the four note-card action buttons that cover the note's own text on
   touch (Brief 5).** One hour, one CSS block, one re-run of `overlap.js`. A new
   bug, found by measurement, that no desktop screenshot could have shown.
6. **Raise the three 18.4px switches and then make DESIGN.md true (Brief 8).**
   Small, but a design document that names three ids as fixed when they are not
   is actively misleading the next session.
7. **Close `/openapi.json` and `/docs` behind the unlock gate.** 238 paths are
   served to anyone who reaches the port. One line, and it is the only security
   finding in this whole audit that is not already handled well.

**Do not start with:** the ES-module refactor, the one-file model, or anything
in the mindmap plan. All three are correct and all three want a net under them
that does not exist until item 1 is done.

---

## What this audit did not verify

Stated plainly, because CLAUDE.md's second standing instruction is that a
session which forgets this reports work as done when it was reasoned.

- **No local model ran.** Every claim in §2E, §1.7 and Brief 7 is read from the
  code, not observed. `chat_tools`/`chat_tools_stream` tool-call fragment
  parsing remains covered only by the fake transport, exactly as CLAUDE.md's
  standing caveat says.
- **Poll back-off when the tab is hidden was not tested** — §F2's 14 requests
  were counted with the tab in the foreground. That the timers do *not* back off
  is read from the code; it is not a measurement.
- **Focus trapping in dialogs was not tested** (§B5 gap 2). AUDIT E5 flagged it
  as inference; it still is.
- **Dark theme and non-default palettes were not measured.** Every number in
  §2 is the default light palette at `deviceScaleFactor: 1`.
- **The fixture was 40 notes.** The 10k-note claims in §D3, §D4 and §F3 are
  reasoned from the query shapes and the recorded 1,501-note timing in
  `app.js:7093`, not measured at scale.
- **Contrast was not sampled.** No colour claim is made anywhere in this
  document for that reason; Brief 4's acceptance requires `pngpixel.py` before
  any glass is removed.
- **Settings, the whiteboard, the documents editor and the OCR workspace were
  not swept.** The seven top-level tabs were. Settings alone holds 17 sections
  and REDESIGN §R7.5 records that it "has never been measured"; that is still
  true of everything except the parts HANDOVER's last session touched.
