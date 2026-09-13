# The professional-grade plan — whiteboard, documents, backend, agent harness

> **Mostly built; the rest is folded in.** Rows marked Built are done; the open rows are now [BACKLOG.md §116](BACKLOG.md) and [WORLD_CLASS_PLAN.md](WORLD_CLASS_PLAN.md) §8 and §11, which is the order to work them in. Do not start work from this file.

**Read after [`../ROADMAP.md`](../ROADMAP.md) and [`HANDOVER.md`](HANDOVER.md). The findings behind this plan — bugs, schema, per-surface gaps — are in [`AUDIT.md`](AUDIT.md).**
Asked for directly: *"make the documents text editor be the best one existing,
and same for the whiteboard. refine the backends, functionality and ui ux for
both... the app needs to shine and be usable professionally... make sure the
app isn't too device heavy. it needs to run VERY smoothly. FIX AND REDESIGN THE
BACKEND. MAKE IT THE ULTIMATE APP AND AGENT HARNESS... IF IT IS TOO MUCH, LAY
OUT THE FULL SCOPED PLAN FOR OPUS AND SONNET TO FOLLOW."*

This is that plan. Every item names the file it lands in, what "done" means,
and how to *measure* it — this repo's own rule (CLAUDE.md) is that a UI claim
without a measurement is a guess. Items are ordered by value ÷ risk within each
section; sections are ordered by what a working professional hits first.

Related, already settled — do not rebuild (HISTORY.md, HANDOVER.md):
Select/Hand/Lasso peers with Select as home; the contextual style panel; panels
clearing each other by measured size (`--wb-h-*`); copy/paste style; hand-tool
click selects; text-box drag; the Files rows; space-delete cascade; force
reload (Ctrl+Alt+R).

---

## 0. Performance and "not device heavy" (cross-cutting, first)

The app is local-first on the user's own machine, often beside a running
model. Every idle cost competes with inference.

| # | Item | Where | Done when / measure |
|---|------|-------|---------------------|
| P1 | **Built** (PLAN sprint 1: one visibility-aware loop, 14 → 4 idle requests/min). **One poll loop, visibility-aware.** Reminders, model status, tasks and notifications each poll on their own timer (CLAUDE.md records a reminder poll running on *two*). Fold into one scheduler in `app.js` that backs off to ≥60s when `document.hidden`, and stops entirely on the lock screen. | `app.js` (search `setInterval(`) | `performance.getEntriesByType("resource")` over 60s idle on the dashboard shows ≤4 requests. Today: count them first and write the number in HANDOVER. |
| P2 | **Already built** (`handleWbZoom` writes once per rAF; found by grep before rebuilding). **Whiteboard: batch every per-frame DOM write through one rAF.** Drags already write transforms directly (good). `handleWbZoom` still calls `wbSyncGridToTransform` + `wbRenderNavigator` synchronously per wheel/pan event. Throttle both to one write per animation frame. | `whiteboard.js:183` | Chrome Performance panel: a 2s trackpad pan on a 200-item board shows no frame >16ms. |
| P3 | **Whiteboard: virtualise off-screen items.** `renderWhiteboard()` joins *every* node/sketch/object on every render. Skip (hide via `display:none`, keep the datum) items whose bbox is >1 viewport outside the current transform; re-check on zoom end. | `whiteboard.js:5700` (`renderWhiteboard`) | 1,000-item board: first paint <300ms, pan stays <16ms/frame. Build the 1,000-item board with the API in a test script and keep it. |
| P4 | **Documents: debounce the live renderer, cap markdown work.** Live mode re-renders the whole document per keystroke. Render on `requestIdleCallback` with a 120ms trailing debounce; render only the changed block when the change is inside one paragraph. | `documents.js` (`renderLive`/`syncDocScroll`) | 20k-word document: typing latency (keydown → paint) <30ms measured with `PerformanceObserver` "event" entries. |
| P5 | **Built** (indexes + `temp_store`; WAL/synchronous were already there). **Backend: SQLite pragmas and indexes.** Set `journal_mode=WAL`, `synchronous=NORMAL`, `temp_store=MEMORY` at connect; add indexes for the columns every list filters on (`workspace_id` is indexed; `Entry.is_deleted`, `Entry.category_id`, `Attachment.entry_id`, `PageRead(kind, source_id)` are not all). | `core/database.py` | `EXPLAIN QUERY PLAN` for `/entries`, `/media`, `/library` shows no `SCAN` on the main tables at 10k notes. |
| P6 | **Built** (`size_bytes` stored at upload, backfilled once; the attachment gallery reads the column). **Backend: never stat the disk in a list.** `size_bytes` now stats every upload on `GET /media` (added by request). Store it on upload and backfill once in a migration. | `routes_files.py` (`list_media`), `alembic/` | `/media` with 2,000 uploads <50ms. |
| P7 | **Embeddings off the request thread.** Confirm every embed happens in the background task queue, never inline in `POST /entries`. | `core/`, `ai/` | `POST /entries` p95 <80ms with the fake embedding backend disabled. |

