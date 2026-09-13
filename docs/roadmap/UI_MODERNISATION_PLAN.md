# UI modernisation — the dev plan for the next session

> Companions: [ROADMAP.md](../ROADMAP.md) (live list — this plan is its top
> priority) · [HANDOVER.md](HANDOVER.md) (what the last session measured and
> left) · [../DESIGN.md](../DESIGN.md) (the rules this plan extends) ·
> [BACKLOG.md](BACKLOG.md) · [HISTORY.md](HISTORY.md) · [ANALYSIS.md](ANALYSIS.md)

## The instruction, verbatim

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

And: "the ui needs to be modernised and proffesionalised for the whole
application ... the application still feels fake, vibe coded and not ready
for professional use. some things feel performative and not at professional
standards in the ui and ux."

## What "fake / vibe coded / performative" means here, concretely

Read against the measurements the last session took (HANDOVER.md, "This
session"), the feeling has five measurable causes. Every phase below attacks
one of them and is judged by a count, not by looking at a screenshot.

1. **Many recipes for one thing.** 17–21 button signatures on a tab; two
   eyebrow recipes; three seg recipes; row gaps of 4/6.4/8/9.6/16px; head
   rows 28/38/40px tall; two card radii. A professional UI has one of each,
   and the eye reads the difference as "assembled from parts".
2. **Decoration doing the work of structure.** Borders inside borders,
   sheen, blobs, shadows and glass everywhere, because tone and whitespace
   were never trusted to group things. Surface tiers started this; it is not
   finished (chips, fields, popovers, the whiteboard panels, the chat dock).
3. **Uneven mass.** 18px card padding on a 1100px card; 12/10/18px shell
   gaps (now one gutter); a hero that is 150px tall for a greeting; widgets
   with 47px of head for one line. Modern layouts are generous at the shell
   and dense inside the component, not the other way round.
4. **Things that move when they should not.** Menus that paint before they
   are placed (fixed for toolbar menus; audit the rest), rows that change
   shape on hover, transitions on layout properties.
5. **Copy and states that are not designed.** Empty states as one grey line,
   errors as toasts, loading as nothing, labels in three tones of voice.

## Rules for the whole plan

- **Measure, change, re-measure.** `scratchpad/ui-sweeps/` holds the sweep
  scripts from the last session (`buttons.js`, `borders.js`, `caps.js`,
  `segs.js`, `rows.js`, `space.js`, `heads.js`, `lib.js`). Each prints a
  signature table per tab. A phase is done when its count is what the phase
  says, in both themes, on the default palette. Run:
  `SCRATCH=<dir> BASE=http://127.0.0.1:<port> PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/<x>.js`
- **Tokens only.** No new px/rem values; `tests/test_style_scale.py` fails
  otherwise. If a phase needs a value the scale lacks, add the token with a
  comment saying which measurement asked for it.
- **Subtract before adding.** Every phase first removes a recipe, a border,
  a shadow, a size — and only then adjusts what is left.
- **One commit per phase, pushed, with the before/after counts in the
  message.** The user's usage is finite; a session that ends mid-phase must
  leave a green, pushed head.
- **Not performative:** no new gradients, glows, animations, badges or
  "AI sparkle" anywhere in this plan. The glass stays where it reads as
  material (the shell, a floating panel) and goes where it reads as effect.

## Decisions made

Standing order 3: a decision recorded here is not re-opened. A missing one
becomes an INBOX entry with a one-line recommendation, which is then taken.

- **A picker that adds to a list is an adder, not a `<select>`** (the owner,
  2026-09-12, on the capture form's "Add to document" box, INBOX 116). A
  `<select>` is the right control for choosing *a* value in a form: it shows
  what it holds. Where the answer is a set rather than a value, the picked
  items are chips and the control that adds one is a button that opens the
  app's own menu (`labelledMenu`, DESIGN.md's recipe index), so the control
  never has to lie about holding a value it cannot show. The failure this
  replaces is exactly that lie: the old handler wrote `value = ""` after
  every pick, so the box snapped back to "None" and read as broken.
  Applies wherever the same shape appears next, not only to this row.

- **Two writing columns are two of the same column** (Brief 22, the Write
  with AI panel, 2026-09-12). Where a panel puts two editors side by side,
  each column is a label, the box, one optional field and one line of
  actions, in that order, and the box is the only thing that stretches. What
  it replaces, measured at 1440x900: boxes of 189.2 and 330.3px from
  `rows="7"` and `rows="14"`, a left column ending 107px above the right one
  with nothing in the gap, an instruction input wedged between two buttons
  that do not read it, and an action row of four weights with a text field
  among the buttons. The two optional fields ride the `.ask-composer`
  recipe, which is also what makes the two rows the same height and so the
  two boxes equal: a row that is the same recipe in both columns is the same
  height in both.

## Phase 0 — tooling and acceptance gates (½ session)

1. Add `tests/test_ui_signatures.py`: a static lint that counts distinct
   `gap:`/`padding:` values on `.row`-class selectors and distinct
   `border-radius` values on surface selectors, with a ceiling the later
   phases lower. It cannot see the DOM; it stops regressions between
   sessions.
2. Add a `make ui-sweep` (or a `scratchpad/ui-sweeps/all.sh`) that runs every
   sweep against a running app and writes the tables to one file, so
   before/after is one diff.
3. Screenshot set: every tab + every Settings section, light and dark, 1440
   and 1024 wide, into the scratchpad. Same script each session.

## Phase 1 — mass and layout (1 session)

Target: the app reads as one shell with rooms in it, not as cards on a
gradient.

1. **Shell.** One gutter (`--page-gutter`, done) — extend to the dashboard
   grid gap, the Library grid gap, and the gap between the sub-tab strip and
   its content (measured 24/17/8px). Status bar and top bar: same height
   family (`--header-h`), same horizontal padding as the page gutter so the
   logo, first tab, sidebar edge and first card edge share one x.
2. **Card system.** `.card` padding to `--space-6/--space-7` on ≥1100px
   content columns (measured 16/20px everywhere, which is dense for a full-
   width panel and right for a widget). Define two card sizes only:
   `.card` (panel) and `.card.compact` (widget, sidebar). Kill card-in-card:
   `.card .card` becomes a tone (`--surface-2`), never a bordered pane.
3. **Dashboard.** Hero from 150px to one row (greeting · date · time · name),
   quick actions become the first widget row, stat tiles fold into the
   Stats widget. Widget head row: 32px, title + one action, no border below.
4. **Sidebars.** One width token, one head row (28/38px measured → one),
   list rows at `--target-min` with tone hover, no bordered rows.
5. **Max reading width.** `.entry-list.is-rows` already caps the measure;
   apply the same `--measure` token to chat bubbles, document preview, the
   Contents page and Settings prose (currently 100% of a 640px column, fine;
   100% of a 1100px column, not).

Acceptance: `space.js` shows one card padding per card size, one card gap,
one shell gutter; head rows at one height; screenshots side by side.

## Phase 2 — component consistency (1–2 sessions)

Target: one recipe per component family, counted.

| Family | Now (measured) | Target |
| --- | --- | --- |
| Buttons | 13–21 signatures per tab | 4: filled, tonal, plain, icon-tonal (+ danger colour) |
| Rows (`.row`, toolbars) | gaps 4/6.4/8/9.6/16px | 2: `--space-3` inside a control group, `--space-4` between groups |
| Head rows | 28/38/40px | 1: `--control-h` |
| Chips/badges | ~6 recipes (tag, link, status, count, filter, inline) | 2: static tag (tone, no border) and interactive filter chip (tonal button) |
| Fields | inputs with border+inset; selects with border+shadow | 1: recessed well, `--field-inset`, no drop shadow |
| Segmented | 3 | 2: tab strip (well) and choice (chip well) — done, keep |
| Menus/popovers | action-menu, select-menu, doc-dock-menu, help-popover, graph panels — 5 shells | 1 `.popover` shell: `--modal-bg-opaque`, `--border`, `--glass-shadow`, `--radius-md`, hidden-until-placed |
| Dialogs | modal-card + 4 one-off panels | 1 |
| List rows | entry-list li, library-card, bookmark-row, extras-row, setting-row | 2: card row (tone) and divider row |

Method per family: run the sweep, read the signature table, pick the winner
(the one most used, already on tokens), rewrite the others onto it, delete
the one-off rules, re-run. Record each family's before/after count in the
commit.

## Phase 3 — typography, colour, glass restraint (½ session)

1. Type: `--text-md` for control labels everywhere (measured 0.85/0.92rem
   one-offs remain in Settings labels and library meta). Muted text at one
   colour, one opacity — no `opacity: 0.75` on top of `--muted`.
2. Colour: the accent is for the one filled action, selection, and links.
   Remove accent from decorative borders, dots and icons that are not
   interactive. Status colours (`--ok/--warn/--error`) only on status.
3. Glass: keep `backdrop-filter` on the top bar, sidebars, floating panels
   and sticky strips. Remove it from widgets and list cards (tone instead) —
   the measured blur layer count drops again and the page stops shimmering.
   Sheen: off by default; the setting stays.
4. Background: the blobs at half strength by default; a professional product
   has a quiet page.

## Phase 4 — motion and placement (½ session)

1. Every floating panel opens through one path: measure → place → reveal.
   The toolbar menus do (`.is-placed`); port the same class to
   `.action-menu`, `.select-menu`, `.help-popover`, the graph panels and the
   whiteboard floating panel, and the chat model panel.
2. No transitions on `left/top/width/height`; opacity and transform only,
   ≤ `--motion-base`. Hover changes tone, never size or shape.
3. Focus rings: one recipe (`--accent` 2px offset) on every interactive
   element; verify with a keyboard-walk script.

## Phase 5 — per-surface passes (1 session each, in this order)

1. **Settings** — the most visited and the most measured; apply phases 1–3
   and the #129 list (spacing, hierarchy, proximity per page).
2. **Notes** (Browse, Capture, Write, Ask) — #132; the capture toolbar's
   density; the row list as the reference list component.
3. **Chat** — dock, sidebar, bubbles; #35's odysseus-style shape as the
   target, kept restrained.
4. **Library** — All/Documents/Files/Images/Links/Contents rows onto the two
   list-row recipes; #101.
5. **Dashboard** — phase 1's hero and widget head; widget internals onto the
   compact card.
6. **Graph, Timeline, Reminders** — toolbars onto the row recipe; the graph's
   floating panels onto the popover shell.
7. **Whiteboard and Documents editor** — panel chrome onto the popover
   shell; the toolbar strip as the reference toolbar; #133, #134.

## Phase 6 — designed states and copy (½ session)

1. Empty states: icon + one sentence + one action, one component, used by
   every list. 2. Loading: skeleton rows for lists, a spinner only inside a
button. 3. Errors: inline under the control that failed; toasts only for
background work. 4. Copy: sentence case everywhere except eyebrows; verbs on
buttons; no exclamation marks; one voice (DESIGN.md gets a "Voice" section).

## Verification, every phase

- Sweep tables before/after in the commit message.
- Screenshots, light and dark, both widths, looked at *and* measured (pixel
  samples for any colour claim, `scrollHeight` for any clipping claim).
- `python -m pytest tests/` green; `ruff`; `node --check`.
- The four traps in CLAUDE.md still apply: stale server, stale `app.js`, a
  screenshot is not a measurement, "already exists" is where triage starts.

## Phase 7 — the reports from the v0.2.2 round that are still open

Each one was triaged against the running app this session; these are the ones
that need building rather than fixing.

1. **The lightbox is an image viewer showing a document.** Reported: "the
   lightbox needs improving for file and pdf previews, no sections or info are
   below it really compared to the images." An image gets caption, read text,
   badges and usage under it; a PDF gets the page and nothing else. It should
   carry the same block, plus what only a document has: page count, which pages
   have been read, and a way into the OCR Workspace at that page.
2. **Line numbers as a setting, in all three editors.** The wrap bug is fixed
   (v0.2.2) but the gutter still appears only for code files in Documents, and
   the note capture and edit panels have no gutter at all. Wanted: one toggle,
   remembered, working for any file type, in all three.
3. **Captioning for documents, not just photographs.** Reported: "image
   captioning, how it is done and displayed needs to be refined for pdf
   documents and other similar documents. with graphs, images and diagrams in
   them." A page of slides is not a photograph: the caption prompt, and where
   the answer is shown, both assume one image with one subject. Needs a
   per-page, per-figure model and a place to show it that is not a single line
   under a thumbnail.
4. **Region select → read just that.** Asked as a question, and it is a good
   one: "can there be a way for the user to manually outline and single out
   regions on a pdf or similar document and then the ai will read what is in
   those regions?? like maybe the user can outline a graph or diagram on a pdf
   slide and then the user cna get the image or ocr model to analyse and caption
   that thing." The workspace already draws region boxes from Tesseract and
   already has a page raster; this is a drag-to-draw on that layer, a crop, and
   the existing read/caption call on the crop. Scoped small, high value.
5. **The Files sub-tab has to show more than a row can hold.** OCR text for a
   long document does not fit where a photo's caption fits; the row needs a
   summary plus a way to open the reading, not a clamped paragraph.
6. **The agent activity panel** — see
   [AGENT_SKILLS_REFORM.md](AGENT_SKILLS_REFORM.md) Phase C, which owns it.

### Built — items 1, 3, 4 and 5

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", UI_MODERNISATION_PLAN.md) on 2026-09-09: a plan holds open work only.

### Decided, 2026-09-13 — how the page reader is reached (do not remake)

From INBOX 125: "alsi I want an easier and more accessible way to access the
ocr workspace as a proper and more central feature." Triaged against the
running app first, because "already exists" is where triage starts, and four
doors were already there: the Files row's own filled "Read this" / "Open
reader" (the 2026-09-12 decision above), the image card's kebab, the
lightbox's "Read text with AI" and its kebab's "See text on the page", and the
toast that offers the way back while a read is still running.

What every one of them has in common is the answer: **each door starts from a
file you have already found.** There is no way in from "I want to read
something", and the reader is absent from both of the app's own "what can this
do" surfaces. That is the same gap, in the same words, as the meeting
recorder's ("I would also like the meeting notes popup to be expanded as a
proper feature ... which is also accessible throughout the app, not just from
the dashboard"), and it gets the same answer, because inventing a second
pattern for the same shape is what DESIGN.md's recipe index exists to stop.

- **The command palette and Tools & features, and nothing new.** Ctrl/Cmd-K
  reaches "Read a document or image with AI" from any tab, and the features
  browser lists it beside Attachments, which is the entry a person who does
  not know the reader exists will actually meet. Those two are the app's
  answer to "make X reachable from anywhere"; a fifth per-file door, a nav
  item or a dock button would each be a new pattern for a feature that already
  has four.
- **It opens on a file rather than on a picker**, in this order: the file you
  last had open in it, else the most recently added readable file, else the
  Files sub-tab with a line saying there is nothing to read yet. The reader's
  own rail already lists every image and file in the notebook (it learned to
  load them itself when "if I open it from the lightbox when viewing an image,
  no other files or images show" was reported), so a picker in front of it
  would be a second list of the list it already has.
- **No new markup.** Both entries are rows in existing catalogues, so there is
  no new id, no new surface and nothing for the recipe index to cover.

### Decided, 2026-09-12 — what a Files row is for (do not remake)

From INBOX 115, "the files rows in files still needs some ui improvement and
redesign, and better function". The row had grown by accretion: five
full-width blocks in a 1218px column, each carrying one short string, 257px
tall at 1440. The question "what should a file row let you do without opening
anything" is settled here so the next pass adds to a shape rather than
restacking it.

- **Two ranks, not five.** The name is the row. Under it, one wrapping line of
  facts at one rank: what the file is (kind, size, pages, added), whether it
  has been read and how much came out, and where it is used. Under that, the
  description, which is the only prose and the only thing that may take two
  lines. Anything new joins one of those three or it does not go on the row.
- **Four verbs, without opening anything**: open it in the reader (the row's
  one filled control), save a copy of the original, rename, delete. The last
  three live in the kebab, which is where every other list in this app puts
  them. "Save a copy" is the one a file list must have and this one did not:
  nothing in the Library could get a file back out of the notebook.
- **A fact is not a control and a control is not a chip.** The reading badge
  states; the "Used in" chips open the note they name; the kebab acts. A row
  that draws all three the same way is the report this decision answers.

### Decided, 2026-09-12 — what the bottom of a picture card is (do not remake)

From INBOX 115 ("the bottom of the image cards in the library images
subsaection needs a desperate redesign and funection") and INBOX 118 after the
first pass ("still poorly designed and look unprofessional"). The Files row
decision above settles a row; this settles the card, which is a different
shape and was being restacked every pass.

- **The card is a picture and one paragraph about it.** Its name is on the
  photograph, its description under it, clamped to two lines, and nothing else
  is a permanent row. A card with nothing in it is short.
- **A fact is a line of text, a disclosure is a control, and neither is the
  other.** Where the picture is used is a count you read (`Used in 2 places`,
  the smallest type on the card, no ground, nothing to press). Whether text
  was found in it is a fold, present only when something is folded. One
  control holding both is what INBOX 118 called unprofessional.
- **Everything you can do to a picture is a row of the card's kebab**, not a
  control on it: open full size, copy the markdown reference, write a
  description, type the text in it, rename, save a copy, the two AI readers,
  and one row per place it is used. Two to three controls on a card at rest,
  against nine to ten before this work.
- **The grid wants equal heights, and the photograph pays for them.** The tile
  is a column, the frame is the one child that grows, with a 9rem floor and a
  16rem ceiling. Measured on six seeded cards at 1440: 261.5px each, bottoms
  within 0.1px, pictures 144 to 249.9px, and 1.0px of slack under the
  emptiest card against 54.5px before. The cost, and it is the accepted one:
  the six descriptions start at six different heights, because the only other
  places to put the difference are a hole under the short cards (what the
  owner reported) or reserved empty rows (what the owner reported first).
- **Provenance is inside the fold**, with the reading it describes. "Described
  by X, read by Y" has been called noise twice (INBOX 56 and the second design
  batch) and is not coming back to the outside of the card.

Built in `75a1d62`, `65cf876` and `4dd3f57`; probed by `scratchpad/ui-sweeps/imagecardfoot.js`
(shape and, with `pixelcontrast.py`, contrast from the rendered pixels) and
`imagecardmenu.js` (the menu rows, run rather than assumed).

**Reported a third time, 2026-09-13, and the decision above is not what was
wrong.** "redesign the bottom text area of the image cards in the library
images subtab again ... the block reads as four unrelated rows of different
weights, and the cards are uneven in height because some have the disclosure
and some do not." Measured before touching anything: the cards were already
equal (261.5px, bottoms within 0.1px), so what reads as uneven is what is
*inside* them, and it was three rows under the picture at three adjacent type
sizes (13.6 / 12 / 11.2px) with a foot running 9.6px to 115.5px across one row.
Three amendments, none of which reopens a bullet above:

- **The count and the fold share one line of facts**, which is the Files rows'
  own `.library-file-meta` shape rather than a new one. They are still two
  objects, one you read and one you press, which is what "a fact is a line of
  text, a disclosure is a control" asks for; they simply no longer take a row
  each. The fold's label on a card is "Text" (the full phrase is its tooltip
  and the heading inside it) because "Used in 2 places" plus a 128.8px chip
  does not fit the 161px a tile has, and a wrapped facts line puts the
  unevenness straight back.
- **The description holds its second line open** (`min-height: 2lh` while
  clamped, picture cards only). A one-line caption left the card 21.8px
  shorter inside than its neighbour, and the grid pays that out as a taller
  photograph, which is the unevenness the report names.
- **A two-row subgrid was built, measured, and taken out**, and this is the
  bullet above being confirmed rather than remade: it does equalise every
  picture (144px) and every foot (118.5px), and it puts the difference back
  as a hole, 75px under the shortest card. The three places to put that
  difference are still a bigger picture, a hole, or unequal cards, and the
  first is still the least bad.

Measured after, at 1440 on the same six seeded cards, in both themes: every
card with a caption and a fact is 240.7px with a 144px picture and a 95.7px
foot, the facts line is 32px whether it carries a chip or a word, the tail
under the last line is 0px, an opened fold takes the card's full width (159px
of 180px, no overflow) and the row grows with it, and contrast is 7.48 / 7.53 /
6.56 in light and 6.47 / 6.44 / 5.06 in dark.

