# The whiteboard: what Phases 1 to 4 left

> Companions: [WHITEBOARD_PLAN.md](../WHITEBOARD_PLAN.md) ·
> [MINDMAP_PLAN.md](../MINDMAP_PLAN.md) · [mindmap.md](mindmap.md) ·
> [../../DESIGN.md](../../DESIGN.md)
>
> Written 2026-09-12 by the agent that built WHITEBOARD_PLAN Phases 1, 2 and
> 3, and extended the same day by the agent that built Phase 4. Everything
> below was measured in a real Chromium against the running app, not read off
> the source. The four phases' own accounts, with their numbers, are in
> HISTORY.md ("Moved from the plans, 2026-09-12").
>
> **Phases 1 to 3 landed whole in `353aef8`, and this file landed with them**,
> so nothing in it was stale when Phase 4 started; the six open items below are
> the same six, re-read against the running app and still open.

## The sweeps that gate this surface

| Sweep | Checks |
| --- | --- |
| `scratchpad/ui-sweeps/whiteboard.js` | **24**: the rail and its keys (Phase 1), the context bar and the arrange actions (Phase 2). Green at 1440x900 light, 1440x900 dark and 390x844. |
| `scratchpad/ui-sweeps/whiteboard3.js` | **12**: the export dialog, the handle recipe and the highlighter's blend (Phase 3). Green at the same three. |
| `scratchpad/ui-sweeps/wbphase4.js` | **19**: root placement on open and on re-open, the edge follow through three kinds of drag measured mid-drag, and Tidy with thirty nodes in all three layouts (Phase 4). Green at 1440x900 light. |

Run them against a **fresh** data dir (`serve.sh <port> /tmp/mm-wbN`): both
seed boards and objects and assert counts, so a dir left over from an earlier
run carries other boards into those checks. They are split at 110s, not by
subject: one sweep running all three phases took longer than a Bash call gets.

## Left to do

### 1. Decision 7's other half: the quick-sketch pad still has its own copy

Decision 7 ends "the quick-sketch pad uses the same tool code, not a copy".
The pad is a `<canvas>` in `frontend/app.js` (`SKETCH_HIGHLIGHTER_ALPHA` 27284,
`SKETCH_HIGHLIGHTER_COMPOSITE` and `SKETCH_HIGHLIGHTER_LINE_JOIN` 27301,
`SKETCH_HIGHLIGHTER_WIDTH_MULTIPLIER` 27309, painted at 27455 and 27530); the
whiteboard is SVG paths in `frontend/whiteboard.js`. They are not one function
apart, they are two rendering models apart, which is why this was left rather
than faked with a shared constants block.

**Not started, and deliberately not half-started:** the two are now at
different values (the whiteboard is 0.4 and multiplies, the pad is 0.35 and
does not), and a run that only copies the numbers across would take the pad
into the exact problem its own comment was written to record (below).

**Next step**: decide whether the pad becomes an SVG surface (and then it can
share `wbHighlighterWidth` and the blend outright) or stays a canvas with one
shared table of "what the highlighter is". That is a design call, not a
mechanical one, so it wants a line in the plan first.

### 2. Multiply is worth 3 luminance units on a dark board, and 20 on a light one

Measured with `scratchpad/pngpixel.py` on two crossing highlighter strokes,
same board, same colour, both themes:

| | bare board | one stroke | both |
| --- | --- | --- | --- |
| light | 252.9 | 229.6 | 211.5 |
| dark | 26.4 | 23.6 | 22.0 |

Multiply darkens, and a dark board has almost nothing left to darken.
`SKETCH_HIGHLIGHTER_COMPOSITE`'s own comment in `app.js` predicted exactly
this ("the same yellow that tints a white page turns to mud on a dark one, and
this app has a dark theme") and is why the *pad* has no blend mode at all.

Decision 7 says multiply, so multiply is what is built: a decision is not
remade by the session that meets it. **Recommendation for whoever takes it**:
`screen` in dark and `multiply` in light, which is what a highlighter does
perceptually on either ground (it makes the marked area stand out, not darker).
One wrinkle to design around rather than discover: the blend is an inline style
because the export clones these nodes into a standalone SVG where a stylesheet
does not follow them, so a theme-switched value has to be re-applied on a theme
change, not left to a media query.

### 3. A sketch's handles scale with the zoom; a card's do not

Measured at zoom 1, where the gate compares them: 10x10 on every kind. The
card and text-box handles are absolutely positioned HTML at a CSS pixel size,
so they stay 10px at any zoom; a sketch's are SVG rects of 10 *board units*
inside `#wb-zoom-group`, so at 2x they are 20px on screen and at 0.5x they are
5px. The selection box itself is already zoom-proof
(`vector-effect: non-scaling-stroke`), so this is the handles only.

**Next step**: either draw the sketch handles at `10 / transform.k` board units
and re-render them on zoom (cheap, but `wbRenderSketchHandles` is not currently
called from the zoom frame, and the pan path is deliberately kept free of work
for reasons `wbUpdateSelectionBar` records), or move them out of the zoom group
into screen coordinates (correct, but the drag maths in that function all
assume board units). Measure the zoom frame before choosing.

### 4. The context bar at phone width is tall, and the plan's open question is half answered

WHITEBOARD_PLAN §7 asks "whether the context bar should pin to the top of the
canvas on a phone instead of floating (measure both at 390)". Floating is
measured, at 390x844 in a 364x604 canvas: 269x54 for an image, 348x112 for a
line, 348x160 for a shape or a text box, 348x208 for an arrow. It is always
inside the canvas and always clear of the selected item. What is not measured
is pinning, because nothing pins yet.

**Next step**: if this is taken, the cheapest honest comparison is a
`data-wb-anchor="top"` branch in `wbUpdateSelectionBar` (the placement already
has three cases) measured against these five numbers.

### 5. The whiteboard's top bar is 13 controls

`docks.js` reports `#wb-topbar` with 13 controls at 1440, against the dock
grammar's ceiling of seven. Out of scope for these phases (the plan's §3 says
the top bar is "the dock grammar, unchanged"), and it is the same counting
question INBOX 47 raises for Notes and Library: a `<select>` is three counted
elements and a `.seg` is one plus one per option. Owner: UI_MODERNISATION_PLAN
Phase 8, with INBOX 47.

