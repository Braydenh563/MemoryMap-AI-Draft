# The redesign: making this feel like an application

> **Superseded.** Kept because code comments and HISTORY.md cite its sections. Its open items live in [UI_MODERNISATION_PLAN.md](UI_MODERNISATION_PLAN.md) and [WORLD_CLASS_PLAN.md](WORLD_CLASS_PLAN.md) §1 and §7. Do not start work from this file.

> *"the app is really glitchy, it feels fake and unprofessional but I cant
> place it… it still feels like a beta and not an actual professionally
> designed and usable application. it feels like it will break any second…
> a lot of the ui elements arent adaptive either, they feel very rudimentary
> and just chucked together with no thought for actual responsive design."*
>
> *"I feel like I cant even use my application as a user and that it is just a
> cool app that has features, but what use are they if the features are hard
> or annoying to use, or if half the screen is taken up by poor ui choices or
> structuring."*

This file is the plan that came out of taking that seriously. It is the
fifth roadmap file — see [ROADMAP.md](../ROADMAP.md),
[BACKLOG.md](BACKLOG.md), [ANALYSIS.md](ANALYSIS.md),
[HISTORY.md](HISTORY.md), [HANDOVER.md](HANDOVER.md).

**Everything in §R1 was measured in a running Chromium against a real
server, not reasoned about.** That matters because the complaint is
*"I can't place it"* — a feeling with no named cause is exactly the thing
that gets answered with a plausible guess and a cosmetic fix. Numbers name
the cause.

---

## R1. What is actually wrong, measured

Seeded with ten notes, a 1440×900 viewport, default theme, fresh profile.

### R1.1 The app is laid out as a web page, not as an application

| What | Measured | What it should be |
| --- | ---: | --- |
| Notes visible in a 900px viewport | **5** | 15–20 |
| Note card height for two lines of text | **121px** | ~44–64px |
| Note card width | **1037px** | 60–75 characters (~640px) |
| Categories sidebar | 260 × 755px holding **three rows** (~110px used) | either dense and useful, or narrower |
| `#entry-list` height inside a 755px `main` | **1248px** | the pane scrolls, not the page |
| Library chrome above the first item | **344px** across four stacked control rows | one row |
| Side gutter at 1024 / 1440 / 1920 | **32px at all three** — a step function, not a response | continuous |
| Category sidebar at 820px wide | **260px, unchanged from 1920** — 32% of the window | proportional |

The last two are the structural ones and everything else follows from them.

**Panes do scroll — that part of the shell is already right.** Measured
after the first draft of this file said otherwise, and the correction is
worth keeping: `document.documentElement` never overflows, and the scroller
is `MAIN` on Notes and `.tab-page` on Timeline and the Dashboard. What is
missing from the shell is not scrolling but *structure* — per-pane history,
more than one pane at a time, and a left rail (§R3.1) — so the work in §R6
item 6 stands, with one less thing to fix.

**Chrome stacks instead of collapsing.** The Library screen draws, top to
bottom: the app tab bar, the Library sub-tab bar, a title row with two
buttons, a row of six stat pills, a row with search + two toggles + a
four-way sort + a view switcher + a filter select, and *then* a row of nine
filter chips. Every one of those is a defensible feature. Together they are
340px — over a third of the viewport — before the first thing the user came
to look at. This is the literal referent of *"half the screen is taken up by
poor ui choices or structuring."*

**Navigation is duplicated three times on one screen.** The Dashboard shows
the top tab bar, a "START SOMETHING" row of five action cards, and a "JUMP
TO" row of eight chips that name *the same seven tabs as the tab bar*. Three
ways to reach the same places, none of them the obvious one.

### R1.2 Files were a dead end, not just ugly

Reported as *"the integration of pdfs and other files is completely broken
and unusable"* and then, more precisely: *"once I uploaded two files into a
note, they became hyperlinked text, I clicked on them, and it took me to a
black fode screen with some text about needing to unlock first… there was no
way for me to go back except for closing the application entirely."*

Reproduced exactly. Three separate defects wearing one complaint:

1. **Two parallel file systems that do not know about each other.**
   `MediaUpload` (`POST /media/upload`) returns a URL that
   `handleFileUpload` pastes into the note as raw markdown — no record on
   the note, no card, no remove. `Attachment` (`POST /entries/{id}/files`)
   creates a real row that renders as a card with a delete button — but it
   needs a note id, so it is unreachable from the composer, which is where
   people attach things.
2. **The link navigated out of the app.** `renderInlineMarkdown` emitted
   `<a href="/media/x.pdf">`. A plain navigation carries no `X-Auth-Token`
   header, so the browser left the SPA, received the unlock guard's 401 JSON
   body, and rendered it with its own JSON viewer — the "black screen with
   the pretty print toggle." The desktop shell has no back button, so the
   only exit was quitting the app.
3. **The file then appeared nowhere.** The Library's gallery rendered
   *every* upload as `<img src="/media/…">`. A PDF failed to decode, the
   `error` handler fired, and **the tile removed itself** — silently, with
   no message, from the only screen that lists uploads. The file was on disk
   and in the database the whole time.

**Fixed and verified live** (commit "Files stop being a dead end…"): file
cards with icon/name/type/Save that open the in-app document viewer, a
matching strip in the composer rendered from the note's own markdown, real
tiles for non-images, and the sub-tab renamed to "Files & Images". Zero
`/media/` anchors remain in a rendered note.

**The important lesson for whoever picks this up:** the viewer already
existed. `openLightbox` already sniffs a non-image `/media/…` URL and hands
it to a document reader that renders PDFs, Office files, code and plain text
through `/media/text`, with find-in-document. It was reachable from the
Library and from the Documents list and *from nowhere in a note*. The bug
was a missing wire, not a missing feature — which is this project's most
common shape and the reason CLAUDE.md opens with "check the running app
first."

### R1.3 Saving a note made you wait for the AI

