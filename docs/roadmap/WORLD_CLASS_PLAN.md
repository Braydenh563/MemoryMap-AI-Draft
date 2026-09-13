# The world-class plan: from "a demo that works" to a product people switch to

**Status: written by direct instruction, for the sessions after this one
(Opus and Sonnet, with a Fable review when one is available).** The
instruction, condensed: research the competitors, find what they have that
MemoryMap does not, find how MemoryMap can stand out, and plan every aspect
of the frontend, the backend, the missing features, the poor utility and the
small things that make an app feel professional rather than like a demo; make
the backend revolutionary; revolutionise UI design, backend structure,
agentic harnessing, and the app's abilities without AI.

This document does not repeat `ANALYSIS.md §114` (the competitive teardown
and the 90-day plan) or `MODERNISATION_AUDIT.md` (findings A to H with the
measured numbers). It builds on both and goes where they stop: it names the
system underneath the small things, gives every feature a dossier with a
gate, and specifies a backend and an AI harness that are a generation ahead
of "a FastAPI app that calls Ollama". Read those two first; this one assumes
them. Every brief below is written to be handed to a session on its own.

Reading order for a fresh session: `CLAUDE.md` → `HANDOVER.md` → this
file's §0 and §8 → the dossier for the feature you were given.

---

## 0. The diagnosis in one page

Three separate audits, two nights of live use, and about forty screenshots
from the owner say the same thing in different words: **every feature is
present, and almost none of them is finished.** "Finished" here has a
precise meaning, and the rest of this document is built on it:

1. **It is one thing, not a pile of parts.** A dock is a bar, not eleven
   buttons placed near each other. A menu is a list, not a stack of buttons.
   A card is a surface with content, not a card in a card in a card.
2. **It answers the next question.** A note shows what links to it. A search
   result says why it matched. A skill run says what it did and lets you
   undo it. An empty state says what to do.
3. **It behaves like its siblings.** Same type, same look, same keys, same
   place, everywhere. The owner's rule, verbatim: "ALL ELEMENTS AND CONTROLS
   OF THE SAME TYPE AND FUNCTION NEED TO BE, ACT, AND PLACED THE SAME
   APP-WIDE."
4. **It is designed for the screen it is on.** A phone gets a phone layout,
   not the desktop one squeezed until chrome is 76% of the page.
5. **It can be reached without a mouse and read without perfect eyes.**
   Arrow keys walk every strip; contrast is measured, not assumed.
6. **It never lies about state.** Saved means saved; running means running;
   an error says what failed and what to do.

The owner's own summary of what a professional app is: "the accessibility
and availability of things, placement and grouping of elements, consistent
design, things flowing and feeling connected." Those are not polish tasks
at the end; they are the acceptance criteria for every brief here.

### Why the app feels "off" even where each screen is fine

The owner said he "can't quite place or identify" it. Having measured, it is
five things, and none is a single screen's fault:

- **Too many surfaces.** Glass on a card on a panel on a page. Every layer
  has its own border and radius, so a settings row reads as a button inside
  a card inside a card. The fix is a surface budget: page, panel, card,
  control. Four levels, and a control never draws a box inside a card unless
  it is interactive.
- **Everything is a button.** Meta chips ("2 steps", "Never run"), model
  names, tags, statuses: all drawn with the button recipe. The eye reads
  forty affordances on a screen with six actions. Fix: a "meta" recipe with
  no border and no hover, and a lint that a `<span>` never carries a button
  class.
- **Filled accent everywhere.** Menu items, active chips, toggles, tiles,
  "Run" buttons, all in the same lavender fill, so the one primary action on
  a screen has no way to be found. Fix: one filled control per surface; the
  rest ghost or tinted.
- **Prose where a control should be.** Two-line explanations above and
  below every setting, so a settings page scrolls three screens for eight
  toggles. Fix: one line max, the rest behind the '?' popover.
- **Wrap instead of layout.** Below 1024 the docks and footers wrap into
  stacks; below 600 nothing changes at all. Fix: Phase 9, designed per
  breakpoint.

The same five, with a lint for each, are the "consistency contract" in §1.

---

## 1. The consistency contract (the system under the little things)

Every earlier plan fixed screens. This one fixes the vocabulary, then makes
the screens follow it. The contract is short enough to memorise and each
line has a lint that fails the build, because the app has been made
inconsistent three times by sessions that did not know the rule existed.

### 1.1 Surfaces (four levels, no more)

| Level | Recipe | Example | Never |
| --- | --- | --- | --- |
| Page | `--bg`, the gutter, nothing else | a tab page | a page border |
| Panel | card fill, glass edge, `--radius`, shadow at rest | a dock, a sidebar, a modal | a panel inside a panel |
| Card | card fill, hairline edge, `--radius-md`, no shadow | a note, a tile, a settings section | a card inside a card |
| Control | one of six recipes below | a button, a field | a control drawing its own card |

Lint: `tests/test_surface_budget.py` walks `index.html` and fails on
`.card .card`, `.panel .panel`, `.card details > summary.btn`, and on any
`.glass` inside `.glass`.

### 1.2 Controls (six recipes, one height)

| Recipe | Use | Rest | Hover | Active |
| --- | --- | --- | --- | --- |
| primary | the one action on the surface | accent-surface fill, on-accent ink | brightness | pressed |
| ghost | every other button | no fill, ink | ghost-bg | accent-soft |
| icon | utilities (refresh, help, more) | ghost, square, `--control-h-lg` | ghost-bg | accent-soft |
| field | text/search/select | inset fill, one border, one radius | border ink | accent ring |
| segment | 2 to 5 exclusive choices | one track, ghost items | item ghost-bg | item accent-soft, ink |
| meta | chips, counts, statuses | no border, no hover, muted | none | none |

All six share `--control-h-lg` (36px) on docks and `--control-h` in forms,
`--radius-md`, the same focus ring, the same icon size (1em) and gap
(`--space-2`), and the icon-text centring rule. Lint:
`tests/test_ui_signatures.py` already counts recipes; extend it to assert at
most ONE primary per `[data-dock-name]` and per `.modal`, and that no
`.chip`/`.meta` has a `border` or a `:hover` rule.

### 1.3 Menus (one recipe)

A menu is `.menu` (panel surface, `--space-1` padding, min-width 14rem) with
`.menu-item` rows (ghost, full width, left aligned, icon column 1.25em,
label, optional right-aligned shortcut or check) and `.menu-sep` hairlines.
Opened by a `details` or a button with `aria-expanded`; closes on pick,
outside click and Escape; flips when it would overflow; arrow keys walk it;
typeahead selects. Every menu in the app (dock more, doc toolbar, whiteboard
Insert/Edit/Arrange/View/Board, chat, context menus, nav history) is this
recipe. Lint: a menu item with a non-transparent rest background fails
`test_ui_signatures.py`.

### 1.4 Bars (docks, heads, toolbars, footers)

A bar is one continuous panel surface. Zones inside it (identity, find,
arrange, actions) are separated by a hairline and equal gaps, never by
boxes. Controls inside are ghost, fields are inset, exactly one primary.
The identity zone never shrinks below its title. A form footer is a bar:
secondary on the left, primary at the far right, and nothing floats over
the primary (the scroll-to-top button hides while a footer is in view).
Lint: `tests/test_dock_grammar.py` (exists) plus a Playwright count in
`docks.js` of distinct control heights per bar (must be 1).

### 1.5 Copy

Sentence case. No em-dashes (lint: `tests/test_no_em_dashes.py` over
`frontend/` and `src/`). One line of description per section, 70 characters
or fewer; longer help goes behind the '?' popover (`data-help-for`). Empty
states name the next action and carry a button for it. Errors say what
failed and what to do, in that order. Numbers use tabular figures.

### 1.6 Keys (the same everywhere)

`/` focuses the surface's search. Arrows walk tablists, menus, lists,
grids. `Enter` opens, `Space` selects, `Escape` closes the innermost thing.
`Ctrl+K` command palette. `Ctrl+N` new note, `Ctrl+S` save, `Ctrl+B/I`
format. `+`/`-`/`0` zoom on canvases, `F` focus selection. `?` opens the
surface's help. Lint: `tests/test_keymap.py` parses a single `KEYMAP` table
in `app.js` and asserts no key is bound twice on the same surface.

### 1.7 Responsive (designed, not wrapped)

Four layouts: phone (≤ 600), tablet portrait (≤ 900), laptop (≤ 1280),
desktop. Each surface declares what it becomes at each: a dock becomes
identity + search + primary + more; a sidebar becomes a sheet; a grid
becomes a list; a canvas tool strip moves to the bottom; the tab bar
becomes a bottom bar with five items and "more". Chrome-to-content ratio
on a phone must be under 35% on every tab (measured by
`scratchpad/audit/chrome.js`; today 76%).

---

## 2. Competitors: what they have that MemoryMap does not (checked, not
assumed)

`§114.1` has the positioning teardown. This is the feature-level gap list,
organised by what a switcher would miss on day one. "Have" means shipped
and used, as of mid-2026.

| Capability | Obsidian | Notion | OneNote | Kortex | Logseq | Capacities | Reflect | MemoryMap today | Gap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Block editor with slash commands | plugin | yes | no | yes | yes | yes | yes | textarea + toolbar | DOCUMENTS_PLAN Phases 2 to 4 |
| Wiki-links with autocomplete and backlinks pane | yes | yes | no | yes | yes | yes | yes | links exist, no `[[` autocomplete, no pane | Dossier D2 |
| Daily notes / journal with a calendar | plugin | template | no | yes | yes | yes | yes | none | Dossier D6 |
| Properties / typed fields per note | yes | databases | no | yes | yes | object types | tags | category + tags | Dossier D5 (typed properties) |
| Database views (table, board, calendar) | plugin | yes | no | partial | query | yes | no | Timeline table (in progress) | Dossier D7 |
| Canvas / whiteboard | yes | no | yes (ink) | yes | yes | no | no | yes | keep, refine |
| Mind map | plugin | no | no | no | no | no | no | yes | keep, refine (a differentiator) |
| Graph view | yes | no | no | yes | yes | yes | no | yes (SVG) | GRAPH_PLAN |
| Local AI chat over notes | plugin | hosted | Copilot | hosted | plugin | hosted | hosted | yes, offline | keep; make checkable |
| Per-claim citations in answers | no | partial | no | partial | no | partial | partial | source list only | §114 F2-1 |
| Web clipper / read-it-later | yes | yes | yes | yes | no | yes | yes | bookmarks only | Dossier D9 |
| PDF annotation | plugin | no | yes | yes | yes | no | no | text extraction only | Dossier D10 |
| Voice capture with transcript | plugin | yes | yes | no | no | no | yes | yes (Whisper) | keep; add the meeting block |
| Templates | yes | yes | no | yes | yes | yes | yes | yes | keep |
| Spaced repetition / recall | plugin | no | no | no | yes | no | no | none | §114 A1 |
| Sync across devices | paid | yes | yes | yes | yes | yes | yes | none | Dossier B6 (local-first sync) |
| Mobile app | yes | yes | yes | yes | yes | yes | yes | responsive web only | Phase 9, then a PWA shell |
| Import from Notion/Obsidian/Evernote | yes | yes | partial | yes | yes | yes | yes | Markdown folder only | §114 F5-3 |
| Version history per note | yes | yes | yes | yes | git | yes | yes | drafts only | Dossier B4 (event log) |
| Command palette | yes | yes | no | yes | yes | yes | yes | yes | keep; make it complete |
| Plugin / extension API | yes | limited | no | no | yes | no | no | MCP server | Dossier B8 |