### 6. The old export popover's CSS still names it in grouped selectors

`.wb-export-menu`'s own rules are gone from `06-timeline-dialogs.css` and
`07-whiteboard-misc.css`, and nothing builds the element any more. The name
still appears in `08-consistency.css` in selector lists that cover every menu
in the app (lines 81, 132, 166, 183, 194, 302, 321, 334, 340, 1157) and once in
the `[data-glass="off"]` list in `03-dashboard-widgets.css`. Removing it from
those is a one-line-per-site sweep with no behaviour behind it; it was left
because those files were being edited by another agent the same night.

## Phase 4: built 2026-09-12, and what it found

Its account is in HISTORY.md ("Moved from the plans, 2026-09-12",
WHITEBOARD_PLAN Phase 4). In one line each:

- **Root placement and the edge follow were already built**, in
  `wbFrameMapOnOpen` and in the three places that collect a drag's edges
  (`wbMapEdgesFor` at `objDragStart`, `wbCaptureBulkMoveOrigin`,
  `wbMapBranchDragOrigin`). What they lacked was a number, and
  `scratchpad/ui-sweeps/wbphase4.js` is it: 0px worst endpoint gap over 29
  edges, mid-drag, for a leaf, a whole branch and a marquee pair.
- **Tidy is clean at thirty nodes** in `tree-right` and `tree-down` (0
  overlapping pairs, minimum gap 26 board units, which is
  `WB_MAP_GAP_BREADTH`), and was **not** in `radial`: 6 overlapping pairs, the
  worst 38x28. Fixed in `wbMapTidyPositions` by letting the rings widen when
  the breadth span needs more than one turn of the circle. 0 pairs after.
- **MINDMAP_PLAN Phases 4 and 5 are not open work.** The plan's §11 records
  them as built and moved to HISTORY on 2026-09-09; a brief that pairs them
  with this phase is naming them by their old status. What is actually left of
  the map is [mindmap.md](mindmap.md)'s "Left to do", which is §12.1's dock
  menus and five sub-items, not Phases 4 to 5.

What Phases 1 to 3 changed underneath Phase 4, kept here because it is still
what an agent arriving at this surface needs to know:

- **The properties drawer is gone.** `#wb-properties-panel` and
  `#wb-selection-bar` no longer exist. Anything that reached for a property
  row by id now reaches into `#wb-context`; the ids of the controls themselves
  are unchanged, which is what kept every handler working.
- **The map's node edit strip is untouched** and still shares the placement
  function with the context bar (`wbUpdateSelectionBar`, which hides whichever
  of the two this selection has not earned). The "one bar over this canvas,
  never two" rule now has a third case: with nothing selected and a drawing
  tool held, the context bar parks over the rail and marks itself
  `data-wb-anchor="rail"`, and the pan frame leaves it alone. A map surface
  that wants to show something in that state has to clear that attribute.
- **The rail's Ink group carries `data-wb-surface="board"`**, so it is hidden
  on a map by `wbSyncMapChrome` like the pen and the shapes. If Phase 4 gives
  a map a drawing tool, that group needs revisiting.
- **C is the straight connector on a board and folds a branch on a map**, and
  the two never meet because the map branch runs only with a topic selected
  and returns. N is the sticky note and Shift+N the overview. Both are
  recorded in the plan's decision 8; a Phase 4 key must not take either.
- **The drag and pan lag is still unattributed** and nothing here was aimed at
  it. Phases 1 to 3 did remove one document-wide query from the pan frame's
  no-selection path (it now reads one dataset property), which is a change in
  the right direction and is *not* a claim the report is fixed. The three dead
  ends are in [mindmap.md](mindmap.md) under "the drag and pan report, third
  time"; start past them.

## What could not be verified

- **One viewport pair and two themes.** 1440x900 and 390x844, light and dark,
  DPR 1. Nothing was seen at 1024, at 820, at DPR 2, or on a real touch device.
- **PDF export.** It goes through the browser's print dialog, which Playwright
  cannot complete, so the PDF column of the scope-by-format matrix is the one
  pair no sweep asserts. The other eight are asserted as real files.
- **Pen pressure and the rail's long-press flyout on a tablet**, unchanged from
  the plan's §7: both were written against `pointerType: "touch"` and neither
  has been driven by a touch device.
- **The highlighter's Shift-straight** is asserted as code and driven with the
  mouse, but the sweep's own highlighter check draws two freehand runs; the
  straight branch is exercised by hand, not by the gate.