> *"the making of new notes was slow and annoying, I feel like the note
> panels should disappear while filing and continuing in the backend with a
> popup notification so I dont have to wait twiddling my thumbs for it to
> file."*

`POST /entries` ran `janitor.categorise` inline — a local-model round trip —
with the composer disabled behind "Filing…". Two more slow things were in
the same request: embedding the note, and a full semantic search run only to
*maybe* show an advisory "this is similar to…" toast.

**Fixed and verified: 971ms → 32ms** on the save round trip, measured in this
sandbox with no model running at all. On a machine actually running a small
local model the old path was seconds. The note now shows a "Filing…" chip
until the background pass lands, then a notification says where it went.

### R1.4 Spaces leaked

> *"I made a new separate space for a uni class, and the pictures and images
> I had from the main area of all spaces were showing in my image gallery??"*

Reproduced in one request pair: a file uploaded with `X-Workspace-ID: uni`
was returned by `GET /media` under `X-Workspace-ID: default`. Cause:
`MediaUpload`, `Reminder`, `Attachment`, `WhiteboardNode`,
`WhiteboardSketch` and `WhiteboardObject` never carried `WorkspaceMixin`, so
the scoping hooks in `core/database.py` skipped them entirely. Notes were
correctly scoped the whole time, which is why this looked like a gallery bug
rather than a data-model one.

**Fixed and verified.** The backfill inherits each child row's space from
its parent note rather than defaulting it — defaulting an attachment would
have filtered it out of *its own note*, which reads as data loss.

### R1.5 The graph is the wrong tool for what it is being asked to do

> *"I wanted to use it as a mindmap where I make a node which is like a core
> idea, with other sub ideas that branch off with notes attached to them."*
> *"the way connections are made feels more annoying and manual."*

This is not a polish problem. The graph view is a **derived** view: nodes
are notes, edges are links the AI proposed or the user confirmed, and the
layout is a d3 force simulation that decides where things go. What is being
asked for is an **authored** view: the user places a core idea, branches
sub-ideas off it, drags them where they want them, and the positions *stay*.

Those are different data models with opposite ownership of position and
structure, and trying to serve both from one screen is why it "misses the
mark". The derived graph is genuinely good at what it is for — *"the other
graph views are decent visually"* — and should keep being that. The mindmap
is a new thing. See §R4.

### R1.6 Uploads that are not images or PDFs are refused outright

`MEDIA_SUFFIXES` accepts nine image types and `.pdf`. `handleFileUpload`
offers the server everything matching `application/*`, `text/*`, `video/*`
and `audio/*`. So dropping a `.docx`, a `.txt` or a code file into the
composer produces a 415 and a red toast, while the *same file* attaches
fine to an already-saved note through `ATTACHMENT_SUFFIXES`, which allows
about sixty types.

The allowlist is not paranoia — `/media/{name}` serves inline from the app's
own origin, so an `.html` or `.svg` landing there is stored XSS, and the AI
can write into that folder too. The fix is not to widen it. See §R3.2.

---

## R2. The diagnosis

Every symptom above is one of three underlying causes. Naming them is the
point of this section, because *"it feels like it will break any second"* is
a real signal and it has real referents.

**C1 — There is no application shell.** The app is a page with a header and
a footer. Panes cannot scroll independently, nothing can be pinned, and
every screen re-solves layout for itself. This causes R1.1 entirely, and
makes every future screen cost more than it should.

**C2 — Features were added beside each other rather than into each other.**
Two file systems (R1.2), two "where do my uploads live" answers, three
navigations to the same seven tabs, a Library that grew a control row per
capability. Nothing was wrong when it was added; nothing was ever merged
afterwards. This is what "chucked together" is describing, and it is
accurate.

**C3 — The interface reports the machine's state instead of getting out of
the way.** "Filing…" with a disabled form (R1.3) is the app telling you
about its own internals while you wait. A confidence percentage on every
card is the same instinct. The fix is not to hide the information — it is to
stop making the user wait for it.

---

## R3. The target shape

The reference the user named is **Kortex**, alongside Obsidian, and the
screenshots supplied show a shape worth copying deliberately. *(Studied from
the supplied screenshots. The linked Vimeo walkthrough was not watched — I
cannot play video — so anything below that is not visible in a still is
marked as an inference.)*

### R3.1 The shell

```
┌───────────────┬──────────────────────────────┬─────────────────────┐
│ Search   ⌘K   │  ← →  Library / Sources / …  │ ← →  New Chat   ✕   │
│ Chat          │                              │                     │
│ Library       │  ┌────────────────────────┐  │  (chat, or a second │
│ Shared        │  │  the thing itself,     │  │   document, or the  │
│               │  │  one narrow column     │  │   connections pane) │
│ FAVORITES     │  │                        │  │                     │
│  ▸ …          │  └────────────────────────┘  │                     │
│ DOCUMENTS     │                              │                     │
│  ▾ Books      │                              │                     │
│    ▸ Purpose  │                              │                     │
└───────────────┴──────────────────────────────┴─────────────────────┘
```

What each part earns:

- **A left rail instead of a top tab bar.** Kortex has no top tabs at all.
  Destinations are a short list at the top of the rail; everything below is
  *the user's own content* as a tree. MemoryMap's seven top tabs plus seven
  Library sub-tabs plus four Notes sub-tabs is three levels of tab bar for
  what is one hierarchy.
- **Per-pane back/forward and breadcrumbs.** Each pane owns its own history
  (`← → Newsletters / … / February 2025 / Dead Internet Theory`). MemoryMap
  has one global nav-history popup for the whole app — which is why it has
  been reported and re-reported: it is trying to be per-pane history in a
  single-pane app.
- **Independently scrolling panes.** The direct fix for C1.
- **A narrow measure for prose.** Kortex's document column is roughly 700px
  in a 1460px window. MemoryMap's note cards are 1037px wide.
- **Dark, low-chroma chrome; content is the only bright thing.** MemoryMap's
  default light theme paints a lilac gradient across the whole background
  behind translucent cards. It is pretty in a screenshot and it is why
  nothing reads as foreground.

