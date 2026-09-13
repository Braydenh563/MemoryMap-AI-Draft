// MemoryMap AI: the graph, drawn to a Canvas 2D surface.
//
// GRAPH_PLAN.md §4 ("Renderer: Canvas 2D first") and §5 Phase 1. This is the
// other half of `graph-worker.js`: the worker decides where the notes are,
// this paints them, and neither one touches the DOM per node.
//
// **Why this exists at all** (§2.1, measured before it was written): the SVG
// renderer builds one `<g>` per node with a circle, a halo, a shine and a
// label, plus two `<line>`s per edge, and rewrites every one of their
// attributes through d3's selection API on every tick. At a few hundred notes
// that is thousands of DOM attribute writes per frame on the same thread the
// pointer is being handled on, which is why dragging stuttered. Here a frame
// is a few hundred canvas path operations regardless of how many notes there
// are, and the simulation is not even on this thread.
//
// It is loaded as a classic script *after* graph.js and before app.js, so
// `renderGraph()` in graph.js can dispatch to `renderGraphCanvas()` by name at
// call time. Nothing in app.js's own top-level wiring names anything in here.
//
// What is deliberately shared with graph.js rather than re-implemented: the
// note popup, the new-note form, the link panel, trace, the minimap, saved
// views, keyboard driving, `fitGraphToView` and the tree/radial/arc layout
// maths. Those are all renderer-agnostic, they work on `graphNodesRef` and on
// `graphSvg`/`graphZoom`, and this file points those at the canvas.

// --- the drawing surface ------------------------------------------------------

let gcCanvas = null; // the <canvas> element
let gcCtx = null;
let gcWorker = null;
//: **Which simulation a message from the worker belongs to.** Bumped every
//: time the node array is replaced, sent with each `init`, and echoed on
//: every tick. A `{type:"stop"}` cannot unsend a tick already posted (both
//: directions of `postMessage` are asynchronous), and the tick handler writes
//: positions *by index*, so a tick from the previous run landing after a
//: relayout overwrites the new positions with the old ones. Measured: the
//: tree switched to 500 ms into a warm force simulation came back with its
//: depth-1 nodes spread over 351 px and its depth-2 nodes over 778 px, where
//: a tree has every node of one depth at one x. That is the scatter reported
//: as "the tree view on the graph is still broken", and it also explains why
//: it was intermittent: at six other moments in the same cooling curve the
//: same switch was clean. A computed layout never sends an `init` at all, so
//: its epoch can match nothing and every tick arriving under it is dropped.
let gcEpoch = 0;
//: The drawing's own copy of the graph. `gcNodes` is the same array
//: `graphNodesRef` points at, so everything in graph.js that walks the nodes
//: (the keyboard, the minimap, `fitGraphToView`, drag-to-link) sees exactly
//: what is on screen. Edges have their `source`/`target` resolved to node
//: objects once per render rather than looked up per frame.
let gcNodes = [];
let gcEdges = [];
let gcAdj = new Map();
let gcById = new Map();
let gcDims = { w: 0, h: 0 };
let gcDpr = 1;
//: The live pan/zoom. Kept here as well as on the element (d3 stores it there)
//: because every draw needs it and `d3.zoomTransform` is a property lookup
//: plus a null check on a hot path.
let gcTransform = null;
let gcObserver = null;
let gcDrawQueued = false;
let gcQuadtree = null;
let gcQuadtreeDirty = true;
//: Set while a pan/zoom gesture is in flight, so a node sliding under a
//: stationary cursor does not register as a hover. Same reasoning the SVG
//: renderer's `graphIsPanning` carries; here it is cheaper, because there is
//: no CSS `:hover` to fight as well.
let gcPanning = false;
//: GRAPH_PLAN Phase 4. A lasso (Shift and drag on empty map) selects notes;
//: the selection dock acts on them. `gcLasso` holds world points while a
//: lasso is being drawn, `gcSelected` the ids it caught (or Shift-clicks
//: added). `graphHiddenIds` is the right-click "Hide" for this visit only:
//: it is not a saved preference, and the legend says how many are hidden.
let gcSelected = new Set();
let gcLasso = null;
let graphHiddenIds = new Set();
let gcLayoutKind = "force";
let gcTree = null; // the laid-out hierarchy for tree/radial/arc, else null
let gcTimeCutoff = null;
let gcColourOf = () => "#888";
let gcTokens = {};
let gcRenderSeq = 0;
//: Timing for the gate (§5 Phase 1) and for `window.__graphDebug`. `firstFrame`
//: is measured from the moment the payload has arrived to the end of the first
//: paint, which is what the plan's "< 300 ms after data arrives" means.
let gcTiming = { dataAt: 0, firstFrame: 0, lastFrame: 0, frames: 0 };
//: The last thing the worker said about itself: how hot the layout still is,
//: and how many steps it has taken. Reported on the debug surface because a
//: slow-looking map is now two separable questions, is the simulation
//: crawling, or is the paint dropping frames, and guessing which cost a round
//: of theorising before this was here.
//: How many labels the last frame wanted and how many it could place
//: without one landing on another (see the label pass in the draw). On
//: the debug surface because "the labels are unreadable" and "the labels
//: are fine" look identical from outside the canvas.
let gcLabelsWanted = 0;
let gcLabelsDrawn = 0;
//: How many of the labels the last frame drew were asked for by name (the
//: hovered or keyboard-focused note, and the search hits): those are drawn
//: whether or not they clash, so they are the number that says whether the
//: collision pass is dropping something somebody went looking for.
let gcLabelsPriority = 0;
//: The boxes the last frame placed, in world coordinates, with the id and the
//: priority rank of each. Read by `scratchpad/ui-sweeps/graph2.js`.
let gcLabelBoxes = [];
let gcAlpha = 0;
let gcTicks = 0;
let gcTickMs = 0;
//: Whether this render has been framed once already, and whether the person
//: has since taken the camera somewhere themselves. See the tick handler for
//: why there are two fits and why the second one is conditional.
let gcFittedOnce = false;
let gcUserZoomed = false;

//: Node radius, GRAPH_PLAN.md §5 Phase 1: `4 + 2*sqrt(degree)`, clamped to
//: [4, 18]. Degree is counted client-side from the edges until Phase 5 sends
//: it on the payload. The SVG renderer sized by PageRank centrality instead,
//: which is a number the reader cannot verify by looking, degree is "how many
//: lines come out of this dot", which is the one thing a graph makes visible.
const GC_MIN_RADIUS = 4;
const GC_MAX_RADIUS = 18;
function gcRadius(node, degree) {
  if (node.isGroup) return node.id === "root" ? 14 : 11;
  const d = degree || 0;
  return Math.max(GC_MIN_RADIUS, Math.min(GC_MAX_RADIUS, 4 + 2 * Math.sqrt(d)));
}

//: Zoom at which labels come on by themselves (§5 Phase 1). Below it a label
//: is unreadable anyway and 2,000 of them are a grey wash; above it there is
//: room for them. A hovered or spotlit node always shows its own.
const GC_LABEL_ZOOM = 1.4;
const GC_LABEL_ALL_MAX = 400;
//: How many search hits are still few enough to be answers rather than a
//: filter, and so are drawn even where they overlap something already there.
//: See the label pass in `gcDraw` for what happens past it.
const GC_LABEL_FORCE_MAX = 12;
//: How far a non-neighbour dims while something is hovered (§5 Phase 1).
const GC_DIM_ALPHA = 0.2;

//: Every colour comes from the app's tokens (§6). Read off the canvas element
//: rather than `:root` so whatever cascade actually applies, theme, a user
//: theme, the dark-mode block, is the one that answers.
function gcReadTokens() {
  const style = getComputedStyle(gcCanvas || document.documentElement);
  const get = (name, fallback) => (style.getPropertyValue(name) || "").trim() || fallback;
  gcTokens = {
    muted: get("--muted", "#8b93a7"),
    accent: get("--accent", "#4f7cff"),
    error: get("--error", "#d2453c"),
    ok: get("--ok", "#2f9e6b"),
    warn: get("--warn", "#c98a17"),
    ink: get("--ink", "#1b1f2a"),
    card: get("--card", "#ffffff"),
    font: get("--font-sans", "system-ui, sans-serif"),
  };
}

//: The edge recipes, transcribed from `.graph-edge*` in
//: css/02-chat-graph.css and `.graph-edge-filing` in
//: css/06-timeline-dialogs.css. Transcribed rather than read back out of the
//: cascade because a canvas has no elements to ask: there is no
//: `.graph-edge-similar` in the DOM to run `getComputedStyle` against. The
//: colours still come from tokens (above), so a theme change moves both.
const GC_EDGE_STYLES = {
  link: { width: 1.6, alpha: 0.55, dash: null, colour: "muted" },
  thread: { width: 1.4, alpha: 0.55, dash: [7, 4], colour: "muted" },
  similar: { width: 1.2, alpha: 0.55, dash: [2, 5], colour: "accent" },
  map: { width: 1.3, alpha: 0.7, dash: [1, 4], colour: "accent" },
  filing: { width: 1.6, alpha: 0.25, dash: [3, 3], colour: "muted" },
  entity: { width: 1.6, alpha: 0.55, dash: null, colour: "muted" },
  document: { width: 1.6, alpha: 0.55, dash: null, colour: "muted" },
};
const GC_EDGE_REASONED = { width: 2.2, alpha: 0.8, dash: null, colour: "accent" };
const GC_EDGE_CONTRADICTS = { width: 2.2, alpha: 0.85, dash: [6, 4], colour: "error" };

function gcEdgeStyle(edge) {
  if (edge.link_type === "contradicts") return GC_EDGE_CONTRADICTS;
  if (edge.kind === "link" && edge.reason) return GC_EDGE_REASONED;
  return GC_EDGE_STYLES[edge.kind] || GC_EDGE_STYLES.link;
}

// --- the surface, sized for the device ----------------------------------------

//: DPR-aware sizing. A canvas has two sizes, the CSS box and the pixel
//: buffer: and getting that wrong is the single most common way a canvas
//: renderer ships blurry. The buffer is the box times the device pixel ratio,
//: and every draw starts by scaling the context by the same number so the
//: drawing code can go on thinking in CSS pixels.
function gcResize() {
  if (!gcCanvas) return false;
  const box = document.getElementById("graph-box");
  const width = (box && box.clientWidth) || 800;
  const height = (box && box.clientHeight) || 540;
  const dpr = window.devicePixelRatio || 1;
  if (width === gcDims.w && height === gcDims.h && dpr === gcDpr) return false;
  gcDims = { w: width, h: height };
  gcDpr = dpr;
  gcCanvas.width = Math.max(1, Math.round(width * dpr));
  gcCanvas.height = Math.max(1, Math.round(height * dpr));
  gcCanvas.style.width = `${width}px`;
  gcCanvas.style.height = `${height}px`;
  graphDims = { w: width, h: height };
  return true;
}

function gcEnsureCanvas() {
  if (gcCanvas) return gcCanvas;
  gcCanvas = document.getElementById("graph-canvas");
  if (!gcCanvas) return null;
  gcCtx = gcCanvas.getContext("2d");
  gcTransform = d3.zoomIdentity;
  gcResize();
  // The card resizes for reasons no `resize` event fires for: the sidebar
  // opening, the legend collapsing, fullscreen. A ResizeObserver is the only
  // thing that sees all of them (§5 Phase 1 asks for one by name).
  if (!gcObserver && typeof ResizeObserver !== "undefined") {
    gcObserver = new ResizeObserver(() => {
      if (gcResize()) gcRequestDraw();
    });
    const box = document.getElementById("graph-box");
    if (box) gcObserver.observe(box);
  }
  gcWireInteraction();
  return gcCanvas;
}

