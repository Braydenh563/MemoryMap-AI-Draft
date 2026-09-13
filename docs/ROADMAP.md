# MemoryMap AI — work plan

The live priority list, restructured. §1–§38's full narrative (every reported
bug, every "decided against," every dead end) has been condensed into
[roadmap/HISTORY.md](roadmap/HISTORY.md) rather than kept here — this file is
now *only* what's still open, ranked by what it unlocks. Section numbers in
code comments and tests still resolve via HISTORY.md's index.

**The standing caveat:** every provider test runs against a fake transport —
tool-call parsing is implemented from the spec, not verified against a
running server. Plain SSE streaming *is* now verified against a real socket
(a stand-in OpenAI-`/v1` server, not real LM Studio/vLLM/llama.cpp or real
inference) — see CLAUDE.md's standing caveat for what that covered. UI claims
are checkable (Chromium is in the sandbox); model *behaviour* claims mostly
are not — reproduce or say plainly you couldn't.

## The plan documents, in one list (read this before opening any of them)

Fifteen files grew under `docs/roadmap/` across six sessions. Only six are
plans to work from; the rest are reference or superseded, and each of those
now says so in its first line.

| Work from these (in this order) | What it covers |
| --- | --- |
| [roadmap/WORLD_CLASS_PLAN.md](roadmap/WORLD_CLASS_PLAN.md) | The week and the quarter, the consistency contract, the flaw classes. **Start here.** How far each plan is: the table at the top of HANDOVER.md. |
| [roadmap/SESSION_BRIEFS.md](roadmap/SESSION_BRIEFS.md) | One complete brief per session of the week, with the operating protocol for smaller models. **Take one brief and start.** |
| [roadmap/INBOX.md](roadmap/INBOX.md) and [roadmap/SESSION_BRIEFS.md](roadmap/SESSION_BRIEFS.md) Brief 18 | The owner's open reports with owners and decisions, and the complete open scope in working order (2026-09-09). |
| [roadmap/UI_MODERNISATION_PLAN.md](roadmap/UI_MODERNISATION_PLAN.md) | Phases 0 to 10 built; Phase 11 (the phone, done properly) open. |
| [roadmap/DOCUMENTS_PLAN.md](roadmap/DOCUMENTS_PLAN.md) | Phases 0, 1 and 2 built in full; Phases 3 to 8 open. |
| [roadmap/GRAPH_PLAN.md](roadmap/GRAPH_PLAN.md) | Phases 1 to 6 built; Phase 4 part two, 6b (minimap) and the local pane open. |
| [roadmap/MINDMAP_PLAN.md](roadmap/MINDMAP_PLAN.md) | Phases 1 to 5 and the previews built; §12 (Coggle-level controls, INBOX 93) open. |
| [roadmap/TIMELINE_PLAN.md](roadmap/TIMELINE_PLAN.md) | The line and table views rebuilt on one row model, Phases 1 to 4. |
| [roadmap/WHITEBOARD_PLAN.md](roadmap/WHITEBOARD_PLAN.md) | The tool rail, the context bar, export dialog, handles, keys; Phases 1 to 4. |
| [roadmap/CHAT_PLAN.md](roadmap/CHAT_PLAN.md) | Checkable answers, one composer, Ask unified, the popup agent, skills that finish; Phases 1 to 4. |
| [roadmap/AGENT_SKILLS_REFORM.md](roadmap/AGENT_SKILLS_REFORM.md) | Phase D (recovery) and the verifier in WORLD_CLASS_PLAN §4 B5. |

| Reference (look things up, do not start from) | |
| --- | --- |
| [roadmap/HANDOVER.md](roadmap/HANDOVER.md) | The current state only (under 600 lines by lint); the session record is HISTORY.md's "HANDOVER archive". |
| [roadmap/HISTORY.md](roadmap/HISTORY.md), [roadmap/BACKLOG.md](roadmap/BACKLOG.md), [roadmap/ANALYSIS.md](roadmap/ANALYSIS.md), [roadmap/MODERNISATION_AUDIT.md](roadmap/MODERNISATION_AUDIT.md) | What is built, the standing backlog, the judgements and competitor reads, the measured audit. |
| [roadmap/PLAN.md](roadmap/PLAN.md), [roadmap/AUDIT.md](roadmap/AUDIT.md), [roadmap/REDESIGN.md](roadmap/REDESIGN.md), [roadmap/FABLE_BRIEF.md](roadmap/FABLE_BRIEF.md) | Superseded; kept only because code comments cite their sections. |

## ► NEXT SESSION (Fable): read this block, then the five plans, in this order

The user's own framing: *"I want it to proceed with the laid out plans in
plan.md and ui_modernisation_plan.md along with anything else in the top
priority of the handover and roadmap."*

**The reading order, before any code:**
1. [CLAUDE.md](../CLAUDE.md) — the traps, the sandbox recipe, the standing caveat.
2. [roadmap/HANDOVER.md](roadmap/HANDOVER.md) — the last session first; what was
   measured, what could not be reproduced, what is half-done.
3. [roadmap/UI_MODERNISATION_PLAN.md](roadmap/UI_MODERNISATION_PLAN.md) — phases
   0-7. **Phase 0 first**: the sweep tooling and acceptance gates, or every
   later phase is unmeasurable.
4. [roadmap/PLAN.md](roadmap/PLAN.md) — the professional-grade plan (whiteboard,
   documents, backend, agent harness, performance) in ship order.
5. [roadmap/AGENT_SKILLS_REFORM.md](roadmap/AGENT_SKILLS_REFORM.md) — phases A-D.
6. [roadmap/MINDMAP_PLAN.md](roadmap/MINDMAP_PLAN.md) — **first pass, to be
   extended and refined by Fable, not executed verbatim.** Its §2 records what
   already exists (a board is already an `Entry`); its §4 asks for a scope call
   before anything is built.
7. [DESIGN.md](DESIGN.md) and [ARCHITECTURE.md](ARCHITECTURE.md) as reference.
8. [roadmap/MODERNISATION_AUDIT.md](roadmap/MODERNISATION_AUDIT.md) — the full
   application audit with the numbers behind it (boot 864ms, 14 idle requests a
   minute, 22 button recipes on Chat, 76% chrome on a phone), a 90-day roadmap
   and eight execution briefs. It **cross-links these plans rather than
   repeating them**, and its §D6 lists three things they still describe as
   missing that are already built.

**The order of work.** Each item is a session or less; each ends green and
pushed.