### R3.2 Documents, files and "elements"

> *"look at how the odysseus documents feature works, you can import, edit
> and create multiple file types, there are options for code lines, viewing
> html and other code, rendering pdfs, exporting, allowing the ai to read
> the documents, able to highlight text and say something in the chat and
> the agent gets the context of what is highlighted and cursor position."*
>
> *"I really like kortex's use of backlinking and elements for structured
> documents as well."*

Both references point at the same thing from different sides: **a document
should be made of typed, addressable blocks, not one flat string.**

Kortex's screenshots show collapsible typed blocks inside a document —
`Connections`, `Research`, `Brain Dump`, `Batch`, `Post`, `Subdocuments`,
`Tags`, `Captures` — nestable, each with an icon and a disclosure triangle,
created from a `/new` palette (`New Group`, `New Element`, `New Source`,
`New Author`). Backlinks appear as a `Connections` block listing linked
documents with direction arrows (↗ outgoing, ↙ incoming).

Odysseus's `static/js/document.js` (11,200 lines, AGPL — and this project is
AGPL-3.0 now, so it **may** come in with its notices; see
[ANALYSIS.md](ANALYSIS.md)) has the other half: multi-document tabs,
per-language syntax highlighting with auto-detection, inline HTML preview,
diff mode with per-chunk accept/reject, Google-Docs-style inline suggestion
bubbles, and — the one the user called out — `getSelectionContext()`, which
hands the chat what is highlighted, re-anchoring or dropping stale
selections first so the model never sees text from a region the user is not
looking at.

Three more patterns are visible in the later screenshots and are worth
naming, because each is a small, self-contained "feels capable" win:

- **A selection toolbar.** Selecting text raises a small floating bar —
  bold, italic, underline, strike, link, highlight, alignment, `Aa`,
  overflow. MemoryMap has *no formatting toolbar at all*, and the
  `==highlight==` syntax added recently has no button. HANDOVER.md already
  identifies this as where it belongs (BACKLOG §109.4).
- **`+ Add context` above the composer, and `@` to mention.** The chat
  composer names what it is about to read *before* you send, as removable
  chips. MemoryMap's chat decides its own context and tells you afterwards.
- **A chats list as a pane, not a screen.** The right pane can hold the list
  of past chats with a one-line preview of the last reply and a turn count,
  and switch to one in place.

**What to build here, in order:**

1. **Selection → chat context.** The single highest ratio of "feels
   capable" to work. Port the shape of `getSelectionContext` (validate the
   offsets before shipping them; a stale selection is worse than none).
2. **A `Connections` block on every note and document**, listing incoming
   and outgoing links with direction. The link data already exists
   (`EntryLink`, `DocumentLink`); nothing surfaces it as a first-class part
   of the document.
3. **Typed blocks**, introduced additively: a fenced marker in the markdown
   that renders as a collapsible titled block, so nothing about storage or
   export changes and an old note is unaffected.
4. **One file model.** Non-image uploads from the composer should become
   real `Attachment` rows on save rather than markdown links to `/media`,
   which also settles R1.6 without widening the inline-served allowlist:
   attachments are served `Content-Disposition: attachment` and already
   allow ~60 types. Images keep the inline path — an image in the middle of
   a paragraph is *content*, not an attachment.

### R3.3 The whiteboard

Directly asked: **fullscreen**. The graph already has
`#graph-fullscreen`/`#graph-fullscreen-close`; the whiteboard has nothing,
and it is the surface that most needs the room. Same treatment, same
tokens.

---

## R4. Concept maps: the authored map, separate from the derived graph

> *"I want ways to make custom knowledge graphs that are like mindmaps where
> I can add and remove nodes, move them around, change how they connect and
> reasons, and just make my own thought process map."*
> *"maybe with a way to export that into a visual diagram on the whiteboard
> but that can be for later as an extension, note it down."*

**Design decision: a new object, not a mode on the existing graph.** §R1.5
gives the reason — the two disagree about who owns position and structure.
Merging them means every interaction has to ask "is this node mine or the
simulation's?", which is exactly the ambiguity that makes the current graph
annoying to use.

**Data model.** Two tables, both `WorkspaceMixin`:

- `ConceptNode` — `map_id`, `label`, `note_id` (nullable: a node may be a
  bare idea with no note behind it yet), `x`, `y`, `colour`, `collapsed`,
  `parent_id` (nullable; a mindmap is a tree, but a tree that is allowed to
  have cross-links).
- `ConceptEdge` — `map_id`, `from_id`, `to_id`, `label`, `kind`. The
  `label` is the *"reasons"* the user asked for, typed by hand, never
  inferred.

The map itself is an `Entry` with a kind flag, the same trick the whiteboard
already uses for boards (`board_id` → `entries.id`) — so a map gets naming,
search, spaces, the recycle bin and the timeline for free.

**Interaction, in priority order.** These are the ones that decide whether
it is usable:

1. Double-click empty canvas → new node, immediately in edit mode.
2. `Tab` on a selected node → new child, positioned and linked.
3. `Enter` → new sibling. (Tab/Enter is the whole reason a mindmap is
   faster than a diagram tool; without it this is just a slower whiteboard.)
4. Drag from a node's edge handle to another node → an edge, with an inline
   label field.
5. Drag a node → it stays there. No simulation, ever.
6. Drop a note onto a node → attach it.

**Export to whiteboard: noted, deliberately later.** The whiteboard already
has objects with position, size, rotation and grouping, so the export is a
translation pass rather than new surface. It is listed here so it is not
forgotten, and left out of the first version because a map that is unpleasant
to author is not made better by being exportable.

---

## R5. The agent harness

> *"I think the way skills are is very tight and a lot of things go wrong.
> the agent harness needs major improvement… there needs to be some weight
> lifting of the application to help the agent use tool calling."*

