# Backlog — the numbered sections


> **The other three:** [ROADMAP.md](../ROADMAP.md) (live work) · [BACKLOG.md](BACKLOG.md) (§1–§29) · [ANALYSIS.md](ANALYSIS.md) (§30–§34, including the licence constraint — AGPL-3.0 now) · [HISTORY.md](HISTORY.md) (already built).

Split out of `ROADMAP.md`, which had reached 4,500 lines and 47 sections. This
file is the **standing backlog**: everything that is still work, numbered as it
always was, so every §-reference elsewhere still resolves.

The live list — what to do next, and the two sections of freshly reported work
(§35, §36) — stays in [ROADMAP.md](../ROADMAP.md). Analysis and finished work
are in [ANALYSIS.md](ANALYSIS.md) and [HISTORY.md](HISTORY.md).

> **Status, 2026-09-07.** Every UI/UX item in this file (§2 quick wins, §15
> Appearance, §16 Sweeping UI quality-of-life, §19 Accessibility, §24
> Dashboard, §29b's visual rows, §64's editor chrome) is now governed by
> [UI_MODERNISATION_PLAN.md](UI_MODERNISATION_PLAN.md), the top priority in
> ROADMAP.md: do them through its phases, not one by one from here. §6 and
> §63 are done (kept for their numbers). Everything else stands.

> The rule that governs all of it, unchanged: **check the running app before
> building anything here.** Three sessions independently rebuilt something that
> already existed, and an audit of §2 found four of its six "quick wins" done.

## 1. Live log console (started, not finished)

**Why.** Asked for directly: the Logs screen should read "like the terminal
running in the background, with key errors flagged", not a list you refresh by
hand.

**What exists.** `core/logbuffer.py` is a 500-record ring buffer attached to the
root logger and uvicorn's. It now sanitises each message to one printable line
(so a chat question or a page title can't forge a row) and keeps tracebacks in a
separate `trace` field for a fold.

**What's left.** Streaming (NDJSON over `fetch`, not `EventSource` — see
HISTORY.md for why), follow/tail with autoscroll, level/text/source
filters, the `trace` fold, merging in `browserLogs`, and an error badge on
the nav item are all **done** — see HISTORY.md. Also done: **exporting a
support bundle** (an allowlist zip of the log buffer, scrubbed
`preferences.json`, and model status).