**Where MemoryMap can stand out** (the things no one on that table has, all
of which the code is already half way to):

1. **The checkable answer.** Every sentence of an AI answer carries the
   note it came from, an "I don't know" is a designed state, and a click
   shows why a result ranked. (§114 combo 1.)
2. **A notebook that files itself and can be audited.** Auto-filing with
   an undo trail and a "why did this go here" for every decision. Nobody
   else does the second half.
3. **Contradictions and tensions as a first-class object.** The
   "disagreed with myself" skill made into a live index and a Dashboard
   widget. (§114 F7-1.)
4. **Mind maps that are notes.** A map node is an entry; a map is a view of
   the notebook. Coggle and XMind cannot link a branch to a note; Obsidian
   cannot make a map at all without a plugin.
5. **A privacy receipt.** A page that proves, from the app's own logs,
   that nothing left the machine. Hosted competitors cannot ship this.
6. **The offline studio.** Audio overview, recall cards, a "brief me before
   the meeting" from the notes, all local. (§114 combo 3.)

---

## 3. Frontend dossiers (one per surface, each a hand-off brief)

Each dossier: what exists → what is wrong (measured) → the target →
the brief → the gate. Effort is in sessions (S ≈ half a session, M ≈ one,
L ≈ two or more). "Owner" is the model that should do it.

### D1 Dashboard (M, Sonnet after a Fable/Opus design pass)

Exists: hero, Start something tiles, Jump to pills, Run a skill, stat
tiles, 24 widgets with a layout editor. Wrong: three launch rows plus a stat
row is four kinds of chip on one screen; widgets are 24 separate recipes;
the widgets dialog is a settings page inside a modal; the "Boards & maps"
widget shows raw thumbnails. Target: a dashboard that reads top to bottom
as greeting → what needs you (due reminders, drafts, tensions) → start →
your notebook (widgets), with one tile recipe and one widget frame (title,
optional count, optional "more" link, body). Brief: one `.widget` frame
component in `dashboard.js`; every widget renders into it; the layout
editor becomes drag-to-reorder on the grid itself with a "customise" mode
toggle; the widgets dialog keeps only add/remove. Gate: recipe count on
Dashboard ≤ 8 (audit script), all 24 widgets in the frame, 390px chrome ratio
< 35%.

### D2 Notes: list, capture, edit (L, Opus)

Exists: the list with card/list views, filters, select mode, capture with
templates, the edit form, connections. Wrong: a note shows no backlinks
inline; `[[` has no autocomplete; the capture footer is two wrapped rows
with a FAB over the Save button; the edit form's gutter drifts. Target:
capture is one field with a slash menu and `[[` autocomplete, a one-row
footer; a note's page has a connections rail (backlinks, links, related by
similarity, in the same map) that is always visible on desktop and a sheet
on phone. Brief: `[[` autocomplete over `/entries?q=` with keyboard
selection; a `.connections-rail` component rendered from `/entries/{id}/links`
(exists) and `/entries/{id}/related`; the footer on the bar recipe. Gate:
typing `[[te` shows matches within 150ms on a 2,000-note fixture; the rail
renders for every note; the FAB never overlaps a primary (Playwright
intersection check).

### D3 Chat (M, Opus)

Exists: streaming answers, sources list, scope chips (backend), personas,
skills picker, tool cards, conversation sidebar. Wrong: no per-claim
citation; the composer's three rows of chips crowd the input; the sidebar
head is not on the dock grammar (in progress). Target: an answer whose
sentences carry superscript source marks that highlight the note on hover;
a composer that is one field with a "+" menu (attach, scope, persona,
skill) and a send button; the "I don't know" state designed. Brief: §114
F2-1 with `routes_chat.py` emitting `cite` events per sentence; composer
rebuilt on the bar recipe. Gate: 95% of sentences in ten fixture answers
carry a citation; composer height ≤ 2 rows at rest at 1024.

### D4 Library (M, Sonnet)

Exists: All, Documents, Boards & maps, Images, Files, AI skills, Links,
Contents sub-tabs, each with its own head. Wrong: eight heads, five
recipes; image cards are 900px tall with "Show more" links and chip-buttons;
skills cards have button-shaped meta. Target: one head (the dock grammar),
one card per kind on one card recipe with a fixed preview aspect (16:10),
title, two meta lines, actions in a "..." menu; the image and file cards
open a detail sheet instead of expanding in place. Gate: card height
uniform per view (± 4px), one head recipe, `docks.js` count = 1 per
sub-tab.

### D5 Properties and tags (M, Opus)

Exists: category, tags, pinned, private, space. Wrong: tags are strings; no
typed fields; no way to say "this note is a person/project/book". Target:
typed properties per note (text, number, date, select, relation), stored
as JSON on the entry (`properties` column, indexed via a generated
`properties_text` for FTS), a property editor in the note head, and a
"kind" property with built-in kinds (person, project, meeting, book, place)
that drive the Library's grouping and the graph's colour rules. Brief:
migration + `/entries/{id}/properties` + editor. Gate: a property
round-trips through the API, FTS finds it, the graph colours by it.

### D6 Daily notes and the journal (S, Sonnet)

Exists: nothing. Target: `Ctrl+D` opens today's note (created from the
Journal template if missing), a calendar strip on the Timeline dock to jump
between days, a "yesterday / tomorrow" pair of links in the note head, a
streak that counts days with a daily note. Brief: `/entries/daily/{date}`
that creates or returns; the calendar strip as a `.segment` of seven with
overflow into a month popover. Gate: the key works from every tab; the
calendar reflects the DB.

### D7 Timeline (L, in progress: see TIMELINE_PLAN.md)

### D8 Reminders (S, Sonnet)

Exists: natural-language add, presets menu, list with views. Wrong: the
list and the notes list use different rows; done items vanish rather than
strike through; no snooze. Target: reminder rows on the same row recipe as
notes, snooze (10m, 1h, tomorrow) in the row menu, done rows strike
through and fade, a "today" band at the top. Gate: row recipe shared
(one class), snooze round-trips.

### D9 Links and the web clipper (M, Opus)

Exists: bookmarks with groups. Target: a "Save page" bookmarklet and a
share-target (PWA) that POSTs a URL; the backend fetches (SearXNG-safe,
offline-tolerant) and stores a readable extract as a document with the
source URL, so links become searchable notes. Brief: `/links/clip` +
readability extraction (vendored, MIT) + a bookmarklet generator in
Settings. Gate: a clipped page is found by search within 2s.

### D10 Documents and PDFs (L, see DOCUMENTS_PLAN.md; add PDF annotation as
Phase 8: highlight → note with page anchor, rendered by pdf.js vendored)

### D11 Whiteboard and mind maps (M, in progress; then MINDMAP_PLAN Phases
4 to 5)

### D12 Graph (L, GRAPH_PLAN.md)

### D13 Settings (M, Sonnet)

Exists: 3,229 lines of settings.js, ~40 sections. Wrong: prose-heavy,
toggle rows in two recipes, model backend card has three paragraphs.
Target: a two-pane settings (section list left, one section right, search
across all), every section = title + one line + controls, help behind '?',
danger actions in a separate red-edged group at the bottom of their
section. Gate: no paragraph over 120 characters outside a popover; one
toggle-row recipe; the section list is a tablist with arrow keys.

### D14 Help, onboarding and the command palette (S, Sonnet)

Exists: help accordion, onboarding overlay, `Ctrl+K`. Wrong: the accordion
is cards in cards; the palette lacks half the actions. Target: help as a
searchable list on the panel surface with flat rows; the palette generated
from the same `ACTIONS` table the menus use, so nothing can be missing.
Gate: every `data-action` in the DOM appears in the palette.

### D15 The shell: top bar, tab bar, bottom bar, sidebars (M, Opus)

Exists: top bar with wordmark, search, utilities (bell, theme, settings,
lock, power) as five square buttons; tab bar; resizable sidebars. Wrong:
the utility cluster is five boxes; on phone the tab bar overflows. Target:
utilities as an icon cluster with hairline separators on the bar surface;
a bottom tab bar on phone (five + more); sidebars as sheets under 900.
Gate: Phase 9 numbers.

---

## 4. The backend, made revolutionary (and still SQLite, still offline)

"Revolutionary" here means: architectural moves that make whole classes of
feature cheap that are expensive today, without a server, a cloud or a
second database. Five moves, in dependency order.

### B1 The event log: every change is a fact, the tables are views

**Built.** Moved to HISTORY.md, "From WORLD_CLASS_PLAN.md B1 and
SESSION_BRIEFS Brief 7: the event log". One table rather than two:
`AuditLog` gained `actor` and `payload`, `core/events.py` is the only
writer and holds `replay`, every public write in `entry/manager.py`
records exactly one event with whole-field values, a purge is one event
with the id list, and `tests/test_events.py` (the spec, formerly strict
xfail throughout) passes with no markers left. History, restore by event
and `GET /events?since=` are live; what the log does not yet feed (sync,
global undo of an AI action, the Timeline strip) is in
`docs/roadmap/agent-remaining/brief7-event-log.md`.

### B2 The job runtime: durable, resumable, observable

Today long work runs in threads with no persistence (MODERNISATION_AUDIT
D2). Move: a `jobs` table (`id, kind, state, progress, payload, result,
error, attempts, run_after, heartbeat`), a single worker thread per process
that leases jobs, a `@job` decorator that makes any function durable, and
SSE `/jobs/stream` for the UI. Jobs: re-index, embed, OCR, caption,
auto-file, skill run, import, backup, model download. Every job is
cancellable, survives a restart, and reports progress in one shape the
"Running now" panel renders. Gate: kill the server mid-OCR, restart, the
job resumes; the panel shows it.

### B3 The retrieval engine: one index, three signals, explained

**Built.** Moved to HISTORY.md, "From WORLD_CLASS_PLAN.md B3 and
SESSION_BRIEFS Brief 11: the retrieval engine". `search/index.py` holds one
FTS5 index over notes, boards, documents, files' extracted text, bookmarks
and reminders, kept in step by the ORM flush; `search/engine.py` returns
`Hit`s carrying bm25, cosine and graph proximity with the words that explain
them; `GET /search` and `/search/stats` serve it; the vector matrix replaced
three per-request scans of every stored vector.
`tests/test_search_engine_spec.py` passes with no markers left. Measured on
the sandbox: keyword 0.6ms and hybrid 0.6ms on 5,000 entries (gates 50 and
200), similarity for one note 18.0ms to 0.0ms. What is left is in
`docs/roadmap/agent-remaining/brief11-retrieval-engine.md`.

**Decisions made** (the three the plan had made differently, revised against
the code and taken; the reasons are in HISTORY):

- A second FTS5 table (`search_index`), not a `kind` column on
  `entries_fts`: that one is external-content over `entries`, so its rowid
  is an entry id and a document could not have a row.
- The index's write path is an `after_flush` hook, not the event log: a
  document edit records no event, so an event-fed index would have gone
  stale on the commonest document write. Brief 7's loud driver is kept
  (`source_for` raises on an unregistered kind).