The framing the user's own coursework uses is the right one: *a harness is
the software that turns an LLM into an agent — it runs tools, enforces
permissions, decides when to stop, manages context, and provides the
interface.* Every one of those is the application's job, not the model's,
and that is the lever with a small local model: **do not ask a 4B model to
be careful; make it structurally hard for it to be wrong.**

Concretely, in the order they pay off:

1. **Fewer tools in front of the model at once.** Tool-choice accuracy falls
   off a cliff as the schema list grows, and small models fall off it first.
   Route to a small tool subset per turn rather than presenting the whole
   catalogue.
2. **Narrow names and descriptions.** A description says *when to use this*,
   not what it does. This is free and it is the single most effective change.
3. **Validate arguments in code and hand the error back.** A rejected call
   with a specific message ("`limit` must be an integer, got `'ten'`") is a
   turn the model can recover from; a swallowed exception is a dead end.
4. **Bound tool results.** A tool that returns 8k tokens of note text has
   spent the context the model needed to *use* it.
5. **Treat retrieved content as data, never as instruction.** Notes, web
   pages and file text are untrusted by construction — the user writes them,
   but so does anything they paste. The security lecture's framing is right:
   guardrails are defence in depth, and the enforcement has to be in code.

**Not yet audited against the running code.** `ai/agent.py`,
`ai/skill_runner.py`, `ai/skills.py` and `ai/tools/` have not been read
against this list at the time of writing. Whoever does it first should say
which of the five are already handled — this project's history says it will
be more than expected.

---

## R5b. Local, offline, private — audited

> *"make sure the app is completely local, offline and private for the
> user."*

Audited and **verified empirically**, not asserted:

- **Zero external requests.** A full tour of all seven tabs in Chromium,
  logging every request the page made, produced **0** to any host other than
  `127.0.0.1:8781`.
- **The browser cannot reach one.** The served CSP is
  `default-src 'self'; connect-src 'self'; object-src 'none';
  frame-ancestors 'none'` with a script hash — no CDN, d3 and p5 vendored.
  Even injected markup has nowhere to send anything.
- **Three outbound hosts exist in the whole backend, all opt-in and all
  defaulting to off:** `html.duckduckgo.com` (web search,
  `web_search_enabled` → `False`), `github.com` / `api.github.com` (update
  check, `update_check_enabled` → `False`), and `searxng`, which is a
  container on the user's own machine.
- The frontend contains no outbound fetch at all; the `ollama.com` string is
  a link in help text.

**What was not audited:** whether Ollama or LM Studio, once running, phone
home on their own. That is outside this codebase and outside what it can
promise — worth stating in the app's own privacy copy rather than implied.

---

## R6. Sequencing

Ordered by *"how much does this change the feeling of using the app per unit
of work"*, which is what was actually asked for.

| # | Work | State |
| --- | --- | --- |
| 1 | Files stop dead-ending; cards everywhere; non-image gallery tiles | **done, verified live** |
| 2 | Non-blocking filing (971ms → 32ms) | **done, verified live** |
| 3 | Cross-space leak for files, reminders, whiteboards | **done, verified live** |
| 4 | Whiteboard fullscreen | small, next |
| 5 | Density pass: note rows, fluid gutter and sidebar, one less Library row | **done, verified live — 5 notes visible → 12** |
| 6 | The shell: left rail, per-pane history, independent scroll | the structural fix (C1); large |
| 7 | Concept maps (§R4) | new feature; large |
| 8 | Selection → chat context, `Connections` block, typed blocks (§R3.2) | "feels capable"; medium each |
| 9 | Agent harness audit against §R5 | unknown until audited |
| 10 | Export a concept map to the whiteboard | deliberately last |

**A note on how to work through this.** Items 5 and 6 are the ones that will
be tempting to do cosmetically — a smaller padding here, a tighter font
there. That is how this got to 21,750 lines of CSS across eight files. The
measurements in §R1.1 are the acceptance criteria: if a change does not move
"notes visible in a 900px viewport" or "pixels of chrome before the first
item", it is not the change.

---

## R7. What is still open, ranked — start here next session

Written at the end of the session that produced §R1–§R6, at the user's
request: *"outline and scope out everything not possible in this session as
the top priority for next sessions."* Every item below was **asked for
directly** and is quoted, so nothing has to be re-derived from a
paraphrase. Ranked by how much it changes the feeling of using the app per
unit of work — the same test §R6 uses.

### R7.1 The document/file editor — the largest single gap

> *"the documents editor feels really rudimentary, unrefined, contained,
> small, and annoying to use and make sense of."*
> *"all the files should be managable, viewable and editable in the library
> and document/file/text editor."*
> *"look at how the odysseus documents feature works, you can import, edit
> and create multiple file types, there are options for code lines, viewing
> html and other code, rendering pdfs, exporting, allowing the ai to read
> the documents, able to highlight text and say something in the chat and
> the agent gets the context of what is highlighted and cursor position."*

**What exists here now:** a markdown editor with a title, outline, word
count and AI actions, plus a read-only viewer (`openLightbox`'s document
mode → `/media/text` → `core/docview.py`) that renders PDFs, Office files,
code and plain text with find-in-document. This session wired notes' own
files into that viewer; nothing else changed.

**What is missing, in build order:**

1. **Selection → chat context. Built.** See HANDOVER.md's selection-context
   section: the bar action, the four re-validation outcomes, the live-view
   offset translation, and the `wrapDocSelection` bug it surfaced. What
   follows is the specification it was built to, kept as written.

   The highest ratio of "feels capable" to
   work in the whole list. Odysseus's `getSelectionContext()`
   (`static/js/document.js`, AGPL — this project is AGPL-3.0 so it may come
   in with notices; see [ANALYSIS.md](ANALYSIS.md)) is the shape to port,
   including the part that matters: it **re-validates offsets before
   shipping them**, so the model never receives text from a region the user
   is no longer looking at. Add cursor position alongside.
