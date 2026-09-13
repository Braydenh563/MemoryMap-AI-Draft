// MemoryMap AI: Whiteboard subsystem (extracted from app.js).
//
// This is the "Whiteboard" tab: boards, cards, sketches-as-objects, links,
// mind-mapping, export: the OneNote/draw.io-style canvas built across
// HISTORY.md §53-§58/§61 (ROADMAP.md Priority 0 item 2; style.css's half of
// that item was split first, into frontend/css/*.css).
//
// Loaded as a second classic (non-module) <script> tag, after app.js, so it
// shares app.js's global scope: everything here can call `$`, `api`,
// `apiJson`, `toast`, `switchTab`, `confirmDialog`, `openSketch` (the
// separate Quick Sketch modal, see below) and the rest of app.js's helpers
// directly, and app.js's command palette calls `createNewBoard`/
// `wbShowCanvasView` right back. None of that requires a particular load
// order: every cross-file call here happens at runtime, inside a function
// body or an event-listener callback, never at parse time. app.js loads
// first only because this file's own top-level code (the `wbZoom = d3.zoom()`
// assignment) needs `d3` from /vendor/d3.v7.min.js, which the existing
// script order already guarantees, nothing here needs app.js to have run
// first.
//
// NOT included here: the "Quick Sketch" pad (`openSketch`/`closeSketch`/
// `saveSketch`/`sketchPen`/... and the `#sketch-*` DOM ids), which stayed in
// app.js. It looks related by name, the task that produced this split
// flagged it explicitly for a call, but it is a separate, still-live Wave F
// ("Platform") feature: a full-screen freehand pad that saves a PNG as a
// note, reachable from the command palette and the floating action menu,
// unrelated by call graph to the board/card system below except that the
// whiteboard toolbar's "Add sketch" button opens it (`openSketch()`, called
// at runtime from `initWhiteboard`). Moving it here would have been a scope
// mistake, not a cleanup, so it was left where it was.
//
// ALSO NOT included here any more: the Library's Documents/Image-Gallery
// sub-tabs, their own selection state, and the `#library-subtabs` switcher: 
// all genuinely Library-owned code (they switch and populate OTHER Library
// sub-tabs, not this one) that had ended up in this file's own
// DOMContentLoaded listener purely because it was written in the same block
// as this tab's own two controls (`wb-boards-new`/`wb-back-to-boards`,
// still below). Moved out to frontend/library.js in the app.js split's
// second file (§88.3); see that file's own header for the full list and the
// reasoning. `renderLibraryBoardsGallery`/`wbShowBoardsLanding`/
// `wbShowCanvasView` stayed: they render and switch between *this* tab's
// own two views (a boards gallery and the canvas), which is whiteboard's own
// concern even though the gallery happens to live inside the Library's
// Whiteboard sub-tab.

// ======================= WHITEBOARD LOGIC =======================
// **Held-space panning, middle-mouse panning, and wheel zoom from every
// tool.** Reported directly: "the whiteboard is really annoying to use with
// the tools, I'm constantly having to switch between tools to select and move
// around."
//
// That was structural rather than a missing shortcut. Panning *was* a tool, 
// you pressed V to pan and S to select, and `selectWbTool` disabled the zoom
// behaviour outright for every other tool (`container.on(".zoom", null)`),
// which also took **wheel zoom** with it. So while drawing you could neither
// scroll the canvas nor zoom it without first changing tool and then changing
// back.
//
// Every drawing app people already know (Figma, Excalidraw, tldraw) solves
// this the same way, and it is a filter rather than a mode: the zoom
// behaviour stays attached at all times, and decides per-event whether a
// gesture is a pan. Held space or the middle mouse button pans from *any*
// tool; a plain left-drag only pans when Pan is genuinely the active tool, so
// drawing, the marquee and lasso are untouched.
let wbSpaceHeld = false;

function wbZoomFilter(event) {
  // Wheel: zoom only with Ctrl/⌘ held (which is also what a trackpad pinch
  // arrives as). A plain wheel *pans*, see the native listener in
  // initWhiteboard: because that is what Miro, FigJam, Figma and draw.io
  // all do, and reported as "annoying to... pan, navigate the board": a
  // wheel that zooms leaves no fast way to move around at a fixed zoom.
  if (event.type === "wheel") return event.ctrlKey || event.metaKey;
  // Middle button pans from anywhere. `buttons` rather than `button` because
  // mousemove reports the held set, and the drag half of the gesture needs to
  // pass the filter too.
  if (event.button === 1 || (event.buttons & 4) === 4) return true;
  // Touch: only in Pan. A finger drag while a brush is selected is a stroke,
  // and stealing it for a pan would make the board undrawable on a tablet.
  if (event.type.startsWith("touch")) return window.currentTool === "pan";
  // Left button: Pan tool, or space held down.
  if (event.button === 0 || event.buttons === 1 || event.buttons === 0) {
    return window.currentTool === "pan" || wbSpaceHeld;
  }
  return false;
}

let wbZoom = d3
  .zoom()
  .scaleExtent([0.1, 4])
  .filter(wbZoomFilter)
  .on("zoom", handleWbZoom);
let wbState = { nodes: [], sketches: [], objects: [] };
let wbHintForcedOpen = false; // the "?" help button's override: see renderWhiteboard
let wbInitialized = false;
// ROADMAP.md Tier 2 §11: Select was folded into Pan, with no visible
// "this is selected" state and no way to delete without switching to the
// Delete tool. `{kind: "sketch"|"node", id}` of whatever's currently
// selected, or null. Rotate isn't part of this, `WhiteboardNode` has no
// angle column at all, so rotation needs a real backend change, not a
// frontend-only pass; left as its own separate item.
let wbSelectedItem = null;
// ROADMAP.md Tier 2 §11 / reported directly: "multi-select, holding down
// shift, area select... missing". A set of `"kind:id"` strings, alongside
// (not replacing) `wbSelectedItem`, a lone selection still goes through
// the single-item path (it's what the sketch resize handles and copy/paste
// are built around, and both only ever make sense for exactly one item);
// this is populated only once a second item joins, via shift-click or a
// marquee drag.
let wbMultiSelection = new Set();
// `deleteSketch`/`deleteNode` are closures defined fresh inside every
// `wbScheduleRender()` call; these hold whichever pair is current, so code
// outside that closure (the Delete-key handler) can still call them.
let wbDeleteSketchRef = null;
let wbDeleteNodeRef = null;
let wbDeleteObjectRef = null;
// `selectWbTool` is a closure defined inside `initWhiteboard` (it needs that
// scope's `container`/`toolGroup`); this holds the current one so code
// outside it, placing a text box switches back to Select once typed , 
// can still call it, the same shape the delete-refs above already use.
let wbSelectToolRef = null;
// Same shape again, for the marquee/lasso selection drag. Reported directly:
// "there's a permanent selection box on my mindmap", a dashed accent
// rectangle sitting on the canvas at rest, ~330x375, with nothing selected.
//
// Measured, not guessed: the rect is a real `.wb-marquee` element, and it
// leaked three different ways, all of them because the *only* thing that
// removed it was a `pointerup` on the board container. Release the button
// anywhere else (over the top bar, over the left rail, off the window) and
// the pointerup never reaches that listener; a second pointerdown then
// overwrote `wbMarqueeEl` and orphaned the first rect for good. It survives
// a re-render and a board reopen too, because it lives in `#wb-zoom-group`,
// which the render joins by data and never clears wholesale.
//
// So the drag now captures the pointer and ends on `pointerup`,
// `pointercancel` or `lostpointercapture`, and this ref lets Escape, a
// click on empty canvas and every board load sweep up anything that still
// got left behind.
let wbCancelSelectionDragRef = null;
//: Remove any marquee/lasso rectangle still on the canvas, wherever it came
//: from. Safe to call at any time: with no drag in flight there is nothing
//: to find. Deliberately a DOM sweep rather than "remove the element I am
//: holding", the leak this fixes was precisely an element nothing was
//: holding any more.
function wbClearSelectionOverlays() {
  wbCancelSelectionDragRef?.();
  for (const stray of document.querySelectorAll(".wb-marquee, .wb-lasso")) stray.remove();
}
// Same shape, for refreshing the "Line ends" control's displayed value when
// the active tool switches between Line and Arrow (each now has its own
// remembered end-style: see the live-reported bug fix in `initWhiteboard`).
let wbRefreshArrowStyleControlRef = null;
// True only between an eraser mousedown and mouseup, the drawing tools
// leave one mark per click-drag, the eraser is meant to remove everything
// the pointer crosses while held, so it needs a "currently held" flag the
// per-item hover handlers in renderWhiteboard can check.
let wbErasing = false;
// True for the span of an in-progress link drag (dragStart → dragEndNode on
// a card, with a link-type tool selected), lets the plain hover listener
// in initWhiteboard step aside rather than fight the drag's own per-frame
// anchor-hint redraw with a second, slightly-stale one.
let wbLinkDragActive = false;
// Which attached-note cards are expanded past their clamp, keyed by node id
// (the whiteboard attachment, not the note itself), same "remember per card
// for the session" shape as `expandedNotes` on the Notes list. A plain `let`
// module-level Set, not persisted: reopening the board later re-clamps.
const wbExpandedNodes = new Set();
// {action: "delete"|"create", kind: "sketch"|"node", payload, id}. Bounded
// so an hour of erasing doesn't grow this forever; only the newest matters.
let wbUndoStack = [];
// ROADMAP.md Tier 2 §11: a redo stack, the same shape as the sketch pad's
// own history: cleared whenever a fresh action is pushed onto wbUndoStack,
// since redoing something that predates a new action would resurrect a
// version of the board the newer action never saw.
let wbRedoStack = [];
const WB_UNDO_MAX = 20;
// Ids currently mid-DELETE. The eraser's mouseenter can fire again for the
// same still-on-screen item before its first DELETE round-trip resolves (a
// slow request, or the pointer wobbling back over it), without this a
// second call pushes a second undo entry and fires a second DELETE for
// something already gone, and the 404 catch then pops the *wrong* undo
// entry off the stack (whatever else was pushed in between).
const wbDeleting = new Set();

//: **All three layers pan the same way, and they did not used to.** Reported:
//: "when I drag the whiteboard around, notes seamlessly move but the shapes
//: and links lag behind."
//:
//: They did. The cards (`#wb-html-layer`) were moved with a CSS `transform`,
//: which the compositor can apply to an already-painted layer; the two SVG
//: groups were moved by setting the `transform` *attribute*, which is a
//: geometry change the renderer has to lay out and repaint every frame. Same
//: numbers, two different pipelines, and on a board with any real number of
//: shapes the SVG one cannot keep up with a pan, so the shapes visibly trail
//: the notes they are attached to.
//:
//: Switching the groups to a CSS transform is only safe because every drag
//: handler in this file resolves pointer coordinates through
//: `getScreenCTM()`, and the question of whether that folds in a CSS
//: transform on an SVG element is the whole risk. Measured in Chromium rather
//: than assumed: two identical `<g>`s, one carrying `transform="translate(37,
//: 61) scale(2.5)"` and one carrying the same as CSS, returned the same
//: matrix, [2.5, 2.5, 37, 844.14], and mapped the same screen point to the
//: same board point, [185.2, -177.66]. Nothing reads the attribute back
//: either, so there is no second consumer to keep in sync.
//:
//: `transform-origin: 0 0` is not optional: CSS defaults an SVG element's
//: origin to the centre of its bounding box, while the `transform` attribute
//: has always scaled about the user-space origin. Without it every zoom would
//: pivot somewhere that moves as the board's contents change. It is set in
//: CSS beside the layers rather than here, so it cannot be lost by an edit to
//: this function.
// PLAN.md P2: a trackpad emits several wheel events per frame, and each one
// used to write three transforms, three grid variables and the navigator
// synchronously. Only the last transform in a frame can be painted, so the
// rest was work the compositor threw away. One pending write per frame.
//
//: **The split: the layers move now, the rest waits for the frame.**
//: Reported as "when I pan the whiteboard and mindmap around, it is still
//: laggy and the shapes and links and everything feels like it lags behind a
//: bit", and the first attempt at it A/B'd six conditions and found identical
//: frame times (this sandbox is vsync-bound), which is the wrong end of the
//: problem: nothing about the *shape* of the work above depended on how long
//: the work took.
//:
//: What the coalescing above is right about is the *cost* half: grid
//: variables, the selection bar and the navigator are per-frame work and
//: three wheel events in one frame should not do them three times. What it
//: was also doing is deferring the transform itself, which is the one write
//: with nothing to save: the compositor can only paint the last value of a
//: frame either way, so writing it on every event costs three style
//: invalidations and no layout, and writing it late can only ever be later.
//:
//: Honest about what that does and does not prove. What is measured
//: (`scratchpad/ui-sweeps/panlag.js`) is that the layer transform is now the
//: new matrix in the same task as the input event, while the grid variables
//: are still written once per frame. What is *not* measured, and cannot be
//: on this box, is a frame of latency: Chromium dispatches coalesced input at
//: the start of a frame and runs `requestAnimationFrame` later in that same
//: frame, so for input that arrives on that path the old code was already
//: painting in the right frame. This removes a deferral that had nothing to
//: gain, for input on any other path; it is not a claim that the report is
//: fixed.
let wbZoomFrame = 0;
let wbZoomPending = null;

function wbApplyZoomTransform(t) {
  const css = `translate(${t.x}px, ${t.y}px) scale(${t.k})`;
  d3.select("#wb-html-layer").style("transform", css);
  d3.select("#wb-zoom-group").style("transform", css);
  d3.select("#wb-overlay-zoom-group").style("transform", css);
}

function handleWbZoom(e) {
  wbApplyZoomTransform(e.transform);
  wbZoomPending = e.transform;
  if (wbZoomFrame) return;
  wbZoomFrame = requestAnimationFrame(() => {
    wbZoomFrame = 0;
    const t = wbZoomPending;
    wbZoomPending = null;
    if (!t) return;
    wbSyncGridToTransform(t);
    wbUpdateSelectionBar();
    // The navigator's viewport rectangle is only true for one transform, so
    // it is redrawn with every pan and zoom. `wbRenderNavigator` returns
    // immediately when the navigator is closed, which is the common case.
    wbRenderNavigator();
  });
}

//: The grid's spacing in board coordinates. Scaled by the zoom so a square
//: stays a square of the *board*, not of the screen, panning and zooming
//: move the ruling with the content, which is the whole point of a grid you
//: can snap to.
const WB_GRID_SPACING = 24;

//: A card's default size before a resize ever sets `width`/`height`
//: explicitly: the CSS auto-size every card used before resize existed,
//: and the same figure this file's own drop-centring/link-anchor math has
//: assumed all along (see the drop handler and `dragStart`'s own comments).
const WB_CARD_DEFAULT_SIZE = { w: 250, h: 150 };

function wbSyncGridToTransform(transform) {
  const el = document.getElementById("whiteboard-container");
  if (!el) return;
  const t = transform || d3.zoomTransform(el);
  el.style.setProperty("--wb-grid-size", `${WB_GRID_SPACING * t.k}px`);
  el.style.setProperty("--wb-grid-offset-x", `${t.x}px`);
  el.style.setProperty("--wb-grid-offset-y", `${t.y}px`);
  //: **And the inverse scale, for anything that must not grow with the board.**
  //: The grid is not the only thing that has to be told what the zoom is. A
  //: grip is a target for a finger rather than part of the drawing, and
  //: measured on a real board, every handle on this canvas was 20px across at
  //: 2x and 5px at 0.5x: the card handles ride `#wb-html-layer`'s CSS scale,
  //: and the sketch and link handles are SVG geometry inside `#wb-zoom-group`,
  //: so both kinds are multiplied by `k`. One `scale(1 / k)` on the handle
  //: cancels that exactly, which is what `--wb-inv-zoom` is for (see the grip
  //: rules in 07-whiteboard-misc.css).
  //:
  //: Published here, once per zoom frame, rather than read per element:
  //: `d3.zoomTransform` per handle would put work back into the pan path this
  //: file has twice been cleared of, and one custom property reaches all
  //: twenty-odd of them through inheritance.
  el.style.setProperty("--wb-inv-zoom", String(1 / (t.k || 1)));
}

function wbGridType() {
  return localStorage.getItem("wb-grid") || "none";
}

function wbSnapOn() {
  // Snapping without a visible grid is a mystery, not a feature, the
  // toggle stays honest by only applying while a grid is actually shown.
  return localStorage.getItem("wb-snap") === "on" && wbGridType() !== "none";
}

//: Round a board coordinate to the nearest grid intersection, when snap is
//: on. A no-op otherwise, so every call site can use it unconditionally.
//: `bypass` (asked for directly: Alt held during a drag temporarily
//: releases the grid lock, the same convention Figma/Illustrator use) skips
//: the rounding for just this one call, without needing the snap toggle
//: itself touched.
function wbSnap(value, bypass) {
  return wbSnapOn() && !bypass ? Math.round(value / WB_GRID_SPACING) * WB_GRID_SPACING : value;
}

//: Smart alignment guides while dragging (asked for directly: "the
//: recognisable popup alignment guides... draw.io and Microsoft
//: PowerPoint have... dotted alignment rule guides... subtly snap"). Scoped
//: to cards and objects as both the dragged item and the things it aligns
//: against: sketches are freehand strokes, not the kind of rectangular
//: "object" this pattern is normally drawn against in the apps it's
//: modelled on. Independent per axis: an X-axis snap and a Y-axis snap can
//: both fire on the same frame (a corner aligning with another item's
//: corner), each drawing its own guide line.
const WB_ALIGN_SNAP_PX = 6; // board units: matches WB_GRID_SPACING's own order of magnitude

function wbAlignmentGuides(excludeKind, excludeId, x, y, w, h) {
  const dragged = { left: x, centerX: x + w / 2, right: x + w, top: y, centerY: y + h / 2, bottom: y + h };
  let bestX = null, bestY = null;
  const others = [];
  for (const [kind, listName] of [["node", "nodes"], ["object", "objects"]]) {
    for (const item of wbState[listName] || []) {
      if (kind === excludeKind && item.id === excludeId) continue;
      const box = wbItemBBox(kind, item);
      if (!box) continue;
      others.push(box);
      const other = {
        left: box.minX, centerX: (box.minX + box.maxX) / 2, right: box.maxX,
        top: box.minY, centerY: (box.minY + box.maxY) / 2, bottom: box.maxY,
      };
      for (const edge of ["left", "centerX", "right"]) {
        const delta = other[edge] - dragged[edge];
        if (Math.abs(delta) <= WB_ALIGN_SNAP_PX && (!bestX || Math.abs(delta) < Math.abs(bestX.delta))) {
          bestX = { delta, at: other[edge], y1: Math.min(dragged.top, other.top), y2: Math.max(dragged.bottom, other.bottom), kind: edge === "centerX" ? "center" : "edge" };
        }
      }
      for (const edge of ["top", "centerY", "bottom"]) {
        const delta = other[edge] - dragged[edge];
        if (Math.abs(delta) <= WB_ALIGN_SNAP_PX && (!bestY || Math.abs(delta) < Math.abs(bestY.delta))) {
          bestY = { delta, at: other[edge], x1: Math.min(dragged.left, other.left), x2: Math.max(dragged.right, other.right), kind: edge === "centerY" ? "center" : "edge" };
        }
      }
    }
  }
  const guideLines = [];
  if (bestX) guideLines.push({ x1: bestX.at, y1: bestX.y1 - 20, x2: bestX.at, y2: bestX.y2 + 20, kind: bestX.kind });
  if (bestY) guideLines.push({ x1: bestY.x1 - 20, y1: bestY.at, x2: bestY.x2 + 20, y2: bestY.at, kind: bestY.kind });
  let dx = bestX ? bestX.delta : 0, dy = bestY ? bestY.delta : 0;

  // Equal-spacing guides ("same spacing", asked for directly): only tried on
  // an axis the edge/center snap above didn't already claim, so a card never
  // fights between "line up with this edge" and "match this gap" mid-drag.
  // Scoped to the single nearest neighbour each side, not every possible
  // triple: that is what draw.io and PowerPoint show too, and it keeps this
  // O(n) per drag frame like the alignment pass above it, not O(n^2).
  if (!bestX) {
    const rowMates = others.filter((b) => b.minY < dragged.bottom && b.maxY > dragged.top);
    const left = rowMates.filter((b) => b.maxX <= dragged.left + WB_ALIGN_SNAP_PX).sort((a, b) => b.maxX - a.maxX)[0];
    const right = rowMates.filter((b) => b.minX >= dragged.right - WB_ALIGN_SNAP_PX).sort((a, b) => a.minX - b.minX)[0];
    if (left && right) {
      const gapLeft = dragged.left - left.maxX, gapRight = right.minX - dragged.right;
      if (gapLeft >= 0 && gapRight >= 0 && Math.abs(gapLeft - gapRight) <= WB_ALIGN_SNAP_PX) {
        const avgGap = (gapLeft + gapRight) / 2;
        dx = left.maxX + avgGap - dragged.left;
        const midY = (Math.max(left.minY, dragged.top) + Math.min(left.maxY, dragged.bottom)) / 2;
        guideLines.push({ x1: left.maxX, y1: midY, x2: dragged.left + dx, y2: midY, kind: "spacing" });
        guideLines.push({ x1: dragged.right + dx, y1: midY, x2: right.minX, y2: midY, kind: "spacing" });
      }
    }
  }
  if (!bestY) {
    const colMates = others.filter((b) => b.minX < dragged.right && b.maxX > dragged.left);
    const above = colMates.filter((b) => b.maxY <= dragged.top + WB_ALIGN_SNAP_PX).sort((a, b) => b.maxY - a.maxY)[0];
    const below = colMates.filter((b) => b.minY >= dragged.bottom - WB_ALIGN_SNAP_PX).sort((a, b) => a.minY - b.minY)[0];
    if (above && below) {
      const gapAbove = dragged.top - above.maxY, gapBelow = below.minY - dragged.bottom;
      if (gapAbove >= 0 && gapBelow >= 0 && Math.abs(gapAbove - gapBelow) <= WB_ALIGN_SNAP_PX) {
        const avgGap = (gapAbove + gapBelow) / 2;
        dy = above.maxY + avgGap - dragged.top;
        const midX = (Math.max(above.minX, dragged.left) + Math.min(above.maxX, dragged.right)) / 2;
        guideLines.push({ x1: midX, y1: above.maxY, x2: midX, y2: dragged.top + dy, kind: "spacing" });
        guideLines.push({ x1: midX, y1: dragged.bottom + dy, x2: midX, y2: below.minY, kind: "spacing" });
      }
    }
  }

  return { dx, dy, guideLines };
}

//: Default guide colours, one per `kind` `wbAlignmentGuides` can report: 
//: "edge" (an outer border lining up with another), "center" (mid-points
//: lining up, the draw.io/PowerPoint convention of a *different* colour so
//: the two are never confused at a glance), and "spacing" (equal gaps).
//: Overridable per the direct ask ("colours should be alterable"); the
//: picker lives in the whiteboard's own shape-menu dropdown rather than a
//: new top menu bar, see HISTORY.md for why that redesign is deferred.
const WB_ALIGN_GUIDE_COLORS = { edge: "#ff00ff", center: "#00c8ff", spacing: "#3ddc84" };
function wbAlignGuideColor(kind) {
  return localStorage.getItem(`wb-guide-color-${kind}`) || WB_ALIGN_GUIDE_COLORS[kind] || WB_ALIGN_GUIDE_COLORS.edge;
}

//: Draws (or clears) the dashed guide lines `wbAlignmentGuides` found: 
//: shared by every drag handler that uses it, same reasoning as
//: `wbShowAnchorHints`'s own shared group.
function wbShowAlignmentGuides(lines) {
  const zoomGroup = document.getElementById("wb-zoom-group");
  if (!zoomGroup) return;
  let group = document.getElementById("wb-align-guides");
  if (!group) {
    group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("id", "wb-align-guides");
    group.setAttribute("pointer-events", "none");
    zoomGroup.appendChild(group);
  }
  group.innerHTML = "";
  for (const line of lines) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", "line");
    el.setAttribute("x1", line.x1);
    el.setAttribute("y1", line.y1);
    el.setAttribute("x2", line.x2);
    el.setAttribute("y2", line.y2);
    el.setAttribute("class", `wb-align-guide-line wb-align-guide-${line.kind || "edge"}`);
    el.setAttribute("stroke", wbAlignGuideColor(line.kind || "edge"));
    group.appendChild(el);
  }
}

function wbClearAlignmentGuides() {
  document.getElementById("wb-align-guides")?.remove();
}

function wbApplyGrid() {
  const el = document.getElementById("whiteboard-container");
  if (!el) return;
  el.dataset.wbGrid = wbGridType();
  wbSyncGridToTransform();
}

//: A board's own background image, kept per board in localStorage the same
//: way its background colour already is, it is a property of how you like
//: to look at that board, not notebook data, and storing it server-side
//: would mean a schema column for something the server never reads.
function wbBgImageKey() {
  return `wb-bg-image-${window.currentBoardId ?? "default"}`;
}

function wbApplyBgImage() {
  const el = document.getElementById("whiteboard-container");
  if (!el) return;
  const url = localStorage.getItem(wbBgImageKey());
  // `mediaSrc`, not the bare url, a CSS `background-image: url(...)` is a
  // plain resource load, same as `<img src>`, so it never attaches
  // X-Auth-Token either.
  el.style.setProperty("--wb-bg-image", url ? `url("${mediaSrc(url)}")` : "none");
}

// A tiny inline SVG baked into a `cursor:` value, so the OS/GPU renders and
// positions it: zero JS on the hot path. This replaces an earlier version
// that tracked the pointer with a `mousemove`-positioned `<div>`: reported
// (and reproduced) as "my mouse keeps snapping to an invisible grid", a
// JS-positioned cursor only moves on however often `mousemove` actually
// fires, which is both slower and less regular than the compositor placing
// a real cursor image, so on a fast swipe the dot visibly lagged and then
// jumped to catch up. A `cursor:` image has no such step: once set, the
// browser draws it exactly like the system arrow.
function wbCursorUrl(inner, { size = 26, hx = 3, hy = size - 3 } = {}) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" ` +
    `viewBox="0 0 ${size} ${size}">${inner}</svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}") ${hx} ${hy}`;
}

// Asked for directly: the sketch pad is meant to be a lite version of the
// whiteboard, so the whiteboard should have at least everything the sketch
// pad does. It already covered pen ("draw"), line, rect, circle and
// eraser; highlighter and arrow were the two genuinely missing ones (a
// third, text, needs its own SVG element type, a `<path>` can't render
// text: and is scoped separately rather than force-fit into this list).
const WB_BRUSH_TOOLS = new Set(["draw", "line", "rect", "circle", "highlighter", "arrow", "triangle", "diamond"]);
//: **The highlighter is a marker that multiplies** (WHITEBOARD_PLAN.md
//: decision 7: "marker with `mix-blend-mode: multiply` at 40% opacity, width
//: 12 to 24, Shift for straight"), which is what FigJam and Apple Freeform
//: both do and what makes two crossing strokes read as two passes of one pen
//: rather than as a third, lighter colour. 0.4, not 0.35: the plan's figure,
//: and multiply darkens where plain alpha did not, so the old number would
//: have made it fainter than it was.
const WB_HIGHLIGHTER_ALPHA = 0.4; // matches the sketch pad's own SKETCH_HIGHLIGHTER_ALPHA
//: A nib, not a scaled pen. The width slider runs 1 to 24 and this was four
//: times it, so a highlighter could be 4px (a pen) or 96px (a wall). Clamped
//: to the plan's 12 to 24, which is the range a real highlighter has.
const WB_HIGHLIGHTER_MIN = 12;
const WB_HIGHLIGHTER_MAX = 24;
//: Takes the pen width rather than reading it: `WB_STROKE_WIDTH` is a `let`
//: inside `initWhiteboard`, not a module constant, so a module-level function
//: that read it threw `WB_STROKE_WIDTH is not defined` on the first stroke
//: (found by the sweep, which drew nothing at all and said so).
function wbHighlighterWidth(penWidth) {
  return Math.min(WB_HIGHLIGHTER_MAX, Math.max(WB_HIGHLIGHTER_MIN, (penWidth || 3) * 4));
}

//: The four closed shape tools fill applies to, a pen/highlighter/line/
//: arrow stroke has no enclosed area a fill would read as filling. Module
//: scope (not inside `initWhiteboard`) since both the live-draw handlers
//: and `renderWhiteboard` (a separate top-level function) need it.
const WB_FILLABLE_SHAPES = new Set(["rect", "circle", "triangle", "diamond"]);

//: SVG `stroke-dasharray` for each style, scaled to the actual stroke width
//: so a thick dashed line doesn't look like a row of dots. `null` (solid)
//: means "don't set the attribute at all", not "set it to empty".
function wbDashArray(style, width) {
  if (style === "dashed") return `${width * 3} ${width * 2}`;
  if (style === "dotted") return `${width} ${width * 1.6}`;
  return null;
}

//: Two head-stroke subpaths meeting at `(tipX, tipY)`, angled back from
//: `approachAngle` (the direction the shaft arrives *from*, in radians), 
//: factored out so both ends of an arrow can draw one (`currentArrowEndStyle`,
//: reported directly: "can't change arrow heads").
//: Absolute width/height for a shape drawn from `(0,0)` to `(dx, dy)`, 
//: equal (a square/perfect circle) while `shiftHeld`, matching the sketch
//: pad's own rect tool (HISTORY.md) and asked for again directly for the
//: whiteboard's shapes generally. Squares to the *larger* of the two raw
//: dimensions so the shape still reaches all the way to the cursor.
function wbShapeDims(dx, dy, shiftHeld) {
  const w = Math.abs(dx), h = Math.abs(dy);
  if (!shiftHeld) return { w, h };
  const s = Math.max(w, h);
  return { w: s, h: s };
}

function wbArrowHeadPath(tipX, tipY, approachAngle, headLen) {
  const h1x = tipX - headLen * Math.cos(approachAngle - Math.PI / 6);
  const h1y = tipY - headLen * Math.sin(approachAngle - Math.PI / 6);
  const h2x = tipX - headLen * Math.cos(approachAngle + Math.PI / 6);
  const h2y = tipY - headLen * Math.sin(approachAngle + Math.PI / 6);
  return `M ${tipX} ${tipY} L ${h1x} ${h1y} M ${tipX} ${tipY} L ${h2x} ${h2y}`;
}

//: Every cap kind a line/arrow/link end can wear, asked for directly ("a
//: full line/arrow end-cap system... circle/square/multi-line ends,
//: independently per end"), the shared arrowhead control only ever grew
//: from Arrow-only to Line-and-Arrow, still one shape. Each is its own
//: closed subpath appended to the shaft's own `d`, same convention
//: `wbArrowHeadPath` already established (a stroked path, no separate SVG
//: element, so hit-testing/move/resize/export keep treating the whole
//: sketch as the one path they already know how to handle), "arrow" here
//: is exactly `wbArrowHeadPath`'s own two-line V, kept for a single call
//: site to switch on.
const WB_CAP_KINDS = ["none", "arrow", "circle", "square", "multiline"];

function wbCapPath(kind, tipX, tipY, approachAngle, headLen) {
  if (!kind || kind === "none") return "";
  if (kind === "arrow") return wbArrowHeadPath(tipX, tipY, approachAngle, headLen);
  if (kind === "circle") {
    const r = headLen / 3;
    // Centred a radius back from the tip along the shaft, so the circle
    // sits *at* the end rather than half hanging past it.
    const cx = tipX - r * Math.cos(approachAngle), cy = tipY - r * Math.sin(approachAngle);
    return `M ${cx - r} ${cy} A ${r} ${r} 0 1 0 ${cx + r} ${cy} A ${r} ${r} 0 1 0 ${cx - r} ${cy} Z`;
  }
  if (kind === "square") {
    const s = headLen / 2.6;
    const cx = tipX - s * Math.cos(approachAngle), cy = tipY - s * Math.sin(approachAngle);
    const cos = Math.cos(approachAngle), sin = Math.sin(approachAngle);
    const corner = (dx, dy) => `${cx + dx * cos - dy * sin} ${cy + dx * sin + dy * cos}`;
    return `M ${corner(-s, -s)} L ${corner(s, -s)} L ${corner(s, s)} L ${corner(-s, s)} Z`;
  }
  // "multiline": two short perpendicular ticks near the tip, the
  // ER-diagram "many" mark, and a visually distinct third option from a
  // filled dot or square rather than a second arrow variant.
  const cos = Math.cos(approachAngle), sin = Math.sin(approachAngle);
  const perpX = -sin, perpY = cos;
  const half = headLen * 0.4;
  const tick = (back) => {
    const bx = tipX - cos * back, by = tipY - sin * back;
    return `M ${bx - perpX * half} ${by - perpY * half} L ${bx + perpX * half} ${by + perpY * half}`;
  };
  return `${tick(headLen * 0.35)} ${tick(headLen * 0.75)}`;
}

function wbCursorForTool(tool, strokeColor, strokeWidth) {
  const color = /^#[0-9a-fA-F]{3,8}$/.test(strokeColor || "") ? strokeColor : "#ffffff";
  if (WB_BRUSH_TOOLS.has(tool)) {
    // A crosshair with a dot in the actual stroke colour at its centre, a
    // plain crosshair can't say what colour is about to land. The dot's own
    // radius now tracks the stroke-width slider too (asked for directly:
    // "the size should be represented on the cursor tip"), clamped to what
    // a 32x32 cursor image can actually show and still stay a browser-legal
    // cursor size cross-platform (Safari caps well below Chrome/Firefox).
    const size = 32, c = size / 2;
    const r = Math.max(3, Math.min(13, Math.round((Number(strokeWidth) || 3) / 2) + 2));
    const inner =
      `<line x1="${c}" y1="1" x2="${c}" y2="${c - r - 2}" stroke="#000" stroke-opacity=".55" stroke-width="1.5"/>` +
      `<line x1="${c}" y1="${c + r + 2}" x2="${c}" y2="${size - 1}" stroke="#000" stroke-opacity=".55" stroke-width="1.5"/>` +
      `<line x1="1" y1="${c}" x2="${c - r - 2}" y2="${c}" stroke="#000" stroke-opacity=".55" stroke-width="1.5"/>` +
      `<line x1="${c + r + 2}" y1="${c}" x2="${size - 1}" y2="${c}" stroke="#000" stroke-opacity=".55" stroke-width="1.5"/>` +
      `<circle cx="${c}" cy="${c}" r="${r}" fill="${color}" stroke="#000" stroke-opacity=".45"/>`;
    return `${wbCursorUrl(inner, { size, hx: c, hy: c })}, crosshair`;
  }
  if (tool === "eraser") {
    const inner =
      `<g transform="rotate(-30 13 13)">` +
      `<rect x="4" y="9" width="16" height="10" rx="2" fill="#f4d9d9" stroke="#8a4a4a" stroke-width="1.5"/>` +
      `<rect x="4" y="9" width="7" height="10" rx="2" fill="#e7bcbc"/>` +
      `</g>`;
    return `${wbCursorUrl(inner, { hx: 6, hy: 20 })}, cell`;
  }
  if (tool === "delete") {
    const inner =
      `<path d="M6 7h14M11 7V4h4v3M9 7l1 15h6l1-15" fill="none" stroke="#d9534f" ` +
      `stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
    return `${wbCursorUrl(inner, { hx: 13, hy: 3 })}, not-allowed`;
  }
  if (tool === "link-straight" || tool === "link-curved") return "crosshair";
  if (tool === "lasso") return "crosshair";
  // Bucket, sticky and text had no case here, so all three fell through to
  // the `""` Pan returns, and `""` means "whatever the CSS says", which for
  // `.whiteboard-container` is `cursor: grab`: measured, three of the app's
  // eighteen board tools showed the open hand that means "drag the canvas"
  // while a click would have filled a shape, dropped a sticky or placed a
  // text box. Same fall-through that Select was fixed for, three tools later.
  if (tool === "bucket") {
    // A tipped bucket with a drip in the colour that is about to land, the
    // same "the cursor says what colour" idea the brush crosshair carries.
    const inner =
      `<g transform="rotate(-35 13 12)">` +
      `<path d="M6 8h12l-1.6 9.5a2 2 0 0 1-2 1.7h-4.8a2 2 0 0 1-2-1.7Z" fill="${color}" ` +
      `stroke="#000" stroke-opacity=".55" stroke-width="1.5" stroke-linejoin="round"/>` +
      `<path d="M6 8h12" fill="none" stroke="#000" stroke-opacity=".55" stroke-width="1.5"/>` +
      `</g>` +
      `<path d="M20 16c1.6 2 2.4 3.2 2.4 4.1a2.4 2.4 0 0 1-4.8 0c0-.9.8-2.1 2.4-4.1Z" ` +
      `fill="${color}" stroke="#000" stroke-opacity=".45" stroke-width="1"/>`;
    return `${wbCursorUrl(inner, { hx: 4, hy: 4 })}, crosshair`;
  }
  // `copy` and `text` rather than two more drawn images: both are system
  // cursors that already mean exactly this ("this click makes a new thing"
  // and "text goes here"), and a system cursor is the one that stays legible
  // over any board colour on any platform.
  if (tool === "sticky") return "copy";
  if (tool === "text") return "text";
  // Reported directly: "the cursor on the selection tool is wrong, it should
  // be a mouse pointer." Select had no case here, so it fell through to the
  // same `""` Pan returns: and `""` means "whatever the CSS says", which for
  // `.whiteboard-container` is `cursor: grab`. So the one tool whose whole
  // job is clicking things showed the open hand that means "drag the canvas",
  // and the two modes were indistinguishable from the pointer alone. `default`
  // (the plain arrow) is what every drawing app shows for select.
  if (tool === "select") return "default";
  return ""; // pan: the CSS grab/grabbing pair already says it
}

// The visible half of Select, asked for directly ("select... as a real
// tool, not folded into pan"). Re-applied after every `wbScheduleRender()`
// (elements are rebuilt on each render, so a class set on the old DOM node
// would vanish silently) as well as right after a click.
const WB_SELECTOR_BY_KIND = {
  sketch: (id) => `.sketch-group[data-id="${id}"]`,
  node: (id) => `.node-card[data-id="${id}"]`,
  object: (id) => `.wb-object[data-id="${id}"]`,
};

const wbMultiKey = (kind, id) => `${kind}:${id}`;

// Asked for directly, more than once: "changing properties of shapes and
// text boxes... fill, border". Single-selection only: the same reasoning
// Grouping: asked for directly (Ctrl+G / Ctrl+Shift+G). Unlike
// `wbMultiSelection` (in-memory, gone on reload), a group's id is persisted
// on every member's own `group_id` column, so clicking any one member later
// reselects the whole set, the other half of this feature lives in
// `wbHandleItemClick` below.
async function wbGroupSelection() {
  if (wbMultiSelection.size < 2) {
    toast("Select more than one item to group them.");
    return;
  }
  const groupId = crypto.randomUUID ? crypto.randomUUID() : `g${Date.now()}${Math.random().toString(36).slice(2)}`;
  for (const key of wbMultiSelection) {
    const sep = key.indexOf(":");
    const kind = key.slice(0, sep), id = Number(key.slice(sep + 1));
    const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
    if (!item) continue;
    item.group_id = groupId;
    if (kind === "sketch") await wbSaveSketchProps(item, {});
    else if (kind === "node") await wbSaveNode(item);
    else await wbSaveObject(item);
  }
  toast("Grouped.");
}

//: Clears `group_id` on every currently-selected member, the current
//: selection is either a multi-selection built by hand, or (per
//: `wbHandleItemClick`'s own group-select branch) already the whole group,
//: since clicking any one grouped member selects all of it.
async function wbUngroupSelection() {
  const keys = wbMultiSelection.size > 0
    ? [...wbMultiSelection]
    : wbSelectedItem ? [wbMultiKey(wbSelectedItem.kind, wbSelectedItem.id)] : [];
  if (keys.length === 0) return;
  let ungrouped = 0;
  for (const key of keys) {
    const sep = key.indexOf(":");
    const kind = key.slice(0, sep), id = Number(key.slice(sep + 1));
    const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
    if (!item || !item.group_id) continue;
    item.group_id = null;
    ungrouped++;
    if (kind === "sketch") await wbSaveSketchProps(item, {});
    else if (kind === "node") await wbSaveNode(item);
    else await wbSaveObject(item);
  }
  if (ungrouped) toast("Ungrouped.");
}

//: A kind-agnostic bounding box (board coordinates, top-left/bottom-right)
//: for alignment/distribute/nudge math, which all need to compare items of
//: different kinds against each other. A sketch has no width/height of its
//: own, its path data *is* its shape, so its box comes from
//: `wbPathBBox`, while a card/object's box is just its x/y plus whichever
//: width/height it currently has (falling back to the same defaults their
//: own resize code uses).
function wbItemBBox(kind, item) {
  if (kind === "sketch") {
    // Mid-drag the moving path lives in `_dragLiveD`; the stored `data` is
    // still where the shape started, and a link following it would lag a
    // whole gesture behind.
    if (typeof item._dragLiveD === "string") return wbPathBBox(item._dragLiveD);
    const parsed = wbSketchParsedData(item);
    if (!parsed) return null; // a link sketch: no shape of its own to align
    return wbPathBBox(parsed.d);
  }
  let w = item.width, h = item.height;
  // A card with no stored size (never manually resized) grows to fit its own
  // text: reported directly, with a screenshot: link anchor points sat well
  // inside a tall card's real border, because every unresized card was
  // assumed to be exactly WB_CARD_DEFAULT_SIZE.h (150px) regardless of how
  // much taller its actual content rendered it. Measured from the live DOM
  // instead, converted to board space with the same zoom-transform division
  // every drag handler already uses (`transform.k`), falls back to the
  // fixed default below only when the element genuinely isn't rendered.
  if (kind === "node") {
    const el = document.querySelector(`.node-card[data-id="${item.id}"]`);
    if (el && el.offsetWidth && el.offsetHeight) {
      // Rendered size wins over a stored one for the same reason as
      // objects below: a card's text can push it taller than the height it
      // was last resized to.
      w = el.offsetWidth;
      h = el.offsetHeight;
    } else if (el) {
      // `offsetWidth/Height`, not `getBoundingClientRect()`: the rect is the
      // axis-aligned box of the *rotated* card, wider and taller than the
      // card itself, so a rotated note's links landed on a box that does
      // not exist (reported: "I rotated a note and the connection didn't
      // stick to the edge"). Layout size is unrotated and unscaled.
      w = w || el.offsetWidth;
      h = h || el.offsetHeight;
    }
  }
  // A text box or sticky can render taller than its stored height once its
  // text wraps (the element grows; the row does not), so the rendered size
  // wins when the element is on screen, a link aimed at the stored box
  // stopped short of the visible one.
  if (kind === "object") {
    const el = document.querySelector(`.wb-object[data-id="${item.id}"]`);
    if (el && el.offsetWidth && el.offsetHeight) {
      w = el.offsetWidth;
      h = el.offsetHeight;
    }
  }
  w = w || (kind === "node" ? WB_CARD_DEFAULT_SIZE.w : WB_OBJECT_MIN_SIZE);
  h = h || (kind === "node" ? WB_CARD_DEFAULT_SIZE.h : WB_OBJECT_MIN_SIZE);
  return { minX: item.x, minY: item.y, maxX: item.x + w, maxY: item.y + h };
}

// --- Getting around a board bigger than the screen -------------------------
//
// Three things any canvas needs once it holds more than one screenful, none
// of which this board had. Measured on a live board before building, rather
// than assumed:
//
//   * **There was no overview at all.** `board-minimap` in this file is the
//     *library thumbnail* drawn on a board's card in Boards & maps, it never
//     rendered on the canvas and has no viewport rectangle. Searching the DOM
//     of an open board for `.wb-minimap`/`#wb-minimap` found nothing.
//   * **There was no way to find a card by its words.** A board is made of
//     notes, and the notebook can full-text search every note in it, except
//     when they are laid out on a board, where the only way to find one was
//     to pan around looking.
//   * **"Fit to Screen" did not fit.** It was
//     `wbZoom.transform(d3.zoomIdentity)`, a reset to 100% at the origin. On
//     a board whose content sits at x=2000 that shows blank canvas, which
//     reads as the board having been wiped rather than as a navigation bug.
//
// All three are answered here, and all three share `wbContentBounds()`.

/** The bounding box of everything on the board, in board coordinates. */
function wbContentBounds() {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const grow = (box) => {
    if (!box) return;
    if (box.minX < minX) minX = box.minX;
    if (box.minY < minY) minY = box.minY;
    if (box.maxX > maxX) maxX = box.maxX;
    if (box.maxY > maxY) maxY = box.maxY;
  };
  // `wbItemBBox` already knows every kind's quirks: a link sketch has no
  // shape of its own and returns null, an unresized card is measured from
  // the live DOM. Reusing it is what keeps the navigator, the fit and the
  // search agreeing with the alignment guides about where things are.
  for (const [kind, list] of Object.entries(WB_LIST_BY_KIND)) {
    for (const item of wbState[list] || []) grow(wbItemBBox(kind, item));
  }
  if (!Number.isFinite(minX)) return null;
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
}

/**
 * Put everything on the board on screen at once.
 *
 * Never zooms *in* past 1: `scaleExtent` allows 4x, but magnifying two cards
 * until they fill a 1440px window is not what anyone means by "fit".
 */
function wbZoomToFit({ animate = true, padding = 64 } = {}) {
  const container = document.getElementById("whiteboard-container");
  if (!container) return;
  const sel = d3.select(container);
  const bounds = wbContentBounds();
  if (!bounds) {
    // An empty board genuinely has nothing to fit, and the origin at 100% is
    // where the first card will land, so that is the honest destination.
    (animate ? sel.transition().duration(300) : sel).call(wbZoom.transform, d3.zoomIdentity);
    return;
  }
  const rect = container.getBoundingClientRect();
  const k = Math.max(
    0.1,
    Math.min(
      1,
      (rect.width - padding * 2) / Math.max(bounds.width, 1),
      (rect.height - padding * 2) / Math.max(bounds.height, 1),
    ),
  );
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;
  const target = d3.zoomIdentity
    .translate(rect.width / 2 - k * cx, rect.height / 2 - k * cy)
    .scale(k);
  (animate ? sel.transition().duration(350) : sel).call(wbZoom.transform, target);
}

//: A fit tighter than this is a map you cannot read: the nodes are there, the
//: words in them are not. Below it, framing the root at 1:1 beats fitting the
//: whole tree, which is what every map tool does on open.
const WB_MAP_OPEN_MIN_SCALE = 0.45;

//: **Frame a map when it opens**, rather than leaving the canvas wherever the
//: last board left it.
//:
//: Reported (mindmap.md H item 2, measured while reproducing report B): a map
//: whose root sits at the board origin opens with that root under
//: `#wb-topbar`, and a double-click on its text hits the top bar instead of
//: the node. Measured before this: the root's box was (16, 128)-(216, 172)
//: against a top bar of (24, 136)-(1416, 182), and `elementFromPoint` at the
//: root's own centre returned a top-bar button.
//:
//: Fit first, because a map is a tree and its shape is the point; but a fit
//: that lands under `WB_MAP_OPEN_MIN_SCALE` is a picture of a map rather than
//: a map, so a big one opens on its root at 1:1 instead. Only maps: an
//: ordinary board is a place you arrange by hand, and re-framing one on every
//: open would throw away the view its owner left it in.
function wbFrameMapOnOpen() {
  if (!wbIsMap()) return;
  const container = document.getElementById("whiteboard-container");
  if (!container) return;
  wbZoomToFit({ animate: false });
  if (d3.zoomTransform(container).k >= WB_MAP_OPEN_MIN_SCALE) return;
  const root = wbMapIndex().roots[0];
  //: `minScale: 1`, and `wbCenterOn` takes the larger of that and the current
  //: zoom: the fit just above left the canvas at something illegible, so this
  //: is the one call that has to be allowed to zoom back in.
  if (root) wbCenterOn(wbItemBBox("object", root), { animate: false, minScale: 1 });
}

/** Centre the viewport on one board-space rectangle, keeping the current zoom. */
function wbCenterOn(box, { animate = true, minScale = 0.55 } = {}) {
  const container = document.getElementById("whiteboard-container");
  if (!container || !box) return;
  const sel = d3.select(container);
  const rect = container.getBoundingClientRect();
  const current = d3.zoomTransform(container);
  // Jumping to a match at 0.12x would land on a card too small to read, so
  // ease the zoom up to something legible, but never zoom *out* to get
  // there, because that would undo a deliberate close-up.
  const k = Math.max(current.k, Math.min(minScale, 1));
  const cx = (box.minX + box.maxX) / 2;
  const cy = (box.minY + box.maxY) / 2;
  const target = d3.zoomIdentity
    .translate(rect.width / 2 - k * cx, rect.height / 2 - k * cy)
    .scale(k);
  (animate ? sel.transition().duration(300) : sel).call(wbZoom.transform, target);
}

// --- The navigator (a live minimap) ----------------------------------------
//
// Deliberately *not* a fifth always-on floating panel. The canvas already
// carries four, and this file's own CSS comments record two separate reports
// of them colliding with each other and running off narrow screens. It opens
// from a button in the zoom cluster, where fit and full screen already live,
// so it sits with the other "where am I" controls: and closes again.

const WB_NAV_W = 208;
const WB_NAV_H = 132;
const WB_NAV_PAD = 6;

function wbNavigatorOpen() {
  const panel = document.getElementById("wb-navigator");
  return !!panel && !panel.classList.contains("hidden");
}

/** Board coordinates -> navigator coordinates, or null on an empty board. */
function wbNavigatorProjection() {
  const bounds = wbContentBounds();
  const container = document.getElementById("whiteboard-container");
  if (!bounds || !container) return null;
  const rect = container.getBoundingClientRect();
  const t = d3.zoomTransform(container);
  // The navigator shows the content *and* wherever the viewport currently is,
  // so a viewport panned off into empty space still draws a rectangle you can
  // drag back: union the two before scaling, or the rectangle silently
  // clamps to the edge and stops telling the truth about where you are.
  const view = {
    minX: (0 - t.x) / t.k,
    minY: (0 - t.y) / t.k,
    maxX: (rect.width - t.x) / t.k,
    maxY: (rect.height - t.y) / t.k,
  };
  const minX = Math.min(bounds.minX, view.minX);
  const minY = Math.min(bounds.minY, view.minY);
  const maxX = Math.max(bounds.maxX, view.maxX);
  const maxY = Math.max(bounds.maxY, view.maxY);
  const w = Math.max(maxX - minX, 1);
  const h = Math.max(maxY - minY, 1);
  const k = Math.min((WB_NAV_W - WB_NAV_PAD * 2) / w, (WB_NAV_H - WB_NAV_PAD * 2) / h);
  const offX = WB_NAV_PAD + ((WB_NAV_W - WB_NAV_PAD * 2) - w * k) / 2;
  const offY = WB_NAV_PAD + ((WB_NAV_H - WB_NAV_PAD * 2) - h * k) / 2;
  return {
    k,
    view,
    toNav: (x, y) => [offX + (x - minX) * k, offY + (y - minY) * k],
    toBoard: (nx, ny) => [minX + (nx - offX) / k, minY + (ny - offY) / k],
  };
}

function wbRenderNavigator() {
  const svg = document.getElementById("wb-navigator-map");
  const empty = document.getElementById("wb-navigator-empty");
  if (!svg || !wbNavigatorOpen()) return;
  const proj = wbNavigatorProjection();
  const bounds = wbContentBounds();
  svg.replaceChildren();
  if (empty) empty.classList.toggle("hidden", !!bounds);
  svg.classList.toggle("hidden", !bounds);
  if (!proj || !bounds) return;
  const NS = "http://www.w3.org/2000/svg";
  const add = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    // Attributes, never a `style` string: this app's CSP rejects inline
    // styles outright, and thirty-five of them once shipped as silently dead
    // markup (CLAUDE.md, "a policy silently refusing the work").
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
    svg.append(el);
    return el;
  };
  for (const [kind, list] of Object.entries(WB_LIST_BY_KIND)) {
    for (const item of wbState[list] || []) {
      const box = wbItemBBox(kind, item);
      if (!box) continue;
      const [x, y] = proj.toNav(box.minX, box.minY);
      const w = Math.max((box.maxX - box.minX) * proj.k, 2);
      const h = Math.max((box.maxY - box.minY) * proj.k, 2);
      const selected = wbMultiSelection.has(wbMultiKey(kind, item.id))
        || (wbSelectedItem && wbSelectedItem.kind === kind && wbSelectedItem.id === item.id);
      add("rect", {
        x, y, width: w, height: h, rx: 1,
        class: `wb-nav-item wb-nav-item-${kind}${selected ? " is-selected" : ""}`,
      });
    }
  }
  const [vx, vy] = proj.toNav(proj.view.minX, proj.view.minY);
  add("rect", {
    x: vx,
    y: vy,
    width: Math.max((proj.view.maxX - proj.view.minX) * proj.k, 4),
    height: Math.max((proj.view.maxY - proj.view.minY) * proj.k, 4),
    class: "wb-nav-viewport",
  });
}

/** Move the viewport so its centre lands where the navigator was clicked. */
function wbNavigatorJump(event) {
  const svg = document.getElementById("wb-navigator-map");
  const proj = wbNavigatorProjection();
  if (!svg || !proj) return;
  const rect = svg.getBoundingClientRect();
  // The SVG is laid out at exactly WB_NAV_W x WB_NAV_H, but a browser zoom or
  // a future responsive tweak could scale it, divide through by the real
  // rendered size rather than trusting the constants.
  const nx = ((event.clientX - rect.left) / rect.width) * WB_NAV_W;
  const ny = ((event.clientY - rect.top) / rect.height) * WB_NAV_H;
  const [bx, by] = proj.toBoard(nx, ny);
  wbCenterOn({ minX: bx, minY: by, maxX: bx, maxY: by }, { animate: false, minScale: 0 });
}

function wbToggleNavigator(force) {
  const panel = document.getElementById("wb-navigator");
  const button = document.getElementById("wb-navigator-toggle");
  if (!panel) return;
  const open = force === undefined ? panel.classList.contains("hidden") : force;
  panel.classList.toggle("hidden", !open);
  if (button) button.setAttribute("aria-expanded", open ? "true" : "false");
  try {
    localStorage.setItem("wb-navigator-open", open ? "1" : "0");
  } catch {
    /* private mode: the navigator just won't be remembered */
  }
  if (open) wbRenderNavigator();
}

// --- Find a card on this board ---------------------------------------------

const wbBoardSearch = { query: "", matches: [], index: -1 };

/**
 * Every searchable string an item carries, lowercased.
 *
 * `byId` is built once per search run rather than per item, `allEntries` is
 * the whole notebook, and re-Mapping it for each of a board's cards on every
 * keystroke is the kind of quiet quadratic that only shows up on someone
 * else's larger notebook.
 *
 * **Not `entriesById`.** That map is a `const` *inside* `renderWhiteboard`,
 * so it does not exist out here, a first cut guarded with
 * `typeof entriesById !== "undefined"`, which meant the guard silently
 * returned "" and the search matched nothing at all while looking like it
 * worked. Caught by driving it in a browser, not by reading it.
 */
function wbSearchTextFor(kind, item, byId) {
  if (kind === "node") {
    const entry = byId ? byId.get(String(item.entry_id)) : null;
    if (entry) return ((entry.content || entry.preview) || "").toLowerCase();
    // The note is not in the in-memory list (created since the last
    // `loadEntries()`), but its card is on screen with its text in it, so
    // read what the person can actually see rather than reporting no match
    // for a card they are looking straight at.
    const el = document.querySelector(`.node-card[data-id="${item.id}"] .wb-card-content`);
    return (el?.textContent || "").toLowerCase();
  }
  if (kind === "object") {
    // A text box keeps its words in the same `data` JSON blob an image keeps
    // its URL in (see WhiteboardObject's own docstring), so a bad parse here
    // means "not searchable", never a thrown render.
    try {
      const data = JSON.parse(item.data || "{}");
      return String(data.content || "").toLowerCase();
    } catch {
      return "";
    }
  }
  return "";
}

function wbBoardSearchRun(query) {
  wbBoardSearch.query = query;
  wbBoardSearch.matches = [];
  wbBoardSearch.index = -1;
  const needle = query.trim().toLowerCase();
  if (needle) {
    const byId = new Map(
      (typeof allEntries !== "undefined" && Array.isArray(allEntries) ? allEntries : []).map((e) => [
        String(e.id),
        e,
      ]),
    );
    for (const kind of ["node", "object"]) {
      for (const item of wbState[WB_LIST_BY_KIND[kind]] || []) {
        if (wbSearchTextFor(kind, item, byId).includes(needle)) {
          wbBoardSearch.matches.push({ kind, id: item.id });
        }
      }
    }
    // Reading order, so pressing Enter walks the board top-to-bottom rather
    // than in whatever order the two lists happened to load.
    wbBoardSearch.matches.sort((a, b) => {
      const ba = wbItemBBox(a.kind, wbSearchItem(a));
      const bb = wbItemBBox(b.kind, wbSearchItem(b));
      if (!ba || !bb) return 0;
      return ba.minY - bb.minY || ba.minX - bb.minX;
    });
  }
  wbApplySearchHighlight();
  wbUpdateSearchCount();
  if (wbBoardSearch.matches.length) wbBoardSearchGo(0);
}

function wbSearchItem(match) {
  return (wbState[WB_LIST_BY_KIND[match.kind]] || []).find((i) => i.id === match.id) || null;
}

function wbApplySearchHighlight() {
  const wanted = new Set(wbBoardSearch.matches.map((m) => wbMultiKey(m.kind, m.id)));
  const current = wbBoardSearch.index >= 0 ? wbBoardSearch.matches[wbBoardSearch.index] : null;
  const currentKey = current ? wbMultiKey(current.kind, current.id) : null;
  for (const el of document.querySelectorAll("#wb-html-layer [data-id], #wb-zoom-group [data-id]")) {
    const kind = el.classList.contains("node-card")
      ? "node"
      : el.classList.contains("wb-object")
      ? "object"
      : null;
    if (!kind) continue;
    const key = wbMultiKey(kind, Number(el.dataset.id));
    el.classList.toggle("wb-search-hit", wanted.has(key));
    el.classList.toggle("wb-search-current", key === currentKey);
  }
}

function wbUpdateSearchCount() {
  const el = document.getElementById("wb-search-count");
  if (!el) return;
  const total = wbBoardSearch.matches.length;
  if (!wbBoardSearch.query.trim()) {
    el.textContent = "";
    return;
  }
  // "3 of 12", not a bare number, a screen reader reading this aria-live
  // region needs to know which of how many, and so does everyone else.
  el.textContent = total ? `${wbBoardSearch.index + 1} of ${total}` : "No matches";
}

/** Step through the matches, wrapping at both ends. */
function wbBoardSearchGo(delta) {
  const total = wbBoardSearch.matches.length;
  if (!total) return;
  const next = wbBoardSearch.index < 0 ? 0 : (wbBoardSearch.index + delta + total) % total;
  wbBoardSearch.index = next;
  const match = wbBoardSearch.matches[next];
  const item = wbSearchItem(match);
  const box = item ? wbItemBBox(match.kind, item) : null;
  if (box) wbCenterOn(box);
  wbApplySearchHighlight();
  wbUpdateSearchCount();
}

function wbCloseBoardSearch() {
  const bar = document.getElementById("wb-search-bar");
  if (!bar) return;
  bar.classList.add("hidden");
  wbBoardSearch.query = "";
  wbBoardSearch.matches = [];
  wbBoardSearch.index = -1;
  wbApplySearchHighlight();
  document.getElementById("whiteboard-container")?.focus?.();
}

function wbOpenBoardSearch() {
  const bar = document.getElementById("wb-search-bar");
  const input = document.getElementById("wb-search-input");
  if (!bar || !input) return;
  bar.classList.remove("hidden");
  input.focus();
  input.select();
}

//: Real anchor/connection points for links (asked for directly, "take
//: inspiration from draw.io", named "worth its own session" three sessions
//: running: HANDOVER.md §53-55). Eight **fixed** points (corners + edge
//: midpoints), as fractions of the shape's own bounding box so a resize
//: carries an anchor with it for free, no migration needed, these two
//: fractions just live as `sourceAnchor`/`targetAnchor` keys in the link
//: sketch's existing `data` JSON blob. Omitting either key is the **free**
//: case: that end "floats", auto-following the rectangle border facing
//: whatever the other end resolves to, every render, draw.io's own
//: behaviour, not a fixed centre-point offset.
const WB_FIXED_ANCHORS = [
  { x: 0, y: 0 }, { x: 0.5, y: 0 }, { x: 1, y: 0 },
  { x: 1, y: 0.5 }, { x: 1, y: 1 }, { x: 0.5, y: 1 },
  { x: 0, y: 1 }, { x: 0, y: 0.5 },
];

//: A link only ever connects nodes (cards) today: see `dragEndNode`'s own
//: hit-test: but takes `kind` rather than assuming "node" so a future
//: object-to-object link doesn't need this rewritten.
//: **Endpoints follow rotation.** Reported with a screenshot: "if I rotate
//: a textbox or shape, the connections no longer fit to the edge and just
//: float in mid air." Cards and objects store `rotation` (degrees, about
//: the box centre) and were measured as their *unrotated* box; a drawn
//: shape bakes its rotation into the path, so its axis-aligned bbox is a
//: superset of the shape and a ray to the bbox edge stops short of it.
//: Two plain pieces of geometry fix both: rotate a point about a centre, and
//: intersect a ray with the shape's own outline.
function wbItemRotation(kind, item) {
  if (kind === "sketch") return 0;
  const deg = Number(item?.rotation);
  return Number.isFinite(deg) ? deg : 0;
}

function wbRotatePoint(pt, center, deg) {
  if (!deg) return pt;
  const rad = (deg * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  const dx = pt.x - center.x, dy = pt.y - center.y;
  return { x: center.x + dx * cos - dy * sin, y: center.y + dx * sin + dy * cos };
}

function wbBoxCenter(box) {
  return { x: (box.minX + box.maxX) / 2, y: (box.minY + box.maxY) / 2 };
}

//: The straight segments of a path, for hit-testing a ray against a drawn
//: shape. Curves (the circle tool's arcs) contribute their endpoints only;
//: the bbox fallback in `wbEdgePoint` covers a shape with no usable segment.
function wbPathPolyline(d) {
  const tokens = (d || "").match(/[MLCHVAZmlchvaz]|-?\d*\.?\d+(?:[eE]-?\d+)?/g);
  if (!tokens) return [];
  const segs = [];
  let i = 0, px = 0, py = 0, sx = 0, sy = 0, cmd = "";
  const num = () => parseFloat(tokens[i++]);
  const lineTo = (x, y) => { segs.push([px, py, x, y]); px = x; py = y; };
  while (i < tokens.length) {
    if (/^[A-Za-z]$/.test(tokens[i])) cmd = tokens[i++];
    if (i >= tokens.length && cmd !== "Z" && cmd !== "z") break;
    switch (cmd) {
      case "M": px = num(); py = num(); sx = px; sy = py; cmd = "L"; break;
      case "m": px += num(); py += num(); sx = px; sy = py; cmd = "l"; break;
      case "L": lineTo(num(), num()); break;
      case "l": { const x = px + num(); lineTo(x, py + num()); break; }
      case "H": lineTo(num(), py); break;
      case "h": lineTo(px + num(), py); break;
      case "V": lineTo(px, num()); break;
      case "v": lineTo(px, py + num()); break;
      case "C": i += 4; lineTo(num(), num()); break;
      case "c": { i += 4; const x = px + num(); lineTo(x, py + num()); break; }
      case "A": i += 5; lineTo(num(), num()); break;
      case "a": { i += 5; const x = px + num(); lineTo(x, py + num()); break; }
      case "Z": case "z": lineTo(sx, sy); cmd = ""; break;
      default: i += 1;
    }
  }
  return segs;
}

//: Where a line from an item's centre toward (towardX, towardY) leaves the
//: item: on its rotated border for a card or text box, on its own outline
//: for a drawn shape.
function wbEdgePoint(kind, item, towardX, towardY) {
  const box = wbItemBBox(kind, item);
  if (!box) return null;
  const c = wbBoxCenter(box);
  if (kind === "sketch") {
    const parsed = typeof item._dragLiveD === "string" ? { d: item._dragLiveD } : wbSketchParsedData(item);
    const segs = parsed ? wbPathPolyline(parsed.d) : [];
    const dx = towardX - c.x, dy = towardY - c.y;
    if (segs.length && (dx || dy)) {
      // Ray c + t·(dx,dy), t ≥ 0, against each segment; nearest hit wins.
      let best = null;
      for (const [x1, y1, x2, y2] of segs) {
        const ex = x2 - x1, ey = y2 - y1;
        const den = dx * ey - dy * ex;
        if (Math.abs(den) < 1e-9) continue;
        const t = ((x1 - c.x) * ey - (y1 - c.y) * ex) / den;
        const u = ((x1 - c.x) * dy - (y1 - c.y) * dx) / den;
        if (t >= 0 && u >= 0 && u <= 1 && (best === null || t < best)) best = t;
      }
      if (best !== null) return { x: c.x + dx * best, y: c.y + dy * best };
    }
    return wbBoxRayIntersection(box, towardX, towardY);
  }
  const rot = wbItemRotation(kind, item);
  if (!rot) return wbBoxRayIntersection(box, towardX, towardY);
  const local = wbRotatePoint({ x: towardX, y: towardY }, c, -rot);
  return wbRotatePoint(wbBoxRayIntersection(box, local.x, local.y), c, rot);
}

//: The direction a curved link should leave an endpoint in: the box's face
//: normal for an upright card, the outward radial for anything rotated or
//: drawn (whose faces are not axis-aligned).
function wbItemEdgeDir(kind, item, pt) {
  const box = wbItemBBox(kind, item);
  if (!box || !pt) return null;
  if (kind !== "sketch" && !wbItemRotation(kind, item)) return wbEdgeNormal(box, pt);
  const c = wbBoxCenter(box);
  const len = Math.hypot(pt.x - c.x, pt.y - c.y);
  return len ? { x: (pt.x - c.x) / len, y: (pt.y - c.y) / len } : null;
}

//: The eight fixed anchors of an item, in board space, rotated with it.
function wbAnchorPositions(kind, item) {
  const box = wbItemBBox(kind, item);
  if (!box) return [];
  const w = box.maxX - box.minX, h = box.maxY - box.minY;
  const c = wbBoxCenter(box);
  const rot = wbItemRotation(kind, item);
  return WB_FIXED_ANCHORS.map((a) => {
    const pt = wbRotatePoint({ x: box.minX + a.x * w, y: box.minY + a.y * h }, c, rot);
    return { anchor: a, x: pt.x, y: pt.y };
  });
}

function wbAnchorPoint(kind, item, anchor) {
  if (!anchor) return null;
  const hit = wbAnchorPositions(kind, item).find((p) => p.anchor.x === anchor.x && p.anchor.y === anchor.y);
  return hit ? { x: hit.x, y: hit.y } : null;
}

//: The nearest of the 8 fixed points to a board-coordinate click, or `null`
//: if none is within `thresholdPx`, `null` is the caller's cue to persist
//: no anchor at all (the free/floating case) rather than a distant one.
function wbNearestAnchor(kind, item, px, py, thresholdPx = 16) {
  let best = null, bestDist = thresholdPx;
  for (const p of wbAnchorPositions(kind, item)) {
    const d = Math.hypot(px - p.x, py - p.y);
    if (d <= bestDist) { bestDist = d; best = p.anchor; }
  }
  return best;
}

//: The standard rectangle/ray intersection: where the line from this box's
//: centre toward `(towardX, towardY)` crosses the box's own border. This is
//: what a "floating" end actually resolves to each render, aimed at the
//: other end's real point, not always the other shape's centre.
//: **Which edge an endpoint sits on, as an outward unit vector.** This is
//: what makes a connector leave a card perpendicular to the side it is
//: attached to, instead of always leaving horizontally.
//:
//: Reported directly: "links don't change in their direction based off the
//: edge they are connected to and where the other end is coming from." Two
//: separate faults produced that, and this function is the input to both
//: fixes (see `wbLinkPathD`).
//:
//: Snapped to one axis rather than used as a raw radial vector: a connector
//: that leaves a rectangle at 37 degrees because that is where the anchor
//: happens to be reads as sloppy, where one that leaves squarely off the top
//: edge reads as deliberate. The dominant axis is chosen by comparing the
//: offset from centre against the box's own half-extents, so a wide, short
//: card still resolves its short edges correctly.
function wbEdgeNormal(box, pt) {
  if (!box || !pt) return null;
  const halfW = (box.maxX - box.minX) / 2 || 1;
  const halfH = (box.maxY - box.minY) / 2 || 1;
  const dx = (pt.x - (box.minX + box.maxX) / 2) / halfW;
  const dy = (pt.y - (box.minY + box.maxY) / 2) / halfH;
  if (!dx && !dy) return null;
  if (Math.abs(dx) >= Math.abs(dy)) return { x: Math.sign(dx) || 1, y: 0 };
  return { x: 0, y: Math.sign(dy) || 1 };
}

//: Attach a direction to an endpoint without changing its shape, so every
//: existing `wbLinkPathD(type, endpoints.source, …)` call site keeps working
//: and simply gains the better curve. An endpoint with no direction (a free
//: dangling point, or the live drag preview) falls back to the old
//: behaviour.
function wbWithDir(pt, dir) {
  return dir ? { x: pt.x, y: pt.y, dir } : pt;
}

function wbBoxRayIntersection(box, towardX, towardY) {
  const cx = (box.minX + box.maxX) / 2, cy = (box.minY + box.maxY) / 2;
  const dx = towardX - cx, dy = towardY - cy;
  if (!dx && !dy) return { x: cx, y: cy };
  const halfW = (box.maxX - box.minX) / 2, halfH = (box.maxY - box.minY) / 2;
  const t = Math.min(dx ? halfW / Math.abs(dx) : Infinity, dy ? halfH / Math.abs(dy) : Infinity);
  return { x: cx + dx * t, y: cy + dy * t };
}

//: The two real endpoints of a link, shared by the render path
//: (`sketchUpdate.each`) and the per-drag-frame follow (`wbUpdateLinkedSketches`)
//: so the two can't drift apart: same reasoning as that function's own
//: comment, just extended to real anchors instead of a hardcoded centre.
//: A fixed end resolves to its own point regardless of the other end; a
//: floating end resolves toward whatever the *other* end actually is (its
//: fixed point if it has one, its centre otherwise), not always the centre.
//: **A link end is a card *or a text object*.** Reported: "I cant even link
//: connections to text boxes or sticky notes." Every end was hard-wired to
//: `wbState.nodes`; a link stores `sourceKind`/`targetKind` now ("node" when
//: absent, so every existing link reads exactly as before) and both ends
//: resolve through the one lookup below.
//: Whether this row has anything to draw *now*.
//:
//: Reported: a node with "a dangling curved edge to nowhere". Deleting one
//: end of a cross-link removes the link's row on the server (every delete
//: route calls `_forget_links_to`) but the client kept its own copy, and the
//: render then set the path's `d` to `""` and left the `<g>` on the canvas -
//: measured: three nodes and one cross-link, delete one end, and the group is
//: still there with an empty path. An empty path draws nothing, but the group
//: is still a hit target and still carries the link's classes, and the next
//: thing to give a `.sketch-group` a decoration would have made it visible.
//:
//: Filtering the data join instead of blanking the path means d3's own
//: `exit().remove()` takes the element away, which is the mechanism that
//: already exists for "this is no longer on the board". The row itself is the
//: server's business: `_drop_orphan_links` deletes it on the next board load.
function wbSketchIsDrawable(sketch) {
  let parsed = null;
  try {
    parsed = JSON.parse(sketch.data || "{}");
  } catch {
    return true; // not ours to judge, a stroke, or a row we cannot read
  }
  if (!parsed || !String(parsed.type || "").startsWith("link-")) return true;
  //: Ids only, deliberately, the same rule the server's `_drop_orphan_links`
  //: applies. Asking `wbResolveLinkEndpoints` instead would drag the DOM into
  //: this: it measures an item's box, which is null for anything not painted
  //: yet, so a link would vanish on the first render of a board and reappear
  //: on the second. A free end (`sourcePoint`/`targetPoint`) is a feature and
  //: stays; only an end that names an id which is gone is an orphan.
  for (const [id, kind] of [
    [parsed.sourceId, parsed.sourceKind || "node"],
    [parsed.targetId, parsed.targetKind || "node"],
  ]) {
    if (id == null) continue;
    if (!wbLinkItem(kind, id)) return false;
  }
  return true;
}

function wbLinkItem(kind, id) {
  if (id == null) return null;
  const list = kind === "object" ? (wbState.objects || [])
    : kind === "sketch" ? (wbState.sketches || [])
    : wbState.nodes;
  return list.find((i) => i.id === id) || null;
}

//: Everything a link can start from or land on: cards, text boxes and
//: stickies, and every drawn shape (a link is a sketch too, and is never a
//: target). Reported: "only notes light up with edge anchor points... and
//: nothing else like shapes, sticky notes and text boxes."
function wbLinkCandidates(excludeKind, excludeId) {
  const out = [];
  for (const n of wbState.nodes) out.push(["node", n]);
  for (const o of wbState.objects || []) if (o.kind === "text") out.push(["object", o]);
  for (const sk of wbState.sketches || []) {
    const parsed = wbSketchParsedData(sk);
    if (!parsed || (parsed.type || "").startsWith("link-")) continue;
    out.push(["sketch", sk]);
  }
  return out.filter(([kind, item]) => !(kind === excludeKind && item.id === excludeId));
}

//: Is a board point inside an item, in the item's own rotated frame, not
//: its axis-aligned box. Reported: "hard to put connections on objects that
//: are rotated as the connection points and borders constantly flicker", 
//: the pointer crossed in and out of the unrotated box while visibly over
//: (or off) the rotated card, so the hints came and went with every move.
function wbPointInItem(kind, item, x, y) {
  const box = wbItemBBox(kind, item);
  if (!box) return false;
  const rot = wbItemRotation(kind, item);
  const p = rot ? wbRotatePoint({ x, y }, wbBoxCenter(box), -rot) : { x, y };
  return p.x >= box.minX && p.x <= box.maxX && p.y >= box.minY && p.y <= box.maxY;
}

function wbLinkCandidateAt(x, y, excludeKind, excludeId) {
  // Topmost first: objects and cards paint above sketches, and a later
  // sibling above an earlier one.
  const candidates = wbLinkCandidates(excludeKind, excludeId).reverse();
  for (const [kind, item] of candidates) {
    if (wbPointInItem(kind, item, x, y)) return [kind, item];
  }
  return null;
}

function wbLinkEndpoints(sourceItem, sourceAnchor, targetItem, targetAnchor, sourceKind = "node", targetKind = "node") {
  const sourceBox = wbItemBBox(sourceKind, sourceItem);
  const targetBox = wbItemBBox(targetKind, targetItem);
  if (!sourceBox || !targetBox) return null;
  const sourceCenter = wbBoxCenter(sourceBox);
  const targetCenter = wbBoxCenter(targetBox);
  const fixedSource = wbAnchorPoint(sourceKind, sourceItem, sourceAnchor);
  const fixedTarget = wbAnchorPoint(targetKind, targetItem, targetAnchor);
  const source = fixedSource || wbEdgePoint(sourceKind, sourceItem, (fixedTarget || targetCenter).x, (fixedTarget || targetCenter).y);
  const target = fixedTarget || wbEdgePoint(targetKind, targetItem, (fixedSource || sourceCenter).x, (fixedSource || sourceCenter).y);
  return {
    source: wbWithDir(source, wbItemEdgeDir(sourceKind, sourceItem, source)),
    target: wbWithDir(target, wbItemEdgeDir(targetKind, targetItem, target)),
  };
}

//: A link end is either attached to a card (`sourceId`/`targetId`, plus an
//: optional fixed `sourceAnchor`/`targetAnchor` fraction: the existing
//: shape) or a free "dangling" point in board space with no card at all
//: (`sourcePoint`/`targetPoint`, `{x, y}`, asked for directly: "even make
//: it a dangling unattached point not attached to an object"). Both ends
//: independently resolved here so any combination, node/node (the
//: original case), node/free, or free/free, renders through one path.
//: Returns `null` for a stale reference (a card end whose id no longer
//: exists), same as the two call sites already treated a missing node.
function wbResolveLinkEndpoints(parsed) {
  const sourceKind = parsed.sourceKind || "node";
  const targetKind = parsed.targetKind || "node";
  const sourceNode = wbLinkItem(sourceKind, parsed.sourceId);
  const targetNode = wbLinkItem(targetKind, parsed.targetId);
  if (parsed.sourceId != null && !sourceNode) return null;
  if (parsed.targetId != null && !targetNode) return null;
  if (!sourceNode && !parsed.sourcePoint) return null;
  if (!targetNode && !parsed.targetPoint) return null;
  if (sourceNode && targetNode) {
    return wbLinkEndpoints(sourceNode, parsed.sourceAnchor, targetNode, parsed.targetAnchor, sourceKind, targetKind);
  }
  if ((sourceNode && !wbItemBBox(sourceKind, sourceNode)) || (targetNode && !wbItemBBox(targetKind, targetNode))) return null;

  const sourceBox = sourceNode ? wbItemBBox(sourceKind, sourceNode) : null;
  const targetBox = targetNode ? wbItemBBox(targetKind, targetNode) : null;
  // A free point is always fixed, there's no card border for it to "aim
  // toward" the way a floating card-end resolves. A card-end with no fixed
  // anchor of its own still floats toward whatever the other end actually
  // is, same as the node/node case.
  const sourceFixed = sourceNode ? wbAnchorPoint(sourceKind, sourceNode, parsed.sourceAnchor) : parsed.sourcePoint;
  const targetFixed = targetNode ? wbAnchorPoint(targetKind, targetNode, parsed.targetAnchor) : parsed.targetPoint;
  const targetCenter = targetBox && wbBoxCenter(targetBox);
  const sourceCenter = sourceBox && wbBoxCenter(sourceBox);
  const source = sourceFixed || wbEdgePoint(sourceKind, sourceNode, (targetFixed || targetCenter).x, (targetFixed || targetCenter).y);
  const target = targetFixed || wbEdgePoint(targetKind, targetNode, (sourceFixed || sourceCenter).x, (sourceFixed || sourceCenter).y);
  // Only a card end has an edge to leave perpendicular to. A free dangling
  // point has no box, so it keeps the plain chord behaviour.
  return {
    source: wbWithDir(source, sourceNode && wbItemEdgeDir(sourceKind, sourceNode, source)),
    target: wbWithDir(target, targetNode && wbItemEdgeDir(targetKind, targetNode, target)),
  };
}

//: Reads a link's own start/end cap kinds, the new independent-per-end
//: fields (`startCap`/`endCap`, one of `WB_CAP_KINDS`) if it has them, or
//: translated from the older single `endStyle` (start/end/both/none,
//: always an arrow) for a link saved before the full end-cap system
//: existed. No migration needed: this is the only place either shape gets
//: read, so an old link keeps rendering exactly as it always did until its
//: caps are actually changed.
function wbLinkCaps(parsed) {
  if (parsed.startCap !== undefined || parsed.endCap !== undefined) {
    return { startCap: parsed.startCap || "none", endCap: parsed.endCap || "none" };
  }
  const style = parsed.endStyle;
  return {
    startCap: style === "start" || style === "both" ? "arrow" : "none",
    endCap: style === "end" || style === "both" ? "arrow" : "none",
  };
}

//: Shared by the render path and the live drag preview so a straight vs.
//: curved link can't compute its path two different ways. `caps` (from
//: `wbLinkCaps`) is optional: asked for directly ("customisable links...
//: connection endpoint designs", later extended to "circle/square/multi-
//: line ends, independently per end"), a link had no endpoint marker
//: option at all before the first version of this. The approach angle for
//: a cap is the straight line to the *other* endpoint, which is exact for
//: a straight link and a reasonable approximation for a curved one (the
//: curve's own tangent at the endpoint, not attempted, this app's curves
//: are gentle enough that the difference is small).
//: **A curved link leaves and enters along the edge it is attached to, and
//: its arrowheads point along the curve rather than along the chord.**
//:
//: Reported: "links don't change in their direction based off the edge they
//: are connected to and where the other end is coming from." That was two
//: faults in this one function, and both are visible on any two cards that
//: are not side by side:
//:
//: 1. **The curve was hardcoded horizontal.** The control points offset the
//:    endpoints in `x` only (`sPt.x + dx/2, sPt.y`), so every curved link
//:    left its source heading sideways and entered its target heading
//:    sideways: whichever edge each end was actually anchored to. Two cards
//:    stacked vertically got an S-bend that bulged out to the side and
//:    re-entered, instead of a short curve leaving the bottom edge and
//:    arriving at the top one.
//: 2. **The arrowhead angle was the chord**, `atan2` between the two
//:    endpoints: not the tangent of the curve it is drawn on. On any link
//:    with real curvature the head pointed visibly off the line it ended.
//:
//: Both now derive from each end's outward edge normal (`wbEdgeNormal`,
//: attached to the endpoint by `wbWithDir`). The control point is pushed
//: along that normal, so the curve leaves perpendicular to its edge; and
//: because a cubic Bezier's tangent at an endpoint is the direction to its
//: adjacent control point, the cap angle is read from that same control
//: point and therefore always agrees with the drawn curve.
//:
//: The offset is proportional to the distance between the ends and clamped:
//: unclamped, two distant cards produced a control point far outside the
//: board and a curve that swung wide of both; a fixed offset made a short
//: link between adjacent cards loop absurdly. An endpoint with no direction
//:, a free dangling point, or the live drag preview, keeps the original
//: horizontal behaviour, which is correct for a point with no edge.
//: `bend`, asked for directly: "I want to be able to double click on lines,
//: add points for curving lines and connections." An offset from the chord's
//: midpoint, in board units; when set, the link is a single quadratic curve
//: through that control point (straight *or* curved kind, a bent straight
//: line is a curve, which is what "add a point" means). Absent, both kinds
//: draw exactly as they always did.
function wbLinkPathD(type, sPt, tPt, caps, width, bend) {
  if (bend && (bend.x || bend.y)) {
    const ctrl = { x: (sPt.x + tPt.x) / 2 + bend.x, y: (sPt.y + tPt.y) / 2 + bend.y };
    let d = `M ${sPt.x} ${sPt.y} Q ${ctrl.x} ${ctrl.y}, ${tPt.x} ${tPt.y}`;
    const startCap = caps?.startCap || "none", endCap = caps?.endCap || "none";
    const headLen = (width || 3) * 4 + 6;
    if (endCap !== "none") d += " " + wbCapPath(endCap, tPt.x, tPt.y, Math.atan2(tPt.y - ctrl.y, tPt.x - ctrl.x), headLen);
    if (startCap !== "none") d += " " + wbCapPath(startCap, sPt.x, sPt.y, Math.atan2(sPt.y - ctrl.y, sPt.x - ctrl.x), headLen);
    return d;
  }
  const straight = type === "link-straight";
  const dx = tPt.x - sPt.x;
  const dy = tPt.y - sPt.y;
  const span = Math.hypot(dx, dy);
  // Enough to read as a deliberate curve, never enough to swing wide.
  const reach = Math.max(24, Math.min(span * 0.4, 160));
  const c1 = sPt.dir
    ? { x: sPt.x + sPt.dir.x * reach, y: sPt.y + sPt.dir.y * reach }
    : { x: sPt.x + dx / 2, y: sPt.y };
  const c2 = tPt.dir
    ? { x: tPt.x + tPt.dir.x * reach, y: tPt.y + tPt.dir.y * reach }
    : { x: tPt.x - dx / 2, y: tPt.y };
  const base = straight
    ? `M ${sPt.x} ${sPt.y} L ${tPt.x} ${tPt.y}`
    : `M ${sPt.x} ${sPt.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${tPt.x} ${tPt.y}`;
  const startCap = caps?.startCap || "none", endCap = caps?.endCap || "none";
  if (startCap === "none" && endCap === "none") return base;
  const headLen = (width || 3) * 4 + 6;
  // On a straight link the chord *is* the tangent. On a curve, the tangent at
  // an end is the direction to that end's own control point, pointing away
  // from the shape, so the head is rotated by PI to point back into it.
  const endAngle = straight
    ? Math.atan2(dy, dx)
    : Math.atan2(tPt.y - c2.y, tPt.x - c2.x);
  const startAngle = straight
    ? Math.atan2(dy, dx) + Math.PI
    : Math.atan2(sPt.y - c1.y, sPt.x - c1.x);
  let d = base;
  if (endCap !== "none") d += " " + wbCapPath(endCap, tPt.x, tPt.y, endAngle, headLen);
  if (startCap !== "none") d += " " + wbCapPath(startCap, sPt.x, sPt.y, startAngle, headLen);
  return d;
}

//: A small SVG dot at each of a shape's 8 fixed anchors, shown while a link
//: drag is in progress so the snap targets are actually discoverable rather
//: than a silent hit-test, draw.io shows the same thing on hover. The
//: nearest one to the live pointer (if within snapping range) renders larger
//: and filled, so "this is where it'll land" is visible before release.
function wbShowAnchorHints(kind, item, nearAnchor) {
  // The overlay layer, not the base SVG's own `#wb-zoom-group`, cards
  // render in an HTML layer *above* that SVG (see `#wb-overlay-layer`'s own
  // comment in index.html), so a hint drawn there for a hovered card would
  // be painted directly underneath it, invisible exactly when it matters.
  const zoomGroup = document.getElementById("wb-overlay-zoom-group");
  if (!zoomGroup) return;
  let hints = document.getElementById("wb-anchor-hints");
  if (!hints) {
    hints = document.createElementNS("http://www.w3.org/2000/svg", "g");
    hints.setAttribute("id", "wb-anchor-hints");
    hints.setAttribute("pointer-events", "none");
    zoomGroup.appendChild(hints);
  }
  hints.innerHTML = "";
  if (!item) return;
  for (const { anchor: a, x, y } of wbAnchorPositions(kind, item)) {
    const near = nearAnchor && nearAnchor.x === a.x && nearAnchor.y === a.y;
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", y);
    dot.setAttribute("r", near ? 6 : 4);
    dot.setAttribute("fill", near ? "var(--accent)" : "var(--card)");
    dot.setAttribute("stroke", "var(--accent)");
    dot.setAttribute("stroke-width", "1.5");
    hints.appendChild(dot);
  }
}

function wbClearAnchorHints() {
  document.getElementById("wb-anchor-hints")?.remove();
}

//: Resolves `wbMultiSelection` into {kind, id, item, bbox} entries, dropping
//: anything stale (deleted since selected) or box-less (a link sketch).
//: Shared by align/distribute/nudge: every one of them needs exactly this.
function wbSelectionEntries() {
  return [...wbMultiSelection]
    .map((key) => {
      const sep = key.indexOf(":");
      const kind = key.slice(0, sep), id = Number(key.slice(sep + 1));
      const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
      return item ? { kind, id, item, bbox: wbItemBBox(kind, item) } : null;
    })
    .filter((e) => e && e.bbox);
}

//: Moves one item by (dx, dy): a sketch by transforming its path, anything
//: else by its own x/y, saves it, and returns the "move" undo entry for
//: it. Shared by nudge/align/distribute, each of which moves a set of items
//: as one user action and needs one entry per item to bundle into a batch.
async function wbMoveItemBy(kind, id, item, dx, dy) {
  const before = WB_KIND_INFO[kind].payload(item);
  if (kind === "sketch") {
    const parsed = wbSketchParsedData(item);
    const newD = wbTransformPathD(parsed.d, { dx, dy });
    await wbSaveSketchD(item, newD);
  } else {
    item.x = (item.x || 0) + dx;
    item.y = (item.y || 0) + dy;
    if (kind === "node") await wbSaveNode(item);
    else await wbSaveObject(item);
  }
  return { action: "move", kind, id, before };
}

//: Pushes N per-item move entries as the one undo step the user actually
//: took: a single "batch" entry when more than one item moved, or the bare
//: entry itself when only one did, so a plain single-item nudge doesn't pay
//: for the extra indirection.
function wbPushMoveBatch(entries) {
  if (entries.length === 0) return;
  wbPushUndo(entries.length === 1 ? entries[0] : { action: "batch", entries });
  wbScheduleRender();
}

// Alignment tools: asked for directly ("alignment tools... missing"), only
// meaningful for two or more selected items. Aligns to the selection's own
// overall bounding box, the same reference every other drawing app uses.
async function wbAlignSelection(edge) {
  const entries = wbSelectionEntries();
  if (entries.length < 2) {
    toast("Select two or more items to align them.");
    return;
  }
  let target;
  if (edge === "left") target = Math.min(...entries.map((e) => e.bbox.minX));
  else if (edge === "right") target = Math.max(...entries.map((e) => e.bbox.maxX));
  else if (edge === "top") target = Math.min(...entries.map((e) => e.bbox.minY));
  else if (edge === "bottom") target = Math.max(...entries.map((e) => e.bbox.maxY));
  else if (edge === "hcenter") {
    const minX = Math.min(...entries.map((e) => e.bbox.minX));
    const maxX = Math.max(...entries.map((e) => e.bbox.maxX));
    target = (minX + maxX) / 2;
  } else if (edge === "vcenter") {
    const minY = Math.min(...entries.map((e) => e.bbox.minY));
    const maxY = Math.max(...entries.map((e) => e.bbox.maxY));
    target = (minY + maxY) / 2;
  }

  const pushed = [];
  for (const e of entries) {
    let dx = 0, dy = 0;
    if (edge === "left") dx = target - e.bbox.minX;
    else if (edge === "right") dx = target - e.bbox.maxX;
    else if (edge === "hcenter") dx = target - (e.bbox.minX + e.bbox.maxX) / 2;
    else if (edge === "top") dy = target - e.bbox.minY;
    else if (edge === "bottom") dy = target - e.bbox.maxY;
    else if (edge === "vcenter") dy = target - (e.bbox.minY + e.bbox.maxY) / 2;
    if (dx === 0 && dy === 0) continue;
    pushed.push(await wbMoveItemBy(e.kind, e.id, e.item, dx, dy));
  }
  wbPushMoveBatch(pushed);
}

// Distribute: asked for as part of the same "alignment tools" request.
// Needs three or more: the first and last (by leading edge, along the chosen
// axis) stay put as the two ends, and whatever is between them is placed so
// that every *gap* is the same.
//
// **Gaps, not centres** (WHITEBOARD_PLAN.md §2 item 4, "no
// distribute-gaps", and decision 3). This spaced centres evenly until now,
// which is the same thing only when every item is the same size: give three
// boxes of 100, 300 and 100 an even centre spacing and the gap on one side
// of the wide one is 100px smaller than the gap on the other, which is
// exactly the arrangement a person reaches for this button to fix. Figma,
// Illustrator and tldraw all offer the gap version under this name, and it
// is the one that makes a row of mixed-width cards look like a row.
async function wbDistributeSelection(axis) {
  const entries = wbSelectionEntries();
  if (entries.length < 3) {
    toast("Select three or more items to space them evenly.");
    return;
  }
  const minOf = (e) => (axis === "horizontal" ? e.bbox.minX : e.bbox.minY);
  const maxOf = (e) => (axis === "horizontal" ? e.bbox.maxX : e.bbox.maxY);
  entries.sort((a, b) => minOf(a) - minOf(b));
  const first = entries[0];
  const last = entries[entries.length - 1];
  const span = maxOf(last) - minOf(first);
  const used = entries.reduce((sum, e) => sum + (maxOf(e) - minOf(e)), 0);
  // Negative when the items overlap more than the span allows; the result is
  // then an even *overlap*, which is still the honest reading of "space these
  // evenly between the two ends" and is what the other apps do.
  const gap = (span - used) / (entries.length - 1);

  const pushed = [];
  let cursor = maxOf(first) + gap;
  for (let i = 1; i < entries.length - 1; i++) {
    const e = entries[i];
    const size = maxOf(e) - minOf(e);
    const delta = cursor - minOf(e);
    cursor += size + gap;
    // Sub-pixel: a move that rounds to nothing is a PUT and an undo entry for
    // no visible change.
    if (Math.abs(delta) < 0.5) continue;
    const dx = axis === "horizontal" ? delta : 0;
    const dy = axis === "horizontal" ? 0 : delta;
    pushed.push(await wbMoveItemBy(e.kind, e.id, e.item, dx, dy));
  }
  wbPushMoveBatch(pushed);
}

//: **Same size**, the third of WHITEBOARD_PLAN decision 3's eleven arrange
//: actions and the one that had no function at all. Every selected item takes
//: the largest one's width (or height); the largest rather than the
//: first-clicked because a marquee selection has no first, and growing to the
//: biggest never hides content the way shrinking to the smallest can.
//:
//: The item keeps its top-left corner: a resize that also moved things would
//: undo the align someone almost certainly did just before this.
async function wbSameSizeSelection(dim) {
  const entries = wbSelectionEntries();
  if (entries.length < 2) {
    toast("Select two or more items to give them the same size.");
    return;
  }
  const sizeOf = (e) => (dim === "width" ? e.bbox.maxX - e.bbox.minX : e.bbox.maxY - e.bbox.minY);
  const target = Math.max(...entries.map(sizeOf));
  const pushed = [];
  for (const e of entries) {
    const size = sizeOf(e);
    if (size <= 0 || Math.abs(size - target) < 0.5) continue;
    const done = await wbSizeItemTo(e, dim, target, target / size);
    if (done) pushed.push(done);
  }
  wbPushMoveBatch(pushed);
}

//: One item resized, in `wbMoveItemBy`'s shape and for the same reason: the
//: history's "move" entry carries the item's whole payload, so a resize
//: undoes through exactly the same PUT a move does (see
//: `wbApplyHistoryEntry`). A drawn shape is a path, so it scales about its own
//: top-left corner rather than taking a width field it does not have.
async function wbSizeItemTo(entry, dim, target, factor) {
  const { kind, id, item, bbox } = entry;
  const before = WB_KIND_INFO[kind].payload(item);
  if (kind === "sketch") {
    const parsed = wbSketchParsedData(item);
    if (!parsed) return null;
    const scaled = wbTransformPathD(parsed.d, {
      sx: dim === "width" ? factor : 1,
      sy: dim === "height" ? factor : 1,
      anchorX: bbox.minX,
      anchorY: bbox.minY,
    });
    await wbSaveSketchD(item, scaled);
  } else {
    // Rounded: both columns are integers on the row, and a card whose stored
    // width is 219.99997 reads back as a different number than it was set to.
    if (dim === "width") item.width = Math.round(target);
    else item.height = Math.round(target);
    if (kind === "node") await wbSaveNode(item);
    else await wbSaveObject(item);
  }
  return { action: "move", kind, id, before };
}

// Extract notes (BACKLOG.md §62): the selected note cards' own content IS
// the "notes-in-context", their combined text is what gets split, and each
// card is also passed as an explicit source so the new note(s) link back to
// where they came from, not just to whatever else in the notebook they
// happen to resemble. Reuses `wbSelectionEntries()`, same as align/
// distribute above, rather than a second way of reading the selection.
function wbExtractNotes() {
  const noteEntries = wbSelectionEntries().filter((e) => e.kind === "node");
  if (noteEntries.length === 0) {
    toast("Select at least one note card to extract from.");
    return;
  }
  const entryIds = [...new Set(noteEntries.map((e) => e.item.entry_id))];
  const byId = new Map(allEntries.map((e) => [e.id, e]));
  // A card whose note isn't in `allEntries` yet (created elsewhere, cache
  // not refreshed) is skipped rather than sent as empty text, it still
  // counts as a source id, just contributes nothing to read from.
  const text = entryIds
    .map((id) => byId.get(id)?.content)
    .filter(Boolean)
    .join("\n\n---\n\n");
  if (!text.trim()) {
    toast("Couldn't read the selected notes' content: try reloading the Notes tab first.");
    return;
  }
  openExtractPreview(text, { sourceEntryIds: entryIds });
}

// Arrow-key nudge: asked for directly ("allow objects to be moved with
// arrow keys"). Moves the whole current selection (single item or multi)
// by one step; the keydown handler in initWhiteboard decides the step size
// (grid spacing when snap is on, else 1px, 10px with Shift).
async function wbNudgeSelection(dx, dy) {
  const entries = wbMultiSelection.size > 0
    ? wbSelectionEntries()
    : wbSelectedItem
      ? (() => {
          const { kind, id } = wbSelectedItem;
          const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
          const bbox = item && wbItemBBox(kind, item);
          return item && bbox ? [{ kind, id, item, bbox }] : [];
        })()
      : [];
  if (entries.length === 0) return;
  const pushed = [];
  for (const e of entries) pushed.push(await wbMoveItemBy(e.kind, e.id, e.item, dx, dy));
  wbPushMoveBatch(pushed);
}

// as the resize handles above, there is no one set of properties to show
// for a mixed multi-selection. A node (note card) and an image object have
// nothing here to edit yet (a card's own text is the note; an image has no
// stroke/fill of its own), so the panel just stays hidden for those.
// The tools that draw something with a colour and a thickness, the ones
// whose settings the properties panel shows when nothing is selected.
const WB_STYLE_TOOLS = new Set([
  "draw", "highlighter", "eraser", "line", "arrow", "rect", "circle",
  "triangle", "diamond", "text", "sticky", "link-straight", "link-curved", "bucket",
]);

//: The two "what is selected, if it is of this kind" lookups. Module-level
//: because both the properties panel's own controls and the copy-style
//: actions below need them, and they close over nothing but module state.
function wbSelectedSketchOrNull() {
  if (!wbSelectedItem || wbSelectedItem.kind !== "sketch") return null;
  return wbState.sketches.find((s) => s.id === wbSelectedItem.id) || null;
}

function wbSelectedTextObjectOrNull() {
  if (!wbSelectedItem || wbSelectedItem.kind !== "object") return null;
  const obj = wbState.objects?.find((o) => o.id === wbSelectedItem.id);
  return obj && obj.kind === "text" ? obj : null;
}

//: **Copy a style off one thing and put it on another.** Asked for directly:
//: "I want a tool or way to copy styles of shapes and links and add them to
//: another shape or link connector of a similar type."
//:
//: Modelled on Excalidraw's copy/paste-style rather than on PowerPoint's
//: format-painter *mode*: select a source, copy, select a target, paste. A
//: painter mode would mean a third cursor state and a "what am I armed with"
//: question on every click; this reuses the selection the board already has.
//:
//: "A similar type" is enforced, not assumed, a text box's style is its
//: font size and its background, a sketch's is its stroke and fill, and
//: pasting one onto the other would either do nothing or write fields the
//: renderer does not read. The copy remembers which kind it came from and
//: refuses the mismatch out loud.
let wbCopiedStyle = null; // { kind: "sketch" | "object", style: {...} }

// Only the fields that are style. Deliberately not `d` (the geometry), not
// `type`, not position: pasting a style must never move or reshape the
// thing it lands on.
const WB_SKETCH_STYLE_KEYS = [
  "color", "width", "dash", "fill", "fillOpacity", "noStroke", "startCap", "endCap",
];
const WB_OBJECT_STYLE_KEYS = ["color", "bg", "border_color", "font_size"];

function wbPickStyle(source, keys) {
  const out = {};
  for (const key of keys) if (source?.[key] !== undefined) out[key] = source[key];
  return out;
}

function wbCopySelectedStyle() {
  const sketch = wbSelectedSketchOrNull();
  if (sketch) {
    let parsed = null;
    try { parsed = JSON.parse(sketch.data); } catch { parsed = null; }
    if (!parsed) return toast("That item has no style to copy.");
    wbCopiedStyle = { kind: "sketch", style: wbPickStyle(parsed, WB_SKETCH_STYLE_KEYS) };
    return toast("Style copied. Select a shape or link and press Ctrl+Alt+V.");
  }
  const obj = wbSelectedTextObjectOrNull();
  if (obj) {
    wbCopiedStyle = { kind: "object", style: wbPickStyle(obj.data, WB_OBJECT_STYLE_KEYS) };
    return toast("Style copied. Select a text box and press Ctrl+Alt+V.");
  }
  toast("Select a shape, link or text box first.");
}

async function wbPasteCopiedStyle() {
  if (!wbCopiedStyle) return toast("Copy a style first (Ctrl+Alt+C).");
  // Every item in a multi-selection, so restyling a diagram is one action
  // rather than one per shape, the same reach `wbApplyBulkMove` already has.
  const entries = wbMultiSelection.size > 0
    ? wbSelectionEntries()
    : (wbSelectedItem ? [wbSelectedItem] : []);
  if (!entries.length) return toast("Select something to paste the style onto.");

  let applied = 0;
  let skipped = 0;
  for (const entry of entries) {
    const list = wbState[WB_LIST_BY_KIND[entry.kind]] || [];
    const item = list.find((i) => i.id === entry.id);
    if (!item) continue;
    if (entry.kind === "sketch" && wbCopiedStyle.kind === "sketch") {
      await wbSaveSketchProps(item, { ...wbCopiedStyle.style });
      applied += 1;
    } else if (entry.kind === "object" && wbCopiedStyle.kind === "object" && item.kind === "text") {
      item.data = { ...item.data, ...wbCopiedStyle.style };
      await wbSaveObject(item);
      applied += 1;
    } else {
      skipped += 1;
    }
  }
  wbScheduleRender();
  wbUpdateContextBar();
  if (!applied) return toast("That style does not fit what you selected.");
  toast(skipped
    ? `Style pasted onto ${applied}. ${skipped} skipped: a different kind of item.`
    : `Style pasted onto ${applied}.`);
}

//: **The kind to controls table** (WHITEBOARD_PLAN.md decision 2). One row
//: per thing that can be selected, saying which of the context bar's groups
//: it shows and which sections of the "..." menu it opens. A new kind of
//: object gets its controls by adding a row here, not by adding a panel; and
//: "the bar shows only what applies" is then a property of this table rather
//: than of forty `classList.toggle` calls spread through a function.
//:
//: The keys are the selection's shape, not the storage kind: a `sketch` is a
//: drawn line, an arrow or a closed shape and those take different controls,
//: and an `object` is a text box or a picture. `wbContextKindOf` below turns
//: a selection into one of these names.
const WB_CONTEXT_CONTROLS = {
  // Nothing selected, a drawing tool held: what the next stroke will use.
  tool: { bar: ["tool"], more: ["more-style"] },
  line: { bar: ["ink", "caps", "stroke", "order"], more: ["more-style"] },
  shape: { bar: ["ink", "stroke", "fill", "order"], more: ["more-style"] },
  link: { bar: ["ink", "caps", "stroke"], more: ["more-style"] },
  text: { bar: ["ink", "text", "order"], more: ["more-style", "more-card"] },
  image: { bar: ["order"], more: ["more-style"] },
  // A note card: its look comes from the note, so what it offers is where it
  // sits and what it can become.
  note: { bar: ["order"], more: ["more-mindmap", "more-notes"] },
  multi: { bar: ["arrange", "order"], more: ["more-notes"] },
};

//: Every group and menu section the table can name, so hiding "everything
//: else" never has to list them.
const WB_CONTEXT_GROUPS = ["tool", "ink", "caps", "stroke", "fill", "text", "arrange", "order"];
const WB_CONTEXT_MENU_SECTIONS = ["more-style", "more-card", "more-guides", "more-notes", "more-mindmap"];

//: Which row of the table a selection reads. Returns null when the bar has
//: nothing to say, which is what closes it.
function wbContextKindOf(sel, item) {
  if (!sel || !item) return null;
  if (sel.kind === "sketch") {
    let parsedLink = null;
    try {
      const candidate = JSON.parse(item.data);
      if (candidate && (candidate.type || "").startsWith("link-")) parsedLink = candidate;
    } catch { /* not JSON: not a link either */ }
    if (parsedLink) return "link";
    const parsed = wbSketchParsedData(item);
    if (!parsed) return null;
    return WB_FILLABLE_SHAPES.has(parsed.shape) ? "shape" : "line";
  }
  if (sel.kind === "node") return "note";
  if (sel.kind === "object") return item.kind === "text" ? "text" : "image";
  return null;
}

//: Shows exactly the groups a row names and hides the rest, in one pass, so
//: a control can never be left over from the last selection.
function wbApplyContextRow(row) {
  const bar = new Set(row?.bar || []);
  const more = new Set(row?.more || []);
  for (const name of WB_CONTEXT_GROUPS) {
    document.querySelector(`#wb-context [data-wb-ctx="${name}"]`)?.classList.toggle("hidden", !bar.has(name));
  }
  for (const name of WB_CONTEXT_MENU_SECTIONS) {
    document.querySelector(`#wb-context-menu [data-wb-ctx="${name}"]`)?.classList.toggle("hidden", !more.has(name));
  }
  // The rows inside the Style section that only some kinds can use.
  for (const id of ["wb-prop-nostroke-row", "wb-prop-md-row", "wb-prop-bullets-row", "wb-fill-opacity-row", "wb-stroke-none-row"]) {
    document.getElementById(id)?.classList.add("hidden");
  }
}

//: **The bar with nothing selected sits over the rail.** Placed here rather
//: than in `wbUpdateSelectionBar` for one measured reason: that function runs
//: on every frame of every pan (`handleWbZoom`), and this position depends on
//: the rail and the host, neither of which a pan moves. `data-wb-anchor` is
//: how the pan frame knows to leave it alone without asking any question that
//: costs a DOM walk; the same lesson the text-editing query above records.
function wbParkContextOnRail(on) {
  const bar = document.getElementById("wb-context");
  const host = document.getElementById("library-view-whiteboard");
  if (!bar || !host) return;
  if (!on) {
    bar.classList.add("hidden");
    delete bar.dataset.wbAnchor;
    return;
  }
  bar.dataset.wbAnchor = "rail";
  bar.classList.remove("hidden");
  // One bar over this canvas, never two (the map strip's own rule).
  document.getElementById("wb-map-strip")?.classList.add("hidden");
  const hostRect = host.getBoundingClientRect();
  const rail = document.getElementById("wb-tools-panel")?.getBoundingClientRect();
  const w = bar.offsetWidth;
  const h = bar.offsetHeight;
  const left = Math.max(8, Math.min(Math.max(8, hostRect.width - w - 8), hostRect.width / 2 - w / 2));
  // Ten pixels over the rail, and never off the top: on a short window the
  // rail's own top edge can be less than the bar's height from the top bar.
  const railTop = rail && rail.height ? rail.top - hostRect.top : hostRect.height - 72;
  const topBar = document.getElementById("wb-topbar")?.getBoundingClientRect();
  const floor = topBar ? topBar.bottom - hostRect.top + 8 : 56;
  bar.style.left = `${Math.round(left)}px`;
  bar.style.top = `${Math.round(Math.max(floor, railTop - h - 10))}px`;
}

//: Filled first, placed second, never the other way round: the bar is centred
//: on the selection from its own measured width, and a bar still holding the
//: last selection's controls is a different width. The map strip's own comment
//: a few hundred lines down records exactly the same trap for the same reason.
function wbUpdateContextBar() {
  const bar = document.getElementById("wb-context");
  if (!bar) return;
  if (wbFillContextBar() === "rail") wbParkContextOnRail(true);
  else wbUpdateSelectionBar();
}

//: What the bar holds, from `WB_CONTEXT_CONTROLS`. Returns "rail" when it is
//: showing a held tool's own settings and so belongs over the rail rather than
//: over a selection it does not have.
function wbFillContextBar() {
  const bar = document.getElementById("wb-context");
  if (!bar) return null;
  const show = (...ids) => ids.forEach((id) => document.getElementById(id)?.classList.remove("hidden"));

  // A multi-selection has no one fill or stroke to edit (mixed kinds), but it
  // does have arrange, which only means anything here.
  if (wbMultiSelection.size > 0) {
    wbApplyContextRow(WB_CONTEXT_CONTROLS.multi);
    // Extract notes (BACKLOG.md §62) only makes sense once the selection
    // actually includes a note card's content to extract from; a selection of
    // pure shapes has no "notes-in-context".
    const hasNoteCard = wbSelectionEntries().some((e) => e.kind === "node");
    document.querySelector('#wb-context-menu [data-wb-ctx="more-notes"]')?.classList.toggle("hidden", !hasNoteCard);
    delete bar.dataset.wbAnchor;
    return null;
  }

  // The bar is also where a drawing tool's own settings live, so it opens for
  // a held tool with nothing selected: otherwise picking the pen would hide
  // the pen's own thickness. This is the split every whiteboard app makes,
  // tools in the rail, their properties in the context surface.
  if (!wbSelectedItem) {
    const toolDraws = WB_STYLE_TOOLS.has(window.currentTool);
    wbApplyContextRow(toolDraws ? WB_CONTEXT_CONTROLS.tool : null);
    if (toolDraws) show("wb-fill-opacity-row", "wb-stroke-none-row");
    if (!toolDraws) wbParkContextOnRail(false);
    return toolDraws ? "rail" : null;
  }
  delete bar.dataset.wbAnchor;

  const { kind, id } = wbSelectedItem;
  const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
  const which = wbContextKindOf(wbSelectedItem, item);
  wbApplyContextRow(which ? WB_CONTEXT_CONTROLS[which] : null);
  if (!which) return;

  if (which === "link") {
    const parsed = JSON.parse(item.data);
    document.getElementById("wb-prop-color").value = parsed.color || "#ffffff";
    document.getElementById("wb-prop-width").value = parsed.width || 3;
    const caps = wbLinkCaps(parsed);
    document.getElementById("wb-prop-startcap").value = caps.startCap;
    document.getElementById("wb-prop-endcap").value = caps.endCap;
    document.getElementById("wb-prop-dash").value = parsed.dash || "solid";
    return;
  }

  if (which === "line" || which === "shape") {
    const parsed = wbSketchParsedData(item);
    document.getElementById("wb-prop-color").value = parsed.color || "#000000";
    document.getElementById("wb-prop-width").value = parsed.width || 3;
    document.getElementById("wb-prop-dash").value = parsed.dash || "solid";
    show("wb-prop-nostroke-row");
    document.getElementById("wb-prop-nostroke").checked = Boolean(parsed.noStroke);
    // **The caps come off the object, never off the tool's default** (the
    // plan's section 2 item 4, and a live report before it): a drawn line
    // reported "Arrow" at both ends because the control was showing
    // `window.currentArrowStyle` rather than what was on the shape.
    const isArrow = wbSketchIsArrow(parsed.d);
    document.querySelector('#wb-context [data-wb-ctx="caps"]')?.classList.toggle("hidden", !isArrow);
    if (isArrow) {
      const caps = wbSketchCaps(parsed);
      document.getElementById("wb-prop-startcap").value = caps.startCap;
      document.getElementById("wb-prop-endcap").value = caps.endCap;
    }
    if (which === "shape") {
      document.getElementById("wb-prop-shapefill").value = parsed.fill || "#3355ff";
      document.getElementById("wb-prop-shapefill-on").checked = Boolean(parsed.fill);
      document.getElementById("wb-prop-shapefill").disabled = !parsed.fill;
    }
    return;
  }

  if (which === "text") {
    for (const button of document.querySelectorAll("#wb-prop-align button")) {
      button.classList.toggle("active", button.dataset.align === (item.data.align || "left"));
    }
    show("wb-prop-md-row", "wb-prop-bullets-row");
    document.getElementById("wb-prop-md").checked = Boolean(item.data.md);
    document.getElementById("wb-prop-color").value = item.data.color || "#1f2430";
    document.getElementById("wb-prop-bg").value = item.data.bg === "transparent" ? "#ffffff" : (item.data.bg || "#ffffff");
    document.getElementById("wb-prop-bg-none").checked = item.data.bg === "transparent";
    document.getElementById("wb-prop-border").value = item.data.border_color === "transparent" ? "#8888aa" : (item.data.border_color || "#8888aa");
    document.getElementById("wb-prop-border-none").checked = item.data.border_color === "transparent";
    document.getElementById("wb-prop-fontsize").value = item.data.font_size || 16;
    // A text box has no line ends and no drawn width; the ink group's width
    // field is a stroke thickness, which a box does not have either.
    document.getElementById("wb-prop-width").parentElement?.classList.add("hidden");
    return;
  }

  if (which === "note") {
    // Mind-mapping (item 25): only worth offering once the card actually has
    // something to arrange; a card with no links is already exactly where a
    // "mind map of one" would put it.
    const hasLink = wbState.sketches.some((s) => {
      try {
        const p = JSON.parse(s.data);
        return p.type && p.type.startsWith("link-") && (p.sourceId === item.id || p.targetId === item.id);
      } catch {
        return false;
      }
    });
    document.querySelector('#wb-context-menu [data-wb-ctx="more-mindmap"]')?.classList.toggle("hidden", !hasLink);
  }
}

//: Mind-mapping (ROADMAP item 25): "Arrange as mind map" auto-positions
//: everything reachable from a selected card via the whiteboard's own
//: links into a Tree or Radial layout, reusing the Graph tab's own
//: `d3.hierarchy`/`d3.tree` approach (see `layoutHierarchy` above) rather
//: than a second layout engine, just against the whiteboard's plain
//: node/link data instead of the notebook's category/reply structure (no
//: categories here, so none of that grouping machinery is needed). A link
//: graph isn't necessarily a tree, cycles, a card linked to two others
//: that are themselves linked, so a BFS from the root turns whatever is
//: reachable into a real spanning tree (first link found wins the "parent"
//: slot), which is the only sense "arrange everything connected to it" can
//: have for a layout that needs one parent per node.
const WB_MINDMAP_TREE_ROW = 170; // spacing across the fan-out axis
const WB_MINDMAP_TREE_COL = 320; // spacing per depth level, left → right
const WB_MINDMAP_RADIAL_STEP = 260; // ring spacing per depth level

//: The undirected adjacency every mind-map operation starts from, every
//: link sketch touching two *currently real* nodes (a stale link to an
//: already-deleted card is silently excluded, same as the render path
//: already does).
function wbLinkAdjacency() {
  const adjacency = new Map();
  const addEdge = (a, b) => {
    if (!adjacency.has(a)) adjacency.set(a, new Set());
    if (!adjacency.has(b)) adjacency.set(b, new Set());
    adjacency.get(a).add(b);
    adjacency.get(b).add(a);
  };
  const nodeIds = new Set(wbState.nodes.map((n) => n.id));
  for (const sketch of wbState.sketches) {
    let parsed;
    try {
      parsed = JSON.parse(sketch.data);
    } catch {
      continue;
    }
    if (!parsed.type || !parsed.type.startsWith("link-")) continue;
    if (nodeIds.has(parsed.sourceId) && nodeIds.has(parsed.targetId)) addEdge(parsed.sourceId, parsed.targetId);
  }
  return adjacency;
}

//: A BFS spanning tree from `rootId`, in the `{parentOf, childrenOf}` shape
//: both `wbArrangeMindMap` and the Tab/Enter branch-entry commands share.
function wbMindMapSpanningTree(rootId) {
  const adjacency = wbLinkAdjacency();
  const parentOf = new Map([[rootId, null]]);
  const childrenOf = new Map([[rootId, []]]);
  const queue = [rootId];
  while (queue.length) {
    const current = queue.shift();
    for (const neighbour of adjacency.get(current) || []) {
      if (parentOf.has(neighbour)) continue;
      parentOf.set(neighbour, current);
      childrenOf.get(current).push(neighbour);
      childrenOf.set(neighbour, []);
      queue.push(neighbour);
    }
  }
  return { parentOf, childrenOf };
}

async function wbArrangeMindMap(rootId, kind) {
  const root = wbState.nodes.find((n) => n.id === rootId);
  if (!root) return;
  const { parentOf, childrenOf } = wbMindMapSpanningTree(rootId);
  if (parentOf.size < 2) {
    toast("Nothing linked to this card to arrange.");
    return;
  }

  // d3.hierarchy wants a tree of plain objects with a `children` accessor: 
  // built once, keyed by node id, the same shape `layoutHierarchy` above
  // builds from `children`/`groups`.
  const buildTree = (id) => ({ id, children: (childrenOf.get(id) || []).map(buildTree) });
  const laid = d3.hierarchy(buildTree(rootId));

  const positions = new Map();
  if (kind === "radial") {
    // Same `d3.tree().size([2*Math.PI, 1])` call `layoutHierarchy`'s own
    // radial branch uses; ring spacing is a plain fixed step per depth
    // here rather than that function's label-aware `radialRings` sizing,
    // since a mind map has no per-ring label-width category to budget for.
    d3.tree().size([2 * Math.PI, 1])(laid);
    laid.each((point) => {
      const radius = point.depth * WB_MINDMAP_RADIAL_STEP;
      positions.set(point.data.id, {
        x: radius * Math.cos(point.x - Math.PI / 2),
        y: radius * Math.sin(point.x - Math.PI / 2),
      });
    });
  } else {
    d3.tree().nodeSize([WB_MINDMAP_TREE_ROW, WB_MINDMAP_TREE_COL])(laid);
    laid.each((point) => {
      positions.set(point.data.id, { x: point.depth * WB_MINDMAP_TREE_COL, y: point.x });
    });
  }

  // The layout is computed around (0,0) at the root, shift the whole
  // result so the root card itself doesn't move, only what's connected to
  // it, which is what "arrange everything connected to it" (not "recentre
  // my board") actually asked for.
  const rootPos = positions.get(rootId);
  const dx = root.x - rootPos.x, dy = root.y - rootPos.y;
  for (const [id, pos] of positions) {
    if (id === rootId) continue;
    const node = wbState.nodes.find((n) => n.id === id);
    if (!node) continue;
    node.x = wbSnap(pos.x + dx);
    node.y = wbSnap(pos.y + dy);
    await wbSaveNode(node);
  }

  // Cached for the Tab/Enter branch-entry commands below, so a card added
  // right after an arrange lands in the layout it was just shown, not a
  // freshly re-derived (and possibly different, since BFS parent choice
  // isn't unique when a card has more than one link back toward the root)
  // spanning tree.
  window.wbMindMap = { rootId, parentOf, childrenOf, kind };
  wbScheduleRender();
  toast(`Arranged ${parentOf.size} cards as a ${kind === "radial" ? "radial" : "tree"} mind map.`);
}

//: Tab/Enter branch entry (item 25's second piece) needs to know a card's
//: "parent" in mind-map terms, which a whiteboard link doesn't carry on its
//: own (just two ids, no direction). Reuses the cached map from a prior
//: `wbArrangeMindMap` run when the given card is part of it; otherwise
//: seeds one lazily, rooted at the card itself, from the board's current
//: links: so Tab/Enter still work sensibly on a board nobody has arranged
//: yet, not only right after clicking Tree/Radial.
function wbMindMapEnsureMap(fromId) {
  if (!window.wbMindMap || !window.wbMindMap.parentOf.has(fromId)) {
    const { parentOf, childrenOf } = wbMindMapSpanningTree(fromId);
    window.wbMindMap = { rootId: fromId, parentOf, childrenOf, kind: window.wbMindMap?.kind || "radial" };
  }
  return window.wbMindMap;
}

//: Creates a real note, a whiteboard card for it, and a link from
//: `parentId`, the one operation both Tab and Enter reduce to, differing
//: only in which card counts as the parent.
async function wbMindMapAddCard(parentId, x, y) {
  const entry = await apiJson("/entries", { method: "POST", body: JSON.stringify({ content: "New branch" }) });
  const nodeRes = await apiJson("/whiteboard/nodes", {
    method: "POST",
    body: JSON.stringify({ entry_id: entry.id, board_id: window.currentBoardId ?? null, x: wbSnap(x), y: wbSnap(y), z: 1 }),
  });
  wbState.nodes.push(nodeRes);
  const sketchRes = await apiJson("/whiteboard/sketches", {
    method: "POST",
    body: JSON.stringify({
      data: JSON.stringify({
        type: "link-curved",
        sourceId: parentId,
        targetId: nodeRes.id,
        color: window.currentStrokeColor || "#ffffff",
      }),
      x: 0, y: 0, z: 1, board_id: window.currentBoardId ?? null,
    }),
  });
  wbState.sketches.push(sketchRes);

  // The card about to render reads its text out of `allEntries`, which was
  // fetched before this note existed. Without this the new branch renders
  // as a placeholder and never resolves, see the `!entry` branch in the
  // card renderer.
  await loadEntries();

  const map = wbMindMapEnsureMap(parentId);
  map.parentOf.set(nodeRes.id, parentId);
  if (!map.childrenOf.has(parentId)) map.childrenOf.set(parentId, []);
  map.childrenOf.get(parentId).push(nodeRes.id);
  map.childrenOf.set(nodeRes.id, []);

  selectWbItem("node", nodeRes.id);
  wbScheduleRender();
  // **A new branch is an empty thought, so it opens ready to be typed.**
  // Before this it was a card reading "New branch" and nothing else: the
  // gesture created a node and then left you to find the way to name it,
  // which is the difference between a mind-mapping tool and a diagram
  // editor. `wbScheduleRender` is async, so this waits for the card to
  // exist rather than assuming it does.
  requestAnimationFrame(() => wbEditNodeText(nodeRes.id));
  return nodeRes;
}

/** Put a card into edit mode with its text selected.
 *
 *  A concept map is written by typing, so the node a branch gesture just
 *  created has to be typeable *now*, not after finding a menu. Selecting
 *  the placeholder means the first keystroke replaces it, which is what
 *  makes `Tab, type, Tab, type` a fluent way to work rather than a sequence
 *  of edits.
 */
function wbEditNodeText(nodeId) {
  const node = wbState.nodes.find((n) => n.id === nodeId);
  if (!node) return;
  const card = document.querySelector(`.node-card[data-id="${nodeId}"]`);
  const content = card?.querySelector(".wb-card-content");
  if (!content) return;
  const entry = allEntries.find((e) => e.id === node.entry_id);
  const original = entry?.content || "";

  const box = document.createElement("textarea");
  box.className = "wb-card-editor";
  box.value = original;
  content.replaceChildren(box);
  box.focus();
  box.select();

  let settled = false;
  const finish = async (save) => {
    if (settled) return;
    settled = true;
    const text = box.value.trim();
    const keep = save && text ? text : original;
    if (save && text && text !== original) {
      try {
        await apiJson(`/entries/${node.entry_id}`, {
          method: "PUT",
          body: JSON.stringify({ content: text }),
        });
        // The card reads its text out of `allEntries`; without this the next
        // render would use the old content and the edit would look discarded.
        await loadEntries();
      } catch (err) {
        toast(err.message || "Couldn't save that.", true);
      }
    }
    // **Put the text back by hand, not by re-rendering.** Found live: after
    // saving, the textarea was still on the card. `wbScheduleRender` runs a
    // d3 data join, and card *content* is only built in the `enter`
    // selection: an existing card keeps whatever DOM it already has, which
    // here was the editor. So the edit saved correctly to the server and
    // looked like it had done nothing, which is the worst of both.
    content.replaceChildren();
    renderMarkdown(content, keep);
    wbScheduleRender();
  };

  // Enter commits, Shift+Enter is a real newline, the convention for a
  // single-idea field. Escape abandons. Blur commits, because clicking away
  // to the next card is the most common way to finish one.
  box.addEventListener("keydown", (event) => {
    event.stopPropagation(); // Tab/Enter here are text, not branch gestures
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      finish(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
    }
  });
  box.addEventListener("blur", () => finish(true));
}

//: Tab: a new child of the selected card, at "the next open radial slot":
//: evenly spaced by angle among the parent's existing children (plus the
//: one about to be added, so a lone first child doesn't land straight on
//: top of the parent), one ring further out.
async function wbMindMapAddChild(parentId) {
  const parent = wbState.nodes.find((n) => n.id === parentId);
  if (!parent) return;
  const map = wbMindMapEnsureMap(parentId);
  const existing = (map.childrenOf.get(parentId) || []).length;
  const slots = Math.max(existing + 1, 3);
  // **Fan out sideways first, not upwards.** The offset used to be
  // `-Math.PI / 2`, straight up, so the very first branch off a root card
  // landed one full ring *above* it. Driven live: a map created at the
  // canvas centre put its first Tab branch off the top edge, clipped and
  // half unreadable, which is a bad first impression of the one gesture the
  // whole feature turns on. Sideways is also how every mind-mapping tool
  // fans a first child, because a page is wider than it is tall.
  const angle = (existing / slots) * 2 * Math.PI;
  const parentBox = wbItemBBox("node", parent);
  const cx = (parentBox.minX + parentBox.maxX) / 2, cy = (parentBox.minY + parentBox.maxY) / 2;
  const w = parent.width || WB_CARD_DEFAULT_SIZE.w, h = parent.height || WB_CARD_DEFAULT_SIZE.h;
  await wbMindMapAddCard(
    parentId,
    cx + WB_MINDMAP_RADIAL_STEP * Math.cos(angle) - w / 2,
    cy + WB_MINDMAP_RADIAL_STEP * Math.sin(angle) - h / 2
  );
}

//: Enter: a new sibling of the selected card (a child of *its* parent).
//: A card with no known parent (the mind map's own root, or one never
//: linked to anything) has no sibling slot to fill, falls back to adding
//: a child of the card itself, the only branch that makes sense there.
async function wbMindMapAddSibling(cardId) {
  const map = wbMindMapEnsureMap(cardId);
  const parentId = map.parentOf.get(cardId);
  await wbMindMapAddChild(parentId == null ? cardId : parentId);
}

// --- maps: a board with a real tree on it (MINDMAP_PLAN.md §5, Phase 2) -----
//
// The backend half (§9) already stores, serves and exports all of this. Until
// this section existed the object renderer drew only `image` and `text`, so a
// map's nodes were in the database, in `GET /tree` and in every export except
// the one place anyone would look for them, the canvas. That is the blocker
// §9.3 names, and everything below is the frontend half of it.
//
// **This is not `wbArrangeMindMap` further up this file.** That is the concept
// map: whiteboard *cards* (a card is a real note) joined by link sketches,
// with a spanning tree inferred by BFS because a link carries no direction. A
// map node is a `WhiteboardObject` with a real `parent_id`, so its tree is
// stored rather than guessed, and a `topic` can exist with no note behind it.
// MINDMAP_PLAN.md §9.2 records why the two data models stayed separate. They
// share a canvas and nothing else, and neither function here calls that one.

//: The object kinds that are map nodes. `topic` is text that lives only on
//: the map; the other four are pointers at library items, drawn with that
//: item's own icon and its *resolved* title, never a copy of it, since a
//: copied title goes stale the moment the note behind it is renamed (§9.2).
const WB_MAP_KINDS = new Set(["topic", "note", "document", "file", "link"]);
const WB_MAP_REFERENCE_KINDS = new Set(["note", "document", "file", "link"]);

//: The Phosphor icon per kind, matching what the same item already shows in
//: the Library: a node has to read as the same object in both places, and
//: picking a second icon for a document here is exactly how it stops doing so.
const WB_MAP_ICONS = {
  topic: "ph-circle",
  note: "ph-note",
  document: "ph-file-text",
  file: "ph-paperclip",
  link: "ph-link-simple",
};

//: How far apart `wbMapTidy` puts things: the gap between two siblings on the
//: breadth axis, and between one depth and the next. Deliberately *not*
//: `MAP_ROW`/`MAP_COL` from routes_whiteboard.py: those are where the server
//: drops a node when nobody said, which only has to be "not on top of its
//: parent"; a tidy layout measures real node sizes and needs only the gap.
const WB_MAP_GAP_BREADTH = 26;
const WB_MAP_GAP_DEPTH = 76;

//: A node's size when it is not in the DOM, collapsed away, or being laid
//: out before its first paint. Matches `wbMapCreateNode`'s own defaults, so a
//: tidy run immediately after a Tab does not jump when the node then renders.
const WB_MAP_NODE_W = 200;
const WB_MAP_NODE_H = 56;

//: What the open board is, as far as maps are concerned: `{type, layout,
//: labels, crossLinks}`, or `null` on an ordinary whiteboard (which is every
//: board that predates this feature, and stays one).
//:
//: On `window` because library.js's gallery asks too, and a module-level
//: `let` here would be invisible to it, the same reason `window.currentBoardId`
//: lives there rather than here.
window.wbMapState = null;

function wbIsMap() {
  return window.wbMapState?.type === "map";
}

function wbMapLayout() {
  return window.wbMapState?.layout || "free";
}

//: Refresh `window.wbMapState` from `GET /boards/{id}/tree`.
//:
//: One request, because that endpoint is the only one carrying all three
//: things this needs: the board's `type`, its `layout`, and the **resolved
//: label** of every reference node. `GET /whiteboard/` returns objects whose
//: `data.ref_id` says which note a node points at and nothing about what that
//: note is called: so without this a map full of notes draws as a column of
//: identical blank boxes.
//:
//: Structure is deliberately *not* taken from here. `parent_id` is already on
//: every object `GET /whiteboard/` returned, so the tree is rebuilt locally on
//: every render (`wbMapIndex`) and a Tab keypress redraws immediately instead
//: of waiting on a round trip to be told what it already knows. This call is
//: for the two facts only the server has.
async function wbRefreshMapState() {
  const boardId = window.currentBoardId ?? null;
  if (!boardId) {
    // The default scratch board has no note behind it, so it has nowhere to
    // store settings and is always an ordinary board (`list_boards`' own
    // comment says so). Nothing to ask for.
    window.wbMapState = null;
    return null;
  }
  try {
    const tree = await apiJson(`/whiteboard/boards/${boardId}/tree`, { silent: true });
    const labels = new Map();
    const facets = new Map();
    // Iterative and seen-guarded: `parent_id` has no database constraint
    // behind it (§9.1), so a ring is possible in principle and has to end this
    // walk rather than the tab.
    const frontier = [...(tree.roots || [])];
    const seen = new Set();
    while (frontier.length) {
      const node = frontier.pop();
      if (!node || seen.has(node.id)) continue;
      seen.add(node.id);
      labels.set(node.id, node.text || "");
      //: What the notebook knows about the note behind this node, for the
      //: perspectives (§5 item 19). Only reference nodes have any, and only
      //: the server can resolve it, so it rides along with the labels rather
      //: than being a second request per node.
      if (node.ref_category || node.ref_updated_at) {
        facets.set(node.id, {
          category: node.ref_category || null,
          updated_at: node.ref_updated_at || null,
        });
      }
      frontier.push(...(node.children || []));
    }
    window.wbMapState = {
      type: tree.type,
      layout: tree.layout,
      labels,
      facets,
      crossLinks: tree.cross_links || [],
    };
  } catch {
    // A board that 404s here (the default board; a note deleted mid-session)
    // is simply not a map. Failing soft matters because this runs on every
    // board load: an ordinary whiteboard must not break because of it.
    window.wbMapState = null;
  }
  return window.wbMapState;
}

// --- Phase 5: perspectives, focus, metrics, templates ------------------------
//
//: MINDMAP_PLAN.md §5 items 18 to 21. Four things that make a map worth
//: keeping rather than worth making, and all four are *views* of the same
//: tree: none of them changes a node, and nothing here writes to the server
//: except a template, which creates nodes exactly as the keyboard does.
//:
//: They live together because they share one idea. A map's own structure is
//: all the canvas knew: which node is whose child, and what each is called.
//: The notebook knows more than that about half the nodes, what they are
//: filed under and when they were last touched, and item 19's own note says
//: this is "the thing a general mindmapper cannot do". `wbMapState.facets`
//: is that knowledge, resolved server-side in `/tree` (a reference node's
//: category and age) and never guessed here.

//: What a node's colour means. Branch is Coggle's rule and the default: the
//: other three answer a question about the notebook instead.
const WB_MAP_PERSPECTIVES = [
  { key: "branch", label: "Branch", hint: "Coggle's own rule: one colour per first-level branch" },
  { key: "category", label: "Category", hint: "The category each note behind a node is filed under" },
  { key: "age", label: "Age", hint: "When the note behind each node was last edited" },
  { key: "notes", label: "Behind a note", hint: "Which nodes stand for a real note and which are just topics" },
];

//: Kept in the browser, not on the board: a perspective is how *you* are
//: looking at a map right now, not a property of the map, and two people
//: opening the same notebook should not change each other's view. Same
//: reasoning as the Library's Cards/Rows preference, which is stored the same
//: way.
function wbMapPerspective() {
  try {
    const stored = localStorage.getItem("wbMapPerspective");
    return WB_MAP_PERSPECTIVES.some((p) => p.key === stored) ? stored : "branch";
  } catch {
    return "branch";
  }
}

function wbMapSetPerspective(key) {
  try {
    localStorage.setItem("wbMapPerspective", key);
  } catch {
    // A browser with storage switched off still gets the view it asked for
    // for this session; it just will not be remembered.
  }
  wbSyncMapChrome();
  renderWhiteboardNow();
}

//: The categories and ages the tree endpoint resolved, by node id. Empty for
//: every topic (a topic has nothing behind it) and for a private note, whose
//: facts stay behind the same boundary its text does.
function wbMapFacets() {
  return window.wbMapState?.facets || new Map();
}

//: Age, in the four buckets a person actually thinks in. Not a continuous
//: ramp: "how old is this" is answered as today / this week / this month /
//: older, and a gradient over six months makes two notes a fortnight apart
//: look identical anyway.
const WB_MAP_AGE_BUCKETS = [
  { key: "today", label: "Today", days: 1 },
  { key: "week", label: "This week", days: 7 },
  { key: "month", label: "This month", days: 31 },
  { key: "older", label: "Older", days: Infinity },
];

function wbMapAgeBucket(iso) {
  if (!iso) return null;
  const then = Date.parse(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  if (Number.isNaN(then)) return null;
  const days = (Date.now() - then) / 86400000;
  return WB_MAP_AGE_BUCKETS.find((bucket) => days < bucket.days) || WB_MAP_AGE_BUCKETS[3];
}

//: The palette every perspective draws from, `d3.schemeTableau10`, which is
//: what branch colour already uses and what `graph.js` colours clusters with.
//: One scale for the whole app rather than a second list of hex per view.
function wbMapPalette() {
  return (window.d3?.schemeTableau10 || []).slice(0, 10);
}

//: A grey for "this node has nothing to say under this perspective": a topic
//: with no note behind it, or a note whose category is unknown. Read off the
//: stylesheet rather than written here, so it follows the theme: a hard-coded
//: grey is invisible in dark mode, which is the failure `--wb-branch` was
//: introduced to avoid.
function wbMapQuietColour() {
  const style = getComputedStyle(document.documentElement);
  return (style.getPropertyValue("--muted") || "#8a8f98").trim();
}

//: Every node's colour under the current perspective, `Map<id, colour>`, the
//: same shape `wbMapColors` returns, so the renderer, the edge pass and the
//: export all keep taking one map and asking it for a colour.
function wbMapNodeColors(index) {
  const perspective = wbMapPerspective();
  if (perspective === "branch") return wbMapColors(index);
  const facets = wbMapFacets();
  const palette = wbMapPalette();
  const quiet = wbMapQuietColour();
  const colors = new Map();

  if (perspective === "notes") {
    for (const node of index.nodes) {
      colors.set(node.id, WB_MAP_REFERENCE_KINDS.has(node.kind) ? palette[0] : quiet);
    }
    return colors;
  }
  if (perspective === "age") {
    for (const node of index.nodes) {
      const bucket = wbMapAgeBucket(facets.get(node.id)?.updated_at);
      const at = bucket ? WB_MAP_AGE_BUCKETS.indexOf(bucket) : -1;
      // Newest darkest: `schemeBlues[4]` runs light to dark, so the index is
      // read from the end. More ink on the thing you touched today is the
      // reading a ramp is for.
      const blues = window.d3?.schemeBlues?.[4];
      colors.set(node.id, at < 0 || !blues ? quiet : blues[blues.length - 1 - at]);
    }
    return colors;
  }
  // Category. The order is the order they appear walking the tree, so the
  // same map draws the same colours twice running.
  const seen = new Map();
  for (const node of index.nodes) {
    const name = facets.get(node.id)?.category;
    if (!name) {
      colors.set(node.id, quiet);
      continue;
    }
    if (!seen.has(name)) seen.set(name, palette[seen.size % palette.length] || quiet);
    colors.set(node.id, seen.get(name));
  }
  return colors;
}

//: What the colours mean, on screen, while they are on screen. A view that
//: recolours a map and does not say what the colours are is a puzzle: the
//: legend is the difference between "these are blue" and "these were edited
//: this week".
function wbRenderMapLegend(passed = null) {
  const box = document.getElementById("wb-map-legend");
  if (!box) return;
  const perspective = wbMapPerspective();
  if (!wbIsMap() || perspective === "branch") {
    box.hidden = true;
    box.replaceChildren();
    return;
  }
  const index = passed || wbMapIndex();
  const facets = wbMapFacets();
  const palette = wbMapPalette();
  const quiet = wbMapQuietColour();
  const rows = [];
  if (perspective === "notes") {
    rows.push({ label: "Stands for a note", colour: palette[0] });
    rows.push({ label: "A topic of its own", colour: quiet });
  } else if (perspective === "age") {
    const blues = window.d3?.schemeBlues?.[4] || [];
    WB_MAP_AGE_BUCKETS.forEach((bucket, at) => {
      rows.push({ label: bucket.label, colour: blues[blues.length - 1 - at] || quiet });
    });
    rows.push({ label: "No note behind it", colour: quiet });
  } else {
    const seen = new Map();
    for (const node of index.nodes) {
      const name = facets.get(node.id)?.category;
      if (!name || seen.has(name)) continue;
      seen.set(name, palette[seen.size % palette.length] || quiet);
    }
    for (const [name, colour] of seen) rows.push({ label: name, colour });
    rows.push({ label: "No note behind it", colour: quiet });
  }

  const title = document.createElement("span");
  title.className = "wb-map-legend-title";
  title.textContent = `Colour: ${WB_MAP_PERSPECTIVES.find((p) => p.key === perspective)?.label || perspective}`;
  const list = document.createElement("div");
  list.className = "wb-map-legend-rows";
  for (const row of rows) {
    const line = document.createElement("span");
    line.className = "wb-map-legend-row";
    const swatch = document.createElement("i");
    swatch.className = "wb-map-legend-swatch";
    swatch.setAttribute("aria-hidden", "true");
    // Through the CSSOM, not an inline `style` attribute in markup: the CSP
    // drops those (CLAUDE.md, "a policy silently refusing the work").
    swatch.style.background = row.colour;
    const text = document.createElement("span");
    text.textContent = row.label;
    line.append(swatch, text);
    list.appendChild(line);
  }
  box.replaceChildren(title, list);
  box.hidden = false;
}

//: **Focus** (§5 item 18, Kumu's): start at one node and reveal the map a
//: step at a time, so a map of two hundred nodes can be read as the six that
//: matter right now.
//:
//: Never persisted, unlike the perspective above: focus is a gesture inside
//: one reading of a map, and coming back tomorrow to a map that only shows
//: four of its nodes, with no memory of having asked for that, is a map that
//: looks broken.
let wbMapFocusState = null;

//: How far focus reaches by default. One step shows the node, its parent and
//: its children, which is the smallest view that still says where you are.
const WB_MAP_FOCUS_DEFAULT_DEPTH = 1;
const WB_MAP_FOCUS_MAX_DEPTH = 6;

//: Everything focus is hiding: every node more than `depth` steps from the
//: focused one, counting parents, children *and* cross-links.
//:
//: Cross-links count because a map's own answer to "what is near this" cannot
//: exclude the edges the user drew to say exactly that; and the walk is a
//: plain breadth-first one over an undirected view of the tree, because
//: "near" is not a direction.
function wbMapFocusHidden(index) {
  const hidden = new Set();
  if (!wbMapFocusState) return hidden;
  const start = index.byId.get(wbMapFocusState.id);
  if (!start) {
    // The focused node was deleted while focus was on. Clearing it here
    // rather than leaving an empty canvas: a view pinned to something that no
    // longer exists shows nothing and explains nothing.
    wbMapFocusState = null;
    return hidden;
  }
  const near = new Map([[start.id, 0]]);
  const queue = [start.id];
  const crossed = new Map();
  for (const link of window.wbMapState?.crossLinks || []) {
    if (!crossed.has(link.source_id)) crossed.set(link.source_id, []);
    if (!crossed.has(link.target_id)) crossed.set(link.target_id, []);
    crossed.get(link.source_id).push(link.target_id);
    crossed.get(link.target_id).push(link.source_id);
  }
  while (queue.length) {
    const id = queue.shift();
    const step = near.get(id);
    if (step >= wbMapFocusState.depth) continue;
    const node = index.byId.get(id);
    const neighbours = [
      ...(index.childrenOf.get(id) || []).map((child) => child.id),
      ...(node?.parent_id != null && index.byId.has(node.parent_id) ? [node.parent_id] : []),
      ...(crossed.get(id) || []),
    ];
    for (const next of neighbours) {
      if (near.has(next) || !index.byId.has(next)) continue;
      near.set(next, step + 1);
      queue.push(next);
    }
  }
  for (const node of index.nodes) {
    if (!near.has(node.id)) hidden.add(node.id);
  }
  return hidden;
}

//: Everything not on screen: a collapsed branch, and whatever focus is
//: holding back. One function so the renderer, the arrow keys and the edge
//: pass cannot disagree about what is visible, which is how a key once moved
//: the selection to a node nobody could see.
function wbMapConcealed(index) {
  // A copy, not the set `wbMapHidden` returned: adding focus's own hidden ids
  // to that one would be this function editing another function's answer.
  const concealed = new Set(wbMapHidden(index));
  for (const id of wbMapFocusHidden(index)) concealed.add(id);
  return concealed;
}

function wbMapSetFocus(id, depth = WB_MAP_FOCUS_DEFAULT_DEPTH) {
  const index = wbMapIndex();
  if (!index.byId.has(id)) return;
  wbMapFocusState = { id, depth: Math.max(1, Math.min(WB_MAP_FOCUS_MAX_DEPTH, depth)) };
  wbSyncMapFocusChrome();
  renderWhiteboardNow();
}

function wbMapClearFocus() {
  if (!wbMapFocusState) return;
  wbMapFocusState = null;
  wbSyncMapFocusChrome();
  renderWhiteboardNow();
}

function wbMapStepFocus(by) {
  if (!wbMapFocusState) return;
  wbMapSetFocus(wbMapFocusState.id, wbMapFocusState.depth + by);
}

//: The focus bar: what is focused, how far it reaches, and the way out.
//:
//: Over the canvas rather than in the top bar, beside the gesture hints, for
//: two reasons: the bar is already fifteen controls wide, and a state this
//: strong (most of the map is not being drawn) has to be visible *where the
//: map is*, not in a strip above it that the eye has learned to skip.
function wbSyncMapFocusChrome(passed = null) {
  const bar = document.getElementById("wb-map-focus");
  if (!bar) return;
  if (!wbIsMap() || !wbMapFocusState) {
    bar.hidden = true;
    return;
  }
  const label = document.getElementById("wb-map-focus-label");
  const depth = document.getElementById("wb-map-focus-depth");
  const index = passed || wbMapIndex();
  const node = index.byId.get(wbMapFocusState.id);
  const name = node ? wbMapLabel(node) : "";
  if (label) label.textContent = name.length > 40 ? `${name.slice(0, 39)}…` : name;
  const shown = index.nodes.length - wbMapFocusHidden(index).size;
  if (depth) {
    depth.textContent = `${wbMapFocusState.depth} step${wbMapFocusState.depth === 1 ? "" : "s"}, ${shown} of ${index.nodes.length} nodes`;
  }
  bar.hidden = false;
}

//: **Map metrics** (§5 item 20), and only the honest ones. Node count, depth
//: and how much of the map stands for something real are facts about this
//: tree; "influence" and the rest of the centrality family need a graph with
//: cycles in it to mean anything, so the one graph measure here is the count
//: of cross-links, which is the thing that makes a map a network at all.
//:
//: An orphan branch is a root that is not the *first* root: a map has one
//: trunk by construction (the creation flow makes one), so a second root is
//: either deliberate or a node that lost its parent, and either way it is
//: worth being told about rather than left to be noticed.
function wbMapStats(index) {
  const facets = wbMapFacets();
  let deepest = 0;
  const depthOf = new Map();
  for (const root of index.roots) {
    const stack = [[root, 1]];
    while (stack.length) {
      const [node, depth] = stack.pop();
      if (depthOf.has(node.id)) continue;
      depthOf.set(node.id, depth);
      deepest = Math.max(deepest, depth);
      for (const child of index.childrenOf.get(node.id) || []) stack.push([child, depth + 1]);
    }
  }
  const references = index.nodes.filter((n) => WB_MAP_REFERENCE_KINDS.has(n.kind));
  const leaves = index.nodes.filter((n) => !(index.childrenOf.get(n.id) || []).length);
  const widest = index.nodes.reduce(
    (best, node) => {
      const kids = (index.childrenOf.get(node.id) || []).length;
      return kids > best.kids ? { node, kids } : best;
    },
    { node: null, kids: 0 }
  );
  const filed = new Set();
  for (const node of index.nodes) {
    const name = facets.get(node.id)?.category;
    if (name) filed.add(name);
  }
  return {
    nodes: index.nodes.length,
    topics: index.nodes.length - references.length,
    references: references.length,
    depth: deepest,
    roots: index.roots.length,
    orphans: Math.max(0, index.roots.length - 1),
    leaves: leaves.length,
    crossLinks: (window.wbMapState?.crossLinks || []).length,
    collapsed: index.nodes.filter((n) => n.data?.collapsed).length,
    categories: filed.size,
    widest: widest.node ? { label: wbMapLabel(widest.node), kids: widest.kids } : null,
  };
}

function wbShowMapStats() {
  if (!wbIsMap()) {
    toast("Stats are about a map's tree: this board is a free canvas.");
    return;
  }
  const stats = wbMapStats(wbMapIndex());
  const rows = [
    ["Nodes", `${stats.nodes} (${stats.references} from the library, ${stats.topics} topics of their own)`],
    ["Depth", `${stats.depth} level${stats.depth === 1 ? "" : "s"}`],
    ["Ends", `${stats.leaves} node${stats.leaves === 1 ? "" : "s"} with nothing under them`],
    ["Widest branch", stats.widest ? `${stats.widest.label} (${stats.widest.kids} children)` : "None yet"],
    ["Cross-links", `${stats.crossLinks}`],
    ["Categories behind it", `${stats.categories}`],
    ["Collapsed", `${stats.collapsed}`],
  ];
  if (stats.orphans) {
    rows.push([
      "Loose roots",
      `${stats.orphans} branch${stats.orphans === 1 ? "" : "es"} not hanging off the first one`,
    ]);
  }
  const body = document.createElement("dl");
  body.className = "wb-map-stats";
  for (const [term, value] of rows) {
    const name = document.createElement("dt");
    name.textContent = term;
    const said = document.createElement("dd");
    said.textContent = value;
    body.append(name, said);
  }
  wbInfoDialog("What this map is made of", body);
}

//: A read-only dialog: a title, a block of content, one way out.
//:
//: `confirmDialog` is the app's dialog for a *question*, and its shape says
//: so: a sentence and two buttons, one of them destructive by default.
//: Reporting facts through it would put an OK and a Cancel under a table of
//: numbers, which asks the reader what they are agreeing to.
function wbInfoDialog(title, body) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay confirm-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", title);
  const card = document.createElement("div");
  card.className = "card modal-card confirm-card";
  const head = document.createElement("div");
  head.className = "row confirm-head";
  const heading = document.createElement("h3");
  heading.className = "confirm-title";
  heading.textContent = title;
  head.appendChild(heading);
  const row = document.createElement("div");
  row.className = "row confirm-actions";
  const returnFocus = document.activeElement;
  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    returnFocus?.focus?.();
  };
  const onKey = (event) => {
    if (event.key !== "Escape") return;
    event.stopPropagation();
    close();
  };
  row.append(smallButton("Close", "Close", close, false));
  card.append(head, body, row);
  overlay.appendChild(card);
  wireBackdropClose(overlay, close);
  document.addEventListener("keydown", onKey, true);
  document.body.appendChild(overlay);
}

//: **Templates** (§5 item 21). The plan's reason, quoted: "an empty canvas is
//: the main reason mindmap features go unused."
//:
//: Offered on the canvas of a map that has nothing but its root, and never
//: again after that: this is the one moment the offer helps, and a panel that
//: kept appearing over a map someone was building would be the opposite of
//: helpful. Dismissing it is remembered per board.
//:
//: Each template is a plain nested list, applied by creating nodes through
//: the same endpoint Tab uses. No new endpoint and no server-side template
//: table: a template *is* a few Tab presses, and writing it as data here
//: keeps it that way.
const WB_MAP_TEMPLATES = [
  {
    key: "brainstorm",
    label: "Brainstorm",
    hint: "Ideas, questions and what to do next",
    nodes: [
      { text: "Ideas", children: [{ text: "First idea" }] },
      { text: "Questions", children: [{ text: "What do I not know yet?" }] },
      { text: "Themes" },
      { text: "Next steps" },
    ],
  },
  {
    key: "decision",
    label: "Decision",
    hint: "Options, what they cost, and what would change your mind",
    nodes: [
      { text: "Options", children: [{ text: "Option A" }, { text: "Option B" }] },
      { text: "What matters", children: [{ text: "Cost" }, { text: "Time" }] },
      { text: "Risks" },
      { text: "What would change my mind" },
    ],
  },
  {
    key: "project",
    label: "Project",
    hint: "Goal, milestones, tasks and who is involved",
    nodes: [
      { text: "Goal" },
      { text: "Milestones", children: [{ text: "First milestone" }] },
      { text: "Tasks" },
      { text: "People" },
      { text: "Risks" },
    ],
  },
  {
    key: "causes",
    label: "Cause and effect",
    hint: "Ishikawa's four: people, process, tools, surroundings",
    nodes: [
      { text: "People" },
      { text: "Process" },
      { text: "Tools" },
      { text: "Surroundings" },
      { text: "What actually happened" },
    ],
  },
];

//: The three panels, resynced together.
//:
//: Called from the render as well as from `wbSyncMapChrome`, because all three
//: describe the map as it is *now*: the template offer has to go the moment a
//: second node exists, the legend has to grow a row when a node arrives from a
//: category nothing else on the map is filed under, and the focus bar counts
//: nodes. Syncing them only on board load left the offer sitting over a map
//: someone had already started building.
//:
//: `index` is passed in where the caller already has one: `wbMapIndex` walks
//: every object, and the render has just done that.
function wbSyncMapViews(index = null) {
  wbSyncMapFocusChrome(index);
  wbRenderMapLegend(index);
  wbRenderMapTemplates();
  wbSyncMapTemplates(index);
  wbSyncMapEmpty(index);
}

//: The way back from an empty map.
//:
//: Reported: "if i delete all nodes in a mindmap, I cant make more nodes."
//: Measured on the running app before touching anything: a map with zero
//: nodes drew no node to press Tab against, no node to right-click, and the
//: template offer is dismissible for good per board, so a map someone had
//: cleared had no route to a first topic at all.
//:
//: Shown at zero nodes only. At one node the template offer takes over, which
//: is the richer thing to say at that moment, and the two would otherwise
//: stack over the same canvas.
function wbSyncMapEmpty(passed = null) {
  const panel = document.getElementById("wb-map-empty");
  if (!panel) return;
  const index = wbIsMap() ? passed || wbMapIndex() : null;
  panel.hidden = !index || index.nodes.length > 0;
}

function wbMapTemplatesDismissedKey(boardId) {
  return `wbMapTemplatesDone:${boardId}`;
}

//: Shown when the map is still just its root, which is exactly when a
//: starting shape is worth offering and never after.
function wbSyncMapTemplates(passed = null) {
  const panel = document.getElementById("wb-map-templates");
  if (!panel) return;
  const boardId = window.currentBoardId;
  let dismissed = false;
  try {
    dismissed = Boolean(boardId && localStorage.getItem(wbMapTemplatesDismissedKey(boardId)));
  } catch {
    dismissed = false;
  }
  const index = wbIsMap() ? passed || wbMapIndex() : null;
  // Not while focus is on: they share the strip under the top bar, and a map
  // being read one branch at a time is not a map anyone wants a starting shape
  // for.
  panel.hidden = !index || dismissed || Boolean(wbMapFocusState) || index.nodes.length > 1;
}

function wbDismissMapTemplates() {
  try {
    if (window.currentBoardId) {
      localStorage.setItem(wbMapTemplatesDismissedKey(window.currentBoardId), "1");
    }
  } catch {
    // Not remembering the dismissal is a smaller failure than refusing to
    // dismiss it, so this is deliberately silent.
  }
  wbSyncMapTemplates();
}

//: Fill the map from a template, under whatever root it already has.
//:
//: Sequential rather than parallel on purpose: every child needs its parent's
//: real id, and a template is a dozen nodes at most, so this is a fraction of
//: a second either way and the order the nodes land in is the order they are
//: written here.
async function wbApplyMapTemplate(key) {
  const template = WB_MAP_TEMPLATES.find((t) => t.key === key);
  if (!template || !wbIsMap()) return;
  const index = wbMapIndex();
  const root = index.roots[0] || null;
  let made = 0;
  const place = async (nodes, parentId) => {
    for (const node of nodes) {
      const created = await wbMapCreateNode({ parentId, text: node.text });
      if (!created) return;
      made += 1;
      if (node.children?.length) await place(node.children, created.id);
    }
  };
  await place(template.nodes, root ? root.id : null);
  wbDismissMapTemplates();
  await wbRefreshMapState();
  await wbMapTidy({ quiet: true });
  renderWhiteboardNow();
  toast(`Started from the ${template.label.toLowerCase()} template: ${made} nodes.`);
}

//: The template panel's own buttons, built once from the list above so a
//: fifth template is one entry rather than one entry and one button.
function wbRenderMapTemplates() {
  const row = document.getElementById("wb-map-template-row");
  if (!row || row.childElementCount) return;
  for (const template of WB_MAP_TEMPLATES) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost small";
    button.dataset.wbTemplate = template.key;
    button.textContent = template.label;
    button.title = template.hint;
    button.addEventListener("click", () => wbApplyMapTemplate(template.key));
    row.appendChild(button);
  }
}

//: The board's map nodes as a tree, rebuilt from `wbState.objects`.
//:
//: **A node whose parent is not on this board is a root**, which is why this
//: is not a walk down from `parent_id == null`. Same rule as `_build_tree`
//: server-side, for the same reason (§9.1): a stale pointer would otherwise
//: make every node under it vanish from the canvas while still sitting in the
//: database, which is the worst way to lose something.
function wbMapIndex() {
  const nodes = (wbState.objects || []).filter((o) => WB_MAP_KINDS.has(o.kind));
  const byId = new Map(nodes.map((o) => [o.id, o]));
  const childrenOf = new Map();
  const roots = [];
  for (const obj of nodes) {
    const parent = obj.parent_id != null ? byId.get(obj.parent_id) : null;
    if (!parent || parent.id === obj.id) {
      roots.push(obj);
    } else {
      if (!childrenOf.has(parent.id)) childrenOf.set(parent.id, []);
      childrenOf.get(parent.id).push(obj);
    }
  }
  // Creation order throughout, so a sibling added with Enter lands after the
  // one it was added from rather than wherever the object array happens to
  // sit: and so two renders of an unchanged map are identical.
  for (const list of childrenOf.values()) list.sort((a, b) => a.id - b.id);
  roots.sort((a, b) => a.id - b.id);
  return { nodes, byId, childrenOf, roots };
}

//: Every node reachable from `id`, itself first, deepest last. Seen-guarded
//: for the ring case above; every walk in this section goes through it.
function wbMapSubtree(index, id) {
  const start = index.byId.get(id);
  if (!start) return [];
  const found = [start];
  const seen = new Set([id]);
  for (let i = 0; i < found.length; i += 1) {
    for (const child of index.childrenOf.get(found[i].id) || []) {
      if (seen.has(child.id)) continue;
      seen.add(child.id);
      found.push(child);
    }
  }
  return found;
}

//: Branch colour, which is Coggle's rule: a **first-level** topic takes the
//: next colour of the palette and every descendant inherits it, unless a node
//: carries its own `data.color`, which then becomes what *its* subtree
//: inherits, so recolouring a branch recolours the branch, not one box.
//:
//: The palette is the categorical scale the graph tab already colours its
//: clusters with (`d3.schemeTableau10`, graph.js ~1405), not a new list of
//: hex. Two surfaces colouring "one group of related things" differently is
//: this app's recurring failure, and a map branch and a graph cluster are the
//: same idea seen twice.
//:
//: Computed for the whole board in one walk rather than per node: a node's
//: colour depends on its ancestors, so a per-node lookup would walk the tree
//: once per node to learn what a single walk already knew.
function wbMapColors(index) {
  const palette = (window.d3?.schemeTableau10 || []).slice(0, 10);
  const colors = new Map();
  const seen = new Set();
  let branch = 0;
  const walk = (node, inherited) => {
    if (seen.has(node.id)) return;
    seen.add(node.id);
    const own = node.data?.color || inherited || null;
    colors.set(node.id, own);
    for (const child of index.childrenOf.get(node.id) || []) {
      // `inherited == null` is true for exactly one generation, the roots'
      // own children, which *are* the first-level topics. Starting the colours
      // at the root instead would give every branch on the map the same
      // colour, which is the one thing branch colour exists not to do.
      const next = child.data?.color
        || (inherited == null && palette.length ? palette[branch++ % palette.length] : own);
      walk(child, next);
    }
  };
  for (const root of index.roots) walk(root, null);
  return colors;
}

//: The nodes a collapsed branch hides. The collapsed node itself stays, it
//: is the thing you click to get the branch back, and it carries the count
//: badge that says how much is behind it.
function wbMapHidden(index) {
  const hidden = new Set();
  for (const node of index.nodes) {
    if (!node.data?.collapsed) continue;
    for (const descendant of wbMapSubtree(index, node.id)) {
      if (descendant.id !== node.id) hidden.add(descendant.id);
    }
  }
  return hidden;
}

//: What a node is *called*. A topic says what it says; a reference node's
//: label was resolved server-side (`_reference_label`) and arrives in
//: `wbMapState.labels`, with `data.content` as the fallback covering the
//: moment between creating one and the next tree refresh.
function wbMapLabel(obj) {
  if (obj.kind === "topic") return obj.data?.content || "";
  const resolved = window.wbMapState?.labels?.get(obj.id);
  if (resolved) return resolved;
  return obj.data?.content || `${obj.kind} ${obj.data?.ref_id ?? ""}`.trim();
}

//: `**bold**`, `*italic*` and `` `code` `` inside a node's own text.
//:
//: **Built as DOM nodes, never as an HTML string.** A node's text is the one
//: thing on a map guaranteed to be arbitrary user input, and this app's own
//: rule (and its CSP) says the same thing twice: nothing user-written reaches
//: `innerHTML`. `document.createTextNode` cannot be escaped wrongly because
//: there is no escaping step to get wrong.
//:
//: Inline only. A node label is a phrase, not a document, the full markdown
//: pass (`renderMarkdown`, which a text box reaches through `data.md`) builds
//: paragraphs and headings, which inside a 56px box is a worse answer than no
//: formatting at all.
//:
//: Each alternative is anchored and bounded by a negated class, so there is no
//: nested quantifier for CodeQL's polynomial-ReDoS shape to find.
const WB_MAP_INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/;

function wbMapInlineText(el, raw) {
  if (!el) return;
  el.replaceChildren();
  for (const piece of String(raw || "").split(WB_MAP_INLINE)) {
    if (!piece) continue;
    let tag = null;
    let inner = piece;
    if (piece.length > 4 && piece.startsWith("**") && piece.endsWith("**")) {
      tag = "strong";
      inner = piece.slice(2, -2);
    } else if (piece.length > 2 && piece.startsWith("*") && piece.endsWith("*")) {
      tag = "em";
      inner = piece.slice(1, -1);
    } else if (piece.length > 2 && piece.startsWith("`") && piece.endsWith("`")) {
      tag = "code";
      inner = piece.slice(1, -1);
    }
    if (!tag) {
      el.append(document.createTextNode(piece));
      continue;
    }
    const marked = document.createElement(tag);
    marked.textContent = inner;
    el.append(marked);
  }
}

//: The static half of a map node, built once as the node enters the DOM.
//:
//: Everything that changes while a map is edited, text, colour, the chevron's
//: direction, the count badge, lives in `wbPaintMapNode` instead, and the
//: chevron and badge are created here *always* and hidden when they have
//: nothing to say. Creating them on demand would mean the enter selection and
//: the update selection each had to know how to build one, which is exactly
//: how the same control ends up drawn two slightly different ways.
function wbBuildMapNode(el, d) {
  el.classed("wb-map-node", true);
  const body = el.append("div").attr("class", "wb-map-node-body");
  //: **Built for every node, hidden when it has nothing to say**, the same
  //: rule the chevron and the count badge already follow here and for the
  //: same reason: a reference node's kind icon and a topic's own chosen icon
  //: (§12.1 item 2) are one element, so the enter selection cannot build one
  //: shape and `wbPaintMapNode` a slightly different one. The class is set in
  //: the paint pass, which is the only place that knows what the node wears.
  body.append("i").attr("class", "wb-map-node-icon").attr("aria-hidden", "true");
  const text = body.append("div")
    .attr("class", "wb-map-text")
    .attr("contenteditable", "false");
  //: Where a topic points (§12.1 item 2's "link"). A real button, not a
  //: decoration: the whole point of setting a link is opening it, and a
  //: marker you have to go back to the strip to follow is a label. Hidden
  //: until there is one. `pointerdown` is stopped so following the link is
  //: not also the first frame of a node drag, the same guard the chevron and
  //: the two add buttons below already carry.
  body.append("button")
    .attr("type", "button")
    .attr("class", "wb-map-link")
    .property("hidden", true)
    .on("pointerdown", (event) => event.stopPropagation())
    .on("click", (event) => {
      event.stopPropagation();
      wbMapOpenLink(d);
    })
    .append("i").attr("class", "ph ph-link").attr("aria-hidden", "true");

  if (d.kind === "topic") {
    // A topic is renamed in place, through the same two functions a text box
    // uses: one edit path for the board, not two. A reference node has no
    // text of its own to edit: its label belongs to the note behind it, so
    // double-clicking one opens that note instead (below).
    text.on("dblclick", function (event) {
      event.stopPropagation();
      wbBeginTextEdit(this);
    });
    text.on("blur", function () {
      wbEndTextEdit(this);
      d.data = { ...d.data, content: this.textContent };
      wbSaveObject(d);
      // Back to the formatted view: `wbBeginTextEdit` put the raw source in
      // for editing, and without this the markers stay on screen as literal
      // asterisks until something else triggers a render.
      wbMapInlineText(this, d.data.content);
    });
    text.on("keydown", function (event) {
      if (!this.isContentEditable) return;
      // While typing, Tab/Enter are text and the branch gestures must not
      // fire: the same `stopPropagation` the card editor above needs, and
      // for the same reason.
      event.stopPropagation();
      if (event.key === "Escape" || (event.key === "Enter" && !event.shiftKey)) {
        event.preventDefault();
        this.blur();
      }
    });
    text.on("pointerdown", function (event) {
      if (this.isContentEditable) event.stopPropagation();
    });
  } else {
    el.on("dblclick", (event) => {
      event.stopPropagation();
      wbMapOpenReference(d);
    });
  }

  //: The count badge: how much a collapsed branch is holding. Without it a
  //: collapsed node is indistinguishable from a leaf, which is the difference
  //: between "folded away" and "not there".
  //:
  //: **A button, because §12.1 item 7 says it reopens on click.** It was a
  //: `<span aria-hidden>` and read as a decoration: the number told you
  //: something was folded away and the only way back was the chevron beside
  //: it. As a button it also answers Space and Enter for free once focused,
  //: which is the other half of the same item (and of §12.0's Space
  //: decision).
  el.append("button")
    .attr("type", "button")
    .attr("class", "wb-map-count")
    .property("hidden", true)
    .on("pointerdown", (event) => event.stopPropagation())
    .on("click", (event) => {
      event.stopPropagation();
      wbMapToggleCollapse(d.id);
    });

  // The chevron (collapse) and the `+` (add a child) are the pointer half of
  // the keyboard gestures: `.ghost.small.icon-only`, the app's own tonal
  // icon-button recipe, not a shape invented for the canvas. Both stop
  // `pointerdown` so grabbing one is not also the start of a node drag.
  const stopDrag = (event) => event.stopPropagation();
  el.append("button")
    .attr("type", "button")
    .attr("class", "ghost small icon-only wb-map-collapse")
    .property("hidden", true)
    .on("pointerdown", stopDrag)
    .on("click", (event) => {
      event.stopPropagation();
      wbMapToggleCollapse(d.id);
    })
    .append("i").attr("class", "ph ph-caret-down").attr("aria-hidden", "true");
  //: **Two ways to grow the map, in one row.** `+` makes a topic; the second
  //: button makes a node that *points at* a real note, document, file or link
  //: (§5 item 11: the half §10.4 recorded as missing: "a reference node was
  //: never placed by hand", so the kind rendered and was unreachable outside
  //: the AI tools).
  //:
  //: A second button rather than a mode on `+`: the two are different acts,
  //: not two settings of one, and a `+` that sometimes opens a dialog is the
  //: "a second modal that only appears after you commit the first" shape
  //: CLAUDE.md records costing five reports on bookmark URLs. Both are also
  //: in the node's context menu, because a right-click is where people look
  //: for "what can I do with this" and these only appear on hover.
  //:
  //: A flex row rather than two absolutely-positioned buttons: two of them
  //: hand-placed off the same corner is how they come to overlap by a few
  //: pixels that a screenshot does not show, which this file has already had
  //: to fix twice for the count badge (see `.wb-map-count`'s own comment).
  //: **The text-size grip** (MINDMAP_PLAN.md §12.1 item 6): drag the node's
  //: own corner and the words get bigger. The strip has four sizes, which is
  //: the right control for "make this a heading"; this is the one for
  //: "a little bigger than that", and mind-mapping tools all have it because
  //: a map's hierarchy is carried as much by size as by position.
  //:
  //: Plain pointer events with capture, not a d3 drag: `preventDefault` on
  //: `pointerdown` suppresses the compatibility `mousedown` that `objDrag`
  //: listens for, so grabbing the grip cannot also be the first frame of a
  //: node drag. The class is in `objDrag`'s own filter as well, because one
  //: guard for this is what the resize handles already learned is not enough.
  el.append("button")
    .attr("type", "button")
    .attr("class", "wb-map-size-grip")
    .attr("title", "Drag to change the text size")
    .attr("aria-label", "Drag to change the text size")
    .on("pointerdown", function (event) {
      event.stopPropagation();
      event.preventDefault();
      wbMapStartSizeDrag(this, event, d);
    })
    .append("i").attr("class", "ph ph-text-aa").attr("aria-hidden", "true");

  const actions = el.append("div").attr("class", "wb-map-actions");
  actions.append("button")
    .attr("type", "button")
    .attr("class", "ghost small icon-only wb-map-add")
    .attr("title", "Add a child (Tab)")
    .attr("aria-label", "Add a child topic")
    .on("pointerdown", stopDrag)
    .on("click", (event) => {
      event.stopPropagation();
      wbMapAddChild(d.id);
    })
    .append("i").attr("class", "ph ph-plus").attr("aria-hidden", "true");
  actions.append("button")
    .attr("type", "button")
    .attr("class", "ghost small icon-only wb-map-ref")
    .attr("title", "Add a child from the library…")
    .attr("aria-label", "Add a child that points at a note, document, file or link")
    .on("pointerdown", stopDrag)
    .on("click", (event) => {
      event.stopPropagation();
      wbMapAddReference(d.id);
    })
    .append("i").attr("class", "ph ph-bookmarks-simple").attr("aria-hidden", "true");
}

//: The half that changes: label, branch colour, chevron, badge. Runs for
//: every visible map node on every render, so it does no work that the enter
//: selection could have done once.
function wbPaintMapNode(el, d, index, colors) {
  const node = el.node();
  if (!node) return;
  const text = node.querySelector(".wb-map-text");
  // Never while it is being typed into: a render triggered by something else
  // moving on the board would otherwise replace the caret and the half-typed
  // word: the exact bug `objectUpdate` already avoids for a text box.
  if (text && document.activeElement !== text) {
    wbMapInlineText(text, wbMapLabel(d));
  }

  // A custom property rather than a colour on each part: the fill, the edge
  // and the branch's own edges all derive from one value in CSS, so a
  // recoloured branch cannot end up with a border of the old colour.
  // Set through CSSOM (`style.setProperty`), not a `style=` attribute: the
  // CSP rejects those outright, and thirty-five of them once shipped as
  // silently dead markup (CLAUDE.md).
  const colour = colors?.get(d.id);
  if (colour) node.style.setProperty("--wb-branch", colour);
  else node.style.removeProperty("--wb-branch");

  const children = index?.childrenOf.get(d.id) || [];
  const collapsed = Boolean(d.data?.collapsed);
  const chevron = node.querySelector(".wb-map-collapse");
  if (chevron) {
    chevron.hidden = children.length === 0;
    chevron.title = collapsed ? "Expand this branch" : "Collapse this branch";
    chevron.setAttribute("aria-label", chevron.title);
    chevron.setAttribute("aria-expanded", collapsed ? "false" : "true");
    const icon = chevron.querySelector("i");
    if (icon) icon.className = collapsed ? "ph ph-caret-right" : "ph ph-caret-down";
  }
  const badge = node.querySelector(".wb-map-count");
  if (badge) {
    // The whole subtree, not just the direct children: what the badge is
    // answering is "how much is folded away here", and a branch three deep
    // that reported "2" would be understating itself by an order of magnitude.
    const buried = collapsed && index ? wbMapSubtree(index, d.id).length - 1 : 0;
    badge.hidden = buried <= 0;
    badge.textContent = String(buried);
    const label = `Open the ${buried} topic${buried === 1 ? "" : "s"} folded in here`;
    badge.title = label;
    badge.setAttribute("aria-label", label);
  }
  el.classed("wb-map-collapsed", collapsed);
  el.classed("wb-map-pinned", Boolean(d.data?.pinned));
  wbPaintMapNodeStyle(node, d);
}

//: What the node edit strip sets, drawn on the node (§12.1 item 2).
//:
//: Split out of `wbPaintMapNode` rather than inlined into it because the
//: strip changes one node at a time and a full render is the wrong price for
//: a bold toggle: `wbMapSetNodeStyle` calls this directly for the node it
//: just changed, and the render calls it for every node, and both get the
//: same result by construction rather than by two lists of properties being
//: kept in step.
function wbPaintMapNodeStyle(node, d) {
  const data = d.data || {};
  node.classList.toggle("wb-map-bold", Boolean(data.bold));
  node.classList.toggle("wb-map-italic", Boolean(data.italic));
  //: The shape is a data attribute rather than four classes for the same
  //: reason `align` is: they are exclusive, and a class per value is a class
  //: somebody forgets to remove. The stylesheet holds the four looks; an
  //: unset shape is the rounded card this map has always drawn.
  if (data.shape) node.dataset.shape = data.shape;
  else delete node.dataset.shape;
  if (data.align) node.dataset.align = data.align;
  else delete node.dataset.align;
  // Px through CSSOM, which is what a text box's own `font_size` already
  // does (`renderWbObjects`): the value is per node and arbitrary, so it
  // cannot be a token, and the stylesheet's own `var(--text-md)` is the
  // default this replaces only when there is something to replace it with.
  if (data.font_size) node.style.fontSize = `${data.font_size}px`;
  else node.style.removeProperty("font-size");

  const icon = node.querySelector(".wb-map-node-icon");
  if (icon) {
    // A topic wears what it was given; a reference node falls back to the
    // icon for its kind, which is what says "this is a note, not a topic".
    const chosen = data.icon || (WB_MAP_REFERENCE_KINDS.has(d.kind) ? null : "");
    const name = chosen || (WB_MAP_REFERENCE_KINDS.has(d.kind)
      ? (WB_MAP_ICONS[d.kind] || WB_MAP_ICONS.topic).replace(/^ph-/, "")
      : "");
    icon.hidden = !name;
    icon.className = name ? `ph ph-${name} wb-map-node-icon` : "wb-map-node-icon";
  }

  const link = node.querySelector(".wb-map-link");
  if (link) {
    const href = typeof data.link === "string" ? data.link : "";
    link.hidden = !href;
    if (href) {
      link.title = `Open ${href}`;
      link.setAttribute("aria-label", `Open the page this topic links to`);
    }
  }
}

//: The three schemes a topic's link may have, checked again at the click.
//:
//: The schema validator (`_safe_link_scheme`) refuses anything else on the
//: way in, so this is the second of two doors, and it is here because a value
//: stored before that validator existed, or written by a tool that talks to
//: the database another way, would otherwise reach `window.open` unexamined.
//: CLAUDE.md's own rule for the map's delete policy says it plainly: a rule
//: enforced at one of two doors is not a rule.
const WB_MAP_LINK_SCHEMES = /^(https?:\/\/|mailto:)/i;

function wbMapOpenLink(d) {
  const href = d.data?.link;
  if (!href || !WB_MAP_LINK_SCHEMES.test(String(href).trim())) {
    toast("That topic's link is not a web address.", true);
    return;
  }
  window.open(String(href).trim(), "_blank", "noopener,noreferrer");
}

//: The grip's drag, from pointerdown to drop.
//:
//: Live on the element and stored once, at the end: a PUT per pixel of drag
//: is the flood `wbBeginTextEdit`'s own blur-save comment warns about, and the
//: node is already showing the new size, so there is nothing to see for it.
//: Divided by the zoom, so the gesture means the same amount of text at every
//: scale rather than four times as much when zoomed out.
function wbMapStartSizeDrag(grip, event, d) {
  const node = grip.closest(".wb-object");
  if (!node) return;
  const container = document.getElementById("whiteboard-container");
  const k = container ? d3.zoomTransform(container).k : 1;
  const startY = event.clientY;
  const startSize = d.data?.font_size || WB_MAP_TEXT_DEFAULT;
  let size = startSize;
  grip.setPointerCapture?.(event.pointerId);
  const move = (moveEvent) => {
    // Four pixels of drag to one of type: the whole useful range (10 to 44)
    // is then about 140px of travel, which is a gesture rather than a twitch.
    const next = startSize + ((moveEvent.clientY - startY) / k) / 4;
    size = Math.round(Math.min(WB_MAP_TEXT_MAX, Math.max(WB_MAP_TEXT_MIN, next)));
    node.style.fontSize = `${size}px`;
  };
  const done = async () => {
    grip.removeEventListener("pointermove", move);
    grip.removeEventListener("pointerup", done);
    grip.removeEventListener("pointercancel", done);
    if (size === startSize) return;
    await wbMapSetNodeStyle(d, { font_size: size });
  };
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", done);
  grip.addEventListener("pointercancel", done);
}

//: Open every folded branch on the map (§12.1 item 7's third route, after the
//: badge and the chevron). One PUT per folded node rather than a bulk call,
//: which is the same bargain `wbSaveBulkMove` makes and for the same reason:
//: there is no bulk endpoint, and the number of *folded* nodes on a map is
//: small even when the map is not.
async function wbMapExpandAll() {
  const folded = wbMapIndex().nodes.filter((o) => o.data?.collapsed);
  if (!folded.length) {
    toast("Nothing is folded away on this map.");
    return;
  }
  for (const node of folded) {
    node.data = { ...node.data, collapsed: false };
    await wbSaveObject(node);
  }
  renderWhiteboardNow();
  wbSyncMapToolState();
  toast(`Opened ${folded.length} branch${folded.length === 1 ? "" : "es"}.`);
}

//: --- drag a branch onto a new parent (MINDMAP_PLAN.md §12.1 item 8) --------
//:
//: Three things, and they are one gesture: dragging a topic takes its branch
//: with it, dropping it on another topic re-parents the branch there, and
//: Ctrl held moves the topic alone and lets its children up to its old parent.

//: The whole branch's starting positions, in the shape `wbApplyBulkMove`
//: already understands. Reusing the marquee's own machinery rather than
//: writing a second mover: it already recomputes from a fixed baseline each
//: frame (rather than compounding a delta), and it already keeps each moved
//: node's tree edges and link sketches live, both of which this needs and
//: neither of which is obvious until they are missing.
function wbMapBranchDragOrigin(d, alone) {
  if (alone || !wbIsMap() || !WB_MAP_KINDS.has(d.kind)) return null;
  const index = wbMapIndex();
  const keys = wbMapSubtree(index, d.id)
    .filter((o) => o.id !== d.id)
    .map((o) => wbMultiKey("object", o.id));
  return keys.length ? wbCaptureBulkMoveOrigin(null, keys) : null;
}

//: The topic under the pointer that this branch could be dropped on, or null.
//:
//: **Geometry, not `elementFromPoint`.** The dragged node follows the pointer,
//: so it is the element under it for the whole gesture; the usual answer is to
//: turn its pointer events off mid-drag, which is a second state to get wrong.
//: The board already knows where everything is, so this asks it.
//:
//: A node's own descendants are excluded because dropping a branch inside
//: itself is the ring `/move` refuses, and an offer the server will reject is
//: worse than no offer.
function wbMapDropTargetAt(d, clientX, clientY) {
  const container = document.getElementById("whiteboard-container");
  if (!container || !wbIsMap() || !WB_MAP_KINDS.has(d.kind)) return null;
  const rect = container.getBoundingClientRect();
  const t = d3.zoomTransform(container);
  const [bx, by] = t.invert([clientX - rect.left, clientY - rect.top]);
  const index = wbMapIndex();
  const forbidden = new Set(wbMapSubtree(index, d.id).map((o) => o.id));
  const hidden = wbMapConcealed(index);
  for (const node of index.nodes) {
    if (forbidden.has(node.id) || hidden.has(node.id)) continue;
    const size = wbMapNodeSize(node);
    if (bx >= node.x && bx <= node.x + size.w && by >= node.y && by <= node.y + size.h) {
      return node;
    }
  }
  return null;
}

//: The highlight, and the one place it is cleared. A class rather than an
//: inline style: the CSP rejects `style=` and a drop cue that silently did
//: nothing is the fourth shape CLAUDE.md §6 lists.
let wbMapDropTargetId = null;

function wbMapShowDropTarget(id) {
  if (wbMapDropTargetId === id) return;
  wbMapClearDropTarget();
  if (id == null) return;
  document.querySelector(`.wb-object[data-id="${id}"]`)?.classList.add("wb-map-drop-target");
  wbMapDropTargetId = id;
}

function wbMapClearDropTarget() {
  if (wbMapDropTargetId == null) return;
  document.querySelector(`.wb-object[data-id="${wbMapDropTargetId}"]`)
    ?.classList.remove("wb-map-drop-target");
  wbMapDropTargetId = null;
}

//: The drop. `alone` is Ctrl held: the topic moves by itself and its children
//: go up to its old parent first, so nothing is orphaned and nothing travels
//: that was not asked for.
//:
//: The node is unpinned on the way: it was dragged, so `wbMapPinOnDrag` would
//: otherwise fix it exactly where the pointer let go, which is the one place
//: it should not stay now that it belongs to a different parent.
async function wbMapTransplant(d, targetId, alone) {
  const boardId = window.currentBoardId;
  const index = wbMapIndex();
  const target = index.byId.get(targetId);
  if (!boardId || !target) return false;
  if (d.parent_id === targetId && !alone) return false;
  const oldParent = index.byId.has(d.parent_id) ? d.parent_id : null;
  const move = (id, parentId) => apiJson(
    `/whiteboard/boards/${boardId}/nodes/${id}/move`,
    { method: "PUT", body: JSON.stringify({ parent_id: parentId }) }
  );
  try {
    if (alone) {
      for (const child of index.childrenOf.get(d.id) || []) {
        Object.assign(child, await move(child.id, oldParent));
      }
    }
    Object.assign(d, await move(d.id, targetId));
  } catch (err) {
    toast(err.message || "Couldn't move that branch.", true);
    return false;
  }
  if (d.data?.pinned) {
    d.data = { ...d.data, pinned: false };
    await wbSaveObject(d);
  }
  await wbMapTidyBranch(targetId);
  if (oldParent != null) await wbMapTidyBranch(oldParent);
  renderWhiteboardNow();
  toast(alone
    ? `Moved this topic under "${wbMapLabel(target)}", its branches stayed.`
    : `Moved this branch under "${wbMapLabel(target)}".`);
  return true;
}

//: Open the library item a reference node stands for. One place, because
//: "double-click opens it" is the whole reason a reference node is different
//: from a topic with the same words in it.
function wbMapOpenReference(d) {
  const refId = d.data?.ref_id;
  if (!refId) return;
  if (d.kind === "note" && typeof openEntryEditor === "function") {
    openEntryEditor(refId);
    return;
  }
  if (d.kind === "document" && typeof openDocument === "function") {
    openDocument(refId);
    return;
  }
  // A file and a bookmark have no single "open this" entry point that is safe
  // to guess at from here, so both go to the Library, which is where the item
  // actually lives. Saying so beats a click that appears to do nothing.
  toast(`This node points at a ${d.kind}: open it from the Library.`);
}

//: A node's drawn size. The DOM first, because a map node is `height: auto`
//: (its text decides how tall it is, so nothing can clip) and the stored
//: `height` column is therefore only ever an approximation of it. Falls back
//: to the stored value, then to the creation defaults, for a node that is not
//: in the DOM at all, collapsed away, or being laid out before first paint.
function wbMapNodeSize(d) {
  const el = document.querySelector(`.wb-object[data-id="${d.id}"]`);
  if (el && el.offsetHeight) return { w: el.offsetWidth, h: el.offsetHeight };
  return { w: d.width || WB_MAP_NODE_W, h: d.height || WB_MAP_NODE_H };
}

//: Where an edge leaves its parent and where it meets its child, by layout, 
//: right/left for a map that grows sideways, bottom/top for one that grows
//: down. `radial` and `free` have no fixed direction, so the axis is chosen
//: per edge from whichever delta is larger, which is what makes a radial map's
//: edges leave a node on the side the child is actually on.
function wbMapEdgeAnchors(parent, child, layout) {
  const p = wbMapNodeSize(parent);
  const c = wbMapNodeSize(child);
  let horizontal = layout === "tree-right";
  if (layout === "radial" || layout === "free") {
    horizontal = Math.abs(child.x - parent.x) >= Math.abs(child.y - parent.y);
  }
  if (horizontal) {
    const leftward = child.x + c.w / 2 < parent.x + p.w / 2;
    return {
      horizontal,
      x1: leftward ? parent.x : parent.x + p.w,
      y1: parent.y + p.h / 2,
      x2: leftward ? child.x + c.w : child.x,
      y2: child.y + c.h / 2,
    };
  }
  const upward = child.y + c.h / 2 < parent.y + p.h / 2;
  return {
    horizontal,
    x1: parent.x + p.w / 2,
    y1: upward ? parent.y : parent.y + p.h,
    x2: child.x + c.w / 2,
    y2: upward ? child.y + c.h : child.y,
  };
}

//: One tree edge's `d`, from the two nodes' live `x`/`y` and their rendered
//: sizes. Factored out of `wbRenderMapEdges` below so the per-frame drag
//: follow (`wbUpdateMapEdges`) recomputes an edge with exactly the maths the
//: render uses: two copies of a cubic drifted apart is precisely the bug
//: `wbUpdateLinkedSketches` warns about for link sketches.
function wbMapEdgePathD(parent, child, layout) {
  const a = wbMapEdgeAnchors(parent, child, layout);
  //: The line's own shape, from the link radial (§12.1 item 4). Read from the
  //: *child*, which is the end of a tree edge that has exactly one incoming
  //: line, and defaulting to the curve, so a map made before this existed
  //: draws exactly as it did.
  //:
  //: All three share the anchors above, so switching between them cannot move
  //: where a line meets a node: the difference is only what happens between
  //: the two points. The elbow turns at the same midpoint the curve's control
  //: points sit on, which is what keeps a column of siblings reading as one
  //: branch in either style.
  const style = child.data?.edge_style || "curve";
  const mx = (a.x1 + a.x2) / 2;
  const my = (a.y1 + a.y2) / 2;
  if (style === "straight") return `M${a.x1} ${a.y1} L${a.x2} ${a.y2}`;
  if (style === "elbow") {
    return a.horizontal
      ? `M${a.x1} ${a.y1} L${mx} ${a.y1} L${mx} ${a.y2} L${a.x2} ${a.y2}`
      : `M${a.x1} ${a.y1} L${a.x1} ${my} L${a.x2} ${my} L${a.x2} ${a.y2}`;
  }
  // Control points on the axis the edge leaves by, at half the span: the
  // curve leaves the parent square to its own edge and arrives square to
  // the child's, which is what makes a column of siblings read as one
  // branch rather than a fan of straight lines crossing each other.
  return a.horizontal
    ? `M${a.x1} ${a.y1} C${mx} ${a.y1} ${mx} ${a.y2} ${a.x2} ${a.y2}`
    : `M${a.x1} ${a.y1} C${a.x1} ${my} ${a.x2} ${my} ${a.x2} ${a.y2}`;
}

//: The tree edges touching `id` (its own edge up to its parent, and one per
//: child), each with the `<path>` that drew it, collected once per drag.
//:
//: **This is the single-node half of the "connections get left behind when i
//: move the notes/nodes around" report** (INBOX 42, with a screenshot of a
//: curve attached to neither node). A tree edge is not a link sketch, so
//: `wbUpdateLinkedSketches` never touched one, and nothing else ran between
//: `dragStart` and the drop: measured before this fix, the edge sat 155.6px
//: from the node it joins through a single-node drag, and stayed there after
//: the drop for any node already pinned (`wbMapPinOnDrag` returns early once
//: `data.pinned` is set, so its `wbScheduleRender` never fired a second
//: time). Precomputed for the same reason `wbLinkedSketchesFor` is: a node
//: gains or loses a parent between drags, never during one.
function wbMapEdgesFor(id) {
  if (!wbIsMap()) return [];
  const index = wbMapIndex();
  const self = index.byId.get(id);
  if (!self) return [];
  const layout = wbMapLayout();
  const found = [];
  const add = (parent, child) => {
    const el = document.querySelector(
      `.wb-map-edges .wb-map-edge[data-parent="${parent.id}"][data-child="${child.id}"]`
    );
    // The invisible twin has to follow the drag as well, or the line you can
    // point at stays where the line used to be: a target that is right until
    // the first time anything moves is worse than no target.
    const hit = document.querySelector(
      `.wb-map-edges .wb-map-edge-hit[data-parent="${parent.id}"][data-child="${child.id}"]`
    );
    if (el && hit) el._wbHitTwin = hit;
    // No element means the edge is not drawn right now (a collapsed or
    // filtered branch), which is not an error: there is simply nothing to
    // follow the drag.
    if (el) found.push({ parent, child, el, layout });
  };
  const parent = self.parent_id != null ? index.byId.get(self.parent_id) : null;
  if (parent) add(parent, self);
  for (const child of index.childrenOf.get(id) || []) add(self, child);
  return found;
}

//: Redraws the edges `wbMapEdgesFor` collected, without a full render. Same
//: bargain as `wbUpdateLinkedSketches`: a full `renderWhiteboardNow()` on
//: every mousemove frame re-binds every card, sketch and object on the board
//: for the sake of two curves, which is the "glitchy and slow to update"
//: report this file already carries.
function wbUpdateMapEdges(edges) {
  for (const { parent, child, el, layout } of edges || []) {
    const d = wbMapEdgePathD(parent, child, layout);
    el.setAttribute("d", d);
    if (el._wbHitTwin) el._wbHitTwin.setAttribute("d", d);
  }
}

//: The parent→child edges, drawn as cubic curves into their own group.
//:
//: A tree edge is deliberately **not** a link sketch. A sketch is a row in the
//: database that has to be created, moved and deleted alongside the node it
//: joins, and `parent_id` already says everything an edge means, so the edge
//: is derived on every render and there is no second thing to keep in step.
//: Cross-links stay real sketches, because they are the edges `parent_id`
//: cannot express (§9.1).
//:
//: The group is the first child of the zoom group so edges sit *under* every
//: sketch and node, which is the only z-order a tree reads correctly in.
function wbRenderMapEdges() {
  const zoomGroup = document.getElementById("wb-zoom-group");
  if (!zoomGroup) return;
  let group = zoomGroup.querySelector(".wb-map-edges");
  if (!wbIsMap()) {
    group?.remove();
    return;
  }
  if (!group) {
    group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "wb-map-edges");
    group.setAttribute("aria-hidden", "true");
    zoomGroup.insertBefore(group, zoomGroup.firstChild);
  }
  const index = wbMapIndex();
  const colors = wbMapNodeColors(index);
  const hidden = wbMapConcealed(index);
  const layout = wbMapLayout();
  const NS = "http://www.w3.org/2000/svg";
  const next = [];
  for (const parent of index.nodes) {
    if (hidden.has(parent.id) || parent.data?.collapsed) continue;
    for (const child of index.childrenOf.get(parent.id) || []) {
      if (hidden.has(child.id)) continue;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("class", child.data?.edge_dashed
        ? "wb-map-edge wb-map-edge-dashed"
        : "wb-map-edge");
      path.setAttribute("d", wbMapEdgePathD(parent, child, layout));
      // The two ends' ids, so a drag can find *this* edge again and redraw it
      // per frame (`wbMapEdgesFor`). The render itself still replaces the
      // whole group wholesale, see the note below; these attributes are the
      // identity a mid-drag update needs and nothing else reads.
      path.setAttribute("data-parent", String(parent.id));
      path.setAttribute("data-child", String(child.id));
      //: **A custom property, not a `stroke` attribute**, and the difference
      //: is the whole branch-colour feature. `.wb-map-edge` declares
      //: `stroke` in 07-whiteboard-misc.css, and a presentation attribute is
      //: a declaration at the bottom of the cascade, below every author rule
      //: however unspecific: so the attribute was dead markup and every edge
      //: on every map drew in the accent. Measured on a five-edge map: three
      //: distinct `stroke` attributes from the branch palette, one computed
      //: colour, `rgb(70, 100, 240)`, which is `--accent`. The thumbnail of
      //: the same map has been branch-coloured this whole time, which is the
      //: opposite of MINDMAP_PLAN §11.1's aim that the two pictures agree.
      //:
      //: `tests/test_svg_paint_attributes.py` is the lint that found it, and
      //: `el.style` sits above the stylesheet where the attribute sat below.
      const colour = colors.get(child.id);
      if (colour) path.style.setProperty("--wb-map-edge-colour", colour);
      next.push(path);
      //: The same curve again, transparent and wide enough to grab (§12.1
      //: item 4). Pushed *after* the visible path so it sits above it in the
      //: group, which is what an SVG hit test needs; it is invisible either
      //: way, and the visible line is inert.
      const hit = document.createElementNS(NS, "path");
      hit.setAttribute("class", "wb-map-edge-hit");
      hit.setAttribute("d", path.getAttribute("d"));
      hit.setAttribute("data-parent", String(parent.id));
      hit.setAttribute("data-child", String(child.id));
      wbWireMapEdgeGestures(hit, child.id);
      next.push(hit);
      //: What the line says (§12.1 items 3 and 4), at the curve's own middle.
      //: The midpoint is exact rather than approximated: both control points
      //: of `wbMapEdgePathD`'s cubic sit on the line between the anchors'
      //: midpoints, so the curve at t=0.5 passes through
      //: ((x1+x2)/2, (y1+y2)/2) in both orientations. Worked out rather than
      //: measured off a screenshot, which is what an offset that looks right
      //: on one layout and wrong on the other comes from.
      const label = child.data?.edge_label;
      if (label) {
        const a = wbMapEdgeAnchors(parent, child, layout);
        const text = document.createElementNS(NS, "text");
        text.setAttribute("class", "wb-map-edge-label");
        text.setAttribute("x", String((a.x1 + a.x2) / 2));
        text.setAttribute("y", String((a.y1 + a.y2) / 2));
        text.setAttribute("dy", "-0.4em");
        text.textContent = String(label);
        next.push(text);
      }
    }
  }
  // Replaced wholesale rather than joined: an edge has no identity of its own
  // (it *is* its two endpoints), so there is nothing for a data join to key
  // on, and a map's edge count is one per node, small enough that rebuilding
  // is cheaper than the bookkeeping a join would need.
  group.replaceChildren(...next);
  wbRenderMapEdgePluses(index, hidden, layout);
}

//: **A `+` at the middle of every line, to put a topic between two others**
//: (MINDMAP_PLAN.md §12.1 item 5, Coggle's own mid-point add). The other half
//: of that item, the `+` at the far end of a branch, is the node's own
//: `.wb-map-add` and has been there since Phase 2.
//:
//: Drawn in `#wb-html-layer` rather than in the edge group, and that is the
//: whole reason this is a separate pass: the layer carries the same pan and
//: zoom the edges do, so a button placed at board coordinates lands on the
//: line and scales with it, *and* it can be a real `button.ghost.small
//: .icon-only` from the app's own ramp instead of a shape drawn in SVG that
//: would be a control nothing else in the app looks like.
//:
//: Invisible until the pointer is on it (CSS), which is what keeps a map of
//: two hundred lines from being a map of two hundred buttons.
function wbRenderMapEdgePluses(index, hidden, layout) {
  const host = document.getElementById("wb-html-layer");
  if (!host) return;
  let layer = host.querySelector(".wb-map-plus-layer");
  if (!wbIsMap()) {
    layer?.remove();
    return;
  }
  if (!layer) {
    layer = document.createElement("div");
    layer.className = "wb-map-plus-layer";
    host.appendChild(layer);
  }
  const next = [];
  for (const parent of index.nodes) {
    if (hidden.has(parent.id) || parent.data?.collapsed) continue;
    for (const child of index.childrenOf.get(parent.id) || []) {
      if (hidden.has(child.id)) continue;
      const a = wbMapEdgeAnchors(parent, child, layout);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ghost small icon-only wb-map-edge-plus";
      button.title = "Put a topic between these two";
      button.setAttribute("aria-label", "Put a topic between these two");
      // Half the button's own 1.5rem, so its centre is on the line rather
      // than its top-left corner. In board units, which is what this layer
      // is measured in.
      button.style.left = `${(a.x1 + a.x2) / 2 - 12}px`;
      button.style.top = `${(a.y1 + a.y2) / 2 - 12}px`;
      const glyph = document.createElement("i");
      glyph.className = "ph ph-plus";
      glyph.setAttribute("aria-hidden", "true");
      button.appendChild(glyph);
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        wbMapInsertBetween(parent.id, child.id);
      });
      //: **It sits exactly where you would right-click the line**, so it has
      //: to pass that gesture on. Found by the sweep the moment this landed:
      //: the link ring stopped opening at a line's middle, because an
      //: invisible button was in front of the hit stroke and a right-click on
      //: a button is not a click. Forwarding it means the whole line answers
      //: the same gesture, middle included.
      button.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        event.stopPropagation();
        wbOpenMapLinkRadial(child.id, event.clientX, event.clientY);
      });
      next.push(button);
    }
  }
  layer.replaceChildren(...next);
}

//: Put a new topic between a parent and one of its children: the new topic
//: takes the parent, and the child takes the new topic.
//:
//: Two steps, and the second is a `/move` rather than a create-with-parent,
//: because the child already exists and `parent_id` is only writable through
//: the endpoint that runs the cycle check. The new topic opens for typing
//: like every other add on this map.
async function wbMapInsertBetween(parentId, childId) {
  const boardId = window.currentBoardId;
  if (!boardId) return;
  const created = await wbMapCreateNode({ parentId });
  if (!created) return;
  const child = (wbState.objects || []).find((o) => o.id === childId);
  if (!child) return;
  try {
    const moved = await apiJson(`/whiteboard/boards/${boardId}/nodes/${childId}/move`, {
      method: "PUT",
      body: JSON.stringify({ parent_id: created.id }),
    });
    Object.assign(child, moved);
  } catch (err) {
    toast(err.message || "Couldn't move that topic under the new one.", true);
    return;
  }
  selectWbItem("object", created.id);
  await wbMapTidyBranch(parentId);
  renderWhiteboardNow();
  wbMapEditNode(created.id);
}

// --- editing a map ----------------------------------------------------------
//
// Obsidian Canvas Mindmap's set (§5 item 5), which is the de-facto standard:
// Tab is a child, Enter a sibling, Shift+Tab outdents, the arrows walk the
// tree, F2 renames and Delete takes the subtree. The point of copying it
// rather than inventing one is that these are the gestures that make a mind
// map fast; dragging boxes one at a time is a drawing tool with a tree drawn
// on it.

//: The selected object, if it is a map node on a map. Everything keyboard
//: below goes through this rather than reading `wbSelectedItem` directly, so
//: "am I editing a map right now" is decided in one place.
function wbSelectedMapNode() {
  if (!wbIsMap() || wbSelectedItem?.kind !== "object") return null;
  const obj = (wbState.objects || []).find((o) => o.id === wbSelectedItem.id);
  return obj && WB_MAP_KINDS.has(obj.kind) ? obj : null;
}

//: Add one node, letting the **server** place it (§9.3: "Omit `x`/`y` and the
//: server places it"). A client that invents coordinates gets them wrong, and
//: gets them wrong differently from the AI tools and the OPML import, which is
//: how one map ends up looking like three tools' opinions of a map.
//: What a topic is called before you have called it anything.
//:
//: **Not an empty string**, which is what the first version created and what
//: looking at the result showed the problem with: five nodes on screen, four
//: of them blank white boxes with no way to tell a node you had not named yet
//: from a rendering fault. `wbMindMapAddCard` above reached the same
//: conclusion for the concept map and calls its own "New branch"; the label is
//: selected on creation, so the first keystroke replaces it either way.
const WB_MAP_NEW_TOPIC = "New topic";

async function wbMapCreateNode({ parentId = null, kind = "topic", text = WB_MAP_NEW_TOPIC, refId = null } = {}) {
  const boardId = window.currentBoardId;
  if (!boardId) return null;
  const body = { kind, parent_id: parentId, text };
  if (refId != null) body.ref_id = refId;
  try {
    const created = await apiJson(`/whiteboard/boards/${boardId}/nodes`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    wbState.objects = wbState.objects || [];
    wbState.objects.push(created);
    wbPushUndo({ action: "create", kind: "object", id: created.id });
    return created;
  } catch (err) {
    toast(err.message || "Couldn't add that node.", true);
    return null;
  }
}

//: Add a child of `parentId`, select it, tidy its branch and open it for
//: typing. **A new branch is an empty thought, so it opens ready to be typed**
//:, the same rule (and the same wording) the concept map's own branch gesture
//: follows further up this file; a node that makes you go and find the way to
//: name it is the difference between a mind-mapping tool and a diagram editor.
async function wbMapAddChild(parentId) {
  const created = await wbMapCreateNode({ parentId });
  if (!created) return null;
  // Expanding first: adding a child to a collapsed node would otherwise put
  // the new node straight into the hidden set, so the gesture would appear to
  // do nothing at all.
  const parent = (wbState.objects || []).find((o) => o.id === parentId);
  if (parent?.data?.collapsed) {
    parent.data = { ...parent.data, collapsed: false };
    await wbSaveObject(parent);
  }
  selectWbItem("object", created.id);
  await wbMapTidyBranch(parentId);
  renderWhiteboardNow();
  wbMapEditNode(created.id);
  return created;
}

//: Add a child that **points at something the library already holds**
//: (MINDMAP_PLAN.md §5 item 11).
//:
//: The label is *not* sent. `POST /boards/{id}/nodes` takes the kind and the
//: id and resolves the title itself, and `GET /tree` re-resolves it on every
//: load (§9.2): so renaming the note renames the node, which is the whole
//: reason a reference node is different from a topic with the same words in
//: it. `text` is left empty deliberately: a copy of the title stored here
//: would be the value that goes stale, and `wbMapLabel` prefers the resolved
//: one anyway.
//:
//: `wbRefreshMapState` is re-run before the render because the resolved label
//: lives in `wbMapState.labels`, which only that call fills, without it the
//: new node draws with no text at all until the next board load, which is
//: exactly the "renders as a blank box" failure §10.2 already fixed once for
//: topics.
async function wbMapAddReference(parentId) {
  if (typeof pickLibraryItemDialog !== "function") return null;
  const chosen = await pickLibraryItemDialog("Point a new node at…");
  if (!chosen) return null;
  const created = await wbMapCreateNode({
    parentId,
    kind: chosen.kind,
    text: "",
    refId: chosen.id,
  });
  if (!created) return null;
  const parent = (wbState.objects || []).find((o) => o.id === parentId);
  if (parent?.data?.collapsed) {
    parent.data = { ...parent.data, collapsed: false };
    await wbSaveObject(parent);
  }
  await wbRefreshMapState();
  selectWbItem("object", created.id);
  await wbMapTidyBranch(parentId);
  renderWhiteboardNow();
  toast(`Added “${chosen.label}” to the map.`);
  return created;
}

//: Enter: a sibling, which is a child of *this* node's parent. A root has no
//: parent to be a sibling under, so Enter there adds another root, which is
//: the only reading of "a sibling of the root" that means anything.
async function wbMapAddSibling(id) {
  const index = wbMapIndex();
  const node = index.byId.get(id);
  if (!node) return null;
  // A dangling `parent_id` counts as no parent, exactly as `wbMapIndex` and
  // `_build_tree` already treat it: so a node under a stale pointer gets a
  // sibling at the top level rather than one hung off a parent that is not
  // on this board.
  const parentId = node.parent_id != null && index.byId.has(node.parent_id)
    ? node.parent_id
    : null;
  return wbMapAddChild(parentId);
}

//: Shift+Tab: outdent: this node becomes a sibling of its own parent.
//:
//: Through `/move`, never `PUT /objects/{id}`, because the move endpoint is
//: the only one that runs the cycle check, §9.3 says so in as many words, and
//: `PUT` deliberately does not touch `parent_id` so the check cannot be
//: bypassed by using the wrong endpoint.
async function wbMapOutdent(id) {
  const boardId = window.currentBoardId;
  const index = wbMapIndex();
  const node = index.byId.get(id);
  if (!boardId || !node) return;
  const parent = node.parent_id != null ? index.byId.get(node.parent_id) : null;
  if (!parent) {
    toast("This is already a top-level topic.");
    return;
  }
  try {
    const moved = await apiJson(`/whiteboard/boards/${boardId}/nodes/${id}/move`, {
      method: "PUT",
      body: JSON.stringify({ parent_id: parent.parent_id ?? null }),
    });
    Object.assign(node, moved);
    await wbMapTidyBranch(moved.parent_id ?? null);
    renderWhiteboardNow();
  } catch (err) {
    toast(err.message || "Couldn't move that node.", true);
  }
}

//: The arrows, in tree terms rather than screen terms: up/down are the
//: siblings either side, left is the parent and right is the first child.
//:
//: Deliberately *not* "whatever box is nearest in that direction on screen".
//: A tree already knows what is above and below a node, and a spatial search
//: gives a different answer the moment two branches overlap, which is
//: precisely when you most need the keys to be predictable.
function wbMapNavigate(id, key) {
  const index = wbMapIndex();
  const node = index.byId.get(id);
  if (!node) return false;
  const hidden = wbMapConcealed(index);
  const siblings = node.parent_id != null && index.byId.has(node.parent_id)
    ? index.childrenOf.get(node.parent_id) || []
    : index.roots;
  const at = siblings.findIndex((s) => s.id === id);
  let target = null;
  if (key === "ArrowUp") target = siblings[at - 1];
  else if (key === "ArrowDown") target = siblings[at + 1];
  else if (key === "ArrowLeft") target = index.byId.get(node.parent_id);
  else if (key === "ArrowRight" && !node.data?.collapsed) {
    target = (index.childrenOf.get(id) || [])[0];
  }
  if (!target || hidden.has(target.id)) return false;
  selectWbItem("object", target.id);
  wbApplySelectionHighlight();
  wbUpdateSelectionBar();
  // Bring it on screen, but **only when it is actually off screen**.
  // Navigating into a node past the edge of the viewport reads exactly like
  // the key having done nothing, so the scroll has to happen; recentring on
  // every arrow instead makes the whole map lurch under you while you are
  // simply walking a branch you can already see, which is worse than either.
  const el = document.querySelector(`.wb-object[data-id="${target.id}"]`);
  const container = document.getElementById("whiteboard-container");
  if (el && container) {
    const node = el.getBoundingClientRect();
    const view = container.getBoundingClientRect();
    const offScreen = node.left < view.left || node.right > view.right
      || node.top < view.top || node.bottom > view.bottom;
    const box = offScreen ? wbItemBBox("object", target) : null;
    if (box) wbCenterOn(box, { animate: true });
  }
  return true;
}

//: F2 / double-click: rename in place, through the same two functions a text
//: box uses. A reference node has no text of its own: its label is the note's,
//: and editing it here would either lie or silently rename the note.
function wbMapEditNode(id) {
  const node = (wbState.objects || []).find((o) => o.id === id);
  if (!node) return;
  if (node.kind !== "topic") {
    toast("This node's name comes from the item it points at.");
    return;
  }
  // The render that just ran replaced this element, so it is looked up fresh
  // rather than kept from before, the same trap `wbCreateTextBox` documents.
  requestAnimationFrame(() => {
    const el = document.querySelector(`.wb-object[data-id="${id}"] .wb-map-text`);
    if (!el) return;
    wbBeginTextEdit(el);
    // Select the whole label so the first keystroke replaces it: a new node
    // arrives empty, and a renamed one is almost always being replaced rather
    // than edited.
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
}

//: **A map always keeps one topic** (MINDMAP_PLAN.md §12.0, decided after the
//: owner asked "should the user even be able to delete the primary core
//: node??").
//:
//: Not a taste call: every way of adding a node hangs off a node that is
//: already on the map (Tab on the selection, the hover +, the node's own
//: right-click menu), so the delete that empties a map is the delete that
//: removes the way to undo itself. The empty-state panel is the net under
//: this; the refusal is the rule.
//:
//: Refusing without an alternative would just be a wall, so the refusal
//: carries the action someone emptying a map actually wants: clear it and
//: start again from one blank topic.
function wbMapDeleteEmptiesMap(id) {
  if (!wbIsMap()) return false;
  const index = wbMapIndex();
  if (!index.byId.has(id)) return false;
  return index.nodes.length - wbMapSubtree(index, id).length <= 0;
}

function wbMapRefuseLastTopic() {
  toastAction(
    "A map keeps at least one topic, so this one stays.",
    "Clear the map",
    wbMapClearToOneTopic
  );
}

//: The explicit version of what deleting the last node would have done by
//: accident: take everything away, then leave one blank topic open for
//: typing, which is the state a new map starts in.
//:
//: Deleting the roots is enough to delete the map: `DELETE
//: /whiteboard/objects/{id}` takes a node's whole subtree with it (§9.1), so
//: one request per root removes every descendant too.
async function wbMapClearToOneTopic() {
  if (!wbIsMap()) return;
  const roots = wbMapIndex().roots;
  for (const root of roots) {
    try {
      const res = await apiJson(`/whiteboard/objects/${root.id}`, { method: "DELETE" });
      const gone = new Set((Array.isArray(res?.deleted) ? res.deleted : []).map((row) => row.id));
      gone.add(root.id);
      wbState.objects = (wbState.objects || []).filter((o) => !gone.has(o.id));
    } catch (err) {
      toast(err.message || "Couldn't clear the map.", true);
      return;
    }
  }
  clearWbSelection();
  await wbMapAddChild(null);
}

//: Delete: the subtree, with a real Undo rather than a confirm dialog.
//:
//: `DELETE /whiteboard/objects/{id}` returns the whole deleted subtree, rows
//: and positions included, precisely so this can put it back (§9.1). A confirm
//: dialog asks you to predict what you are about to lose; an undo shows you.
//: The re-create walks the returned list in order, it comes back parents
//: first: and maps each old id to its new one, so the tree comes back with
//: the shape it had rather than as a heap of roots.
async function wbMapDeleteSubtree(id) {
  const boardId = window.currentBoardId;
  const node = (wbState.objects || []).find((o) => o.id === id);
  if (!boardId || !node) return;
  if (wbMapDeleteEmptiesMap(id)) {
    wbMapRefuseLastTopic();
    return;
  }
  let deleted = [];
  try {
    const res = await apiJson(`/whiteboard/objects/${id}`, { method: "DELETE" });
    deleted = Array.isArray(res.deleted) ? res.deleted : [];
  } catch (err) {
    toast(err.message || "Couldn't delete that.", true);
    return;
  }
  const gone = new Set(deleted.map((row) => row.id));
  wbState.objects = (wbState.objects || []).filter((o) => !gone.has(o.id));
  clearWbSelection();
  wbScheduleRender();
  const count = deleted.length;
  toastAction(
    `Deleted ${count} node${count === 1 ? "" : "s"}.`,
    "Undo",
    async () => {
      const remap = new Map();
      for (const row of deleted) {
        // **A parent that was not itself deleted keeps its own id.** The first
        // version fell back to `null` whenever `remap` had no entry, which is
        // true for exactly one row, the top of the deleted subtree, whose
        // parent is still sitting on the board. So the branch came back as a
        // *root* instead of reattaching where it was taken from: five nodes
        // restored, four parent links gone down to three, measured. Only a
        // parent inside `deleted` needs translating, because only those have
        // new ids.
        const parent = row.parent_id == null
          ? null
          : remap.get(row.parent_id) ?? row.parent_id;
        const body = {
          kind: row.kind,
          parent_id: parent,
          text: row.data?.content || "",
          x: row.x,
          y: row.y,
        };
        if (row.data?.ref_id != null) body.ref_id = row.data.ref_id;
        if (row.data?.color) body.color = row.data.color;
        try {
          const recreated = await apiJson(`/whiteboard/boards/${boardId}/nodes`, {
            method: "POST",
            body: JSON.stringify(body),
          });
          remap.set(row.id, recreated.id);
          wbState.objects.push(recreated);
        } catch (err) {
          toast(err.message || "Couldn't restore that node.", true);
          break;
        }
      }
      await wbRefreshMapState();
      renderWhiteboardNow();
    }
  );
}

//: The chevron: fold a branch away, or bring it back. `collapsed` is per-node
//: view state in the object's own JSON blob (§9.1), so it survives a reload
//: and the tree endpoint hands it back, a fold you made yesterday is still
//: folded today, which is the only version of this that is worth having.
async function wbMapToggleCollapse(id) {
  const node = (wbState.objects || []).find((o) => o.id === id);
  if (!node) return;
  node.data = { ...node.data, collapsed: !node.data?.collapsed };
  wbScheduleRender();
  await wbSaveObject(node);
}

// --- tidy: Reingold–Tilford with variable node sizes (§5 item 6) ------------
//
// Implemented here rather than pulled in, because the app is offline-first and
// there is no CDN to pull from, and because `graph.js` already hand-rolls its
// own layout, so this is a sibling of existing code rather than a new
// dependency. The reference is Buchheim, Jünger and Leipert's linear-time form
// of Reingold–Tilford, with d3-flextree's extension: the distance between two
// nodes is half of each one's own size plus a gap, instead of a constant.
// Variable sizes are not a nicety here, a map node is as tall as its text.
//
// The breadth axis (siblings) is exact, per node. The depth axis is one offset
// per level, taken from the widest node on that level: that is what `d3.tree`
// itself does, and a per-node depth would let two nodes on the same level sit
// at different distances from the root, which reads as a broken tree rather
// than a tidy one.

//: One tidy pass. `roots` are wrapper objects `{obj, children}`; everything
//: else on a wrapper is the algorithm's own bookkeeping.
function wbTidyFirstWalk(v, breadthOf, gap) {
  if (!v.children.length) {
    v.prelim = v.number > 0 && v.parent
      ? v.parent.children[v.number - 1].prelim + wbTidyDistance(v, v.parent.children[v.number - 1], breadthOf, gap)
      : 0;
    return;
  }
  let defaultAncestor = v.children[0];
  for (const w of v.children) {
    wbTidyFirstWalk(w, breadthOf, gap);
    defaultAncestor = wbTidyApportion(w, defaultAncestor, breadthOf, gap);
  }
  wbTidyExecuteShifts(v);
  const midpoint = (v.children[0].prelim + v.children[v.children.length - 1].prelim) / 2;
  const left = v.number > 0 && v.parent ? v.parent.children[v.number - 1] : null;
  if (left) {
    v.prelim = left.prelim + wbTidyDistance(v, left, breadthOf, gap);
    v.mod = v.prelim - midpoint;
  } else {
    v.prelim = midpoint;
  }
}

//: How far apart two nodes on the same level must sit: half of each one's own
//: breadth plus the gap. The constant this replaces is the whole difference
//: between a tidy tree of identical boxes and one of real, differently-sized
//: nodes: with a constant, a tall node overlaps its neighbours and a short
//: one leaves a hole.
function wbTidyDistance(a, b, breadthOf, gap) {
  return (breadthOf(a) + breadthOf(b)) / 2 + gap;
}

function wbTidyNextLeft(v) {
  return v.children.length ? v.children[0] : v.thread;
}

function wbTidyNextRight(v) {
  return v.children.length ? v.children[v.children.length - 1] : v.thread;
}

function wbTidyMoveSubtree(wm, wp, shift) {
  const subtrees = wp.number - wm.number;
  if (!subtrees) return;
  wp.change -= shift / subtrees;
  wp.shift += shift;
  wm.change += shift / subtrees;
  wp.prelim += shift;
  wp.mod += shift;
}

function wbTidyExecuteShifts(v) {
  let shift = 0;
  let change = 0;
  for (let i = v.children.length - 1; i >= 0; i -= 1) {
    const w = v.children[i];
    w.prelim += shift;
    w.mod += shift;
    change += w.change;
    shift += w.shift + change;
  }
}

function wbTidyAncestor(vim, v, defaultAncestor) {
  return vim.ancestor && vim.ancestor.parent === v.parent ? vim.ancestor : defaultAncestor;
}

//: The part that makes the tree *tidy*: walk the right contour of everything
//: to the left and the left contour of this subtree in step, and push this
//: subtree right by however much they overlap. The threads (`nextLeft` /
//: `nextRight` falling back to `.thread`) are what keep it linear-time instead
//: of re-walking whole subtrees.
function wbTidyApportion(v, defaultAncestor, breadthOf, gap) {
  const left = v.number > 0 && v.parent ? v.parent.children[v.number - 1] : null;
  if (!left) return defaultAncestor;
  let vip = v;
  let vop = v;
  let vim = left;
  let vom = vip.parent.children[0];
  let sip = vip.mod;
  let sop = vop.mod;
  let sim = vim.mod;
  let som = vom.mod;
  while (wbTidyNextRight(vim) && wbTidyNextLeft(vip)) {
    vim = wbTidyNextRight(vim);
    vip = wbTidyNextLeft(vip);
    vom = wbTidyNextLeft(vom);
    vop = wbTidyNextRight(vop);
    vop.ancestor = v;
    const shift = vim.prelim + sim - (vip.prelim + sip) + wbTidyDistance(vim, vip, breadthOf, gap);
    if (shift > 0) {
      wbTidyMoveSubtree(wbTidyAncestor(vim, v, defaultAncestor), v, shift);
      sip += shift;
      sop += shift;
    }
    sim += vim.mod;
    sip += vip.mod;
    som += vom.mod;
    sop += vop.mod;
  }
  if (wbTidyNextRight(vim) && !wbTidyNextRight(vop)) {
    vop.thread = wbTidyNextRight(vim);
    vop.mod += sim - sop;
  }
  if (wbTidyNextLeft(vip) && !wbTidyNextLeft(vom)) {
    vom.thread = wbTidyNextLeft(vip);
    vom.mod += sip - som;
    return v;
  }
  return defaultAncestor;
}

//: The tidy positions for every map node, as `Map(id -> {x, y})`.
//:
//: Pure: it reads sizes and the tree and returns coordinates, touching neither
//: the DOM nor the network. That is what lets `wbMapTidy` below run the whole
//: layout, then paint once and save once, §8's "auto-layout must run off the
//: paint path", which is a real constraint here because the whiteboard already
//: had a lag bug of exactly that shape (task #71).
function wbMapTidyPositions(index, layout) {
  if (!index.roots.length) return new Map();
  const vertical = layout === "tree-down" || layout === "radial";
  // Breadth is the axis siblings spread along: heights for a map that grows
  // sideways, widths for one that grows downward. Radial spreads siblings
  // around a ring, so its breadth is a width too, arc length, before it is
  // turned into an angle.
  const sizes = new Map(index.nodes.map((o) => [o.id, wbMapNodeSize(o)]));
  //: **Radial measures breadth in angle, not in pixels**, and that is not a
  //: refinement: it is what makes the layout correct near the middle. The
  //: breadth axis becomes the angle, so a fixed pixel gap buys a *wide* angle
  //: at the first ring and a narrow one at the fifth: laid out in pixels, the
  //: nodes closest to the root overlap each other while the outer rings sit in
  //: empty space. Measured before this existed: two overlapping boxes out of
  //: five on the first radial layout. Dividing each node's width by its own
  //: ring number asks for the angle that width actually needs at that radius,
  //: which is d3's own `separation(a, b) / a.depth` in another form. The gap
  //: is folded in here for the same reason, so the distance function keeps
  //: working in one unit.
  const radial = layout === "radial";
  const breadthOf = (w) => {
    if (!w.obj) return 0; // the virtual root below has no size of its own
    const s = sizes.get(w.obj.id) || { w: WB_MAP_NODE_W, h: WB_MAP_NODE_H };
    if (radial) return (s.w + WB_MAP_GAP_BREADTH) / Math.max(1, w.depth);
    return vertical ? s.w : s.h;
  };
  const gap = radial ? 0 : WB_MAP_GAP_BREADTH;

  // One virtual root over the real ones, so a map with two top-level topics
  // is laid out as one tree rather than two overlapping ones. It is dropped
  // before any coordinate is written.
  const wrap = (obj, parent, number, depth) => {
    const node = {
      obj, parent, number, depth, children: [],
      prelim: 0, mod: 0, shift: 0, change: 0, thread: null, ancestor: null,
    };
    node.ancestor = node;
    const kids = obj ? index.childrenOf.get(obj.id) || [] : index.roots;
    // A collapsed branch is not laid out: its children are not on screen, and
    // reserving room for them would leave a hole where the fold is.
    if (!obj || !obj.data?.collapsed) {
      kids.forEach((child, i) => node.children.push(wrap(child, node, i, depth + 1)));
    }
    return node;
  };
  const virtual = wrap(null, null, 0, -1);

  wbTidyFirstWalk(virtual, breadthOf, gap);

  // Depth offsets: one per level, from the widest (or tallest) node on it.
  const perDepth = [];
  const collect = (w) => {
    if (w.obj) {
      const s = sizes.get(w.obj.id) || { w: WB_MAP_NODE_W, h: WB_MAP_NODE_H };
      perDepth[w.depth] = Math.max(perDepth[w.depth] || 0, vertical ? s.h : s.w);
    }
    w.children.forEach(collect);
  };
  collect(virtual);
  const ring = Math.max(...perDepth.filter(Number.isFinite), WB_MAP_NODE_W) + WB_MAP_GAP_DEPTH;
  const offsets = [0];
  for (let d = 1; d < perDepth.length; d += 1) {
    // Radial does not use these: its radius per ring is worked out below,
    // from the span the first walk actually produced.
    offsets[d] = offsets[d - 1] + (perDepth[d - 1] || 0) + WB_MAP_GAP_DEPTH;
  }

  const flat = [];
  const second = (w, m) => {
    if (w.obj) flat.push({ obj: w.obj, breadth: w.prelim + m, depth: w.depth });
    for (const child of w.children) second(child, m + w.mod);
  };
  second(virtual, 0);
  if (!flat.length) return new Map();

  const positions = new Map();
  if (layout === "radial") {
    // x as angle, y as radius, the same call `d3.tree().size([2π, 1])` makes
    // and the same reading of it: the breadth axis, normalised, *is* the angle.
    // The span is padded so the first and last branch do not meet back at the
    // top: by the *smallest* node extent in the layout, which is one node's
    // worth of angle at the outermost ring. Padding by a raw pixel constant
    // was wrong for the same reason the breadths above are divided by depth:
    // it is not a quantity in this unit at all.
    const extentOf = (f) =>
      ((sizes.get(f.obj.id)?.w || WB_MAP_NODE_W) + WB_MAP_GAP_BREADTH) / Math.max(1, f.depth);
    const min = Math.min(...flat.map((f) => f.breadth));
    const max = Math.max(...flat.map((f) => f.breadth));
    const span = max - min + Math.min(...flat.map(extentOf)) || 1;
    //: **The rings grow when the circle runs out of room**, and without this
    //: a radial map overlaps itself as soon as it has more nodes than one
    //: turn can hold. The breadth axis is normalised onto 2π, so the factor
    //: from a breadth unit to an angle is `2π / span`, while the arc a node
    //: needs at depth `d` is its own breadth divided by the ring spacing (the
    //: breadths above are already divided by depth for exactly this reason).
    //: The two agree only while `span <= 2π * ring`; past that the normalise
    //: silently compresses every node into less arc than it occupies. So the
    //: spacing is whichever is larger, which spreads a big map over wider
    //: rings instead of stacking it on top of itself, and is a no-op on any
    //: map small enough that the base spacing was already sufficient.
    //: Measured (WHITEBOARD_PLAN Phase 4, `wbphase4.js`): 30 nodes in radial
    //: gave 6 overlapping pairs, the worst 38x28 board units, and 0 after.
    const ringRadius = Math.max(ring, span / (2 * Math.PI));
    for (const f of flat) {
      const size = sizes.get(f.obj.id) || { w: WB_MAP_NODE_W, h: WB_MAP_NODE_H };
      const angle = ((f.breadth - min) / span) * 2 * Math.PI - Math.PI / 2;
      const radius = f.depth * ringRadius;
      // Centres, then back to the top-left corner an object's `x`/`y` mean.
      positions.set(f.obj.id, {
        x: radius * Math.cos(angle) - size.w / 2,
        y: radius * Math.sin(angle) - size.h / 2,
      });
    }
  } else {
    for (const f of flat) {
      const size = sizes.get(f.obj.id) || { w: WB_MAP_NODE_W, h: WB_MAP_NODE_H };
      const along = offsets[f.depth] || 0;
      positions.set(f.obj.id, vertical
        ? { x: f.breadth - size.w / 2, y: along }
        : { x: along, y: f.breadth - size.h / 2 });
    }
  }

  // Shift the whole layout so the first root keeps the position it already
  // had. "Tidy this map" means tidy it, not "recentre my board", the same
  // choice, for the same reason, `wbArrangeMindMap` makes further up.
  const anchor = positions.get(index.roots[0].id);
  if (anchor) {
    const dx = index.roots[0].x - anchor.x;
    const dy = index.roots[0].y - anchor.y;
    for (const pos of positions.values()) {
      pos.x += dx;
      pos.y += dy;
    }
  }
  return positions;
}

//: Lay the map out and save it: compute everything, paint once, then write.
//:
//: The three phases are the point. `wbMapTidyPositions` touches nothing;
//: `wbApplyBulkMove` moves every element in one pass; `wbSaveBulkMove` is the
//: only part that goes near the network, and it runs after the paint. That is
//: §8's "auto-layout must run off the paint path", and it reuses the two
//: functions a multi-item drag already uses rather than writing a third way to
//: move a set of things.
async function wbMapTidy({ onlyBranch = null, quiet = false } = {}) {
  if (!wbIsMap()) return 0;
  const layout = wbMapLayout();
  if (layout === "free") {
    if (!quiet) toast("This map's layout is Free, pick a layout to tidy it.");
    return 0;
  }
  const index = wbMapIndex();
  const positions = wbMapTidyPositions(index, layout);
  if (!positions.size) return 0;

  // Which nodes this run is allowed to move. A branch tidy (after adding a
  // child) touches only that branch, so the rest of the map does not jump
  // under you while you are typing into a new node.
  const scope = onlyBranch != null
    ? new Set(wbMapSubtree(index, onlyBranch).map((o) => o.id))
    : null;

  const origin = new Map();
  for (const [id, pos] of positions) {
    const obj = index.byId.get(id);
    if (!obj) continue;
    if (scope && !scope.has(id)) continue;
    // **A dragged node is pinned, and a pinned node keeps its place.** That is
    // Coggle's bargain: tidy is on demand, and anything you positioned by hand
    // is a decision, not a thing to be undone by the next tidy. Its children
    // still take their tidy positions, the fold is in the branch, not the
    // whole map.
    if (obj.data?.pinned) continue;
    if (Math.abs(obj.x - pos.x) < 0.5 && Math.abs(obj.y - pos.y) < 0.5) continue;
    origin.set(wbMultiKey("object", id), { kind: "object", id, item: obj, x: pos.x, y: pos.y });
  }
  if (!origin.size) return 0;
  // Zero delta, because each entry already carries its own target, the
  // bulk-move helper adds `dx`/`dy` to the origin it was given, so handing it
  // the destinations and no delta is how one shared helper does a per-node
  // layout as well as a rigid drag.
  wbApplyBulkMove(origin, 0, 0);
  renderWhiteboardNow();
  await wbSaveBulkMove(origin);
  return origin.size;
}

//: Re-tidy one branch after a node was added to it, when the layout asks for
//: it. Silent by design: this runs as part of Tab, and a toast per keystroke
//: while building a map out is noise, not feedback.
async function wbMapTidyBranch(parentId) {
  if (!wbIsMap() || wbMapLayout() === "free") return;
  // Whole-map when a root gained a child: a new top-level branch changes where
  // every other branch has to sit, so tidying only the new one would leave it
  // sitting on top of its neighbour.
  const index = wbMapIndex();
  const parent = parentId != null ? index.byId.get(parentId) : null;
  const scope = parent && parent.parent_id != null ? parent.parent_id : null;
  await wbMapTidy({ onlyBranch: scope, quiet: true });
}

//: The board top bar's map controls: a "Map" chip that says what this board
//: is, the layout picker, and Tidy. All three are hidden on an ordinary
//: whiteboard rather than disabled, a control that can never apply here is
//: not a control you want to read past on every other board.
//:
//: The chip is `.library-chip`, which is the app's own filter-chip recipe
//: (DESIGN.md, "the interactive filter chip"), not a badge invented for the
//: canvas.
//: The whiteboard tools a map has no use for, by the tool name the dock
//: button carries. Freehand, the highlighter, the eraser and the fill paint on
//: a surface a map does not have; the six shapes, the sticky, the free text
//: box and the image place things a tree cannot hold, since everything on a
//: map is a node with a parent. Kept as a set rather than read off the hidden
//: sections, because this also has to answer "was the tool that is *currently*
//: selected one of these" after a board-to-map switch.
const WB_BOARD_ONLY_TOOLS = new Set([
  "draw", "highlighter", "eraser", "bucket",
  "line", "arrow", "rect", "circle", "triangle", "diamond",
  "sticky", "text",
]);

//: Which dock sections a map shows (MINDMAP_PLAN.md §12.0).
//:
//: The owner: "even though it is built off the whiteboard, it isnt the white
//: board and they needs to stay relatively separate with the mindmap having
//: controls specific to it, but the mindmap can keep important and usable
//: parts of the whiteboard." So this is a split, not a second dock: the
//: sections that only make sense on a board are marked in the markup, the
//: map's own sections are marked the other way, and the shared three (move,
//: connect, edit) carry no marker at all and are never touched here.
function wbSyncToolSurfaces(isMap) {
  for (const section of document.querySelectorAll("#wb-tool-group [data-wb-surface]")) {
    section.hidden = section.dataset.wbSurface === (isMap ? "board" : "map");
  }
  // A tool stays selected across a board switch, so opening a map while the
  // pen was active would leave the pen drawing on a surface whose own button
  // is no longer on screen: a mode with no way out, which is the exact shape
  // of bug the hidden sections are meant to prevent.
  if (isMap && WB_BOARD_ONLY_TOOLS.has(window.currentTool)) wbSelectToolRef?.("select");
}

//: The map controls that act on the selection, kept honest about whether
//: there is one.
//:
//: Disabled rather than hidden: a control that vanishes teaches nothing, and
//: what these need to say is "pick a topic first", which the title says while
//: the button is still there to be read. "Add a top-level topic" is never
//: disabled, that is the one that has to work on an empty map.
function wbSyncMapToolState() {
  const node = wbSelectedMapNode();
  const collapse = document.getElementById("wb-map-collapse");
  const colour = document.getElementById("wb-map-branch-color");
  for (const id of ["wb-map-add-child", "wb-map-add-sibling", "wb-map-focus-here"]) {
    const button = document.getElementById(id);
    if (button) button.disabled = !node;
  }
  if (collapse) {
    collapse.disabled = !node;
    const folded = Boolean(node?.data?.collapsed);
    const icon = document.getElementById("wb-map-collapse-icon");
    if (icon) icon.className = `ph ph-caret-circle-${folded ? "right" : "down"}`;
    const label = folded ? "Open the selected branch again (C)" : "Fold the selected branch away (C)";
    collapse.title = label;
    collapse.setAttribute("aria-label", label);
  }
  if (colour) {
    //: **A node carries its colour on its own card, so a trunk can set one
    //: too** (MINDMAP_PLAN.md §12.0, decided after the previous run left the
    //: picker disabled on a root). The earlier reasoning was that a colour
    //: paints only the line coming *into* a node, and a root has no incoming
    //: line: true of the edge, false of the card. `wbPaintMapNode` already
    //: writes `--wb-branch` on every node from the same map `wbMapColors`
    //: returns, and `.wb-map-node` already draws that as the 4px spine down
    //: its leading edge, so a root's own colour was drawn all along and only
    //: the control refused to set it. What stays true is that it does not
    //: *cascade*: the roots' children are the first-level topics and start
    //: the palette over by design (`wbMapColors`'s own comment), which is
    //: Coggle's rule, so a trunk's colour marks the trunk and leaves its
    //: branches their own colours. The title says which of the two it is.
    const index = node ? wbMapIndex() : null;
    const isRoot = Boolean(node) && !(node.parent_id != null && index.byId.has(node.parent_id));
    colour.disabled = !node;
    colour.title = isRoot
      ? "Topic colour: a trunk colours its own card, each branch under it keeps its own"
      : "Branch colour: it carries down to everything under this topic";
    // The colour it is *actually drawn in*, which for most nodes is the one
    // inherited from the branch rather than anything stored on the node: a
    // picker that opens on white over a blue branch is a picker that lies.
    if (node) {
      const effective = wbMapColors(index).get(node.id);
      if (effective && /^#[0-9a-f]{6}$/i.test(effective)) colour.value = effective;
    }
  }
}

//: --- the node edit strip (MINDMAP_PLAN.md §12.1 item 2) ---------------------
//:
//: Coggle's four are text, link, image and icon. Text and icon are here in
//: full; link is a web address on the topic, drawn as a marker that opens it;
//: **image is not built** (it needs the upload path a board image uses, and a
//: node whose body is a picture rather than a label), and
//: `agent-remaining/mindmap.md` carries the next step for it.
//:
//: Size and alignment reuse `font_size` and `align`, which a text box already
//: stores in the same units, rather than inventing a second vocabulary for
//: the same two ideas. Weight and slant are their own booleans rather than
//: `**markdown**` written into the label: §12.0 says styling is per node and
//: in `data`, and a label is already markdown-ish, so a bold *marker* and the
//: emphasis someone typed would be fighting over the same asterisks.

//: A guard, not a convenience. `enhanceSelect` mirrors the real `<select>`
//: into its own opener on the `change` event only, so a value written here
//: without dispatching one leaves the visible control reading the previous
//: node's value. Dispatching it lands in this file's own change handlers,
//: which would then save the value straight back onto the node: this flag is
//: what tells them the change came from the sync rather than from a person.
let wbMapStripSyncing = false;

function wbSyncMapStrip(node) {
  const data = node.data || {};
  wbMapStripSyncing = true;
  try {
    for (const [id, on] of [["wb-map-bold", data.bold], ["wb-map-italic", data.italic]]) {
      const button = document.getElementById(id);
      if (!button) continue;
      button.classList.toggle("active", Boolean(on));
      button.setAttribute("aria-pressed", on ? "true" : "false");
    }
    const setSelect = (id, value) => {
      const el = document.getElementById(id);
      if (!el || el.value === value) return;
      el.value = value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
    };
    //: **M is no stored size at all**, not a number that happens to equal the
    //: stylesheet's. `.wb-map-node` reads at `--text-md`; writing the same
    //: value as a px on the node would pin it there, so a later change to the
    //: type scale would move every map in the app except the nodes somebody
    //: had once set to "medium". The empty option is M for exactly that
    //: reason, and it is also what makes "back to normal" reachable.
    setSelect("wb-map-text-size", data.font_size ? String(data.font_size) : "");
    setSelect("wb-map-align", data.align || "");
    setSelect("wb-map-strip-icon", data.icon || "");
    setSelect("wb-map-shape", data.shape || "");
    const link = document.getElementById("wb-map-strip-link");
    if (link) {
      const has = Boolean(data.link);
      link.classList.toggle("active", has);
      link.title = has ? `Change where this topic points (${data.link})` : "Link this topic to a page";
    }
    const colour = document.getElementById("wb-map-strip-color");
    if (colour) {
      // The colour it is *drawn* in, which for most nodes is inherited from
      // the branch: same rule (and the same reason) as the dock's own picker.
      const effective = wbMapColors(wbMapIndex()).get(node.id);
      if (effective && /^#[0-9a-f]{6}$/i.test(effective)) colour.value = effective;
    }
  } finally {
    wbMapStripSyncing = false;
  }
}

//: The size the text grip starts from when a node has never been sized, and
//: the bounds it may drag between (§12.1 item 6). Measured rather than
//: assumed: `.wb-map-node` reads at `--text-md`, which computes to 13.6px at
//: the default root size, so 14 is that rounded to a whole pixel. The strip's
//: own "M" stores nothing at all instead, see `wbSyncMapStrip`.
const WB_MAP_TEXT_DEFAULT = 14;
const WB_MAP_TEXT_MIN = 10;
const WB_MAP_TEXT_MAX = 44;

//: One write path for everything the strip and the radial set. Saves, repaints
//: the node it changed (not the board: a bold toggle is not worth re-binding
//: every card and sketch, the "glitchy and slow to update" report this file
//: already carries) and re-places the strip, whose width changes with what it
//: now says.
async function wbMapSetNodeStyle(node, patch) {
  if (!node) return;
  node.data = { ...node.data, ...patch };
  const el = document.querySelector(`.wb-object[data-id="${node.id}"]`);
  if (el) wbPaintMapNodeStyle(el, node);
  await wbSaveObject(node);
  wbUpdateSelectionBar();
}

//: --- the node radial (MINDMAP_PLAN.md §12.1 item 3) ------------------------
//:
//: Coggle's idiom, and the reason §12.1 exists: the controls appear on the
//: thing you picked. Opened by the same two gestures the board's own context
//: menu uses (`wbOpenContextMenuFor` hands a map node here), so right-click
//: and touch-and-hold both reach it without a second gesture to learn.
//:
//: Eight slots, in the markup's own order, clockwise from the top. The ring
//: is not a menu in the ARIA sense and does not claim to be one: a menu is a
//: list you walk with the arrows, this is a toolbar arranged in a circle, and
//: `role="toolbar"` is what a screen reader can do something useful with.
//: (It is also why this adds no hand-built `role="menu"`, which
//: `tests/test_ui_recipes.py` counts.)

//: The node the open ring belongs to. Read at click time by every slot, so a
//: ring left open across a render acts on the node it was opened for rather
//: than on whatever is selected now.
let wbMapRadialFor = null;

//: **Show the ring at a point, then slide it back inside the window.**
//: Both rings are placed from a point with nothing between them and the edge
//: of the screen: the node ring from the node's own centre, the link ring
//: from the pointer. A map grows outward, so its newest topics are exactly
//: the ones nearest an edge, and a ring around one of those lost two or
//: three of its eight slots off-screen: the control was least reachable
//: where it was most needed.
//:
//: **Why the whole ring moves, rather than the slots being rotated or
//: reflected into the room that is left.** A ring of eight slots at 45
//: degrees is its own reflection in both axes and its own rotation by any
//: multiple of 45, so neither of those changes which directions are covered:
//: whatever angle the ring is turned through, some slot still points at the
//: nearest edge, and at 22.5 degrees (the most any rotation can buy) a slot
//: aimed at the left edge still reaches 68 * cos 22.5 = 63px of the 82px it
//: needs. Turning the ring also moves every slot away from the position the
//: person learned it at, to buy 19px. Sliding the whole ring keeps all eight
//: in their own places and in their own order, and a shift is bounded by the
//: ring's own reach (82px), which is less than a topic is wide: the ring
//: still reads as belonging to the node it came from.
//:
//: Measured after the ring is shown, not before, which is the ordering
//: `placeEscapedMenu` in app.js paid for: a rect read inside a
//: `display: none` ancestor is all zeroes, and zeroes here would produce a
//: confident shift from nothing. Measured off the slots rather than off the
//: ring, for the same reason from the other direction: the ring's own box is
//: deliberately `width: 0; height: 0` so that it cannot cover the node it
//: surrounds, so its rect says nothing about where its slots are. The union
//: of the slots is the honest answer, and it stays honest if the radius, the
//: slot size or the number of slots ever changes.
function wbPlaceMapRadial(ring, host, x, y, clear) {
  const margin = 8;
  ring.style.left = `${Math.round(x)}px`;
  ring.style.top = `${Math.round(y)}px`;
  ring.style.removeProperty("--wb-radial-r");
  ring.classList.remove("hidden");
  const hostRect = host.getBoundingClientRect();
  if (!hostRect.width || !hostRect.height) return;
  wbSizeMapRadial(ring, hostRect, clear);
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (const slot of ring.children) {
    const box = slot.getBoundingClientRect();
    if (!box.width && !box.height) continue;
    left = Math.min(left, box.left);
    top = Math.min(top, box.top);
    right = Math.max(right, box.right);
    bottom = Math.max(bottom, box.bottom);
  }
  if (!Number.isFinite(left)) return;
  //: The window, cut down to the canvas, and then cut down again by the two
  //: panels that float *over* the canvas: on screen is not the same as
  //: reachable. Measured at 1440x900: the host starts at y=128 and the map's
  //: top bar covers 136 to 182 of it, so a trunk near the top of a map (the
  //: common case, that is where a map starts) would have had its upper slots
  //: placed under the bar, which takes the click.
  //:
  //: A panel counts against an edge only when it is a *band* across the
  //: canvas, more than half the host's width for a top or bottom bar and
  //: more than half its height for a side one, because both of these panels
  //: are draggable and one parked in the middle of the board is something to
  //: place a ring beside, not a wall to stay out of. The same rule then
  //: handles the tool panel's own "dock as a sidebar" state without knowing
  //: it exists.
  let loX = Math.max(margin, hostRect.left + margin);
  let hiX = Math.min(window.innerWidth - margin, hostRect.right - margin);
  let loY = Math.max(margin, hostRect.top + margin);
  let hiY = Math.min(window.innerHeight - margin, hostRect.bottom - margin);
  for (const id of ["wb-topbar", "wb-tools-panel"]) {
    const panel = document.getElementById(id);
    if (!panel || panel.hidden || panel.classList.contains("hidden")) continue;
    const bar = panel.getBoundingClientRect();
    if (!bar.width || !bar.height) continue;
    const midY = hostRect.top + hostRect.height / 2;
    const midX = hostRect.left + hostRect.width / 2;
    if (bar.width > hostRect.width / 2) {
      if (bar.bottom < midY) loY = Math.max(loY, bar.bottom + margin);
      else if (bar.top > midY) hiY = Math.min(hiY, bar.top - margin);
    }
    if (bar.height > hostRect.height / 2) {
      if (bar.right < midX) loX = Math.max(loX, bar.right + margin);
      else if (bar.left > midX) hiX = Math.min(hiX, bar.left - margin);
    }
  }
  //: Right edge first and left edge second, so that on a canvas narrower
  //: than the ring (which no real viewport is, 164px against 390, but a
  //: split pane could be) the ring is pinned to the edge a reader starts
  //: from rather than half off both sides.
  let dx = 0, dy = 0;
  if (right > hiX) dx = hiX - right;
  if (left + dx < loX) dx = loX - left;
  if (bottom > hiY) dy = hiY - bottom;
  if (top + dy < loY) dy = loY - top;
  if (dx) ring.style.left = `${Math.round(x + dx)}px`;
  if (dy) ring.style.top = `${Math.round(y + dy)}px`;
}

//: **Push the ring clear of the node's own box, not of its centre.**
//:
//: The ring was built at a fixed 4.25rem, which is a circle of radius 68 drawn
//: around the node's centre. A default topic measures 200 by 44 on screen, so
//: the east and west slots landed 36px *inside* the box, over the node's text
//: and over its own chevron, and the four diagonals cleared it by 12px. That
//: is the report ("fix the look of the mindmap item radial"): the maths was
//: right and the reading was wrong, because a ring centred on a node covers
//: the node whenever the node is wider than the ring is round.
//:
//: So the radius is raised per node to the one that clears its measured box:
//: half the node's larger side, plus half a slot, plus the same 8px margin
//: this function already keeps against every edge. The slots stay on one
//: circle (`mapstrip.js` asserts a spread of 2px or less), the ring stays
//: centred on the node it belongs to, and nothing about the order or the
//: directions moves, so a person who learned where Tidy sits still finds it
//: there.
//:
//: Two caps, because a radius taken from a box has no upper bound of its own:
//: the ring may not grow past 2.5 times its base, beyond which it reads as a
//: hoop on the canvas rather than as this node's controls (a topic resized
//: past ~300px wide keeps its slots on its own margin instead, which is empty
//: on a node that large), and it may not grow past what the canvas can hold.
//:
//: Every number here is measured, not assumed: the base radius and the slot
//: size are read back off the live ring (the ring's own box is a zero-sized
//: point at its anchor, so a slot centre minus that point *is* the radius),
//: which is why this runs after the ring is shown and why a change to the
//: stylesheet's radius or slot size needs no edit here.
function wbSizeMapRadial(ring, hostRect, clear) {
  if (!clear || !(clear.w > 0) || !(clear.h > 0)) return;
  const slot = ring.querySelector(".wb-map-radial-slot");
  if (!slot) return;
  const box = slot.getBoundingClientRect();
  if (!box.width) return;
  const origin = ring.getBoundingClientRect();
  const base = Math.hypot(box.left + box.width / 2 - origin.left,
    box.top + box.height / 2 - origin.top);
  if (!base) return;
  const want = Math.max(clear.w, clear.h) / 2 + box.width / 2 + 8;
  const fits = Math.min(hostRect.width, hostRect.height) / 2 - box.width / 2 - 8;
  const r = Math.min(want, base * 2.5, Math.max(base, fits));
  if (r > base + 1) ring.style.setProperty("--wb-radial-r", `${Math.round(r)}px`);
}

//: How far an open ring pokes past the node it surrounds, top and bottom, in
//: the coordinates `wbUpdateSelectionBar` places the strip in. A ring wide
//: enough to clear a 200px topic reaches 136px from its centre, which is over
//: the strip the same node already has above it: measured before this, two of
//: the eight slots were drawn on the strip's own selects. The strip stands off
//: the ring rather than off the node while the ring is open, and goes back
//: when it closes. Measured off the slots, not off the ring's box, which is a
//: zero-sized point (`wbPlaceMapRadial`), and off the live ring rather than
//: from the radius, so a ring the clamp has slid reports where it actually is.
function wbMapRadialOverhang(hostRect, top, bottom) {
  const none = { above: 0, below: 0 };
  const ring = document.getElementById("wb-map-radial");
  if (!ring || ring.classList.contains("hidden")) return none;
  let minTop = Infinity, maxBottom = -Infinity;
  for (const slot of ring.children) {
    const r = slot.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    minTop = Math.min(minTop, r.top);
    maxBottom = Math.max(maxBottom, r.bottom);
  }
  if (!Number.isFinite(minTop)) return none;
  const above = hostRect.top + top - minTop;
  const below = maxBottom - (hostRect.top + bottom);
  return { above: above > 0 ? above + 8 : 0, below: below > 0 ? below + 8 : 0 };
}

//: The node whose ring is open wears a class while it is open, because two of
//: its own hover controls (add a branch, add a topic beside) are two of the
//: ring's eight slots and sit inside the ring's circle. Two buttons for one
//: action, one of them under the ring, is the clutter the report was about.
function wbMarkMapRadialNode(id) {
  for (const el of document.querySelectorAll(".wb-object.wb-radial-open")) {
    el.classList.remove("wb-radial-open");
  }
  if (id == null) return;
  document.querySelector(`.wb-object[data-id="${id}"]`)?.classList.add("wb-radial-open");
}

function wbCloseMapRadial() {
  const ring = document.getElementById("wb-map-radial");
  if (!ring || ring.classList.contains("hidden")) return;
  ring.classList.add("hidden");
  wbMapRadialFor = null;
  wbSyncMapRadialAlt(false);
  wbMarkMapRadialNode(null);
  wbUpdateSelectionBar();
}

//: Alt held turns the two add slots into the two remove slots (Coggle). The
//: swap is drawn, not just honoured: a modifier that changes what a button
//: does without saying so is the "secret" this file's own space-pan comment
//: warns about.
function wbSyncMapRadialAlt(alt) {
  const pairs = [
    ["wb-radial-child", alt
      ? ["ph-trash", "Remove this branch: this topic and everything under it"]
      : ["ph-arrow-elbow-down-right", "Add a branch off this topic (Tab). Hold Alt to remove the branch instead"]],
    ["wb-radial-sibling", alt
      ? ["ph-minus-circle", "Remove this topic only: its branches move up to its parent"]
      : ["ph-arrow-down", "Add a topic beside this one (Enter). Hold Alt to remove this topic and keep its branch"]],
  ];
  for (const [id, [icon, title]] of pairs) {
    const button = document.getElementById(id);
    if (!button) continue;
    button.classList.toggle("wb-map-radial-danger", alt);
    button.title = title;
    button.setAttribute("aria-label", title.split(".")[0]);
    const glyph = button.querySelector("i");
    if (glyph) glyph.className = `ph ${icon}`;
  }
}

function wbOpenMapRadial(node) {
  const ring = document.getElementById("wb-map-radial");
  const container = document.getElementById("whiteboard-container");
  const host = document.getElementById("library-view-whiteboard");
  if (!ring || !container || !host || !node) return false;
  const box = wbItemBBox("object", node);
  if (!box) return false;
  // The node's centre in the view's own coordinates, through the live zoom
  // transform: the same route `wbUpdateSelectionBar` takes, because a ring
  // placed from the pointer instead would sit off-centre on every node whose
  // edge you happened to right-click.
  const t = d3.zoomTransform(container);
  const rect = container.getBoundingClientRect();
  const hostRect = host.getBoundingClientRect();
  const cx = rect.left - hostRect.left + t.applyX((box.minX + box.maxX) / 2);
  const cy = rect.top - hostRect.top + t.applyY((box.minY + box.maxY) / 2);
  wbMapRadialFor = node.id;
  //: The node's box on screen, not on the board: the slots are a fixed size in
  //: px whatever the zoom, so what the ring has to clear is what the node
  //: measures at the zoom in force.
  wbPlaceMapRadial(ring, host, cx, cy, {
    w: (box.maxX - box.minX) * t.k,
    h: (box.maxY - box.minY) * t.k,
  });
  wbSyncMapRadialAlt(false);
  const collapse = document.getElementById("wb-radial-collapse");
  if (collapse) {
    const folded = Boolean(node.data?.collapsed);
    const label = folded ? "Open this branch again (C)" : "Fold this branch away (C)";
    collapse.title = label;
    collapse.setAttribute("aria-label", label);
    const glyph = collapse.querySelector("i");
    if (glyph) glyph.className = `ph ph-caret-circle-${folded ? "right" : "down"}`;
  }
  const sever = document.getElementById("wb-radial-sever");
  // A trunk has no parent to be cut from, and a slot that cannot act says so
  // rather than doing nothing (the same rule the dock's own controls follow).
  if (sever) {
    const rooted = node.parent_id == null || !wbMapIndex().byId.has(node.parent_id);
    sever.disabled = rooted;
    sever.title = rooted
      ? "This topic is already a trunk of its own"
      : "Cut this topic free of its parent, as a trunk of its own";
  }
  wbMarkMapRadialNode(node.id);
  wbUpdateSelectionBar();
  return true;
}

//: The node an open ring acts on, or null. Every slot goes through this so a
//: ring whose node has since been deleted closes instead of throwing.
function wbMapRadialNode() {
  if (wbMapRadialFor == null) return null;
  const node = (wbState.objects || []).find((o) => o.id === wbMapRadialFor);
  if (!node || !WB_MAP_KINDS.has(node.kind)) {
    wbCloseMapRadial();
    return null;
  }
  return node;
}

//: Copy a branch: this topic and everything under it, as a sibling of itself.
//:
//: Built from the node endpoint rather than from the board's copy/paste,
//: which works on a flat selection and would paste ten unrelated boxes where
//: a branch was. Parents before children (`wbMapSubtree` returns them in that
//: order), so every child's new parent already exists by the time it is
//: created: an old id maps to a new one exactly once.
async function wbMapCopyBranch(id) {
  const index = wbMapIndex();
  const source = index.byId.get(id);
  if (!source) return;
  const subtree = wbMapSubtree(index, id);
  if (subtree.length > WB_MAP_COPY_MAX) {
    toast(`That branch has ${subtree.length} topics: copying stops at ${WB_MAP_COPY_MAX}.`, true);
    return;
  }
  const mapped = new Map();
  for (const node of subtree) {
    const parentId = node.id === id
      ? (index.byId.has(node.parent_id) ? node.parent_id : null)
      : mapped.get(node.parent_id);
    // A child whose parent failed to copy has nowhere to go: stop rather than
    // scattering the rest of the branch at the top level.
    if (node.id !== id && parentId == null) break;
    const created = await wbMapCreateNode({
      parentId: parentId ?? null,
      kind: node.kind,
      text: wbMapLabel(node),
      refId: node.data?.ref_id ?? null,
    });
    if (!created) break;
    // The copy looks like the original: the styling lives in `data` and the
    // create endpoint only takes a label, so it is written straight after.
    const style = {};
    for (const key of WB_MAP_STYLE_KEYS) {
      if (node.data?.[key] != null) style[key] = node.data[key];
    }
    if (Object.keys(style).length) {
      created.data = { ...created.data, ...style };
      await wbSaveObject(created);
    }
    mapped.set(node.id, created.id);
  }
  await wbMapTidy({ quiet: true });
  renderWhiteboardNow();
  const rootCopy = mapped.get(id);
  if (rootCopy) selectWbItem("object", rootCopy);
  toast(`Copied ${mapped.size} topic${mapped.size === 1 ? "" : "s"}.`);
}

//: A branch big enough that copying it is a mistake rather than an intention.
//: One POST per node (there is no bulk create), so a thousand-node branch
//: would be a thousand requests: the same shape `wbSaveBulkMove` already
//: pays for, and the reason a cap is kinder than a progress bar here.
const WB_MAP_COPY_MAX = 120;

//: Everything the strip and the radial can set on a node, in one list, so a
//: copy carries what the original wore and "reset to the branch" clears
//: exactly the same set. A key added to one and not the other is how a copy
//: quietly loses its colour.
const WB_MAP_STYLE_KEYS = [
  "color", "bold", "italic", "font_size", "align", "icon", "link", "edge_label",
  "shape",
];

//: Remove this topic and keep its branch: the children move up to its parent
//: first, then the node goes. Through `/move`, which is the only endpoint
//: that runs the cycle check (`wbMapOutdent`'s own comment), and children
//: first so a failure leaves the branch attached to something rather than
//: orphaned under a node that no longer exists.
async function wbMapRemoveKeepingBranch(id) {
  const boardId = window.currentBoardId;
  const index = wbMapIndex();
  const node = index.byId.get(id);
  if (!boardId || !node) return;
  const children = index.childrenOf.get(id) || [];
  // The last-topic rule, at this door too: removing the only topic on the map
  // empties it, and §12.0 says a map is never empty.
  if (!children.length && wbMapDeleteEmptiesMap(id)) {
    wbMapRefuseLastTopic();
    return;
  }
  const parentId = index.byId.has(node.parent_id) ? node.parent_id : null;
  try {
    for (const child of children) {
      const moved = await apiJson(`/whiteboard/boards/${boardId}/nodes/${child.id}/move`, {
        method: "PUT",
        body: JSON.stringify({ parent_id: parentId }),
      });
      Object.assign(child, moved);
    }
  } catch (err) {
    toast(err.message || "Couldn't move that branch up.", true);
    return;
  }
  await wbMapDeleteSubtree(id);
  await wbMapTidyBranch(parentId);
}

//: Sever (§12.1 item 9): cut a topic free of its parent so it becomes a trunk
//: of its own, branch and all. `parent_id: null` is a move the endpoint
//: already supports; floating topics are allowed by §12.0 ("multiple roots
//: are allowed"), so this needs no new rule, only a way to ask for it.
async function wbMapSever(id) {
  const boardId = window.currentBoardId;
  const index = wbMapIndex();
  const node = index.byId.get(id);
  if (!boardId || !node) return;
  if (node.parent_id == null || !index.byId.has(node.parent_id)) {
    toast("This topic is already a trunk of its own.");
    return;
  }
  const oldParent = node.parent_id;
  try {
    const moved = await apiJson(`/whiteboard/boards/${boardId}/nodes/${id}/move`, {
      method: "PUT",
      body: JSON.stringify({ parent_id: null }),
    });
    Object.assign(node, moved);
  } catch (err) {
    toast(err.message || "Couldn't cut that topic free.", true);
    return;
  }
  // A severed topic keeps the colour it had as part of the branch it left,
  // which would be a lie about where it belongs: it is its own trunk now, so
  // it starts the palette again like every other trunk's children do.
  if (node.data?.color) await wbMapSetNodeStyle(node, { color: null });
  await wbMapTidyBranch(oldParent);
  renderWhiteboardNow();
  toastAction("Cut free as its own trunk.", "Put it back", async () => {
    try {
      const back = await apiJson(`/whiteboard/boards/${boardId}/nodes/${id}/move`, {
        method: "PUT",
        body: JSON.stringify({ parent_id: oldParent }),
      });
      Object.assign(node, back);
      await wbMapTidyBranch(oldParent);
      renderWhiteboardNow();
    } catch (err) {
      toast(err.message || "Couldn't put it back.", true);
    }
  });
}

//: What the line into a topic says. Stored on the child, which is the end of
//: a tree edge that has exactly one of them (see the schema's own comment),
//: and drawn by `wbRenderMapEdges`.
async function wbMapLabelEdge(id) {
  const index = wbMapIndex();
  const node = index.byId.get(id);
  if (!node) return;
  if (!index.byId.has(node.parent_id)) {
    toast("A trunk has no line into it to label.");
    return;
  }
  const current = node.data?.edge_label || "";
  const answer = await promptDialog(
    "What does the line into this topic say?",
    current,
    { confirmLabel: current ? "Change the label" : "Add the label" }
  );
  const text = String(answer ?? "").trim();
  // Same rule as the strip's link: `promptDialog` cannot tell Escape from an
  // empty field, so an empty answer changes nothing. Clearing a label is
  // "Back to the branch" on this same ring.
  if (!text) return;
  await wbMapSetNodeStyle(node, { edge_label: text.slice(0, 80) });
  renderWhiteboardNow();
}

//: "Back to the branch" (§12.0: "'Reset to branch' on any node"). Drops every
//: key the strip and the radial can set, in one list rather than one button
//: per property, which is what makes it usable as the way out of a node you
//: have over-decorated.
async function wbMapResetToBranch(id) {
  const node = (wbState.objects || []).find((o) => o.id === id);
  if (!node) return;
  const patch = {};
  for (const key of WB_MAP_STYLE_KEYS) patch[key] = null;
  await wbMapSetNodeStyle(node, patch);
  renderWhiteboardNow();
  toast("Back to the branch's own look.");
}

//: --- the link radial (MINDMAP_PLAN.md §12.1 item 4) -------------------------
//:
//: The same ring, on the line rather than on the topic. Every slot writes to
//: the **child**, because a tree edge has no row of its own: it is
//: `parent_id`, and the child is the end of it with exactly one incoming line.
//:
//: **Coggle's plain left-click on a line opens the colour wheel alone, and
//: that is deliberately not copied.** A left-click on this canvas is how you
//: clear a selection, and a tree edge is a 2px line inside a 16px target: a
//: near-miss would open a colour picker you did not ask for, on a branch you
//: were only trying to click past. The ring is the same gesture as the node's
//: (right-click, or hold on a touch screen), which is one gesture to learn
//: rather than two, and the colour well is a slot inside it.
let wbMapLinkRadialFor = null;

function wbCloseMapLinkRadial() {
  const ring = document.getElementById("wb-map-link-radial");
  if (!ring || ring.classList.contains("hidden")) return;
  ring.classList.add("hidden");
  wbMapLinkRadialFor = null;
}

//: The gestures on one edge's hit stroke. Bound at creation rather than
//: delegated: the edge group is replaced wholesale on every render
//: (`wbRenderMapEdges`'s own comment says why), so there is exactly one
//: binding per element per lifetime and nothing to clean up.
function wbWireMapEdgeGestures(hit, childId) {
  let holdTimer = null;
  const cancelHold = () => {
    if (holdTimer) clearTimeout(holdTimer);
    holdTimer = null;
  };
  hit.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
    wbOpenMapLinkRadial(childId, event.clientX, event.clientY);
  });
  // Touch has no right-click, so a hold stands in, with the same 500ms and
  // the same cancel-on-move shape the node's own menu gesture uses.
  hit.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch") return;
    cancelHold();
    holdTimer = setTimeout(() => {
      holdTimer = null;
      wbOpenMapLinkRadial(childId, event.clientX, event.clientY);
    }, 500);
  });
  for (const name of ["pointerup", "pointercancel", "pointermove"]) {
    hit.addEventListener(name, cancelHold);
  }
}

function wbOpenMapLinkRadial(childId, clientX, clientY) {
  const ring = document.getElementById("wb-map-link-radial");
  const host = document.getElementById("library-view-whiteboard");
  const index = wbMapIndex();
  const child = index.byId.get(childId);
  if (!ring || !host || !child) return;
  wbCloseContextMenu();
  wbCloseMapRadial();
  // At the pointer, not at the line's middle: a branch edge can be hundreds of
  // pixels long and a ring that jumped to its midpoint would open somewhere
  // you were not looking.
  const hostRect = host.getBoundingClientRect();
  wbMapLinkRadialFor = childId;
  wbPlaceMapRadial(ring, host, clientX - hostRect.left, clientY - hostRect.top);
  wbSyncMapLinkRadial(child, index);
}

function wbSyncMapLinkRadial(child, index) {
  const style = child.data?.edge_style || "curve";
  for (const [id, name] of [
    ["wb-link-curve", "curve"], ["wb-link-elbow", "elbow"], ["wb-link-straight", "straight"],
  ]) {
    document.getElementById(id)?.classList.toggle("active", style === name);
  }
  const dashed = document.getElementById("wb-link-dashed");
  if (dashed) {
    const on = Boolean(child.data?.edge_dashed);
    dashed.classList.toggle("active", on);
    dashed.setAttribute("aria-pressed", on ? "true" : "false");
    dashed.title = on ? "Draw this line solid again" : "Dash this line";
  }
  const colour = document.getElementById("wb-link-color");
  if (colour) {
    // What the line is *drawn* in, which is the branch's colour unless this
    // node carries its own: the same rule the dock and the strip follow.
    const effective = wbMapColors(index).get(child.id);
    if (effective && /^#[0-9a-f]{6}$/i.test(effective)) colour.value = effective;
  }
  const reverse = document.getElementById("wb-link-reverse");
  if (reverse) {
    // Turning a line around makes the parent a child of the child. If the
    // parent is a trunk that is a clean swap; it is never possible for a line
    // that is not there, which is the only case worth refusing.
    const parent = index.byId.get(child.parent_id);
    reverse.disabled = !parent;
  }
}

//: Turn a line around: the topic below becomes the one above.
//:
//: Two moves, in this order, and the order is the whole of it. Moving the
//: parent under the child while the child is still under the parent is
//: exactly the ring `/move`'s cycle check refuses, so the child is lifted to
//: the parent's own parent first: after that neither is a descendant of the
//: other and the second move is an ordinary re-parent.
async function wbMapReverseEdge(childId) {
  const boardId = window.currentBoardId;
  const index = wbMapIndex();
  const child = index.byId.get(childId);
  const parent = child ? index.byId.get(child.parent_id) : null;
  if (!boardId || !child || !parent) return;
  const grandparent = index.byId.has(parent.parent_id) ? parent.parent_id : null;
  const move = (id, parentId) => apiJson(
    `/whiteboard/boards/${boardId}/nodes/${id}/move`,
    { method: "PUT", body: JSON.stringify({ parent_id: parentId }) }
  );
  try {
    Object.assign(child, await move(child.id, grandparent));
    Object.assign(parent, await move(parent.id, child.id));
  } catch (err) {
    toast(err.message || "Couldn't turn that line around.", true);
    return;
  }
  await wbMapTidy({ quiet: true });
  renderWhiteboardNow();
  toast("Turned the line around.");
}

function wbSyncMapChrome() {
  const isMap = wbIsMap();
  wbSyncToolSurfaces(isMap);
  wbSyncMapToolState();
  // A map that grows downward puts the branch spine on the node's top edge and
  // its chevron underneath: decided once here as a class on the view rather
  // than per node, since it is a property of the layout, not of any one node.
  document.getElementById("library-view-whiteboard")
    ?.classList.toggle("wb-map-down", isMap && wbMapLayout() === "tree-down");
  //: The switch says what it will do, not what the board is: a button whose
  //: label is the current state reads as a toggle that is already on, and this
  //: one changes the board rather than reporting it.
  const kind = document.getElementById("wb-board-kind-label");
  if (kind) kind.textContent = isMap ? "Turn into a whiteboard" : "Turn into a mind map";
  const chip = document.getElementById("wb-map-chip");
  const picker = document.getElementById("wb-map-layout");
  const tidy = document.getElementById("wb-map-tidy");
  if (chip) chip.hidden = !isMap;
  if (tidy) tidy.hidden = !isMap;
  if (picker) {
    picker.hidden = !isMap;
    picker.value = wbMapLayout();
  }
  //: Phase 5's own chrome. All of it is a *view* of the map, so it is synced
  //: from the same place the layout picker is rather than from wherever each
  //: happened to be changed: the failure this avoids is a control that reports
  //: a state the canvas disagrees with.
  const perspective = document.getElementById("wb-map-perspective");
  if (perspective) {
    perspective.value = wbMapPerspective();
    const row = perspective.closest(".wb-menu-row");
    if (row) row.hidden = !isMap;
  }
  const statsRow = document.getElementById("wb-map-stats-item");
  if (statsRow) statsRow.hidden = !isMap;
  const expandRow = document.getElementById("wb-map-expand-all");
  if (expandRow) expandRow.hidden = !isMap;
  if (!isMap && wbMapFocusState) wbMapFocusState = null;
  wbSyncMapViews();
}

//: Change the layout, then lay the map out in it. Changing a layout without
//: applying it would leave the picker saying "tree-down" over a map still
//: arranged sideways, which is a control that reports a state the screen
//: disagrees with: the shape of bug this app has been bitten by repeatedly.
async function wbMapSetLayout(layout) {
  const boardId = window.currentBoardId;
  if (!boardId || !wbIsMap()) return;
  try {
    await apiJson(`/whiteboard/boards/${boardId}`, {
      method: "PUT",
      body: JSON.stringify({ layout }),
    });
    window.wbMapState = { ...window.wbMapState, layout };
    wbSyncMapChrome();
    const moved = await wbMapTidy({ quiet: true });
    renderWhiteboardNow();
    toast(layout === "free"
      ? "Layout set to Free, nodes stay where you put them."
      : `Laid out ${moved} node${moved === 1 ? "" : "s"}.`);
  } catch (err) {
    toast(err.message || "Couldn't change the layout.", true);
  }
}

//: **Dragging a node pins it.** The other half of the tidy bargain above: a
//: position you chose by hand is a decision, and the next Tidy has to leave it
//: alone or the gesture is pointless. Called from the object drag's own end
//: handler, and only for a real move on a map, a click that happened to
//: register as a zero-length drag must not silently pin anything.
async function wbMapPinOnDrag(d) {
  if (!wbIsMap() || !WB_MAP_KINDS.has(d.kind) || d.data?.pinned) return;
  d.data = { ...d.data, pinned: true };
  await wbSaveObject(d);
  wbScheduleRender();
}

function wbApplySelectionHighlight() {
  document
    .querySelectorAll(".sketch-group.wb-selected, .node-card.wb-selected, .wb-object.wb-selected")
    .forEach((el) => el.classList.remove("wb-selected"));
  // A sketch's resize handles have nowhere else to live between renders
  // (unlike a card/object, which always has 8 handle children of its own), 
  // recomputed here so they track a fresh selection or a just-finished move.
  // Only for the single-item selection, a multi-selection has no one
  // bounding box to hang 8 handles off, and resizing a set isn't built.
  wbRenderSketchHandles();
  wbUpdateContextBar();
  // The map dock's own buttons act on the selected topic, so they follow the
  // selection for the same reason the properties panel above does.
  wbSyncMapToolState();
  for (const key of wbMultiSelection) {
    const sep = key.indexOf(":");
    const kind = key.slice(0, sep), id = Number(key.slice(sep + 1));
    document.querySelector(WB_SELECTOR_BY_KIND[kind](id))?.classList.add("wb-selected");
  }
  if (!wbSelectedItem) return;
  const selector = WB_SELECTOR_BY_KIND[wbSelectedItem.kind](wbSelectedItem.id);
  document.querySelector(selector)?.classList.add("wb-selected");
}

function selectWbItem(kind, id) {
  wbSelectedItem = { kind, id };
  wbApplySelectionHighlight();
  //: **The chrome that depends on the selection, updated where the selection
  //: changes.** Both of these used to wait for the next render or the next
  //: pan frame, which is why the map dock's own controls were re-synced by
  //: hand at half a dozen call sites and why the node edit strip would
  //: otherwise appear a frame late (or not at all, for a selection made
  //: without a render behind it: `wbHandleItemClick` ends here and renders
  //: nothing). One call site rather than every caller remembering two.
  wbSyncMapToolState();
  wbUpdateSelectionBar();
}

//: Select everything on the board (Edit → Select all, Ctrl+A on the
//: canvas). Links are left out: they follow what they join.
function wbSelectAllItems() {
  wbSelectedItem = null;
  wbMultiSelection.clear();
  for (const [kind, item] of wbLinkCandidates()) wbMultiSelection.add(wbMultiKey(kind, item.id));
  wbApplySelectionHighlight();
  wbUpdateContextBar();
  wbUpdateSelectionBar();
}

function clearWbSelection() {
  if (!wbSelectedItem && wbMultiSelection.size === 0) return;
  wbSelectedItem = null;
  wbMultiSelection.clear();
  wbApplySelectionHighlight();
  wbSyncMapToolState();
  wbUpdateSelectionBar();
}

//: **Where the context bar goes.** Above the selection, in the view's own
//: coordinates, from the item's board bbox through the live zoom transform,
//: re-placed on every render and every pan/zoom frame. What it *contains* is
//: `wbUpdateContextBar`'s job; this only decides the two numbers.
//:
//: One more case than the bar it replaced: with nothing selected and a
//: drawing tool held, the bar carries that tool's own settings and has no
//: selection to sit above, so it sits centred just over the tool rail, which
//: is where the thing it is about is. Excalidraw and tldraw both park the
//: style panel against the rail for the same reason.
function wbUpdateSelectionBar() {
  const bar = document.getElementById("wb-context");
  if (!bar) return;
  const sel = wbSelectedItem;
  // `> 0`, not `> 1`: `wbUpdateContextBar` fills the bar for a selection of
  // one shift-clicked item and this hid it again, so that selection had an
  // arrange row nobody could see. `wbSelectionBounds` is happy with one.
  const multi = wbMultiSelection.size > 0;
  const container = document.getElementById("whiteboard-container");
  const host = document.getElementById("library-view-whiteboard");
  //: **A map node gets the map's own strip, in the board bar's place**
  //: (MINDMAP_PLAN.md §12.1 item 2). One bar above a node, never two: two
  //: absolutely-positioned bars computed from the same box is exactly how
  //: they come to overlap, and this file has already paid for that twice
  //: (see `.wb-map-count`). The board's bar offers duplicate, copy style and
  //: the z-order pair, none of which a topic in a tree has a use for, and
  //: the strip offers how the topic reads and what it points at, which is
  //: what the whiteboard has no equivalent of. Everything below places
  //: whichever of the two this selection earns; `other` is hidden every time
  //: so switching between a card and a topic cannot leave one behind.
  const strip = document.getElementById("wb-map-strip");
  const mapNode = wbMultiSelection.size > 1 ? null : wbSelectedMapNode();
  const active = mapNode ? strip : bar;
  const hideBoth = () => {
    bar.classList.add("hidden");
    strip?.classList.add("hidden");
    delete bar.dataset.wbAnchor;
  };
  if (!container || !host || wbLinkDragActive || !active) {
    hideBoth();
    return;
  }
  if (!sel && !multi) {
    // Nothing selected. The bar may still be open on a held drawing tool, in
    // which case it is anchored to the rail and `wbUpdateContextBar` placed
    // it; leave it exactly where it is. This branch is the hot one: it runs on
    // every frame of every pan, which is why it does no work and asks no
    // question the DOM has to be walked to answer.
    if (bar.dataset.wbAnchor === "rail") {
      strip?.classList.add("hidden");
      return;
    }
    hideBoth();
    return;
  }
  delete bar.dataset.wbAnchor;
  // **The document-wide query runs last, not first.** This function is called
  // from the pan/zoom frame (`handleWbZoom`), so it runs at up to 60 Hz while
  // someone drags the canvas, and `querySelector(".wb-object.wb-text-editing")`
  // walks the whole document every time even though nothing is selected, which
  // is the common case during a pan. Measured on a 201-node map, 60 frames of
  // a drag pan: 0.46ms per call before this reorder against 0.013ms for the
  // grid sync and 0.02ms for the navigator beside it. The four checks above
  // are all constant-time and one of them is true whenever nothing is
  // selected, so putting them first skips the walk entirely.
  if (document.querySelector(".wb-object.wb-text-editing")) {
    hideBoth();
    return;
  }
  // A multi-selection gets the bar above the whole group, that is where
  // Arrange's align/distribute and Export "just the selection" matter.
  let box = null;
  if (multi) {
    const b = wbSelectionBounds();
    if (b) box = { minX: b.minX, minY: b.minY, maxX: b.minX + b.width, maxY: b.minY + b.height };
  } else {
    const item = (wbState[WB_LIST_BY_KIND[sel.kind]] || []).find((i) => i.id === sel.id);
    box = item ? wbItemBBox(sel.kind, item) : null;
  }
  if (!box) {
    hideBoth();
    return;
  }
  const t = d3.zoomTransform(container);
  const rect = container.getBoundingClientRect();
  const hostRect = host.getBoundingClientRect();
  const cx = rect.left - hostRect.left + t.applyX((box.minX + box.maxX) / 2);
  const top = rect.top - hostRect.top + t.applyY(box.minY);
  const bottom = rect.top - hostRect.top + t.applyY(box.maxY);
  (mapNode ? bar : strip)?.classList.add("hidden");
  // Filled before it is measured: the strip's controls take their values from
  // the node, and a select whose value changed is a different width, so
  // reading `offsetWidth` first would centre the bar on last node's size.
  if (mapNode) wbSyncMapStrip(mapNode);
  active.classList.remove("hidden");
  const w = active.offsetWidth, h = active.offsetHeight;
  // 44px above, not 10: the rotation handle sits 28px above a card or
  // text box (`.wb-rotate-handle`, 12px tall), and a bar placed just over
  // the item covered it, reported: "I can't rotate objects because that
  // panel appears."
  const gapAbove = 44, gapBelow = 10;
  const left = Math.max(8, Math.min(hostRect.width - w - 8, cx - w / 2));
  //: With this node's ring open, the strip clears the *ring* rather than the
  //: node: a ring wide enough to clear a 200px topic reaches 136px from the
  //: node's centre, and two of its eight slots were drawn on the strip's own
  //: selects (INBOX 114). Raised to the ring's reach, not added to the 44
  //: above, which is the room a card's rotate handle needs and a topic has no
  //: handle: adding the two pushed the strip past the floor below.
  let overAbove = 0, overBelow = 0;
  if (mapNode && wbMapRadialFor === mapNode.id) {
    const over = wbMapRadialOverhang(hostRect, top, bottom);
    overAbove = over.above ? Math.max(0, over.above + gapBelow - gapAbove) : 0;
    overBelow = over.below;
  }
  // Above the item; below it when the top bar would cover the bar. The floor
  // is the bar's own clearance and not the ring's: a floor raised by the room
  // the ring takes *below* the node is what sent the strip down there.
  const topBar = document.getElementById("wb-topbar")?.getBoundingClientRect();
  const floor = topBar ? topBar.bottom - hostRect.top + gapBelow : 56;
  let y = top - h - gapAbove - overAbove;
  if (y < floor) y = bottom + gapBelow + overBelow;
  active.style.left = `${Math.round(left)}px`;
  active.style.top = `${Math.round(y)}px`;
}

// Shared by every item's own click handler (sketch/node/object): a plain
// click replaces whatever was selected, exactly as before; a shift-click
// adds or removes just this one item from the multi-selection, first
// folding any existing lone selection into it so "click one, then
// shift-click another" and "shift-click two in a row" end up in the same
// state.
function wbHandleItemClick(kind, id, event) {
  if (event.shiftKey) {
    if (wbSelectedItem) {
      wbMultiSelection.add(wbMultiKey(wbSelectedItem.kind, wbSelectedItem.id));
      wbSelectedItem = null;
    }
    const key = wbMultiKey(kind, id);
    if (wbMultiSelection.has(key)) wbMultiSelection.delete(key);
    else wbMultiSelection.add(key);
    wbApplySelectionHighlight();
    return;
  }
  wbMultiSelection.clear();
  // A plain click on a *grouped* item selects the whole group, not just the
  // one thing clicked: the other half of Ctrl+G (`wbGroupSelection`).
  const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
  if (item && item.group_id) {
    for (const [memberKind, listName] of Object.entries(WB_LIST_BY_KIND)) {
      for (const candidate of wbState[listName] || []) {
        if (candidate.group_id === item.group_id) wbMultiSelection.add(wbMultiKey(memberKind, candidate.id));
      }
    }
    wbSelectedItem = null;
    wbApplySelectionHighlight();
    return;
  }
  selectWbItem(kind, id);
}

//: Which `wbState` list a selection's item lives in, by kind, one place so
//: it can't drift out of step with `WB_KIND_INFO`'s own list names.
const WB_LIST_BY_KIND = { sketch: "sketches", node: "nodes", object: "objects" };

// Delete/Backspace with something selected, the other half of "select as
// a real tool": today, deleting anything meant switching to the Delete
// tool first. Reuses `deleteSketch`/`deleteNode`/`deleteObject`, so a
// selection-delete gets undo/redo for free, the same as every other way of
// deleting one. A non-empty multi-selection takes priority over the
// single-item one: the two are mutually exclusive by construction
// (`wbHandleItemClick`/marquee-select always clear one when populating the
// other), but checking the set first is the honest way to say so.
function deleteWbSelection() {
  if (wbMultiSelection.size > 0) {
    const keys = [...wbMultiSelection];
    wbMultiSelection.clear();
    for (const key of keys) {
      const sep = key.indexOf(":");
      const kind = key.slice(0, sep), id = Number(key.slice(sep + 1));
      const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
      if (!item) continue;
      if (kind === "sketch") wbDeleteSketchRef?.(item);
      else if (kind === "node") wbDeleteNodeRef?.(item);
      else wbDeleteObjectRef?.(item);
    }
    wbApplySelectionHighlight();
    return true;
  }
  if (!wbSelectedItem) return false;
  const { kind, id } = wbSelectedItem;
  const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
  clearWbSelection();
  if (!item) return false;
  if (kind === "sketch") wbDeleteSketchRef?.(item);
  else if (kind === "node") wbDeleteNodeRef?.(item);
  else wbDeleteObjectRef?.(item);
  return true;
}

// --- Layer order: bring to front / send to back (asked for directly) ------
//
// `z` already exists on every kind's own row and already drives paint order
// (`.style("z-index", d => d.z)`, both nodes' and objects' own render merge
// a few hundred lines down), nothing here needed a schema change or a new
// render path, only an action that actually changes the number. Nodes and
// objects share one HTML stacking context (`canvas` in renderWhiteboard),
// so they interleave against each other; a sketch renders in the separate
// SVG layer beneath both (wbShowAnchorHints's own comment explains why), so
// it only ever reorders against other sketches, never in front of a card.
// An honest limit of this app's layering, not something faked here.

function wbZOrderPeers(kind) {
  return kind === "sketch"
    ? wbState.sketches || []
    : [...(wbState.nodes || []), ...(wbState.objects || [])];
}

//: Moves one item to the front/back of its own layer and saves it, mirroring
//: `wbMoveItemBy`'s shape (capture `before`, mutate, save, return a "move"
//: undo entry) so it plugs into the same undo/redo stack without a new
//: action type.
async function wbSetZOrder(kind, item, toFront) {
  const zs = wbZOrderPeers(kind).map((p) => p.z || 0);
  const next = toFront ? Math.max(0, ...zs) + 1 : Math.min(0, ...zs) - 1;
  if ((item.z || 0) === next) return null;
  const before = WB_KIND_INFO[kind].payload(item);
  item.z = next;
  try {
    const saved = await apiJson(`${WB_KIND_INFO[kind].base}/${item.id}`, {
      method: "PUT",
      body: JSON.stringify(WB_KIND_INFO[kind].payload(item)),
    });
    Object.assign(item, saved);
  } catch {
    recordBrowserLog("WARN", [`[Whiteboard] ${kind} ${item.id} is stale: reloading the board`]);
    await fetchWhiteboardState();
    wbScheduleRender();
    return null;
  }
  return { action: "move", kind, id: item.id, before };
}

//: The context menu's own entry point, single selection or a whole
//: multi-selection at once, same iteration shape `deleteWbSelection` above
//: already uses.
async function wbSendSelectionZOrder(toFront) {
  const targets = [];
  if (wbMultiSelection.size > 0) {
    for (const key of wbMultiSelection) {
      const sep = key.indexOf(":");
      const kind = key.slice(0, sep), id = Number(key.slice(sep + 1));
      const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
      if (item) targets.push({ kind, item });
    }
  } else if (wbSelectedItem) {
    const { kind, id } = wbSelectedItem;
    const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
    if (item) targets.push({ kind, item });
  }
  if (!targets.length) return;
  const entries = [];
  for (const { kind, item } of targets) {
    const entry = await wbSetZOrder(kind, item, toFront);
    if (entry) entries.push(entry);
  }
  if (entries.length === 1) wbPushUndo(entries[0]);
  else if (entries.length > 1) wbPushUndo({ action: "batch", entries });
  if (entries.length) wbScheduleRender();
}

// --- Bulk move: dragging one member of a multi-selection moves all of them
// together: the reason to select more than one thing in the first place.
// Three per-kind drag handlers (node/object/sketch) each call these three
// functions at start/drag/end rather than reimplementing the same
// fixed-baseline-per-frame maths three times (see wbSaveSketchD's own
// comment on why re-deriving from a live-mutated value drifts).

function wbDragIsBulkMove(kind, id) {
  return wbMultiSelection.size > 1 && wbMultiSelection.has(wbMultiKey(kind, id));
}

//: Every other multi-selected member's position/shape at the *start* of a
//: bulk drag, so each frame recomputes from one fixed baseline instead of
//: compounding a per-frame delta onto an already-moved value (the exact bug
//: `wbSnap`'s own accumulation fix above exists to avoid, here for a whole
//: set instead of one item).
function wbCaptureBulkMoveOrigin(excludeKey, keys = wbMultiSelection) {
  const origin = new Map();
  for (const key of keys) {
    if (key === excludeKey) continue; // the dragged item's own handler already moves it
    const sep = key.indexOf(":");
    const kind = key.slice(0, sep), id = Number(key.slice(sep + 1));
    const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
    if (!item) continue;
    if (kind === "sketch") {
      const parsed = wbSketchParsedData(item);
      if (parsed) origin.set(key, { kind, id, item, d: parsed.d });
    } else {
      // **Precomputed here, for the same reason `dragStart` precomputes it
      // for the one card you actually grabbed** (`wbLinkedSketchesFor`'s own
      // comment): every other member of a marquee-selected group also moves
      // this drag, and without its own linked-sketch list, nothing was ever
      // going to update *its* edges frame by frame - only the primary
      // dragged card's `d._linkedSketches` existed at all. Reported: "the
      // connections/edges get left behind when i move the notes/nodes
      // around", which is exactly the shape of a bug that only shows on a
      // multi-card drag, a single card was always fine.
      // `mapEdges` only for an object: a map node *is* an object, and a card
      // and an object can share an id, so asking for a card's tree edges
      // would follow the wrong node's branch.
      origin.set(key, {
        kind, id, item, x: item.x, y: item.y,
        linked: wbLinkedSketchesFor(id, kind),
        mapEdges: kind === "object" ? wbMapEdgesFor(id) : [],
      });
    }
  }
  return origin;
}

function wbApplyBulkMove(origin, dx, dy) {
  for (const entry of origin.values()) {
    if (entry.kind === "sketch") {
      const newD = wbTransformPathD(entry.d, { dx, dy });
      const el = document.querySelector(`.sketch-group[data-id="${entry.id}"]`);
      el?.querySelector(".sketch-path")?.setAttribute("d", newD);
      el?.querySelector(".sketch-hitbox")?.setAttribute("d", newD);
      entry.item._liveD = newD;
    } else {
      entry.item.x = entry.x + dx;
      entry.item.y = entry.y + dy;
      const el = document.querySelector(WB_SELECTOR_BY_KIND[entry.kind](entry.id));
      if (el) el.style.transform = wbItemTransform(entry.item);
      // See this entry's own comment in `wbCaptureBulkMoveOrigin`: without
      // this, only the card the pointer is actually on kept its edges live
      // during a multi-select drag.
      wbUpdateLinkedSketches(entry.id, entry.linked);
      // Same for a map's tree edges, which are not sketches at all: a marquee
      // drag of half a branch left every one of its curves behind.
      if (entry.mapEdges?.length) wbUpdateMapEdges(entry.mapEdges);
    }
  }
}

async function wbSaveBulkMove(origin) {
  for (const entry of origin.values()) {
    if (entry.kind === "sketch") {
      if (entry.item._liveD) {
        const d = entry.item._liveD;
        delete entry.item._liveD;
        await wbSaveSketchD(entry.item, d);
      }
    } else if (entry.kind === "node") {
      await wbSaveNode(entry.item);
    } else {
      await wbSaveObject(entry.item);
    }
  }
}


// Copy/paste: reported directly: "can't copy/paste objects drawn or made
// on whiteboard". One snapshot, not a real OS clipboard: this app has
// nothing to gain from `navigator.clipboard` here (no cross-tab/cross-app
// paste target makes sense for a sketch's own path data), and a plain
// in-memory value is simpler and needs no permission prompt.
let wbClipboard = null; // {kind, payload}: see WB_KIND_INFO's own payload() per kind

//: A card is deliberately excluded. `POST /whiteboard/nodes` is "one card
//: per note per board" by design (routes_whiteboard.py's own comment: two
//: cards for the same note stacked on each other reads as one card that
//: won't drag properly): POSTing a copy would silently *move* the
//: original card to the paste offset instead of creating a second one,
//: which is worse than not supporting copy/paste for cards at all.
function wbCopySelection() {
  if (!wbSelectedItem) return false;
  if (wbSelectedItem.kind === "node") {
    toast("A note card can't be copied: drag it, or drop the note again from the Library.");
    return false;
  }
  const { kind, id } = wbSelectedItem;
  const item = (wbState[WB_LIST_BY_KIND[kind]] || []).find((i) => i.id === id);
  if (!item) return false;
  if (kind === "sketch" && !wbSketchParsedData(item)) {
    // A link sketch: its `data` has no `d`, only sourceId/targetId, and is
    // recomputed from two cards' positions on every render; nothing here is
    // a standalone shape to copy.
    toast("A link can't be copied: copy the cards it connects instead.");
    return false;
  }
  wbClipboard = { kind, payload: WB_KIND_INFO[kind].payload(item) };
  toast("Copied.");
  return true;
}

//: Applied to both axes on paste, so the copy lands visibly beside the
//: original rather than exactly on top of it, same reasoning as every
//: other drawing app's paste offset.
const WB_PASTE_OFFSET = 24;

async function wbPasteClipboard() {
  if (!wbClipboard) return;
  const { kind, payload } = wbClipboard;
  const { base, list } = WB_KIND_INFO[kind];
  const body = {
    ...payload,
    x: (payload.x || 0) + WB_PASTE_OFFSET,
    y: (payload.y || 0) + WB_PASTE_OFFSET,
    board_id: window.currentBoardId,
  };
  if (kind === "sketch") {
    // A sketch's own x/y isn't what positions it on screen, its path data
    // is (wbTransformPathD's own comment): so bumping x/y alone would draw
    // the paste directly on top of the original, offset in the database but
    // not on the board.
    const parsed = wbSketchParsedData({ data: body.data });
    if (parsed) {
      parsed.d = wbTransformPathD(parsed.d, { dx: WB_PASTE_OFFSET, dy: WB_PASTE_OFFSET });
      body.data = JSON.stringify(parsed);
    }
  }
  try {
    const created = await apiJson(base, { method: "POST", body: JSON.stringify(body) });
    wbState[list].push(created);
    wbPushUndo({ action: "create", kind, id: created.id });
    wbScheduleRender();
    wbSelectToolRef?.("select");
    selectWbItem(kind, created.id);
  } catch (err) {
    toast(err.message || "Couldn't paste that.", true);
  }
}

// Cut: ROADMAP §89.12, asked as a question alongside the context menu
// below. Same restrictions as copy (a card can't be cut, a link-sketch
// can't be cut): wbCopySelection already toasts why, so cut just declines
// to delete anything when the copy half refuses.
function wbCutSelection() {
  if (!wbCopySelection()) return false;
  deleteWbSelection();
  return true;
}

// --- Right-click / long-press menu for a selection (ROADMAP §89.12) --------
//
// Asked as a question, alongside cut above: today the only way to act on a
// selection is a keyboard shortcut, and `wbOpenDockedMenu`'s reparent-to-body
// technique (a few hundred lines up) is the only precedent in this file for
// a menu that has to escape a clipped, scrolling ancestor, so this reuses
// that shape rather than inventing a second one, just triggered by a gesture
// on the canvas instead of a toolbar toggle.
let wbCtxMenuEl = null;

//: Rebuilt on every open rather than cached with static buttons: a card
//: can't be copied or cut at all (`wbCopySelection`'s own comment: POSTing
//: a copy would silently move the original instead of duplicating it), and
//: a menu offering two buttons guaranteed to fail is worse than one that
//: only ever offers what this selection can actually do.
function wbBuildContextMenu(kind) {
  if (!wbCtxMenuEl) {
    const menu = document.createElement("div");
    menu.className = "action-menu wb-ctx-menu hidden";
    menu.setAttribute("role", "menu");
    document.body.appendChild(menu);
    wbCtxMenuEl = menu;
  }
  const menu = wbCtxMenuEl;
  menu.replaceChildren();
  const item = (label, title, fn) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "menu-item";
    button.setAttribute("role", "menuitem");
    button.textContent = label;
    if (title) button.title = title;
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      wbCloseContextMenu();
      fn();
    });
    menu.appendChild(button);
  };
  if (kind !== "node") {
    item("Copy", "Ctrl/Cmd+C", () => wbCopySelection());
    item("Cut", "Ctrl/Cmd+X", () => wbCutSelection());
  }
  //: The two ways to grow a map, on the node you just right-clicked
  //: (MINDMAP_PLAN.md §5 item 11). The hover controls on the node itself are
  //: the primary affordance; this is the discoverable one, a right-click is
  //: where people look for "what can I do with this", and the `+`/library
  //: buttons only appear once the pointer is already on the node.
  const mapNode = wbSelectedMapNode();
  if (mapNode && wbMultiSelection.size <= 1) {
    item("Add a child topic", "Tab", () => wbMapAddChild(mapNode.id));
    item("Add from the library…", "Point a new child at a note, document, file or link", () =>
      wbMapAddReference(mapNode.id)
    );
    //: Focus (§5 item 18). On the node's own menu because focus is about one
    //: node: "show me around here" is a thing you say pointing at something.
    item("Focus here", "F", () => wbMapSetFocus(mapNode.id));
    //: The other half of the dock's colour picker: a colour wheel can set a
    //: colour but has no way to say "none", and without this a node that was
    //: coloured once could never rejoin its branch.
    if (mapNode.data?.color) {
      item("Reset the colour to the branch", "Inherit this branch's colour again", async () => {
        mapNode.data = { ...mapNode.data, color: null };
        await wbSaveObject(mapNode);
        renderWhiteboardNow();
        wbSyncMapToolState();
      });
    }
  }
  // Asked for directly. Available for every kind, a sketch reorders
  // against other sketches, a card/object against both (wbZOrderPeers'
  // own comment has the full reasoning for that split).
  item("Bring to Front", "Move above everything else in this layer", () => wbSendSelectionZOrder(true));
  item("Send to Back", "Move below everything else in this layer", () => wbSendSelectionZOrder(false));
  item("Delete", "Delete", () => deleteWbSelection());
  return menu;
}

function wbCloseContextMenu() {
  wbCtxMenuEl?.classList.add("hidden");
}

//: Selects whatever the gesture landed on (unless it's already part of a
//: multi-selection: right-clicking one member of a group opens the menu
//: for the whole group, same rule a plain click already uses) and opens the
//: menu at the pointer, clamped to the viewport the same way the docked
//: toolbar menu already clamps itself.
function wbOpenContextMenuFor(kind, id, clientX, clientY) {
  const key = wbMultiKey(kind, id);
  if (!wbMultiSelection.has(key)) wbHandleItemClick(kind, id, { shiftKey: false });
  //: **A map node gets the ring, not the list** (MINDMAP_PLAN.md §12.1 item
  //: 3). Routed here rather than at the two gestures because right-click and
  //: touch-and-hold both already arrive at this one function: splitting the
  //: decision across both is how one of them ends up opening the other thing.
  //: A multi-selection keeps the flat menu, which is the only one of the two
  //: whose actions mean anything for more than one item.
  const ringNode = wbMultiSelection.size === 0 ? wbSelectedMapNode() : null;
  if (ringNode && ringNode.id === id) {
    wbCloseContextMenu();
    if (wbOpenMapRadial(ringNode)) return;
  }
  wbCloseMapRadial();
  // Copy/Cut only ever act on a single-item selection (`wbCopySelection`'s
  // own `wbSelectedItem` check): a multi-selection gets the same "node"
  // treatment as a card, which is "Delete only", rather than two buttons
  // that would silently do nothing.
  const menu = wbBuildContextMenu(wbMultiSelection.size > 0 ? "node" : kind);
  menu.classList.remove("hidden");
  menu.style.left = `${clientX}px`;
  menu.style.top = `${clientY}px`;
  const margin = 8;
  const rect = menu.getBoundingClientRect();
  if (rect.right > window.innerWidth - margin) {
    menu.style.left = `${Math.max(margin, window.innerWidth - rect.width - margin)}px`;
  }
  if (rect.bottom > window.innerHeight - margin) {
    menu.style.top = `${Math.max(margin, window.innerHeight - rect.height - margin)}px`;
  }
}

document.addEventListener("click", (e) => {
  if (wbCtxMenuEl && !wbCtxMenuEl.classList.contains("hidden") && !e.target.closest(".wb-ctx-menu")) {
    wbCloseContextMenu();
  }
  // The ring closes on a click anywhere but itself, the same rule. Its own
  // slots close it from their handlers instead, after they have acted.
  if (!e.target.closest("#wb-map-radial")) wbCloseMapRadial();
  if (!e.target.closest("#wb-map-link-radial")) wbCloseMapLinkRadial();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    wbCloseContextMenu();
    wbCloseMapRadial();
    wbCloseMapLinkRadial();
  }
  // Alt is a live modifier while the ring is open, so it is watched here
  // rather than read only at the click: the two add slots re-label themselves
  // the moment it goes down. `e.altKey` rather than `e.key === "Alt"` so the
  // ring is right even when Alt arrives with another key held.
  if (wbMapRadialFor != null) wbSyncMapRadialAlt(e.altKey);
});
document.addEventListener("keyup", (e) => {
  if (wbMapRadialFor != null) wbSyncMapRadialAlt(e.altKey);
});

//: Wires the gesture onto one item type's `enter()` selection: called
//: right after that type's own `.on("click", ...)` is set up, so it only
//: needs binding once per element the same way click already is (d3 keeps
//: the same DOM node across a keyed re-render, so a handler bound on enter
//: persists without needing to be re-applied on every update/merge).
//: Is this pointer target inside something that is *actually* being typed
//: into? One place, because the attribute-versus-element mistake below has
//: now been made twice in this file for two different gestures.
function wbIsEditingTarget(target) {
  const editable = target?.closest?.("[contenteditable]");
  return Boolean(editable && editable.isContentEditable);
}

function wbWireContextMenu(selection, kind) {
  let holdTimer = null;
  const cancelHold = () => {
    if (holdTimer) {
      clearTimeout(holdTimer);
      holdTimer = null;
    }
  };
  selection
    .on("contextmenu.wbctx", (event, d) => {
      // A text object's own editable body needs its native context menu
      // (cut/copy/paste, spellcheck): hijacking it here would make the
      // text box's contenteditable unusable with the mouse.
      //
      // **Asked of the element, not of the attribute.** `closest(
      // "[contenteditable]")` matches `contenteditable="false"` too, because
      // an attribute selector tests that the attribute is *there*. Every text
      // box and every map node on this board carries exactly that attribute
      // while it is not being edited (`wbBuildMapNode`, and the object render
      // below), so this guard fired on all of them and a right-click on a
      // topic opened nothing at all: found by opening the node radial's own
      // sweep and watching the ring never appear. Same lesson `objDrag`'s own
      // filter records a hundred lines further down, in the same words: ask
      // whether it *is* editable.
      if (wbIsEditingTarget(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      wbOpenContextMenuFor(kind, d.id, event.clientX, event.clientY);
    })
    // Touch has no right-click, so a hold stands in for it, same 500ms
    // threshold and cancel-on-release/move shape as the toolbar toggle's own
    // long-press (wbWireToggleGestures, a few hundred lines up).
    .on("pointerdown.wbctx", (event, d) => {
      if (event.pointerType !== "touch") return;
      if (wbIsEditingTarget(event.target)) return;
      cancelHold();
      holdTimer = setTimeout(() => {
        holdTimer = null;
        wbOpenContextMenuFor(kind, d.id, event.clientX, event.clientY);
      }, 500);
    })
    .on("pointerup.wbctx pointercancel.wbctx pointermove.wbctx", cancelHold);
}

function wbUpdateUndoRedoButtons() {
  const undoBtn = document.getElementById("wb-undo");
  const redoBtn = document.getElementById("wb-redo");
  if (undoBtn) undoBtn.disabled = wbUndoStack.length === 0;
  if (redoBtn) redoBtn.disabled = wbRedoStack.length === 0;
}

function wbPushUndo(entry) {
  wbUndoStack.push(entry);
  if (wbUndoStack.length > WB_UNDO_MAX) wbUndoStack.shift();
  // A fresh action makes whatever redo history existed unreachable, the
  // same rule the sketch pad's own `sketchSaveSnapshot` already follows.
  wbRedoStack = [];
  wbUpdateUndoRedoButtons();
}

// The shared half of undo and redo: pop one entry off `from`, apply its
// inverse, and push what would undo *that* onto `to`. Undo and redo are
// each other's mirror image: pop from one stack, push the reverse onto
// the other: so one function drives both rather than two near-duplicates
// that could drift apart.
//: Per-kind: the collection endpoint, which key in `wbState` holds it, and
//: how to turn a live item back into a POST body. One table rather than a
//: three-way ternary repeated at every call site, adding the "object" kind
//: (images/text boxes) here is the only change `wbApplyHistoryEntry` needed
//: to cover them too.
const WB_KIND_INFO = {
  sketch: {
    base: "/whiteboard/sketches",
    list: "sketches",
    payload: (d) => ({ data: d.data, board_id: d.board_id, x: d.x, y: d.y, z: d.z, group_id: d.group_id ?? null }),
  },
  node: {
    base: "/whiteboard/nodes",
    list: "nodes",
    payload: (d) => ({
      entry_id: d.entry_id, board_id: d.board_id, x: d.x, y: d.y, z: d.z,
      width: d.width ?? null, height: d.height ?? null, rotation: d.rotation ?? null,
      group_id: d.group_id ?? null,
    }),
  },
  object: {
    base: "/whiteboard/objects",
    list: "objects",
    payload: (d) => ({
      kind: d.kind, data: d.data, board_id: d.board_id,
      x: d.x, y: d.y, z: d.z, width: d.width, height: d.height,
      rotation: d.rotation ?? null, group_id: d.group_id ?? null,
    }),
  },
};

//: A card/object's CSS transform: translate always, plus a rotate(deg)
//: about its own centre when it has one. `translate() rotate()` (in that
//: order) is the standard idiom for "move this box, then spin it in
//: place": `transform-origin`'s default (50% 50%) is resolved once in the
//: element's own untransformed box, so the rotation pivots on the box's own
//: centre regardless of where the translate moved it to, the reverse order
//: would instead swing the box around a point offset from its own body.
//: **A drag handle that lives inside the thing it moves needs a container
//: that doesn't.** Reported directly: text boxes "spasm positions and are
//: basically unmovable".
//:
//: `d3.drag` measures each frame's `event.dx/dy` between two `d3.pointer`
//: readings taken against its *container*, and that container defaults to
//: `this.parentNode`. For a drag bound to the item itself (`objDrag`) the
//: parent is `#wb-html-layer`, which holds still while one object moves, so
//: the deltas are true screen pixels and `/ transform.k` converts them to
//: board units correctly. But `.wb-object-grip` and `.wb-resize-handle` are
//: *children* of the item, so their default container is the item, and the
//: item's own `transform` is rewritten on every frame of the drag. For an
//: HTML element `d3.pointer` returns `clientX - getBoundingClientRect().left`,
//: so the origin it measures from moves by exactly the amount just applied
//: and the next frame's delta is cancelled against it. The box judders in
//: place instead of following the cursor.
//:
//: Only text objects get a grip (an image has no contenteditable competing
//: for its body), which is why this was reported for text boxes alone. The
//: resize handles have the same flaw on the `w`/`n` corners only: those are
//: the ones that move `x`/`y` as well as the size, which is the standing
//: "zoom-drift in move/resize handles" report.
//:
//: Pointing every such drag at the item's own parent is a no-op for the
//: handles that were already fine (a stable origin either way) and a fix for
//: the ones that were not.
function wbStableDragContainer(itemSelector) {
  return function () {
    return this.closest(itemSelector)?.parentNode || this.parentNode;
  };
}

//: **A text box is a box first and a text field second.** The other half of
//: the same report ("I can't drag text boxes... basically unmovable"): the
//: `.wb-text-content` was `contenteditable` from the moment it rendered and
//: fills the box edge to edge, so it swallowed every pointerdown before the
//: object's own drag could see one. The only draggable surface left was the
//: grip and a ~0.5rem strip of padding, and grabbing anywhere else did
//: nothing at all, which reads as "broken" rather than "aim for the handle".
//:
//: So the box is only editable once you ask it to be, which is what every
//: canvas app with text does (Figma, Excalidraw, PowerPoint): drag it like
//: any other object, double-click to get a caret, blur to go back. A box
//: made by the text tool starts in edit mode, since the whole point of
//: click-to-place is typing straight away.
//: **Rendered markdown in a text box or sticky, toggleable.** Asked for
//: directly. Editing always shows the raw text, markdown you cannot see is
//: markdown you cannot fix, so this paints the rendered form only when the
//: box is not being edited, and `wbBeginTextEdit` puts the source back.
function wbPaintTextContent(contentEl, d) {
  if (!contentEl) return;
  const raw = d.data.content || "";
  if (d.data.md && raw.trim() && typeof renderMarkdown === "function") {
    contentEl.replaceChildren();
    contentEl.classList.add("wb-text-md");
    renderMarkdown(contentEl, raw);
    return;
  }
  contentEl.classList.remove("wb-text-md");
  contentEl.textContent = raw;
}

//: Wrap the selection inside a text box (or the whole text, when nothing is
//: selected) in a markdown marker, the formatting bar a text box never had.
function wbWrapTextSelection(marker) {
  const item = wbSelectedTextObjectOrNull();
  if (!item) return;
  const el = document.querySelector(`.wb-object[data-id="${item.id}"] .wb-text-content`);
  const raw = item.data.content || "";
  const sel = window.getSelection();
  let next;
  if (el && el.isContentEditable && sel && sel.rangeCount && !sel.isCollapsed && el.contains(sel.anchorNode)) {
    const picked = sel.toString();
    next = raw.replace(picked, `${marker}${picked}${marker}`);
  } else {
    next = raw.trim() ? `${marker}${raw}${marker}` : raw;
  }
  item.data = { ...item.data, content: next };
  wbSaveObject(item);
  wbScheduleRender();
}

function wbBulletTextLines() {
  const item = wbSelectedTextObjectOrNull();
  if (!item) return;
  const lines = (item.data.content || "").split("\n");
  const allBulleted = lines.every((line) => !line.trim() || line.trimStart().startsWith("- "));
  item.data = {
    ...item.data,
    content: lines
      .map((line) => (!line.trim() ? line : allBulleted ? line.replace(/^(\s*)- /, "$1") : `- ${line}`))
      .join("\n"),
  };
  wbSaveObject(item);
  wbScheduleRender();
}

function wbBeginTextEdit(contentEl) {
  if (!contentEl || contentEl.isContentEditable) return;
  //: Back to the source while editing, whatever the rendered view showed.
  const objectEl = contentEl.closest(".wb-object");
  const item = (wbState.objects || []).find((o) => String(o.id) === objectEl?.dataset.id);
  if (item) {
    contentEl.classList.remove("wb-text-md");
    contentEl.textContent = item.data.content || "";
  }
  contentEl.setAttribute("contenteditable", "true");
  contentEl.closest(".wb-object")?.classList.add("wb-text-editing");
  contentEl.focus();
}

function wbEndTextEdit(contentEl) {
  if (!contentEl) return;
  contentEl.setAttribute("contenteditable", "false");
  contentEl.closest(".wb-object")?.classList.remove("wb-text-editing");
}

function wbItemTransform(d) {
  const rot = d.rotation ? ` rotate(${d.rotation}deg)` : "";
  return `translate(${d.x}px, ${d.y}px)${rot}`;
}

//: A screen-space point's angle from a screen-space centre, in degrees,
//: 0-360, with "straight up" (the rotate handle's own resting position) as
//: 0: so an untouched handle already reads as the item's actual rotation.
//: `shiftSnap` rounds to the nearest 15°, the same modifier convention as
//: shift-to-constrain while drawing a shape.
//: `wbAngleFromCenterDeg`, but for a sketch's rotate handle specifically, 
//: the center it's given is in *board* space (the same coordinate space
//: `d` itself uses), while the pointer only ever arrives in *screen*
//: space (`clientX`/`clientY`). The resize-handle drag just above this
//: function divides `event.dx` by the zoom scale by hand for the same
//: reason: an SVG child's d3.drag coordinates are not auto-corrected for
//: an ancestor `<g transform>` in this app's actual DOM, so the two
//: spaces have to be reconciled explicitly rather than assumed to match.
function wbSketchAngleFromCenterDeg(boardCx, boardCy, sourceEvent, shiftSnap) {
  const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
  const rect = document.getElementById("wb-svg-layer").getBoundingClientRect();
  const screenCx = boardCx * transform.k + transform.x + rect.left;
  const screenCy = boardCy * transform.k + transform.y + rect.top;
  return wbAngleFromCenterDeg(screenCx, screenCy, sourceEvent.clientX, sourceEvent.clientY, shiftSnap);
}

function wbAngleFromCenterDeg(cx, cy, px, py, shiftSnap) {
  let deg = Math.atan2(py - cy, px - cx) * (180 / Math.PI) + 90;
  deg = ((deg % 360) + 360) % 360;
  if (shiftSnap) deg = Math.round(deg / 15) * 15 % 360;
  return Math.round(deg);
}

async function wbApplyHistoryEntry(from, to) {
  const entry = from.pop();
  if (!entry) return false;
  if (entry.action === "batch") {
    // A single user gesture that touched several items at once, an
    // arrow-key nudge on a multi-selection, or an alignment/distribute pass
    //, needs to undo/redo as the one action it visibly was, not N separate
    // Undo presses. Bundles N sub-entries and replays each through this same
    // function (recursively: none of the sub-actions are themselves
    // batches), re-bundling whatever came back as the one reverse entry.
    const reverse = [];
    for (const sub of entry.entries) {
      const subTo = [];
      await wbApplyHistoryEntry([sub], subTo);
      if (subTo.length) reverse.push(subTo[0]);
    }
    to.push({ action: "batch", entries: reverse });
    return true;
  }
  const { base, list, payload: toPayload } = WB_KIND_INFO[entry.kind];
  if (entry.action === "delete") {
    // This entry means "bring back what was deleted". Applying it recreates
    // the item; reversing *that* is deleting the newly-recreated one again.
    const restored = await apiJson(base, { method: "POST", body: JSON.stringify(entry.payload) });
    wbState[list].push(restored);
    to.push({ action: "create", kind: entry.kind, id: restored.id });
  } else if (entry.action === "move") {
    // A drag, resize, or nudge's own undo: asked for directly ("account
    // for resizes, rotates, positional movement"). `before` is the item's
    // whole payload (x/y, width/height, a sketch's own `d`) as it was right
    // before the change, so this one action type covers move and resize
    // both: restoring is the same PUT either way, just a different set of
    // fields differing from the current row. Mirrors the delete/create pair
    // above: capture the *current* state before overwriting it, so the
    // pushed reverse entry can undo the undo.
    const item = wbState[list].find((i) => i.id === entry.id);
    if (!item) return true; // stale: nothing to restore, but the stack still advances
    const current = toPayload(item);
    const restored = await apiJson(`${base}/${entry.id}`, { method: "PUT", body: JSON.stringify(entry.before) });
    Object.assign(item, restored);
    to.push({ action: "move", kind: entry.kind, id: entry.id, before: current });
  } else {
    // This entry means "remove what was created". The item's current data
    // has to be captured *before* deleting it, once gone, nothing else
    // remembers what it looked like, and the reverse of this reverse (a
    // future redo/undo) needs a real payload to recreate it from, not a
    // blank one.
    const item = wbState[list].find((i) => i.id === entry.id);
    const payload = item && toPayload(item);
    await apiJson(`${base}/${entry.id}`, { method: "DELETE" });
    wbState[list] = wbState[list].filter((i) => i.id !== entry.id);
    if (payload) to.push({ action: "delete", kind: entry.kind, payload });
  }
  return true;
}

// Reverses the single most recent create or delete, a sketch stroke, a
// shape, a link, or a note card. Asked for implicitly by adding an eraser:
// a tool whose whole job is deleting things you swipe over needs a safety
// net more than any other control on this toolbar.
async function wbUndo() {
  try {
    if (!(await wbApplyHistoryEntry(wbUndoStack, wbRedoStack))) return;
    wbUpdateUndoRedoButtons();
    wbScheduleRender();
  } catch {
    toast("Couldn't undo that.", true);
  }
}

// Reapplies whatever the most recent undo took back, asked for directly
// (`wbUndoStack` "exists; nothing analogous does"). Pushes the reverse onto
// `wbUndoStack`, so undo/redo/undo/redo keeps working rather than only
// ever reversing once.
async function wbRedo() {
  try {
    if (!(await wbApplyHistoryEntry(wbRedoStack, wbUndoStack))) return;
    wbUpdateUndoRedoButtons();
    wbScheduleRender();
  } catch {
    toast("Couldn't redo that.", true);
  }
}

// Images and text boxes, the two new object kinds, created here and
// rendered by `renderWbObjects`. One shared creator (a POST plus the usual
// create-undo-entry dance every other whiteboard item already does) rather
// than a copy per kind, since only the `kind`/`data` differ.
async function wbCreateObject(kind, data, x, y, width, height) {
  const body = { kind, data, board_id: window.currentBoardId, x, y, z: 1, width, height };
  try {
    const created = await apiJson("/whiteboard/objects", { method: "POST", body: JSON.stringify(body) });
    wbState.objects = wbState.objects || [];
    wbState.objects.push(created);
    wbPushUndo({ action: "create", kind: "object", id: created.id });
    wbScheduleRender();
    await refreshBoardList();
    return created;
  } catch (err) {
    toast(err.message || "Couldn't add that to the board.", true);
    return null;
  }
}

//: **A sticky note is a text box that already looks like one** (PLAN.md W3).
//: Same object kind, same editor, same properties panel, the difference is
//: three defaults (a yellow fill, a warm border, a larger face) and a size
//: that fits a thought rather than a paragraph. Kept as `kind: "text"` on
//: purpose: no schema change, and every text feature (copy style, AI, undo)
//: works on a sticky the day it exists.
async function wbCreateSticky(x, y) {
  const created = await wbCreateObject(
    "text",
    { content: "", bg: "#fff4a3", border_color: "#e8d56a", color: "#2a2a1f", font_size: 16 },
    x - 90, y - 70, 180, 140
  );
  if (!created) return;
  wbSelectToolRef?.("select");
  requestAnimationFrame(() => {
    const el = document.querySelector(`.wb-object[data-id="${created.id}"] .wb-text-content`);
    if (el) wbBeginTextEdit(el);
  });
}

async function wbCreateTextBox(x, y) {
  const created = await wbCreateObject(
    "text",
    { content: "" },
    x - 100, y - 40, 200, 80
  );
  if (!created) return;
  wbSelectToolRef?.("select");
  // The point of click-to-place is typing immediately, a text box with
  // nothing in it and no visible focus is a box nobody knows they can type
  // into. wbScheduleRender() just rebuilt the DOM, so the element has to be
  // looked up fresh rather than kept from before the render.
  requestAnimationFrame(() => {
    const el = document.querySelector(`.wb-object[data-id="${created.id}"] .wb-text-content`);
    if (el) wbBeginTextEdit(el);
  });
}

// Asked for directly. Deletes every card and sketch on the *current* board
// (not other boards: clearing is scoped the same way everything else on
// this screen is). Reuses the same undo entries a single delete already
// pushes, one per item, rather than inventing a second "bulk" undo shape: 
// so Ctrl+Z after Clear brings items back one at a time, exactly like an
// eraser swipe over the same items would.
//: Delete the board you are standing on.
//:
//: Reported: "there's no way to delete a board while in that board on the
//: whiteboard and mindmap". The action existed only on the gallery card's
//: kebab menu, so removing the board in front of you meant leaving it, finding
//: it again in the list, and opening a menu on its card.
//:
//: The default board (`id === null`) is the one board that cannot go: it
//: always exists, it is what the canvas falls back to, and the gallery
//: already draws it without a kebab for the same reason. Saying so is better
//: than hiding the row, which would leave the menu a different shape on that
//: one board with nothing to explain the gap.
//:
//: `DELETE /entries/{id}` and not a whiteboard route, because a board **is**
//: an Entry (MINDMAP_PLAN.md §4 option B) and that is the same call the
//: gallery's own Delete makes. Afterwards the canvas has no board to show, so
//: it goes back to the gallery rather than sitting on a board that is gone.
async function wbDeleteCurrentBoard() {
  const boardId = window.currentBoardId ?? null;
  if (boardId === null) {
    toast("The default board cannot be deleted. Use Clear to empty it.");
    return;
  }
  const select = $("wb-board-select");
  const title =
    select?.options?.[select.selectedIndex]?.textContent?.trim() || "this board";
  if (!(await confirmDialog(`Delete "${title}"? This cannot be undone.`))) return;
  try {
    await apiJson(`/entries/${boardId}`, { method: "DELETE" });
  } catch (err) {
    toast(err.message || "Couldn't delete that board.", true);
    return;
  }
  window.currentBoardId = null;
  wbShowBoardsLanding();
  await refreshBoardList();
  toast(`Deleted "${title}".`);
}

async function wbClearBoard() {
  const total = wbState.nodes.length + wbState.sketches.length + (wbState.objects?.length || 0);
  if (total === 0) {
    toast("This board is already empty.");
    return;
  }
  const ok = await confirmDialog(
    `Clear this board? ${total} item${total === 1 ? "" : "s"} will be removed. ` +
    "Ctrl+Z undoes them one at a time afterward."
  );
  if (!ok) return;
  try {
    for (const kind of ["node", "sketch", "object"]) {
      const { base, list, payload } = WB_KIND_INFO[kind];
      for (const item of [...(wbState[list] || [])]) {
        await apiJson(`${base}/${item.id}`, { method: "DELETE" });
        wbPushUndo({ action: "delete", kind, payload: payload(item) });
      }
      wbState[list] = [];
    }
    wbSelectedItem = null;
    wbScheduleRender();
    await refreshBoardList();
    toast("Board cleared.");
  } catch {
    toast("Couldn't clear the whole board, reloading to show what's left.", true);
    await fetchWhiteboardState();
    wbScheduleRender();
  }
}

// --- Whiteboard export (asked for directly: "a way to screen clip a or a
// selected area and export as an image/pdf/svg etc") -----------------------
//
// No marquee/multi-select exists yet (HANDOVER's own open list), so "a
// selected area" becomes two concrete scopes instead: what's currently
// framed on screen (the literal "screen clip" reading), or the whole board
// regardless of pan/zoom. Both are built the same way, as a real SVG
// string, sized to board-space coordinates, which then serves all three
// formats: written out directly for .svg, rasterized through an off-screen
// <canvas> for .png, and for PDF, handed to the browser's own Print →
// "Save as PDF" rather than hand-rolling PDF bytes, which is what every
// pure-client web app already does for this and needs no library to do.
function wbSvgEscape(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// A rough character-count wrap, no live font metrics are available while
// building a string that isn't in the DOM yet. Good enough for a legible
// label in an export, not typeset text. `maxLines` caps height (a card's
// own export label is deliberately short; a text box gets more room).
function wbSvgWrapLines(text, maxWidth, maxLines = 6, charWidth = 7) {
  const charsPerLine = Math.max(10, Math.floor(maxWidth / charWidth));
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = (line + " " + word).trim();
    if (next.length > charsPerLine && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
    if (lines.length >= maxLines) break;
  }
  if (line && lines.length < maxLines) lines.push(line);
  return lines;
}

function wbSvgText(lines, x, y, { fontSize = 13, fill = "#1f2430", lineHeight } = {}) {
  const dy = lineHeight || fontSize + 3;
  const tspans = lines
    .map((l, i) => `<tspan x="${x}" dy="${i === 0 ? 0 : dy}">${wbSvgEscape(l)}</tspan>`)
    .join("");
  return `<text x="${x}" y="${y}" font-family="sans-serif" font-size="${fontSize}" fill="${fill}">${tspans}</text>`;
}

function wbSvgWrappedText(text, x, y, maxWidth) {
  return wbSvgText(wbSvgWrapLines(text, maxWidth), x, y);
}

// The board's full extent, every card and sketch, with padding, computed
// from what's actually rendered (`getBBox`/`offsetWidth`) rather than
// guessed constants, so it stays right if a card's real size ever changes.
function wbBoardBounds() {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const node of wbState.nodes) {
    const el = document.querySelector(`.node-card[data-id="${node.id}"]`);
    const w = el ? el.offsetWidth : 250;
    const h = el ? el.offsetHeight : 150;
    minX = Math.min(minX, node.x);
    minY = Math.min(minY, node.y);
    maxX = Math.max(maxX, node.x + w);
    maxY = Math.max(maxY, node.y + h);
  }
  for (const sketch of wbState.sketches) {
    const el = document.querySelector(`.sketch-group[data-id="${sketch.id}"]`);
    if (!el) continue;
    try {
      const bbox = el.getBBox();
      minX = Math.min(minX, bbox.x);
      minY = Math.min(minY, bbox.y);
      maxX = Math.max(maxX, bbox.x + bbox.width);
      maxY = Math.max(maxY, bbox.y + bbox.height);
    } catch {
      /* getBBox throws on an element the browser hasn't laid out yet */
    }
  }
  for (const obj of wbState.objects || []) {
    minX = Math.min(minX, obj.x);
    minY = Math.min(minY, obj.y);
    maxX = Math.max(maxX, obj.x + obj.width);
    maxY = Math.max(maxY, obj.y + obj.height);
  }
  if (!Number.isFinite(minX)) return { minX: 0, minY: 0, width: 800, height: 600 };
  const pad = 60;
  return {
    minX: minX - pad,
    minY: minY - pad,
    width: maxX - minX + pad * 2,
    height: maxY - minY + pad * 2,
  };
}

//: Bounds of the current selection, asked for directly ("an export selection
//: feature"). Reuses `wbSelectionEntries()` (already shared by
//: align/distribute/nudge) for a real multi-selection; a lone
//: `wbSelectedItem` falls back to `wbItemBBox` directly since that path
//: never populates `wbMultiSelection`. A link sketch has no bbox of its
//: own (`wbItemBBox` returns null for one), `null` here means "nothing
//: exportable selected", which the export menu's own gating already checks.
function wbSelectionBounds() {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const boxes = wbMultiSelection.size > 0
    ? wbSelectionEntries().map((e) => e.bbox)
    : wbSelectedItem
      ? [wbItemBBox(wbSelectedItem.kind, (wbState[WB_LIST_BY_KIND[wbSelectedItem.kind]] || []).find((i) => i.id === wbSelectedItem.id))].filter(Boolean)
      : [];
  for (const box of boxes) {
    minX = Math.min(minX, box.minX);
    minY = Math.min(minY, box.minY);
    maxX = Math.max(maxX, box.maxX);
    maxY = Math.max(maxY, box.maxY);
  }
  if (!Number.isFinite(minX)) return null;
  const pad = 40;
  return { minX: minX - pad, minY: minY - pad, width: maxX - minX + pad * 2, height: maxY - minY + pad * 2 };
}

// What's actually framed on screen right now, in board-space coordinates, 
// the inverse of the pan/zoom transform the container itself carries.
function wbVisibleBounds() {
  const container = document.getElementById("whiteboard-container");
  const transform = d3.zoomTransform(container);
  const rect = container.getBoundingClientRect();
  return {
    minX: -transform.x / transform.k,
    minY: -transform.y / transform.k,
    width: rect.width / transform.k,
    height: rect.height / transform.k,
  };
}

//: Which items an "export selection" pass should include: everything else
//: in `wbBuildExportSvg` only needs a membership check, so this is the one
//: place that reads `wbSelectedItem`/`wbMultiSelection` for it. `null` (not
//: scope "selection") means "no filter", i.e. every other scope keeps
//: exporting the whole board it always did.
function wbSelectedKeys() {
  if (wbMultiSelection.size > 0) return wbMultiSelection;
  if (wbSelectedItem) return new Set([wbMultiKey(wbSelectedItem.kind, wbSelectedItem.id)]);
  return new Set();
}

function wbBuildExportSvg(scope) {
  const bounds = scope === "selection" ? wbSelectionBounds()
    : scope === "visible" ? wbVisibleBounds() : wbBoardBounds();
  const { minX, minY, width, height } = bounds || wbBoardBounds();
  const onlyKeys = scope === "selection" ? wbSelectedKeys() : null;
  const container = document.getElementById("whiteboard-container");
  const bgColor = container ? getComputedStyle(container).backgroundColor : "#1b1f2c";

  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX} ${minY} ${width} ${height}" ` +
      `width="${Math.round(width)}" height="${Math.round(height)}">`,
    `<rect x="${minX}" y="${minY}" width="${width}" height="${height}" fill="${bgColor}" />`,
  ];

  // A map's branch colours, and its tree edges, both computed once for the
  // whole export. The edges are cloned out of the live DOM rather than
  // recomputed: they are already real SVG paths in board coordinates (that is
  // the whole reason `wbRenderMapEdges` draws them as SVG instead of on a
  // canvas), so cloning them is exact and cannot disagree with what is on
  // screen. First in the list, so they sit under every node.
  const exportMapIndex = wbIsMap() ? wbMapIndex() : null;
  const exportMapColors = exportMapIndex ? wbMapNodeColors(exportMapIndex) : null;
  if (exportMapIndex) {
    for (const edge of document.querySelectorAll(".wb-map-edges .wb-map-edge")) {
      const clone = edge.cloneNode(true);
      clone.removeAttribute("class");
      clone.setAttribute("fill", "none");
      if (!clone.getAttribute("stroke")) clone.setAttribute("stroke", "#8888aa");
      clone.setAttribute("stroke-width", "2");
      parts.push(clone.outerHTML);
    }
  }

  // Sketches already exist as real SVG, cloned as-is rather than
  // reinterpreted, so a stroke's colour/width/opacity (including the
  // highlighter's own translucency) survives into the export untouched.
  for (const sketch of wbState.sketches) {
    if (onlyKeys && !onlyKeys.has(wbMultiKey("sketch", sketch.id))) continue;
    const el = document.querySelector(`.sketch-group[data-id="${sketch.id}"]`);
    if (!el) continue;
    const clone = el.cloneNode(true);
    clone.removeAttribute("class");
    parts.push(clone.outerHTML);
  }

  // Cards are the HTML layer, which doesn't survive SVG rasterization the
  // way real SVG does, a simplified rect + label stands in for the live
  // card, matching what the live card itself shows (raw content, truncated;
  // it has no private-note masking of its own to match either).
  const exportEntriesById = new Map(allEntries.map((e) => [String(e.id), e]));
  for (const node of wbState.nodes) {
    if (onlyKeys && !onlyKeys.has(wbMultiKey("node", node.id))) continue;
    const entry = exportEntriesById.get(String(node.entry_id));
    const el = document.querySelector(`.node-card[data-id="${node.id}"]`);
    const w = el ? el.offsetWidth : 250;
    const h = el ? el.offsetHeight : 150;
    const label = entry ? notePreviewText(entry.content || "").slice(0, 160) : `Note ${node.entry_id}`;
    parts.push(`<g transform="translate(${node.x}, ${node.y})">`);
    parts.push(
      `<rect width="${w}" height="${h}" rx="10" fill="#ffffffcc" stroke="#8888aa" stroke-width="1.5" />`
    );
    parts.push(wbSvgWrappedText(label || "Empty note", 14, 24, w - 28));
    parts.push("</g>");
  }

  // Images and text boxes, the two new object kinds, neither tied to a
  // note. An <image> element rasterizes cleanly since the URL is always
  // same-origin (isRenderableUrl already guarantees that server-side); a
  // text box gets the same simplified rect+label treatment a card does,
  // but honours the colour/size it was actually given rather than a fixed
  // look, since those are the whole point of a text box.
  for (const obj of wbState.objects || []) {
    if (onlyKeys && !onlyKeys.has(wbMultiKey("object", obj.id))) continue;
    parts.push(`<g transform="translate(${obj.x}, ${obj.y})">`);
    if (obj.kind === "image" && obj.data.url) {
      // `mediaSrc`, not the bare url: rasterizing this SVG loads it through
      // a plain `<img>` (see `wbRasterizeSvg`), which never attaches
      // X-Auth-Token: the same gap that made the image never render on the
      // board itself, here too.
      parts.push(
        `<image href="${wbSvgEscape(mediaSrc(obj.data.url))}" width="${obj.width}" height="${obj.height}" ` +
          `preserveAspectRatio="xMidYMid slice" />`
      );
    } else if (WB_MAP_KINDS.has(obj.kind)) {
      // A map node exports as what it looks like: a rounded box with the
      // branch's colour down its leading edge and its label inside. Without
      // this branch a map exported as an empty `<g>` per node: every PNG and
      // SVG of a mind map came out blank, which is the same "stored, served
      // and not drawn" gap this whole section exists to close, one layer down.
      const size = wbMapNodeSize(obj);
      const colour = exportMapColors?.get(obj.id) || "#8888aa";
      parts.push(
        `<rect width="${size.w}" height="${size.h}" rx="8" fill="#ffffffee" ` +
          `stroke="${wbSvgEscape(colour)}" stroke-width="1.5" />`
      );
      parts.push(
        `<rect width="4" height="${size.h}" rx="2" fill="${wbSvgEscape(colour)}" />`
      );
      const lines = wbSvgWrapLines(wbMapLabel(obj), size.w - 28, 4, 7.5);
      parts.push(wbSvgText(lines, 14, 22, { fontSize: 14, fill: "#1f2430", lineHeight: 17 }));
    } else if (obj.kind === "text") {
      const fontSize = obj.data.font_size || 16;
      const lines = wbSvgWrapLines(obj.data.content || "", obj.width - 20, 20, fontSize * 0.55);
      parts.push(
        wbSvgText(lines, 10, fontSize + 8, {
          fontSize,
          fill: obj.data.color || "#1f2430",
          lineHeight: fontSize * 1.25,
        })
      );
    }
    parts.push("</g>");
  }

  parts.push("</svg>");
  return { svg: parts.join(""), width, height };
}

function wbRasterizeSvg(svgString, width, height, mime) {
  return new Promise((resolve, reject) => {
    const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width));
      canvas.height = Math.max(1, Math.round(height));
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob(
        (result) => (result ? resolve(result) : reject(new Error("Couldn't rasterize the board."))),
        mime
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Couldn't rasterize the board."));
    };
    img.src = url;
  });
}

//: Markdown outline / OPML, straight from `GET /boards/{id}/export` (§9.3).
//:
//: The **server** renders both, and that is deliberate: the same two formats
//: are what `import_board` reads back and what the AI's `read_mindmap` builds
//: its outline from, so a second renderer here would be a third opinion of
//: what this map says, and the one nobody would think to keep in step.
//:
//: `api()` rather than `apiJson()` because the response is a text file with a
//: `Content-Disposition`, not JSON; `saveFile` is the app's own download
//: helper and is what makes this work in the desktop shell, where a browser
//: download has nowhere to land.
async function wbExportMapText(format) {
  const boardId = window.currentBoardId;
  if (!boardId) {
    toast("The default board isn't a map: outlines come from a map.");
    return;
  }
  const res = await api(`/whiteboard/boards/${boardId}/export?format=${encodeURIComponent(format)}`);
  const blob = await res.blob();
  // The board picker's own label, minus the "(3 items)" it appends: the same
  // strip `renameCurrentBoard` already does, and the only place the open
  // board's title exists on the client.
  const title = document.getElementById("wb-board-select")?.selectedOptions?.[0]
    ?.textContent.replace(/\s*\(\d+ items?\)$/, "") || "mindmap";
  // The extension the format actually is, a `.md` file holding OPML is a
  // file nothing will open. The name is reduced to word characters, spaces and
  // hyphens because a map may be called anything at all and this becomes a
  // filename on someone's disk.
  const safe = title.replace(/[^\w -]+/g, "").trim() || "mindmap";
  //: One table, so the extension and the sentence can never disagree about
  //: which format was actually asked for: which is what a pair of ternaries
  //: here would have turned into the moment a third format arrived.
  const formats = {
    markdown: { suffix: "md", said: "a Markdown outline" },
    opml: { suffix: "opml", said: "OPML" },
    freemind: { suffix: "mm", said: "a FreeMind map" },
  };
  const chosen = formats[format] || formats.markdown;
  await saveFile(`${safe}.${chosen.suffix}`, blob);
  toast(`Map exported as ${chosen.said}.`);
}

//: **Make a map of these notes** (MINDMAP_PLAN.md §5 item 15).
//:
//: Three steps, in the order a person would say them: pick the notes, look at
//: what came back, then create it. The middle step is the whole point, and it
//: is `generate_diagram`'s and the note extractor's own preview-before-commit
//: convention: `POST /boards/propose` writes nothing at all, so a proposal
//: that is wrong costs a Cancel rather than a board to go and delete.
//:
//: The proposal is shown as **the outline itself, editable**, rather than as a
//: rendered tree with controls to rearrange it. It is the same indented text
//: the Markdown export writes and the import reads, a person can retype a line
//: or delete three of them faster than any node editor would let them, and the
//: map is one keystroke from being editable properly anyway once it exists.
//:
//: `source` says who wrote it. A local 4B model asked for an outline answers
//: with a paragraph often enough that the server falls back to the notebook's
//: own filing, and a proposal that quietly claimed to be the model's when it
//: was not would make the model look better than it is, which is exactly the
//: kind of thing this app does not do.
async function wbGenerateMapFromNotes() {
  if (typeof pickNotesDialog !== "function") return;
  const chosen = await pickNotesDialog("Which notes should the map be built from?", {
    confirmLabel: "Propose a map",
  });
  if (!chosen || !chosen.length) return;

  toast("Working out a shape for those notes…");
  let proposal = null;
  try {
    proposal = await apiJson("/whiteboard/boards/propose", {
      method: "POST",
      body: JSON.stringify({ note_ids: chosen.map((note) => note.id) }),
    });
  } catch (error) {
    toast(error.message || "Couldn't propose a map from those notes.", true);
    return;
  }

  const accepted = await wbReviewMapProposal(proposal);
  if (!accepted) return;
  try {
    const board = await apiJson("/whiteboard/boards/generate", {
      method: "POST",
      body: JSON.stringify({
        name: accepted.name,
        outline: accepted.outline,
        note_ids: proposal.note_ids,
      }),
    });
    window.wbLastCreatedBoard = board;
    toast(`Made “${board.title}”: ${board.object_count} node${board.object_count === 1 ? "" : "s"}.`);
    // Straight into the map, for the same reason the import opens what it
    // imported: landing back on an unchanged-looking list is how a thing that
    // worked reads as a thing that did not.
    await openWhiteboardBoard(board.id);
  } catch (error) {
    toast(error.message || "Couldn't create that map.", true);
  }
}

//: The middle step: the proposal, as text, with a name beside it.
//:
//: Its own dialog rather than `promptDialog` because the thing being reviewed
//: is a block of lines, not a value: a single-line input for a twenty-line
//: outline would make the one step that exists for reading it the one step
//: that cannot show it.
function wbReviewMapProposal(proposal) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay confirm-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Review the proposed map");

    const card = document.createElement("div");
    card.className = "card modal-card confirm-card wb-proposal-card";
    const head = document.createElement("div");
    head.className = "row confirm-head";
    const title = document.createElement("h3");
    title.className = "confirm-title";
    title.textContent = "Review the map before it is made";
    head.appendChild(title);

    const said = document.createElement("p");
    said.className = "muted";
    //: Three fallbacks, three sentences. "Your model is not running" is
    //: something the reader can go and fix; "the model answered with a
    //: paragraph" is something about the model they chose; and reporting
    //: either as the other is the kind of small dishonesty that teaches
    //: people not to read these lines at all.
    const because = {
      model: "Proposed by your local model",
      offline: "Grouped by how they are filed, because no local model is running",
      unusable: "Grouped by how they are filed, because the model did not answer with an outline",
      failed: "Grouped by how they are filed, because the model could not be reached",
    };
    const counted = `${proposal.notes} note${proposal.notes === 1 ? "" : "s"}`;
    said.textContent = `${because[proposal.reason] || because.offline}, from ${counted}. Edit anything here before it is created.`;

    const name = document.createElement("input");
    name.type = "text";
    name.value = proposal.name || "";
    name.setAttribute("aria-label", "What to call the map");

    const outline = document.createElement("textarea");
    outline.className = "wb-proposal-outline";
    outline.value = proposal.outline || "";
    outline.rows = 12;
    outline.spellcheck = false;
    outline.setAttribute("aria-label", "The proposed outline, one node per line");

    const returnFocus = document.activeElement;
    let settled = false;
    const close = (answer) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      returnFocus?.focus?.();
      resolve(answer);
    };
    // Escape only. Enter is a newline in a textarea, which is the whole point
    // of this dialog being one.
    const onKey = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close(null);
    };

    const row = document.createElement("div");
    row.className = "row confirm-actions";
    row.append(
      smallButton("Cancel", "Cancel", () => close(null)),
      smallButton("Create the map", "Create the map", () => {
        const text = outline.value.trim();
        if (!text) {
          toast("There is nothing in the outline to build.", true);
          return;
        }
        close({ name: name.value.trim() || proposal.name || "Generated map", outline: text });
      }, false)
    );
    card.append(head, said, name, outline, row);
    overlay.appendChild(card);
    wireBackdropClose(overlay, () => close(null));
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    outline.focus();
  });
}

//: How much of a file this will send. Matches `MAX_IMPORT_CHARS` in
//: routes_whiteboard.py exactly: the server refuses anything longer with a
//: 422, and finding that out after uploading 4MB and waiting is a worse way to
//: learn it than a sentence naming the number.
const WB_MAX_IMPORT_CHARS = 400000;

//: Import a mind map from an OPML or Markdown outline (§5 item 17).
//:
//: **The extension picks the format**, and nothing asks the user to confirm
//: it. `POST /whiteboard/boards/import` takes `{format, content, name?}` and
//: only knows the two, and a `.opml` file is not ambiguous, a second dialog
//: to repeat what the filename already said is exactly the shape CLAUDE.md
//: records as the real bug behind five bookmark-URL reports.
//:
//: `name` is deliberately not sent: the server takes the title out of the
//: document itself (an OPML `<head><title>`, a Markdown `#` heading) and falls
//: back to "Imported map". A filename is a worse name than the one the author
//: wrote inside the file.
async function wbImportOutlineFile(event) {
  const input = event.target;
  const file = input.files && input.files[0];
  // Cleared immediately so importing the *same* file twice in a row still
  // fires `change` the second time: the one thing this pattern gets wrong
  // when it is written without it.
  input.value = "";
  if (!file) return;
  // FreeMind first: a `.mm` file is XML too, so an extension test that asked
  // "is it XML?" first would send every FreeMind map to the OPML parser and
  // import it as an empty map, since OPML's nodes are `<outline>` and
  // FreeMind's are `<node>`, and neither parser finds the other's.
  const format = /\.mm$/i.test(file.name)
    ? "freemind"
    : /\.(opml|xml)$/i.test(file.name)
      ? "opml"
      : "markdown";
  let content = "";
  try {
    content = await file.text();
  } catch {
    toast("Couldn't read that file.", true);
    return;
  }
  if (!content.trim()) {
    toast("That file is empty.", true);
    return;
  }
  if (content.length > WB_MAX_IMPORT_CHARS) {
    toast(
      `That outline is ${content.length.toLocaleString()} characters: the limit is ${WB_MAX_IMPORT_CHARS.toLocaleString()}.`,
      true
    );
    return;
  }
  try {
    const board = await apiJson("/whiteboard/boards/import", {
      method: "POST",
      body: JSON.stringify({ format, content }),
    });
    // The gallery is refreshed *and* the new map is opened, because an import
    // is a thing you then want to look at, landing back on an unchanged-
    // looking list is how an import that worked reads as one that did not.
    window.wbLastCreatedBoard = board;
    renderLibraryBoardsGallery();
    toast(
      `Imported “${board.title}”: ${board.object_count} node${board.object_count === 1 ? "" : "s"}.`
    );
    openWhiteboardBoard(board.id);
  } catch (error) {
    // The server's own message, not a generic one: it names the actual
    // refusal ("Unknown import format", a DOCTYPE in the OPML, a parse
    // failure), and those are the only things a person can act on.
    toast(error.message || "Couldn't import that outline.", true);
  }
}

async function wbExportSvg(scope) {
  const { svg } = wbBuildExportSvg(scope);
  await saveFile(`whiteboard-${scope}.svg`, new Blob([svg], { type: "image/svg+xml" }));
  toast("Board exported as SVG.");
}

// Shared with the background-image picker above, which inlines the same
// three lines: pulled out here because this is the second call site and a
// third (this one) is exactly when a copy-pasted upload stops being fine.
async function uploadToLibrary(filename, blob) {
  const formData = new FormData();
  formData.append("file", new File([blob], filename, { type: blob.type }));
  return apiJson("/media/upload", {
    method: "POST",
    headers: { "X-Auth-Token": authToken() },
    body: formData,
  });
}

async function wbExportPng(scope) {
  const { svg, width, height } = wbBuildExportSvg(scope);
  const blob = await wbRasterizeSvg(svg, width, height, "image/png");
  const filename = `whiteboard-${scope}.png`;
  await saveFile(filename, blob);
  // Asked for directly: an exported board should show up in the Library's
  // Images gallery, not only as a file on disk that the app has no record
  // of. Best-effort: a failed upload must not make the export itself look
  // like it failed, since the download above already succeeded.
  try {
    await uploadToLibrary(filename, blob);
    toast("Board exported as PNG, and added to your image library.");
  } catch {
    toast("Board exported as PNG.");
  }
}

//: **Straight into the image library, with no file on disk.** Asked for
//: directly: "maybe I should be able to highlight a rectangular section
//: and/or select a bunch of things in a whiteboard and export it to a png
//: which can then appear in the image library."
//:
//: `wbExportPng` above already uploads a copy, but it downloads the file
//: first, and "put this drawing in my library" and "save this file to my
//: computer" are different intentions that should not be one button. The
//: marquee and shift-click already produce the selection this exports; this
//: is the missing half that turns a region of the board into a real image
//: the gallery, the captioner and semantic search can all see.
async function wbSaveToLibrary(scope) {
  const { svg, width, height } = wbBuildExportSvg(scope);
  const blob = await wbRasterizeSvg(svg, width, height, "image/png");
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  await uploadToLibrary(`whiteboard-${scope}-${stamp}.png`, blob);
  toast("Added to your image library.");
}

async function wbExportPdf(scope) {
  const { svg, width, height } = wbBuildExportSvg(scope);
  const blob = await wbRasterizeSvg(svg, width, height, "image/png");
  const url = URL.createObjectURL(blob);
  const win = window.open("", "_blank");
  if (!win) {
    URL.revokeObjectURL(url);
    toast("Allow pop-ups to export as PDF, it opens Print, then Save as PDF.", true);
    return;
  }
  win.document.write(
    `<!doctype html><html><head><title>MemoryMap whiteboard export</title><style>` +
      `@page { margin: 0; } html,body{margin:0;padding:0;background:#fff;}` +
      `img{display:block;width:100%;height:auto;}</style></head>` +
      `<body><img src="${url}" alt="Whiteboard export"></body></html>`
  );
  win.document.close();
  win.onload = () => {
    win.focus();
    win.print();
  };
  toast('Opened Print: choose "Save as PDF" as the destination.');
}

//: **Export is a dialog, not a popover** (WHITEBOARD_PLAN.md decision 4).
//:
//: It was a list: five headings of two or three options each, built as a
//: floating menu anchored to whichever button opened it, which is how it came
//: to be reported as "a full-height list in the wrong place" (INBOX 12, with a
//: screenshot of it running off the bottom of the window). The choices are a
//: matrix, scope by format, and a list of every cell of a matrix is as long as
//: the product of its sides. Two segmented rows are as long as the sum.
//:
//: Excalidraw's export dialog is exactly this shape (a scope toggle plus
//: format buttons), which is the research note in §8 of the plan.
const WB_EXPORT_SCOPES = [
  { value: "selection", label: "Selection", title: "Just what is selected" },
  { value: "visible", label: "On screen", title: "Exactly what the canvas is showing now" },
  { value: "whole", label: "Whole board", title: "Everything on the board" },
];

//: Each format says which scopes it can answer, rather than the dialog
//: knowing: SVG has no meaning for "on screen" (it is the board's vectors, not
//: a screenshot), and an outline is the whole tree or nothing. `map: true`
//: marks the three that only exist on a mind map, for the reason the old menu
//: gave in the same words: an outline of a whiteboard is not a thing.
const WB_EXPORT_FORMATS = [
  {
    value: "png", label: "PNG", scopes: ["selection", "visible", "whole"],
    note: "An image file, and a copy in your image library.",
    run: (scope) => wbExportPng(scope),
  },
  {
    value: "library", label: "Image library", scopes: ["selection", "visible", "whole"],
    note: "Straight into the gallery, with no file saved to disk.",
    run: (scope) => wbSaveToLibrary(scope),
  },
  {
    value: "svg", label: "SVG", scopes: ["selection", "whole"],
    note: "Vector, so it stays sharp at any size.",
    run: (scope) => wbExportSvg(scope),
  },
  {
    value: "pdf", label: "PDF", scopes: ["selection", "visible", "whole"],
    note: "Opens Print: choose “Save as PDF” as the destination.",
    run: (scope) => wbExportPdf(scope),
  },
  {
    value: "markdown", label: "Markdown", scopes: ["whole"], map: true,
    note: "The map as an indented outline.",
    run: () => wbExportMapText("markdown"),
  },
  {
    value: "opml", label: "OPML", scopes: ["whole"], map: true,
    note: "The interchange format every mind mapper reads.",
    run: () => wbExportMapText("opml"),
  },
  {
    value: "freemind", label: "FreeMind", scopes: ["whole"], map: true,
    note: "For FreeMind and Freeplane.",
    run: () => wbExportMapText("freemind"),
  },
];

//: One `.seg` on the app's own recipe (`promptDialog`'s, down to the
//: `aria-pressed` pair), built twice here rather than once in app.js because
//: this pair talk to each other: picking a format that cannot answer the
//: current scope has to move the scope.
function wbExportSegment(label, options, chosen, onPick) {
  const seg = document.createElement("div");
  seg.className = "seg seg-compact wb-export-seg";
  seg.setAttribute("role", "group");
  seg.setAttribute("aria-label", label);
  for (const option of options) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option.label;
    button.dataset.value = option.value;
    if (option.title) button.title = option.title;
    button.addEventListener("click", () => onPick(option.value));
    seg.appendChild(button);
  }
  return seg;
}

function wbSyncExportSeg(seg, chosen, allowed) {
  for (const button of seg.querySelectorAll("button")) {
    const on = button.dataset.value === chosen;
    button.classList.toggle("active", on);
    button.setAttribute("aria-pressed", on ? "true" : "false");
    // Disabled, not hidden: a scope that vanishes and comes back as the format
    // changes makes the row jump under the pointer, and "SVG cannot do what is
    // on screen" is worth saying rather than hiding.
    const usable = !allowed || allowed.has(button.dataset.value);
    button.disabled = !usable;
  }
}

function wbExportBoard() {
  const hasSelection = wbMultiSelection.size > 0 || Boolean(wbSelectedItem);
  const isMap = wbIsMap();
  const formats = WB_EXPORT_FORMATS.filter((f) => !f.map || isMap);
  let format = formats[0];
  let scope = hasSelection ? "selection" : "visible";

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay confirm-overlay wb-export-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Export this board");

  const card = document.createElement("div");
  card.className = "card modal-card confirm-card wb-export-card";
  const head = document.createElement("div");
  head.className = "row confirm-head";
  const title = document.createElement("h3");
  title.className = "confirm-title";
  title.textContent = "Export this board";
  head.appendChild(title);

  const formatLabel = document.createElement("span");
  formatLabel.className = "wb-export-label";
  formatLabel.textContent = "Format";
  const scopeLabel = document.createElement("span");
  scopeLabel.className = "wb-export-label";
  scopeLabel.textContent = "How much";
  const note = document.createElement("p");
  note.className = "confirm-text wb-export-note";

  const scopeSeg = wbExportSegment("How much to export", WB_EXPORT_SCOPES, scope, (value) => {
    scope = value;
    sync();
  });
  const formatSeg = wbExportSegment("Format", formats, format.value, (value) => {
    format = formats.find((f) => f.value === value) || formats[0];
    // The scope follows the format when the format cannot answer it, rather
    // than the Export button refusing a pair the dialog let you make.
    if (!format.scopes.includes(scope)) scope = format.scopes.find((s) => s !== "selection" || hasSelection) || format.scopes[0];
    sync();
  });

  function sync() {
    const allowed = new Set(format.scopes.filter((s) => s !== "selection" || hasSelection));
    if (!allowed.has(scope)) scope = [...allowed][0];
    wbSyncExportSeg(formatSeg, format.value, null);
    wbSyncExportSeg(scopeSeg, scope, allowed);
    const chosenScope = WB_EXPORT_SCOPES.find((s) => s.value === scope);
    // Two sentences, the format's and the scope's, so the line reads the same
    // way round whichever of the two was changed last.
    note.textContent = [format.note, chosenScope ? `${chosenScope.title}.` : ""].filter(Boolean).join(" ");
  }

  let settled = false;
  const close = () => {
    if (settled) return;
    settled = true;
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    returnFocus?.focus?.();
  };
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      go();
    }
  };
  const go = async () => {
    const chosen = format;
    const where = scope;
    close();
    try {
      await chosen.run(where);
    } catch (err) {
      toast(err.message || "Couldn't export the board.", true);
    }
  };

  const returnFocus = document.activeElement;
  const row = document.createElement("div");
  row.className = "row confirm-actions";
  const exportBtn = smallButton("Export", "Export", go, false);
  exportBtn.id = "wb-export-go";
  row.append(smallButton("Cancel", "Cancel", close), exportBtn);
  card.append(head, formatLabel, formatSeg, scopeLabel, scopeSeg, note, row);
  overlay.appendChild(card);
  wireBackdropClose(overlay, close);
  document.addEventListener("keydown", onKey, true);
  document.body.appendChild(overlay);
  sync();
  exportBtn.focus();
}

async function initWhiteboard() {
  if (wbInitialized) return;
  wbInitialized = true;
  
  const container = d3.select("#whiteboard-container");
  container.call(wbZoom).on("dblclick.zoom", null);
  // Plain wheel pans (Shift+wheel pans sideways); Ctrl/⌘+wheel is left to
  // d3-zoom's own handler by `wbZoomFilter`. `passive: false` so the page
  // behind the board does not scroll as well.
  if (!container.node().dataset.wbWheelPan) {
    container.node().dataset.wbWheelPan = "1";
    container.node().addEventListener("wheel", (e) => {
      if (e.ctrlKey || e.metaKey) return;
      e.preventDefault();
      const k = d3.zoomTransform(container.node()).k || 1;
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      let dx = e.deltaX * unit, dy = e.deltaY * unit;
      if (e.shiftKey && !dx) { dx = dy; dy = 0; }
      container.call(wbZoom.translateBy, -dx / k, -dy / k);
    }, { passive: false });
  }
  
  // Toolbar hooks
  document.getElementById("wb-zoom-in").addEventListener("click", () => container.transition().call(wbZoom.scaleBy, 1.2));
  document.getElementById("wb-zoom-out").addEventListener("click", () => container.transition().call(wbZoom.scaleBy, 0.8));
  // Was `wbZoom.transform(d3.zoomIdentity)`, a reset to 100% at the origin,
  // under a button labelled "Fit to Screen". See `wbZoomToFit`.
  document.getElementById("wb-zoom-fit").addEventListener("click", () => wbZoomToFit());

  // **An arrow, not the function directly.** `addEventListener` passes the
  // click event as the first argument, which would land in
  // `toggleWhiteboardFullscreen`'s own `force` parameter: a `MouseEvent` is
  // truthy, so `force === undefined` was never true and the toggle could
  // only ever turn full screen *on*. Reported as "I cant exit full screen
  // mode in the whiteboard".
  document.getElementById("wb-fullscreen")?.addEventListener("click", () => toggleWhiteboardFullscreen());

  // --- Navigator ----------------------------------------------------------
  document.getElementById("wb-navigator-toggle")?.addEventListener("click", () => wbToggleNavigator());
  document.getElementById("wb-navigator-close")?.addEventListener("click", () => wbToggleNavigator(false));
  document.getElementById("wb-navigator-fit")?.addEventListener("click", () => wbZoomToFit());
  const navMap = document.getElementById("wb-navigator-map");
  if (navMap) {
    // Pointer events rather than mouse events, so a pen or a touch drag on a
    // tablet moves the viewport too, this is a drawing app, and the board is
    // reachable from a touchscreen.
    let navDragging = false;
    navMap.addEventListener("pointerdown", (event) => {
      navDragging = true;
      navMap.setPointerCapture(event.pointerId);
      wbNavigatorJump(event);
      event.preventDefault();
    });
    navMap.addEventListener("pointermove", (event) => {
      if (navDragging) wbNavigatorJump(event);
    });
    const endNavDrag = (event) => {
      if (!navDragging) return;
      navDragging = false;
      try {
        navMap.releasePointerCapture(event.pointerId);
      } catch {
        /* the pointer was already gone */
      }
    };
    navMap.addEventListener("pointerup", endNavDrag);
    navMap.addEventListener("pointercancel", endNavDrag);
  }
  try {
    if (localStorage.getItem("wb-navigator-open") === "1") wbToggleNavigator(true);
  } catch {
    /* private mode: open it by hand */
  }

  // --- Find a card on this board ------------------------------------------
  document.getElementById("wb-search-toggle")?.addEventListener("click", () => {
    const bar = document.getElementById("wb-search-bar");
    if (bar && !bar.classList.contains("hidden")) wbCloseBoardSearch();
    else wbOpenBoardSearch();
  });
  document.getElementById("wb-search-close")?.addEventListener("click", wbCloseBoardSearch);
  document.getElementById("wb-search-prev")?.addEventListener("click", () => wbBoardSearchGo(-1));
  document.getElementById("wb-search-next")?.addEventListener("click", () => wbBoardSearchGo(1));
  const searchInput = document.getElementById("wb-search-input");
  if (searchInput) {
    searchInput.addEventListener("input", () => wbBoardSearchRun(searchInput.value));
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        // Enter re-runs nothing: the matches are already live from `input`.
        // It only steps, which is what every find bar in every editor does.
        wbBoardSearchGo(event.shiftKey ? -1 : 1);
      } else if (event.key === "Escape") {
        event.preventDefault();
        wbCloseBoardSearch();
      }
    });
  }
  
  // Sidebar toggling
  const setWbLibraryOpen = (open) => {
    const sidebar = $("whiteboard-sidebar");
    sidebar.classList.toggle("hidden", !open);
    $("wb-add-note")?.classList.toggle("is-on", open);
    if (open) renderWbLibrary();
  };
  $("wb-add-note").addEventListener("click", () => {
    // Toggling on the class rather than reading it back: the panel covers the
    // toggle, so "click it again to close" was not reachable.
    setWbLibraryOpen($("whiteboard-sidebar").classList.contains("hidden"));
  });
  $("wb-library-close")?.addEventListener("click", () => setWbLibraryOpen(false));

  const btnAddSketch = document.getElementById("wb-add-sketch");
  if (btnAddSketch) {
    btnAddSketch.addEventListener("click", () => {
      openSketch();
    });
  }

  const boardSelect = document.getElementById("wb-board-select");
  if (boardSelect) {
    boardSelect.addEventListener("change", async (e) => {
      window.currentBoardId = e.target.value || null;
      await fetchWhiteboardState();
      wbScheduleRender();
      // The background image is stored per board, so switching boards has
      // to re-read it: otherwise the previous board's image stays up.
      wbApplyBgImage();
    });
  }
  $("wb-new-board")?.addEventListener("click", createNewBoard);
  $("wb-rename-board")?.addEventListener("click", renameCurrentBoard);
  $("wb-map-layout")?.addEventListener("change", (e) => wbMapSetLayout(e.target.value));
  //: Phase 5's controls (§5 items 18 to 21). Wired here with the rest of the
  //: board chrome rather than inside their own render functions, which is the
  //: shape `tests/test_frontend_handlers.py` exists to keep: a listener added
  //: where an element is drawn is a listener added again every time it is
  //: redrawn.
  $("wb-map-perspective")?.addEventListener("change", (e) => wbMapSetPerspective(e.target.value));
  $("wb-map-stats-item")?.addEventListener("click", wbShowMapStats);
  $("wb-map-expand-all")?.addEventListener("click", wbMapExpandAll);
  $("wb-map-focus-less")?.addEventListener("click", () => wbMapStepFocus(-1));
  $("wb-map-focus-more")?.addEventListener("click", () => wbMapStepFocus(1));
  $("wb-map-focus-clear")?.addEventListener("click", wbMapClearFocus);
  $("wb-map-templates-dismiss")?.addEventListener("click", wbDismissMapTemplates);
  //: A root, because there is nothing on the map to hang it off: `null` as the
  //: parent is exactly what `wbMapAddChild` already means by a top-level
  //: topic, and it opens the new node for typing like every other add does.
  $("wb-map-empty-add")?.addEventListener("click", () => wbMapAddChild(null));
  //: The map dock (MINDMAP_PLAN.md §12.1 item 1). Every one of these already
  //: existed as a key or a hover affordance and nothing else, which is the
  //: owner's complaint in one line: "the mindmap needs to be more separated
  //: with its own controls". No new behaviour is written here on purpose,
  //: these call the same functions Tab, Enter, F and the node's own chevron
  //: call, so the two routes cannot drift.
  $("wb-map-add-root")?.addEventListener("click", () => wbMapAddChild(null));
  $("wb-map-add-child")?.addEventListener("click", () => {
    const node = wbSelectedMapNode();
    if (node) wbMapAddChild(node.id);
  });
  $("wb-map-add-sibling")?.addEventListener("click", () => {
    const node = wbSelectedMapNode();
    if (node) wbMapAddSibling(node.id);
  });
  $("wb-map-collapse")?.addEventListener("click", async () => {
    const node = wbSelectedMapNode();
    if (!node) return;
    await wbMapToggleCollapse(node.id);
    wbSyncMapToolState();
  });
  //: Focus is one key in both directions (see the F handler), so it is one
  //: button in both directions too.
  $("wb-map-focus-here")?.addEventListener("click", () => {
    const node = wbSelectedMapNode();
    if (!node) return;
    if (wbMapFocusState && wbMapFocusState.id === node.id) wbMapClearFocus();
    else wbMapSetFocus(node.id);
  });
  //: Branch colour (§12.0: "styling is per node, with inheritance down the
  //: branch"). `wbMapColors` has read `data.color` and carried it down to
  //: every descendant since Phase 2, and nothing in the app could write it:
  //: the colour of a branch was whatever the palette handed out. This is that
  //: control. `change` rather than `input` so dragging across a colour wheel
  //: writes once, the same rule the board background picker follows.
  $("wb-map-branch-color")?.addEventListener("change", async (e) => {
    const node = wbSelectedMapNode();
    if (!node) return;
    node.data = { ...node.data, color: e.target.value };
    await wbSaveObject(node);
    renderWhiteboardNow();
  });
  //: The node radial (§12.1 item 3). Each slot reads the node the ring was
  //: opened for, acts, and closes: a ring that stayed open over a map that has
  //: just been re-laid-out would be pointing at empty canvas.
  const radialSlot = (id, run) => {
    $(id)?.addEventListener("click", async (event) => {
      const node = wbMapRadialNode();
      wbCloseMapRadial();
      if (node) await run(node, event);
    });
  };
  radialSlot("wb-radial-child", (node, event) => (
    // Alt swaps the adds for the removes, which is Coggle's gesture. Read
    // from the event rather than from a flag the ring kept, so a keyboard
    // activation with Alt held is the same as a click with Alt held.
    event.altKey ? wbMapDeleteSubtree(node.id) : wbMapAddChild(node.id)
  ));
  radialSlot("wb-radial-sibling", (node, event) => (
    event.altKey ? wbMapRemoveKeepingBranch(node.id) : wbMapAddSibling(node.id)
  ));
  radialSlot("wb-radial-collapse", (node) => wbMapToggleCollapse(node.id));
  radialSlot("wb-radial-tidy", async (node) => {
    const moved = await wbMapTidy({ onlyBranch: node.id, quiet: true });
    toast(moved
      ? `Laid out ${moved} topic${moved === 1 ? "" : "s"}.`
      : "This branch is already where the layout puts it.");
  });
  radialSlot("wb-radial-copy", (node) => wbMapCopyBranch(node.id));
  //: **The library add, not the line's label.** The ring holds eight, and a
  //: right-click on a map node used to open the flat menu, which carried
  //: "Add from the library…": taking that away would have left the reference
  //: node reachable only from the hover row on the node itself. The line's
  //: label kept its own route, on the link ring, where a line's own property
  //: belongs.
  radialSlot("wb-radial-ref", (node) => wbMapAddReference(node.id));
  radialSlot("wb-radial-sever", (node) => wbMapSever(node.id));
  radialSlot("wb-radial-reset", (node) => wbMapResetToBranch(node.id));

  //: The link ring (§12.1 item 4). Same shape as the node ring's slots, one
  //: difference: the colour well is an `<input>`, so it listens for `change`
  //: and closes the ring itself rather than on the click that opened the
  //: browser's own picker.
  const linkNode = () => {
    if (wbMapLinkRadialFor == null) return null;
    const node = (wbState.objects || []).find((o) => o.id === wbMapLinkRadialFor);
    if (!node) wbCloseMapLinkRadial();
    return node || null;
  };
  const linkSlot = (id, run) => {
    $(id)?.addEventListener("click", async () => {
      const node = linkNode();
      wbCloseMapLinkRadial();
      if (node) await run(node);
    });
  };
  linkSlot("wb-link-reverse", (node) => wbMapReverseEdge(node.id));
  linkSlot("wb-link-label", (node) => wbMapLabelEdge(node.id));
  for (const [id, style] of [
    ["wb-link-curve", "curve"], ["wb-link-elbow", "elbow"], ["wb-link-straight", "straight"],
  ]) {
    // `curve` is stored as no value at all, the way the strip's "M" is: the
    // default has to stay the default, or a map full of nodes pinned to
    // "curve" would stop following a later change to how a map draws.
    linkSlot(id, async (node) => {
      await wbMapSetNodeStyle(node, { edge_style: style === "curve" ? null : style });
      renderWhiteboardNow();
    });
  }
  linkSlot("wb-link-dashed", async (node) => {
    await wbMapSetNodeStyle(node, { edge_dashed: !node.data?.edge_dashed || null });
    renderWhiteboardNow();
  });
  linkSlot("wb-link-cut", (node) => wbMapSever(node.id));
  $("wb-link-color")?.addEventListener("change", async (e) => {
    const node = linkNode();
    wbCloseMapLinkRadial();
    if (!node) return;
    node.data = { ...node.data, color: e.target.value };
    await wbSaveObject(node);
    renderWhiteboardNow();
  });

  //: The node edit strip (§12.1 item 2). Every handler reads the selection at
  //: the moment it fires rather than closing over a node: the strip is one set
  //: of controls that moves between nodes, so a captured node is a control
  //: that keeps editing whatever was selected when the page loaded.
  $("wb-map-bold")?.addEventListener("click", () => {
    const node = wbSelectedMapNode();
    if (node) wbMapSetNodeStyle(node, { bold: !node.data?.bold });
  });
  $("wb-map-italic")?.addEventListener("click", () => {
    const node = wbSelectedMapNode();
    if (node) wbMapSetNodeStyle(node, { italic: !node.data?.italic });
  });
  $("wb-map-text-size")?.addEventListener("change", (e) => {
    if (wbMapStripSyncing) return;
    const node = wbSelectedMapNode();
    if (node) wbMapSetNodeStyle(node, { font_size: Number(e.target.value) || null });
  });
  $("wb-map-align")?.addEventListener("change", (e) => {
    if (wbMapStripSyncing) return;
    const node = wbSelectedMapNode();
    // Empty means "auto", which is no stored alignment at all rather than
    // `left`: a node that has never been aligned and one aligned left read
    // the same on screen and must not read the same in an export.
    if (node) wbMapSetNodeStyle(node, { align: e.target.value || null });
  });
  $("wb-map-strip-icon")?.addEventListener("change", (e) => {
    if (wbMapStripSyncing) return;
    const node = wbSelectedMapNode();
    if (node) wbMapSetNodeStyle(node, { icon: e.target.value || null });
  });
  $("wb-map-shape")?.addEventListener("change", (e) => {
    if (wbMapStripSyncing) return;
    const node = wbSelectedMapNode();
    // Empty is rounded, stored as nothing at all, for the same reason "M"
    // stores no font size: a map made before shapes existed and one somebody
    // set back to rounded are the same map, and neither should carry a field.
    if (node) wbMapSetNodeStyle(node, { shape: e.target.value || null });
  });
  $("wb-map-strip-color")?.addEventListener("change", async (e) => {
    const node = wbSelectedMapNode();
    if (!node) return;
    // A colour carries down the branch, so this one *does* redraw the board:
    // every descendant's card and every edge below it changes with it.
    node.data = { ...node.data, color: e.target.value };
    await wbSaveObject(node);
    renderWhiteboardNow();
  });
  $("wb-map-strip-link")?.addEventListener("click", async () => {
    const node = wbSelectedMapNode();
    if (!node) return;
    const current = node.data?.link || "";
    const next = await promptDialog(
      "Where should this topic point? An http, https or mailto address.",
      current,
      { confirmLabel: current ? "Update the link" : "Add the link" }
    );
    //: **An empty answer changes nothing, it does not remove the link.**
    //: `promptDialog` resolves with `""` for Escape, for Cancel and for an
    //: empty field alike (`close("")` on all three paths), so "empty means
    //: remove" would make Escape destructive, which is the one thing Escape
    //: must never be. Removing a link is "Unlink" on the node radial, where
    //: a destructive action can say what it is.
    const trimmed = String(next ?? "").trim();
    if (!trimmed) return;
    if (trimmed && !WB_MAP_LINK_SCHEMES.test(trimmed)) {
      toast("A topic's link has to be an http, https or mailto address.", true);
      return;
    }
    await wbMapSetNodeStyle(node, { link: trimmed });
  });
  $("wb-map-tidy")?.addEventListener("click", async () => {
    const moved = await wbMapTidy({ quiet: true });
    toast(moved
      ? `Tidied ${moved} node${moved === 1 ? "" : "s"}.`
      : "Everything is already where this layout puts it.");
  });
  $("wb-empty-hint-close")?.addEventListener("click", () => {
    $("wb-empty-hint")?.classList.add("hidden");
  });
  $("wb-empty-hint-dismiss")?.addEventListener("click", () => {
    localStorage.setItem("wbEmptyHintDismissed", "1");
    wbHintForcedOpen = false;
    $("wb-empty-hint")?.classList.add("hidden");
  });
  // Asked for directly: a way back after "Don't show this again". Overrides
  // both the dismissed flag and the has-content check below, since without
  // that override this button would do nothing on a board that isn't empty.
  $("wb-help-btn")?.addEventListener("click", () => {
    wbHintForcedOpen = true;
    $("wb-empty-hint")?.classList.remove("hidden");
  });

  // Board background colour, asked for directly, the ambient generative-art
  // canvas showed straight through the board before this (`--wb-board-bg`,
  // declared in :root, is the fix for anyone who never touches the picker).
  // `input` previews live while dragging the swatch; `change` (fires once,
  // on release/close) is what actually persists, so dragging across ten
  // hues doesn't write ten times.
  const bgColorPicker = document.getElementById("wb-bg-color-picker");
  const bgColorReset = document.getElementById("wb-bg-color-reset");
  // The real default (the theme's --modal-bg) as a hex string, read fresh
  // each time rather than cached, the whole point of "reset to theme
  // default" is that it still means the *current* theme after a switch.
  const themeDefaultBoardHex = () => {
    const rgb = getComputedStyle(container.node()).backgroundColor;
    const m = rgb.match(/(\d+),\s*(\d+),\s*(\d+)/);
    return m ? "#" + m.slice(1, 4).map((n) => Number(n).toString(16).padStart(2, "0")).join("") : null;
  };
  if (bgColorPicker) {
    const savedBg = localStorage.getItem("wb-bg-color");
    if (savedBg) {
      container.node().style.setProperty("--wb-board-bg", savedBg);
      bgColorPicker.value = savedBg;
    } else {
      // Reflect the real default in the swatch, not an arbitrary placeholder
      // that doesn't match what's on screen.
      const hex = themeDefaultBoardHex();
      if (hex) bgColorPicker.value = hex;
    }
    bgColorPicker.addEventListener("input", (e) => {
      container.node().style.setProperty("--wb-board-bg", e.target.value);
    });
    bgColorPicker.addEventListener("change", (e) => {
      localStorage.setItem("wb-bg-color", e.target.value);
    });
  }
  // Asked for directly: once you've picked a colour there was no way back to
  // the theme's own board colour short of guessing its hex. Clearing the
  // saved override and re-reading the CSS the board falls back to (rather
  // than a hardcoded hex) means this still means "the theme's colour" after
  // a light/dark switch, not just "whatever it happened to be once".
  if (bgColorReset && bgColorPicker) {
    bgColorReset.addEventListener("click", () => {
      localStorage.removeItem("wb-bg-color");
      container.node().style.removeProperty("--wb-board-bg");
      const hex = themeDefaultBoardHex();
      if (hex) bgColorPicker.value = hex;
      toast("Board background reset to the theme default.");
    });
  }

  // Draggable toolbar panels, asked for directly. Only the small ⠿ grip
  // starts a drag: the panels are almost entirely buttons and inputs, so
  // "grab anywhere on the panel" would fight every click they already
  // handle. Clamped to `#library-view-whiteboard`'s own box, which is the
  // visible window for this view (it fills the tab below the header), so a
  // dragged panel stops at the edge instead of sliding out under the tab bar
  // or off the side of the screen.
  function makeWbPanelDraggable(panel, storageKey) {
    const grip = panel.querySelector(".wb-panel-grip");
    const bounds = document.getElementById("library-view-whiteboard");
    if (!grip || !bounds) return;

    function clamp(left, top) {
      const boundsRect = bounds.getBoundingClientRect();
      const panelRect = panel.getBoundingClientRect();
      const maxLeft = Math.max(0, boundsRect.width - panelRect.width);
      const maxTop = Math.max(0, boundsRect.height - panelRect.height);
      return [Math.min(Math.max(0, left), maxLeft), Math.min(Math.max(0, top), maxTop)];
    }

    function place(left, top) {
      panel.style.left = `${left}px`;
      panel.style.top = `${top}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
      // The bottom-center panel is horizontally centred via `left: 50%` +
      // `transform: translateX(-50%)`, a centring trick, not a drag offset.
      // Left uncleared, an explicit `left` still renders shifted left by
      // half the panel's own width, so a drag ends up visibly ~200px from
      // wherever the pointer actually released it (found by measuring, not
      // by reading the CSS, the rendered box and the styled `left` disagreed
      // by exactly panelWidth / 2).
      panel.style.transform = "none";
    }

    const saved = localStorage.getItem(storageKey);
    if (saved) {
      try {
        const { left, top } = JSON.parse(saved);
        const [cLeft, cTop] = clamp(left, top);
        place(cLeft, cTop);
      } catch {
        // A corrupt saved value is not worth failing over, the panel just
        // keeps its CSS-anchored corner instead.
      }
    }

    let dragging = false;
    let startX = 0;
    let startY = 0;
    let startLeft = 0;
    let startTop = 0;

    grip.addEventListener("pointerdown", (e) => {
      dragging = true;
      grip.setPointerCapture(e.pointerId);
      grip.classList.add("is-dragging");
      const panelRect = panel.getBoundingClientRect();
      const boundsRect = bounds.getBoundingClientRect();
      // Converts from whichever CSS corner (top-left/top-right/…) the panel
      // started anchored to into an explicit left/top box, so the first drag
      // of a session moves it from wherever it visually is rather than
      // snapping somewhere else first.
      startLeft = panelRect.left - boundsRect.left;
      startTop = panelRect.top - boundsRect.top;
      startX = e.clientX;
      startY = e.clientY;
      place(startLeft, startTop);
      e.preventDefault();
    });

    grip.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const [left, top] = clamp(startLeft + (e.clientX - startX), startTop + (e.clientY - startY));
      place(left, top);
    });

    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      grip.classList.remove("is-dragging");
      if (e?.pointerId != null) grip.releasePointerCapture?.(e.pointerId);
      localStorage.setItem(
        storageKey,
        JSON.stringify({ left: parseFloat(panel.style.left) || 0, top: parseFloat(panel.style.top) || 0 })
      );
    }
    grip.addEventListener("pointerup", endDrag);
    grip.addEventListener("pointercancel", endDrag);

    // The box can resize (window resize, the library sidebar opening) after
    // a position was saved for a larger one, reclamp so a panel never ends
    // up partly or fully off-screen.
    new ResizeObserver(() => {
      if (!panel.style.left) return;
      const [left, top] = clamp(parseFloat(panel.style.left), parseFloat(panel.style.top));
      place(left, top);
    }).observe(bounds);
  }

  document.querySelectorAll(".whiteboard-floating-panel[data-panel-id]").forEach((panel) => {
    makeWbPanelDraggable(panel, `wb-panel-pos-${panel.dataset.panelId}`);
  });

  // **The panels clear each other by measurement, not by a tuned constant.**
  //
  // Reported a third time, as "the properties and top right panel overlap
  // each other... they need to be better and more responsive". The properties
  // panel sat at a hardcoded `top: 11rem`, which is a guess at how tall the
  // top-right panel happens to be, and the CSS comment on it records the
  // guess being bumped from 6rem, then from 10rem, after the same report each
  // time. It cannot be a constant: that panel wraps its eight controls onto
  // one, two or three rows depending on the board's width, so its height is a
  // function of the viewport. The same guessing shows up twice more, the
  // gesture strip's own `bottom`, and the narrow-window rule that lifts the
  // zoom cluster by `30vh` because, as its comment says, "CSS cannot measure
  // a sibling".
  //
  // A ResizeObserver can. Each panel that others have to clear publishes its
  // own height as a custom property on the view, and every rule that needs to
  // sit above or below one derives its offset from that, so the layout is
  // correct at every width, at every wrap count, and after any change to a
  // panel's contents, with no number left to re-tune.
  //
  // Deliberately *not* wired into the drag system: a panel the reader has
  // dragged carries inline `top`/`left`, which wins over these rules anyway,
  // so a custom position keeps working exactly as before.
  const wbPanelMetricsRoot = document.getElementById("library-view-whiteboard");
  if (wbPanelMetricsRoot && typeof ResizeObserver !== "undefined") {
    // "library" is gone (its controls are in the top bar now) but the token
    // stays declared for the one rule in 06-timeline-dialogs.css that the
    // later drawer rule overrides; "topbar" and "zoom" are what the drawer,
    // the sidebar, the search bar and the overview clear today.
    for (const [panelId, name] of [["topbar", "topbar"], ["tools", "tools"], ["zoom", "zoom"]]) {
      const panel = document.querySelector(`[data-panel-id="${panelId}"]`);
      if (!panel) continue;
      const publish = () => {
        const box = panel.getBoundingClientRect();
        // A hidden panel measures 0, and a 0 here would collapse the offset
        // of whatever is clearing it right on top of the panel above. The
        // CSS fallbacks stay in charge until there is a real size to use.
        if (box.height > 0) wbPanelMetricsRoot.style.setProperty(`--wb-h-${name}`, `${Math.round(box.height)}px`);
        if (box.width > 0) wbPanelMetricsRoot.style.setProperty(`--wb-w-${name}`, `${Math.round(box.width)}px`);
      };
      publish();
      new ResizeObserver(publish).observe(panel);
    }
  }

  // Asked for directly: once a panel's been dragged there was no way back to
  // its default corner short of clearing localStorage by hand. Clears every
  // panel's saved position and its drag-time inline styles (left/top/right/
  // bottom/transform, all set by `place()` above) so each panel's own
  // top-left/top-right/bottom-center CSS class: never removed, only ever
  // overridden by the inline styles, takes back over.
  const resetPanelsBtn = document.getElementById("wb-reset-panels");
  if (resetPanelsBtn) {
    resetPanelsBtn.addEventListener("click", () => {
      document.querySelectorAll(".whiteboard-floating-panel[data-panel-id]").forEach((panel) => {
        localStorage.removeItem(`wb-panel-pos-${panel.dataset.panelId}`);
        panel.style.left = "";
        panel.style.top = "";
        panel.style.right = "";
        panel.style.bottom = "";
        panel.style.transform = "";
      });
      toast("Panel positions reset.");
    });
  }

  // Grid, snap-to-grid and a board background image (all asked for
  // directly). Each is a per-browser display preference like the board
  // colour beside them, so all three live in localStorage rather than
  // costing the notebook a schema column the server would never read.
  const gridSelect = $("wb-grid-select");
  if (gridSelect) {
    gridSelect.value = wbGridType();
    gridSelect.addEventListener("change", (e) => {
      localStorage.setItem("wb-grid", e.target.value);
      wbApplyGrid();
      // Snap only bites while a grid is visible, so the checkbox has to
      // follow the grid going away rather than silently staying "on".
      $("wb-snap-toggle").disabled = e.target.value === "none";
    });
  }
  const snapToggle = $("wb-snap-toggle");
  if (snapToggle) {
    snapToggle.checked = localStorage.getItem("wb-snap") === "on";
    snapToggle.disabled = wbGridType() === "none";
    snapToggle.addEventListener("change", (e) => {
      localStorage.setItem("wb-snap", e.target.checked ? "on" : "off");
    });
  }
  const bgImageInput = $("wb-bg-image-input");
  $("wb-bg-image")?.addEventListener("click", async () => {
    // A background already set means the button's job is to offer removing
    // it: a second "clear it" control for something most boards never use
    // would be permanent clutter on a panel that is already busy.
    if (localStorage.getItem(wbBgImageKey())) {
      if (await confirmDialog("Remove this board's background image?")) {
        localStorage.removeItem(wbBgImageKey());
        wbApplyBgImage();
        toast("Background image removed.");
        return;
      }
      return;
    }
    bgImageInput?.click();
  });
  bgImageInput?.addEventListener("change", async () => {
    const file = bgImageInput.files?.[0];
    bgImageInput.value = "";
    if (!file) return;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const uploaded = await apiJson("/media/upload", {
        method: "POST",
        headers: { "X-Auth-Token": authToken() },
        body: formData,
      });
      localStorage.setItem(wbBgImageKey(), uploaded.url);
      wbApplyBgImage();
      toast("Background image set.");
    } catch (err) {
      toast(err.message || "Couldn't set that background image.", true);
    }
  });
  wbApplyGrid();
  wbApplyBgImage();

  $("wb-clear-board")?.addEventListener("click", wbClearBoard);
  $("wb-delete-board")?.addEventListener("click", wbDeleteCurrentBoard);
  $("wb-export")?.addEventListener("click", wbExportBoard);

  // Tool Selection
  window.currentTool = "pan";
  let isDrawing = false;
  let currentDrawPath = null;
  let currentDrawData = []; // array of [x, y]
  // Reported directly: a white stroke, hardcoded regardless of theme, on a
  // light-theme board whose background (`--wb-board-bg: var(--modal-bg)`,
  // theme-aware) is itself light, drawing anything was invisible from the
  // first stroke. Defaults to black on light, white on dark, matching
  // whichever the board's own background actually resolves to; a saved
  // choice (persisted the same way the board's own background colour is)
  // always wins over the theme default.
  const savedStroke = localStorage.getItem("wb-stroke-color");
  window.currentStrokeColor =
    savedStroke || (document.documentElement.dataset.mode === "dark" ? "#ffffff" : "#000000");
  // Shared with the mousedown handler below, so the cursor preview drawn
  // here is never a different size than what actually gets drawn. Was a
  // fixed `const` (asked about directly: "does the whiteboard have a tool
  // for adjusting pen size... line/shape width?", it didn't), now `let`,
  // driven by `#wb-stroke-width` below, so every closure over this variable
  // (the highlighter's own 4x multiplier, arrowhead length, the saved
  // sketch's own width) picks up a change without needing to be rewired.
  let WB_STROKE_WIDTH = Number(localStorage.getItem("wb-stroke-width")) || 3;
  const strokeWidthInput = document.getElementById("wb-stroke-width");
  const strokeWidthBadge = document.getElementById("wb-stroke-width-badge");
  let strokeWidthBadgeTimer = null;
  function showStrokeWidthBadge() {
    if (!strokeWidthBadge || !strokeWidthInput) return;
    const r = strokeWidthInput.getBoundingClientRect();
    strokeWidthBadge.textContent = `${WB_STROKE_WIDTH}px`;
    strokeWidthBadge.style.left = `${r.left + r.width / 2}px`;
    strokeWidthBadge.style.top = `${r.top - 8}px`;
    strokeWidthBadge.classList.remove("hidden");
    clearTimeout(strokeWidthBadgeTimer);
    strokeWidthBadgeTimer = setTimeout(() => strokeWidthBadge.classList.add("hidden"), 900);
  }
  if (strokeWidthInput) {
    strokeWidthInput.value = String(WB_STROKE_WIDTH);
    strokeWidthInput.addEventListener("input", (e) => {
      WB_STROKE_WIDTH = Number(e.target.value) || 3;
      localStorage.setItem("wb-stroke-width", String(WB_STROKE_WIDTH));
      updateWbCursor();
      showStrokeWidthBadge();
    });
  }

  const toolGroup = document.getElementById("wb-tool-group");
  const arrowStyleSelect = document.getElementById("wb-arrow-style");
  // Live-reported: "I selected the line tool and it still drew with an
  // arrow head." Line and Arrow share this one control (asked for
  // directly, so a plain line *can* carry a head), but they used to share
  // a single `currentArrowStyle` value too: so drawing with Arrow first
  // (default "end") left Line permanently defaulting to an arrowhead as
  // well, since nothing ever reset it. Each tool now keeps its own
  // default (Line: none, Arrow: end) and its own localStorage key; the
  // control itself still reads/writes whichever tool is currently active,
  // via `wbCurrentEndStyleKind`/`wbSetCurrentEndStyle` below.
  window.currentLineEndStyle = localStorage.getItem("wb-line-end-style") || "none";
  window.currentArrowEndStyle = localStorage.getItem("wb-arrow-style") || "end";
  function wbCurrentEndStyleKind() {
    return window.currentTool === "line" ? "line" : "arrow";
  }
  function wbCurrentEndStyle() {
    return wbCurrentEndStyleKind() === "line" ? window.currentLineEndStyle : window.currentArrowEndStyle;
  }
  function wbSetCurrentEndStyle(value) {
    if (wbCurrentEndStyleKind() === "line") {
      window.currentLineEndStyle = value;
      localStorage.setItem("wb-line-end-style", value);
    } else {
      window.currentArrowEndStyle = value;
      localStorage.setItem("wb-arrow-style", value);
    }
  }
  wbRefreshArrowStyleControlRef = () => {
    if (arrowStyleSelect) arrowStyleSelect.value = wbCurrentEndStyle();
  };
  if (arrowStyleSelect) {
    arrowStyleSelect.value = wbCurrentEndStyle();
    arrowStyleSelect.addEventListener("change", (e) => wbSetCurrentEndStyle(e.target.value));
  }

  // Fill/stroke-style controls for the shape tools, asked for directly
  // ("stroke width, style, and colour... fill colour/transparency...
  // options for no border/stroke or background"). Persisted the same way
  // every other drawing preference here already is, so a choice survives a
  // reload instead of resetting to "no fill, solid" every session.
  const fillColorInput = document.getElementById("wb-fill-color");
  const fillOpacityInput = document.getElementById("wb-fill-opacity");
  const fillNoneInput = document.getElementById("wb-fill-none");
  const strokeStyleSelect = document.getElementById("wb-stroke-style");
  const strokeNoneInput = document.getElementById("wb-stroke-none");

  window.currentFillColor = localStorage.getItem("wb-fill-color") || "#3355ff";
  window.currentFillOpacity = Number(localStorage.getItem("wb-fill-opacity") ?? 100);
  window.currentFillNone = localStorage.getItem("wb-fill-none") !== "off"; // default on (no fill)
  window.currentDashStyle = localStorage.getItem("wb-stroke-style") || "solid";
  window.currentStrokeNone = localStorage.getItem("wb-stroke-none") === "on";

  if (fillColorInput) {
    fillColorInput.value = window.currentFillColor;
    fillColorInput.addEventListener("input", (e) => {
      window.currentFillColor = e.target.value;
      localStorage.setItem("wb-fill-color", e.target.value);
    });
  }
  if (fillOpacityInput) {
    fillOpacityInput.value = String(window.currentFillOpacity);
    fillOpacityInput.addEventListener("input", (e) => {
      window.currentFillOpacity = Number(e.target.value);
      localStorage.setItem("wb-fill-opacity", e.target.value);
    });
  }
  if (fillNoneInput) {
    fillNoneInput.checked = window.currentFillNone;
    fillNoneInput.addEventListener("change", (e) => {
      window.currentFillNone = e.target.checked;
      localStorage.setItem("wb-fill-none", e.target.checked ? "on" : "off");
    });
  }
  if (strokeStyleSelect) {
    strokeStyleSelect.value = window.currentDashStyle;
    strokeStyleSelect.addEventListener("change", (e) => {
      window.currentDashStyle = e.target.value;
      localStorage.setItem("wb-stroke-style", e.target.value);
    });
  }
  if (strokeNoneInput) {
    strokeNoneInput.checked = window.currentStrokeNone;
    strokeNoneInput.addEventListener("change", (e) => {
      window.currentStrokeNone = e.target.checked;
      localStorage.setItem("wb-stroke-none", e.target.checked ? "on" : "off");
    });
  }

  // Alignment-guide colours: asked for directly ("colours should be
  // alterable"). `wbAlignGuideColor` already reads localStorage on every
  // guide redraw, so these listeners only need to persist the choice; no
  // live guide is showing while this dropdown is open to also repaint.
  for (const kind of ["edge", "center", "spacing"]) {
    const input = document.getElementById(`wb-guide-color-${kind}`);
    if (!input) continue;
    input.value = wbAlignGuideColor(kind);
    input.addEventListener("input", (e) => {
      localStorage.setItem(`wb-guide-color-${kind}`, e.target.value);
    });
  }

  // The properties panel's own controls: each reads `wbSelectedItem` fresh
  // at change time rather than closing over it, since the panel can stay
  // open across several edits to the same selection. The two lookups these
  // use are module-level (see above `wbCopySelectedStyle`): they read only
  // `wbSelectedItem`/`wbState`, and the copy-style actions need them too.
  document.getElementById("wb-copy-style")?.addEventListener("click", wbCopySelectedStyle);
  document.getElementById("wb-paste-style")?.addEventListener("click", wbPasteCopiedStyle);
  document.getElementById("wb-prop-bold")?.addEventListener("click", () => wbWrapTextSelection("**"));
  document.getElementById("wb-prop-italic")?.addEventListener("click", () => wbWrapTextSelection("*"));
  document.getElementById("wb-prop-bullets")?.addEventListener("click", wbBulletTextLines);
  document.getElementById("wb-prop-align")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-align]");
    const item = wbSelectedTextObjectOrNull();
    if (!button || !item) return;
    item.data = { ...item.data, align: button.dataset.align };
    wbSaveObject(item);
    wbScheduleRender();
    wbUpdateContextBar();
  });
  document.getElementById("wb-prop-md")?.addEventListener("change", (event) => {
    const item = wbSelectedTextObjectOrNull();
    if (!item) return;
    item.data = { ...item.data, md: event.target.checked };
    wbSaveObject(item);
    wbScheduleRender();
  });
  // The context bar's action buttons reuse the keyboard paths exactly
  // (Ctrl+D, [ ], Delete) so the two can never disagree.
  const selBar = document.getElementById("wb-context");
  if (selBar) {
    // Keep the board's focus, but not on the controls people type into or
    // drag: swallowing mousedown on the whole bar took the caret out of the
    // width field and stopped a slider taking a drag at all.
    selBar.addEventListener("mousedown", (e) => {
      if (e.target.closest("input, select, textarea, [contenteditable=true]")) return;
      e.preventDefault();
    });
    const zOrder = (toFront) => {
      const sel = wbSelectedItem;
      const item = sel && (wbState[WB_LIST_BY_KIND[sel.kind]] || []).find((i) => i.id === sel.id);
      if (!item) return;
      wbSetZOrder(sel.kind, item, toFront).then((undo) => {
        if (undo) wbPushUndo(undo);
        wbScheduleRender();
      });
    };
    const actions = {
      "wb-selbar-duplicate": () => {
        const kept = wbClipboard;
        if (wbCopySelection()) wbPasteClipboard().finally(() => { wbClipboard = kept; });
      },
      "wb-selbar-back": () => zOrder(false),
      "wb-selbar-forward": () => zOrder(true),
      "wb-selbar-delete": () => deleteWbSelection(),
      "wb-selbar-export": () => wbExportBoard(document.getElementById("wb-selbar-export")),
    };
    for (const [id, fn] of Object.entries(actions)) {
      document.getElementById(id)?.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
    }
  }
  document.getElementById("wb-prop-color")?.addEventListener("change", async (e) => {
    const sketch = wbSelectedSketchOrNull();
    if (sketch) {
      await wbSaveSketchProps(sketch, { color: e.target.value });
      wbScheduleRender();
      return;
    }
    const obj = wbSelectedTextObjectOrNull();
    if (obj) {
      obj.data = { ...obj.data, color: e.target.value };
      await wbSaveObject(obj);
      wbScheduleRender();
    }
  });
  document.getElementById("wb-prop-width")?.addEventListener("change", async (e) => {
    const sketch = wbSelectedSketchOrNull();
    if (!sketch) return;
    const width = Math.max(1, Math.min(40, Number(e.target.value) || 3));
    await wbSaveSketchProps(sketch, { width });
    wbScheduleRender();
  });
  // Start/end cap dropdowns: independently per end (asked for directly),
  // replacing the single shared "which end gets an arrowhead" control.
  // Shared by both: reads the *other* end's current cap first (from
  // whichever field it's actually stored in, the explicit new one, or
  // the legacy `endStyle` for a link that predates it) so changing one end
  // never silently resets the other.
  async function wbSetCap(which, value) {
    const sketch = wbSelectedSketchOrNull();
    if (!sketch) return;
    let linkParsed = null;
    try {
      const candidate = JSON.parse(sketch.data);
      if (candidate && (candidate.type || "").startsWith("link-")) linkParsed = candidate;
    } catch { /* not a link */ }
    if (linkParsed) {
      // A link's caps are computed at render time from `startCap`/`endCap`
      // (`wbLinkPathD`), not baked into a stored path the way a drawn
      // arrow's is: nothing to regenerate, just persist the choice.
      const current = wbLinkCaps(linkParsed);
      current[which] = value;
      await wbSaveSketchProps(sketch, {
        startCap: current.startCap, endCap: current.endCap, endStyle: undefined,
      });
      wbScheduleRender();
      return;
    }
    const parsed = wbSketchParsedData(sketch);
    if (!parsed || !wbSketchIsArrow(parsed.d)) return;
    const current = wbSketchCaps(parsed);
    current[which] = value;
    const headLen = (parsed.width || WB_STROKE_WIDTH) * 4 + 6;
    const newD = wbRegenerateShapeCaps(parsed.d, current.startCap, current.endCap, headLen);
    await wbSaveSketchProps(sketch, { d: newD, startCap: current.startCap, endCap: current.endCap });
    wbScheduleRender();
  }
  document.getElementById("wb-prop-startcap")?.addEventListener("change", (e) => wbSetCap("startCap", e.target.value));
  document.getElementById("wb-prop-endcap")?.addEventListener("change", (e) => wbSetCap("endCap", e.target.value));
  document.getElementById("wb-prop-bg")?.addEventListener("change", async (e) => {
    const obj = wbSelectedTextObjectOrNull();
    if (!obj) return;
    obj.data = { ...obj.data, bg: e.target.value };
    document.getElementById("wb-prop-bg-none").checked = false;
    await wbSaveObject(obj);
    wbScheduleRender();
  });
  document.getElementById("wb-prop-bg-none")?.addEventListener("change", async (e) => {
    const obj = wbSelectedTextObjectOrNull();
    if (!obj) return;
    // "transparent" is a real, distinguishable value, `bg || ""` (the
    // render path) would otherwise fall back to the CSS default translucent
    // panel look for an empty string, not the "no fill at all" this asks
    // for. Asked for directly: "options for no border/stroke or background".
    obj.data = { ...obj.data, bg: e.target.checked ? "transparent" : document.getElementById("wb-prop-bg").value };
    await wbSaveObject(obj);
    wbScheduleRender();
  });
  document.getElementById("wb-prop-border")?.addEventListener("change", async (e) => {
    const obj = wbSelectedTextObjectOrNull();
    if (!obj) return;
    obj.data = { ...obj.data, border_color: e.target.value };
    document.getElementById("wb-prop-border-none").checked = false;
    await wbSaveObject(obj);
    wbScheduleRender();
  });
  document.getElementById("wb-prop-border-none")?.addEventListener("change", async (e) => {
    const obj = wbSelectedTextObjectOrNull();
    if (!obj) return;
    obj.data = { ...obj.data, border_color: e.target.checked ? "transparent" : document.getElementById("wb-prop-border").value };
    await wbSaveObject(obj);
    wbScheduleRender();
  });
  document.getElementById("wb-prop-dash")?.addEventListener("change", async (e) => {
    const sketch = wbSelectedSketchOrNull();
    if (!sketch) return;
    await wbSaveSketchProps(sketch, { dash: e.target.value === "solid" ? undefined : e.target.value });
    wbScheduleRender();
  });
  document.getElementById("wb-prop-nostroke")?.addEventListener("change", async (e) => {
    const sketch = wbSelectedSketchOrNull();
    if (!sketch) return;
    await wbSaveSketchProps(sketch, { noStroke: e.target.checked || undefined });
    wbScheduleRender();
  });
  document.getElementById("wb-prop-shapefill")?.addEventListener("change", async (e) => {
    const sketch = wbSelectedSketchOrNull();
    if (!sketch) return;
    document.getElementById("wb-prop-shapefill-on").checked = true;
    document.getElementById("wb-prop-shapefill").disabled = false;
    await wbSaveSketchProps(sketch, { fill: e.target.value, fillOpacity: 1 });
    wbScheduleRender();
  });
  document.getElementById("wb-prop-shapefill-on")?.addEventListener("change", async (e) => {
    const sketch = wbSelectedSketchOrNull();
    if (!sketch) return;
    document.getElementById("wb-prop-shapefill").disabled = !e.target.checked;
    await wbSaveSketchProps(sketch, { fill: e.target.checked ? document.getElementById("wb-prop-shapefill").value : undefined });
    wbScheduleRender();
  });
  document.getElementById("wb-prop-fontsize")?.addEventListener("change", async (e) => {
    const obj = wbSelectedTextObjectOrNull();
    if (!obj) return;
    const fontSize = Math.max(8, Math.min(200, Number(e.target.value) || 16));
    obj.data = { ...obj.data, font_size: fontSize };
    await wbSaveObject(obj);
    wbScheduleRender();
  });
  document.getElementById("wb-multi-group")?.addEventListener("click", wbGroupSelection);
  document.getElementById("wb-multi-ungroup")?.addEventListener("click", wbUngroupSelection);
  document.getElementById("wb-align-left")?.addEventListener("click", () => wbAlignSelection("left"));
  document.getElementById("wb-align-hcenter")?.addEventListener("click", () => wbAlignSelection("hcenter"));
  document.getElementById("wb-align-right")?.addEventListener("click", () => wbAlignSelection("right"));
  document.getElementById("wb-align-top")?.addEventListener("click", () => wbAlignSelection("top"));
  document.getElementById("wb-align-vcenter")?.addEventListener("click", () => wbAlignSelection("vcenter"));
  document.getElementById("wb-align-bottom")?.addEventListener("click", () => wbAlignSelection("bottom"));
  document.getElementById("wb-distribute-h")?.addEventListener("click", () => wbDistributeSelection("horizontal"));
  document.getElementById("wb-distribute-v")?.addEventListener("click", () => wbDistributeSelection("vertical"));
  document.getElementById("wb-same-width")?.addEventListener("click", () => wbSameSizeSelection("width"));
  document.getElementById("wb-same-height")?.addEventListener("click", () => wbSameSizeSelection("height"));
  document.getElementById("wb-extract-notes")?.addEventListener("click", wbExtractNotes);
  document.getElementById("wb-mindmap-tree")?.addEventListener("click", () => {
    if (wbSelectedItem?.kind === "node") wbArrangeMindMap(wbSelectedItem.id, "tree");
  });
  document.getElementById("wb-mindmap-radial")?.addEventListener("click", () => {
    if (wbSelectedItem?.kind === "node") wbArrangeMindMap(wbSelectedItem.id, "radial");
  });

  const containerEl = document.getElementById("whiteboard-container");
  const undoBtn = document.getElementById("wb-undo");

  function updateWbCursor() {
    containerEl.setAttribute("data-current-tool", window.currentTool);
    containerEl.style.cursor = wbCursorForTool(window.currentTool, window.currentStrokeColor, WB_STROKE_WIDTH);
  }

  // The six shape tools folded into the toolbar's own dropdown: asked for
  // directly ("the tool bar is getting quite long"). Kept as one list so
  // the toggle button's own icon/active-state and the arrow-style control's
  // relevance can both key off it without drifting apart.
  const WB_SHAPE_TOOLS = new Set(["line", "arrow", "rect", "circle", "triangle", "diamond"]);
  let lastShapeTool = "line"; // what a plain click on the toggle (not the caret) selects
  const shapeToggle = document.getElementById("wb-shape-toggle");
  const shapeToggleIcon = document.getElementById("wb-shape-toggle-icon");
  const shapeMenu = document.getElementById("wb-shape-menu");

  // The selection tools were a dropdown; they are three peer buttons now
  // (see index.html) so there is no toggle left to keep in sync.

  // The one place a tool switch happens, so the toolbar click and the
  // keyboard shortcuts below can never drift out of sync with each other.
  function selectWbTool(tool) {
    window.currentTool = tool;
    if (toolGroup) {
      toolGroup.querySelectorAll("button[data-tool]").forEach((b) => {
        b.classList.toggle("active", b.dataset.tool === tool);
      });
    }
    // The zoom behaviour stays attached for every tool. It used to be
    // detached for all but Pan so a drag could not fight drawing, but
    // `wbZoomFilter` (top of file) now makes that decision per event, and
    // detaching also removed **wheel zoom**, so you could not zoom or scroll
    // the canvas while any drawing tool was selected without switching tool
    // and switching back. That was a large part of the reported "constantly
    // having to switch between tools".
    container.call(wbZoom).on("dblclick.zoom", null);
    // The toggle shows whichever shape is actually active (and reads as
    // "on" the same way any other tool button does) instead of a fixed
    // icon: picking "circle" from the menu should look exactly like
    // picking "circle" used to when it was its own top-level button.
    if (shapeToggle && WB_SHAPE_TOOLS.has(tool)) {
      lastShapeTool = tool;
      const chosen = shapeMenu?.querySelector(`button[data-tool="${tool}"] svg`);
      if (chosen && shapeToggleIcon) shapeToggleIcon.innerHTML = chosen.innerHTML;
      shapeToggle.classList.add("active");
    } else if (shapeToggle) {
      shapeToggle.classList.remove("active");
    }
    if (shapeMenu && shapeToggle) wbCloseDockedMenu(shapeMenu, shapeToggle);
    wbRefreshArrowStyleControlRef?.();
    updateWbCursor();
    // The properties panel now also carries the style a drawing tool will
    // use, so a tool switch has to reopen/close it, see its own comment.
    wbUpdateContextBar();
  }

  wbSelectToolRef = selectWbTool;

  if (toolGroup) {
    toolGroup.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-tool]");
      if (btn) selectWbTool(btn.dataset.tool);
    });
  }

  // Docked as a sidebar, the toolbar panel scrolls (`overflow-y: auto`, so a
  // tall tool column fits above the canvas), three attempts at this,
  // reported directly each time: (1) CSS-only positioning was clipped by
  // that same overflow (setting only `overflow-y` coerces `overflow-x` to
  // `auto` too, clipping both axes, a real CSS rule, not a bug in that one
  // declaration). (2) `position: fixed` should escape an ancestor's overflow
  // entirely, but this panel's `.glass` class sets `backdrop-filter`, which: 
  // like `transform`/`filter`, creates a new containing block for fixed
  // descendants and traps them right back inside it. (3) toggling the whole
  // panel's `overflow` to `visible` while a menu was open avoided the clip,
  // but also uncapped the tool column's own `max-height` for as long as the
  // menu stayed open, spilling tools out past the panel's bottom edge with
  // no scrollbar to reach them.
  //
  // The only thing that both escapes the clip *and* leaves the scrolling
  // tool column alone is not being inside it: the open menu is reparented to
  // <body> (remembering where it came from, to put it back on close) and
  // positioned from the toggle's own `getBoundingClientRect()`, same as any
  // popover library would. Its own click listener below (rather than relying
  // on bubbling to #wb-tool-group's delegated one) is what makes that safe, 
  // a tool button click needs to work identically whether the menu is
  // sitting in its normal spot (bottom-docked) or reparented to <body>
  // (side-docked, open).
  function wbOpenDockedMenu(menu, toggle) {
    menu.classList.remove("hidden");
    toggle.setAttribute("aria-expanded", "true");
    const panel = toggle.closest(".whiteboard-floating-panel");
    if (panel?.dataset.dock === "side" && !menu._wbHome) {
      menu._wbHome = { parent: menu.parentNode, next: menu.nextSibling };
      document.body.appendChild(menu);
      const toggleRect = toggle.getBoundingClientRect();
      menu.style.position = "fixed";
      menu.style.left = `${toggleRect.right + 8}px`;
      menu.style.top = `${toggleRect.top}px`;
      menu.style.bottom = "auto";
      menu.style.transform = "none";
      menu.style.zIndex = "200";
      // The menu can be bigger than the toggle it opened from, the shape
      // menu's fill/stroke/guide-colour rows run well past the toolbar's
      // own height, and a toggle near the bottom of a tall docked column
      // put `top: toggleRect.top` most of the way down the screen already.
      // Reported directly ("go out of the window"). Clamped against the
      // real viewport rather than just the toggle's position: measured
      // after being placed, since its actual rendered size isn't known
      // until it's in the DOM and visible.
      const margin = 8;
      const menuRect = menu.getBoundingClientRect();
      if (menuRect.right > window.innerWidth - margin) {
        menu.style.left = `${Math.max(margin, window.innerWidth - menuRect.width - margin)}px`;
      }
      if (menuRect.bottom > window.innerHeight - margin) {
        menu.style.top = `${Math.max(margin, window.innerHeight - menuRect.height - margin)}px`;
      }
    }
  }

  function wbCloseDockedMenu(menu, toggle) {
    menu.classList.add("hidden");
    toggle.setAttribute("aria-expanded", "false");
    if (menu._wbHome) {
      menu._wbHome.parent.insertBefore(menu, menu._wbHome.next);
      menu._wbHome = null;
      menu.style.position = "";
      menu.style.left = "";
      menu.style.top = "";
      menu.style.bottom = "";
      menu.style.transform = "";
      menu.style.zIndex = "";
    }
  }

  // Asked for directly: a plain click/tap on the toggle's icon selects the
  // tool it's already showing (matching every other toolbar button, and
  // matching what the toggle looks like it should do). The picker only
  // opens from the caret, a right-click, a double-click, or, touch has
  // neither of those: holding the tool down.
  function wbWireToggleGestures(toggle, menu, getLastTool) {
    if (!toggle || !menu) return;
    const picker = toggle.parentElement; // #wb-shape-picker / #wb-select-picker
    let holdTimer = null;
    let suppressClick = false; // a long-press's own release still fires a click

    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      if (e.target.closest(".wb-shape-caret")) {
        if (menu.classList.contains("hidden")) wbOpenDockedMenu(menu, toggle);
        else wbCloseDockedMenu(menu, toggle);
      } else {
        selectWbTool(getLastTool());
      }
    });
    toggle.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      wbOpenDockedMenu(menu, toggle);
    });
    toggle.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      wbOpenDockedMenu(menu, toggle);
    });
    toggle.addEventListener("pointerdown", (e) => {
      if (e.pointerType !== "touch") return;
      holdTimer = setTimeout(() => {
        holdTimer = null;
        suppressClick = true;
        wbOpenDockedMenu(menu, toggle);
      }, 500);
    });
    const cancelHold = () => {
      if (holdTimer) {
        clearTimeout(holdTimer);
        holdTimer = null;
      }
    };
    toggle.addEventListener("pointerup", cancelHold);
    toggle.addEventListener("pointercancel", cancelHold);
    toggle.addEventListener("pointerleave", cancelHold);

    // Handled directly rather than relying on the click bubbling up to
    // #wb-tool-group's own delegated listener: once open+side-docked, the
    // menu is reparented to <body> (see wbOpenDockedMenu) and is no longer
    // a descendant of #wb-tool-group at all, so that bubbling path stops
    // reaching it. stopPropagation here is what it is safe now, unlike the
    // old bottom-docked-only version of this handler, this is the only
    // listener that will ever see the click, in either dock mode.
    menu.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-tool]");
      if (btn) {
        e.stopPropagation();
        selectWbTool(btn.dataset.tool);
      }
    });
    document.addEventListener("click", (e) => {
      if (!menu.classList.contains("hidden") && !picker.contains(e.target) && !menu.contains(e.target)) {
        wbCloseDockedMenu(menu, toggle);
      }
    });
  }

  wbWireToggleGestures(shapeToggle, shapeMenu, () => lastShapeTool);

  // Asked for directly: the toolbar should be adjustable as a sidebar, not
  // only a bottom bar. `data-dock` drives the CSS (row vs. column layout,
  // which edge it's pinned to); persisted so the choice survives a reload
  // the same way panel positions already do.
  // **Three grouped menus in the top bar, Insert, View, Board.** Asked
  // for: "add more features in the top bar and spread them out in grouped
  // section dropdowns." One `.wb-board-menu-wrap` per menu; opening one
  // closes the others; an outside click or Escape (capture phase: the
  // board's own keydown swallows Escape from a focused toolbar button)
  // closes all. The Insert menu reuses the dock's own tool buttons so the
  // two can never disagree about what a sticky or a text box is.
  //: Each menu is held by reference rather than found again through its wrap:
  //: once `escapeMenuIfClipped` has moved it to <body> it is no longer inside
  //: the wrap at all, and a `wrap.querySelector` close would find nothing and
  //: leave the menu open for good.
  const boardMenus = [...document.querySelectorAll(".wb-board-menu-wrap")]
    .map((wrap) => ({ toggle: wrap.querySelector("[data-wb-menu-toggle]"), menu: wrap.querySelector(".wb-board-menu") }))
    .filter((pair) => pair.toggle && pair.menu);
  const closeAllWbMenus = () => {
    for (const { toggle, menu } of boardMenus) {
      menu.classList.add("hidden");
      toggle.setAttribute("aria-expanded", "false");
      // Back where it lives, and the stylesheet's own cap back: the next open
      // measures from scratch rather than from a stale number.
      restoreEscapedMenu(menu);
      menu.style.maxHeight = "";
    }
  };
  //: **A top-bar menu stays inside the window and scrolls when it is taller.**
  //:
  //: Reported with a screenshot of the View menu (INBOX 43): the menus "clip
  //: at the bottom of the panel and do not scroll". A cap alone was not the
  //: whole story: measured at 1280x640 with a board open, View and Arrange
  //: both ended at y=628 inside a 640px window, correctly capped, while
  //: `#library-view-whiteboard` (`overflow: hidden`) ends at y=579, so the
  //: last 49px of each menu were cut off by an ancestor and unreachable,
  //: scrollbar or no scrollbar. Escaping that ancestor is what fixed it.
  //:
  //: `escapeAndCapMenu` (app.js) is that fix, and `details.dock-menu`'s too:
  //: this file used to hold its own copy of it, identical down to the margin
  //: and the 120px floor, which is how a later improvement to one of them
  //: would have missed the other. It is deliberately not the same recipe as
  //: `wireEscapedActionMenu`'s `place()`, which positions its menu itself;
  //: these menus keep the position the stylesheet gives them whenever nothing
  //: clips them, and only their height is decided. The reasons are written out
  //: at both functions in app.js.
  for (const { toggle, menu } of boardMenus) {
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      const wasHidden = menu.classList.contains("hidden");
      closeAllWbMenus();
      if (wasHidden) {
        menu.classList.remove("hidden");
        toggle.setAttribute("aria-expanded", "true");
        // Before the measurement: a switch's own state can change how tall
        // the list is.
        syncPanelSwitches();
        escapeAndCapMenu(menu, toggle);
      }
    });
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest(".wb-board-menu, .wb-board-menu-wrap")) return;
    // A Panels switch forwards to the top bar's own toggle with a synthetic
    // `.click()`, which bubbled here as an "outside" click and shut the
    // menu the moment a switch was used (reported). Only a real pointer
    // or keyboard click outside the menu closes it.
    if (!e.isTrusted) return;
    closeAllWbMenus();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAllWbMenus();
  }, true);
  // Edit / Arrange menu items forward to the control that already owns the
  // action (`data-wb-click`), so a menu can never drift from the dock, the
  // drawer or the selection bar. `data-wb-fn` is for the one action with
  // no button of its own.
  document.addEventListener("click", (e) => {
    const item = e.target.closest(".wb-board-menu [data-wb-click], .wb-board-menu [data-wb-fn]");
    if (!item) return;
    e.stopPropagation();
    closeAllWbMenus();
    if (item.dataset.wbFn === "select-all") { wbSelectAllItems(); return; }
    document.getElementById(item.dataset.wbClick)?.click();
  });
  //: **A board can change its mind.** Reported: "when I press the boards
  //: dropdown to change boards, I cant tell which one is a whiteboard and
  //: which one is a mindmap". The picker has grouped the two kinds under
  //: `<optgroup>` since MINDMAP_PLAN §5 item 12, and it can only group boards
  //: that say which kind they are: `_board_settings` defaults every board that
  //: predates maps to "board", which is the right default and the wrong answer
  //: for a board somebody has been using as a map ever since. The route has
  //: taken a `type` from the beginning (`rename_board`, "also where a board
  //: becomes a map and back"); nothing in the app ever sent one.
  //:
  //: The default scratch board has no note behind it and so no settings to
  //: store, which is why the control says so rather than failing quietly.
  document.getElementById("wb-board-kind")?.addEventListener("click", async () => {
    closeAllWbMenus();
    const boardId = window.currentBoardId ?? null;
    if (!boardId) {
      toast("The default board cannot change kind. Make a new board to start a mind map.", true);
      return;
    }
    const becomingMap = !wbIsMap();
    try {
      await apiJson(`/whiteboard/boards/${boardId}`, {
        method: "PUT",
        body: JSON.stringify({ type: becomingMap ? "map" : "board" }),
      });
    } catch (error) {
      toast(error.message || "That board could not be changed.", true);
      return;
    }
    //: Reopened rather than patched in place: the two kinds draw different
    //: chrome, different tools and a different renderer, and a half-switched
    //: board is the shape of bug this file has had before.
    await openWhiteboardBoard(boardId);
    toast(becomingMap ? "Now a mind map." : "Now a whiteboard.");
  });

  document.getElementById("wb-insert-menu")?.addEventListener("click", (e) => {
    const choice = e.target.closest("[data-wb-insert]");
    if (!choice) return;
    closeAllWbMenus();
    const what = choice.dataset.wbInsert;
    if (what === "image") document.getElementById("wb-add-image")?.click();
    else if (what === "note") document.getElementById("wb-add-note")?.click();
    else document.querySelector(`#wb-tool-group [data-tool="${what}"]`)?.click();
  });

  // **Panels, managed in one place.** Asked for: "there needs to be a window
  // option to manage what windows are showing and not". Four switches in
  // the Board menu: Context bar (a preference: off means the bar never
  // opens, even with a selection; the class is read by CSS), and Overview,
  // Library and Search, which are the same toggles the top bar carries,
  // shown as on/off so their state can be read without hunting for them.
  const propsPref = document.getElementById("wb-panel-props");
  const viewHost = document.getElementById("library-view-whiteboard");
  //: The class and the switch now govern the context bar, which is what
  //: replaced the drawer this preference was written for. The storage key is
  //: unchanged on purpose: a person who turned the drawer off once should not
  //: have the new surface turn itself back on under them.
  const applyPropsPref = (on) => {
    viewHost?.classList.toggle("wb-hide-context", !on);
    if (propsPref) propsPref.checked = on;
  };
  applyPropsPref(localStorage.getItem("wb-panel-props") !== "off");
  propsPref?.addEventListener("change", () => {
    localStorage.setItem("wb-panel-props", propsPref.checked ? "on" : "off");
    applyPropsPref(propsPref.checked);
  });
  const panelSwitches = [
    ["wb-panel-overview", "wb-navigator", "wb-navigator-toggle"],
    ["wb-panel-library", "whiteboard-sidebar", "wb-add-note"],
    ["wb-panel-search", "wb-search-bar", "wb-search-toggle"],
  ];
  function syncPanelSwitches() {
    for (const [switchId, panelId] of panelSwitches) {
      const sw = document.getElementById(switchId);
      const panel = document.getElementById(panelId);
      if (sw && panel) sw.checked = !panel.classList.contains("hidden");
    }
  }
  for (const [switchId, , toggleId] of panelSwitches) {
    document.getElementById(switchId)?.addEventListener("change", () => {
      document.getElementById(toggleId)?.click();
      syncPanelSwitches();
    });
  }

  const toolsPanel = document.getElementById("wb-tools-panel");
  const dockToggle = document.getElementById("wb-dock-toggle");
  if (toolsPanel && dockToggle) {
    const applyDock = (dock) => {
      toolsPanel.dataset.dock = dock;
      dockToggle.title = dock === "bottom" ? "Dock as a sidebar" : "Dock as a bottom bar";
      // The button reads as the current state, the tooltip as the action.
      setLabel(dockToggle, dock === "bottom" ? "ph:sidebar-simple Bottom" : "ph:sidebar-simple Side");
    };
    applyDock(localStorage.getItem("wb-toolbar-dock") || "bottom");
    dockToggle.addEventListener("click", () => {
      const next = toolsPanel.dataset.dock === "bottom" ? "side" : "bottom";
      localStorage.setItem("wb-toolbar-dock", next);
      applyDock(next);
    });
  }

  // **The ink swatch on the rail is the drawing colour** (WHITEBOARD_PLAN.md
  // decision 1). It was a row in the properties drawer as well until Phase 2
  // removed that drawer; one control for one setting, on the surface that
  // holds the tool it belongs to.
  //
  // `input` as well as `change`: a native colour picker fires `input`
  // continuously while a colour is being dragged and `change` once at the end,
  // and a swatch that only catches up when the dialog closes is exactly the
  // "does this control do anything" read this group exists to fix.
  const railInk = document.getElementById("wb-rail-ink");
  if (railInk) {
    railInk.value = window.currentStrokeColor;
    for (const type of ["input", "change"]) {
      railInk.addEventListener(type, (e) => {
        window.currentStrokeColor = e.target.value;
        localStorage.setItem("wb-stroke-color", e.target.value);
        updateWbCursor();
      });
    }
  }

  if (undoBtn) {
    undoBtn.disabled = true;
    undoBtn.addEventListener("click", wbUndo);
  }
  const redoBtn = document.getElementById("wb-redo");
  if (redoBtn) {
    redoBtn.disabled = true;
    redoBtn.addEventListener("click", wbRedo);
  }

  // Keyboard shortcuts, asked for as part of the wider usability pass: a
  // toolbar of eight icon buttons is not obviously faster than the tool you
  // already have your hand on, and every serious drawing app (Figma,
  // Excalidraw, tldraw) uses this exact letter set for exactly that reason, 
  // muscle memory transfers in, rather than having to be learned from
  // scratch. Guarded to the whiteboard sub-tab and away from anything with
  // its own idea of what typing means (an input, a textarea, a
  // contenteditable note), the same guard the app's other global shortcuts
  // already use.
  const WB_TOOL_KEYS = {
    // V selects and H is the hand, the way every whiteboard people already
    // know binds them. V used to be Pan (and S Select); S stays as an alias
    // so the old habit still works.
    v: "select",
    h: "pan",
    s: "select",
    k: "lasso",
    p: "draw",
    m: "highlighter",
    l: "line",
    a: "arrow",
    r: "rect",
    o: "circle",
    g: "triangle",
    d: "diamond",
    t: "text",
    e: "eraser",
    b: "bucket",
    x: "delete",
    // WHITEBOARD_PLAN.md decision 8 names N for the sticky and C for the
    // connector; both were tools with no key at all, which the Phase 1 sweep
    // measured ("18 tools, 3 without a key"). The board has *two* connectors
    // and the decision names one letter, so the second takes the shifted form
    // of the same letter (recorded in INBOX with its recommendation rather
    // than decided here; see `WB_TOOL_SHIFT_KEYS` below).
    n: "sticky",
    c: "link-straight",
  };
  // Shift + the same letter, for the second tool of a pair. One table rather
  // than an `if` beside the dispatch, so a third pair cannot be added in a
  // different shape.
  const WB_TOOL_SHIFT_KEYS = {
    c: "link-curved",
  };
  // Keys that press a button rather than pick a tool: uploading an image is an
  // action with a file dialog behind it, not a mode you hold. Declared on the
  // markup (`data-wb-key`) so the sweep reads the same source the tooltip does.
  const WB_ACTION_KEYS = {
    i: "wb-add-image",
  };
  // Held space = pan, from whatever tool you are holding. The flag is read by
  // `wbZoomFilter`; nothing about the active tool changes, so releasing space
  // puts you back exactly where you were rather than in a different mode.
  //
  // The cursor changes with it, because a modifier that alters what a drag
  // does has to say so before the drag, a grab cursor is how every canvas
  // app signals this, and without it "space does something" is a secret.
  const wbCanvasEl = () => document.getElementById("whiteboard-container");
  function wbSetSpaceHeld(held) {
    if (wbSpaceHeld === held) return;
    wbSpaceHeld = held;
    const el = wbCanvasEl();
    if (el) el.classList.toggle("wb-space-pan", held);
  }
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space") wbSetSpaceHeld(false);
  });
  // A board left while space is down would otherwise stay stuck in pan.
  window.addEventListener("blur", () => wbSetSpaceHeld(false));

  // **Clicking the board gives the board the keyboard.** Single-key
  // shortcuts are guarded (correctly) against firing while a field has
  // focus, but a canvas is not focusable by default, so clicking it left
  // focus wherever it happened to be, on whatever control was touched last,
  // or on the lock screen's own password field for a freshly unlocked app.
  // `tabindex="-1"` (index.html) plus this makes the board take focus the way
  // every other surface does, so the tool keys work after clicking the thing
  // they act on. Out of the tab order deliberately: it is a canvas, not a
  // stop on the keyboard path through the page.
  container.node()?.addEventListener("pointerdown", (e) => {
    // Any editable body, not the two class names that were editable when
    // this was written: pulling focus to the canvas out from under a map
    // node's editor is the other half of "I cant highlight text in mindmap
    // text boxes", the caret went to the container mid-gesture.
    if (e.target.closest(".whiteboard-floating-panel, [contenteditable=true]")) return;
    document.getElementById("whiteboard-container")?.focus({ preventScroll: true });
  });

  document.addEventListener("keydown", (e) => {
    const view = document.getElementById("library-view-whiteboard");
    if (!view || view.classList.contains("hidden")) return;
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    // Ctrl+F is deliberately *not* bound here. The app already owns it for
    // "Find on this page", and binding it a second time opened both bars at
    // once: `preventDefault` does not stop another listener, only the
    // browser. `openGlobalFind` in app.js now hands off to the board search
    // when a board is open, which is one owner for one shortcut and the same
    // shape as the handoff it already does for the lightbox's find.
    // `offsetParent` is the visibility half, and it is load-bearing: the lock
    // overlay's own password field keeps DOM focus after the overlay is
    // hidden, so on a freshly unlocked app `activeElement` is an `<input>`
    // that nobody can see or type into, and this guard then swallowed every
    // single-key shortcut on the board (V/H/P, `n`, `/`) for the whole
    // session. Measured, not guessed: `document.activeElement` read
    // `INPUT#lock-password` on a board that had been open for minutes. A
    // field you cannot see is not a field you are typing in.
    const active = document.activeElement;
    const typing = active
      && (tag === "input" || tag === "textarea" || active.isContentEditable)
      && active.offsetParent !== null;
    if (typing) return;
    // **Shift+N for the overview, because bare N is the sticky note**
    // (WHITEBOARD_PLAN.md decision 8). This took the bare letter first,
    // "matching the single-letter tool keys this board already uses", and the
    // plan then gave that letter to a tool, which is the collision the Phase 1
    // sweep found: N selected nothing and opened the overview instead. Same
    // letter shifted rather than a third letter invented, the same shape the
    // second connector takes on Shift+C. Modifier chords are still left alone
    // so Ctrl+N opens a browser window.
    // `e.shiftKey` plus the lower-cased letter, not `e.key === "N"`: a real
    // keyboard reports the shifted letter as "N", but not every source does
    // (Playwright's own `Shift+n` sends shiftKey with key "n"), and the rest
    // of this handler already reads letters the lower-cased way.
    if (e.shiftKey && e.key.toLowerCase() === "n" && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      wbToggleNavigator();
      return;
    }
    // "/" is the other find idiom, and costs nothing to support.
    if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      wbOpenBoardSearch();
      return;
    }
    if (e.code === "Space") {
      //: **Space stays the pan, except on a fold control** (MINDMAP_PLAN.md
      //: §12.0). §12.1 item 7 asks for "reopens on click and on Space", and
      //: held space is this canvas's pan gesture from every tool
      //: (`wbZoomFilter`): a map node is selected nearly all the time once
      //: someone is editing, so binding Space to collapse would take the pan
      //: away exactly when it is most used, and would make a map pan
      //: differently from a board. So Space folds a branch where the plan
      //: asked it to, on the fold control itself: with the keyboard focus on
      //: a node's chevron or the dock's Collapse button, this handler stands
      //: aside and the browser's own button activation runs. `C` is the key
      //: for the same thing with the canvas focused (below).
      if (document.activeElement?.closest(".wb-map-collapse, #wb-map-collapse")) return;
      // preventDefault so the page does not scroll under the board, and so a
      // focused toolbar button is not "clicked" by the space that is panning.
      e.preventDefault();
      wbSetSpaceHeld(true);
      return;
    }
    // Escape cascades one level at a time, the way every editor does it:
    // with something selected it clears the selection and leaves the tool
    // alone; with nothing selected it returns to Select. One key that did
    // both at once meant deselecting a shape mid-pen-session also threw
    // away the pen.
    if (e.key === "Escape") {
      // A selection drag in flight (or a rectangle a previous one left
      // behind) goes first, Escape is where people reach when something is
      // stuck on the canvas, and it did nothing about this before.
      wbClearSelectionOverlays();
      if (wbSelectedItem || wbMultiSelection.size > 0) clearWbSelection();
      else selectWbTool("select");
      return;
    }
    // --- a map's own keys (MINDMAP_PLAN.md §5 item 5) ----------------------
    //
    // Obsidian Canvas Mindmap's set, which is the de-facto standard, and the
    // reason this block sits *above* the card gestures and the arrow-key
    // nudge below rather than beside them: on a map, Delete means "this
    // subtree, undoably" and the arrows mean "walk the tree", both of which
    // the generic handlers further down would otherwise have already claimed.
    // Every branch returns, so nothing here falls through to them.
    const mapNode = wbSelectedMapNode();
    if (mapNode) {
      if (e.key === "Tab") {
        e.preventDefault();
        // Shift+Tab outdents. Through `/move`, which is the only endpoint
        // that runs the cycle check, see `wbMapOutdent`.
        if (e.shiftKey) wbMapOutdent(mapNode.id);
        else wbMapAddChild(mapNode.id);
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        wbMapAddSibling(mapNode.id);
        return;
      }
      if (e.key === "F2") {
        e.preventDefault();
        wbMapEditNode(mapNode.id);
        return;
      }
      //: C folds and unfolds the selected branch, the canvas-focused half of
      //: the Space decision above. A letter rather than a modifier chord
      //: because it sits beside the map's other bare keys (Tab, Enter, F,
      //: the arrows). `c` became the connector's key on a *board*
      //: (WHITEBOARD_PLAN decision 8, `WB_TOOL_KEYS`), and Connect is one of
      //: the three sections a map keeps. The two never collide because this
      //: branch runs only with a map node selected and returns: with a topic
      //: in hand C folds it, with nothing selected C reaches for the
      //: cross-link, which is the only thing C could usefully mean there.
      if ((e.key === "c" || e.key === "C") && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        wbMapToggleCollapse(mapNode.id);
        return;
      }
      //: F focuses here, and F again lets the whole map back (§5 item 18).
      //: One key for both directions because focus is a mode you look through
      //: rather than a thing you set: the way out has to be as cheap as the
      //: way in, or people stop using it.
      if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        if (wbMapFocusState && wbMapFocusState.id === mapNode.id) wbMapClearFocus();
        else wbMapSetFocus(mapNode.id);
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        wbMapDeleteSubtree(mapNode.id);
        return;
      }
      // The arrows walk the tree, but only unmodified. Shift/Ctrl arrows stay
      // with the nudge below, so a node that genuinely needs moving by hand
      // still can be.
      if (
        ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)
        && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey
      ) {
        e.preventDefault();
        wbMapNavigate(mapNode.id, e.key);
        return;
      }
    }

    // Delete/Backspace with a selection, the other half of Select as a
    // real tool: previously the only way to delete anything was switching
    // to the Delete tool and clicking it.
    // wbMultiSelection alongside wbSelectedItem: deleteWbSelection() already
    // handles a marquee multi-select correctly, but this guard only ever
    // checked the single-item variable - the two are mutually exclusive by
    // construction, so a multi-selection left this false and Delete/
    // Backspace silently did nothing. Reported directly.
    if ((e.key === "Delete" || e.key === "Backspace") && (wbSelectedItem || wbMultiSelection.size > 0)) {
      e.preventDefault();
      deleteWbSelection();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z") {
      e.preventDefault();
      wbUndo();
      return;
    }
    // Both common redo chords: Ctrl+Shift+Z (the sketch pad's own
    // convention) and Ctrl+Y (Windows' more familiar one).
    if (
      (e.ctrlKey || e.metaKey) &&
      ((e.shiftKey && e.key.toLowerCase() === "z") || (!e.shiftKey && e.key.toLowerCase() === "y"))
    ) {
      e.preventDefault();
      wbRedo();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "c") {
      if (wbCopySelection()) e.preventDefault();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "x") {
      if (wbCutSelection()) e.preventDefault();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "v") {
      e.preventDefault();
      wbPasteClipboard();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "g") {
      e.preventDefault();
      wbUngroupSelection();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "g") {
      e.preventDefault();
      wbGroupSelection();
      return;
    }
    // Mind-mapping's keyboard-driven branch entry (item 25's second piece,
    // asked for directly): Tab adds a linked child of the selected card,
    // Enter adds a sibling. The actual ergonomic difference between "a
    // whiteboard you can draw a mind map on" and "a mind-mapping tool", 
    // dragging cards one at a time to fake this defeats the point of
    // having it. Guarded to a single selected *card*, a sketch or object
    // has no "branch" of its own to add one to.
    if (e.key === "Tab" && wbSelectedItem?.kind === "node") {
      e.preventDefault();
      wbMindMapAddChild(wbSelectedItem.id);
      return;
    }
    if (e.key === "Enter" && wbSelectedItem?.kind === "node") {
      e.preventDefault();
      wbMindMapAddSibling(wbSelectedItem.id);
      return;
    }
    // Arrow-key nudge, asked for directly. Grid step while snap is on (the
    // nudge should land on the same grid a drag would), else 1px/10px, 
    // Shift for the bigger jump, the same convention a slider's own arrow
    // keys use elsewhere in this app.
    if (
      ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key) &&
      (wbSelectedItem || wbMultiSelection.size > 0)
    ) {
      e.preventDefault();
      const step = wbSnapOn() ? WB_GRID_SPACING : e.shiftKey ? 10 : 1;
      const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
      const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
      wbNudgeSelection(dx, dy);
      return;
    }
    // Copy/paste style: Ctrl+Alt+C / Ctrl+Alt+V, the chord Excalidraw uses,
    // and checked before the modifier bail-out below since it *is* a chord.
    if ((e.ctrlKey || e.metaKey) && e.altKey && !e.shiftKey) {
      const key = e.key.toLowerCase();
      if (key === "c") { e.preventDefault(); wbCopySelectedStyle(); return; }
      if (key === "v") { e.preventDefault(); wbPasteCopiedStyle(); return; }
    }
    // Ctrl+D duplicates the selection in place (PLAN.md W6): the chord
    // Figma, Miro and tldraw share. Implemented as copy+paste through the
    // clipboard the app already has, with the clipboard put back afterwards
    // so a duplicate never overwrites something you meant to paste later.
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "a") {
      e.preventDefault();
      wbSelectAllItems();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "d") {
      e.preventDefault();
      const kept = wbClipboard;
      if (wbCopySelection()) wbPasteClipboard().finally(() => { wbClipboard = kept; });
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return; // leave browser/OS shortcuts alone
    // `[` sends the selected item back, `]` brings it forward (PLAN.md W6).
    // Same keys as Figma/Sketch; the z helpers already existed for the
    // context menu, this only gives them a key.
    if ((e.key === "[" || e.key === "]") && wbSelectedItem) {
      const sel = wbSelectedItem;
      const item = (wbState[WB_LIST_BY_KIND[sel.kind]] || []).find((i) => i.id === sel.id);
      if (item) {
        e.preventDefault();
        wbSetZOrder(sel.kind, item, e.key === "]").then((undo) => {
          if (undo) wbPushUndo(undo);
          wbScheduleRender();
        });
        return;
      }
    }
    const letter = e.key.toLowerCase();
    // Shift first: `e.key` for Shift+C is "C", which lower-cases onto the
    // unshifted tool, so reading the shift table second would make the two
    // connectors unreachable from each other.
    // A shifted letter with no pair still picks the unshifted tool, which is
    // what it did before this table existed: Shift+P has always been the pen.
    const mapped = (e.shiftKey && WB_TOOL_SHIFT_KEYS[letter]) || WB_TOOL_KEYS[letter];
    if (mapped) {
      if (mapped !== "select") clearWbSelection(); // switching away from Select drops it
      selectWbTool(mapped);
      return;
    }
    if (WB_ACTION_KEYS[letter]) {
      const btn = document.getElementById(WB_ACTION_KEYS[letter]);
      if (btn) {
        e.preventDefault();
        btn.click();
      }
    }
  });

  // Opens in Select, like every whiteboard app, panning is always
  // available on held space and the middle mouse button regardless.
  selectWbTool("select"); // the initial state

  // Drawing event handlers on the SVG itself or container
  const svgCanvas = document.getElementById("wb-svg-layer");
  
  function getLogicalMouse(e) {
    const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
    const rect = svgCanvas.getBoundingClientRect();
    const x = (e.clientX - rect.left - transform.x) / transform.k;
    const y = (e.clientY - rect.top - transform.y) / transform.k;
    return [x, y];
  }
  
  // The eraser doesn't draw: it deletes whatever the pointer crosses while
  // held, which is renderWhiteboard's job (it owns the sketch/node elements
  // this has to hit-test against). All this needs to track is "is the
  // button currently down", on the container so it works over both the SVG
  // sketch layer and the HTML card layer.
  // Pointer events, not mouse events: they unify mouse/touch/pen into one
  // stream, which is what lets a finger draw, erase and pan here at all, 
  // touch never dispatches "mouse*" events reliably, and never dispatches
  // them for a stylus. `touch-action: none` on .whiteboard-container (CSS)
  // is the other half of this: without it the browser eats the gesture for
  // page-scroll before a single pointer event reaches here.
  containerEl.addEventListener("pointerdown", (e) => {
    if (window.currentTool === "eraser") {
      wbErasing = true;
      // Reported directly: "with the eraser, I can't touch and drag to
      // delete items" (the pen works fine touch-dragged the same way).
      // Touch, unlike a mouse, implicitly captures the pointer to
      // whatever element received this pointerdown, so a dragging finger
      // never fires `pointerenter` on the *other* sketches/cards it passes
      // over; the eraser's per-element `pointerenter` handlers (below) can
      // only ever catch the one thing first touched. Releasing capture
      // explicitly restores normal per-element pointer events for the rest
      // of the gesture, and `pointermove` here (coordinate-based, not
      // target-based) is the second half, it doesn't depend on capture
      // behaving correctly at all, so it also covers browsers/pens where
      // pointerenter is delivered unreliably during a fast drag.
      e.target.releasePointerCapture?.(e.pointerId);
    }
  });
  window.addEventListener("pointerup", () => {
    wbErasing = false;
  });
  containerEl.addEventListener("pointermove", (e) => {
    if (window.currentTool !== "eraser" || !wbErasing) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const sketchEl = el?.closest(".sketch-group");
    if (sketchEl) {
      const item = wbState.sketches.find((s) => s.id === Number(sketchEl.dataset.id));
      if (item) wbDeleteSketchRef?.(item);
      return;
    }
    const cardEl = el?.closest(".node-card");
    if (cardEl) {
      const item = wbState.nodes.find((n) => n.id === Number(cardEl.dataset.id));
      if (item) wbDeleteNodeRef?.(item);
      return;
    }
    const objEl = el?.closest(".wb-object");
    if (objEl) {
      const item = (wbState.objects || []).find((o) => o.id === Number(objEl.dataset.id));
      if (item) wbDeleteObjectRef?.(item);
    }
  });
  // Clicking empty canvas with Select active clears the selection, every
  // card/sketch's own click handler calls stopPropagation() under Select,
  // so a click that reaches here was never on an item. A completed marquee
  // drag (below) also ends on empty canvas, which fires this same native
  // `click` right afterward (unlike d3.drag, a plain addEventListener drag
  // gets no automatic click-suppression), `wbMarqueeJustSelected` is the
  // one-shot flag that stops it from wiping out the selection the marquee
  // just made.
  containerEl.addEventListener("click", (e) => {
    if (window.currentTool === "select" || window.currentTool === "lasso") {
      if (wbMarqueeJustSelected) {
        wbMarqueeJustSelected = false;
      } else {
        clearWbSelection();
        // The other half of the Escape fix: a click on empty canvas is the
        // first thing anyone tries on a rectangle that will not go away.
        wbClearSelectionOverlays();
      }
    }
    // A text box is placed by clicking, not dragged like a shape, it has
    // no natural "size while dragging" the way a rect does, so click-to-drop
    // at a sensible default size (typed into afterward) is the same model
    // OneNote and every sticky-note tool already use.
    // No `e.target` check: like the Select-clear branch above, this relies
    // on an item's own click handler having already called stopPropagation()
    // if the click actually landed on a card/sketch/object, a click that
    // reaches here bubbled up from truly empty canvas either way.
    if (window.currentTool === "text") {
      const [x, y] = getLogicalMouse(e);
      wbCreateTextBox(x, y);
    }
    if (window.currentTool === "sticky") {
      const [x, y] = getLogicalMouse(e);
      wbCreateSticky(x, y);
    }
  });

  // Rectangle marquee select: reported directly ("area select... missing").
  // Only engages when the pointerdown target is genuinely empty canvas: a
  // card/sketch/object's own drag already claims the gesture otherwise (the
  // node/object drags' `.filter()`, the sketch drag's own tool check), so
  // checking the target here is enough without a second stopPropagation
  // dance.
  //
  // **The handle layer has to be in this list, and stopPropagation cannot
  // stand in for it.** Reported: "when I adjust things like links, the area
  // select happens too", dragging a link's endpoint drew a selection
  // marquee across the board at the same time. The endpoint handles are not
  // inside `.sketch-group`; they live in their own `.wb-sketch-handle-group`
  // over in `#wb-overlay-zoom-group`, precisely so a card can sit above the
  // base layer without burying them. So they passed this test as empty
  // canvas.
  //
  // Their drag does call `stopPropagation` on d3-drag's "start", and that is
  // why this looked correct. It fires on the wrong event: d3-drag listens for
  // `mousedown`, this listens for `pointerdown`, and a pointerdown is
  // dispatched *before* the compatibility mousedown it generates. By the time
  // the handle stops propagation the marquee has already begun. Two event
  // families cannot cancel each other, so the target check is the only place
  // this can be fixed.
  function wbIsEmptyCanvasTarget(target) {
    return !target.closest?.(
      ".node-card, .sketch-group, .wb-object, .wb-sketch-handle-group, .wb-resize-handle",
    );
  }
  function rectsIntersect(ax, ay, aw, ah, bx, by, bw, bh) {
    return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
  }
  let wbMarqueeStart = null;
  let wbMarqueeEl = null;
  let wbMarqueeJustSelected = false;
  //: End the marquee gesture and take its rectangle off the canvas. Every
  //: exit from the drag goes through here, the completed one, the cancelled
  //: one, and the sweep `wbClearSelectionOverlays` runs, so there is exactly
  //: one place that can forget to remove the element.
  function wbEndMarqueeDrag() {
    wbMarqueeEl?.remove();
    wbMarqueeEl = null;
    wbMarqueeStart = null;
  }
  containerEl.addEventListener("pointerdown", (e) => {
    if (window.currentTool !== "select" || !wbIsEmptyCanvasTarget(e.target)) return;
    // Primary button only. A right-click opens the context menu and a middle
    // click pans; neither ends with the pointerup this drag is waiting for,
    // so both used to start a rectangle that nothing would ever remove.
    if (e.button !== 0 || !e.isPrimary) return;
    // A gesture already in flight loses its rectangle rather than orphaning
    // it: `wbMarqueeEl` is one variable, so a second pointerdown overwrote
    // the reference to the first rect and left it on the canvas forever.
    wbEndMarqueeDrag();
    const [x, y] = getLogicalMouse(e);
    wbMarqueeStart = { x, y, shiftKey: e.shiftKey, pointerId: e.pointerId };
    wbMarqueeEl = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    wbMarqueeEl.setAttribute("class", "wb-marquee");
    wbMarqueeEl.setAttribute("x", x);
    wbMarqueeEl.setAttribute("y", y);
    wbMarqueeEl.setAttribute("width", 0);
    wbMarqueeEl.setAttribute("height", 0);
    //: **The overlay layer, above the cards.** INBOX 84: "whiteboard
    //: rectangle selection draws behind objects." `#wb-zoom-group` lives in
    //: `#wb-svg-layer`, which is *under* `#wb-html-layer` by DOM order, on
    //: purpose, so a pen stroke passes behind a card. A marquee is the
    //: opposite case: it says what you are about to select, and a rectangle
    //: hidden behind the very things it is selecting says nothing. The lasso
    //: has always gone to `#wb-overlay-zoom-group` for exactly this reason
    //: (see its own append below); the rectangle never did.
    document.getElementById("wb-overlay-zoom-group").appendChild(wbMarqueeEl);
    // **The capture is the fix.** Without it every pointermove and pointerup
    // outside the container went to whatever element was under the cursor,
    // so a drag that ended over the top bar, over the left rail or off the
    // window simply never finished, and left its rectangle behind.
    try {
      containerEl.setPointerCapture(e.pointerId);
    } catch (err) {
      // A synthetic pointerdown (a test, an assistive tool) has no real
      // pointer to capture. The window-level listeners below still end it.
    }
  });
  window.addEventListener("pointermove", (e) => {
    if (!wbMarqueeStart) return;
    const [x, y] = getLogicalMouse(e);
    const mx = Math.min(wbMarqueeStart.x, x), my = Math.min(wbMarqueeStart.y, y);
    const w = Math.abs(x - wbMarqueeStart.x), h = Math.abs(y - wbMarqueeStart.y);
    wbMarqueeEl.setAttribute("x", mx);
    wbMarqueeEl.setAttribute("y", my);
    wbMarqueeEl.setAttribute("width", w);
    wbMarqueeEl.setAttribute("height", h);
  });
  // Anchor points weren't discoverable until a link drag was already under
  // way: asked for directly: "when I hover over objects, their anchor
  // points should display... so I can connect them." A plain hover with a
  // link-type tool selected, no drag started yet, now shows the same 8
  // fixed-point hints the in-progress drag already draws (`wbShowAnchorHints`,
  // shared so the two can't drift visually apart). Skips while an actual
  // link drag is running (`wbLinkDragActive`), that path already redraws
  // hints every frame from the live pointer position, and this would just
  // be a second, slightly-stale write to the same DOM nodes.
  containerEl.addEventListener("pointermove", (e) => {
    if (!window.currentTool || !window.currentTool.startsWith("link-")) return;
    if (wbLinkDragActive) return;
    const [x, y] = getLogicalMouse(e);
    // Every linkable thing, in its rotated frame, this was cards only, on
    // their unrotated box (reported: stickies "light up" wrong).
    const hit = wbLinkCandidateAt(x, y);
    if (hit) wbShowAnchorHints(hit[0], hit[1], wbNearestAnchor(hit[0], hit[1], x, y));
    else wbClearAnchorHints();
  });

  // On `window`, not on the container, and for three event names rather than
  // one. The container's own pointerup is not enough: a capture can be lost
  // (`lostpointercapture`), a gesture can be taken over by the browser
  // (`pointercancel`), and a synthetic pointerdown was never captured at all.
  // Every one of those used to leave the rectangle on the board.
  window.addEventListener("pointercancel", () => wbEndMarqueeDrag());
  window.addEventListener("lostpointercapture", () => wbEndMarqueeDrag());
  window.addEventListener("pointerup", (e) => {
    if (!wbMarqueeStart) return;
    const [x, y] = getLogicalMouse(e);
    const mx = Math.min(wbMarqueeStart.x, x), my = Math.min(wbMarqueeStart.y, y);
    const mw = Math.abs(x - wbMarqueeStart.x), mh = Math.abs(y - wbMarqueeStart.y);
    const shiftKey = wbMarqueeStart.shiftKey;
    wbEndMarqueeDrag();
    // Too small to be a deliberate drag, the plain "click" listener above
    // already handles this as a click-to-clear-selection instead.
    if (mw < 4 && mh < 4) return;
    if (!shiftKey) wbMultiSelection.clear();
    for (const node of wbState.nodes) {
      const el = document.querySelector(WB_SELECTOR_BY_KIND.node(node.id));
      const w = el?.offsetWidth || 250, h = el?.offsetHeight || 150;
      if (rectsIntersect(mx, my, mw, mh, node.x, node.y, w, h)) {
        wbMultiSelection.add(wbMultiKey("node", node.id));
      }
    }
    for (const obj of wbState.objects || []) {
      if (rectsIntersect(mx, my, mw, mh, obj.x, obj.y, obj.width, obj.height)) {
        wbMultiSelection.add(wbMultiKey("object", obj.id));
      }
    }
    for (const sketch of wbState.sketches) {
      const parsed = wbSketchParsedData(sketch);
      if (!parsed) continue; // a link sketch: nothing here to select as a shape
      const bbox = wbPathBBox(parsed.d);
      if (bbox && rectsIntersect(mx, my, mw, mh, bbox.minX, bbox.minY, bbox.width, bbox.height)) {
        wbMultiSelection.add(wbMultiKey("sketch", sketch.id));
      }
    }
    wbSelectedItem = null;
    wbMarqueeJustSelected = true;
    wbApplySelectionHighlight();
  });

  // Freeform lasso select: asked for directly ("all the selection tools
  // (e.g. rectangle select and lasso)"). Same shape as the marquee just
  // above (empty-canvas-only pointerdown, shift to add, `wbMarqueeJustSelected`
  // shared so the trailing native "click" doesn't wipe the result) but hit-
  // tests each item's *centre point* against the traced polygon rather than
  // rectangle-intersecting its bounding box, a lasso is a freeform loop, so
  // "is this item's middle inside the loop" is the one test that stays
  // cheap (one ray-cast per item, not a polygon-clip against every edge) and
  // still matches what a user visually circled.
  function wbPointInPolygon(px, py, points) {
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const [xi, yi] = points[i], [xj, yj] = points[j];
      const crosses = yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi;
      if (crosses) inside = !inside;
    }
    return inside;
  }
  let wbLassoPoints = null;
  let wbLassoEl = null;
  let wbLassoShift = false;
  //: The lasso's half of `wbEndMarqueeDrag`, and it exists for the same
  //: reported bug: a loop released outside the container left its polyline
  //: on the canvas with nothing holding a reference to it.
  function wbEndLassoDrag() {
    wbLassoEl?.remove();
    wbLassoEl = null;
    wbLassoPoints = null;
  }
  //: Both drags, from anywhere in the file, see `wbCancelSelectionDragRef`.
  wbCancelSelectionDragRef = () => {
    wbEndMarqueeDrag();
    wbEndLassoDrag();
  };
  containerEl.addEventListener("pointerdown", (e) => {
    // Unlike the marquee (`wbIsEmptyCanvasTarget`, above: empty canvas
    // only, since a drag starting *on* a card there means "move it"), a
    // lasso loop is drawn freeform and routinely starts right at the edge
    // of the first thing it means to circle, reported directly as "the
    // lasso tool doesn't work properly". Still excludes an actual handle,
    // which needs its own drag gesture to keep working.
    if (window.currentTool !== "lasso" || e.target.closest?.(".wb-resize-handle, .wb-rotate-handle, .wb-object-grip, .wb-link-endpoint-handle")) return;
    if (e.button !== 0 || !e.isPrimary) return;
    wbEndLassoDrag();
    const [x, y] = getLogicalMouse(e);
    wbLassoPoints = [[x, y]];
    wbLassoShift = e.shiftKey;
    wbLassoEl = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    wbLassoEl.setAttribute("class", "wb-lasso");
    wbLassoEl.setAttribute("points", `${x},${y}`);
    // The overlay layer, which paints above the HTML card layer, in the
    // base SVG the loop was drawn *under* every card and sticky (reported:
    // "the lasso select tool is behind everything").
    document.getElementById("wb-overlay-zoom-group").appendChild(wbLassoEl);
    try {
      containerEl.setPointerCapture(e.pointerId);
    } catch (err) {
      // See the marquee's own comment: a synthetic pointer cannot be caught.
    }
  });
  window.addEventListener("pointercancel", () => wbEndLassoDrag());
  window.addEventListener("lostpointercapture", () => wbEndLassoDrag());
  window.addEventListener("pointermove", (e) => {
    if (!wbLassoPoints) return;
    const [x, y] = getLogicalMouse(e);
    wbLassoPoints.push([x, y]);
    wbLassoEl.setAttribute("points", wbLassoPoints.map(([px, py]) => `${px},${py}`).join(" "));
  });
  window.addEventListener("pointerup", () => {
    if (!wbLassoPoints) return;
    const points = wbLassoPoints, shiftKey = wbLassoShift;
    wbEndLassoDrag();
    if (points.length < 3) return; // a tap, not a loop, nothing to select
    if (!shiftKey) wbMultiSelection.clear();
    for (const node of wbState.nodes) {
      const el = document.querySelector(WB_SELECTOR_BY_KIND.node(node.id));
      const w = el?.offsetWidth || 250, h = el?.offsetHeight || 150;
      if (wbPointInPolygon(node.x + w / 2, node.y + h / 2, points)) {
        wbMultiSelection.add(wbMultiKey("node", node.id));
      }
    }
    for (const obj of wbState.objects || []) {
      if (wbPointInPolygon(obj.x + obj.width / 2, obj.y + obj.height / 2, points)) {
        wbMultiSelection.add(wbMultiKey("object", obj.id));
      }
    }
    for (const sketch of wbState.sketches) {
      const parsed = wbSketchParsedData(sketch);
      if (!parsed) continue; // a link sketch: nothing here to select as a shape
      const bbox = wbPathBBox(parsed.d);
      if (bbox && wbPointInPolygon(bbox.minX + bbox.width / 2, bbox.minY + bbox.height / 2, points)) {
        wbMultiSelection.add(wbMultiKey("sketch", sketch.id));
      }
    }
    wbSelectedItem = null;
    wbMarqueeJustSelected = true;
    wbApplySelectionHighlight();
  });

  // Images: paste, drag-and-drop, or the upload button, asked for
  // directly, and all three funnel through the same upload+place path
  // `handleFileUpload` already established for notes (POST /media/upload,
  // then a placed reference, a board object here instead of markdown text).
  async function wbPlaceUploadedImage(file, x, y) {
    if (!file || !file.type?.startsWith("image/")) return;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const uploaded = await apiJson("/media/upload", {
        method: "POST",
        headers: { "X-Auth-Token": authToken() },
        body: formData,
      });
      const img = new Image();
      const naturalSize = await new Promise((resolve) => {
        img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
        img.onerror = () => resolve({ w: 300, h: 200 });
        img.src = mediaSrc(uploaded.url);
      });
      const width = Math.min(400, naturalSize.w || 300);
      const height = width * ((naturalSize.h || 200) / (naturalSize.w || 300));
      await wbCreateObject("image", { url: uploaded.url }, x - width / 2, y - height / 2, width, height);
    } catch (err) {
      toast(err.message || "Couldn't add that image.", true);
    }
  }

  containerEl.addEventListener("dragover", (e) => {
    if (e.dataTransfer?.types?.includes("Files")) e.preventDefault();
  });
  containerEl.addEventListener("drop", (e) => {
    if (!e.dataTransfer?.files?.length) return;
    e.preventDefault();
    const [x, y] = getLogicalMouse(e);
    for (const file of e.dataTransfer.files) wbPlaceUploadedImage(file, x, y);
  });
  // Paste has no drop coordinate to place at, the centre of whatever's
  // currently in view reads better than always the same fixed board
  // position, which would stack every pasted image on top of the last one.
  containerEl.addEventListener("paste", (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files = [...items].filter((i) => i.kind === "file").map((i) => i.getAsFile());
    if (!files.length) return;
    e.preventDefault();
    const rect = containerEl.getBoundingClientRect();
    const [x, y] = getLogicalMouse({ clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 });
    for (const file of files) wbPlaceUploadedImage(file, x, y);
  });
  const imageFileInput = document.getElementById("wb-image-file-input");
  document.getElementById("wb-add-image")?.addEventListener("click", () => imageFileInput?.click());
  imageFileInput?.addEventListener("change", () => {
    const rect = containerEl.getBoundingClientRect();
    const [x, y] = getLogicalMouse({ clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 });
    for (const file of imageFileInput.files) wbPlaceUploadedImage(file, x, y);
    imageFileInput.value = "";
  });

  // On `containerEl`, not `svgCanvas`, the same reasoning the eraser
  // listener above already follows. `svgCanvas` only ever sees a
  // pointerdown that lands directly on it or on something inside it; a
  // click that starts on a card (`#wb-html-layer`, a sibling painted on
  // top) never reaches it at all, which is the exact mechanism behind
  // "drawing over a note just moves the note". `containerEl` is an
  // ancestor of both layers, so it sees every pointerdown either way, 
  // and, with the card/object drags above now filtered out while a brush
  // tool is active, nothing else claims the gesture first.
  containerEl.addEventListener("pointerdown", (e) => {
    if (!WB_BRUSH_TOOLS.has(window.currentTool)) return;
    e.stopPropagation();
    isDrawing = true;
    const [x, y] = getLogicalMouse(e);
    
    currentDrawData = [[x, y]];
    currentDrawPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    // Fill only applies to the four closed shapes, and only when "no fill"
    // isn't checked: asked for directly ("fill colour/transparency...
    // options for no border/stroke or background").
    if (WB_FILLABLE_SHAPES.has(window.currentTool) && !window.currentFillNone) {
      currentDrawPath.setAttribute("fill", window.currentFillColor);
      currentDrawPath.setAttribute("fill-opacity", String(window.currentFillOpacity / 100));
    } else {
      currentDrawPath.setAttribute("fill", "none");
    }
    currentDrawPath.setAttribute("stroke", window.currentStrokeNone ? "none" : window.currentStrokeColor);
    // A highlighter needs to be visibly wider and translucent, or it isn't a
    // highlighter: the sketch pad's own version of this exact control had
    // its opacity so low it was reported as invisible (HISTORY.md §46).
    currentDrawPath.setAttribute(
      "stroke-width",
      String(window.currentTool === "highlighter" ? wbHighlighterWidth(WB_STROKE_WIDTH) : WB_STROKE_WIDTH)
    );
    if (window.currentTool === "highlighter") {
      currentDrawPath.setAttribute("stroke-opacity", String(WB_HIGHLIGHTER_ALPHA));
      currentDrawPath.setAttribute("stroke-linecap", "square");
      // An inline style, not a class: the export clones these elements into a
      // standalone SVG where a stylesheet does not follow them, and
      // `el.style.x = ...` is the form this app's CSP allows (an inline
      // `style=` attribute in the markup is refused).
      currentDrawPath.style.mixBlendMode = "multiply";
    } else {
      currentDrawPath.setAttribute("stroke-linecap", "round");
    }
    currentDrawPath.setAttribute("stroke-linejoin", "round");
    const dashArray = wbDashArray(window.currentDashStyle, WB_STROKE_WIDTH);
    if (dashArray) currentDrawPath.setAttribute("stroke-dasharray", dashArray);
    currentDrawPath.setAttribute("d", `M ${x} ${y}`);
    document.getElementById("wb-zoom-group").appendChild(currentDrawPath);
  });
  
  containerEl.addEventListener("pointermove", (e) => {
    if (!isDrawing || !WB_BRUSH_TOOLS.has(window.currentTool)) return;
    e.stopPropagation();
    const [x, y] = getLogicalMouse(e);
    
    if (window.currentTool === "draw" || window.currentTool === "highlighter") {
      // **Shift draws a straight run** (decision 7). Held mid-stroke it
      // replaces whatever has been drawn since the start point with one
      // segment, and letting go carries on freehand from there, which is how
      // a straightedge behaves and how every app that offers this does it.
      if (e.shiftKey && window.currentTool === "highlighter") {
        const [sx0, sy0] = currentDrawData[0];
        currentDrawData.length = 1;
        currentDrawData.push([x, y]);
        currentDrawPath.setAttribute("d", `M ${sx0} ${sy0} L ${x} ${y}`);
        return;
      }
      currentDrawData.push([x, y]);
      const d = currentDrawData.map((pt, i) => (i === 0 ? `M ${pt[0]} ${pt[1]}` : `L ${pt[0]} ${pt[1]}`)).join(" ");
      currentDrawPath.setAttribute("d", d);
    } else {
      // Shape tools: only start and current point matter
      const [sx, sy] = currentDrawData[0];
      if (window.currentTool === "line" || window.currentTool === "arrow") {
        // One path, one or more subpaths, a plain SVG `d` string can hold
        // more than one `M`, and every subpath in it shares the same
        // stroke, so this is the shaft plus whichever head strokes the
        // *active tool's own* end-style calls for in a single element,
        // rather than several sketches that would each need their own undo
        // entry and could drift apart. Asked for directly: "regular lines
        // should also get line end options... arrow heads", the Line and
        // Arrow tools share the same "Line ends" control, so a plain line
        // *can* carry an arrowhead, but each tool keeps its own remembered
        // default (Line: none, Arrow: end): see the live-reported bug fix
        // on `currentLineEndStyle`/`currentArrowEndStyle` in `initWhiteboard`.
        const angle = Math.atan2(y - sy, x - sx);
        const headLen = WB_STROKE_WIDTH * 4 + 6;
        let d = `M ${sx} ${sy} L ${x} ${y}`;
        const style = (window.currentTool === "line" ? window.currentLineEndStyle : window.currentArrowEndStyle) || "none";
        if (style === "end" || style === "both") d += " " + wbArrowHeadPath(x, y, angle, headLen);
        if (style === "start" || style === "both") d += " " + wbArrowHeadPath(sx, sy, angle + Math.PI, headLen);
        currentDrawPath.setAttribute("d", d);
      } else if (window.currentTool === "rect") {
        const mx = Math.min(sx, x), my = Math.min(sy, y);
        const { w, h } = wbShapeDims(x - sx, y - sy, e.shiftKey);
        currentDrawPath.setAttribute("d", `M ${mx} ${my} h ${w} v ${h} h ${-w} Z`);
      } else if (window.currentTool === "circle") {
        const { w: rx, h: ry } = wbShapeDims(x - sx, y - sy, e.shiftKey);
        currentDrawPath.setAttribute("d", `M ${sx - rx} ${sy} a ${rx} ${ry} 0 1 0 ${rx * 2} 0 a ${rx} ${ry} 0 1 0 ${-rx * 2} 0`);
      } else if (window.currentTool === "triangle") {
        // Asked for directly ("more types of shapes"). Plain `L` commands,
        // same as the pen/line tools, no new command type for
        // wbTransformPathD/wbPathBBox to learn.
        const mx = Math.min(sx, x), my = Math.min(sy, y);
        const { w, h } = wbShapeDims(x - sx, y - sy, e.shiftKey);
        currentDrawPath.setAttribute(
          "d",
          `M ${mx + w / 2} ${my} L ${mx + w} ${my + h} L ${mx} ${my + h} Z`
        );
      } else if (window.currentTool === "diamond") {
        const mx = Math.min(sx, x), my = Math.min(sy, y);
        const { w, h } = wbShapeDims(x - sx, y - sy, e.shiftKey);
        currentDrawPath.setAttribute(
          "d",
          `M ${mx + w / 2} ${my} L ${mx + w} ${my + h / 2} L ${mx + w / 2} ${my + h} L ${mx} ${my + h / 2} Z`
        );
      }
    }
  });
  
  containerEl.addEventListener("pointerup", async (e) => {
    if (!isDrawing || !WB_BRUSH_TOOLS.has(window.currentTool)) return;
    e.stopPropagation();
    isDrawing = false;
    
    const [x, y] = getLogicalMouse(e);
    const [sx, sy] = currentDrawData[0];
    
    // A plain click with no drag, reported directly: the pen tool "doesn't
    // respond to a single click, only a drag", which the sketch pad's own
    // pen never had wrong (see `sketchEnd`'s own `!sketchMoved` branch, the
    // same fix mirrored here). A `moveto` with no `lineto` after it draws
    // nothing at all, so a stationary click has to add a near-zero-length
    // segment, round linecaps turn that into a visible dot, rather than
    // being discarded as "no shape to save".
    const isFreehand = window.currentTool === "draw" || window.currentTool === "highlighter";
    if (isFreehand && currentDrawData.length < 2) {
      currentDrawPath.setAttribute("d", `M ${sx} ${sy} L ${sx} ${sy + 0.1}`);
    } else if (!isFreehand && Math.abs(x - sx) < 2 && Math.abs(y - sy) < 2) {
      // Shape tools (line/arrow/rect/circle) need an actual drag to have a
      // size: a zero-size shape isn't a reasonable click-to-draw default
      // the way a pen dot is, so these are still discarded.
      if (currentDrawPath) currentDrawPath.remove();
      currentDrawPath = null;
      return;
    }
    
    // Save sketch to API. The backend schema has no width/opacity/fill/dash
    // columns, so all of it has to travel inside `data`, otherwise a saved
    // stroke reloads at the hardcoded 3px default regardless of what
    // #wb-stroke-width was actually set to when it was drawn (a real bug,
    // caught while wiring that control up: only the highlighter branch here
    // ever saved its own width; a plain pen/line/shape stroke silently lost
    // whatever size it was actually drawn at the moment the page reloaded).
    const d = currentDrawPath.getAttribute("d");
    const isHighlighter = window.currentTool === "highlighter";
    const isFillable = WB_FILLABLE_SHAPES.has(window.currentTool);
    const blob = {
      d,
      color: currentStrokeColor,
      width: isHighlighter ? wbHighlighterWidth(WB_STROKE_WIDTH) : WB_STROKE_WIDTH,
      shape: window.currentTool,
    };
    if (isHighlighter) {
      blob.opacity = WB_HIGHLIGHTER_ALPHA;
    } else {
      if (window.currentDashStyle !== "solid") blob.dash = window.currentDashStyle;
      if (window.currentStrokeNone) blob.noStroke = true;
      if (isFillable && !window.currentFillNone) {
        blob.fill = window.currentFillColor;
        blob.fillOpacity = window.currentFillOpacity / 100;
      }
    }
    const sketchData = {
      data: JSON.stringify(blob),
      x: 0,
      y: 0,
      z: 5,
      board_id: window.currentBoardId
    };

    try {
      const res = await apiJson("/whiteboard/sketches", { method: "POST", body: JSON.stringify(sketchData) });
      wbState.sketches.push(res);
      wbPushUndo({ action: "create", kind: "sketch", id: res.id });
      // Hand off to renderWhiteboard's own data-bound element for this
      // sketch: a real bug found while adding the eraser: this raw `<path>`
      // is not part of the `g.sketch-group` selection renderWhiteboard binds
      // wbState.sketches to, so a stroke just drawn had no way to be deleted
      // or erased until a full reload re-fetched it from the server and
      // rendered it "properly" the first time.
      currentDrawPath.remove();
      wbScheduleRender();
    } catch (err) {
      console.error("Failed to save sketch:", err);
      if (currentDrawPath) currentDrawPath.remove();
    }

    currentDrawPath = null;
    currentDrawData = [];
  });

  // Drop handler for Library
  document.getElementById("whiteboard-container").addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  
  document.getElementById("whiteboard-container").addEventListener("drop", async (e) => {
    e.preventDefault();
    const dropped = e.dataTransfer.getData("text/plain");
    if (!dropped) return;
    //: **Only a note id may be dropped here.** `text/plain` is whatever the
    //: drag carried, and a selection, a url or a filename all satisfy a bare
    //: truthiness test: `parseInt` then gave `NaN`, `JSON.stringify` wrote it
    //: as `null`, and the server answered 422 with "entry_id: Input should be
    //: a valid integer, input: null". Seen in the owner's console on
    //: 2026-09-09, beside an "Error creating node: {}" that said nothing.
    const entryId = Number.parseInt(dropped, 10);
    if (!Number.isInteger(entryId) || entryId <= 0) {
      toast("Drop a note from the Library onto the board. That was not a note.", true);
      return;
    }
    
    // Reported directly: "I dragged a note from the library dropdown onto
    // the board but the note appeared in the top left, not in the centre
    // where I placed it." `#wb-html-layer` already carries the pan/zoom as
    // a CSS `transform` (handleWbZoom above), so its own
    // `getBoundingClientRect()` is *already* shifted and scaled by
    // `transform.x/y/k`; subtracting `transform.x` and dividing by
    // `transform.k` again then applied the same pan and zoom a second
    // time, which is exactly wrong once the board has been panned or
    // zoomed away from its default 0,0/1x. `#whiteboard-container` is the
    // element `d3.zoom` is attached to and never itself carries the CSS
    // transform, so its rect is the stable reference `transform.invert`
    // expects.
    const container = document.getElementById("whiteboard-container");
    const transform = d3.zoomTransform(container);
    const rect = container.getBoundingClientRect();

    // Calculate logical x,y
    const logicalX = (e.clientX - rect.left - transform.x) / transform.k;
    const logicalY = (e.clientY - rect.top - transform.y) / transform.k;

    // Reported directly: a dropped note lands "quite offset from where I
    // dropped it". `d.x`/`d.y` are the card's own top-left corner (that's
    // what `renderWhiteboard`'s `translate(d.x, d.y)` positions), so storing
    // the raw drop point put the *corner* under the cursor, not the card, 
    // for the app's own ~250×150 default card size that reads as up to
    // 125px right and 75px down from where you actually let go. Centring it
    // on the drop point instead matches how a text box/image already places
    // itself on click/drop (`wbCreateTextBox`, `wbPlaceUploadedImage`).
    const nodeData = {
      entry_id: entryId,
      x: logicalX - 125,
      y: logicalY - 75,
      z: 10,
      board_id: window.currentBoardId
    };
    
    try {
      const res = await apiJson("/whiteboard/nodes", { method: "POST", body: JSON.stringify(nodeData) });
      // If it exists in state already, replace it. Otherwise push.
      const idx = wbState.nodes.findIndex(n => n.id === res.id);
      if (idx !== -1) wbState.nodes[idx] = res;
      else wbState.nodes.push(res);
      wbScheduleRender();
    } catch (err) {
      //: `console.error("...", err)` printed "{}": an Error's `message` is not
      //: an enumerable own property, so the console's object view showed
      //: nothing at all and the reader was told a card failed without being
      //: told why. The message is what the server sent, and it belongs on
      //: screen rather than in a console nobody has open.
      const why = (err && err.message) || "the server refused it";
      console.error("Error creating node:", why);
      toast(`Could not add that note to the board: ${why}`, true);
    }
  });


  
  await fetchWhiteboardState();
  wbScheduleRender();
}

function renderWbLibrary() {
  const list = document.getElementById("wb-library-list");
  list.innerHTML = "";
  for (const entry of allEntries) {
    const li = document.createElement("li");
    li.className = "wb-library-item";
    // `notePreviewText` (app.js), not the raw body. Reported with a
    // screenshot of this very list: a sketch note read "A real drawn sketch
    // ![A real drawn sket…", because its drawing lives in the note as inline
    // `![alt](/media/…)` markdown and this printed it verbatim. Every other
    // list of notes in the app already goes through this helper, the
    // whiteboard's own card renderer two hundred lines up included, so this
    // was the last place a note's markdown leaked into a label.
    const text = notePreviewText(entry.content || entry.preview || "");
    li.textContent = text ? (text.length > 40 ? text.substring(0, 40) + "…" : text) : entry.id;
    li.title = text || String(entry.id);
    li.draggable = true;
    li.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", entry.id);
      e.dataTransfer.effectAllowed = "copy";
    });
    list.appendChild(li);
  }
}

window.currentBoardId = null;

//: **A response is only allowed to land on the board it was asked for.**
//:
//: Found while testing the board search, and it is worth writing down because
//: it looked like a search bug for three rounds: `window.currentBoardId` read
//: 128 (the board that had just been opened, and the one the picker showed)
//: while `wbState.nodes` held the two cards of board 85. The board on screen
//: was not the board the app thought was open.
//:
//: `openWhiteboardBoard` clicks the Boards & maps sub-tab, and that click
//: starts its own load for whatever board was selected before; it then sets
//: `currentBoardId` and starts a second load for the board actually asked
//: for. Both used to `wbState = res` unconditionally, so whichever response
//: happened to arrive last won, intermittently, which is why two identical
//: probe runs disagreed.
//:
//: The guard is the ordinary one for an out-of-order response: remember which
//: board the request was for, and throw the answer away if it is no longer
//: the question being asked. Never mind "last write wins" with a sequence
//: number: the board id *is* the identity here, and comparing it means a
//: re-fetch of the same board still applies normally.
async function fetchWhiteboardState() {
  const requestedBoardId = window.currentBoardId ?? null;
  try {
    const url = requestedBoardId ? `/whiteboard/?board_id=${requestedBoardId}` : "/whiteboard/";
    const res = await apiJson(url);
    if ((window.currentBoardId ?? null) !== requestedBoardId) return;
    wbState = res;
    // Before the board list, and awaited: everything that draws a map node
    // reads `window.wbMapState` for the board's type and for reference
    // labels, so a render that beat this call would draw the map as a plain
    // whiteboard once and then correct itself, a visible flash of the wrong
    // thing on every single board open.
    await wbRefreshMapState();
    wbSyncMapChrome();
    await refreshBoardList();
  } catch (err) {
    console.error("Whiteboard fetch error:", err);
  }
}

// Reported directly: "the different board options confuse me." It used to
// be every note in the notebook, since architecturally any note can serve as
// a board_id: the picker took that literally and offered a 50-item dropdown
// of notes that had never been anywhere near the whiteboard. GET
// /whiteboard/boards lists only notes something is actually on, plus the
// always-present default board (see routes_whiteboard.py for the full
// writeup). Re-fetched on every state load rather than cached once: creating
// or first-using a board should show up in the picker without a reload.
// `justCreated`: a board this session just made, which won't come back from
// the server yet: nothing is on it, and the endpoint only lists boards
// something has actually been placed on (see its own docstring). Without
// this, switching straight to a brand-new board made the dropdown fall back
// to whatever option happened to match nothing, which looked like the new
// board had failed to switch to at all.
async function refreshBoardList(justCreated = null) {
  const select = document.getElementById("wb-board-select");
  if (!select) return;
  //: To the end, not the first page: `GET /whiteboard/boards` is paged now
  //: (`BOARDS_PAGE_SIZE`), and a picker that offers some of your boards is
  //: worse than one that takes a second request to offer all of them.
  const boards = await apiPagedList("/whiteboard/boards", 200, { silent: true }).catch(() => null);
  if (!boards) return;
  if (justCreated && !boards.some((b) => b.id === justCreated.id)) {
    boards.push({ ...justCreated, node_count: 0, sketch_count: 0, object_count: 0 });
  }
  select.replaceChildren();
  //: **A map says it is one, in the row** (MINDMAP_PLAN.md §5 item 12, the
  //: decision `mapChip` already follows on the timeline, in a note and in the
  //: chat). Reported: "whiteboards and mindmaps need to be differentiable in
  //: the boards selector". Measured before: five options reading
  //: `Title (N items)`, four of them maps, with nothing on any of them saying
  //: so, and an aria-label that called all five whiteboards.
  //:
  //: `<optgroup>` rather than a glyph in front of every label: a native
  //: `<option>` cannot hold the icon `mapChip` marks a map with (it renders as
  //: text only, and in the OS's own popup on Windows and macOS), so the choice
  //: is a character standing in for the icon or the platform's own way of
  //: saying "these are one kind and those are another". The app already uses
  //: `<optgroup>` for exactly that in three other selects, so this is the
  //: recipe rather than a fourth idea.
  //:
  //: Grouped only when both kinds are actually present: with nothing to tell
  //: it apart from, a lone "Whiteboards" heading above every row is a label
  //: that answers a question nobody asked.
  const mapsPresent = boards.some((b) => b.type === "map");
  const boardsPresent = boards.some((b) => b.type !== "map");
  const groups = new Map();
  if (mapsPresent && boardsPresent) {
    for (const [key, label] of [["map", "Mind maps"], ["board", "Whiteboards"]]) {
      const group = document.createElement("optgroup");
      group.label = label;
      groups.set(key, group);
      select.appendChild(group);
    }
  }
  for (const board of boards) {
    const opt = document.createElement("option");
    opt.value = board.id ?? "";
    // Images and text boxes count too, a board holding only those (no
    // cards or sketches) read as "(0 items)" here, which is exactly what
    // exposed this: a board with three text boxes on it, live-verified.
    const count = board.node_count + board.sketch_count + (board.object_count || 0);
    opt.textContent = board.id === null
      ? board.title
      : `${board.title} (${count} item${count === 1 ? "" : "s"})`;
    (groups.get(board.type === "map" ? "map" : "board") || select).appendChild(opt);
  }
  select.value = window.currentBoardId || "";
  // The default scratch board (`board_id=null`) has no underlying note to
  // rename: `rename_board` 404s on anything that isn't a real positive id.
  const renameBtn = document.getElementById("wb-rename-board");
  if (renameBtn) renameBtn.disabled = !window.currentBoardId;
}

async function renameCurrentBoard() {
  if (!window.currentBoardId) return;
  const current = document.getElementById("wb-board-select")?.selectedOptions?.[0]?.textContent
    .replace(/\s*\(\d+ items?\)$/, "") || "";
  const name = await promptDialog("Rename this board:", current);
  if (!name || !name.trim()) return;
  try {
    const board = await apiJson(`/whiteboard/boards/${window.currentBoardId}`, {
      method: "PUT",
      body: JSON.stringify({ title: name.trim() }),
    });
    await refreshBoardList(board);
    toast(`Board renamed to "${board.title}".`);
  } catch (err) {
    toast(err.message || "Couldn't rename that board.", true);
  }
}

//: Create a board: or a map, which is the same thing with a `type` on it
//: (MINDMAP_PLAN.md §4 chose option B: one data model, two behaviours).
//:
//: `preset` lets the Library's "New mind map" action skip straight to the map
//: half without the dialog having to be answered twice; left alone, the dialog
//: asks, defaulting to whatever it was told.
async function createNewBoard(preset = "board") {
  const answer = await promptDialog("Name the new board:", "", {
    segment: {
      label: "What kind of board",
      value: preset,
      // The icons are the same two the boards picker groups by and the Board
      // menu's Kind row uses, so the shape means the same thing everywhere.
      options: [
        {
          value: "board",
          label: "ph:squares-four Board",
          title: "A free canvas: notes, sketches, images",
        },
        {
          value: "map",
          label: "ph:tree-structure Mind map",
          title: "A tree: topics, branches and keyboard editing",
        },
      ],
    },
  });
  const name = answer?.text || "";
  const kind = answer?.choice === "map" ? "map" : "board";
  if (!name || !name.trim()) return;
  try {
    const board = await apiJson("/whiteboard/boards", {
      method: "POST",
      // A map is created **in** its layout, not converted into one afterwards:
      // `tree-right` is the layout every mainstream mindmapper opens in, and a
      // map that starts as `free` would put its first three nodes wherever the
      // server's fallback placement happened to drop them and only tidy up
      // once someone found the picker.
      body: JSON.stringify(
        kind === "map"
          ? { name: name.trim(), type: "map", layout: "tree-right" }
          : { name: name.trim() }
      ),
    });
    window.currentBoardId = board.id;
    if (kind === "map") {
      // One root topic, named after the map. **An empty canvas is the main
      // reason mindmap features go unused** (MINDMAP_PLAN.md §5 item 21), and
      // a map with nothing on it has no node to press Tab on, so the one
      // gesture the whole feature turns on would have nowhere to start.
      await apiJson(`/whiteboard/boards/${board.id}/nodes`, {
        method: "POST",
        body: JSON.stringify({ kind: "topic", parent_id: null, text: name.trim() }),
      }).catch((err) => toast(err.message || "Couldn't add the root topic.", true));
    }
    // `list_boards` only lists a board once something is actually placed on
    // it (see its own docstring), an empty new one is invisible to both
    // this dropdown (already handled below via `justCreated`) and the
    // landing gallery, which would otherwise make a board someone just
    // created appear to vanish the moment they go back to the list.
    window.wbLastCreatedBoard = board;
    // `fetchWhiteboardState`, not a bare GET: it is the one path that also
    // refreshes `window.wbMapState` and the top bar's map controls, and a map
    // created through a second copy of those two lines opened as an ordinary
    // whiteboard until the next board switch, the node was there, the Map
    // chip was not, and none of the keys worked.
    await fetchWhiteboardState();
    wbScheduleRender();
    if (kind === "map") {
      // Selected, so Tab works on the very first keystroke. A map whose root
      // has to be clicked before the keyboard does anything teaches the wrong
      // thing about the feature in its first five seconds.
      const root = (wbState.objects || []).find((o) => WB_MAP_KINDS.has(o.kind));
      if (root) selectWbItem("object", root.id);
      renderWhiteboardNow();
      //: **Centred on the actual canvas, not wherever the server's own
      //: `tree-right` placement happened to land it.** Reported: a new map's
      //: first node opened under the top bar. The root is real DOM now
      //: (`renderWhiteboardNow` just ran), so its true rendered box is
      //: available for `wbCenterOn` (see `createConceptMap`'s matching fix
      //: and its own comment for why a guessed coordinate cannot do this
      //: instead: the visible canvas size is neither constant nor known
      //: until it is actually measured).
      if (root) wbCenterOn(wbItemBBox("object", root), { animate: false });
      toast(`Mind map "${board.title}" created: Tab adds a branch, Enter a sibling.`);
    } else {
      toast(`Board "${board.title}" created.`);
    }
  } catch (err) {
    toast(err.message || "Couldn't create that board.", true);
  }
}

// --- Sketch move/resize (ROADMAP.md Tier 2 §11 / user-reported: "can't
// move objects drawn on the whiteboard", "can't resize... can't shorten
// lines") -------------------------------------------------------------------
//
// Cards and objects have real x/y/width/height columns; a sketch is just an
// SVG path string (`d`), so "move" and "resize" both mean rewriting the
// coordinates inside that string rather than moving a positioned element.
// This is *not* a general SVG path parser, it only has to round-trip
// exactly the commands this app's own drawing tools ever emit (see the
// `pointermove` handler above: `M`/`L` for pen and lines, `C` for link
// curves, `h`/`v`/`Z` for rect, `a` for circle): a path from anywhere else
// was never a possibility, so there is no reason to handle SVG's full
// command set.
//: `rotate` (degrees, about `anchorX`/`anchorY`) is what a sketch didn't
//: have: cards and objects rotate (a drag handle + a stored `rotation`
//: column), but a sketch *is* its path data, and rotating a path correctly
//: needs care `dx`/`sx` alone don't: `h`/`v` (a purely horizontal/vertical
//: relative line: this app's own rect tool emits them) can't represent a
//: rotated line at all, since rotating "purely horizontal" by anything
//: other than a multiple of 90° makes it not horizontal any more, so each
//: becomes an absolute `L` instead once rotation is non-zero. `a` (the
//: circle tool's arc pairs) stays relative, a rotation adds straight onto
//: the arc's own `x-axis-rotation` parameter and rotates its endpoint
//: delta; `rx`/`ry`/large-arc/sweep are unchanged, which is exact for a
//: *pure* rotation (no reflection): this app never emits a negative
//: scale, so that combination doesn't need handling here.
function wbTransformPathD(d, { dx = 0, dy = 0, sx = 1, sy = 1, rotate = 0, anchorX = 0, anchorY = 0 } = {}) {
  const theta = (rotate * Math.PI) / 180;
  const cos = Math.cos(theta), sin = Math.sin(theta);
  const mapPoint = (x, y) => {
    const scaledX = anchorX + (x - anchorX) * sx;
    const scaledY = anchorY + (y - anchorY) * sy;
    const relX = scaledX - anchorX, relY = scaledY - anchorY;
    return [anchorX + relX * cos - relY * sin + dx, anchorY + relX * sin + relY * cos + dy];
  };
  // A relative delta scales the same way a point's offset from the anchor
  // does, but never translates (dx/dy are a position's own change, not a
  // vector's).
  const mapDelta = (ddx, ddy) => {
    const scaledX = ddx * sx, scaledY = ddy * sy;
    return [scaledX * cos - scaledY * sin, scaledX * sin + scaledY * cos];
  };
  const tokens = d.match(/[MLCHVAZmlchvaz]|-?\d*\.?\d+(?:[eE]-?\d+)?/g);
  if (!tokens) return d;
  let i = 0, px = 0, py = 0; // current point, tracked only for h/v → L under rotation
  const out = [];
  while (i < tokens.length) {
    const cmd = tokens[i++];
    if (cmd === "M" || cmd === "L") {
      const x = parseFloat(tokens[i++]), y = parseFloat(tokens[i++]);
      const [mx, my] = mapPoint(x, y);
      out.push(cmd, mx, my);
      px = x; py = y;
    } else if (cmd === "C") {
      const n = [];
      for (let k = 0; k < 6; k++) n.push(parseFloat(tokens[i++]));
      const [x1, y1] = mapPoint(n[0], n[1]);
      const [x2, y2] = mapPoint(n[2], n[3]);
      const [x3, y3] = mapPoint(n[4], n[5]);
      out.push(cmd, x1, y1, x2, y2, x3, y3);
      px = n[4]; py = n[5];
    } else if (cmd === "h") {
      const ddx = parseFloat(tokens[i++]);
      if (rotate) {
        const [mx, my] = mapPoint(px + ddx, py);
        out.push("L", mx, my);
      } else {
        out.push(cmd, ddx * sx);
      }
      px += ddx;
    } else if (cmd === "v") {
      const ddy = parseFloat(tokens[i++]);
      if (rotate) {
        const [mx, my] = mapPoint(px, py + ddy);
        out.push("L", mx, my);
      } else {
        out.push(cmd, ddy * sy);
      }
      py += ddy;
    } else if (cmd === "a") {
      const rx = parseFloat(tokens[i++]) * sx, ry = parseFloat(tokens[i++]) * sy;
      const rot = parseFloat(tokens[i++]) + rotate, large = tokens[i++], sweep = tokens[i++];
      const edx = parseFloat(tokens[i++]), edy = parseFloat(tokens[i++]);
      const [mdx, mdy] = mapDelta(edx, edy);
      out.push(cmd, rx, ry, rot, large, sweep, mdx, mdy);
      px += edx; py += edy;
    } else if (cmd === "Z" || cmd === "z") {
      out.push(cmd);
    } else {
      return d; // an unrecognised token: leave the path untouched rather than corrupt it
    }
  }
  return out.join(" ");
}

//: The bounding box of a path this app drew, walked the same way a real SVG
//: renderer would (tracking the pen's current point through relative
//: commands) rather than just min/maxing every raw number, `h`/`v`/`a`'s
//: numbers are deltas and radii, not coordinates, and mixing them into a
//: coordinate min/max would produce a nonsense box.
function wbPathBBox(d) {
  const tokens = d.match(/[MLCHVAZmlchvaz]|-?\d*\.?\d+(?:[eE]-?\d+)?/g);
  if (!tokens) return null;
  let i = 0, px = 0, py = 0;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const visit = (x, y) => {
    minX = Math.min(minX, x); minY = Math.min(minY, y);
    maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
  };
  while (i < tokens.length) {
    const cmd = tokens[i++];
    if (cmd === "M" || cmd === "L") {
      px = parseFloat(tokens[i++]); py = parseFloat(tokens[i++]);
      visit(px, py);
    } else if (cmd === "C") {
      const n = [];
      for (let k = 0; k < 6; k++) n.push(parseFloat(tokens[i++]));
      visit(n[0], n[1]); visit(n[2], n[3]); visit(n[4], n[5]);
      px = n[4]; py = n[5];
    } else if (cmd === "h") {
      px += parseFloat(tokens[i++]);
      visit(px, py);
    } else if (cmd === "v") {
      py += parseFloat(tokens[i++]);
      visit(px, py);
    } else if (cmd === "a") {
      const rx = parseFloat(tokens[i++]), ry = parseFloat(tokens[i++]);
      i += 3; // x-axis-rotation, large-arc-flag, sweep-flag: unused for a bbox
      const ex = parseFloat(tokens[i++]), ey = parseFloat(tokens[i++]);
      // Exact for the axis-aligned circle/ellipse this tool ever draws: two
      // half-arcs whose shared chord's midpoint is the ellipse's own centre.
      const midX = px + ex / 2, midY = py + ey / 2;
      visit(midX - rx, midY - ry);
      visit(midX + rx, midY + ry);
      px += ex; py += ey;
    }
    // Z/z closes back to the last M, doesn't move the pen for bbox purposes.
  }
  return isFinite(minX) ? { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY } : null;
}

//: A handle drag's dx/dy (board-space) turned into the same
//: {sx, sy, anchorX, anchorY} shape `wbTransformPathD` takes: the opposite
//: corner/edge from whichever handle moved stays fixed, mirroring
//: `resizeDrag`'s own width/height-and-floor logic for image/text objects.
const WB_SKETCH_MIN_SIZE = 10;
function wbSketchResizeTransform(bbox, handle, dx, dy, shiftKey) {
  const { minX, minY, maxX, maxY } = bbox;
  let newMinX = minX, newMaxX = maxX, newMinY = minY, newMaxY = maxY;
  if (handle.includes("e")) newMaxX = Math.max(minX + WB_SKETCH_MIN_SIZE, maxX + dx);
  if (handle.includes("w")) newMinX = Math.min(maxX - WB_SKETCH_MIN_SIZE, minX + dx);
  if (handle.includes("s")) newMaxY = Math.max(minY + WB_SKETCH_MIN_SIZE, maxY + dy);
  if (handle.includes("n")) newMinY = Math.min(maxY - WB_SKETCH_MIN_SIZE, minY + dy);
  // Reported directly: shift while resizing didn't snap to a square. Only a
  // corner handle ("nw"/"ne"/"se"/"sw", length 2) has two free axes to lock
  // together; the larger of the two free-form extents wins, and the corner
  // *opposite* the one being dragged stays anchored, matching `anchorX`/
  // `anchorY` below rather than recentring the shape.
  const isCorner = handle.length === 2;
  if (isCorner && shiftKey) {
    const size = Math.max(newMaxX - newMinX, newMaxY - newMinY, WB_SKETCH_MIN_SIZE);
    if (handle.includes("e")) newMaxX = newMinX + size; else newMinX = newMaxX - size;
    if (handle.includes("s")) newMaxY = newMinY + size; else newMinY = newMaxY - size;
  }
  const oldW = maxX - minX || 1, oldH = maxY - minY || 1;
  const sx = handle.includes("e") || handle.includes("w") ? (newMaxX - newMinX) / oldW : 1;
  const sy = handle.includes("n") || handle.includes("s") ? (newMaxY - newMinY) / oldH : 1;
  return { sx, sy, anchorX: handle.includes("w") ? maxX : minX, anchorY: handle.includes("n") ? maxY : minY };
}

//: A sketch's own `data` blob, whether it's `{d, color}` or the wider
//: `{d, color, width, opacity}` a highlighter carries (HISTORY.md): parsed
//: once so move/resize can rewrite just `d` and leave every other field
//: (colour, the highlighter's width/opacity) exactly as it was.
// Detected from the path data itself, not a stored "kind" field (sketches
// don't have one): rect/triangle/diamond's own preview-drawing code (above,
// in the pointermove handler) closes its path with Z; circle instead
// returns to its start point via two arc ("a") commands. Line/arrow/pen/
// highlighter never do either.
function wbSketchIsClosedShape(sketch) {
  const d = wbSketchParsedData(sketch)?.d || "";
  const trimmed = d.trim();
  return /[Zz]\s*$/.test(trimmed) || /\ba\s/i.test(trimmed);
}

function wbSketchParsedData(sketch) {
  try {
    const parsed = JSON.parse(sketch.data);
    return parsed && typeof parsed.d === "string" ? parsed : null;
  } catch {
    return null;
  }
}

//: Merges `partial` into the sketch's own parsed data blob and saves the
//: whole thing back: the general form `wbSaveSketchD` (move/resize) and
//: the properties panel (colour/width/arrowhead) both reduce to. Unlike
//: `wbSketchParsedData` (which deliberately stays strict to `.d`-shaped
//: data for the move/resize code that assumes it), this also accepts a
//: link sketch: asked for directly ("customisable links... colour"),
//: which silently did nothing before this: the colour/width properties-
//: panel rows already called this function for *any* selected sketch, but
//: a link has no `.d`, so `wbSketchParsedData` returned null and the save
//: was a silent no-op.
async function wbSaveSketchProps(sketch, partial) {
  let parsed;
  try {
    const candidate = JSON.parse(sketch.data);
    if (candidate && (typeof candidate.d === "string" || (candidate.type || "").startsWith("link-"))) {
      parsed = candidate;
    }
  } catch {
    parsed = null;
  }
  if (!parsed) return;
  Object.assign(parsed, partial);
  sketch.data = JSON.stringify(parsed);
  try {
    const saved = await apiJson(`/whiteboard/sketches/${sketch.id}`, {
      method: "PUT",
      body: JSON.stringify({
        data: sketch.data, board_id: sketch.board_id, x: sketch.x, y: sketch.y, z: sketch.z,
        group_id: sketch.group_id ?? null,
      }),
    });
    Object.assign(sketch, saved);
  } catch {
    recordBrowserLog("WARN", [`[Whiteboard] sketch ${sketch.id} is stale: reloading the board`]);
    await fetchWhiteboardState();
    wbScheduleRender();
  }
}

async function wbSaveSketchD(sketch, newD) {
  await wbSaveSketchProps(sketch, { d: newD });
}

// Paint-bucket tool: recolour whatever's clicked with the main toolbar's
// stroke colour. Closed shapes (rect/circle/triangle/diamond) get their
// fill set, since that's the area a bucket click reads as "inside" of;
// anything else (line/arrow/pen stroke) has no interior, so its stroke is
// recoloured instead, the same colour the rail's ink swatch shows.
async function wbBucketFillSketch(sketch) {
  const color = document.getElementById("wb-rail-ink")?.value || "#3355ff";
  let parsed;
  try {
    parsed = JSON.parse(sketch.data);
  } catch {
    return;
  }
  if (parsed && WB_FILLABLE_SHAPES.has(parsed.shape)) {
    await wbSaveSketchProps(sketch, { fill: color });
  } else {
    await wbSaveSketchProps(sketch, { color });
  }
  wbScheduleRender();
}

//: True once a sketch's `d` has more than one `M`, every shape this app's
//: own tools ever draw uses exactly one *except* an arrow (shaft + one or
//: two head subpaths, `wbArrowHeadPath`'s own `M`s). Good enough to tell
//: "this is an arrow" apart from a line/rect/circle/triangle/diamond/pen
//: stroke without a dedicated `kind` field on every sketch.
function wbSketchIsArrow(d) {
  return (d.match(/M/g) || []).length > 1;
}

//: Rebuilds a line/arrow's own two end caps from its shaft, the shaft is
//: always the sketch's first subpath, `M sx sy L ex ey` (every arrow this
//: app draws starts that way), so either end's cap can be changed after
//: the fact without needing to have stored which shape was originally
//: chosen. Independently per end (`WB_CAP_KINDS` each): asked for
//: directly ("a full line/arrow end-cap system... circle/square/multi-line
//: ends"), replacing the single shared arrowhead-only version.
function wbRegenerateShapeCaps(d, startCap, endCap, headLen) {
  const m = d.match(/^M\s*(-?[\d.]+(?:e-?\d+)?)\s+(-?[\d.]+(?:e-?\d+)?)\s+L\s*(-?[\d.]+(?:e-?\d+)?)\s+(-?[\d.]+(?:e-?\d+)?)/);
  if (!m) return d;
  const sx = parseFloat(m[1]), sy = parseFloat(m[2]), ex = parseFloat(m[3]), ey = parseFloat(m[4]);
  const angle = Math.atan2(ey - sy, ex - sx);
  let out = `M ${sx} ${sy} L ${ex} ${ey}`;
  if (endCap && endCap !== "none") out += " " + wbCapPath(endCap, ex, ey, angle, headLen);
  if (startCap && startCap !== "none") out += " " + wbCapPath(startCap, sx, sy, angle + Math.PI, headLen);
  return out;
}

//: What style a drawn line/arrow's own path is *actually* carrying,
//: needed because the properties panel used to just show whatever the
//: active drawing tool's current default was (live-reported bug, same
//: session as the Line-tool-always-drew-an-arrowhead one above), which
//: lies the moment a sketch's real style differs from that default.
//: `wbArrowHeadPath` always starts its own subpath at the tip it's drawn
//: for, so a head is detected by which of the shaft's two endpoints each
//: extra `M` lands on: exact, not guessed, since these are the same
//: coordinates the shaft itself was drawn from.
function wbDetectArrowStyle(d) {
  const m = d.match(/^M\s*(-?[\d.]+(?:e-?\d+)?)\s+(-?[\d.]+(?:e-?\d+)?)\s+L\s*(-?[\d.]+(?:e-?\d+)?)\s+(-?[\d.]+(?:e-?\d+)?)/);
  if (!m) return "none";
  const sx = parseFloat(m[1]), sy = parseFloat(m[2]), ex = parseFloat(m[3]), ey = parseFloat(m[4]);
  let hasEnd = false, hasStart = false;
  //: **Scanned from *after* the shaft's own `M`, not from the start of `d`.**
  //: Reported: "arrow drawn shows both caps as Arrow in properties" -
  //: reproduced live: an arrow with only an end head stored no `startCap`/
  //: `endCap` fields at all (an older/legacy shape), so this ran, and `m[0]`
  //: (the shaft's own leading `M sx sy L ex ey`, matched above) begins with
  //: exactly the same `M sx sy` a *real* start-cap marker would - the loop
  //: below used to scan the whole string including that leading `M`, so
  //: every plain shaft with no start cap at all still measured a
  //: zero-distance "hit" on its own start point and reported one anyway.
  //: Slicing it off leaves only the head subpaths `wbArrowHeadPath` actually
  //: appended, which is what this function is supposed to be reading.
  for (const extra of d.slice(m[0].length).matchAll(/M\s*(-?[\d.]+(?:e-?\d+)?)\s+(-?[\d.]+(?:e-?\d+)?)/g)) {
    const x = parseFloat(extra[1]), y = parseFloat(extra[2]);
    if (Math.hypot(x - ex, y - ey) < 0.5) hasEnd = true;
    else if (Math.hypot(x - sx, y - sy) < 0.5) hasStart = true;
  }
  if (hasEnd && hasStart) return "both";
  if (hasEnd) return "end";
  if (hasStart) return "start";
  return "none";
}

//: A drawn line/arrow's own two cap kinds, the explicit `startCap`/
//: `endCap` fields (any of `WB_CAP_KINDS`) if this sketch has them, or
//: `wbDetectArrowStyle`'s older binary read translated to "arrow"/"none"
//: for one saved before the full end-cap system existed. Explicit fields
//: rather than shape-sniffing every cap kind out of the raw path: circle
//: and square are geometrically ambiguous with plenty of things a pen
//: stroke could also draw, where an arrow's two-line V (`wbDetectArrowStyle`)
//: is not: so a *new* cap choice is trusted and stored, and only a link
//: with no stored choice at all falls back to inferring one.
function wbSketchCaps(parsed) {
  if (parsed.startCap !== undefined || parsed.endCap !== undefined) {
    return { startCap: parsed.startCap || "none", endCap: parsed.endCap || "none" };
  }
  const legacy = wbDetectArrowStyle(parsed.d);
  return {
    startCap: legacy === "start" || legacy === "both" ? "arrow" : "none",
    endCap: legacy === "end" || legacy === "both" ? "arrow" : "none",
  };
}

//: Two draggable handles at a selected link's own resolved endpoints, 
//: asked for directly: "I should be able to move the points where lines,
//: arrows and links connect on objects to other points or even make it a
//: dangling unattached point not attached to an object." Dragging one
//: rewrites *that end's* own reference (`sourceId`/`sourceAnchor` or
//: `targetId`/`targetAnchor`, reattach, snapping to the nearest of the
//: hovered card's 8 fixed anchors the same way creating a link already
//: does) or, released over empty canvas, `sourcePoint`/`targetPoint`, a
//: fixed board-space point with no card at all. `wbResolveLinkEndpoints`
//: already reads both shapes, so nothing else needs to change to render one.
// Remove every sketch handle group, from **both** layers it can live in.
//
// Reported with a screenshot: "when I change where links are connected on
// notes or objects on the whiteboard, these weird small circles are left
// hanging." They are link endpoint handles, and the cause was a layer split
// that the cleanup never caught up with, handles for a *link* are appended to
// `#wb-overlay-zoom-group` (they sit on a card's own border, which the base
// SVG paints underneath the card's HTML, so they had to move up a layer),
// while both existing clears only ever swept `#wb-zoom-group`. Every
// re-render appended a fresh group and none of the old ones was ever removed,
// so the circles accumulated.
//
// One helper, used by all three call sites, so a third layer cannot
// reintroduce the same gap quietly.
function wbClearSketchHandles() {
  for (const layer of ["#wb-zoom-group", "#wb-overlay-zoom-group"]) {
    d3.select(layer).selectAll(".wb-sketch-handle-group").remove();
  }
}

function wbRenderLinkEndpointHandles(sketch, parsed) {
  const endpoints = wbResolveLinkEndpoints(parsed);
  if (!endpoints) return;
  // The overlay layer (see its own comment in index.html), an endpoint
  // sits *on a card's own border* by definition, which the base SVG layer
  // paints underneath the card's HTML element. A handle there would be
  // both invisible and unclickable exactly where it's needed most.
  // Clear before drawing: this appends rather than data-joining, so without
  // it every call leaves its predecessor behind on the board.
  wbClearSketchHandles();
  const group = d3.select("#wb-overlay-zoom-group").append("g").attr("class", "wb-sketch-handle-group");

  // The bend handle: drag to curve the link, double-click to straighten it.
  // Sits at the control point (or the chord midpoint when there is none) so
  // the thing you grab is the thing that moves.
  {
    const mid = { x: (endpoints.source.x + endpoints.target.x) / 2, y: (endpoints.source.y + endpoints.target.y) / 2 };
    const bendLive = { x: parsed.bend?.x || 0, y: parsed.bend?.y || 0 };
    const paths = () => [".sketch-path", ".sketch-hitbox"].map((c) => document.querySelector(`.sketch-group[data-id="${sketch.id}"] ${c}`));
    const repaint = () => {
      const d = wbLinkPathD(parsed.type, endpoints.source, endpoints.target, wbLinkCaps(parsed), parsed.width, bendLive);
      for (const el of paths()) el?.setAttribute("d", d);
    };
    const handle = group.append("circle")
      .attr("class", "wb-link-bend-handle")
      .attr("cx", mid.x + bendLive.x).attr("cy", mid.y + bendLive.y)
      .attr("r", 6);
    handle.append("title").text("Drag to bend this link · double-click to straighten");
    handle.call(
      d3.drag()
        .on("start", (event) => event.sourceEvent.stopPropagation())
        .on("drag", function (event) {
          bendLive.x += event.dx;
          bendLive.y += event.dy;
          d3.select(this).attr("cx", mid.x + bendLive.x).attr("cy", mid.y + bendLive.y);
          repaint();
        })
        .on("end", async () => {
          const before = WB_KIND_INFO.sketch.payload(sketch);
          await wbSaveSketchProps(sketch, { bend: (bendLive.x || bendLive.y) ? { x: bendLive.x, y: bendLive.y } : undefined });
          wbPushUndo({ action: "move", kind: "sketch", id: sketch.id, before });
          wbScheduleRender();
        })
    ).on("dblclick", async (event) => {
      event.stopPropagation();
      const before = WB_KIND_INFO.sketch.payload(sketch);
      await wbSaveSketchProps(sketch, { bend: undefined });
      wbPushUndo({ action: "move", kind: "sketch", id: sketch.id, before });
      wbScheduleRender();
    });
  }

  //: Dragging a link's end onto something: any card, text box, sticky or
  //: shape, tested in its rotated frame. This was cards on their unrotated
  //: box, so an end dropped on a rotated sticky became a free point that
  //: floated just off it (reported, with a screenshot).
  const hoveredItemAt = (px, py) => wbLinkCandidateAt(px, py);

  for (const end of ["source", "target"]) {
    const other = end === "source" ? "target" : "source";
    const live = { x: endpoints[end].x, y: endpoints[end].y };
    group.append("circle")
      .attr("class", "wb-link-endpoint-handle")
      .attr("data-end", end)
      .attr("cx", live.x).attr("cy", live.y)
      .attr("r", 7)
      .style("cursor", "crosshair")
      .call(
        d3.drag()
          .on("start", (event) => event.sourceEvent.stopPropagation())
          .on("drag", function (event) {
            // No `/ transform.k` here: unlike the HTML-element card/object
            // drags elsewhere in this file, this circle's drag container
            // (its parent `<g>`, d3-drag's default) sits *inside* the zoomed
            // `#wb-overlay-zoom-group`. d3.pointer() resolves SVG coordinates
            // through the element's `getScreenCTM()`, which already folds in
            // every ancestor transform: so `event.dx`/`dy` arrive pre-divided
            // by the zoom scale. Dividing again here shrank every frame's
            // movement by a second factor of the zoom level: reported
            // directly ("when I drag the whiteboard links, it goes off my
            // cursor"), and confirmed live: at 2x zoom the handle trailed
            // the cursor by exactly half the dragged distance, growing every
            // frame, matching a `1/k` double-division exactly.
            live.x += event.dx;
            live.y += event.dy;
            d3.select(this).attr("cx", live.x).attr("cy", live.y);
            const previewPts = end === "source" ? [live, endpoints[other]] : [endpoints[other], live];
            const previewD = wbLinkPathD(parsed.type, previewPts[0], previewPts[1], wbLinkCaps(parsed), parsed.width, parsed.bend);
            document.querySelector(`.sketch-group[data-id="${sketch.id}"] .sketch-path`)?.setAttribute("d", previewD);
            document.querySelector(`.sketch-group[data-id="${sketch.id}"] .sketch-hitbox`)?.setAttribute("d", previewD);

            const hit = hoveredItemAt(live.x, live.y);
            if (hit) wbShowAnchorHints(hit[0], hit[1], wbNearestAnchor(hit[0], hit[1], live.x, live.y));
            else wbClearAnchorHints();
          })
          .on("end", async () => {
            wbClearAnchorHints();
            const before = WB_KIND_INFO.sketch.payload(sketch);
            const hit = hoveredItemAt(live.x, live.y);
            const partial = {};
            if (hit) {
              const [kind, item] = hit;
              partial[end + "Id"] = item.id;
              partial[end + "Kind"] = kind === "node" ? undefined : kind;
              partial[end + "Anchor"] = wbNearestAnchor(kind, item, live.x, live.y) || undefined;
              partial[end + "Point"] = undefined;
            } else {
              partial[end + "Id"] = undefined;
              partial[end + "Kind"] = undefined;
              partial[end + "Anchor"] = undefined;
              partial[end + "Point"] = { x: live.x, y: live.y };
            }
            await wbSaveSketchProps(sketch, partial);
            wbPushUndo({ action: "move", kind: "sketch", id: sketch.id, before });
            wbScheduleRender();
          })
      );
  }
}

// The handles themselves: a fresh SVG group per selection, since (unlike a
// card/object's own always-present handles) a sketch has no fixed element to
// attach 8 children to; it's rebuilt on every selection change and after
// every `wbScheduleRender()` re-applies the current selection.
function wbRenderSketchHandles() {
  wbClearSketchHandles();
  if (!wbSelectedItem || wbSelectedItem.kind !== "sketch") return;
  const sketch = wbState.sketches.find((s) => s.id === wbSelectedItem.id);
  if (!sketch) return;
  // A link sketch has no `.d` of its own: `wbSketchParsedData` returns
  // null for it, and the 8-point bbox resize handles below make no sense
  // for a path recomputed fresh from its endpoints every render anyway.
  // It gets its own two endpoint handles instead (below).
  let rawParsed;
  try { rawParsed = JSON.parse(sketch.data); } catch { rawParsed = null; }
  if (rawParsed && (rawParsed.type || "").startsWith("link-")) {
    wbRenderLinkEndpointHandles(sketch, rawParsed);
    return;
  }
  const parsed = wbSketchParsedData(sketch);
  if (!parsed) return;
  const bbox = wbPathBBox(parsed.d);
  if (!bbox) return;

  const group = d3.select("#wb-zoom-group")
    .append("g")
    .attr("class", "wb-sketch-handle-group");

  //: **One selection box for every kind** (WHITEBOARD_PLAN.md decision 6). A
  //: card and a text box wear a 1px `--accent` outline; a sketch wore a dashed
  //: 35%-opacity stroke *along its own path* instead, so the same click read
  //: as two different kinds of thing and a thin diagonal line had no box at
  //: all. This is that outline, drawn round the shape's own bbox.
  group.append("rect")
    .attr("class", "wb-sketch-selection-box")
    .attr("x", bbox.minX - 2).attr("y", bbox.minY - 2)
    .attr("width", (bbox.maxX - bbox.minX) + 4)
    .attr("height", (bbox.maxY - bbox.minY) + 4);

  for (const handle of ["nw", "n", "ne", "e", "se", "s", "sw", "w"]) {
    const hx = handle.includes("w") ? bbox.minX : handle.includes("e") ? bbox.maxX : (bbox.minX + bbox.maxX) / 2;
    const hy = handle.includes("n") ? bbox.minY : handle.includes("s") ? bbox.maxY : (bbox.minY + bbox.maxY) / 2;
    let rawDX = 0, rawDY = 0; // this handle's own running total for the drag closure below
    group.append("rect")
      .attr("class", "wb-sketch-resize-handle")
      .attr("data-handle", handle)
      .attr("x", hx - 5).attr("y", hy - 5)
      .attr("width", 10).attr("height", 10)
      .style("cursor", `${handle}-resize`)
      .call(
        d3.drag()
          .on("start", (event) => {
            event.sourceEvent.stopPropagation();
            // event.dx/dy are per-frame deltas (since the *previous* event,
            // not since the drag started), recomputing the transform from
            // the original bbox using only the latest frame's delta each
            // time would apply just that one frame's worth of movement and
            // throw the rest away. Accumulated from the start instead, the
            // same fix as the drag-snap accumulation bug above.
            rawDX = 0;
            rawDY = 0;
            sketch._resizeUndoBefore = WB_KIND_INFO.sketch.payload(sketch);
          })
          .on("drag", (event) => {
            const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
            rawDX += event.dx / transform.k;
            rawDY += event.dy / transform.k;
            const t = wbSketchResizeTransform(bbox, handle, rawDX, rawDY, event.sourceEvent.shiftKey);
            const newD = wbTransformPathD(parsed.d, t);
            document.querySelector(`.sketch-group[data-id="${sketch.id}"] .sketch-path`)?.setAttribute("d", newD);
            document.querySelector(`.sketch-group[data-id="${sketch.id}"] .sketch-hitbox`)?.setAttribute("d", newD);
            sketch._liveD = newD; // read at drag end, without waiting for a full render
          })
          .on("end", async () => {
            const before = sketch._resizeUndoBefore;
            delete sketch._resizeUndoBefore;
            if (sketch._liveD) {
              const finalD = sketch._liveD;
              delete sketch._liveD;
              await wbSaveSketchD(sketch, finalD);
              if (before) wbPushUndo({ action: "move", kind: "sketch", id: sketch.id, before });
            }
            wbScheduleRender();
          })
      );
  }

  // Rotation: asked for directly, the one thing cards/objects already had
  // (a drag handle above the item, Shift snaps to 15°) that a sketch
  // didn't, since its "shape" is its path data rather than a stored
  // rotation column. Baked into `d` on release via `wbTransformPathD`'s new
  // `rotate` support, the same "commit into the path" convention move and
  // resize already use for a sketch, not a live CSS transform, which
  // would need a rotation to remember and re-apply on every future edit
  // instead of just being the shape's own coordinates.
  const centerX = (bbox.minX + bbox.maxX) / 2, centerY = (bbox.minY + bbox.maxY) / 2;
  const handleY = bbox.minY - 28;
  //: The anchor both halves of this control are scaled about, in board units:
  //: the point where the stem meets the shape. See the grip rules in
  //: 07-whiteboard-misc.css: the circle and the stem are siblings rather than
  //: an element and its pseudo-element, so the shared origin cannot be written
  //: as a percentage of either one and has to come from the bbox here.
  const rotateAnchor = `${centerX}px ${bbox.minY}px`;
  group.append("line")
    .attr("class", "wb-rotate-handle-stem")
    .style("transform-origin", rotateAnchor)
    .attr("x1", centerX).attr("y1", bbox.minY).attr("x2", centerX).attr("y2", handleY);
  // Absolute, not incremental: the handle sits straight above the shape's
  // centre (0°, the same reference `wbAngleFromCenterDeg` uses), so the
  // rotation applied is exactly the pointer's own angle from vertical, the
  // same "the handle follows your cursor" feel `nodeRotateDrag` above
  // already established for cards.
  let rotateOriginalD = null, rotateLiveD = null;
  group.append("circle")
    .attr("class", "wb-sketch-rotate-handle")
    // r 6, not 7: the card and text-box grip is 12px across
    // (`.wb-rotate-handle`), and 14 against 12 was the one measured difference
    // left between the two recipes.
    .attr("cx", centerX).attr("cy", handleY).attr("r", 6)
    .style("transform-origin", rotateAnchor)
    .style("cursor", "grab")
    .call(
      d3.drag()
        .on("start", (event) => {
          event.sourceEvent.stopPropagation();
          rotateOriginalD = parsed.d;
          sketch._rotateUndoBefore = WB_KIND_INFO.sketch.payload(sketch);
        })
        .on("drag", (event) => {
          const currentAngle = wbSketchAngleFromCenterDeg(centerX, centerY, event.sourceEvent, event.sourceEvent.shiftKey);
          const newD = wbTransformPathD(rotateOriginalD, { rotate: currentAngle, anchorX: centerX, anchorY: centerY });
          rotateLiveD = newD;
          document.querySelector(`.sketch-group[data-id="${sketch.id}"] .sketch-path`)?.setAttribute("d", newD);
          document.querySelector(`.sketch-group[data-id="${sketch.id}"] .sketch-hitbox`)?.setAttribute("d", newD);
        })
        .on("end", async () => {
          const before = sketch._rotateUndoBefore;
          delete sketch._rotateUndoBefore;
          if (rotateLiveD) {
            const finalD = rotateLiveD;
            rotateLiveD = null;
            await wbSaveSketchD(sketch, finalD);
            if (before) wbPushUndo({ action: "move", kind: "sketch", id: sketch.id, before });
          }
          wbScheduleRender();
        })
    );
}

// Coalesce a burst of state changes into one paint.
//
// **This is the cause of the whiteboard feeling "janky and uncomfortable".**
// renderWhiteboard() below is a full d3 data-join over every sketch, node and
// object on the board, and it was called directly from 48 places. A single
// user action routinely touches several of them, move a card, update its
// links, mark the board dirty, refresh the selection, so one drag or one
// paste could repaint the entire board three or four times in the same frame,
// each pass re-joining every item and re-binding every handler.
//
// Nothing here makes the render itself cheaper. It makes it happen once per
// frame instead of once per state change, which is where the wasted work
// actually was. requestAnimationFrame rather than a microtask because the
// point is to land exactly one paint per displayed frame.
//
// **Safe to batch because no caller reads the DOM straight after rendering**, 
// checked across all 48 sites before converting them; a call followed by a
// getBoundingClientRect or querySelector would have needed to stay synchronous
// and none was. `renderWhiteboardNow()` is kept for anything that ever does.
let wbRenderQueued = false;

function wbScheduleRender() {
  if (wbRenderQueued) return;
  wbRenderQueued = true;
  requestAnimationFrame(() => {
    wbRenderQueued = false;
    renderWhiteboard();
    wbUpdateSelectionBar();
  });
}

// The unbatched escape hatch. Prefer wbScheduleRender(); use this only when
// the very next statement has to read the rendered DOM.
function renderWhiteboardNow() {
  wbRenderQueued = false;
  renderWhiteboard();
  // A render replaces card elements, so the search highlight classes are gone
  // with them and the navigator's item rectangles are stale. Both re-apply
  // from state rather than being re-derived by their own callers.
  wbApplySearchHighlight();
  wbRenderNavigator();
}

function renderWhiteboard() {
  // Built once per render, not once per card: `allEntries.find(...)` inside
  // a per-card callback is O(cards × notebook size) on every single render
  //, for a large notebook that is real, measurable work paid on every
  // whiteboard update, not just once. A note's id never changes shape
  // (string vs number) across a session, so this Map stays valid for the
  // whole render pass below.
  const entriesById = new Map(allEntries.map((e) => [String(e.id), e]));

  document
    .getElementById("wb-empty-hint")
    ?.classList.toggle(
      "hidden",
      // Objects count too: a board holding only a text box or an image is
      // not empty, and left out of this sum the hint sat on top of them.
      // Asked for directly: an option to turn the hint off entirely, once
      // it's served its purpose, `localStorage`, the same durability the
      // onboarding tour's own "don't show again" already uses.
      // `wbHintForcedOpen` overrides both checks: the "?" help button's way
      // back after a dismiss, or on a board that already has content.
      !wbHintForcedOpen &&
        // A map gets `#wb-map-empty` instead: this panel is the whiteboard's
        // own help, and on an emptied map it was pens, shapes and the eraser
        // sitting over a surface none of them apply to.
        (wbIsMap() ||
          (wbState.nodes?.length || 0) +
          (wbState.sketches?.length || 0) +
          (wbState.objects?.length || 0) >
            0 ||
          localStorage.getItem("wbEmptyHintDismissed") === "1")
    );

  // Render Sketches (SVG)
  const svgGroup = d3.select("#wb-zoom-group");
  const sketchSelection = svgGroup.selectAll("g.sketch-group")
    .data((wbState.sketches || []).filter(wbSketchIsDrawable), d => d.id);
    
  // Deleting a sketch two ways: "delete" is a click on the one thing you
  // mean to remove; "eraser" is a drag: mouseenter fires for everything the
  // pointer crosses while wbErasing is true, matching how an eraser tool
  // behaves in every other drawing app.
  async function deleteSketch(d) {
    const deletingKey = `sketch:${d.id}`;
    if (wbDeleting.has(deletingKey)) return;
    wbDeleting.add(deletingKey);
    wbPushUndo({
      action: "delete",
      kind: "sketch",
      payload: { data: d.data, board_id: d.board_id, x: d.x, y: d.y, z: d.z },
    });
    try {
      await apiJson(`/whiteboard/sketches/${d.id}`, { method: "DELETE" });
      wbState.sketches = wbState.sketches.filter((s) => s.id !== d.id);
      wbScheduleRender();
    } catch (e) {
      console.error(e);
      wbUndoStack.pop(); // the delete never happened, so neither did the undo entry
    } finally {
      wbDeleting.delete(deletingKey);
    }
  }
  // `deleteSketch`/`deleteNode` are re-created on every render (they close
  // over this render's own `d3` selections), so the Delete-key handler set
  // up once in `initWhiteboard` can't reference them directly, it always
  // needs *this* render's version, not whichever one existed when it was
  // first wired.
  wbDeleteSketchRef = deleteSketch;

  // Move: reported directly: "can't move objects made or drawn on
  // whiteboard". Cards/objects get this from their own `d3.drag`; a sketch
  // never had one at all. Filtered to the Select tool only, the same as a
  // click here means "select" rather than "erase", under any other tool
  // (pan, a brush, eraser/delete) this must stay out of the way entirely,
  // pan in particular, since the canvas's own zoom/pan drag needs an
  // unclaimed pointerdown to reach it.
  const sketchDrag = d3.drag()
    .filter(() => window.currentTool === "select" || Boolean(window.currentTool?.startsWith("link-")))
    .on("start", function (event, d) {
      event.sourceEvent.stopPropagation();
      // A link tool drags a *link* out of the shape, not the shape, the same
      // delegation `objDrag` does for text boxes and stickies.
      if (window.currentTool?.startsWith("link-")) {
        if (!wbSketchParsedData(d)) return;
        d._linkKind = "sketch";
        return dragStart.call(this, event, d);
      }
      const parsed = wbSketchParsedData(d);
      d._linkedSketches = wbLinkedSketchesFor(d.id, "sketch");
      d._dragOriginalD = parsed ? parsed.d : null;
      d._moveUndoBefore = WB_KIND_INFO.sketch.payload(d);
      // Raw (never-snapped) running totals, applied fresh from the
      // *original* d each frame, the same fix as `dragging`'s own comment
      // above: re-snapping an already-snapped value every frame discards
      // the sub-grid remainder and can get stuck.
      d._dragRawDX = 0;
      d._dragRawDY = 0;
      // Selection itself is deliberately *not* touched here, it lives
      // entirely in the 'click' listener below, which only ever fires for a
      // genuinely unmoved gesture (d3 suppresses the native click once real
      // movement crosses the threshold). Doing it here too, keyed off "did
      // this drag start", was tried and had a real bug: `wbDragIsBulkMove`
      // is also true for a second shift-click meant to *toggle a member
      // back off* an existing multi-selection, so treating every "start" as
      // "begin a bulk move" swallowed that click's toggle entirely: a
      // second shift-click on an already-selected item did nothing.
      // `d._bulkOrigin` itself is decided lazily, on the first real "drag"
      // frame below, for the same reason.
    })
    .on("drag", function (event, d) {
      if (d._linkKind === "sketch") return dragging.call(this, event, d);
      if (d._dragOriginalD == null) return;
      // First real movement of this gesture, decide once whether this is
      // a solo move or a bulk move of the whole multi-selection. Deferred
      // to here rather than "start" (see its own comment) specifically so
      // a zero-movement click never reaches this at all.
      if (d._bulkOrigin === undefined) {
        d._bulkOrigin = wbDragIsBulkMove("sketch", d.id)
          ? wbCaptureBulkMoveOrigin(wbMultiKey("sketch", d.id))
          : null;
      }
      const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
      d._dragRawDX += event.dx / transform.k;
      d._dragRawDY += event.dy / transform.k;
      const bypassSnap = event.sourceEvent?.altKey;
      const dx = wbSnap(d._dragRawDX, bypassSnap), dy = wbSnap(d._dragRawDY, bypassSnap);
      const newD = wbTransformPathD(d._dragOriginalD, { dx, dy });
      d._dragLiveD = newD;
      const el = document.querySelector(`.sketch-group[data-id="${d.id}"]`);
      el?.querySelector(".sketch-path")?.setAttribute("d", newD);
      el?.querySelector(".sketch-hitbox")?.setAttribute("d", newD);
      if (d._linkedSketches?.length) wbUpdateLinkedSketches(d.id, d._linkedSketches);
      wbUpdateSelectionBar();
      if (d._bulkOrigin) wbApplyBulkMove(d._bulkOrigin, dx, dy);
      // Handles would otherwise trail the sketch by a whole render, cheap
      // to keep in step since there are at most 8 of them.
      wbClearSketchHandles();
    })
    .on("end", async function (event, d) {
      if (d._linkKind === "sketch") {
        const r = dragEndNode.call(this, event, d);
        d._linkKind = null;
        return r;
      }
      delete d._linkedSketches;
      if (d._dragOriginalD == null) return;
      const finalD = d._dragLiveD;
      const bulkOrigin = d._bulkOrigin;
      const moveBefore = d._moveUndoBefore;
      delete d._dragOriginalD;
      delete d._dragRawDX;
      delete d._dragRawDY;
      delete d._dragLiveD;
      delete d._bulkOrigin;
      delete d._moveUndoBefore;
      // `finalD`/`bulkOrigin` are only ever set once real movement occurred
      // (in "drag" above): a zero-movement click leaves both undefined, so
      // this correctly does nothing rather than a wasted save.
      if (finalD) {
        await wbSaveSketchD(d, finalD);
        if (moveBefore) wbPushUndo({ action: "move", kind: "sketch", id: d.id, before: moveBefore });
      }
      if (bulkOrigin) await wbSaveBulkMove(bulkOrigin);
      wbScheduleRender();
    });

  const sketchEnter = sketchSelection.enter()
    .append("g")
    .attr("class", "sketch-group")
    .attr("data-id", d => d.id)
    .style("cursor", () => (window.currentTool === "delete" || window.currentTool === "eraser" || window.currentTool === "select") ? "pointer" : "default")
    .call(sketchDrag)
    .on("dblclick", async (event, d) => {
      // Asked for directly: "double click on lines, add points for curving
      // lines and connections." Only a link has a bend; a drawn shape's own
      // double-click is left to whatever else wants it.
      let parsed = null;
      try { parsed = JSON.parse(d.data); } catch { parsed = null; }
      if (!parsed || !(parsed.type || "").startsWith("link-")) return;
      event.stopPropagation();
      const endpoints = wbResolveLinkEndpoints(parsed);
      if (!endpoints) return;
      const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
      const rect = document.getElementById("wb-svg-layer").getBoundingClientRect();
      const px = (event.clientX - rect.left - transform.x) / transform.k;
      const py = (event.clientY - rect.top - transform.y) / transform.k;
      const mid = { x: (endpoints.source.x + endpoints.target.x) / 2, y: (endpoints.source.y + endpoints.target.y) / 2 };
      // A quadratic through the click: the control point is twice as far from
      // the chord as the point you want the curve to pass through.
      const bend = { x: (px - mid.x) * 2, y: (py - mid.y) * 2 };
      const before = WB_KIND_INFO.sketch.payload(d);
      await wbSaveSketchProps(d, { bend });
      wbPushUndo({ action: "move", kind: "sketch", id: d.id, before });
      wbSelectToolRef?.("select");
      selectWbItem("sketch", d.id);
      wbScheduleRender();
    })
    .on("click", (event, d) => {
      // ROADMAP row 0(b), asked for directly: with the Hand active, a plain
      // click on something switches to Select and selects it. A pan is a
      // drag; a click that moved nothing is a choice of *this*, and every
      // whiteboard app (Miro, FigJam, tldraw) reads it that way.
      if (window.currentTool === "select" || window.currentTool === "pan") {
        event.stopPropagation(); // don't also hit the "empty canvas clears selection" handler
        if (window.currentTool === "pan") wbSelectToolRef?.("select");
        wbHandleItemClick("sketch", d.id, event);
        return;
      }
      // Reported directly, same family as the pen's single-click dot: a
      // plain click with the eraser (no drag across anything) did nothing, 
      // only `mouseenter` while `wbErasing` was true caught a stroke, which
      // needs movement to fire at all. The eraser is "delete, but you can
      // also drag across several", a single click should erase the one
      // thing clicked, the same as the delete tool does.
      if (window.currentTool === "delete" || window.currentTool === "eraser") deleteSketch(d);
      if (window.currentTool === "bucket") { event.stopPropagation(); wbBucketFillSketch(d); }
    })
    .on("pointerenter", (event, d) => {
      if (window.currentTool === "eraser" && wbErasing) deleteSketch(d);
    });

  sketchEnter.append("path")
    .attr("class", "sketch-hitbox")
    .attr("fill", "none")
    .attr("stroke", "transparent")
    .attr("stroke-width", "20")
    // A closed shape (rect/circle/triangle/diamond) reads as solid, so
    // clicking its interior should select it, not just the ~20px band
    // around its outline that's the only sensible hit-area an open pen/line
    // squiggle has. Reported directly ("shapes are hard to select"): every
    // sketch used `pointer-events: stroke`, so a rectangle's hollow middle
    // silently didn't count as a click on it.
    .attr("pointer-events", (d) => wbSketchIsClosedShape(d) ? "all" : "stroke");

  sketchEnter.append("path")
    .attr("class", "sketch-path")
    .attr("fill", "none")
    .attr("stroke-width", "3")
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round")
    .attr("pointer-events", "none");

  wbWireContextMenu(sketchEnter, "sketch");

  const sketchUpdate = sketchEnter.merge(sketchSelection);

  // A cross-link on a map is drawn dashed (MINDMAP_PLAN.md §5 item 9, the
  // systems-map convention for "related, but not part of the tree"). The
  // sketch itself is untouched, this is a class, so the same link on an
  // ordinary board still draws exactly as it always did, and nothing about the
  // stored data changes when a board's type does.
  const crossLinkIds = new Set(
    wbIsMap() ? (window.wbMapState?.crossLinks || []).map((l) => `${l.from_id}:${l.to_id}`) : []
  );
  sketchUpdate.classed("wb-map-crosslink", (d) => {
    if (!crossLinkIds.size) return false;
    let parsed;
    try {
      parsed = JSON.parse(d.data);
    } catch {
      return false;
    }
    return crossLinkIds.has(`${parsed?.sourceId}:${parsed?.targetId}`);
  });

  sketchUpdate.each(function(d) {
    let pathData = d.data;
    let stroke = "var(--text-color)";
    let strokeWidth = "3";
    let strokeOpacity = 1;
    let fill = "none";
    let fillOpacity = 1;
    let dashArray = null;
    let isHighlighterStroke = false;
    try {
      const parsed = JSON.parse(d.data);
      if (parsed.d) {
        pathData = parsed.d;
        // `shape` names the tool that drew it, which is what says "highlighter"
        // rather than "a stroke that happens to carry an opacity": a pen
        // stroke restyled through the context bar could have one too.
        isHighlighterStroke = parsed.shape === "highlighter";
        stroke = parsed.noStroke ? "none" : (parsed.color || stroke);
        // Highlighter strokes carry their own width/opacity (see the mouseup
        // handler that writes them), everything else keeps the defaults
        // above, set explicitly every render so a reused element can't keep
        // a stale highlighter width after its data changes.
        if (parsed.width) strokeWidth = String(parsed.width);
        if (parsed.opacity != null) strokeOpacity = parsed.opacity;
        // Fill/dash: asked for directly ("fill colour/transparency...
        // stroke width, style, and colour"). Absent on any sketch drawn
        // before this existed, which is exactly why these default to "no
        // fill, solid" rather than reading undefined.
        if (parsed.fill) {
          fill = parsed.fill;
          fillOpacity = parsed.fillOpacity != null ? parsed.fillOpacity : 1;
        }
        dashArray = wbDashArray(parsed.dash || "solid", parsed.width || 3);
      } else if (parsed.type && parsed.type.startsWith("link-")) {
        stroke = parsed.color || stroke;
        strokeWidth = String(parsed.width || 3);
        dashArray = wbDashArray(parsed.dash || "solid", parsed.width || 3);
        const endpoints = wbResolveLinkEndpoints(parsed);
        pathData = endpoints ? wbLinkPathD(parsed.type, endpoints.source, endpoints.target, wbLinkCaps(parsed), parsed.width, parsed.bend) : "";
      }
    } catch(e) {}
    d3.select(this).select(".sketch-hitbox").attr("d", pathData);
    d3.select(this).select(".sketch-path")
      // The highlighter's multiply, re-applied every render and cleared on
      // every other kind so a reused element cannot keep it: the same reason
      // the width and opacity above are set explicitly rather than only when
      // present. Inline rather than a class because the export clones these
      // nodes into a standalone SVG.
      .style("mix-blend-mode", isHighlighterStroke ? "multiply" : null)
      .attr("d", pathData)
      .attr("stroke", stroke)
      .attr("stroke-width", strokeWidth)
      .attr("stroke-opacity", strokeOpacity)
      .attr("fill", fill)
      .attr("fill-opacity", fillOpacity)
      // `null` removes the attribute entirely (d3's own convention) rather
      // than setting `stroke-dasharray=""`, which some renderers treat as
      // "zero-length dashes" instead of "solid", a reused element from a
      // dashed sketch must not leave a stale dasharray on a solid one.
      .attr("stroke-dasharray", dashArray);
  });
    
  sketchSelection.exit().remove();

  // Render Nodes (Cards)
  const canvas = d3.select("#wb-html-layer");
  const nodeSelection = canvas.selectAll(".wb-card.node-card")
    .data(wbState.nodes, d => d.id);
    
  async function deleteNode(d) {
    const deletingKey = `node:${d.id}`;
    if (wbDeleting.has(deletingKey)) return;
    wbDeleting.add(deletingKey);
    wbPushUndo({
      action: "delete",
      kind: "node",
      payload: { entry_id: d.entry_id, board_id: d.board_id, x: d.x, y: d.y, z: d.z },
    });
    try {
      await apiJson(`/whiteboard/nodes/${d.id}`, { method: "DELETE" });
      wbState.nodes = wbState.nodes.filter((n) => n.id !== d.id);
      // also delete links connected to it? For MVP just delete the node.
      wbScheduleRender();
    } catch (e) {
      console.error(e);
      wbUndoStack.pop();
    } finally {
      wbDeleting.delete(deletingKey);
    }
  }
  wbDeleteNodeRef = deleteNode; // see the matching comment on wbDeleteSketchRef above

  //: Card resize: asked for directly ("resizing... cards"). `width`/`height`
  //: are nullable (unset means "auto", the CSS-sized default every card used
  //: before this existed); a resize sets them explicitly for the first time.
  //: Shares `resizeDrag`'s own maths (see `renderWbObjects`) rather than a
  //: second copy: the two differ only in which element/datum they close
  //: over, so it's built inline here with the same shape.
  function nodeResizeDrag(handle) {
    let rawDX = 0, rawDY = 0;
    return d3.drag()
      // The handle sits inside the card it resizes, see
      // `wbStableDragContainer`. Matters for `w`/`n`, which move x/y too.
      .container(wbStableDragContainer(".node-card"))
      .on("start", (event, d) => {
        event.sourceEvent.stopPropagation();
        rawDX = 0;
        rawDY = 0;
        d._resizeUndoBefore = WB_KIND_INFO.node.payload(d);
      })
      .on("drag", (event, d) => {
        const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
        rawDX += event.dx / transform.k;
        rawDY += event.dy / transform.k;
        const startW = d._resizeStartW ?? (d._resizeStartW = d.width || WB_CARD_DEFAULT_SIZE.w);
        const startH = d._resizeStartH ?? (d._resizeStartH = d.height || WB_CARD_DEFAULT_SIZE.h);
        const startX = d._resizeStartX ?? (d._resizeStartX = d.x);
        const startY = d._resizeStartY ?? (d._resizeStartY = d.y);
        let width = startW, height = startH, x = startX, y = startY;
        if (handle.includes("e")) width = Math.max(WB_OBJECT_MIN_SIZE, startW + rawDX);
        if (handle.includes("w")) width = Math.max(WB_OBJECT_MIN_SIZE, startW - rawDX);
        if (handle.includes("s")) height = Math.max(WB_OBJECT_MIN_SIZE, startH + rawDY);
        if (handle.includes("n")) height = Math.max(WB_OBJECT_MIN_SIZE, startH - rawDY);
        // Reported directly: shift while resizing didn't snap to a square.
        // Only a corner handle has two free axes to lock together, the
        // larger of the two free-form sizes wins. Computed before the x/y
        // anchor adjustment below so a w/n handle's anchor math sees the
        // final, square-constrained size rather than the pre-shift one.
        if (handle.length === 2 && event.sourceEvent.shiftKey) {
          width = height = Math.max(width, height);
        }
        if (handle.includes("w")) x = startX + (startW - width);
        if (handle.includes("n")) y = startY + (startH - height);
        d.width = width;
        d.height = height;
        d.x = x;
        d.y = y;
        const el = document.querySelector(`.node-card[data-id="${d.id}"]`);
        if (el) {
          el.style.width = `${width}px`;
          el.style.height = `${height}px`;
          el.style.transform = wbItemTransform(d);
        }
      })
      .on("end", async (event, d) => {
        delete d._resizeStartW;
        delete d._resizeStartH;
        delete d._resizeStartX;
        delete d._resizeStartY;
        await wbSaveNode(d);
        const before = d._resizeUndoBefore;
        delete d._resizeUndoBefore;
        if (before) wbPushUndo({ action: "move", kind: "node", id: d.id, before });
        wbScheduleRender();
      });
  }

  //: Rotation: asked for directly, more than once ("rotations", "anchor
  //: points, rotations, resizing, cropping"). A single handle above the
  //: item's own top-centre, the same convention every drawing app uses;
  //: `getBoundingClientRect()`'s centre stays correct even mid-rotation
  //: (an axis-aligned box's centre coincides with the true rotation centre
  //: regardless of how far the box itself has turned), so this needs no
  //: zoom/pan math the way position drags do, only the *angle* to the
  //: cursor matters, and angle is unaffected by uniform scale/pan.
  function nodeRotateDrag() {
    return d3.drag()
      .on("start", (event, d) => {
        event.sourceEvent.stopPropagation();
        d._rotateUndoBefore = WB_KIND_INFO.node.payload(d);
      })
      .on("drag", (event, d) => {
        const el = document.querySelector(`.node-card[data-id="${d.id}"]`);
        if (!el) return;
        const rect = el.getBoundingClientRect();
        d.rotation = wbAngleFromCenterDeg(
          rect.left + rect.width / 2, rect.top + rect.height / 2,
          event.sourceEvent.clientX, event.sourceEvent.clientY,
          event.sourceEvent.shiftKey
        );
        el.style.transform = wbItemTransform(d);
      })
      .on("end", async (event, d) => {
        await wbSaveNode(d);
        const before = d._rotateUndoBefore;
        delete d._rotateUndoBefore;
        if (before) wbPushUndo({ action: "move", kind: "node", id: d.id, before });
      });
  }

  const nodeEnter = nodeSelection.enter()
    .append("div")
    .attr("class", "wb-card node-card")
    .attr("data-id", (d) => d.id)
    .style("transform", wbItemTransform)
    .style("width", (d) => (d.width ? `${d.width}px` : ""))
    .style("height", (d) => (d.height ? `${d.height}px` : ""))
    .style("z-index", d => d.z)
    .call(d3.drag()
      // Reported directly: drawing over a note "just moves the note
      // instead" of drawing on it. Cards sit in `#wb-html-layer`, a sibling
      // painted on top of `#wb-svg-layer`, a pointerdown that lands on a
      // card never reaches the SVG layer's own draw listener at all, and
      // this drag (bound directly to the card) intercepted it first
      // regardless of which tool was active. Filtering it out here, rather
      // than only inside the start/drag handlers below, stops d3 from
      // capturing the gesture in the first place, so the same pointerdown
      // is free to bubble to `containerEl`'s brush listener instead.
      // A resize handle (below) owns its own drag, same reasoning as
      // `objDrag`'s own filter, and a real bug this filter's absence caused:
      // without the exclusion, this card-level drag also engaged for the
      // exact same pointerdown, and whichever one's gesture-tracking the
      // browser resolved first silently won, so a resize handle drag never
      // visibly resized anything.
      // `currentTool !== "lasso"`: reported directly ("the lasso tool
      // doesn't work properly"), a lasso loop is meant to start from
      // anywhere, including right at a card's own edge, but this filter
      // (unlike the lasso's own pointerdown listener) never excluded the
      // lasso tool the way it already excludes the brush tools, so a lasso
      // gesture begun on top of a card silently moved the card instead of
      // ever reaching the lasso's own draw logic.
      // `.wb-card-more`: the Show more/less toggle added below, without this
      // exclusion its pointerdown started a card drag the same way a resize
      // handle's did before it was excluded (see that comment above), so the
      // click never registered and the toggle silently did nothing.
      .filter((event) => !WB_BRUSH_TOOLS.has(window.currentTool) && window.currentTool !== "lasso" && !event.ctrlKey && !event.button && !event.target.closest(".wb-resize-handle, .wb-rotate-handle, .wb-card-more"))
      .on("start", dragStart)
      .on("drag", dragging)
      .on("end", dragEndNode))
    .on("click", (event, d) => {
      // ROADMAP row 0(b), asked for directly: with the Hand active, a plain
      // click on something switches to Select and selects it. A pan is a
      // drag; a click that moved nothing is a choice of *this*, and every
      // whiteboard app (Miro, FigJam, tldraw) reads it that way.
      if (window.currentTool === "select" || window.currentTool === "pan") {
        event.stopPropagation();
        if (window.currentTool === "pan") wbSelectToolRef?.("select");
        wbHandleItemClick("node", d.id, event);
        return;
      }
      // Same fix as the sketch group above: a single eraser click, no drag,
      // now erases the one card clicked instead of needing movement to
      // trigger a mouseenter.
      if (window.currentTool === "delete" || window.currentTool === "eraser") deleteNode(d);
    })
    .on("pointerenter", (event, d) => {
      if (window.currentTool === "eraser" && wbErasing) deleteNode(d);
    });
      
  // Reported directly: "when I attach notes to a whiteboard I want to see
  // the WHOLE note, not a cut-off version". This used to hard-truncate to
  // 100 plain-text characters with no way back to the rest, worse than the
  // Notes list's own long-note handling, which this now matches: render the
  // full note through the app's real markdown renderer (not textContent: 
  // a note can have headings, code, links), clamp it only past a height cap,
  // and give it the same "Show more"/"Show less" control and wording as
  // `.entry-more`, keyed by this whiteboard node's id in `wbExpandedNodes`
  // (not the note's own id: the same note can sit on the board twice).
  nodeEnter.each(function (d) {
    const card = d3.select(this);
    const entry = entriesById.get(String(d.entry_id));
    if (!entry) {
      // **"Loading…" with nothing loading.** `entriesById` is built from
      // `allEntries`, the app's in-memory note list, so a card whose note
      // was created *after* the last `loadEntries()` said "Loading…"
      // forever, because nothing here ever fetched it. Every path that
      // creates a note and immediately places it now refreshes that list
      // first (`wbMindMapAddCard`, `createConceptMap`), which is the real
      // fix; this branch is the honest fallback for the case that remains:
      // a card pointing at a note that has actually been deleted.
      card.append("div").attr("class", "wb-card-content muted").node().textContent =
        "This note is no longer here";
      return;
    }
    // A sketch's actual content is a file attachment, not text, never
    // reflected here before (§89 item 10): thumb_attachment_id/thumb_url
    // covers that, entry.attachments covers a note with a real attached
    // image. Same priority libraryCard() (library.js) already uses. A
    // pasted/dropped image living as inline markdown in entry.content is
    // NOT handled here: that already renders through renderMarkdown below,
    // and would be shown twice if it were.
    const firstImageAttachment = (entry.attachments || []).find((a) => a.is_image);
    const thumbSrc = entry.thumb_attachment_id
      ? mediaSrc(`/files/${entry.thumb_attachment_id}`)
      : entry.thumb_url
      ? mediaSrc(entry.thumb_url)
      : firstImageAttachment
      ? mediaSrc(`/files/${firstImageAttachment.id}`)
      : null;
    if (thumbSrc) {
      card.append("img").attr("class", "wb-card-thumb").attr("src", thumbSrc).attr("alt", "").attr("loading", "lazy");
    }
    const contentEl = card.append("div").attr("class", "wb-card-content").node();
    const text = entry.content || entry.preview || "";
    if (!text) {
      // The thumbnail above IS the content for a sketch/image-only note, 
      // "Empty note" next to a picture would read as a bug, not a note.
      if (!thumbSrc) contentEl.textContent = "Empty note";
      return;
    }
    renderMarkdown(contentEl, text);
    const isLong = text.length > LONG_NOTE_CHARS || text.split("\n").length > LONG_NOTE_LINES;
    if (!isLong) return;
    const expanded = () => wbExpandedNodes.has(d.id);
    contentEl.classList.toggle("wb-card-content-clamped", !expanded());
    const toggle = card.append("button")
      .attr("type", "button")
      .attr("class", "entry-more wb-card-more")
      .text(expanded() ? "Show less" : "Show more");
    toggle.on("click", (event) => {
      event.stopPropagation();
      if (expanded()) wbExpandedNodes.delete(d.id);
      else wbExpandedNodes.add(d.id);
      contentEl.classList.toggle("wb-card-content-clamped", !expanded());
      toggle.text(expanded() ? "Show less" : "Show more");
    });
  });

  for (const handle of ["nw", "n", "ne", "e", "se", "s", "sw", "w"]) {
    nodeEnter.append("div")
      .attr("class", "wb-resize-handle")
      .attr("data-handle", handle)
      .call(nodeResizeDrag(handle));
  }
  nodeEnter.append("div")
    .attr("class", "wb-rotate-handle")
    .attr("title", "Drag to rotate: hold Shift to snap to 15°")
    .call(nodeRotateDrag());

  wbWireContextMenu(nodeEnter, "node");

  nodeSelection.merge(nodeEnter)
    .style("transform", wbItemTransform)
    .style("width", (d) => (d.width ? `${d.width}px` : ""))
    .style("height", (d) => (d.height ? `${d.height}px` : ""))
    .style("z-index", d => d.z);

  nodeSelection.exit().remove();

  renderWbObjects(canvas);

  // After the nodes, never before: an edge is drawn between two *measured*
  // boxes (`wbMapNodeSize` reads `offsetHeight`, since a map node's height is
  // its text's), so running this first would measure the previous render's
  // sizes and leave every edge one frame stale, visible as edges that lag
  // behind a node the moment its text changes length.
  wbRenderMapEdges();

  // Every element above was just rebuilt, so any `.wb-selected` class set
  // before this render is gone with it, re-apply from the state that
  // actually persists (`wbSelectedItem`), not the DOM.
  wbApplySelectionHighlight();
}

//: Min size a resize can shrink an object to, small enough for a sticky
//: note, too small to lose an image/text box entirely off the canvas.
const WB_OBJECT_MIN_SIZE = 40;

//: One PUT body builder for a node, shared by every call site that saves
//: one (drag-end, resize-end, bulk-move, grouping), three of those used to
//: each build the body by hand, and it was exactly that duplication that
//: let a save silently drop `group_id` back to null the first time this
//: file added it (nothing reminded the third copy to include the new field).
async function wbSaveNode(node) {
  try {
    const saved = await apiJson(`/whiteboard/nodes/${node.id}`, {
      method: "PUT",
      body: JSON.stringify({
        entry_id: node.entry_id,
        board_id: node.board_id ?? window.currentBoardId ?? null,
        x: node.x, y: node.y, z: node.z,
        width: node.width ?? null, height: node.height ?? null,
        rotation: node.rotation ?? null,
        group_id: node.group_id ?? null,
      }),
    });
    Object.assign(node, saved);
  } catch {
    recordBrowserLog("WARN", [`[Whiteboard] card ${node.id} is stale: reloading the board`]);
    await fetchWhiteboardState();
    wbScheduleRender();
  }
}

async function wbSaveObject(d) {
  const body = {
    kind: d.kind, data: d.data, board_id: d.board_id,
    x: d.x, y: d.y, z: d.z, width: d.width, height: d.height,
    rotation: d.rotation ?? null,
    group_id: d.group_id ?? null,
  };
  try {
    const saved = await apiJson(`/whiteboard/objects/${d.id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    Object.assign(d, saved);
  } catch {
    // Same recoverable-stale-client shape every other whiteboard write here
    // already follows: a 404 means this object (or its board) is gone.
    recordBrowserLog("WARN", [`[Whiteboard] object ${d.id} is stale: reloading the board`]);
    await fetchWhiteboardState();
    wbScheduleRender();
  }
}

// Cards and sketches each render in their own function, inlined into
// renderWhiteboard directly; objects get their own function instead, two
// genuinely different element shapes (an <img>, a contenteditable <div>)
// sharing one drag+resize+select scaffold reads better factored out than
// inlined a third time.
function renderWbObjects(canvas) {
  async function deleteObject(d) {
    // The same rule as the map's own subtree delete, at the other door: this
    // is what the Delete tool, the context menu's Delete and the selection
    // bar all call, and a rule enforced at one of two doors is not a rule.
    if (WB_MAP_KINDS.has(d.kind) && wbMapDeleteEmptiesMap(d.id)) {
      wbMapRefuseLastTopic();
      return;
    }
    const deletingKey = `object:${d.id}`;
    if (wbDeleting.has(deletingKey)) return;
    wbDeleting.add(deletingKey);
    wbPushUndo({ action: "delete", kind: "object", payload: WB_KIND_INFO.object.payload(d) });
    try {
      const res = await apiJson(`/whiteboard/objects/${d.id}`, { method: "DELETE" });
      // **Whatever the server says it deleted, not just the row we asked
      // about.** On a map this endpoint takes the node's whole subtree and
      // returns it as `deleted[]` (§9.1), so dropping only `d.id` here left
      // every descendant on the canvas as a card pointing at a row that no
      // longer exists: visible as nodes that survive a delete and then 404
      // on the next save. Found by deleting a branch with the Delete key and
      // counting: the server removed two rows, the board still drew one of
      // them. An ordinary text box or image has no children, so `deleted`
      // is a single row there and this is exactly what it always was.
      const gone = new Set(
        Array.isArray(res?.deleted) && res.deleted.length
          ? res.deleted.map((row) => row.id)
          : [d.id]
      );
      wbState.objects = wbState.objects.filter((o) => !gone.has(o.id));
      wbScheduleRender();
    } catch (e) {
      console.error(e);
      wbUndoStack.pop();
    } finally {
      wbDeleting.delete(deletingKey);
    }
  }
  wbDeleteObjectRef = deleteObject;

  // Shared by both `objDrag` (bound to the whole `.wb-object`) and
  // `gripDrag` (bound only to `.wb-object-grip`, see below): `this` is
  // whichever element the gesture actually started on, so every DOM write
  // goes through `this.closest(".wb-object")` rather than `this` directly,
  // the same convention `resizeDrag`'s own "drag" handler already uses.
  function objDragStart(event, d) {
    if (window.currentTool === "eraser" || window.currentTool === "delete" || window.currentTool === "bucket") return;
    // A link tool on a text box starts a *link* from it, through the same
    // three handlers the cards use, see `wbLinkItem`.
    if (window.currentTool?.startsWith("link-")) { d._linkKind = "object"; return dragStart.call(this, event, d); }
    d._linkedSketches = wbLinkedSketchesFor(d.id, "object");
    // A map node's tree edges are not sketches (see `wbMapEdgesFor`), so the
    // line above finds none of them: collected here for the same reason and
    // at the same moment.
    d._mapEdges = wbMapEdgesFor(d.id);
    // `.raise()` deliberately does NOT happen here, moved to objDragMove.
    // See the matching comment on the card drag's own `dragging` for the
    // real bug this caused (raising mid-`start` breaks the browser's click
    // synthesis, so a plain click-to-select on an object never fired).
    // See the matching comment on the card drag's own `dragStart`: a raw,
    // never-snapped running position, so small per-frame deltas actually
    // accumulate instead of being rounded away against the previous
    // frame's already-snapped value.
    d._rawX = d.x;
    d._rawY = d.y;
    d._dragOriginX = d.x;
    d._dragOriginY = d.y;
    d._moveUndoBefore = WB_KIND_INFO.object.payload(d);
    // Bulk-move detection is deliberately deferred to the first real
    // "drag" frame below, not decided here, see the matching comment on
    // the sketch drag's own "start" for the click-toggle bug that caused.
  }
  function objDragMove(event, d) {
    if (window.currentTool === "eraser" || window.currentTool === "delete" || window.currentTool === "bucket") return;
    if (window.currentTool?.startsWith("link-")) return dragging.call(this, event, d);
    if (d._bulkOrigin === undefined) {
      //: **A map node drags its branch with it** (MINDMAP_PLAN.md §12.1 item
      //: 8). Decided on the first real drag frame, like the marquee case
      //: beside it and for the same reason (see the sketch drag's own "start"
      //: comment): deciding at `start` turns a click into a bulk move.
      //: Ctrl held means the topic travels alone, and is read here because
      //: that is the frame the decision is made in.
      d._dragAlone = Boolean(event.sourceEvent?.ctrlKey || event.sourceEvent?.metaKey);
      d._bulkOrigin = wbDragIsBulkMove("object", d.id)
        ? wbCaptureBulkMoveOrigin(wbMultiKey("object", d.id))
        : wbMapBranchDragOrigin(d, d._dragAlone);
    }
    d3.select(this.closest(".wb-object")).raise();
    // d3.drag's dx/dy are raw screen pixels, not board-space, the
    // resize handles below already divide by the zoom scale for exactly
    // this reason; a plain drag has to as well, or a card/object moves
    // faster than the cursor when zoomed out and slower when zoomed in.
    const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
    d._rawX = (d._rawX ?? d.x) + event.dx / transform.k;
    d._rawY = (d._rawY ?? d.y) + event.dy / transform.k;
    const bypassSnap = event.sourceEvent?.altKey;
    d.x = wbSnap(d._rawX, bypassSnap);
    d.y = wbSnap(d._rawY, bypassSnap);
    // Smart alignment guides: asked for directly ("draw.io and Microsoft
    // PowerPoint have... dotted alignment rule guides"). Same Alt bypass as
    // grid-snap just above: holding it means "no snap assistance at all
    // for this drag", one concept, not two separate modifier keys to learn.
    if (!bypassSnap && !d._bulkOrigin) {
      const { dx, dy, guideLines } = wbAlignmentGuides("object", d.id, d.x, d.y, d.width, d.height);
      d.x += dx;
      d.y += dy;
      wbShowAlignmentGuides(guideLines);
    } else {
      wbClearAlignmentGuides();
    }
    d3.select(this.closest(".wb-object")).style("transform", wbItemTransform(d));
    if (d._linkedSketches?.length) wbUpdateLinkedSketches(d.id, d._linkedSketches);
    if (d._mapEdges?.length) wbUpdateMapEdges(d._mapEdges);
    wbUpdateSelectionBar();
    if (d._bulkOrigin) wbApplyBulkMove(d._bulkOrigin, d.x - d._dragOriginX, d.y - d._dragOriginY);
    // The topic this branch would land on, lit as you pass over it. From the
    // pointer's own position rather than the node's, because what you aim at
    // is where you are pointing, not where the box has caught up to.
    const source = event.sourceEvent;
    if (source && wbIsMap() && WB_MAP_KINDS.has(d.kind)) {
      d._dropTarget = wbMapDropTargetAt(d, source.clientX, source.clientY);
      wbMapShowDropTarget(d._dropTarget?.id ?? null);
    }
  }
  async function objDragEnd(event, d) {
    if (window.currentTool === "eraser" || window.currentTool === "delete" || window.currentTool === "bucket") return;
    if (window.currentTool?.startsWith("link-")) { const r = dragEndNode.call(this, event, d); d._linkKind = null; return r; }
    d._linkedSketches = null;
    // Dropped: the paths this drag held references to are about to be
    // replaced by the next render, and a stale element would be updated in
    // place forever (invisibly, since it is no longer in the document).
    d._mapEdges = null;
    wbClearAlignmentGuides();
    const bulkOrigin = d._bulkOrigin;
    // Reset unconditionally: a solo drag sets this to `null` (see
    // "drag" above), and leaving it there would make the *next* gesture's
    // `=== undefined` check think bulk-move was already decided and skip
    // redetecting it, permanently treating this object as "never bulk"
    // even after it later joins a multi-selection.
    delete d._bulkOrigin;
    //: Dropped on another topic: that is a transplant, not a placement, and
    //: it replaces the ordinary save below entirely (`/move` is the only
    //: endpoint that may write `parent_id`, and it re-lays the branch after).
    const dropTarget = d._dropTarget;
    const alone = d._dragAlone;
    delete d._dropTarget;
    delete d._dragAlone;
    wbMapClearDropTarget();
    if (dropTarget) {
      delete d._moveUndoBefore;
      if (bulkOrigin) await wbSaveBulkMove(bulkOrigin);
      await wbMapTransplant(d, dropTarget.id, alone);
      return;
    }
    const moveBefore = d._moveUndoBefore;
    delete d._moveUndoBefore;
    //: **A click is not a drop, and must not save.** `objDrag` runs for a
    //: plain click too (d3-drag listens for `mousedown`, and a click is a
    //: mousedown with no movement), and this used to PUT the object every
    //: time regardless. On its own that is only a wasted request; the bug is
    //: that the PUT carries whatever `d.data` held when the gesture ended,
    //: and a click on a control *inside* the node (the chevron, the count
    //: badge, the two add buttons) fires its own save in the same tick. Two
    //: PUTs to one row with no defined order: measured on the fold chevron,
    //: one click sent `collapsed: null` and `collapsed: true` and the map
    //: kept whichever landed second, so a branch folded on screen and came
    //: back unfolded on the next refresh. Found by `mindmap.js`'s SVG export
    //: check, which counted two edges where the map had four.
    //:
    //: The same "did it really move" test the undo entry below already used,
    //: hoisted above the save so it governs both.
    const reallyMoved = !moveBefore || moveBefore.x !== d.x || moveBefore.y !== d.y;
    if (reallyMoved) await wbSaveObject(d);
    if (moveBefore && reallyMoved) {
      wbPushUndo({ action: "move", kind: "object", id: d.id, before: moveBefore });
      // A map node that was actually moved is now pinned, see
      // `wbMapPinOnDrag`. Gated on the same "did it really move" check the
      // undo entry uses, so a click is never mistaken for a placement.
      await wbMapPinOnDrag(d);
    }
    if (bulkOrigin) await wbSaveBulkMove(bulkOrigin);
  }

  const objDrag = d3.drag()
    // A resize handle owns its own drag (below); a text box's own text
    // needs plain clicks/selection to reach it, not a canvas-wide drag. And,
    // same reasoning as the card drag's own filter above: a brush tool must
    // be able to draw over an image/text object, not drag it. `.wb-object-grip`
    // has its own separate drag instance (`gripDrag`, below): excluded here
    // so a grip grab doesn't *also* start this instance for the same
    // gesture. A real bug caught live: excluding it here alone isn't enough
    //, `objDrag` is one shared behaviour object bound to both the object
    // and the grip, so its filter runs for *both* elements' own pointerdown,
    // and target-closest can't tell "the grip's own listener" from "the
    // object's listener catching a bubbled grip click" apart. `gripDrag`
    // below exists precisely because that distinction needs two behaviour
    // objects, not one filter.
    .filter((event) => {
      if (WB_BRUSH_TOOLS.has(window.currentTool) || window.currentTool === "lasso") return false;
      if (event.target.closest(
        ".wb-resize-handle, .wb-rotate-handle, .wb-object-grip, .wb-map-size-grip"
      )) return false;
      // `.wb-text-content` used to be excluded outright, which is what left a
      // text box draggable only by its grip, see `wbBeginTextEdit`. It only
      // needs to keep the pointer while it is *being edited*, for the caret
      // and for selecting words; the rest of the time it is just the face of
      // a box and drags like one.
      //
      // **Asked for by class, this missed the map node entirely.** Reported:
      // "I cant highlight text in mindmap text boxes." A map node's editor is
      // `.wb-map-text`, not `.wb-text-content`, so this filter let the drag
      // run: measured, a click-drag across a node being edited selected the
      // empty string and moved the node 165px instead. The node's own
      // `pointerdown` stopPropagation cannot help, d3-drag listens for
      // `mousedown`, and this file already records that two event families
      // cannot cancel each other (see the marquee's handle-layer comment).
      // Asking the *element* whether it is editable rather than naming the
      // classes that happen to be editable today is what stops the next
      // editable surface on the canvas from re-learning this.
      const text = event.target.closest("[contenteditable]");
      if (text && text.isContentEditable) return false;
      return true;
    })
    .on("start", objDragStart)
    .on("drag", objDragMove)
    .on("end", objDragEnd);

  // The grip's own drag instance (see the comment above), `stopPropagation`
  // on start is the same fix `resizeDrag`/`objectRotateDrag` already use to
  // keep their own handle grabs from also bubbling into the object's own
  // `objDrag` listener.
  const gripDrag = d3.drag()
    // The grip sits inside the box it moves, see `wbStableDragContainer`.
    .container(wbStableDragContainer(".wb-object"))
    .filter((event) => !WB_BRUSH_TOOLS.has(window.currentTool) && window.currentTool !== "lasso")
    .on("start", function (event, d) {
      event.sourceEvent.stopPropagation();
      objDragStart.call(this, event, d);
    })
    .on("drag", objDragMove)
    .on("end", objDragEnd);

  function resizeDrag(handle) {
    return d3.drag()
      // The handle sits inside the object it resizes, see
      // `wbStableDragContainer`. Matters for `w`/`n`, which move x/y too.
      .container(wbStableDragContainer(".wb-object"))
      .on("start", function (event, d) {
        event.sourceEvent.stopPropagation(); // don't also start objDrag
        d._resizeUndoBefore = WB_KIND_INFO.object.payload(d);
      })
      .on("drag", function (event, d) {
        const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
        const dx = event.dx / transform.k;
        const dy = event.dy / transform.k;
        let newWidth = d.width, newHeight = d.height;
        if (handle.includes("e")) newWidth = Math.max(WB_OBJECT_MIN_SIZE, d.width + dx);
        if (handle.includes("w")) newWidth = Math.max(WB_OBJECT_MIN_SIZE, d.width - dx);
        if (handle.includes("s")) newHeight = Math.max(WB_OBJECT_MIN_SIZE, d.height + dy);
        if (handle.includes("n")) newHeight = Math.max(WB_OBJECT_MIN_SIZE, d.height - dy);
        // Reported directly: shift while resizing didn't snap to a square, 
        // same fix as nodeResizeDrag's own copy just above.
        if (handle.length === 2 && event.sourceEvent.shiftKey) {
          newWidth = newHeight = Math.max(newWidth, newHeight);
        }
        if (handle.includes("w")) d.x += d.width - newWidth;
        if (handle.includes("n")) d.y += d.height - newHeight;
        d.width = newWidth;
        d.height = newHeight;
        const el = d3.select(this.closest(".wb-object"));
        el.style("width", `${d.width}px`)
          .style("height", `${d.height}px`)
          .style("transform", wbItemTransform(d));
      })
      .on("end", async (event, d) => {
        await wbSaveObject(d);
        const before = d._resizeUndoBefore;
        delete d._resizeUndoBefore;
        if (before) wbPushUndo({ action: "move", kind: "object", id: d.id, before });
      });
  }

  //: Same as `nodeRotateDrag` above: kept as two small copies rather than
  //: one shared function because they close over different elements/PUT
  //: helpers (`.node-card` vs `.wb-object`, `wbSaveNode` vs `wbSaveObject`),
  //: the same reasoning `nodeResizeDrag`'s own comment already gives for not
  //: sharing with `resizeDrag`.
  function objectRotateDrag() {
    return d3.drag()
      .on("start", (event, d) => {
        event.sourceEvent.stopPropagation();
        d._rotateUndoBefore = WB_KIND_INFO.object.payload(d);
      })
      .on("drag", (event, d) => {
        const el = document.querySelector(`.wb-object[data-id="${d.id}"]`);
        if (!el) return;
        const rect = el.getBoundingClientRect();
        d.rotation = wbAngleFromCenterDeg(
          rect.left + rect.width / 2, rect.top + rect.height / 2,
          event.sourceEvent.clientX, event.sourceEvent.clientY,
          event.sourceEvent.shiftKey
        );
        el.style.transform = wbItemTransform(d);
      })
      .on("end", async (event, d) => {
        await wbSaveObject(d);
        const before = d._rotateUndoBefore;
        delete d._rotateUndoBefore;
        if (before) wbPushUndo({ action: "move", kind: "object", id: d.id, before });
      });
  }

  // The map facts for this render pass, computed once here rather than per
  // node: `wbMapColors` walks the whole tree by design (see its own comment),
  // and calling it from inside a per-node callback would walk it once per node.
  const mapIndex = wbIsMap() ? wbMapIndex() : null;
  const mapColors = mapIndex ? wbMapNodeColors(mapIndex) : null;
  const mapHidden = mapIndex ? wbMapConcealed(mapIndex) : null;
  // The focus bar's counts, the legend's rows and the template offer all
  // describe the map this pass is about to draw (§5 items 18 to 21).
  wbSyncMapViews(mapIndex);
  // **A collapsed branch leaves the DOM rather than being hidden with CSS.**
  // The export, the board bounds, the marquee and every `querySelector` in
  // this file read the DOM, a `display: none` node would still be found by
  // all four, so a folded branch would keep showing up in exports and keep
  // stretching the board's bounds while being invisible on screen.
  const objectData = mapHidden?.size
    ? (wbState.objects || []).filter((o) => !mapHidden.has(o.id))
    : (wbState.objects || []);
  const objectSelection = canvas.selectAll(".wb-object")
    .data(objectData, (d) => d.id);

  // A map node is `height: auto`, its own text decides how tall it is, so a
  // long topic grows its box instead of being sliced by `overflow: hidden`,
  // which is the failure CLAUDE.md records costing six rounds on one popup.
  const objectHeight = (d) => (WB_MAP_KINDS.has(d.kind) ? "auto" : `${d.height}px`);

  const objectEnter = objectSelection.enter()
    .append("div")
    .attr("class", (d) => `wb-object wb-object-${d.kind}`)
    .attr("data-id", (d) => d.id)
    .style("transform", wbItemTransform)
    .style("width", (d) => `${d.width}px`)
    .style("height", objectHeight)
    .style("z-index", (d) => d.z)
    .call(objDrag)
    .on("click", (event, d) => {
      // ROADMAP row 0(b), asked for directly: with the Hand active, a plain
      // click on something switches to Select and selects it. A pan is a
      // drag; a click that moved nothing is a choice of *this*, and every
      // whiteboard app (Miro, FigJam, tldraw) reads it that way.
      if (window.currentTool === "select" || window.currentTool === "pan") {
        event.stopPropagation();
        if (window.currentTool === "pan") wbSelectToolRef?.("select");
        wbHandleItemClick("object", d.id, event);
        return;
      }
      if (window.currentTool === "delete" || window.currentTool === "eraser") deleteObject(d);
    })
    .on("pointerenter", (event, d) => {
      if (window.currentTool === "eraser" && wbErasing) deleteObject(d);
    });

  objectEnter.each(function (d) {
    const el = d3.select(this);
    if (d.kind === "image") {
      // Asked for directly: an image deleted out from under a board (via
      // the Library gallery's own delete, or by hand off disk) left a
      // plain broken-image glyph: "there should probably be a placeholder
      // or closable box that says it is deleted in its place." The close
      // button removes the object outright rather than leaving a
      // permanently-broken box on the board.
      el.append("img").attr("src", mediaSrc(d.data.url) || "").attr("alt", "")
        .on("error", function () {
          d3.select(this).remove();
          if (el.select(".wb-object-deleted").empty()) {
            const placeholder = el.append("div").attr("class", "wb-object-deleted");
            placeholder.append("span").text("Image deleted");
            placeholder.append("button")
              .attr("type", "button")
              .attr("class", "ghost small icon-button")
              .attr("title", "Remove this")
              .text("✕")
              .on("click", (event) => { event.stopPropagation(); deleteObject(d); });
          }
        });
    } else if (WB_MAP_KINDS.has(d.kind)) {
      // A map node, not a text box. Checked before the `else` below because
      // that branch is "everything that isn't an image", which is what drew a
      // topic as a bare, unlabelled text box for as long as the kinds existed
      // without this: stored, served, and on screen as nothing recognisable.
      wbBuildMapNode(el, d);
    } else {
      // Fill/border, asked for directly (the properties panel): set on the
      // outer object div, which is what `.wb-object-text`'s own default
      // background/border style, so an unset value falls back to the CSS
      // default rather than an empty override.
      el.style("background", d.data.bg || "").style("border-color", d.data.border_color || "");
      // Asked for directly ("objects are also difficult and annoying to
      // move around"): `.wb-text-content` fills the entire box and both
      // the filter above and its own pointerdown handler below correctly
      // keep drag away from it while typing, which meant the *only*
      // draggable surface left was the ~0.5rem padding strip around the
      // text, the same width as the resize handles that sit right on top
      // of it. A dedicated grip, same convention as the panels' own
      // `.wb-panel-grip`, gives a guaranteed, adequately-sized place to
      // grab regardless of how much text is in the box. Text objects only: 
      // an image has no competing contenteditable claim on its body, so it
      // was already fully draggable once the resize-handle bug above was
      // fixed.
      el.append("div")
        .attr("class", "wb-object-grip")
        .attr("title", "Drag to move")
        .text("⠿")
        .call(gripDrag);
      const content = el.append("div")
        .attr("class", "wb-text-content")
        // Not editable until asked, see `wbBeginTextEdit` for why.
        .attr("contenteditable", "false")
        .style("color", d.data.color || "")
        .style("font-size", d.data.font_size ? `${d.data.font_size}px` : "")
        .text(d.data.content || "");
      // Saved on blur, not on every keystroke, a PUT per character would
      // flood the server and make undo/redo of everything *else* land
      // between two half-typed states.
      content.on("blur", function () {
        wbEndTextEdit(this);
        d.data = { ...d.data, content: this.textContent };
        wbSaveObject(d);
      });
      // Typing is text-box business, not the canvas's: Delete/Backspace
      // here must edit the text, not delete the whole box the way the same
      // keys do when an object is merely *selected*. Both of these are gated
      // on actually being in edit mode now: a box that is not being edited
      // has to let the pointer through to the object's own drag, and its
      // Delete key belongs to the canvas again.
      content.on("keydown", function (event) {
        if (this.isContentEditable) event.stopPropagation();
      });
      content.on("pointerdown", function (event) {
        if (this.isContentEditable) event.stopPropagation();
      });
      content.on("dblclick", function (event) {
        event.stopPropagation();
        wbBeginTextEdit(this);
      });
    }
    // A map node gets neither. Its height is its text's (see `objectHeight`),
    // so a vertical resize handle would fight the content and lose; and a
    // rotated node is a node whose edges no longer meet its anchors, which
    // makes the tree unreadable for no gain a mind-mapper has ever asked for.
    // The eight handles and the rotate grip also sit exactly where the
    // chevron and the `+` do, and would swallow both.
    if (WB_MAP_KINDS.has(d.kind)) return;
    for (const handle of ["nw", "n", "ne", "e", "se", "s", "sw", "w"]) {
      el.append("div")
        .attr("class", "wb-resize-handle")
        .attr("data-handle", handle)
        .call(resizeDrag(handle));
    }
    el.append("div")
      .attr("class", "wb-rotate-handle")
      .attr("title", "Drag to rotate: hold Shift to snap to 15°")
      .call(objectRotateDrag());
  });

  wbWireContextMenu(objectEnter, "object");

  const objectUpdate = objectEnter.merge(objectSelection);
  objectUpdate
    .style("transform", wbItemTransform)
    .style("width", (d) => `${d.width}px`)
    .style("height", objectHeight)
    .style("z-index", (d) => d.z);
  // An image's own src can change (rare: nothing in this UI replaces one
  // yet, but a future paste-to-replace shouldn't need this rewritten) and a
  // text box's saved colour/size might have changed elsewhere (undo/redo);
  // the text itself is deliberately left alone here so a re-render mid-edit
  // (another item moving, say) can't overwrite what's being typed.
  objectUpdate.each(function (d) {
    const el = d3.select(this);
    if (d.kind === "image") {
      el.select("img").attr("src", mediaSrc(d.data.url) || "");
    } else if (WB_MAP_KINDS.has(d.kind)) {
      wbPaintMapNode(el, d, mapIndex, mapColors);
      // The stored `height` is what the bounds, the alignment guides and the
      // tidy layout all read, and a map node's real height is whatever its
      // text needed. Syncing it here (locally: no PUT, nothing to save) is
      // what keeps those three agreeing with what is actually on screen; the
      // value rides along to the server on the node's next real save.
      if (this.offsetHeight) d.height = this.offsetHeight;
    } else {
      el.style("background", d.data.bg || "").style("border-color", d.data.border_color || "");
      const textEl = el.select(".wb-text-content");
      textEl.style("color", d.data.color || "")
        .style("font-size", d.data.font_size ? `${d.data.font_size}px` : "")
        .style("text-align", d.data.align || "");
      if (document.activeElement !== textEl.node()) wbPaintTextContent(textEl.node(), d);
    }
  });

  objectSelection.exit().remove();
}

//: The sketches touching `nodeId`, pre-parsed once. `wbUpdateLinkedSketches`
//: used to do this same JSON.parse-and-scan of *every* sketch on the board on
//: every single mousemove frame of a card drag, a board with a few hundred
//: sketches (strokes plus link lines) turns a drag into dozens of full-board
//: parses a second, visible as stutter on a busy board. `dragStart` below
//: builds this list once per drag instead; a card gains or loses a link only
//: between drags, never mid-drag, so it doesn't need to be live.
function wbLinkedSketchesFor(nodeId, kind = "node") {
  const found = [];
  for (const sketch of wbState.sketches) {
    let parsed;
    try {
      parsed = JSON.parse(sketch.data);
    } catch {
      continue;
    }
    if (!parsed.type || !parsed.type.startsWith("link-")) continue;
    const atSource = parsed.sourceId === nodeId && (parsed.sourceKind || "node") === kind;
    const atTarget = parsed.targetId === nodeId && (parsed.targetKind || "node") === kind;
    if (!atSource && !atTarget) continue;
    found.push({ sketch, parsed });
  }
  return found;
}

//: Recomputes just the link-sketch paths touching `nodeId`, without a full
//: `wbScheduleRender()`, reported directly as "resizing and drawing shapes
//: is glitchy and slow to update". `dragging` below used to call the full
//: render on every single mousemove frame of a card drag, purely to keep a
//: link line's endpoint following the card, which re-binds *every* card,
//: sketch and object on the board, dozens of times a second, for one card's
//: own link. Mirrors the link-path maths in `renderWhiteboard`'s own
//: `sketchUpdate.each` exactly, so the two can't drift apart.
//: `precomputed`, when given, skips the board-wide scan, see
//: `wbLinkedSketchesFor`'s own comment for why `dragging` always passes one.
function wbUpdateLinkedSketches(nodeId, precomputed) {
  const pairs = precomputed || wbLinkedSketchesFor(nodeId);
  for (const { sketch, parsed } of pairs) {
    const endpoints = wbResolveLinkEndpoints(parsed);
    if (!endpoints) continue;
    const pathData = wbLinkPathD(parsed.type, endpoints.source, endpoints.target, wbLinkCaps(parsed), parsed.width, parsed.bend);
    const el = document.querySelector(`.sketch-group[data-id="${sketch.id}"]`);
    el?.querySelector(".sketch-path")?.setAttribute("d", pathData);
    el?.querySelector(".sketch-hitbox")?.setAttribute("d", pathData);
  }
}

function dragStart(event, d) {
  // Eraser/delete don't move cards: a swipe meant to erase a run of cards
  // must not also drag the first one it touches out from under the pointer.
  if (window.currentTool === "eraser" || window.currentTool === "delete" || window.currentTool === "bucket") return;
  if (window.currentTool && window.currentTool.startsWith("link-")) {
    // Real anchors: snap the link's own start to whichever of the source
    // card's 8 fixed points the drag actually began near, so a link from a
    // specific corner stays pinned there through a later resize, `null`
    // (nothing near enough) is the free/floating case, resolved fresh every
    // render in `wbLinkEndpoints` instead of frozen at drag-start.
    const startTransform = d3.zoomTransform(document.getElementById("whiteboard-container"));
    const startRect = document.getElementById("wb-svg-layer").getBoundingClientRect();
    const startX = (event.sourceEvent.clientX - startRect.left - startTransform.x) / startTransform.k;
    const startY = (event.sourceEvent.clientY - startRect.top - startTransform.y) / startTransform.k;
    d.linkSourceAnchor = wbNearestAnchor(d._linkKind || "node", d, startX, startY);
    wbLinkDragActive = true;
    wbShowAnchorHints(d._linkKind || "node", d, d.linkSourceAnchor);
    d.linkingPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    d.linkingPath.setAttribute("fill", "none");
    d.linkingPath.setAttribute("stroke", window.currentStrokeColor || "#ffffff");
    d.linkingPath.setAttribute("stroke-width", "3");
    document.getElementById("wb-zoom-group").appendChild(d.linkingPath);
  } else {
    // `.raise()` deliberately does NOT happen here, see the matching
    // comment in `dragging` below for a real bug this caused.
    // Reported directly: "hard to move notes diagonally when on grid lock".
    // `dragging` below used to re-snap the *already-snapped* `d.x`/`d.y`
    // every frame: each small per-frame delta got rounded straight back to
    // the same grid line it started from, discarding the sub-grid remainder
    // instead of carrying it forward, so many frames of real motion could
    // add up to nothing until one single frame happened to cross a whole
    // grid step by itself. A raw (never-snapped) running position, seeded
    // here and only read through `wbSnap` when applying/saving, fixes it:
    // every pixel of real cursor motion accumulates, and only the *display*
    // rounds to the grid.
    d._rawX = d.x;
    d._rawY = d.y;
    d._dragOriginX = d.x;
    d._dragOriginY = d.y;
    // See wbLinkedSketchesFor's own comment: parsed once here rather than on
    // every frame of the drag that's about to start.
    d._linkedSketches = wbLinkedSketchesFor(d.id);
    // Asked for directly: undo should cover a move, not only create/delete.
    // Snapshotted before anything below can mutate `d`.
    d._moveUndoBefore = WB_KIND_INFO.node.payload(d);
    // Bulk-move detection is deliberately deferred to the first real
    // "drag" frame below, not decided here, see the matching comment on
    // the sketch drag's own "start" for the click-toggle bug that caused.
  }
}

function dragging(event, d) {
  if (window.currentTool === "eraser" || window.currentTool === "delete" || window.currentTool === "bucket") return;
  if (window.currentTool && window.currentTool.startsWith("link-")) {
    const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
    const rect = document.getElementById("wb-svg-layer").getBoundingClientRect();
    const mx = (event.sourceEvent.clientX - rect.left - transform.x) / transform.k;
    const my = (event.sourceEvent.clientY - rect.top - transform.y) / transform.k;

    // A fixed source anchor stays put; a floating one re-aims at the live
    // pointer every frame: the same rectangle-intersection the render path
    // uses, not the old fixed centre-point.
    const fixedStart = wbAnchorPoint(d._linkKind || "node", d, d.linkSourceAnchor);
    const start = fixedStart || wbEdgePoint(d._linkKind || "node", d, mx, my);
    d.linkingPath.setAttribute("d", wbLinkPathD(window.currentTool, start, { x: mx, y: my }));

    // Anchor hints follow whichever card, text box, sticky or shape the
    // pointer is over, so the drop target's own snap points are visible
    // before release.
    const hover = wbLinkCandidateAt(mx, my, d._linkKind || "node", d.id);
    if (hover) wbShowAnchorHints(hover[0], hover[1], wbNearestAnchor(hover[0], hover[1], mx, my));
    else wbShowAnchorHints(d._linkKind || "node", d, d.linkSourceAnchor);
  } else {
    // Pre-existing gap, not introduced this session, caught while adding
    // snap-to-grid here: event.dx/dy are raw screen pixels, the
    // link-drawing branch just above already divides by the zoom scale for
    // the same reason. Without it, a card dragged while zoomed moved faster
    // than the cursor when zoomed out and slower when zoomed in, and snap
    // would round a wrongly-scaled delta.
    if (d._bulkOrigin === undefined) {
      d._bulkOrigin = wbDragIsBulkMove("node", d.id)
        ? wbCaptureBulkMoveOrigin(wbMultiKey("node", d.id))
        : null;
    }
    // Real bug, found live while testing click-to-select on a card: this
    // used to run in `dragStart`, unconditionally, on *every* pointerdown, 
    // including a plain click with zero movement. `.raise()` reappends the
    // node as its parent's last child (for z-order while actively
    // dragging), and doing that mid-gesture is enough to make the browser
    // never synthesize the following "click" event at all: confirmed by
    // instrumenting both the card's own click handler and the container's
    // "empty canvas" one and seeing *neither* fire, while an ordinary
    // sketch (whose own drag "start" never calls `.raise()`) selected
    // correctly the same way. Moved here, into `dragging`, which: unlike
    // `dragStart`, only ever runs after real movement has already
    // happened, so a plain click's click event is never touched.
    d3.select(this).raise();
    const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
    d._rawX = (d._rawX ?? d.x) + event.dx / transform.k;
    d._rawY = (d._rawY ?? d.y) + event.dy / transform.k;
    // Asked for directly: Alt held during a drag temporarily releases the
    // grid lock, the same convention Figma/Illustrator use, a per-call
    // bypass rather than touching the snap toggle itself.
    const bypassSnap = event.sourceEvent?.altKey;
    d.x = wbSnap(d._rawX, bypassSnap);
    d.y = wbSnap(d._rawY, bypassSnap);
    // Smart alignment guides: asked for directly ("draw.io and Microsoft
    // PowerPoint have... dotted alignment rule guides"). Same Alt bypass as
    // grid-snap just above: one modifier, "no snap assistance", not two.
    if (!bypassSnap && !d._bulkOrigin) {
      const w = d.width || WB_CARD_DEFAULT_SIZE.w, h = d.height || WB_CARD_DEFAULT_SIZE.h;
      const { dx, dy, guideLines } = wbAlignmentGuides("node", d.id, d.x, d.y, w, h);
      d.x += dx;
      d.y += dy;
      wbShowAlignmentGuides(guideLines);
    } else {
      wbClearAlignmentGuides();
    }
    d3.select(this).style("transform", wbItemTransform(d));
    wbUpdateSelectionBar();
    // Update this card's own link lines directly rather than a full
    // wbScheduleRender(), see wbUpdateLinkedSketches's own comment for why
    // that was the "glitchy and slow to update" report.
    wbUpdateLinkedSketches(d.id, d._linkedSketches);
    if (d._bulkOrigin) wbApplyBulkMove(d._bulkOrigin, d.x - d._dragOriginX, d.y - d._dragOriginY);
  }
}

async function dragEndNode(event, d) {
  if (window.currentTool && window.currentTool.startsWith("link-")) {
    if (d.linkingPath) d.linkingPath.remove();
    d.linkingPath = null;
    wbLinkDragActive = false;
    wbClearAnchorHints();

    const transform = d3.zoomTransform(document.getElementById("whiteboard-container"));
    const rect = document.getElementById("wb-svg-layer").getBoundingClientRect();
    const mx = (event.sourceEvent.clientX - rect.left - transform.x) / transform.k;
    const my = (event.sourceEvent.clientY - rect.top - transform.y) / transform.k;

    const sourceKind = d._linkKind || "node";
    const hit = wbLinkCandidateAt(mx, my, sourceKind, d.id);
    const targetNode = hit ? hit[1] : null;
    const targetKind = hit ? hit[0] : "node";

    if (targetNode) {
       // The release point's own nearest anchor on the target, same as the
       // source got at drag-start, `null` (nothing near enough) persists
       // as a free/floating end, same as the source's own case.
       const targetAnchor = wbNearestAnchor(targetKind, targetNode, mx, my);
       const sketchData = {
         data: JSON.stringify({
            type: window.currentTool,
            sourceId: d.id,
            targetId: targetNode.id,
            sourceKind: sourceKind === "node" ? undefined : sourceKind,
            targetKind: targetKind === "node" ? undefined : targetKind,
            color: window.currentStrokeColor || "#ffffff",
            sourceAnchor: d.linkSourceAnchor || undefined,
            targetAnchor: targetAnchor || undefined,
         }),
         x: 0, y: 0, z: 1,
         board_id: window.currentBoardId
       };
       try {
         const res = await apiJson("/whiteboard/sketches", { method: "POST", body: JSON.stringify(sketchData) });
         wbState.sketches.push(res);
         wbPushUndo({ action: "create", kind: "sketch", id: res.id });
         wbScheduleRender();
       } catch (err) {
         console.error(err);
       }
    }
    d.linkSourceAnchor = null;
  } else {
    wbClearAlignmentGuides();
    // Sync back to API.
    //
    // `board_id` has to go with it. The server takes the whole node on a PUT,
    // so omitting it read as "move this to the global board", dragging a card
    // on a named board silently moved it off that board.
    //
    // And a 404 here is recoverable rather than fatal: it means this client's
    // copy of the board is stale (the note was purged, or the board was
    // rebuilt). Refetching puts the screen back in step; leaving it, as this
    // did, shows a card sitting where you dropped it that is not saved
    // anywhere: the worst of both answers.
    await wbSaveNode(d);
    // The directly-dragged item's own move-undo. A bulk drag's *other*
    // members don't get one each, undo after a group move puts back only
    // the card actually dragged, not the whole group; a real limitation,
    // not attempted further this session.
    const moveBefore = d._moveUndoBefore;
    delete d._moveUndoBefore;
    if (moveBefore && (moveBefore.x !== d.x || moveBefore.y !== d.y)) {
      wbPushUndo({ action: "move", kind: "node", id: d.id, before: moveBefore });
    }
    // Reset unconditionally, even when this gesture wasn't a bulk move, 
    // see the matching comment in objDrag's own "end" for why leaving a
    // solo drag's `null` in place would break bulk-move detection later.
    const bulkOrigin = d._bulkOrigin;
    delete d._bulkOrigin;
    if (bulkOrigin) await wbSaveBulkMove(bulkOrigin);
  }
}

// The Whiteboards sub-tab's own two controls. This DOMContentLoaded
// listener used to also hold the #library-subtabs switcher and the
// Documents/Media sub-tabs' refresh/search/upload wiring: none of that is
// whiteboard's own code (it switches between and wires OTHER Library
// sub-tabs), and it has moved to library.js, which is the Library's actual
// home now (ROADMAP.md §88.3 flagged this as "an accident worth fixing
// while splitting"). Only these two survive here, unchanged.
document.addEventListener("DOMContentLoaded", () => {
  $("wb-boards-new")?.addEventListener("click", async () => {
    wbShowCanvasView();
    await createNewBoard();
  });
  // The same dialog, opened with the Mind map segment already chosen, not a
  // second creation path with its own copy of the create-and-open sequence.
  $("wb-boards-new-map")?.addEventListener("click", async () => {
    wbShowCanvasView();
    await createNewBoard("map");
  });
  //: Import (§5 item 17). The button opens the hidden input, the input does
  //: the work: the app's own file-picking pattern (`pickJsonFile`,
  //: `importMarkdown`), so a file arrives the same way here as everywhere
  //: else. Wired on the input's `change` rather than assigned as `onchange`
  //: inside the click handler, because a second click would then rebind it and
  //: `tests/test_frontend_handlers.py` exists to catch exactly that shape.
  //: The third way to start a map, beside New mind map and Import outline
  //: (§5 item 15). In the same row because it is the same kind of action:
  //: "start a map", from notes that already exist rather than from an empty
  //: canvas or from a file.
  $("wb-boards-generate")?.addEventListener("click", wbGenerateMapFromNotes);
  $("wb-boards-import")?.addEventListener("click", () => {
    $("wb-import-map-file")?.click();
  });
  $("wb-import-map-file")?.addEventListener("change", wbImportOutlineFile);
  $("wb-back-to-boards")?.addEventListener("click", wbShowBoardsLanding);
  $("library-boards-search")?.addEventListener("input", renderLibraryBoardsGallery);
  // The Reload button beside "+ New board", now named after what it reloads.
  // It was `library-media-refresh`, a copy-paste leftover from the Media
  // sub-tab, and that name is why it sat unwired for so long: searching the id
  // found a listener that a reader assumed was this button's. Checked before
  // renaming rather than after: the id appears exactly once in index.html and
  // exactly once in the JS, here, and `library.js` does not mention it at all,
  // so the comment this replaces was itself out of date about the Media
  // sub-tab wiring it. `library-boards-refresh` matches the
  // `#library-boards-search` beside it.
  //
  // Its title and aria-label said only "Reload", which on a header holding
  // New board, Import outline and Help does not say reload what.
  $("library-boards-refresh")?.addEventListener("click", renderLibraryBoardsGallery);
});

// The Whiteboards tab has two views sharing one subtab: a boards gallery
// (the landing view) and the actual canvas, asked for directly, replacing
// two separate doors onto the whiteboard (a bare canvas tab defaulting to
// whatever board was last open, plus a picker tab) with one. Canvas init
// is lazy and idempotent (`wbInitialized` guards it), so switching between
// the two views repeatedly costs nothing after the first time.
function wbShowCanvasView() {
  $("wb-boards-landing")?.classList.add("hidden");
  $("wb-canvas-view")?.classList.remove("hidden");
  setTimeout(initWhiteboard, 50);
}

function wbShowBoardsLanding() {
  // First, because the boards list lives inside the element full screen
  // pins to the viewport, see `wbLeaveFullscreen` for what that looked
  // like when it was left on.
  wbLeaveFullscreen();
  $("wb-canvas-view")?.classList.add("hidden");
  $("wb-boards-landing")?.classList.remove("hidden");
  renderLibraryBoardsGallery();
}

//: Sorting for the Whiteboards sub-tab, the fifth and last list to get it
//: ("the library subtabs are missing sorting and filtering options").
//:
//: `BoardOut` (routes_whiteboard.py) carries no timestamps at all, so there is
//: no honest "newest first" here: a board's `id` is the only thing that
//: orders by age, and it does, because a board *is* an Entry and entry ids
//: rise with creation. Named "Newest first" rather than "Highest id" because
//: that is what it means to the person reading it.
//:
//: The default board (`id === null`) is pinned first under every sort. It is
//: the one board that always exists and cannot be renamed or deleted, the
//: gallery already treats it as a fixed landmark (no tick, no ⋯ menu), and a
//: sort that shuffled it into the middle of the list would take that away.
const BOARD_SORTS = {
  newest: (a, b) => (b.id || 0) - (a.id || 0),
  oldest: (a, b) => (a.id || 0) - (b.id || 0),
  az: (a, b) => String(a.title || "").localeCompare(String(b.title || ""), undefined, { sensitivity: "base" }),
  za: (a, b) => String(b.title || "").localeCompare(String(a.title || ""), undefined, { sensitivity: "base" }),
  fullest: (a, b) => boardItemCount(b) - boardItemCount(a),
};

const BOARD_SORT_KEY = "library-boards-sort";

function boardItemCount(board) {
  return (board.node_count || 0) + (board.sketch_count || 0) + (board.object_count || 0);
}

function boardSort() {
  const stored = localStorage.getItem(BOARD_SORT_KEY);
  return BOARD_SORTS[stored] ? stored : "newest";
}

//: On `window` because `syncLibraryBoardsTicks` (library.js) rebuilds this
//: same list to line the *n*th checkbox up with the *n*th card. Its own
//: comment says it must apply "the exact same filter"; a sort is now part of
//: that, and a second copy of this function would tick the wrong boards the
//: first time the two drifted.
window.wbVisibleBoards = function wbVisibleBoards(boards, needle) {
  const shown = needle
    ? boards.filter((b) => String(b.title || "").toLowerCase().includes(needle))
    : [...boards];
  shown.sort(BOARD_SORTS[boardSort()]);
  const fixed = shown.filter((b) => b.id === null);
  return fixed.length ? [...fixed, ...shown.filter((b) => b.id !== null)] : shown;
};

document.addEventListener("DOMContentLoaded", () => {
  const select = $("library-boards-sort");
  if (!select) return;
  select.value = boardSort();
  select.addEventListener("change", () => {
    localStorage.setItem(BOARD_SORT_KEY, select.value);
    renderLibraryBoardsGallery();
  });
});

window.renderLibraryBoardsGallery = renderLibraryBoardsGallery;

//: Maps / Boards / All (MINDMAP_PLAN.md §5 item 10). Which one is showing.
//: In `localStorage` for the same reason the view mode and the sort already
//: are: a filter you have to set again on every visit is one you stop using.
const BOARD_FILTER_KEY = "library-boards-filter";
const BOARD_FILTERS = [
  { key: "all", label: "All", icon: "ph:squares-four", type: null },
  { key: "map", label: "Maps", icon: "ph:tree-structure", type: "map" },
  { key: "board", label: "Boards", icon: "ph:pencil-simple-line", type: "board" },
];

function boardTypeFilter() {
  const stored = localStorage.getItem(BOARD_FILTER_KEY);
  return BOARD_FILTERS.some((f) => f.key === stored) ? stored : "all";
}

//: The chip row itself. `.library-chip`, the app's own filter-chip recipe,
//: with the count on the chip, the Everything sub-tab's rule and for the same
//: reason: a filter you have to press to discover is empty wastes a click
//: every time, and with three of them that is the whole row.
function renderBoardTypeFilter(counts) {
  const box = $("library-boards-filter");
  if (!box) return;
  const active = boardTypeFilter();
  box.replaceChildren();
  for (const filter of BOARD_FILTERS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `library-chip${filter.key === active ? " active" : ""}`;
    button.dataset.boardFilter = filter.key;
    button.setAttribute("aria-pressed", String(filter.key === active));
    const icon = document.createElement("span");
    setLabel(icon, filter.icon);
    icon.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = filter.label;
    button.append(icon, label);
    if (counts) {
      const badge = document.createElement("span");
      badge.className = "library-chip-count";
      badge.textContent = String(counts[filter.key] ?? 0);
      button.appendChild(badge);
    }
    button.addEventListener("click", () => {
      localStorage.setItem(BOARD_FILTER_KEY, filter.key);
      renderLibraryBoardsGallery();
    });
    box.appendChild(button);
  }
}

async function renderLibraryBoardsGallery() {
  const grid = $("library-boards-grid");
  const empty = $("library-boards-empty");
  const noMatch = $("library-boards-no-match");
  if (!grid) return;
  // Always the unfiltered list, then narrowed here. `?type=` exists and works
  // (§9.3), but the chips carry counts, and counts for the two kinds you are
  // *not* looking at cannot come from a request that excluded them, asking
  // three times to draw one row would be three round trips for one small
  // array. The server-side filter earns its place for a caller that wants only
  // maps and no counts; this one wants both.
  // And to the end, for the same reason `refreshBoardList` reads it that way:
  // the chips below count what came back, so a first page would make the
  // counts a count of the first page.
  const boards = await apiPagedList("/whiteboard/boards", 200, { silent: true }).catch(() => null);
  if (!boards) { grid.replaceChildren(); empty?.classList.remove("hidden"); noMatch?.classList.add("hidden"); return; }
  // See `createNewBoard`'s own comment: a board with nothing on it yet
  // doesn't come back from the server at all.
  const created = window.wbLastCreatedBoard;
  if (created && !boards.some((b) => b.id === created.id)) {
    boards.push({ ...created, node_count: 0, sketch_count: 0, object_count: 0 });
  }
  // Counted before the filter, so each chip says how many it *would* show.
  const counts = { all: boards.length, map: 0, board: 0 };
  for (const b of boards) counts[b.type === "map" ? "map" : "board"] += 1;
  renderBoardTypeFilter(counts);
  const wanted = BOARD_FILTERS.find((f) => f.key === boardTypeFilter())?.type ?? null;
  const inScope = wanted ? boards.filter((b) => (b.type || "board") === wanted) : boards;
  const needle = ($("library-boards-search")?.value || "").trim().toLowerCase();
  const shown = window.wbVisibleBoards(inScope, needle);
  //: `.library-list` is the Library's own rows mode (00-tokens-shell.css) and
  //: a board card is already a `.library-card`, so this is the whole change:
  //: the same class the All sub-tab toggles, driven by the same preference.
  const rowsMode = localStorage.getItem("libraryView") === "list";
  grid.classList.toggle("library-list", rowsMode);
  grid.replaceChildren();
  if (!shown.length) {
    const isFilteredEmpty = Boolean(needle) && boards.length > 0;
    empty?.classList.toggle("hidden", isFilteredEmpty);
    noMatch?.classList.toggle("hidden", !isFilteredEmpty);
    if (noMatch && isFilteredEmpty) {
      noMatch.textContent = `No boards match “${needle}”.`;
    }
    return;
  }
  empty?.classList.add("hidden");
  noMatch?.classList.add("hidden");
  for (const board of shown) {
    // An `<article>` with role="button", the same shape libraryCard() and
    // the Documents subtab's doc-list-item use: a plain <button> can't
    // also host the kebab menu's own <button>, and reported live: "can't
    // rename or delete a board from the Whiteboards subtab", the exact gap
    // that shape already closed for documents.
    const card = document.createElement("article");
    card.className = "library-card library-board-card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    const open = () => openWhiteboardBoard(board.id);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (event.target !== card) return; // a key pressed inside the menu is its own
      event.preventDefault();
      open();
    });

    const top = document.createElement("div");
    top.className = "library-card-top";
    const icon = document.createElement("span");
    icon.className = "library-card-icon";
    // A map and a board share this sub-tab, so the icon is the one thing on
    // the card that says which of the two you are looking at before you read
    // the title: the same icon the top bar's Map chip and the New mind map
    // action use, so the three agree.
    const isMapCard = board.type === "map";
    setLabel(icon, isMapCard ? "ph:tree-structure" : "ph:squares-four");
    icon.setAttribute("aria-hidden", "true");
    top.appendChild(icon);

    const title = document.createElement("strong");
    title.className = "library-card-title";
    title.textContent = board.title;

    const meta = document.createElement("span");
    meta.className = "muted library-card-meta";
    // One sentence about how much is on a board, shared with every other
    // surface that says it, `mapCountLabel` in app.js. It used to be nine
    // lines here and four in the dashboard's own widget, which is how the two
    // came to disagree about what to call a map's objects.
    meta.textContent = mapCountLabel(board);

    // **A thumbnail of the board itself**, rather than the same icon on every
    // card. Asked for directly: the Boards & maps sub-tab is "boring and
    // should probably have previews".
    //
    // `mapPreview` (app.js) is now the only place this picture is drawn.
    // MINDMAP_PLAN.md §5 item 12 asked for exactly one preview renderer, and
    // the reason was already visible here: this card drew the tree edges, the
    // labels and the sketch squiggles, while the dashboard's boards widget
    // drew the same `preview_items` with none of them, so the one fact that
    // tells a map from a board was missing from one of the two places a map
    // shows up. An empty board still draws nothing and keeps its "Empty
    // board" line, which says more than a blank rectangle would.
    //: Every board gets one, including an empty one: `mapPreview` draws the
    //: designed empty state itself now. This used to be a three-way branch,
    //: with a hand-made dashed `<span>` for rows mode only, because the rows
    //: whose board had a preview pushed their title 34px right of the rows
    //: whose board did not (measured: 107px, 155px and 189px on three
    //: consecutive rows). One picture per board, one left edge.
    const minimap = mapPreview(board, { size: "card" });
    card.append(top, title, minimap, meta);

    // The default (id === null) scratch board isn't a note and can't be
    // renamed or deleted the way a real board (a plain Entry: see
    // create_board in routes_whiteboard.py) can.
    if (board.id !== null) {
      const menu = kebabMenu(
        [
          makeMenuItem("ph:pencil-simple Rename", "Rename this board", async () => {
            const next = await promptDialog("Rename this board:", board.title);
            if (!next) return;
            await apiJson(`/whiteboard/boards/${board.id}`, {
              method: "PUT",
              body: JSON.stringify({ title: next }),
            }).catch((e) => toast(e.message, true));
            renderLibraryBoardsGallery();
          }),
          // ROADMAP.md item 8: creating, listing and renaming a map all
          // worked; duplicating did not exist, and it is the one that makes a
          // map reusable: a laid-out map is a template for the next one.
          // The copy is deep server-side (its cards are new notes), so
          // editing it cannot rewrite the original's.
          makeMenuItem("ph:copy Duplicate", "Make a copy of this board", async () => {
            try {
              const copy = await apiJson(`/whiteboard/boards/${board.id}/duplicate`, {
                method: "POST",
              });
              renderLibraryBoardsGallery();
              toast(`Copied to “${copy.title}”`);
            } catch (e) {
              toast(e.message, true);
            }
          }),
          makeMenuItem("ph:trash Delete", "Delete this board", async () => {
            if (!(await confirmDialog(`Delete "${board.title}"? This cannot be undone.`))) return;
            await apiJson(`/entries/${board.id}`, { method: "DELETE" }).catch((e) => toast(e.message, true));
            renderLibraryBoardsGallery();
          }),
        ],
        `Actions for "${board.title}"`
      );
      menu.classList.add("library-card-menu");
      menu.addEventListener("click", (event) => event.stopPropagation());
      card.appendChild(menu);
    }

    grid.appendChild(card);
  }
}

//: Leaving the canvas has to leave full screen with it.
//:
//: Reported: "if i am still in whiteboard fullscreen and press the back to
//: boards button, the ui is broken." It was: `wb-fullscreen` pins
//: `#library-view-whiteboard` to `position: fixed; inset: 0` at z-index
//: 1000, and the *boards list* lives inside that same element, so going
//: back left the list covering the entire window, over the app header, the
//: Library sub-tabs and everything else, with no visible way out because the
//: control that turns it off is on the canvas you just left.
//:
//: Called from every exit rather than only from the back button: the board
//: picker, a board card and the Library sub-tabs can all take you off the
//: canvas too, and each would have had the same bug.
function wbLeaveFullscreen() {
  document.getElementById("library-view-whiteboard")?.classList.remove("wb-fullscreen");
  const button = document.getElementById("wb-fullscreen");
  if (button) {
    button.classList.remove("is-on");
    button.title = "Full screen (Esc to leave)";
    const icon = button.querySelector("i");
    if (icon) icon.className = "ph ph-arrows-out";
  }
}

// Jump to the real whiteboard canvas with a specific board loaded.
async function openWhiteboardBoard(boardId) {
  switchTab("library");
  const wbSubtab = document.querySelector('#library-subtabs button[data-target="library-view-whiteboard"]');
  wbSubtab?.click();
  wbShowCanvasView();
  await new Promise((resolve) => setTimeout(resolve, 60));
  window.currentBoardId = boardId ?? null;
  // Anything a previous board's selection drag left behind goes now. The
  // rectangle lives in `#wb-zoom-group`, which the render joins by data and
  // never empties, so without this a stray one followed you from board to
  // board and read as "a permanent selection box on my mindmap".
  wbClearSelectionOverlays();
  await fetchWhiteboardState();
  wbScheduleRender();
  wbApplyBgImage();
  renderWbGestureHints();
  //: Rendered now rather than on the next frame, because the framing below
  //: measures the nodes it is about to fit (a map node is `height: auto`, so
  //: its real size only exists once it is in the document).
  if (wbIsMap()) {
    renderWhiteboardNow();
    wbFrameMapOnOpen();
  }
  //: **A board is a place, so opening one is a navigation.** Asked as part of
  //: "is everythign wired to the nav history and universal undo/redo": it was
  //: not. `switchTab("library")` above records "library", and then opening
  //: board after board recorded nothing at all, so Back from the fourth board
  //: you looked at left the Library entirely rather than returning to the
  //: third. Documents, graph focus and chat conversations all already record
  //: their own identity this way (`doc:{id}`, `focus:{id}`, `conv:{id}`); this
  //: is the same key for the same reason.
  if (typeof recordTabVisit === "function") {
    recordTabVisit("library", boardId ? `board:${boardId}` : "library-view-whiteboard");
  }
}

//: Where "concept maps are unlearnable" is actually answered.
//:
//: The map creates well, a root card, selected, and a toast naming Tab and
//: Enter. Then the toast goes, and the board says nothing at all about the
//: three gestures that *are* the feature. Everything else here is discoverable
//: by pointing at it; these are keys, and a key you were told about once is a
//: key you do not have.
//:
//: Two rules, both from the capture box's own hint: teach at the moment it
//: applies, and never nag. So it shows while the board is still small enough
//: to be starting (a map you have built out has taught you these already), and
//: dismissing it is permanent.
const WB_GESTURES_DISMISSED = "wbGesturesDismissed";
//: Up to this many cards still counts as "just started". Four is a root and
//: three branches: by then you have either used Tab or you are doing
//: something else with the board.
const WB_GESTURE_CARD_LIMIT = 4;

function renderWbGestureHints() {
  const strip = document.getElementById("wb-gestures");
  if (!strip) return;
  let dismissed = false;
  try {
    dismissed = localStorage.getItem(WB_GESTURES_DISMISSED) === "1";
  } catch {
    //: A browser with storage blocked shows the hint every time, which is the
    //: safe direction to fail in: an extra reminder beats a silent feature.
  }
  const cards = (wbState && wbState.nodes ? wbState.nodes.length : 0);
  strip.classList.toggle("hidden", dismissed || cards > WB_GESTURE_CARD_LIMIT);
}
window.renderWbGestureHints = renderWbGestureHints;

document.getElementById("wb-gestures-dismiss")?.addEventListener("click", () => {
  try {
    localStorage.setItem(WB_GESTURES_DISMISSED, "1");
  } catch {
    /* nothing to persist to, hiding it for this session is still correct */
  }
  document.getElementById("wb-gestures")?.classList.add("hidden");
});

/** A new concept map: a board that opens with a core idea on it, selected
 *  and ready to branch from.
 *
 *  Asked for directly: "I want ways to make custom knowledge graphs that are
 *  like mindmaps where I can add and remove nodes, move them around, change
 *  how they connect and reasons, and just make my own thought process map",
 *  and on where it belongs, "I should be able to make and manage map graphs
 *  (maybe in library??)".
 *
 *  **Deliberately not a new canvas.** Everything a concept map needs already
 *  exists on the whiteboard, freely placed cards whose positions persist, a
 *  link tool, `Tab` for a new branch off the selected card and `Enter` for a
 *  sibling, "Arrange as mind map" to re-tidy, pan/zoom, undo, spaces,
 *  export. A parallel implementation would have been a second set of all of
 *  that, immediately behind on every fix either one got.
 *
 *  So what this adds is the three things that were actually missing, and
 *  they are all about *entry*:
 *
 *  1. **A name.** Nothing in the app said the words "concept map", so the
 *     feature was reachable only through a button called "New board" on a
 *     tab called Whiteboards. A feature nobody can name is a feature nobody
 *     finds: reported as missing while fully built.
 *  2. **A root.** An empty board is a blank rectangle; `Tab` and `Enter` do
 *     nothing until something is selected, so the one gesture that makes
 *     this a mind map was unreachable from the state the board opens in.
 *  3. **The gestures, said out loud, once**, at the moment they apply.
 *
 *  The map is a board, so a concept map exported to the whiteboard is a
 *  concept map: which closes the "maybe with a way to export that into a
 *  visual diagram on the whiteboard" half of the ask by construction rather
 *  than by building an exporter.
 */
async function createConceptMap() {
  const name = await promptDialog("What is this map about?", "");
  if (!name || !name.trim()) return;
  const title = name.trim();
  try {
    const board = await apiJson("/whiteboard/boards", {
      method: "POST",
      body: JSON.stringify({ name: title }),
    });
    // The root idea is a real note, the same as every other card on a board.
    // That is the app's own premise rather than a shortcut: an idea here *is*
    // a short note, which is what lets a map node carry tags, links, search
    // and everything else a note has. `defer_filing` keeps the AI's
    // categorisation off the critical path, the map should open now.
    const root = await apiJson("/entries", {
      method: "POST",
      body: JSON.stringify({ content: `# ${title}`, tags: [], defer_filing: true }),
    });
    await apiJson("/whiteboard/nodes", {
      method: "POST",
      body: JSON.stringify({
        // A board-space coordinate the root can call home; the view is
        // centred on it below once the canvas has actually rendered, so
        // this number is arbitrary rather than a claim about the viewport.
        entry_id: root.id,
        board_id: board.id,
        x: 400,
        y: 260,
        z: 1,
      }),
    });
    window.wbLastCreatedBoard = board;
    // Same reason as `wbMindMapAddCard`: the root card reads its text out of
    // `allEntries`, and this note is newer than the last fetch.
    await loadEntries();
    await openWhiteboardBoard(board.id);
    // Selected, because `Tab`/`Enter` act on the selection and an unselected
    // root leaves the map's whole point one undiscoverable click away.
    const placed = wbState.nodes.find((n) => n.entry_id === root.id);
    if (placed) selectWbItem("node", placed.id);
    //: **Centred on the root, not on a guessed coordinate.** Reported: a new
    //: map's first node opened under the top bar rather than in the middle
    //: of the canvas. The node was placed at a fixed (400, 260) on the
    //: (correct, sound) theory that an unzoomed, unpanned view puts the
    //: canvas origin at the container's own top-left, so (400, 260) would
    //: read as "the middle" - but that assumed a container size that was
    //: never measured, and the actual visible canvas (the window, minus the
    //: top bar, the sidebar and the tool rail) is neither the number this
    //: guessed nor a constant: `wbCenterOn` already exists for exactly this
    //: (the navigator's own "jump to a match" uses it), reading the
    //: container's real `getBoundingClientRect()` the way the guess did not.
    //: Not animated: there is nothing to animate *from*, the board has just
    //: opened.
    if (placed) wbCenterOn(wbItemBBox("node", placed), { animate: false });
    toast(`“${title}”: press Tab for a branch, Enter for a sibling.`);
  } catch (err) {
    toast(err.message || "Couldn't create that map.", true);
  }
}
window.createConceptMap = createConceptMap;

/** Full screen for the board, asked for directly ("the whiteboard
 *  definately needs a fullscreen mode because it feels too squished").
 *
 *  Measured before building: the canvas is 1376x676 inside a 1440x900
 *  window, so a quarter of the height is the app header, the Library
 *  sub-tab bar and the status bar. None of those help while drawing.
 *
 *  The class goes on `#library-view-whiteboard`, not on `#wb-canvas-view`.
 *  That looks like the wrong element and is not: `#wb-canvas-view` is a
 *  wrapper whose children are all absolutely positioned, so it measures
 *  **0px tall**: giving it `position: fixed; inset: 0` would size it, but
 *  the board would then be sized by a parent that had not been, which is
 *  the shape of bug this file already has a comment about further down.
 *  `#library-view-whiteboard` is the element that actually carries the
 *  board's height today, so it is the one to promote.
 *
 *  Escape leaves, matching every other full-screen surface in the app.
 */
function toggleWhiteboardFullscreen(force) {
  const host = document.getElementById("library-view-whiteboard");
  if (!host) return;
  // Only a real boolean forces a state; anything else (notably a DOM event
  // arriving from a listener registered by reference) means "toggle". Belt
  // and braces with the arrow at the call site, this one is what makes the
  // function safe to pass around at all.
  const on =
    typeof force === "boolean" ? force : !host.classList.contains("wb-fullscreen");
  host.classList.toggle("wb-fullscreen", on);
  const button = document.getElementById("wb-fullscreen");
  if (button) {
    button.classList.toggle("is-on", on);
    button.title = on ? "Leave full screen (Esc)" : "Full screen (Esc to leave)";
    const icon = button.querySelector("i");
    if (icon) icon.className = on ? "ph ph-arrows-in" : "ph ph-arrows-out";
  }
  // d3's zoom reads the container's size when it clamps a pan, and the
  // floating panels are positioned against it, neither notices a class
  // change on an ancestor on its own.
  window.dispatchEvent(new Event("resize"));
}

// Escape leaves full screen. Capture phase and a check that we are actually
// in it, so this never swallows an Escape meant for a dialog opened *over*
// the board (the properties panel's own inputs, a confirm), those are the
// common case and closing the whole board instead would be maddening.
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const host = document.getElementById("library-view-whiteboard");
  if (!host || !host.classList.contains("wb-fullscreen")) return;
  if (document.querySelector(".modal-overlay:not(.hidden), .lightbox")) return;
  toggleWhiteboardFullscreen(false);
});