- `before:`/`after:` are exclusive, `until:`/`since:` inclusive; an
  unreadable date is left in the text rather than guessed at; a query with
  operators is never "time only".

### B4 The knowledge kernel: entities, claims, links, tensions

Today entities and links exist as tables written by skills. Move: a small
kernel that maintains, from the event log, derived tables: `entities`
(people, projects, places, terms; merged by alias), `claims` (a sentence
plus its note, extracted by the model when idle, with a confidence),
`links` (typed: refers-to, contradicts, supports, follows, part-of), and
`tensions` (pairs of claims the model judged incompatible). All derived,
all rebuildable, all with a "computed by <model> at <ts>" stamp shown in the
UI. This is what makes the Tensions widget, derived person/project pages,
per-claim citations and "what changed about X" possible. Gate: rebuild from
scratch on the fixture is deterministic; every derived row cites its
source event.

### B5 The AI harness: plan, act, verify, budget, learn

Today: a step is a turn (MODERNISATION_AUDIT E1); tool contracts exist
(AGENT_SKILLS_REFORM Phases A to C). Move:

- **Typed tools with contracts** (exists) plus **pre/post conditions**
  checked in Python, not by the model: a `file_note` tool refuses a
  category that does not exist; a `merge_notes` tool requires both ids to
  be live.
- **A planner that emits a plan object** (exists as A2) that the executor
  runs step by step with a **token and time budget** per run, a **verifier**
  step that re-reads the changed rows and checks the skill's stated
  postcondition (e.g. "every note now has ≥ 1 tag"), and a **repair loop**
  of at most two rounds.
- **Small-model mode** (exists) made the default under 8B: one tool per
  turn, forced JSON via grammar when the backend supports it (llama.cpp
  and Ollama both do), few-shot from the skill's own eval cases.
- **Evals as fixtures** (A6 exists): every skill ships with three
  notebooks and expected outcomes; `pytest -m evals` runs them against
  the fake transport; a nightly local run against a real model writes
  `docs/MODELS.md` (the "I don't know" bench, §114 F2-2).
- **Learning from corrections**: when a user moves an auto-filed note,
  the kernel records a `correction` event; the filing prompt is built with
  the last N corrections for that category (§114 F1-1). No training, no
  telemetry, and the notebook gets better at filing itself.

Gate: on the eval fixtures, a 3B model completes ≥ 80% of built-in skills
with zero invalid tool calls; every run shows plan, steps, verification and
an undo button.

### B6 Local-first sync (L, later; design now)

Because B1 makes every change an event, sync is: export the log since a
cursor as an encrypted file, import elsewhere, resolve by last-writer-wins
per field with the event history kept (no CRDT needed for a single-user
notebook; conflicts become two versions in History). Transport: a folder
(iCloud/Dropbox/Syncthing) or a LAN pairing over the existing server with a
QR code. Gate: two instances round-trip 1,000 events with no loss.

### B7 The API contract

One error shape (exists, B3 in PLAN.md), cursor pagination on every list
(finish D4 in the audit), ETags on entries, `If-Match` on writes (so the
editor cannot clobber a background AI edit), an OpenAPI schema behind the
auth gate, and a `/capabilities` endpoint the UI reads once so features
appear only when their backend is there (OCR, embeddings, TTS).

### B8 Extensions

The MCP server exists. Move: the same tool registry that serves MCP serves
a `/tools` HTTP API and a "user skills" folder of Markdown skills (already
the skill format). That is the plugin API: a skill is a Markdown file with
tool calls; a tool is a Python function registered with a contract. Gate:
a skill dropped into the folder appears in the picker without a restart.

---

## 5. Abilities without AI (the app must be excellent with the model off)

The owner's phrase: "features of the application even without AI." Today
too much routes through the model. Each of these is pure code:

1. **Search operators** everywhere: `tag:`, `kind:`, `in:space`, `before:`,
   `after:`, `has:file`, `is:pinned`, quoted phrases, `-not`. One parser,
   used by Notes, Library, Timeline, Chat scope, the palette.
2. **Saved searches as smart folders** in the Notes sidebar (backend exists).
3. **Backlinks and unlinked mentions** (a plain FTS query for the title).
4. **Templates with variables** (`{{date}}`, `{{title}}`, `{{clipboard}}`,
   cursor position).
5. **Bulk actions** from any selection: tag, move, merge, export, delete,
   make a map, add to board.
6. **Export** any selection as Markdown folder, one document, PDF (print
   CSS), OPML for maps, PNG for boards.
7. **Import** Markdown folders with wiki-links preserved, Notion zips,
   Evernote enex, Apple Notes HTML.
8. **Keyboard everything** (§1.6) and a **shortcut sheet** on `?`.
9. **Word count, reading time, outline** for every document (exists for
   documents; extend to notes).
10. **A real trash** with restore and 30-day purge (exists as bin; make it
    consistent for every kind).

---

## 6. Measuring "professional" without telemetry

Every gate above is a number a script produces on the sandbox. The ones
worth a Dashboard-of-the-project (a Markdown table in `HANDOVER.md`,
updated per session):

| Metric | Script | Today | Target |
| --- | --- | --- | --- |
| Distinct control recipes on the busiest screen | `scratchpad/audit/recipes.js` | 22 (Chat) | ≤ 8 |
| Control heights per bar | `docks.js` | 1 to 4 | 1 |
| Chrome ratio at 390 | `audit/chrome.js` | 76% | < 35% |
| Paragraphs > 120 chars outside popovers | `audit/prose.js` | ~60 | 0 |
| Em-dashes in `frontend/` + `src/` | `test_no_em_dashes.py` | ~9,000 | 0 |
| Contrast failures, both themes | `contrast.js` | 0 after fix | 0 |
| Console errors across all tabs at 3 widths | `errors.js` | 0 | 0 |
| Tablists without arrow keys | `audit/keys.js` | 0 after fix | 0 |
| Idle requests per minute | `audit/idle.js` | 4 on 2026-09-12 (`/models/status` every 30s, `/reminders` and `/tasks` once a minute; was 14) | ≤ 2 |
| First paint of Graph on 2k notes | `graph-fixture.js` | n/a (SVG) | < 300ms |
| Search p95 on 5k notes | `tests/test_search_perf.py` | 14.2 ms median at 3,000 notes, 4 statements, flat (8.4 at 200, 10.5 at 1,000), 2026-09-12 | < 200ms |
| Capture write cost | the same probe against `POST /entries` | 9.0 ms and 16 statements at 1,206 notes, identical at 56 and 406, 2026-09-12 | flat |
| Resurfacing read | `ai/resurface` | 6.7 ms at 800 notes after its index; 23.0 ms with no LIMIT and 58.7 ms with a LIMIT and no index | flat |
| Skill eval pass rate, 3B model | `pytest -m evals` | n/a | ≥ 80% |

---

## 7. The small things (a checklist that sessions keep reopening)

Each of these has been reported by the owner at least once. They are cheap
and they are what "refined" means. A session that has an hour left should
take five of these.

- Icon and label centred in every button, chip and menu item (measure).
- Focus rings visible on every control in both themes.
- Hover states on every clickable thing; cursor pointer only on clickable
  things.
- Disabled looks disabled and says why on hover.
- Every list has an empty state with an action; every empty state uses the
  same recipe.
- Every destructive action confirms in the same dialog recipe and offers
  undo where possible.
- Every async action shows progress in the same place (the button itself
  for < 2s, the Running-now panel for longer).
- Toasts: one recipe, bottom centre on phone, bottom right on desktop,
  with an action where one applies.
- Dates: relative under 7 days, absolute after; one formatter.
- Numbers: tabular figures in tables and stats.
- Truncation: titles ellipsise, never clip; the full text in `title`.
- Scroll: only the content scrolls, never the page under a dock; sticky
  heads stick.
- Selection: text is selectable everywhere text is (no `user-select: none`
  on content, including mind map nodes).
- Keyboard: Escape always closes the innermost thing; Enter in a single
  field dialog submits it.
- Touch: 44px targets on phone, no hover-only affordances.
- Motion: 150ms ease-out for state, 250ms for layout, none under
  reduced-motion.
- Copy: sentence case, no em-dashes, no "Oops", no exclamation marks.
- Modals: one width scale (24, 32, 44rem), title + body + footer, footer
  actions right-aligned with the primary last.
- Forms: labels above fields, one column under 600, required marked,
  errors inline under the field.
- Links: underlined on hover only, accent colour, external ones marked.

---

## 8. Execution order for the coming week (Opus/Sonnet sessions)

Assumes the in-flight agents (Phase 8 docks, Phase 9 responsive, Documents
Phase 0, Graph Phase 1, menus/bars consistency, mindmap bugs, timeline
redesign, tooltips/copy) have merged. Each row is one session or less.

| # | Brief | Owner | Gate |
| --- | --- | --- | --- |
| 1 | §1 lints: surface budget, one-primary, meta-no-hover, no-em-dash, keymap | Sonnet | all green on main |
| 2 | §7 checklist, first ten items, measured | Sonnet | audit scripts |
| 3 | D13 Settings two-pane | Sonnet | prose metric 0 |
| 4 | D2 Notes: `[[` autocomplete + connections rail | Opus | 150ms, rail on every note |
| 5 | B1 event log | Opus | built (HISTORY.md) |
| 6 | B2 job runtime | Opus | resume after kill |
| 7 | D3 Chat per-claim citations + composer | Opus | 95% cited |
| 8 | B3 retrieval engine with explanations | Opus | perf gates |
| 9 | D5 typed properties + D6 daily notes | Opus then Sonnet | round-trips |
| 10 | D4 Library one card recipe | Sonnet | uniform heights |
| 11 | D1 Dashboard widget frame | Sonnet | ≤ 8 recipes |
| 12 | B4 knowledge kernel + Tensions widget | Opus | deterministic rebuild |
| 13 | B5 harness: verifier, budget, corrections | Opus | evals ≥ 80% |
| 14 | D9 clipper, D8 reminders, D14 palette from ACTIONS | Sonnet | per dossier |
| 15 | GRAPH_PLAN Phases 2 to 5 | Opus | frame-rate gates |
| 16 | DOCUMENTS_PLAN Phases 1 to 7 | Opus | per phase |
| 17 | B7 API contract, B8 extensions | Sonnet | schema behind auth |
| 18 | PWA shell + share target; B6 sync design doc | Opus | installable, clip works |

Rules for every session: read `CLAUDE.md`; check the running app before
building; merge the branch first; commit after every step; measure before
claiming; no em-dashes; update `HANDOVER.md` with what was measured and
what could not be verified.

---

## 9. On testing with a real model in the sandbox

The owner asked whether to install llama.cpp and a local model in the
project so sessions can test against a real model. Answer: not in the
repository (a GGUF is hundreds of MB to GBs and would break the clone,
CI and the AGPL notices), but yes as a **dev-only script**:
`scratchpad/llama-dev.sh` builds or downloads a llama.cpp `llama-server`
release for the sandbox's CPU, fetches one small instruct GGUF
(Qwen2.5-1.5B-Instruct Q4 or Llama-3.2-1B-Instruct Q4, about 1 GB) into the
scratch directory, and starts it on a port the app's OpenAI-compatible
provider can be pointed at. The sandbox's network policy and disk allowance
decide whether it works; the script must fail loudly and the suite must
never depend on it. It lifts the last half of CLAUDE.md's standing caveat
(real inference) for skills evals, and `pytest -m evals --real` would use
it. Add it as row 0 of §8 for the first session with network access.

