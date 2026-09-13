# The whiteboard: controls that belong together, tools that behave

**Status: written by Fable by direct instruction ("the whiteboard panels
and tools need a better modern redesign still, this is horrendous"; "the
whiteboard control elements dont have that joined and cohesive feel"),
from the owner's screenshots and the code. Executed after
DOCUMENTS_PLAN.md and before MINDMAP_PLAN Phases 4 to 5, which build on
the same canvas.**

Back to [../ROADMAP.md](../ROADMAP.md).

## 1. What exists (checked in the code)

`frontend/whiteboard.js` (9,767 lines) draws an infinite dotted canvas with
object kinds `note`, `document`, `file`, `image`, `sketch`, `text`, `square`,
`circle`, `arrow`, `topic`/`node`/`radial` (mind maps) and `object`. Chrome:
a top bar on the Phase 8 grammar (Boards, board picker, rename, add, Map
toggle, layout select, Tidy, search, minimap, Insert/Edit/Arrange/View/Board
menus, Library, fullscreen); a bottom tool strip of 16 round buttons in
five groups (select, pan, lasso; pen, marker, eraser, fill; line with a
caret; sticky, text, image; straight and curved connectors; delete, undo,
redo); a zoom strip bottom right; a floating selection bar (duplicate,
style pipette, fill, send back, bring front, export, delete); a
properties panel on the right (copy style, guide colours, colour, width,
start cap, end cap, stroke style, and the arrange block: group, ungroup,
align, space, extract notes); the export popover; the new-board dialog.

## 2. Why it disappoints (from the screenshots, each checked in the code)

1. **Five surfaces, five recipes.** The top bar is the dock grammar; the
   tool strip is 16 separate circles on a pill; the selection bar is a
   third shape; the properties panel is a fourth (a scrolling column of
   label/control pairs with no sections); the arrange block is a fifth,
   and its buttons draw an icon on top of their label ("Ungroup" with the
   scissors through it) because the icon-only recipe and the labelled
   recipe are both applied. Nothing says "this is one tool".
2. **The tool strip does not say what a tool does or which is active
   beyond one filled circle**, has no labels, no shortcuts shown, and the
   line tool's caret opens a menu that is the only sub-tool picker in the
   strip. The colour of the ink you are about to draw is not visible
   anywhere on the strip.
3. **The export popover** opens as a 1,300px list (five sections of three)
   under the selection bar and runs off the screen (screenshot). The
   choices are a matrix (scope: selection / screen / board; format: image
   library / PNG / SVG / PDF / outline) rendered as a list.
4. **Properties lie or hide.** A drawn line reports Start cap Arrow and
   End cap Arrow when only the end has one (the default for the line tool
   is written into both selects); the arrange block offers Space and
   Group but no align-centre, no distribute-gaps, no same-size.
5. **Selection handles differ by kind** (notes show a thin rectangle with
   outside handles; shapes show handles on the corner with a rotate stem)
   so the same drag reads as two different objects.
6. **The highlighter draws opaque** and the quick-sketch highlighter
   "needs reworking" (owner): no multiply blend, no width, no straightness.
7. **A new mind map's root sits under the top bar; dragged map nodes leave
   their edges behind** (a regression from the marquee fix; owner's
   screenshot). Tidy never measured past five nodes.
8. **No keyboard model.** V, H, P, T, R, O, L, Delete, Ctrl+D, Ctrl+G,
   arrows nudge: the strip has none of it and the help does not say.

## 3. The target, in one paragraph

One canvas with three chrome pieces that share one recipe: the top bar
(the dock grammar, unchanged), a **tool rail** (one panel, tools as ghost
buttons with an active state, each with a tooltip naming its key, one
ink swatch that shows the pen colour and opens the colour picker, sub-tools
as a small flyout on long-press or the caret), and a **context bar** that
replaces both the floating selection bar and the properties panel: it
appears above the selection, shows only what applies to the selected
kinds (colour, stroke, caps for lines; fill and corner for shapes; font
for text; align/distribute/group when two or more), and opens a compact
popover for the long tail. Export is a dialog with two rows of segments
(scope, format) and one primary button. Handles are one recipe for every
kind. Every tool has a key and every key is in the tooltip and the help.

## 4. Decisions made (do not re-decide)

1. **Tool rail, not circles.** `.wb-rail` is a panel (card surface, glass
   edge) holding `.wb-tool` ghost buttons at `--control-h-lg`; the active
   tool is `accent-soft` with `aria-pressed`; groups are separated by a
   hairline; the ink swatch is the last group. Bottom-centre on desktop,
   bottom full-width on phone (Phase 9 already moved it).
2. **One context bar** (`.wb-context`) replaces `.wb-selection-bar` and
   `#wb-properties-panel`. Built from a table of kind → controls, so a new
   kind gets its controls by adding a row, not a panel. The long tail
   (guide colours, copy style, extract notes) lives in a "..." popover on
   the bar.
3. **Arrange is a segment group in the context bar**: align (left,
   centre, right, top, middle, bottom), distribute (horizontal, vertical),
   same size (width, height), group/ungroup, order (front, back). All
   eleven exist as functions or are ten lines each; the block in the
   screenshot is missing five of them.
4. **Export is a dialog** (`.modal` recipe): scope segment (selection,
   screen, board), format segment (PNG, SVG, PDF, Markdown outline, OPML,
   Save to image library), one primary "Export". The popover goes.
5. **Caps default per tool**: line tool = none/none, arrow tool = none /
   arrow, connector = none/none; the properties read the object, never
   the tool default (bug 4).
6. **One handle recipe** for every kind: eight handles, rotate stem on
   top, the bounding box at `--accent` 1px; a note's inner card no longer
   draws its own outline.
7. **Highlighter** = marker with `mix-blend-mode: multiply` at 40%
   opacity, width 12 to 24, Shift for straight; the quick-sketch pad uses
   the same tool code, not a copy.
8. **Keys** (also in tooltips and help): V select, H pan, L lasso, P pen,
   M marker, E eraser, N sticky, T text, I image, C connector, A arrow,
   R rectangle, O ellipse, Delete, Ctrl+D duplicate, Ctrl+G group,
   Ctrl+Shift+G ungroup, arrows nudge 1px (Shift 10px), + / - / 0 zoom,
   F fit selection, Escape deselect. Same as the graph where they overlap.
   Two letters this list did not settle, decided while building Phase 1 and
   followed from here (the interrupt rule's point 4: a decision is recorded
   in the plan it affects):
   - **The board has two connectors and this list names one letter.** C is
     the straight link, Shift+C the curved one. The shifted form of the same
     letter rather than a second letter, so the pair reads as one idea; the
     built rail kept K for lasso and L for line, which is why L is not the
     lasso here.
   - **N was already the board overview** (bare, since the overview was
     built) and this list gives it to the sticky note. The sticky takes N and
     the overview moves to Shift+N, which is the same shifted-pair shape, and
     the top bar's button and the board help say so.
9. **Mind map root placement**: new root centred in the visible canvas,
   below the top bar's inset; edges are re-drawn from the node model on
   every drag frame (the marquee fix must not have detached them; add the
   sweep check that a dragged node's edge endpoint moves with it).

## Built, 2026-09-09: one surface per panel, and the Arrange section

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", WHITEBOARD_PLAN.md) on 2026-09-09: a plan holds open work only.

## 5. Phases

### Phase 1: the rail and the keys: BUILT, 2026-09-12
Moved to HISTORY.md ("Moved from the plans, 2026-09-12", WHITEBOARD_PLAN
Phase 1): a plan holds open work only. The gate lives on in
`scratchpad/ui-sweeps/whiteboard.js` (13 checks, green at 1440x900 light
and dark and at 390x844).

### Phase 2: the context bar: BUILT, 2026-09-12
Moved to HISTORY.md ("Moved from the plans, 2026-09-12", WHITEBOARD_PLAN
Phase 2): a plan holds open work only. Its gate lives on in
`scratchpad/ui-sweeps/whiteboard.js` (24 checks, green at 1440x900 light
and dark and at 390x844).

### Phase 3: export dialog, handles, highlighter: BUILT, 2026-09-12
Moved to HISTORY.md ("Moved from the plans, 2026-09-12", WHITEBOARD_PLAN
Phase 3): a plan holds open work only. Its gate lives on in
`scratchpad/ui-sweeps/whiteboard3.js` (12 checks, green at 1440x900 light
and dark and at 390x844). Two parts of decision 7 are **open**, with their
measurements: the quick-sketch pad still has its own copy of the
highlighter rather than sharing this code, and multiply is worth 20
luminance units a pass on a light board and 3 on a dark one, which is the
objection the pad's own comment in `app.js` already records. Both are in
[`agent-remaining/whiteboard-phases.md`](agent-remaining/whiteboard-phases.md).

### Phase 4: mind map regressions and Tidy: BUILT, 2026-09-12
Moved to HISTORY.md ("Moved from the plans, 2026-09-12", WHITEBOARD_PLAN
Phase 4): a plan holds open work only. Its gate lives on in
`scratchpad/ui-sweeps/wbphase4.js` (19 checks). Root placement and the
per-frame edge follow were already built and are now measured (0px endpoint
gap over 29 edges, mid-drag, for a leaf, a whole branch and a marquee pair);
Tidy with thirty nodes leaves no overlaps in any layout, which took one fix:
a radial map past about twenty nodes compressed its rings into less arc than
its nodes occupied.

## 6. Consistency rules

Tokens only; the rail and the context bar are the same `.panel` surface
the docks use; buttons are the six recipes of WORLD_CLASS_PLAN §1.2; menus
are the one menu recipe; dialogs the modal recipe; keys in KEYMAP.

## 7. Not verified until built

Touch: the rail's long-press flyout on a tablet; pen pressure for the
marker; whether the context bar should pin to the top of the canvas on a
phone instead of floating. **Floating is measured** (2026-09-12, Phase 2):
at 390x844 the bar wraps to 348px wide and 54px (an image) to 208px (an
arrow, four rows) in a 364x604 canvas, sits clear of the selected item at
every kind, and never leaves the canvas. That is the case *for* floating and
against pinning; what is not measured is a real finger on a real tablet,
which is what the rest of this section is waiting for too.

## 8. Research: tldraw, Excalidraw, Miro, FigJam, and what it changes here

Written from working knowledge of the products, not a live teardown;
confirm in the product before building the phase where it matters.

- **tldraw** (MIT-licensed core, the strongest reference for a web
  canvas): one vertical or bottom tool rail of ghost buttons with a
  single active state; a *style panel* that shows only the properties
  the selection can take (colour, fill, dash, size, font, align) and
  collapses to an icon when nothing is selected; selection handles are
  identical for every shape; arrows bind to shapes and re-route; keys
  V H D X R O A L T N F E, with the key shown in each tooltip. Implication:
  decisions 1, 2, 6 and 8 are tldraw's shape almost exactly, which is a
  good sign, and tldraw's style panel confirms that "only what applies"
  is the right rule for the context bar.
- **Excalidraw** puts the property panel at the left as a stacked card
  and the tool rail at the top; its export dialog is exactly a scope
  toggle (selection / whole) plus format buttons with a preview.
  Implication: decision 4's dialog should include a live preview
  thumbnail; it costs one `toBlob` and prevents the "which scope did I
  pick" mistake.
- **Miro** and **FigJam** show a *contextual toolbar* floating above the
  selection for the common properties and put the long tail in a side
  panel. Implication: the "..." popover in decision 2 is the same split;
  keep the bar to at most seven controls and measure it.
- **Highlighter**: FigJam and Apple Freeform draw highlighter strokes
  with multiply blending and a fixed wide nib, straight with Shift.
  Implication: decision 7 is the norm.
- **Mind map tools** (XMind, Coggle): the root is created centred and
  selected in edit mode; child nodes are created on Tab at the parent's
  side and the layout re-flows; edges are part of the node model, not
  separate objects. Implication: decision 9, and MINDMAP_PLAN Phases 4 to
  5 should treat edges as derived from the tree, never as objects that
  can detach.

## Placed from INBOX, 2026-09-09

The owner's reports this plan owns, moved whole from INBOX.md with their numbers (never reused). Each becomes a phase row when its phase is written; until then this list is the phase.

12. **Whiteboard: export-selection popover opens a full-height list in the
    wrong place; arrow drawn shows both caps as Arrow in properties;
    missing align-centre and distribute-gaps; the arrange panel's buttons
    are unreadable (icons overlapping text).** Owner: WHITEBOARD_PLAN.md.
    **The caps part only is fixed** (my scope was "12 only the caps part"):
    `wbDetectArrowStyle`'s own regex scan included the shaft's leading `M`
    (matched separately, one line above, specifically to exclude it) in
    its search for head markers, so a shaft with zero start caps still
    measured a false zero-distance hit on its own start point and reported
    "both". Slicing the shaft's own match off the string before scanning
    fixed it; verified live (`startcap: "none"`, was `"arrow"`). The
    export-popover placement, align-centre/distribute-gaps and the arrange
    panel's icon/text overlap are **still open**, not touched this session.
25. **Whiteboard: the edge anchor outline on note objects differs from
    every other object kind.** Decision: one anchor recipe for all kinds
    (the shape one; the note one goes). Owner: WHITEBOARD_PLAN Phase 1.
43. **(the top bar's menus: fixed, e1e395b; the rest is Phase 1)**
    **Whiteboard bottom tool rail and the properties panel** are not on
    the refined recipes (the top bar is). Owner: WHITEBOARD_PLAN Phase 1.
    **Done, one part:** the five top-bar menus (Insert, Edit, Arrange, View,
    Board) clipped at the bottom of the panel, the View menu screenshot in
    31. They were already capped to the window, which was not the bug:
    measured at 1280x640, View and Arrange ended at y=628 inside a 640px
    window while `#library-view-whiteboard` (`overflow: hidden`) ends at
    y=579, so the last 49px was cut off by an ancestor. Now on 31's recipe
    (escape the clipper, then cap, then scroll). kebab-viewport.js sweeps
    all five at 1440x900, 1280x640 and 1280x420: 15 cases, all OK. The tool
    rail and the properties panel are still open.
47. **Notes (10) and Library (9) still count over the seven-control
    ceiling** (`scratchpad/ui-sweeps/docks.js`), same as Graph did before
    this batch. Graph's fix (moving `#graph-view-picker` into its More menu)
    is not a decision this item can reuse for these two: graph.md section 3
    named its own two candidates for graph specifically, and named nothing
    for Notes or Library beyond the counts, so guessing which of their
    controls moves where is a design call, not a mechanical one (CLAUDE.md
    §2 rule 3 -- a missing decision is recorded, not remade). Both docks'
    inflated counts are partly an artefact of how `docks.js` counts, worth
    knowing before picking a fix: a native `<select>` is auto-enhanced into
    three counted elements (the select, its `.select-shell`, its
    `.select-opener`), and a `.seg` segmented control counts as one plus one
    per visible option, so Library's sort select and its two-button
    Cards/Rows segment alone are 6 of its 9, and Notes' sort select and its
    two-button Rows/Cards segment are 7 of its 10. Recommendation: before
    moving anything, decide in UI_MODERNISATION_PLAN Phase 8 whether the
    ceiling counts *controls a person reasons about* (a segmented view
    toggle is one decision, not three) or literal DOM elements as `docks.js`
    does today; if the latter stands, the same "into an existing menu"
    treatment graph got is available for Library's `#library-sort` (into
    Filter or More) and Notes' `#note-sort` (into a menu of its own), which
    would need one new decision line each rather than either being moved on
    a solo guess. Owner: UI_MODERNISATION_PLAN Phase 8.

### Performance on small laptops, measured 2026-09-08 23:30 UTC (Chromium, 1366x768, no GPU)

Numbers from `scratchpad/weight.js`: first load 6.7 MB over 71 requests
(uncompressed; the gzip layer is scoped to non-streaming API replies and
does not cover static files); unlock to ready 4.0s; idle traffic 4
requests a minute (was 14 in the audit); DOM 5,870 elements; JS heap 16 MB;
four blurred surfaces covering 32% of the viewport at rest; frame p95
16.7ms scrolling Notes. Script weight: app.js 1.6 MB, whiteboard.js 469 KB,
library.js 348 KB, documents.js 280 KB, graph.js 177 KB, all loaded at boot,
plus d3 and p5 vendored; 124 `backdrop-filter` rules across the CSS.

48. **Every module parses at boot, whichever tab opens.** Decision: load
    whiteboard.js, documents.js, library.js and graph.js on first use of
    their tab (a small loader in app.js, `tests/test_frontend_load_order.py`
    updated for the split; boot stays synchronous for app.js and the
    guards). Expected: the parse cost of about 1.3 MB of JavaScript leaves
    the startup path. Owner: Opus. Size M.
64. **Whiteboard properties panel, "needs a massive redesign and fix"**
    (three screenshots, 01:30): Copy style row, Guide colours (three swatch
    rows), then Group / Ungroup overlapping each other, an arrow button, the
    three align icons, two Space buttons and Extract notes "just chucked at
    the bottom". Owner: WHITEBOARD Phase 1 (properties panel), Opus.
    Decision: sections with a heading each (Style, Guides, Arrange, Notes);
    Arrange as one icon toolbar row on the dock recipe (align x3, distribute
    x2, group/ungroup as a pair) with tooltips, never label buttons that
    overlap; Extract notes as the section's one text button; measure that
    no two controls' rects intersect and the panel scrolls inside.
65. **Whiteboard panels "feel unrefined": the buttons look separate from
    the panels** (bottom tool bar, zoom pill, properties). Same fix as
    INBOX 52: one surface per panel, hairline dividers, no per-control
    background except the active tool. Owner: WHITEBOARD Phase 1.
56. **Library image cards, "really ugly"** (screenshot): thumbnail, file
    name, "Used in" chip, a Description bullet with Show more, a model chip,
    a "Text in this image" bullet with Show more, a "Read by ..." chip: six
    ranks of information at one weight, chips for provenance that read as
    actions. Owner: Opus, next slot, with INBOX 52 (whiteboard bottom bar).
    Recommendation: thumbnail with the file name on it; one line "Used in
    <chip>"; the description as one paragraph with a "More" toggle; the OCR
    text folded under a single "Text in this image" disclosure; provenance
    as one muted line at the foot ("Described by X, read by Y"), no chips.
52. **Whiteboard bottom bar: the tool groups "feel separate from the
    panels and not integrated"** (screenshot: seven pill groups with their
    own backgrounds and dividers inside one bar, and the zoom pill on the
    right in a different style). Owner: WHITEBOARD Phase 1 (bottom rail),
    with the mind map agent's whiteboard work merged first. Recommendation:
    one bar surface, groups separated by a hairline divider only, no
    per-group background; the zoom pill on the same recipe. Size S.

## Placed from INBOX, 2026-09-09 (the owner's evening batch)

- "can the whiteboard arrange tools be better structured??" (screenshot):
  ten icon-only buttons under one ARRANGE heading in a ragged 2-3-3-2 grid.
  Three labelled sub-rows (Group, Align, Distribute), three per row, each
  with a title and an aria-label.
- "the view dropdown is still overly short", and separately "on the
  mindmap, the view dropdown is even more visually broken". Both are the
  escaped-menu height, fixed on 2026-09-09 (`place()` now measures at
  `max-height: none` and caps against the room the trigger actually has).
  Retest both at 1440 and 820 before closing.
- Console, 2026-09-09: `POST /whiteboard/nodes` answered 422 with
  `entry_id: Input should be a valid integer, input: null`, and the app
  logged "Error creating node: {}". A node created with no backing entry
  sends null where the schema wants an int. Two halves: the schema should
  accept a node with no entry (a plain shape is not a note), and the
  client's error path should say what failed rather than print an empty
  object.
