# Professional audit — what is missing, what is sub-par, what nobody noticed

> **Superseded** by [MODERNISATION_AUDIT.md](MODERNISATION_AUDIT.md) (measured) and [WORLD_CLASS_PLAN.md](WORLD_CLASS_PLAN.md) §10 (flaw classes with commands). Kept for its section pointers. Do not start work from this file.

**Companion to [`PLAN.md`](PLAN.md)** (the ship-ordered plan) and
[`../ROADMAP.md`](../ROADMAP.md). Asked for directly: *"the full professional
audit of what is missing, what needs changing, refining, redesigning and how,
restructuring, full schema changes, what has been missed, bugs that have gone
unnoticed. a lot of the features and utilities are very sub par and don't
work how they actually should in modern applications."*

Method: everything below was either **measured in a browser this session**
(Playwright against the running app, numbers quoted), **read in the source**
(file:line quoted), or **found by a test written this session**. Where a
claim is inference it says so. Fixed-this-session items are marked ✅ so the
next session does not re-diagnose them.

---

## A. Bugs that had gone unnoticed (found this session)

| # | Bug | Evidence | Status |
|---|-----|----------|--------|
| A1 | Text boxes juddered and were "basically unmovable": `d3.drag` measured deltas against the moving element because the grip is its child (default container = `parentNode`). | `whiteboard.js` `gripDrag`; also the w/n resize handles (the standing "zoom-drift" report) | ✅ `wbStableDragContainer` |
| A2 | Every single-key shortcut app-wide was dead after unlock: focus stayed on the hidden `#lock-password`, and every "don't steal keys while typing" guard saw an `<input>`. | measured `document.activeElement === INPUT#lock-password` on an open board | ✅ blur on unlock + visibility-aware guard on the board; **other guards elsewhere still check tag only** — grep `activeElement?.tagName` and apply the same `offsetParent !== null` test |
| A3 | Whiteboard panel clearances were four hardcoded guesses at sibling sizes (`top: 11rem`, `bottom: 5.25rem`, `30vh`, `18rem`), re-tuned three times after the same report. | CSS comments record each bump | ✅ measured via ResizeObserver → `--wb-h-*/--wb-w-*` |
| A4 | The tool row overlapped the zoom cluster by 33px at *every* width tested (18rem reserved; cluster is 339px). | measured 1280/900/760 | ✅ |
| A5 | Properties panel collapsed to 18px at ≤900px from a `max-height` calc that went negative. | measured | ✅ |
| A6 | Documents editor collapsed into an 18rem column when the sidebar hid — twice: the grid auto-placed the editor into the sidebar track, **and** the sidebar resize handle writes `grid-template-columns` inline (`app.js:15433`) so a plain CSS fix could not win. | measured 218px→1200px | ✅ (`!important`, deliberately) |
| A7 | Deleting a space *reassigned* everything to "default" instead of deleting. Also: 9 unscoped side tables (revisions, dates, mentions, embeddings, bookmarks, AI edits, doc links, page reads) FK into scoped rows and had no cascade — a plain delete raised `IntegrityError`. | `routes_spaces.py`; FK failures during the rewrite | ✅ cascade + 5 tests |
| A8 | "Delete this reading" never appeared for a vision reading: gated on Tesseract *regions*. | `library.js` `ocrRenderRegions` | ✅ |
| A9 | Notification read toggle did nothing for rows without an `id`. | `app.js` | ✅ |
| A10 | Sketches listed twice (Images *and* All-tab "files"). | `routes_library.py` | ✅ |
| A11 | `/media` `size_bytes` added by request stats the disk per row on every list — fine at 100 files, wrong at 5,000. | `routes_files.py list_media` | open → PLAN P6 |
| A12 | Hand-tool click did nothing on items (had to switch tools). | ROADMAP row 0b | ✅ |
| A13 | Lightbox Describe/Read never regenerated after a clear (no `force`). | `app.js` lightbox `run()` | ✅ |
| A14 | The test suite's fake embedding backend *succeeds*, so the no-embeddings fallback path (this project's default install) had no coverage until a monkeypatch forced it. | `tests/test_document_tools.py` | ✅ for documents; **files.py's equivalent path is still untested** |
| A16 | ✅ **Resolved — a harness artifact, not a bug.** The "New board" name confirm (`.confirm-overlay`, `aria-modal`) was still open under the script and intercepted the synthetic click; with it dismissed, Text and Sticky both place an object and open it for editing. Original report: **Text tool and Sticky tool did not place an object on a synthetic canvas click** in the Playwright harness (rect *drag* creates fine; `currentTool` stayed `text`/`sticky`, no object row). Either a harness limitation (d3-zoom click suppression on a synthetic `mouse.click`) or a real bug in the canvas click path that owns `wbCreateTextBox` (`whiteboard.js:4448`). **Unresolved — reproduce by hand first**: if a real click also fails, this is a P0. | `scratchpad/wbf.js` this session | open |
| A15 | `notify()` (OS notification) and the in-app notification history are two systems; the history lives in `localStorage`, capped, unsynced with reminders' own `done` state. | `app.js:23867`, `:18620` | open → B-section |