---

## 10. Flaws found by static probes (cheap to reproduce, each with its command)

Run from the repo root. Each line is a class of bug, not a single bug; the
count is the size of the class today. A session that takes one of these
should fix the class and add the lint that keeps it fixed.

| # | Flaw | Evidence | Why it matters | Fix (and lint) |
| --- | --- | --- | --- | --- |
| F1 | 57 distinct `localStorage` keys read ad hoc, 14 of them `JSON.parse`d | `grep -o 'localStorage.getItem("[^"]*")' frontend/*.js \| sort -u \| wc -l` | This is the shape of the worst UI bug in the project's history (two settings missing from `APPEARANCE_DEFAULTS` wrote `NaN` into CSS): a value invalid where it is used, set somewhere else. Corrupt or missing storage throws inside JSON.parse and takes the caller's whole init with it. | One `prefs` module: a schema with defaults and a version per key, `prefs.get(key)` never throws and never returns undefined, migration on version bump. Lint: no direct `localStorage.getItem` outside `prefs.js`. |
| F2 | 25 list endpoints, 3 accept `limit` | `grep -n "^def list_" -A 6 src/memorymap/api/routes_*.py \| grep -c limit` | Every list is O(notebook). A 5k-note notebook makes the Library, Timeline and Graph tabs multi-second. (MODERNISATION_AUDIT D4.) | Cursor pagination on all 25 with one helper, `?limit=&cursor=`, `next_cursor` in the body; the frontend's list renderers page on scroll. Lint: a test enumerates routers and asserts every `list_*` takes `limit`. |
| F3 | **Measured, 2026-09-12, and smaller than this row assumed at a realistic size.** `search_manager.semantic_search` still reads and parses every vector row per request, and it is on the Ask and chat path. At 2,000 notes and 384 dimensions that read and parse is 5.6 ms per request against 5.3 ms for the matmul over the same vectors already in memory, so it is about half the cost of a search at that size and grows linearly: about 56 ms at 20k and 140 ms at 50k. The three whole-notebook features (link suggestions, tensions, graph edges) already read `engine.vectors_by_id`, which serves the process-level matrix, so the fix is to point `semantic_search` at the same matrix. **Not done here, deliberately**: it is the most important path in the app and the swap has to keep the mixed-width behaviour this function grew (a model swap inside one backend leaves rows at the old width, and stacking them raised and took every search down with it), so it wants its own brief and its own tests rather than a late-night edit. | `search/search_manager.py` ~279, `search/engine.py` `vectors_by_id` | still open, sized |
| F4 | 88 `except Exception:` / bare `except:` in `src/` | `grep -rn "except Exception:\|except:" src/memorymap --include=*.py \| wc -l` | Failures become silence (the "features that never ran once" shape). | Each one either re-raises as the error contract, logs with `exc_info` to the logbuffer, or is narrowed. Lint: ruff `BLE001` enabled with a per-site `# noqa: BLE001 <reason>`. |
| F5 | 13 raw `fetch()` calls beside `api()` | `grep -n 'fetch(\`\|fetch("' frontend/*.js \| grep -v "api\b"` | Each re-implements the auth header, the error contract and the offline path; one is `/chat/stream`, the most important call in the app. | `api.stream()` and `api.upload()` helpers; the 13 sites move onto them. Lint: no bare `fetch(` outside `api.js`. |
| F6 | **Mostly fixed, and the old figure was stale.** Measured 2026-09-12 with `scratchpad/ui-sweeps/idle.js` (new: it wraps `setInterval` before any page script runs, so every live interval is named with the line that started it, and counts requests over a full idle minute in each visibility state). Requests: 4 in a visible minute (`/models/status` x2, `/reminders`, `/tasks`) and 2 hidden, not the 14 this row was written from, which the status poll's own backoff had already fixed. Timers: two one-second clocks survived hiding, `tickClocks` (app.js) and `paintDashClock` (dashboard.js), both painting HH:MM once a second to a tab nobody could see. Both now stop on `visibilitychange` and repaint on return; the only interval left while hidden is the 60s reminder check, which is the one thing a background tab should keep doing. What is left of this row is the `scheduler` it proposes, which is a refactor rather than a fix. | `idle.js`, `app.js`, `dashboard.js` | was battery | timers done, scheduler open |
| F7 | Threads in 16 modules share SQLAlchemy sessions created per call | `grep -rln "threading.Thread" src/memorymap` | SQLite is fine with this only while each thread opens its own session and nobody passes ORM objects across; nothing enforces it, and the "Could not refresh instance" 500 seen this session was exactly that shape. | B2 job runtime: one worker, jobs get a fresh session, results are plain dicts. Lint: `Thread(` allowed only in `core/jobs.py`. |
| F8 | Two `innerHTML` writes with interpolated data | `grep -n 'innerHTML\s*=\s*\`[^\`]*\${' frontend/*.js` | Both interpolate app-controlled strings today; the pattern is the XSS shape and the next author will interpolate a title. | `setLabel()` (exists) at both sites. Lint: no `innerHTML =` with `${` anywhere. |
| F9 | **Fixed.** The gate is per router (`dependencies=locked`), and a router added without it read exactly like one with it. `tests/test_every_route_is_locked.py` walks every route the app serves and asserts 401 without a token, against an allowlist that carries a reason per line. It found one: `GET /changelog`, open, now locked. Proven in both directions (dropping `dependencies=locked` from one router fails it with that router's three routes named). The walk itself is the subtle half: this FastAPI keeps an included router as one lazy entry, so the obvious `isinstance(route, APIRoute)` filter sees 3 routes out of 200 and passes with the whole API unchecked. | `api/app.py`, `tests/test_every_route_is_locked.py` | was medium | done |
| F10 | Extracted text, captions and OCR live in three columns with three UIs | `grep -n "vision_ocr_text\|ocr_text\|caption" src/memorymap/api/routes_files.py \| wc -l` | The Files card shows one, hides one, and the search indexes some; the owner's "only the first line" report was one symptom. | One `readings` table (`media_id, kind, page, text, model, ts`), one renderer, all kinds indexed (B3). |
| F11 | The graph, dashboard constellation and map thumbnails are three renderers | `grep -c "forceSimulation" frontend/graph.js frontend/dashboard.js frontend/whiteboard.js` | Three physics, three colour maps, three sets of bugs. | GRAPH_PLAN §3: one renderer with `size: "pane" | "tile" | "full"`. |
| F12 | Frontend state lives in module globals, DOM and localStorage with no single owner | MODERNISATION_AUDIT C2 | Every "the list did not refresh" bug. | A small store: `state.get/set/subscribe` per slice, renderers subscribe; introduced slice by slice (notes list first). |

Two flaws this session found by driving the app, recorded here so they are
fixed as classes: a new board was created through a path that also created
a note (entries and boards share a table and a create path; the filter
belongs in one place), and a dialog's `<details>` did not close on Escape
(now handled globally; the lint is "every `details` menu closes on Escape",
in `docks.js`).

---

## 11. The week, session by session (Opus/Sonnet), and the quarter

Assumes the in-flight agents have merged and PR #144 is green. One row is
one session; a session ends with the gate green, a commit, and a HANDOVER
line. Order matters: each row leaves the next one cheaper.

| Day | Session | Model | Gate |
| --- | --- | --- | --- |
| Mon | Em-dash sweep (`scratchpad/emdash.py`), `test_no_em_dashes.py`, full suite | Sonnet | 0 em-dashes in frontend+src, suite green |
| Mon | §1 lints: surface budget, one primary per surface, meta-no-hover, keymap table | Sonnet | lints pass on main |
| Tue | F1 `prefs` module + F5 `api.stream/upload` + F8 | Sonnet | lints; errors.js 0 |
| Tue | D13 Settings two-pane, rest of the '?' popovers (54 paragraphs left, `scratchpad/help-audit/count.py`) | Sonnet | count.py TOTAL 0 |
| Wed | TIMELINE_PLAN.md Phases 1 to 2 (the measured baseline is in `scratchpad/ui-sweeps/timeline-audit*.js`) | Opus | timeline.js sweep |
| Wed | F2 pagination on all 25 lists + F6 scheduler | Opus | route test; idle ≤ 2/min |
| Thu | B1 event log | Opus | built (HISTORY.md) |
| Thu | D2 `[[` autocomplete + connections rail | Opus | 150ms; rail on every note |
| Fri | B2 job runtime + F7 | Opus | resume after kill |
| Fri | D4 Library one card recipe + D1 widget frame | Sonnet | uniform heights; ≤ 8 recipes |
| Sat | B3 retrieval engine + F3 + F10 | Opus | 5k fixture perf; every hit explained |
| Sat | D3 per-claim citations | Opus | 95% cited |
| Sun | B5 harness verifier + corrections; evals | Opus | ≥ 80% on 3B |
| Sun | HANDOVER, ROADMAP, BACKLOG rewritten to the new state; FABLE_BRIEF for the next Fable window | Sonnet | test_docs_layout |

**The quarter after** (in order, each two to four sessions): GRAPH_PLAN
Phases 2 to 5 · DOCUMENTS_PLAN Phases 1 to 7 · MINDMAP_PLAN Phases 4 to 5
· B4 knowledge kernel and the Tensions widget · D5 properties and D6
daily notes · D9 clipper and the PWA shell with share target · B6 sync
design and a folder-transport spike · B8 extensions · the offline studio
(§114 combo 3) · Notion and Obsidian importers · F12 the store, slice by
slice · a11y audit with a screen reader script · packaging: one-click
installers with a model-included first run sized honestly (§114 F11-1).

**What to hand the next Fable window** (judgement-heavy, not typing-heavy):
review of B1 to B3 as merged; the design decision for the block editor
(DOCUMENTS_PLAN §4) once CM6 is measured under the CSP; the sync
conflict model; the answer-citation UX; and a fresh screenshot-driven
pass on whatever still "feels off" once §1 is enforced.

---

## 12. Security review (read, not penetration-tested; each item names the file)

The threat model matters: the app binds 127.0.0.1 by default, so most of
these are "fine on localhost, real the day LAN mode ships". They are
listed so LAN mode cannot ship without them (Brief 15).

| # | Finding | Where | Severity now / on LAN | Fix |
| --- | --- | --- | --- | --- |
| S1 | The session token travels in `?token=` on every `/media` and `/files` URL (`mediaSrc`, `frontend/app.js` ~215), so it lands in browser history, in uvicorn's access log, and in any note a person pastes an image URL into (the code already notes a doubled `?token=`). `Referrer-Policy: no-referrer` stops the Referer leak only. | `app.js` mediaSrc; `core/security.py` query-token path | low / high | A media-scoped, short-lived HMAC token (path + expiry, signed with a per-session key) or an HttpOnly cookie set at unlock and read only by `/media` and `/files`; the API keeps the header. Log scrubbing for `token=` either way. |
| S2 | Unlock throttling is one global list (`routes_auth.py` `_failed_unlocks`), not per client. | `routes_auth.py` ~93 | none / medium (five wrong tries from anyone locks the owner out for up to five minutes) | Key the throttle by client address once the bind is not loopback; keep the global ceiling as a second layer. |
| S3 | `import_directory` and `import_markdown` take a filesystem path from the request body and read it. Correct for the single user on localhost; on LAN it is arbitrary directory read for any holder of a token. | `routes_settings.py` ~1750 | none / high | Refuse when the bind is not loopback; or restrict to the user's home; the desktop shell should use a native picker and pass a handle, not a path. |
| S4 | `OriginCheckMiddleware` lets a request with neither Origin nor Referer through. Browsers always send Origin on cross-site state changes, so this is not the CSRF hole it looks like; it is a note so nobody "fixes" it into breaking curl and the desktop shell. | `core/security.py` ~78 | none | Keep; add the test that a cross-origin POST with Origin set is 403. |
| S5 | Bookmarks normalise a URL by adding a scheme and nothing else; today nothing fetches it. The clipper (D9) and any title preview MUST reuse `websearch.py`'s private-address check (~689) before the first `requests.get`. | `routes_bookmarks.py` ~36 | none / high once fetching exists | Move the private-IP guard into `core/security.py` as `assert_public_url()` and call it from every outbound fetch (bookmarks, clipper, update downloader, provider base URL). |
| S6 | The model provider base URL is user-set and fetched from the server; by design it points at localhost, so SSRF to the LAN is "the feature". | `ai/provider.py` | none / low | On LAN mode, show the configured URL in the privacy receipt; never follow redirects off the configured host. |
| S7 | **Fixed.** 16 `LIKE`/`ILIKE` sites, of which 13 took user text without escaping `%` and `_`, so a search for `100%` matched every row and `a_b` matched `axb`. `like_escape` and `LIKE_ESCAPE` are in `core/database.py`; every site that builds a pattern from a value now passes both, and the three that stayed bare are the literal `"image/%"` in routes_library, where the wildcard is meant. `tests/test_like_escaping.py` pins the behaviour through the documents and conversations searches and greps every call site for the pairing (both halves fail on their own: an escaped pattern with no `escape=` finds nothing at all). | `core/database.py`, 8 modules | was correctness | done |
| S8 | Backups restore by `Path(name).name` inside `backups/` (good); `searxng_install` extracts tar members it vets (good); uploads are `basename`d and the media dir is checked with `is_relative_to` (good); `X-Content-Type-Options: nosniff` and `Content-Disposition: attachment` on files (good). Recorded so nobody re-audits them. | as named | none | Keep the tests that pin each. |
| S9 | **Fixed (99adcc9).** `renderInlineMarkdown` set `a.href` from note text with no scheme check; the CSP blocked `javascript:` and nothing else did. `safeHref()` allow-lists http, https, mailto, tel, relative and anchors; `tests/test_markdown_link_schemes.py` pins it. | `app.js` renderInlineMarkdown | was low | done |
| S10 | **Confirmed off**: `docs_url`, `redoc_url` and `openapi_url` are `None` in `create_app` (`api/app.py` ~361). MODERNISATION_AUDIT D5 is stale. | `api/app.py` | none | Record in D5. |
| S11 | **Fixed, and it was not on the list.** `POST /update/apply` downloaded `browser_download_url` straight out of the GitHub release row and ran it silently as an installer, with only a truncation check between the two. TLS means only whoever controls the releases can choose that URL, so nothing was open today; the gap was between trusting the release and trusting whatever URL the release names. The host is now checked before a byte is written (https, and one of github.com, api.github.com, objects.githubusercontent.com), with the refusal, the https-only rule and the two ways an `endswith` allowlist is usually beaten all pinned in `tests/test_update.py`. | `api/routes_update.py` | was low | done |

**Brief 15 (network hardening, Opus, one session):** S1, S2, S3, S5 as one
change set with a `tests/test_lan_mode.py` that starts the app bound to
0.0.0.0 in a subprocess and asserts each behaviour; only after it passes
does Settings offer "Allow other devices on this network".

## 13. Open bugs and gaps from the merged agent reports (with owners)

Each of these was found by measuring and deferred with evidence; the
`agent-remaining/*.md` file named carries the file, id and next step.

- Whiteboard board-preview minimap writes NaN rects (20 console errors on
  a notebook with boards; `app.js` `board-minimap-card`). Owner: mindmap
  item F (previews), since the new miniature renderer replaces it.
- 1024px still wraps the Writing Room controls and the capture attachment
  row. Owner: consistency.md.
- Tab bar scrolls between 600 and 819px; short tab captions below 480 are
  a copy decision for the owner. Owner: responsive.md.
- Notes (8) and Graph (9) docks are over the seven-control ceiling. Owner:
  docks.md; the fix is a second "more" group, not hiding.
- `#wb-topbar` is 104px at 390. Owner: responsive.md.
- The whiteboard's five menus were restyled but never driven (the board
  would not open in the driver). Owner: consistency.md; first step is a
  sweep that opens a board by API id, then each menu.
