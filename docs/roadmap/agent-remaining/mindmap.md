# Mind map: what is left

> Companions: [MINDMAP_PLAN.md](../MINDMAP_PLAN.md) ·
> [HANDOVER.md](../HANDOVER.md) · [../../DESIGN.md](../../DESIGN.md)
>
> Rewritten after the sixth run, which closed the three things the fifth
> left: the exports now carry everything the strip and the rings set, both
> rings stay inside the canvas, and all of it has been measured in dark mode
> and at 390x844. Their account is in HISTORY.md ("Moved from the plans,
> 2026-09-12"). Everything below was checked in a real Chromium against the
> running app, not read off the source.

## Closed, with where the numbers are

| Was | Now |
| --- | --- |
| A to E, H, and INBOX 42 | First three runs: MINDMAP_PLAN §9 and §10, HISTORY, and the commits they name. |
| F, the whiteboard and map previews | MINDMAP_PLAN §11.1. |
| G, Phases 4 and 5 | MINDMAP_PLAN §11.1. |
| §12.1 item 1, the map's own dock | HISTORY, "Moved from the plans, 2026-09-09". |
| §12.1 items 2 to 9 | HISTORY, "Moved from the plans, 2026-09-12": the edit strip, the node radial, the link radial, the mid-line add, the text-size grip, uncollapse, transplant and sever. |
| Their exports, their viewport clamp, the dark/narrow pass, and node shape | HISTORY, same date, "what the sixth run closed behind items 2 to 9". The shape list is a §12.0 decision. |
| The two open decisions (Space, a trunk's colour) | MINDMAP_PLAN §12.0, decided 2026-09-12 with the reason for each. |

## The sweeps that gate this

| Sweep | Checks |
| --- | --- |
| `scratchpad/ui-sweeps/mindmap.js` | **76**, re-run and green |
| `scratchpad/ui-sweeps/mindmap3.js` | **57**, re-run and green after two repairs to the sweep itself (see below) |
| `scratchpad/ui-sweeps/mindmap-theme.js` (`THEME=dark`) | **9** (was 7), re-run: 9/9 dark at 1440, 8/9 dark at 390 (the one failure is the shell's own 7px overflow, below) |
| `scratchpad/ui-sweeps/mapdock.js` | **26** (was 25): the dock split, the delete doors, the empty map, the two §12.0 decisions, the three ways out of a fold, and the dock's reach at phone width |
| `scratchpad/ui-sweeps/mapstrip.js` | **39** (was 33): the edit strip, both radials, the mid-line add, the grip, transplant, sever, the strip's own box, both rings against the edge of the canvas, and the four node shapes |
| `scratchpad/ui-sweeps/panlag.js` | **5**, new: where a pan's work happens |

Run them against a **fresh** data dir (`serve.sh <port> /tmp/mm-mapN`): the
sweeps assert board-gallery contents and tree shapes, so a dir left over from
an earlier run carries other boards into those checks.

`mapstrip.js` and `mapdock.js` take `VIEWPORT=390x844` now, as
`mindmap-theme.js` already did, and `THEME=dark` works on all three through
`lib.js`. At phone width `mapstrip.js` frames the map (the app's own
`wbZoomToFit`) before each gesture that has to land on a node: the
re-framing finding under "not fixed" says why.

## Left to do

### 1. The rest of §12.1 item 1: the dock's four menus, NOT started

Layout and Tidy are still in the top bar rather than the dock, and the
Style, Insert, Arrange, Present and Export menus named in item 1 are not
written. The Topic and Branch sections carry six controls between them.

**Next step**: the dock grammar allows seven visible controls and the rest
behind ▾ menus. Style is now mostly redundant (the strip and the link ring
carry colour, weight, size, alignment and line shape), so the honest list is
Layout ▾, Insert ▾, Arrange ▾ and Export ▾, and Layout is a move of
`#wb-map-layout` and `#wb-map-tidy` out of `#wb-topbar` rather than new UI.

### 2. The five sub-items of §12.1 items 2 to 9 that were not built

Each with its reason, in the plan at §12.1 under "2 to 9". In the order
worth doing them:

- **An image in a node** (item 2). Needs the board's own upload path
  (`/whiteboard/media`) and a node whose body is a picture rather than a
  label, which is a second node shape rather than a fourth strip button.
- **Curve control points** (item 5). Two more `data` fields on the child and
  a third hit target per line, and it now has to compose with the three
  line shapes item 4 added.
- **Line thickness** (item 4), **Shift+drag to sever** (item 9) and
  **comments on a node** (item 3, which is §12.2 item 6): each is one line
  in the plan, and each has a reason there for being left.

### 3. The dark theme and the narrow viewport: done for the strip, the rings and the dock, NOT for the rest of the map

Run at 1440 light, 1440 dark and 390x844: mapstrip 37/37 in all three,
mapdock 26/26 in all three, mindmap-theme 9/9 dark at 1440. The strip's
392px-in-a-364px-canvas was real and is fixed (it wraps); the rings are
clamped. What is still unseen narrow or dark: the mid-line `+`, the
drop-target outline, the templates card (`#wb-map-templates`, which covered
the only topic of a new map at 390 in a probe: reproduce before fixing, it
was an empty map), and everything in `mindmap.js` and `mindmap3.js`, neither
of which takes a `VIEWPORT` yet.

**Next step**: give `mindmap.js` and `mindmap3.js` the same four-line
`VIEWPORT` block `mapstrip.js` has, and run both narrow.

### 4. Perspectives on a map that actually has notes on it: NOT measured

Unchanged from the fourth run. Colour-by-category and colour-by-age were
measured on a map of topics, where both are the quiet grey by construction.

**Next step**: build a map of twenty note nodes across four categories
(`POST /boards/{id}/nodes` with `kind: "note"`), switch the View menu's
Colour by, and measure the distinct `--wb-branch` values plus contrast
against `--card` with `scratchpad/pngpixel.py`.

### 5. INBOX 43's second half: NOT started

The whiteboard's bottom tool rail and properties panel onto the bar and
panel recipes of `08-consistency.css`. Untouched for two runs.

### 6. The AI half, still unexercised

No real model has answered the map proposal prompt, and no map *tool*
(`read_mindmap`, `create_mindmap`, `add_map_node`, `link_map_nodes`) has been
driven from the UI in five runs.

## Found while measuring, and fixed

- **The two XML exports carry a node's look now, and read it back.** What
  each format got, and why the four fields FreeMind has no word for ride as
  private attributes rather than as invented FreeMind, is in HISTORY
  ("what the sixth run closed behind items 2 to 9"). `MAP_STYLE_FIELDS` in
  `routes_whiteboard.py` is the one list the tree endpoint, both exports and
  both imports read, so a tenth field added to the strip and not to that list
  is the next silent loss.
- **Both rings slide inside the canvas.** `wbPlaceMapRadial` in
  `whiteboard.js`, shared by the node ring and the link ring, measured off
  the slots after the ring is shown. Its bound is the canvas minus the
  panels that float in bands across it, so a trunk near the top no longer
  puts three slots under the top bar.
- **The node edit strip wraps.** Two centred rows at 390x844, capped to
  `calc(100% - var(--space-6))`; unchanged at any width that fits it.
- **A click on a topic saved the topic, and raced the control you clicked.**
  `objDrag` runs for a plain click as well as a drag, and `objDragEnd` PUT
  the object every time; a click on the fold chevron therefore sent
  `collapsed: null` and `collapsed: true` to the same row in one tick with no
  defined order, and the map kept whichever landed second. Found by
  `mindmap.js`'s SVG export check counting two edges where the map had four,
  then instrumented in a real browser and confirmed against a worktree of the
  commit before this session. The save is gated on "did it really move" now.
- **`mindmap3.js` had been timing out since 2026-09-09**, when the Boards &
  maps dock put "Import outline…" and "Map from notes…" behind its ⋯. The
  sweep clicked a button inside a closed `<details>`, which Playwright reports
  as a thirty-second timeout rather than as "the control moved". Worth knowing
  for the next sweep that stalls: **a click that hangs is a z-order or a
  visibility bug**, not a slow app.

## Found while measuring, not fixed

- **`WB_MAP_STYLE_KEYS` does not carry the two fields the link ring writes.**
  `edge_style` and `edge_dashed` are missing from that list in
  `whiteboard.js`, whose own comment says it is "everything the strip and the
  radial can set on a node", so copying a branch loses its line shape and its
  dash and "back to the branch" leaves them behind. Not fixed here because
  "back to the branch" enumerates what it drops in its own tooltip and adding
  a line's shape to that list is a small design call, not a typo. One line
  plus the tooltip when it is taken.

- **The app shell scrolls sideways by 7px at 390x844**, on every tab, not
  just the map: `document.documentElement.scrollWidth` 397 in a 390 window,
  with 43 elements past the right edge and `.header-controls` (266px wide,
  right edge 397) the outermost. Not the map's, and not fixed here because it
  is the shell's own narrow-width layout; it is the one failing check in
  `mindmap-theme.js` at `VIEWPORT=390x844` ("the page itself does not scroll
  sideways"). Worth an INBOX entry of its own.
- **`wbMapNodeSize` and the rendered node disagreed by 94px at 390x844.**
  Found by the corner-ring check in `mapstrip.js`: a pan computed to put a
  node's centre at a chosen point landed it 47px (half of 94) to the left,
  every time, at phone width only. The sweep corrects itself by measuring and
  panning again, and records the drift; what it means is that some consumer
  of that size (the layout, the edge anchors, the ring's own centring) is
  working from a width the node does not have at that viewport. Reproduce
  before theorising: it may be a render ordering rather than a wrong width.
- **A map does not re-frame itself after a tidy**, which at 390 leaves the
  trunk's own centre off the canvas (measured: the root's box at x=-95,
  `elementFromPoint` at its centre returning the shell behind the canvas).
  §12.0 says auto-arrange is a command and not a constant, so this is a
  decision to make rather than a bug to fix: the honest options are to frame
  after a tidy that pushed content off the canvas, or to leave it and rely on
  Fit.

- **The pan lag is now half-attributed.** The structural half was real and is
  fixed: `handleWbZoom` deferred the three layer transforms to
  `requestAnimationFrame` along with the per-frame work, and the transform is
  the one write with nothing to save. It is written in the handler now
  (`panlag.js`, 5 checks). **It did not reproduce as a frame-rate problem**:
  the fourth run's six-condition A/B read 16.6 to 16.8ms medians throughout
  because this sandbox is vsync-bound, and nothing here can show what the
  owner sees. The change removes a deferral with nothing to gain; it is not a
  claim that the report is fixed. If it recurs, the next thing to look at is
  `--wb-grid-offset-*`, which repaints the container's background while the
  layers composite: moving the grid onto its own transformed layer is a
  separate change with its own measurement.
- **The two XML exports still recurse, and nothing bounds a map's depth.**
  Unchanged from the fourth run: `_export_opml` and `_export_freemind` walk
  the tree with a recursive helper while every other walk in that file is
  iterative. A thousand Tabs down one branch would export as a
  `RecursionError`, which is a 500.
- **Tidy still persists one node at a time**, and so do the new branch
  operations: copy branch is one POST per node (capped at 120 for that
  reason), transplant is one `/move` per child in the Ctrl case, and "open
  every folded branch" is one PUT per folded node. A bulk endpoint is the fix
  if any of them ever matters.
- **A sweep's CSS overrides are silently refused, and the run looks
  successful** (the page's CSP is `style-src 'self'`). `el.style.x = ...`
  from `page.evaluate` is allowed and is how every number here was taken.
- **Reading a resting `:hover` state needs the pointer moved away first.**
  The text-size grip's "invisible until pointed at" check read opacity 1
  twice before the sweep started parking the mouse at 4,4: Playwright leaves
  the cursor wherever the last click put it, and `:hover` is a real state.

## What could not be verified

- **The sixth run**: the exports were tested against their own importers and
  against the shapes FreeMind and OPML document, never against FreeMind,
  Freeplane, XMind, Coggle or MindMeister themselves, so "it opens there
  looking the way it did" is reasoned from their formats, not observed. The
  narrow pass is one viewport (390x844, DPR 1) and the dark pass one theme at
  1440; nothing was seen at 1024, at DPR 2, or on a real touch device.
- **The fifth run**: one viewport (1440x900, DPR 1) and light theme.
- No real inference, and no AI map tool driven from the UI.
- Touch: both radials' long-press paths and the mid-line `+` were written
  against `pointerType: "touch"` and never driven by a touch device.
- PDF export goes through the browser's print dialog, which Playwright cannot
  complete.

## The drag and pan report, third time: what the next run should not repeat

The owner, 2026-09-12 afternoon: "the whiteboard is still laggy to drag and
pan around, it isnt perfextly smooth and uniform like it should be on a
professional application". That is the third report. Two measured passes have
failed to attribute it and one real change landed (`a2ab550`, the pan's layer
transforms moved into the event), which the commit is careful to say does not
prove the report fixed.

An attempt this afternoon got no further, and the useful part is why, so the
next run starts past it rather than at it:

- **Frame rate is not the measurement here.** This sandbox is vsync-bound at
  about 16.7ms in every condition anyone has tried, including with the whole
  card layer removed. Six conditions returned six identical numbers.
- **Synthetic `PointerEvent`s dispatched from `page.evaluate` do not reach
  d3's drag behaviour at all.** A profile built that way measured 0ms per
  event across 60 events and was measuring nothing whatsoever. Use
  Playwright's own `page.mouse.down/move/up`, which produces trusted events.
- **`openWhiteboardBoard(id)` called from `page.evaluate` leaves the boards
  landing showing**, so the board never opens and `.wb-object` count is 0.
  `mapstrip.js`'s `newBoard(page, name, type)` clicks through the real UI and
  works; reuse it rather than writing a third one.
- **What is worth measuring** is the app's own work per event, which the
  display cannot hide: wrap `wbUpdateSelectionBar`, `renderWhiteboardNow`,
  `wbScheduleRender`, `wbSyncGridToTransform`, `wbRenderNavigator` and count
  calls and self time across a real 60-move drag, and count
  `Document.prototype.querySelector` calls over the same window. The pan work
  found its one real cost exactly that way: a document-wide query at 0.46ms
  per frame against 0.013ms for the grid sync beside it.
- The drag handlers are worth reading first for the same shape:
  `frontend/whiteboard.js` around the `.on("drag")` handlers does a
  `document.querySelector` per event to find the element it is moving, and
  calls `wbUpdateSelectionBar()` on every event.

**Nothing here is a claim that the cause is known.** It is a list of the
three ways to waste an hour on it, and the one measurement that has ever
produced a number worth acting on.

### The fourth pass, 2026-09-12 (WHITEBOARD_PLAN Phase 4): still not reproduced, and one real thing found on the way

A CDP CPU profile, which is the instrument the previous three passes did not
use: `scratchpad/ui-sweeps/dragprofile3.js` samples the stack at 100us through
a real 60-move `page.mouse` drag on a board of 120 objects, and rolls the
samples up by self time. It sees the drag handlers themselves, which no
monkey-patch can: `objDragStart`, `objDragMove`, `objDragEnd` and
`wbAlignmentGuides` are inside an IIFE and have no global binding, which is why
`dragprofile2.js` could only wrap the globals around them.

**The lag did not reproduce, again, and the profile says why it will not
here.** Over 60 moves on a 120-object board the app's total main-thread work
was 33.8ms, which is **0.56ms per move** against a 16.7ms frame, and **no
`whiteboard.js` frame reached 1ms of self time across the whole drag**. The
same drag with 119 of the 120 objects hidden measured 0.43ms per move. There
is nothing in this profile that could make a frame late, so the next pass
should not spend its time on `objDragMove` on the strength of a reading taken
here. What a profile taken on the owner's own machine would show is the open
question, and it is the only thing that can close this report.

**What the profile did find, which is real and is fixed:** the top of the
drag's own profile was not the whiteboard at all, it was p5. Six emblem
sketches (`EMBLEM_SLOTS` in `app.js`) are built at boot and five of them live
inside a panel that is `display: none` almost all the time (the lock screen,
onboarding, the chat and graph empty states, About), each running its own 24fps
draw loop for a canvas with no box. Measured on an idle board: **six canvases
alive, one visible, 5.0 `requestAnimationFrame` requests per displayed frame**.
They are paused by an `IntersectionObserver` now and started again the moment
their holder is on screen, which is what the owner's "never static and always
rotating" asks for; A/B inside one run, `scratchpad/ui-sweeps/wbdrawloops.js`:
**0.0 requests per frame, against 5.0 with the loops forced back on**.

This is **not** a claim that the drag report is fixed. It is work the app was
doing for nothing, found while looking for the report, and the honest status of
the report is unchanged: four passes, not reproduced in this sandbox.

**Still not looked at**, and the next thing worth trying: `paintDashClock`
(`dashboard.js`) appeared in every drag profile taken here, on a tab that was
not open. That is the same shape as the emblems and belongs to whoever owns
`dashboard.js`.
