# Graph: what is left

Phase 2 of `GRAPH_PLAN.md` is complete, and its "Built, Phase 2" section
carries the numbers. The five items this file used to list from that phase
are done: the pan that lit up a note nobody pointed at (INBOX 28, fixed on
the branch in 0b26491 and confirmed with an assertion here), the gear button
(INBOX 21), the options panel (INBOX 41), the spread, full screen (INBOX 29)
and the label collision pass with its probe (INBOX 27).

This file's own three items (INBOX batch C, 2026-09-08) are done too:

1. **Saved views now store gravity/spread, not the boolean that never
   existed.** `graphCaptureView()`/`graphApplyView()` read and wrote
   `.checked` on `#graph-physics`, the Physics section div, not a checkbox;
   every saved view stored `physics: true` regardless of the sliders. Fixed
   to capture/restore `gravity`/`spread` directly (the two things "physics"
   means to a reader); `#graph-show-entities`/`#graph-show-documents` were
   the same bug on two more controls (the real ids are
   `#graph-entities`/`#graph-documents`), fixed alongside since it was the
   same two functions. `scratchpad/ui-sweeps/graphphysics.js` sets the
   sliders away from default, saves a view, moves them again, restores, and
   reads the DOM and localStorage back; confirmed it fails against the
   pre-fix code by stashing.
2. **The options panel no longer scrolls at 1440x900.** 627px of list in a
   488px cap before; 418 vs 418 (no scroll) after, both themes. Physics'
   "Unpin all" and Links' "Suggest links" each moved off their own row and
   onto their section's header row (`.dock-menu-section-head`, the two
   candidates this file named); `.dock-menu-section`'s own padding/gap
   tightened, scoped to `.graph-options` only so no other dock menu in the
   app lost any room (the third, last-named candidate); and, beyond what
   either candidate covered on its own, the "Show" section's six
   independent switches now sit two to a row (`.graph-toggle-grid`, one
   column again below 820 where touch targets grow to 44px) rather than
   one, which is where most of the remaining room came from. No control
   shrank: every switch is still the same 30px `.graph-option-row` height
   it was.