## B. Schema and backend — what a professional backend would change

Read `core/database.py` end to end. These are structural, ordered by damage.

| # | Finding | Why it matters | Change |
|---|---------|----------------|--------|
| B1 | **Two tables for one concept: `MediaUpload` and `Attachment`.** Two routers, two OCR/caption paths, two galleries stitched in JS with `_isAttachment` branches (28 sites in `library.js`/`app.js`). Every file feature is built twice or half. | Every bug in files reproduces twice; features (size, read state, page reads) land on one side first. | One `File` model (`id, kind∈{upload,attachment,sketch}, entry_id?, filename, stored_name, mime, size, sha256, created_at, workspace_id`) + `FileReading` (`file_id, reader∈{tesseract,vision,caption}, model, text, edited, created_at`). Migrate both tables in; keep old routes as thin shims for one release. PLAN B1. |
| B2 | **Scoping is ambient session state** (`session.info["workspace_id"]` + a `do_orm_execute` event), with `impersonate_workspace(session,"all")` as the escape hatch. Any query a developer writes is silently filtered — or silently *not*, on the wrong session. | The space-delete bug was exactly this class. Invisible behaviour is the enemy of correctness. | Explicit `Scope` dependency passed to every query helper; delete `impersonate_workspace`. PLAN B7. |
| B3 | **No job table.** Captioning, OCR, page reads, embeddings, tensions run inline or on ad-hoc threads; progress is a `taskhistory` log line; the frontend's `trackOcrRead` is a client-side in-flight map that dies with the tab. | Killing the app mid-read leaves nothing to resume; the UI cannot show a queue. | `jobs(id, kind, target_kind, target_id, state, progress, error, created_at, started_at, finished_at)` + one worker. All model calls except chat go through it. PLAN B2. |
| B4 | **Search is `ILIKE` scans** (`Entry.content.ilike`, `Document.content.ilike`, `/library?q=`). No FTS index. Typo tolerance was bolted onto the *stats* search only. | Linear in notebook size; 10k notes will feel it. | SQLite FTS5 virtual table over entries/documents/readings with trigram tokenizer; one `search(q, scope)` helper. PLAN B5. |
| B5 | **`PageRead` is keyed `(kind, source_id, page)` with no FK.** Orphans accumulate silently when a file is deleted outside the cascade. | Storage leak; stale readings can reattach if an id is reused. | Folds into `FileReading` (B1) with a real FK + ON DELETE CASCADE. |
| B6 | **`Entry` is overloaded**: notes, boards (`WhiteboardNode.board_id → entries.id`), sketches (image-only notes), meetings (tag), templates (would be tag). The Library has to sniff content (`strip_inline_markdown(content) == ""`) to know a sketch. | Every list filters by heuristics; a board is a "note" in every count. | `Entry.kind ∈ {note, board, sketch, meeting, template}` column, indexed; backfill by the same heuristics once; every list filters on it. |
| B7 | **Undo is in memory** (`wbUndoStack`, `pushUndo` in app.js). Reload = gone. | Professional tools survive a reload. | Per-board/per-doc undo journal in `localStorage` (cheap) or a `history` table (proper). PLAN W7. |
| B8 | **Revisions exist for documents and entries but not for whiteboard boards.** A wrong "Clear board" is 30 individual undos or nothing. | No board history at all. | Snapshot `board_revisions(board_id, snapshot_json, created_at)` on every N mutations / on close. |
| B9 | **No `sha256` on files** → no dedupe, no integrity check on backup/restore. | Duplicate uploads; silent corruption undetectable. | Column + compute on upload (B1). |
| B10 | **Indexes**: `workspace_id` is indexed; `Entry.is_deleted`, `Entry.category_id`, `Attachment.entry_id`, `EntryLink.(source,target)`, `Reminder.due_at` are not verified indexed. | Full scans on the hottest filters. | Audit with `EXPLAIN QUERY PLAN`; add; PLAN P5 (also WAL + `synchronous=NORMAL`). |
| B11 | **Errors are not a contract.** Some routes raise `HTTPException(detail=str)`, some let exceptions become bare 500s (the space-delete `IntegrityError` was one). | The UI shows "Request failed". | `{code, detail, hint, ref}` everywhere; global handler. PLAN B3. |
| B12 | **No pagination on any list.** | `/entries`, `/media`, `/documents`, `/library` return everything. | Cursor pagination. PLAN B4. |
| B13 | **Notifications and reminders are two unrelated stores** (localStorage vs DB). "Mark complete" on a reminder notification cannot complete the reminder. | The user's own report: "individual mark as complete buttons". | Notifications become rows (`notifications(id, kind, ref_kind, ref_id, at, read_at, done_at)`), and a reminder notification's "done" completes the reminder. |
| B14 | **Settings are a flat key/value blob with typed values bolted on** (HANDOVER: "typed values in the advanced"). | Every new setting is a string-parsing hazard. | Keep KV, but a single `settings_schema.py` declaring type/default/validator per key; the API rejects bad writes. |