// --- hovering a node -----------------------------------------------------------
//: Asked for: "can you make graph nodes temporarily expand to fill their glow
//: bubble when I hover over them or smth?? I feel like the graph nodes could
//: look slightly nicer, cooler, more professional and more modern. visually".
//:
//: Every node is already drawn with a halo 6px outside its core, and until now
//: the only thing hovering one changed was a ring around it. The dot now grows
//: out to that halo and the halo steps a little further out and brightens, so
//: the glow stays a glow around the node rather than something the node has
//: swallowed.
//:
//: **Animated here rather than in CSS.** The SVG renderer could do this with a
//: `:hover` rule; this one paints to a canvas, which has no elements to hover
//: and no transitions. So the eased value is held as one number and the draw
//: loop is asked for frames only while it is moving: `gcHoverFrom`/`gcHoverTo`
//: name the node it is leaving and the node it is entering, and both are
//: eased, so moving the pointer straight from one node to the next shrinks the
//: first while the second grows instead of snapping.
//:
//: The cost is bounded by construction: at most two nodes are ever mid-ease,
//: the animation is 140ms, and when nothing is easing `gcHoverEase` is exactly
//: 1 and no frames are requested at all.
const GC_HOVER_GROW = 6;       // exactly the gap from a core to its own halo
const GC_HOVER_HALO_GROW = 3;  // and the halo keeps half that much clear
const GC_HOVER_MS = 140;
let gcHoverTo = null;          // the node id growing
let gcHoverFrom = null;        // the node id shrinking back
let gcHoverStart = 0;
let gcHoverEase = 1;           // 0 to 1 across the two above

//: `1 - (1 - t)^3`: fast away from the start, settling at the end. The same
//: shape as the `cubic-bezier(0.2, 0.8, 0.3, 1)` the stylesheet uses for the
//: SVG renderer's version of this, so the two renderers feel the same.
function gcEaseOut(t) {
  const c = Math.min(1, Math.max(0, t));
  return 1 - (1 - c) * (1 - c) * (1 - c);
}

//: Called when the hovered node changes. Whatever was growing starts
//: shrinking from wherever it had got to, so a fast sweep across a cluster
//: does not leave a node stuck large.
function gcHoverChanged(nextId) {
  gcHoverFrom = gcHoverEase < 1 && gcHoverTo != null ? gcHoverTo : gcHoverFrom;
  if (gcHoverEase >= 1) gcHoverFrom = gcHoverTo;
  gcHoverTo = nextId;
  gcHoverStart = performance.now();
  gcHoverEase = 0;
}

//: How much bigger this node is drawing right now, in world units. Zero for
//: every node that is neither entering nor leaving the hover, which is all but
//: two of them.
function gcHoverGrow(node, base) {
  if (node.id === gcHoverTo) return base * gcHoverEase;
  if (node.id === gcHoverFrom) return base * (1 - gcHoverEase);
  return 0;
}

//: Advances the ease and says whether another frame is owed. Called once per
//: draw, before anything is measured, so every radius in that frame agrees.
function gcHoverStep() {
  if (gcHoverEase >= 1) return false;
  //: A reader who has asked for less motion gets the size change without the
  //: travel: the node is simply already large. Removing the growth as well
  //: would leave them with no hover feedback on this renderer at all, since
  //: there is no CSS here to give them a colour change instead.
  const still = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  gcHoverEase = still ? 1 : gcEaseOut((performance.now() - gcHoverStart) / GC_HOVER_MS);
  if (gcHoverEase >= 1) {
    gcHoverEase = 1;
    gcHoverFrom = null;
    return false;
  }
  return true;
}

// --- the draw ------------------------------------------------------------------

function gcRequestDraw() {
  if (gcDrawQueued || !gcCtx) return;
  gcDrawQueued = true;
  requestAnimationFrame(() => {
    gcDrawQueued = false;
    gcDraw();
    if (gcMinimapQueued) {
      gcMinimapQueued = false;
      graphMinimapFrame();
    }
  });
}

//: **The minimap rides the draw's frame.** A pan used to repaint it
//: synchronously on every pointer event: measured over a forty-move pan,
//: forty full repaints, each one four passes over every node and three
//: document lookups, plus up to 700 fresh `<circle>` elements. Only the last
//: of those can be seen, exactly as with the canvas itself, so it belongs in
//: the frame with the draw rather than in the event. What does happen in the
//: event is the thing that has to: `gcTransform` is the new matrix before the
//: handler returns, so anything reading the camera reads the current one.
let gcMinimapQueued = false;
function gcRequestMinimapFrame() {
  gcMinimapQueued = true;
  gcRequestDraw();
}

//: **Two controls that were read out of the document on every frame.** The
//: search box and the labels switch are static elements, and `gcDraw` walked
//: the document for both of them on every frame of every pan, drag and hover:
//: 41 lookups each over a forty-move pan. Cached by id, re-found if the node
//: is ever replaced, which is the same shape the whiteboard's selection-bar
//: lookup needed for the same reason.
const gcElCache = new Map();
function gcEl(id) {
  const hit = gcElCache.get(id);
  if (hit && hit.isConnected) return hit;
  const found = document.getElementById(id);
  if (found) gcElCache.set(id, found);
  else gcElCache.delete(id);
  return found;
}

//: What is dimmed and what is lit, in one pass, for the same reason the SVG
//: renderer's `applyGraphHighlight` does it in one pass: search, the "similar
//: notes" spotlight, a traced path and the hover neighbourhood are four
//: sources of the same signal, and two of them computed separately contradict
//: each other on screen.
function gcHighlight() {
  const search = gcEl("graph-search");
  const query = (search ? search.value : "").trim().toLowerCase();
  const onPath = graphTrace ? new Set(graphTrace.ids) : null;
  const ids = graphHighlightIds;
  const searchOk = (n) =>
    onPath ? onPath.has(n.id) : ids ? ids.has(n.id) : !query || n.preview.toLowerCase().includes(query);
  const neighbours =
    graphHoveredId != null && gcAdj ? gcAdj.get(graphHoveredId) : null;
  const hoverOk = (id) => neighbours == null || id === graphHoveredId || neighbours.has(id);
  return {
    active: Boolean(query || ids || onPath),
    onPath,
    hovering: neighbours != null,
    searchOk,
    hoverOk,
  };
}

function gcVisibleAtTime(node) {
  if (gcTimeCutoff == null) return true;
  if (node.isGroup) return true;
  const at = new Date(node.created_at || Date.now()).getTime();
  return at <= gcTimeCutoff;
}

