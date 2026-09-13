# The documents editor — a professional dev plan

**Status: written by direct instruction; to be executed after the plans in
[UI_MODERNISATION_PLAN.md](UI_MODERNISATION_PLAN.md),
[AGENT_SKILLS_REFORM.md](AGENT_SKILLS_REFORM.md),
[MINDMAP_PLAN.md](MINDMAP_PLAN.md), [PLAN.md](PLAN.md) and
[REDESIGN.md](REDESIGN.md) are done, in the order
[ROADMAP.md](../ROADMAP.md) gives.** One decision (§4) has to be made before
any of it is built.

## 1. The instruction, verbatim

> Id like you re redesign and reimagine the documents editor, and Id like you
> to expand the documents editor help and suggestions, if something gets
> underlined, I want to be able to click on that and see suggestions. The
> whole documents page and editor needs a professional redesign and
> imagination because it is still reallllly annoying to use, and the ui and
> ux just isn't there, it's missing soooo many features and I need you to
> lay out a full professional dev plan for it so that it takes features from
> top editors like notion, obsidian, onenote, kortex.co etc and even beats
> them. The whole documents editor feels chucked together and then polished
> but from being chucked together and it doesn't feel professionally or
> designed for the modern day user. So many features I expect it to have
> are either downright missing or don't show themselves how they should.

The last sentence is the diagnosis to keep in view: **the gap is as much
features that exist and do not show themselves as features that are
missing.** §2 lists what exists precisely so §3 can say which of those the
plan fixes by *exposure* rather than by building again.

## 2. What exists (checked in the code, not assumed)

`frontend/documents.js` (~5,000 lines), the `.doc-dock` markup in
`index.html` (lines ~2200–2620) and `05-sidebars-themes.css` /
`07-whiteboard-misc.css`.

| Area | What is there | Where |
| --- | --- | --- |
| Views | Live (per-paragraph textareas rendered in place), Source (one textarea), Split, Read | `#doc-view-seg`, `docSetView` |
| Chrome | header (title, file-type select, save status, view segment, formatting toggle, AI edit, extract, ⋯ menu), a 26-control formatting strip (collapsed by default since D1), a status bar (Ln/Col, chars, words, reading time, goal, suggestions, Autocorrect and Suggestions switches), a left sidebar (Documents / Outline tabs, Recent, backlinks) | `.doc-dock-head`, `#doc-toolbar`, `#doc-statusbar`, `#doc-sidebar` |
| Structure | outline from headings, backlinks, `[[` wikilinks with autocomplete, `/` slash menu, connections dialog | `editor.js` `EDITOR_SURFACES`, `doc-outline`, `doc-backlinks` |
| Writing aids | prose checks (repeated words, long sentences, a confident spelling list) with a findings menu at the caret on double/right-click in Source and real underlines in Live (`docMarkLiveFindings`), inline completion from the document's and notebook's own vocabulary, autocorrect, a dictionary, "Check with AI", a word goal | documents.js ~3665–4700 |
| Editing | find & replace (D5), line-number gutters (7.2), indent/dedent/comment toggles, native undo kept through `execCommand('insertText')`, tables/quote/code/divider via the Insert menu (as markdown text) | `docReplaceRange`, `#doc-find-bar`, `mountGutterFor` |
| AI | AI edit (rewrite in place), selection → chat context with offset re-validation, AI review | `doc-ai`, `wrapDocSelection` |
| Files | any text/code file opens in the same editor with syntax highlighting and language detection; PDF/Office open read-only with extracted text; HTML preview pane; export text/markdown/PDF (print) | `docview.py`, `/files/{id}/html-preview` |
| History | revisions stored server-side; a history dialog | `doc-history`, `GET /documents/{id}/revisions` |
| Templates | new from template with `{{date}}`/`{{title}}` | documents.js ~594 |

**In flight as this is written:** D2 (a selection-driven floating toolbar)
and D3 (a document-local undo stack across Live and Source) on a subagent
branch — see HANDOVER.md. Both are absorbed by §5 Phase 1/2 rather than
redone.

## 3. The diagnosis

Three separate problems, and they need three separate answers. Conflating
them is how the editor ended up "chucked together and then polished".

### 3.1 The surface is a `<textarea>`, and everything the user misses follows from that

A textarea's value is a string. It cannot carry a mark, so nothing in
Source view can be underlined, which is why "click the underlined word" is
answered today with "double-click and we look up the caret offset" — the
comment at documents.js ~4626 says so honestly. Live view works around it
with one textarea per paragraph, which is why the caret is lost on a mode
switch, why undo was two stacks (D3), why a selection cannot span two
paragraphs in Live, why there is no drag handle, no block selection, no
inline widget (a chip for a linked note, an embedded map, a rendered
formula), and why tables are markdown text you edit by hand.

Every mainstream editor the instruction names solved this the same way:
**a real editing surface with decorations.** Obsidian's editor is
CodeMirror 6 with the markdown rendered as decorations over the source
("live preview"); Notion is a block model over `contenteditable`; Kortex
and OneNote are contenteditable block editors. None of them edits in a
textarea. §4 is the decision about which of those this app becomes.

### 3.2 The chrome is an inventory, not a design

Measured at 1440 (`scratchpad/…/docks.js`, screenshots
`dock-documents*.png`): the header carries seven kinds of thing in one row
(identity, file type, save status, a four-way view segment, a formatting
toggle, AI edit, extract, a ⋯ menu); the formatting strip has **26
controls in two wrapping rows** even after D1 collapsed it by default; the
status bar mixes measurements (Ln 7, Col 45 · 129 chars · 22 words) with
two settings switches and an action (Set a goal). At 820px (iPad) the strip
becomes three rows and the sidebar clips its own "Recent" label and New
button. It is every control the editor has, laid end to end.