## C. Whiteboard — sub-par against Miro / FigJam / tldraw (after this session's fixes)

Status now: **one top bar (navigation left, board actions right, look/grid/export/clear behind a Board menu), a centred icon-only tool dock (`role="toolbar"`, arrow-key focus), a fixed right-hand properties drawer, a three-button zoom cluster — nothing draggable, measured overlap-free at 1440/1100/820**; Select/Hand/Lasso peers, Select home, copy/paste style, Ctrl+D, `[`/`]`, hand-click selects, sticky tool, connectors to text/stickies, bend points, Escape cascade (selection → tool), one zoom write per frame. Still missing, in order of how often a professional hits it:

1. **Group transform of a multi-selection** (resize/rotate the set). Marquee selects; handles don't appear for the set. PLAN W1.
2. **Connector routing**: ~~attach at card centre~~ — ends now sit on the item's rotated border or a shape's own outline, with eight snapping anchors and a bend handle; **still no orthogonal mode**. PLAN W2.
3. **Frames** (titled containers that move their contents; export a frame). PLAN W4.
4. **Text on shapes**: a rectangle cannot carry a label without a separate text box on top. Add `data.label` to shape sketches; render centred.
5. **Snap to objects** exists (alignment guides); **snap to grid while resizing** does not.
6. **Board outline / layers panel**: no list of what is on the board; large boards are unnavigable except by the minimap.
7. **Touch/pen**: no `pointerType` discrimination; a resting palm pans. PLAN W9.
8. **Selection export** (PNG/SVG of the selection only). PLAN W10.
9. **Keyboard**: no `Ctrl+Shift+H/V` flip, no `Alt+drag` duplicate-drag, `Escape` does not cascade (edit → selection → tool).
10. **AI on the board** — the differentiator nobody else has offline: summarise a frame, cluster stickies, explain a link. Tools exist; the panel actions do not. PLAN W11.
11. **Accessibility**: the tool dock is a `role="toolbar"` with arrow-key focus now; the canvas itself still has no roving tabindex over items — a keyboard user cannot select the third card. Add `tabindex="0"` per item + arrow navigation + `aria-label` from content.

## D. Documents — sub-par against Obsidian / Typora / iA Writer

Status now: single-row dock, toolbar collapsed by default (chrome 187px → 102px above the first line at 1440px), live/source/split/read, slash menu, `[[` links, outline, backlinks, find & replace, revisions stored, AI edit, print.