// --- Phase 4: export at 2x with the legend ------------------------------------------
//: Re-renders the map into an offscreen canvas at `scale` times the screen's
//: pixel density by swapping the draw target for one frame (gcDraw reads
//: gcCtx and gcDpr; gcDims, the CSS size, stays the same, so the transform
//: is identical and nothing moves), then paints the legend and a caption
//: over it. Upscaling the live bitmap would only blur it.
function gcExportPng(scale = 2) {
  if (!gcCtx || !gcCanvas || !gcDims.w) return null;
  const out = document.createElement("canvas");
  out.width = Math.round(gcDims.w * gcDpr * scale);
  out.height = Math.round(gcDims.h * gcDpr * scale);
  const ctx = out.getContext("2d");
  const liveCtx = gcCtx;
  const liveDpr = gcDpr;
  ctx.fillStyle = gcTokens.page || (document.documentElement.dataset.mode === "dark" ? "#12141c" : "#eef1f5");
  ctx.fillRect(0, 0, out.width, out.height);
  try {
    gcCtx = ctx;
    gcDpr = liveDpr * scale;
    gcDraw();
  } finally {
    gcCtx = liveCtx;
    gcDpr = liveDpr;
  }
  ctx.setTransform(gcDpr * scale, 0, 0, gcDpr * scale, 0, 0);
  const rows = [...document.querySelectorAll("#graph-legend .legend-toggle:not(.legend-off)")]
    .map((item) => ({ text: item.textContent.trim(), colour: item.querySelector(".legend-dot")?.style.background || gcTokens.muted }))
    .filter((row) => row.text)
    .slice(0, 14);
  const noteCount = gcNodes.filter((n) => !n.isGroup).length;
  const caption = `${noteCount} note${noteCount === 1 ? "" : "s"} · ${new Date().toLocaleDateString()}`;
  ctx.font = "12px system-ui, sans-serif";
  const lineH = 18;
  const pad = 10;
  const width = Math.max(ctx.measureText(caption).width, ...rows.map((r) => ctx.measureText(r.text).width + 18)) + pad * 2;
  const height = (rows.length + 1) * lineH + pad * 2;
  const x = 12;
  const y = gcDims.h - height - 12;
  ctx.globalAlpha = 0.92;
  ctx.fillStyle = gcTokens.card || "#ffffff";
  ctx.beginPath();
  ctx.roundRect(x, y, width, height, 8);
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.fillStyle = gcTokens.ink || "#111";
  ctx.textBaseline = "middle";
  ctx.fillText(caption, x + pad, y + pad + lineH / 2);
  rows.forEach((row, i) => {
    const cy = y + pad + lineH * (i + 1) + lineH / 2;
    ctx.fillStyle = row.colour;
    ctx.beginPath();
    ctx.arc(x + pad + 5, cy, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = gcTokens.ink || "#111";
    ctx.fillText(row.text, x + pad + 18, cy);
  });
  return out;
}

function gcDraw() {
  if (!gcCtx || !gcCanvas) return;
  const started = performance.now();
  //: Advanced once, before anything is measured, so every radius in this frame
  //: agrees, and another frame is asked for only while it is still moving.
  const easing = gcHoverStep();
  const ctx = gcCtx;
  const t = gcTransform || d3.zoomIdentity;
  const k = t.k;
  ctx.setTransform(gcDpr, 0, 0, gcDpr, 0, 0);
  ctx.clearRect(0, 0, gcDims.w, gcDims.h);
  ctx.save();
  ctx.translate(t.x, t.y);
  ctx.scale(k, k);

  // Cull to the visible world rectangle. On a 2,000-note map zoomed in, this
  // is the difference between drawing 2,000 nodes and drawing forty.
  const margin = 80 / k;
  const view = {
    left: -t.x / k - margin,
    top: -t.y / k - margin,
    right: (gcDims.w - t.x) / k + margin,
    bottom: (gcDims.h - t.y) / k + margin,
  };
  const inView = (n) =>
    n.x >= view.left && n.x <= view.right && n.y >= view.top && n.y <= view.bottom;

  const hl = gcHighlight();
  const labelsOn = (() => {
    const box = gcEl("graph-labels");
    return box ? box.checked : true;
  })();

  // --- edges -------------------------------------------------------------
  // Bucketed by recipe and by whether they are dimmed, so the context's
  // stroke state is set once per bucket rather than once per edge. A dashed
  // stroke is the expensive one, and there are only ever a handful of dashes.
  const buckets = new Map();
  for (const edge of gcEdges) {
    const a = edge.source;
    const b = edge.target;
    if (!a || !b || !Number.isFinite(a.x) || !Number.isFinite(b.x)) continue;
    if (!gcVisibleAtTime(a) || !gcVisibleAtTime(b)) continue;
    // Both ends off-screen on the same side: nothing of the line can be in
    // frame. A cheap, conservative test, an edge crossing the viewport with
    // both ends outside still gets drawn.
    if (
      (a.x < view.left && b.x < view.left) ||
      (a.x > view.right && b.x > view.right) ||
      (a.y < view.top && b.y < view.top) ||
      (a.y > view.bottom && b.y > view.bottom)
    ) {
      continue;
    }
    const bySearch = !hl.active || (hl.searchOk(a) && hl.searchOk(b));
    const byHover =
      !hl.hovering || a.id === graphHoveredId || b.id === graphHoveredId;
    const dim = !(bySearch && byHover);
    const style = gcEdgeStyle(edge);
    const key = `${edge.kind}|${style.colour}|${style.width}|${style.dash}|${dim}`;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { style, dim, path: new Path2D() };
      buckets.set(key, bucket);
    }
    if (gcTree) {
      // A tree's edges are curves between fixed points. `hierarchyPath` and
      // `arcPath` already return SVG path data, and Path2D speaks it, so the
      // curve maths is shared with the SVG renderer rather than rewritten.
      if (!edge._path2d) {
        edge._path2d = new Path2D(gcTree.arc ? arcPath(edge) : hierarchyPath(edge, gcTree.radial));
      }
      bucket.path.addPath(edge._path2d);
    } else {
      bucket.path.moveTo(a.x, a.y);
      bucket.path.lineTo(b.x, b.y);
    }
  }
  for (const bucket of buckets.values()) {
    const style = bucket.style;
    ctx.strokeStyle = gcTokens[style.colour] || gcTokens.muted;
    // `.graph-edge.graph-dim` is opacity 0.06 in the stylesheet; kept, because
    // a dimmed edge that is still readable defeats the spotlight.
    ctx.globalAlpha = bucket.dim ? 0.06 : style.alpha;
    ctx.lineWidth = style.width / k;
    ctx.setLineDash(style.dash ? style.dash.map((v) => v / k) : []);
    ctx.stroke(bucket.path);
  }
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;

  // --- the traced path ----------------------------------------------------
  gcDrawTrace(ctx, k);

  // --- nodes --------------------------------------------------------------
  // Two batched fills per colour (halo, then core) and one batched stroke for
  // the ordinary ring. Only the handful of nodes that are hovered, matched,
  // pinned, held, hub or on a path get their own stroke.
  const haloByColour = new Map();
  const coreByColour = new Map();
  const ringed = [];
  const hubs = { path: new Path2D(), any: false };
  const labelled = [];
  const drawn = [];
  const hotHalos = [];
  for (const node of gcNodes) {
    if (!Number.isFinite(node.x)) continue;
    if (!gcVisibleAtTime(node)) continue;
    if (!inView(node)) continue;
    const dim = !(hl.searchOk(node) && hl.hoverOk(node.id));
    const key = `${node.colour}|${dim}`;
    let halo = haloByColour.get(key);
    if (!halo) {
      halo = { colour: node.colour, dim, path: new Path2D() };
      haloByColour.set(key, halo);
      coreByColour.set(key, { colour: node.colour, dim, path: new Path2D() });
    }
    //: The hover growth, applied once and remembered on the node, so the core,
    //: the halo, the plain ring, the hub ring and the special ring below all
    //: draw against the same radius this frame. Reading it four times would
    //: let the ring and the dot it rings disagree by a fraction of a pixel
    //: mid-ease, which reads as a shimmer on the outline.
    node._grow = gcHoverGrow(node, GC_HOVER_GROW);
    //: The at most two nodes mid-ease, kept aside so their halo can be lit
    //: without breaking the colour batching every other node relies on.
    const heat = gcHoverGrow(node, 1);
    if (heat > 0) hotHalos.push({ node, heat });
    const r = node.r + node._grow;
    const haloR = node.r + 6 + gcHoverGrow(node, GC_HOVER_HALO_GROW);
    halo.path.moveTo(node.x + haloR, node.y);
    halo.path.arc(node.x, node.y, haloR, 0, Math.PI * 2);
    const core = coreByColour.get(key);
    core.path.moveTo(node.x + r, node.y);
    core.path.arc(node.x, node.y, r, 0, Math.PI * 2);
    drawn.push(node);
    node._dim = dim;
    const focused = node.id === graphHoveredId || node.id === graphKeyboardId;
    const matched = hl.active && hl.searchOk(node);
    const onPath = hl.onPath ? hl.onPath.has(node.id) : false;
    const special =
      focused ||
      matched ||
      onPath ||
      node.pinned ||
      node.fx != null ||
      node.type === "entity" ||
      node.type === "document" ||
      node === gcDropTarget;
    if (special) {
      ringed.push({ node, focused, matched, onPath, dim });
    } else if (!dim && (gcAdj.get(node.id) || { size: 0 }).size >= 3) {
      // **A hub's ring is batched, not drawn per node.** Average degree in a
      // real notebook is about four, so "degree >= 3" is most of the map: one
      // `beginPath`/`stroke` each was 2,000 stroke calls a frame at the fitted
      // zoom and on its own blew the 16 ms budget. Every hub ring is the same
      // colour and the same width, so it is one path and one stroke.
      hubs.path.moveTo(node.x + node.r + node._grow, node.y);
      hubs.path.arc(node.x, node.y, node.r + node._grow, 0, Math.PI * 2);
      hubs.any = true;
    }
    // Labels come on by zoom, and a hovered or spotlit note always shows its
    // own: including with the Labels tickbox off, which is what
    // `.graph-labels-hidden g.graph-focus .graph-label { opacity: 1 }` does on
    // the SVG renderer. "Labels off" means "not all of them", not "never".
    // "Labels on" means on. Reported with a screenshot: the tickbox was on
    // and one hovered label showed, because every other label waited for a
    // zoom past GC_LABEL_ZOOM that a fitted 35-note map never reaches. Below
    // GC_LABEL_ALL_MAX nodes the tickbox shows them all at any zoom; above
    // it the zoom gate stays, since 2,000 labels at the fitted zoom are
    // paint the eye cannot read and the frame budget cannot afford.
    const labelsForAll = labelsOn && gcNodes.length <= GC_LABEL_ALL_MAX;
    if (!dim && ((labelsOn && (labelsForAll || k > GC_LABEL_ZOOM || matched)) || focused)) {
      labelled.push(node);
    }
  }
  for (const [key, halo] of haloByColour) {
    ctx.globalAlpha = halo.dim ? 0.05 : 0.18;
    ctx.fillStyle = halo.colour;
    ctx.fill(halo.path);
    const core = coreByColour.get(key);
    ctx.globalAlpha = core.dim ? GC_DIM_ALPHA : 1;
    ctx.fillStyle = core.colour;
    ctx.fill(core.path);
  }
  //: The hovered node's halo, lit. A second fill over the one the batch
  //: already laid down, because pulling this node out of its colour batch to
  //: give it a different alpha would cost a fill per colour rather than a fill
  //: per hovered node, and there are at most two of those.
  //:
  //: 0.33 over the batch's 0.18 composites to 0.45: `1 - (1 - 0.18)(1 - 0.33)`.
  //: Multiplying by `heat` is what makes it ease in and out with the size,
  //: including on the node being left, whose `heat` is counting down.
  for (const hot of hotHalos) {
    if (hot.node._dim) continue;
    ctx.globalAlpha = 0.33 * hot.heat;
    ctx.fillStyle = hot.node.colour;
    ctx.beginPath();
    ctx.arc(
      hot.node.x,
      hot.node.y,
      hot.node.r + 6 + gcHoverGrow(hot.node, GC_HOVER_HALO_GROW),
      0,
      Math.PI * 2,
    );
    ctx.fill();
  }

  // The ordinary ring (`.graph-core { stroke: var(--card) }`) in one pass.
  ctx.globalAlpha = 1;
  ctx.strokeStyle = gcTokens.card;
  ctx.lineWidth = 2 / k;
  const plain = new Path2D();
  for (const node of drawn) {
    if (node._dim) continue;
    plain.moveTo(node.x + node.r + node._grow, node.y);
    plain.arc(node.x, node.y, node.r + node._grow, 0, Math.PI * 2);
  }
  ctx.stroke(plain);
  if (hubs.any) {
    // Well-connected notes get a brighter ring so the structure of the
    // notebook is visible without reading a single label.
    ctx.strokeStyle = gcTokens.accent;
    ctx.lineWidth = 2.5 / k;
    ctx.stroke(hubs.path);
  }

  gcDrawSelection(ctx, k);
  for (const item of ringed) {
    const node = item.node;
    ctx.globalAlpha = item.dim ? GC_DIM_ALPHA : 1;
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.r + (node._grow || 0), 0, Math.PI * 2);
    if (node === gcDropTarget) {
      ctx.strokeStyle = gcTokens.ok;
      ctx.lineWidth = 4 / k;
    } else if (item.onPath) {
      ctx.strokeStyle = gcTokens.accent;
      ctx.lineWidth = 3.5 / k;
    } else if (item.focused) {
      ctx.strokeStyle = gcTokens.accent;
      ctx.lineWidth = 3.5 / k;
    } else if (item.matched) {
      ctx.strokeStyle = gcTokens.accent;
      ctx.lineWidth = 3 / k;
    } else if (node.fx != null && gcLayoutKind === "force") {
      // Held in place by a drag or a double-click: the same dashed ink ring
      // `.graph-held` draws, so a held note looks held on both renderers.
      //
      //: Force layout only. Tree, radial and arc hold every node by setting
      //: `fx`/`fy` from the computed hierarchy, so this test was true for all
      //: of them at once and the whole board wore the ring that means "you
      //: pinned this". Reported on 2026-09-09: "on the other graph view
      //: types, they all have the dotted border as they are static but that
      //: shouldnt be the case".
      ctx.strokeStyle = gcTokens.ink;
      ctx.lineWidth = 2 / k;
      ctx.setLineDash([3 / k, 2 / k]);
    } else if (node.pinned) {
      ctx.strokeStyle = gcTokens.warn;
      ctx.lineWidth = 2 / k;
    } else if (node.type === "entity" || node.type === "document") {
      ctx.strokeStyle = gcTokens.ink;
      ctx.lineWidth = 2 / k;
      ctx.setLineDash(node.type === "entity" ? [3 / k, 2 / k] : [1 / k, 3 / k]);
    } else {
      // Unreachable while `ringed` only takes the nodes the branches above
      // name; kept so a future ring condition added to that test cannot draw
      // with whatever stroke the previous node happened to leave set.
      ctx.strokeStyle = gcTokens.accent;
      ctx.lineWidth = 2.5 / k;
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.globalAlpha = 1;

  // --- labels -------------------------------------------------------------
  gcLabelsWanted = 0;
  gcLabelsDrawn = 0;
  gcLabelsPriority = 0;
  // Cleared per frame, not only written per frame: a map whose labels have
  // just been switched off would otherwise report the boxes of the last frame
  // that had any.
  gcLabelBoxes = [];
  if (labelled.length) {
    const size = 12 / k;
    // Divided by the zoom so a label is a constant size on screen: the whole
    // context is scaled by k, and a fixed font size would make labels grow
    // with the map until three of them filled the card.
    ctx.font = `500 ${size}px ${gcTokens.font}`;
    // A tree's rows are 34px apart, so a label under the node lands on the
    // next row's; beside it is the only place it fits. The web spreads in two
    // dimensions and reads better with the label under the dot. (Radial and
    // arc labels are centred under the node here rather than rotated onto the
    // spoke, which is the one place this renderer is visibly plainer than the
    // SVG one: recorded in GRAPH_PLAN.md's "Built" section.)
    const beside = Boolean(gcTree) && !gcTree.radial && !gcTree.arc;
    ctx.textAlign = beside ? "left" : "center";
    ctx.textBaseline = "middle";
    ctx.lineJoin = "round";
    ctx.lineWidth = 3 / k;
    ctx.strokeStyle = gcTokens.card;
    ctx.fillStyle = gcTokens.ink;
    // **Labels do not stack.** Reported with a screenshot: with the Labels
    // tickbox on, a fitted map drew all of them (every board under
    // `GC_LABEL_ALL_MAX`), and in the dense middle of a force layout that is
    // a pile of overlapping words that says less than no label at all.
    //
    // So a label is drawn only if its own text box is still free. The order
    // decides which one wins the space, and it is not the order the nodes
    // happen to be in: whatever the pointer or the keyboard is on first (it
    // was asked for by name), then the search hits (the reason someone
    // typed), then the best-connected notes, which are the ones a map is
    // read by. Those two priority classes are drawn even when they clash,
    // because a label you asked for and cannot see is a bug, not tidiness.
    // The rest come back on hover or above `GC_LABEL_ZOOM`, which is the
    // gesture the map already teaches.
    //
    // The overlap test is a linear scan of what has been placed: the placed
    // set is bounded by the frame's area over a label's, a few dozen, so
    // this is thousands of number comparisons and no allocation, not the
    // quadtree it looks like it wants.
    const labelRank = (node) =>
      node.id === graphHoveredId || node.id === graphKeyboardId
        ? 0
        : hl.active && hl.searchOk(node)
          ? 1
          : 2;
    // **A search that matches half the notebook is not a request for half the
    // notebook's labels.** Found by the probe on the 300-note fixture:
    // searching a word every note contains made all 264 hits rank 1, and rank
    // 1 was drawn through any clash, so the pile the collision pass exists to
    // prevent came straight back through the search box. A handful of hits is
    // a question about those notes and each one keeps its label whatever it
    // lands on; past that it is a filter, and a filter's job is done by the
    // dimming, with the labels queued ahead of everything else and still
    // subject to the same test as everything else. The hovered or
    // keyboard-focused note is never in this trade: there is exactly one of
    // it, and it was pointed at.
    const hits = labelled.reduce((n, node) => n + (labelRank(node) === 1 ? 1 : 0), 0);
    const forceHits = hits <= GC_LABEL_FORCE_MAX;
    labelled.sort((a, b) => {
      const rank = labelRank(a) - labelRank(b);
      if (rank) return rank;
      const degreeA = (gcAdj.get(a.id) || { size: 0 }).size;
      const degreeB = (gcAdj.get(b.id) || { size: 0 }).size;
      return degreeB - degreeA;
    });
    const placed = [];
    gcLabelsWanted = labelled.length;
    gcLabelsPriority = 0;
    const padX = 4 / k;
    const padY = 2 / k;
    // `paint-order: stroke` on `.graph-label`, the halo goes down first so a
    // label stays legible over an edge or another node.
    for (const node of labelled) {
      const text = gcLabelText(node);
      // `measureText` is cheap but not free at a few hundred labels a frame,
      // and the answer only changes when the text or the zoom does.
      if (node._labelText !== text || node._labelSize !== size) {
        node._labelText = text;
        node._labelSize = size;
        node._labelWidth = ctx.measureText(text).width;
      }
      const width = node._labelWidth;
      const x = beside ? node.x + node.r + 7 : node.x;
      const y = beside ? node.y : node.y + node.r + 13;
      const left = (beside ? x : x - width / 2) - padX;
      const rank = labelRank(node);
      if (rank < 2) gcLabelsPriority += 1;
      // The id and the rank ride along with the geometry because the only
      // way to ask "do the labels on screen overlap" from outside a canvas is
      // to be handed the boxes: a screenshot of a pile of words and a
      // screenshot of a clean map are the same bytes to a sweep.
      const box = {
        id: node.id,
        rank,
        left,
        right: left + width + padX * 2,
        top: y - size / 2 - padY,
        bottom: y + size / 2 + padY,
      };
      let clashes = false;
      for (const other of placed) {
        if (
          box.left < other.right &&
          box.right > other.left &&
          box.top < other.bottom &&
          box.bottom > other.top
        ) {
          clashes = true;
          break;
        }
      }
      if (clashes && !(rank === 0 || (rank === 1 && forceHits))) continue;
      placed.push(box);
      ctx.strokeText(text, x, y);
      ctx.fillText(text, x, y);
    }
    gcLabelBoxes = placed;
    gcLabelsDrawn = placed.length;
  }

  ctx.restore();
  gcTiming.lastFrame = performance.now() - started;
  gcTiming.frames += 1;
  // **Only a frame with something in it stops the clock.** A frame drawn
  // before the first positions exist is a blank canvas, and calling that "the
  // first frame" would be measuring nothing and reporting a good number for
  // it: the exact shape of self-deception the gate exists to prevent.
  if (!gcTiming.firstFrame && gcTiming.dataAt && drawn.length) {
    gcTiming.firstFrame = performance.now() - gcTiming.dataAt;
  }
  //: One more frame while the hover is still growing or shrinking. Nothing
  //: is scheduled once `gcHoverStep` reports it has arrived, so an idle graph
  //: costs no frames at all.
  if (easing) gcRequestDraw();
}

function gcLabelText(node) {
  const limit = gcTree ? (gcTree.arc ? 12 : gcTree.radial ? 16 : 30) : 22;
  const text = node.preview || "";
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

//: The trace overlay. Drawn from the same `graphTrace`/`graphTraceRoutes`
//: state the SVG renderer's `drawTrace` fills in, so trace mode, the route
//: chips and the readout are untouched by the change of renderer.
function gcDrawTrace(ctx, k) {
  const routes = graphTraceRoutes.length
    ? graphTraceRoutes
    : graphTrace
      ? [{ steps: graphTrace.steps }]
      : [];
  if (!routes.length || !gcById) return;
  const colours = [gcTokens.accent, gcTokens.ok, gcTokens.warn];
  const isArc = gcTree && gcTree.arc;
  const drawRoute = (route, index, selected) => {
    ctx.strokeStyle = colours[index % 3];
    ctx.globalAlpha = selected ? 0.85 : 0.42;
    ctx.lineWidth = (selected ? 4 : 2) / k;
    ctx.setLineDash(selected ? [] : [6 / k, 5 / k]);
    ctx.lineCap = "round";
    ctx.beginPath();
    for (const step of route.steps || []) {
      const from = gcById.get(step.source);
      const to = gcById.get(step.target);
      if (!from || !to || !Number.isFinite(from.x) || !Number.isFinite(to.x)) continue;
      if (isArc) {
        ctx.stroke(new Path2D(tracePath(from, to)));
      } else {
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
      }
    }
    if (!isArc) ctx.stroke();
  };
  routes.forEach((route, index) => {
    if (index === graphTraceIndex) return; // drawn last so it wins the overlap
    drawRoute(route, index, false);
  });
  if (routes[graphTraceIndex]) drawRoute(routes[graphTraceIndex], graphTraceIndex, true);
  ctx.globalAlpha = 1;
  ctx.setLineDash([]);
}

// --- hit-testing ----------------------------------------------------------------

//: A `d3.quadtree` over the node positions (§4: "Hit-testing via a quadtree,
//: not per-node DOM events"). Rebuilt lazily: marked dirty by every draw, and
//: actually rebuilt only when something asks what is under the pointer, which
//: is at most once a frame and only while the pointer is over the map.
function gcTreeIndex() {
  if (gcQuadtree && !gcQuadtreeDirty) return gcQuadtree;
  gcQuadtree = d3
    .quadtree()
    .x((n) => n.x)
    .y((n) => n.y)
    .addAll(gcNodes.filter((n) => Number.isFinite(n.x) && Number.isFinite(n.y)));
  gcQuadtreeDirty = false;
  return gcQuadtree;
}

//: The node under a point given in world coordinates, or null. The search
//: radius is generous by exactly the slop a pointer needs at the current zoom:
//: a 4px dot at k=0.3 is a one-pixel target otherwise.
function gcNodeAtWorld(x, y) {
  if (!gcNodes.length) return null;
  const slop = 6 / ((gcTransform && gcTransform.k) || 1);
  const found = gcTreeIndex().find(x, y, GC_MAX_RADIUS + slop + 8);
  if (!found) return null;
  if (!gcVisibleAtTime(found)) return null;
  const distance = Math.hypot(found.x - x, found.y - y);
  return distance <= found.r + slop ? found : null;
}

function gcWorldPoint(event) {
  const point = d3.pointer(event, gcCanvas);
  const t = gcTransform || d3.zoomIdentity;
  return t.invert(point);
}

//: The edge under a point, for the link-management panel a click on a link
//: opens. Linear over the edges rather than indexed: it runs once per click,
//: never per frame, and an index that has to be kept in step with a moving
//: layout would cost more than it saves.
function gcEdgeAtWorld(x, y) {
  const tolerance = 8 / ((gcTransform && gcTransform.k) || 1);
  let best = null;
  let bestDistance = tolerance;
  for (const edge of gcEdges) {
    if (edge.kind !== "link") continue;
    const a = edge.source;
    const b = edge.target;
    if (!a || !b || !Number.isFinite(a.x) || !Number.isFinite(b.x)) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const lengthSq = dx * dx + dy * dy || 1;
    let t = ((x - a.x) * dx + (y - a.y) * dy) / lengthSq;
    t = Math.max(0, Math.min(1, t));
    const distance = Math.hypot(a.x + t * dx - x, a.y + t * dy - y);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = edge;
    }
  }
  return best;
}

// --- pointer, zoom and drag -----------------------------------------------------

let gcDropTarget = null;
let gcDragNode = null;
let gcWired = false;

function gcWireInteraction() {
  if (gcWired || !gcCanvas) return;
  gcWired = true;
  const selection = d3.select(gcCanvas);

  const zoom = d3
    .zoom()
    .scaleExtent([0.05, 5])
    // A drag that starts on a node moves the node; anywhere else pans. Without
    // this filter d3-zoom claims the gesture first and a node can never be
    // picked up.
    .filter((event) => {
      if (event.type === "wheel") return true;
      if (event.button) return false;
      // Shift and drag on empty map is the lasso, not a pan.
      if (event.shiftKey) return false;
      const [x, y] = gcWorldPoint(event);
      return !gcNodeAtWorld(x, y);
    })
    .on("start", () => {
      gcPanning = true;
      graphHoveredId = null;
      gcRequestDraw();
    })
    .on("zoom", (event) => {
      // `sourceEvent` is set for a real gesture and null for a programmatic
      // transform, which is how "the user went to look at something" is told
      // apart from "the renderer framed the map".
      if (event.sourceEvent) gcUserZoomed = true;
      gcTransform = event.transform;
      gcRequestDraw();
      gcRequestMinimapFrame();
    })
    .on("end", () => {
      gcPanning = false;
      gcRequestDraw();
    });
  selection.call(zoom).on("dblclick.zoom", null);

  // The rest of the app drives zoom through `graphSvg`/`graphZoom`, the
  // +/-/fit buttons, the keyboard, the minimap, saved views, `fitGraphToView`.
  // Pointing those two at the canvas is what makes every one of them keep
  // working without a line of change: `d3.zoom` does not care what element it
  // is attached to, and `d3.zoomTransform` reads the transform off the node.
  graphSvg = selection;
  graphZoom = zoom;
  graphCanvas = null; // there is no <g> to transform any more

  selection.call(
    d3
      .drag()
      // **The canvas, not its parent.** d3-drag's default container is
      // `this.parentNode`, so without this the pointer would be measured
      // against `#graph-box` while the subject's coordinates are measured
      // against the canvas: an offset that is zero today and stops being zero
      // the moment anything is laid out above the canvas inside the box.
      .container(() => gcCanvas)
      .subject((event) => {
        //: **Nothing is dragged in a computed layout.** A tree, a ring or an
        //: arc *is* its shape, and a node pulled out of it makes the picture
        //: a lie; the position also comes back on the next relayout, so the
        //: gesture would not even hold. A null subject means d3-drag declines
        //: the gesture and the zoom behaviour keeps the pointer, so panning
        //: still works where a drag used to start.
        if (gcLayoutKind !== "force") return null;
        const [x, y] = gcWorldPoint(event);
        const node = gcNodeAtWorld(x, y);
        if (!node) return null;
        const [sx, sy] = (gcTransform || d3.zoomIdentity).apply([node.x, node.y]);
        return { node, x: sx, y: sy };
      })
      .on("start", (event) => {
        const node = event.subject.node;
        gcDragNode = node;
        node._dragStartX = node.x;
        node._dragStartY = node.y;
        node._wasPinned = node.fx != null;
        //: **Shift is what pins.** INBOX 96, the owner: "my original annoyance
        //: was that I'd try to drag a node or cluster around and it would just
        //: snap back ... but I move a node a little and then I have to unpin
        //: it and there's got to be a better way." Both halves of that are one
        //: rule: a plain drag places a node and lets the map settle around it,
        //: an explicit pin holds it against the simulation for good. Read at
        //: `start` rather than at `end` because the modifier is part of the
        //: gesture the reader began, and a Shift pressed or released mid-drag
        //: would otherwise change what the gesture meant halfway through.
        node._dragShift = Boolean(event.sourceEvent && event.sourceEvent.shiftKey);
        const [wx, wy] = (gcTransform || d3.zoomIdentity).invert([event.x, event.y]);
        node.fx = wx;
        node.fy = wy;
        gcPost({ type: "drag", phase: "start", id: node.id, x: wx, y: wy });
        // **Everything holds still except this note's own neighbours.**
        //
        // Two rules were in conflict here and both are real. The SVG renderer
        // froze the entire map for the length of a drag, because drag-to-link
        // asks you to aim at a note and aiming at a moving target is not a
        // gesture: that was a direct report. But GRAPH_PLAN.md §3 asks for
        // the opposite thing, and it is the whole point of this phase:
        // "dragging feels physical (the neighbours follow and the rest
        // settles)". Freezing everything makes a drag a pointer-follow with a
        // simulation running behind it that cannot move anything.
        //
        // Freezing everything *except the direct neighbourhood* satisfies both:
        // the notes attached to the one in your hand come along, which is the
        // physicality, and every other note on the map holds the position you
        // are aiming at, which is the gesture.
        const following = gcAdj.get(node.id) || new Set();
        gcPost({
          type: "freeze",
          ids: gcNodes
            .filter((n) => n !== node && n.fx == null && !following.has(n.id))
            .map((n) => n.id),
        });
      })
      .on("drag", (event) => {
        const node = event.subject.node;
        const [wx, wy] = (gcTransform || d3.zoomIdentity).invert([event.x, event.y]);
        node.fx = wx;
        node.fy = wy;
        node.x = wx;
        node.y = wy;
        gcQuadtreeDirty = true;
        gcPost({ type: "drag", phase: "move", id: node.id, x: wx, y: wy });
        gcDropTarget = graphNodeUnder(node, { x: wx, y: wy });
        gcRequestDraw();
      })
      .on("end", (event) => {
        const node = event.subject.node;
        gcDragNode = null;
        const over = gcDropTarget;
        gcDropTarget = null;
        const movedFar =
          Math.abs(node.x - node._dragStartX) > 2 || Math.abs(node.y - node._dragStartY) > 2;
        //: A plain drag places the node and releases it: the worker's own
        //: `keep: false` path clears `fx`/`fy` and lets `alphaTarget(0)`
        //: decay, so the node settles from where it was dropped with its
        //: neighbours rather than snapping back to where it came from. That
        //: decay is the "better way" the report asks for, and it was already
        //: written; what was wrong is that a moved node never reached it,
        //: because any drag over 2px counted as a pin.
        //:
        //: A zero-distance drag is still a click and pins nothing, and a node
        //: that was already pinned stays pinned at its new place: dragging a
        //: pinned node is a reposition, not a request to release it.
        const keep = node._dragShift || node._wasPinned;
        gcPost({ type: "drag", phase: "end", id: node.id, keep });
        gcPost({ type: "thaw" });
        if (!keep) {
          node.fx = null;
          node.fy = null;
        }
        if (over && movedFar) {
          linkByDrop(node, over);
        } else if (!movedFar) {
          gcClickNode(event.sourceEvent, node);
        } else if (!node.isGroup && keep) {
          //: Only a real pin is written down. A placement that the simulation
          //: is free to relax has no position worth surviving a reload, and
          //: saving one was what made every small nudge into a pin the reader
          //: then had to find and undo.
          node.graph_pin_x = node.fx;
          node.graph_pin_y = node.fy;
          apiJson(`/graph/pin/${node.id}`, {
            method: "PUT",
            body: JSON.stringify({ x: node.graph_pin_x, y: node.graph_pin_y }),
          }).catch(() => {
            // Best-effort, exactly as on the SVG path: the placement has
            // already taken effect in memory, so a failed save costs the
            // reload and nothing else.
          });
        }
        gcRequestDraw();
      })
  );

  gcCanvas.addEventListener("pointermove", (event) => {
    if (gcPanning || gcDragNode) return;
    const [x, y] = gcWorldPoint(event);
    const node = gcNodeAtWorld(x, y);
    const id = node ? node.id : null;
    if (id !== graphHoveredId) {
      graphHoveredId = id;
      gcHoverChanged(id);
      // The native tooltip the SVG renderer got from a `<title>` child. A
      // canvas has no children, so the canvas itself carries whichever one
      // applies.
      gcCanvas.title = node ? gcTooltip(node) : "";
      gcRequestDraw();
    }
  });
  gcCanvas.addEventListener("pointerleave", () => {
    if (graphHoveredId == null) return;
    graphHoveredId = null;
    gcHoverChanged(null);
    gcCanvas.title = "";
    gcRequestDraw();
  });

  gcCanvas.addEventListener("click", (event) => {
    const [x, y] = gcWorldPoint(event);
    const hit = gcNodeAtWorld(x, y);
    if (hit) {
      //: **A node is clicked here in every layout but force.** Reported:
      //: "the note node popups dont show on any of the graph views when I
      //: click on a node except for the force view." In a force layout a
      //: click on a node is a zero-distance drag, and d3-drag's `end`
      //: turns it into one (`gcClickNode`), which is why this used to
      //: return. But a computed layout has no drag at all: `subject()`
      //: deliberately returns null for tree, radial and arc so a node
      //: cannot be pulled out of a shape that *is* the meaning, and with
      //: no drag there is no `end` and nothing ever opened the popup.
      //: The click event is the only thing those three layouts get, so it
      //: is where their click lives.
      if (gcLayoutKind === "force") return;
      gcClickNode(event, hit);
      return;
    }
    const edge = gcEdgeAtWorld(x, y);
    if (edge) {
      openGraphLinkPanel(edge, gcNodes);
      return;
    }
    closeGraphPopup();
    closeGraphNewNote();
  });

  gcCanvas.addEventListener("dblclick", (event) => {
    const [x, y] = gcWorldPoint(event);
    const node = gcNodeAtWorld(x, y);
    if (!node) {
      // Grow the map: double-click empty space to add a note right there.
      openGraphNewNote(event);
      return;
    }
    //: A double click in a computed layout used to clear that one node's
    //: `fx`/`fy` and hand it to the force simulation, which then re-solved
    //: from there and pulled the rest of the tree apart with it: reported as
    //: "I test double clicked on a node and it broke them all out of
    //: position". There is no pin to toggle where every position is computed.
    if (gcLayoutKind !== "force") return;
    gcTogglePin(node);
  });
  gcWireLasso();
  gcWireNodeMenu();
  gcWireSelectionDock();
}

function gcTogglePin(node) {
  const wasPinned = node.fx != null;
  if (wasPinned) {
    node.fx = null;
    node.fy = null;
    gcPost({ type: "unpin", id: node.id });
  } else {
    node.fx = node.x;
    node.fy = node.y;
    gcPost({ type: "pin", id: node.id, x: node.x, y: node.y });
  }
  gcRequestDraw();
  if (node.isGroup) return;
  node.graph_pin_x = wasPinned ? null : node.fx;
  node.graph_pin_y = wasPinned ? null : node.fy;
  apiJson(`/graph/pin/${node.id}`, {
    method: "PUT",
    body: JSON.stringify({ x: node.graph_pin_x, y: node.graph_pin_y }),
  }).catch(() => {
  });
}

// --- Phase 4: the lasso ----------------------------------------------------------
function gcPointInPolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function gcWireLasso() {
  gcCanvas.addEventListener("pointerdown", (event) => {
    if (!event.shiftKey || event.button) return;
    const [x, y] = gcWorldPoint(event);
    if (gcNodeAtWorld(x, y)) return;
    gcLasso = { points: [[x, y]] };
    gcCanvas.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  gcCanvas.addEventListener("pointermove", (event) => {
    if (!gcLasso) return;
    gcLasso.points.push(gcWorldPoint(event));
    gcRequestDraw();
  });
  const finish = (event) => {
    if (!gcLasso) return;
    const points = gcLasso.points;
    gcLasso = null;
    try {
      gcCanvas.releasePointerCapture(event.pointerId);
    } catch {
    }
    if (points.length > 2) {
      const caught = gcNodes.filter((n) => !n.isGroup && gcPointInPolygon(n.x, n.y, points)).map((n) => n.id);
      // A second Shift-lasso adds to the first, so two sweeps build one selection.
      for (const id of caught) gcSelected.add(id);
    }
    gcSelectionChanged();
    gcRequestDraw();
  };
  gcCanvas.addEventListener("pointerup", finish);
  gcCanvas.addEventListener("pointercancel", finish);
}

function gcDrawSelection(ctx, k) {
  if (gcSelected.size) {
    ctx.save();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = gcTokens.accent;
    ctx.lineWidth = 3 / k;
    ctx.setLineDash([4 / k, 3 / k]);
    for (const node of gcNodes) {
      if (!gcSelected.has(node.id)) continue;
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r + 5 / k, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }
  if (gcLasso && gcLasso.points.length > 1) {
    ctx.save();
    ctx.beginPath();
    gcLasso.points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.fillStyle = gcTokens.accent;
    ctx.globalAlpha = 0.08;
    ctx.fill();
    ctx.globalAlpha = 0.9;
    ctx.strokeStyle = gcTokens.accent;
    ctx.lineWidth = 1.5 / k;
    ctx.setLineDash([6 / k, 4 / k]);
    ctx.stroke();
    ctx.restore();
  }
}

// --- Phase 4: the selection dock ---------------------------------------------------
function gcSelectionChanged() {
  const dock = document.getElementById("graph-selection-dock");
  const count = document.getElementById("graph-selection-count");
  if (!dock || !count) return;
  const live = [...gcSelected].filter((id) => gcById.has(id));
  gcSelected = new Set(live);
  dock.classList.toggle("hidden", !live.length);
  count.textContent = `${live.length} selected`;
}

function gcSelectedNodes() {
  return [...gcSelected].map((id) => gcById.get(id)).filter(Boolean);
}

function gcWireSelectionDock() {
  const on = (id, fn) => document.getElementById(id)?.addEventListener("click", fn);
  on("graph-selection-clear", () => {
    gcSelected.clear();
    gcSelectionChanged();
    gcRequestDraw();
  });
  on("graph-selection-tag", async () => {
    const nodes = gcSelectedNodes();
    if (!nodes.length) return;
    const tag = (await promptDialog("Tag these notes", "", { confirmLabel: "Add tag" })).trim().replace(/^#/, "");
    if (!tag) return;
    let done = 0;
    for (const node of nodes) {
      const tags = Array.from(new Set([...(node.tags || []), tag]));
      // PUT: the entries route has no PATCH, and EntryUpdate leaves every
      // field it is not given alone.
      const ok = await apiJson(`/entries/${node.id}`, { method: "PUT", body: JSON.stringify({ tags }) }).catch(() => null);
      if (ok) {
        node.tags = tags;
        done += 1;
      }
    }
    toast(`Tagged ${done} note${done === 1 ? "" : "s"} #${tag}.`);
    renderGraph();
  });
  on("graph-selection-link", async () => {
    const nodes = gcSelectedNodes();
    if (nodes.length < 2) {
      toast("Select at least two notes to link them.");
      return;
    }
    // Pairwise up to six notes (fifteen links); past that a hub, every note
    // linked to the first, which keeps the map readable.
    const pairs = [];
    if (nodes.length <= 6) {
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) pairs.push([nodes[i], nodes[j]]);
    } else {
      for (let i = 1; i < nodes.length; i++) pairs.push([nodes[0], nodes[i]]);
    }
    let made = 0;
    for (const [a, b] of pairs) {
      if (gcAdj.get(a.id)?.has(b.id)) continue;
      const ok = await apiJson(`/entries/${a.id}/links`, { method: "POST", body: JSON.stringify({ target_id: b.id }) }).catch(() => null);
      if (ok) made += 1;
    }
    toast(made ? `Linked ${made} pair${made === 1 ? "" : "s"}.` : "Those notes were already linked.");
    renderGraph();
  });
  on("graph-selection-map", async () => {
    const nodes = gcSelectedNodes();
    if (!nodes.length) return;
    const name = (await promptDialog("Name the mind map", "", { confirmLabel: "Create map" })).trim();
    if (!name) return;
    // "map" is the board type a mind map carries (BOARD_TYPES in
    // routes_whiteboard.py); "tree-right" is the layout a fresh map gets.
    const board = await apiJson("/whiteboard/boards", {
      method: "POST",
      body: JSON.stringify({ name, type: "map", layout: "tree-right" }),
    }).catch(() => null);
    if (!board?.id) {
      toast("Could not create the map.");
      return;
    }
    const root = await apiJson(`/whiteboard/boards/${board.id}/nodes`, { method: "POST", body: JSON.stringify({ kind: "topic", text: name }) }).catch(() => null);
    for (const node of nodes) {
      await apiJson(`/whiteboard/boards/${board.id}/nodes`, {
        method: "POST",
        body: JSON.stringify({ kind: "note", ref_id: node.id, parent_id: root?.id ?? null, text: node.preview || "" }),
      }).catch(() => null);
    }
    toast(`Mind map “${name}” made from ${nodes.length} note${nodes.length === 1 ? "" : "s"}. It is in Library, Boards.`);
  });
}

// --- Phase 4: the right-click menu ---------------------------------------------------
let gcNodeMenuEl = null;
function gcCloseNodeMenu() {
  if (gcNodeMenuEl) gcNodeMenuEl.remove();
  gcNodeMenuEl = null;
}

function gcWireNodeMenu() {
  gcCanvas.addEventListener("contextmenu", (event) => {
    const [x, y] = gcWorldPoint(event);
    const node = gcNodeAtWorld(x, y);
    if (!node || node.isGroup) return;
    event.preventDefault();
    gcShowNodeMenu(node, event.clientX, event.clientY);
  });
  document.addEventListener(
    "pointerdown",
    (event) => {
      if (gcNodeMenuEl && !gcNodeMenuEl.contains(event.target)) gcCloseNodeMenu();
    },
    true
  );
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && gcNodeMenuEl) gcCloseNodeMenu();
  });
  window.addEventListener("wheel", gcCloseNodeMenu, { passive: true });
}

function gcShowNodeMenu(node, clientX, clientY) {
  gcCloseNodeMenu();
  const menu = document.createElement("div");
  menu.className = "action-menu action-menu-escaped graph-node-menu";
  menu.setAttribute("role", "menu");
  const item = (icon, text, onPick) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "menu-item doc-dock-menu-item";
    button.setAttribute("role", "menuitem");
    setLabel(button, `${icon} ${text}`);
    button.addEventListener("click", () => {
      gcCloseNodeMenu();
      onPick();
    });
    menu.appendChild(button);
  };
  const isNote = node.type !== "entity" && node.type !== "document";
  if (isNote) item("ph:arrow-square-out", "Open", () => flashEntry(node.id));
  item(node.fx != null ? "ph:push-pin-slash" : "ph:push-pin", node.fx != null ? "Unpin" : "Pin in place", () => gcTogglePin(node));
  if (isNote) {
    item("ph:crosshair", "Focus on this note", () => {
      graphFocusModeId = node.id;
      renderGraph();
    });
  }
  const selected = gcSelected.has(node.id);
  item(selected ? "ph:selection-slash" : "ph:selection-plus", selected ? "Remove from selection" : "Add to selection", () => {
    if (gcSelected.has(node.id)) gcSelected.delete(node.id);
    else gcSelected.add(node.id);
    gcSelectionChanged();
    gcRequestDraw();
  });
  item("ph:eye-slash", "Hide on this map", () => {
    graphHiddenIds.add(node.id);
    gcSelected.delete(node.id);
    gcSelectionChanged();
    renderGraph();
  });
  document.body.appendChild(menu);
  gcNodeMenuEl = menu;
  const rect = menu.getBoundingClientRect();
  const left = Math.min(clientX, window.innerWidth - rect.width - 8);
  const top = Math.min(clientY, window.innerHeight - rect.height - 8);
  menu.style.position = "fixed";
  menu.style.left = `${Math.max(8, left)}px`;
  menu.style.top = `${Math.max(8, top)}px`;
  menu.querySelector("button")?.focus();
}