| | Work | Why here |
| --- | --- | --- |
| 1 | **UI Phase 0** — sweep tooling, `tests/test_ui_signatures.py`, the screenshot set | Nothing after this is measurable without it |
| 2 | **UI Phases 1-2** — mass and layout, then component consistency by *count* | The largest visible change; the user's standing complaint |
| 3 | **Skills reform Phases A-B** — step contracts, small-model mode | The app's AI is unusable on a 4B model today; this is the functional half of "feels unprofessional" |
| 4 | **UI Phase 3-4** — type/colour/glass restraint, placement and motion | Finishes the look; cheap once 1-2 are done |
| 5 | **Skills reform Phase C** — the run as a collapsible object; verify tool calls in chat | Also closes the agent-activity report |
| 6 | **UI Phase 7** — document lightbox, note-editor gutters, document captioning, region OCR, the Files row | This round's leftovers |
| 7 | **UI Phases 5-6** — per-surface passes, designed states and copy | Long tail |
| 8 | **Mindmaps** — refine [MINDMAP_PLAN.md](roadmap/MINDMAP_PLAN.md), make the §4 scope call, then Phases 1-3 | The user's stated vision; needs 1-2 done first so it is built on a settled design system |
| 9 | **PLAN.md's remaining tracks** — backend hardening, performance, packaging | Least user-visible, most durable |
| 10 | **UI Phase 8 — the dock grammar** ([roadmap/UI_MODERNISATION_PLAN.md](roadmap/UI_MODERNISATION_PLAN.md) Phase 8): every tab's and sub-tab's control dock onto one zone order, one height, one primary action, with a lint | By direct instruction after the plans above: "features there and not intentionally designed" |
| 11 | **UI Phase 9 — responsive by device** (Phase 9): iPad landscape/portrait and iPhone as stated breakpoints, touch targets, bottom docks above the keyboard | Same instruction |
| 12 | **[roadmap/DOCUMENTS_PLAN.md](roadmap/DOCUMENTS_PLAN.md)** — the documents editor reimagined: Phase 0 (click an underline, see suggestions) first, then chrome, then the editing surface (§4's decision: CodeMirror 6, vendored), blocks, connections, review, export | The largest single gap left; §4's decision has to be made before code |
| 13 | **[roadmap/GRAPH_PLAN.md](roadmap/GRAPH_PLAN.md)** — the graph redesigned front and back: a canvas renderer with the simulation in a worker, physical drag, degree sizing, zoom-level labels, colour rules and groups, a full-tab space, lasso → actions, a local-graph pane | By direct instruction; the graph is the surface furthest from the second-brain references the user named |

**Status after the Fable session** (each line is measured and pushed on
PR #144; the numbers are in the commit messages and in
[roadmap/HANDOVER.md](roadmap/HANDOVER.md)):

| | Status |
| --- | --- |
| 1 UI Phase 0 | **Done.** `tests/test_ui_signatures.py`, `scratchpad/ui-sweeps/*`, the screenshot set. |
| 2 UI Phases 1-2 | **Done.** Row gaps 5 → 3, buttons on the ramp, one popover shell, one radius. |
| 3 Skills reform A-B | **Done** (fake transport only — the real-model acceptance in AGENT_SKILLS_REFORM.md is still open). |
| 4 UI Phases 3-4 | **Done.** Glass 28 → 4 layers on the Dashboard, one focus ring, no hover lifts. |
| 5 Skills reform C | **Done.** The run as a list; tool chips verified on all three chat paths against the stand-in server. |
| 6 UI Phase 7 | 7.2 (gutters) done; lightbox/captioning/region OCR/Files row in review from a subagent branch. |
| 7 UI Phases 5-6 | Settings, reminders, whiteboard bar, editor chrome, sub-tabs, phone width (Settings 10/10 sections fit, Notes toolbar 172 → 80px, first note 445 → 345), every empty state has an action. Open: a phone pass on Library/Graph/Whiteboard/Documents, a dark-theme pixel pass, the copy pass. |
| 8 Mindmaps | Scope call made (option B); Phases 1 and 2 done and swept (35/35); Phase 3 in flight; Phases 4-5 open — see [roadmap/BACKLOG.md §116](roadmap/BACKLOG.md). |
| 9 PLAN.md tracks | Sprint 1 done (P1, P2 was already there, P5, B3, P6); B9 done; D1/D5 done; W5/W6-part were already built; D2/D3 and A1/A2/A6 in flight. Open: the rest of §1-§4 — listed in [roadmap/BACKLOG.md §116](roadmap/BACKLOG.md). |

**Standing rules for all of it** (from CLAUDE.md, learned expensively):
measure → change → re-measure, with the number in the commit message; check the
running app before building anything; say plainly what you could not verify; one
pushed, green commit per item.

## ► TOP PRIORITY, by direct instruction: modernise and professionalise the UI

The full dev plan — causes, phases, per-family targets, acceptance counts and
the order of work — is **[roadmap/UI_MODERNISATION_PLAN.md](roadmap/UI_MODERNISATION_PLAN.md)**.
Start there. The sweep scripts it relies on are in `scratchpad/ui-sweeps/`.
The instruction, verbatim:

> fix instances like this where there are hard rectangle box background
> colours behind rows. and there are still a lot of inconsistencies in ui
> style, sizing, alignment, positioning, spacing, gaps, margins, colour, style
> aesthetic etc. also sometimes when oeping dropdown menus or panels like for
> tooltips or in the formatting toolbars, the panels will flicker somewhere
> else on the screen then appear in the right place. now that you have done
> the structure fix. I need you to do a consistency fix, and also adjust the
> larger mass spacing and panels for the app. it needs to be professional and
> usable, not overly performative. the aesthetic needs to fit, not just be a
> crude imitation of modern aesthetics. I need you to modernise the ui.

"the application still feels fake, vibe coded and not ready for professional
use. some things feel performative and not at professional standards in the
ui and ux." Done so far (HANDOVER.md, "This session"): surface tiers and the
border budget, the button ramp, one eyebrow, seg semantics, one card radius,
one shell gutter, the Files tick, toolbar menus hidden until placed, the
Contents strip. Everything else in the plan is open.

## ► TOP PRIORITY, second half: the agent and skills reform

**[roadmap/AGENT_SKILLS_REFORM.md](roadmap/AGENT_SKILLS_REFORM.md)** — the
other thing asked for in the same breath as the UI: "the way skills work is
waaayyy too strict on smaller models ... the models often dont even properly
complete a step before they are prompted for the next step. its an absolute
mess. the whole system needs a reform." Four phases: a step gets a
machine-checkable contract and is re-prompted rather than skipped; a
small-model mode that offers one tool per step; the run as a collapsible
object instead of a text dump; and recovery from a stalled step.

## ► START HERE: the redesign is the priority

A full UX/architecture re-imagining was asked for and is written up in
**[roadmap/REDESIGN.md](roadmap/REDESIGN.md)** — measured evidence for every
complaint, the three underlying causes, the target shape, a complete ledger
of all forty requests with their state (§R8), and the numbers as they stand
(§R9). **Read it before doing any UI, file-handling, graph or backend work.**

**Read the top of [roadmap/HANDOVER.md](roadmap/HANDOVER.md) first — it is
ahead of this file.** Its own top section is the whiteboard priority below,
by direct instruction. Under that: the v0.2.0 round, the two defect shapes
behind nearly every visual bug reported, what is done, and fifteen open
items all top priority by instruction. It still carries the reversal worth
knowing before any file work — PDFs and documents must be viewable,
downloadable and manageable **without any AI model in the loop** — and the
note that anything editor- or slash-command-shaped starts from
`frontend/editor.js`, which has a "/" menu.

**The next session's order of work, highest value first.** Each links to the
section that holds the quoted request and the detail:

| | Work | Why it is first |
| --- | --- | --- |
| P | **The professional-grade plan** — whiteboard, documents, backend, agent harness, performance; scoped, measured, in ship order. [roadmap/PLAN.md](roadmap/PLAN.md), with the professional audit behind it in [roadmap/AUDIT.md](roadmap/AUDIT.md). Written by direct instruction as the follow-on to row 0. | Read it before starting any whiteboard, documents or backend work. |
| 0 | **The whiteboard's panels and controls, in full — moved here by direct instruction, ahead of everything below.** Full narrative in [roadmap/HANDOVER.md](roadmap/HANDOVER.md)'s own top section. | Two asks: (a) the layout/structure/distribution/positioning redesign this row already named as the open half of item 7 below — panels reported clashing with each other and the canvas; (b) new, specific: while the **Pan** tool is active, clicking (or double-clicking — pick one deliberately) directly on a card/sketch/shape should switch to **Selection** and select it, instead of requiring a manual tool switch first. Not built yet — logged here first, per this file's own standing rule. |
| 0c | **Graph Trace: multiple paths between two nodes, coloured and switchable** ([roadmap/HANDOVER.md](roadmap/HANDOVER.md), "logged, not built" §1). | Reported live. `GET /graph/path` returns one BFS shortest path today; this needs a k-shortest/all-simple-paths search server-side and a path switcher plus per-path colour in `graph.js`'s Trace panel. Scope the cap on N before building — unbounded all-paths search can blow up on a densely-linked notebook. |
| 4 | **The pane-based shell** ([§R7.5](roadmap/REDESIGN.md), [§R8.3](roadmap/REDESIGN.md)) | Every remaining UI complaint is downstream of seven screens that each own the whole window. Its acceptance criterion is the distinct-left-edge count in [DESIGN.md](DESIGN.md) — re-baseline it on a fixed fixture first, per §R9. |
| 5 | **Cross-linking: the `@` picker** ([§R7.3](roadmap/REDESIGN.md)) | Link direction landed; **the Connections block is now built** (`GET /entries/{id}/connections` and `/documents/{id}/connections`, the dialog off both ⋯ menus, `tests/test_connections_block.py`) — it groups links by direction and adds the documents, boards and files each thing is joined to, none of which were surfaced anywhere. What is left of this row is the one universal `@` picker. **§R7.3 item 3 (typed collapsible blocks) is now built too** — `> [!note]-` and `> [!note]+` render as a `<details>`, with a "Collapsible section" slash command; a plain `> [!note]` is unchanged, so old notes are unaffected exactly as that item required. |
| 7 | **Settings, and the whiteboard's panel layout** ([§R7.5](roadmap/REDESIGN.md)) | Settings has never been measured. Panel control sizes are unified; the layout rethink is now row 0 above, promoted by direct instruction. |
| 9 | **The backend list** ([§R7.7](roadmap/REDESIGN.md)) | Not urgent. Includes the answer to "should it be async" — measured, and it is **no**; the reasoning is there so nobody redoes it. |

**Two standing rules from that work**, both learned the expensive way this
session:

- **Measure, change, re-measure.** Every claim in REDESIGN.md has a number
  behind it. A change that does not move one of §R1's numbers is decoration.
- **A load-time path behind a condition needs a test that meets the
  condition.** A crash that hung the app on its loading screen passed
  `node --check`, passed every cold-boot test, and needed exactly one thing
  to reproduce: an unsaved draft in the capture box. See
  `tests/test_frontend_load_order.py`.

## What is open right now (older list — the top section supersedes it)

**The overnight round is in [roadmap/HANDOVER.md](roadmap/HANDOVER.md)'s first
section — read it before this list.** Built there, do not rebuild: document OCR
through the workspace (PDFs rasterised page by page, plus a per-page vision
read), the chat header/sources/message redesign, Notion block handles in the
documents live view, `agent_activity_notices`, and typed values in the advanced
response settings. Still open from it: concept-map learnability. **Built since:
the whiteboard rethink and more dashboard widgets** — HISTORY.md §103.

Six sessions of finished narrative used to sit above this line. It has moved
to [roadmap/HISTORY.md](roadmap/HISTORY.md)'s "§80 to §86" index, because a
live work plan should open with what is *live* — and because this file has a
2,000-line ceiling that `tests/test_docs_layout.py` enforces, and narrating
completed work at the top is how it got there.

**Before starting anything below, read
[roadmap/HISTORY.md](roadmap/HISTORY.md).** Four sessions have now rebuilt
something that already existed, and the two most recent near-misses were both
caught by one grep: the Reminders calendar view (listed as a gap, already
built and wired) and the graph's own non-visual keyboard layer. A grep miss
and a real gap look identical from the outside.

**Start at item 0** in the live list below — the editor rewrite, just
reprioritized to the top. Then [§89](#89--reported-this-session-not-yet-built-start-here-next)
(pagination, a large chat-file-upload redesign, both logged not built) and
[§90](#90--reported-this-session-the-appjs-splits-live-verification-pass-not-yet-built)
(a Settings overlap bug, now fixed; a small-screen/tablet audit, not yet
touched). §88.3, the `app.js` split, is **done**; §88.4 stays **skipped**,
by direct instruction. §88.0 lists what was already fixed — check first.

**A fifteen-ask report plus a second round of ideas landed together — all of
it, with its audit verdicts and a located handoff list, is [§87](#87--the-connected-notebook-pass-the-editor-layer-and-everything-reported-with-it)
below. Five of those fifteen were already built; §87.1 says which, and where.**

### The live list

Everything genuinely open, ranked. **Reprioritized to the top, by direct
instruction, ahead of the numbered items below.**

~~0. **A hybrid live-rendering document editor.**~~ **Built (§93/§94).**
   Full narrative: HISTORY.md §100.

**The new top of the list is item A below (llama.cpp), by direct
instruction.** See BACKLOG.md's "§95 — the forward list" for the full
brainstorm this was drawn from.

**What §94 left undone, in priority order.** Written at the end of that
session so nothing depends on remembering the conversation. Each says *why* it
was not done, because "not done" and "decided against" are different facts.

~~B. **Backup retention is not a setting.**~~ **Built.** Full narrative: HISTORY.md §100.

~~C. **Restart after installing a package, and from Settings → About.**~~
   **The About-page half is built.** `POST /system/restart` is the second
   caller of `restart_in_console_mode` the console-mode switch already used —
   same mechanism, current console visibility preserved rather than flipped
   — behind a "Restart MemoryMap" button in Settings → About, shown only
   once `desktopShell()` confirms there is anything to restart into. **Not
   yet done: wiring it to the Extras install-completion flow specifically**
   (the confirm dialog still just says "needs a restart afterwards" with no
   button appearing once that install actually finishes) — real remaining
   scope, since that means hooking the restart offer into whatever the
   Extras panel polls for a finished install, not reused here.

~~D. **Notes do not render markdown.**~~ **Partly built, and the rest is
   staying out on purpose.** A later session already gave notes real inline
   markdown — bold, italic, code spans, links, images, strikethrough, LaTeX
   (`renderInlineMarkdown`, wired into the note-card list via
   `renderNoteText`) — specifically fixing "notes show raw `**text**`".
   Full block-level markdown (headings, lists, tables, fenced code, the
   `renderMarkdown` chat/documents/digest use) is deliberately still out: a
   note-card list rendered that way "gets very tall very fast," which the
   comment above `renderInlineMarkdown` calls out as the worse problem. Code
   highlighting and mermaid rendering are still genuinely missing everywhere
   (`grep mermaid frontend/` is empty) — that part of BACKLOG §96's "finish
   the rendering story" is still open, just not the notes half.

E. **`app.js` is 22,000 lines.** The clean first extraction is `chat.js`
   (~3,300 contiguous lines: ask, the chat tab, image attachment, the agent
   timeline, the dock disclosure), following the §88.3 pattern that already
   produced documents.js, library.js, dashboard.js and settings.js. Deferred
   because it is a refactor with real regression risk and no user-visible
   gain, and there were functional requests outstanding.

F. **Three things this environment cannot verify**, all needing a real
   Windows/desktop run:
   - `scripts/splash.ps1` renders (Linux sandbox, no PowerShell). Its
     progress bar was reported empty and fixed blind — a WinForms
     ProgressBar drops the themed renderer, and with it the Marquee
     animation, the moment ForeColor or BackColor is set.
   - The four `ocr` suggested models as actual `ollama pull` targets. The
     repos and file sizes were checked against the live Hugging Face Hub;
     nobody has run the pull.
   - Printing to PDF from the document editor's Read mode.

G. **The whiteboard's own refinement pass**, beyond the panel-collision fix.
   **The efficiency half turned out already done, checked before assuming
   the "never audited" claim still held**: every drag handler read (sketch,
   resize, card) already mutates the DOM directly during a drag instead of
   calling `wbScheduleRender()`/a full `renderWhiteboard()` per frame — and
   the card handler carries its own comment recording a *prior* live
   report ("glitchy and slow to update") that was root-caused to exactly
   that shape and already fixed. `wbScheduleRender` itself batches to one
   paint per frame regardless, checked "across all 48 sites" per its own
   comment. Feature gaps are the part still genuinely open — no code-
   reading answers that, and none was invented here.

~~A. **First-class llama.cpp support.**~~ **Steps 1–2 built.** Step 1
   ("say so" in `core/extras.py`) turned out already done, found stale in
   this file rather than in the code. Step 2: `OpenAICompatClient` now
   probes `llama-server`'s own `/props` (`_fetch_props`/`is_llama_cpp`,
   `ai/openai_client.py`) as a fallback context-length source, ranked
   between the per-model catalogue entry and the guess-from-name table —
   plain llama.cpp reports neither `loaded_context_length` nor
   `max_context_length` on `/v1/models`, so this is a real number in place
   of a guess. 2 new tests (`test_providers.py`). **Step 3 (in-process
   `llama-cpp-python`) stays explicitly not done** — the wheel-matrix cost
   this item's own §97 narrative (HANDOVER.md) weighed against it still
   holds, and nothing changed it.
Items 1–2, below, are the ones with real substance after that.

~~1. **Vision-capable models could not be shown an image.**~~ **Built.**
   Composer attachment, vision-model selection and captioning. Full
   narrative in HISTORY.md; kept here as a number so §-references still
   resolve.

~~2. **Notes-tab pagination with page-aware note links.**~~ **Built, both
   halves.** `#notes-page-size`/`#notes-pagination` (BACKLOG §77 item 1);
   `resolveNotePage()`/`flashEntry` now land a wiki-link click on the
   *page* its target is on, not just scroll a page that might not contain
   it. Full build note, the design question's answer, and live thread-
   child verification in BACKLOG §77 item 2.

~~3. **The Timeline's line view needs a real visual pass**~~ — the vague half
   ("very professional and ready for public use") is still unscoped, say
   what specifically next time it's reported; **§87.6's own concrete design
   is now built**: "Thread" joins Category/Tag/None as a `group` value
   (`GET /timeline?group=thread`, `routes_timeline._thread_bands`) — one
   lane per root note and everything that continues it via `Entry.parent_id`,
   the branch-and-tributary shape IDEAS.md asked for and the grid view could
   never show at all. A parent outside the loaded date window becomes its
   own root rather than a second query reaching further back (same
   simplification the `days` filter already asks the rest of the view to
   accept); a note with no children folds into one shared "Single notes &
   smaller threads" lane rather than spending a lane on every lone note, the
   same long-tail folding category/tag bands already use. No frontend
   changes needed beyond the new dropdown option — `renderTimelineBranch`
   already rendered whatever bands the backend sent. 2 new backend tests.
   **Live-verified in Chromium**: seeded a real 4-note thread plus one lone
   note via the real API, selected Line view → Thread — the thread's own
   lane drew a spine-branching line through all 4 dots, the lone note
   correctly landed in the shared lane, zero console errors. The grid
   view's text-cropping half is done; a re-report after that fix was never
   reproduced in this sandbox's Chromium and needs the actual browser/OS it
   happens on.

4. **The Documents editor is behind the rest of the app** (BACKLOG §64) —
   the item's own text already said "not scoped in detail here," and §87.1's
   audit found it **stronger than this claim**: autosave, outline, find/
   replace, preview, AI edit, extract-to-notes, and md/PDF export all
   already exist. Live-checked again this session (created a document,
   opened the editor, zero console errors) rather than left as an
   assumption — nothing concretely broken surfaced, and per this file's own
   rule ("say what specifically, next time it's reported"), no speculative
   redesign was invented to fill the gap. **That specific complaint has now
   arrived** — "chucked together basic editor with poor usability and tool
   usage... windows and panes get squished together" — see item 0 at the
   top of the live list, which is where it is now scoped.
   ~~`GET /documents` has no search parameter~~ **Built**: `?q=` matches
   title *and* content (`Document.title.ilike | Document.content.ilike`),
   mirroring a filter `ai/tools/documents.py`'s `_list_documents` already
   had for the AI — the gap was only ever that a person couldn't reach it.
   The Library's Documents search box now sends it server-side instead of
   filtering titles client-side (all it could do — `_summary()` never sent
   a document's body to the browser at all). 5 new tests
   (`test_documents_api.py`).
   ~~The whiteboard's `aria-label` coverage lags the Graph's~~ **Already
   fixed, reconfirmed live rather than trusted**: §87.7b's "40 form
   controls… all now carry a name… zero remaining" claim was checked
   directly this session with a fresh DOM sweep of both the whiteboard
   landing view and an open canvas (85 interactive controls total) — one
   false positive (`#wb-snap-toggle`, a checkbox whose accessible name comes
   from its wrapping `<label>`'s visible text, invisible to a naive
   textContent-on-the-input check) and nothing else. The claim holds.

5. **Claim-specificity in the hallucination net.** `agent.unsupported_claims`
   catches a claim with *no* matching write ("I tagged it" when nothing was)
   but not one that mismatches what happened ("I tagged it as Work" when a
   different tag was applied). Needs real model output to tune against, which
   this sandbox cannot provide.

~~6. **Guided first-run tour**, and the rest of onboarding.~~ **Built.**
   Full narrative: HISTORY.md §100.

~~7. **Alembic migrations.**~~ **Built.** Full narrative: HISTORY.md §100.

8. **What happens when Ollama hangs, rather than errors.** Checked this
   session, not fixed — closer to already-handled than the item implies.
   `OllamaClient.__init__` already sets a 600s request timeout with a
   documented reason (a cold model load on CPU-only hardware can genuinely
   take that long), and every chat/generate call wraps the underlying
   `requests` exception into `OllamaError(f"Chat with '{model}' failed:
   {exc}")`, which `routes_chat.py` already catches. So a hang is bounded and
   does produce a real, if unpolished, message — not silence. What's
   **unverified**, because this sandbox has no reachable Ollama to actually
   hang: whether that message reaches the chat UI as something a user reads
   as "it gave up and here's why" versus a raw exception string, and whether
   ten minutes of a spinner before that message *feels* like "an unbounded
   spinner" regardless of the technical bound. Needs a real slow-loading
   model to observe, not more source reading.

~~9. **Crash-safe recovery for an interrupted re-index or model download.**~~
   **Checked directly — already safe by construction.** Full narrative,
   including the one cosmetic gap left open (no `taskhistory` record for a
   hard crash mid-reindex): HISTORY.md §100.

10. **macOS release packaging.** Linux is done; macOS is not.

10a. **faster-whisper will not install, and nobody has yet seen the real
    error.** Reported twice from a live Windows session, the second time with
    a screenshot: the Background-tasks card says "pip exited with code 1. The
    log above says why" and there is no pip output above it. A fix landed to
    route `core/extras.py`'s install output through Python `logging` (so
    `logbuffer.py` can see it and Settings → Logs can show it), because pip's
    captured output never went through `logging` and was therefore invisible
    on the Logs page. **That fix has never been confirmed to surface anything**
    — no session has captured the real Settings → Logs output from a live
    failure since. Next step is not a code change: it is one run on the
    machine that fails, searching the Logs page for `memorymap.extras`, and
    pasting what it says. Everything before that is guessing, and two sessions
    have already guessed.

~~11. **Sorting and grouping saved chats.**~~ **Built.** Full narrative,
    including the corrected "model is not stored per turn" premise:
    HISTORY.md §100.

~~12. **The Documents Library sub-tab needs a full visual redesign.**~~ **Built.** Full narrative: HISTORY.md §100.

~~13. **Back/forward navigation still misses most navigation types.**~~ **Built, all four cases.** Library's sub-tabs (§88.1 item 7), saved chat
    conversations (`openConversation`/`newChatConversation` recording a
    `{tab: "chat", section}` entry, restored by `stepTabHistory` — the
    session that built this also had to make `stepTabHistory` `async` and
    `await` that branch specifically, since `openConversation` calls
    `recordTabVisit` itself only *after* an `await apiJson(...)`, and an
    un-awaited restore let the `finally` clear `tabHistory.navigating` too
    early, turning every Back/Forward through a saved chat into a spurious
    new entry). **Documents and Graph focus mode turned out to be already
    built too** — found by grep before being re-built, not assumed:
    `documents.js:349` and `graph.js:2702` already call `recordTabVisit`
    (`doc:<id>` / `focus:<id>`), and `stepTabHistory` already restores
    both. Live-verified rather than trusted, since a call site existing is
    not the same claim as it working: opened a document, switched to
    Dashboard, pressed Back — the Documents tab reopened with the right
    title loaded. Separately, entered Graph focus mode on a note, switched
    to Dashboard, pressed Back — the Graph tab reopened with the same
    note's focus mode active and "Clear focus" visible. Zero console
    errors either check.

### Smaller, and genuinely cheap

- **`ai/tools/__init__.py` is still ~3,360 lines** — the `TOOLS` registry plus
  most note-CRUD and agent orchestration. Left deliberately when the other
  four modules were extracted; it is the most interleaved part of the file and
  needs its own session.
~~- **`manager.all_tags()` has no cap**, unlike every sibling section of the
  same responses.~~ **Built.** `routes_library.py`'s `_tags()` now slices
  to `PER_KIND_LIMIT` like every other kind section there; already most-
  used-first, so the slice keeps the tags worth finding by. `GET /tags`
  (the Tag Manager itself) stays uncapped on purpose — its job is renaming
  or deleting *any* tag. 2 new tests.
- **Mirroring ordinary toasts into the notifications panel** — the other half
  of the mute feature. Every `toast()` call site needs a `kind` first, or the
  panel floods with routine "Saved." noise.
- **A `prefers-reduced-motion` audit of the remaining meaningful animations**,
  and a screen-reader pass over the dynamic regions that announce nothing
  (BACKLOG §19; the focus-trap and tap-target halves are now done).
~~- **Colour-contrast verification against WCAG AA**~~ **Measured, live, for
  the first time.** A Playwright script walked every visible text node on the
  Dashboard and the Settings modal (light mode, glass on — the default),
  composited each element's effective background up the ancestor chain
  (handling translucent glass surfaces), and computed WCAG contrast ratios.
  Two apparent 1:1 "white on white" hits (a digest button, Settings'
  "Connect" button) were **false positives in the audit script itself**, not
  real bugs: both use `background-color: oklab(...)` — a real solid indigo
  fill — and the script's regex-based colour parser only understood
  `rgb()`/`rgba()`, so it silently treated `oklab()` as "no background" and
  fell through to a white default. Real remaining findings, after that fix,
  are marginal: the brand indigo (`rgb(79,109,245)`) on white or on its own
  light-indigo chip background lands at 3.64–4.34:1 against a 4.5:1 target at
  small sizes (12–12.8px) — a wordmark ("MemoryMap AI", exempt under WCAG
  1.4.3's own logotype carve-out), a status chip, and a category chip.
  Nothing found reads as actually hard to read; the misses are all within
  ~0.2–0.9 of the threshold, not the kind of failure a person notices without
  a tool. **Not exhaustive** — the audit didn't check dark mode (a naive
  `data-theme` attribute set didn't actually flip the app's real theme
  machinery, so those results were identical to light mode and discarded)
  and doesn't account for elements hidden behind an open modal being walked
  anyway. Fixing the marginal misses means darkening the one shared accent
  colour used everywhere as this app's brand indigo — real blast radius for
  a ~0.2–0.9 ratio gap nobody has reported noticing; leave it unless a
  specific instance is flagged.

### New this session, not yet scoped

- **The Library grid and the Notes list now share `renderIncrementally`, and
  the Timeline and log console deliberately do not.** The Timeline is a CSS
  grid whose cell order *is* its layout; the log console is already capped and
  its follow mode needs the newest rows, which an from-the-top renderer would
  never paint. Both decisions are commented at the call site. If a third list
  ever wants windowing, check which shape it is first.
- **33 CSS selectors look orphaned to a naive sweep and are not** — they are
  built by template (`heat-${n}`, `library-${kind}`, `priority-${p}`,
  `result-reason-${r}`, `plan-step-${s}`, `outline-h${n}`, `graph-edge-${k}`).
  Three genuinely dead rules were removed in §86. Anyone re-running that sweep
  should expect the same 33 false positives rather than deleting them.
- **`GET /entries?semantic=true` is now called from two places** (the Notes
  tab and the Library). If a third appears, the fetch-and-cache shape in
  `refreshLibrarySemantic` is the one to extract.

## §88 — the live-report backlog, the Kortex/Eden read, and the app.js split

**This section is the next session's work queue, in order.** §88.1 is what was
reported and is still open; §88.2 is the competitor read the user asked for;
§88.3 is the app.js split, which is the priority *after* §88.1 and §88.2 are
done; §88.4 is the context/memory/harness analysis.

Everything here was reported live in one long session. What was fixed in that
same session is in §88.0 so nobody re-fixes it.

### 88.0 Fixed already — do not re-fix

| Report | Cause |
| --- | --- |
| *(38 older rows moved out)* | The oldest entries of this table were condensed into [roadmap/HISTORY.md](roadmap/HISTORY.md) to keep this file under its own length rule (`tests/test_docs_layout.py`). Nothing was lost — the rule exists because a roadmap nobody finishes reading is a roadmap that gets rebuilt |

### 88.1 Reported and still open — work this list top-down

**Tier A — broken behaviour.**

~~1. **"The AI randomly fails in the Ask sub-tab saying it isn't available."**~~
   **A real, evidenced cause found and fixed — not the utility-model theory.**
   `/models/status` used to probe Ollama *twice* per poll: `is_running()`
   (2s timeout) and, inside `_installed_models()`, `list_models()` (5s
   timeout) — both hitting Ollama's own `/api/tags`. Sequentially that is up
   to 7s for one poll, and `refreshModelStatus()` (`app.js`) aborts that exact
   call at a hard 5s. A backend that is genuinely up but momentarily slow
   (mid-generation, a cold model load) could lose that race and read as
   unavailable — which matches the "signal timed out" log line from the same
   report exactly. `routes_models.py`'s `status()` now makes one round-trip
   instead of two (`list_models()` alone tells you both whether Ollama is up
   and what's installed), and the frontend's abort moved to 8s — real
   headroom above the new, lower worst case instead of racing it at the wire.
   **Not verified against a real slow-loading model** (no reachable Ollama in
   this sandbox) — the mismatch itself was confirmed by reading both sides of
   the timeout, not by reproducing the hang. The utility-model theory in the
   original report may still be worth checking if this doesn't fully explain
   a future recurrence.
~~2. **`Unhandled promise rejection: TypeError: Cannot read properties of null
   (reading 'replace')`.**~~ **Fixed** — see §88.0's row; it was
   `recentSkills` carrying a poisoned `null` entry from before §88.0's
   `startSkill` fix, read unguarded on every dashboard render.
~~3. **The notebook constellation canvas keeps disappearing.**~~ **Fixed a
   second, real trigger.** ARCHITECTURE §10's canvas-measures-zero pattern
   was already handled for theme changes (`refreshArtForTheme`); what wasn't
   handled at all was the canvas's own **size** going stale — the sketch had
   no resize handling whatsoever, so `holder.clientWidth` was measured once
   at setup and never re-synced. Added a `ResizeObserver` on the holder
   (not just `p.windowResized`, which alone would miss the Edit-layout
   "Wide" toggle — a card-width change with no window resize event at all).
   Verified live: a window resize, the Wide toggle, and a tab-away-and-back
   cycle all keep the canvas correctly sized and visible, zero console
   errors in any case.
4. **The new-chat button disappeared from the Ask tab.** Traced, not fixed:
   it only shows after a real (non-"hint") answer completes
   (`show("retry-btn", ..., "new-chat-btn")` in `app.js`), and the show logic
   itself is correct — no bug found in it. Most likely the same root cause as
   item 1 above (a hint/unavailable response never reaches that line), which
   this sandbox cannot confirm without a reachable model. If re-reported
   *with* a working AI connection, that would rule this theory out.
5. **The AI Skills sub-tab "is just very unfinished and nothing really
   works."** Audited directly, verified live in Chromium (`library-view-skills`,
   19 skills loaded, zero console errors) rather than trusted from the report.
   The vague complaint does **not** hold up as stated — most of the sub-tab is
   real:
   - **Run Skill** — works. Prompts for inputs when the skill has any, runs it
     in chat.
   - **+ New Skill** — works. Opens Settings → Skills with a blank, focused
     form (deliberately reuses that editor rather than growing a second one).
   - **Skill Logs sidebar** — works, filters the audit log for skill/agent
     actions; correctly shows "No skill execution logs found" on a fresh
     profile.
   - **Autonomous Workers toggle, Auto-tag, Auto-link** — real, wired to
     `setPreference`, not decorative.
   - **Edit / Delete a custom skill** — real, but **only reachable from
     Settings → Skills**, not from a card on this sub-tab. Deliberate (one
     editor, not two) but easy to read as "missing" from this tab alone —
     worth a card-level Edit/Delete shortcut if this gets revisited.
   - **Schedule** — the one genuinely broken piece: a literal placeholder
     (`toast("Scheduler functionality coming soon!")`). This is the same
     surface as the Kortex/Eden "automation pipelines" item (§88.2 item 8) —
     build there, not as a one-off button, so it doesn't get built twice.
~~6. **The graph is slow and janky to move around.**~~ **Profiled, not
   guessed at — two real causes found and fixed, one deeper cost left open.**
   120 seeded notes/40 links, Chromium's CDP `Performance` metrics, pan and
   node drag measured *separately*, and — because this sandbox's VM is fast
   enough to hide real jank — re-measured under `Emulation.setCPUThrottlingRate`
   6× as the standard proxy for lower-end hardware:
   - **Native `:hover` churn during a pan.** `graphIsPanning` already muted
     the *application's* hover logic, but the browser's own `:hover`
     pseudo-class still matches every node the cursor physically sweeps under
     mid-drag, re-triggering `.graph-core`/`.graph-halo`'s CSS transitions —
     invisible to any JS mute because it's browser-level, not app-level.
     Fixed: `canvas.classed("graph-panning", true)` in the same zoom
     `start`/`end` handlers, `.graph-panning .graph-node { pointer-events:
     none }` in CSS. Node drags are unaffected — their own `mousedown`
     already calls `stopPropagation()` before the zoom behaviour's `start`
     ever fires. recalc-style time during a pan dropped measurably
     (unthrottled: 85.7ms → 72.8ms over a fixed gesture).
   - **The much bigger cause: panning or dragging *while the force
     simulation is still cooling*.** Measured directly, 6× throttle: the
     same pan gesture cost **80% main-thread busy** while the simulation was
     still hot (`alpha` ≈ 0.87) versus **57%** after it had settled
     (`alpha` < 0.001) — confirmed by tracking `graphSimulation.alpha()`
     directly over time, not assumed. The tick handler updates every
     node/edge/label position on every tick (~60/sec while running), which
     directly competes with whatever the user is doing — and default decay
     (0.0228) takes ~300 ticks, which under real throttling stretched cooling
     past 15 seconds. That squarely covers "pan right after the graph opens,"
     the single most likely first action a user takes. Fixed:
     `.alphaDecay(0.05)` on the simulation — cools in ~10s instead of ~15–18s
     under the same throttle. This does **not** change where the layout
     settles (the forces decide that, not the decay rate), only how many
     ticks it takes to get there — verified with a screenshot: 120 notes,
     same well-spread layout, nothing broken.
   - **What's still open, and why it wasn't attempted here**: even fully
     cooled, a pan still cost 51–57% main-thread busy under 6× throttle —
     real SVG hit-testing/paint cost over 120+ nodes that neither fix above
     touches. The deeper fix is the tick handler's own O(n) full-graph DOM
     update, the same shape the whiteboard's `wbScheduleRender()` fixed for
     its 49 call sites (HISTORY, this file's own precedent) — skipping
     label/cluster updates on alternate ticks, or a dirty-flag partial
     update, is the next step if this is reported again after these two
     fixes ship. Not attempted this session: it's a structural change to a
     hot path, not a profiling-guided small fix, and deserves the same
     "don't guess, measure first" treatment on its own.
   - All existing graph/frontend tests, `ruff check`, and `node --check
     graph.js` stay green; verified live in Chromium (screenshot, zero
     console errors) both before and after.

**Tier B — UI/UX, each concrete.**

~~7. **Back/forward across the Library's own sub-tabs.**~~ **Built.** The
   click handler (`whiteboard.js`) now calls the same `recordTabVisit("library",
   targetId)` Notes' sub-tabs use; `stepTabHistory` (`app.js`) restores by
   clicking the matching sub-tab button rather than duplicating its
   section-show/whiteboard-landing/gallery-render logic. A bare `{tab:
   "library"}` entry (recorded when the tab itself opens, before any sub-tab
   click) falls back to "All" rather than leaving a stale sub-view on screen.
   Verified live: Whiteboards → back → Documents → back → All → forward →
   Documents, in order.
~~8. **The Documents Library sub-tab needs a visual redesign.**~~ **Built** —
   see the live-list's own item 12, which has the full root cause and fix.
~~9. **The Whiteboards Library sub-tab is bland**~~ **Built** — search, sort
   and a Cards/Rows switch on the Library's one shared view preference. Same pass: Contents rebuilt as a real index (sticky sections, filter, jump bar,
   folding, by-month grouping) and the three-pane OCR workspace — HANDOVER.md's
   third batch has both, and what Tesseract's absence here left unverified.
10. **The graph dock may get too tall and squish the graph.** Now three
    deliberate rows; if it grows again, the answer is an overflow menu rather
    than a fourth row.
12. **The minimap needs a visual and usability upgrade.** Checked before
    touching it — it already has more than the vague ask implies: dots are
    coloured by category (`node.colour`, matching the main graph), clicking
    it re-centres the main view there (`initGraphMinimap`'s `jump`
    handler), and the viewport frame is clamped to the box with a comment
    recording the specific "201×39 inside a 168×112 box" edge case that fix
    covers. What looked plain in a screenshot this session was the test
    data (every note "Uncategorised", so every dot is one colour), not a
    gap in the mechanism. Left alone rather than making speculative
    cosmetic changes with no concrete complaint to act on — "say what
    specifically, next time it's reported" is this file's own rule for
    exactly this shape of ask.
~~13. **Graph node labels show raw callout syntax** (`Review > [!tip] Remem…`).~~
    **Fixed** — `routes_graph.py`'s `_preview()` now strips a callout's
    opening line the same way it already strips a `#` heading.
~~17. **Timeline line view redesign.**~~ **Built** — see the live list's item 3
    above for the full build note and live verification.
~~18. **Semantic search ignores time words** ("recents").~~ **Already
    built — checked before building, found done.** `search/query.py`'s
    `understand()` parses "recently"/"recent" (and "yesterday", "last week",
    "three days ago", "on tuesday", …) into a date range with a `soft` flag,
    and `search_manager._retrieve` uses it: a soft range sorts matches
    newest-first as a tiebreak rather than excluding anything outside a
    fixed window (the code's own comments record "jokes I have saved
    recently" — this exact phrase — as the motivating case that was fixed).
    Verified live rather than trusting the comments: two notes containing
    "jokes", one 3 days old and one 200 days old, given the query "jokes I
    have saved recently" — the 3-day note ranked first. Whoever re-reported
    this hit a real gap somewhere, but it isn't the mechanism itself; likely
    either a phrasing the parser's patterns don't cover, or the chat path
    specifically (`routes_chat.py`) not passing something query.py needs —
    worth asking what exact phrase was typed, next time.

**Tier C — the big editor feature, worth its own session.**

19. **A hybrid live-rendering document editor — moved to item 0 at the top of
    this list.** Asked for precisely: "a mix between the straight md editor
    and the rendered version where it renders as the user finishes typing…
    if you click on the line or the section it will unrender until
    unselected, in which it will rerender" (the Obsidian Live Preview /
    Typora model), and joined this session by a second, separate complaint
    about the current editor's usability and cramped panes. Full scoping —
    why this is not a small change, and the recommended per-block-editor
    path — is at item 0, not duplicated here.

### 88.2 Kortex / Eden — what is worth taking, and what is not

Two analyses were supplied. Eden is Kortex's successor and is a **cloud,
social-media** product; the user's instruction is explicit: *"make sure to keep
everything local, I don't want the cloud stuff."* So the social corpus, the
multi-platform scheduler, the creator index and the affiliate system are all
**out** — not because they are bad, but because they are the half of Eden that
cannot exist in a local-first notebook.

**Already built here — do not "add" these:** an MCP server
(`src/memorymap/mcp_server.py`), markdown export, a document/notes split, AI
synthesis over the notebook, saved prompts (skills), audio (read-aloud), and a
web reader with highlight capture.

**Worth taking, ranked by value per unit of effort:**

~~1. **Boards hold *references*, never copies.**~~ **Already built —
   checked directly, not assumed missing, and this section's own framing
   was stale.** `WhiteboardNode.entry_id` is a plain foreign key, never a
   content copy, and `POST /whiteboard/nodes`' own dedup check is scoped to
   `(entry_id, board_id)` together — not `entry_id` alone — specifically so
   the same note can sit on several boards at once. Verified end to end,
   not just read: the same note added to two different boards produces two
   independent rows; deleting the reference on one board leaves the other
   board's reference and the note itself completely untouched. New
   regression test, `test_the_same_note_can_be_referenced_from_two_boards_
   at_once` (`test_whiteboard.py`) — the two existing whiteboard tests
   nearby cover *moving* a card between boards and *deduping* two drops on
   the *same* board, neither of which exercises two simultaneous
   references, which is the actual claim this item made. This is still the
   honest answer to the open **note clusters** ask (§87.3) — a cluster is a
   board of these references — but there is nothing left to build for the
   reference mechanism itself; what remains, if this is picked up again, is
   UI for a person to *find* a note's other boards from one of them (the
   data already supports the query, nothing surfaces it).
2. **Drag from an item's connection dot onto empty canvas to spawn a chat
   already connected to it.** The whiteboard already has real anchor points and
   AI actions; this joins them into one gesture and is the single most
   compelling interaction in either product. **Scoped this session, not
   built** — real design, not a placeholder: `graph.js`'s connection-dot drag
   already exists for *linking two notes*; the new gesture is the same
   pointer-down-on-a-dot-and-drag start, but releasing over *empty* canvas
   (not another node) instead spawns a floating "start a chat about this"
   affordance at the drop point, and accepting it calls `switchTab("chat")`
   → `newChatConversation()` with that note pre-attached, exactly the
   existing `attachedNoteIds`/`note_ids` mechanism the composer's own note
   picker already populates — no new backend concept, only a new whiteboard
   gesture and its drop-target UI. The real risk is disambiguating this drag
   from the *existing* drag-to-link-another-node gesture and from an
   ordinary pan, at the same anchor point — worth prototyping the hit-test
   before writing the spawn UI, not the other way around. Not attempted
   this session: a new pointer gesture on a canvas that already has pan,
   node-drag, and link-drag sharing the same surface is exactly the kind of
   change §87.7c's own rule ("profile before touching it") argues for
   doing deliberately, and the graph performance work earlier this session
   is a fresh reminder of how much is already happening on that surface.
3. **The pane system** — open anything in a side pane while writing, and keep
   research/chat visible beside the draft. The document editor already has a
   sidebar; this generalises it to "open *any* item in a pane". **Scoped, not
   built.** This is the largest of the four and touches the most surface:
   every full-screen "open X" flow in the app (a note, a document, a chat
   conversation, a whiteboard board) would need a second, pane-sized render
   path alongside its existing full-tab one, and the document editor's
   sidebar — the thing this item generalises — is itself deeply wired to
   `#doc-*` ids specific to the document editor, not a reusable component.
   The honest shape of this as a real project: (a) extract the document
   sidebar into a generic `openInPane(kind, id)` container first, proven on
   the one thing that already has a pane; (b) add exactly one more kind
   (the best-value pairing is a note or a chat beside a document, since
   "research/chat visible beside the draft" was the concrete ask); (c) only
   then consider generalising further. Attempting all of it at once, in the
   same session as five other features, is how a UI architecture change
   ships half-migrated — this needs its own session, deliberately, the same
   caution this file already applies to the hybrid live-rendering editor.
4. **Custom AI = instructions + chosen knowledge sources**, with **"use when"
   rules** so the assistant knows when to reach for a source. This is a direct
   upgrade to the existing skills/personas: today a skill is a prompt, and the
   gap is attaching a *bounded* knowledge set to it. Local equivalent of
   sources: selected notes, documents, boards and tags — never creators.
   **Scoped this session, and the good news found while scoping it: the hard
   half already exists.** `ChatRequest.attached_notes_only` + `note_ids`
   (`routes_chat.py`) is already the exact "a deliberately closed set of
   notes — retrieval finding more is pollution, not help" mechanism this
   item needs; it was built for Trace's "generate a story from this path"
   and never reused. The real remaining work is entirely on the skill side,
   not the retrieval side: add a `sources` field to a skill (`ai/skills.py`'s
   `normalise`/`SkillItem` in `routes_settings.py`) — a list of `{kind:
   "note"|"document"|"tag", id_or_name}` — and have `skill_runner.run_skill`
   resolve it to a concrete `note_ids` list at run start (a tag resolves to
   every note carrying it, at that moment, not a saved snapshot) and pass
   `attached_notes_only=True` alongside it. Documents aren't retrievable
   content today (`routes_documents.py`'s own docstring: documents "never
   appear in note search… unless the user asks for them by name") — a
   document *source* would need its content folded into the skill's prompt
   directly rather than routed through note retrieval, a smaller, separate
   piece. "Use when" rules are the one part with no existing mechanism at
   all: today a skill is picked by name or by `tools.focus_for`'s keyword
   cueing, never by matching a source's stated purpose — that half needs a
   real design decision (a short natural-language rule matched how, by
   whom) this session didn't make.
~~5. **The interview technique.**~~ **Built** — "Interview me about an idea"
   in `ai/skills.py`'s `BUILTIN_SKILLS`, using the existing `ask_user` tool
   for a real back-and-forth mid-run rather than a one-shot prompt.
6. **Reader-mode capture with citations preserved.** Partly built (the web
   reader); the missing half is that a highlight becomes its own first-class
   item with its source link intact.
~~6. **Reader-mode capture with citations preserved.**~~ **The missing half is
   now built.** "Source as metadata, not just folded into body text" —
   `Entry.source_url`/`source_title`, new additive columns, populated by
   `saveSelectionAsNote`'s existing "Save with its source" flow
   (`selectionSource`/`clippingMarkdown`, both unchanged) alongside the
   markdown blockquote+link it already wrote into the body — the body copy
   stays deliberately, so a note is still a plain, portable file with no app
   behind it. A note card now shows a real "🌐 source title" chip that opens
   the page, and the field is real API surface (`GET`/`POST /entries`), not
   something only recoverable by parsing markdown. 3 new tests
   (`test_api_entries.py`).

7. **Audio overview of a notebook/document**, generated locally with the
   existing read-aloud voices and saved as a file. **Scoped this session —
   the framing undersold the gap, and it's worth recording why rather than
   attempting a partial build.** "The existing read-aloud voices" are the
   browser's native `speechSynthesis` (Web Speech API) — real, but it only
   *plays live*; there is no standard browser API to capture that audio to
   a file, and this codebase has no server-side TTS engine at all (no
   pyttsx3, no Piper, nothing — confirmed by grep, not assumed). So this
   isn't "wire an existing capability to a save button," it's "add a new
   local TTS dependency," which is exactly the category of heavy install
   this project has burned time on before (CLAUDE.md's own standing torch/
   sentence-transformers warning). Two honest paths, neither attempted here:
   (a) a lightweight local TTS package (Piper is the most-cited
   CPU-friendly option, ONNX-based, no torch) generating a real audio file
   server-side, replacing `speechSynthesis` for this one feature only,
   evaluated for install cost the same way `core/ocr.py`'s Tesseract
   dependency was; (b) narrow the ask to "record what speechSynthesis
   already plays" via `MediaRecorder` capturing system/tab audio — fragile,
   permission-heavy, and browser-dependent, so a worse fit for a desktop
   app than (a). Recommend (a), sized and evaluated in its own session
   rather than guessed at here.
8. **Automation pipelines** — user-facing trigger→action rules. The autonomous
   agent already does four fixed jobs; this is the same machinery with a UI.
   **Checked, not built — the premise needed correcting first.** `ai/
   autonomous.py` is **one** scheduled pass on **one** fixed interval (default
   6 hours), not four distinct jobs with their own triggers — "four fixed
   jobs" describes what that single pass *does* each time it runs (filing,
   linking, tidy suggestions, digest), not four independently triggerable
   pipelines. A real trigger→action UI needs, at minimum: a rules table
   (trigger type, trigger config, action type, action config, enabled), a
   trigger *types* beyond "every N hours" (this app already has real event
   moments worth hooking — a note saved, a category assigned, a reminder
   fired), and a UI to build/list/toggle/delete rules — none of which exist
   today in any form. This is a genuinely new subsystem, not a UI layered
   on existing machinery as the item's own text implied; sizing it
   honestly is why it wasn't started this session.

**Explicitly not taken:** the social corpus and outlier detection, multi-platform
scheduling, auto-DM, creator-as-voice-clone, pooled team credits, affiliate
links. All require a cloud service and other people's data.

**On the UI/UX quality the user admired:** the concrete, copyable parts are
(a) keyboard-first navigation with visible shortcuts, (b) one primary loop
stated plainly — capture → discover → write, (c) panes instead of modal
context-switching, and (d) restraint: few controls visible at rest, more on
demand. This session's graph-toolbar work is (d); the pane system is (c).

### 88.3 The app.js split — done

Four files split out, verified live, narrative in
[HISTORY.md §88.3](roadmap/HISTORY.md#883--the-appjs-split-full-narrative-moved-from-roadmapmd-now-complete).

### 88.4 Context, memory and harness engineering — an analysis

Asked for directly. What exists, and where the real headroom is.

**What exists.** Retrieval is `search_manager.retrieve_detailed`
(`routes_chat.py`), gated by `ai/intent.py`'s `needs_retrieval` so a chat turn
that needs no notes does not pay for a search. The system prompt is budgeted
and **asserted** (`agent.PROSE_BUDGET_CHARS`) because every sentence is resent
each round. Conversations can be compressed (§35I). Tools are a fixed registry
in `ai/tools/`. There is a "what the AI remembers" surface (§39B).

**Corrected — items 1 and 2 below were already built by a prior session
(`search_manager.py`, commits `be53bd5`/`03b9a3e`/`a399926`), and this section
was never updated to say so. Checked directly, per this file's own rule.**

**What's actually still a gap, in order of value:**

5. **Tool retrieval is all-or-nothing.** Still genuinely open. Every tool
   definition is sent every round. §33 already scoped semantic tool
   retrieval and rightly said it needs measuring first — item 4's
   instrumentation is now in place to do that measuring.

**One caution that still applies to item 5, the one real gap left in this
section.** Every provider test in this repo runs against a fake transport,
and this sandbox has no reachable model. Retrieval *quality* changes cannot
be evaluated here at all. Use item 4's new instrumentation and a small
fixed question set *first*, or this becomes a change nobody can prove
helped.

## §89 — reported this session, not yet built

Landed live, in one long session, alongside the app.js split's first file
(documents.js — done, see §88.3) and a vision-chat redesign (also done: see
`routes_chat._image_caption_context` — a chat model with no vision of its
own now gets a caption from the resolved vision model folded into the
question, instead of the whole turn silently swapping to a different model).
**Several items below were asked for again after already being built the
same session — check `roadmap/HISTORY.md`'s own "§89's already built
callouts" entry before rebuilding anything that sounds finished.**

**Still open:**

~~1. **Pagination on other tabs.**~~ **Built, across all four surfaces**
   (Notes, Reminders' Done group, Library Documents, Library "All").
   Full narrative: HISTORY.md §100.

~~2. **Uploading a document (not an image) to the chat composer fails
   silently into the transcript.**~~ **Mostly already built by a later
   session and never checked off here; one real bug found and fixed —
   full audit in HISTORY.md §102.** Attached-document content never
   reached the model at all (a field the composer sent, the backend never
   read) — now fixed and tested. Still genuinely open: true staging
   (upload on send, not on pick — a real behavioural decision, not a
   bug), and attaching an already-uploaded Library document rather than
   importing a fresh one.

~~3. **Vision-model OCR, as an alternative (or complement) to Tesseract, with
   model-pull suggestions in Settings → Models.**~~ **Already built —
   this whole item, found stale in this file rather than in the code, per
   CLAUDE.md's own top rule.** `ai/vision_ocr.py` is exactly the per-image
   *choice* of extractor this item asked for: `vision_ocr_text`/
   `vision_ocr_and_store`/`vision_ocr_in_background` write to
   `MediaUpload.vision_ocr_text`/`vision_ocr_model`, a field distinct from
   Tesseract's own `ocr_text` — both are shown side by side in the lightbox
   ("Text read by {model}", `library.js`), and `POST` to the vision-OCR
   route (`routes_files.vision_ocr_media`) lets a person re-run or hand-edit
   the result per image, same write-once/background-trigger shape
   `caption_and_store` established. Settings → Models pulls its suggestions
   from `SUGGESTED_MODELS` (`ai/model_manager.py`) via `GET
   /models/suggested`, rendered by `app.js`'s `suggestedCatalog` loop
   (wired in `settings.js`) — a `"vision"` group (moondream up to
   qwen2.5vl:32b) and a separate `"ocr"` group specifically for document
   readers (GLM-OCR, PaddleOCR-VL, Qwen3-VL-4B, DeepSeek-OCR), each with a
   size and a purpose line. This also settles the exact question this item
   left open: `glm-ocr`/`deepseek-ocr` **are** real, checked-against-the-
   live-Hub tags (`hf.co/ggml-org/GLM-OCR-GGUF`/`hf.co/ggml-org/DeepSeek-OCR-GGUF`),
   not shorthand for the general vision models — the code comment above
   `SUGGESTED_MODELS["ocr"]` records that check explicitly, unlike the
   `"vision"` list's own entries, several of which are still marked
   "unconfirmed tag" for the same honest reason this item originally
   couldn't check either.

~~4. **A visual indicator on a chat message's own metadata line for which
   mode answered it.**~~ **Built.** `messageMetaLine()` (app.js) takes a new
   `usedTools` param and renders an "Ask"/"Agent" chip — same
   icon/label pair as `#chat-mode-seg` — positioned beside the model name.
   Read off the turn's own `effectiveUseTools` at send time, not the live
   toggle, so a conversation that spans mode switches shows what each past
   turn actually ran with. Persisted as a new `used_tools` bool on
   `TurnBody`/`_turn_messages` (routes_conversations.py) so it survives a
   reload; older saved turns simply have no key and render no chip, same as
   every other field this line already treats that way. 2 new tests
   (test_conversations_api.py). **Live-verified in Chromium**: two turns
   posted straight through `/conversations` with `used_tools: false`/`true`
   and real `stats`, reopened via `openConversation` — the metadata line
   read `850 ms · 5% · Ask · llama3.2` and `4.2s · 11% · Request ·
   llama3.2 · 1` respectively (the second chip says "Agent" since the
   INBOX 39 rename), chip text and position exactly as designed,
   zero console errors. No live Ollama was needed since the chip renders
   from saved-turn data, not a live stream.

~~5. **Images pasted, dragged, or dropped into the chat composer don't reach
   the vision-chat staging system at all.**~~ **Built** — the scoping fix,
   the safer of the two options this item's own diagnosis named: the global
   `drop`/`paste` listeners (app.js) matched **any** `<textarea>` by tag
   name alone, `#chat-input` included, routing it through `handleFileUpload`
   (built for the Notes/Document composer — inserts literal
   `![Uploading…]()` markdown into the textarea) instead of
   `attachImageFiles()`/`renderImageAttachments()`, the real card-token
   staging the composer's "＋" button already used. `#chat-input` is now
   excluded from both listeners and given its own branch: image files go
   through `attachImageFiles()`; a non-image file dropped/pasted there gets
   a toast ("only images... right now") instead of broken markdown, since
   real non-image chat uploads are item 2 below, not this fix. **Live
   Chromium verification**: dispatched a real `ClipboardEvent` with an image
   file at `#chat-input` — `attachedImages` populated with a real
   upload id/url, the input stayed empty (no markdown text landed in it),
   zero console errors. Also fixed alongside it, same root cause class: a
   failed upload in the Notes/Document composer (`handleFileUpload`'s own
   catch) used to leave `*(Failed to upload X)*` sitting in the note/document
   content — content is what gets saved, a toast is a notification, and the
   two were conflated the same way the chat composer's placeholder was.

~~6. **Captioning an image with a vision model should show in the background
   tasks list.**~~ **Built.** Same mechanism the item asked to reuse:
   `captioning.running_captions()` is a small in-memory dict (`upload_id` →
   filename) set around the actual `caption_text` model call inside
   `caption_and_store`, cleared in a `finally` so a raised exception can't
   leave a job stuck "running" forever. `routes_tasks.collect()` reads it
   and appends a `kind: "caption"` entry, same shape every other job there
   already has — the frontend's `renderTasks()` is fully data-driven, so no
   frontend change was needed at all. Not cancellable, same reasoning as the
   embedding warm-up already in this list: one blocking model call with
   nothing to check a flag between. 2 new tests (a mid-call spy in
   test_captioning.py, a `/tasks` shape check in test_tasks.py).

7. **The Documents editor's "AI edit" feature should become a more general
   AI assistant**, not just an in-place editor of existing text. Asked for
   directly: today it only edits/rewrites what's already on the page; the
   ask is for it to also write new content and remove content on request -
   closer to an agentic assistant for the document than a single "improve
   this selection" action. Not yet scoped - likely touches whatever
   `doc-ai-instruction`/the AI-edit route already is, but "write" and
   "remove" as first-class actions (as opposed to "replace selection with
   edited version") may need a different request/response shape than the
   current edit flow, so scope that before building rather than bolting new
   verbs onto the existing one.

8. **Lightbox prev/next arrow icons read as off-centre.** Reported with a
   screenshot. **Checked live this session, at last** (a real uploaded PNG,
   500×350 — earlier sessions had no image in this sandbox's test data to
   open a lightbox against at all): `.lightbox-prev`/`.lightbox-next`
   render at the correct left/right positions, and the `<i class="ph
   ph-caret-*">` icon element's own box is perfectly concentric with its
   button (measured via `getBoundingClientRect()`, offset 0,0 on both
   buttons) — `display: grid; place-items: center` is doing what its
   comment says. Cropped screenshots of both buttons at native size showed
   nothing visually off-centre to the eye either. **Not reproduced** — this
   report may be specific to the reporter's OS/browser font rendering of
   the vendored Phosphor glyphs, which this sandbox's Chromium can't
   speak to. One genuine, minor finding along the way, not the reported
   bug: with a **pathological 1×1 pixel test image**, the two buttons
   appeared to cross order (next rendered left of prev) — not investigated
   further, since a real uploaded photo is never 1×1 and this has nothing
   to do with the off-centre report. Leave both alone unless re-reported
   with the reporter's own OS/browser.

9. **Settings modal reads as poor contrast / hazy in light mode.** Reported
   with a screenshot; not reproduced. Audited the pipeline this bug class
   would live in (`APPEARANCE_DEFAULTS`/`applyAppearance()`, app.js — where
   the project's worst UI bug to date came from, an unguarded custom
   property computing to the literal string `"undefined"`/`"NaN"`): every
   key has a default, and a fresh profile's Settings modal in forced light
   mode plus glass on (user confirmed glass is on) renders correctly in
   this sandbox. The user's screenshots consistently show a custom teal
   accent, not the default indigo — likely specific to their own accent/
   glass-blur/opacity/shadow values. Need those values, or a live session.

~~10. **Images and sketches attached to a note don't render on the whiteboard
    canvas.**~~ **Built.** `nodeEnter.each` now renders a `.wb-card-thumb`
    above the note text, same priority as `libraryCard()` (library.js):
    `thumb_attachment_id`, then `thumb_url`, then the first image in
    `entry.attachments`. Inline `![...](...)` markdown in `entry.content`
    is deliberately untouched — already renders through `renderMarkdown`, and
    would show twice if this added it too. **Live-verified, not just a
    source-read**: real PNG attached via `POST /entries/{id}/files` — not
    `/media/upload` alone, which is the generic drag-into-markdown upload
    with no entry association and silently returned `attachments: []` —
    added to a board, opened in the browser: `<img>` loaded with real
    dimensions, auth via the query-param fallback, zero console errors.

10. **The sketch pad: a selection tool** — the one part of this item still
    open (the rest is in HISTORY.md, "Retired from the live files"). Clicking
    an existing stroke/shape to move, resize or delete it; today's tools only
    ever draw a new one. The pad is pure-raster (`ImageData` snapshots for
    undo, no discrete stroke objects), so this is an architecture change,
    not a patch — unlike the whiteboard's discrete-object select (item 11).
    The toolbar redesign comes after it, not before.
11. **Whether AI-driven work (image captioning, and AI features generally)
    should run asynchronously as a standing design principle**, not just
    get a background-tasks *indicator* (item 6 above, already logged - this
    is a broader question, not a duplicate of it). Raised as an open
    question, not scoped. `ai/captioning.caption_in_background` already
    demonstrates the shape for at least one feature (a background thread,
    fire-and-forget from the route); worth an actual audit of which AI
    calls in this app are still synchronous/blocking-the-request today
    (chat streaming already isn't, by its nature) before deciding whether
    this becomes a standing pattern applied elsewhere or stays per-feature.

~~12. **Whiteboard cut, and a right-click/long-press menu for a selection.**~~
    **Built.** `wbCutSelection()` is copy-then-delete, wired to Ctrl/Cmd+X
    beside the existing Ctrl/Cmd+C/V handlers. The context menu reuses
    `wbOpenDockedMenu`'s own reparent-to-`<body>`-and-position technique
    (this item's own diagnosis named it as the template) via a new
    `wbWireContextMenu(selection, kind)`, bound once per sketch/card/object
    on their `enter()` selection the same way `.on("click", ...)` already
    is. Right-click opens it immediately; touch gets a 500ms hold, same
    threshold as the toolbar toggle's own long-press, cancelled on
    release/move. Copy/Cut are omitted from the menu (not merely disabled)
    for a card or a multi-selection, both of which `wbCopySelection` already
    refuses — a menu offering two buttons guaranteed to fail is worse than
    one that only shows what the selection can do. A text object's own
    `contenteditable` body is excluded from both gestures so its native
    cut/copy/paste/spellcheck menu still works with the mouse.
    **Live-verified in Chromium** (desktop right-click; touch long-press
    was not exercised — Playwright's touch emulation wasn't set up this
    session): right-clicking a text object opens the menu with Copy/Cut/
    Delete at the pointer, clamped correctly; right-clicking a note card
    opens it with **Delete only**, confirming the card-exclusion guard;
    clicking outside closes it; the Delete button removes the object from
    the DOM; Ctrl+X removes a selected object (`.wb-object` count 5→4) and
    Ctrl+V restores it (back to 5). Zero console errors throughout.

## §90 — reported this session (the app.js split's live-verification pass), not yet built

~~1. **`#agent-monitor` overlaps two Settings nav buttons and eats their
   clicks.**~~ **Built.** Found live (Playwright, verifying the settings.js
   split): a real 30s click-timeout on "Help"/"About", intercepted by the
   floating `#agent-monitor` panel. More general than Settings alone —
   `.modal-overlay` sat at `z-index: 55`, far below the monitor's `1000`, so
   **every dialog in the app** was partly unclickable under it. Fixed:
   `.modal-overlay` → `z-index: 1010`, matching `.selection-popup`'s
   already-established tier for this exact shape (above the monitor, below
   the toast box's 1050). `#sketch-overlay`/`#improve-overlay` moved with
   it — both are pinned to `.modal-overlay`'s tier so a confirm dialog
   raised from inside either still stacks above it by DOM order, which
   would have broken had only `.modal-overlay` moved. Verified live: both
   buttons click cleanly now, zero console errors.

2. **Small-screen (tablet/phone) layout needs a real audit, not spot fixes.**
   **A real audit now exists — Dashboard and Library, both widths, screenshotted
   and zero console errors.** Tablet (820px): the tab bar fits on one row, the
   dashboard's "Start something"/"Jump to" cards flow into a clean responsive
   grid, and Library's dock plus its filter-chip row have room to spare — this
   already reads as "a professional app," not a squished desktop layout,
   which was the concrete worry behind this item. Phone (390px): also
   genuinely clean — Library's five sub-tabs wrap into two full-width rows
   rather than clipping, the dock stacks its title/New-document button/
   refresh sensibly, filter chips wrap without overlap. **The one real,
   already-diagnosed gap is the top tab bar specifically** (measured
   separately, see below) — not Library, not the dashboard. Chat, Graph, the
   whiteboard and the document editor at these widths are still unaudited;
   worth checking before assuming the same clean result holds everywhere.
   Asked for directly — "better handling and ui structure of smaller device
   sizes... potentially even a whole rearrangement." Audit `docs/DESIGN.md`'s
   breakpoints against phone (~390px) and tablet (~768-1024px) width, surface
   by surface: the 17-section Settings modal, the document editor (live-list
   item 0 — already "squished" at *desktop* width), the whiteboard, the
   dashboard's masonry grid. Measure before rebuilding.

   **The tab bar specifically — measured live at 390px, the "not confirmed
   either way" question from an earlier pass now answered.** The
   `tabs-wrapped` mechanism (`syncTabOverflowFade`, `app.js`) does correctly
   fire at phone width — the strip drops to its own full-width row rather
   than squeezing beside the wordmark — but even on its own row, seven tabs
   still don't fit a 364px-wide bar (`scrollWidth` 640 vs `clientWidth`
   364: Dashboard/Notes/Chat/Graph visible, Library/Timeline/Reminders need
   a scroll). The `fade-end` class and its `mask-image` **are** correctly
   applied (checked via `getComputedStyle`, not assumed) — the mechanism
   isn't broken. What a real screenshot at 390px shows is that a soft
   24px alpha fade over a busy glass background doesn't read as "scroll for
   more" next to a tab whose label is cut clean off mid-letter ("Librar|")
   — it reads as the tab bar being broken, which is exactly the ambiguity
   the prior pass flagged and couldn't settle without a browser. Not fixed
   here: the honest next step is a stronger affordance (a small chevron
   cue is the obvious candidate), but that's a new visual pattern with no
   existing precedent anywhere else in this app to match against — a real
   design call, not a "just add a gradient" fix, and better made
   deliberately than invented under a broader autonomous pass.

~~3. **Upload any document type (not just images), with a real per-type
   viewer and AI able to read it — even a small model.**~~ **Built** —
   see the live list's item 2 above for the full audit and the one real
   bug (extracted text never reaching the model) found and fixed there.
~~4. **The documents-dock row wasn't aligned.**~~ **Fixed.** `#doc-view-seg`
   inherited `.seg`'s stock `margin-bottom: 0.5rem`; nothing zeroed it for
   `.doc-dock`, so the pills sat 4px above "AI edit"/"Extract notes"/the
   kebab — the exact bug `.chat-dock-controls .seg` already fixed for
   itself. `.doc-dock .seg { margin: 0; }` added; live-verified, all six
   controls now share one `centerY`. Also answered: the Library sub-tabs
   bar is deliberately absent from the editor (§87.7d) — the editor has its
   own switcher (sidebar Recent list + "Browse all in Library →"); showing
   All/Whiteboards/Image Gallery there would apply to nothing on screen.

## §87 — the connected-notebook pass: the editor layer, and everything reported with it

Fifteen asks arrived in one message, then a second round of ideas on top. This
section is the whole of it, **audit-first**: every ask was checked against the
source *before* being scoped, because this project's most expensive recurring
mistake is rebuilding something that already exists. **Five of the fifteen
turned out to be already built or half-built.** Those rows are the most
valuable part of this section — they are what stops a sixth session rebuilding
them.

### 87.1 The audit — do not rebuild these

| Ask | Verdict | Where it already lives |
| --- | --- | --- |
| Slash commands | ABSENT (now built, 87.2) | BACKLOG §64 confirmed it |
| Callout boxes / frames | ABSENT (now built, 87.2) | `renderMarkdown`'s blockquote branch had no `[!kind]` sniffing |
| Wiki-links | PARTIAL | Worked in notes (`renderNoteText`) and doc preview (`layerDocWikiLinks`) — but two *different* resolvers, `[[` autocomplete on `#entry-content` only, and no create-on-miss. Backend hook: `sync_wiki_links`, `entry/manager.py:1496` |
| Gravity / spread sliders | **ALREADY BUILT** | `index.html:1263-1269`, applied `graph.js:1255-1273`, persisted. Known gap: no effect under tree/radial (BACKLOG §536) |
| Move nodes freely | **BUILT** | Drag still releases an unpinned node on drop (correct — that's a normal drag, not a hold). Double-click pin is now persisted (`Entry.graph_pin_x/y`, `PUT /graph/pin/{id}`) and survives a reload. A real toggle bug found live in the process — a double-click's own two constituent clicks each ran a zero-distance drag that unconditionally cleared the pin before the dblclick handler saw it, so unpinning never actually worked — is also fixed. Full narrative: HISTORY.md §100 |
| Hide nodes / groups | PARTIAL | Category-legend hide, orphan hide and time filter all exist. **No per-node hide, no marquee** — a full marquee exists only in `whiteboard.js:3167-3320` |
| Graph → whiteboard | ABSENT | But **both auto-layout engines already exist**: `ai/tools/whiteboard.py:263-432` and `wbMindMapSpanningTree` |
| Custom graph configurations | **ALREADY BUILT** | Saved views, `graph.js:2839-2958` |
| Document outline / sections | PARTIAL | `renderDocOutline` existed; jumping was caret-based and `renderMarkdown` emitted no heading ids |
| Document → notes | **ALREADY BUILT** | `#doc-extract` → `openExtractPreview`, backend `source_document_id`. Note→doc too (`expandNoteIntoDocument`) |
| Parent / child notes | **ALREADY BUILT** | `Entry.parent_id`, `core/database.py:198`, commented "a child continues its parent". Rendered nested, walked by pathfinding, feeds staleness |
| Thought continuation | PARTIAL | "Continue" exists **on note cards** (`app.js:1877`, posts `parent_id`). **Not in Capture** |
| Capture: manual link picker | ABSENT | `saveEntry` posts only `{content, tags, category, document_ids}` |
| Suggest links + editable reasons | **ALREADY BUILT — in the Graph tab** | `#link-suggest-btn` → `loadLinkSuggestions` (`app.js:21358-21500`), confidence + editable reason + Link/Dismiss. **Relocate, do not rebuild** |
| Note clusters | ABSENT as specified | See 87.5 — four adjacent concepts exist and none fits |
| AI link quality | PARTIAL | Candidates are **pure embedding cosine** (`routes_entries.py:476-502`); the LLM only writes the reason afterwards (`ai/links.py:97-185`). `EntryLink` is untyped |
| Ask latency | NOT a frontend bug | Explicit submit, so debounce is correctly absent. Cost is `search_manager.retrieve_detailed` + model streaming. No client answer cache |
| Loading animations | PARTIAL | `spinnerEl`, `typingDots`, shimmer skeletons and progress bars all exist with reduced-motion fallbacks. **Uncovered:** graph link-suggestions fetch, Library semantic refresh, note-picker search |
| Documents editor "behind the app" | **STRONGER THAN ROADMAP CLAIMED** | Already had autosave + beforeunload guard, word goal, preview, AI edit, extract-notes, find/replace, md/PDF export, outline sidebar |
| Features feel disconnected | STRUCTURAL | **Documents was not in the tab bar** — `TABS` carried it but `revealTab` aliased it to Library |
| Whiteboard "janky" | **ROOT CAUSE FOUND** | `renderWhiteboard()` is a full d3 data-join over every item, called from **49 sites**, no dirty flag, no rAF batching, drag handlers re-allocated inside the render |

### 87.2 Built this session

- **`frontend/editor.js`** (new file — deliberately not more of `app.js`; see
  Tier 4 on why a split must not share a diff with live edits). The `/` menu:
  caret-anchored popup measured with a mirror div, four command groups
  (blocks/frames, links/references, AI actions, templates), ranked matching,
  and **one delegated listener per event** rather than per-textarea — which is
  why `ALLOWED_DOUBLES` in `test_frontend_handlers.py` needed no new entry.
- **Callouts**, `> [!kind] Title`, eight kinds. Syntax chosen because it
  degrades to an ordinary blockquote in any other reader — portability is the
  premise of a local-first notebook that stores plain markdown. Body is
  markdown-rendered, so a callout can hold lists and code.
- **Heading anchors** in `renderMarkdown`, de-duplicated per render.
- **Transclusion `![[note]]`**, notes only and deliberately so: `GET /documents`
  returns no content, and `renderMarkdown` runs on every streamed chat chunk,
  so a fetch in that path is a request storm waiting to happen.
- **One wiki resolver** (`resolveWikiTarget`) replacing the note-only and
  document-only pair, so `[[name]]` finally means the same thing in every pane.
- **Create-on-miss**: clicking an unresolved link offers to create the note or
  the document. **User-confirmed, never background** — silently materialising
  notes from typos is exactly what the autonomous agent is careful not to do.
- **Documents promoted to a real tab**, reversing §36F. That reversal is
  commented at both sites rather than silently applied: §36F correctly removed
  a *second list*; what it did not anticipate is that being reachable only
  *through* another tab is what made the feature read as second-class.
- **`test_frontend_handlers.py` extended to scan `editor.js`** — a lint that
  cannot see a file cannot catch anything in it.

### 87.3 Tags as first-class objects — the decision behind note clusters

The cluster ask ("group notes for a purpose, without affecting links") has
**four adjacent concepts that each fail it**: *spaces* partition (a note is in
exactly one, others vanish), *categories* are one-per-note, *whiteboard
`group_id`* is board items only, and the graph's own "clusters" are **computed
connected components** — the literal opposite of link-independent. *Tags* are
the only many-per-note, user-defined, link-independent thing already here.

So the recommendation is **not a fifth concept — promote tags**. Today
`Entry.tags` is a JSON array of strings (`database.py:189`). First-class means
a `Tag` table (id, name, description, colour, created_at) plus an association
table, and it buys, in one change:

- **Rename a tag everywhere at once.** Today a rename means rewriting the JSON
  array on every note that carries it.
- **Merge two tags** (`work` / `Work` / `work-stuff`) — the single most common
  real tag-hygiene job, and currently impossible without a script.
- **A description and a colour**, which the graph can then key off.
- **A tag becomes an object**, so it can be a node, collapse, and be saved in a
  view — which is what the cluster ask actually wanted.

**Two warnings, both load-bearing:**

1. **This makes Alembic (live-list item 7) a real prerequisite, not a
   nice-to-have.** A new table plus a one-time backfill of every note's JSON
   array is precisely the change the additive auto-migrator "cannot rename or
   drop" warning is about. Do not start this while migrations are hand-rolled.
2. **Keep `entry.tags` working as a property.** Every read path in the app and
   the AI tools reads it as a list of strings. If the promotion changes that
   shape, the blast radius is the whole codebase; if it stays a hybrid
   property over the new rows, it is contained.

### 87.4 Grouping the graph by tag — the real problem is the many-to-many

Asked for directly. Worth stating plainly: **the rendering is the easy half.**
`graph.js` already colours by category and already has hierarchy layouts. The
actual design problem is that a note has **one** category but **many** tags, so
"group by tag" is ambiguous for every multi-tagged note. Three honest options:

- **(a) Primary tag** — first tag wins. Trivial, and quietly wrong for the
  notes that matter most (the well-tagged ones).
- **(b) Tag supernodes** — each tag is a node; notes link to their tags. A note
  with three tags sits between three anchors and the force layout does the
  rest. Composes with 87.3, and is the closest to what was asked for.
- **(c) Duplicate the note per group** with ghost edges. Reads well, but two
  dots for one note breaks every count and every selection.

**Recommendation: (b)**, and only after 87.3 — a supernode needs a tag object
to *be*.

### 87.5 Link strength and typed links (extends the Phase D work)

Asked for directly and it is a good idea, partly because **half the field
already exists**: `EntryLink.reason_confidence` is a float that today only ever
holds an embedding cosine score. Generalising it into a composite strength over
several signals is the natural next step:

| Signal | Where it already is | Used for weighting? |
| --- | --- | --- |
| Explicit `link_type` (6 named kinds) | `EntryLink.link_type` | **Yes — first slice, built** |
| Deduced-reason confidence | `EntryLink.reason_confidence` | **Yes — first slice, built** |
| Embedding similarity | `routes_entries.py:476-502` | Only indirectly (`SIMILAR_WEIGHT` in paths.py, flat) |
| Explicit `[[wiki link]]`, distinguished from any other bare link | `sync_wiki_links` | **No — see the correction below** |
| Shared tags (Jaccard) | `Entry.tags`, better after 87.3 | No |
| Same category | `Entry.category_id` | No |
| Temporal proximity | `created_at` — written the same afternoon is a real signal | No |

**First slice built** — `link_strength()`, wired into both `entry/paths.py`
and `graph_expansion()`. Full narrative, including the correction that
"explicit `[[wiki link]]` should be strongest" can't be built as scoped
(nothing distinguishes how a link was made): HISTORY.md §100.

**Two design calls, for the composite that is still open — the derived
signals (shared tags, category, temporal proximity), not the explicit ones
already built above:**

1. **Store the components, not just the number.** This app already learned that
   "these are related" is not good enough — that is why link *reasons* exist. A
   single blended 0.72 is the same mistake in numeric form. Store the
   contributing signals so the UI can say *"shared tags (work, q3), same
   category, written the same day"*. That is also what makes the score
   debuggable when it is wrong.
2. **Store explicit, compute derived.** An explicit link's type and strength
   belong in the row (done, above). Shared-tag and same-category strength
   changes every time a tag changes, so storing it means an invalidation
   problem; compute those at query time, which is what `_similarity_edges`
   already does for similarity — but note both consumers are on a hot path
   (`graph_expansion` runs on every chat/ask retrieval), so a per-pair
   query-time computation needs real measurement first, not an assumption
   that it's cheap. §88.4 item 4's per-stage token accounting (built) is
   available for that measurement now.

### 87.6 The Timeline line view — a concrete design, at last (built — see live list item 3)

Live-list item 3 has said "needs a real visual pass" and nothing more, twice.
Here is the specific version, and it comes from joining two things already in
the repo that nobody has connected:

- `IDEAS.md` asks for **"a visual timeline like a branching line with off
  shoots"**.
- `Entry.parent_id` **already stores exactly that branch structure** — threads,
  where a child continues its parent. The line view currently ignores it
  entirely and renders one flat chronological line.

So the design is: **the trunk is time; a thread is a tributary.** A note with
children sprouts a branch that runs alongside the trunk and rejoins nowhere —
it just ends where the thread ended. No new data, no new endpoint; the branch
structure is a `parent_id` walk the pathfinder already knows how to do
(`entry/paths.py:189-191`). Everything else (curve style, density, labels) is
polish on top of a structure that finally means something.

### 87.7 General visual pass — what is actually worth doing

Grounded in the audit rather than invented, and marked where already tracked:

- **Loading states on the three uncovered surfaces** (87.9 item 4). The
  primitives all exist; this is application, not design.
- **Colour contrast has never been measured against WCAG AA** — already an open
  live-list item, still true, and now with more surfaces (callouts add eight
  tinted backgrounds that nobody has measured text against).
- **Emoji vs. icons is a *pending decision*, item 16f** — and note that this
  session's callouts and `/` menu use emoji, consistent with the app as it
  stands today. If 16f lands on an SVG set, `CALLOUT_KINDS` in `editor.js` is a
  single data table and the `/` menu's labels are one more; both are cheap to
  convert, which is why they were written as data.
- **Empty states**, unscoped and worth a sweep: what the graph, timeline and
  dashboard show before the first note exists is already named as the
  highest-leverage onboarding work.
- **The whiteboard has no minimap** though the graph now does — an asymmetry,
  not a bug.

### 87.7b Reported live during this session — fixed, with what was measured

- **The minimap covered the zoom buttons.** Reported, then measured rather
  than assumed: at 1400×900 the minimap spanned x1160–1338 and the zoom
  buttons x1298–1334, and at z-index 5 against their 2 it won outright.
  **Its corner is now a user setting** (the user's own suggestion, and the
  right one — no corner is free on every layout: the toolbar owns the top, the
  agent monitor bottom-left, the zoom buttons bottom-right). Default top-left.
  Verified: `overlapsZoom: false`, the choice persists, "off" hides it.
- **The graph toolbar was a flat run of a dozen equally-weighted controls**
  that wrapped into a mostly-empty second row. Now five labelled groups with
  hairline separators. Measured after: 5 groups, 2 rows, **every control 32px**
  (the one-height rule DESIGN.md states for this strip), no horizontal
  overflow. The minimap's visibility and position were **merged into one
  control** rather than added as a second — the redesign should not be paid
  for with more clutter.
- **Back/forward between pages**, in the status bar as asked, visually
  distinct from undo/redo (caret icons vs. u-turn arrows, plus a divider —
  they move you between pages; undo/redo change your notes). Deliberately not
  `pushState`: this is a single page with no routing, so browser history
  entries would let its Back button walk out of the app entirely. Verified
  including the browser rule that a new visit mid-stack discards what was
  ahead.
- **40 form controls had no accessible name at all** — mostly whiteboard
  ones, which confirms the roadmap's own note that the whiteboard's
  `aria-label` coverage lags the graph's. All 40 now carry a name and a
  tooltip; a re-run of the audit reports zero remaining. Worth recording how
  that number was reached: a naive sweep flagged **212 buttons**, but a
  visible text label *is* an accessible name, so a tooltip on a button that
  says "Save" is noise rather than a fix. Filtering to controls with no
  visible text left 9, of which 7 are labelled at runtime by
  `paintStatusItem` — the genuine gap was the form controls, not the buttons.
- **"The search relevance settings section stays highlighted permanently."**
  Real, and a good example of the shape this codebase keeps meeting. Three
  places add a `flash` class; two clear it on a 2,700 ms timer and this one
  never did. It looked harmless because the animation ends on `transparent`,
  so on an ordinary machine the highlight fades and the stuck class is
  invisible — but under `prefers-reduced-motion: reduce` the stylesheet
  deliberately swaps the animation for a **static** outline and background,
  and with nothing removing the class that highlight is permanent. Fixed by
  giving it the same cleanup its two siblings already had, and verified with
  the browser context set to `reducedMotion: "reduce"`.

### 87.7d The Library restructure, and the Documents-tab reversal

Decided with the user, and worth recording because it **reverses a decision
made earlier the same session** — Documents was promoted to a top-level tab
and then moved back.

The reason the reversal is right: the original complaint ("documents feel
inaccessible") was diagnosed as *depth of click*, and it was not. The Library
sub-tab labelled **"Documents" actually showed everything** — notes, chats,
files and documents together — so the one place a person would look for their
documents was the one place with no documents-only view. Promoting a top-level
tab treated the symptom; giving Documents its own Library section treats the
cause.

What changed:

- Library sub-tabs are now **All · Documents · Whiteboards · Image Gallery ·
  AI Skills**. The first kept its `library-view-documents` id (referenced in
  several places; a rename buys nothing) and is now labelled "All".
- **Documents gets its own section**, `library-view-docs`, with title search,
  a new-document button and word/updated metadata. It reuses `GET /documents`
  and `openDocument()` rather than adding an endpoint or a second path into
  the editor.
- **Drafts stopped being a sub-tab and became a chip** in the All view's
  filter row. A draft is a state a note is in, not a separate kind of object.
  This needed a real backend collector (`_drafts()` in `routes_library.py`),
  **not** a relaxed filter: drafts are deliberately excluded from `_notes()`
  because "draft notes appear as regular notes in the main library" was
  reported and fixed once already. They carry `kind: "draft"` so the chip
  finds them while "Everything" still does not show them.
- The top-level Documents tab is gone and `revealTab`'s
  documents→library button alias is restored, with a comment recording both
  the promotion and the reversal so it is not re-derived.

Verified live: the main tab is absent, the five sub-tabs read in the right
order, the Drafts chip appears in the filter row, and the Documents section
renders and opens documents. Zero console errors.

**One process note worth keeping.** The Drafts chip first measured `0` and the
cause was not the code: `routes_library.py` had changed and **uvicorn had not
been restarted**. That is CLAUDE.md's own documented trap, hit while working
from the file that documents it.

### 87.7c Reported live, NOT yet built — next session starts here

~~1. **The graph is slow and janky to move around.**~~ **Profiled directly
   (120 notes, 6x CPU throttling, CDP `Performance.getMetrics`) — one real
   cause found and fixed, one still open.**
   **Fixed:** `graphSimulation.stop()` was only ever called "before every
   rebuild," never on leaving the Graph tab — so a simulation still cooling
   when the user switched away kept ticking on whatever tab they moved to.
   Measured: Dashboard busy time 21% before ever opening Graph, 58% right
   after leaving it, ~12 more seconds to decay back to baseline. This is
   very likely a real contributor to "the app feels slow" reports that
   don't obviously implicate the graph. Now stopped on tab-leave; re-measured
   at ~20% (baseline) within 6 seconds instead of 12+.
   **Still open:** the graph's own busy time *while cooling, on the Graph
   tab itself* is genuinely high (82-88%, matching this file's own prior
   documented pass) and this session did not reduce it — the existing
   `alphaDecay(0.05)` tuning was already in place and the physics/tick-cost
   work described just above this item was not reopened. Whether that
   specific window still reads as "janky" to a real user on real (not
   throttled) hardware is unverified — this sandbox has no way to compare
   against unthrottled perception, only relative measurements.
~~2. **The saved-view select truncates to "No saved vi…"** in the redesigned
   toolbar.~~ **Already fixed** — `.graph-toolbar #graph-view-picker`
   already carries `min-width: 12.5rem` with a comment recording this exact
   symptom. Verified live: `scrollWidth` (198px) fits inside the rendered
   width (200px), "No saved views" shows in full.
~~3. **Graph node labels show raw callout syntax**~~ **Fixed** — see the
   live list's item 13 above.
~~4. **Semantic search ignores time words.**~~ **Already built** — see the
   live list's item 18 above for what exists (`search/query.py`'s
   `understand()`, wired into `search_manager._retrieve`) and how it was
   verified live this session.
5. **The graph minimap "can no longer be hidden or shown."** The toggle button
   became a dropdown with **Off** as its first option, and that dropdown is
   verified working (`MINIMAP -> off hides it: true`). So either this is a
   stale cached bundle — the service worker serving an older `app.js`, which
   this repo has been caught by before — or the dropdown is simply less
   discoverable than the button was. If it is re-reported after a hard
   refresh, the answer is discoverability, and the fix is a visible toggle
   next to the position select rather than folding both into one control.
~~6. **Timeline line view redesign.**~~ **Built** — see live list item 3.

### 87.8 Checked this session — three of four were already done, the fourth partly fixed

~~Backlinks panel ("what links here") — edges already stored by
`sync_wiki_links`; a query plus a sidebar section.~~ **Already built,
found by checking rather than assuming.** `manager.links_for_entry()` is
already bidirectional ("all links touching this entry"), and every note
card's `.entry-links` row (`app.js`) already renders it as clickable
preview chips — this app's link model has no directional/citation
semantics (a link's reason reads "the same phrase either direction" —
`entry/paths.py`'s own docstring), so an undirected "linked notes" panel
*is* the backlinks panel, not a lesser version of one.

~~Whiteboard render scheduler (the 49-call-site fix above).~~ **Already
fixed** — see item G on the live list above: every drag handler already
mutates the DOM directly rather than calling `wbScheduleRender()`/a full
re-render, checked across all 48 call sites per that function's own
comment.

~~Typed links / `link_type` as the first slice of 87.5.~~ **Built this
session** — see §87.5's own text above for the full narrative
(`link_strength()`, wired into `entry/paths.py` and `graph_expansion()`).

**Graph performance (§87.7c item 1) — profiled, partly fixed.** One real
cause found and fixed (the simulation kept running on other tabs after
leaving Graph); the graph's own busy time while actively cooling on its
own tab is still high and unaddressed. §87.7c's own text above has the
full narrative and the measured numbers.

### 87.9 Handoff list — each item already located, none needs re-deriving

1. **Capture: manual link picker + suggest-links button.** Reuse
   `loadLinkSuggestions` (`app.js:21358-21500`) and its editable-reason rows.
   **Do not write a second suggester.** Links apply after save (a note needs an
   id), so hold a pending set and flush it in `saveEntry` (`app.js:4380`).
2. **Capture: "continues from…" picker.** `Entry.parent_id` and its validation
   already exist (`routes_entries.py:183-216`). A note-picker plus one field.
3. **Graph: persist node positions, add per-node hide.** Stop clearing `fx/fy`
   at `graph.js:1473-1474` when free layout is on; persist pins beside the
   other per-device graph state (`GRAPH_VIEWS_KEY`, `graph.js:2839`). Add a
   right-click node menu as the one surface for hide/pin/expand/open.
4. **Loading states** for the graph link-suggestions fetch (`app.js:21358`),
   Library semantic refresh (`app.js:19437`) and note-picker search. Respect
   the existing reduced-motion fallbacks.
5. **Ask: a client-side answer cache** keyed on question + notebook version.
   **Say in the handover that the real latency is server-side retrieval** —
   this makes a repeat feel instant, nothing more. Do not claim a fix.
6. **Graph → whiteboard.** Marquee-select in the graph first (port
   `whiteboard.js:3167-3320`), then hand the ids to the **existing** layout
   engines (`ai/tools/whiteboard.py:263-432`).
7. **Document → graph / whiteboard**, building on `openExtractPreview`.
8. **Ctrl+K as a true omni-jump.** The palette exists (`app.js:17486-17620`);
   widen its index to notes, documents, boards and saved graph views.
9. **Unlinked mentions.** Scan **titles only** or it floods, and **offer, never
   auto-apply**. Reuse the accept/dismiss row from `loadLinkSuggestions`.
10. **Document sub-pages.** Notes have `parent_id`; documents do not. One
    nullable additive column plus nesting in `#doc-list`.
11. **AI-authored callouts.** Let the agent emit `> [!question]` blocks. Note
    `agent.PROSE_BUDGET_CHARS` is **asserted** — the prompt has a budget.

## Read these two first (older entry point; see the top of this file)

| | What's in it |
| --- | --- |
| [roadmap/HANDOVER.md](roadmap/HANDOVER.md) | **The last session's handover.** What changed, what couldn't be checked and why. Read this first. |
| [roadmap/HISTORY.md](roadmap/HISTORY.md) | Everything already built, and every backlog item already closed — with the reasoning, condensed. **Check here before building anything.** Four sessions have rebuilt something that already existed. |
| [roadmap/BACKLOG.md](roadmap/BACKLOG.md) | Standing backlog items not yet promoted to this file's live list. |
| [roadmap/ANALYSIS.md](roadmap/ANALYSIS.md) | Judgements: the odysseus read, and the licence constraint — **this project is AGPL-3.0 now, not MIT**, so §34a's "no code crosses either way" is half-lifted. What was deliberately not taken. Also §59: the claude-obsidian/cognee/graphify read behind items 32–36 below, and §60: a second odysseus read after the repo tripled in size — a real non-atomic-write bug it found, an MCP shape worth copying, and its own admission that the backend isn't better designed. **New: §114**, a product-strategy read — a live competitor teardown (NotebookLM, Obsidian, Anytype, Capacities, Khoj, Granola, Kortex), an upgrade list for every existing feature, 18 new-feature proposals, a scored 90-day plan, and the answer to "how do you measure anything in an app with no telemetry". It also strikes three §111.2 items as already built. |
| [DESIGN.md](DESIGN.md) | The design system. `tests/test_style_scale.py` enforces it. |

## Still open after §105

§105 (HISTORY.md) closed a long run of live reports. What it did **not** close,
each already located:

1. **The translation action has never met a model.** `docTranslatePassage`
   hands the passage to the chat composer with the question written. That the
   composer receives it is verified; that a local model answers it well is not.
2. **The vision reader is still unexercised.** Every OCR test drives a fake
   transport. `?reader=tesseract` is now a real alternative and is equally
   unmeasured — no `tesseract` binary in the sandbox either.
3. **Tensions still has no measured hit rate** (§104's caveat, unchanged).
4. **Source view cannot underline a flagged word**, and structurally cannot: a
   `<textarea>`'s value is a string. Double-click and right-click open the same
   menu off the caret offset. If this keeps being reported, the answer is a
   contenteditable source view, which is a much larger change than it looks.
## Next up, ranked by what it unlocks

**One list, four tiers. Work top-down and do not skip.** The failure this
project actually has is not forgetting work — it is a later session picking
something interesting from further down while a correctness bug sits at the
top. If an item is blocked, say so in the handover and take the next one.

The tiers are not equal. Nothing in Tier 2 is worth more than any Tier 1 item.

### Tier 1 — correctness and trust

Things that are wrong, lose work, or make the app feel unreliable.

**This tier is empty, and that is the point of saying so.** Every item that
was here has been fixed and re-verified against source; the resolutions are in
[roadmap/HISTORY.md](roadmap/HISTORY.md). Two carry a caveat worth keeping
rather than a clean tick:

- **Meeting transcription** now fails with a distinct 503 and a clear cause
  rather than a mystery error — but **no session has ever observed a
  successful transcription**, because this sandbox's network policy blocks
  `huggingface.co`. If it is re-reported, that is the untested half.
- **Notifications** were audited and traced by call site rather than driven in
  a browser. Say so if the behaviour is re-reported.

The one genuinely open correctness item, **claim-specificity in the
hallucination net**, is item 5 of the live list at the top of this file — it
needs real model output to tune against, which this sandbox cannot provide.

### Tier 2 — half-built features, cheap to finish

Each is already paid for; a small amount of work turns a frustrating surface
into a good one.

11. **The whiteboard, properly.** ~~Images, text boxes, resize (8-handle
    corner+edge), grid (lines/dots/isometric)+snap, per-board background
    image, export (PNG/SVG/PDF), clear-board, a redesigned board picker,
    redo, single-item select, undo/redo, per-tool cursors, an eraser,
    keyboard shortcuts, draggable toolbar panels, highlighter+arrow tools,
    a board-colour reset, touch input (pointer events), sketch move+resize,
    copy/paste, multi-select (shift-click/marquee/bulk move/bulk delete),
    grid-snap on every item kind (not just cards), shift-to-constrain a
    drawn shape, Alt to bypass snap for one drag, two more shape types
    (triangle/diamond), arrowhead styles, precise drop placement, a real
    "glitchy and slow to update" perf bug (a full board re-render on every
    card-drag frame), a properties panel (colour/width/arrowhead/fill/
    border/font-size) for the current single selection, card resize
    (8-handle, same as images/text boxes), object grouping (Ctrl+G/
    Ctrl+Shift+G, a persisted `group_id`, click-one-selects-the-whole-group),
    undo/redo extended to cover move *and* resize (not just create/delete),
    arrow-key nudge (grid-step when snap is on, 1px/10px+Shift otherwise),
    alignment tools (left/h-centre/right/top/v-centre/bottom) and distribute
    (horizontal/vertical) for a multi-selection, and rotation (a drag
    handle above the item, Shift snaps to 15°, for cards and objects — see
    "still open" below for why sketches don't have it yet)~~ **all done,
    verified live — see HISTORY.md §53–§55 for the full list and how each
    was verified.**

    **Still genuinely open, ranked by what's actually left.**
    - **Image cropping.** Asked about directly; not scoped or built —
      needs a decision on the interaction (a crop rectangle over the full
      image vs. a separate "adjust" mode) before building.
    - ~~**A whiteboard backend/perf pass**~~ **Partly done (HISTORY.md
      §57).** The one real client-side O(cards × notebook size) issue found
      is fixed. **Not done**: a real profile against a large, many-hundred-
      item board — nothing this session was measured against one.
14. **Timeline line view, and text placement in grid view.** The grid view's
    text-placement half is **done**: an unprefixed `line-clamp` fixed
    (kept alongside `-webkit-line-clamp`), plus the backend's `preview`
    field truncating with an ellipsis. **Re-reported after that fix, still
    cut off**, not reproduced in this sandbox's Chromium; a defensive
    `max-height` was added as a safety net (HISTORY.md §49-adjacent) but
    this is hardening, not a diagnosis — the next session needs the actual
    browser/OS this is happening in. ~~**Also reported: the line-view's own
    note popup shows no markdown rendering and no sketch/image attachment
    preview.**~~ **Fixed and verified live (HISTORY.md §51).** **§87.6's
    concrete design (thread bands) is now built — see live list item 3.**
    **Still open:** the *vague* half of the original report ("very
    professional and ready for public use" — no specifics given), and grid
    view could still take general UX polish beyond the text-cropping fix
    (not scoped further — say what specifically, next time it's reported).
16c. ~~**Images and files still can't be copied, pasted, or dragged into
    notes.**~~ **Two of three already worked — checked live before
    building anything (HISTORY.md §51).** The third path — a file-picker
    button (`📎 Attach`) — was genuinely missing and is now built.
16d. ~~**An optional title field in Capture, and everywhere a note can be
    created.**~~ **Decided and built (HISTORY.md §52).** Writes the leading
    `# {title}` heading line into `content` on save, verified live end to
    end from both Capture and the graph's "+ New note" popup.
16e. **Decision made, not yet built**: both a native-OS picker and a
    built-in in-app palette, same pattern as 16f — a toggle in Settings →
    Appearance picks which one opens. Not scoped further (which inputs get
    the trigger control, where the built-in palette's emoji set/data comes
    from) — do that scoping next to whatever picks up 16f, since both share
    the same Appearance-tab toggle mechanism and are cheaper built together.
16f. **Decision made, not yet built**: an SVG icon set *and* monochrome
    emoji, both available, with a toggle in Settings → Appearance to switch
    between them (not a single fixed replacement). Needs: (1) the actual
    count/categorisation pass (decorative vs. load-bearing) this item
    already called for, (2) an icon set picked and the SVGs wired in
    alongside the existing emoji rather than replacing them outright, (3)
    the CSS monochrome-filter path for the emoji option, (4) the Appearance
    toggle and the app-wide switch it drives. Sizeable — a full session's
    worth, not a quick pass.
    Original ask, kept for context: **a full sweep of emoji usage across
    the app**:
    *"I feel the application is very heavy with emojis, it feels too much
    like AI slop... make sure they are only used professionally and with
    intention, otherwise professional icons are the better way to go."*
    Also considering colourless/monochrome emoji as a middle ground, but
    undecided. This is a design decision affecting most of `index.html` and
    a large fraction of `app.js` (tab icons, button labels, toast prefixes,
    status chips) — not a quick pass. Needs, in order: (1) an actual count
    and categorisation (decorative vs. load-bearing — some emoji are the
    only differentiator between otherwise-identical icons, e.g. the
    notification kind icons), (2) a decision on the replacement (SVG icon
    set vs. monochrome emoji vs. selective removal), (3) then a build pass.
    Doing the build pass before the decision risks redoing the same ground
    twice, which this project's own history (HISTORY.md's repeated "checked
    before building" theme) is precisely the failure mode it keeps warning
    about.
### Open questions raised this session, not built

- **Should Capture have its own title field**, separate from the leading-
  heading convention §43 already shipped (`manager.extract_title` reads a
  `#`–`######` first line, computed on read rather than stored)? Asked
  directly, including "if the user begins a note with `#` maybe it moves to
  the optional title input" — genuinely a design question in the same shape
  §43 was worked through as, not a bug: a second, separate title field would
  either duplicate the heading-line mechanism (keeping both in sync) or
  replace it (undoing the "read off the note, not enforced" decision §43's
  writeup already recorded). Needs a decision before either is built, not a
  guess.
- **"The dashboard isn't detecting my name."** Traced end to end
  (`renderNameNudge`/`withDisplayName` read `prefsCache.display_name`, and
  `savePrefs` updates both the cache and re-renders the greeting on save) and
  the code reads correct — the nudge is *designed* to show exactly when
  `display_name` is empty, so a fresh profile with no name saved yet showing
  "👋 Add your name" is very likely the feature working as built, not a bug.
  Could not reproduce a case where a name was actually saved and still not
  shown; if it recurs, check `GET /preferences` directly for whether
  `display_name` actually persisted, rather than assuming the render path.
- **The Timeline grid's "text cut off with no ellipsis" report** (§38a item
  2 was believed fixed) was re-investigated live: seeded notes up to 122
  characters at the grid's actual 13rem column width and read
  `getComputedStyle` on every `.timeline-dot`. Two things came out of it,
  neither a confirmed fix: `-webkit-box`'s **computed** `display` resolves to
  `flow-root` in this sandbox's Chromium, not `-webkit-box` — the property
  the existing code comment says is "what this display mode actually reads"
  isn't actually the mechanism in effect here, though clamping still worked
  correctly in every case tested (`scrollHeight === clientHeight`, nothing
  overflowing). Could not reproduce actual clipped, non-ellipsised text with
  any input tried. Worth re-checking with the user's exact note content and
  browser before guessing at a CSS change — this project's own standing rule
  is to reproduce before theorising, and this one didn't reproduce.

### Tier 3 — new capability

Worth doing, and worth doing after the above.

22. **Meeting recordings as first-class objects**: pause/resume, replay, save
    as a voice note, transcribe in the background. Blocked on Tier 1 item 1.
23. **Notification expansion**: reminders, and opt-in AI nudges from the
    utility model. Blocked on Tier 1 item 5 — decide what they *are* first.
24. **Graph layouts beyond Arc** — mind map, treemap/sunburst, adjacency
    matrix. Each is a materially different rendering approach, not a fourth
    case the existing `layoutHierarchy` machinery covers free. The decorative
    half (skins, minimap, PNG export) is the smaller contained piece if a
    session wants a quicker win. Asked for by name as "an Obsidian-style
    knowledge graph": Obsidian's is a force layout, which this app already
    has. ~~The interaction half — smooth pan/zoom feel, node-drag
    responsiveness, a cleaner minimal aesthetic at rest — done this
    session (HISTORY.md §71): a tuning pass on the existing force
    simulation, not a new layout algorithm, per this item's own note that a
    new algorithm probably wasn't the actual gap.~~ **New layouts
    themselves are still open** — nothing above touched that part.
27. **llama.cpp, actually wired in.** A new `ai/provider.py` entry alongside
    Ollama/OpenAI-compatible, a GGUF file picker (files on disk, not a
    registry to pull from), and `core/extras.py`'s `unavailable` string
    removed once it is real. Asked about directly and deferred, not forgotten.
28. **§20's async-httpx refactor.** Deferred so there was always a known-good
    streaming path to bisect against; that reason has expired, and the cost
    grows as more providers touch the sync path.
29. **Better-looking theme previews** in Appearance.
30. **Standing backlog, the rest** — [roadmap/BACKLOG.md](roadmap/BACKLOG.md)
    holds ~65 numbered sections; most are either done (check before
    rebuilding — this file's own repeated lesson), blocked on a design
    decision, or genuinely large. The items below are the ones re-read this
    session that are neither: concretely scoped already, no decision
    blocking them, and not duplicated by anything above. Ranked by impact
    versus how contained the change is, highest first. **MCP support**
    (BACKLOG §29, ANALYSIS §60) is no longer in this list — see item 38.
    30a. ~~**Note-list keyboard navigation**~~ **Done (HISTORY.md §68).** A
        roving tabindex through `#entry-list` — arrows move focus, Enter
        opens the focused note the same way its Edit button does.
        Live-verified: Tab into the list, ArrowDown moves the tab stop,
        Enter opens edit mode.
    30b. ~~**Archive, for notes.**~~ **Done** (commit `4825e70`, this file's
        own tracking never got updated when it landed — caught this session
        by checking the running app before assuming the item was still
        open, per CLAUDE.md's own top rule). `Entry.archived_at`
        (additive auto-migration), `POST /entries/{id}/archive`/`/unarchive`,
        `GET /entries?archived=true`, a Library "Archived" filter chip +
        overview tile (`_shelved()` in `routes_library.py` — deliberately
        named apart from the pre-existing `_archive()`, which is actually
        the bin under an earlier, different naming decision; both
        docstrings cross-reference the collision so it can't cause
        confusion again), and a Notes-tab "Archive" action next to (not
        grouped with) "Move to bin". 13 backend tests
        (`test_archive.py`, `test_library.py`) plus live Playwright
        verification at the time. **Re-verified this session**: archived a
        fresh note via the API, confirmed it appears under the Library's
        Archived chip with the right count, zero console errors.
        **Extended to chats and documents this session** — the named
        remaining scope, done: `Conversation.archived_at`/
        `Document.archived_at` (both additive), `PUT
        /conversations/{id}/archive`/`/unarchive` and `PUT
        /documents/{id}/archive`/`/unarchive`, an "Archive" action beside
        Delete in the chat sidebar and the documents dock (not grouped
        with it, same placement as the notes version), and `_shelved()`
        extended to include both with a `"subtype"` field so the Library's
        one Shelved filter now covers all three kinds. 10 new tests
        (`test_conversation_archive.py`, `test_document_archive.py`).
        **Live-verified**: archived a real chat and document through the
        actual endpoints, confirmed both vanish from their ordinary lists
        and appear under the Library's Archived chip (screenshot: two
        cards, correct titles, "archived"/"just now" metadata), then
        unarchived both back to their normal lists — zero console errors
        throughout. The frontend kebab menu's own Archive/Unarchive click
        path is the same `makeMenuItem`/`kebabMenu` shape the notes version
        already uses successfully, but wasn't itself click-driven in this
        verification (a generic popup-visibility timing issue in the test
        harness, not a reproduced app bug) — the API + Library-rendering
        half of the round trip was. §26 lists three things that build on
        the full archive afterwards (a "delete everything" control, one
        assembled "your data" page, opt-in auto-archive-by-age).
    30c. ~~**Chat metadata not surviving a reload**~~ **Checked before
        building, found already fixed (HISTORY.md §70).** `_turn_messages`
        (routes_conversations.py) persists `stats`/`elapsed_ms` on the
        assistant message, and `openConversation`'s replay
        (`if (message.stats) messageMetaLine(...)`) already renders them —
        both already covered by `tests/test_chat_metadata.py`. Re-verified
        live: single-turn, multi-turn, and a turn with tool chips all show
        the correct meta line after a real reload. Whatever prompted this
        item is either already resolved or a different, unreported bug.
    30d. ~~**OCR text extraction on an uploaded image**~~ (BACKLOG §4 item
        1). **Done, verified live (HANDOVER.md's latest entry).** Local
        `pytesseract`/Tesseract (no torch, no cloud call), on a background
        thread so the upload response never waits on it. Fed into the
        Library's own Image Gallery search (new — that tab had no search
        box before) rather than the notes' `entries_fts` index this item's
        own text originally pointed at — a `MediaUpload` isn't an `Entry`,
        and that index's triggers are wired to the `entries` table
        specifically, so this was the honest integration point, not the
        literal one. `tesseract` is a system binary `pip` can't install;
        degrades to "no OCR text" cleanly when it's missing, documented in
        INSTALL.md. "What was on that whiteboard photo from March" is now
        answerable by typing a word from the photo into that search box.
    30e. ~~**Undo toasts for soft-deletes, in place of confirm dialogs**~~
        **Done (HISTORY.md §68).** `batchDelete()` already built the undo
        toast under a real soft delete and *also* gated it behind a
        confirm — removed the confirm, matching the single-note "Move to
        bin" action, which already had none.
    30f. ~~**README and GitHub Pages drift**~~ **Done (HISTORY.md §68).**
        Both had settled into naming pre-rebuild systems as current — README
        pointed at "Settings → Activity"/"Settings → Optional extras" (moved
        to the Library / renamed "Packages"); the Pages site claimed "Six
        tabs" and still listed a standalone Documents tab. Fixed both.
    30g. **A per-chat token meter, and an eval harness** — kept as a pointer
        only, not scoped further here; see BACKLOG.md directly for both.
31. **Expand the autonomous background agent's capabilities.** Asked for
    directly, without a specific gap named — today it does three things
    (`_enabled_tasks` in `ai/autonomous.py`): tag untagged notes, link
    conceptually related ones, flag duplicates. ~~Candidates worth scoping
    before picking one: acting on stale/orphaned notes~~ — **chosen and
    built this session (HISTORY.md §72)**: `entry/staleness.py`'s
    `find_stale_orphaned_notes()`, a new deterministic pass in
    `_run_optimization()` behind its own `auto_stale_review_enabled`
    preference (off by default, like entities), tags a qualifying note
    `stale` rather than acting on it further — nobody's watching an
    unattended pass, so the same caution `blocked_tools` already applies
    to `delete_note` applies here too. **Checked live this session, and a
    real bug found in the process**: `auto_stale_review_enabled` had a live
    Settings checkbox but was never declared on `PreferencesBody` —
    Tier 1 item 4a's exact bug shape, just missed on this one preference —
    so every attempt to turn it on silently did nothing, which is why it
    could never be end-to-end verified before now. Fixed (field declared,
    echoed back from `GET /preferences`, added to `_AUTONOMOUS_PREFS`), then
    verified for real: backdated a note's `updated_at` 200 days in the
    database directly, enabled the preference through the real route,
    triggered a pass via `POST /tasks/trigger-autonomous`, and the note came
    back tagged `stale`. Two new regression tests. The other two candidates
    — proactive digest/on-this-day surfacing, and letting a saved skill run
    on the same schedule — are still open.
### Tier 4 — deferred, with the reason

Not a dump: each says why it is not Tier 3.

- **`app.js` module split** (29.1k lines now, up from the 20.7k this entry
  was last written against — §60's session). Still worth doing
  *deliberately*, and now with an actual first candidate instead of "pick
  something": the whiteboard is a single unbroken, clearly-marked 5,300-line
  block (`// === WHITEBOARD LOGIC ===` at line 23292 through the next marked
  section at 28586) — the largest coherent subsystem in the file by a wide
  margin, and one a session could plausibly extract to `whiteboard.js` in
  one sitting with the `tests-e2e/` Playwright smoke suite as the safety
  net. Not attempted this session — the risk isn't the extraction itself,
  it's doing it *in the same sitting* as live edits to that exact code (this
  session's whiteboard bug fixes), where a half-done split and a bug fix
  landing in the same diff is much harder to review or revert than either
  alone. Do the split on a quiet day, not appended to a bug-fix session.
  (`style.css`'s own split is done — see Priority 0 item 2 above — and was
  exactly this: its own dedicated pass, not appended to anything else.)
- **A second React frontend.** A second implementation of every screen, kept
  in step by hand, for an app whose brief is "no build step". The cost is not
  the first version — it is every change afterwards having two homes. If the
  motive is component structure rather than React, the split above is cheaper.
- **"Make everything faster."** Not actionable as written, and the measured
  slow paths are fixed: PageRank and the similarity sweep are cached per
  notebook version, three N+1s and two O(n²) traps are gone. The next real
  work needs a profile against a large notebook, not a sweep.
- **Spacing and clashing controls across the app.** Real, and too broad as one
  item. The design tokens and the lints make each instance a small fix; raise
  them as they are noticed rather than as a project.
- **A pass over "the Gemini/antigravity improvements".** Done — see
  HISTORY.md's §40. 46 tests and 4 lints so the next such audit is cheaper.
- **The "full UI audit" umbrella.** Break into dated sub-items as capacity
  allows. The concrete pieces left: a colour-scale pass to match the existing
  spacing/type work, and a widget-density sweep.
- **"Clean up, consolidate and refactor the test files."** Asked again
  (§60's session), so this time checked with the actual method the entry
  above calls for, not re-deferred on the same reasoning twice: grepped
  every `@pytest.fixture` across all 107 files for a name reused in more
  than one — none found. The two closest near-misses (`ollama()` in both
  `test_presets.py` and `test_model_specs.py`) build genuinely different
  mocks, not a copy-paste duplicate. **The finding is that there is no
  finding** — no reinvented fixture, no `test_x`/`test_x_more` pair sharing
  setup, nothing a mechanical merge would safely collapse. The largest files
  at the time (`test_skills.py`, then in the 850-900 line range, and a
  handful of others past 700) were each single-topic and coherent, not
  grab-bags — a size-triggered split would separate a fixture from the
  twenty tests that share it for no reason but the line count. Still
  nothing to do here until a real duplication turns up. (Two of the four
  files originally named here no longer exist under those names — one
  renamed, one split by domain in a later pass — so file names are not
  repeated verbatim; the conclusion doesn't depend on which specific files
  happened to be biggest that day.)

### The rule this section exists to enforce

Anything reported goes in here with a tier, **immediately**, even if nobody is
working on it. This project's failure mode is not forgetting to write things
down — it is writing them somewhere a later session does not read, and then
rebuilding or re-deriving them. One ordered list, in the file every session is
told to open first.

## How to work on this repo

- `pytest tests/` — 2,700+ tests, fully offline, no Ollama needed
  (`pytest.ini` sets `pythonpath = src`).
- `ruff check .` — matches CI.
- `node --check frontend/app.js` — one large plain-JS file; run after every edit.
- **Install non-ML deps by hand** (see root `CLAUDE.md`) — do not install
  `torch` or `sentence-transformers`; both have failed to install cleanly in
  past sessions and the suite passes without them (semantic search falls
  back to keywords; tests that care use a fake embedding backend).
- **Drive the app in a browser before claiming a UI change works.** Chromium
  + Playwright are in the sandbox. Launch with `service_workers="block"` or
  `sw.js` serves a cached `app.js` and you'll be testing yesterday's code.
  Assert on measured geometry (`scrollWidth - clientWidth`), not screenshots.
- **Collect the console while driving.** The app sends a strict CSP; a
  refused style/script/fetch shows up *only* in the console — no failed
  request, no thrown error, the thing just silently doesn't happen.

### Traps that have each cost real time

1. **Don't guess element ids** — check `index.html` or query generically.
2. **`git checkout <file>` discards uncommitted work in that file.** Commit
   before experimenting.
3. **A POST response can lie about stored state** — SQLAlchemy returns the
   in-memory object; assert on the next GET, not the create response.
4. **`utcnow() + offset` is a lie with a timezone attached** — it tags UTC on
   a value that actually holds local wall-clock. Build the user's clock as
   `utcnow().astimezone(timezone(offset))`.
5. **The Notes tab is sub-tabbed.** Anything that scrolls to a note must call
   `showNotesSection("browse")` first, or it targets an element inside
   `display: none`.
6. **The app sends a strict CSP; a violation is reported only in the console.**
   No failed request, no thrown error. An injected `<style>` tag won't apply
   (use `adoptedStyleSheets`), `style=""` in `index.html` won't apply (use a
   class in one of `frontend/css/*.css`), and a script from off-origin is
   refused outright.
7. **CSS automatic minimum sizing is the usual cause of a wide page.** A
   `1fr` grid track or a flex item with default `min-width: auto` refuses to
   shrink below its content; `overflow-x: auto` on the child does nothing
   until every ancestor has an explicit floor.
8. **A POSIX idiom can mean something else on Windows, silently** —
   `os.kill(pid, 0)` terminates on Windows rather than probing; the sandbox
   is Linux, so this class of bug never reproduces here.
9. **A control that "does nothing" is usually working** — check the
   *computed* result. Most reported cases wrote correctly and were then
   overridden by CSS source order, a status poll repainting, or living in a
   hidden section.
10. **This suite cannot see any of the above.** Every UI bug this project has
    found passed a fully green test run first.

Full historical detail for every trap above — the original report, the
diagnosis, the fix, and what verification could and couldn't cover — is in
[roadmap/HISTORY.md](roadmap/HISTORY.md).