**Corrections after a grep (CLAUDE.md's "already exists" rule, again):** a floating selection toolbar *does* exist (`editor.js` `SELECTION_BAR_ACTIONS`, `.selection-bar`, over `#doc-content`, every `.lp-src` live block and the note editor); `/table` exists in the slash menu; the revision history UI exists (`#doc-history-dialog`, list/preview/restore); focus mode exists (`#doc-focus-toggle`, `.doc-focus`). Templates now exist too (`DOC_TEMPLATES` in `documents.js`, `#doc-template-dialog`, five shapes with `{{date}}`/`{{title}}`). The list below is what is genuinely still missing.

1. ~~No floating selection toolbar~~ — exists (see above).
2. **Undo breaks across Live↔Source** (browser undo stacks are per-element). PLAN D3.
3. **Tables**: `/table` exists; **no Tab between cells, no row/column add/remove**. PLAN D4.
4. ~~Revision history has no UI~~ — exists (`#doc-history-dialog`).
5. **AI edit replaces text wholesale** — no diff, no per-hunk accept. PLAN D11.
6. ~~Templates: none~~ — built (`DOC_TEMPLATES`).
7. ~~Focus/typewriter mode: none~~ — exists (`toggleDocFocus`).
8. **Live renderer re-renders the whole document per keystroke** (inference from `renderLive` shape; measure with a 20k-word doc before touching). PLAN P4.
9. **Math, footnotes, task-list progress**: not rendered.
10. **Accessibility**: the Live pane is `contenteditable` with no `aria-multiline`/role; headings in Live are not real `<h1..h6>` for AT; the toolbar buttons lack `aria-pressed` for active states (some do).

## E. App-wide usability and accessibility — the things that read as "side project"

| # | Finding | Evidence / where | Fix |
|---|---------|------------------|-----|
| E1 | **Four independent poll loops** (reminders, model status, tasks, notifications), none visibility-aware. | `app.js` `setInterval(` sites; CLAUDE.md records a reminder poll on two timers | One scheduler, backs off when hidden, stops when locked. PLAN P1. |
| E2 | **Modals stacked on modals** (bookmark URL edit was a second modal after the first — HANDOVER). | HANDOVER | Rule: no modal opens from a modal; use inline expansion or a drawer. Audit every `openModal(` call site. |
| E3 | **Toasts carry actions the user cannot find again** ("Show it", "Undo") and vanish in 5s. | `toastProgress`, undo toasts | A persistent activity drawer (the jobs table from B3 gives it content) with the same actions. |
| E4 | **Keyboard-shortcut discoverability**: the `?` sheet exists; shortcuts are not shown in menus/tooltips consistently (some titles say "(V)", most don't). | index.html titles | Every command has one source of truth (`DEFAULT_SHORTCUTS`); tooltips render from it. |
| E5 | **Focus management**: dialogs do not trap focus or restore it on close (inference — verify with Playwright `document.activeElement` after `Escape`). | | `inert` on the background + restore focus to the opener. |
| E6 | **Colour contrast in glass panels**: `--modal-bg` is 96% opaque by design; over dense text it ghosted (CLAUDE.md). The same tier is used for every floating panel. | CLAUDE.md nav-history story | Measure every glass surface with `scratchpad/pngpixel.py` over the densest content it can float over; raise opacity where ratio < 4.5:1. |
| E7 | **Empty states** are text-only ("Nothing here yet"); modern apps put the primary action in the empty state. | Library sub-tabs, Documents | Each empty state: one sentence + the one button. |
| E8 | **Onboarding overlay** is dismissed by class toggling from tests; verify it is dismissible by keyboard and does not reappear after lock/unlock. | | Playwright assertion. |
| E9 | **Lock screen rate limiter** counts *any* wrong submit including an empty field; a test harness (and a user with a sticky Enter key) gets locked out for 108s. | `/auth/unlock` "Too many wrong passwords — try again in 108s" after empty submits | Don't count empty/short submits; show remaining attempts. |
| E10 | **Cache headers**: assets are version-stamped, but the desktop webview still ran stale `app.js` often enough that a force-reload had to be added this session. | HANDOVER; Ctrl+Alt+R | Ship the service worker with a version-keyed cache name and `skipWaiting` on activate; the stamp alone is not enough in a webview. |
| E11 | **Touch targets**: several icon buttons are 28–32px; WCAG 2.5.8 wants 24px min, Apple 44pt. | `.small` buttons | Audit with a Playwright sweep of every visible button's bbox; list <36px. |
| E12 | **Reduced motion** is honoured in places (`reducedMotionWanted()`), not systematically. | grep | One `@media (prefers-reduced-motion)` block that zeroes every transition token. |
| E13 | **i18n/RTL**: none (dates via `toLocaleDateString` only). | | Out of scope for now; note it so nobody hardcodes more strings. |

## F. Agent harness — what "ultimate" needs that is not there

1. Tools return prose or ad-hoc dicts; the chat renders some as cards, some as text. PLAN A1.
2. No plan/verify loop; a failed tool call ends the turn. PLAN A2.
3. Memory is implicit (prompt prefix); nothing lists or deletes what the agent "knows". PLAN A3.
4. No eval set; every prompt change is unmeasured. PLAN A6.
5. Stop does not cancel the model call or roll back partial writes. PLAN A5.
6. Not an MCP server/client; the notebook cannot be used *from* Claude Code or *use* other tools. PLAN A7.
7. The `read_file`/`get_document` keyword-window fallback built this session is the right shape; extend it to `search_notes` (still head-clipped).

## G. Test-suite gaps

- No Playwright suite in CI beyond the "E2E smoke"; every measurement this session was a scratch script. Promote `scratchpad/*.js` patterns into `tests/e2e/` with the three viewport widths.
- No test drives the no-embeddings fallback for `ai/tools/files.py`.
- No test for the lock-screen rate limiter's empty-submit behaviour (E9).
- No test asserts that hidden inputs don't swallow shortcuts (A2) — add one that hides `#lock-password` and presses `v` on the board.
- Style-scale lint caught undeclared tokens this session (good); add a lint that fails on `grid-template-columns`/`top`/`bottom` values expressed as bare `rem` constants inside `.whiteboard-floating-panel*` rules — the exact class of bug in A3.

## I. Bug, security and complexity scan (asked for directly)

**Security — what was looked for and what was found.**

| Check | Result |
|---|---|
| `subprocess` with `shell=True`, `os.system`, `eval`/`exec`, `pickle`, `yaml.load` | None. The three `subprocess.Popen` calls (`routes_files.py` open-exports-folder, `__main__.py` launcher) pass argv lists, no shell. |
| SQL built from strings | None. The two raw `text()` queries (FTS `MATCH`, `entries_fts_vocab` range) take bound parameters; the MATCH terms are `\W`-stripped words, and the vocab range is a single first letter. |
| Path traversal on file routes | Guarded: `os.path.basename` on upload names (`routes_files.py:785`), `resolve()` + `is_relative_to(media_dir)` on delete (`:1390`). CodeQL runs in CI. |
| `innerHTML` in the frontend | Six sites; all static markup or `escapeHtml()`-wrapped (`app.js:12496` diff viewer). The CSP forbids inline handlers regardless. |
| Auth | Every route sits behind the `X-Auth-Token` gate in `app.py`; the lock has a wrong-password rate limit (hit it twice from the harness this session). |
| Dependencies | No new packages this session. |

**Complexity (ruff `C901`, threshold 25):** `ai/agent.py run_agent` **45**,
`ai/autonomous.py _run_optimization` **31**, `api/routes_chat.py chat_stream`
**26**. Nothing else in `src/` is over 25. These are the three places a
future bug is most likely to hide, and the three to split before adding to
them — none was touched this session. No algorithm added this session is
worse than linear in the board's item count (`wbLinkCandidateAt` is a
linear scan; `wbEdgePoint` is linear in a path's segments; the vocabulary
correction is one range scan per query word).

**Bugs found by measurement this session, all fixed:** the dock wrapping at
50% width (abs-pos `left: 50%`); a `.card` margin offsetting every bottom
panel by 16px; the Files thumbnail's spanned-row height creating a 108px
hole; the selection tick stretched to the row width; the OCR rail tabs
clipped at 9rem; opening an image from a continuous-mode document; stored
page readings all badged as the on-screen page; Escape not closing the
Board menu from a focused toolbar button (the board's keydown swallowed it —
now a capture-phase listener).

## H. Suggested order (feeds PLAN.md's sprints)

1. B11 error contract + E1 one poll loop + B10 pragmas/indexes — one session, everything feels faster and nothing says "Request failed".
2. B3 jobs table → wire OCR/caption/page-reads/embeddings through it; E3 activity drawer on top.
3. B1 one file model (behind a new router; migrate the frontend gallery + lightbox + OCR workspace to one shape; delete `_isAttachment`).
4. D2/D3/D11 editor feel; C1/C2 whiteboard fluency.
5. B6 `Entry.kind`, B13 notifications table, B4 pagination, B5 FTS.
6. A1/A2/A6 harness; W11 AI on the board.