2. **Editing a file, not only viewing it. Built** — `docview.editability`
   decides, and its four refusals are written to be shown. See HANDOVER.md.
   The specification, as written:

   Text and code files can be
   edited in place; a PDF or .docx cannot, and the honest reason is worth
   putting in the UI rather than leaving as a dead end — the viewer returns
   *extracted text*, which has already stopped being a .docx.
3. **Syntax highlighting with language auto-detection. Built** — written
   in-repo rather than from odysseus's `HLJS_TO_DROPDOWN` map, because there
   is no CDN to load highlight.js from and no bundler to vendor it with. See
   HANDOVER.md, including the user-chosen-accent trap it hit.
4. **An HTML preview pane. Built** — and the `blob:` route this item
   assumed turned out to be the wrong one: a `blob:` document inherits its
   creator's CSP, so the framed page loses its own styling. It is served
   from `/files/{id}/html-preview` with a policy of its own instead. See
   HANDOVER.md.
5. **Export. Built** — "Export text" beside Save, named after what the
   extracted text *is* rather than the file it came from.
6. **A file opens in the editor from the Library. Already true** — the
   Files tiles have always passed `/files/{id}` to the lightbox, and with
   item 2 the lightbox *is* the editor. Nothing was built for this.

### R7.2 Stage every file until the thing it belongs to is committed

> *"ALL FILES, need to be rendered, manageable, files should only be
> instantly uploaded if directly through the library and there needs to be a
> file uplaod button. files should only be staged and not permanently saved
> while uploaded to a note that hasnt been saved yet, or chat messages that
> havent been sent yet etc."*

**Done:** non-image files dropped in the note composer stage and become real
`Attachment`s on save. **Chat attachments now stage too** (`attachImageFiles`
keeps the `File` and an object URL; `commitStagedImages()` uploads at send).
Verified against a running server: attaching leaves `/media` at 0 and renders
a `blob:` thumbnail; committing takes it to 1.

**The audit this section asked for is done.** Every remaining `/media/upload`
call site was classified:

| Path | Verdict |
| --- | --- |
| Library → Files & Images → Upload | **Correct.** The one place instant upload is the point. |
| The sketch pad's Save | **Correct.** Pressing Save *is* the commit; there is no draft to abandon. |
| Chat attachments | **Now staged.** |
| Note-composer inline images | **The one real gap left.** |

**Why the last one is still open, deliberately.** It is the hard case for the
reason already noted — an image in the middle of a paragraph is *content*,
so its markdown needs a URL at the point it was dropped. The shape is known
(a placeholder keyed to a staged `File`, rendered from an object URL and
rewritten at save), and `handleFileUpload` already has both halves of the
scaffolding: a `canStage` guard scoped to `#entry-content`, and an existing
placeholder-then-rewrite flow for the upload it does today.

What stopped it being done in the same pass as the chat half is the failure
mode, not the effort. Every path that can save the composer has to rewrite
the staged markers first; one that does not leaves `staged:`/`blob:` URLs
inside saved note content — **corrupted notes, which is worse than the
recoverable orphan it replaces** (orphans already have a collector: Library →
orphan cleanup, `media_gc.find_orphaned_media`). Do it with a test per save
path, not as a drive-by.

### R7.3 Cross-linking everything

> *"all the features in the entire application need to be closely integrated
> and work with eahc other, I should be able to seamelessly utilise, flick,
> link, manage, create and search between multiple features in each primary
> feature."*
> *"I really like kortex's use of backlinking and elements for structured
> documents as well."*

1. **A `Connections` block on every note and document**, listing incoming
   and outgoing links with direction (↗ out, ↙ in). The data already exists
   (`EntryLink`, `DocumentLink`); nothing surfaces it as part of the thing.
2. **One universal picker** — `@` in any composer, resolving notes,
   documents, files and maps alike, replacing the several kind-specific
   pickers.