A professional editor's chrome answers three questions and nothing else:
*what am I looking at* (title, where it lives, whether it is saved), *how
am I looking at it* (the view), and *what can I do to what I have selected*
(a toolbar that appears **for a selection**, and a `/` menu for blocks).
Everything else is a menu, a palette or a setting.

### 3.3 Features that exist and do not show themselves

- The findings menu exists and is reachable only by double-click or
  right-click in Source — nothing on screen says so.
- The `/` menu, `[[` links, the connections dialog, revisions, templates,
  the word goal and the dictionary are all behind a key or a ⋯ item with no
  discoverable entry.
- Backlinks render as a list of titles with no context line, so they read
  as a lookup, not as knowledge.
- Split view and Read view are a segment button each, next to Live and
  Source, so a four-way toggle competes with the title for the eye.

## 4. The decision to make first: the editing surface

Three options. The plan below is written for **B**; A is its first step
either way; C is recorded so the next session does not re-derive it.

**A — Keep the textarea, add a backdrop (one session).** The
"highlight-within-textarea" technique: a `div` behind a transparent-ink
textarea, same font, same padding, same wrapping, holding the text with
`<mark>`s where the findings are. Underlines appear in Source; a click
lands in the textarea, sets the caret, and the existing findings menu opens
for the finding at that offset (`docFindingAtOffset` already does this).
Cheap, offline, and it answers the sentence in the instruction directly.
What it does not give: inline widgets, block handles, a single model for
Live and Source, decent tables. **Do this first regardless** — it is the
bridge, and it is measurable in a day.

**B — CodeMirror 6, vendored (recommended).** MIT-licensed, no build step
needed (a single prebuilt bundle under `frontend/vendor/`, ~350 KB, the
licence file beside it, the same way `d3.v7.min.js` and `p5` are vendored
today). It gives, natively and offline: decorations (underlines that are
clickable, widgets, block backgrounds), a real undo history, search and
replace, folding, syntax highlighting for every file type this editor
already opens, line numbers, IME and mobile input that a hand-rolled
contenteditable never gets right, and a plugin API. **Live preview becomes
decorations over the markdown source** — headings rendered as headings,
`**bold**` shown bold with the markers hidden until the caret enters them,
links as chips, images and embeds as widgets — which is exactly Obsidian's
architecture and the one with the most published prior art. Markdown stays
the single source of truth; every existing endpoint, revision, export and
AI action keeps working unchanged. Source view is the same editor with the
decoration set switched off. Split and Read stay as they are.
Cost: the D2/D3 work in flight is partly superseded (CM6 has its own undo
and selection API — D2's toolbar is kept as the *UI*, re-pointed at CM6's
`dispatch`), and `EDITOR_SURFACES`' textarea assumptions in `editor.js`
have to be re-pointed at one adapter (`docSurface()`: get/set text,
selection, replace range) — which is also what finally lets the note
composer and the documents editor share one implementation.

**C — A block editor over `contenteditable` (Notion's model).** Rejected
for this app. It needs a second document model (blocks) beside the
markdown one, a serialiser both ways, and it makes every existing feature
that reads offsets (selection → chat, revisions, the AI edit, exports)
a translation problem. The Notion-style features people actually want
(a `/` menu, drag handles, callouts, toggles, columns) are all achievable
as decorations and widgets in B.

**Made in this document: B, with A as Phase 0.** The ROADMAP entry should
not be started until a session has read CM6's licence into
`frontend/vendor/` and confirmed the bundle loads under this app's CSP
(no `eval`, no inline styles — CM6 injects a stylesheet through the CSSOM,
which the CSP allows; verify before building on it).

## 5. The phases

Each phase ends green, measured, pushed, with a HANDOVER.md entry that
says what was not verified. Measurements use the Chromium sandbox; the
editor sweep is `scratchpad/ui-sweeps/editor.js` (from the D2/D3 branch),
extended per phase.

### Phase 0 — the bridge: click an underline, see suggestions (1 session)

1. **Backdrop underlines in Source** (§4 A). Findings from `docProseFound`
   drawn as `<mark class="doc-finding doc-finding-{kind}">` behind the
   textarea; the mark's kind decides the underline (spelling: wavy red;
   style: wavy blue; repeated word: dotted), the same three the Live view
   already uses so the two views agree.
2. **One click opens the suggestions.** `click` (not only double- or
   right-click) on a finding opens the existing menu at the caret, with the
   suggestions **ranked**: the dictionary's nearest words by edit distance,
   then the notebook's own vocabulary (`docCompleteWords`), then "Add to
   dictionary" and "Ignore in this document". Keyboard: `Alt+Enter` on a
   finding opens the same menu (the VS Code gesture).
3. **A findings count that is a control.** The status bar's "No
   suggestions" becomes a chip — `3 suggestions` — that opens the panel;
   `F8` / `Shift+F8` step through findings (VS Code again). The switches
   (Autocorrect, Suggestions) leave the status bar for Settings → Documents
   and the ⋯ menu; a status bar states, it does not configure.
4. **Suggestions explain themselves.** Every finding carries a one-line
   *why* ("'their' here is probably 'there'": only when a rule is certain;
   "this sentence is 61 words") and the panel groups by kind with counts.
   Acceptance: in Chromium, type a misspelt word in Source → an underline
   appears within 300 ms → one click opens a menu whose first item replaces
   the word → `F8` moves to the next finding; the same in Live.

### Phase 1 — chrome: three questions, three places (1 session)

1. **Header = identity.** Left: a breadcrumb (`Documents › Design system
   notes`) that is also the title field; right: save state as one word
   with a timestamp on hover, the view control, one ⋯. The file-type select
   moves into the ⋯ (it changes once per document); AI edit and extract
   become items in the selection toolbar and the ⋯. Target: **≤ 5 controls
   in the header**, one height (`--control-h-lg`), one baseline.