- The SVG graph path stays behind a flag until the drag gate is met on a
  quieter machine. Owner: GRAPH_PLAN Phase 2.
- Timeline: everything (audited, not built). Owner: Brief 5.
- 54 paragraphs still outside popovers. Owner: Brief 4.
- `#library-media-refresh` is misnamed; Settings has two heading indents.
  Owner: docks.md.
- Tidy layout never measured past five nodes; a newly opened map leaves
  its root under the top bar. Owner: mindmap.md item H.

## 14. The core algorithms, read line by line (2026-09-08)

The owner asked whether the core algorithms are the best they can be, and
what would revolutionise the app decisively. Read, not assumed:
`search_manager.py`, `embeddings.py`, `janitor.categorise`, `intent.py`,
`grounding.py`, `_ensure_fts5`.

### What is already good

- Keyword search is FTS5 with `bm25()`, tag boost, prefix fallback,
  vocabulary-based spelling correction, then an OR fallback. Sound.
- Semantic search is brute-force cosine with a z-score relative floor,
  scored on `(id, vector)` tuples, fine to about 50k notes.
- Fusion is reciprocal rank fusion, then a two-hop graph expansion.
- Filing asks the model first, falls back to the embedding centroid, and
  logs the method. Every decision is explainable.

### What was wrong, and is fixed this session

- **No stemming.** The FTS index used the default tokenizer, so "prove"
  never found "proving" and "boot" never found "boots". With no AI
  running that was the whole of search. Now `porter unicode61`, with a
  one-time rebuild of an older index (`tests/test_keyword_search.py`).
- **Grounding scored only the retrieval set at 40% word overlap.** A
  paraphrase, and every note the model read through a tool mid-turn, went
  uncited. Now touched notes are candidates and a note's distinctive words
  ground from 20% (`tests/test_grounding.py`).

### The moves that would outshine everything else, in order of leverage

1. **A learning loop that never leaves the machine.** Every correction the
   owner makes is a training signal nobody uses: a re-filed note, a
   dismissed link suggestion, a result opened after a question, an
   accepted "related" chip. Store each as an event (B1), and let three
   algorithms read them: filing gets the nearest already-filed notes and
   the owner's past corrections as evidence in the prompt (k-NN
   few-shot from the notebook itself, which is the single biggest
   accuracy lever for a small model); search gets a per-note boost from
   what was opened after similar questions, with decay; link suggestions
   never resurface a dismissed pair and raise the prior of an accepted
   neighbourhood. No competitor does this offline. Size M; spec tests
   first (`tests/test_learning_spec.py`, strict xfail).
2. **Index everything** (B3). Documents, files' extracted text, board
   nodes and bookmarks are not in FTS5 or the vector table, so Ask cannot
   see them unless attached by hand. This is the largest capability hole
   in the app and is already specified; it goes first among the backend
   moves.
3. **Chunked vectors and sentence-level citations.** One vector per note
   loses long notes and every document. Embed paragraphs (one row per
   chunk, `entry_id, ordinal, vector`), retrieve chunks, and ground each
   answer sentence by cosine against chunks when an embedding backend is
   up, falling back to the lexical scorer. A citation then points at the
   paragraph, and the chip quotes it. Size M.
4. **Claims and tensions** (B4): the invention that no notebook has. It is
   expensive (a model idle loop) and depends on 1 to 3; keep it after them.

What is not worth doing: replacing RRF, replacing bm25, or an approximate
nearest-neighbour index below 50k notes. The measured costs are elsewhere.

## 15. Inventions: eight things no notebook does, specified for Opus and Sonnet