## Phase 8 — control docks: one grammar for every tab's head (2 sessions)

**The instruction, verbatim** (after Phases 0–7 were built):

> I would like you to go through the tabs and subtabs and features and
> redesign the controls and elements often in the top docks or bottom docks
> professionally. A lot of them just feel like buttons and elements chucked
> at the top of the main panels. […] So many of the main control elements at
> the top of each tab or subtab feel soo fake and rudimentary, not
> professional, they aren't aligned, they just feel like features there and
> note intentionally designed. Use all your ui and ux skills, features need
> to be properly grouped, use drop downs if you see fit but don't over use
> them, think spacing, alignment, hierarchy, learnability (A MUST! ALL
> ELEMENTS AND CONTTOLS OF THE SAME TYPE AND FUNCTION NEED TO BE, ACT, AND
> PLACED THE SAME APP-WIDE), accessibility.

**Measured at 1440 before this phase** (`scratchpad/…/docks.js`, one row
per dock: controls, distinct control heights, kinds):

| Dock | Controls | Heights | What the eye reads |
| --- | --- | --- | --- |
| Graph toolbar | 28 | 1 / 24 / 25 / 32 | two segments, a select, five buttons, a filled "New note" *and* "Concept maps" in the head row, a count and a legend below — every feature the tab has, in a row |
| Library head + toolbar | 2 + 16 | 18 / 30 / 36 | two switches, a segmented sort **and** a sort select saying the same thing, a view segment, a filter select, then eleven chips |
| Notes toolbar | 14 | 32 / 36 | title, refresh, Select, view segment, search, Semantic, help, sort, page size |
| Whiteboard top bar | 17 | 32 / 36 | back, board select, rename, add, layout select, then search, minimap, five menus, Library, fullscreen |
| Documents header + strip | 9 + 26 | 28 / 32 / 36 | see DOCUMENTS_PLAN.md §3.2 |
| Timeline toolbar | 9 | 24 / 32 | View, a select, Today, Options, Highlight, a filter, a count, help |
| Reminders | 1 + 8 + 4 | 28 / 44 | a magic row, eight presets, four due buttons — three rows of ghost buttons |
| Chat | 1 + 6 | 28 / 36 | a filled New, then a toolbar of six at a different height |