2. **View = one segmented control, two options in the row, two behind
   it.** Edit / Read as the segment; Split and Source as choices inside
   Edit's menu (a small chevron), remembered per document. Rationale:
   Live is what people mean by "edit"; Source and Split are modes, not
   destinations. (Obsidian: Edit / Read, with Source as a setting.)
3. **Formatting = for a selection, or by `/`.** The 26-control strip is
   retired as a permanent row. D2's floating toolbar is the formatting UI
   (bold, italic, strikethrough, code, link, highlight ▾, heading ▾, quote,
   list ▾, AI ▾); block insertion is the `/` menu with a visible "＋" at the
   start of an empty line (Notion's affordance). The strip survives as an
   opt-in "Always show formatting" setting for people who want it, which is
   what `#doc-toolbar-mode` already remembers.
4. **Status bar = facts and one action.** `22 words · 5 min` on the left,
   `3 suggestions` (a chip) and the goal ring in the middle, `Ln 7, Col 45`
   on the right. Nothing else.
5. **Sidebar = one list, one outline, one panel width.** Documents / Outline
   / Backlinks as three tabs with counts, a collapse that remembers, and at
   ≤ 1100px it becomes a sheet from the left (§5 Phase 6). "Recent" is the
   default sort of the Documents list, not a section of its own.
   Acceptance: `surfaces.js`'s document family reports header ≤ 44px,
   one control height, chrome above the first line ≤ 96px at 1280
   (PLAN D1's own gate), and at 820px the sidebar's labels are unclipped
   (scrollWidth = clientWidth on every sidebar label).

### Phase 2 — the engine: CodeMirror 6 as the surface (2 sessions)

1. Vendor CM6 (`@codemirror/state`, `view`, `commands`, `search`,
   `language`, `lang-markdown`, the languages the file editor already
   detects) as one bundle under `frontend/vendor/codemirror/` with its
   `LICENSE`; a `tests/test_vendor_licences.py` that asserts the licence
   file exists beside every vendored bundle.
2. `docSurface()` — the one adapter every existing feature talks to: text
   get/set, selection get/set, `replaceRange`, `onChange`, `coordsAt`. Every
   `$("doc-content")` read in documents.js and editor.js goes through it.
3. **Live preview as decorations**: headings, emphasis, code, links as
   chips, task checkboxes that toggle, block quotes and callouts with a
   left bar, images and embeds as widgets, hidden markers that reveal when
   the caret enters the range. Source = the same editor with the decoration
   set off.
4. Findings as CM6 decorations (Phase 0's backdrop retired), undo as CM6
   history (D3 retired), find/replace via CM6's search panel restyled onto
   the app's field recipe, folding on headings, the gutters via CM6's line
   numbers. The existing `/` menu, `[[` autocomplete and selection → chat
   re-pointed at the adapter.
   Acceptance: `editor.js` sweep — type in Live, switch to Source, Ctrl+Z
   undoes the Live edit (D3's own gate); a 20k-word document keeps keydown
   → paint < 30 ms (PLAN P4's gate, measurable now); every existing
   documents test passes; `node --check` and the DOM lints green.

### Phase 3 — blocks and structure: built, 2026-09-12

All five items. The record, with every measurement and every decision, is in
HISTORY.md ("From DOCUMENTS_PLAN.md Phase 3", items 1 to 3 and items 4 and 5);
what the phase left open is in `agent-remaining/documents-phase4.md`.

**The syntax this phase decided, kept here because later phases read it**:
`:::columns` opens a columns block, `:::column` starts the next column, `:::`
closes; an image's options are pipe-separated and read by shape, so
`![[river.jpg|300|center]]` and `![A river|300|center](/media/river.jpg)` mean
the same thing.

### Phase 4 — the connected document (1 session)

1. **Backlinks with context**: built, 2026-09-12. `GET
   /documents/{id}/backlinks` answers for notes and documents at once, the
   panel shows the sentence around each link with "link back", and unlinked
   mentions sit below with "link", which rewrites the mention in the source
   that wrote it. Decisions in section 11.
2. **Block references** (`^block-id`): built, 2026-09-12. A paragraph carries
   `^an-id` at the end of its last line; `[[Doc#^id]]` links to it and
   `![[Doc#^id]]` embeds it, from a note, a map node or a chat. The model is
   `DOC-BLOCKREF-BEGIN`..`END` in `documents.js` (run in node by
   `tests/test_doc_blockrefs.py`), the "/" menu's "Link to this block" writes
   the id and copies the reference, the marker hides in Live and is stripped
   from Read, and `scratchpad/ui-sweeps/docblockref.js` measures the lot
   (25/25). Decisions in section 11.
3. **Outline drag-to-reorder** (PLAN D6), breadcrumbs for the heading the
   caret is in, sticky outline that highlights the current section.
4. **Command palette** (`Ctrl+K`) listing every editor action with its
   shortcut — the single biggest fix for "features that do not show
   themselves" — and a `?` shortcut sheet generated from the same table so
   the two cannot disagree.
5. **Daily notes** and **templates gallery** (New ▾ → Meeting / Spec /
   Decision / Weekly review / Daily), templates stored as documents tagged
   `template` (exists) and offered with a preview.

### Phase 5 — review, history and AI (1 session)

1. **Comments and annotations** on a range (`==highlight== %%comment%%`),
   listed in a right panel, resolvable, exported as footnotes.
2. **Version history UI**: a timeline of revisions with a diff view and
   Restore (PLAN D8); an "AI changed this" filter using the per-document AI
   edit log that exists.
3. **AI edit with a diff preview** and accept/reject per hunk (PLAN D11);
   "Check with AI" renders its findings *as findings* (Phase 0's menu),
   not as a paragraph of advice.
4. **Focus and typewriter modes** (PLAN D9), reading typography for Read
   view (measure, leading, a serif option), a print stylesheet.

### Phase 6 — responsive by device (½ session, with UI Phase 9)

- **≥ 1100 (desktop)**: the layout above.
- **820–1100 (iPad landscape, small laptop)**: the sidebar collapses to
  icons and opens as an overlay; the selection toolbar is the only
  formatting UI; the status bar keeps facts only.
- **600–820 (iPad portrait)**: single pane; the sidebar is a sheet from the
  left; the ⋯ absorbs the view control's minor modes.
- **< 600 (phone)**: the editor is the page; a bottom formatting bar that
  sits above the on-screen keyboard (`env(keyboard-inset-height)` where
  available, `visualViewport` otherwise) with the six most-used actions and
  a `/` button; the outline is a sheet from the bottom. Touch targets 44px.
  Acceptance: `errors.js` at 390/820/1024 reports 0 findings on the
  editor; the first line of text is on screen with the keyboard open.

### Phase 8 — one editor everywhere (1 session, the owner's ask, 2026-09-09)

The owner: "plan for the note capture and editors in the notes tab, making
a new note from the graph, and anywhere there is a note related capture,
edit or view area with a text box to integrate features similar to the
documents upgrade. The editors need to be consistent in form and
function." Today the app has nineteen textareas in the page and seventeen
more made in script, and five of them are note editors with five
different feature sets: the capture box (`#entry-content`: formatting
strip, `[[` autocomplete, attachments, dictate, improve), the inline note
edit (`app.js` ~3988 and ~15256: a bare textarea), the graph's note popup
and new-note box (`#graph-popup-content`, `#graph-new-content`: bare), the
Write with the AI panes (`#draft-thoughts`, `#draft-text`: bare, the draft
in monospace) and the document (`#doc-content`: the engine after Phase 2).

**Decisions (made here, not remade).**
- One factory, `noteSurface(host, options)`, built on Phase 2's
  `docSurface()` adapter and the same CodeMirror bundle, replaces every
  note editor. Options: `size` (`inline` for a card, `box` for capture
  and popups, `page` for the document), `live` (decorations on or off),
  `strip` (the formatting strip, opt-in as in Phase 1), `findings`,
  `attachments`. The textarea stays as the fallback and as the form value
  carrier (the surface mirrors into it on change), so every existing
  save path, test and handler keeps working unchanged.
- The same features in every surface: Live decorations, `[[` note
  autocomplete, the `/` menu, the selection toolbar (bold, italic, code,
  link, list, ask the AI), undo history, Ctrl+S, `==highlight==`, task
  boxes, paste of images and files into the attachments row where the
  surface has one. What differs is size and chrome, never behaviour.
- One recipe in `09-editor.css`: `.note-surface` with the three size
  variants, the tokens' radius, `--control-h` for the strip, the same
  focus ring; a lint (`tests/test_note_surface.py`) that every note
  textarea in the page carries `data-note-surface` and is mounted through
  the factory (grep the ids), and that no new `<textarea>` for note text
  appears without it.
- The engine loads on the first focus of any surface, once per page.
- The chat composer is not a note editor: it gets `[[` and `/` only, and
  keeps its own recipe (send on Enter).

**8a, capture and the inline note edit** (½ session): `#entry-content` and
the two script-made edit boxes mount the surface (`size: box` and
`inline`); the capture's formatting strip becomes the selection toolbar
with the strip opt-in; attachments, dictate and improve stay. Gate: every
capture test passes; typing in capture with 2,000 notes loaded keeps
keydown to paint under 30 ms; errors.js clean.

**8b, the graph's popups and Write with the AI** (¼ session): the node
popup's editor (GRAPH Phase 6 sizes it four lines minimum) and the
new-note box mount `size: box`; Write with the AI's two panes mount the
surface with `live` on for the draft (no monospace). Gate: graph4b.js
and the write panel's own test.

**8c, the rest** (¼ session): whiteboard note cards edit in a `size:
inline` surface in place of the canvas text field; reminders' magic box
stays plain (it is a sentence, not a note); the skill editor's steps box
gets the `/` menu only. Gate: touch.js and mindmap.js unchanged.

### Phase 7 — export and interchange (½ session)

PDF (via the print stylesheet), HTML (self-contained), DOCX (server-side
via `docview`'s existing readers reversed, or `python-docx` as an optional
extra), Markdown with assets; import of `.docx`/`.html` to markdown. A
document's export options live in the ⋯, with the same names everywhere.

## 6. Competitor matrix (what the plan takes from whom)

| Feature | Notion | Obsidian | OneNote | Kortex | Here today | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| `/` block menu | ✓ | ✓ (plugin) | – | ✓ | ✓ (hidden) | P1 exposes, P3 extends |
| Live preview over markdown | – | ✓ | – | – | partial | P2 |
| Selection toolbar | ✓ | – | ✓ | ✓ | D2 in flight | P1 |
| Click a squiggle → suggestions | ✓ (browser) | ✓ (browser) | ✓ | ✓ | Live only | **P0** |
| Tables editor | ✓ | ✓ | ✓ | ✓ | markdown text | P3 |
| Callouts / toggles | ✓ | ✓ | – | ✓ | partial | P3 |
| Math | ✓ | ✓ | ✓ | – | – | P3 |
| Embeds of other objects | ✓ | ✓ | – | ✓ | – | P3 |
| Properties / frontmatter | ✓ | ✓ | – | ✓ | – | P3 |
| Backlinks with context | – | ✓ | – | ✓ | titles only | P4 |
| Block references | ✓ | ✓ | – | – | – | P4 |
| Command palette | ✓ | ✓ | – | ✓ | – | P4 |
| Daily notes / templates | ✓ | ✓ | – | ✓ | templates | P4 |
| Comments | ✓ | – | – | ✓ | – | P5 |
| Version history with diff | ✓ | ✓ (sync) | ✓ | – | list only | P5 |
| AI edit with diff | ✓ | – | ✓ | ✓ | replace in place | P5 |
| Focus / typewriter | – | ✓ | – | ✓ | – | P5 |
| Works with the plug pulled | – | ✓ | partial | – | ✓ | kept |
| The AI reads *your* notes, locally | – | – | – | – | ✓ | kept — the thing that beats them |

## 7. Files this will touch

`frontend/documents.js` (split into `documents/{surface,chrome,findings,
blocks,connections}.js` — served as-is, `test_frontend_load_order.py`
enforces order), `frontend/editor.js` (the adapter), `frontend/vendor/
codemirror/`, `index.html` (`.doc-dock`), `05-sidebars-themes.css`,
`07-whiteboard-misc.css`, `src/memorymap/api/routes_documents.py`
(properties, comments, block ids), `core/docview.py` (export), tests
under `tests/test_documents_*.py`, `scratchpad/ui-sweeps/editor.js`.

## 8. Acceptance for the whole plan

- The instruction's sentence, literally: an underlined word is clickable
  and shows suggestions, in every view, measured in Chromium.
- Header ≤ 5 controls; chrome above the first line ≤ 96px at 1280; one
  control height in every dock row; 0 `errors.js` findings at 390/820/1024.
- Every row of §6's "Plan" column has a test or a sweep assertion.
- `python -m pytest tests/` green; `ruff`; `node --check` on every file.
- HANDOVER.md says what was not verified — a real vision model, a real
  on-screen keyboard and a real iPad are three things the sandbox cannot
  supply.

## 9. Risks

- **CM6 under the CSP.** Verify first (§4). If it cannot inject its
  stylesheet, ship its CSS as a static file and set `EditorView.styleModule`
  off.
- **The note composer diverging.** The adapter (`docSurface`) is what
  keeps the capture box, the note edit form and the documents editor on
  one implementation; a phase that adds a feature to one and not the
  others has failed the learnability rule in UI_MODERNISATION_PLAN Phase 8.
- **Two undo stacks again.** D3's stack and CM6's history must not both
  be live; Phase 2 retires D3's the day CM6 lands.
- **Prompt budget.** Properties and comments reach the AI as context;
  `agent.PROSE_BUDGET_CHARS` is asserted and stays that way.

---

## Built, Phase 1 (the chrome), 2026-09-09

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", DOCUMENTS_PLAN.md) on 2026-09-09: a plan holds open work only.

## Built, Phase 2 step 1 (the engine, vendored and verified under the CSP), 2026-09-09

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", DOCUMENTS_PLAN.md) on 2026-09-09: a plan holds open work only.

## Built, Phase 2 steps 2 to 4 (the engine under the editor), 2026-09-09

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", DOCUMENTS_PLAN.md) on 2026-09-09: a plan holds open work only. What is left open from this phase is in `agent-remaining/documents-engine.md`.

## Built — Phase 0

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", DOCUMENTS_PLAN.md) on 2026-09-09: a plan holds open work only.

## Built, Phase 3 (tables, blocks, embeds, properties, columns), 2026-09-12

Moved to HISTORY.md ("From DOCUMENTS_PLAN.md Phase 3", two entries) on
2026-09-12: a plan holds open work only. What the phase left behind is in
`agent-remaining/documents-phase4.md`.

## Placed from INBOX: 107d, the segmented mini bars

"Note in the redesign documents and where it is supposed to that I want to get
rid of and redesign these mini menu bars as they are in a couple popups around
the place and they desperately need a modern redesign or alternative", with a
photo of `#doc-ai-verb`, the Edit / Write / Remove bar in this tab's AI
assistant panel.

**Done, 2026-09-12, and the decision is in `docs/DESIGN.md`** ("A choice
control's selected segment is `--accent-surface` behind `--on-accent`"), which
is where it belongs: it is a rule about a recipe, not about this tab. The
short version, so it is not re-litigated here: the two radio-backed bars
(`#doc-ai-verb`, `#graph-layout`) were the app's own segmented control drawn
with a different set of numbers, and the selected option was a 14% accent tint
behind body-coloured text with a drop shadow under it, which is not a selected
state anyone can see across a popup. They read as the other twenty-eight `.seg`
groups now. Measured before and after with
`scratchpad/ui-sweeps/segbars.js`; the numbers are in DESIGN.md and in the
commit.

**The label size this found is closed too** (`9586542`, a later pass the same
day). `.seg button` set no `font-size` at all, so it inherited whatever tab it
was on: measured at three sizes across the app, 16px on the tab strips, 13.6px
on two choice controls and 12.8px on three more. Every choice control is on
`--text-md` now, the tab strips deliberately are not. Re-measured here: all
nine segments across `#doc-ai-verb`, `#doc-view-seg` and `#graph-layout` read
13.6px.

## Placed from INBOX, 2026-09-09 (the owner's evening batch)

Verbatim, with the reading each one gets.

**All five were worked on 2026-09-09 and all five are done.** The built
record, with every measurement, is in HISTORY.md, "Built, the owner's
evening batch (DOCUMENTS_PLAN's INBOX items), 2026-09-09". What is left of
each below is the owner's sentence, the one-line answer, and anything the
work found and did *not* fix, which is the part that is still open.

- "the documents edit and read toggle options dont fit in the toggle and go
  out of it at the bottom". Done: the pills fit inside their segment at 1440
  and 1280. The cause was not the `padding-block: 0` this entry used to
  guess at; see HISTORY.
- "md formatting should go invisible unless i click back on that word or
  section or navigate with backspace, delete or arrow keys etc to where
  those formatting markers are." Done: the cursor-in-range test was already
  built and works; `---` and a callout's `[!kind]` were the two markers it
  had never been run on, and both hide now.
  **The caret jump is fixed, and the fix is a decision** (recorded here so it
  is not remade). Revealing a marker used to shift the caret 28.4px to the
  *right* on a leftward keystroke, because the reveal put four characters
  immediately to its left: measured with `coordsAtPos` walking left through
  `A **bold** word here.` as x 560.3, 554, 544.2, 531.1, then 559.5.
  `EditorView.atomicRanges` is the usual answer and is the wrong one here, as
  it would step *over* the marker rather than into it and entering it is what
  this sentence asks for. **A marker now reveals when the caret is on its
  line, not when it is inside its range** (`rangeRevealed` in
  `docLivePlugin`). Phase 2 item 3 said "when the caret enters the range";
  this supersedes that phrase and nothing else about it. The reasons: the line
  is what holds still, so horizontal movement inside one causes no reflow at
  all and the caret walk is now strictly monotonic (measured, fourteen steps,
  642.2 down to 529.4 with no reversal); the one reflow left happens when the
  caret *arrives* on a line, which is a click or a vertical move and both
  relocate the caret anyway; and `HeaderMark`, `QuoteMark` and `TaskMarker`
  already worked this way, so the eight constructs now agree instead of
  splitting into two behaviours. `scratchpad/ui-sweeps/cm-reveal.js` asserts
  the monotonic walk, so the jump cannot come back unnoticed.
- "I want to be able to use the documents tab as a plain text editor like
  before as a view option (not the default though)", "and also if I select
  a txt document, and/or other code file document, and these can have line
  numbers as well", "for code files, include code syntax and make it a
  proper code editor like vs code." Done: the edit menu is Live (default),
  Source, Split, Plain, with Line numbers as a row under them.
  **The missing modes are settled, with the numbers** (a decision, not an
  oversight; measured 2026-09-09 by building the bundle four ways).
  Baseline 787,401 raw / 269,374 gzipped.
  - **`swift`, `r` and `ini` added.** Together +7,658 raw and **+2,476
    gzipped**, under 1%. All three are ordinary legacy stream modes. `ini` is
    CodeMirror's `properties` mode, which is what that format is called there;
    it marks sections bold, keys at 600 and comments muted italic, and leaves
    values plain, which is the whole of an INI file's syntax.
    (An earlier note here said "`r` has no CodeMirror mode at all". That was
    wrong: `@codemirror/legacy-modes/mode/r` exists. It was written from
    memory rather than from the package, which is the same failure as the two
    entries above it.)
  - **`php` refused.** `@codemirror/lang-php` is not a legacy mode but a full
    Lezer grammar that also pulls in `lang-html`, because PHP is embedded in
    HTML. On its own it costs +98,144 raw and **+28,563 gzipped: 10.6% of the
    bundle for one language**, in a local notebook whose documents are notes
    and plans. Revisit if anyone asks for it; the number is here so the answer
    does not have to be re-derived.
  - **`csv` refused, permanently.** There is no CSV mode in CodeMirror and
    there should not be: a CSV has no syntax, so a highlighter would colour
    its commas and nothing else. What a CSV wants is a table view, which is a
    different feature.
  `scratchpad/ui-sweeps/docviews.js` asserts all five, including that `php`
  and `csv` highlight *nothing*, so adding a mode later has to come with an
  update to this decision rather than silently.
- "i still cant click on a grammar or misspeled underlined word and see a
  popup like in a realworld editor like obsidian, word, notion, vs code."
  **It already worked**, and this entry's previous claim that "the click
  target and its popover never landed" was a reading of the source without a
  browser. `scratchpad/ui-sweeps/docsuggest.js` is now the standing check.
  **What would still read as "cant click":** Read view has no editing
  surface and so no marks, and a code file suppresses findings entirely. If
  the report comes back, ask which view it was in before touching the code.
- "redesign and refine the outlines section of the documents tab as well"
  (two screenshots). Done: all five problems in them.
  **Found while measuring and still open:** `enhanceSelect` (app.js ~18427)
  rebuilds every `<select>` as a shell with a `<button>` opener and takes the
  native element out of the tab order, so `select.focus()` anywhere in this
  app focuses nothing and a `keydown` bound to a select never fires. Two
  listeners in this batch were written that way before a sweep caught it.
  There is no lint for the class; a cheap one would fail on `.focus()` or
  `addEventListener("keydown"` applied to a variable holding a `<select>`.
  The empty column above References is fixed: both sections carried
  `flex: 1 1 auto`, so with a two-heading document the outline was 312.4px of
  box around 68.3px of content and References 296.5px around 46px, leaving
  243.1px of nothing between them. `flex: 0 1 auto` on both; now 85.3px around
  68.3px and 69.4px around 46px, and `docoutline.js` fails on any section more
  than 40px taller than what is in it. Found while measuring that: `.linklike`
  cancels the filled button's background and border and never cancelled its
  `box-shadow`, so all fifteen text links in the app drew an accent halo
  behind their words.
- "the whole documents sidebar and ui needs fixing and the document editor
  still needs a lot of refinement and cleaning but its still in development
  so just make sure you cover it all."

## 10. The spelling check: decided 2026-09-12

**The problem, stated once.** The spelling rule looked each word up in
`DOC_AUTOCORRECT`, a hand-written table of 42 typos, and treated every word
absent from it as correctly spelled. "tets" was never flagged and neither
was anything else a person mistypes. The owner's two reports are that one
cause seen twice: "spelling errors and grammar arent picked up all the
time", and "no edit suggestions popup panel appears when I click on
underlined words", the second because the underline being clicked was the
browser's native squiggle (the editor set `spellcheck="true"`), which the
app cannot see and has no finding under.

**Decision: ship a real word list (option a), not an honest retreat
(option b).** The panel, the popup, the ranked suggestions, the dictionary
and the ignore list were all already built and all of them were starved of
the one thing that makes them worth opening. Retreating to "we only check
grammar and style" would have left the owner with a checker that still
cannot answer a click on a misspelling, because the browser's squiggle is
not ours to open a menu on. The list is the cheaper half of the work and it
is the half that makes the other half true.

**What was chosen, and the numbers.**
- The English Speller Database (SCOWL's successor), tier 60, US and UK
  spellings both, plus its "hacker" special list. `frontend/vendor/wordlist/`
  with its `LICENSE` and a `build.sh` that records the exact parameters.
- Licence: permissive, notice-retention only. It asks that the copyright
  notice travel with any list built from it, which `LICENSE` does. Safe
  under this project's AGPL-3.0 (ANALYSIS.md's licence constraint).
- 92,972 words. 871,173 bytes raw, 252,926 over the wire under this app's
  own gzip, one fetch, lazily on the first prose pass, never on first paint.
- `DOC_EXTRA_WORDS` in documents.js carries 75 words the app is written in
  that a general list does not have yet (json, backend, webhook). It is in
  the app rather than appended to the vendored file so that file stays
  exactly what its build script produces.

**The rules that keep it from crying wolf**, each one measured rather than
assumed: code fences, inline code, addresses, markdown link destinations,
reference definitions, html tags, `[[note links]]` and frontmatter are
masked out of every prose rule, not only the spelling one; acronyms
(`HTTP`), internal capitals (`MemoryMap`, `docSurface`) and letter runs
touching a digit, a slash, an `@` or a dotted name (`utf-8`, `app.js`) are
never checked. Measured on 8,000 characters of this project's own README:
six findings, five distinct words, every one of them a product name or a
coinage rather than a false positive.

**The browser's own spellcheck is now off while ours is on**, and
conditional rather than deleted: `docCmParts.spell` turns it back on if the
word list fails to load. Two underlines under one word, only one of which
answers a click, is worse than either alone.

**Suggestions and autocorrect come from the same generator.** The candidate
set is the edits one step from the typed word, filtered against the list
(Norvig's shape: a few hundred Set lookups rather than 93,000 edit-distance
computations), ranked by how specific the edit is, because there are n-1
transpositions of a word against 25n substitutions. Autocorrect fires only
on a *unique* transposition, or a unique dropped letter when there is no
transposition, on a word of four letters or more; everything else is a menu.

**Measured cost.** `docProseFindings` over an 8,000-character document: 2.8ms
cold, 0.9ms warm, against a 300ms keystroke-to-underline budget. The
candidate list is computed when the menu opens, not during the pass: doing
it per unknown word per pass measured 29ms on a 276-character document.

**Found while doing this, not fixed.**
- `scratchpad/ui-sweeps/docviews.js` fails on "the view menu has no
  line-numbers row" and then throws on a null click. Reproduced against the
  branch before any of this landed, so it is an older gap in the view menu
  rather than a regression: either the row goes back or the sweep stops
  asking for it.
- The suggestion menu draws the same check icon on every one of its five
  word rows, so the words read as five identical actions rather than as the
  answer with the actions underneath. The separating rule is there and it is
  doing the work on its own. A real spell menu differentiates them by more.
- The checker still reads only the shape of a sentence. Its/it's, agreement
  and tense are behind "Check with AI", which is a button press rather than
  a pass, for the reason `docProseHeader` records.

## 11. Phase 4 decisions, made 2026-09-12

The plan asked for five things and left four choices inside them unmade. They
are made here, with the reason, so no later session re-derives them.

**Backlinks are scanned on the server.** The browser holds every note
(`allEntries`) but no other document's *content*: `_summary()` deliberately
sends a preview, because a document runs to thousands of words. A client-side
scan would have found note backlinks and silently missed every document one.
One endpoint (`GET /documents/{id}/backlinks`) answers for both kinds and
defines "a mention" exactly once.

**The panel's two actions mean one thing each.** "Link back", on a row that
already links here, inserts `[[Source]]` **at the caret**, because that is
where every other insert in this editor writes (the `/` menu, the table
command, the properties command); an action that alone appended to the end of
the document would be the one place "insert" means something else. "Link", on
an unlinked mention, rewrites the mention **in the source that wrote it**,
through that kind's own update route, so the note's revision, its `[[link]]`
sync and its search vector happen exactly as they do for a hand edit.

**A source that links is not also an unlinked mention**, and a title under
four characters is never hunted as one. The second list means "not connected
yet"; a source in both says the opposite of what each list is for, and "AI"
or "Q3" as a mention would match a third of a notebook. A *linked* mention is
an exact `[[name]]` and is found at any title length.

**Block references are Obsidian's syntax, and the id is generated.** A block
carries `^an-id` at the end of its last line; the link is
`[[Document title#^an-id]]` and the embed is the same with a leading `!`,
which is the form Phase 3's embeds already parse the left half of. The id is
generated by the command that copies the link, never asked for: a person
naming their own ids is a person maintaining them, and the one thing a block
reference must survive is the paragraph being rewritten around it. The id
shape is narrower than Obsidian's (`[A-Za-z0-9][A-Za-z0-9-]{0,31}`) because
ids are generated here, so the only reason to accept more is to read somebody
else's file, and a `^` followed by punctuation is far more likely to be
arithmetic (`2^31`) than a block id.

**A block is the run of non-blank lines around the caret, except in a list,
where it is the item's own line**, and a position inside a fenced code block
has no block at all: the text in a fence is code, and appending an id to it
changes what the code says.

**A block reference points at a document, not at a note.** The id has to be
written into the target's text by the command that copies the link, and a
note has no editor here to put one in. A note is still linkable by `[[name]]`,
which is what it has always been.

**An embedded block is drawn as quoted markdown, not as a card.** Every other
embed draws an *object* through the renderer that owns it (a note card, a map
chip, a file tile). A block is a paragraph of this notebook's own writing, so
it is drawn as what it is, with a source line that opens the document at the
block.

## 12. The writing intelligence as one feature: decided 2026-09-13

The owner, verbatim (INBOX 142, which also settles 128): *"the suggestions box
at the bottom takes up a lot of my screen and it makes the text editor really
small. also the popup edit suggestions menu screws upn the screen and make sit
go out of bounds.and when I click on the issue from the suggestions thing, the
box just appears right there in my face. the whole editor intelligence and auto
correct and dictionary stuff needs a whole ux redesign and improvement"*

Four surfaces grew separately and are read as four features: the underlines in
the text, the word menu, the suggestions panel at the foot, and the dictionary.
Two of the four reports were answered before this section was written (the
panel's height, `min(60vh, 32rem)` down to `min(33vh, 22rem)`, and the panel row
anchoring its menu to the word it names rather than to the row under the
pointer). What follows is the rest of it, as one pass with one decision, because
patching the remaining two would leave the fifth complaint, the one that names
the whole thing, untouched.

**Measured first, at 1440x900 (`scratchpad/ui-sweeps/spellwide.js` and
`spellwide2.js`), because three of the four reports are geometry:**

- **The wide gap is a wrapped finding.** A finding whose span crosses a soft
  wrap is one mark element drawn as two fragments, and the menu was anchored to
  `getBoundingClientRect()`, which returns the *union* of them. Measured on a
  doubled "the the" at a wrap point: fragments at `1187..1218` on one line and
  `471..497` on the next, union `left 471, right 1218, top 359, bottom 404`, so
  the menu opened at `471, 408`: **716px to the left of the words that were
  clicked and a line below them.** That is INBOX 128's "off to the side with a
  wide gap", reproduced; the probe that could not reproduce it
  (`spellanchor.js`) measures a single-word finding, which never wraps.
- **Out of bounds is the menu hanging past the card.** A flagged word at the
  end of a long line sits at `left 1161` in a card that ends at `1255`, and the
  menu opened at `1161..1401`: 146 of its 240px clear of the document card, in
  the window's own right-hand gutter, which is what the screenshot shows. The
  placement clamps to the *window*, so nothing said the card had an edge.
- **Two surfaces for one word.** Pressing a panel row put the menu at
  `587..864` over a panel occupying the bottom third of the window: 335px of
  menu over 297px of panel, 70% of the window's height spent on the two
  answers to one misspelled word, with the sentence being discussed behind
  both.
- **One finding, three vocabularies.** The panel row says the reason then the
  words, the menu head says the words then the reason, the underline says
  nothing a reader can see (a `title`), and the feature is called five things in
  four places: "N suggestions" (the chip), "Writing suggestions" (the panel),
  "Your dictionary" (the dialog), "Autocorrect as I type" and "Suggest words as
  I type" (the dock menu).

### Decisions made

**D1. One name and one drawing of a finding.** The feature is *writing
suggestions*. A finding is drawn by one function, `docFindingLine`, in both
places that draw one: a kind dot in the same colour as that kind's underline,
then the flagged words, then the reason, in that order, in the panel row and in
the menu's head. Three surfaces describing one object in three orders is the
"assembled rather than designed" failure DESIGN.md's contrast rule names, at the
level of copy instead of spacing.

**D2. Three scopes, three homes, and no surface does another's job.**
- the underline says **where** and nothing else;
- the word menu answers **this occurrence**: the candidate words, add to
  dictionary, ignore in this document;
- the panel answers **the whole document**: the list, the counts, fix all,
  check with AI, the dictionary;
- the dictionary dialog holds the **standing rules**: the word list and the
  spelling variant.

The two passage actions ("Ask the AI for wordings", "Translate this passage")
are offered on a **passage**, not on a word: a finding whose text is a single
word already has its other wordings in the candidate list above, and
translating one word is a dictionary lookup rather than a translation. This
takes the common menu from nine rows to seven and is the one composition change
here; both actions keep working exactly as they did on the findings that are
passages (a repeat, a spacing slip, a long sentence).

**D3. The panel acts in place, and never opens the floating menu.** A row
expands under itself, inside the panel, with the same candidates and the same
actions the menu offers, and the document scrolls the word to the *middle* of
the editor so it is visible while the row is open. This is the fix for "the box
just appears right there in my face" at its cause: the menu was the only way to
act on a row, so a list at the foot of the window had to open a 335px popup over
the text to answer anything. One surface at a time is DESIGN.md's popover rule;
a panel that has to open a popover to be useful was breaking it structurally.

The open row is the current row: `aria-expanded` on the control,
`aria-current="location"` on the row, painted from the attribute, and brought
into view by the panel's own `scrollTop` rather than `scrollIntoView`, which is
the recipe index's rule for a list that says where you are.

**D4. The floating menu belongs to the text, and it stays inside the editor.**
It is anchored to the **fragment under the pointer** (`getClientRects()`, never
the union), placed inside the editor's own visible box before the viewport is
considered, flipped to the left of the word rather than allowed to hang past the
card, clamped on all four sides, and, if the word is not visible at all, the
editor scrolls it to the middle first. A menu that points at a word that is off
screen is a menu pointing at nothing.

**D5. Nothing here is rebuilt.** The rules (`docProseFindings`), the word list,
the marks, the ranked candidates (`docSuggestAlternatives`), autocorrect, the
ignore list, the dictionary and its server home (`writing_dictionary`) and the
three underline shapes all stay exactly as they are. This section changes where
answers appear and what they are called, which is what the report asks for. The
two writing switches stay in the dock menu, where Phase 0 item 3 put them on
purpose ("a status bar states, it does not configure"); decisions are not
remade.

### Acceptance

In Chromium, measured, both themes: a wrapped finding's menu opens within 24px
of the fragment that was clicked; no menu's box leaves the viewport or hangs
past the editor card's right edge at 1440, 1100 and 820 wide, in Live, Source
and Split, with Large text and Spacious on; pressing a panel row opens no
floating surface at all and leaves the word visible; 0 console errors; contrast
passes.

## Built, the sidebar redesign (INBOX 115), 2026-09-12

Moved to HISTORY.md ("Moved from the plans, 2026-09-12", DOCUMENTS_PLAN.md) on
2026-09-12: a plan holds open work only. What is left open is in
`agent-remaining/doc-sidebar.md`.