function gcTooltip(node) {
  const links = (gcAdj && gcAdj.get(node.id) ? gcAdj.get(node.id).size : 0) || 0;
  return (
    `${node.preview}\n[${node.category}] · ${links} connection${links === 1 ? "" : "s"}` +
    `${node.access_count ? ` · used ${node.access_count}×` : ""}`
  );
}

//: A click on a node, with the same three modes the SVG renderer had: trace
//: mode picks an end, an in-flight "Link" picks the other note, otherwise the
//: note opens in the popup.
function gcClickNode(event, node) {
  if (event && event.shiftKey && !node.isGroup) {
    if (gcSelected.has(node.id)) gcSelected.delete(node.id);
    else gcSelected.add(node.id);
    gcSelectionChanged();
    gcRequestDraw();
    return;
  }
  if (node.isGroup || node.type === "entity" || node.type === "document") return;
  if (traceModeActive) {
    pickTraceEnd(node);
    return;
  }
  if (typeof linkSource !== "undefined" && linkSource !== null) {
    beginOrCompleteLink(node);
    return;
  }
  openGraphPopup(event || { clientX: 0, clientY: 0, stopPropagation() {} }, node);
}

// --- the worker ------------------------------------------------------------------

function gcPost(message) {
  if (gcWorker) gcWorker.postMessage(message);
}