Written 2026-09-08 by direct instruction ("invent world class features
... something the likes of which the world hasn't seen yet"). Each one is
specified to the level a session can build from without a design pass:
what the person sees, why it is new, what already exists to build on
(checked in the code, file named), the data, the endpoints, the algorithm,
the tests written first, the gate, the size and the model. Dependencies are
explicit; the order at the end respects them.

### The asymmetry these exploit

Every cloud notebook rations model calls, because each call costs money.
MemoryMap's model is local, idle 99% of the time, and free per token. That
is the one thing a cloud product cannot copy: **the notebook can spend
hours of model time on itself while nobody is watching**, and show its
work in the morning. Inventions 1, 3, 5 and 8 are built on that. The
second asymmetry is that the corpus is one person's own thinking, not the
web: contradictions, repeated ideas, unanswered questions and forgotten
notes are *signal* here, where in a search engine they are noise.
Inventions 2, 4 and 6 are built on that. Invention 7 is the loop that makes
the other seven get better with use.

### I1 The night shift: the notebook that understands itself while you sleep

**What the person sees.** A "While you were away" card on the Dashboard
each morning: "Read 14 new notes. Found 3 claims that disagree with older
ones, 2 questions you answered without noticing, 6 dates, 4 people. 2
notes look like duplicates." Each line opens a review list where every
item is accept / dismiss / open the note, and each item shows *which note
and which sentence* it came from and *which model, when* decided it. Off
by default, one switch in Settings > Background tasks, with a token budget
per night and a battery guard.

**Why it is new.** Notion AI, Mem and Reflect do a summary on demand.
Nobody runs a standing, budgeted, auditable analysis of the whole
notebook on the owner's own machine, with provenance on every derived
fact, that the owner can reject line by line and that learns from the
rejections (I7).

**Builds on.** `ai/autonomous.py` (the scheduler: interval, battery guard,
snooze, a barred-destructive-tools agent pass; start() wired in app
lifespan), `ai/entities.py` (`extract_entities_pass`, `Entity`,
`EntityMention`), the tensions pipeline in `api/routes_entries.py`
(`TENSION_CANDIDATE_THRESHOLD`, `accept_tension`, dismissed set in a
preference), `EntryDate` and `reminder_parser.py` (dates), the near
duplicate check on save, `entry_revisions` (so "new since last run" is a
revision cursor, not a timestamp guess).

**Data.** One new table `derived_facts` (id, kind in {claim, question,
duplicate, tension, entity, date}, entry_id, revision_id, span_start,
span_end, text, payload JSON, confidence 0 to 1, model, computed_at,
status in {new, accepted, dismissed}, run_id). One `night_runs` table
(id, started_at, finished_at, cursor_revision_id, tokens_spent, budget,
counts JSON, stopped_reason). Every existing derived thing (entity
mention, tension) gets a `run_id` column so the morning card can group by
run. Nothing is written to a note. Ever.

**Endpoints.** `GET /night/latest` (the card), `GET /night/runs/{id}/facts?
kind=&status=` (the review list, paged), `POST /night/facts/{id}` (status
accept or dismiss; accept of a `tension` calls the existing accept path;
accept of a `date` creates the reminder through the existing reminder
route; accept of a `duplicate` opens the existing merge), `POST /night/run`
(manual, for testing and for "run now").

**Algorithm.** A run is a plan of passes with a shared budget: (1) cursor:
revisions since the last run; (2) cheap passes first, no model: dates
(`reminder_parser`), duplicates (embedding cosine over new notes against
all, threshold from the save-time check), entities (regex plus the
existing pass); (3) model passes, each note once, one prompt per note that
returns a JSON list of claims and open questions (the schema is in the
prompt, the parser rejects anything else); (4) tensions: for each new claim,
top-k similar claims by cosine, then one model call per pair above the
threshold asking "compatible / incompatible / unrelated" with a one-line
reason; (5) answered questions: for each open question, top-k similar
claims written *later*; one model call asks "does this answer it". Stop
when the budget is spent; record where; resume from the cursor next night.
Small-model mode: passes 3 to 5 use the small prompt variants
(`AGENT_SKILLS_REFORM` Phase B), one item per call.

**Tests first** (`tests/test_night_shift_spec.py`, strict xfail until each
passes): a run over the fixture notebook with the fake model produces the
expected counts per kind; every fact cites an entry, a revision and a
span inside it; a second run with no new revisions produces zero facts
and spends zero tokens; a budget of N stops the run with
`stopped_reason=budget` and a cursor before the unprocessed notes;
dismissing a fact hides it from `/night/latest` and writes a
`corrections` event (I7); a run is skipped on battery; nothing in
`entries` changes (row hash before and after).

**Gate.** On the 2,000-note fixture, a full first run under the fake model
finishes in under 5 minutes wall clock and the card renders under 100ms
from `/night/latest`. **Size** L (two sessions). **Model** Opus for the
runner and prompts, Sonnet for the review UI on the modal and list
recipes.

### I2 The margin reader: a second reader in the editor, from your own notes

**What the person sees.** While writing a note or document, a quiet
margin column (off by default per editor, one toggle in the toolbar's
more menu) fills with at most three cards, each pinned to the paragraph
it is about: "You wrote the opposite on 12 May: 'the batch size should
stay at 32'" (open, or mark not a contradiction), "This repeats your
note 'Why I left the project'" (open, link), "Answers your open question
from March: 'is the API worth the cost?'" (link as answer), "A date:
Thursday 3pm. Make a reminder?". Nothing is ever inserted into the text.
Cards fade when the paragraph changes and re-run after a pause.

**Why it is new.** Every editor's AI writes *for* you (autocomplete,
rewrite). None reads *with* you against your own past thinking. Obsidian
Copilot chats; Notion AI drafts; Mem surfaces similar notes as a list, not
pinned to the sentence and not typed (contradiction, repeat, answer,
commitment).

**Builds on.** The Phase 0 backdrop and underline geometry in
`documents.js` (a card is anchored the same way an underline is), the
selection toolbar D2, the chunk vectors from §14 item 3, I1's
`derived_facts` for claims and open questions, `EntryDate`.

**Data.** None persisted except accepted links (typed `EntryLink`:
contradicts, repeats, answers) and created reminders. Cards are computed.

**Endpoints.** `POST /editor/read` with `{entry_id | document_id, paragraph:
str, ordinal: int}` returns `[{kind, text, source_entry_id, source_span,
reason, confidence}]`, at most three, in under 300ms without the model
(similar chunk plus claim table lookups) and, when the model is up, a
second event over SSE with the model-judged kinds. Debounced client-side at
1.2s after typing stops in a paragraph; one in-flight request per editor;
the reply is dropped if the paragraph text changed.

**Algorithm.** Embed the paragraph (cached by text); top-5 chunks by
cosine excluding the current note; for each, if I1 has a claim in that
chunk, ask the model (small prompt) for the relation in {contradicts,
repeats, answers, unrelated}; without a model, show "related" only. Dates
through `reminder_parser` locally. Rank by confidence, cap three, never
show the same source twice in one note session.

**Tests first** (`tests/test_margin_reader_spec.py`): the endpoint
returns at most three cards; a paragraph that repeats a fixture note
verbatim yields `repeats` with that note; a paragraph that negates a
fixture claim yields `contradicts` under the fake model; a date yields a
`date` card with a parsed ISO timestamp; with the model down the endpoint
still answers in under 300ms with `related` cards; `test_frontend_ids.py`
and the CSP lint pass for the margin column.

**Gate.** Measured in Chromium: typing latency in the editor unchanged
(frame time p95 within 1ms of before, `scratchpad/ui-sweeps/editor.js`);
a card appears within 2s of a pause. **Size** M. **Model** Opus (the
frontend anchoring is design work).

### I3 Open questions: the notebook keeps a list of what you have not answered

**What the person sees.** A "Questions" view under Notes (a sub-tab):
every question you have written to yourself, newest first, each with
"asked 3 March in 'Pricing thoughts'" and one of three states: open,
answered ("you answered this on 9 April in 'Call with Sam'", with the
sentence), or dropped. The Dashboard shows the count and the oldest open
one. Ask can be scoped to it: "what am I still undecided about?" answers
from this list with citations.

**Why it is new.** Task managers track tasks you *declared*. Nobody tracks
the questions you *asked in passing* and tells you when a later note
answered them. This is the feature that makes a notebook feel like it
remembers on your behalf.

**Builds on.** I1 (extraction and the "answers" pass), the grounding
scorer for the answered-by sentence, the Notes sub-tab strip and the dock
grammar (a `questions` dock on the grammar), `EntryLink` typed `answers`.

**Data.** `derived_facts` of kind `question` with payload `{answered_by:
fact_id | null, dropped: bool}`. No new table.

**Endpoints.** `GET /questions?state=` (paged), `POST /questions/{id}`
(`{state}`; marking answered by hand asks for the note and stores a typed
link), the Ask box gets `scope: "questions"`.

**Tests first** (`tests/test_questions_spec.py`): a fixture note with two
questions yields two open facts with spans; a later note that the fake
model judges as answering one flips its state and the link exists; Ask
with the scope cites only question facts; dropping is reversible and
recorded as a correction (I7).

**Gate.** The view renders under 100ms for 500 questions; the dock passes
`test_dock_grammar.py`. **Size** M. **Model** Sonnet for the view on the
list recipe; Opus for the Ask scope.

### I4 Resurfacing: the ideas you are about to forget, when they matter

**Built, 2026-09-12.** The backend is `ai/resurface.py` with
`routes_resurface.py` (Brief 23), and the surface is the Dashboard's
Rediscover widget, which now leads with the three most faded notes and their
reason ("120 days old, no links, never opened") and falls back to its shuffle
under ten notes. Dismissing a card is a `dismiss_resurface` correction in the
same store the filing and search corrections use. The one design decision
taken here rather than in the plan: the scores refresh themselves on the
first read of the day (`resurface.ensure_fresh`) rather than from the night
shift, because the night shift only runs with the AI on and this feature
needs no model at all; measured at 2,000 notes, 137 ms to build the table and
4.3 ms for the read.

The "Forgotten" sort in Notes is built too: `GET /resurface/all` hands back
the order (not the daily three, which is a rotation over the top of it and
stable within a day, so the two are separate routes on purpose) and the sort
orders by position rather than recomputing the weights in the browser.
Measured in Chromium on a notebook aged 20 to 280 days: newest-first led with
the newest note, "Forgotten first" led with the 280-day-old one that had
never been opened, and the reasons matched the server's.

What is still open from the entry below: the margin row in the note editor,
which is I2's surface and is not built. The original entry, for the record:

**What the person sees.** Three cards a day, on the Dashboard and as a
row in the note editor's margin (I2) when relevant: "You have not opened
'Interview prep notes' in 94 days. It is close to what you are writing
now." Each card is open / keep surfacing / never again. A "Forgotten"
sort in Notes lists the notebook by fading score.

**Why it is new.** Readwise resurfaces highlights at random on a schedule.
Nobody resurfaces *your own notes* by a fading score conditioned on what
you are doing *now* (the open note, the active space, today's reminders),
with the choice fed back into the score.

**Builds on.** `Entry.access_count`, `updated_at`, `EntryLink` degree,
the vectors, the active space, the Dashboard widget system, I7 for the
feedback.

**Algorithm.** `fading = age_days_since_last_open × (1 / (1 + degree)) ×
(1 / (1 + opens))`, computed nightly for every note into a `note_scores`
table (entry_id, fading, computed_at). At request time (`GET /resurface?
context_entry_id=&space_id=`), take the top 200 by fading, score each by
cosine to the context (the open note's vector, else the space centroid,
else today's reminders' text), multiply, drop anything dismissed as
"never again", return three. The daily set is fixed for the day (seeded
by the date) so the card does not change on every reload.

**Tests first** (`tests/test_resurface_spec.py`): a never-opened,
unlinked, old note outranks a linked recent one; the context vector
reorders the top three; "never again" is honoured across restarts; the
three are stable within a day and change across days; a notebook under
ten notes returns an empty list rather than the same three forever.

**Gate.** `GET /resurface` under 50ms at 5k notes (scores precomputed).
**Size** S. **Model** Sonnet.

### I5 Time travel over meaning: what did I think about X in March?

**What the person sees.** A date control on Ask ("as of…") and a
"Then and now" panel on any note: the note as it was on that date, and a
two-column diff of the *claims* (not the text) between then and now: "Then:
the batch size should stay at 32. Now: 64 after the memory fix." Ask with
a date answers from the notebook as it stood then, citing the revision.

**Why it is new.** Version history exists everywhere. Answering a question
*from the notebook as it was*, and diffing what you believed rather than
what you typed, does not exist anywhere.

**Builds on.** `entry_revisions` (already written before every change,
quiet-period coalesced), I1's claims with `revision_id`, the Ask box, the
grounding scorer (it grounds against revision text the same way).

**Data.** No new table. Claims already carry `revision_id`; `GET
/entries/{id}/claims?as_of=` resolves the revision at that date.

**Endpoints.** `POST /chat/stream` gains `as_of: date | null`; retrieval
runs over revision text at that date (FTS5 over a temporary table of
as-of contents for the candidate set, vectors re-embedded on demand and
cached by revision id); `GET /entries/{id}/then-and-now?as_of=` returns
`{then: [claims], now: [claims], changed: [(then_id, now_id, kind)]}`
where kind is `revised | dropped | new`, from claim cosine plus the fake
or real model's judgement.

**Tests first** (`tests/test_time_travel_spec.py`): a note edited on
three dates answers a question differently as of each date, citing the
right revision; the then-and-now diff on the fixture reports one revised,
one dropped, one new; an `as_of` before the notebook existed returns an
empty, honest answer rather than today's.

**Gate.** As-of retrieval under 1s at 5k notes for a 200-candidate set.
**Size** M. **Model** Opus.

### I6 Evidence cards: answers you can audit sentence by sentence

**What the person sees.** Every AI answer sentence carries a small marker;
hovering shows the *paragraph* it came from, with the three reasons it was
chosen (words matched, meaning score, graph distance) as three short bars,
and the verifier's verdict: supported, partly, or unsupported. Unsupported
sentences are rendered in a lighter tone with "no note says this". A
"Show the evidence" toggle opens the answer and its sources side by side,
each source scrolled to the paragraph. A one-line trust score under the
answer: "9 of 11 sentences supported by your notes".

**Why it is new.** Perplexity cites pages; it cannot say which sentence
is unsupported, and its citations are page-level. Here the corpus is
finite and local, so every sentence can be checked against every
paragraph, and the verifier (B5) can say no.

**Builds on.** This session's grounding change (touched notes, distinctive
words, labels), `addInlineCitations` and `renderAnswerGrounding` in
`app.js`, `match_info` (the three signals already exist per hit), the
verifier spec `tests/test_harness_verifier_spec.py`, §14 item 3 for
paragraph-level anchors.