## 1. Whiteboard — to the level of Miro / FigJam / tldraw

Structure is now right (peers, contextual panel, measured clearance). What
separates "works" from "professional" is fluency: the things you do fifty
times an hour must be one gesture.

| # | Item | Where | Done when / measure |
|---|------|-------|---------------------|
| W1 | **Multi-select marquee + shift-click on *everything*, with a group bounding box and 8 handles.** Marquee/lasso exist; group resize/rotate of a multi-selection does not. | `whiteboard.js` (`wbMultiSelection`, `nodeResizeDrag`) | Select 3 shapes, drag a corner: all three scale about the group centre. |
| W2 | **Smart connectors.** Links snap to the nearest of 4 anchor points on a card and re-route around the card they leave. Curved links get a midpoint handle. | `whiteboard.js` (`wbLinkPathD`, link drag) | Drag a card; its links stay attached at the anchor, never through the card body. |
| W3 | **Sticky notes as a first-class object** (colour presets, auto-sizing text, `N` shortcut). Today "text box" is the only text object and it is not a sticky. | `index.html` tools, `whiteboard.js` objects (`kind: "sticky"`), backend `WhiteboardObject.data` (no schema change) | Press N, click, type — a yellow sticky appears sized to its text. |
| W4 | **Frames/sections** — a titled rectangle that moves its contents with it and appears in the navigator and the board outline. | `WhiteboardObject kind:"frame"`, `wbApplyBulkMove` | Drag a frame: children move; export "this frame only" works. |
| W5 | **Already built** (`wbAlignSelection`/distribute exist). **Alignment and distribution toolbar for multi-selections** (align L/C/R/T/M/B, distribute H/V, tidy-up). The properties panel already shows a multi-select row; put the six buttons there. | `wbUpdatePropertiesPanel` multi branch | Six buttons, each verified against computed bboxes in a Playwright test. |
| W6 | **Partly built** (`[`/`]` z-order exists; flip and the sheet assertions are open). **Keyboard completeness**: arrow nudge exists; add Ctrl+D duplicate, Ctrl+G/Shift+G group (exists), `[`/`]` z-order, `Ctrl+Shift+H/V` flip, `Escape` cascades (edit → selection → tool). Publish them in the `?` sheet. | `whiteboard.js` keydown (line ~4092) | Every shortcut in the `?` sheet has a Playwright assertion. |
| W7 | **Board-level undo that survives reload** — the undo stack is in-memory. Persist the last 50 entries per board in `localStorage` keyed by board id. | `wbUndoStack` | Move a card, reload, Ctrl+Z restores it. |
| W8 | **Minimap always available, not a toggle** in fullscreen; collapsible corner. | navigator code | Fullscreen shows the minimap by default at ≥1280px. |
| W9 | **Touch and pen**: two-finger pan/zoom, single-finger draw with a pen, palm rejection via `pointerType`. | `wbZoomFilter`, drawing handlers | On a touch device (or Playwright touch emulation) drawing with `pointerType:"pen"` while a `touch` pointer rests does not pan. |
| W10 | **Export**: PNG at 2× and SVG of the *selection*, with the board background optional. Export menu exists for the whole board. | `wb-export-menu` | Selection export produces a file whose bbox equals the selection's. |
| W11 | **AI on the board** (the genuinely new part): "Summarise this frame into a note", "Turn these stickies into a mind map", "Explain the connection between A and B" — each a properties-panel action on the selection, calling the existing agent tools. Stream the result into a new card beside the selection. | `wbUpdatePropertiesPanel`, `ai/tools/whiteboard.py` (new: `summarise_selection`, `cluster_items`) | Works with the fake transport in tests; the card appears with a "Made by <model>" byline. |

## 2. Documents — to the level of Obsidian / Typora / iA Writer

The editor has the Obsidian half (live preview, slash commands, `[[` links,
outline, backlinks) and the Notion half (typed blocks, AI edit). What is
missing is *editor feel* and *document structure*.