Seven docks, seven layouts. Phases 1–5 fixed the *recipes* (heights,
radii, gaps); what they did not fix is the **grammar** — what goes where,
in what order, in what kind of control — and that is what "chucked at the
top" means.

### The dock grammar (the rule the whole phase enforces)

One dock, three zones, read left to right, the same on every tab and every
sub-tab:

```
[ Title · context ]  [ Search ]  [ Filter ▾ ] [ Sort ▾ ] [ View ⋮⋮ ]   ·   [ Primary ] [ ⋯ ]
   identity            find        narrow       order      how          ·     act      more
```

1. **Identity first**: the title (or breadcrumb) and, when the surface has
   one, its context chip (the board's name, the space, a count). Never a
   control.
2. **Find, narrow, order, view — in that order, always.** Search is the
   first control after the title on every list surface. Filters are one
   `Filter ▾` popover (the Notes sheet from Phase 5 is the model) or a chip
   row *below* the dock, never both. Sort is one select, never a segment
   and a select. View is one segmented control with icons (rows / cards /
   grid), never text.
3. **One primary action, at the right, filled.** `New note`, `New
   document`, `New board`, `Send`. A second filled button in a dock is a
   defect. Everything else is ghost or icon-only.
4. **Utilities at the far right, in a fixed order**: refresh, help, ⋯.
   Refresh is always the same icon in the same place; help is always last.
5. **Seven visible controls per row, then overflow.** An eighth goes into
   `⋯` or a named popover (`Options ▾`, `Insert ▾`). Menus are for verbs
   that are used sometimes; a verb used every minute stays in the row.
6. **One height, one baseline, two gaps.** `--control-h-lg` for every
   control in a dock, `--space-3` inside a group, `--space-4` between
   groups (Phase 2's numbers), the group boundary drawn by gap alone —
   never by a rule or a border.
7. **The same control does the same thing everywhere.** A segmented
   control changes *view*; a select changes *sort or filter*; a switch is a
   *setting* and lives in a popover or in Settings, not in a dock; a chip
   is a *filter you can see*. A control that breaks this on one tab is
   moved, not styled.
8. **Accessible by construction**: every dock is `role="toolbar"` with
   roving tabindex (arrow keys move between controls), every icon-only
   control has `aria-label` and a tooltip, every popover is
   `aria-expanded`/`aria-controls`, focus returns to the opener on close,
   contrast ≥ 4.5:1 measured with `pngpixel.py`.

### The work, surface by surface

Each is one commit, before/after inventory in the message, driven in
Chromium at 1440 / 1024 / 820 / 390.

1. **The lint first.** `tests/test_dock_grammar.py`: statically, for every
   element marked `data-dock`, at most one `.primary`/filled button, no
   `input[type=checkbox]` outside a popover, no text-only segmented control,
   and the utilities in order. `scratchpad/ui-sweeps/docks.js` becomes the
   runtime sweep: controls per row, heights per row, zone order.
2. **Graph** (worst first): title + count; search; `Layout ▾` and
   `Colour ▾` as one `View ▾` popover holding both segments and the
   options; saved views as one select with save/delete inside it; `Refresh`,
   `Export` into `⋯`; one primary (`New note`); `Concept maps` becomes a
   link in the identity zone. 28 → ≤ 9 visible.
3. **Library** (All and every sub-tab, one recipe): title; search; `Filter
   ▾` (semantic, include bin, kind); one sort select; one view segment;
   `＋ Create`; refresh; help. The chip row stays *below* as the visible
   filter. The duplicate segmented sort goes. Sub-tabs (Documents, Boards,
   Images, Files, Links, Contents, Skills) take the identical zones with
   their own words.
4. **Notes**: the toolbar from Phase 5 already has search-first and a
   filters sheet at ≤ 600; apply the sheet at every width as `Filter ▾`, one
   sort select, the view segment, `Select` into `⋯`.
5. **Whiteboard**: identity (back · board select · rename) left; search;
   the five menus stay (they are verbs used sometimes) but at one height
   and one gap; minimap, Library, fullscreen as utilities right; the map
   controls (chip, layout, Tidy) as the context chip and a `Layout ▾`.
6. **Documents**: DOCUMENTS_PLAN.md Phase 1 owns the editor's own chrome;
   the *Documents list* dock follows item 3.
7. **Timeline, Reminders, Chat, Dashboard**: Timeline onto the grammar
   (View segment with icons, `Options ▾`, search, Today as the primary);
   Reminders' three rows of ghost buttons become one row (the magic field)
   plus one `Presets ▾` popover, with the due chips as the visible filter;
   Chat's toolbar at the dock height with `New chat` as the one filled
   control; the Dashboard hero's clock and greeting as identity, its two
   quick actions as primary + ghost.
8. **Settings sections** already have one form recipe (Phase 5.1); their
   heads take the grammar's identity zone only.

Acceptance: `docks.js` reports **one height per dock**, zone order correct
on every tab and sub-tab, ≤ 7 visible controls per row, exactly one filled
control per dock; `test_dock_grammar.py` green; `errors.js` 0 findings at
all four widths; a keyboard-only pass (Tab into each dock, arrows across
it, Enter opens a popover, Escape closes it and returns focus) scripted in
`scratchpad/ui-sweeps/keys.js`.

### The two bars that are not docks (added by direct instruction)

- **The top bar** (`#top-bar`: logo, space switcher, notifications, theme,
  settings, lock, quit) and **the tab bar**: one height, one gap, utilities
  in the same order as every dock's, the space switcher as a select-shaped
  control rather than a button that looks like a tab. Phone: the tab bar
  moves to the bottom (Phase 9).
- **The whiteboard top bar** (`#wb-topbar`): a menu bar is its own valid
  pattern (Insert · Edit · Arrange · View · Board) but it follows the
  dock's zones — identity (Boards ‹, board select, rename, new; the Map
  chip, layout, Tidy), find (search, navigator), the menus, actions
  (Library, fullscreen) — one height, and its menus on the `.dock-menu`
  recipe so they close on pick, outside click and Escape like every other
  menu. The floating tool palette and the properties panel take the
  popover shell. Nothing on the board may feel like a different app.
### Built, second sitting

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", UI_MODERNISATION_PLAN.md) on 2026-09-09: a plan holds open work only.

## Phase 9 — responsive by device, on purpose (1 session)

**The instruction, verbatim:** "Also intentional and adjusted design that
alters specifically for smaller resolutions like for iPad, tablet, iPhone
etc."

Phase 5's phone work was reactive — each 390px finding fixed where it was
found. This phase makes the breakpoints a design, stated once:

| Width | Device | What changes, app-wide |
| --- | --- | --- |
| ≥ 1100 | desktop, iPad landscape with a sidebar | the layout above; sidebars open |
| 820–1100 | iPad landscape, small laptop | sidebars collapse to icons; docks keep seven controls; whiteboard properties panel becomes a sheet |
| 600–820 | iPad portrait | one column; sidebars are sheets from the left; docks keep identity + search + `Filter ▾` + primary, the rest in `⋯`; two-up card grids |
| < 600 | iPhone | the phone rules from Phase 5, applied to every tab: strips scroll, one control row, the primary action pinned bottom-right as a floating button, bottom docks (chat composer, the documents formatting bar) above the on-screen keyboard |

Rules: touch targets 44 × 44 CSS px at < 820 (`--target-min` steps up in
the 820 media block, not per component); `env(safe-area-inset-*)` on the
top bar, the status bar and every bottom dock; `hover:` styles gated behind
`@media (hover: hover)`; the tab bar becomes a bottom tab bar at < 600
(thumb reach), with the top bar keeping identity and utilities only;
`prefers-reduced-motion` honoured in the same block.

Acceptance: `errors.js` at **390, 820, 1024 and 1440**, 0 findings on
every tab and sub-tab; `all.sh` gains `WIDTH=820`; a `touch.js` sweep
(Playwright `hasTouch`, `isMobile`) taps every dock control on Notes,
Library and Chat at 390 and asserts each hit target ≥ 44px and that no tap
lands on two controls; screenshots at all four widths in the shots set.

## Built — Phase 9

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", UI_MODERNISATION_PLAN.md) on 2026-09-09: a plan holds open work only.

## Not in this plan

New features. The plan is subtraction and alignment; the feature backlog
(BACKLOG.md) waits until the shell is quiet.

## Phase 10 — the Liquid Glass adoptions (½ session)

DESIGN.md's "Taken from Liquid Glass and the HIG" rules 2, 3, 4, 8, 10 and
12, as the placed items below (INBOX 100 to 104). Rules 2, 3 and 12 are
built (100, 101, 103; moved to HISTORY.md, "Moved from the plans,
2026-09-09"). Rule 4's `.glass-clear` and `--text-on-glass` (102) are open
and carry a measurement that changes the question, below. Rule 10's
receding tab bar (104) is phone work and moves to Phase 11 with the rest of
it. Deliberately not taken: refraction and lensing (measured too costly),
title-case headers.

## Phase 11 — the phone, done properly (1 to 2 sessions, next session or later)

The owner, 2026-09-09: "the mobile view still needs quite a lot of work but
that isn't for this PR, scope and plan it for later sessions." Phase 9's
under-600 rules are moved here whole; this PR ships desktop and tablet.

**Decisions (made here).** The phone is a design of its own, not the
desktop squeezed: one column, one thing at a time, the primary action
within thumb reach, every panel a sheet, every list a full-width row.
Standalone (installed) mode and the browser tab get the same layout;
`env(safe-area-inset-*)` on every fixed edge. Nothing is hidden that the
desktop has; it is reached through a sheet or a ⋯ menu instead.

1. **Navigation.** A five-item bottom tab bar (Notes, Chat, Graph,
   Library, More) that recedes to icons on scroll down and returns on
   scroll up (INBOX 104), never hidden; More is a sheet with the rest of
   the tabs and Settings; the top bar keeps the title, the AI dot and one
   action.
2. **Notes.** Capture as a full-height sheet from the floating + button;
   the list as full-width rows with swipe actions (pin, bin) matched to
   the row's menu (the HIG rule); filters in a sheet; the note view as a
   page with a back button, its actions in a bottom bar.
3. **Chat.** The composer above the keyboard with the attachments and
   mode in one row; sources as a sheet; the sidebar as a sheet from the
   left edge; the popup agent unavailable on the phone (the chat is the
   agent).
4. **Graph.** Pan and pinch, tap to select, long-press for the node
   menu (no right click), lasso by long-press then drag, the docks as one
   bottom sheet with the colour rule, groups and views; the node panel as
   a sheet.
5. **Library and Files.** Two-up cards, the reader full-screen with a
   bottom bar; upload from the share sheet.
6. **Documents.** Read view by default, Edit as a full-screen sheet with
   the selection toolbar only (no strip), the outline as a sheet.
7. **Whiteboard and maps.** View and light edit only on a phone (pan,
   zoom, select, move, edit text); creation tools in a sheet; the mind
   map's + handles are touch-sized.
8. **Settings, dashboard, timeline, reminders.** Settings as a page list
   (sections as rows) with a back button; dashboard widgets one column;
   timeline as the table view; reminders as rows with swipe done.
9. **Touch.** 44px targets everywhere below 820 (Phase 9's token step
   holds), no hover-only affordance (every hover state has a tap
   equivalent), long-press replaces right-click app-wide.
10. **The status bar at 320: taken, the first way.** Measured 2026-09-12,
    after the header was made to fit: at 320 x 844 the page still scrolled
    sideways, 355 in 320, and the bar was the cause (its six surviving items
    need 355px: the AI dot 28, reminders 18, the nav group 147, undo 44, redo
    44, the agent dot 18, plus gaps). The bar is deliberately `nowrap`, since
    a wrapped status bar changes the height of the window's furniture as its
    own text changes, so of the two options here it took the scroller: below
    400 the bar scrolls with the `edge-fade` recipe every other overflowing
    strip uses, and nothing is hidden. Measured after: the page is 320 in 320
    and 360 in 360, and every width from 320 to 1024 is clean. The second
    option, one action and a sheet, is still the right end state and is this
    phase's own item 1.

11. **Gates.** A phone sweep (`scratchpad/ui-sweeps/phone.js`) at 390 x 844
    and 430 x 932 per tab: no horizontal scroll, no control under 44px,
    the primary action within the lower 40% of the screen, the composer
    above a simulated keyboard, every desktop action reachable in at most
    two taps (counted); errors.js and contrast.js at 390; a screenshot
    set for the owner per tab, because this is the one surface the owner
    checks on a real phone.

## Placed from INBOX, 2026-09-09

The owner's reports this plan owns, moved whole from INBOX.md with their numbers (never reused). Each becomes a phase row when its phase is written; until then this list is the phase.

Built and moved to HISTORY.md ("Moved from the plans, 2026-09-09"): 100 the
scroll edge effect, 101 the concentric corner token and its lint, 103 the
menus that open out of their opener.

102. **Clear glass with a scrim, and text on glass**: `.glass-clear` (blur
    only, `--card` at 30%) for the whiteboard's floating panels and the
    graph's docks over the art, paired with `--glass-scrim` (35% ink) when
    the surface is light; `--text-on-glass` one contrast step above
    `--text` on every blurred surface. Owner: Opus. Size S.

    **Measured before building it, and the numbers move the decision**
    (2026-09-09, 1440x900, the running app):

    - `--text-on-glass` has no deficit to close. The menu row on the Notes
      kebab and on the dock's Filter menu is **15.25:1** in light and
      **14.14:1** in dark (`scratchpad/ui-sweeps/onglass.js`), because those
      surfaces are `--modal-bg` at 96% rather than thin glass, and
      contrast.js reports **0** low-contrast items on every tab and ten
      Settings sections in *both* themes. A token that raises 15:1 to 16:1
      is a token nothing needs.
    - `.glass-clear` on `.whiteboard-floating-panel` would reverse a
      recorded decision. That panel was deliberately moved *up* to
      `--modal-bg`, with the reason written beside it in
      06-timeline-dialogs.css: at the page-card tier it "read visibly
      thinner than every sibling panel" over the board's own art.
    - The one surface where the variant is honest is the graph's floating
      zoom pill, which is `--card` plus `--glass-filter` over the animated
      background, and it shares the floating-control recipe with
      `.scroll-top`, so changing one changes both.

    **Recommendation, to be taken unless the owner says otherwise**: keep
    `.glass-clear` and `--glass-scrim` for a surface that actually floats
    over media (a whiteboard image background, the lightbox), build it with
    that surface rather than ahead of it, and drop `--text-on-glass` until a
    measurement asks for it. Rule 4 in DESIGN.md stays as the principle.

104. **The phone tab bar recedes on scroll** (icons only on scroll down,
    full on scroll up), never hidden. Moved to Phase 11: it is phone work
    and the phone gets its own session.

94. **Background animations: fix, refine and improve.** Owner: UI Phase 3
    follow-up (Opus): each style gets a measured frame cost, a still frame
    under Performance mode, no seams at the edges, the intensity slider
    changes something visible at every step.

    Three of the four are done and are in HISTORY.md ("Moved from the plans,
    2026-09-09"): the frame cost per style is measured and printed by
    `scratchpad/ui-sweeps/bgart.js` (aurora +21ms, constellation +20ms,
    waves +17ms, bubbles +17ms, mesh +28ms with a 167ms worst frame, over a
    16.6ms idle baseline, headless and therefore software-rasterised);
    Performance mode now stops the art dead, which it did not before because
    `bg-motion: moving` bypassed the only test it reached the art through;
    and there are no seams (the canvas is resized with the window and covers
    it exactly at 1440x900, 900x1200 and 1600x800). Two of the five styles
    also ignored the intensity slider's density and now scale with it.

    **What is left is the fourth**: does the slider change something a
    person notices at *every* step? Two ways of measuring it failed and both
    are written into the sweep so they are not repeated: ink on the canvas
    varies more between two boots of the same settings than it does across
    the slider (every style places its marks with `p.random`), and the frame
    cost at the two ends moves by less than the environment's noise. The
    honest next step is a human looking at five screenshots, or a change of
    design so the slider drives something with a large signature (the wash's
    own alpha, say) rather than the population alone.
60. **Dashboard "Jump to / Run a skill / stat tiles" section**: built, moved
    to HISTORY.md ("Moved from the plans, 2026-09-09"). The band fills its own
    width, carries a Continue pill and a fortnight sparkline, and every skill
    pill says when it last ran.

## Placed from INBOX, 2026-09-09 (the owner's evening batch)

Global, cross-surface. Phase 9 (responsive) and Phase 10 (Liquid Glass)
own most of these.

Five of these are built and are in HISTORY.md ("Moved from the plans,
2026-09-09"): the quick-nav chord's guide and its three new second keys, the
dashboard's back-to-top threshold, the heatmap's size, and the dark palette's
glass. What is left is below.

- "ctrl s for saving settings changes while on the settings modal doesnt
  work and it needs visual confirmation as well."
- "there are also still wrapping issues in the packages tab with the
  buttons, titles, and badges" (screenshot: the Tesseract row's title, its
  Installed badge, and Reinstall / Remove on three lines).
- "the panels and sidebars in windows actually go quite far down below
  where the scroll should stop, and the ai skill sidebar isnt 100%
  height."
- "the containers of all the ui in each tab page have hard corner
  rectangular edges so I want that fixed because the shadows make the cut
  off pretty obvious."
- "the links edit save and cancel buttons arent consistent" (screenshot: an
  accent pill beside a grey rounded rectangle at a different radius and
  height).
- "the words 'write something first' is at the bottom of the note capture
  tab when I didnt do anything?? maybe I fumbled a button": a validation
  message shown on load rather than on submit.
- "I was in the ocr workspace and the model dropdown combobox at the top
  bar didnt open."
- "I think the screen shots on the readme need an update from all the ui
  changes."