**Data.** None new. The grounding event grows per row: `chunk_ordinal`,
`span`, `signals: {bm25, cosine, graph}`, `verdict`.

**Tests first** (`tests/test_evidence_spec.py`): each grounded row carries
a chunk ordinal and a span that exists in that note; an answer sentence
with no candidate is marked `unsupported` and the trust line counts it;
the side-by-side view scrolls the source to the span (Playwright: the
span's rect is inside the viewport); the markers survive the final
markdown re-render (the bug already fixed once in `askQuestion`).

**Gate.** Trust score correct on the eval fixture's golden answers
(`tests/eval/golden.py`), citation score in `tests/eval/scoring.py` up
from its current baseline (record the number first). **Size** M. **Model**
Opus.

### I7 The corrections loop: every "no" makes the notebook better

**What the person sees.** Nothing new to do. Re-file a note, dismiss a
suggestion, mark a tension wrong, pick a different search result, say
"never again" to a card: the app records it and changes its behaviour.
Settings shows a small "Learned from you" panel: "37 corrections. Filing
accuracy 71% to 89% over the last 200 notes. Reset."

**Why it is new.** Offline apps do not learn; online apps learn on the
server from everyone. A per-person model that lives in the SQLite file,
is inspectable, resettable and explains itself is not something anyone
ships.

**Builds on.** `AuditLog` (re-file events already logged as
"recategorised -> X"), the dismissed sets kept as preferences, `janitor.
categorise` (the prompt), `search_manager._rank` (the fusion), the link
suggestion route.

**Data.** `corrections` (id, kind in {refile, dismiss_link, accept_link,
dismiss_tension, dismiss_resurface, open_after_ask, dismiss_fact}, subject
JSON, from_value, to_value, at). `learned_boosts` (kind, key, weight,
updated_at), rebuilt from `corrections` on demand (derived, so Reset is a
delete).

**Algorithm.** Filing: the prompt gets the three nearest already-filed
notes with their categories *and* the last three refile corrections whose
from_value matches the model's likely answer ("you moved notes like this
from Work to Projects twice"); the centroid fallback subtracts a category
the owner has refiled away from twice. Search: `open_after_ask` adds a
boost of 0.15 per open to that note for questions with cosine over 0.8 to
the asked question, decaying by half every 30 days, applied inside the
fusion as a fourth ranked list. Links and tensions: a dismissed pair
never returns; an accepted pair raises the threshold weight of its
two categories by a small constant. All weights bounded; all shown in the
panel.

**Tests first** (`tests/test_learning_spec.py`): a refile is recorded and
appears in the next filing prompt for a similar note; after two refiles
away from a category the centroid path no longer chooses it; an
`open_after_ask` reorders the next similar question's results; a
dismissed link pair is absent from `/entries/link-suggestions`; Reset
empties `learned_boosts` and behaviour returns to baseline; the panel's
accuracy number equals the fixture's computed value.

**Gate.** Filing accuracy on the eval fixture with 20 synthetic
corrections improves by at least 10 points; search p95 unchanged. **Size**
M. **Model** Opus for the prompt and fusion changes, Sonnet for the panel.

### I8 The model bench: which local model is best on *your* notebook

**What the person sees.** Settings > Models > "Test my models": pick two
or more installed models, press Run; twenty minutes later a table: filing
accuracy, citation accuracy, tool-call success, answer latency, tokens per
answer, each with a number and a one-line example of a failure. "Use this
one" applies it. Runs on the night shift budget if left overnight.

**Why it is new.** Every local-AI app tells you to "try a model". None
measures one against your own notes, offline, and shows the failures.

**Builds on.** `tests/eval/` (fixture, golden, scoring for tool choice and
citation), `ai/model_manager.py`, `routes_models.py`, I1's scheduler.

**Algorithm.** Build a held-out set from the owner's notebook: sample 40
notes, generate one question per note whose answer is a sentence in it
(no model needed: pick a claim from I1, or a sentence with two
distinctive terms), plus the note's own category. For each model: file the
40 notes cold, answer the 40 questions, run five scripted tool tasks;
score with `tests/eval/scoring.py`'s functions moved into `ai/bench.py`
(the tests then import from there, so the harness and the feature cannot
drift). Report per model.

**Tests first** (`tests/test_bench_spec.py`): a bench over the fixture
with two fake models that differ in one scripted answer ranks them in the
right order; the report names the failing question; a bench respects the
budget and can be stopped; "Use this one" switches the chat model
preference.

**Gate.** The bench over two models on 40 notes completes under 30 minutes
on the reference small model; the numbers reproduce within 2 points on a
second run. **Size** M. **Model** Sonnet (the scoring exists; this is
plumbing and a table).

### I9 What the notebook learned: one place to see, edit, delete and switch it all off

Added by direct instruction: "give the user the ability to see what the
notebook has learned and to be able to edit, delete and manage it so in
case the AI models get things wrong the user can fix it, also a way to
toggle the features on and off." This is not a ninth feature beside the
eight; it is the contract every one of them ships under. **No invention
above is built until its rows appear here.**

**What the person sees.** Settings > "What the notebook learned" (its
own section, next to Background tasks). At the top, one switch per
invention, each with a one-line description and a `?` popover: Night
shift (I1), Margin reader (I2), Open questions (I3), Resurfacing (I4),
Evidence checks (I6), Learning from corrections (I7), Model bench (I8).
Time travel (I5) has no switch; it only reads revisions. Off means: the
feature computes nothing, shows nothing, and its existing rows are kept
but inert (a banner in the section says "paused, N items kept"). A master
switch "Pause all learning" sets every one off in one click.

Below the switches, one table with a kind filter and a search box, every
row a fact the app derived rather than the person wrote: claims,
questions, tensions, duplicates, entity merges, dates, learned boosts
(I7), resurfacing decisions, filing corrections. Each row shows: the text,
the note and sentence it came from (click to open, scrolled to the span),
which model and when, the confidence, its status, and three actions:
**Edit** (the text, the entity name, the category, the weight: an edited
row is marked "edited by you" and is never overwritten by a later run),
**Delete** (gone, and recorded as a correction so the same fact is not
re-derived next run), **Reset to what the model said** (for an edited
row). Bulk: select all in the filter, delete or accept. At the bottom:
"Forget everything learned" (deletes every derived row and every boost,
keeps notes and revisions untouched, asks once), and "Export what the
notebook learned" (one JSON file, so the person can read it outside the
app).

Each invention's own surface (the morning card, a margin card, a question
row, a resurfacing card) carries a small "Learned: manage" link to this
section filtered to that kind, so a wrong fact can be fixed where it is
met, not only in Settings.

**Why it matters.** A model that is wrong quietly is worse than no model.
Every derived thing in this app is inspectable, attributable and
reversible, and the person can turn the model's judgement off entirely
and keep the notebook. That is the promise that lets the eight inventions
run unattended.

**Builds on.** `derived_facts` and `night_runs` (I1), `corrections` and
`learned_boosts` (I7), `note_scores` (I4), the preference store for the
switches, the Settings section recipe (D13), the list and modal recipes.

**Data.** `derived_facts` gains `edited_by_user: bool`, `original_text`,
`original_payload` (for Reset). `corrections` gains kind
`delete_fact`, `edit_fact`. Switches are preferences named
`learn.<invention>.enabled` (default off for I1, I2, I7, I8; on for I3,
I4, I6 once their upstream is on) plus `learn.paused` (master).

**Endpoints.** `GET /learned?kind=&q=&status=&page=` (the table, paged),
`PATCH /learned/{id}` (`{text | payload | status}`, sets `edited_by_user`),
`DELETE /learned/{id}` (writes the correction), `POST /learned/{id}/reset`,
`POST /learned/bulk` (`{ids, action}`), `DELETE /learned` (forget
everything; requires `{confirm: true}`), `GET /learned/export` (JSON),
`GET|PUT /learned/switches`.