| # | Item | Where | Done when / measure |
|---|------|-------|---------------------|
| D1 | **Built** (one header row, strip collapsed by default; chrome 171 → 89px). **One header row, not five.** Title · format · view segment · save state · ⋯ in a single 2.375rem row; the formatting strip collapsed by default and revealed on selection (Medium/Notion-style floating toolbar) or with `Ctrl+/`. | `index.html` `.doc-dock`, `05-sidebars-themes.css` `.doc-toolbar` | Chrome above the first line of text ≤ 2 rows at 1280px (measure `#doc-panes`'s top offset: today 171px of chrome; target ≤ 96px). |
| D2 | **Already built** (`#selection-bar` in editor.js — audited, its Live-view placement fixed; 2.8 ms to appear). **Selection-driven floating toolbar** (bold/italic/link/heading/quote/code/AI) that appears above a selection in Live and Source. | `documents.js` (new `docFloatingToolbar`) | Select a word: toolbar appears within 1 frame, positioned by `getBoundingClientRect`, clamped to the pane (the same `clampToolbarMenu` rules). |
| D3 | **Built** (document-local stack across Live and Source, 200 entries, 500 ms coalescing; `scratchpad/ui-sweeps/editor.js` 35/35). **Real undo/redo with a document-local stack** across Live *and* Source (browser undo breaks on mode switch). | `documents.js` | Type in Live, switch to Source, Ctrl+Z undoes the Live edit. |
| D4 | **Tables**: `/table`, Tab between cells, row/column add/remove from a cell menu, live-rendered. | `documents.js` slash menu, renderer | A 3×3 table survives a Live→Source→Live round trip byte-exact. |
| D5 | **Already built** (`#doc-find-bar`, replace one/all). **Find & replace** inside the document (`Ctrl+H`), regex optional, with match count and highlight in both modes. | `documents.js` | 200 matches highlighted <50ms. |
| D6 | **Headings navigation**: outline exists; add drag-to-reorder sections in the outline (moves the whole section's text). | `doc-outline` | Drag H2 "B" above "A": document text reorders; undo restores. |
| D7 | **Callouts, footnotes, task lists with progress, math (KaTeX-free: render `$…$` with a small in-repo MathML shim)**. Collapsible callouts exist. | renderer | Each construct has a render test in `tests/test_markdown_*.py`. |
| D8 | **Version history UI on the document** — revisions are stored; show a right-hand timeline with diff view and "restore". | `documents.js`, `GET /documents/{id}/revisions` | Restore any of 10 revisions; diff highlights inserted/removed lines. |
| D9 | **Typewriter/focus mode and reading stats** (words, reading time exist; add "focus current paragraph"). | `documents.js`, CSS | Toggle dims all but the caret's paragraph. |
| D10 | **Already built** (`{{date}}`/`{{title}}` templates in documents.js). **Templates**: new-document-from-template (meeting, spec, decision record, weekly review) stored as documents tagged `template`. | `routes_documents.py` (`?template=`), Library "New" menu | New → Template → document created with `{{date}}` filled. |
| D11 | **AI inside the editor, professionally**: inline "rewrite / shorten / expand / fix grammar" on selection with a diff preview and accept/reject per hunk — never silently replacing text. `POST /documents/{id}/ai-edit` exists; add a `dry_run` that returns a unified diff. | `documents.js`, `routes_documents.py` | Accept one hunk of three: only that hunk applies. |

## 3. Backend — fix and redesign

The API works. It is not yet *designed*: three code paths do the same job
(media vs attachment vs sketch), errors surface as bare 500s, and long jobs
block requests.

| # | Item | Where | Done when / measure |
|---|------|-------|---------------------|
| B1 | **One file model.** `MediaUpload` and `Attachment` are two tables for one concept, with two routers, two OCR paths and two galleries stitched together in JS (`_isAttachment` everywhere). Introduce a `File` view/model with a single `/files` API; keep both tables as storage behind it; migrate the frontend to the one shape; delete the `_isAttachment` branches. | `core/database.py`, new `api/routes_files_v2.py`, `library.js`, `app.js` lightbox | `grep -c _isAttachment frontend/` → 0. All existing file tests pass through the new router. |
| B2 | **A real job queue for every model call.** Caption, OCR, page reads, embeddings, tensions all run inline in requests or ad-hoc threads. One `jobs` table + one worker thread; every long call returns `202 {job_id}`; `GET /jobs/{id}` streams progress; the frontend's existing `toastProgress` subscribes. `trackOcrRead` becomes a client of this. | `core/jobs.py` (new), `taskhistory.py`, routes | No request handler calls the model directly except `/chat/stream`. Killing the app mid-job leaves the job `failed`, never half-written. |
| B3 | **Built** (`{detail, code, hint}` on every HTTPException; `500 {code:"internal", ref}`). **Errors as a contract.** Every `HTTPException` carries `{code, detail, hint}`; the frontend renders `hint`. No bare 500s: an unhandled exception becomes `500 {code:"internal", ref:<uuid>}` logged with the ref. | `api/app.py` exception handlers | `tests/test_error_contract.py`: every route returns JSON on failure. |
| B4 | **Pagination everywhere.** `/entries`, `/media`, `/documents`, `/library` return everything. Cursor pagination (`?after=`) with the frontend's lists loading on scroll. | routes, `library.js`, `app.js` notes list | 10k notes: first paint of Notes <200ms. |
| B5 | **Full-text search with FTS5**, replacing `ILIKE` scans (`_list_documents`, `/library?q=`, note search). Keeps the keyword fallback the tests already depend on. | `core/search.py`, migration | `q=` over 10k notes <30ms; typo tolerance via trigram tokenizer. |
| B6 | **Migrations you can trust.** Alembic exists; add a startup check that refuses to boot on an unknown schema version and a `--migrate` flag, plus a pre-migration backup of `memorymap.db`. | `core/database.py`, `main.py` | Downgrade the db by hand → app refuses with a clear message and a backup path. |
| B7 | **Workspace scoping as middleware, not ambient session state.** The `X-Workspace-ID` filter lives in a SQLAlchemy event; `impersonate_workspace` exists because it gets in the way. Move scoping into an explicit `Scope` dependency every route declares. | `core/deps.py`, all routes | `grep -c impersonate_workspace src/` → 0. |
| B8 | **Backups and export as a product feature.** Nightly zip of db + media to a user-chosen folder; one-click restore; per-space export. | `core/backup.py` (new), Settings | Restore into a fresh data dir reproduces the notebook byte-for-byte. |
| B9 | **Built** (`GET /debug/health`; Settings › About Health block with latency p50/p95). **Observability that costs nothing.** A `/debug/health` with db size, job queue depth, model latency p50/p95 (from `taskhistory`), and the last 20 errors — surfaced in Settings › About. | `routes_models.py` or new | Page renders in <20ms. |

## 4. Agent harness — "the ultimate agent harness"

The harness works with small local models (HISTORY §8, §110). To be the
harness people build on:

| # | Item | Where | Done when / measure |
|---|------|-------|---------------------|
| A1 | **Built** (`ai/cards.py` projection table, five kinds, coverage-tested; one chip renderer in app.js). **Tool results as typed cards, not prose.** Every tool returns `{kind, items:[...]}` and the chat renders a card per kind (note, document, file, board, reminder) with its real actions. Some do; make it all. | `ai/tools/*.py`, `app.js` chat renderer | `grep` finds no tool returning a bare string. |
| A2 | **Built** (`MAX_REPLANS = 2`, a failed step rewritten in place; `tests/test_agent_plan.py`). **Plan → execute → verify loop with a visible plan.** For multi-step asks the agent posts a checklist card, ticks steps as tools return, and re-plans on a failed step (max 2). | `ai/agent.py` | `tests/test_agent_plan.py` with the fake transport: a 3-step ask produces 3 ticks. |
| A3 | **Memory with provenance.** The agent's "what I know about you" is a set of notes tagged `memory` with the turn that created each; a Settings page lists and deletes them. Never silent. | `ai/memory.py` (new), Settings | Every memory line shows "from chat <title>, <date>". |
| A4 | **Skills as files.** The Skills library exists; let a skill be a markdown file in `data/skills/` with frontmatter (name, trigger, tools allowed), hot-reloaded. | `ai/skills.py` | Drop a file in; it appears in the library without restart. |
| A5 | **Budgets and interruption.** Per-turn token/time budget in Settings; a Stop that actually cancels the model call (Ollama supports it) and rolls back partial tool writes via the undo stack. | `ai/agent.py`, `ai/ollama_client.py` | Stop at 2s: no note was created; the chat shows "stopped". |
| A6 | **Built** (`tests/eval/`, 33 golden asks, score 1.000 in CI; `scripts/eval.py` for a real model — never run against one). **Eval harness in-repo.** 30 golden asks over a fixture notebook, scored on tool choice and citation correctness, run in CI against the fake transport and locally against a real model with `make eval`. | `tests/eval/` | CI prints a score; a regression fails the build. |
| A7 | **MCP in and out.** Expose the notebook's tools as an MCP server (stdio) so Claude Code / other agents can use this notebook; allow attaching external MCP servers as tools. | `ai/mcp_server.py`, `ai/mcp_client.py` | `claude mcp add memorymap …` lists `search_notes`, `get_document`, … |

## 5. Ship order (suggested sprints, each ends green + measured)

1. **P1, P2, P5, B3** — smoothness and no bare 500s. One session.
2. **D1, D2, D3, D5** — the editor feels professional. One session.
3. **W1, W2, W5, W6** — the whiteboard is fluent. One session.
4. **B2, B1** — the job queue, then the one file model. Two sessions; B1 is the risky one, do it behind the new `/files` router with the old routes kept until every test moves.
5. **A1, A2, A6** — the harness becomes measurable. One session.
6. **W3, W4, W11, D4, D8, D11** — the features that make it *unique*. Two sessions.
7. **B4, B5, B7, B8, A3–A5, A7** — scale and openness.

Every sprint: run the full suite, `ruff check .`, `node --check` on every
touched JS, one Playwright measurement per UI claim, and a HANDOVER.md entry
that says what was *not* verified.

## 6. Semantic search and the knowledge graph — "the ultimate upgrade"

Asked for directly. Today: keyword `ILIKE` scans everywhere, an optional
embedding backend (absent on the default install), a graph drawn from explicit
links plus a "similar notes" spotlight, and `EntityMention` rows that exist
but drive nothing. The design below is what Obsidian-plus-Cognee would be if it
were offline, one process, and honest about a CPU-only laptop.

| # | Item | Where | Done when / measure |
|---|------|-------|---------------------|
| S1 | **Hybrid retrieval, one function.** `search(q, scope, k)` = FTS5 (trigram tokenizer → typo tolerance for free) **and** embedding kNN, fused by reciprocal-rank fusion; keyword-only when no embedding backend. Every search box, the agent's `search_notes`, `list_documents` and the stats search call *this*. | new `core/search.py`; migrations for FTS5 tables over entries, documents, file readings | Golden set of 40 (query → expected note) over the fixture notebook: MRR ≥ 0.8 with embeddings, ≥ 0.6 without. |
| S2 | **Embeddings that do not cook the laptop.** Embed on the job queue (PLAN B2) with a bounded worker, chunked (≈300 tokens, 20% overlap), stored in a `chunks(id, ref_kind, ref_id, ord, text, vector BLOB, model)` table; cosine via numpy over a memory-mapped matrix, no torch (CLAUDE.md). Re-embed only chunks whose text hash changed. | `core/embeddings.py`, `core/jobs.py` | Startup does **zero** embedding work (see E14); a 10k-note notebook embeds incrementally at <5% CPU average with the worker's sleep. |
| S3 | **Entities as first-class graph nodes.** `EntityMention` already links entries to entities; extract with a small local model *on the queue*, dedupe by normalised name, and let the graph show entity hubs (people, projects, places) that connect notes without an explicit link. | `ai/entities.py`, `graph.js` | A note mentioning "Matthew McKague" and a document mentioning the same name share a hub node. |
| S4 | **Inferred edges with provenance.** Three edge kinds in the graph, each toggleable and each labelled with *why*: explicit `[[link]]`, shared entity, embedding-similar (top-3, cosine ≥ 0.82). | `routes_graph.py`, `graph.js` legend | Hovering an inferred edge shows "similar (0.87)" or "both mention X". |
| S5 | **Communities and a time axis.** Louvain/label-propagation over the fused graph (pure Python, cached per notebook version) colours clusters; a time slider fades nodes by last edit. | `core/graph.py` | 2k-node graph clusters in <2s, cached until the next mutation. |
| S6 | **Graph as a query surface.** Click a cluster → "what is this about?" (the agent summarises the cluster's notes); select two nodes → "path between" (Yen's already exists) and "explain the connection". | `graph.js`, agent tools | Works with the fake transport in tests. |
| S7 | **Backlinks and unlinked mentions everywhere** (Obsidian's killer feature): every note/document panel lists notes that mention its title without linking, with one-click "link it". | `routes_entries.py /connections`, panels | FTS query on the title; test with three unlinked mentions. |
| S8 | **Index health in Settings**: chunk count, embedded %, model, last run, "rebuild" — and never a silent rebuild on boot. | Settings › Search | Numbers match the tables. |

## 7. Startup and thermal behaviour (reported: "fan noticeably speeds up when starting")

Not yet measured — measure first, then fix. Candidates, in order of likelihood:

1. **Embedding/index rebuild on boot** — grep `startup`/`lifespan` handlers in `api/app.py` and `core/` for anything that walks every entry.
2. **Model warm-up / `/api/show` per installed model** on the first `/models/status` (HANDOVER records this tripping a 5s abort).
3. **Four poll loops starting at once** (PLAN P1).
4. **Media GC / orphan scan** on boot.

Measure: `py-spy top --pid <uvicorn>` for the first 60s after launch, and Chrome's Performance panel for the first 10s of the page. Write both numbers into HANDOVER.md before changing anything. Target: the process is idle (<3% CPU) within 10s of the window appearing, with all indexing deferred to the job queue at low priority.

---

# Part II — every other tab, sub-tab, utility and ability

Asked for directly: *"do the cutting edge professional plan for every other
feature and the rest of the application, all the tabs, subtabs, utilities,
features, abilities."* Same format as Part I. Inventory taken from
`index.html` (tabs: Dashboard, Notes, Chat, Graph, Library[All · Documents ·
Boards & maps · Images · Files · AI Skills · Links · Contents], Timeline,
Reminders; Settings[Account · Appearance · Preferences · Models · Tools ·
Skills · Personas · Templates · Web search · Memory · Tasks · Data · Logs ·
Shortcuts · Extras · Help · About]; overlays: command palette / popup agent,
OCR workspace, lightbox/file viewer, meeting recorder, connections, history,
binned, improve, features) and from `api/` (28 routers).

The bar for every row is the same: *how does the best app in that category
do this, and what is the one measurement that proves we match it.*

## 8. Dashboard

| # | Item | Done when / measure |
|---|------|---------------------|
| H1 | **Widgets are the dashboard; the dashboard is not a page of cards.** Today: a fixed set of widgets plus a widgets menu (HISTORY §75). Move to a 12-column drag/resize grid (react-grid-layout semantics, no library: pointer events + CSS grid areas), layouts saved per space. | Drag "Reminders" to the right column, resize to 6 cols, reload: identical. |
| H2 | **Widget catalogue with previews** — each widget declares `{id, title, minSize, dataSource}`; the menu shows a live miniature. | Every widget in `dashboard.js` has a catalogue entry; adding one needs no menu edit. |
| H3 | **"Today" as the default first widget**: due reminders, notes touched today, unread notifications, the last chat — one glance, one row. | First paint <150ms from cached data; refreshes via the one poll loop (P1). |
| H4 | **Stats that mean something**: streak, notes/week sparkline, top categories drift, "unlinked notes" count with a fix-it link. | Sparklines are inline SVG built from `/insights`; no chart library. |
| H5 | **Keyboard**: `1–9` jumps to widget N when the dashboard has focus; widgets are `role="region"` with labels. | Playwright: press 3 → focus inside widget 3. |

## 9. Notes (capture + list)

| # | Item | Done when / measure |
|---|------|---------------------|
| N1 | **Capture box = the same editor as Documents**, not a second implementation (slash menu, `[[`, `@`, paste-to-attach, drag-drop). One editor component, two mounts. | `grep -c contenteditable frontend/` drops to one implementation; every documents editor test passes on the capture box. |
| N2 | **Filing is a suggestion chip, never a modal**: category/tags/links appear as chips under the box as the model returns; Enter accepts, Esc dismisses, typing edits. (Non-blocking filing exists; make the *result* inline.) | No dialog opens during capture; p95 keystroke→paint <30ms while filing runs. |
| N3 | **Rows view is the default and is virtualised** (10k notes, 60fps scroll). Cards stay for image-bearing notes. | 10k fixture: scroll jank 0 long frames over 5s (Performance panel). |
| N4 | **Bulk actions bar** on select: move to space, add tag, pin, archive, delete, "ask the AI about these". Exists partly; make it one bar with keyboard (Shift+↑/↓ extends selection). | Every bulk action has a Playwright test. |
| N5 | **Inline expand, not navigate**: a row opens in place with the full editor (Notion-style), `Esc` closes, `Ctrl+Enter` saves. | Open/close a row without the list scroll position changing. |
| N6 | **Saved filters as sidebar items** (they exist as "Save filter"): show them in the left rail with counts; `is:unlinked`, `has:file`, `cat:`, `tag:`, `before:`/`after:` all documented in the `?` hint. | Each filter token has a test in `test_search_syntax.py`. |
| N7 | **Private notes**: lock icon, blur on lock screen, excluded from search/embeddings unless unlocked (exists) — add per-note passphrase option and an audit line in Settings › Data of what is private. | Private note never appears in `/library`, `/graph`, `/insights`, agent tools (tests exist; add graph/insights). |

## 10. Chat and the agent surface

| # | Item | Done when / measure |
|---|------|---------------------|
| C1 | **Every tool result is a card** with its real actions (open, pin, add to document, undo) — PLAN A1 — and a "used N sources" strip that expands to citations with highlighted spans. | No tool result renders as a bare paragraph. |
| C2 | **Composer**: multi-line by default, `/` commands, `@` mentions for notes/documents/boards/files (the universal picker, ROADMAP row 5), drag-drop files, paste image → attached with caption+OCR queued (exists) and a visible job chip. | `@` picker is one component used by chat, capture and documents. |
| C3 | **Conversation management**: pin, rename (fixed), fork from a turn, export as markdown, "turn this answer into a note/document" one click. | Fork creates a new conversation with turns ≤ N copied. |
| C4 | **Streaming that never stalls or dies** (HISTORY records three fixes) — add a heartbeat: if no token in 20s show "still thinking" with the model's tokens/s; Stop cancels server-side (A5). | Kill Ollama mid-stream: the UI shows a clear error within 5s, never a spinner forever. |
| C5 | **Model panel**: current model, context used / max as a bar, tools enabled, persona — in the header, one click to change. Exists in parts; unify. | Context bar updates per turn from the server's own count. |
| C6 | **Ask history** as a sidebar filter (exists), plus "ask again with the current notebook" and diffing the two answers. | |
| C7 | **Popup agent (Ctrl+K)** = command palette + agent in one input: commands first, then "ask the notebook", results navigable (exists), actions inline. Keyboard-only end to end. | Playwright: open, type, arrow, Enter, Esc — never touches the mouse. |

## 11. Graph

| # | Item | Done when / measure |
|---|------|---------------------|
| G1 | Backend per PLAN §6 (S3–S6): entity hubs, inferred edges with provenance, communities, time slider. | |
| G2 | **Rendering**: Canvas/WebGL for >500 nodes (d3-force in a worker), SVG below; level-of-detail labels; pin/unpin; focus mode (neighbourhood of one node, depth slider). | 2k nodes at 60fps pan; force layout in a Web Worker so the UI never blocks. |
| G3 | **Filters as chips**: by space, category, tag, date range, edge kind; saved views. | |
| G4 | **Graph → action**: select nodes → "make a board from these", "summarise", "find the path" (exists), "merge duplicates" (via `/duplicates`). | |
| G5 | **Accessibility**: a list view of the same graph (node, degree, cluster) for AT and for keyboard users; the canvas is not the only door. | |

## 12. Library

| Sub-tab | Item | Done when / measure |
|---|------|---------------------|
| All | **One list component** for All/Documents/Boards/Links/Contents (row, card, table density modes; sort; filters; multi-select; kebab) — today each sub-tab has its own renderer with drift (HISTORY §81/§90/§91 were all drift bugs). | One `LibraryList` in `library.js`; each sub-tab is a data source + column spec. |
| All | **`Entry.kind`** (AUDIT B6) drives the type filter instead of content sniffing. | |
| Documents | Table view with title, words, updated, links, "in board"; inline rename; open in split with the current document. | |
| Boards & maps | Thumbnail = a real rendered snapshot (PNG stored on save, not re-drawn); duplicate/template a board; "recent boards" in the whiteboard's own board picker. | Thumbnail load is one `<img>`, not a live render. |
| Images | Justified grid (Google Photos rows), date groups, lightbox with keyboard, "find similar" via embeddings (S2), bulk caption/OCR via the job queue with one progress bar. | |
| Files | Rows exist; add: column sort, type/size/read-state filters as chips, "open in reader" primary, "extract to notes" (page range → notes), duplicate detection by `sha256` (B9). | |
| AI Skills | Skills as files (A4) with a preview, enable/disable, "run on selection"; the library shows which skill produced which note. | |
| Links | Bookmark rows with favicon, reader-mode cache (offline copy of the page text — it's a local-first app), "cite in note", dead-link check on demand. | |
| Contents | This is the "everything" table: make it the power view — column picker, group by, export CSV/JSON of the current view. | |

## 13. Timeline

| # | Item | Done when / measure |
|---|------|---------------------|
| T1 | **Virtualised, date-grouped, with a scrubber** (year → month → day) and a density heatmap in the scrubber. | 10k items scroll at 60fps. |
| T2 | **Everything is an event**: notes, documents (created/edited), files, boards, reminders due/done, chats, meetings — toggleable kinds, one colour per kind, consistent with Graph and Dashboard. | |
| T3 | **"On this day" and "a week ago"** rows; jump-to-date; range select → "summarise this week". | |
| T4 | Popups show every attachment (fixed) — make the popup the same card component the Library uses. | |

## 14. Reminders

| # | Item | Done when / measure |
|---|------|---------------------|
| R1 | **Natural-language input** ("tomorrow 9am", "every Monday", "in 2 weeks") parsed locally (chrono-style, in-repo, no dependency); recurrence stored as RFC 5545 RRULE. | 30 phrases in a test table parse to the expected UTC instants. |
| R2 | **Reminder ↔ notification ↔ note are one thing**: a reminder notification's Done completes the reminder (AUDIT B13); a reminder created from a note links back. | |
| R3 | **Views**: Today / Upcoming / Overdue / Done, calendar month view, drag to reschedule. | |
| R4 | **OS notifications that fire while the app is open only** (it has no background process) — say so once in Settings, and offer an `.ics` export so a real calendar can carry them. | `.ics` validates; Google/Apple Calendar import shows the recurrence. |

## 15. Settings — section by section

| Section | Item |
|---|------|
| Account | Password change with current-password check; auto-lock timeout; "what is stored where" summary; lock-screen attempt counter fix (AUDIT E9). |
| Appearance | Theme, density, font, accent — all previewed live in a sample card; reduced-motion honoured globally (E12); `APPEARANCE_DEFAULTS` completeness lint (the NaN-border bug in CLAUDE.md) as a test. |
| Preferences | Default view per tab, editor defaults (toolbar collapsed, width, spellcheck), capture defaults (auto-file on/off), language. |
| Models | Installed models with capabilities (vision/OCR/embedding) as badges; pull with progress via the job queue; per-task model choice (chat, vision, OCR, embedding, caption) in one table; latency p50/p95 from `taskhistory` next to each. |
| Tools | Per-tool on/off exists; add per-tool "ask before writing" and a dry-run log. |
| Skills / Personas / Templates | Files on disk (A4), editable in the Documents editor, import/export as a zip. |
| Web search | Provider, allowlist/denylist, "offline only" master switch that greys every network feature and says so in the status bar. |
| Memory | Every memory line with provenance and delete (A3). |
| Tasks | The job queue (B2) — running, queued, failed with retry; cancel. |
| Data | Backup now / schedule / restore (B8); export space as markdown+files; import (Obsidian vault exists, add Notion/Apple Notes/Evernote `.enex`); storage breakdown by kind; "rebuild search index" (S8). |
| Logs | Tail of the app log with level filter and "copy for a bug report" that redacts note text. |
| Shortcuts | Editable (exists); conflicts detected; printable cheat sheet. |
| Extras | Move each item to the section it belongs to; this section should not exist. |
| Help | Searchable; each topic links to the control it describes ("show me"). |
| About | Version, update check (`/update` exists), force reload (done), health (B9), licences (AGPL notice + vendored MIT skills). |

## 16. Utilities and overlays

| # | Item | Done when / measure |
|---|------|---------------------|
| U1 | **OCR workspace**: page thumbnails rail (exists) + text pane with per-page confidence, region ↔ text hover-link (exists for Tesseract only; vision readings get sentence-level anchors by asking the model for bbox-free "line N" markers), re-read one region, export all text as a document, keyboard paging. | |
| U2 | **Lightbox / file viewer**: one viewer for images, PDFs, text/code (exists); add zoom-to-fit/100%/fill, pan, rotate, EXIF/PDF info panel, "open in OCR workspace" (exists), "edit in Documents" for text (exists). | |
| U3 | **Meeting recorder**: live transcript with speaker turns, pause (exists), "summarise + action items → reminders" one click, save as document with the audio attached and timestamps clickable. | Clicking a transcript line seeks the audio. |
| U4 | **Web search**: results as cards with a cached reader copy; "save as link"; "cite"; never runs when Offline-only is on. | |
| U5 | **Command palette**: fuzzy over commands + notes + documents + boards + settings; recent first; `>` for commands, `#` tags, `@` people/entities. | |
| U6 | **Notifications**: rows in the DB (B13), grouped by day, per-row done/read, mark all, snooze, "open" for every row, badge that matches the panel. | |
| U7 | **Connections / history / binned / improve overlays**: each becomes a right-hand drawer, not a modal (AUDIT E2), so the thing it describes stays visible. | |
| U8 | **Spaces**: switcher in the top bar with counts; per-space icon/colour; hide (exists); delete cascades (done); move items between spaces with drag. | |
| U9 | **Drafts / Duplicates / Insights / Tensions**: surface them where they apply (a duplicate badge on the note, a tension chip in chat) instead of separate pages; keep the pages as lists. Tensions verified against a real model before shipping wider (task #113). | |
| U10 | **Desktop shell (pywebview)**: tray with quick capture (Ctrl+Shift+Space global), start at login, single-instance, deep links `memorymap://note/123`, native file dialogs, proper window state restore. | |

## 17. Cross-cutting quality bars (apply to every row above)

- **Accessibility**: every control reachable by keyboard, `aria-pressed`/`aria-expanded` truthful, focus visible, dialogs trap and restore focus, contrast ≥ 4.5:1 measured with `scratchpad/pngpixel.py`, reduced motion global, canvas surfaces have list equivalents.
- **Performance**: no long frame >50ms on any interaction; every list virtualised past 200 rows; startup idle within 10s (§7); one poll loop (P1).
- **Consistency**: one list component, one editor component, one picker (`@`/`[[`), one card component, one drawer pattern, one toast+activity pattern; `docs/DESIGN.md` is the source and `test_style_scale.py` the gate.
- **Verification**: one Playwright measurement per UI claim in `tests/e2e/`, three widths; a HANDOVER line for anything not verified.
- **Offline-first honesty**: any feature that needs the network is gated by one switch and says so where it is used.

## 18. Order for Part II (after Part I sprints 1–3)

1. §15 Settings › Models/Tasks/Data + U6 notifications rows (they expose the job queue and the notification table already built in Part I).
2. §9 N1 one editor + C2 `@` picker (one component, three mounts) — the single biggest consistency win.
3. §12 one `LibraryList` + `Entry.kind`.
4. §14 R1/R2 reminders NLP + unification; §13 T1/T2 timeline.
5. §8 dashboard grid; §11 G2 graph rendering; U1/U3.
6. U10 desktop shell.