3. **Typed, collapsible blocks** inside a document (Kortex's "elements"),
   introduced as a fenced marker in the markdown so storage and export do
   not change and old notes are unaffected.

### R7.4 The agent harness

> *"I think the way skills are is very tight and a lot of things go wrong.
> the agent harness needs major improvement… there needs to be some weight
> lifiting of the application to help thbe agent use tool calling."*

§R5 lists the five changes and their order. **None has been audited against
the running code** — `ai/agent.py`, `ai/skill_runner.py`, `ai/skills.py` and
`ai/tools/` have not been read against that list. Do that first and say
which are already handled; this project's history says it will be more than
expected.

### R7.5 The rest of the UI, surface by surface

> *"ALL THE UI NEEDS IMPROVEMENT, INCLUDING THE SETTINGS AND WHITEBOARD AND
> EVERYTHING ELSE."*
> *"fix and reimagine/refine the ui control elements and panels on the
> witeboard as well."*
> *"a lot of ui elements arent where they should be from a learnability and
> ux point of view. it doesnt feel intuitive."*

The method is set: measure first, then change, then re-measure. The numbers
that matter are in §R1.1 and in [DESIGN.md](../DESIGN.md)'s new
principles section. Per surface:

- **The shell (§R6 item 6)** is still the big one, and its acceptance
  criterion is the alignment count in DESIGN.md: **37 distinct left edges on
  the Dashboard, 35 on Graph, 32 on Notes**, against the two-to-four a
  composed layout has. A change that does not reduce that count is not the
  change.
- **The whiteboard's panels.** Five floating draggable panels with mixed
  control sizes, unlabelled icon buttons and a raw colour input. Full screen
  landed this session; the panels did not.
- **Settings** has not been measured at all.
- **The Dashboard's triple navigation** — the tab bar, "START SOMETHING",
  and a "JUMP TO" row naming the same seven tabs — is the clearest
  learnability fault found and is a deletion, not a redesign.

### R7.6 Concept maps: manage, not just make

Creating one works end to end (§R4, built). Still missing: a **Maps listing
in the Library** — rename, delete, duplicate, open — so they can be managed
rather than only found through the Whiteboards sub-tab.

### R7.7 Backend

> *"fix and refine the backend after or at least scope it for next session."*

Nothing here is urgent after this session's fixes; it is the honest list of
what a backend pass should cover.

- **`app.js` is 26,000 lines.** It was split once already; the split moved
  four files out and left this. Every UI change pays for it.
- **The notes list renders every note into the DOM.** Fine at 40, not at
  4,000. Virtualization is the standard answer and the skill's own
  guidelines name it.
- **`_to_out` is ~4 queries per entry**; `_to_out_bulk` exists for lists but
  not every caller uses it.
- **The two file models remain two.** `MediaUpload` (inline, images/PDF
  only, served inline) and `Attachment` (per-entry, ~60 types, served as a
  download) now behave consistently at the UI, but a single model with a
  `disposition` flag would remove the class of bug this session fixed three
  instances of.
- **`filing_similar_id` is not a ForeignKey**, deliberately (see its
  docstring); a periodic sweep for dangling ids would be tidier than
  resolving-and-shrugging forever.
- **Alembic is stamped but unused.** The additive auto-migrator plus this
  session's two hand-written rebuilds is now three migration mechanisms. Pick
  one before a fourth.

#### "Should the backend be async?" — asked directly, and the answer is no

> *"I feel like the backend should be made asyncronous if it isnt already,
> maybe add it to the list for backend fixes and redesigns??"*

Worth putting on the list precisely so it does not get done. Measured: **230
sync `def` routes, 1 `async def`, and a blocking `create_engine`** (the
stdlib `sqlite3` driver).

That is already the correct arrangement, and the reason is a FastAPI detail
that is easy to have backwards. **A `def` route runs in a threadpool** —
Starlette hands it to anyio's worker pool, so requests already run
concurrently and one slow route does not block another. That is why
deferring note filing worked at all.

Converting those 230 routes to `async def` **without** also replacing the
database layer would make things strictly worse: blocking `sqlite3` calls
would then run on the event loop itself and serialise every request in the
process, turning a working threadpool into a global lock.

Doing it *properly* means `aiosqlite`, `AsyncSession`, and rewriting every
route and every `session.query` in the codebase. For a single-user
local-first app the payoff is close to zero: SQLite serialises writers
regardless, WAL and a 5s busy timeout are already set, and the only latency
anyone actually feels is the local model — which this session moved off the
request path.

**The real wins are elsewhere and are already on this list**: keep slow work
off the request (filing, embedding and the duplicate search moved this
session; captioning, OCR and vision-OCR were already there), use
`_to_out_bulk` everywhere a list is served, and virtualize the notes list.
Revisit async only if this ever becomes multi-user or gains a real network
backend — at which point the database layer changes first and the routes
follow, not the other way round.

---

## R8. The complete request ledger

> *"scan all my requests from this chat session and make sure you havent
> missed anything"*, asked four times, and *"make sure none of my requests in
> the entire chat have been unaccounted for."*

Every ask from the session that produced this file, in the order it arrived,
with what happened to it. **Nothing here is a paraphrase of a paraphrase** —
if an item is still open, its own §R7 entry quotes the original words.

| # | The ask | State |
| --- | --- | --- |
| 1 | PDFs in notes are "pure md with no visual card allowing me to delete the files" | **Done** — file cards, composer strip, remove |
| 2 | "I cant see, manage or view the files or documents anywhere" | **Done** — non-image gallery tiles; sub-tab is "Files & Images" |
| 3 | Clicking a note's file → "black fode screen… no way for me to go back" | **Done** — opens the in-app viewer; zero `/media/` anchors remain |
| 4 | Files the composer refused (.docx, .txt, code) | **Done** — staged, attached on save |
| 5 | "the documents editor feels really rudimentary… annoying to use" | **Open** — §R7.1, the largest gap |
| 6 | Odysseus document features (code, HTML, PDF, export, selection→chat) | **Open** — §R7.1, in build order |
| 7 | "all the files should be managable, viewable and editable in the library and document/file/text editor" | **Partly** — manageable and viewable; editable is §R7.1 |
| 8 | Files staged, not saved, until the note/message is committed | **Partly** — note files stage; images and chat are §R7.2 |
| 9 | Instant upload only through the Library, with an upload button | **Partly** — the button exists; §R7.2 finishes the rule |
| 10 | Graph as a mindmap: core idea, branches, notes attached | **Done** — concept maps, §R4 |
| 11 | "make and manage map graphs (maybe in library??)" | **Partly** — create is in the Library; managing is §R7.6 |
| 12 | Export a map to the whiteboard, "for later" | **Done by construction** — a map *is* a board |
| 13 | Making notes "slow and annoying"; panels should disappear, file in the background | **Done** — 971ms → 32ms, "Filing…" chip, notification |
| 14 | Images from the main space showing in another space's gallery | **Done** — six models scoped; backfill inherits from the parent |
| 15 | Whiteboard "definately needs a fullscreen mode" | **Done** — 1376×676 → 1440×900 |
| 16 | Graph "soooooo annoying to use"; connections "annoying and manual" | **Done** — a drag places a note and it stays placed |
| 17 | "the gravity and separation in the main graph view are annoying" | **Done** — the world is sized by node count, not the window's shape |
| 18 | "the graph nodes seem to be stuck in an invisible rectangular box" | **Done** — same fix; measured 5 of 47 nodes on the boundary |
| 19 | Graph node popups "need a full redesign" | **Done** — a 3-column grid, equal widths, wider popup, readable note |
| 20 | "the graph view area keeps feeling squashed… due to the top dock" | **Done** — one-row legend, explanation moved to a tooltip |
| 21 | "the exit full screen button even shows when not in fullscreen" | **Done** — a regression I introduced, same session |
| 22 | The minimap sitting over the map | **Done** — translucent at rest, full on hover |
| 23 | "half the screen is taken up by poor ui choices or structuring" | **Done** — 5 notes visible → 12; a Library row removed |
| 24 | Margins/edges losing space; adapt to any resolution | **Done** — fluid gutter and sidebar, measured at six widths |
| 25 | "there are no animations for chat generation" | **Done** — a streaming caret |
| 26 | "ui elements arent where they should be… doesnt feel intuitive" | **Partly** — the Dashboard's triple nav is gone; §R7.5 |
| 27 | Keep the old note layout as an option | **Done** — a rows/cards toggle |
| 28 | Typography, spacing, alignment, sizing, consistency, CARP | **Done** — DESIGN.md's principles section, `--target-min`, two lints |
| 29 | "they should be part of design.md and you should be sticking to them" | **Done** — and two are now enforced in CI |
| 30 | Save the UI skills so future sessions have them | **Done** — seven vendored in `.claude/skills/` |
| 31 | "ALL THE UI NEEDS IMPROVEMENT, INCLUDING THE SETTINGS AND WHITEBOARD" | **Partly** — §R7.5; Settings is unmeasured |
| 32 | Reimagine the whiteboard's control panels | **Partly** — sizes unified; the layout rethink is §R7.5 |
| 33 | Everything cross-linked and searchable from everywhere | **Partly** — link direction landed; §R7.3 |
| 34 | "make sure the app is completely local, offline and private" | **Done** — audited, §R5b |
| 35 | Spaces kept separate unless viewing All spaces | **Done** — and found a 500 that made two spaces impossible |
| 36 | "the app is stuck on th eloading screen" (pydesktop) | **Mitigated** — see §R8.1 |
| 37 | Make the backend asynchronous | **Answered: no** — §R7.7, with the measurements |
| 38 | "I can use keyboard shortcuts to access features even when locked out" | **Done** — a lock gate, §R8.2 |
| 39 | "if the backend is closed the ui should fail to load" | **Done** — the service worker no longer caches the shell |
| 40 | Commit and push in batches so nothing is lost | **Done** — pushed throughout |
| 41 | "the app is stuck on th eloading screen" — the real cause | **Done** — a TDZ crash of mine; §R8.4 |
| 42 | Ctrl+Shift+R is a hotkey, so that advice was unusable | **Done** — every message says restart the app instead |
| 43 | "the terminal and logs need to capture everything" | **Done** — `POST /logs/client`, outside the unlock gate |
| 44 | "should the toggle switches be looking like that??" | **Done** — another regression of mine, §R8.4 |
| 45 | "the linked notes buttons arent aligned" | **Done** — measured to 0px offset |
| 46 | Make cards the default note view, and remember the choice | **Done** — verified across a reload |
| 47 | "the compact cards need to be expandable" | **Done** — a row opens out in place |
| 48 | Spacing and excessive paragraph text in Settings | **Open** — §R7.5; Settings is still unmeasured |
| 49 | "a show more/less button appears when it isnt needed sometimes" | **Done** — measured on the next frame, removed when nothing is clipped |
| 50 | "notes shouldnt be truncated" | **Done** — same fix; a note that fits is never clamped |
| 51 | "if I delete a deleted image placeholder, it should stay deleted" | **Open** — §R7.8 |
| 52 | Filter by space while in All spaces | **Open** — §R7.9 |

### R7.8 A dismissed image placeholder comes back

> *"if I delete a deleted image placeholder, it should stay deleted"*

When a note's inline image no longer exists on disk, `renderInlineMarkdown`
swaps the broken `<img>` for a closable placeholder — and its × calls
`placeholder.remove()`, which takes the *element* out of the DOM and leaves
the `![alt](/media/…)` markdown in the note untouched. The next render puts
it straight back.

The fix is the one the *other* placeholder in that same function already
uses: `renderNoteText`'s `remove-inline-image` event, which rewrites the
note's content and PUTs it. Dismissing should either do that (delete it for
good) or say it is only hiding it for now. It must not look like a delete
and behave like a blink.