**Rules the runners obey** (each a test): a runner checks its switch
before every pass and exits cleanly when off; a runner never overwrites a
row with `edited_by_user`; a deleted fact's `(entry_id, kind, text
hash)` is in `corrections` and the runner skips re-deriving it; `learn.
paused` stops every runner within one poll interval; the table never
shows a row from a note the person cannot open (private, binned).

**Tests first** (`tests/test_learned_spec.py`, strict xfail until built):
the section lists a fact from each kind with its source span; editing a
claim marks it and survives a re-run of the night shift over the same
note; deleting a fact writes a correction and the next run does not
re-create it; Reset restores the model's text; "Forget everything" leaves
`entries` and `entry_revisions` byte-identical and every derived table
empty; each switch off yields zero new rows from its runner and a 204 with
`{paused: true}` from its endpoints; the export round-trips (import is
not offered; the file is for reading); the master switch flips all seven
and the section shows "paused" on each.

**Gate.** The table renders 2,000 rows paged under 100ms per page; every
row's "open source" lands on the span (Playwright: the span's rect inside
the viewport); the section passes `test_dock_grammar.py`,
`test_style_scale.py` and the CSP lint. **Size** M. **Model** Opus for the
runner contract and endpoints, Sonnet for the table on the list recipe.

**Order.** I9's table and switches are built with I7 (the first invention
in the order below), so from the first learned boost onward there is a
place to see it; each later invention adds its kinds to the same table.

### Order and dependencies

```
§14.2 chunk vectors  →  I6 evidence cards
B1 event log (or the corrections table alone)  →  I7 corrections loop
I1 night shift  →  I3 questions, I5 time travel (claims), I8 bench (budget)
I1 + §14.2      →  I2 margin reader
nothing         →  I4 resurfacing, I7 (with its own corrections table)
```

Start with I9's switches and table together with I7, then I4 (no
dependencies, both improve every existing feature), then §14.2 and I6,
then I1, then I3, I2, I5, I8. Each adds its rows to I9 as it lands. Each is one
brief row in SESSION_BRIEFS when its turn comes; none is built ad hoc.

### What was deliberately left out

Autocomplete and "write it for me": every competitor has it and it makes
the notebook sound like the model. Cloud sync of the derived tables: the
inventions work because the data never leaves. A plugin marketplace before
B8: an extension surface without the event log is a support burden with
no lever behind it.

## 16. The backend, read for structure, silent failure and lag (2026-09-08)

Static probes over `src/memorymap` (`scratchpad/probe_backend.py`), each
number reproducible. Security is in §12 and was not repeated; nothing new
was found there beyond what §12 lists.

**Complexity is concentrated, which is good news.** Four functions carry
most of it and are the only ones worth restructuring:

| Function | Lines | Branches |
| --- | --- | --- |
| `ai/agent.py run_agent` | 788 | 71 |
| `ai/skill_runner.py run_skill` | 493 | 48 |
| `api/routes_chat.py chat_stream` | 384 | 46 |
| `api/routes_graph.py graph` | 298 | 37 |

Move: `run_agent` into a `Turn` object with one method per round phase
(prompt, call, dispatch, feed back, finish), which is also what B5's
verifier needs to sit between "call" and "feed back"; `chat_stream` into
prepare, route, stream, ground, with `lines()` a generator over a small
state object. No behaviour change; the existing tests are the gate
(`test_agent_*`, `test_chat_*`, `test_agent_plan.py`). Size M, Opus,
after B5's spec tests exist so the split serves them.

**Silent failure.** 129 `except Exception` handlers, 18 of them `pass`
(`embeddings.py` 234, 254, 261, 444; `entities.py` 141;
`reminder_parser.py` 205; `tools/_common.py` 337; `vision_ocr.py` 320;
`routes_settings.py` 1515; `routes_spaces.py` 219; `atomic_io.py` 41;
`pdfpages.py` 186, 240; `security.py` 407; `taskhistory.py` 90;
`manager.py` 811; `searxng_install.py` 499, 560). Rule for the pass:
each becomes `logger.debug` with the exception, or a comment naming the
failure it swallows and why that is right. Sonnet, one session, one
commit per file, no behaviour change.

**A thread-safety bug, fixed this session.** `EmbeddingService._embed_cache`
was read and evicted from request threads and the re-index thread with no
lock; the eviction iterates the dict, which raises under a concurrent
insert. Now one lock around the cache, never around the embedding call.

**Lag, measured by reading, to be measured by running.**

- `semantic_search` loads every vector blob from SQLite and decodes it on
  every query (`select(EmbeddingRecord.entry_id, EmbeddingRecord.embedding)`).
  At 10k notes of 384 floats that is 15 MB decoded per Ask. Move: a
  process-level matrix cache keyed by `(backend_id, max(EmbeddingRecord.
  updated_at), count)`, invalidated by the same fingerprint trick
  `routes_graph._cached` already uses. Gate: Ask retrieval under 30ms at
  10k notes. Size S, Sonnet.
- `similar_pairs` is O(n²) and is called from three routes (link
  suggestions, tensions, graph edges) on each request; the graph route
  caches it, the other two do not. Move: one cached pair table computed by
  the night shift (I1) or on the graph fingerprint. Size S, Sonnet.
- The frontend runs nine `setInterval` polls; MODERNISATION_AUDIT measured
  14 idle requests a minute. Move: one `/events` SSE stream (B1's log is
  the natural source) and the polls become subscriptions. Size M, Opus.
- Five route files exceed 1,750 lines (`routes_files.py` at 2,998). Not a
  bug; a session cost. Split by resource when each is next touched, never
  as its own task.

**Consistency findings.** Route handlers are wired by decorator, so a
"defined once, never referenced" probe is noise for them; excluding
decorated functions leaves under ten candidates, all private helpers
behind a feature flag. Not worth a session.

## Placed from INBOX, 2026-09-09

The owner's reports this plan owns, moved whole from INBOX.md with their numbers (never reused). Each becomes a phase row when its phase is written; until then this list is the phase.

1. **Deleting a space leaves its notes in "All spaces".** Read and not
   reproduced in code: `routes_spaces.delete_space` hard-deletes every
   workspace-scoped row in one transaction and
   `tests/test_space_delete_cascades.py` proves it. The likeliest cause is
   notes captured while "All spaces" was selected: those carry the default
   workspace, not the space, so deleting the space cannot touch them. Fix
   the cause of the confusion, not the cascade: (a) show the space chip on
   every note card and in the edit form; (b) the capture form files into
   the *selected* space and says which; (c) a "Move to space" bulk action.
   Owner: D2 and D5. If the owner can reproduce with a note that shows the
   space chip, reopen as a backend bug.
15. **Modal backdrop blur does not cover the full viewport height.** Read: `.modal-overlay` is `position: fixed; inset: 0`, so the unblurred strip is the desktop shell's native title bar, outside the page. Not a CSS bug; if it matters, the shell (pywebview/Electron) must draw a frameless window with the app's own title bar. Owner: packaging.
22. **Settings > Packages rows misaligned** (icon, text and the install
    button on different baselines). Owner: consistency.md item 4; the
    alignment sweep must include Settings > Packages and Settings > Help.
23. **Settings > Help gaps** (accordion rows touch, sections have no
    rhythm). Owner: help-popovers.md, with item 22.
26. **"Things that feel off that I cannot place."** After the consistency
    and docks lists close, one review pass per tab with the vendored
    design skills (`.claude/skills/README.md`) against DESIGN.md, writing
    findings as consistency.md rows, not fixing ad hoc. Owner:
    consistency.md, last item.

62. **"The documents formatting toolbar is gone."** Intentional, DOCUMENTS
    Phase 1: the strip is opt-in through the editor's ⋯ menu, "Always show
    formatting", and Phase 2 makes the floating selection toolbar the
    formatting UI. Nothing to fix; if the owner wants the strip on by
    default, flip the default in one line (documents.js `docToolbarMode`).
99. **Quick wins (Fable, 05:20): five features the plans did not list,
    each a day or less, each with the site.** (a) Undo on every delete
    toast: notes, boards, documents and reminders already soft-delete;
    `toastAction(msg, "Undo", () => restore)` at each delete call site
    (grep `toast(` beside `DELETE`), so a wrong click never reaches the
    bin. (b) "Reopen where I left off": documents and chats restore
    scroll position per id (localStorage `scroll:<kind>:<id>`), the
    Dashboard "Continue" tile (INBOX 60) reads the same keys. (c) The AI
    dot's tooltip shows the last answer's latency and the model's context
    use ("granite4.1:3b, 2.1 s, 39% of window"), from data the chat
    header already has. (d) A "Paste as note" global shortcut
    (Ctrl+Shift+V anywhere) that captures the clipboard as a new note
    with the AI filing it, the fastest capture path on a desktop. (e)
    Search operators in the Notes search box (`tag:`, `space:`,
    `before:`, `after:`, `has:file`), parsed client-side into the existing
    filters, with the operators listed in the box's '?' popover.
79. **Files sub-tab rows "could still use a massive redesign upgrade", and
    clicking the file name does nothing**. Owner: Library dossier
    (WORLD_CLASS 4), Opus: one row recipe (thumbnail, name as the one
    link that opens the reader, meta line, reading state as a small
    disclosure, actions in a kebab), the name clickable.
92. **Suggested links panel UI refine** (screenshot: rows of quoted
    pairs, a wide "Why?" input, a percent chip, Link and X). Owner: Opus,
    next slot: two note chips joined by an arrow, the score as a small
    bar, the reason field collapsed behind "Add a reason", Link primary
    per row, a "Link all above 70%" action in the head.
97. **OCR alternative to pytesseract**, asked directly. Answer: RapidOCR
    (PaddleOCR models on onnxruntime, pip-installable, no system binary,
    better on photos and mixed layouts, about 60 MB of models, Apache-2)
    is the one to offer; EasyOCR needs torch (never). Placed as a
    Settings > Packages option beside Tesseract, same reading pipeline,
    the reader named on the row. Owner: next session, Sonnet (backend
    adapter with a fake in tests) plus the Packages row.
98. **The documents formatting toolbar**: see 62; the owner asked again.
    Default stays opt-in until Phase 2's selection toolbar lands.

## 17. The original vision, audited (2026-09-09)

The owner's first notes, written months before a line of code (the
"AI Assistant Personal Database Management" list and the May 2026 master
reference), read against what exists. Almost all of it is built; the seven
rows marked open are the vision's own features nobody has planned since,
and they go first in the next session's World-class section.

| The original idea | Today |
| --- | --- |
| Type anything, a local AI files it; guided mode when you want to choose | Built (capture, Let the AI decide, guided) |
| Two AIs: a Janitor that files and never talks, a Librarian that answers and never writes | Built as the filing step and the chat; the librarian tags, links and flags duplicates in the background |
| A conversational answer and the raw database results side by side | Built (Ask: the answer beside the matching records) |
| Confidence on every filing, low ones flagged for review | Built half: the score shows; **open: a review queue** (below) |
| The AI tidies the database over time: merges near-duplicate categories, removes empty ones, respects manual changes | Built half: duplicates flagged, links suggested; **open: category tidy proposals** |
| Preferences for how the database is structured | **Open: a filing style preference** |
| Recycle bin, 30 days, configurable, clearable | Built |
| 100% offline, models local; optional web search for context | Built (models through Ollama, not bundled, by decision; web search opt-in) |
| File attachments copied into the app's folder | Built (Files, three readings per image, PDFs read page by page) |
| Google Drive plus Notion plus NotebookLM | Built as Library, Documents and Ask with sources |
| AI-generated data visualisation | **Open: charts from questions** |
| Last five queries; most-accessed information | Built (Ask history); **open: most-opened widget** |
| A log of everything entered, accessed, altered, archived | Built (activity log) |
| Manual links, or tell the AI about a link | Built |
| The graph like Obsidian's | Built (the canvas graph, Phases 1 to 5) |
| Submit a whole Markdown file as an entry | Built (documents import) |
| A whiteboard or canvas, submitted as an entry, editable later | Built (whiteboard, mind maps) |
| Export in bulk or in part | Built (JSON, CSV, Markdown, zip) |
| Login with a hashed password | Built (bcrypt, throttled) |
| A profile the AI uses, built over time, opt-out and delete | Built (About you; What it remembers) |
| Speech to text; the AI reads answers aloud; explains what you entered | Built (Whisper, read aloud); **open: "explain this note"** |
| Reminders, maybe a calendar | Built (reminders); **open: calendar export and month view** |
| Fine-tuning | Dropped, correctly, in the May document |

**The seven open rows, as quick rows for the next session (WORLD_CLASS,
after Brief 18 section A):**

1. **Review queue.** A Notes filter "Needs review" for filings under 60%
   confidence and anything filed Uncategorised, with Accept, Refile and
   Split per row; the count on the dashboard. Backend: `confidence` and
   `category_id` exist; one query. Size S.
2. **Tidy categories.** The librarian proposes merges (two categories
   whose embeddings and names are near) and removals (empty for 30 days)
   as a proposal list in Settings > What it remembers; nothing moves
   until accepted; manual renames are remembered as "do not merge". Size M.
3. **Filing style.** A preference (by topic, by project, by time) added
   to the filing prompt and to the category namer, with three examples
   each; the default is by topic. Size S.
4. **Charts from questions.** Ask answers a counting or trend question
   ("how many notes per category this month", "my race times") with a
   bar or line drawn from the records, the data table under it, the
   chart exportable as PNG. Size M.
5. **Most opened.** A dashboard widget of the ten notes opened most this
   month (the view counter exists on the node panel). Size S.
6. **Explain this note.** A note action that reads the note aloud and
   then says what it links to and why, from the link reasons. Size S.
7. **Calendar.** `.ics` export per reminder and for all, and a month view
   beside the reminders list. Size M.

The principle the first notes state and the app keeps: the AI is a
servant, not a gatekeeper; everything it does can be seen, edited and
undone.