- **Getting one error OUT of the log** (asked for directly after the console
  landed: "make sure that if there is an error in the log that it can be
  accessed and copied"). Each record has its own copy button that takes the
  traceback with it, an open traceback has a **Copy traceback** of its own,
  and "Copy all" relabels to "Copy 12 shown" whenever a filter is hiding
  something. **The real find here was underneath:** every copy in the whole
  app went through `navigator.clipboard`, which browsers expose **only in a
  secure context**. `http://localhost` qualifies, which is why nothing had
  ever shown it — but reach the app at `http://192.168.1.20:8000` or through
  a tunnel (§17's mobile-access question, and the proxied client address §8b
  already saw in a real log) and the API is `undefined`, so every copy button
  in the app was a no-op that said "couldn't copy". Copying now tries the
  modern API, then `execCommand` on plain http, then shows the text
  pre-selected in a dialog. A test asserts no caller writes to
  `navigator.clipboard` directly any more, since a helper only some callers
  use leaves the rest quietly lying.
- ~~**Export a support bundle.**~~ **done** — see below; it is an allowlist,
  not a denylist. One button that zips the log buffer,
  `preferences.json` with anything sensitive stripped, and Ollama/model
  status (`/models/status`) into a file the user attaches to a bug report —
  asked for indirectly ("an interface for managing the application… errors
  etc") and echoed by the outside review's "support bundle" suggestion.
  Everything in it is already local and already visible somewhere in the app;
  this only collects it. No new telemetry — the file is written to disk and
  the user chooses whether to send it, which is the difference between this
  and the outside review's other suggestion (opt-in crash reporting),
  rejected in §30.
- ~~**Confirm nothing is silently dropped.**~~ **Done.** `logbuffer.py`
  tracks `_dropped`/`_dropped_since` (a full ring buffer counts what it
  discards rather than losing the fact silently), and the frontend renders it
  — "N earlier records … the oldest record still kept is from …" — whenever
  `stats().dropped` is nonzero.

---

## 2. Quick wins

Small, self-contained, each removing a visible annoyance.

**Nothing here is open — all six are done**, and the section is kept rather
than deleted for two reasons: a `§2` in a code comment still has to land
somewhere, and the *shape* of what happened here is worth keeping. Four of the
six turned out to be **already built when this list was written** — checked in
the running app rather than assumed, because by then three sessions had
independently rebuilt something that already existed. That ratio (four stale
claims out of six) is the single best argument for the "check before you
build" rule at the top of CLAUDE.md, and deleting the evidence would make the
rule look like superstition rather than a measured result.

Already built when claimed as open: the SearXNG install path, the Notes
sidebar sticky rule, a per-code-block copy button in chat answers, and
conversation search by content.

Genuinely built afterwards:

- **Empty chats could not be deleted.** A `Delete` button in the chat toolbar
  now covers both cases — an empty or unsaved pane resets silently, a saved
  one gets the sidebar's own confirm dialog and then
  `DELETE /conversations/{id}`.
- **Document outline / table of contents, word-count goal, reading time** —
  all three, not just the outline. `renderDocOutline` builds the TOC,
  `renderDocStats` shows reading time, and `promptDocWordGoal`
  (`#doc-word-goal`) is a working word-count-goal control. §5 already recorded
  the outline and reading-time halves as done and called the word-count goal
  "the one unbuilt part" — it was built too.

---

## 3. Chat page: Chat / Agent / Browse sub-tabs

> **Status (audited this session, ROADMAP.md §38 item 5): substantially done,
> via a different — and, on the evidence, better — shape than "three
> sub-tabs".** Checked against the actual code rather than re-reading this
> section's original wording as a spec:
>
> - **Chat vs Agent** → the Ask/Agent mode toggle in the chat dock, not a
>   tab switch. Same distinction, one click instead of a navigation.
> - **Browse** → the web panel (§36G), a persistent column beside the
>   conversation rather than a third tab — and §36G's own reasoning
>   ("a reading surface cannot live inside a control strip... as a column it
>   needs no cap and sits beside the composer") is a real argument *against*
>   folding it back into a tab, not just a different implementation of the
>   same idea.
> - **Cross-linking** ("the agent hands a page to Browse, Browse hands a page
>   to chat") → `askAboutPage()` does the Browse-to-chat direction (💬 Ask
>   about this closes the panel, asks the agent to `read_url` the page).
> - **Visible plan/progress** → `make_plan`'s ticked-step display, built
>   since (§35's "Next session: start here" item 1), satisfies this more
>   generally than a per-tab progress view would have.
> - **Independent web-search gating** ("works even when the chat/agent
>   web_search tool is off") → there is one `web_search_enabled` pref
>   already, not two competing toggles to decouple; the panel opens
>   regardless and says plainly why a search won't work if it's off, rather
>   than being blocked by a separate "Agent mode" switch.
>
> **The one genuine, real, small gap:** "which tools are allowed this turn,
> max rounds" as a **user-facing** Agent-mode control. `agent.py`'s
> `_agentic_reply` already takes `allowed_tools`/`max_rounds` as real
> parameters — the backend has the knob — but nothing in `app.js` exposes it;
> tool selection is automatic (`tools.focus_for`) with no manual override UI.
> Worth building only if a real use case shows up wanting it (most users want
> automatic selection, not a per-turn allowlist to manage); not worth a
> session on its own.
>
> **A second small gap, scoped but not built:** a tool-call chip today is a
> flat one-line label (`toolChip()`, app.js ~6200) — no way to see what the
> AI actually sent the tool or what came back, purely a cosmetic upgrade
> asked for directly ("a dropdown which shows the input tool call command
> and the output... collapsed by default... doesn't affect the AI, only a
> visual upgrade"). Real but genuinely multi-file, not a CSS tweak: `agent.py`
> already has `arguments` in scope where it builds each tool event but the
> SSE stream to the frontend only ever sends a human-readable `label`, not
> the raw arguments or the raw result — those would need adding to the event
> payload (additively; the model's own context is built from a separate
> prompt-construction path and would be untouched, so this is safe to add
> without the caveat in the ask being a real risk). Frontend: `toolChip()`
> becomes a `<details>`/`<summary>` with two collapsed sections (input as
> formatted JSON, output in a `overflow-y: auto` box for a long result) —
> and the chat-history `serialise()`/`replay()` round-trip (app.js ~6083)
> needs the same two fields or the dropdown disappears the moment a saved
> conversation is reopened, which would read as a second bug. Three files,
> one new SSE field, one schema change to what a saved conversation stores —
> real work, correctly deferred rather than rushed this session.

**Why.** Asked for directly. The page mixes three activities in one column, and
the web panel is bolted on top of the message list.

**Shape.**

- **Chat** — plain grounded Q&A
- **Agent** — tool-calling with its own controls: which tools are allowed this
  turn, max rounds, visible plan/progress, and a stop that keeps what it already
  did
- **Browse** — web search results, reader view, page history

Cross-linking is the point: the agent hands a page to Browse, Browse hands a page
to the chat. Web-search gating should be independent — a Browse-only mode where
the section works even when the chat/agent `web_search` tool is off.

**On the "in-built browser".** In the browser-served app this can only be an
`<iframe>`, and most sites send `X-Frame-Options`/`frame-ancestors` that refuse
to load in one — it would fail on exactly the sites worth opening. Proxying and
rewriting pages server-side is effectively writing a browser, and re-introduces
every tracker the privacy work removed. So the reader view stays the web path,
and a genuine embedded browser belongs in the desktop shell, whose webview can
navigate anywhere. **This ties §3 to §7.**

---

## 4. Library tab: chats, documents, images, archive

> **Status: item 4 (the Library tab itself) is done — §36F/G built it and it
> now absorbed the Notes tab's Bin/Activity/Tags panels too, well past this
> section's original scope. Item 1 (drag-drop any file type onto the capture
> box, OCR on uploaded images) is now also fully done, OCR being the last
> genuinely open piece (ROADMAP.md item 30d). Item 3 (`archived_at` — notes'
> own archive shipped; chats/documents still don't have one, see ROADMAP.md
> item 30b) is still genuinely open.** This section read as entirely unbuilt
> before an earlier audit, which is exactly the kind of staleness that costs
> a session; check `routes_library.py` and the `Entry`/`Document`/
> `Conversation` models before assuming otherwise.

**Why.** Asked for directly. Everything that isn't a note lives only in its own
tab, and there is no archive at all.

**Order matters — images first, since the gallery is a view over what they
store:**

1. **File uploads on notes — asked for again, directly: "I want to be able
   to upload files with notes."** Worth being precise about what's already
   there versus what isn't, since this is narrower than it sounds:
   - **Already exists:** images can be pasted or dropped into a note or
     document (this item, above), and `📎 Attach a file` stores an arbitrary
     file (PDF, `.docx`, anything) against a note and gives you back a
     download — so the storage layer and one upload path both already
     handle non-image files.
   - ~~**What's actually missing:** that attach path is a button, reached
     after the note exists — there's no drag-and-drop of an arbitrary file
     straight onto the capture box itself.~~ **Stale — already done.**
     `app.js`'s global `dragover`/`drop`/`paste` handlers match *any*
     `<textarea>` (including `#entry-content`) and already filter for
     `image/`, `application/`, `text/`, `video/` and `audio/` — not
     image-only — and attach every file in a multi-file drop, not just the
     first. A file-picker button (`#entry-attach-file`) reuses the same
     `handleFileUpload` for a third path. See the "ROADMAP.md Tier 2 §16c"
     comment right above `#entry-attach-file`'s listener in `app.js` — this
     was checked and closed a session ago; this bullet just never got
     updated to say so.
   - ~~**Genuinely still open:** a non-image attachment showed no preview in
     the note card~~ **Done, both halves.** `handleFileUpload` always wrote
     `![name](url)` (image markdown) regardless of file type, so a
     PDF/docx/etc. rendered as a broken `<img>` and its `onerror` handler
     reported it as **"filename deleted"**, actively lying about data loss —
     non-image files now get plain link markdown (`[name](url)`) instead.
     And that link now carries a type-specific Phosphor icon
     (`attachmentIconClass()` in `app.js`, keyed off the file extension for
     `/media/` uploads only — an arbitrary external link's extension isn't
     trustworthy enough to icon the same way) instead of reading identically
     to a plain URL.
   - ~~**A step further, genuinely new: extracting text from what's
     uploaded, not just storing it.**~~ **Done — see ROADMAP.md item 30d
     and HANDOVER.md's latest entry.** Local `pytesseract`/Tesseract, on a
     background thread, feeds the Library's own Image Gallery search (new)
     rather than the notes' FTS5 index this bullet originally pointed at —
     a `MediaUpload` isn't an `Entry`, so that was the honest integration
     point once the actual schema was checked, not the literal one this
     text guessed at. "What was on that whiteboard photo from March" is
     now answerable.
2. **A bigger sketch board — asked for again: "improve sketches board, maybe
   a whiteboard tab??"** See below; promoted out of this list into its own
   full write-up given how much is actually being asked for.
3. **Archive.** A state between "active" and "binned", for things you want out
   of the way but not deleted. Applies to notes, chats and documents: one
   `archived_at` column per table, an additive migration.
4. **Library tab.** One place showing stored images, documents, chats and
   archived items, with previews, sorting and search.

---

## 4a. A real whiteboard, not just a bigger sketch

**Why, and what's actually being asked for.** The sketch pad today is one
canvas producing one PNG, tied 1:1 to one note — closer to a Polaroid than a
whiteboard. "Expand and improve sketches board, maybe a whiteboard tab??"
plus the follow-up ask for it directly means something with more freedom
than that: a canvas that isn't locked to a single note, that you can come
back to and keep adding to, and that plausibly holds more than ink — text
boxes, shapes, maybe pinned note cards.

**Two genuinely different things live under "whiteboard," and they have very
different costs:**

- **A bigger, freestanding sketch.** Still a raster canvas producing one
  image, same technology as today's sketch pad — the difference is it's not
  born attached to a note (it's its own Library item, per §4 item 4 above),
  it can be reopened and drawn on further rather than being a one-shot
  export, and it can be arbitrarily large/pannable rather than a fixed
  small pad. This is genuinely close to what already exists: same
  `attachments` storage shape, same rendering approach, mostly a change in
  *lifecycle* (persistent and reopenable, not one-and-done) rather than new
  technology.
- **A structured canvas** — separate movable/resizable elements (shapes,
  text, sticky notes, embedded note cards you can drag onto it), each
  stored as its own positioned object rather than baked into one flat
  image. This is what tools like Excalidraw or tldraw actually are, and
  it's a different kind of feature: an infinite-canvas scene graph with its
  own undo model, not an extension of the sketch pad. It's also the version
  that would let a whiteboard hold *note cards* pinned to it — which is the
  part that would make it feel like part of this app rather than a bolted-on
  drawing tool, since nothing else here does that.

**Worth sequencing rather than picking one.** The freestanding raster
version is a small, mostly-lifecycle change and delivers most of the
"expand the sketch board" ask on its own. The structured version is a real
build — a second rendering system alongside §9's graph — and is only worth
it if the raster version turns out to not be enough. Ship the first as the
actual whiteboard tab; treat the second as a stretch goal that depends on
whether people actually want to move things around after drawing them,
which is not knowable in advance.

**Where it lives.** Library tab (§4) as its own item type is the better fit
than nesting it under Notes — a whiteboard that isn't 1:1 with a note has
nowhere natural to sit in the Notes tab, and the Library tab is already
being built as the home for "everything that isn't a note."

---

## 4b. Templates and base layouts (boards, maps, documents)

Asked for 2026-09-13, looking at a board an agent had built to photograph for
the README: *"add the ability to save whiteboard templates and base layouts, Im
inspired by this example whiteboard png the agent took and it can be like canva
templates, same with the mindmap and documents."* Deferred out of the 0.3.0 PR
by the owner the same day: *"put the templates idea in the roadmap, not for
this pr."*

**Most of this exists and must not be rebuilt.** Notes already have templates
(`BUILTIN_TEMPLATES` in app.js, with a "Yours" group beside a "Built-in" one,
offered through `#entry-template`) and that grouping is the shape the request
describes. Documents already have "new from template" with `{{date}}` and
`{{title}}` substitution, and DOCUMENTS_PLAN Phase 5 item 5 already specifies
the gallery. Boards can already be copied whole through
`POST /whiteboard/boards/{board_id}/duplicate`, and `BoardOut` already carries
`preview_items`, `preview_edges` and `preview_aspect`, which is what draws the
board cards in the Library, so the gallery's thumbnails are solved.

So the feature is one idea: a board, map or document *marked* as a template,
shown in a gallery with a preview, copied on use. The full brief, including the
decision to record first (where the mark lives: `board_settings` on the board's
own note, the way `type` and `layout` already do, against a separate table) and
the build order (boards, then maps, then documents, each end to end), is
SESSION_BRIEFS.md Brief 32.

## 5. Documents

Checked against the running app, not assumed:

- ~~**Outline / table of contents**, reading time~~ **done.** `renderDocOutline`/
  `renderDocStats` — see HISTORY.md.
- ~~**Expand a note into a document**~~ **done** — leaves the note untouched
  and says so.
- ~~**Word-count goal**~~ **Done.** `promptDocWordGoal`/`#doc-word-goal` set a
  target, persisted per-document (`docWordGoal:<id>` in localStorage), with
  progress shown against it.
- **AI chat bar inside the document** — partly there. `doc-ai-panel` already
  edits a selection or the whole document and shows the result as a proposal.
  What's missing is the *conversational* shape: ask a question about the
  document without it proposing an edit.
- **A real document browser** — the sidebar list is not a gallery
- ~~**Attach documents to notes**~~ **done, both directions.** The capture
  box's *Add to document* picker, a note's own 📄 chip/menu entry, and a
  document's list of the notes it draws on all share the same two
  `document_links` routes — see HISTORY.md.
- **Document history** — notes have `EntryRevision`; documents have no
  equivalent table, and the AI edit overwrites on accept

### Asked for this session, not yet built

A round of use produced four requests about documents at once, and they are
one direction rather than four features: *"I want the documents to be more
like using Obsidian or Notion."* Ordered by how much each one gets in the way.

- **A mini AI chat bar in the document editor.** Asked for directly: *"a mini
  chat bar on the documents page to request the ai to do stuff, like write
  something, edit something specific (the whole document or current selection
  etc)."* This is the biggest of the four and the closest to already existing:
  `doc-ai-panel` edits a selection or the whole document and shows the result
  as a proposal, so the *editing* half is built. What is missing is the
  **conversational** half — a bar you type an instruction into, in place, that
  can either answer about the document or propose an edit to it, and that
  keeps the thread of what you have already asked. Two decisions to make
  before building it: whether it shares `/chat`'s conversation store (a
  document's thread is about the document, so probably its own), and whether
  an instruction with a selection active always means "edit this" (it should
  — ambiguity there is what makes an AI editor feel unpredictable).
- **Upload a file as a document, attached to a note.** Asked as *"I want to be
  able to upload a document to a note"*. Distinct from `📎 Attach a file`,
  which stores a blob against the note and gives you back a download: this
  would take a `.md` or `.txt`, make it a real Document with its text in the
  editor, and link it to the note in one step. The pieces exist — `/files`
  ingests uploads, `/documents` creates, `document_links` joins — so this is
  mostly a route that does the three together, plus deciding what to do with a
  `.docx` or a PDF (probably: refuse politely rather than half-convert).
- **Obsidian/Notion editing — asked for again, more emphatically: "have all
  the features as well."** Worth being explicit about what "all the
  features" would actually include, since Obsidian and Notion aren't the
  same product and "all of both" isn't a coherent target. The editor is a
  `<textarea>` with a preview beside it today. What people mean by this
  request, roughly in order of how much each is missed:
  - `[[wiki links]]` between documents (notes already have them — the
    parser is in `renderNoteText`)
  - a `/` command menu at the cursor
  - drag-and-drop images that land as markdown
  - backlinks ("what links here")
  - live-preview editing where the markup renders in place instead of in a
    second pane — the one that would change the feel and also the one that
    means giving up the textarea; worth doing deliberately, and last
  - **Sub-pages.** Notion's documents nest into a tree; MemoryMap's are
    flat. Worth deciding this one early rather than late, since it's a data
    model question (`documents` would need a `parent_id`) that every other
    item in this list is easier to build on top of than to retrofit under.
  - **Transclusion — embedding, not just linking.** `document_links` already
    connects a note to a document, and `[[wiki links]]` connect document to
    document, but both are references you click through, not content
    rendered inline. Obsidian's `![[note]]` embeds the note's actual text
    where you put the embed. This is the feature that would make the
    notes/documents "two halves of a whole" framing actually true visually,
    not just at the data layer — worth building once backlinks exist, since
    an embed is close to a backlink that renders instead of just linking.
  - **A full properties/database system is worth ruling out explicitly,
    not leaving ambiguous.** Notion's defining feature is that a page can
    carry structured properties and be queried like a database row — that's
    a different kind of thing from a markdown document with metadata, and
    building it properly would mean a second data model living alongside
    notes' tags/categories rather than reusing them. Worth deciding this is
    out of scope on purpose (tags and categories already give notes
    lightweight structure; documents don't obviously need a second, heavier
    system) rather than something quietly missing from an "all the
    features" list that was never going to include it.
- **Documents on the graph and the timeline.** Asked as *"docs should also
  probably show on the graph and timeline"*. Both views are built around
  `Entry` and would need a second node/point kind. The design question is not
  technical: a document is not a note, and drawing it as one would say the
  wrong thing. On the graph it wants its own shape and to sit where its notes
  are (it is a hub over them, which is exactly what `document_links` records);
  on the timeline it wants to be a band or a marker rather than a dot, because
  a document is written over weeks and a note happens at a moment.

---

## 6. OpenAI-compatible backends — **done**

Built — the detail moved to [HISTORY.md](HISTORY.md) ("Retired from the live files, 2026-09-07"). Kept for its number.

## 7. Desktop packaging

**Windows installer: built, not yet run for real.** Asked directly which of
portable/installed/both, which platform(s) first, whether to pay for code
signing, and where to distribute — answers: installed (not portable),
Windows only for v1, unsigned for now (a certificate isn't worth it before
there's a user base to justify the yearly cost), GitHub Releases only. Built
on those answers: `packaging/windows/memorymap.spec` (PyInstaller, onedir —
onefile re-extracts itself on every launch, a bad fit for something meant to
open like a normal desktop app), `packaging/windows/installer.iss` (Inno
Setup, per-user install so an unsigned build doesn't *also* need an admin
prompt on top of the SmartScreen click-through), and a `build-windows-
installer` job on `release.yml` that builds and attaches the installer to
the GitHub Release a `v*` tag already creates. `core/config.py`'s
`_default_data_dir()` and `api/app.py`'s `FRONTEND_DIR` both needed a
`sys.frozen` branch — their existing path math assumes a `src/` layer a
PyInstaller bundle doesn't have, which would have pointed both at the wrong
directory silently.

**Honestly unverified**: this repo has no Windows machine to build or run it
on, so none of the above has executed for real yet — only reasoned through.
It ships from CI (windows-latest) on the next `v*` tag, which is a real
Windows build the moment it runs; what's unverified is specifically whether
that first real run succeeds without a fix. Worth watching the first
tagged release's Actions run rather than assuming green.

**"Does the installer stay up to date?" — built: a check, not an auto-update.**
Asked directly. Answer: no, and it was never going to — a static installer
build has no mechanism to patch itself, and building one (differential
updates, a signed update feed) is a lot of infrastructure for a project at
this stage. What shipped instead, since the alternative is a user on a
six-month-old build with no way to know it: `update_check_enabled`
preference (off by default, same reasoning as `web_search_enabled` — see
`core/config.py`), a `GET /update/check` endpoint that compares
`memorymap.__version__` against GitHub's `releases/latest` tag numerically
(never lexically — "0.10.0" has to sort after "0.9.0"), and Settings → About
wiring: the checkbox, a "Check now" button, and a silent check on startup
that only ever toasts when a newer version genuinely exists. Two real bugs
were caught testing this live rather than trusting it once it typechecked:
`PreferencesBody` (routes_settings.py) never declared the new field, so
Pydantic silently dropped it from every PUT; and `get_preferences()` built
its response as an explicit field-by-field dict that never echoed the new
key back — the exact bug this same file's own comment already describes
happening once before, to `autonomous_tasks_enabled` and friends. Both fixed
and re-verified live (Playwright: toggle, reload, confirm it survives).

**Why.** Asked for: "run as a professional product".

**Recommendation: not Electron.** The app is Python + static files; Electron
would bundle a second runtime (~150 MB) and a Node toolchain to deliver what
`--desktop` already does in-process via pywebview, and Python would still need
shipping alongside it. Alternatives weighed: Tauri and Wails (Rust/Go shells,
tiny binaries, but neither solves shipping Python), Neutralino (immature), plain
PWA (already supported via `manifest.webmanifest` + `sw.js`).

**Plan, updated — some of this is now built, not still planned.** Hardening
the pywebview mode: **tray — built**, see §25. Single instance, native menus,
graceful port fallback when 8000 is taken, and a first-run flow specific to
the packaged build are still open. The "PyInstaller one-file" half of this
paragraph is superseded by the actual decision recorded above — **onedir**,
not onefile, because onefile re-extracts itself on every launch. pywebview's
webview is also where the genuine embedded browser from §3 becomes possible.

**Portable vs installed, worth deciding rather than defaulting into one.**
PyInstaller can build either — a one-file executable that runs from a USB
stick with `data/` beside it, or a real OS-integrated install (Start Menu
entry, `/Applications`, an uninstaller). They want different things from
`MEMORYMAP_DATA_DIR`: portable mode wants data relative to the executable by
default (so the whole thing is one folder you can move); an installed app
wants a proper per-user data directory (`%APPDATA%`, `~/Library/Application
Support`, `~/.local/share`) so it survives a reinstall. Worth picking the
default deliberately per platform rather than the build script producing
whichever one falls out of the PyInstaller config first.

**Cross-platform status, since it was asked about directly** ("make
memorymap-ai cross-platform and compatible with linux and if possible mac as
well"): closer to done than the ask implies. `start.sh` already exists
alongside `start.bat`, and the app itself is Python + SQLite + a browser, none
of which is Windows-specific. What genuinely is Windows-specific: the two
`searxng_manager` fixes in §8b (`os.kill(pid, 0)` terminating instead of
checking, `rmtree` failing on git's read-only objects) are guarded to only
run their Windows branch, so they should be harmless elsewhere, but that is
still unverified on real macOS/Linux hardware rather than reasoned from the
code — the honest status is "should work," not "confirmed." The PyInstaller
builds above are the part with no cross-platform equivalent yet at all.

---

## 8. Open bug list

Every bug this section originally listed — the launcher breaking on a folder
rename, a theme picker whose layered defaults silently cancelled part of
each new theme, the Lagoon/Shallows palette refinements, background tasks
showing nothing while SearXNG started, the cramped AI emblem, the dashboard
widgets missing until a tab switch, plus a long table of "reported as / what
it actually was" fixes (numbered lists, chat-bubble overflow, "Invalid
Date", CSS specificity ties, sketches not opening from the graph, web search
silently returning nothing) and the bugs found incidentally while fixing
those — has been reproduced in Chromium and fixed. Full detail, including
*what each report's real cause turned out to be* (the expensive part to
repeat if it isn't kept), is in HISTORY.md.

**From the ideas parking lot, never formally triaged.** Reported informally
(`IDEAS.md`) rather than reproduced in a browser yet — worth the same
ten-second grep-first check as everything else in this document before
anyone spends a session on them:

- **A note filed under the wrong category by a wide margin** — "I wrote 'ai
  is cool' as a note and it was filed under Sketches". Sketches is a specific
  category the janitor's cheap embedding-centroid path can match against
  (§4 of `ARCHITECTURE.md`), so this smells like a centroid gone stale or too
  few notes in the right category to out-vote it, rather than a one-off.
  Worth checking what "Sketches" actually contains before assuming the AI is
  at fault.
- **Settings can't be reached on a narrow/mobile viewport.** Distinct from
  the general accessibility pass in §19 — this is specifically Settings, and
  worth checking against the header's documented degrade order (§10 of
  `ARCHITECTURE.md`) before assuming it needs new CSS rather than a missing
  breakpoint.
- **Some dashboard widgets don't render markdown.** The note list's
  `renderInlineMarkdown` (§22) was deliberately not extended everywhere; the
  dashboard's own small note previews strip markers instead
  (`notePreviewText`). A widget showing raw `**bold**` is likely one that
  calls neither — worth an inventory of which dashboard widgets go through
  which path.
- **The "notebook constellation" widget doesn't redraw on a theme change.**
  The graph's galaxy/starfield styling (§9) points at this widget as proof
  the aesthetic works; §10 of `ARCHITECTURE.md` already documents the general
  version of this bug for the emblem (p5 measures a canvas as zero inside a
  hidden tab, and has to redraw on theme change since the accent moves) —
  very likely the same cause in a second place.
- **Gravity and Spread only affect the force-directed layout.** Real:
  `nodeSize`/panning-based tree and radial-ring layouts (§9) don't run a
  physics simulation, so these two controls have nothing to act on outside
  the default layout. Not obviously a bug — worth deciding whether they
  should grey out under tree/radial, or gain layout-specific meaning (row
  spacing, ring gap) instead of silently doing nothing.

**Still open here**

- **Improve the extracted page's visual rendering.** Not a bug — the reader now
  carries heading levels, so it can be laid out as a real document (typographic
  scale, measure capped around 70ch, blockquotes, lists, code). Grouped with
  §13.

**The lesson worth keeping.** Four of these were "this control does nothing",
and in three of the four the control was working perfectly — the write landed
and was then overridden by CSS source order, a status poll, or a hidden
section. Reading the handler will not show you that. Reproduce in a browser and
measure the *computed* result; it is faster than reading, not slower. The
recurring causes are now written up as invariants in `docs/ARCHITECTURE.md` §10.

---

## 8b. Web search — two Windows bugs found, and what is left

~~**Port 8888 being taken was a dead end.**~~ **fixed.** `start()` now
settles a port first (the wanted one, else 8080/8081/8890/8899, or
`MEMORYMAP_SEARXNG_PORT`).

**Not yet fixed:** a start attempt and an install can be in flight at the
same time — a start already waiting when a reinstall begins sits out its
full `START_TIMEOUT` against a virtualenv being rebuilt underneath it, then
blames SearXNG for writing no output. Fixing it properly means making
`_wait_until_ready` interruptible (a generation counter or a
`threading.Event` that `install_source` sets). Not a quick change, which is
why it is here rather than done.

**SearXNG itself now installs, starts, answers its JSON API, passes
`websearch.probe_searxng`, and returns real results on a user's own
Windows machine — confirmed, not deduced.** Six real bugs stood between
"install path exists" and that (three platform-independent — a Windows-only
`git clone` colon-in-filename failure, `pip install -e .`'s isolated-build
`msgspec` import error, and the `tracker_url_remover` plugin dying at boot
on any offline/proxied machine; three Windows-only — `os.kill(pid, 0)`
actually terminating the process instead of probing it, a stale
`is_checkout()`/`shutil.rmtree` interaction that made a failed reinstall
reproduce itself, and the POSIX-only `import pwd` in `searx/valkeydb.py`).
Full diagnosis of each, and the fix, is in HISTORY.md — worth reading in
full if SearXNG install/start is ever reported broken again, since the
shape ("Windows-only", "happens before SearXNG writes a line") is a strong
signal for which of the six it is.

Also present, from earlier sessions: a `↻ Reinstall` button (wipes the venv
and checkout, keeps `settings.yml` and its secret key) and a port line saying
whether 8888 is free, held by a working SearXNG, or held by something else.

**A deliberate security pass, rather than more one-off fixes.** Asked
broadly — "full security sweep and analysis… must be fully private, hack
proof, and secure… web browsing should be as private, secure, and
untrackable as possible" — which is this section's whole subject already,
just not gathered into one pass. What exists today: the CodeQL alert list is
closed, the DNS-rebinding TOCTOU on both the reader and the SearXNG search
path is closed, redirects are re-checked hop by hop rather than trusted,
private notes are encrypted and excluded from every AI tool, and CodeQL
runs on every push plus weekly. Brute-force protection on the unlock gate,
a tight CSP, the scrypt KDF behind private notes, and cross-origin
protection on the local API are all **done** — see HISTORY.md and §20.
What a deliberate pass would add on top, parallel to §19's accessibility
audit:

- A dependency-vulnerability sweep (`pip-audit` / `npm audit` equivalent for
  the vendored JS, since nothing currently checks either), and a fresh look
  at this section's own three easy-to-break rules (§8b's opening) to confirm
  nothing has quietly regressed since they were written down.
- **Search-specific items** now live in §13, since SearXNG went from "being
  built" to "actually running" this pass.

---

## 9. The graph — make it a tool, and give it a look

**Why.** Asked repeatedly: "expand on the capabilities of the graph", "more
utility and ways to use and visualise my notes", "it's still kinda plain — it
needs more life and design style". `main` made it keyboard-operable; it is still
a plain force-directed blob that doesn't fill its own panel.

**Layouts — the shape the notes are arranged in.** Asked for directly: "can
you add different types of graph views… like tree graph diagrams and the
like". These are separate from *styling*: a layout decides where a note goes,
a style decides what it looks like once it is there. Layouts first, because a
force-directed blob is the thing that makes the graph hard to read, and no
amount of styling fixes it.

The notebook has three different structures in it, and each one wants a
different picture:

| Structure | Where it comes from | Layout that shows it |
| --- | --- | --- |
| Hierarchy | category → note, and `parent_id` threads | tree, radial tree, treemap, sunburst |
| Network | `entry_links` (wiki links, AI links) | force, arc diagram, adjacency matrix |
| Sequence | `created_at`, `entry_dates` (§10A) | timeline-graph, growth animation |

- ~~**Tree**~~ and ~~**radial tree**~~ **built**, then re-fixed after a
  reported readability bug (both were first sized to the panel's raw
  dimensions rather than by what a label needs — see HISTORY.md for the
  `nodeSize`/ring-by-depth fix and the three label-collision bugs it also
  found).
- **Mind map from one note** — pick a note as the root and lay everything else
  out by hops along `entry_links`. Different from the tree above: the
  hierarchy there is filing, here it is connection.
- **Treemap / sunburst** — area as weight, so a category with 200 notes looks
  like one. Best for "where does my writing actually go?", and the only layout
  here that answers a question about proportion.
- ~~**Arc diagram**~~ **built, on the filing hierarchy rather than
  `entry_links`** (a deliberate departure from this bullet's original "links
  as arcs" framing — tree and radial already draw the *filing* hierarchy, and
  a links-as-arcs view is still a real, different, unbuilt layout). Verified
  in Chromium against a seeded notebook — see HISTORY.md.
- **Adjacency matrix** — no crossing edges at all, so it stays readable when a
  force graph has turned into wool. Worth it only once there are hundreds of
  links.
- **Timeline-graph** — the graph laid out left-to-right by date, links as
  arcs. §10's Timeline tab does the axis; this would do the axis *and* the
  links, which is the one thing neither view has.
- **Subway map** — orthogonal edges, categories as lines. Beautiful and
  genuinely hard: it needs edge routing, which is real work rather than a
  layout call.

**Styling — the same layout, dressed differently.** These are skins over
whichever layout is picked, not layouts of their own:

- **Galaxy / starfield** — notes as stars sized by access count, links as
  faint filaments. The dashboard's "notebook constellation" widget already
  proves the aesthetic works.
- **Sea chart** — islands per category, notes as landmarks, links as shipping
  routes, unlinked notes adrift. Parchment palette pairs with it.
- Plain force-directed stays the default; everything else is a picker.

**Fit and framing.** It should size to its panel and re-fit on resize, with
zoom-to-fit, zoom controls, and a minimap for large notebooks.

**Utility it still lacks:**

- Filter by category, tag or date range; double-click to focus a neighbourhood
- **Paths between two notes** — the question a graph is uniquely good at
- Cluster detection, with "name this cluster" handed to the AI
- Orphans and hubs surfaced explicitly
- Create a link by dragging one node onto another
- Timeline scrub — play the notebook's growth
- PNG/SVG export of the current view
- A `related_notes(id, depth)` tool so the model can walk links, not just
  similarity

---

## 10. Timeline tab, and time-aware notes

**Why.** Asked for directly, and it is the most substantial new idea in the
backlog. Notes say "today", "yesterday", "last week", "two days ago" — phrasing
that is correct when written and misleading forever after. Today nothing records
what those phrases *resolved to*.

**Three parts. The first two are done — the third is the one asked for again,
more directly, and is not built yet:**

~~**A. Resolve relative time at capture.**~~ **done.** Every note's temporal
phrases are resolved when it is saved and stored in `entry_dates` with the
phrase beside the date; `entry/timewords.py` is deterministic regexes and
arithmetic, not a model call. Shown as a chip on the note rather than marked
up inside the text. See HISTORY.md for the full list of handled phrasings.

**Still open from A:** tagging notes that contain relative time so they are
findable as a class, and nudging on stale ones ("this said 'tomorrow' three
weeks ago — did it happen?"). Both are queries over `entry_dates` now that
the data exists.

~~**B. A Timeline tab.**~~ **built, first version — and it is a grid, on
purpose, for what it's for.** A time axis across, one band per category or
tag down the side, a bucket size you pick, drawn as a CSS grid (not SVG) so
it scrolls/tabs/reads-aloud for free, capped at eight bands plus "Everything
else".

~~**C. A branch/line view**~~ **built — asked for again, more directly,
because B reads as a calendar rather than a timeline.** A spine plus one
lane per band, connected by a stub at each band's first note; the branch
source is category/tag (not §9's cluster detection — see HISTORY.md for
why), and "rejoins the spine" was deliberately not built (a branch runs its
full lane length, which is a more honest shape than implying a thread
concluded). A real hit-testing bug (an invisible connector stub eating
clicks meant for the dots above it) was found and fixed verifying this
live. Verified in Chromium against seeded notes across four categories and
a reply thread; the one thing not verified is the tick-label spacing
against a notebook that genuinely spans weeks or months (all seeded notes
landed on the same day). No new table — reads `entry_dates` (§10A) and the
existing category/tag grouping; the only new state is a `localStorage`
view preference.

**Still open in B (the grid view):**

- **Events as bands.** The shape this slots into: one more `group` value, once
  there is an `events` table. Places and themes can be derived from what is
  already stored; events cannot.
- **Reminders and their completion** as points on the axis.
- **Zoom from days to years as a gesture**, rather than a bucket picker.

**Data shape:** a new `events` table (`title`, `at`, `precision`, `kind`,
`entry_id?`, `source`), plus `entry_dates` for resolved expressions. Both
additive.

---

## 11. Performance, accuracy and AI efficiency

### Headroom — evaluated, not adopted

Asked: *"is it worth trying to analyse and implement something like headroom
for token efficiency?"* ([headroomlabs-ai/headroom][hr] — Apache-2.0, 62k
stars, active). It compresses tool outputs, logs and RAG chunks before they
reach the model: 60–95% off JSON, 15–20% for coding agents, with benchmark
accuracy held. It is a good project. It is the wrong fit here, for three
reasons that are about **this** app rather than about it:

1. **There is no token bill.** Ollama runs on the user's own machine, so a
   token costs latency and context window, not money. Headroom's headline
   numbers are savings on a metered API.
2. **It would compete for the same CPU.** The compression path wants ONNX
   Runtime and a transformer of its own, running immediately before the local
   LLM on the same hardware. Saving 1–2k tokens of prefill by spending an
   inference pass is very likely net-negative on wall-clock for a 7B model on
   a laptop — and it needs AVX2, which is not a promise this app can make.
3. **The JSON it would compress is the JSON that cannot be compressed.**
   This one was worth measuring rather than assuming, and the measurement
   moved the answer. A representative agent prompt — ten retrieved notes, two
   turns of history, focused tools:

   | Part | Chars | Share |
   | --- | ---: | ---: |
   | System prompt (prose) | 2,521 | 34.4% |
   | History (prose) | 77 | 1.1% |
   | Notes + question (prose) | 1,381 | 18.9% |
   | **Tool schemas (JSON)** | **3,340** | **45.6%** |
   | Total | 7,319 | |

   So the prompt *is* nearly half JSON — more than expected. But that JSON is
   the **tool schemas**, and Headroom compresses tool *outputs*, logs, files
   and RAG chunks. A schema is a contract the runtime parses to constrain the
   model's tool calls; compress it and the calls stop being valid. It is the
   one JSON block in this prompt that has to go verbatim.

   What is genuinely in scope: the notes (18.9% — this is the RAG-chunk case
   Headroom is built for) and the tool results appended during a loop, which
   are already hand-shaped summaries (`_note_summary`: id, preview, category,
   tags, dates). At its own headline 60% on the addressable part, that is
   roughly 11% off the prompt — real, but not the 60–70% the numbers suggest
   at a glance, and not worth ONNX Runtime to get.

   **The 45.6% is still the thing to attack — just not with compression.**
   `focus_for` already took it from 10,215 to 3,340 characters. Getting it
   lower is more schema pruning: shorter descriptions, fewer tools per focus,
   dropping parameters with obvious defaults. That is the highest-leverage
   work left in this section and it costs nothing but care.

Set against a **hard** cost: ONNX Runtime plus a model download, in an app
whose whole proposition is offline, self-contained and light — one that
vendors d3 and p5 locally rather than take a CDN.

**What was worth taking from it, and cost nothing:**

- ~~**Prefix-cache alignment** (their CacheAligner)~~ **done, and it found a
  real bug.** The idea is to keep the front of the prompt byte-identical so
  the provider's KV cache survives. Checking ours against that: the system
  prompt carried `local.isoformat()` — *microseconds* — above the history and
  the notes. Every round of every turn differed from the last, so Ollama's
  prefix cache could never hold anything below that line, and each round of a
  tool loop re-read the entire prompt. Now to the minute, which is identical
  across the rounds of one loop and still correct for everything the app does
  with it ("remind me in 10 minutes" is not resolved to the second).
- ~~**Reversible compression** (their CCR — send a short form, let the model
  fetch the original on demand)~~ **done.** A note now goes into the prompt
  capped at `MAX_NOTE_CHARS` (900), cut with a marker naming the call that
  reads the rest: `… [cut — call get_note(7) to read it in full]`. Safe only
  because the model can undo it, which is the whole idea — and the tools guide
  already told it to call `get_note` before quoting. Most notes are a line or
  two and are untouched; ten notes of 4,000 characters used to be 40,000 and
  now fit the budget.
- **Verbosity steering.** Output tokens are half the latency and are not
  budgeted at all. A style hint already exists; a length hint does not.
  Asked for as a bigger idea — a **quick / normal / detailed** picker on chat
  and agent turns, where quick trims the length hint (and, on a model that
  supports it, disables its own "thinking") and detailed asks for the
  opposite, with the option to pin a specific model to each level rather
  than always using whichever is set in Settings → Models. That's a UI and a
  prompt change, not a new capability — the pieces (a style hint, a
  per-purpose model already existing for chat/embedding/utility) are already
  there; this is a preset over them.
- **Temperature and sampling parameters, not just length — asked for
  directly.** "Is it a good idea to change model temperature and other
  parameters, as well as the amount of thinking, based off the type of
  task?" Yes, and it's the same preset idea as the bullet above, widened:
  quick/factual work (recalling a note, answering "when did I write X")
  wants low temperature and a short or disabled thinking budget; open-ended
  work (drafting, brainstorming) wants both opened up. Ollama's
  `/api/chat` already accepts `temperature`, `top_p`, and — on models that
  support it — a `think` toggle or budget per request; none of this needs a
  new capability from the model side, only a place in the request that
  today always uses whatever the default is.
  - **Manual first, automatic second — same ordering logic as model
    routing below, and for the same reason.** A per-mode set of parameters
    the person picks (or accepts a sensible default for) is honest about
    being a preset. Auto-adjusting parameters *by task* needs the same
    "how hard is this turn" judgement call that model routing does, so it
    inherits the same risk of being wrong confidently rather than
    obviously.
  - **Auto-adjusting *by model*, though, is worth doing regardless of the
    task question, because it's not a guess.** Not every installed model
    supports a thinking toggle, and the ones that do vary in what "off"
    means for reasoning quality on a given task. `Settings → Models`
    already knows which model is loaded — extending that to record what
    the model actually supports (thinking toggle, its context length, a
    sane default temperature) means a quick-mode preset can *fail closed*
    gracefully on a model that doesn't support the setting instead of
    sending a parameter Ollama silently ignores or errors on, which is a
    real gap regardless of whether task-based auto-routing ever happens.
- **Dynamically switch models by task complexity.** A related but separate
  ask — "optional," and worth keeping optional: a short factual question
  routed to a small fast model and an agent job routed to a larger one,
  automatically. The honest version of this needs a cheap way to estimate
  "how hard is this turn" before picking a model, which is itself a model
  call or a heuristic that will be wrong sometimes — worth prototyping as a
  manual per-mode assignment (the bullet above) before attempting to guess.
- **A model comparison / test-run feature — asked for directly: "test and
  compare different models for use in the application so you can choose the
  best one."** This is the eval harness below, pointed at a different
  variable. The harness already needs a fixed set of representative prompts
  to catch regressions over *time*; running that same fixed set against
  every installed model in one pass, and showing the results side by side —
  tokens, latency, and (for the ones with a known-good answer, like "what
  did I write about X") whether it actually got it right — answers "which
  model" instead of "did this get worse." One dataset, two use cases: a
  scheduled or CI-triggered run watches for regressions on the model
  currently in use; a manually-triggered run compares candidates before
  switching. Worth building as one feature with two entry points rather
  than two separate ones, since duplicating the prompt set would mean they
  drift out of sync with each other.

**Before any more of this: measure.** §11a was done by counting characters of
tool schema, which is why it worked. "A 3-turn chat shows 8.7k tokens" is not
yet broken down into system / tools / history / notes / question, and until it
is, the next optimisation is a guess.

[hr]: https://github.com/headroomlabs-ai/headroom


**Why.** Asked: "make sure all the code, processes, and AI usage is fully
optimised and efficient", and "more ways to make the program and AI more
accurate, usable, capable, and faster".

**Measure first** — there is no profiling in the repo, so where a chat turn
spends its time is currently a guess.

- **Prompt reuse.** Every agent round resends the whole message list; Ollama's
  `keep_alive` and prompt-prefix reuse are never set.
- **Cap tool output.** Return previews by default, full text only on request.
- ~~**Hybrid retrieval** (semantic + keyword, reciprocal-rank fusion)~~ **done**
  — HISTORY.md's "Retrieval reads the question before searching it": both
  searches run and their rankings fuse by RRF, not either/or. Flagged stale in
  this session's backlog audit; was still marked open here.
- **Re-ranking** with a small cross-encoder over the top-20, behind a setting.
- **Batch embeddings** — the backfill embeds one note at a time.
- **Warm the model** so the first chat doesn't pay the load cost.
- **Frontend**: `app.js` is now ~20k lines (was ~12k when this line was
  written — it has not shrunk) parsed on every load, and `renderEntries`
  rebuilds the entire list on any change. See §31's module-split
  recommendation in ANALYSIS.md, still unaddressed.
- **Context warning** as the window fills — the per-turn cost is already shown.
~~- **A per-chat token/context meter the user can actually see.**~~ **Built**
  (ROADMAP §88.4 item 4). Asked twice, once directly ("a better way to track
  tokens and other things") and once from the outside review ("prompt
  inspector, token counts, latency breakdown"). §11a already measured this
  server-side (prompt composition logged per round, chars only, Settings →
  Logs only) — now also attached as a token estimate to the chat metadata
  line's own window-fill tooltip, exactly the "~1.4k tokens this turn, 3.1k
  fixed overhead" shape asked for, per stage (system/tools/history/notes)
  rather than a single fixed-overhead number.
- **An eval/benchmark harness tied to changes here.** Every optimisation in
  this section so far has been measured by hand, in one session, against
  whatever the person doing it happened to type. A small fixed set of
  representative prompts (a few notes, a few questions, a skill run) that CI
  or a pre-release check can run against a real Ollama model and report
  tokens/latency/answer-still-correct would catch a regression before a user
  does. The outside review's suggestion that actually survived — not because
  of any specific tool, but because "measure first" is already this
  section's own rule (§11a) and there's no repeatable way to do it yet. The
  same fixed prompt set is also what the model-comparison feature further
  down this section runs, against every installed model instead of just the
  one in use — one dataset, watching for regressions over time and
  differences across models with the same tool.
  - **Worth tracking retrieval quality specifically, not folding it into
    "answer-still-correct."** A wrong answer can come from the model
    reasoning badly over the right notes, or from search handing it the
    wrong notes to begin with — those are different bugs with different
    fixes, and a single pass/fail per prompt can't tell them apart. A known
    query with a known correct note (or set of notes) lets the harness
    check "did search find the right thing" separately from "did the model
    say the right thing," which is what actually lets a hybrid-search or
    re-ranking change (§11) be judged on its own rather than blamed on or
    credited to whatever model happened to be loaded.

**§11a — token usage in chats.** Asked directly: "is there a way to reduce
excessive token usage in the chats?" A three-turn conversation showed 8.7k
tokens. Where it goes, cheapest fix first:

- Retrieved notes are re-sent in full on every turn, including turns that are
  a follow-up to the previous answer and need no new retrieval at all.
- `MAX_CLIENT_HISTORY` turns of prior Q&A go up each time, whole.
- Tool results accumulate within a turn (already capped by
  `TOOL_RESULT_BUDGET_CHARS`, but the cap is generous at 24k characters).
- The system prompt is long and grew again this session; it is re-sent every
  round of every turn, which is where Ollama's prompt-prefix reuse and
  `keep_alive` would actually pay.

**Half of this has now been measured, and the answer was not where anyone was
looking.** The *fixed* overhead — system prompt plus every tool schema, sent
before a word of the question, the notes or the history, on each of up to
`MAX_ROUNDS` rounds — is ~12,400 characters, about **3,050 tokens**. Of that,
**9,957 characters (77%) is the tool schemas**, not the prose. Trimming the
guide was the smaller half by a wide margin.

`agent.PROMPT_BUDGET_CHARS` now caps it and `tests/test_prompt_budget.py`
fails the build if it drifts past, because this grows invisibly: every tool
added costs the same budget and nothing else in the suite would notice.

**Why it matters more than the arithmetic suggests.** Ollama defaults to a
4096-token window unless the model declares otherwise, and overflow is dropped
from the *front* — which is the system prompt. A 3B model (granite4.1:3b,
llama3.2:3b, qwen3.5:2b — the ones this is aimed at) that overflows therefore
stops knowing it has tools at all, and reports as **"the AI won't use
tools"**, which is the hardest possible symptom to trace back to a long
prompt. Settings → Tools is the user-facing escape hatch, and there is now a
test proving that switch reaches the wire rather than only the executor.

**The remaining win is offering fewer tools per turn, not trimming more
words.** 28 schemas go up every round whether the question is "how many notes
do I have" or "remind me to call mum". A relevance filter — or a small
always-on core plus an opt-in rest — is worth more than anything left in the
prose. Do it before §21 adds skill tools to the same budget.

Still unmeasured, and still worth measuring before cutting: which of the
*variable* costs above dominates a real 3-turn chat. Log the prompt-token
count per round. Summarising older history is the usual answer, but it costs a
model call, so it should be the last resort rather than the first.

---

## 12. Does the AI know it is an agent?

**Why.** Asked: "does it know it is an agent and can use tools and skills freely
and in multiple turns if necessary?" and later, "I need agents to use tools more
and better if they are required."

**Honest answer: partly.** `TOOLS_GUIDE` says tools exist and forbids claiming a
save that didn't happen. The loop runs to `MAX_ROUNDS = 6`. What it is *not*
told:

- That taking several rounds deliberately is expected — plan, act, check, answer
- That skills exist at all (the tools are there; the prompt never mentions them)
- What to do when a tool fails — the error is returned with no guidance, so
  small models give up or repeat the same call
- That a search snippet is rarely enough and `read_url` exists
- What the user can already see (the step timeline), so it stops re-narrating

**Done since.** `TOOLS_GUIDE` now says that taking several turns is expected
("look something up, read what you found, look up anything still missing, then
answer"), that a search result is a clipped sentence and `read_url` exists,
and that the user can already see the tool timeline so it should stop
narrating its process back to them.

Failed tool calls now carry a `what_to_do` field matched to the failure — a
missing id says to search rather than guess another, a disabled tool says to
stop calling it, bad arguments say to re-read the schema and retry once — and
an identical call that fails twice is told so explicitly. Previously a failure
was a bare `{"error": …}`, and small models either apologised and stopped or
looped on it until the round limit ran out.

**Still to add:** an explicit `plan` step rendered at the top of the timeline
(build it with §21, which needs the same structure); a "required tools" hint
for requests that clearly need one; and a nudge when the model answers a
notebook question without having searched.

**Note the ordering.** None of this fixes "the AI won't make me a skill" —
that fails because `save_skill` can only store a prompt string, so there is
nothing for a better-instructed model to call. §21 first.

---

## 13. Web search effectiveness

**Now that SearXNG actually works (§8b), what's left is refinement, not
bug-fixing** — asked for directly: "the whole search UI just needs
refinement, and make sure that the search methods are as secure and private
as possible." Split into the two things actually asked for.

**Quality and UX:**

- **Query expansion** — two or three phrasings, results fused
- **Read before answering** — tell the model a snippet is rarely enough
- **Cite sources** with the domains actually read
- ~~**Per-turn result cache**~~ **Built — found by checking, not assumed
  missing.** `websearch._CACHE`/`_cache_get`/`_cache_put`, keyed on
  `provider::searxng_url::query::limit`, a small in-process dict with the
  simplest correct eviction (clear it all once it's full) rather than a real
  LRU, which this cache's size doesn't need.
- ~~**SearXNG as the recommended default** once §2's install path
  works~~ — the install path works now (§8b); worth actually flipping the
  default and updating the README/onboarding copy that still frames it as an
  advanced option
- ~~**Say which engine answered.**~~ **Built — found by checking, not
  assumed missing.** `websearch.answered_by()` returns a label plus a
  plain-English privacy note per provider ("SearXNG — your own instance,
  the query stayed on your machine" vs. "DuckDuckGo — a third party saw
  this query, but not your notes"); `routes_websearch.py` attaches it as
  `answered_by` on every search response, including a zero-result one on
  purpose ("no results" and "no results *from DuckDuckGo*" are different
  facts); `app.js`'s web-search status line already renders both the label
  and the detail beside the result count.
- **Result cards worth reading, not just clicking.** A title and a link today;
  a domain/favicon and a snippet with the matched terms highlighted would let
  someone judge relevance before opening the reader view, the same reasoning
  search engines converged on decades ago
- **Open a result straight into the reader** without a second round trip —
  ties to §3's Browse sub-tab, which is the natural home for this
- **Distinguish *why* zero results came back** in the UI itself, not just the
  log — rate-limited, engine down, genuinely nothing found are three
  different situations and currently look identical to the person searching
- **Deciding *when* to search, not just how well it searches once asked.**
  Asked for as "better agentic web search through chat" — read as being about
  judgement, not just result quality. Today `web_search` is one tool among 28
  the model can choose or not; nothing measures whether it reaches for it
  when a question is actually time-sensitive ("what's the latest version of
  X") versus when it should trust the notebook or say it doesn't know. That's
  a prompting and evaluation question more than a code one — a good
  candidate for the eval harness in §11 to actually track, rather than
  something to "fix" once.

**Privacy and security, specific to search** — extending §8b's general
security pass with what's particular to this feature. What's already true:
only the search words leave the machine, never notes; the request looks like
an ordinary browser rather than naming the app; no cookies survive between
searches; queries go by POST so they don't land in access logs; tracking
parameters are stripped from result URLs before they're ever shown; a
self-hosted SearXNG keeps the query on the user's own network entirely
rather than reaching a third party at all. Worth checking on top of that,
now that SearXNG is a real running thing rather than a plan:

- **SearXNG's own outbound behaviour.** A default SearXNG install can be
  configured to query dozens of upstream engines, including ones with their
  own tracking, and some engine plugins hit third-party autocomplete/suggestion
  endpoints unless turned off — the `tracker_url_remover` plugin was already
  found to break startup entirely (§8b, bug 5) and disabled; worth a pass
  over the *rest* of the generated `settings.yml` for anything else
  defaulting to "on" that shouldn't be, not just the one that crashed.
- **No client-side favicon/thumbnail fetching per result.** A common leak in
  search UIs: fetching each result's favicon from the result's own domain, at
  render time, tells that domain someone searched and got them as a result —
  before the person has chosen to visit anything. Worth confirming the result
  card ideas above don't introduce this by loading icons live rather than
  bundling a small generic set.
- ~~**SearXNG bound to localhost, not the LAN.**~~ **confirmed for the
  source path, and it was wrong for docker** — `_start_docker` published on
  every interface (docker's own default), which is worse than an open port
  since SearXNG has no auth in front of it. Fixed; see HISTORY.md.
- **A visible statement of what's true**, not just true in the code. The
  Privacy and security section of the README already says most of this
  clearly; worth linking it from Settings → Web search directly, next to the
  engine picker, so the privacy properties are legible exactly where someone
  is deciding whether to turn search on — rather than something you have to
  already know to go and read.

---

## 14. More tools worth adding

`create_document` / `edit_document` (the AI can read documents but not write
them) · `related_notes(id, depth)` (§9) · `move_notes` (bulk re-file) ·
`merge_notes` · `export_notes` · `find_similar(note_id)` · `stats` ·
`add_event` / `list_events` (§10) · `set_preference` over a small allowlist so
"make your answers shorter" works · `unlink_notes` / `delete_reminder` (§21,
gives skill runs a real undo for those two change types) ·
~~`create_category` / `merge_categories` / `delete_category`~~ **done, plus
`rename_category`** (name-based, not id-based, since the model has never
seen an id — see HISTORY.md for the three decisions behind the shape).

> ~~**⚠ The prompt budget is now the binding constraint on this section.**~~
> **Lifted — the constraint was an assumption, not a fact.** `tools.
> within_budget` now fits schemas to the window the model *reports*
> (`ollama_client.usable_context`) rather than a fixed 4096, dropping the
> least-relevant tools when they don't fit and logging what it held back.
> Core tools (search, read a note) always go first. See HISTORY.md for the
> per-window table. **What this means for the rest of this section: add the
> tools** — the cost of one more is a per-turn question the app now answers
> itself, not a fixed budget to ration against.

---

## 15. Appearance: more of everything

Asked for: "more options for the appearances — fonts, colours, sizing, themes,
palettes."

- **Fonts**: beyond system/serif/mono — a curated set including a dyslexia-
  friendly face, plus per-surface choice (UI vs note body vs code)
- **Sizing**: independent UI scale and reading size; line-height and measure
  (line width) controls, which matter more for long notes than font size
- **Colours**: per-surface accents, a custom palette builder (pick a base,
  derive the set), and import/export of a palette as JSON
- **More themes and palettes**, and a "surprise me" that generates a coherent
  one
- **Save a custom combination as your own theme**, not just a custom palette.
  Asked as "allow for saving of custom appearances and themes" — the palette
  builder above already covers colour; a theme is colour *plus* light/dark,
  font, density, radius and glass (see "Themes vs palettes?" in the closing
  Q&A), so saving one as a named preset means capturing all of
  `appearancePref`, not just the swatches.
- **Live preview** while hovering a theme, before committing
- ~~Fix the reported bug where individual controls resist change under a
  theme~~ done (§8, HISTORY.md).

---

## 16. Sweeping UI quality-of-life

- ~~**A status bar along the bottom**~~ **done** (`#status-bar`/
  `renderStatusBar()`) — flagged stale by a backlog audit; see the
  near-duplicate bullet further down this list too.
- **Sorting and grouping saved chats** — also from IDEAS.md and also homeless
  until now. Conversations sort by recency and nothing else; there is no "by
  length", "by which model answered", no folders, no grouping by topic. The
  data to sort by is already stored per turn (the model, the token cost, the
  timestamps), so this is a list-rendering job. The IDEAS note suggests an
  agent tool and a skill for it too, which would fall out of §14's shape once
  the sort exists.
- **Undo toasts** for anything soft-deleted, instead of confirm dialogs
- **Optimistic UI** — a saved note appears instantly and reconciles
- **Consistent empty states** and loading skeletons
- **Keyboard**: `/` focuses search, `g`+letter jumps tabs, Escape closes every
  overlay
- **Bulk selection** in the note list
- **"What changed" after an AI action** — chips say what ran, not what it did
- **Confirm on close** with unsaved text
- **Relative timestamps** everywhere, absolute on hover
- ~~**Dashboard**: audit every quick-access button actually lands where it
  says~~ done (§8) — every quick link now checked from all three Notes
  sub-tabs. Still worth doing: **add the ones that are missing**
- ~~**Collapsible sidebars.**~~ **Done** — `makeSidebarResizable`'s
  `sidebar-collapse-toggle` is wired on all three (Notes, Chat, Documents).
- ~~**A status bar pinned to the bottom.**~~ **done, same item as above** —
  a second, near-duplicate bullet for the same ask; both are satisfied by the
  one `#status-bar` that now exists.
- **Keyboard-only navigation, confirmed end to end rather than assumed.**
  §19 already covers focus traps and screen-reader gaps; this is narrower
  and more basic — can someone move through the note list, open a note, edit
  its tags, and file a reminder without a mouse touching anything? The
  bullet above already has a few keys bound (`/`, `g`+letter, Escape); the
  gap is whether the note list itself supports arrow-key movement and Enter
  to open, which is the one interaction pattern used constantly enough that
  its absence would be felt every session, not just noticed in an audit.
- **A global quick-capture hotkey in desktop mode.** Not asked for directly,
  but the app's own pitch — "just capture, a local AI files it" — implies
  capture should be as close to zero-friction as opening the app currently
  isn't. `--desktop` (§7) already owns a native window; a system-wide
  hotkey that pops a capture box without switching to the app at all (the
  way Apple Notes' quick note or Notion's quick capture work) would make the
  core loop genuinely faster than opening a tab, typing, and filing —
  rather than just as fast. Browser-tab mode can't do this (no OS-level
  hotkey access from a page), so it's specifically a `--desktop` win, and
  worth scoping alongside the rest of §7's packaging work rather than
  separately.

---

## 17. Use cases the app can't serve yet

- ~~**Meeting notes**~~ **record → transcribe → note built (a
  `#meeting-overlay`, `/voice/transcribe-meeting`, review-before-save, a
  `meeting` tag); action-item extraction still open** — needs a real model
  call parsing free text into multiple structured reminders, a different
  shape from the single-phrase parser `POST /reminders/parse` does, and
  this sandbox has neither faster-whisper nor a running Ollama to verify a
  new prompt against. See HISTORY.md for what was and wasn't verified live.
- **Reading and research** — the Browse section (§3) plus highlights saved as
  notes back-linked to their source
- **Journalling** — a daily-note pattern; the pieces exist, nothing ties them
- **Task management** — reminders are not tasks (no sub-tasks, projects, or
  "someday"). Commit to it or stay deliberately out.
- **Study / revision** — spaced repetition; access-count and embeddings are
  already stored
- **Sharing one note or document** — no export-one-thing path today
- **A second device** — single-user by design; sync is a much larger decision
  and should be stated as out of scope rather than left implied. Asked
  concretely as "a way to run the app on a mobile device like my iPhone",
  which is a smaller ask than sync: the frontend is already a PWA with a
  mobile pass (Wave F), so a phone on the same network *could* just point a
  browser at it — except the server binds to `localhost` on purpose (§1 of
  `ARCHITECTURE.md`), which is exactly what stops that. Opening it to the LAN
  is a real security decision (anyone on the network reaches an unlocked API
  surface until the password gate, not just the person at the keyboard), not
  a config flag to flip quietly — worth stating explicitly as "possible, not
  yet safe to default to" rather than leaving it unaddressed.
  - **If sync is ever actually pursued**, the shape worth reaching for is
    the one Gemini's (grounded) suggestion named: local-network only —
    mDNS discovery plus a direct connection between two instances on the
    same network, never a public relay — which keeps the "nothing leaves
    the machine unless asked" principle intact in spirit (nothing leaves
    *the network*) rather than quietly becoming a cloud feature. Recording
    the shape without changing the decision above: sync is still a much
    bigger undertaking than the mobile-access question alone, and worth
    staying out of scope until that's a deliberate yes.

---

## 18. Agent quality

The registry is now 28 tools and reaches the whole notebook, documents and chat
history. What's still weak:

- No plan/progress for a multi-step job — the step timeline shows what happened,
  not what remains
- ~~No way to stop an agent turn mid-way and keep what it already did~~ **done**
  — `#chat-stop` aborts the stream and keeps the partial answer.
- A tool that fails is reported, but the model isn't told how to recover
- `_CLAIM_PATTERN` catches "I saved it" when no write tool ran — worth extending
  to other claim types
- **The agent only lives in the Chat tab.** Asked for as "allow the agent to
  be accessed from anywhere in the program" — every other tab already has the
  pieces this would reuse (the confirm-before-destructive pattern from design
  principle 6, the plan/step/result UI from §21), so a floating entry point
  that opens the same agent against "whatever I'm looking at right now" is
  more a routing change than a new agent. Before/after comparison on an edit
  already exists in one place — a skill run's changes list shows **View** and
  **Undo** per row (§21) — the ask was really for that pattern everywhere an
  edit happens, not a new mechanism.
- **The agent controlling the screen itself** — "allow the agent to control
  your screen within the application to navigate and make changes… with the
  user able to cancel it at any time". A different and much bigger thing than
  the tool-calling loop that exists today: it means the agent driving the
  frontend the way the Playwright driver in §10 of `ARCHITECTURE.md` drives
  it for testing, not just calling an API. Flagging it rather than scoping
  it — it would need its own cancellation and audit story on top of
  everything §21 already built for tool calls, and it's worth deciding
  whether the tool registry can get there first before reaching for UI
  automation.

---

## 19. Accessibility audit

Deserves one deliberate pass rather than more ad-hoc fixes. **Two of the five
are now done** (§85, §86):

- ~~Focus traps in overlays are inconsistent~~ **done.** `activeOverlay()` no
  longer works from a hard-coded list of eight ids — it finds any visible
  `[role="dialog"][aria-modal="true"]` and takes the topmost, so a new modal is
  trapped from the moment it exists. Gated on `aria-modal` specifically
  because 13 of the app's dialogs are anchored *popovers* whose page stays
  interactive, and trapping Tab in one of those would be a worse bug than the
  one being fixed.
- ~~Tap targets below the WCAG 2.5.8 24px minimum~~ **done**, and the original
  finding was half wrong: it named the checkbox elements, but a wrapping
  `<label>` makes the label the target. A live sweep of every tab and Settings
  found five real failures (a 1px-short chip, two label-wrapped toggles at
  20px, a bare 13×13 Library tick, and one Settings link) and fixed them.
- **Colour contrast is still unverified against WCAG AA** for the newer
  palettes and the glass surfaces in particular. Never actually measured — the
  one item here that needs a tool rather than a reading.
- **A screen-reader pass**: several dynamic regions still announce nothing.
  `announce()`/`#live-region` exists and the graph uses it well; most of the
  app does not.
- **`prefers-reduced-motion` fallbacks** for the remaining meaningful
  animations. 15 blocks exist; nobody has audited what is *not* covered.
- **Settings on a narrow viewport** — folded in here rather than fixed in
  isolation, since it is likely the same class of breakpoint gap.

## 20. Backend

- **Async httpx client** — touches the streaming path, which is what makes chat
  feel responsive, so a subtle regression wouldn't show up in tests. Do it with
  §6.
- ~~**Alembic migrations** — the additive auto-migrator cannot rename or drop, and
  won't survive a real schema change~~ **Built.** `migrations/` (Alembic),
  `_ensure_alembic_baseline()` (`core/database.py`) stamps any pre-existing
  database at the baseline revision on first run under the new system so it
  never tries to replay history against data that already has the schema.
  Full narrative: HISTORY.md §100. Stale here since — found by checking the
  running app before trusting this list, not assumed.
- ~~**Session TTL** — tokens live in memory and never expire~~ **done.** Two
  clocks (idle 12h, absolute 7d), expiry closes the vault too. See
  HISTORY.md.
- ~~**Cross-origin requests against the local API — worth checking directly,
  not assuming.**~~ **checked, and it was open. Now closed** by
  `core/security.py:OriginCheckMiddleware`. The real exposure was worse than
  the item assumed: the most vulnerable moment is *before* a password
  exists, when a drive-by `POST /auth/setup` from a malicious page in
  another tab could have claimed the notebook outright — a browser enforces
  the target's CORS policy, not the attacker's. See HISTORY.md.
- ~~**Is SQLite in WAL mode?**~~ **yes, and it already was** —
  `core/database.py` sets it on every connect, `busy_timeout=5000` and
  `synchronous=NORMAL` beside it. Pinned by a test now.
- ~~**What blocks the request thread.**~~ **Checked directly, not assumed —
  none of the three named cases actually do.** A re-index
  (`model_manager.start_reindex`) and a model pull
  (`model_manager.start_pull`) each spawn a daemon `threading.Thread`
  before returning, same as `searxng_manager.start()`'s own install/start
  path — none of the three ties up the thread serving the request that
  triggered them. **The daily backup is different, and safer than the
  worry implied**: `_backup_if_due()` (api/app.py) runs once during
  `create_app()`, *before* uvicorn starts accepting connections at all — a
  due backup makes the app take longer to finish starting, not something
  a live request ever waits on mid-session. A manually-triggered backup
  (`POST /backups` → `backup.backup_now`, a plain sync route function) is
  the one real nuance: FastAPI runs a sync `def` route in its own bounded
  threadpool, not on the asyncio event-loop thread, so it doesn't freeze
  concurrent requests the way a truly blocking call on the event loop
  would — it just holds one worker-thread slot for the copy's duration,
  which is a non-issue for a single-user local app with nobody else
  concurrently hitting the API. Nothing here needed fixing; this item can
  be struck rather than built.
- ~~**Singletons and worker count are coupled, and that coupling isn't written
  down anywhere.**~~ **done — checked in the running code, not assumed.**
  `deps.refuse_multiple_workers()` already exists and already runs first
  thing in `create_app()`, before any singleton is built: it reads
  `--workers`/`-w` off `sys.argv` and the `WEB_CONCURRENCY` env var (what
  uvicorn and gunicorn both honour), and raises `MultipleWorkersError` with
  the full reason and the fix rather than a warning nobody reads. Covered by
  `tests/test_worker_guard.py`. This item can be struck rather than built.
- ~~**Confirmed, not just suspected: `GET /entries` is genuinely
  unbounded.**~~ **done.** Asked for directly ("that is a real app feature
  that enhances good design and will probably be needed for real world
  use"). `GET /entries` now takes `limit`/`offset` (default page 1000, hard
  ceiling 5000 — `ENTRIES_PAGE_SIZE`/`_MAX` in `routes_entries.py`) and
  reports the true count via an `X-Total-Count` response header regardless
  of the page. `entry/manager.py` grew matching `limit`/`offset` params on
  all three list functions plus `count_entries`/`count_deleted_entries`/
  `count_archived_entries` — additive (`None` still means "everything"), so
  every existing in-process caller is unaffected.

  The risk this item itself named — a silent cap making old notes invisible
  everywhere at once — is why the fix isn't just a `.limit()`. `app.js`'s
  `loadEntries()` now fetches pages in a loop, painting the first page
  immediately and filling the rest in the background; every one of
  `allEntries`'s ~30 read sites (search-as-you-type, keyboard nav, the
  sidebar, tag suggestions) needed zero changes, because `allEntries` still
  ends up exactly as complete as it always was once loading finishes — just
  without one unbounded response getting it there. A `_entriesLoadGeneration`
  counter (same shape as `loadOnboardingDiagnostics`'s staleness guard)
  stops a slow page from a superseded load splicing stale rows back in if
  `loadEntries()` is called again mid-page-load.

  One real regression caught in the same pass, not by guessing but by
  grepping every `/entries` GET call site before calling this done: three
  dashboard widgets (`renderPinnedWidget`, `renderRecentNotesWidget`,
  `renderTopTagsWidget`) each independently re-fetched the *whole* list —
  which the new 1000-row default would have silently truncated,
  `renderTopTagsWidget` most seriously (wrong tag counts on any notebook
  past 1000 notes, with no error to notice it by). Fixed by having all
  three prefer the already-loaded `allEntries`, the same pattern
  `renderRandomNoteWidget` already used. Also found and removed while
  auditing those call sites: `copyLogs()` built a `/entries` URL and
  `fetch`ed it, then never used the response — dead code, unrelated to
  logs, silently wasting a request (and failing every time, since a bare
  `fetch()` skips the auth header `api()` adds).

  Verified live, not just by the new backend/frontend tests: seeded 2500
  notes directly via `entry.manager`, confirmed exactly three page requests
  fire (`limit=1000&offset=0/1000/2000`), `allEntries.length` and the
  status bar both land on 2500, all 2500 rows actually render, and the
  Dashboard's own widgets (including the fixed tag-counting one) show
  correct totals with zero console errors — screenshotted.
- ~~**What happens when Ollama hangs, rather than errors.**~~ **Checked
  directly — already built, all three pieces this item asked for.**
  `OllamaClient.__init__` (ai/ollama_client.py) sets a 600s request
  timeout by deliberate design, not the default — its own comment records
  the exact live report that set the number ("models larger than like 4B
  params struggle to even load or respond") and the reasoning: long enough
  to cover a slow cold load on CPU-only hardware, short enough to
  eventually give up rather than hang forever. The frontend's own
  "still waiting" half already exists too: `sendChatMessage`'s
  `slowLoadTimeout` (app.js) shows "Loading model… (this may take a
  moment)" once 5s have passed with no reply. And the failure past the
  timeout is surfaced, not silent — `routes_chat.py`'s streaming
  generator has an outer `except Exception` boundary around both "before
  the first event" and "mid-stream" that turns *any* unhandled error,
  including a `requests.ReadTimeout` once 600s is up, into a real answer
  event ("Something went wrong before it could start: …") instead of the
  stream just stopping. Nothing here needed building.
- **Crash-safe recovery for a re-index or a model download interrupted
  mid-way.** Half-checked directly. **The re-index half is safe by
  design, already, without a resume button**: `_run_reindex`
  (ai/model_manager.py) deletes an entry's stale vector and commits, *then*
  regenerates and stores the new one — so a crash between those two steps
  leaves that one entry with no vector at all, not a corrupt or
  inconsistent one, and `start_reindex`'s own docstring already covers this
  exact state: semantic search falls back to keyword search for any entry
  missing a current vector, the same fallback a re-index that hasn't run
  yet relies on. The in-memory `Job` doesn't survive a restart either, so
  there is no stale "still running" status to confuse the health-check
  screen — a fresh launch just sees no job, and the next re-index (full,
  not a true resume-from-checkpoint) fixes whatever was left incomplete.
  No corruption, no confusing error, nothing to build here. **The model-pull
  half is still genuinely open** — whether a `POST /api/pull` cut off
  mid-stream resumes from Ollama's own blob store on the next pull is
  Ollama's own behaviour, outside this codebase, and wasn't verified this
  session (no live Ollama in this sandbox to interrupt and re-pull
  against).

---

## 21. Skills — rebuilt; what is left

**Why.** Reported directly: "the skill system also needs a remake. The way
skills are used currently, and what the skills are at the moment, are
incorrect and are closer to just presaved mini prompts. I keep on trying to
get the AI to make me some skills in the chat but it doesn't recognise that it
needs to use tools and how to properly utilise the workspace."

**That description was accurate**, and the shape has changed. A skill was
`{name, prompt}`; clicking one dropped its prompt into the chat box, and
`save_skill` stored a name and a string — so "make me a skill that files my
inbox notes" could only produce another sentence, because the storage had
nowhere to put the steps. Fixing the prompt alone would not have helped.

**What a skill is now** (`ai/skills.py`, one validator for every way in):

- **prompt** — what it should do. A skill with only this behaves exactly as it
  did before, which is why nothing was lost.
- **steps** — ordered instructions, numbered into the run instruction and
  drawn as a plan at the top of the step timeline before anything runs.
- **tools** — an explicit allowlist. Only those schemas go on the wire and
  anything outside the list is refused at execution, so it is a safety
  property and not just a prompt. It is also §11a: the full registry is 10,215
  characters of schema on *every round*; "🏷 Auto-tag my notes" ships 1,963.
- **inputs** — declared `{{placeholders}}`, asked for before the run. A
  placeholder with no input behind it is refused on save, in the editor and in
  `save_skill` alike, because the alternative is a model handed a literal
  `{{tag}}` inventing a value.

Two decisions worth keeping:

**The built-in skills moved out of `app.js`** and are served from
`GET /skills` with the user's own. The server could not previously resolve a
skill the user clicked, `list_skills` answered "you have none" while ten were
on screen, and every field added to a skill had to be added twice.

**The declared tools are named in the instruction text as well as narrowed on
the wire.** Not redundancy: the reported failure was a model that *had* tools
and did not know it was meant to act, and telling a 3B model "use `tag_note`"
is what makes it reach for one.

**And what running one now does** (`ai/skill_runner.py`):

- **One turn per step.** Not one request carrying a numbered list — that is a
  plan the model may ignore, and a 3B model given four instructions at once
  does the first and narrates the rest. The app knows which step is running,
  so the UI ticks them off as they finish.
- **A step that fails is named**, with the reason, and the run stops there
  instead of ploughing on. §21 asked for exactly this.
- **The run ends in what changed**, not prose claiming something happened:
  a list of every write, each with a **View** and — where an inverse exists —
  an **Undo**. The undo is a tool call captured *before* the write and run
  through `POST /chat/tools/execute`, the same endpoint the confirm button
  uses. It is stripped out of what the model sees, since every field left in
  a tool result is resent on every later round.
- **Every built-in is a real job**: steps, tools, and declared inputs asked
  for in one dialog before the run. "Draft an email" asks who and what
  instead of spending a chat round on it.

**Still to do:**

- **Re-running a past run.** A skill is repeatable; a *run* is not yet
  something you can replay over a different set of notes.
- **Undo the whole run**, rather than one change at a time. Gemini's
  (grounded) suggestion was a heavier version of this worth naming
  explicitly: a local, silent version-control snapshot before a bulk
  operation runs, so a bad auto-tagging pass or a skill gone wrong can be
  rolled back wholesale rather than change by change. This sits between two
  things that already exist rather than needing to be built from nothing —
  daily backups (§ "Where your data lives" in the README) are too coarse
  (once a day, not once per run) and per-change Undo above is too fine (a
  20-note bulk tag is 20 things to individually undo); a snapshot taken
  specifically before a skill run or bulk tool call, kept for a short
  window, is the missing middle size. Worth building as "one more backup,
  triggered by an event instead of a timer" rather than actually reaching
  for git — the existing backup mechanism already solves the storage
  question, just not the timing.
- **Links and reminders have no inverse tool**, so those two changes are
  listed without an Undo. `unlink_notes` / `delete_reminder` would fix it, at
  the cost of two more schemas in the per-round budget (§11a) — worth doing
  when something else needs them too.

---

## 22. Reported in use, not yet done

Small, concrete, each seen in the running app:

- ~~**Take me to the thing the agent just changed.**~~ **Done — this entry
  was stale.** Checked against the running app (agent.py), not assumed:
  `_change_note_id`/`_change_document_id`/`_change_reminder_id`/
  `_change_category_name` all exist and are wired into every `change` event
  (`create_note`, `edit_note`, `tag_note`, `pin_note`, `restore_note`,
  `link_notes`, `unlink_notes` — all four route through the note's own id,
  which is the right target for "View" either way; `create_document`;
  `set_reminder`/`complete_reminder`; `create_category`/`rename_category`/
  `merge_categories`). `changeRow` (`frontend/app.js`) renders the View
  button from whichever id is present, and is called from both the live
  per-turn tool-call rendering *and* a skill run's final "what changed"
  list — the "two things to decide" below were both resolved. Only the
  destructive-result question below is still open, and it's a small,
  separate decision, not a rebuild.

  ~~Still open: whether a **destructive** result... should offer to
  navigate to the recycle bin~~ **Done for notes, the only one of the three
  that was actually wired.** `changeRow`'s "View" button on a `delete_note`
  result reused `flashEntry`, which only ever looks in the ordinary browse
  list — a note just moved to the bin is never there, so it silently found
  nothing. `delete_note` now gets its own "View in bin" button
  (`flashLibraryItem`, `frontend/app.js`), which opens the Library's Bin
  filter and highlights the note there — the one place it actually lives.
  Verified live (Playwright): create → delete via the API → call the new
  function → lands on Library, Bin filter active, correct card found and
  highlighted, across three repeated runs. Document and category deletes
  never route through `changeRow`'s note-id branch at all (`delete_document`
  is parked for a confirm rather than reaching this code path, per
  `agent.py`'s own comment on `_DOCUMENT_ID_FIELD`; there's no
  `delete_category` change event either) — so there was nothing else to fix
  under this item, not a partial fix.

- ~~**Magic Add schedules relative reminders a whole timezone offset late.**~~
  **fixed** — the route built the user's clock as `utcnow() + offset`
  (aware, tagged UTC, actually holding local wall-clock), so the model was
  told a fictional offset and trusted; error was exactly the user's UTC
  offset. Also: "in …" phrases now resolve by rule, not a 3B model doing
  arithmetic. See HISTORY.md.

- ~~**Background tasks vanish when they finish.**~~ **Done** —
  `renderTaskHistory` persists finished tasks (outcome, duration) and
  `task-history-clear` is the shared "clear history" affordance.
- **Chat / Agent / Browse selector and a browse UI.** Asked for directly
  ("can the chat interface be improved?? like the selector for agent mode
  and the web browser ui??") — this is §3, already designed there, unbuilt.
  Treat §3 as user-requested now, not speculative.
- **Agent continuation quality.** "The agent really struggles to continue a
  chat based off the previous message." Two things landed for it (2026-07:
  the most recent answer now reaches the next turn nearly whole —
  `librarian.history_messages` / LAST_ANSWER_CHARS — and every agent turn
  logs its prompt composition as memorymap.agent "prompt composition").
  Next step per §11a: read those logs from a real 3-turn chat, see whether
  notes or history dominates, and only then trim the variable half.
- ~~**A skill that writes skills.**~~ **Built** — "Build a skill" in
  `ai/skills.py`'s `BUILTIN_SKILLS`, same `ask_user`-driven interview shape
  as "Interview me about an idea": asks what the job should do, whether it
  touches notes (decides the tool allowlist), what should be an input, drafts
  the whole thing and confirms before calling `save_skill` — and checks
  `list_skills` first so a near-duplicate ask reuses rather than doubling up.
- **Appearance settings page (§15).** Asked whether it can be improved;
  nobody has audited it against §15 yet. The chat empty-state emblem now
  animates (same motion switch as the ai-mark), which was the one concrete
  ask.
- **Bot-walled sites in the reader.** Cloudflare-fronted wikis and Reddit
  403/challenge the reader on TLS fingerprint alone; no header can fix
  that. The reader now names the wall instead of dumping a status
  (websearch.fetch_readable), but actually reading such sites would take
  browser impersonation — decide deliberately whether that dependency is
  ever worth it before anyone "fixes" this again.
- ~~**Chat metadata disappears on a reload or app restart.**~~ **Done — this
  entry was stale.** Checked against the running app (`openConversation` in
  `frontend/app.js`), not assumed: `message.stats` is persisted and the
  function's own comment already says why — "Rebuild the metadata line...
  it was only ever built from the live stream... Turns saved before this
  stored no stats and correctly get no line, rather than a row of '?'s."
  Whoever fixed this didn't strike the entry here.
- **README and GitHub Pages drift out of date.** Asked for directly: "update
  the readme and gh pages site to have up to date information". The README's
  own "What's in it" table still said six tabs after the Timeline tab (§10)
  shipped, and its "Next up" list still named the pre-rebuild skill system
  and pre-SearXNG web search as open work after both were done — exactly the
  kind of drift this document itself warns about in its opening note. Worth
  a pass through README, the GitHub Pages site (still on the "ideas, not
  yet" list in `CHANGELOG.md`) and this file together, since all three
  describe the same app and only this one gets updated every session.

- ~~**Notes don't render markdown.**~~ **done** — but read how before
  extending it. `renderInlineMarkdown` handles bold/italic/`code`/strike
  *only* (block elements are deliberately excluded from the list — see
  HISTORY.md); the dashboard's own small note lists strip markers instead.
- ~~**A hero header on the dashboard.**~~ **done** — emblem and wordmark
  inside the greeting card, hidden below 720px.
- ~~**The chat box can't grow.**~~ **done** — a textarea that grows with the
  text now, was a single-line `<input>`.
- ~~**A long note fills the list.**~~ **done** — anything past
  `LONG_NOTE_CHARS` clamps with a fade and "Show more".
- ~~**SearXNG starts but never answers** — capture its output.~~ Done; the
  cause was us — see §8b.

---

## 23. Organisation: manual grouping and multi-category notes

**Why.** Two related asks: "manually group notes together (separate from
the main sorting)" and "a note should be able to have multiple categories".
Both point at the same gap — filing today is exactly one category per note
(`entries.category_id`, a single foreign key, chosen by the janitor or the
user) plus tags for everything else multi-valued.

**Worth checking before building either.** Tags already are a multi-label,
user- or AI-applied system (`entries.tags`, a JSON column, with `tag:work` as
a search operator). A genuine "multiple categories" ask might already be
served by tagging more — worth finding out what the category is doing for
the person that a tag isn't (a category has an embedding centroid the
janitor matches against; a tag doesn't) before adding a join table.

**If it's still wanted after that:**

- **Multi-category** is a schema change — `entries.category_id` becomes a
  join table (`entry_categories`), and the janitor's cheap match (§4 of
  `ARCHITECTURE.md`) needs a rule for what happens when a note matches two
  centroids well. An additive migration, but touches the one part of the
  filing pipeline every other feature assumes is single-valued (the sidebar
  count, the graph's category layer in §9, "all notes in category X" queries).
- **Manual grouping**, kept genuinely separate from categories/tags, is
  smaller: a `collections` table and a join table, with no AI involvement at
  all — the person decides what belongs together, the app doesn't guess.
  Closer to a saved filter (§2) built by hand than to a new kind of filing.

---

## 24. Dashboard: more widgets, and layout depth

**Why.** Asked for directly: "more dashboard widgets! maybe some pie
graphs??" The dashboard already has a rearrangeable layout (Phase 5) and a
widget set (streak, at-a-glance counts, AI digest, activity heatmap,
on-this-day, focus timer) — this is more of the same shape, not a new system.

- **A category/tag breakdown** — the pie chart asked for, over
  `count_notes`-shaped data that already exists for the agent tool of the
  same name (§7 of `ARCHITECTURE.md`).
- **A writing-frequency chart** — bars over the activity heatmap's own data,
  a different read of the same numbers (streak vs volume).
- **A "stale notes" widget** — pairs with §10A's still-open idea of nudging on
  a note whose relative-time phrase has gone stale ("this said 'tomorrow'
  three weeks ago").
- **A "forgotten connections" widget — proactive rather than on-demand.**
  Gemini's actually-grounded suggestion (its second pass, after reading the
  real feature set): the graph already lets the AI suggest connections for
  a note *you're looking at* (§9); this is the same underlying similarity
  search run the other way — periodically, in the background, over notes
  nobody has looked at together, surfacing "these two from months apart
  might be related" on the dashboard rather than waiting to be asked.
  Nothing new to build on the retrieval side — §9's clustering and the
  embedding search both already exist; what's new is running it
  unprompted and having somewhere to show the result. Worth capping
  aggressively (one suggestion, not a feed) so it reads as a genuine find
  rather than the AI narrating its own similarity scores at you.
- Before adding more: audit which existing widgets render markdown and which
  don't (§8's ideas-parking-lot bug) so a new widget doesn't repeat the gap.

---

## 25. App control: tray, health checks, and dependency repair

**The tray itself: built.** Asked directly — "hide the terminal but let it be
reached", "manage it through the system tray and popup windows" — and
answered: closing the desktop window now minimizes to a tray icon instead of
quitting (`window.events.closing` returns `False` to cancel the real close),
and the tray menu is Open / View Logs (opens Settings → Logs, the third
AskUserQuestion answer this session) / Restart (`os.execv`, same process
re-launched rather than a second one spawned) / Quit (`window.destroy()`,
which is what actually unblocks the `webview.start()` call and lets the
process exit). See `memorymap.__main__._start_tray`. `pystray` + `Pillow`
ride along with the existing `desktop` extra in `core/extras.py` — same
button that already installs `pywebview` — and the Windows installer's
PyInstaller spec bundles both, so this is always on for anyone who used the
installer.

Degrades the same way every other optional extra in this app does: no
`pystray`/`Pillow` (or, seen for real in this sandbox, a `pystray` backend
that fails at import — `Xlib.error.DisplayNameError` on Linux with no X
server) means `_start_tray` returns `None`, logs why, and the window goes
back to closing for real. That fallback path is what's actually been run in
this sandbox; the tray *appearing*, the menu *working*, and minimize-to-tray
*behaving* on a real Windows taskbar have not — no Windows box and no GUI
toolkit here to run pywebview at all, so this carries the same "built,
reasoned through, not yet seen" caveat §7's installer already carries, for
the same reason.

The health-check screen and repair actions below are still open — this
covers only the tray/console half of the section's original ask.

**Why.** Several asks that are really one request in different words: "an
interface for managing the application… backend, cmd prompt console, quit,
update, install/fix/uninstall/reinstall packages and dependencies,
faster-whisper, and more… application health check, errors" — plus "improve
or expand on start.bat, don't make a cmd prompt window show but make it
accessible (maybe system tray)" and "a way to exit the app and close the
program quitting the backend". §7's desktop-packaging plan already lists
"single instance, native menus, tray" as part of hardening `--desktop`; this
section is the *content* of that tray/console, not the packaging shell
around it.

- **A visible health check.** Is the venv intact, does Ollama answer, is the
  embedding model loaded, is SearXNG (if installed) alive, how much disk is
  `data/` using. Most of these already have an answer somewhere in the app
  (`/models/status`, `searxng_manager.status()`); this is one screen that
  asks all of them and states plainly what's wrong rather than making the
  person go looking.
- **Repair actions from that screen**, not just a diagnosis: reinstall a
  dependency, re-pull a stuck model download, restart SearXNG. The SearXNG
  ↻ Reinstall button (§8) is the existing pattern to extend, not a new idea.
- **A real quit**, distinct from closing the browser tab — stopping the
  server process, not just the window. `--desktop` mode is the natural home
  for this since it already owns a process to exit; browser-tab mode can't
  kill its own server from the tab.
- **Update channels** (stable/beta/dev) — worth deferring until §7 actually
  ships an installer; there's nothing to channel yet while `git pull` plus
  the launcher's own dependency check is the update path.
- **A hidden console window on Windows, reachable rather than gone** — the
  ask was for the cmd window not to show at all *and* to still be reachable,
  which is two different things depending on whether the point is "get it out
  of my way" (a tray icon, minimised) or "I don't need to see it, ever, but
  Settings → Logs already covers that" (nothing to build). Worth confirming
  which was meant.

---

## 26. Data lifecycle: archive, a full wipe, and a real trust page

**Why.** Groups a few related asks that are all "what happens to old or
unwanted data" rather than day-to-day filing: "data and note compression",
plus the general expectation that a local-first app should let someone see
and delete everything it holds — the outside review's "local data map,
retention policy UI" specifically, which is real and not yet one coherent
thing anywhere in the app.

- **Archive** — already scoped in §4 item 2 (an `archived_at` column,
  additive migration). This section doesn't repeat it, just notes it's the
  prerequisite for the rest here.
- **A "delete everything" control.** Export (JSON/CSV/Markdown) already
  exists; there's no equivalent single action for the other direction — wipe
  the database, uploads and preferences and start over, distinct from
  `--reset-password` which only clears the credential. Worth being as
  explicit about what it destroys as `--reset-password` already is.
- **A real storage breakdown, not just the database file.** Asked for
  directly: "can the user see a visual depiction of the storage size the
  application takes up... so they can manage and uninstall optional
  dependencies they don't really use." `GET /storage` today reports only
  `database_bytes` — nothing for `uploads/` (attachments, sketches),
  nothing for the installed extras themselves (`core/extras.py`, which
  already has a real install/uninstall path but no size next to the
  button — `sentence-transformers` alone is the "~2 GB, it pulls in
  PyTorch" case named in its own catalogue entry, exactly the kind of
  thing worth seeing before deciding to keep it). Not a quick add: needs a
  directory-walk per extra's actual installed footprint (import metadata
  doesn't give you bytes on disk), likely cached rather than computed on
  every Settings load. The "uninstall now, reinstall later" half already
  works (`core/extras.py`'s remove/start) — this is purely the missing
  "how much is this costing me" number and a chart on top of facts that
  mostly already exist.
- **One actual "your data" page, not the pieces scattered.** The individual
  facts already exist — where the data lives and how big it is (README),
  what's in the audit log (Settings → Activity), what export and wipe do
  (above) — but there's nowhere that shows all of it as one trust surface.
  This is mostly assembly, not new data: a page that states plainly what's
  stored, where, for how long by default, and links straight to export and
  wipe from the same screen, rather than requiring someone to already know
  those live in three different places.
- **Opt-in retention rules — "forgetting," not just "archiving."** Archive
  above is a manual action; nothing today acts on a note's age on its own.
  A genuinely opt-in rule ("auto-archive notes untouched for a year") is a
  different, smaller thing than automatic deletion — reversible, off by
  default, and closer to the "stale notes" dashboard nudge (§24) than to a
  destructive background job. Worth being conservative here: the app's own
  design principle is that saving a note never fails and nothing is lost
  silently, so any auto-archival needs to be loud about what it did, not
  quiet.
- **Note compression** — asked for directly, and worth being honest about the
  payoff before building it. Notes are short text in SQLite; a notebook of a
  few thousand notes is low tens of megabytes uncompressed, and SQLite pages
  already compress well under most filesystems' own compression. This is
  likely solving a problem that doesn't exist yet at any realistic notebook
  size — worth measuring an actual `data/memorymap.db` before writing any
  compression code, not assuming it's needed.
- **A synthesised export, not just a raw one.** Export today (JSON/CSV/MD)
  is a dump of what's selected; Gemini's grounded suggestion was a step
  beyond that — pick a tag or a cluster and have the AI *compile* it into
  one coherent document (a project writeup, a portfolio piece, a README)
  rather than a folder of separate files the person still has to assemble
  by hand. Closer to a skill (§21) than to the export routes: it's a
  read-many, write-one operation with a prompt behind it, not a format
  conversion. Worth scoping as a skill once the skill system's tool
  allowlist (§21) is solid, rather than as a fourth export format.

---

## 27. Onboarding and first-run experience

**Why.** Asked for directly: "a guided setup on first install (like setting
your name, choosing a model if one isn't yet downloaded, a tour, making the
first note etc)". There already is an `onboarding-overlay` (referenced by
every Playwright driver script in this document as something to dismiss
before testing), so this is about what it covers, not whether it exists.

- ~~**Confirm what the current onboarding actually walks through**~~ **done —
  five static slides** (welcome, capture, ask, graph, appearance), no
  diagnostics anywhere.
- ~~**Fold in first-run diagnostics.**~~ **built — Ollama reachability and
  where the notebook lives**, a new dynamic slide reusing the existing
  `/models/status`/`/storage` endpoints. See HISTORY.md.
  - **Offering to pull a small model (`llama3.2`) if none is installed, and
    checking `MEMORYMAP_DATA_DIR` is writable specifically, are still open.**
    The reachability half shipped; the "fix it for me" half (a pull button)
    and the writability check are real, separate pieces of work.
- **Name, first note, model choice** — as asked, still open. The dashboard's
  name-nudge work already solved the *name* half; onboarding doing it once
  at the start would be the same fix moved earlier, not a new one.
- ~~**Say what the graph and timeline actually are, once, early.**~~ **built**
  — the "Explore your graph" slide now names both the Graph tab and the
  Timeline's Line view.
- ~~**What stays local, and how much space it's using**~~ **built as part of
  the diagnostics slide above** rather than a separate step.
- **Benchmark installed models on first run, to suggest a default rather
  than assuming one** — still open, blocked on §11's model-comparison
  feature existing to wire into, as originally scoped.

---

## 28. In-app help: an AI that knows the docs

**Why.** Asked for directly: "the help area in settings has an ask-AI
feature where the AI has access to all the program documentation and can
help answer your questions."

**Shape.** Closer to the librarian (§4 of `ARCHITECTURE.md`) than to the
agent: grounded, read-only, answers from a fixed corpus rather than the
notebook. The corpus is already written — `README.md`, `ARCHITECTURE.md`,
this file, `CONTRIBUTING.md` — so this is a retrieval index over the repo's
own docs plus a chat surface in Settings → Help, not a new kind of AI
feature. Worth deciding whether it's a `search_docs` tool the *existing*
agent can call (cheaper, reuses everything) or a wholly separate grounded
chat (simpler to reason about, since it never needs to touch the notebook or
a destructive tool). The agent is already offered a narrowed tool set per
question via `tools.focus_for` (§7 of `ARCHITECTURE.md`) — a docs question is
exactly the kind of thing that focusing already exists to route.

---

## 29. Extensibility ideas, not yet scoped

Three asks that are genuinely bigger than anything else in this document and
don't have a shape yet — recorded so they aren't lost, not because any of
them are close to being built:

- **MCP tool support** — "an in-built browser with MCP tool abilities to
  accompany the web search". The Model Context Protocol would let MemoryMap
  either expose its own tools (§7 of `ARCHITECTURE.md`'s 58-tool registry) to
  other MCP clients, or consume external MCP servers as more tools for its
  own agent. Either direction is a real integration, not a checkbox — it
  would need its own trust model, since an external MCP server is exactly
  the kind of thing design principle 1 (offline-first, one narrow opt-in
  exception for web search) currently doesn't have a category for.
  **No longer a blank slate** — ANALYSIS.md §60 (ROADMAP.md item 38) read
  odysseus's actual MCP implementation and split this into two: expose (no
  new trust model needed, build first) and consume (needs the trust model
  this paragraph already flagged, build second).
- **A VS Code extension.** No stated purpose yet beyond the idea itself —
  worth asking what it would let someone do that the app's own web UI, PWA
  and desktop window don't, before scoping anything.
- **A browser clipper.** Gemini's suggestion: a lightweight extension that
  saves a page's text, link and metadata straight from the browser, rather
  than routing through the in-app reader (§13). Distinct enough from the
  in-built browser idea above to list separately — a clipper is passive
  capture from wherever you're already browsing; the in-built browser is the
  app going out and reading on the agent's behalf. Both would land in the
  same place (a note, or the queue in §4a's file-upload work), but they're
  answering different questions about where "capture" happens, and building
  a browser extension is its own packaging problem on top of anything
  MemoryMap does today.

## 29c. Whiteboard, brainstormed — not yet triaged

Asked for directly (make the whiteboard "the best fusion of Microsoft
Whiteboard, OneNote, Draw.io, and Mermaid.js"), after ROADMAP item 11/25's
own confirmed list was cleared (HISTORY.md §56–§57). None of this is
scoped or decided — recorded so it isn't lost, same reasoning as §29
above, and specifically so it doesn't get rebuilt from scratch by a
session that only reads ROADMAP.md's live list.

- **Mermaid.js text-to-diagram, both directions.** Paste Mermaid syntax
  (flowchart/sequence/mindmap) and have it render as real cards/links on a
  board — a deterministic, syntax-driven sibling to the AI-guided
  generation already built (item 11), appealing to anyone who already
  thinks in Mermaid rather than prose. Export the other way (a board →
  Mermaid markdown) makes a diagram portable into a note, a doc, or a
  GitHub README — this app already renders Mermaid fences in note/doc
  markdown (grep `mermaid` in app.js) if that's still true by the time
  this is picked up, worth checking first rather than assuming.
- **Frames/swimlanes** — a named, resizable container a card can be
  dropped into (Draw.io/Miro's own primitive), for process diagrams and
  Kanban-shaped boards. Distinct from grouping (§55, `group_id`): a group
  is "move these together"; a frame is a visible, labelled region that
  cards *belong to*, and reads in an export.
- **Board templates** — a gallery of starting layouts (retrospective,
  SWOT, Kanban, a blank mind-map with just a root card) instead of every
  board starting empty. Needs a decision on where templates live (shipped
  JSON fixtures vs. "save this board as a template").
- **A layers panel** — toggle visibility/lock of a named subset of items,
  the way Draw.io's own layers work. Cheap to want, not cheap to build:
  needs a `layer` concept added to three tables (nodes/sketches/objects)
  and a real UI, not a quick pass.
- ~~**Smart alignment guides while dragging**~~ **Done — see HISTORY.md
  §58** (edge/centre/spacing, colour-coded, Alt bypass).
- **Ink-to-text (handwriting OCR) on sketches** — OneNote's own
  differentiator. A real ML dependency (on-device OCR), so it collides
  with this project's own "don't install torch" constraint unless a
  lightweight option exists; needs research before it's even a maybe.
- **Presentation/step-through mode** — number a sequence of cards or
  frames and step through them full-screen, Miro's own "presentation
  mode." Distinct from the existing zoom/pan/export; nothing here reuses.
- **A board version history**, separate from the undo stack (which is
  in-memory, gone on reload) — notes already have this (History tab);
  boards don't. Needs a real design decision (snapshot-on-interval vs.
  a change log like `AuditLog` already gives notes) before scoping.

## 29d. Whiteboard — scoped and next, not brainstormed

Unlike §29c above, these four were specific asks from the same session
(HISTORY.md §58) with a clear shape. Three are now built (HISTORY.md §61);
the fourth — links to objects — is still open.

- ~~**Rename a board.**~~ **Done (HISTORY.md §61).** `PUT
  /whiteboard/boards/{id}` rewrites the underlying note's first `#
  heading` line; the one board that isn't a note (`board_id=None`,
  "Default board") is refused with a clear error rather than crashing.
- ~~**A Library gallery of boards, mind-maps, and uploaded images.**~~
  **Done (HISTORY.md §61).** The Library's whiteboard area is now two
  sub-tabs: "Whiteboards" (a board gallery over `GET /whiteboard/boards`,
  plus "+ New board", replacing the bare board-switcher dropdown as the
  only way to see what boards exist) and "Image Gallery" (sourced from the
  new `/media` listing rather than `/whiteboard/images`, since it also
  needed to cover plain note-image uploads, not just whiteboard image
  objects — see the Tier 3 media item in ROADMAP.md for what's still open
  there).
- ~~**A structured, small-model-friendly diagram-generation tool.**~~
  **Done (HISTORY.md §61).** `generate_diagram` takes a flat node list
  (`title` or `note_id`, plus `parent_ref`) and a `layout`
  (`tree`/`radial`), creates every card and link server-side in one call,
  and computes placement itself — a BFS depth/slot layout in Python
  (`_diagram_tree_positions`) rather than a full port of
  `wbArrangeMindMap`, since the AI tool only needed the placement math, not
  the interactive drag machinery around it. Capped at 60 nodes; refuses no
  root, more than one root/a cycle, an unresolvable `parent_ref`, and a
  node with both `title` and `note_id`.
- **Links that can reach an object (image/text box), not just a card.**
  Asked about directly (HISTORY.md §58): the border/anchor math itself
  (`wbAnchorPoint`/`wbLinkEndpoints`/`wbBoxRayIntersection`) is generic —
  it already takes a `kind`, and `wbItemBBox("object", ...)` already
  works — but every actual entry point to "what can a link end on" is
  hardcoded to cards only:
  - `dragEndNode`'s own hit-test (app.js) loops `for (const node of
    wbState.nodes)` — an object is never even considered as a drop target
    for the live drag-to-link gesture.
  - `add_whiteboard_link` (`src/memorymap/ai/tools/__init__.py`) does
    `session.get(WhiteboardNode, ...)` for both ends — passing an object's
    id raises "No whiteboard card with id …", not a working link.
  - The link sketch's own data shape (`sourceId`/`targetId`) has no
    `sourceKind`/`targetKind` — every render-time lookup
    (`sketchUpdate.each`, `wbUpdateLinkedSketches`) assumes both ends are
    nodes and would need a kind tag to know which state array to resolve
    an id against.
  Scoped shape: add `sourceKind`/`targetKind` (default `"node"` for every
  existing link, so this doesn't need a migration), extend the hit-tests
  above to also check `wbState.objects`, and give `add_whiteboard_link`
  optional `from_kind`/`to_kind` args. The board/self-link guards just
  added this session (`source.board_id != target.board_id`, `source.id ==
  target.id`) will need the same kind-awareness — comparing a node's id to
  an object's id is meaningless without also checking they're the same
  `kind`.

---

## 29e. Whiteboard master spec (uploaded, MS Whiteboard/OneNote/draw.io/
Illustrator feature audit) — reconciled against 29c/29d, not transcribed

A large uploaded document (~790 lines) did an exhaustive feature-by-feature
comparison against four reference apps and proposed a 6-phase rebuild. Its
Part A (the reference-app feature catalogue) is solid and worth keeping for
future scoping. **Its Part B "current-state audit" and therefore Part C's
gap matrix are meaningfully stale — do not build from them without
re-checking each item against the live code first**, per this file's own
standing rule. Spot-checking a handful of its "MISSING"/"P0" claims found
three that are already done:

- **"`#wb-search` unwired, P0 bug"** — already deleted, `993e639` (see
  ROADMAP.md §0/§1).
- **"Deleting a note leaves whiteboard cards behind, no cascade"** — already
  swept: `autonomous.clean_orphaned_board_cards()`
  (`ai/autonomous.py:320-326`), covered by
  `test_a_card_whose_note_was_purged_is_swept_up`.
- **"Cards show raw truncated text, not the note's formatting" (flagged
  P0/P1, "clearest OneNote-fidelity gap")** — already fixed: card content
  renders through the app's real markdown renderer, not `textContent`
  (`app.js:28975-28997`, own comment documents the fix directly).

Given that hit rate, the rest of its gap matrix (mostly P2/P3 polish items)
should be treated as **candidate**, not verified, until someone re-runs the
same check live. What follows is only what was independently confirmed
against the current code, or was already tracked:

**Already brainstormed — see 29c, don't re-add:** board templates, layers
panel, frames/swimlanes, board version history, Mermaid text↔diagram both
directions, presentation/step-through mode, ink-to-text (already flagged
there as colliding with the no-torch constraint).

**Already scoped — see 29d:** links reaching an object, not just a card
(still open); rename/gallery/`generate_diagram` (done, HISTORY §61).

**Genuinely new, verified missing, not covered by 29c/29d:**
- **Object lock** — no `locked` column on nodes/sketches/objects today
  (checked `core/database.py`). Cheap: one boolean per table, a toggle in
  the Properties panel.
- **Numeric X/Y/W/H/rotation entry** in the Properties panel — confirmed no
  such inputs exist in `index.html` today; only drag-based resize/rotate.
- **A swatches/saved-palette panel** shared across stroke/fill/text-colour
  pickers — confirmed nothing exists beyond the app's own accent-theme
  picker (unrelated). Every colour control today is an ad-hoc native
  `<input type=color>`.
- **Font family + bold/italic/underline for whiteboard text boxes** —
  confirmed only font size exists today.
- **Connector/link labels** on whiteboard links — distinct from the Graph
  tab's link-reason field; whiteboard's own `WhiteboardSketch` link type
  has no label. Would matter if `generate_diagram` output is ever meant to
  carry relationship text ("depends on," "leads to"), not just a line.
- **AI-readability additions**, extending what `readwhiteboard`/
  `searchwhiteboard`/`generate_diagram` already do (`ai/tools/__init__.py`): an
  outline-text export mode (Mermaid-adjacent, for the AI or a human to read
  a board as a flat description); a semantic (embedding-based) index over
  whiteboard text-box content, since `searchwhiteboard` is keyword-only
  today; letting `generate_diagram` extend an existing board's cards as
  parent context, not just create fresh ones.
- **Orphaned media garbage collection** — confirmed still genuinely
  missing (no `clean_orphaned_media`-shaped function anywhere), unlike the
  card-cascade claim above which turned out to already be fixed.
- Smaller polish items the spec's Part C lists and a live check didn't
  contradict, kept for reference rather than re-verified line by line:
  resize-from-center, flip h/v, whole-object opacity, a status bar
  (zoom/tool/item-count), a contextual quick-action bar near a fresh
  selection.

**Not adopting**, matching the spec's own reasoning: full vector path/anchor
editing (Illustrator's actual product category — wrong tool for a
mindmapping app), real-time multi-user collaboration (contradicts this
project's single-user/local-first design principle), handwriting/math ink
recognition (no stylus-first workflow in evidence), image trace/pattern
fills/mesh gradients (print-design-tier, no tie to this app's use case).

---


## 29b. Carried out of the §40 audit

Full context in [../ROADMAP.md §40](../ROADMAP.md#40-the-antigravity-audit);
the features these attach to are described in §39. Companions:
[ANALYSIS.md](ANALYSIS.md) · [HISTORY.md](HISTORY.md) ·
[HANDOVER.md](HANDOVER.md).

Ranked. The first two are the same problem wearing two hats — a feature that
changes the app's behaviour without showing the user what it did:

1. ~~**A memory-stream screen.**~~ **Built** — Settings → The AI → *What it
   remembers*. Original entry kept for the reasoning:
   `save_user_preference` lets the model write
   standing instructions into its own future system prompts. There is no UI:
   the user cannot list them, edit one, or turn one off. The `user_preferences.
   active` column exists precisely for that and nothing sets it. Small piece of
   work, and it is the difference between a helpful feature and an
   unexplainable one.
2. **A dry-run for the background librarian.** Turning it on lets an agent edit
   the notebook unattended. There is no preview. `taskhistory` records each run
   and the agent already emits `change` events with undo payloads, so "here is
   what the last pass did, undo any of it" is mostly assembly.
3. ~~**Whiteboard cards outlive their notes.**~~ **Done** —
   `autonomous.clean_orphaned_board_cards`, beside the vector sweep.
4. **`graph_local` costs a full notebook scan** to draw a local neighbourhood:
   every entry loaded, a full similarity sweep, and a PageRank over every node.
   Correct, and the opposite of what "focus mode" should cost.
5. ~~**PageRank runs on every `/graph` call, uncached.**~~ **Done** — see
   ROADMAP.md §0/§9 item 2: `routes_graph.py:60-105` caches pagerank/
   similarity by a notebook fingerprint, invalidated on write or embedding-
   model switch — exactly the "invalidation on write rather than a TTL" this
   item asked for.
6. ~~**`/media/{filename}` serves uploads same-origin with no type restriction.**~~
   **Done** — allowlist on upload *and* on serve, plus `Content-Disposition`.
   Original reasoning:
   No traversal — the name goes through `safe_filename` — but an uploaded
   `.svg` or `.html` is served from the app's own origin, and the AI can write
   here too. A `Content-Disposition: attachment` and an extension allowlist.
7. **Decide on `edit_note` being destructive.** See ANALYSIS §34b.

---

## 62. Extract notes — from the Writing Room, Documents, and Graph selections

**Built, preview-first.** `ai/extractor.py` (`propose_split`,
`merge_near_duplicates`), `POST /entries/extract/preview` and
`/entries/extract/commit`, and one shared preview modal wired to the Writing
Room, Documents and the whiteboard — plus, since §85, the **text-selection
kebab**, which made it reachable from any prose in the app rather than only
those three surfaces. 21 tests in `tests/test_extract_notes.py`. Full
resolution note in [HISTORY.md](HISTORY.md).

**Still not verified:** the AI's actual splitting, categorising and
link-reasoning judgement against a real model — this sandbox has no Ollama, so
only the fake-transport tests exercise it.

## 63. Ship a starter skills library — DONE, this claim was stale

Built — the detail moved to [HISTORY.md](HISTORY.md) ("Retired from the live files, 2026-09-07"). Kept for its number.

## 64. Documents editor — behind the rest of the app, needs its own pass

The Documents tab (`app.js:5314`, "long-form writing") is a plain
markdown text area: confirmed no slash-command menu, no block nesting, no
focus/distraction-free mode. Every one of those is table-stakes in a
"second brain" competitor (Kortex, Notion, Obsidian) and the app already
has the primitives a slash-command menu would reuse — the command palette
pattern already exists elsewhere in the app (see DESIGN.md/ARCHITECTURE.md
for the existing overlay/palette convention) and would not need a new
interaction model invented from scratch, just a document-scoped instance
of it. Not scoped in detail here — flagged so it's not lost, and so the
next session doing this doesn't start from "what does a modern editor
need" without first reading what Documents currently has.

## 65. Highlight/web-clip capture

From the Kortex read (ANALYSIS.md §66): a way to save a highlighted passage
from something read elsewhere straight into a searchable note.

**Half built (§85).** The capture surface exists and is the piece this item
called small: highlight any prose in the app, open the selection kebab (⋯),
and **"Save with its source"** appears whenever the passage came from the web
reader — saving it as a markdown blockquote with a real link back to the page.
`clippingMarkdown`/`selectionSource` in `app.js`. The passage is quoted rather
than pasted flat on purpose: a clipping is somebody else's words, and a
notebook that cannot tell them from yours is worse than one that refuses
clippings.

**Still open, and deliberately separate:**

- **Sources outside the app.** Today the only surface that knows where a
  passage came from is the built-in web reader. A passage pasted in from a
  real browser, a PDF reader or a Kindle arrives with no origin at all, and
  nothing asks for one. The smallest useful next step is a paste-a-highlight
  box that takes the text *and* a URL/title by hand.
- **Source as metadata rather than body text.** §65 originally asked for the
  source "kept as metadata rather than folded into searchable body text". What
  shipped folds it into the note body as a link, because `Entry` has no source
  column. A real one is an additive schema change plus a place to show it.
- **A Readwise/Kindle importer** is a genuine integration and should be sized
  separately before anyone commits to it.

## 75. Voice memos: capture, storage, playback, and a dedicated library page

Asked for directly. `/entries/{id}/files` now has a real allowlist
(`ATTACHMENT_SUFFIXES` in `routes_files.py` — images, PDF, common office
formats, text and code, refusing anything else with a 415, e.g. video), but
audio is deliberately not on that list yet — there is no player anywhere in
the app, so an uploaded `.mp3` would just be a file nobody could listen to.
Three separable pieces, roughly in the order they'd need building: (1) a
record-a-voice-memo control (browser `MediaRecorder`, saved as an
attachment once `.mp3`/`.wav`/`.m4a`/`.webm` are added to the allowlist and
a size ceiling suited to audio rather than documents is picked — 50MB is
generous for a PDF and stingy for 20 minutes of audio), (2) an `<audio>`
player wherever an attachment is already rendered inline (the note card,
the lightbox), and (3) a Library subtab alongside AI Skills/Whiteboards/
Image Gallery listing every audio attachment across the notebook, the way
`routes_library.py`'s `_notes()`/`_archive()`/`_shelved()` already do for
images via `thumb_by_entry`. Meeting notes were the specific use case
raised — a memo recorded during a meeting, attached to that note.

## 76. Keyword-only note filing while the AI is unavailable, flagged for later AI review

Asked for directly, and specifically **not** the same as `janitor.categorise`'s
existing low-confidence path (routes_entries.py's `create_entry` already
falls back to `UNCATEGORISED` when the AI call itself fails — that's a
"give up" fallback, not a second opinion). What's being asked for is a real
non-AI filer: while no local model is available at all, look at a new
note's own words (keyword/term overlap against existing categories and
tags — no embeddings, no model call) to make a real best-effort filing
guess instead of dumping everything into Uncategorised, and tag every note
filed this way so it's unmistakable later. Once the AI is available again —
on its own schedule, not necessarily right away — the autonomous agent's
existing stale/orphaned-note review pass (§17 in the session's
completed-work list) checks that tag specifically: did the keyword guess
get the filing and metadata right, and correct it if not. Scope: a
keyword-overlap filer as a genuine alternative code path when
`deps.get_ollama()`/the model manager reports unavailable (not merely a
lower-confidence branch of the AI path), a `filed_by="keyword_fallback"` (or
similar) marker distinct from the existing `"none"`/`"thread"`/`"user"`
values, and a query added to the existing review pass rather than a new one.

## 77. Notes-tab pagination and page-aware note links

Asked for directly: a large notebook's Notes tab is one continuously growing
list rather than a paged view with a page-size choice and a page selector.

**The performance half is done and is NOT this item (§86).** `renderEntries`
now renders in chunks as you scroll (`renderIncrementally`), so the DOM is
proportional to what you have scrolled past rather than to the notebook —
measured at 1,501 notes as 533 ms → 16 ms and 31,680 → 4,306 nodes. That
deliberately keeps the list **one continuous scroll**, which is the thing this
item distinguishes itself from.

**Item 1 is now built. Item 2 is still open and scoped below.**

1. ~~A page-size preference and a page selector top and bottom.~~ **Built.**
   `#notes-page-size` (All / 25 / 50 / 100, default All — today's continuous
   scroll, untouched) sits beside the existing Sort control; choosing a
   number replaces the scroll with one flat page and a Prev/Next bar
   (`#notes-pagination`) below the list. Persisted in `localStorage`, the
   same pattern as the graph's gravity/spread sliders. Deliberately kept
   separate from §86's `renderIncrementally` chunking — that stays the "All"
   path's implementation, unmodified. `paginateNotesForDisplay()`
   (`app.js`) is the one seam both the flat-sort list and the threaded list
   pass through, so a page can never overrun its slice.
   **One accepted trade-off, not a bug**: a thread can split across a page
   boundary (a parent on page 2, a continuation on page 3) — pagination
   slices the already-flattened `[entry, depth]` order rather than keeping
   threads whole across page boundaries, matching the same "small, don't
   over-build this" scope this item's own text asked for. Verified live in
   Chromium: 120 seeded notes at 25/page → 5 pages, Prev disabled on page 1,
   Next/Prev step correctly, switching back to "All" restores the original
   60-item scroll window with zero console errors. `test_frontend_ids.py`,
   `test_frontend_handlers.py`, `test_style_scale.py` all still pass.
   **Follow-up, fixed the same session, and worth recording because it wasn't
   really about this one select.** Reported directly: the page-size dropdown
   didn't match Sort's height/alignment. Measured before touching anything —
   height and font-size already matched exactly (both inherit
   `.library-toolbar select`'s shared sizing rule) — the real bug was width:
   the global `select { width: 100% }` base rule (`01-forms-settings.css`)
   is correct for a form field and wrong in a flex toolbar, and it only
   showed up here because this was the first `<select>` crowded enough to
   land *alone* on a wrapped line — with siblings to flex-shrink against
   (Sort, sharing a line with five other controls) the same 100% preferred
   width just never mattered before. `.library-toolbar select { width: auto
   }` fixes it at the toolbar level, not per-control, so the next crowded
   `<select>` added here inherits the fix rather than re-discovering the bug.
~~2. **The hard half: a wiki-link click has to land on the right *page*.**~~
   **Built.** `flashEntry` (app.js) already answered the design question
   this item was scoped around: it resets category, drafts and search to
   whatever the target's own view needs *before* it draws anything — a
   jump always lands in that reset default view, never in whichever
   filter the *origin* (Chat, the graph, a document) happened to have
   active, since most origins have no Notes-tab filter state to preserve
   in the first place. With that view fixed, the only thing missing was
   the page number.

   `orderedNotesForCurrentView()` is `renderEntries`'s own order —
   flat-sorted or thread-flattened, whichever the current search/sort
   picks — pulled out so there is exactly one place that decides "what
   order do these notes render in," used both to paint the list and to
   answer "which page is note N on." Deliberately **not** used to replace
   `renderEntries`'s own inline copy of the same logic: that render path
   is live, tested, and previously verified with real numbers (§86,
   §77 item 1); rewriting it to consume a shared helper risked a working
   feature for a refactor with no user-visible gain, so the small
   duplication was accepted instead. `resolveNotePage(id)` walks that
   order, finds the note, and divides by the active page size — "All"
   (no pagination) always answers page 1. Returns `null` for a note the
   current filters would hide entirely, which `flashEntry` treats as "stay
   on whatever page you're on" rather than lying about a page number.

   **Live-verified, both branches.** 61 flat notes, 25/page: starting on
   page 1, clicking a wiki-link to the oldest (page-3) note lands on
   "Page 3 of 3" with that exact note flashed. The harder case — the one
   this item's own text worried about, a thread **child** whose page
   depends on its *parent's* position, not its own sort key — verified
   separately: a parent buried under 55 newer notes, its child linked to
   directly, correctly resolves to "Page 3 of 3" with the child itself
   (not the parent) flashed and `.thread-child` still set. Zero console
   errors either run.

## 78. Whether the backend needs more concurrency than it already has

**Answered by the code, in the §85 audit — nothing to build.** Route handlers
are sync `def` on purpose: 238 sync against 1 async across `routes_*.py`, so
FastAPI runs every one of them in a threadpool and blocking IO inside them is
correct rather than a bug. SQLite is in WAL with `busy_timeout=5000`, so a
background job overlapping a page load is routine. The async-httpx item in §20
is a smaller and more optional change than this section assumed.

## 79. Linux release packaging — done; macOS still open

Asked for directly. Linux: built — `packaging/linux/memorymap.spec` +
`build-linux-package` in `.github/workflows/release.yml`, zipping a
PyInstaller onedir build (no installer format needed the way Windows
needs Inno Setup). Ships **without** the system tray: `_start_tray` runs
pystray's event loop on a background thread while `webview.start()`
blocks the main one, which the code's own comment says only Windows'
backend is known to tolerate — Linux's GTK backend has the same
main-thread-only constraint that already ruled out macOS, so the tray
call is now gated to `sys.platform == "win32"` rather than guessing.
Icon is `icon-512.png`, not the `.ico` (never confirmed GdkPixbuf decodes
it). Unverified until the Linux CI job actually runs, per this project's
standing rule for anything PyInstaller — it doesn't cross-compile.

**macOS is possible but has a real barrier beyond code.** An unsigned
`.app` triggers Gatekeeper's "app is damaged" warning on a current
macOS — not a bug, a deliberate OS policy — so shipping one that
actually opens for someone else requires an Apple Developer account
($99/year) and a notarization step in CI, not just a PyInstaller/DMG
build. Also inherits the same tray/threading question above and would
need its own answer, not an assumption it behaves like Linux. Worth
deciding deliberately rather than discovering after building the rest.

---

---

## 79b. New items, raised by the §85/§86 audit — not yet triaged

Logged rather than built. Each was found while doing something else, so none
has been scoped; they are here so the finding is not lost with the session.

- **Chat history has retention; nothing else does.** §86 added
  `conversation_retention_days` (off by default, pinned chats exempt). The
  same question is unasked for `AuditLog`, `entry_revisions` and the task
  history — all three grow monotonically, and `entry_revisions` in particular
  keeps a full copy of a note's text on every edit. Nobody has measured which
  of them actually gets large in a year of real use, and that measurement
  should come before any policy.
- ~~**A support-bundle size ceiling.**~~ **Checked, not needed.** This entry's
  own premise ("no cap") was wrong: `core/logbuffer.py` already bounds every
  input to the bundle — `MAX_RECORDS = 500`, each message truncated to
  `MAX_MESSAGE_CHARS = 2000`, each trace sliced to 8000 chars in
  `BufferHandler.emit` — so `logs.json` tops out around ~5MB uncompressed in
  the worst case, and `preferences.json`/`status.json`/`counts.json`
  (`routes_settings.support_bundle`) are all small, fixed-shape payloads with
  no user-content field that could grow unbounded. No ceiling to add; grep
  before building would have found this.
- **`GET /entries?semantic=true` now has two callers** (the Notes tab and, as
  of §86, the Library). The fetch-and-cache shape in `refreshLibrarySemantic`
  is the one to extract if a third appears — the command palette is the
  obvious candidate.
- **Semantic search still has no meaning for four of the five Library kinds.**
  §86 shipped the honest version — meaning-matching for notes, words for
  documents, chats, images and skills, and the control says so. The real
  question it defers: *should* documents be embedded? They are the one other
  kind with substantial prose, and embedding them would make "find the
  document about X" work the way notes already do. Not obviously worth the
  index size; worth deciding rather than leaving implicit.
- **Colour contrast has never been measured.** BACKLOG §19 has said so for a
  long time and every pass since has fixed something else. It needs a
  contrast-ratio tool run over the glass surfaces and the newer palettes, not
  another reading of the CSS.
- **The document-textarea resize fix has never been seen working.** Headless
  Chromium will not drive a native resize handle — real mouse events and
  CDP-level ones both left the rendered height unchanged, and an isolated
  repro showed the same. Whether that is this Chromium build or evidence the
  root-cause theory is wrong was never chased down. One look in a headed
  browser settles it.
- **A naive orphaned-CSS sweep produces 33 false positives.** Classes built by
  template (`heat-${n}`, `library-${kind}`, `priority-${p}`,
  `result-reason-${r}`, `plan-step-${s}`, `outline-h${n}`, `graph-edge-${k}`)
  look dead to any grep for the literal string. Three genuinely dead rules
  were removed in §86; anyone re-running that sweep should expect the same 33
  and not delete them.
- **A visual splash/loading window during startup, before the server exists
  to serve one.** Asked for directly: on Windows, `start.bat`'s dependency
  install (and the self-update `git pull` before it) can run for minutes with
  only console text as feedback — invisible entirely if the user launched via
  `start-desktop.bat` without watching the console, or if it's minimized. The
  desktop mode already solved the *narrower* version of this (see
  `_wait_for_server`'s docstring in `__main__.py` — the pywebview window
  doesn't open at all until the server is confirmed accepting connections, so
  there's no long black-screen window sitting open), but nothing shows
  anything at all during the pip-install/git-pull phase that happens before
  that. A real splash would need its own lightweight window (Tk ships with
  every Python install and needs no extra dependency, unlike pywebview) shown
  by the launcher itself, independent of the app server, then closed once
  `_wait_for_server` succeeds — a different lifecycle than anything else in
  this launcher, not a small addition to an existing one. Scoping this
  properly (what shows, on both start.bat and start.sh, in both browser-tab
  and desktop mode) is its own session, not a follow-on to the app.js split.
- **Agent-mode auto-detection with a confirmation popup.** Asked for
  directly: when the AI notices a chat message looks like it needs agent
  mode (tools/multi-step work) but the user isn't in it, offer to switch
  with a confirmation popup in the chat — and if the user isn't on the Chat
  tab when this comes up, a notification instead, same as for other things
  needing the user's input mid-run. Needs real scoping before building: what
  actually triggers the detection (a cheap heuristic vs. a model call before
  every message — the latter costs a round trip per message, which cuts
  against the token-efficiency ask two items below), and how it interacts
  with `skillManual`/step-by-step mode already in the agent loop.
- **Skill auto-detection with a confirmation popup.** Same shape as the
  item above, for the app's saved Skills instead of agent mode: detect when
  a user's chat message matches an existing skill and ask before running
  it, rather than requiring the user to invoke it by name. Same open
  question about what the detection costs per message.
- **Start/completion notifications for named sub-processes.** Asked for
  directly, naming "renaming with AI," "generating title," and "other
  things" as examples — a toast or notification when one of these begins,
  and a second one confirming success (or failure) once it ends, rather
  than the current silent-until-done (or silently-failed) behaviour.
  `core/taskhistory.py` already gives failed/completed background jobs a
  home (this session wired captioning into it, §91) and
  `recordNotification` (app.js) already exists for the notification centre
  half — the gap is the *in-progress* half: nothing currently fires when
  one of these starts, only when it ends. Scoping needed: which calls count
  as "sub-processes" worth this treatment (every `apiJson` call would be
  far too noisy) — likely the same handful already named plus whatever else
  already blocks the UI behind a spinner (caption generate/regenerate,
  link-reason generation, the AI edit route).
- **A deeper token-efficiency and small-model-suitability pass on chat and
  agent prompts.** Asked for directly: "see if the token usage and
  consumption in chats can be reduced and made more efficient... make all
  processes in the chat tab and backend suitable and well designed for
  smaller models as well as larger models." `agent.PROSE_BUDGET_CHARS` is
  already asserted (CLAUDE.md), and this session's provider-level retry
  fix (§91) reduces one concrete waste — a failed call needing a manual
  resend that re-sends the whole prompt again. Nothing beyond that has been
  measured this session: a real pass would need to profile actual prompt
  sizes across the librarian/agent/skill paths against a range of context
  windows (the app already tracks `usable_context` per model) and look for
  prompt content that scales with notebook size rather than staying flat.
- **AI follow-up question suggestions in chat and the Ask sub-tab.** Asked
  for directly: after an answer, offer 2-3 suggested follow-up questions,
  in both the Chat tab's conversations and the Notes tab's Ask sub-tab.
  `loadChatSuggestions()` (app.js) already exists for a *different* kind of
  suggestion (conversation starters, empty-state only) — this would be a
  new per-answer suggestion, generated from the answer just given, most
  likely reusing the existing chat model rather than a new route.
- **Graph minimap drag-to-zoom, plus pinch/keyboard zoom.** Asked for
  directly: click-and-drag a rectangle over the graph's minimap to redefine
  the main view's window/position/zoom to match, and two-finger
  pinch-zoom (touch) plus a keyboard zoom in/out, matching what the main
  graph canvas already supports. `graph.js` already owns the minimap
  rendering and the main canvas's own zoom/pan handlers — this extends
  both rather than adding a new subsystem, but the minimap's own hit-testing
  and coordinate-mapping (screen rect → graph viewport) isn't scoped yet.
- **Compression/archival for rarely-used notes, documents, files and
  chats.** Asked for directly: let the user compress content they don't
  touch much and restore it on demand, at three possible granularities —
  one item, a whole space, or a group matched by some rule — with chat
  conversations floated as a candidate too. Worth doing, but genuinely
  underspecified before it's buildable, and the open questions matter more
  than the mechanism:
  - **What "compressed" means here.** Gzipping a markdown row saves little
    (SQLite text compresses well already at the filesystem/backup level,
    and notes/documents are what semantic search, the graph and the AI's
    retrieved context all read directly — compressing the row means every
    one of those needs a decompress-on-read path, or has to skip
    compressed items, which is a correctness change dressed as a storage
    optimisation). What plausibly does help: `MediaUpload` files
    (whiteboard photos, attachments) are actual binary weight, so
    archiving *those* — moving cold files to a separate on-disk location,
    or genuinely compressing image bytes — is the more defensible half of
    this idea.
  - **What "rarely used" means.** `Entry.access_count` already exists and
    is the obvious signal, but nothing currently reads it for this
    purpose; a real design needs a threshold (count, or count-since-last-N-
    days) and a way to preview what would be archived before it happens.
  - **Automatic-by-criteria is the riskier half.** A background job that
    silently archives content on its own schedule needs to be very sure it
    never removes something the user is about to look for — at minimum a
    dry-run/preview step and an easy bulk-restore, closer in spirit to
    `media_gc.py`'s existing "dry run first, refuse rather than guess"
    posture than to a fire-and-forget cron job.
  - Chat conversations specifically are already the cheapest form of this:
    they are pure JSON text with no embeddings or graph edges pointing at
    them, so "compress" there could mean something as simple as excluding
    older, unpinned conversations from the default list view rather than
    an actual archive format — worth deciding before building either.
- **Can the AI read chat conversation history?** Partly already built and
  worth knowing about rather than reopening blind: an agent-mode tool
  (`ai/tools/__init__.py`, searches `Conversation.title`/`.messages` by
  keyword) already lets the AI look up *other* saved chats by name/topic —
  built specifically because "each turn only ever saw its own thread, so
  the assistant had no memory of anything said in a different chat." Two
  real gaps remain: it's an agent-mode tool, so it isn't reachable from a
  plain conversational chat unless tools are enabled; and it searches by
  keyword rather than being handed relevant history proactively the way
  notes are via retrieval. Extending keyword search to embedding-based
  recall, or surfacing it outside agent mode, is the open half of this.
- **A note against ROADMAP.md §90 item 3** (upload any document type with a
  real per-type viewer, not built yet — see there for the full ask):
  asked for directly, when this gets built, a scanned/non-selectable PDF
  page's text extraction should go through the vision model
  (`ai/vision_ocr.py`'s existing shape — rasterise the page, transcribe it
  the same way an image is today), **not** Tesseract+`pdf2image`/poppler.
  "I primarily want this AI OCR to be separate from Tesseract... only want
  to use an AI vision model for OCR for images and scanned documents" —
  Tesseract (`core/ocr.py`) stays as the separate, already-built,
  install-optional local path for raster images (it already degrades to
  "extracts nothing" if not installed, so a notebook that never installs
  it already gets exactly this today for images); the new PDF-page path
  should not add a second dependency on it.

---

## §95 — the forward list

Asked for directly: *"brainstorm new features and improvements… what features
are missing, what should be added, what new capabilities?"* Written after a
session that read most of the codebase, so these are shaped by what is
actually there rather than by what a notes app generally has.

**Ranked by (what it unlocks) ÷ (what it costs), not by size.** Anything
already built is excluded — five items were dropped from this list during
writing for exactly that reason, which is the standing lesson of this file.

### A. Model and backend

1. **llama.cpp, properly framed.** Now item A in ROADMAP.md. The app already
   speaks to `llama-server`; what is missing is saying so, detecting it via
   `/props` (which reports the real `n_ctx`), and *then* deciding whether
   in-process `llama-cpp-python` is worth a per-accelerator wheel matrix.
~~2. **Model health card.**~~ **Built (§97).** Settings → Models' existing
   spec table (size, quantisation, window, capabilities) now has a plain-
   language line under it: "a long chat will start dropping its earliest
   messages after roughly N exchanges", computed client-side from
   `usable_context` using the same shares `ai/context.py` uses server-side
   (an estimate, not a promise — an average exchange length is itself a
   guess). Banded at the edges: a very small window says so without a
   number, a very large one says it won't run out.
~~3. **Per-task model routing, made explicit.**~~ **Built (§97).** Settings →
   Background tasks' finished-jobs list already carried the model name
   (`taskhistory.record`'s `name` param, set by captioning and OCR already)
   but never rendered it — one line in `renderTaskHistory` (app.js) to show
   it next to the timestamp. Also added `name=` to the autonomous-pass
   recording (it used the utility model but never said so).
4. **A "this model is struggling" signal.** §94 added a probe that tells a
   broken tools path from an outage. The same signal could be surfaced:
   after two tool-path failures on one model, offer the tool-free mode
   rather than silently degrading each turn.

### B. Retrieval and context — where the real quality ceiling is

5. **Show the context budget in the UI.** `context.plan` already rations
   every part of the prompt and logs it. The chat has a percentage meter but
   no breakdown, so "why didn't it see my note?" is unanswerable without the
   log. A hover on the meter showing *system / notes / history / reply* is
   nearly free and answers the single most common AI complaint.
~~6. **Recency and pinning as retrieval signals.**~~ **Built (§97).** A
   third ranked list — the hybrid candidates reordered by pinned-first,
   then most-recently-touched — fused (RRF, by rank position, same as the
   existing semantic/keyword fusion) into the two `search_manager.py`
   already had. Deliberately a *reorder of candidates a real search already
   found*, never a new source of matches: a pinned note unrelated to the
   question is not a better answer to it. New test proves it (two notes
   tied exactly on relevance, pinning the older one flips the tie-break
   that would otherwise always favour the newer id).
7. **Re-rank the top N with the utility model.** Hybrid search picks eight
   notes; a 1B model scoring those eight for actual relevance to the question
   costs one short call and is the standard fix for "it quoted the wrong
   note".
8. **Conversation summaries as retrieval targets.** `compress_chat` writes
   summaries; nothing searches them. A question about something discussed a
   month ago cannot reach it unless a note was made.

### C. Capture — the half the app is named for

9. **Web clipper.** `read_url` exists server-side; there is no bookmarklet or
   share target, so saving a page means copy-paste.
10. **Email-in.** A local IMAP poller filing into a category is a well-worn
    pattern and turns the app into a capture destination rather than a place
    you go.
~~11. **Recurring notes / templates with dates.**~~ **Mostly already built,
    fixed the rest (§97).** `applyTemplate()` (app.js) already resolves a
    literal `{date}` token against any template's content — built-in
    ("Journal — {date}") or custom — via a plain string replace, so a
    daily-note template already worked. What was missing was
    *discoverability*: nothing in the Templates settings "Add your own" UI
    said the token existed. Added a one-line tip under the custom-template
    textarea. True recurrence (auto-create on a schedule) is still not
    built and would be a separate, larger feature.
12. **Voice capture beyond dictation.** faster-whisper is already an extra.
    A "record a thought" button that transcribes *and* files is a different
    feature from dictating into a box.

### D. Trust and safety

~~13. **Private notes need an audit trail.**~~ **Already built when checked
    (§97, HANDOVER.md).** `get_entry` (routes_entries.py) already logs
    `"decrypted"` for a private note read while the vault is unlocked —
    this item was stale, not the code.
~~14. **Export a single note/document.**~~ **Built (§97).** `GET
    /entries/{id}/export.md`, mirroring the document route already in
    place — same title-as-H1 preamble (skipped when the note already
    starts with one), same filename sanitising. A "Download .md" item on
    a note's own overflow menu (Notes tab) and its Library "All"-view
    card menu, in the same spot the Document kind's own copy already
    sits. 4 new tests (`test_api_entries.py`).
15. **A dry-run mode for the agent.** `make_plan` shows intent, but a user
    who wants "tell me what you would change without changing it" has to
    trust the plan. A mode that collects the writes and shows a diff before
    committing would make destructive skills usable by people who currently
    avoid agent mode.

### E. Polish worth doing as one pass

~~16. **A real empty state for every tab.**~~ **Partially done (§97).** The
    Library's three subtabs that sit beside "All" (Documents, Whiteboards,
    Image Gallery) had a bare one-line `<p class="muted">` where "All"
    itself already had the icon+title `.empty-state` component — fixed to
    match. Along the way, found and fixed a real bug the source read alone
    would have missed: `renderLibraryDocuments()`/
    `renderLibraryBoardsGallery()` overwrote the empty-state element's
    `textContent` on every render (to show the "no search match" message),
    which silently wiped out the new icon+title markup the instant the
    function ran — the rich version would have shown for one frame, then
    been replaced by plain text. Fixed by giving the "no results for this
    search" case its own sibling element (`*-no-match`), matching the
    pattern the Image Gallery subtab already used correctly. Verified live:
    genuine-empty (icon+title), no-search-match (plain text), and had-results
    all screenshotted. Chat sidebar's `#conv-empty` and the Documents tab's
    own `#doc-empty` were deliberately left as plain text — narrow sidebar
    lists, not grid panes, so the same treatment would look oversized;
    unlike the three fixed, no user report named them.
~~17. **Keyboard-first navigation.**~~ **Already built when checked (§97).**
    `initEntryListKeyboardNav()` (app.js) already does Up/Down roving-
    tabindex movement between note cards and Enter-to-edit, wired up and
    called at module load. Verified live (Playwright): focus, ArrowDown
    twice, ArrowUp back, Enter opened the note for editing — all correct.
    This entry was stale, not the code.
18. **Undo for destructive skill runs.** Individual tools record undo; a run
    that made twelve changes has twelve separate undos and no "undo that
    run".
19. **`app.js` is 22,000 lines.** The clean first extraction is `chat.js`
    (~3,300 contiguous lines: ask, the chat tab, image attachment, the agent
    timeline, the dock disclosure), following the §88.3 pattern that already
    produced documents.js, library.js, dashboard.js and settings.js. No
    user-visible gain, so it waits behind anything on this list that has one.
~~20. **Backup retention should be a setting.**~~ **Built.** Settings → Data
    → "Keep this many backups" (`#backup-retention`), a real preference that
    prunes immediately on change — was a hard-coded, always-enforced cap
    before.

### Deliberately not on this list

- **Sync / multi-device.** It is the most-asked-for thing in every notebook
  app and it is the one that would break this one: the app's premise is that
  the data never leaves the machine, and every sync design either weakens
  that or adds a server. If it is ever done it needs its own decision, not a
  backlog line.
- **A plugin system.** Skills already cover the "make the app do a new thing"
  case without a new extension surface to secure.

---

## §96 — Guides, and diagrams the whiteboard can take

Asked for directly, and the two halves belong together: both are about the AI
producing *structured* output the user then owns.

### Guides — curated instructions the AI writes to

A **Guide** is a named, editable instruction set the AI pulls in when it is
writing: how to scaffold an academic assignment, how this user wants LaTeX
written, when a mermaid diagram is the right answer, a house style for
meeting notes. Ships with curated ones; the user can edit any of them and add
their own.

**Why it is not a persona and not a skill**, which is the design question:

- A **persona** changes *voice* and applies to everything.
- A **skill** is a *procedure* the agent runs, start to finish.
- A **Guide** is a *format contract* for one piece of output — it does not run,
  it constrains. Several can apply at once (an assignment guide + a LaTeX
  guide), which neither of the others allows.

Shape:

- Stored like skills (a table, editable in Settings), with a name, a trigger
  hint, and the instruction body.
- **Selected, not always-on.** Attached explicitly in the composer or the
  document editor, and *offered* by the same deterministic matcher the tool
  focus uses (`ai/toolwords.py`) — which already tells "write my assignment"
  from "what is an assignment". Prompt budget is the reason: guides are prose,
  prose is the fixed cost `§94` just spent a release cutting, and a guide that
  silently attaches itself would undo that.
- Budgeted the same way everything else is (`ai/context.py`), with its own
  share, so a long guide crowds out notes visibly rather than silently.
- Applies to all three surfaces the user named: chat replies, note drafting,
  and `POST /documents/{id}/ai-edit`.

**Open question worth answering before building:** whether a guide should be
able to carry *examples* (few-shot) as well as instructions. Examples work far
better on small models and cost far more tokens — probably a per-guide flag
rather than a global decision.

### Diagrams: mermaid as the interchange format

The user's framing is the right one and worth keeping exactly: the AI writes
**mermaid**, the user previews and edits the mermaid, and only when they are
happy is it *exported* to the whiteboard as real cards, boxes and connectors —
**with the mermaid kept**, so it can be re-edited or reused later.

That ordering matters. `generate_diagram` already exists and writes straight
to the whiteboard, which means a wrong diagram is a mess to undo. Mermaid as
an intermediate makes the AI's output a *text artefact the user owns*: cheap to
regenerate, diffable, editable by hand, and portable out of this app entirely.

Work, in order:

1. **Render mermaid where markdown already renders.** Fenced ```mermaid blocks
   in chat, notes and documents. Nothing renders them today (`grep mermaid
   frontend/` is empty), so today they show as code.
2. **A preview + edit step** — the mermaid on one side, the rendered diagram on
   the other. The document editor's Split view is the same shape and can be
   reused rather than rebuilt.
3. **Export to whiteboard**: mermaid AST -> whiteboard cards, shapes and links.
   The whiteboard already has all three primitives and `wbArrangeMindMap`
   already does tree/radial layout, so this is a translation, not a new engine.
4. **Keep the source.** The generated mermaid is stored on the board it
   produced, so "edit the diagram" can mean either "move this card" or "change
   the text and re-export".

### Related, and cheap: finish the rendering story

Checked this session: chat, documents and the dashboard digest all go through
`renderMarkdown`, but **notes deliberately do not** (see the comment at
`app.js:3791`), and **no surface renders mermaid or highlights code**. Before
any of the above, worth settling as one pass: which surfaces render markdown,
whether code blocks get syntax highlighting, and whether notes should join —
because "the AI wrote a diagram and I can't see it" and "my code block is
grey" are the same gap.

## §98 — reported live during the §90.2 small-screen pass, logged not built

Four asks landed while the small-screen audit was running. Two were built the
same session (the capture-composer `?` guide; the gallery-menu clipping fix —
both in HANDOVER.md). These are the ones deliberately left open, with what was
already checked so the next session does not re-derive it.

1. **Collapsible / dropdown blocks at small screen sizes.** Asked for
   directly, and deferred by the same message: *"some element blocks can
   collapse and become dropdown menus, or can have left right buttons to move
   left and right."* This is the shape §90.2 (ROADMAP) was heading toward
   anyway, so treat it as that item's design direction rather than a separate
   one. **What the audit already measured, so it does not need re-running:**
   at 390px the tab bar is genuinely scrollable (`scrollWidth` 640 vs
   `clientWidth` 364) and `#notes-subtabs` likewise (591 vs 341) — both now
   at least *look* scrollable (`.edge-fade`, built this session), which is the
   affordance half, not the restructure half. The dashboard heatmap's
   apparently-off-canvas cells were chased down and are a **false positive**
   (a deliberately horizontally-scrolling widget, scrolled to today by
   design). Library, Chat and Graph reported clean at both 390px and 820px.
   So the remaining work is a genuine layout restructure on the surfaces that
   are merely *cramped* rather than broken — the 17-section Settings modal and
   the document editor being the two named candidates — not a bug hunt.

2. **Links in a note should show as a card, like an attached image or file.**
   Asked as a question: *"if the user adds links to notes in the capture tab,
   can they show as a card like an attached image or file at the bottom??"*
   **Read this before scoping it, because two different things are called a
   "link" here and only one of them is missing.** A `[[wiki link]]` to another
   note *already* renders as a clickable chip on the saved note
   (`renderNoteText`/`renderInlineMarkdown`, app.js) — that half exists and
   should not be rebuilt. What does not exist is a card for an **external
   URL**: paste `https://…` into a note and it renders as a plain inline
   link, with none of the treatment `#entry-attachment-chips` gives an
   attached file. The ask is for that shape — a card at the bottom of the
   note, beside the attachment chips. Open design questions, all real:
   whether the card is generated at save time or render time; whether it
   fetches anything (this app is **offline-first** — a card that needs a
   favicon or an OpenGraph title is a network call this project has spent
   real effort avoiding, so the honest default is a card built from the URL
   itself: host, path, and the link text the user typed); and whether
   removing the card removes the URL from the note's text, which is exactly
   the question `#entry-attachment-chips` already answered for images (it
   detaches the reference, it does not delete the upload) and should answer
   the same way for consistency.

3. ~~**The lightbox's bottom bar should do more.**~~ **Built** — a
   `.lightbox-actions` row: zoom out / a live % / zoom in / Fit, plus
   wheel-to-zoom (1x-6x), drag-to-pan once magnified, Copy text, and Save.
   Everything works off what `openLightbox` already receives, so it lights
   up for every caller rather than only the Library's richer items. The
   id-requiring actions below (describe with AI, re-run OCR, rename,
   delete) are the part **still open** — see the note at the end of this
   item. Original scoping kept:

3b. **The lightbox's bottom bar should do more.** Asked directly: *"can you
   improve on and expand the capabilities and features at the bottom of the
   lightbox?"* Not scoped this session. **What is there today**, so the next
   session starts from fact rather than the screenshot: `openLightbox`
   (app.js:2560) builds a `.lightbox-meta` line (filename, and "3 of 12" when
   there is more than one item) and a `.lightbox-info` panel below it holding
   four optional fields — `infoFacts` (dimensions, date added, filename),
   `infoCaption`, `infoText` (OCR), and `infoByline`. So it is already an
   *information* surface and has no *actions* at all: no download, no delete,
   no rename, no "describe with AI", no rotate, no zoom, no copy-text. The
   obvious move is that the five actions the gallery kebab already offers
   (rename, describe with AI, read text with AI, read text offline, delete)
   should be reachable from the lightbox too, since the lightbox is where you
   are actually *looking* at the picture — the same "the action belongs where
   the decision is made" reasoning that put the caption and OCR text there in
   the first place. **This half is what is still open**, and it needs one
   piece of plumbing first: no caller passes a media `id` to `openLightbox`
   today, so the Library caller (`library.js:1810`) has to start passing one
   and each action has to hide itself when it is absent — the same optional-
   field pattern `caption`/`text`/`byline` already use. Zoom and pan, the
   other half named here, are **built** (see above).

4. **Meeting notes need a real home.** Asked directly: *"the Meeting notes
   feature still needs a way to be accessed and better utilised as well as
   managed in the library as rn it is only accessible through the
   dashboard."* **Checked before scoping, and the premise is partly out of
   date — read this first.** Meetings are *already* a Library filter chip
   (`library.js:129`, `{ key: "meeting", icon: "ph:video-camera", label:
   "Meetings" }`) with a live count and a working filter, implemented as a
   tag filter over notes rather than a real kind (`libraryKind === "meeting"`
   filters `i.kind === "note" && tags.includes("meeting")`, library.js:372)
   — a meeting note is a finished note, unlike a draft, which is why it is a
   chip and not a sub-tab. Recording is also already reachable from the
   command palette (`ph:microphone Record a meeting or lecture`,
   app.js:16106), not only the Dashboard, and app.js:16101 carries a comment
   recording an earlier ask to expand that popup into a proper surface.
   So the genuine remaining work is **not** "add it to the Library" and
   **not** "add a second entry point" — both exist. It is the *"better
   utilised"* half, which is the unscoped one: what a meeting note should
   carry beyond a transcript (speakers, decisions, action items → reminders,
   a summary), and whether a meeting deserves to stop being a tagged note and
   become a first-class kind — which is a schema change with an Alembic
   migration behind it, and should be decided deliberately rather than
   drifted into. Scope that question first; the UI follows from the answer.

## §99 — the lightbox as a showcase, and uploads split by file type

Reported live across several messages. The lightbox half is **partly built**
(see HANDOVER.md); the upload half is **logged, not built**, and is the
larger piece.

### What was built

Built — the detail moved to [HISTORY.md](HISTORY.md) ("Retired from the live files, 2026-09-07"). Kept for its number.

### Still open — the upload split, and what it collides with

Asked for directly: *"there should be an upload documents option in the
documents tab in the library for uploading files pdf, docx, spreadsheet,
code documents, md, text files etc. all uploaded files get split based on
their filetype between the documents and image gallery tabs in the library,
and all documents should be viewable and editable in the documents area."*

**Read this before starting, because there is a real constraint in the way
and it is a security boundary, not an oversight.** There are two allowlists:

- `ATTACHMENT_SUFFIXES` (routes_files.py) is broad — pdf/docx/xlsx/csv/md/
  txt/code/zip. Attachments are **downloaded**, never served inline, and
  already reach `docview.extract` via `GET /files/{id}/text`.
- `MEDIA_SUFFIXES` is images + PDF only, and its comment explains why: that
  folder **is served**, and *"the AI can write into this folder too, so 'the
  only person who can put a file here is the person at the keyboard' is not
  true."* It is an allowlist precisely because a missed denylist entry there
  is a served-file problem.

So "all uploaded files go to /media and get split by type in the Library"
cannot be done by widening `MEDIA_SUFFIXES` — that would put .html, .svg and
friends in a served directory the AI can write to. The honest shapes are:

1. **Route by type at upload time**: an image goes to `media/` (served,
   narrow allowlist, unchanged), anything else goes to the attachment/
   uploads path (never served inline) and the Library lists both, reading
   documents through the text extractor. Most work, least risk, and it is
   the one that matches how the app already stores each kind.
2. Widen `MEDIA_SUFFIXES` and harden serving (explicit `Content-Type`,
   `Content-Disposition: attachment`, a sandboxed CSP on that route).
   Smaller diff, but it re-opens a question this codebase already closed
   deliberately — do not take this one without saying so out loud.

**"Editable in the documents area" needs its own decision first.** The
preview is read-only because the text is *extracted* — `core/docview.py`'s
own docstring makes the point that editing would mean writing text back into
a format it was never in. Editing a .docx in place is not a feature this app
can honestly offer. What it *can* offer, and what is probably meant: **import
the extracted text as a real MemoryMap document**, which is then editable
like any other, with the original file kept as the source. That is a
different feature from "edit the upload", and much more achievable — scope
it as import, not as in-place editing.

Also still open on the lightbox itself: the id-requiring actions (describe
with AI, re-run OCR, rename, delete), which need callers to pass a media id
— see §98 item 3.

## §101 — the knowledge graph should be second nature to the AI, everywhere

Asked for directly: the AI should be able to "flawlessly and instantly jump
between notes, know their link reasons, know the context between notes,
understand their meaning and purpose... at a relatively low cost," across
every AI feature and especially search — not a new capability so much as a
demand that an existing one stop being partial and optional.

**This is not a fresh ask — it is §87.5 and §88.4 items 3–5, restated as a
requirement rather than a nice-to-have, and worth reading in that order
before scoping anything new:**

~~- **§87.5 (live list, this file)** already scoped typed, weighted links
  (`EntryLink.link_type`/strength) as the mechanism for "know their link
  reasons"~~ **First slice built** — `link_strength()`, wired into both
  `entry/paths.py` and `graph_expansion()`. Still open: the composite over
  shared tags/category/temporal proximity (§87.5's own text has the full
  split of what's done vs. not).
- **§88.4 items 1–2 (ROADMAP.md)** are the reason "jump between notes" is
  already partly real: `graph_expansion()` walks linked neighbours of a
  chat/ask question's top hits and is wired into every retrieval call
  (`_retrieve()`) — not a special mode, the default path. **It now does
  weight *which* neighbour matters more** — §87.5's typed-link slice above,
  the two items being the same feature scoped from two different sides.
- **§88.4 item 3 ("memory is a surface, not a system")** is the "understand
  their meaning and purpose" half at the *notebook* level, not just per-note
  — no tiered always-on/retrieved/session-only memory exists anywhere in
  `ai/` today.
~~- **§88.4 item 4 ("no token accounting per stage")**~~ **Built** — the "at a
  relatively low cost" half, and was the *prerequisite* to anything else
  here, not an independent item. A per-stage token estimate (system/tool
  schemas/history/notes) is now attached to every turn's stats and shown in
  the chat metadata line's tooltip, so a graph-expanded, link-weighted
  retrieval pass's actual cost can now be read off directly, turn by turn,
  rather than needing new instrumentation first.

**Not re-scoped here, on purpose — the order has now run two of its three
steps.** Writing a second, parallel design for "AI-native graph navigation"
without first building §88.4 item 4's measurement would have repeated this
project's own standing caution (§88.4's closing note: "every one of these
becomes a change nobody can prove helped"). The order that respects what is
already true: instrument (item 4, done) → weight links (§87.5's explicit
slice, done) → **re-measure whether `graph_expansion`'s existing walk got
better — still open, and now the actual next step**, not §87.5's remaining
derived-signal composite and not a new mechanism beside the one that
already runs on every retrieval call. This sandbox has no reachable model,
so that re-measurement needs a real Ollama and cannot happen here.

## §102 — a live competitor read (Kortex, Granola, Mem.ai), audited before logging

This sandbox has working web access this session — earlier reads in this
project's history (§30, §59, §60, §88.2) were done blind, from supplied text
or with a network policy blocking outbound access. Asked directly to look at
Kortex, Granola and a "second-brain" app (Mem.ai — the most-cited product
making that exact claim) live and compare. A subagent did the web research;
**every finding it returned was then checked against this codebase before
being logged here**, per this file's own standing rule — two of its claims
were wrong and are corrected below rather than repeated. Kortex.co and
Granola.ai themselves were blocked by this sandbox's own egress proxy even
though general web search worked, so those two products are read from
reviews/docs pages, not a first-hand render — a real gap, not this session's
laziness.

**Corrected before logging — do not re-file these as gaps:**
- *"No way to scope a chat query to chosen notes"* — **false.** `note_ids`
  plus `attached_notes_only` (`routes_chat.py`) already do exactly this;
  `_attached_notes` already gates it through the same private-note check
  every other read path uses. The subagent's finding didn't check the
  running code, which is the exact trap CLAUDE.md warns about — recorded
  here so nobody re-runs into it from this angle.
- *"No import from other note apps"* — **overstated.** `POST
  /import/markdown` and `/import/directory` (`routes_settings.py`) already
  round-trip Obsidian-style frontmatter and import a whole folder tree.
  What's genuinely still missing is narrower: a Notion-specific importer
  (Notion's export is HTML+CSV by default, not the plain markdown this
  already reads) and any first-run *offer* to import during onboarding
  rather than a buried Settings action.

**Worth taking, ranked:**

1. **A live "rough bullets + transcript → merged note" capture flow**
   (Granola's core loop). Today's voice-memo/meeting path
   (`routes_voice.transcribe_meeting`) transcribes; nothing lets a person
   type short notes *during* the recording and then merges those bullets
   with the full transcript into one structured note afterward. Since
   transcription is already local, the merge step is a local-LLM prompt,
   not a new dependency — the more contained version of item 2 below.
2. **A structured summary block on a transcribed meeting** (decisions /
   action items / owner / date), extracted once after transcription.
   Checked: `transcribe_meeting` returns a transcript with no such
   extraction step today. Same shape as `caption_and_store`'s
   write-once-after-upload pattern.
3. **A persistent "related to this note" panel inside the note editor
   itself**, live while writing — not just the graph tab's link-suggestion
   flow, which is a separate mode a person has to go find. Cheap once
   scoped: the embedding-similarity query graph's own link-suggestion
   endpoint already runs already exists (`routes_entries.py` similarity
   scan); this would be a small, always-visible panel reading the same
   signal for whichever note is currently open.
4. **Typed note templates with a fixed field schema** (Sales Call, 1:1,
   Standup — Granola ships ~29), distinct from Skills (free-form saved
   *prompts*). A template would pre-structure a note's headings/fields
   before AI touches it, rather than the AI free-writing a whole note from
   a prompt. Needs a real schema decision (stored as structured `Entry`
   metadata vs. just a markdown skeleton) before building.
5. **A quick-capture popup from the system tray** — the tray already
   exists (`__main__.py`) with several nav items; a hotkey/click that opens
   a tiny always-on-top composer (title + body, Enter to save) without
   raising the full window is small, purely local, and matches a pattern
   several competitors treat as table stakes.
6. **Inline citations in chat answers that point back to a specific note**,
   clickable to jump there. MemoryMap's retrieval already knows which
   notes it drew on (`search_manager.retrieve_detailed`); what's unclear
   without a live model to check is whether the *rendered answer text*
   itself carries a per-claim link back to its source note, versus only a
   list of sources alongside the answer. Verify against a real chat turn
   before scoping further — may already be partially there.
7. **A dedicated, browsable highlights/clippings collection**, distinct
   from an ordinary note. Checked: `app.js`'s own comment names this "the
   capture surface half of BACKLOG.md §65 (highlight/web-clip capture)" —
   selecting text and capturing it as a note already works, but that
   capture becomes an ordinary note, not an entry in a separate,
   source-attributed quote library the way Kortex's is. Worth deciding
   whether that's a real gap or just a different (arguably more
   consistent-with-the-rest-of-the-app) design before building a second
   collection type.
8. **Basic local speaker separation on a transcript** (Speaker 1/2/3, no
   naming needed) — checked, genuinely absent (`grep -i speaker` across
   `src/` is empty). A fully local diarization pass, if the transcription
   library already in use supports one, would be a real, contained
   improvement over a flat transcript with no turn-taking structure.
9. **A live, inline organization suggestion while typing** (a tag/category
   chip appearing as you write), as an *optional* companion to — not a
   replacement for — the existing off-by-default, audited background
   auto-tag job. The batch job's conservatism (gated, logged, reviewable)
   is a deliberate design choice recorded elsewhere in this file and
   should stay the default; this would be an opt-in faster-feedback mode
   for someone who wants it.
10. **A one-click "synthesize these notes into a draft" action**
    (Kortex's "Blogger"): a named button in the graph/note UI that pulls a
    chosen set of linked/selected notes into a cohesive long-form outline
    or draft, distinct from a person hand-writing that prompt themselves
    in chat today. The re-paste of this same competitor research (a later
    session) named this one specifically as missing from the list above —
    correctly; it isn't covered by any of items 1–9. `expandNoteIntoDocument`
    (app.js) is the nearest existing thing and only ever takes *one* note.

**Out of scope, and why — not filed as gaps:** calendar-integrated
auto-join of video calls (needs a cloud calendar account or a bot joining
the call); shared/collaborative workspaces (needs a multi-user server,
against the single-user/no-sync design); native mobile companion apps kept
in sync (needs cloud sync or a self-hosted server); meeting-platform-specific
speaker-name capture via a browser extension (the local, nameless version is
item 8 above instead).

## §103 — reported live this session, and a batch of feature asks — logged, none built yet

1. **The Documents-list kebab menu reported visually broken, with a
   screenshot** (a teal-bordered box around "Preview" alone, then a
   separately-styled block for Rename/Download/Delete below it). **Not
   reproduced.** Tried live in this sandbox's Chromium: default light theme
   and dark mode (`applyThemeChoice('dark')`), both desktop (1400px) and
   phone (390px) width, on the exact menu the screenshot matches
   (`library.js`'s Documents sub-tab kebab, `wireEscapedActionMenu` —
   already reparented to `<body>` with a `position: fixed` placement
   computed from the opener's own rect). Every reproduction measured and
   screenshotted clean: one menu, one background, items evenly spaced, no
   overlap. One real but much smaller thing found along the way, not a
   match for the report: the escaped menu's background
   (`rgba(24,27,37,0.97)` in dark mode) is very slightly translucent, so a
   document row directly behind it is faintly visible through it — worth a
   fully-opaque background if this comes up again, but not what was
   photographed. The screenshot's teal accent and glassy look don't match
   this app's default palette, the same shape a prior session's Settings-
   modal-contrast report turned out to be ("the user's screenshots
   consistently show a custom teal accent, not the default indigo") —
   next report should include the browser/OS, whether a custom accent/
   glass setting is on, and the zoom level.
2. **The Library "All" tab needs more utility**, asked for broadly with
   several concrete examples worth splitting out:
   - **Tag management — rename, merge, browse.** `entry/manager.py` already
     has `rename_tag`/`delete_tag` (merge-by-rename: renaming to an
     existing tag's name merges into it) and `GET /tags` already returns
     every tag uncapped specifically so a management screen could reach all
     of them — but **no frontend "Tag Manager" screen calls any of this**
     (`grep -rn "Tag Manager\|renameTag" frontend/` is empty). The backend
     is the built half; the UI is the missing half.
   - **Click a tag to see every note carrying it — confirmed, partly
     built, from a different surface than asked about.** The dashboard's
     Tag Cloud widget (`renderTagCloudWidget`, `dashboard.js`) already does
     this: clicking a tag sets the Notes search box to the tag name,
     switches tabs, and filters. Real gap: it's a **text search** on the
     tag word, not a strict "notes tagged exactly X" filter (a note that
     merely mentions the word "work" in its body would also match), and
     it's reachable only from a Dashboard widget someone has to have
     added — not from the Library "All" tab's own tag chips, which is
     where this was actually asked about. The Library's `Tags 0` filter
     chip (seen in the Library toolbar) switches the grid to a *list of
     tags*, not straight to one tag's notes — confirm live before deciding
     whether that's the missing link or a third mechanism is needed.
   - ~~**Renaming a saved chat.**~~ **Already built — the prior session's
     own grep missed it because the function isn't named `renameConversation`.**
     The saved-chats list's kebab menu already has both "Rename" (a prompt
     dialog, `PUT /conversations/{id}`) and "Name with AI"
     (`POST /conversations/{id}/retitle`, `app.js` ~line 11252). Corrected
     here rather than left standing.
   - The broader "make more and easily access them" ask (drafts, chats,
     files, everything) needs a concrete list of what's missing per kind
     rather than one broad redesign — say what specifically, next time.
3. **Recording new meeting notes already works** (`openMeetingRecorder`,
   `Ctrl+Shift+R`). **Editing an existing one is unconfirmed** — a
   transcribed meeting presumably lands as an ordinary note or document,
   editable the normal way, but whether there's a dedicated "re-open this
   meeting" flow (re-transcribe, resume a paused recording, see the
   original audio again) was not checked this session. Scope by asking
   what "edit" should mean here before building anything.
4. **Whiteboard: curved lines and custom anchor points — partly built,
   asked for again without checking first (caught before repeating that
   mistake here).** A link already toggles straight vs. curved
   (`wbLinkPathD`, a symmetric cubic bezier through the midpoint — not a
   freeform curve), and objects already have **eight fixed** anchor points
   (corners + edge midpoints, `WB` link code, HANDOVER §53-55, "inspiration
   from draw.io") that a resize carries along for free. What's genuinely
   still open: an anchor point anywhere on an object's edge, not just the
   fixed eight, and interactively bending an existing link's curve (drag a
   control-point handle) rather than only the automatic symmetric bezier.
   A freeform curved *sketch* tool (not object-to-object links at all) is
   a separate, bigger ask — the sketch pad is pure-raster today (ROADMAP's
   own Tier 2 item 10 already names this as needing a real architecture
   change, not a small patch).
~~5. **Whiteboard: bring-to-front / send-to-back for a selection.**~~
   **Built.** Turned out cheaper than it looked: every item already had a
   `z` column, unused for anything but a fixed value set at creation, and
   the render code already painted from it (`.style("z-index", d => d.z)`,
   both cards' and objects' own merge) — so no schema change and no new
   render path, only the missing action. `wbSetZOrder(kind, item, toFront)`
   sets `z` to one past the current max/min among its layer's peers and
   saves via the existing PUT route, plugging into the existing undo stack
   as a "move" entry. Two new "Bring to Front"/"Send to Back" items in the
   right-click/long-press context menu, for a single selection or a whole
   multi-selection at once. **One real architectural limit, stated rather
   than hidden**: cards and objects share one HTML stacking context and
   interleave freely against each other; a sketch renders in a separate
   SVG layer underneath both, so it only ever reorders against other
   sketches — it can never be brought in front of a card. **Live-verified
   in Chromium**: two overlapping text objects created via the real API,
   the back one confirmed actually obscured (Playwright's own
   actionability check reported the front box "intercepts pointer
   events"), right-clicked → Bring to Front → the stacking visibly
   flipped, and the new `z` value survived a full page reload (read
   straight from `wbState` after a fresh navigation, not just checked
   in-memory).

## §105 — Library "All" tab: the create button now follows the filter chip, the rest is scoped not built

Asked for directly: the create button at the top of the Library "All" tab
should change based on the active filter chip — "Create Note" on Notes,
"Create/Upload Document" on Documents, "New Chat" on Chats, "Transcribe
Audio" on Meetings, and a general "Create +" picker modal on "Everything" —
plus more general capability to rename and create things (tags, categories,
chats) directly from the Library.

**Built:** the button now matches the active chip for the four kinds with
one unambiguous thing to create (Notes/Documents/Chats/Meetings —
`LIBRARY_CREATE_BY_KIND`, library.js). Verified live: switching chips
changes the label and the resulting action (Notes → Capture and focuses the
box; Documents → the existing new-document flow; Chats → a fresh
conversation; Meetings → the recorder). **Item 1 below is now also built**
(re-asked for directly in a later session): "Everything" and every other
ambiguous chip (Files, Tags, Drafts, Activity, the bin) now open a real
"What would you like to create?" modal (`openLibraryCreatePicker`,
library.js) instead of silently defaulting to "+ New note" — a full overlay
rather than a `kebabMenu()` dropdown, since the button isn't wrapped in
`.menu-wrap` and `.library-view-section`'s own scroll-clipping is exactly
the trap `wireEscapedActionMenu` exists to work around elsewhere; a modal
sidesteps both rather than fighting them. Live-verified: opens on the
default "Everything" chip, lists all four kinds plus Cancel, picking one
runs it and closes, Escape and backdrop-click both cancel.

**Not built — logged rather than rushed:**
1. **A "categories" section of the Library** doesn't exist —
   `LIBRARY_KINDS` (library.js) has note/document/chat/file/tag/draft/
   meeting, no category. Cheaper than it sounds: `PUT` and `DELETE
   /categories/{id}` already exist (routes_categories.py), and
   `renameCategory()` (app.js) already renames one from the Notes tab's own
   sidebar — reusable as-is, not built from scratch. "Create an empty
   category" has no real meaning today (a Category row is created
   on-demand the first time a note is filed into it — `get_or_create_category`,
   entry/manager.py); a Library category view would need to decide whether
   that stays true or an empty category becomes a first-class creatable
   thing.
2. **Renaming a tag "everywhere"** has no dedicated endpoint — tags are a
   JSON array on each `Entry`, not a table, so "rename this tag" today
   means editing it per-note. A real rename-everywhere action needs either
   a new endpoint that rewrites the tag across every entry carrying it, or
   a documented decision that it's out of scope and a tag is meant to be
   cheap to abandon and recreate rather than renamed in place.
3. **Creating a note/chat directly from the Library**, rather than jumping
   to the Notes/Chat tab. The create picker (built above) is the natural
   place to extend from — "type it right here" inside that same modal,
   rather than a separate affordance.

## §106 — Links, Contents and note References built; §102 items 5 and 6 checked, not built as originally scoped

Asked for directly, three things together: can notes/documents reference
each other with a References section; a place to store/bookmark website
links; a table-of-contents-style hyperlinked, visualised view of the
notebook's structure. Checked first, per this file's own standing rule —
`[[wiki links]]` already covered note-to-note linking with autocomplete,
transclusion and backlink chips (`app.js`, extensively) and the Graph tab
already visualises links coloured/filtered by category. What was genuinely
missing: anywhere to save a link to the open web, and a fast textual outline
distinct from the Graph's spatial one.

**Built:**
- **A `Bookmark` model and `/bookmarks` CRUD** (`core/database.py`,
  `api/routes_bookmarks.py`) — its own small table, not folded into `Entry`:
  a bookmark has no body to search, file, or auto-categorise, so forcing it
  through the note pipeline would solve a problem it doesn't have. URLs
  typed without a scheme ("example.com") are normalised to `https://`.
  Creating a URL that's already saved still creates the row and returns
  `duplicate_of` the existing one — warn, don't block, since re-saving a
  link by accident is normal, not a mistake worth refusing.
- **Grouping**, asked about directly ("should they be groupable?"): a free-
  text `group_name` column rather than a real folder table — a full nested-
  folder model (a tree table, drag-to-move UI) is a lot of new machinery for
  what a flat field mostly already buys. A "/" convention ("Work/Reading")
  the frontend renders as a visual hierarchy, still just one string. Filter
  chips above the list, a search box (client-side, matching the Image
  Gallery's own filter), pin-to-top, and edit/move/delete actions round out
  the Library → **Links** subtab.
- **A note's References**: a note can now attach a saved bookmark
  (`entry_bookmarks` join table, `POST/GET/DELETE /entries/{id}/bookmarks`),
  shown live in the edit form right below the related-notes panel, with an
  "Attach a link" picker. Its own small table and its own endpoint — not
  folded into `EntryLink` (which connects two `Entry` rows) or into
  `EntryOut`'s bulk-fetched `links` field, matching the precedent
  `/entries/{id}/related` already set: only the editor needs this, so it
  shouldn't grow a query on every paginated list render.
- **Library → Contents**: a hyperlinked outline of the notebook, grouped by
  category or by tag, click a note to jump straight to it. Built from
  `allEntries` (already loaded for the Notes tab) grouped client-side, not a
  new endpoint — refetched on every visit like every sibling Library subtab,
  not cached, since a stale outline (a just-deleted note still listed) would
  be a wrong answer, not just an old one. This is deliberately the *fast,
  scannable* half of "visualised links between sections and tags"; the
  *spatial* half is the Graph tab's job already, and Contents links out to
  it rather than duplicating a second visualisation engine.
- Live-verified in Chromium: add/pin/edit/group/delete a bookmark, filter by
  group and by search text, the duplicate-URL toast, both Contents modes
  grouping correctly and jumping to a note, and attaching/detaching a
  bookmark reference from a note's edit form — all measured, not assumed.
  One real bug caught this way and fixed before shipping: `ph-push-pin-fill`
  doesn't exist in this app's bundled Phosphor set (checked: only
  `push-pin`/`-slash`/`-simple`/`-simple-slash` do), so the pin button
  rendered blank — `-slash` for "already pinned" is the same pairing the
  pinned-chat button already uses.

**§102 item 5 (tray quick-capture), corrected rather than rebuilt:** the
tray's own "New note" item (`__main__.py`) already does the load-bearing
part of this ask — one click, past the lock screen, straight to a focused
empty note, no tab-hunting. What it does *not* do is the literal ask, "a
tiny always-on-top composer... without raising the full window" — it raises
the full window. Not built this session, and deliberately not attempted
blind: a real floating composer needs a second `pywebview` window (a new
`webview.create_window()` call, its own minimal page, its own focus/close
semantics coordinated with the main window's lock state and the existing
tray event-loop threading, which `_start_tray`'s own docstring already
flags as delicate). This sandbox has no Windows, no `pywebview` runtime, and
no display at all for this code path — confirmed live: importing `pystray`
here raises `Xlib.error.DisplayNameError` on this headless box, the exact
failure `_start_tray`'s own except-clause already anticipates. Writing a new
window-management code path with zero ability to launch or see it is how a
"small" feature ships broken; needs a real Windows session to build safely.

**§102 item 6 (inline chat citations), resolved — the answer was "no", found
by reading the code, not by needing a live model:** the retrieved notes sent
to the model are numbered in the prompt (`librarian.build_messages`, "1.
[category] ..."), but nothing in `GROUNDING` instructs the model to cite
that number, and the frontend's `#chat-results` list is a plain, separate
source list rendered alongside the answer — never parsed out of the answer
text itself. So: confirmed, not "unclear without a live model" any more —
there is no per-claim citation today, only a source list next to the
answer. Building real inline citations is a prompt-reliability question a
fake-transport test can't settle (would a small local model actually emit
`[1]`-style markers consistently enough to parse?) — left open for a
session with a live Ollama/LM Studio to validate against, per this
project's own standing caveat about model-behaviour work. **Not chat-
specific**, asked about directly afterward: search summaries and the weekly
digest ground their prose in the same retrieved-notes-numbered-in-the-
prompt shape `librarian.build_messages` uses, with the same absence of a
citation instruction — so this is one cross-cutting gap across every place
the AI writes prose from notes, not three separate ones.

**Bookmarks elsewhere, asked about directly:** *Documents* — **built**:
`DocumentBookmark` (same shape as `EntryBookmark`, keyed to `document_id`
instead of `entry_id`), `GET/POST/DELETE /documents/{id}/bookmarks`, and a
**References** section in the document editor's own Outline sidebar tab
(next to Backlinks/Notes it draws on), with the same "Attach a link" picker
notes got. Live-verified in Chromium: attach, the reference chip opens the
URL, detach, and the picker correctly lists every saved bookmark regardless
of which note or document (if any) already references it. *Graph* —
recommended **against** adding bookmarks as graph nodes: the Graph is built
around note-to-note similarity and typed links, and a bookmark has no
content to compare against anything, so it would be a node with different
semantics bolted onto a visualisation designed around one kind of thing. A
small "has references" indicator on a note's own graph node is a
reasonable, much smaller alternative if this is picked up later — not built
this session.

**The Library "All" tab's create/upload buttons — confirmed still covered
by §105, not missed.** §105 above already logs this in full: the button now
follows the active filter chip for the four unambiguous kinds
(Notes/Documents/Chats/Meetings), and §105 item 1 already names the
remaining gap precisely — a real "choose what to create" picker for
Everything and every kind with no single obvious answer (Files, Tags,
Drafts, Activity, the bin), not yet built, with the open question being
dropdown-off-the-button vs. a real modal. Nothing new to add here; re-
reading §105 rather than re-logging it.

**A second competitor-analysis pass (Kortex/Granola/Mem.ai) was re-pasted
this session, from a different subagent run than §102's** — cross-checked
against §102 rather than logged as new, since it is the same three products
against the same feature list and overlaps almost entirely:
- Its items 1–4, 6, 8–10 are §102's items 1, 3, 7, 6, 5, 9, 10 respectively
  — already logged there, unchanged.
- Its item 5 ("import from other note apps") and item 7 ("chat query
  scoping via explicit note selection") are the two claims §102 already
  checked against the running code and corrected — false/overstated, see
  §102's own "Corrected before logging" block. Restated here only so a
  future session doesn't re-file them from this second paste without
  noticing §102 already settled them.
- Its item 11 ("structured decisions/action-items block on meeting notes")
  is §102 item 2 — and item 2 is now **built** (this session, §25/§31 in
  the live task list): `librarian.summarize_meeting`, `POST
  /voice/summarize`, wired into `saveMeetingNote()`.
- Its item 12 ("speaker labeling on local transcripts") is §102 item 8,
  unchanged — still genuinely absent, still needs checking whether the
  transcription library in use supports local diarization at all before
  scoping further.

No new gaps in this second pass beyond what §102 already carries.

## §107 — a fast live-report round: nav-history contrast, Contents redesign, a bookmark-edit gap, and three items logged not built

**Fixed, live-verified:**
- **The nav-history popup was unreadable in dark mode** — reported directly.
  Reproduced (dark theme, 20+ stack entries): rows were cramped (`gap:
  0.15rem`) with small text, reading as garbled at a glance even though
  the computed colour itself (`#e7e9ee` on `rgba(24,27,37,0.97)`) was fine
  — this was a spacing/size problem, not a contrast one. `.nav-history-menu`
  and `.nav-history-item` now use the standard spacing tokens and
  `--text-md`/`line-height: 1.6`. Confirmed legible after.
- **Contents redesigned** — reported as "ugly." Was bare headings and a
  flat link list with no containment; now a card grid
  (`.contents-outline` → CSS grid, one bordered `.contents-section` card
  per group), matching the card language `.bookmark-row`/`.outline-link`
  already use elsewhere.
- **A bookmark's Edit action only ever touched its title, not the URL** —
  reported directly. Now prompts for both (two sequential dialogs, matching
  the group button's own one-dialog-per-property shape — `promptDialog`
  only ever takes one field, so a combined dialog would be new machinery
  for a two-field edit that happens rarely).

**Noticed while fixing the above, not chased further:** the nav-history
popup's own label for a Library sub-tab visit can show the raw internal id
("Library → library-view-contents") instead of a friendly name —
`entryLabel()` looks up `[data-section="..."]`, but Library's sub-tabs
carry `data-target`, not `data-section`. Pre-existing for every Library
sub-tab, not something this session's Links/Contents additions introduced;
cosmetic, not chased given the session's remaining budget.

**Asked about directly, logged rather than built this pass:**
1. **Whiteboard selection/move/copy UX** — "highlight and select stuff and
   move it... copy elements and move them other places or to other
   boards... the whiteboard controls still feel annoying to use." Not
   scoped or built this session — needs its own live audit of what
   `whiteboard.js`'s current select/drag code actually does before judging
   what's missing versus just rough, and copy-between-boards specifically
   is new surface (today's model is one board's own nodes/sketches/
   objects; moving one to a *different* board's own table is not
   something any existing endpoint does). A real "big feature" candidate
   for its own session, not a quick fix.
2. **The AI Skills tab's step/tool lists still read as unstyled** —
   reported directly, with a screenshot: numbered steps and the tool list
   render as plain paragraphs directly on the card background, with no
   visual container distinguishing them from the rest of the card (unlike
   the "N steps"/"N tools" chips above them, which are already styled).
   Not investigated or fixed this session — the markup/CSS for this
   specific sub-view wasn't located before the session's budget ran out;
   next session should grep `library.js` for the skill-card renderer
   (`renderSkillsDashboard` and neighbours) rather than re-diagnosing from
   scratch.
3. **Inline chat/search/digest citations, tray floating composer,
   templates, highlights collection, speaker diarization, live tag
   suggestions, one-click draft synthesis** — all still open exactly as
   §102/§106 already describe them; nothing new to add.
4. **Library's sub-tab bar asked to match Notes' own sub-tab styling —
   built.** Both shared the `.seg` base class, but only `.notes-subtabs`
   (05-sidebars-themes.css) layered the raised-card look on top of it
   (border, shadow, blur, sticky); `.library-subtabs`
   (07-whiteboard-misc.css) never got the same treatment and stayed the
   plainer generic pill. `.library-subtabs` now carries the same
   properties. Live-verified side-by-side in dark mode — matching now.

**Fixed in the same follow-up round, also live-verified:**
- **The nav-history popup's last row sat flush against the bottom edge**
  with no breathing room, unlike the clear gap above the first row — the
  container's own `padding-bottom` isn't reliably honoured past the end of
  a scrolled flex container's content in every engine. `.nav-history-item:
  last-child { margin-bottom: var(--space-2); }` is the robust fix.
- **Contents cards showed a stray horizontal scrollbar that cut off both a
  long filename and its hover highlight.** Only `overflow-y` was set on
  `.contents-list`, which — per the CSS spec's own computed-value rule for
  a box scrollable on one axis — silently turned `overflow-x` into `auto`
  too, so an unbroken filename with no wrap point forced the box wide
  instead of tall. Fixed with `overflow-x: hidden` plus
  `white-space: normal; overflow-wrap: anywhere` on the link itself, so a
  long name wraps onto a second line instead of forcing horizontal scroll.

**Reported, not reproduced — logged rather than guessed at:**
- **The back-to-top button reportedly appears on a page that isn't
  scrollable.** Read `scrollTopTargetEl()`/the `update()` loop
  (app.js, ~L15949-16069): each tab's scroll target is either a nested
  container (`NESTED_SCROLL_TABS`) or that tab's own `.tab-page` element
  via `scrollingPage()`, and the show/hide condition is a plain
  `scrollTop > 400` check — nothing in this path obviously explains a
  false positive on a page with too little content to scroll 400px in the
  first place. A live repro attempt (scripted scroll + tab switch) did not
  reproduce it, but the scroll-trigger method used was itself suspect (the
  button never showed even on a tab confirmed scrollable), so this is an
  inconclusive negative, not a clean bill of health. Needs a real repro —
  which tab specifically, and whether it's on first load or after
  switching from an already-scrolled tab — before attempting a fix.

**New feature request, logged only — not scoped or built:**
- **Highlighting text in notes and documents.** Asked for directly. Not
  investigated this session — needs its own pass to decide the storage
  shape (inline markup in the note/document's own text vs. a separate
  span-range table) and how it interacts with existing markdown rendering
  and the AI's own reading of note content, before scoping further.

## §108 — a fast bug-fix round: three real front-end bugs and a batch of small polish

**Fixed, all traced to a root cause rather than patched blind:**
- **Nav-history popup, genuinely broken this time** — reproduced: a
  history of short single-word entries (a plain tab visit, no sub-section)
  shrank the popup's fit-content width down to a narrow, sub-pixel value
  (164.34px measured), and text that narrow inside a `text-overflow:
  ellipsis` flex child rendered as illegible marks rather than real
  glyphs — confirmed clean again at both a wider `min-width` and a higher
  device-pixel-ratio, so this was the popup's own sizing, not a font/theme
  regression. `min-width: min(14rem, 90vw)` keeps it out of that zone
  regardless of how short any one entry's own label is.
- **`#search-help` and `#capture-help`** were bespoke hand-rolled click
  toggles from before `initHelpToggle` existed, never migrated — missing
  the outside-click and Escape closes every *other* help toggle in the app
  gets (reported: "the capture a thought tooltip doesn't close when
  clicking off it"), and `search-help-hint` also carried its own one-off
  `.search-help` class instead of the shared `.graph-help-panel` floating
  look `capture-help-hint` already had (reported separately as a style
  mismatch between the two). Both now go through `initHelpToggle`; live-
  verified open/outside-click-close and confirmed `search-help-hint`
  carries `.graph-help-panel` now.
- **The AI Skills tab's step/tool lists** — reported directly, with a
  screenshot: expanded, they read as plain paragraphs sat right on the
  card background. `.skill-fact-list` now gets a bordered/backgrounded box
  of its own (`--chip-bg`, `--radius-md`), the same card-on-card language
  `.contents-section` uses.
- **The Graph options row's toggles** (Similarity/Entities/Documents/Hide
  unlinked/Labels) were bare switches with muted text — hard to tell where
  one control ended and the next began, reported directly, with a request
  to match the Semantic toggle's own look. All five now also carry
  `.checkbox-label`, the shared pill-chip class that toggle already had —
  same fix applied to two more bare `.tools-toggle`s found the same way
  (Agent mode, Settings → Logs' "Follow").
- **The lightbox's document preview panel** was translucent (`var(--card)`,
  deliberately glass) sitting over the lightbox's own darkened backdrop —
  reported as "somewhat transparent". Switched to `var(--modal-bg)`, the
  same near-opaque token every other floating overlay already reads text
  against.
- **`.library-subtabs button` was more rounded than `.notes-subtabs
  button`** — traced to cascade order, not a missing class: a global
  "user-tunable corner rounding" rule (`.seg button`,
  04-chat-dock-appearance.css) sets a bigger radius and loads *before*
  `.notes-subtabs button`'s own explicit `--radius-md` override, so Notes
  wins on load order while Library's own button rule (added this session,
  07-whiteboard-misc.css) never set the property at all and inherited the
  bigger one by default. Now sets it explicitly too.

**Built, asked for directly:**
- **A "Clear" button for the AI Skills sidebar's own log list** —
  `DELETE /audit?entity_type=...` (`entity_type` required, so this can
  never be a way to wipe the *whole* audit trail — note edits/deletes are
  real accountability history, not a scrollback buffer — only the one
  filtered slice a caller names). The sidebar's sticky/full-height/
  internal-scroll behaviour itself was **already built** in an earlier
  stretch of this session (checked before touching anything, per this
  file's own standing rule) — only the clear action was actually missing.
- **Suggested-link reasons, the thing "Explain your existing links" was
  reported as not doing** (it never could — see that button's own long-
  standing comment) — a new "Suggest reasons" button next to it,
  `POST /entries/link-suggestions/reasons`, fills each pending suggestion's
  empty Why box with an AI guess (best-effort per pair, degrades to an
  empty list rather than an error when the model is down). Kept the
  original backfill button rather than replacing it — it's a real, working,
  separate capability (reasons for links that already exist) the ask
  didn't say to remove.

**Bookmark URL editing** — re-checked after being reported again: the fix
from earlier this session (`library.js`'s bookmark Edit action prompting
for both title and URL) is still present and correct on disk. If still
seeing title-only editing, it's very likely a stale cached `app.js`/
`library.js` — this project's own history names exactly that trap
(HANDOVER.md, "a static-file cache header that let the desktop app run
yesterday's app.js").

**Still open, unchanged from §106/§107:** whiteboard select/move/copy-
between-boards UX, a tray floating composer, inline chat/search/digest
citations — all need either a live model, a Windows environment, or their
own scoping session, none of which this one has.

## §109 — the measured bug round, the competitor gap list triaged, and what is genuinely still open

Three things in this section: bugs fixed this session **with the measurement
that proved each one** (not a reading of the source), the twelve-item
competitor gap analysis triaged against what this app already has, and a
brainstormed list of what is missing that nobody has asked for yet.

### 109.1 Fixed, and how each was actually proven

The theme of this round: **four separate reports were "already fixed" by the
source and still wrong on screen, and one was never a bug at all.** Reading
the code decided none of them. What decided them was measuring.

- **The nav-history popup, reported four times** ("garbled overlapping
  text", "completely broken", "still broken", with screenshots). Every
  earlier fix — spacing, a `min-width` floor, a last-row margin, moving it
  out of the status bar's `backdrop-filter` stacking context — was aimed at
  the wrong cause, and each one was "verified" by *looking at a screenshot*,
  which is exactly how four rounds got spent on it.

  The actual cause, found by decoding the screenshot PNG and reading raw
  pixel values instead of trusting my own eyes on it: `--modal-bg` is
  `rgba(…, 0.96)`, i.e. **4% see-through by design**. Over most backdrops
  that is invisible. Over the note editor — the densest block of small text
  in the app — 4% is enough for the labels underneath to survive as legible
  ghosting, and any screenshot pipeline that rescales or recompresses
  amplifies it further. Sampled down the popup's left padding column, the
  background read `(252,253,255)` at the top and `(244,246,253)` lower down:
  a real, measurable ~8-unit gradient that was the form showing through.

  Fix: a new `--modal-bg-opaque` token (alpha 1) used by `.nav-history-menu`.
  Re-sampled after: every point reads `(252,253,255)` exactly, uniformly.
  `--modal-bg` itself is left alone — its other callers (Settings, the
  command palette) float over much emptier backdrops.

  **And that was only half of it.** The popup was reported broken *again*
  after the opacity fix, with a dark-mode screenshot showing the rows as
  scattered dashes. That is the "illegible dashes" symptom an earlier
  stretch of this session wrote off as a screenshot/DPI capture artifact —
  **that conclusion was wrong, and writing it off is what let the bug
  survive several more rounds.** Measured this time instead of looked at:
  each row reported `scrollHeight` 35px inside a 32.36px box, so the
  `overflow: hidden` on `.nav-history-item` was slicing every glyph down to
  its top few pixels — which is precisely what "dashes" were. The rows are
  `<button>`s, and the app's generic button rule pins a fixed control
  height; the menu escaped that while it lived inside `#status-bar` (whose
  own `.status-item` rules won) and stopped escaping when it was moved out
  to the body earlier in this same round. Fixed with `height: auto;
  min-height: 0` plus flex centring; re-measured `clipped: false`, and the
  dark-mode render is clean and fully legible.

  Two independent bugs presenting as one complaint — which is why each
  individual fix "didn't work", and why the report kept coming back.

  **The transferable lesson, and it is the important part of this section:**
  a screenshot viewed by eye is not evidence at this precision. Both a human
  and a vision model will read faint luminance gradients as "ghost text" or
  fail to see a real 4% blend depending on scaling. `scratchpad/pngpixel.py`
  (a ~50-line pure-Python PNG reader, no dependencies) samples exact pixels
  and is the tool to reach for whenever a report is about transparency,
  contrast, or a colour looking wrong. For anything about text being cut
  off, the equivalent is comparing `scrollHeight` against `clientHeight`,
  which settles in one number what rounds of staring at screenshots could
  not. **Never close a visual report as "a capture artifact" without a
  measurement that says so.**

- **The AI Skills sidebar, reported three times** ("still doesn't float and
  stay 100% the height of the screen"). The sticking was never broken —
  measured: scrolling its container by 400px left it pinned at y=196.97
  exactly. **The height was wrong.** `max-height: var(--page-sticky-h)`
  resolved to 655px, but this sidebar's scrolling ancestor is
  `#library-view-skills`, a *nested* scroller only 534px tall, so the card
  ran 121px past its own viewport and 52px below the fold on an 800px
  screen. `--page-sticky-h` is the right figure only for a sidebar whose
  scroller is the page (`.doc-sidebar`, where the pattern was copied from).
  Fixed with `container-type: size` on the scroller and `max-height: 100cqh`
  on the sidebar; measured after: 534.2px, bottom at 731, still pinned.

- **The Graph options separator** clashing with the "All time" read-out —
  the divider `::before` set only `margin-inline-end`, so it had the parent
  gap on one side and gap+space-3 on the other. Now `margin-inline`.

- **No caption byline in the lightbox** — the Library tile has carried one
  since captions became hand-editable; only the lightbox was missing its
  half, so the same picture named its transcriber but not its describer.
  Added, mirroring `syncCaptionBadge` exactly.

- **The OCR text in the image gallery** is now clamped and expandable like
  the caption above it, for both the Tesseract and the vision-model field.

- **Bookmark URL editing — not a bug, and this is the third report of it.**
  Reproduced the whole flow live in Chromium this time rather than grepping
  again: Edit opens "Title:" prefilled, saving opens "URL:" prefilled,
  changing both persists, and a full page reload still shows the new title
  and the new URL. The code is correct and the behaviour is correct.
  Everything points at a stale cached `library.js` on the reporting machine
  — the trap HANDOVER.md already names. **If it is reported a fourth time,
  do not re-read the handler; get the served file's ETag and the browser's
  actual loaded copy and compare them.**

- **The nav-history popup "doesn't appear in the Documents tab"** — does not
  reproduce. Measured in both Notes and Library→Documents: visible, correct
  box, `elementFromPoint` at its centre lands inside the menu (so nothing is
  covering it), no page errors. Same stale-cache suspicion as above.

### 109.2 Text highlighting — built

Built — the detail moved to [HISTORY.md](HISTORY.md) ("Retired from the live files, 2026-09-07"). Kept for its number.

### 109.3 The competitor gap analysis, triaged

The twelve-item Kortex/Granola/Mem read was checked against the app rather
than filed as-is. **Six of the twelve are already built** — which is the
same ratio an earlier audit found, and the reason this project's standing
rule exists. Do not rebuild these:

| # | Gap | Status |
| --- | --- | --- |
| 2 | Persistent related-notes panel in the editor | **Built** — updates live while editing, not just on click |
| 6 | Inline citations in AI answers | **Built** — answers carry the notes they came from |
| 8 | Global quick-capture from the system tray | **Built** |
| 11 | Structured decisions/action-items block on meeting notes | **Built** — prepended automatically on save |
| 4 | Highlights/clippings library | **Partly** — Links (bookmarks) shipped this session; quote-level highlights are not a library yet, but `==highlight==` now exists as the capture syntax |
| 7 | Chat query scoping to selected notes | **Partly** — notes can be hand-attached to a chat turn; there is no "search only these" scope toggle |

Genuinely open, ranked by value-per-effort:

1. **Import from other note apps** (gap 5) — *the single biggest adoption
   blocker in the list.* A local-first tool cannot lean on a cloud migration
   service, so a folder of Markdown, a Notion export zip and an Obsidian
   vault all need a real importer: front-matter → tags, `[[wiki links]]` →
   real links, attachments copied in, and a dry-run preview before anything
   is written. Nothing here needs a model. Start with plain Markdown; Notion
   and Obsidian are the same importer with two front-matter dialects.
2. **Typed note templates with structured fields** (gap 3) — Skills are
   reusable *prompts*; this is a different thing: a category-bound field
   schema (decisions, owners, dates) that renders as a form and stores
   structured values. The meeting-summary block already proves the output
   shape is useful; this generalises it.
3. **Speaker labelling on transcripts** (gap 12) — transcription is already
   local, so "Speaker 1/2/3" by voice is an incremental local win. Named
   speakers need no platform integration if the user can rename a label once
   and have it stick for that recording.
4. **Rough notes + transcript merge** (gap 1) — the two-stage capture
   Granola is built around. Recording, transcription and the summary block
   all exist; what is missing is the *merge* of the user's own bullets with
   the transcript into one note, which is one more local-model pass.
5. **"Compose a document from these notes"** (gap 10) — the agent can
   already do it from a hand-written prompt; this is a button on a graph or
   list selection, not new capability.
6. **Live organise-suggestions while typing** (gap 9) — offer it *alongside*
   the audited background librarian, never replacing it. The gating and the
   audit log are deliberate and must survive.

### 109.4 Brainstormed — not asked for, worth doing

- **The selection popup in editors — decide, then build.** Reported twice as
  "the ellipse kebab button doesn't appear when I highlight things", and now
  partly explained rather than guessed at. On *rendered* content it works:
  driven live against `.entry-content`, the popup appears with the right
  text. It does not appear in the note editor, and that is deliberate —
  `SELECTION_POPUP_EXCLUDED` is `"input, textarea, [contenteditable],
  .selection-popup"`, and the editor is a `<textarea>`.

  So this is a design decision, not a bug fix, which is why it is logged
  rather than half-built: **should selecting text inside the editor offer
  the same actions as selecting it on a note card?** The argument for is
  that the editor is exactly where you would want highlight-with-colour,
  "extract this to its own note" and "link this to…". The argument against
  is that a popup over a live cursor fights normal text editing. A textarea
  can supply the selection via `selectionStart`/`selectionEnd`, so the
  capability is cheap once the decision is made; the awkward part is
  dismissal behaviour while typing continues. Whoever picks this up: get
  that decision from the user first. Beyond
  fixing whatever regressed, selecting text is the natural home for
  highlight-with-colour, "ask the AI about this", "extract to a new note"
  and "link this to…". Today selection offers nothing consistent.
- **Highlights as a queryable collection.** Once `==highlight==` is in use,
  "show me everything I highlighted this month" is a search-index question,
  not a schema question — the marks are already in `content`.
- **Backlinks panel.** The graph knows what links *to* a note; the note
  itself never shows it.
- **A conflict-safe editor.** Two windows on the same note silently
  last-write-wins today.
- **Search-result grouping by category/tag**, with counts — the result list
  is flat however many hit.
- **Export a single note or document** (Markdown/PDF). Backups export
  everything; there is no "send this one to someone".
- **A keyboard-shortcut sheet.** `Ctrl`+`K` exists, zoom exists, dictation
  exists; nothing lists them in one place.
- **Per-note pinned AI context** — a note that is always in scope for chat
  ("my current project"), rather than relying on retrieval to find it.
- **Bulk tag editing** from the notes list, with the same undo the rest of
  the app has.
- **A "why is this here?" affordance on graph edges** — the reasons exist;
  clicking an edge should show one.


## §110 — the toolbar round: formatting in Notes, and five more measured bugs

### 110.1 Built

Built — the detail moved to [HISTORY.md](HISTORY.md) ("Retired from the live files, 2026-09-07"). Kept for its number.

### 110.2 The five bugs, and the measurement that found each

- **Gallery kebab stayed open over the rename field.** The close-on-pick
  listener was on the bubble phase, with a comment explaining that each
  button's handler should run first — but every one of those handlers opens
  with `stopPropagation()` to keep the click off the tile beneath, so the
  click never reached the listener. Capture phase fixes it; closing the menu
  does not cancel the click still travelling to the button.
- **The graph dock's divider clashing with the time read-out**, reported
  twice and "fixed" once by reasoning. Measured: the group sat at exactly its
  300px `max-width` while the read-out's right edge was at 705px against a
  group edge of 698 — **the label had overflowed its own box by 7px** and
  landed 2px from the next group. A flex item's automatic minimum size is its
  content, so `min-width: 4rem` on the slider did not make it the thing that
  gave way. Now it is. Re-measured: no overflow, 10px to the divider.
- **Skill step numbers clipped against the panel border** — four reports,
  three of them "fixed" by changing padding. An `outside` `::marker` hangs
  into the padding by an amount CSS at this level cannot bound, so no padding
  value was ever going to settle it. The numbers are now real spans in a
  two-column grid gutter: they cannot overhang, and wrapped steps align under
  their own text rather than under the number.
- **The Regenerate-greeting button wrapping onto its own line.** The (usually
  empty) status span had `flex: 1 1 auto`, giving it a 178px content basis:
  256 + 205 + 178 + gaps = 663px against a 656px row. A zero basis lets it
  take only what is left.
- **Bookmark URL editing, reported five times, working every time it was
  tested.** The handler was correct and the flow was reproduced end to end —
  including persistence through a reload — on every check. The fault was
  never in the code; it was that a second modal appearing only *after* you
  commit the first is a bad way to expose a second field, and anything that
  interrupts between them (a stale script, an Escape, a mis-click) leaves the
  URL never asked for and looks exactly like "editing the URL is broken".
  Now one inline form with all three fields visible at once. Separately,
  **every local css/js URL is version-stamped** (`?v=<version>`, pinned by
  `tests/test_asset_cache_busting.py`) so a stale cached `library.js` cannot
  survive a release — this project's most-repeated false bug report.

### 110.3 Still open

- **Whether the selection popup should appear in the note editor at all** is
  now moot — it does. What is *not* settled is its dismissal behaviour while
  typing continues; it currently follows the same rules as on rendered
  content. Watch for reports of it getting in the way mid-sentence.
- Everything in §109.3 (the triaged competitor gaps — **six of the twelve
  were already built, check that table first**) and §109.4.
- Highlights as a queryable collection, backlinks panel, conflict-safe
  editor, per-note pinned AI context, bulk tag editing — all §109.4.

## §111 — where this app should go next, grounded in what the code actually does

Asked for directly: missing features, inefficiencies, and future directions.
Everything below was checked against the codebase rather than imagined, and
anything already built is named as such so nobody rebuilds it.

### 111.1 Inefficiencies, measured or read rather than guessed

- **The notes list has no virtualisation, and every render rebuilds it.**
  `loadEntries` pages at `ENTRIES_PAGE_SIZE = 1000` but loops until it has
  *all* entries, and `renderEntries()` opens with `list.replaceChildren()`
  and then builds a node per entry. This file's own comments talk about a
  75k-note notebook; at that size this is 75,000 DOM nodes rebuilt on every
  filter keystroke, tag toggle and save. **This is the single biggest
  scalability item in the frontend** and it is invisible until someone has a
  big notebook, because it is fine at a few hundred. Windowing the list (or
  rendering only the filtered slice plus a sentinel) is the fix; the
  server-side pagination it needs already exists.
- **`/entries/link-suggestions/reasons` is sequential.** Up to twelve model
  round-trips one after another in a threadpool endpoint. Concurrency would
  not help much — a single local model serialises anyway — so the honest
  lever was the count, now capped at 6 automatically with the button for the
  rest. Worth revisiting only if someone runs a server that batches.
- **Filing costs a model round-trip per capture** since the order was
  reversed. Now a preference (`ai_first_filing`), so this is a *choice*
  rather than a cost, but it is worth measuring on a slow model before
  assuming the default suits everyone.
- **Three places independently decide what markdown means**: `MD_ACTIONS`
  (toolbars), `INLINE_MD`/`INLINE_MD_LEGACY` (the renderer), and editor.js's
  "/" menu. The Red/Grey highlight bug (§110) lived precisely in the gap
  between two of them. `tests/test_highlight_colours.py` pins the colour
  lists, but the general fix is one grammar module the three consume.

### 111.2 Features worth building, ranked by value per unit of work

1. **Import from other note apps.** Still the biggest adoption blocker: a
   local-first tool cannot lean on a cloud migration service. A folder of
   Markdown first (front-matter → tags, `[[wiki links]]` → real links,
   attachments copied in, dry-run preview before anything is written);
   Notion and Obsidian are the same importer with different front-matter
   dialects. Needs no model at all.
2. **Backlinks on the note itself.** The graph already knows what links *to*
   a note; the note never shows it. Cheap, and it is half of what people mean
   by a connected notebook.
3. **Highlights as a queryable collection.** Now that `==highlight==` exists,
   "show me everything I highlighted this month" is a search-index question,
   not a schema one — the marks are already in `content`. This is also the
   honest version of the "clippings library" competitor gap (§109.3 item 4).
4. **Export a single note or document** (Markdown/PDF). Backups export
   everything; there is no "send this one to someone".
5. **Typed note templates with structured fields** — a category-bound schema
   (decisions, owners, dates) rendered as a form. The meeting-summary block
   already proves the output shape is useful; this generalises it. Skills are
   reusable *prompts*, which is a different thing.
6. **Bulk tag editing** from the notes list, with the same undo everything
   else has.
7. **A keyboard-shortcut sheet.** `Ctrl+K`, zoom, dictation and the "/" menu
   all exist and nothing lists them in one place.
8. **Per-note pinned AI context** — a note that is always in scope for chat
   ("my current project"), instead of relying on retrieval to find it.
9. **Speaker labelling on transcripts.** Transcription is already local, so
   "Speaker 1/2/3" by voice is incremental; letting a user rename a label
   once and having it stick for that recording covers the rest.
10. **A conflict-safe editor.** Two windows on the same note is silently
    last-write-wins today. Low frequency, high annoyance when it happens.

### 111.3 Directions, not features

- **Decide what the graph is *for*.** It is currently a picture plus a thing
  the AI can walk. The two uses pull in different directions — a human wants
  few, meaningful edges; retrieval wants many, weighted ones. Typed links and
  link strength (§87.5) are the lever, but the decision comes first.
- **The AI's honesty surface is the app's real differentiator.** Answers
  already carry the notes behind them and the librarian is audited and
  gated. Every future AI feature should be held to that bar — visible
  reasoning, an undo, and a log — rather than added as another silent
  automation.
- **Decide whether the note editor is a text box or an editor.** It now has
  a toolbar, a preview and a selection menu, while Documents has a full
  four-view editor. Either the composer stays deliberately small and defers
  to Documents for real writing, or the two converge. Drifting between the
  two is what produces a third dialect of markdown.

## §112 — the strategic pass: what would make this app hard to compete with

Asked for directly: *"brainstorm the future of development for the app in the
roadmap and backlog, what features are missing, what needs to be done, fixed,
refined, scaled, refined, optimised and more. how can we professionalise the app
further and make it stand out from competitors"* — alongside the standing
instruction to make it *"something that hasn't been done before"* and *"valuable
that users would be willing to pay for"*.

§111 above is the previous pass and is still the honest inventory of
inefficiencies; this one is about **positioning**, and every claim here was
checked against the code rather than imagined.

### 112.1 The one thing this app has that the others structurally cannot

Every competitor in this category is either cloud-first with AI (Notion AI, Mem,
Reflect, Tana, NotebookLM, Saner) or local-first without it (Obsidian, Logseq,
Anytype, Zettlr). The first group cannot promise privacy because the model is
somebody else's server; the second cannot promise intelligence because there is
nothing to ask. **MemoryMap is local-first *and* has a model**, and that is not a
feature list — it is a category of its own, and almost nothing in the product
currently *says* so.

The strategic mistake to avoid is competing on features the cloud tools will
always win (polish at scale, mobile, real-time collaboration). The strategic
opening is everything that is only possible when the model is on the same
machine as the data:

- **It can read everything, not a retrieved sample.** A cloud tool meters
  tokens, so it retrieves five notes and hopes. A local model costs only time,
  so a *slow, thorough* pass over the whole notebook is affordable — overnight,
  or while the laptop charges. `ai/autonomous.py` already has the scheduler for
  this; what is missing is the framing: "MemoryMap read your whole notebook last
  night, here is what it noticed."
- **It can be wrong safely.** Nothing leaves the machine, so a speculative
  suggestion costs nothing but a dismissal. That is why `tensions.py` (finding
  contradictions between notes) is a *better* fit here than anywhere else.
- **It works with no network at all.** Already true and almost never said. The
  `notebook_stats` work in this session is the shape to repeat: a question
  answered exactly, instantly, with the model stopped.

**Action:** the product should say this. An honest, visible "what ran, on what,
and what left this machine (nothing)" surface is worth more than three features.
Some of it exists (`AuditLog`, Settings → Privacy); none of it is a headline.

### 112.2 Missing features, ranked by "would someone pay for this"

Ranked by the gap between what it costs to build and what it would be worth.

1. **Import from other note apps** — still, and it is still first. A local-first
   tool cannot lean on a cloud migration service, and until this exists nobody
   with an existing notebook can *try* the app properly. Markdown folder first
   (front-matter → tags, `[[wiki links]]` → real links, attachments copied in, a
   dry-run preview); Obsidian and Notion exports are the same importer with
   different front-matter dialects. **Needs no model.** Carried from §111.2 item
   1 unchanged because it has not been done and nothing has displaced it.
2. **The nightly pass, as a product surface.** `ai/autonomous.py` exists and
   `tensions.py` exists. What does not exist is the morning artefact: *one card*
   that says what the model did overnight — new links it proposes, contradictions
   it found, notes it thinks are stale, questions it thinks are unanswered — each
   accept/dismissable. This is the single most differentiated thing on this list
   and most of the machinery is already written.
3. **Backlinks on the note itself.** The graph knows what links *to* a note and
   the note never shows it. Half of what people mean by "connected notebook",
   and cheap. (§111.2 item 2, still not done.)
4. **Ask the notebook about itself, generally.** `ai/notebook_stats.py` (this
   session) answers tags/categories/counts/links/timing exactly, with no model.
   The pattern generalises: "which notes have I not touched in a year", "what did
   I write about most in March", "which tags always appear together". Each is a
   query, not a generation — exact, instant, and impossible to hallucinate. **A
   competitor with a cloud model literally cannot make these fast or free.**
5. **Export one note or document** (Markdown/PDF). Backups export everything;
   there is no "send this one to someone". Trivial, and it is the difference
   between a private tool and a tool you can work with other people through.
6. **Typed templates with structured fields** — a category-bound schema
   (decision / owner / due) rendered as a form, queryable afterwards. Tana's
   whole proposition, achievable here because the data is local and the schema
   can be a preference rather than a migration.
7. **A keyboard-shortcut sheet.** `Ctrl+K`, zoom, dictation and the "/" menu all
   exist and nothing lists them anywhere. Ten minutes of work; it is the
   difference between "has shortcuts" and "feels professional".
8. **Per-note pinned AI context** — "always consider this note", instead of
   hoping retrieval finds it. One preference, one prompt slot.
9. **Highlights as a queryable collection.** `==highlight==` already parses;
   "everything I highlighted this month" is a search-index question.
10. **A conflict-safe editor.** Two windows on one note is last-write-wins.
    Rare, and infuriating exactly once.

### 112.3 Scaling and optimisation, in the order it will actually bite

- **The notes list still has no virtualisation** (§111.1, unchanged). `renderEntries()`
  rebuilds a node per entry on every keystroke. Fine at 500 notes, unusable at
  50,000, and invisible until someone has the second one. **This is the largest
  scalability item in the app** and the server-side pagination it needs already
  exists.
- **`frontend/app.js` is past 30,000 lines.** The four splits (`library.js`,
  `dashboard.js`, `settings.js`, `documents.js`) worked and stopped. The next
  natural seams are chat (~6k lines), the lightbox (~1.2k) and the notifications
  centre. Each is a session's work and each makes the next bug cheaper to find.
- **Three grammars for markdown** (§111.1). `MD_ACTIONS`, `INLINE_MD`, and
  editor.js's "/" menu each decide independently what the syntax means. Every
  bug in the gap between them has been a real reported bug. One module.
- **The suite is 2,700 tests and ~8 minutes.** Still fine; worth watching. The
  lints (`test_style_scale`, `test_frontend_ids`, `test_icon_only_buttons`,
  `test_icon_label_gap`) are the cheapest tests in the file and have caught the
  most — that ratio is an argument for more of them, not fewer.
- **Embeddings are optional and the fallback is silent.** Semantic search
  degrades to keywords with no model; the app should *say* which one answered.
  It is a one-line badge and it is the difference between "the search is bad"
  and "the search is in keyword mode".

### 112.4 What "professionalise" actually means here

Not more features. Four things, in order:

1. **Nothing that is broken.** This session alone found a null dereference that
   silently aborted `openConversation`, a panel that opened five pixels below the
   fold, a checkbox no click could reach, an OCR result thrown away on close, and
   a restore that destroyed the version it was restoring. Every one was invisible
   from reading the code and obvious within a minute of driving the app. **The
   discipline that finds these — reproduce, measure, then fix — is worth more
   than any roadmap item**, and the two new lint files exist to stop that class
   of thing recurring.
2. **One shape for one thing.** Two ⋯ builders drew different glyphs; two Stop
   buttons used different icons; the same setting had two controls that could
   disagree. Each is small; together they are what makes an app feel homemade.
   `test_icon_only_buttons.py` and `test_icon_label_gap.py` are the start of
   mechanising this — more of the design system belongs in lints.
3. **Say what the app is doing.** Background tasks, page reads, captions and the
   nightly pass all now report themselves. The remaining gap is *what the AI
   did*, kept where a person can audit it: the AI edit log is per-document, and
   there is no notebook-wide "what has the model changed" view.
4. **A first run that explains itself.** The onboarding overlay exists. What
   does not exist is the answer to "I have 4,000 notes in Obsidian, now what" —
   which is item 1 of §112.2 again, and the reason it stays first.

### 112.5 Deliberately not doing

Written down so a later session does not spend a week rediscovering why.

- **Mobile apps and sync.** The offline, single-machine promise is the product.
  Sync is a distributed-systems project that would compromise it, and the export
  and file-tree work already covers "get my data onto another machine".
- **Real-time collaboration.** Same reason, more so.
- **A plugin marketplace.** The skills library covers reusable prompts; arbitrary
  third-party code in a privacy-first app is a contradiction, not a feature.
- **Chasing Notion's block editor.** Documents has four views and a real
  toolbar. Deciding *whether the note composer converges with it* (§111.3) is
  the open question; rebuilding Notion is not.

## §116 — capability gaps identified in the Fable session

Everything here was found while working the plans — by measuring the running
app, by reading a subagent's diff, or by an item a subagent had to drop. Each
line says where it came from so the next session does not re-derive it. Items
already in [PLAN.md](PLAN.md) are referenced by their row id rather than
restated.

### 116.1 Dropped or half-done, and therefore first

1. **Unlink uploads when a map's entry is purged.** Backend sprint 2's third
   item; the agent backed it out as a mindmap dependency. A purged board
   `Entry` leaves its objects' image files on disk. `entry/manager.py`'s purge
   path plus a test that counts files in `uploads/` before and after.
2. **The Health block shows no latency.** `GET /debug/health` returns
   `latency_ms_by_kind` (p50/p95/count per task kind); Settings → About draws
   size, counts, jobs and the last error and not that row. One more
   `.setting-row`, filled by `renderHealthBlock`.
3. **A phone pass on the other four tabs.** Only Notes, Chat and Settings were
   measured at 390px. Library (the boards landing's head row, the docs list),
   Graph (the toolbar), Whiteboard (the top bar, the properties panel) and the
   documents editor (`.doc-dock`) have not been. `errors.js` at 390 is the
   gate; `phone*.js` in the session scratchpad are the probes.
4. **A dark-theme pixel pass.** Every new surface this session (the popover
   shell, the Filters sheet, map nodes, the Health block) was measured in
   light only. `THEME=dark` is honoured by `lib.js`; `scratchpad/pngpixel.py`
   is the tool; the bar is 4.5:1 for text.
5. **Real-model verification of the skills reform** — still the open
   acceptance criterion in AGENT_SKILLS_REFORM.md; needs a machine with a
   4B model, not the sandbox.

### 116.2 Mindmaps, Phases 4-5 (MINDMAP_PLAN.md §5 items 14-21)

6. **FreeMind `.mm` import and export** (item 16/17) — OPML and Markdown
   exist; `.mm` is the third interchange format and the one XMind and
   Freeplane speak natively. Same `_parse_opml`/`export` shape, defusedxml.
7. **"Make a map of these notes"** (item 15) as a first-class action: the
   tools exist (`create_mindmap`, `add_map_node`); what is missing is the
   entry point (a selection in Notes → "Map these", a chat suggestion chip)
   and the accept/edit step before anything is written.
8. **Focus mode, filter/perspective, metrics, templates** (items 18-21).
   Templates first — an empty map is the reason the feature goes unused;
   `createNewBoard` already seeds one root, so a template is "seed these
   nodes" through the same `POST /nodes` calls.
9. **Layout performance at scale** (§8 risk): build a 500-node map with the
   API in a script and time `wbMapTidy` and first paint. Argued linear,
   never measured.
10. **Cross-links need a gesture.** The dashed rendering exists and the tree
    endpoint reports them; nothing in the UI *draws* one between two map
    nodes except the generic link sketch tool. A "link to…" on the selected
    node, reusing the reference picker Phase 3 adds.

### 116.3 PLAN.md rows not started (by track)

11. **Whiteboard** — W1 group resize, W2 smart connectors, W3 sticky notes,
    W4 frames, W6's flip keys, W7 undo that survives reload, W8 minimap in
    fullscreen, W9 touch/pen, W10 selection export, W11 AI on the board.
    W5 and `[`/`]` were already built (found by grep before building).
12. **Documents** — D4 tables, D6 outline drag-to-reorder, D7 callouts/
    footnotes/math, D8 revision UI, D9 focus mode, D11 AI edit with a diff
    preview. D10 (templates) exists (`{{date}}`/`{{title}}` in
    documents.js) — do not rebuild.
13. **Backend** — B1 one file model, B2 the job queue, B6 migration check,
    B7 workspace scoping as a dependency, B8 backups as a product feature.
    B4/B5: `/entries` pagination and FTS5 for notes already exist
    (MODERNISATION_AUDIT.md §D6); the open half is the *other* lists.
14. **Harness** — A3 memory with provenance, A4 skills as files, A5 budgets
    and a Stop that cancels, A7 MCP in and out.

### 116.4 Tooling

15. **One launcher per agent.** `scratchpad/ui-sweeps/serve.sh PORT DIR`
    starts a server with its own data dir and log, so two servers can never
    share a SQLite file again (HANDOVER.md, "Traps found this session").
    Every brief to a subagent should name a port and use it.
16. **A phone run and a dark run of `all.sh`.** `all.sh` sweeps 1440/1024
    light. Add `WIDTH=390` and `THEME=dark` passes so 116.3 and 116.4 have
    a gate rather than a probe.