### R7.9 Filtering inside "All spaces"

> *"I think there should be a way to filter out content from different
> spaces in the all spaces space"*

"All spaces" is implemented as `workspace_id = "all"`, which switches the
scoping hooks off entirely (`core/database.py`) — so it is genuinely
everything, with no way to narrow it. Two pieces are needed:

1. **Say which space each thing is from.** A note in the All view carries no
   marker at all today, which is most of why the view feels like a pile. A
   space chip on the card is the smaller half and worth doing alone.
2. **Filter by space.** The scoping hook takes one id; a *set* of ids is the
   real change, and it belongs in `_add_workspace_filter` rather than in each
   route, for the same reason the single-id version does.

Worth doing together with the space chip, and worth measuring after: the All
view is the one screen where the notes list has no other grouping.

### R8.4 Three regressions I introduced, and what they have in common

Recorded because the pattern matters more than the three fixes.

1. **`button.small { display: inline-flex }`** (added to centre a label inside
   the new hit-target floor) is specificity (0,1,1), and every rule in the app
   that hides a button by class alone — `.graph-fullscreen-close { display:
   none }` — is (0,1,0). It forced all of them visible. Reported within
   minutes: "the exit full screen button even shows when not in fullscreen."
2. **`input[type="checkbox"] { min-height: var(--target-min) }`** (added to
   lift 13×13 native checkboxes to the 24px floor) beat the switch pattern's
   own `height: 1.15rem`, because `min-height` wins over `height`. Every
   toggle in Settings inflated into a slab: "should the toggle switches be
   looking like that??"
3. **`let captureStagedFiles`** declared beside the function that fills it,
   19,000 lines below the load-time code that reads it — a temporal-dead-zone
   crash that aborted `app.js` and hung the app on its loading screen.

All three are the same mistake: **a broad rule written for one problem,
applied to a codebase whose other rules were not checked against it.** The
first two were CSS specificity, the third was evaluation order. None was
visible in the diff; all three were visible in one screenshot.

The defence that worked is worth keeping: `boot-guard.js` caught the third
one and named it exactly, which is why it took minutes rather than a
session. The defence that did *not* work is worth naming too — every
cold-boot test passed, because the crashing path only runs when there is an
unsaved draft. **A load-time path behind a condition needs a test that meets
the condition.**