function gcStop() {
  gcPost({ type: "stop" });
}

function gcStartWorker(nodes, edges, world) {
  if (!gcWorker) {
    // Version-stamped for the same reason index.html's script tags are
    // (tests/test_asset_cache_busting.py): a desktop wrapper with its own
    // cache can otherwise go on running yesterday's worker forever, and a
    // stale worker is invisible, nothing logs, the map just behaves like the
    // build before last. The stamp is lifted off this file's own <script>
    // tag rather than kept in a second place that can drift from it.
    const own = document.querySelector('script[src*="graph-canvas.js"]');
    const stamp = ((own && own.getAttribute("src")) || "").split("?v=")[1] || "0";
    gcWorker = new Worker(`/graph-worker.js?v=${stamp}`);
    gcWorker.onmessage = (event) => {
      const message = event.data || {};
      //: A message from a simulation that no longer matches what is on screen
      //: is dropped whole, buffer included: handing a stale buffer back would
      //: decrement an `inFlight` count that the newer `init` has already
      //: reset, and the worker allocates a replacement for nothing worse than
      //: one skipped frame's worth of pool.
      if (message.epoch !== gcEpoch) return;
      if (message.type === "tick") {
        gcAlpha = message.alpha;
        gcTicks = message.ticks || 0;
        gcTickMs = message.tickMs || 0;
        const positions = message.positions;
        const count = Math.min(gcNodes.length, positions.length / 2);
        for (let i = 0; i < count; i++) {
          const node = gcNodes[i];
          // A node being dragged is authoritative on this side: its position
          // came from the pointer this frame and the worker's copy is one
          // message behind.
          if (node === gcDragNode) continue;
          node.x = positions[i * 2];
          node.y = positions[i * 2 + 1];
        }
        // The positions moved, so the hit-test index is stale. Marked here
        // rather than at the end of every draw: a settled map redraws on
        // hover without anything having moved, and rebuilding a 2,000-point
        // quadtree per pointermove for nothing is a millisecond a frame.
        gcQuadtreeDirty = true;
        gcRequestDraw();
        // **Framed twice: once straight away, once when it settles.**
        //
        // The SVG renderer framed the map exactly once, when the simulation
        // cooled below alpha 0.08, about 110 ticks. Measured on the 2,000-note
        // fixture in this sandbox, a tick costs ~80 ms, so that is nine seconds
        // of watching a graph whose notes are mostly outside the frame at
        // zoom 1, with no way to know that is what you are looking at. The
        // first tick is framed immediately instead, so the map is *visible*
        // from the first moment, and the settle re-frames it once the layout
        // has actually decided its shape.
        //
        // The second fit is skipped if the user has zoomed or panned in the
        // meantime: recentring the camera out from under someone who has
        // deliberately gone to look at something is the reported bug
        // `graphAutoFitDone` exists for, and an early fit must not reintroduce
        // it by making the late fit unconditional.
        if (!graphAutoFitDone && gcNodes.length) {
          if (!gcFittedOnce) {
            gcFittedOnce = true;
            fitGraphToView(graphSvg, null, graphZoom, gcNodes, gcDims.w, gcDims.h);
          } else if (message.alpha < 0.08) {
            graphAutoFitDone = true;
            if (!gcUserZoomed) {
              fitGraphToView(graphSvg, null, graphZoom, gcNodes, gcDims.w, gcDims.h);
            }
          }
        }
        // Hand the buffer back so the worker can reuse it (see its `pool`).
        gcWorker.postMessage({ type: "recycle", buffer: positions.buffer }, [positions.buffer]);
        graphMinimapTick += 1;
        if (graphMinimapTick % 8 === 0) graphMinimapPaint();
      } else if (message.type === "end") {
        graphMinimapPaint();
        if (!graphAutoFitDone && gcNodes.length) {
          graphAutoFitDone = true;
          fitGraphToView(graphSvg, null, graphZoom, gcNodes, gcDims.w, gcDims.h);
        }
      }
    };
    gcWorker.onerror = () => {
      // A worker that will not start must not take the map with it: the nodes
      // already have positions (inherited, pinned or spiral), so the canvas
      // still draws a static graph.
      gcRequestDraw();
    };
  }
  gcFittedOnce = false;
  gcPost({
    type: "init",
    epoch: gcEpoch,
    // Performance mode (settings.js): the physics yields twice as long
    // between ticks, half the CPU for a layout that converges a little later.
    perf: document.documentElement.dataset.perf === "on",
    nodes: nodes.map((n) => ({
      id: n.id,
      x: n.x,
      y: n.y,
      fx: n.fx == null ? null : n.fx,
      fy: n.fy == null ? null : n.fy,
      r: n.r,
    })),
    edges: edges.map((e) => ({
      source: e.source.id != null ? e.source.id : e.source,
      target: e.target.id != null ? e.target.id : e.target,
      kind: e.kind,
    })),
    params: {
      gravity: Number(localStorage.getItem("graph-gravity") || 50),
      spread: Number(localStorage.getItem("graph-spread") || 50),
    },
    world,
    alpha: 1,
  });
}