3. **The graph dock is at six controls, under the seven-control ceiling.**
   The saved-views select (`#graph-view-picker`) moved into the More menu,
   beside Save/Delete which already act on whatever it has selected;
   `docks.js` reads 6 now, was 9. Notes (10) and Library (9) are still over
   the ceiling: INBOX 47 records why this batch didn't extend the same
   move to them (graph.md named its own two candidates for graph
   specifically; nothing was decided for those two docks, and guessing is a
   design call CLAUDE.md's rule 3 says to record, not remake).

Everything below was measured against `scratchpad/ui-sweeps/serve.sh 8861
/tmp/mm-graph3` (35 notes, 55 links), a second server on 8862 with a
300-note, 571-link fixture (both built by `scratchpad/graph-fixture.js`),
and, for this batch's three items, `scratchpad/ui-sweeps/serve.sh 8891
/tmp/mm-batch-c` with a 5-note fixture. The phase sweep is
`scratchpad/ui-sweeps/graph2.js`, which asserts every number it prints and
exits non-zero with a FAIL block; its one FAIL right now ("a search for one
note drew no label for it") predates this batch, confirmed by stashing this
batch's changes and rerunning.

## INBOX 114's two graph reports, 2026-09-12 (done)

Both reproduced before either was touched, on a 43-note, 60-link fixture
(`scratchpad/graph-fixture.js` into `serve.sh 8851 /tmp/mm-graph2`).

1. **"The tree view on the graph is still broken"** was a race, not the
   layout. `renderGraphCanvas` lays out the hierarchy, replaces `gcNodes`,
   then calls `gcStop()`, and `gcStop` posts a message: it cannot unsend a
   tick the worker has already posted. The tick handler writes positions
   **by index** with nothing to say which simulation they came from, so a
   tick from the force run delivered after the switch wrote the old
   solution over the tree's first 43 positions. Fixed with an epoch on the
   worker protocol (`ba892b0`): bumped wherever the node array is replaced,
   sent with `init`, echoed on every `tick` and `end`, and a mismatch is
   dropped whole. A computed layout never sends an `init`, so nothing the
   worker says can match it. `graphtreerace.js` switches to the tree at
   every 100ms of the cooling curve: 469.2px and 962.3px of depth-band
   spread at one of fifteen moments before, 30 of 30 clean after.
   Note for the next reader: `7a7bec1`'s unmeasured-box fix was checked
   here as the other candidate and **not reproduced** on the canvas
   renderer (`graphcold.js`: the box is 0x0 before the tab opens and
   1406x765 by the time the layout runs), so it was left alone.
2. **"The note node popups dont show on any of the graph views ... except
   for the force view"** was the click path (`f72eec8`). A click on a node
   was handled by d3-drag's `end` as a zero-distance drag, and `subject()`
   returns null for tree, radial and arc on purpose, so those three had no
   path to the popup at all. The canvas click listener opens the node
   itself under a computed layout and still defers to the drag in force.
   `graphtree.js`: 448x338 in force and closed in the other three before,
   448x338 in all four after.

Found while measuring those two, fixed alongside:

- **Trace could not find a note on the canvas renderer** (`43525ac`).
  `setTraceEnd` looked the note up in `graphNodeSelection`, the SVG
  renderer's `<g>` join, which is null on the canvas renderer, so every
  Trace started from a node popup answered "that note isn't on the map
  right now". It reads `graphNodesRef` now. Clicking two notes in trace
  mode was never affected (`pickTraceEnd` is handed the node).
- **`graph.js`, the phase sweep, had been dying three checks in** since
  Phase 3 turned "Colour by" into a `<select>`: it drove the radio group
  that used to be there and threw on a null, taking the seventeen checks
  after it with it. It runs to the end now, 30 checks, 0 findings.
- **`graph3.js` and `graph4.js` were pinned to a dead port** (8784) and
  had not run since they were written. They read `BASE` now and both pass.

## The movement optimisation, 2026-09-12 (done)

Asked for directly, after `a2ab550` did the same for the whiteboard
(`c7f76c6`). The whiteboard's "write the transform in the event, not a
frame later" does not apply to a canvas, where the paint *is* the work; the
other two shapes both did.

- `graphMinimapPaint` ran synchronously on every pan and wheel event: four
  passes over every node, three document lookups and up to 700 fresh
  `<circle>` elements, for a picture identical apart from the viewport
  rectangle. Split into `graphMinimapFrame` (four attribute writes against
  the last full paint's projection) and coalesced into the draw's frame.
  The full paint runs where the positions really changed, which now
  includes an explicit call after a relayout on both renderers: the pan
  used to refresh the dots by accident and no longer does.
- `#graph-search` and `#graph-labels` were a `getElementById` per frame of
  every pan, drag and hover. Cached by id.
- `graphNodeUnder` took a square root per note per pointer event of a drag.
  Squared both sides.

Measured with `graphmove.js` (new): document lookups by the graph, before
then after, pan 202 then 0, zoom 102 then 0, drag 140 then 30 (those 30 are
the worker's one-in-eight-ticks full repaints while the notes really are
moving). Full minimap repaints during a 40-move pan: 40 then 0.
**Not a claim that the lag report is fixed**: frame times prove nothing on
this box (vsync-bound at ~16.7ms), the self-time figures are hundredths of
a millisecond on a 43-note map and are noise at that size, and the case
that this matters at 2,000 notes is read off the code, not measured.

## Open, found and not fixed

- ~~`graph2.js` has five failures~~ **all five closed, 2026-09-12 evening,
  and two of them were never real.** The three about the options panel
  ("rows come at 2 heights [30, 41.6]", "row labels come at 2 sizes", "a row
  draws its control to the left of its label") were one row: the Groups
  section's add-row wore `.graph-option-row`, whose recipe is one setting
  with its name on the left and its control on the right, while it makes a
  group and so has no label. It is its own form-row shape now, on the same
  height floor, and the panel measures 10 rows at one height and one label
  size. The two label failures ("a broad search piles the labels up again",
  "a search for one note drew no label for it") **do not reproduce on a real
  notebook**: they were measured on a scratch profile holding a single note,
  where a search matches nothing and "0 of 0 labels drawn" trips a check
  written for a populated map. Re-run against the 50-node fixture on
  `/tmp/mm-graph2`: 0 failures, whole sweep. The lesson is the sweep's, not
  the graph's: a check that cannot tell "nothing matched" from "labels are
  broken" will cry wolf on every small fixture.
- The node popup redesign the owner names in the same message ("I dont
  think you have redesigned the popup agent yet") is not this batch:
  GRAPH_PLAN Phase 6 and the three rows under "Placed from INBOX,
  2026-09-09" hold the node panel, and the agent popup is another surface.

## Not verified anywhere in this phase, this batch included

- Chromium only, and no second browser.
- 1440x900 for everything. The options panel's narrow-width fallback (the
  two-column "Show" grid collapsing to one column below 820) was checked at
  1024 and 390 for clipping and wrapping only (`graphopt820.js`); it still
  scrolls at those two widths, same as before this batch, and that scrolling
  itself was not re-measured against a target the way 1440x900 was.
- `contrast.js` was run on every tab in both themes and separately on the
  options panel with it open (21 text nodes, worst ratio 7.4 light and 7.86
  dark) before this batch; not rerun against the header-merge or two-column
  changes.
- Nothing was looked at: every claim is a `getBoundingClientRect`, a
  `getComputedStyle` or a `__graphDebug` read.
- The world constant in `gcWorldFor` (1.6 to 1.25) is not exercised at 35 or
  300 notes, where the viewport floor decides the world. Above about a
  thousand notes it is reasoned, not measured.
- Touch and pinch on the map are still untested, and so is the graph at a
  phone width beyond the panel.
- The 2026-09-12 batch above: Chromium only, 1440x900 only, one 43-node
  fixture. The epoch fix is measured against a race whose window is one
  message hop wide, so the sweep that guards it is probabilistic (it caught
  the bug at 1 of 15 moments on a single pass, which is why it runs two);
  it is not a proof that no stale tick can ever land.

## The phases after this one

`GRAPH_PLAN.md` Phase 3 (colour rules and groups), Phase 4 (lasso select,
right-click menu, a local-graph pane, the time slider's Play, PNG export at
2x) and Phase 5 (the backend fields, positions on views, the `?since=`
cursor) are all untouched, and INBOX 41's "the graph needs a utility, UI and
interaction clean-up" points at Phase 4.