### R8.1 The stuck loading screen, and what was actually found

Not reproduced: a cold boot on a fresh profile clears the splash in
1.2–1.4s with no JS errors, database init is 140ms on an existing database,
static assets are served `no-cache` with an ETag, and there is no CSP
violation.

But two real causes of exactly that symptom were found and closed:

1. **A stale server serves a stale CSP hash.** `create_app` computes the
   inline-script hashes from `index.html` **once, at startup**. A server left
   running from before an update therefore sends a hash that no longer
   matches, the browser refuses the page's own inline script, and the app
   dies with the splash still up. Reproduced here by accident, mid-session.
   The boot guard moved out of that inline block into `boot-guard.js` —
   `script-src 'self'` covers a same-origin file unconditionally, so the
   thing that reports a broken boot can no longer be broken by the same
   fault. It names this case specifically, with the fix (restart the server).
2. **The splash had no failure state at all.** `initAuth` bounds its own
   probe, so it cannot hang if it runs; the gap was every failure where it
   never runs. The guard now surfaces the real error, a CSP refusal, or a
   12-second "this is taking too long".

**Still worth checking on the desktop build next session**, since the report
was specific to it: whether PyWebView is caching, and whether it starts its
server before or after the frontend is unpacked.

### R8.2 Shortcuts worked while the notebook was locked

> *"I can use keyboard shortcuts to access features even when locked out…
> like the meeting notes popup."*

A privacy hole, not a polish item, and it had no guard of any kind: the
global `keydown` handler ran the full shortcut table with the lock overlay
up — the command palette (which lists and opens notes **by title**), `/` to
focus search, the `g`-then-letter tab jumps, the meeting recorder. The lock
screen is this app's only privacy boundary and the keyboard walked past it.

Fixed with one gate at the very top of the handler, reading the overlay's own
`hidden` class rather than a second flag — the same source of truth the rest
of the app already uses, because a boundary with two of those is a boundary
that drifts back open.

**A lock audit is the follow-up**, and it belongs at the top of §R7: this
was found by a user pressing keys, not by a test. What else is reachable
while locked — drag and drop onto the window, the browser's own context
menu, a `#hash` route, an already-open second tab — has not been checked.

### R8.3 The UI, re-imagined: what the remaining work is *for*

> *"deep think the rest of the ui reimagined designs as well as for the
> backend."*

Everything above is a list of repairs. This is the shape they are repairs
*toward*, so the next session is not just working a queue.

**The organising idea: one workspace, many panes.** MemoryMap today is seven
screens that each own the whole window, and switching loses everything about
where you were. Every unresolved complaint in §R7 is downstream of that:
cross-linking is hard because you cannot see two things at once (§R7.3); the
document editor feels "contained and small" because it is a tab, not a pane
(§R7.1); alignment is bad because seven screens each solve layout for
themselves (37 distinct left edges); and the Dashboard needed a duplicate
navigation because there was no persistent way to get anywhere.

Kortex's answer, in the screenshots supplied, is the one to take:

- **A left rail that is content, not chrome.** Destinations at the top;
  below them, the user's own tree. MemoryMap has seven top tabs, seven
  Library sub-tabs and four Notes sub-tabs — three levels of tab bar over
  one hierarchy.
- **Panes, each with its own back/forward and breadcrumbs.** This also
  retires the nav-history popup, which has been reported and re-fixed
  repeatedly *because it is per-pane history in a single-pane app*.
- **A narrow measure for prose, wide chrome around it.** The 72ch cap the
  note cards got this session, applied to documents.
- **Content is the only bright thing.** The default theme paints a lilac
  gradient behind translucent cards, which is why nothing reads as
  foreground.

**The test for every piece of it** is already written down and is not taste:
does it reduce the distinct-left-edge count (DESIGN.md), and does it move
"pixels of chrome before the first item" (§R1.1)? A change that does neither
is decoration.

**And the backend's version of the same idea:** the two file models
(`MediaUpload` inline vs `Attachment` downloaded) are the same shape of
problem one layer down — one concept, two implementations, and every bug
this session fixed in files was a seam between them. One model with a
`disposition` flag removes the class, not the instances. The same is true of
three migration mechanisms and of `app.js` at 26,000 lines. None of that is
urgent; all of it is why small changes cost more than they should.

---

## R9. Where the numbers stand at the end of this session

Measured the same way as §R1, on the same machine, at 1440×900.

| | Before | After |
| --- | ---: | ---: |
| Notes visible in a 900px viewport | 5 | **12** |
| Note row height (2-line note) | 121px incl. gap | **57px**, no gap |
| Save round trip, no model running | 971ms | **32ms** |
| Library chrome above the first item | 344px | **301px** |
| Side gutter at 1024 / 1440 / 1920 | 32 / 32 / 32px | **22.5 / 31.7 / 32px** |
| Sidebar at 820px wide | 260px (32% of the window) | **197px** |
| Distinct control heights — Notes | 7 | **4** |
| Distinct control heights — Library | 7 | **4** |
| Controls below the 24px target floor | 13 across 4 tabs | **0** |
| `/media/` anchors in a rendered note | one per file | **0** |
| Graph nodes on the layout's bounding edge | most of them | **5 of 47** |

**One number deliberately not claimed as improved: alignment.** Distinct
left edges now read 40 (Dashboard), 41 (Graph), 36 (Notes) against the
37/35/32 in §R1.1 — but the notebook has three times as many notes in it
than when the baseline was taken, so the two are **not comparable** and
neither figure should be quoted as progress or regression. Alignment is the
shell's problem (§R7.5), it has not been worked yet, and the honest position
is that it is unchanged. Re-baseline it on a fixed fixture before starting
that work, or the same ambiguity will repeat.

**What has demonstrably not been done** is in §R7, and the largest piece of
it — the document editor and the pane-based shell — is most of what is left
between this app and the one the requests describe.