//: The world the simulation solves in, a square whose side grows with
//: sqrt(count). Carried over from the SVG renderer along with the reason it is
//: square and count-based rather than a multiple of the frame: a graph box is
//: wide and short, so multiplying the frame gave a few hundred pixels of
//: vertical room and the layout settled against the walls into a lattice,
//: reported as "the graph nodes are like locked into a box".
function gcWorldFor(count, width, height) {
  const perNode = 2 * (GC_MAX_RADIUS + 28);
  // 1.25, not 1.6. The world is the wall a reheated layout cannot push past,
  // and it was sized for a simulation whose span grew like sqrt(count) with
  // nothing holding it in; the worker now scales its repulsion and its centre
  // force by the note count (`densityScale`/`centreScale` in graph-worker.js),
  // so the natural spread is a good deal smaller than the room this used to
  // reserve and the gap between the two was somewhere a node could wander to
  // and be lost. Measured at 35 and 300 notes this changes nothing at all:
  // both are under the viewport floor below. It bites above about a thousand
  // notes, where it is reasoned rather than measured.
  const roomy = Math.sqrt(Math.max(count, 1)) * perNode * 1.25;
  const side = Math.max(roomy, width * 1.8, height * 1.8);
  return {
    left: (width - side) / 2,
    top: (height - side) / 2,
    right: (width - side) / 2 + side,
    bottom: (height - side) / 2 + side,
  };
}

// --- the render ------------------------------------------------------------------

//: The Canvas 2D renderer, behind the same `renderGraph()` entry, on the same
//: data, with the same ids and the same dock controls. Everything from the
//: fetch down to the stats line is the SVG renderer's own sequence: what
//: changes is that the drawing is a canvas and the simulation is a worker.
async function renderGraphCanvas() {
  if (!gcEnsureCanvas()) return;
  const sequence = ++gcRenderSeq;
  const wantSimilarity = document.getElementById("graph-similarity").checked;
  const wantEntities = document.getElementById("graph-entities")
    ? document.getElementById("graph-entities").checked
    : false;
  const wantDocuments = document.getElementById("graph-documents")
    ? document.getElementById("graph-documents").checked
    : false;
  const wantMaps = document.getElementById("graph-maps")
    ? document.getElementById("graph-maps").checked
    : false;
  const endpoint = graphFocusModeId
    ? `/graph/local/${graphFocusModeId}?depth=2&similarity=${wantSimilarity}`
    : `/graph?${wantSimilarity ? "similarity=true&" : ""}${wantEntities ? "include_entities=true&" : ""}${
        wantDocuments ? "include_documents=true&" : ""
      }${wantMaps ? "include_maps=true" : ""}`;
  const data = await apiJson(endpoint).catch(() => null);
  if (!data) return;
  // A slow answer that has been overtaken by a newer render must not paint
  // over it. The SVG path had the same race and answered it by clearing the
  // SVG; a canvas has nothing to clear, so the sequence number is the guard.
  if (sequence !== gcRenderSeq) return;
  gcTiming = { dataAt: performance.now(), firstFrame: 0, lastFrame: 0, frames: 0 };
  // A fresh visit to the tab (`graphAutoFitDone` cleared by switchTab) is also
  // a fresh camera: forget that the last visit's viewer had zoomed somewhere.
  if (!graphAutoFitDone) gcUserZoomed = false;

  gcReadTokens();
  const empty = document.getElementById("graph-empty");
  empty.style.display = data.nodes.length > 0 ? "none" : "grid";
  empty.classList.toggle("hidden", data.nodes.length > 0);

  const colour = d3.scaleOrdinal(data.categories, d3.schemeTableau10.concat(d3.schemeSet3));
  const clusterColour = d3.scaleOrdinal(d3.schemeTableau10.concat(d3.schemeSet3));
  const colourMode = graphColourMode();
  graphStructure =
    colourMode === "cluster" ? await apiJson("/graph/structure").catch(() => null) : null;
  if (sequence !== gcRenderSeq) return;
  // GRAPH_PLAN Phase 3: the colour follows a rule, and a group (a saved
  // search) paints over the rule for the notes it matches.
  const groups = await graphResolveGroups();
  if (sequence !== gcRenderSeq) return;
  const ruleColour = gcRuleScale(colourMode, data);
  gcColourOf = (node) => {
    const groupIndex = graphGroupOf.get(node.id);
    if (groupIndex !== undefined && !node.isGroup) return graphGroupColour(groupIndex);
    if (node.isGroup) return colour(node.category);
    if (colourMode === "category") return colour(node.category);
    if (colourMode === "cluster") {
      if (!graphStructure) return colour(node.category);
      const cluster = graphStructure.cluster_of[String(node.id)];
      return cluster === undefined ? gcTokens.muted : clusterColour(String(cluster));
    }
    return ruleColour(gcRuleKey(colourMode, node));
  };
  graphRenderLegend(data, colourMode, colour, clusterColour, ruleColour, groups);
  gcSelectionChanged();

  const ruleHides = colourMode !== "category" && colourMode !== "cluster";
  let visibleNodes = data.nodes.filter(
    (n) =>
      !graphHiddenCategories.has(n.category) &&
      !graphHiddenIds.has(n.id) &&
      !(ruleHides && graphHiddenKeys.has(`${colourMode}:${gcRuleKey(colourMode, n)}`)) &&
      !(graphGroupOf.has(n.id) && groups[graphGroupOf.get(n.id)]?.hiddenOnMap)
  );
  const kept = new Set(visibleNodes.map((n) => n.id));
  const visibleEdges = data.edges.filter((e) => kept.has(e.source) && kept.has(e.target));
  const hideOrphans = document.getElementById("graph-hide-orphans");
  if (hideOrphans && hideOrphans.checked) {
    const connected = new Set();
    for (const edge of visibleEdges) {
      connected.add(edge.source);
      connected.add(edge.target);
    }
    visibleNodes = visibleNodes.filter((n) => connected.has(n.id));
  }
  if (!visibleNodes.length) {
    empty.style.display = "grid";
    empty.classList.remove("hidden");
    gcNodes = [];
    gcEdges = [];
    gcAdj = new Map();
    gcById = new Map();
    graphNodesRef = gcNodes;
    gcStop();
    gcRequestDraw();
    return;
  }

  gcResize();
  const width = gcDims.w;
  const height = gcDims.h;
  gcLayoutKind = graphLayout();
  gcTree =
    gcLayoutKind === "force"
      ? null
      : layoutHierarchy(visibleNodes.map((n) => ({ ...n })), gcLayoutKind, width, height);

  // A note already on screen keeps the spot it had settled into, so a legend
  // toggle or a slider change does not replay the whole "explode outward"
  // animation. Same inheritance the SVG renderer does, and for the same
  // reported reason.
  const prior = new Map((graphNodesRef || []).map((n) => [n.id, { x: n.x, y: n.y }]));
  const nodes = gcTree
    ? gcTree.nodes
    : visibleNodes.map((n) => {
        const was = prior.get(n.id);
        const built = was && Number.isFinite(was.x) ? { ...n, ...was } : { ...n };
        if (built.graph_pin_x != null && built.graph_pin_y != null) {
          built.fx = built.graph_pin_x;
          built.fy = built.graph_pin_y;
        }
        return built;
      });
  const edges = gcTree ? gcTree.links : visibleEdges.map((e) => ({ ...e }));

  gcById = new Map(nodes.map((n) => [n.id, n]));
  gcAdj = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const edge of edges) {
    const from = edge.source && edge.source.id != null ? edge.source.id : edge.source;
    const to = edge.target && edge.target.id != null ? edge.target.id : edge.target;
    if (gcAdj.has(from)) gcAdj.get(from).add(to);
    if (gcAdj.has(to)) gcAdj.get(to).add(from);
    // Resolve to the node objects once, here, rather than on every frame.
    edge.source = gcById.get(from) || edge.source;
    edge.target = gcById.get(to) || edge.target;
    edge._path2d = null;
  }
  for (const node of nodes) {
    node.r = gcRadius(node, (gcAdj.get(node.id) || { size: 0 }).size);
    node.colour = gcColourOf(node);
  }
  //: **A note with no position yet is placed here, not in the worker.**
  //: d3-force assigns its phyllotaxis spiral inside `forceSimulation`, which
  //: means the main thread has no positions at all until the first tick comes
  //: back: so the frame drawn the instant the payload arrives would be an
  //: empty canvas, and the gate's "first frame after data" would be timing a
  //: blank. The same spiral is laid down here (identical constants, so the
  //: worker keeps these rather than re-placing anything) and the first frame
  //: is a real picture of the notebook that then relaxes into its layout.
  if (!gcTree) {
    const centreX = width / 2;
    const centreY = height / 2;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    nodes.forEach((node, index) => {
      if (Number.isFinite(node.x) && Number.isFinite(node.y)) return;
      const radius = 10 * Math.sqrt(0.5 + index);
      const angle = index * goldenAngle;
      node.x = centreX + radius * Math.cos(angle);
      node.y = centreY + radius * Math.sin(angle);
    });
  }
  // Everything the worker could still be about is now gone: whatever it says
  // next is about the previous node array and is dropped on arrival.
  gcEpoch += 1;
  gcNodes = nodes;
  gcEdges = edges;
  graphNodesRef = nodes;
  graphAdjacency = gcAdj;
  gcQuadtreeDirty = true;

  initGraphMinimap();
  initGraphViews();

  if (gcTree) {
    gcStop();
    if (!graphAutoFitDone) {
      graphAutoFitDone = true;
      frameTree(graphSvg, graphZoom, null, nodes, width, height, gcTree.radial);
    }
  } else {
    gcStartWorker(nodes, edges, gcWorldFor(nodes.length, width, height));
  }

  graphRenderStats(data, nodes, edges, colourMode, gcLayoutKind);
  graphSyncTimeSlider(data, (cutoff) => {
    gcTimeCutoff = cutoff;
    gcRequestDraw();
  });
  fillTracePickers(nodes);
  drawTrace();
  applyGraphHighlight();
  initGraphKeyboard();
  //: A full paint, because this is exactly the moment the dots are wrong: a
  //: different set of notes, at different places. A pan only ever moves the
  //: rectangle (`graphMinimapFrame`), so nothing else on that path repaints
  //: them, and the force layout's own repaint rides the worker's ticks, which
  //: a computed layout does not have at all.
  graphMinimapPaint();
  gcRequestDraw();
}

// --- the chrome around the drawing ------------------------------------------------
//
// The legend, the stats line and the time slider are the same controls on
// either renderer: they describe the data, not the drawing. They live here
// rather than in graph.js because this is the file that survives Phase 1: the
// SVG renderer keeps its own inline copies until it is deleted, and then there
// is one of each.

//: One entry per category (click to filter) or per cluster (click to
//: spotlight). A legend whose dots do not match the colours on screen is worse
//: than no legend, so which of the two it shows follows the colour mode.
//: The key a rule reads off a node, and the order its legend lists them in.
const GC_AGE_BUCKETS = ["Today", "This week", "This month", "This quarter", "Older"];
function gcRuleKey(rule, node) {
  if (rule === "kind") return node.kind || "note";
  if (rule === "space") return node.space_id || "default";
  if (rule === "tag") return (node.tags && node.tags[0]) || "No tag";
  if (rule === "file") return node.has_file ? "Has a file" : "No file";
  if (rule === "age") {
    const days = node.created_at ? (Date.now() - Date.parse(node.created_at)) / 86400000 : Infinity;
    if (days <= 1) return GC_AGE_BUCKETS[0];
    if (days <= 7) return GC_AGE_BUCKETS[1];
    if (days <= 30) return GC_AGE_BUCKETS[2];
    if (days <= 90) return GC_AGE_BUCKETS[3];
    return GC_AGE_BUCKETS[4];
  }
  return node.category;
}
function gcRuleDomain(rule, data) {
  if (rule === "age") return GC_AGE_BUCKETS;
  if (rule === "file") return ["Has a file", "No file"];
  const keys = new Set(data.nodes.filter((n) => !n.isGroup).map((n) => gcRuleKey(rule, n)));
  return [...keys].sort((a, b) => String(a).localeCompare(String(b)));
}
function gcRuleScale(rule, data) {
  if (rule === "age") return d3.scaleOrdinal(GC_AGE_BUCKETS, ["#2f80ed", "#56a3f5", "#8ec2f7", "#c3dcf7", "#9aa1ad"]);
  if (rule === "file") return d3.scaleOrdinal(["Has a file", "No file"], ["#17bebb", "#9aa1ad"]);
  return d3.scaleOrdinal(gcRuleDomain(rule, data), d3.schemeTableau10.concat(d3.schemeSet3));
}

function graphRenderLegend(data, colourMode, colour, clusterColour, ruleColour = null, groups = []) {
  const legend = document.getElementById("graph-legend");
  if (!legend) return;
  legend.replaceChildren();
  if (graphHiddenIds.size) {
    const hidden = document.createElement("button");
    hidden.className = "legend-item legend-toggle legend-off";
    hidden.title = "Show the notes hidden from this map again";
    hidden.textContent = `${graphHiddenIds.size} hidden on this map. Show`;
    hidden.addEventListener("click", () => {
      graphHiddenIds.clear();
      renderGraph();
    });
    legend.appendChild(hidden);
  }
  // Groups lead the legend whatever the rule: they paint over it.
  groups.forEach((group, index) => {
    const off = Boolean(group.hiddenOnMap);
    const item = document.createElement("button");
    item.className = "legend-item legend-toggle legend-group";
    item.title = off ? `Show the notes matching “${group.query}” again` : `Hide the notes matching “${group.query}”`;
    item.classList.toggle("legend-off", off);
    item.setAttribute("aria-pressed", String(!off));
    const dot = document.createElement("span");
    dot.className = "legend-dot";
    dot.style.background = graphGroupColour(index);
    const count = [...graphGroupOf.values()].filter((i) => i === index).length;
    item.append(dot, document.createTextNode(`${group.query} (${count})`));
    item.addEventListener("click", () => {
      const next = graphGroups();
      if (next[index]) next[index].hiddenOnMap = !next[index].hiddenOnMap;
      graphSetGroups(next);
    });
    legend.appendChild(item);
  });
  if (ruleColour && colourMode !== "category" && colourMode !== "cluster") {
    for (const key of gcRuleDomain(colourMode, data)) {
      const token = `${colourMode}:${key}`;
      const off = graphHiddenKeys.has(token);
      const item = document.createElement("button");
      item.className = "legend-item legend-toggle";
      item.title = off ? `Show ${key} again` : `Hide ${key} from the map`;
      item.classList.toggle("legend-off", off);
      item.setAttribute("aria-pressed", String(!off));
      const dot = document.createElement("span");
      dot.className = "legend-dot";
      dot.style.background = ruleColour(key);
      item.append(dot, document.createTextNode(String(key)));
      item.addEventListener("click", () => {
        if (graphHiddenKeys.has(token)) graphHiddenKeys.delete(token);
        else graphHiddenKeys.add(token);
        renderGraph();
      });
      legend.appendChild(item);
    }
    return;
  }
  const entry = (title, dotColour, text, onClick, off) => {
    const item = document.createElement("button");
    item.className = "legend-item legend-toggle";
    item.title = title;
    if (off !== undefined) {
      item.classList.toggle("legend-off", off);
      item.setAttribute("aria-pressed", String(!off));
    }
    const dot = document.createElement("span");
    dot.className = "legend-dot";
    dot.style.background = dotColour;
    item.append(dot, document.createTextNode(text));
    item.addEventListener("click", onClick);
    legend.appendChild(item);
    return item;
  };
  if (colourMode === "cluster" && graphStructure) {
    graphStructure.clusters.forEach((cluster, position) => {
      entry(
        `${cluster.size} notes, around "${cluster.core.preview}"` +
          (cluster.categories.length ? ` · ${cluster.categories.join(", ")}` : ""),
        clusterColour(String(position)),
        `${cluster.core.preview} (${cluster.size})`,
        () => {
          graphHighlightIds = new Set(cluster.ids);
          applyGraphHighlight();
        }
      );
    });
    if (graphStructure.orphan_count) {
      entry(
        "Notes with no link, no reply and no shared tag",
        gcTokens.muted,
        `unconnected (${graphStructure.orphan_count})`,
        () => {
          graphHighlightIds = new Set(graphStructure.orphans.map((n) => n.id));
          applyGraphHighlight();
        }
      );
    }
    if (graphHiddenCategories.size) {
      // The category filters still apply in this mode, they just have no
      // controls. Saying so beats a map quietly missing notes.
      const note = document.createElement("span");
      note.className = "legend-item";
      note.textContent = `${graphHiddenCategories.size} category filter${
        graphHiddenCategories.size === 1 ? "" : "s"
      } still on: switch to “By category” to change them`;
      legend.appendChild(note);
    }
    return;
  }
  for (const category of data.categories) {
    const off = graphHiddenCategories.has(category);
    entry(
      off ? `Show ${category} again` : `Hide ${category} from the map`,
      colour(category),
      category,
      () => {
        if (graphHiddenCategories.has(category)) graphHiddenCategories.delete(category);
        else graphHiddenCategories.add(category);
        renderGraph();
      },
      off
    );
  }
}

//: A plain-language readout of what is on screen. The counts are facts about
//: this notebook and stay on the line; the sentence explaining how a layout
//: works is the same every time you read it, so it is the line's tooltip.
function graphRenderStats(data, nodes, edges, colourMode, layoutKind) {
  const line = document.getElementById("graph-stats");
  if (!line) return;
  const counts = { link: 0, thread: 0, similar: 0, filing: 0, map: 0 };
  for (const edge of edges) counts[edge.kind] = (counts[edge.kind] || 0) + 1;
  const noteCount = nodes.filter((n) => !n.isGroup).length;
  const parts = [`${noteCount} note${noteCount === 1 ? "" : "s"}`];
  if (counts.link) parts.push(`${counts.link} link${counts.link === 1 ? "" : "s"}`);
  if (counts.thread) parts.push(`${counts.thread} thread${counts.thread === 1 ? "" : "s"}`);
  if (counts.similar)
    parts.push(`${counts.similar} similarity line${counts.similar === 1 ? "" : "s"}`);
  if (counts.filing) parts.push(`${counts.filing} filed under a category`);
  if (counts.map) parts.push(`${counts.map} on a mind map`);
  const shape =
    colourMode === "cluster" && graphStructure
      ? `${graphStructure.clusters.length} cluster${
          graphStructure.clusters.length === 1 ? "" : "s"
        }` +
        (graphStructure.small_clusters
          ? ` + ${graphStructure.small_clusters} pair${
              graphStructure.small_clusters === 1 ? "" : "s"
            }`
          : "") +
        `, ${graphStructure.orphan_count} connected to nothing.`
      : layoutKind === "tree"
        ? "filed left to right; replies branch off the note they answer."
        : layoutKind === "radial"
          ? "categories around the centre; replies branch off the note they answer."
          : layoutKind === "arc"
            ? "one line, filed left to right; arcs below show what answers what."
            : "";
  line.textContent = parts.join(" · ");
  line.title = shape;
}

//: The time slider's bounds, recomputed every render. They used to be computed
//: once behind a flag that never reset, so any note created after the first
//: render sat beyond the slider's own "all time" end and stayed permanently
//: hidden once the filter had run. The guard below keeps what the user was
//: actually doing with it: parked at the end, or deliberately looking at an
//: earlier cut-off.
function graphSyncTimeSlider(data, apply) {
  const slider = document.getElementById("graph-time-slider");
  const label = document.getElementById("graph-time-label");
  if (!slider || !data.nodes.length) return;
  const stamps = data.nodes
    .map((n) => new Date(n.created_at || Date.now()).getTime())
    .filter(Number.isFinite);
  const min = stamps.length ? Math.min(...stamps) : Date.now();
  const max = stamps.length ? Math.max(...stamps) : Date.now();
  const previousMax = Number(slider.max);
  const wasAtEnd = !slider.dataset.graphInit || Number(slider.value) >= previousMax;
  slider.min = min;
  slider.max = max;
  slider.step = (max - min) / 100 || 1;
  slider.value = wasAtEnd ? max : Math.min(Number(slider.value), max);
  slider.dataset.graphInit = "1";
  const say = (value) => {
    if (!label) return;
    label.textContent =
      value >= max ? "All time" : `Up to ${new Date(value).toLocaleDateString()}`;
  };
  const set = (value) => {
    say(value);
    // `null` rather than the maximum when the slider is at its end: "no filter"
    // and "a cut-off that happens to be the newest note" are the same picture
    // but not the same state, and the debug surface reports which.
    apply(value >= max ? null : value);
  };
  slider.oninput = (event) => set(Number(event.target.value));
  say(Number(slider.value));
  set(Number(slider.value));
  graphWireTimePlay(slider, set);
}

// --- Phase 4: Play on the time slider --------------------------------------------------
//: Sweeps the cutoff from the first note to the last over about eight
//: seconds, so the notebook grows on screen in the order it was written.
//: A touch on the slider, or a second press, stops it where it is.
let gcTimePlayFrame = null;
function graphWireTimePlay(slider, set) {
  const button = document.getElementById("graph-time-play");
  if (!button || button._wired) return;
  button._wired = true;
  const setPlaying = (on) => {
    button.setAttribute("aria-pressed", String(on));
    button.title = on ? "Pause" : "Play through time";
    setLabel(button, on ? "ph:pause" : "ph:play");
  };
  const stop = () => {
    if (gcTimePlayFrame) cancelAnimationFrame(gcTimePlayFrame);
    gcTimePlayFrame = null;
    setPlaying(false);
  };
  button.addEventListener("click", () => {
    if (gcTimePlayFrame) {
      stop();
      return;
    }
    const min = Number(slider.min);
    const max = Number(slider.max);
    if (!(max > min)) return;
    const duration = 8000;
    const startValue = Number(slider.value) >= max ? min : Number(slider.value);
    const startAt = performance.now() - ((startValue - min) / (max - min)) * duration;
    setPlaying(true);
    const tick = (now) => {
      const value = Math.min(max, min + ((now - startAt) / duration) * (max - min));
      slider.value = value;
      set(value);
      if (value >= max) {
        stop();
        return;
      }
      gcTimePlayFrame = requestAnimationFrame(tick);
    };
    gcTimePlayFrame = requestAnimationFrame(tick);
  });
  slider.addEventListener("pointerdown", stop);
  setPlaying(false);
}

// --- the read-only debug surface -------------------------------------------------
//
//: `window.__graphDebug` exists so the gate script (scratchpad/ui-sweeps/
//: graph.js) can assert that a control changed *what is drawn* rather than
//: only that the control moved. It is deliberately a getter returning a frozen
//: snapshot: nothing outside this file can write to it, so it cannot become a
//: back door into the renderer's state, and reading it can never change what
//: the next frame draws.
Object.defineProperty(window, "__graphDebug", {
  configurable: false,
  get() {
    const t = gcTransform || { x: 0, y: 0, k: 1 };
    return Object.freeze({
      renderer: gcCanvas && !gcCanvas.classList.contains("hidden") ? "canvas" : "svg",
      nodes: gcNodes.length,
      edges: gcEdges.length,
      layout: gcLayoutKind,
      colourMode: typeof graphColourMode === "function" ? graphColourMode() : "category",
      transform: Object.freeze({ x: t.x, y: t.y, k: t.k }),
      hovered: graphHoveredId,
      focusModeId: graphFocusModeId,
      hiddenCategories: Object.freeze([...graphHiddenCategories]),
      timeCutoff: gcTimeCutoff,
      trace: graphTrace ? Object.freeze([...graphTrace.ids]) : null,
      highlight: graphHighlightIds ? graphHighlightIds.size : 0,
      alpha: gcAlpha,
      ticks: gcTicks,
      tickMs: gcTickMs,
      labelsWanted: gcLabelsWanted,
      labelsDrawn: gcLabelsDrawn,
      labelsPriority: gcLabelsPriority,
      // Capped: this is a debug read on every frame's worth of geometry, and
      // a 2,000-label frame would put a megabyte through the getter.
      labelBoxes: gcLabelBoxes.slice(0, 300).map((b) => Object.freeze({ ...b })),
      firstFrameMs: gcTiming.firstFrame,
      lastFrameMs: gcTiming.lastFrame,
      frames: gcTiming.frames,
      radii: Object.freeze(gcNodes.slice(0, 40).map((n) => n.r)),
      colours: Object.freeze(gcNodes.slice(0, 40).map((n) => n.colour)),
      positions: Object.freeze(
        gcNodes.slice(0, 40).map((n) => Object.freeze([Math.round(n.x), Math.round(n.y)]))
      ),
      // Enough geometry for a sweep to check the *shape* of a computed
      // layout rather than only that one was chosen: which node is where,
      // how deep the hierarchy put it, and where each edge's two ends are.
      // `positions` above cannot answer "does depth increase away from the
      // root" or "do two edges cross", which are the two questions the tree
      // report turns on. Capped like the labels, and for the same reason.
      nodeGeometry: Object.freeze(
        gcNodes.slice(0, 300).map((n) =>
          Object.freeze({
            id: n.id,
            x: Math.round(n.x * 10) / 10,
            y: Math.round(n.y * 10) / 10,
            r: n.r,
            depth: n.depth == null ? null : n.depth,
            group: Boolean(n.isGroup),
          })
        )
      ),
      edgeGeometry: Object.freeze(
        gcEdges.slice(0, 300).map((e) =>
          Object.freeze([
            Math.round(e.source.x * 10) / 10,
            Math.round(e.source.y * 10) / 10,
            Math.round(e.target.x * 10) / 10,
            Math.round(e.target.y * 10) / 10,
          ])
        )
      ),
    });
  },
});
