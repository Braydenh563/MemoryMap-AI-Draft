// MemoryMap AI: Graph view subsystem (extracted from app.js).
//
// This is the "Graph" tab: the Obsidian-style force-directed map, its
// alternate layouts (tree/radial/arc), path tracing between two notes,
// drag-to-link, cluster colouring, keyboard driving, the node-edit popup,
// and "grow the map" (§9, §41). D3 is vendored locally (frontend/vendor): 
// the offline rule allows no CDN.
//
// Loaded as a THIRD classic (non-module) <script> tag, BEFORE app.js: see
// index.html. That order is not arbitrary and not interchangeable with the
// whiteboard.js split that preceded this one: app.js's own top-level wiring
// (the "$(\"graph-similarity\").addEventListener(\"change\", renderGraph)"
// cluster, and half a dozen like it, popup close/save, new-note save, the
// resize handler) passes functions and reads `let`s defined below *as bare
// identifiers, evaluated the moment that line of app.js runs*, not inside a
// closure, not deferred to a later event. In the original single file this
// worked regardless of position because function declarations hoist across
// the whole script; split into two <script> tags, each tag is its own
// hoisting scope, so if app.js ran first those lines would throw
// `ReferenceError: renderGraph is not defined` and: because that is
// synchronous top-level script code, abort the rest of app.js's own wiring
// partway through, not just the graph feature. So this file has to have
// already run before app.js reaches that code, meaning this script tag comes
// first. (whiteboard.js has no such bare top-level references into this
// file or into app.js, everything it calls across files happens inside a
// function body: which is why it could stay ordered after app.js.)
//
// This file's own top-level code needs only `document` (for the Escape-key
// handler that closes an open trace) and literal constants, nothing here
// needs app.js or whiteboard.js to have run first. It does need `d3` from
// /vendor/d3.v7.min.js, which the existing script order already guarantees.
//
// Everything else here calls back into app.js's shared helpers (`$`, `api`,
// `apiJson`, `toast`, `confirmDialog`, `switchTab`, `renderInlineMarkdown`,
// `loadEntries`, and more) the same way whiteboard.js does: at runtime,
// inside a function body, by which point every script has loaded.

// --- graph view (Wave E) ----------------------------------------------------------
// An Obsidian-style force-directed map. D3 is vendored locally
// (frontend/vendor): the offline rule allows no CDN.

let graphSimulation = null; // stopped before every rebuild
let graphHiddenCategories = new Set(); // legend toggles (Wave M)
let graphNodeSelection = null; // live d3 selections, for search-highlight
let graphEdgeSelection = null;
let graphLabelSelection = null; // the label layer's per-node <g> wrappers
// Refs kept so the on-screen zoom buttons can drive the same behaviour as
// scroll-zoom, and hover-highlight can look up a node's neighbours.
let graphSvg = null;
let graphZoom = null;
let graphCanvas = null;
let graphNodesRef = null;
let graphMinimapTick = 0; // throttles minimap repaints during a cooling layout
//: Set by the renderer each time the map is built. Repositions the label
//: layer after it has been skipped while invisible, see the tick handler.
//: A no-op before the first render, so every caller can call it blind.
let graphCatchUpLabels = () => {};
let graphDims = { w: 0, h: 0 };
// Set once the camera has auto-framed the map for the tab's current visit,
// and cleared again by switchTab() on the next fresh entry, see the two
// uses below for why. `renderGraph()` alone can't tell "just opened the
// tab" from "a filter checkbox changed" apart; the caller has to say which.
let graphAutoFitDone = false;
let graphHoveredId = null; // node the pointer is over (spotlight its links)
let graphIsPanning = false; // an active pan/zoom drag, see zoomBehavior below
let graphAdjacency = null; // Map<id, Set<neighbourId>>
// The traced path is drawn in its own layer, above the edges and the nodes: a
// step can be a shared tag, which the map draws no edge for, so highlighting
// the existing lines would show a chain with holes in it (§9).
let graphTraceLayer = null;

// How much of a linked note's text a link chip shows. Long enough to know
// which note it is, short enough that four of them are a row rather than a
// paragraph: a chip is a signpost, and a signpost with a sentence on it is
// not a signpost. The full text is the chip's tooltip.
const LINK_CHIP_CHARS = 28;

// How much of a note the list shows before clamping it. Roughly ten lines at
// a comfortable reading width, long enough that a normal note is never
// clipped, short enough that one essay can't take the whole screen.
const LONG_NOTE_CHARS = 500;
const LONG_NOTE_LINES = 10;
// Which notes the user has opened out, for this session. Not persisted: it is
// a reading position, not a preference.
const expandedNotes = new Set();

// The character count decides which notes *might* be too tall; only a
// measurement can say whether one actually is, because that depends on the
// width it is rendered at. So the clamp goes on optimistically and this takes
// it back off wherever the note fits after all, a "Show more" on a note that
// is fully visible is worse than no clamping at all.
//
// It bails when the list is off screen: this renders inside a `display: none`
// sub-tab, where every measurement is 0. `showNotesSection` calls it again on
// the way in, which is the moment the numbers become real.
function settleNoteClamps() {
  const list = $("entry-list");
  if (!list || !list.offsetParent) return;
  for (const content of list.querySelectorAll(".entry-content.entry-clamped")) {
    const toggle = content.parentElement?.querySelector(".entry-more");
    if (content.scrollHeight <= content.clientHeight + 4) {
      content.classList.remove("entry-clamped");
      toggle?.remove();
    }
  }
}

//: The largest a node can get, from `graphNodeRadius` below: its 9px base
//: plus the 12px ceiling on the centrality bonus (the access bonus caps
//: lower, and `Math.max` takes one or the other, never both). Named because
//: the world-size calculation needs to reserve room for the worst case
//: rather than the average, and a literal there would drift the moment
//: either cap below changed.
const GRAPH_NODE_MAX_RADIUS = 21;

function graphNodeRadius(node) {
  //: The canvas renderer sizes a node by its *degree* (GRAPH_PLAN.md §5 Phase
  //: 1: `4 + 2·√degree`, clamped) and stores the answer on the node, because
  //: degree is the one thing about a graph a reader can check by looking. Every
  //: caller that only needs "how big is this dot", `fitGraphToView`,
  //: `graphNodeUnder`, the minimap: then gets the right number on either
  //: renderer without knowing which one drew it.
  if (node.r != null) return node.r;
  // A category heading in a tree layout is a fixed size, it has no access
  // count of its own, and sizing it by one would be inventing a number.
  if (node.isGroup) return node.id === "root" ? 14 : 11;
  
  // Sized dynamically based on PageRank centrality (hub importance) and usage.
  // This physically represents the most important notes in the Knowledge Graph.
  const centralityBonus = node.centrality ? Math.min(12, node.centrality * 800) : 0;
  const accessBonus = Math.min(6, Math.sqrt(node.access_count || 0) * 1.5);
  
  return 9 + Math.max(centralityBonus, accessBonus);
}

// --- graph layouts (§9) -----------------------------------------------------------
//
// Asked for directly: "can you add different types of graph views… like tree
// graph diagrams and the like". A layout decides *where* a note goes; the
// styling is a separate question. Force is the default because it shows the
// links; the trees are here because most notebooks have far more filing than
// links, and a force graph of mostly-unlinked notes is a cloud of dots.
//
// The hierarchy is real data, not an invention: notebook → category → note,
// with a note's replies (`parent_id`, the train-of-thought threads) nested
// under the note they answer, so a thread reads as one branch.

function graphLayout() {
  const saved = localStorage.getItem("graph-layout");
  return ["force", "tree", "radial", "arc"].includes(saved) ? saved : "force";
}

//: **Tree, Radial and Arc compute every position, so nothing in them moves.**
//: Reported on 2026-09-09: "on the other graph view types, they all have the
//: dotted border as they are static but that shouldnt be the case ... I was
//: on the tree graph, I test double clicked on a node and it broke them all
//: out of position."
//:
//: Both halves have the same cause. A computed layout holds its nodes by
//: setting `fx`/`fy` on every one of them, and `fx != null` is exactly the
//: test the held ring and the pin toggle read: so every node in a tree wore
//: the ring that means "you pinned this", and a double click cleared one
//: node's `fx`, handing it back to the force simulation, which re-solved from
//: there and pulled the whole tree apart.
//:
//: The decision, and it is the one the layouts already imply: a computed
//: layout is read-only for position. The shape is the meaning in a tree, a
//: ring or an arc, and a node dragged out of it makes the picture a lie. So
//: no ring, no drag, no double-click pin here. Pan, zoom, hover, select and
//: the node menu are untouched: nothing that reads the graph is lost, only
//: the two gestures that would rearrange a layout the app arranged.
function graphLayoutIsComputed() {
  return graphLayout() !== "force";
}

// Gravity and Spread scale the force simulation, and the tree layouts do not
// run one: their positions come from the hierarchy. Left enabled they are two
// controls that move, save, and change nothing, which reads as a broken app
// rather than an inapplicable setting. Disabled, with the reason on hover.
function setGraphPhysicsEnabled(layoutKind) {
  const applies = layoutKind === "force";
  const box = $("graph-physics");
  if (!box) return;
  const why = applies
    ? ""
    : "Only applies to the Force (web) layout: the other layouts' positions come from the filing hierarchy, not physics.";
  box.classList.toggle("is-disabled", !applies);
  for (const id of ["graph-gravity", "graph-spread"]) {
    const slider = $(id);
    if (!slider) continue;
    slider.disabled = !applies;
    // Restore the slider's own description when it applies again, rather than
    // leaving the explanation of why it did not.
    if (applies) {
      slider.title =
        id === "graph-gravity"
          ? "How strongly notes pull together"
          : "How far apart linked notes sit";
    } else {
      slider.title = why;
    }
  }
  // The labels are separate elements, so they need the attribute too or the
  // hover explanation is missing on exactly the words being greyed out.
  for (const label of box.querySelectorAll("label")) {
    label.title = why;
  }
}

// A category level in a tree layout. It is a real node in the drawing so the
// join, the colours and the labels all work unchanged, but it is not a note,
// so anything that would open or edit one has to check.
function graphGroupNode(category) {
  return {
    id: `group:${category}`,
    isGroup: true,
    preview: category,
    category,
    access_count: 0,
    pinned: false,
  };
}

// Row height and column width for the tree. Fixed sizes, not a bounding box:
// `d3.tree().size([...])` squeezes every leaf into the panel's height, so a
// notebook with 29 notes got 18 pixels a row and the labels printed on top of
// each other (reported with a photo). `nodeSize` gives each note the room a
// label needs and lets the tree be as tall as it is, the panel pans and
// zooms, which is what those controls are for.
const TREE_ROW = 34;
const TREE_COL = 235;

// The radial is the opposite problem: it is a shape you read whole, so it has
// to fit the panel, and a fixed radius meant a 29-note notebook was drawn at
// 0.55×: every label technically present and none of them readable. Size the
// rings from the panel instead, and only grow past it when the notes need the
// circumference (below ~RADIAL_ARC pixels of arc each, labels collide).
const RADIAL_ARC = 22; // arc length a note needs on its ring
const RADIAL_LABEL = 118; // room the labels take outside the outermost ring
// A category name is written along its spoke, pointing out, so its ring has
// to clear the notes' ring by more than that name is long.
const RADIAL_GAP = 82;
// A reply hangs one shorter step outside the note it answers, and since a
// lone reply inherits its parent's angle exactly, the parent's label is
// written straight down the same spoke. That is why an intermediate note is
// labelled shorter than a leaf (RADIAL_STEM below): the step has to clear it.
const REPLY_RING = 78;
const RADIAL_STEM = 10; // characters, for a label written down a shared spoke

// The arc layout (§9's third hierarchy view, beside tree and radial): every
// node, category, note and reply alike, sits on one baseline, in the same
// left-to-right order a depth-first walk of the filing hierarchy would print
// them in (so a category's notes stay contiguous), and a parent-child edge is
// a shallow arc under the line instead of a tree's elbow or a radial's ring.
// It reads at a glance what tree/radial cannot: how many branches a
// notebook's filing has and how deep any one of them runs, in the width of a
// single row rather than the height of a tree or the footprint of a circle.
const ARC_STEP = 58; // horizontal spacing per node
// Reported directly, with a screenshot: a label's text was long enough, at a
// 46px step and a 40° tilt, to run its own end into the *next* node's slot: 
// read as "the label is attached to the wrong node". At ARC_STEP's old value,
// 20 chars * ~6.5px/char * cos(40°) was ~100px of horizontal travel, more
// than two node-steps. Shortened here, and the step above widened and the
// tilt below steepened, so a label's horizontal reach stays under one step.
const ARC_LABEL_LIMIT = 12; // characters: diagonal labels have less room before they cross the next node's arc

// Labels on the left half of the circle would read upside down, so they are
// turned around: which swaps which way "outward" is for everything after.
function radialFlip(node) {
  const degrees = ((node.angle || 0) * 180) / Math.PI - 90;
  return degrees > 90 || degrees < -90;
}

// Where each ring goes. Every constraint here is a thing that was measured
// going wrong: categories too tight to name, notes too tight to label, the
// whole circle too big for the panel, or, just as bad, needlessly small in
// a panel with room to spare.
function radialRings(leafCount, groupCount, rings, width, height) {
  // The floor matters as much as the arc: a dozen categories all radiating
  // from a 58px ring read as one blob at the centre, whatever the maths said
  // about them technically not touching. It grows with the count, because
  // four categories on that same ring only look sparse.
  const inner = Math.max((groupCount * RADIAL_ARC) / (2 * Math.PI), 40 + groupCount * 3);
  const room = Math.max(Math.min(width, height) / 2 - 12, 130) - RADIAL_LABEL;
  const extra = rings > 2 ? REPLY_RING : 0;
  const notes = Math.max(
    (leafCount * RADIAL_ARC) / (2 * Math.PI),
    inner + RADIAL_GAP,
    // Fill the panel when it is bigger than the minimum, a readable circle
    // is a big one. `frameTree` zooms out when the minimum wins instead.
    Math.min(room - extra, 320)
  );
  return { inner, notes, outer: notes + extra };
}

function layoutHierarchy(nodes, kind, width, height) {
  // Build parent → children from the notes themselves.
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const groups = new Map();
  for (const node of nodes) {
    if (!groups.has(node.category)) groups.set(node.category, graphGroupNode(node.category));
  }
  const root = { id: "root", isGroup: true, preview: "Notebook", category: "", access_count: 0 };
  const children = new Map([[root.id, [...groups.values()]]]);
  for (const group of groups.values()) children.set(group.id, []);
  for (const node of nodes) {
    // A reply hangs off the note it answers, wherever that note is filed, 
    // splitting a thread across categories would lose the thing it is.
    const parent =
      node.parent_id != null && byId.has(node.parent_id)
        ? byId.get(node.parent_id)
        : groups.get(node.category);
    if (!children.has(node.id)) children.set(node.id, []);
    children.get(parent.id).push(node);
  }

  const laid = d3.hierarchy(root, (d) => children.get(d.id) || []);
  const radial = kind === "radial";
  const arc = kind === "arc";
  if (arc) {
    // Pre-order: a category is visited before any of its notes, and each
    // note before its own replies, so walking the hierarchy in this order
    // and handing out one baseline slot per stop keeps every branch
    // contiguous, the same property `separation` gives the tree and radial
    // layouts a different way.
    let slot = 0;
    laid.eachBefore((point) => {
      point.x = slot * ARC_STEP;
      point.y = 0;
      slot += 1;
    });
  } else if (radial) {
    // `d3.tree`, not `d3.cluster`: cluster rings a node by its *height*, so a
    // category that happened to contain a thread was drawn one ring closer in
    // than its siblings and the circle came out ragged. Here a ring means a
    // depth, notebook, category, note, reply, which is what the view says
    // it means.
    d3
      .tree()
      .size([2 * Math.PI, 1])
      // Notes under different categories need more air than siblings, and the
      // gap has to shrink as the circle grows, the standard radial rule.
      // Categories get a wedge of their own on top of that, or the ones with
      // a single note in them end up sharing a slot with their neighbour.
      .separation((a, b) =>
        a.depth === 1 ? 2 : (a.parent === b.parent ? 1 : 2) / a.depth
      )(laid);
    const rings = radialRings(
      // Those wedges are real circumference, so count them: sizing the ring
      // off the notes alone would under-measure it by a third.
      (laid.leaves().length || 1) + groups.size,
      groups.size,
      laid.height || 1,
      width,
      height
    );
    const deep = Math.max((laid.height || 1) - 2, 1);
    laid.each((point) => {
      if (!point.depth) point.y = 0;
      else if (point.depth === 1) point.y = rings.inner;
      else {
        point.y = rings.notes + ((point.depth - 2) / deep) * (rings.outer - rings.notes);
      }
    });
  } else {
    d3.tree().nodeSize([TREE_ROW, TREE_COL])(laid);
  }

  const placed = [];
  const links = [];
  laid.each((point) => {
    const node = point.data;
    if (radial) {
      // d3's radial convention: x is the angle, y the distance out.
      node.angle = point.x;
      node.radius = point.y;
      node.x = point.y * Math.cos(point.x - Math.PI / 2);
      node.y = point.y * Math.sin(point.x - Math.PI / 2);
    } else if (arc) {
      // Already the real coordinates, assigned above, once, in traversal
      // order, and never touched again.
      node.x = point.x;
      node.y = point.y;
    } else {
      node.x = point.y; // depth runs left → right
      node.y = point.x;
    }
    node.fx = node.x;
    node.fy = node.y;
    node.depth = point.depth;
    node.isLeaf = !point.children;
    // A lone child inherits its parent's row (or, on the radial, its angle),
    // so the parent's label is written straight down the line joining them.
    // Only *that* parent has to keep its label short.
    node.shared = Boolean(point.children?.some((child) => child.x === point.x));
    placed.push(node);
    if (point.parent) {
      links.push({
        source: point.parent.data,
        target: node,
        kind: node.parent_id != null ? "thread" : "filing",
      });
    }
  });
  return { nodes: placed, links, radial, arc };
}

// A tree drawn with straight diagonals reads as a fan of loose string. Elbows
// (horizontal out, vertical across, horizontal in) are what makes it look
// like a tree diagram, and on the radial one, arcs that follow the rings.
function hierarchyPath(link, radial) {
  const { source: a, target: b } = link;
  if (radial) {
    return d3
      .linkRadial()
      .angle((d) => d.angle)
      .radius((d) => d.radius)({ source: a, target: b });
  }
  const mid = (a.x + b.x) / 2;
  return `M${a.x},${a.y}C${mid},${a.y} ${mid},${b.y} ${b.x},${b.y}`;
}

// The arc layout's own edge shape: every node sits on the same baseline (see
// `layoutHierarchy`'s `arc` branch), so a parent-child edge is a flattened
// half-ellipse dipping below the line rather than a tree's elbow or a
// radial's ring-following curve. A pre-order walk always visits a parent
// before its children, so `a.x < b.x` here always: the arc only ever needs
// to sweep one way.
function arcPath(link) {
  const { source: a, target: b } = link;
  const rx = Math.max((b.x - a.x) / 2, 1);
  const ry = rx * 0.6; // flatter than a true semicircle, a full one over a
  // long span dominates the map more than the connection it is drawing.
  return `M${a.x},${a.y}A${rx},${ry} 0 0,1 ${b.x},${b.y}`;
}

// A tall tree does not want to be squeezed into the panel: zoomed to fit, 29
// rows of text become illegible. Fit the *width*, never magnify past 1:1, and
// start at the top, the panel pans, and a readable tree you scroll beats a
// complete one you can't read.
function frameTree(svg, zoomBehavior, canvas, nodes, width, height, radial) {
  // Labels stick out past the node they belong to: to the right in a tree, in
  // every direction on a radial, and by however much the longest one happens
  // to be. Guessing that with a padding constant left label tips off the edge
  // of the panel; the drawing is already in the DOM, so ask it. `getBBox` is
  // in the canvas's own coordinates, the zoom transform is not applied yet , 
  // and covers the rotated labels' real corners.
  // `getBBox` is an SVG method: on the canvas renderer there is no element to
  // ask, and `canvas` arrives null. The zero-width fallback below is the same
  // path a hidden panel already took, so both cases are handled by the code
  // that was already here rather than by a second branch.
  const drawn =
    canvas && canvas.node() && canvas.node().getBBox ? canvas.node().getBBox() : { width: 0 };
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  // A hidden panel measures zero, so fall back to the node positions.
  const box = drawn.width
    ? drawn
    : {
        x: Math.min(...xs) - 40,
        y: Math.min(...ys) - 30,
        width: Math.max(...xs) - Math.min(...xs) + 200,
        height: Math.max(...ys) - Math.min(...ys) + 60,
      };
  const minX = box.x - 10;
  const maxX = box.x + box.width + 10;
  const minY = box.y - 10;
  const maxY = box.y + box.height + 10;
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  // A radial is a shape you read whole, so both dimensions have to fit. A
  // tree grows downwards without limit, so squeezing it into the panel is
  // exactly what made 29 rows unreadable, but a notebook that *nearly* fits
  // is worth a small zoom-out to see whole, and only falls back to panning
  // when the price of fitting would be text you can't read.
  const both = Math.min((width - 20) / spanX, (height - 20) / spanY);
  const fit = radial || both >= 0.8 ? both : (width - 20) / spanX;
  const scale = Math.max(0.35, Math.min(1, fit));
  // Same rule on both axes: centre what fits, otherwise anchor to the start
  // so the root is the part you can see.
  const tx =
    spanX * scale <= width - 20
      ? width / 2 - scale * (minX + maxX) / 2
      : 10 - scale * minX;
  // Centre vertically only when the whole thing already fits; otherwise start
  // at the top, because a tree is read from its root down.
  const ty =
    spanY * scale <= height - 20
      ? height / 2 - scale * (minY + maxY) / 2
      : 10 - scale * minY;
  svg
    .transition()
    .duration(400)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

// --- tracing a path between two notes (§9) -----------------------------------
//
// The question a graph answers better than any list, *how are these two
// related?*: and the one this view could not answer at all. Everything above
// shows you **that** notes connect; this shows you the route, and names each
// step: a link somebody made, a reply, or a tag the two share.
//
// The search itself is on the server (`entry/paths.py`, `GET /graph/path`) and
// is shared with the AI's `path_between` tool, deliberately: a picture and an
// answer that disagree about what is connected is worse than either alone.

//: The traced path, or null. `{ ids: [...], steps: [...] }`, ids in order, so
//: the drawing can look up consecutive pairs without re-deriving them.
let graphTrace = null;
//: The overlay lines, kept so the force simulation's tick can move them with
//: the nodes they join.
let graphTraceLines = null;

//: **Every route between the two notes, best first, and which one is showing.**
//: Asked for directly: "allow for multiple paths to be displayed if they
//: exist." `/graph/path` now returns `routes: [...]` alongside the best one it
//: always returned, so `graphTrace` above keeps meaning "the route currently
//: being read" and nothing that already depended on it had to change.
//:
//: The map draws *all* of them at once, each in its own colour, with the
//: selected one solid and the rest ghosted, because the answer to "is that the
//: only way these connect?" is a picture, and switching between routes one at a
//: time never shows you that there are three.
let graphTraceRoutes = [];
let graphTraceIndex = 0;

// The two pickers, filled from whatever the map is currently showing. Rebuilt
// on every render because the map's contents change: and the selection is
// carried across, since a rebuild that silently forgets which notes you were
// asking about is a control that undoes your work.
let traceModeActive = false;
let traceFromNode = null;
let traceToNode = null;

// The graph was redrawn, so the two picked nodes are stale objects from the
// previous layout. Re-point them at the new ones by id, dropping them instead
// would mean a filter change silently threw away the trace you were reading.
function fillTracePickers(nodes) {
  const byId = new Map(nodes.map((n) => [String(n.id), n]));
  if (traceFromNode) traceFromNode = byId.get(String(traceFromNode.id)) || null;
  if (traceToNode) traceToNode = byId.get(String(traceToNode.id)) || null;
  renderTraceState();
}

function setTracePanelOpen(open) {
  traceModeActive = open;
  if (!open) clearTrace({ quiet: true });
  $("graph-trace").classList.toggle("hidden", !open);
  $("graph-trace-toggle")?.setAttribute("aria-expanded", String(open));
  $("graph-trace-toggle")?.classList.toggle("is-on", open);
  // A mode has to look like one. Without this the map behaves differently
  // from a moment ago with nothing on screen saying so, which is the
  // difference between a tool and a glitch: the cursor becomes a crosshair
  // over the nodes and the graph card picks up a tinted edge.
  $("graph-card")?.classList.toggle("is-tracing", open);
  localStorage.setItem("graph-trace-open", open ? "1" : "0");
  if (open) {
    renderTraceState();
    // Re-opening the panel: most commonly by coming back to the Graph tab
    // after clicking a note in the trace path's own readout, which jumps to
    // the Notes tab (flashEntry) and left the panel "open" in localStorage: 
    // used to unconditionally overwrite #graph-trace-result with the opening
    // prompt, discarding a trace someone had already run (reported: "trace
    // resets when a note hyperlink in the trace path is clicked on"). Show
    // whatever's actually true instead of always restarting the script.
    if (!traceFromNode) {
      showTraceMessage("Click a note to start.");
    } else if (!traceToNode) {
      showTraceMessage("Click where to end.");
    } else if (graphTrace) {
      renderTraceReadout({ ...graphTrace, hops: graphTrace.steps.length });
    }
    // else: both ends picked but no result yet, a trace is mid-flight,
    // leave whatever runTrace() last wrote (e.g. "Tracing…") alone.
  }
}

// Escape leaves the mode. A mode you can only leave by finding the button
// that started it is a trap, and this one changes what clicking does.
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !traceModeActive) return;
  // Any *visible* overlay, not merely a present one, and `querySelectorAll`,
  // not `querySelector`. Nine `.modal-overlay` elements sit in the markup
  // permanently with `.hidden` on them, so asking for the first one matched a
  // hidden element every time and Escape appeared to do nothing; asking
  // whether *the first* is visible would then miss a dialog further down the
  // document. Escape belongs to whatever is on top of the trace panel.
  const overlays = [...document.querySelectorAll(".modal-overlay, .confirm-overlay")];
  if (overlays.some((el) => !el.classList.contains("hidden"))) return;
  setTracePanelOpen(false);
});

// --- Trace, redesigned (§41) ------------------------------------------------------
//
// Reported as "annoying and pretty much unusable", and it was, for one reason
// that made everything else about it worse: **the map did not respond.**
// `traceModeActive` was set and consulted nowhere, so picking the two ends
// meant using two `<select>` elements that listed every note in the notebook
// by its opening words. On any real notebook that is a scroll through hundreds
// of near-identical lines, to choose two notes that are visible on screen.
//
// It is a two-click mode now: turn Trace on, click a note, click another. The
// panel stops being a form and becomes a readout of where you are, which end
// you are choosing, what is chosen, and a way to swap or undo it. Escape
// leaves. The rules that make a mode bearable rather than a trap:
//
// - it always says what the next click will do (`renderTraceState`);
// - one click back: Undo removes the last end rather than resetting both;
// - Swap, because "actually, the other direction" is the commonest correction
//   and re-picking both to get it is the thing that made this infuriating;
// - clicking the same note twice is a no-op with a reason, not a silent
//   failure or a path from a note to itself.

function pickTraceEnd(node) {
  if (!node) return;
  if (traceFromNode && String(traceFromNode.id) === String(node.id)) {
    showTraceMessage("That's already the start, pick a different note to end at.");
    return;
  }
  if (!traceFromNode || traceToNode) {
    // Starting over: a third click begins a new trace rather than doing
    // nothing, which is what someone who has read the answer wants next.
    traceFromNode = node;
    traceToNode = null;
    graphTrace = null;
    drawTrace();
    applyGraphHighlight();
  } else {
    traceToNode = node;
  }
  renderTraceState();
  if (traceFromNode && traceToNode) runTrace();
}

function traceLabel(node) {
  const text = (node?.preview || "").trim();
  return text.length > 32 ? `${text.slice(0, 31)}…` : text || `note #${node?.id}`;
}

// The panel as a readout: what is chosen, what the next click does, and the
// two corrections worth having.
function renderTraceState() {
  const holder = $("graph-trace-ends");
  if (!holder) return;
  holder.replaceChildren();

  const chip = (node, role) => {
    const span = document.createElement("span");
    span.className = "trace-chip" + (node ? " is-set" : " is-empty");
    span.textContent = node ? traceLabel(node) : role;
    if (node) span.title = node.preview || "";
    return span;
  };

  const arrow = document.createElement("span");
  arrow.className = "graph-trace-arrow";
  arrow.textContent = "→";
  arrow.setAttribute("aria-hidden", "true");
  holder.append(chip(traceFromNode, "click a note to start"), arrow,
                chip(traceToNode, "then click where to end"));

  if (traceFromNode && traceToNode) {
    const swap = document.createElement("button");
    swap.type = "button";
    swap.className = "ghost small";
    setLabel(swap, "ph:arrows-left-right Swap");
    swap.title = "Trace the other way round";
    swap.addEventListener("click", () => {
      [traceFromNode, traceToNode] = [traceToNode, traceFromNode];
      renderTraceState();
      runTrace();
    });
    holder.appendChild(swap);
  }
  if (traceFromNode) {
    const back = document.createElement("button");
    back.type = "button";
    back.className = "ghost small";
    setLabel(back, "ph:arrow-u-up-left Undo");
    back.title = "Unpick the last note";
    back.addEventListener("click", () => {
      // One step back, not a reset. Mis-clicking the second note should not
      // cost you the first one.
      if (traceToNode) traceToNode = null;
      else traceFromNode = null;
      graphTrace = null;
      renderTraceState();
      drawTrace();
      applyGraphHighlight();
      showTraceMessage(traceFromNode ? "Click where to end." : "Click a note to start.");
    });
    holder.appendChild(back);
  }
}

// Kept for the note context menu, which offers "trace from here".
function setTraceEnd(which, noteId) {
  setTracePanelOpen(true);
  //: **`graphNodesRef`, not the d3 selection.** `graphNodeSelection` is the
  //: SVG renderer's own `<g>` join and is null on the canvas renderer, so this
  //: found nothing there and every Trace started from the node popup answered
  //: "that note isn't on the map right now" whatever was on the map. Found by
  //: `graph.js`'s own sweep once it got far enough to reach the check.
  //: `graphNodesRef` is the live node array on both renderers, which is the
  //: whole reason it exists, and the selection stays as the fallback for a
  //: moment when the array has not been built yet.
  const node =
    (graphNodesRef || []).find((n) => String(n.id) === String(noteId)) ||
    graphNodeSelection?.data().find((n) => String(n.id) === String(noteId));
  if (!node) {
    showTraceMessage("That note isn't on the map right now, clear filters and try again.");
    return;
  }
  if (which === "from") traceFromNode = node;
  else traceToNode = node;
  renderTraceState();
  if (traceFromNode && traceToNode) runTrace();
}

function showTraceMessage(text) {
  const box = $("graph-trace-result");
  if (!box) return;
  box.replaceChildren(document.createTextNode(text));
  box.classList.remove("hidden");
  box.classList.add("is-empty");
}

function clearTrace({ quiet = false } = {}) {
  graphTrace = null;
  graphTraceRoutes = [];
  graphTraceIndex = 0;
  traceFromNode = null;
  traceToNode = null;
  if (traceModeActive && !quiet) {
    // This looked up a "graph-trace-status" element, which does not exist, 
    // the readout is #graph-trace-result, and showTraceMessage is how you
    // write to it. The lookup was guarded by `if (status)`, so the prompt
    // simply never appeared and trace mode began with no instructions.
    showTraceMessage("Click a starting note");
  } else {
    const box = $("graph-trace-result");
    if (box) {
      box.replaceChildren();
      box.classList.add("hidden");
      box.classList.remove("is-empty");
    }
  }
  // Both branches still have to repaint: clearing the readout without
  // redrawing leaves the old highlighted path drawn on the map.
  drawTrace();
  applyGraphHighlight();
}

async function runTrace() {
  if (!traceFromNode || !traceToNode) {
    showTraceMessage("Pick two notes to trace between.");
    return;
  }
  // Trace used to read two <select> values into local `from`/`to`. It became
  // click-two-notes-on-the-map, the selects went away, and these three
  // references to `from`/`to` were left behind pointing at nothing, so the
  // moment you picked a second note, Trace threw a ReferenceError and did
  // nothing at all, with the failure visible only in the console.
  const from = traceFromNode.id;
  const to = traceToNode.id;
  if (from === to) {
    showTraceMessage("Those are the same note, pick two different ones.");
    return;
  }
  showTraceMessage("Tracing…");
  const result = await apiJson(
    `/graph/path?source=${encodeURIComponent(from)}&target=${encodeURIComponent(to)}`
  ).catch(() => null);
  if (!result) {
    showTraceMessage("Couldn't trace that: the server didn't answer.");
    return;
  }
  if (!result.found) {
    graphTrace = null;
    // The server's reason, verbatim. "No path" on its own is the kind of
    // answer that makes people assume the feature is broken; what they need is
    // which of the three possible causes it was.
    showTraceMessage(result.reason || "No path between those two notes.");
    drawTrace();
    applyGraphHighlight();
    return;
  }
  //: `routes` is always present and always has the best route first when the
  //: server says `found`, but an older server (or a cached response from one)
  //: would not send it, and a readout that renders nothing is worse than one
  //: with a single route in it. Fall back to the top-level shape, which every
  //: version has sent.
  graphTraceRoutes = Array.isArray(result.routes) && result.routes.length
    ? result.routes
    : [{ hops: result.hops, nodes: result.nodes, steps: result.steps }];
  graphTraceIndex = 0;
  selectTraceRoute(0, { redraw: false });
  drawTrace();
  applyGraphHighlight();
}

// The chain in words, under the strip. The map shows the shape; this says what
// each step *is*, which the map cannot, a line between two notes looks the
// same whether you drew it or they merely share a tag.
// Redesigned twice (ROADMAP.md item 5). The first redesign this session
// put one row per note plus one row per connector, stacked vertically, 
// reported back immediately as "crushes the graph, takes up most of the
// page", because it was never actually looked at running: a path of even
// four or five hops is eight-plus rows tall in a box that sits in normal
// document flow directly above the canvas, so it pushed the whole map
// down out of view. This version goes back to a single horizontal,
// wrapping strip: the note chips and the arrow-plus-reason connectors
// between them all flow and wrap together like a sentence, the same
// footprint the *original* pre-redesign version had, but with the notes
// as visually distinct chips and a real arrow glyph instead of an em-dash,
// and `.graph-trace-path`'s own `max-height` + scroll (below, in the CSS)
// as a hard floor under how tall this can ever get, so no path length can
// repeat this mistake even if the wrapping math is ever wrong again.
//: Switch which of the routes is being read. Everything downstream: 
//: `graphTrace`, the readout, the highlighted nodes, which overlay line is
//: solid: hangs off `graphTraceIndex`, so this is the one place that changes
//: and the four surfaces cannot disagree about which route is selected.
function selectTraceRoute(index, { redraw = true } = {}) {
  if (!graphTraceRoutes.length) return;
  graphTraceIndex = Math.max(0, Math.min(index, graphTraceRoutes.length - 1));
  const route = graphTraceRoutes[graphTraceIndex];
  graphTrace = {
    ids: route.nodes.map((n) => n.id),
    steps: route.steps,
    nodes: route.nodes,
  };
  renderTraceReadout({ ...route, hops: route.steps.length });
  if (redraw) {
    drawTrace();
    applyGraphHighlight();
  }
}

//: The shapes "Generate story from path" can make.
//:
//: It was one hard-coded prompt, "write a cohesive, publishable narrative" , 
//: which is one good answer to a question with several. Asked to "improve and
//: extend the generate story from path feature": the path is a chain of
//: *reasons*, and what you want built out of it depends entirely on why you
//: traced it. An explainer, a timeline and an argument are three different
//: documents from the same five notes, and picking between them is one click
//: rather than a re-prompt in the chat.
//:
//: `ask` is written to be joined onto the shared preamble in `storyPrompt`, so
//: the part that says "use the connections, follow the order" is stated once
//: and every shape inherits it. A shape that restated it would be a shape that
//: could drift from it.
const TRACE_STORY_SHAPES = [
  {
    id: "story",
    label: "A narrative",
    icon: "ph:book-open-text",
    hint: "publishable prose that ties the notes together",
    ask: "Write a cohesive, publishable narrative weaving these thoughts together.",
  },
  {
    id: "explain",
    label: "An explainer",
    icon: "ph:lightbulb",
    hint: "how these connect, in plain language",
    ask:
      "Explain in plain language how these notes connect, as a short essay a " +
      "colleague could follow without knowing the background.",
  },
  {
    id: "timeline",
    label: "A timeline",
    icon: "ph:clock-counter-clockwise",
    hint: "how the thinking developed, in order",
    ask:
      "Lay these out as a timeline of how the thinking developed: what came " +
      "first, what it led to, and what changed along the way.",
  },
  {
    id: "argument",
    label: "An argument",
    icon: "ph:scales",
    hint: "claim, evidence, caveats",
    ask:
      "Build the argument these notes add up to. State the claim, give the " +
      "evidence from the notes, then the caveats and what would change it.",
  },
  {
    id: "teach",
    label: "Teaching notes",
    icon: "ph:graduation-cap",
    hint: "what to learn first, then next, and why",
    ask:
      "Turn this into teaching notes: what someone should learn first, what " +
      "next, and why each step depends on the one before it.",
  },
  {
    id: "brief",
    label: "A short brief",
    icon: "ph:note",
    hint: "one paragraph, twenty seconds to read",
    ask:
      "Write one tight paragraph a busy colleague could read in twenty " +
      "seconds and come away knowing how these connect.",
  },
];

//: The preamble every shape shares. The connection reasons are the whole point
//:, a story built from the notes alone is a story about five unrelated things,
//: and the *reasons* are what the traced path actually discovered.
function storyPrompt(shape, route) {
  const reasons = route.steps.map((step) => step.how).join("; ");
  const alternatives =
    graphTraceRoutes.length > 1
      ? ` This is route ${graphTraceIndex + 1} of ${graphTraceRoutes.length} between the same two notes; write about this one.`
      : "";
  return (
    `${shape.ask} Follow the exact order the notes are attached in, and use ` +
    `the connection between each step (${reasons}) as part of what ties it ` +
    `together, not just the notes' own text.${alternatives}`
  );
}

function renderTraceReadout(result) {
  const box = $("graph-trace-result");
  if (!box) return;
  box.classList.remove("hidden", "is-empty");
  const noteButton = (node) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "graph-trace-note";
    renderInlineMarkdown(button, node.preview, [], true);
    button.title = `Open this note (${node.category})`;
    button.addEventListener("click", () => flashEntry(node.id));
    return button;
  };
  const byId = new Map(result.nodes.map((n) => [n.id, n]));

  const header = document.createElement("div");
  header.className = "graph-trace-header";
  const summary = document.createElement("span");
  summary.className = "graph-trace-step";
  summary.textContent = `${result.hops} step${result.hops === 1 ? "" : "s"}`;
  header.appendChild(summary);

  const path = document.createElement("div");
  path.className = "graph-trace-path";
  path.appendChild(noteButton(result.nodes[0]));
  for (const step of result.steps) {
    const connector = document.createElement("span");
    connector.className = "graph-trace-connector";
    connector.title = step.how;
    const arrow = document.createElement("span");
    arrow.className = "graph-trace-arrow-icon";
    arrow.textContent = "→";
    arrow.setAttribute("aria-hidden", "true");
    const how = document.createElement("span");
    how.className = "graph-trace-connector-label";
    how.textContent = step.how;
    connector.append(arrow, how);
    path.append(connector, noteButton(byId.get(step.target)));
  }

  const pieces = [header, path];

  //: **The route switcher.** Only drawn when there is more than one route, so
  //: the common case, the two notes connect one way, is exactly the row it
  //: has always been rather than a row with a lonely "1 of 1" on it.
  //:
  //: Each chip carries the same `data-route` index the overlay lines do, which
  //: is what ties a chip to a coloured line on the map: chip 2 and the line
  //: drawn in colour 2 are the same route, and you can see that without
  //: clicking anything.
  if (graphTraceRoutes.length > 1) {
    const switcher = document.createElement("div");
    switcher.className = "graph-trace-routes";
    switcher.setAttribute("role", "tablist");
    switcher.setAttribute("aria-label", "Routes between these two notes");
    graphTraceRoutes.forEach((route, index) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "graph-trace-route-chip";
      chip.dataset.route = String(index);
      chip.setAttribute("role", "tab");
      const active = index === graphTraceIndex;
      chip.classList.toggle("is-active", active);
      chip.setAttribute("aria-selected", String(active));
      const swatch = document.createElement("span");
      swatch.className = "graph-trace-route-swatch";
      swatch.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      const hops = route.steps.length;
      label.textContent = `Route ${index + 1} · ${hops} step${hops === 1 ? "" : "s"}`;
      chip.append(swatch, label);
      chip.title =
        index === 0
          ? "The shortest route: the one the map draws solid by default"
          : "Another way these two notes connect";
      chip.addEventListener("click", () => selectTraceRoute(index));
      switcher.appendChild(chip);
    });
    pieces.splice(1, 0, switcher);
  }

  // Story Mode: Synthesize the path into a narrative.
  //
  // Was three inline `.style.x =` assignments against `var(--primary)` /
  // `var(--primary-fg)`, tokens that don't exist in this design system (it's
  // `--accent`/`--on-accent`), and the CSP's `style-src: 'self'` (no
  // `unsafe-inline`) refuses an inline style attribute outright regardless,
  // which is what `.style.x =` sets under the hood. Both silently no-op, so
  // the button rendered as a bare `.graph-trace-note` with none of its
  // intended emphasis. A real class with real tokens, per DESIGN.md.
  //
  //: **And it is a menu now, not one button.** It sent a single hard-coded
  //: "write a publishable narrative" prompt, which is one good answer to a
  //: question that has several: the same five notes and the same chain of
  //: reasons make a different document depending on why you traced them.
  //: `TRACE_STORY_SHAPES` holds the six, `storyPrompt` states the shared part
  //: once, and the summary still runs the default (a narrative) on a plain
  //: click so the one-press path nobody has to learn is unchanged.
  const story = document.createElement("details");
  story.className = "doc-dock-menu doc-toolbar-menu graph-trace-story";
  //: `.doc-toolbar-menu` deliberately: it is what `clampToolbarMenu` keys on,
  //: so this menu gets the app's viewport-fixed placement, its flip-when-there-
  //: is-no-room and its re-place-on-scroll for free rather than growing a
  //: fourth opinion about where a dropdown goes.
  const storyOpener = document.createElement("summary");
  storyOpener.className = "graph-trace-note story-mode-btn";
  setLabel(storyOpener, "ph:magic-wand Generate from path");
  storyOpener.title = "Build something out of this path, using the AI locally";
  const caret = document.createElement("i");
  caret.className = "ph ph-caret-down doc-toolbar-menu-caret";
  caret.setAttribute("aria-hidden", "true");
  storyOpener.appendChild(caret);
  const list = document.createElement("div");
  list.className = "doc-dock-menu-list";
  for (const shape of TRACE_STORY_SHAPES) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "doc-dock-menu-item";
    setLabel(item, `${shape.icon} ${shape.label}`);
    item.title = shape.hint;
    item.addEventListener("click", () => {
      story.open = false;
      const route = graphTraceRoutes[graphTraceIndex] || result;
      switchTab("chat");
      sendChatMessage(storyPrompt(shape, route), {
        noteIds: graphTrace.ids,
        attachedNotesOnly: true,
      });
    });
    list.appendChild(item);
  }
  story.append(storyOpener, list);
  header.appendChild(story);

  box.replaceChildren(...pieces);
}

// Arc layout puts every node on one shared baseline (`layoutHierarchy`'s
// `arc` branch: see `arcPath`), which is why *its* edges are curves in the
// first place: a straight line between two nodes on that baseline is just
// the baseline itself. The trace overlay drew a straight chord regardless of
// layout, so in Arc specifically the "highlighted path" sat exactly where
// the row of ordinary nodes already was, reported as connections being
// hard to see on non-tree layouts, and this is the layout where the overlay
// was not just hard to see but nearly the same line as no overlay at all.
//
// Taller than `arcPath`'s own curve (0.9 vs 0.6) so the highlighted route
// arches visibly clear of the row instead of tracking the same shape as the
// muted, thin edges underneath it, and unlike `arcPath`, which can assume
// `a.x < b.x` because a pre-order walk always visits a parent before its
// children, a traced path can run either direction through the hierarchy.
function tracePath(a, b) {
  const rx = Math.max(Math.abs(b.x - a.x) / 2, 1);
  const ry = rx * 0.9;
  const sweep = a.x <= b.x ? 1 : 0;
  return `M${a.x},${a.y}A${rx},${ry} 0 0,${sweep} ${b.x},${b.y}`;
}

// Position the overlay from the nodes it joins. Called once for a laid-out
// tree, and on every tick of the force simulation, which is why it is a
// function of the current node objects rather than of stored coordinates.
function positionTraceLines() {
  if (!graphTraceLines) return;
  if (graphLayout() === "arc") {
    graphTraceLines.attr("d", (d) => tracePath(d.from, d.to));
  } else {
    graphTraceLines
      .attr("x1", (d) => d.from.x)
      .attr("y1", (d) => d.from.y)
      .attr("x2", (d) => d.to.x)
      .attr("y2", (d) => d.to.y);
  }
}

// (Re)draw the overlay for the current trace. Segments whose notes are not on
// the map are dropped rather than drawn to nowhere, the readout above still
// names them.
function drawTrace() {
  // On the canvas renderer the overlay is painted from `graphTrace` /
  // `graphTraceRoutes` inside the frame (see `gcDrawTrace`), so redrawing it is
  // a redraw request. Everything above this line, running the search, filling
  // the readout, the route chips, is renderer-agnostic and unchanged.
  if (graphRenderer() === "canvas" && typeof gcRequestDraw === "function") {
    gcRequestDraw();
    return;
  }
  if (!graphTraceLayer) return;
  const byId = new Map((graphNodesRef || []).map((n) => [n.id, n]));
  //: **Every route is drawn, not just the selected one.** The question a
  //: second route answers is "is that the only way these connect?", and that
  //: is a question about the picture: switching between routes one at a time
  //: would never show you that there are three. The selected one is solid, the
  //: rest are ghosted (see `.graph-path-route-*` and `.is-dimmed` in the
  //: stylesheet), and the colour index matches the route chip's swatch, so a
  //: line and its chip are the same route without a click.
  //:
  //: A segment shared by two routes is drawn twice, deliberately: the second
  //: draw sits on top, so a shared spine reads in the selected route's colour
  //: rather than in whichever route happened to be rendered last.
  const routes = graphTraceRoutes.length
    ? graphTraceRoutes
    : graphTrace
      ? [{ steps: graphTrace.steps }]
      : [];
  const segments = [];
  routes.forEach((route, index) => {
    if (index === graphTraceIndex) return; // drawn last, so it wins the overlap
    for (const step of route.steps || []) {
      const from = byId.get(step.source);
      const to = byId.get(step.target);
      if (from && to) segments.push({ from, to, kind: step.kind, route: index, dim: true });
    }
  });
  for (const step of routes[graphTraceIndex]?.steps || []) {
    const from = byId.get(step.source);
    const to = byId.get(step.target);
    if (from && to) {
      segments.push({ from, to, kind: step.kind, route: graphTraceIndex, dim: false });
    }
  }
  // Arc draws the overlay as a <path> (see `tracePath`); every other layout
  // draws it as a <line>. Switching layout while a trace is active must not
  // leave the previous shape's elements behind: `.selectAll(tag)` only ever
  // sees its own tag, so the other one is removed by hand first.
  const isArc = graphLayout() === "arc";
  graphTraceLayer.selectAll(isArc ? "line" : "path").remove();
  graphTraceLines = graphTraceLayer
    .selectAll(isArc ? "path" : "line")
    .data(segments)
    .join(isArc ? "path" : "line")
    // `.graph-path-line` already sets `fill: none`, needed for the <path>
    // case, harmless on a <line>.
    .attr(
      "class",
      (d) =>
        `graph-path-line graph-path-${d.kind} graph-path-route-${d.route % 3}` +
        (d.dim ? " is-dimmed" : "")
    );
  positionTraceLines();
  if (graphNodeSelection) {
    //: Only the *selected* route's notes are marked "on path". The other
    //: routes are visible as lines; lighting up their notes too would make
    //: half the map look traced and undo the point of highlighting anything.
    const onPath = new Set(graphTrace ? graphTrace.ids : []);
    graphNodeSelection.classed("graph-on-path", (d) => onPath.has(d.id));
    graphNodeSelection.classed(
      "graph-path-end",
      (d) =>
        graphTrace != null &&
        (d.id === graphTrace.ids[0] || d.id === graphTrace.ids[graphTrace.ids.length - 1])
    );
  }
}

// --- drag one note onto another to link them (§9) ----------------------------
//
// The map already had a link gesture, Link in the popup, then click the other
// note: which works and is two dialogs deep. Dropping one note on another is
// the gesture people try first, and it costs nothing to support: the drag
// behaviour is already there to move nodes about.
//
// The whole risk here is an *accidental* link, since every drag now ends over
// something or nothing. Three things answer that, and all three are needed:
// the target lights up while you are over it, the drop has to land on the
// note's own circle rather than near it, and the link that results is
// undoable from the toast.

//: How much of a miss still counts as a hit. Zero would demand pixel accuracy
//: on a moving target; the node's own radius plus this is the circle you are
//: actually aiming at.
//:
//: Raised from 6 after driving the gesture in a browser. A note is a 9px
//: circle, so six pixels of slop meant hitting a 15px target that is *drifting*
//:, dragging reheats the simulation, so everything else keeps moving while
//: you aim. Fourteen makes it a comfortable 23px and is still far short of the
//: nearest neighbour, so a drop in open space still links nothing.
const DROP_SLOP = 14;

//: The note the current drag is hovering over, remembered from the last
//: `drag` event so the drop can use it. See the `end` handler for why a fresh
//: hit test at release finds nothing.
let graphDropTarget = null;

//: The nodes a drag pinned so they would hold still while it aimed. Kept as a
//: list rather than inferred at release, because "was pinned by this drag" and
//: "was held by the user" are the same `fx != null` afterwards, and releasing
//: the second kind would silently undo a double-click hold.
let graphDragPinned = [];

function graphNodeUnder(dragged, event) {
  for (const other of graphNodesRef || []) {
    if (other === dragged || other.isGroup) continue;
    const dx = (other.x ?? 0) - event.x;
    const dy = (other.y ?? 0) - event.y;
    // Squared, not `Math.hypot`. This runs over every node on every pointer
    // event of a drag, so the square root is one transcendental call per note
    // per event for a comparison that does not need it.
    const reach = graphNodeRadius(other) + DROP_SLOP;
    if (dx * dx + dy * dy <= reach * reach) return other;
  }
  return null;
}

//: The kinds of connection a link can carry.
//:
//: **Mirrors `LINK_TYPES` in src/memorymap/core/database.py, and
//: `tests/test_link_types.py` fails the build if the two drift.** Duplicated
//: rather than fetched because this list is needed to draw a dialog before any
//: request has been made, and a picker that has to wait on the network to know
//: what it can offer is a picker that opens empty.
const GRAPH_LINK_TYPES = [
  ["related", "Related", "These belong together"],
  ["continues", "Continues", "This carries on from that"],
  ["context", "Extra context", "This explains or supports that"],
  ["supports", "Supports", "This is evidence for that"],
  ["contradicts", "Contradicts", "These disagree"],
  ["example_of", "Example of", "This is an instance of that"],
];

// Ask what kind of link this is before making it. Resolves to
// `{link_type, reason}`, or null when the user cancels.
//
// Asked for directly: dropping one note on another used to make a flat,
// unexplained link with no way back except an Undo toast you had to catch in
// time. Now the drop opens this, nothing is written until "Create link", and
// Cancel leaves the notebook untouched, which is the "ability to cancel the
// linkage" half of the request, and the reason this is a dialog rather than a
// toast offering to edit afterwards.
function askLinkDetails(from, to) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay confirm-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const card = document.createElement("div");
    card.className = "card modal-card link-kind-card";

    const heading = document.createElement("h3");
    heading.textContent = "How are these connected?";
    card.appendChild(heading);

    const pair = document.createElement("p");
    pair.className = "muted link-kind-pair";
    pair.textContent = `“${from.preview}” → “${to.preview}”`;
    card.appendChild(pair);

    // Direction matters for half the vocabulary, "continues" and "example of"
    // read backwards if the arrow is the other way round, so it is stated
    // above rather than left to be inferred from which node was dragged.
    const list = document.createElement("div");
    list.className = "link-kind-list";
    let chosen = "related";
    const buttons = [];
    for (const [value, label, hint] of GRAPH_LINK_TYPES) {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "link-kind-option" + (value === chosen ? " active" : "");
      option.setAttribute("aria-pressed", String(value === chosen));
      const name = document.createElement("span");
      name.className = "link-kind-name";
      name.textContent = label;
      const why = document.createElement("span");
      why.className = "link-kind-hint";
      why.textContent = hint;
      option.append(name, why);
      option.addEventListener("click", () => {
        chosen = value;
        for (const other of buttons) {
          const on = other.dataset.value === value;
          other.classList.toggle("active", on);
          other.setAttribute("aria-pressed", String(on));
        }
      });
      option.dataset.value = value;
      buttons.push(option);
      list.appendChild(option);
    }
    card.appendChild(list);

    const reasonLabel = document.createElement("label");
    reasonLabel.className = "field";
    const reasonText = document.createElement("span");
    reasonText.textContent = "Why? (optional)";
    const reasonBox = document.createElement("input");
    reasonBox.type = "text";
    reasonBox.maxLength = 200;
    reasonBox.placeholder = "Left blank, the AI will try to work it out";
    reasonLabel.append(reasonText, reasonBox);
    card.appendChild(reasonLabel);

    const row = document.createElement("div");
    row.className = "row confirm-actions";

    let settled = false;
    const close = (answer) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      returnFocus?.focus?.();
      resolve(answer);
    };
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close(null);
      } else if (event.key === "Enter" && event.target.tagName === "INPUT") {
        event.stopPropagation();
        close({ link_type: chosen, reason: reasonBox.value.trim() || null });
      }
    };

    const returnFocus = document.activeElement;
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "ghost small";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => close(null));
    const create = document.createElement("button");
    create.type = "button";
    create.className = "small accent";
    create.textContent = "Create link";
    create.addEventListener("click", () =>
      close({ link_type: chosen, reason: reasonBox.value.trim() || null })
    );
    row.append(cancel, create);
    card.appendChild(row);
    overlay.appendChild(card);
    wireBackdropClose(overlay, () => close(null));
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    // Cancel takes focus, not Create: a stray Enter arriving with the dialog
    // must not be the thing that writes a link into the notebook.
    cancel.focus();
  });
}

async function linkByDrop(from, to) {
  // Already connected: say so rather than firing a request that will 400. The
  // adjacency map is what the map itself is drawn from, so this agrees with
  // what the user can see.
  if (graphAdjacency?.get(from.id)?.has(to.id)) {
    toast("Those two are already connected.");
    return;
  }
  const details = await askLinkDetails(from, to);
  if (!details) return; // cancelled: nothing is written

  const updated = await apiJson(`/entries/${from.id}/links`, {
    method: "POST",
    body: JSON.stringify({
      target_id: to.id,
      reason: details.reason,
      link_type: details.link_type,
    }),
  }).catch((error) => {
    toast(error.message, true);
    return null;
  });
  if (!updated) return;
  await loadEntries().catch(() => {});
  renderGraph();
  // The new link's own id, so Undo removes *this* link rather than whatever
  // link happens to join them, they may have been linked twice by different
  // routes, and guessing is how an undo deletes the wrong thing.
  const made = (updated.links || []).find((link) => link.entry_id === to.id);
  toastAction(
    `Linked "${from.preview}" to "${to.preview}".`,
    "Undo",
    async () => {
      if (!made) return;
      await api(`/entries/${from.id}/links/${made.link_id}`, { method: "DELETE" });
      await loadEntries().catch(() => {});
      renderGraph();
      toast("Link removed.");
    }
  );
}

// --- colouring by cluster (§9) -----------------------------------------------
//
// A layout says where a note goes; this says what its colour *means*. By
// category is the filing, which is what somebody decided to call it. By
// cluster is the structure: which notes can actually reach each other through
// links, replies and shared tags. The two are often nothing like each other,
// and that difference is the most useful thing the map can show.

//: The last structure fetched, so the legend and the stats line agree with the
//: colours without three round trips.
let graphStructure = null;

//: GRAPH_PLAN Phase 3. The rule the colours follow; anything the select
//: does not offer collapses to category, so a stale saved view cannot ask
//: for a rule that no longer exists.
const GRAPH_COLOUR_RULES = ["category", "cluster", "kind", "age", "space", "tag", "file"];

function graphColourMode() {
  const value = document.getElementById("graph-colour")?.value;
  return GRAPH_COLOUR_RULES.includes(value) ? value : "category";
}

//: Legend toggles for the non-category rules, keyed "rule:value". Category
//: keeps its own set (graphHiddenCategories) because saved views already
//: store it under that name.
let graphHiddenKeys = new Set();

// --- Groups: a saved search painted one colour (GRAPH_PLAN Phase 3) -------------
const GRAPH_GROUPS_KEY = "graph-groups";
const GRAPH_GROUP_COLOURS = ["#e4572e", "#17bebb", "#ffc914", "#76b041", "#a06cd5", "#f07ca2", "#2f80ed", "#8d6e63"];
//: id -> group index, rebuilt on every render from the live search results.
let graphGroupOf = new Map();

function graphGroups() {
  try {
    const parsed = JSON.parse(localStorage.getItem(GRAPH_GROUPS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((g) => g && typeof g.query === "string" && g.query.trim()) : [];
  } catch {
    return [];
  }
}

function graphSetGroups(groups) {
  localStorage.setItem(GRAPH_GROUPS_KEY, JSON.stringify(groups));
  graphRenderGroups();
  renderGraph();
}

function graphGroupColour(index) {
  return GRAPH_GROUP_COLOURS[index % GRAPH_GROUP_COLOURS.length];
}

//: Which notes each group paints, from the same search the Notes tab runs.
//: Resolved per render so a group is a rule, not a snapshot. A failed search
//: paints nothing rather than everything.
async function graphResolveGroups() {
  const groups = graphGroups();
  const map = new Map();
  await Promise.all(
    groups.map(async (group, index) => {
      const reply = await apiJson(`/graph/match?q=${encodeURIComponent(group.query)}`).catch(() => null);
      for (const id of reply?.ids || []) {
        if (typeof id === "number" && !map.has(id)) map.set(id, index);
      }
    })
  );
  graphGroupOf = map;
  return groups;
}

function graphRenderGroups() {
  const list = document.getElementById("graph-groups");
  if (!list) return;
  list.replaceChildren();
  const groups = graphGroups();
  if (!groups.length) {
    const empty = document.createElement("p");
    empty.className = "muted graph-groups-empty";
    empty.textContent = "No groups yet. Add a search and its notes take one colour.";
    list.appendChild(empty);
    return;
  }
  groups.forEach((group, index) => {
    const row = document.createElement("div");
    row.className = "graph-group-row";
    row.setAttribute("role", "listitem");
    const dot = document.createElement("span");
    dot.className = "legend-dot";
    dot.style.background = graphGroupColour(index);
    const name = document.createElement("span");
    name.className = "graph-group-name";
    name.textContent = group.query;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ghost small icon-only";
    remove.title = `Remove the group “${group.query}”`;
    remove.setAttribute("aria-label", remove.title);
    setLabel(remove, "ph:x");
    remove.addEventListener("click", () => graphSetGroups(groups.filter((_, i) => i !== index)));
    row.append(dot, name, remove);
    list.appendChild(row);
  });
}

function initGraphGroups() {
  const add = document.getElementById("graph-group-add");
  const input = document.getElementById("graph-group-query");
  if (!add || !input || add._wired) return;
  add._wired = true;
  const submit = () => {
    const query = input.value.trim();
    if (!query) return;
    const groups = graphGroups();
    if (groups.some((g) => g.query.toLowerCase() === query.toLowerCase())) {
      toast("That group already exists.");
      return;
    }
    if (groups.length >= GRAPH_GROUP_COLOURS.length) {
      toast(`Up to ${GRAPH_GROUP_COLOURS.length} groups, so each keeps its own colour.`);
      return;
    }
    input.value = "";
    graphSetGroups([...groups, { query }]);
  };
  add.addEventListener("click", submit);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  });
  graphRenderGroups();
}

let graphFocusModeId = null;

//: Which renderer draws the map, GRAPH_PLAN.md §5 Phase 1.
//:
//: The canvas renderer (graph-canvas.js) replaces the SVG one below; while
//: both exist, `localStorage["graph-renderer"] = "svg"` puts the old one back.
//: That switch is not a preference and has no control in the UI, it exists so
//: the gate's before/after frame numbers could be measured on one build,
//: against one fixture, rather than compared across two checkouts. The SVG
//: path is deleted in one commit once the canvas one passes the gate, and this
//: function goes with it.
function graphRenderer() {
  return localStorage.getItem("graph-renderer") === "svg" ? "svg" : "canvas";
}

async function renderGraph() {
  const svg = document.getElementById("graph-svg");
  const canvas = document.getElementById("graph-canvas");
  // `typeof` rather than a bare name: graph-canvas.js is a separate <script>,
  // and a load failure there must degrade to the old renderer rather than
  // throw a ReferenceError out of every control that calls this.
  const useCanvas =
    graphRenderer() === "canvas" && canvas && typeof renderGraphCanvas === "function";
  if (svg) svg.classList.toggle("hidden", Boolean(useCanvas));
  if (canvas) canvas.classList.toggle("hidden", !useCanvas);
  if (useCanvas) return renderGraphCanvas();
  return renderGraphSvg();
}

async function renderGraphSvg() {
  const wantSimilarity = $("graph-similarity").checked;
  // ROADMAP.md item 34: off by default and only on the top-level graph, not
  // the local/focus view: entities are membership edges to *notes*, and
  // /graph/local's own depth-limited walk has no equivalent concept yet.
  const wantEntities = $("graph-entities")?.checked;
  // Tier 2 item 16, same "top-level graph only" scope as entities just
  // above: a document's edge is a link to a *note*, and /graph/local's own
  // depth-limited BFS has no equivalent concept yet.
  const wantDocuments = $("graph-documents")?.checked;
  // MINDMAP_PLAN.md §5 item 13, same "top-level graph only" scope as the two
  // above, and for the same reason: a map's edge is membership of a *note*,
  // and /graph/local's depth-limited BFS has no equivalent concept yet.
  const wantMaps = $("graph-maps")?.checked;
  const endpoint = graphFocusModeId
    ? `/graph/local/${graphFocusModeId}?depth=2&similarity=${wantSimilarity}`
    : `/graph?${wantSimilarity ? "similarity=true&" : ""}${wantEntities ? "include_entities=true&" : ""}${wantDocuments ? "include_documents=true&" : ""}${wantMaps ? "include_maps=true" : ""}`;
    
  const data = await apiJson(endpoint).catch(() => null);
  if (!data) return;

  if (graphSimulation) graphSimulation.stop();
  const svg = d3.select("#graph-svg");
  svg.on(".zoom", null); // Prevent memory leak from duplicate zoom listeners
  svg.selectAll("*").remove();

  // Premium UI: Orb gradient definitions for tactile nodes
  const defs = svg.append("defs");
  const orbGrad = defs.append("radialGradient")
    .attr("id", "orb-shine")
    .attr("cx", "35%")
    .attr("cy", "30%")
    .attr("r", "65%");
  orbGrad.append("stop").attr("offset", "0%").attr("stop-color", "white").attr("stop-opacity", "0.65");
  orbGrad.append("stop").attr("offset", "100%").attr("stop-color", "white").attr("stop-opacity", "0");

  // Inline display beats every stylesheet rule, the overlay can never
  // float over a populated graph again (user-reported, Wave O).
  const empty = $("graph-empty");
  empty.style.display = data.nodes.length > 0 ? "none" : "grid";
  empty.classList.toggle("hidden", data.nodes.length > 0);

  // Colour legend: one dot per category, same scale as the nodes.
  const color = d3.scaleOrdinal(
    data.categories,
    d3.schemeTableau10.concat(d3.schemeSet3)
  );
  const clusterColour = d3.scaleOrdinal(
    d3.schemeTableau10.concat(d3.schemeSet3)
  );
  const colourMode = graphColourMode();
  // The structure is only fetched when something is going to show it. It is a
  // traversal of the whole notebook, and an ordinary look at the map should
  // not pay for an answer nobody asked for.
  graphStructure =
    colourMode === "cluster"
      ? await apiJson("/graph/structure").catch(() => null)
      : null;
  // What a node's colour means. Category headings in a tree layout keep their
  // category colour in both modes: they are filing by definition, and a
  // heading is not a note that can belong to a cluster.
  const nodeColour = (d) => {
    if (colourMode === "category" || !graphStructure || d.isGroup) {
      return color(d.category);
    }
    const cluster = graphStructure.cluster_of[String(d.id)];
    // Connected to nothing: deliberately not a colour of its own. An orphan is
    // the absence of structure, and giving it a bright twelfth hue would make
    // the thing that is missing look like another kind of group.
    return cluster === undefined ? "var(--muted)" : clusterColour(String(cluster));
  };

  const legend = $("graph-legend");
  legend.replaceChildren();
  if (colourMode === "cluster" && graphStructure) {
    // In cluster mode the legend describes clusters, because a legend whose
    // dots do not match the colours on screen is worse than no legend. Its
    // entries highlight rather than filter, a cluster is something you want
    // to *find*, where a category is something you want to get out of the way.
    graphStructure.clusters.forEach((cluster, position) => {
      const item = document.createElement("button");
      item.className = "legend-item legend-toggle";
      item.title =
        `${cluster.size} notes, around "${cluster.core.preview}"` +
        (cluster.categories.length ? ` · ${cluster.categories.join(", ")}` : "");
      const dot = document.createElement("span");
      dot.className = "legend-dot";
      dot.style.background = clusterColour(String(position));
      item.append(
        dot,
        document.createTextNode(`${cluster.core.preview} (${cluster.size})`)
      );
      item.addEventListener("click", () => {
        graphHighlightIds = new Set(cluster.ids);
        applyGraphHighlight();
      });
      legend.appendChild(item);
    });
    if (graphStructure.orphan_count) {
      const item = document.createElement("button");
      item.className = "legend-item legend-toggle";
      item.title = "Notes with no link, no reply and no shared tag";
      const dot = document.createElement("span");
      dot.className = "legend-dot";
      dot.style.background = "var(--muted)";
      item.append(
        dot,
        document.createTextNode(`unconnected (${graphStructure.orphan_count})`)
      );
      item.addEventListener("click", () => {
        graphHighlightIds = new Set(graphStructure.orphans.map((n) => n.id));
        applyGraphHighlight();
      });
      legend.appendChild(item);
    }
    if (graphHiddenCategories.size) {
      // The category filters still apply, they just have no controls in this
      // mode. Saying so beats a map quietly missing notes.
      const note = document.createElement("span");
      note.className = "legend-item";
      note.textContent = `${graphHiddenCategories.size} category filter${
        graphHiddenCategories.size === 1 ? "" : "s"
      } still on: switch to “By category” to change them`;
      legend.appendChild(note);
    }
  } else {
    for (const category of data.categories) {
      // Legend entries double as filters (Wave M): click to hide/show.
      const item = document.createElement("button");
      item.className = "legend-item legend-toggle";
      item.classList.toggle("legend-off", graphHiddenCategories.has(category));
      item.title = graphHiddenCategories.has(category)
        ? `Show ${category} again`
        : `Hide ${category} from the map`;
      item.setAttribute("aria-pressed", String(!graphHiddenCategories.has(category)));
      const dot = document.createElement("span");
      dot.className = "legend-dot";
      dot.style.background = color(category);
      item.append(dot, document.createTextNode(category));
      item.addEventListener("click", () => {
        if (graphHiddenCategories.has(category)) graphHiddenCategories.delete(category);
        else graphHiddenCategories.add(category);
        renderGraph();
      });
      legend.appendChild(item);
    }
  }

  // Apply the legend filter: drop hidden categories and their edges.
  let visibleNodes = data.nodes.filter(
    (n) => !graphHiddenCategories.has(n.category)
  );
  const keptIds = new Set(visibleNodes.map((n) => n.id));
  const visibleEdges = data.edges.filter(
    (e) => keptIds.has(e.source) && keptIds.has(e.target)
  );
  // "Hide unlinked" (declutter): keep only notes that appear in an edge.
  if ($("graph-hide-orphans") && $("graph-hide-orphans").checked) {
    const connected = new Set();
    for (const e of visibleEdges) {
      connected.add(e.source);
      connected.add(e.target);
    }
    visibleNodes = visibleNodes.filter((n) => connected.has(n.id));
  }
  if (!visibleNodes.length) {
    empty.style.display = "grid";
    empty.classList.remove("hidden");
    return;
  }

  const box = $("graph-box");
  //: **Whether those two fallbacks below are load-bearing this run.** A box
  //: inside a tab that has not been laid out yet reports `clientWidth` 0, so
  //: the `|| 800` is not a safety net, it is a guess that then gets used as
  //: the frame for a whole layout. The tree layouts are the ones where that
  //: shows: reported as "I loaded up the tree graph and it looked like this
  //: but when I went onto another graph view and came back it was fine",
  //: which is the second render finding a real width. Recorded here and
  //: acted on where the tree is framed.
  const boxMeasured = box.clientWidth > 0 && box.clientHeight > 0;
  const width = box.clientWidth || 800;
  const height = box.clientHeight || 540;
  svg.attr("viewBox", [0, 0, width, height]);

  // One zoomable/pannable group holds everything.
  const canvas = svg.append("g");
  const zoomBehavior = d3
    .zoom()
    .scaleExtent([0.05, 5])
    // Reported: dragging on empty canvas "sometimes highlights an unrelated
    // note". A pan drag translates the whole canvas under a stationary
    // cursor, so whatever node happens to slide past it fires a real
    // `mouseenter`, and clearing hover only at the start/end of the
    // gesture left a race: a `mouseenter` mid-pan (the node passing under
    // the cursor) could re-set it *after* "start" cleared it, and nothing
    // cleared it again until the next real hover. `graphIsPanning` mutes
    // hover updates for the gesture's whole duration instead, so a node
    // sliding past during a pan never lights up at all, only a real,
    // stationary hover once the drag is over does.
    .on("start", () => {
      graphIsPanning = true;
      graphHoveredId = null;
      applyGraphHighlight();
      // Profiled directly (120 notes, Chromium CDP metrics): a pan drag cost
      // noticeably more main-thread recalc-style time than an idle baseline,
      // even though `graphIsPanning` above already mutes the *application's*
      // hover logic. The gap is the browser's own `:hover` pseudo-class: 
      // every node the cursor physically sweeps under during the drag still
      // matches `.graph-node:hover`, which re-triggers CSS transitions
      // (`.graph-core`'s `stroke`/`stroke-width`, `.graph-halo`'s `opacity`)
      // per node, invisible to any JS mute. `pointer-events: none` for the
      // gesture's duration removes that hit-testing entirely; node drags
      // never reach here (their own `mousedown` already calls
      // `stopPropagation()` before the zoom behaviour's `start` fires), so
      // this cannot affect them.
      canvas.classed("graph-panning", true);
    })
    .on("end", () => {
      graphIsPanning = false;
      graphHoveredId = null;
      applyGraphHighlight();
      canvas.classed("graph-panning", false);
    })
    .on("zoom", (event) => {
      canvas.attr("transform", event.transform);
      graphMinimapFrame(); // the viewport rectangle follows the real transform
      // Semantic Zoom logic
      const isZoomedOut = event.transform.k < 0.45;
      if (canvas.classed("semantic-zoom-out") !== isZoomedOut) {
        canvas.classed("semantic-zoom-out", isZoomedOut);
        const duration = 250;
        
        // Use try/catch or typeof since these are initialized after zoom setup
        if (typeof nodeGroups !== "undefined") {
          nodeGroups.transition().duration(duration).style("opacity", isZoomedOut ? 0 : 1).style("pointer-events", isZoomedOut ? "none" : "all");
          if (typeof labelLayer !== "undefined") {
            labelLayer.transition().duration(duration).style("opacity", isZoomedOut ? 0 : 1);
            // Zooming back in is the other way the layer becomes visible.
            // The transition sets opacity asynchronously, so the catch-up
            // has to run after it or `labelsOnScreen()` still reads "0".
            if (!isZoomedOut) setTimeout(graphCatchUpLabels, duration + 20);
          }
          if (typeof edgeLayer !== "undefined") edgeLayer.transition().duration(duration).style("opacity", isZoomedOut ? 0 : 1);
          if (typeof graphTraceLayer !== "undefined" && graphTraceLayer) graphTraceLayer.transition().duration(duration).style("opacity", isZoomedOut ? 0 : 1);
          if (typeof clusterLayer !== "undefined" && clusterLayer) clusterLayer.transition().duration(duration).style("opacity", isZoomedOut ? 1 : 0).style("pointer-events", isZoomedOut ? "all" : "none");
        }
      }
    });
  svg.call(zoomBehavior).on("dblclick.zoom", null); // dblclick pins, not zooms

  // Keep refs so the +/−/fit buttons drive this same zoom behaviour.
  graphSvg = svg;
  graphZoom = zoomBehavior;
  graphCanvas = canvas;
  graphDims = { w: width, h: height };
  initGraphMinimap();
  initGraphDockHeightToken();
  initGraphViews();

  // D3 mutates these (x/y/vx/vy), so work on copies.
  const layoutKind = graphLayout();
  const tree = layoutKind === "force" ? null : layoutHierarchy(
    visibleNodes.map((n) => ({ ...n })), layoutKind, width, height
  );
  // In a tree the drawn edges *are* the hierarchy: the note links are a
  // different structure, and overlaying them turns the tree back into the
  // web it exists to be an alternative to.
  //
  // A force-layout note that was already on screen keeps the spot it had
  // settled into: read from `graphNodesRef` before it's overwritten below
  //, instead of every render restarting the whole map's "explode outward
  // from the centre" animation from scratch. Before this, toggling a single
  // legend filter or dragging a physics slider replayed that same
  // full-notebook animation, which read as the map never actually being at
  // rest. A genuinely new node (nothing to inherit) still gets D3's normal
  // spiral placement: only existing notes are pinned in place at start.
  const priorPositions = new Map(
    (graphNodesRef || []).map((n) => [n.id, { x: n.x, y: n.y, vx: n.vx, vy: n.vy }])
  );
  const nodes = tree
    ? tree.nodes
    : visibleNodes.map((n) => {
        const prior = priorPositions.get(n.id);
        const built = prior ? { ...n, ...prior } : { ...n };
        // Restore a persisted double-click pin. Deliberately re-applied on
        // every render, not just a fresh load: `prior` above only carries
        // x/y/vx/vy, never fx/fy, so without this a pin held this same
        // session was silently dropped by the next legend-filter toggle or
        // physics-slider change: the reload case ROADMAP §87.1 named was
        // one symptom of the same "fx/fy never survives a rebuild" gap.
        if (built.graph_pin_x != null && built.graph_pin_y != null) {
          built.fx = built.graph_pin_x;
          built.fy = built.graph_pin_y;
        }
        return built;
      });
  const edges = tree ? tree.links : visibleEdges.map((e) => ({ ...e }));
  graphNodesRef = nodes;
  // Adjacency for hover-highlight: which notes each note is linked to.
  graphAdjacency = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const e of edges) {
    const from = tree ? e.source.id : e.source;
    const to = tree ? e.target.id : e.target;
    graphAdjacency.get(from)?.add(to);
    graphAdjacency.get(to)?.add(from);
  }

  // Physics sliders (0–100, default 50) scale the tuned defaults so the
  // out-of-the-box layout is unchanged at 50.
  const gravity = Number(localStorage.getItem("graph-gravity") ?? 50);
  const spread = Number(localStorage.getItem("graph-spread") ?? 50);
  const spreadScale = 0.5 + spread / 50; // 0.5×–2.5× the base link distance
  const gravityScale = 0.4 + gravity / 41.7; // stronger pull → tighter clusters

  graphSimulation = tree
    ? null
    : d3
    .forceSimulation(nodes)
    // Profiled directly (120 notes, Chromium CDP metrics under 6x CPU
    // throttling: the standard proxy for lower-end hardware): a pan/drag
    // *while the simulation is still cooling* cost 80% main-thread busy
    // time; the same gesture after it had settled cost 57%. The tick
    // handler updates every node/edge/label position on every tick, so it
    // directly competes with whatever the user is doing, and the default
    // decay (0.0228) takes ~300 ticks, which under real throttling is many
    // seconds, squarely covering "pan right after the graph opens", the
    // single most likely first action. A faster decay does not change
    // where the layout settles (the forces above decide that), only how
    // many ticks it takes to get there, which is the actual jank window.
    .alphaDecay(0.05)
    .force(
      "link",
      d3
        .forceLink(edges)
        .id((d) => d.id)
        .distance((d) => (d.kind === "similar" ? 130 : 80) * spreadScale)
    )
    // More repulsion + a mild centring pull → notes spread out and fill
    // the space instead of clumping in the middle (Wave N polish).
    .force("charge", d3.forceManyBody().strength(-340 / gravityScale))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("x", d3.forceX(width / 2).strength(0.04))
    .force("y", d3.forceY(height / 2).strength(0.06))
    .force("collide", d3.forceCollide().radius((d) => graphNodeRadius(d) + 24));
  // How much larger than the visible frame the simulation may spread. 1.8 is
  // not arbitrary: the clamp below has to be loose enough that the repulsion
  // and collide forces, not the walls, decide where a node ends up, at 1.0
  // (the frame itself) they packed into a lattice, and tight enough that the
  // drift the clamp exists to stop is still bounded. Zoom-to-fit means a
  // larger world is only ever a smaller starting zoom, never lost notes.
  const GRAPH_WORLD_SCALE = 1.8;
  // **The world is sized by how many notes there are, not by the shape of
  // the window.** Reported again after the 1.8x-the-frame version above:
  // "the graph nodes seem to be stuck in an invisible rectangular box", with
  // a screenshot showing them packed against a straight edge.
  //
  // Multiplying the frame was the right idea and the wrong axis. A graph box
  // is wide and short, so `height * 1.8` on a full-screen map is a few
  // hundred pixels of vertical room, and every node claims a collide radius
  // of roughly 50px plus 24 of padding. Past about twenty notes the walls,
  // not the forces, are what the layout settles against, and what settles
  // between outward repulsion and a wall is a rectangle. The frame's aspect
  // ratio has nothing to do with how much room a given number of notes
  // needs, which is why tying the two kept reproducing this.
  //
  // So: a **square** world whose side grows with sqrt(count): area scales
  // linearly with the number of notes, which is the honest relationship, 
  // floored at the old frame-derived size so a small notebook is unchanged.
  // Square, because a circular blob is what these forces actually produce
  // and a square is the smallest box that never squashes one.
  //
  // A bigger world costs nothing on screen: zoom-to-fit frames whatever the
  // nodes end up occupying, so this only ever changes their arrangement.
  const perNode = 2 * (GRAPH_NODE_MAX_RADIUS + 28);
  const roomy = Math.sqrt(Math.max(nodes.length, 1)) * perNode * 1.6;
  const worldSide = Math.max(roomy, width * GRAPH_WORLD_SCALE, height * GRAPH_WORLD_SCALE);
  const worldW = worldSide;
  const worldH = worldSide;
  const worldLeft = (width - worldW) / 2;
  const worldTop = (height - worldH) / 2;
  const worldRight = worldLeft + worldW;
  const worldBottom = worldTop + worldH;
  if (tree) graphSimulation = null;

  // A tree's edges are curves between fixed points; the web's are lines that
  // move on every tick. Different elements, so each can be what it needs.
  const edgeLayer = canvas.append("g");
  const edgePathD = (d) => (tree.arc ? arcPath(d) : hierarchyPath(d, tree.radial));
  const edgeLines = tree
    ? edgeLayer
        .selectAll("path.graph-edge")
        .data(edges)
        .join("path")
        .attr("class", (d) => `graph-edge graph-edge-${d.kind}`)
        .attr("fill", "none")
        .attr("d", edgePathD)
    : edgeLayer
        .selectAll("line.graph-edge")
        .data(edges)
        .join("line")
        .attr("class", (d) => `graph-edge graph-edge-${d.kind}`);

  // Reported directly: the actual visible line (1.6px, thinner once dimmed)
  // is a hard target to click precisely. A second, invisible, much wider
  // stroke on the same path/line is the standard SVG way to grow a click
  // target without also growing what's drawn: the same shape as the
  // whiteboard's own `.sketch-hitbox` this session already added for the
  // identical reason. Drawn *under* the visible line's join below so the
  // tooltip/click listener attach to this wider element, not the thin one.
  const edgeHitLines = tree
    ? edgeLayer
        .selectAll("path.graph-edge-hit")
        .data(edges)
        .join("path")
        .attr("class", (d) => `graph-edge-hit graph-edge-${d.kind}`)
        .attr("fill", "none")
        .attr("d", edgePathD)
    : edgeLayer
        .selectAll("line.graph-edge-hit")
        .data(edges)
        .join("line")
        .attr("class", (d) => `graph-edge-hit graph-edge-${d.kind}`);

  // A link's own reason ("why are these connected?", asked for directly),
  // as a native SVG tooltip. `<title>` is the SVG way to get a hover
  // tooltip on a shape; there's no HTML `title` attribute equivalent for
  // `<line>`/`<path>`. Re-added after every join rather than left stale, so
  // a link edited or re-drawn on refresh doesn't keep showing an old reason.
  edgeHitLines.each(function (d) {
    const el = d3.select(this);
    el.selectAll("title").remove();
    if (d.reason) {
      // A deduced reason carries a confidence score (0..1); one a person or
      // the AI typed doesn't, so this only ever shows up on the guessed kind.
      const text =
        d.reason_confidence != null
          ? `${d.reason} (${Math.round(d.reason_confidence * 100)}% confidence, deduced)`
          : d.reason;
      el.append("title").text(text);
    }
  });
  // A reason was hover-only before this, discoverable only by finding the
  // one edge you already suspected and holding still over it. Asked for
  // directly: "a visual way to see the reasons... and a way to manage/add/
  // remove/edit them." A distinct edge style makes "this connection has a
  // documented reason" visible at a glance, not just on hover; a click
  // opens the real management panel below. The class also drives
  // `.graph-edge-reasoned`'s stronger colour on the *visible* thin line, 
  // toggled on both selections so hover/reason styling and the click
  // target agree on which edges are which.
  edgeLines.classed("graph-edge-reasoned", (d) => d.kind === "link" && !!d.reason);
  // **A disagreement should not look like every other line on the map.**
  // `contradicts` is the one link type that says the two notes are at odds
  // rather than together (see `core/database.py`'s LINK_TYPES), and the
  // Tensions review now produces them, but the graph drew them exactly like
  // a "related" edge, so the payoff of finding one was invisible here.
  edgeLines.classed("graph-edge-contradicts", (d) => d.link_type === "contradicts");
  edgeHitLines
    .classed("graph-edge-manageable", (d) => d.kind === "link")
    .on("click", (event, d) => {
      if (d.kind !== "link") return;
      event.stopPropagation();
      openGraphLinkPanel(d, nodes);
    });

  // Semantic Zoom: Clustering super-nodes
  const categoryGroups = d3.group(nodes, d => d.category || "Uncategorized");
  const clustersData = Array.from(categoryGroups, ([key, values]) => ({ id: key, category: key, nodes: values }));
  
  const clusterLayer = canvas.append("g")
    .attr("class", "graph-clusters-layer")
    .style("opacity", 0) // Hidden by default (zoomed in)
    .style("pointer-events", "none");
    
  const clusterGroups = clusterLayer
    .selectAll("g")
    .data(clustersData)
    .join("g")
    .attr("class", "graph-cluster");
    
  clusterGroups.append("circle")
    .attr("r", d => 25 + Math.sqrt(d.nodes.length) * 12)
    .attr("fill", d => clusterColour(d.category))
    .attr("fill-opacity", 0.6)
    .attr("stroke", d => d3.color(clusterColour(d.category)).darker(1))
    .attr("stroke-width", 2);
    
  clusterGroups.append("text")
    .text(d => d.category)
    .attr("text-anchor", "middle")
    .attr("dy", "0.3em")
    .style("font-size", "16px")
    .style("font-weight", "bold")
    .style("fill", "var(--text-main)")
    .style("paint-order", "stroke")
    .style("stroke", "var(--bg-main)")
    .style("stroke-width", "4px")
    .style("stroke-linecap", "round")
    .style("stroke-linejoin", "round");

  const nodeGroups = canvas
    .append("g")
    .selectAll("g")
    .data(nodes)
    .join("g")
    .attr("class", "graph-node")
    //: **The hover scale, per node, because every node is a different size.**
    //: Asked for: "can you make graph nodes temporarily expand to fill their
    //: glow bubble when I hover over them or smth?? I feel like the graph
    //: nodes could look slightly nicer, cooler, more professional and more
    //: modern."
    //:
    //: The halo is drawn at `graphNodeRadius(d) + 6`, so the factor that takes
    //: the core exactly out to it is `(r + 6) / r`, and that is a different
    //: number for every node: 1.67 on a 9px leaf, 1.30 on a 20px hub. A single
    //: hard-coded scale in the stylesheet would overshoot the small nodes and
    //: barely move the large ones, which is the opposite of the effect. CSS
    //: cannot compute it either (`r` is an attribute, not a value CSS can read
    //: back), so the arithmetic is done here, where the radius is known, and
    //: handed to the stylesheet as a custom property.
    //:
    //: `.style()` and not a `style=` attribute: the CSP refuses inline style
    //: attributes, and d3's `.style` goes through `setProperty` on the
    //: element, which it allows.
    .style("--graph-hover-scale", (d) => {
      const r = graphNodeRadius(d);
      return r > 0 ? (r + 6) / r : 1;
    })
    // A pin restored above (fx/fy set from graph_pin_x/graph_pin_y) needs
    // the same held-look the dblclick handler gives a pin made live, 
    // otherwise a reload shows the node correctly *held in place* with no
    // visual sign it's pinned at all.
    .classed("graph-held", (d) => !graphLayoutIsComputed() && d.fx != null)
    .call(
      d3
        .drag()
        //: A drag never starts in a computed layout. `filter` rather than a
        //: guard inside `start`: d3-drag's own filter is what decides whether
        //: the gesture exists at all, so the pointer keeps its normal
        //: behaviour (the zoom behaviour's pan) instead of being captured by
        //: a drag that then declines to do anything.
        .filter((event) => !graphLayoutIsComputed() && !event.button && !event.ctrlKey)
        .on("start", (event, d) => {
          if (!event.active) graphSimulation?.alphaTarget(0.3).restart();
          // Real bug, found live while testing the pin-persistence feature
          // below: **an ordinary click is a zero-distance drag**, d3-drag
          // fires start/end on any mousedown+mouseup, moved or not, and
          // this handler used to set/clear `d.fx` on *every* click
          // unconditionally, node-being-dragged included. A double-click's
          // own two constituent clicks each ran a full drag start/end
          // cycle *before* the dblclick handler ever saw `d.fx`, which
          // cleared a pre-existing pin both times, so the dblclick
          // handler always found `d.fx === null` and could only ever pin,
          // never unpin, no matter what the node's real state was.
          // Remembered here and restored at "end" below, the same care
          // `graphDragPinned` already gives every *other* node.
          d.wasPinnedBeforeThisDrag = d.fx != null;
          //: Shift is the pin (INBOX 96). Read at the start of the gesture,
          //: not at its end, so a modifier pressed or released mid-drag
          //: cannot change what the gesture meant halfway through.
          d.dragShift = Boolean(event.sourceEvent && event.sourceEvent.shiftKey);
          // Where this gesture began, so "end" can tell a placement from a
          // bare click: see its own comment.
          d.dragStartX = d.x;
          d.dragStartY = d.y;
          d.fx = d.x;
          d.fy = d.y;
          // **Everything else stands still for the length of the drag.**
          // Reported: "how does the drag to connect work if the nodes are
          // constantly pushed away from each other?" It didn't, and that is
          // the honest answer: reheating the simulation set every *other*
          // note moving at exactly the moment you were trying to aim at one.
          // The code below already carried a workaround for the symptom
          // (remembering the lit target rather than hit-testing at release,
          // because the target moved out from under the pointer); this
          // removes the cause. Aiming at a moving target is not a gesture, it
          // is a reflex test.
          //
          // Pinned by hand here rather than by stopping the simulation,
          // because the ticks are what keep the edges attached to the node
          // you *are* dragging. And only the nodes this pins are released, 
          // a note double-clicked to hold its place stays held, which is the
          // whole point of that gesture.
          graphDragPinned = [];
          for (const other of nodes) {
            if (other === d || other.fx != null) continue;
            other.fx = other.x;
            other.fy = other.y;
            graphDragPinned.push(other);
          }
        })
        .on("drag", (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
          // Drag-to-link (§9): light up whatever this note is currently over,
          // so the gesture says what it will do *before* it does it. Without
          // this, dropping is a guess and every miss is an accidental link.
          graphDropTarget = graphNodeUnder(d, event);
          nodeGroups.classed("graph-drop-target", (other) => other === graphDropTarget);
        })
        // A regular function, not an arrow: `d3.select(this)` below needs the
        // dragged node's own element, and d3 supplies it as `this`. An arrow
        // would silently close over the module scope instead and the
        // held-look would be applied to nothing.
        .on("end", function (event, d) {
          if (!event.active) graphSimulation?.alphaTarget(0);
          // **The note that was lit, not the one under the cursor now.**
          // Dragging reheats the simulation, so every other node is still
          // drifting: between the last mousemove and the mouse-up the target
          // moves out from under the pointer, and a fresh hit test at release
          // finds nothing. Driven in a browser: the highlight appeared and the
          // link was never made, every time.
          //
          // Using the remembered target also matches what the person saw. The
          // node lit up; releasing links *that* one. A gesture that can light
          // one note and link another would be worse than one that missed.
          const over = graphDropTarget;
          graphDropTarget = null;
          nodeGroups.classed("graph-drop-target", false);
          if (over) linkByDrop(d, over);
          // Let the layout breathe again, but only the nodes this drag
          // pinned. A node the user held with a double-click keeps its place.
          for (const other of graphDragPinned) {
            other.fx = null;
            other.fy = null;
          }
          graphDragPinned = [];
          if (tree) return; // a laid-out tree keeps its shape

          // **Dragging a note places it, and it stays placed.** Reported
          // directly: "the way connections are made feels more annoying and
          // manual", "the main graph view, while cool to look at, is soooooo
          // annoying to use", "the gravity and separation in the main graph
          // view are annoying".
          //
          // This line used to be `d.fx = null; d.fy = null`, the node you
          // had just dragged somewhere was handed straight back to the
          // simulation, which pulled it off to wherever the forces wanted it.
          // Holding a note where you put it required a *double-click*, a
          // gesture nothing on screen mentions. So the honest description of
          // the old behaviour is: the one obvious way to arrange the map did
          // not arrange it, and the way that did was invisible.
          //
          // A drag is an intentional placement, the most deliberate gesture
          // in the whole view, so it is treated as one. Double-click keeps
          // its meaning and becomes the *inverse*: hand this note back to
          // the layout. That is a better pairing than the old one anyway,
          // because "let go of this" is the rarer action and the one worth
          // hiding behind a second gesture.
          //
          // A drag that never moved is not a placement. d3-drag fires
          // start/end on a bare click (the bug the "start" handler above
          // documents at length), and pinning every note anyone clicked on
          // would freeze the map by accident.
          const movedFar =
            Math.abs(d.x - d.dragStartX) > 2 || Math.abs(d.y - d.dragStartY) > 2;
          //: **A plain drag places a note; Shift pins it.** This block used
          //: to pin on any drag over 2px, and the long comment above records
          //: why: before it, a released note was handed straight back to the
          //: simulation and pulled off to wherever the forces wanted, so
          //: arranging the map was impossible.
          //:
          //: The owner has now asked for the other end of that (INBOX 96):
          //: "I move a node a little and then I have to unpin it and there's
          //: got to be a better way." Both complaints are satisfied by the
          //: same rule, and the reason is that releasing is not the same as
          //: snapping back: the simulation's alpha is already decaying at
          //: this point, so a released node settles *from where it was
          //: dropped*, with its neighbours, instead of being yanked to a
          //: fresh solution. Placement without permanence is what the map
          //: wanted all along; a pin, for the notes that must not move, is
          //: Shift and drag, or the node menu.
          const pinning = d.dragShift || d.wasPinnedBeforeThisDrag;
          if (!pinning) {
            d.fx = null;
            d.fy = null;
          } else if (movedFar && !d.isGroup) {
            // Same persistence the double-click pin has always used, so a
            // map you arranged is still arranged after a reload, which is
            // most of what "make my own thought process map" means.
            d3.select(this).classed("graph-held", true);
            d.graph_pin_x = d.fx;
            d.graph_pin_y = d.fy;
            apiJson(`/graph/pin/${d.id}`, {
              method: "PUT",
              body: JSON.stringify({ x: d.graph_pin_x, y: d.graph_pin_y }),
            }).catch(() => {
              // Best-effort, exactly as the double-click path already is: the
              // in-memory placement above has already taken effect, so a
              // failed save costs the reload and nothing else.
            });
          }
          delete d.wasPinnedBeforeThisDrag;
          delete d.dragShift;
        })
    )
    .on("click", (event, d) => {
      // Same treatment as an entity node: view-only for this first pass, 
      // opening a document from here would need the Library's own
      // document-editor navigation, not a note's, and that's a separate
      // change from making the node visible and connected in the first
      // place.
      if (d.isGroup || d.type === "entity" || d.type === "document") return;
      // Trace is a *mode*: while it is on, clicking the map picks the two ends
      // rather than opening notes. This branch is the whole reason Trace was
      // unusable: `traceModeActive` was set and then consulted nowhere, so
      // the map stayed inert and the only way to choose a note was two
      // select boxes listing every note in the notebook by its first words.
      if (traceModeActive) {
        event.stopPropagation();
        pickTraceEnd(d);
        return;
      }
      // Same gap Trace had before the branch above: the popup's own "Link"
      // button sets `linkSource` and its toast says "click another note on
      // the map to link them", but nothing here ever read `linkSource` -
      // so that click just opened the second note's popup instead of
      // completing the link. Reported directly ("doesn't properly function
      // when I try to click on another note to link it").
      if (linkSource !== null) {
        event.stopPropagation();
        beginOrCompleteLink(d);
        return;
      }
      openGraphPopup(event, d);
    })
    // Double-click pins a node where it is; again releases it (Wave M).
    // Persisted server-side (PUT /graph/pin/{id}) so the pin survives a
    // reload, not just this session, ROADMAP §87.1's own audit named the
    // in-memory-only version as the gap. Group nodes (tree/radial layout's
    // synthetic category rows) have no backing note to persist against, so
    // they keep the old in-memory-only behaviour.
    .on("dblclick", function (event, d) {
      event.stopPropagation(); // don't also zoom
      //: In a tree, a ring or an arc every node is already held at a computed
      //: position, so "unpin" would release it into a simulation that then
      //: re-solves the whole board: the reported "I test double clicked on a
      //: node and it broke them all out of position".
      if (graphLayoutIsComputed()) return;
      const wasPinned = d.fx != null;
      if (wasPinned) {
        d.fx = null;
        d.fy = null;
        d3.select(this).classed("graph-held", false);
      } else {
        d.fx = d.x;
        d.fy = d.y;
        d3.select(this).classed("graph-held", true);
      }
      if (d.isGroup) return;
      d.graph_pin_x = wasPinned ? null : d.fx;
      d.graph_pin_y = wasPinned ? null : d.fy;
      apiJson(`/graph/pin/${d.id}`, {
        method: "PUT",
        body: JSON.stringify({ x: d.graph_pin_x, y: d.graph_pin_y }),
      }).catch(() => {
        // Best-effort: a failed save leaves the pin working for this
        // session (the in-memory fx/fy above already took effect) and
        // simply not surviving a reload, the same degraded-but-working
        // shape this feature had before persistence existed at all.
      });
    });

  // A soft outer halo behind each node, gives the map more depth and makes
  // busy hub notes read as brighter (visual polish, user request).
  nodeGroups
    .append("circle")
    .attr("class", "graph-halo")
    .attr("r", (d) => graphNodeRadius(d) + 6)
    .attr("fill", nodeColour);

  nodeGroups
    .append("circle")
    .attr("class", "graph-core")
    .classed("graph-group", (d) => Boolean(d.isGroup))
    // A differently-shaped node was the roadmap's own suggestion (item 34)
    // for telling an entity apart from a note at a glance; a dashed ring is
    // the version that doesn't need a second SVG shape (a <rect> sized and
    // centred to match graphNodeRadius) for one node kind.
    .classed("graph-node-entity", (d) => d.type === "entity")
    .classed("graph-node-document", (d) => d.type === "document")
    .attr("r", graphNodeRadius)
    .attr("fill", nodeColour)
    .classed("graph-pinned", (d) => d.pinned)
    // Well-connected notes get a highlighted ring so the "hubs" of your
    // notebook stand out at a glance.
    .classed("graph-hub", (d) => (graphAdjacency.get(d.id)?.size || 0) >= 3);

  // Apply the premium orb shine over the core for a 3D tactile aesthetic
  nodeGroups
    .append("circle")
    .attr("class", "graph-orb-shine")
    .attr("r", graphNodeRadius)
    .attr("fill", "url(#orb-shine)")
    .attr("pointer-events", "none");
  // A star badge, so favourites are identifiable at a glance. Said as
  // "Favourite" rather than "Pinned" for the reason the popup's own note
  // below records: one flag, one name, everywhere.
  nodeGroups
    .filter((d) => d.pinned)
    .append("text")
    .attr("class", "graph-pin-badge")
    .attr("dy", (d) => -graphNodeRadius(d) - 4)
    .text("Favourite");
  // Native tooltip: full preview + category + how connected it is.
  nodeGroups.append("title").text((d) => {
    const links = graphAdjacency.get(d.id)?.size || 0;
    return (
      `${d.preview}\n[${d.category}] · ${links} connection${links === 1 ? "" : "s"}` +
      `${d.access_count ? ` · used ${d.access_count}×` : ""}`
    );
  });
  // Where the label goes is the difference between a readable tree and a
  // pile of overlapping text. Under the node is right for the web, where
  // nodes are spread in two dimensions; in a tree the rows are only
  // TREE_ROW apart, so it has to sit *beside* the node instead.
  const labelLayer = canvas.append("g").attr("class", "graph-label-layer");
  const labelGroups = labelLayer.selectAll("g").data(nodes).join("g");
  const labels = labelGroups
    .append("text")
    .attr(
      "class",
      (d) =>
        `graph-label${tree ? " graph-label-tree" : ""}` +
        `${tree && d.isGroup ? " graph-label-group" : ""}`
    )
    .text((d) => {
      // A radial's labels stick out of every side, so their length is what
      // decides how far the view has to zoom out; a tree's only extend
      // right, into space the columns already reserve.
      // Radial labels are what decide how far the view has to zoom out, and
      // the two written down a *shared* spoke, a category's, and a note that
      // has a reply hanging off it, are the ones that have to stay short.
      const limit = !tree
        ? 22
        : tree.arc
          ? ARC_LABEL_LIMIT
          : !tree.radial
            ? 30
            : d.isGroup || d.shared
              ? RADIAL_STEM
              : 16;
      return d.preview.length > limit ? d.preview.slice(0, limit - 1) + "…" : d.preview;
    });
  if (!tree) {
    labels.attr("dy", (d) => graphNodeRadius(d) + 13);
  } else if (tree.arc) {
    // Every node sits on one baseline, so a label straight above or below it
    // would collide with its neighbours within a single ARC_STEP. Tilted and
    // pivoted on its own anchor point (not the origin), it reads outward from
    // the node instead of overlapping the one next to it.
    //
    // Reported directly, with a screenshot: tilted *upward* (the original
    // `rotate(-40, ...)`), every label sat in exactly the space `arcPath`'s
    // connection lines curve through above the baseline, the labels and
    // the arcs they were meant to sit beside were fighting for the same
    // strip of the map. Measured before touching anything: 60 of 61 labels
    // had a bounding box overlapping a `.graph-edge`. Flipping the tilt to
    // point *down* moves every label into the empty half of the row, the
    // arcs never dip below the baseline, while keeping the same
    // anti-collision shape (still angled and reading outward, not stacked
    // straight down onto the next node).
    labels
      .attr("x", (d) => graphNodeRadius(d) + 6)
      .attr("y", 0)
      .attr("dy", "0.31em")
      // Steeper than the original 40°, more vertical, less horizontal reach
      // per character: so a label's own end lands closer to underneath its
      // node instead of drifting into the next node's slot (see ARC_STEP above).
      .attr("transform", (d) => `rotate(58, ${graphNodeRadius(d) + 6}, 0)`)
      .style("text-anchor", "start");
  } else if (tree.radial) {
    // Rotated to its own radius and flipped on the left half, or every label
    // past the halfway point reads upside down. The hub is the exception: it
    // has no meaningful direction to point in, and radiating from radius 0
    // put it straight through whichever category shared its angle.
    labels
      .attr("dy", (d) => (d.depth ? "0.31em" : graphNodeRadius(d) + 13))
      .attr("transform", (d) => {
        if (!d.depth) return null;
        const degrees = ((d.angle || 0) * 180) / Math.PI - 90;
        return `rotate(${degrees})${radialFlip(d) ? " rotate(180)" : ""}`;
      })
      // The offset is an `x` *inside* the flipped frame, not a translate
      // outside it: translating by −out and then rotating 180° sends the
      // label back across the node towards the centre, which is how the hub's
      // name ended up printed over a category's.
      .attr("x", (d) => {
        if (!d.depth) return 0;
        const out = graphNodeRadius(d) + 6;
        return radialFlip(d) ? -out : out;
      })
      // A style, not an attribute: `.graph-node text` sets `text-anchor:
      // middle` in the stylesheet, and a rule always beats a presentation
      // attribute: set as an attr, every one of these silently stayed
      // centred and the labels overlapped the ring.
      .style("text-anchor", (d) => (!d.depth ? "middle" : radialFlip(d) ? "end" : "start"));
  } else {
    labels
      // A node with children has edges leaving it rightwards, along the line
      // its own label would sit on, and where the child is a lone reply that
      // edge runs the label's whole length. A halo hides a thin line between
      // glyphs but not between words, so it read as struck through. Every
      // branch point is labelled above its row instead; leaves, which nothing
      // leaves from, keep the label beside them.
      .attr("dy", (d) => (d.isLeaf ? "0.31em" : -graphNodeRadius(d) - 5))
      .attr("x", (d) => graphNodeRadius(d) + 7)
      .style("text-anchor", "start");
  }

  // The traced path sits above both the edges and the nodes, because it is an
  // answer drawn over the picture rather than another connection in it.
  graphTraceLayer = canvas.append("g").attr("class", "graph-trace-layer");

  // Labels toggle: when off, labels only appear on hover (declutters a big
  // map). Driven by a class so toggling never rebuilds the simulation.
  $("graph-box").classList.toggle("graph-labels-hidden", !$("graph-labels").checked);
  graphCatchUpLabels();

  // A plain-language readout of what's on screen, so the map isn't a
  // mystery: how many notes and what kinds of connections link them.
  const counts = { link: 0, thread: 0, similar: 0, filing: 0, map: 0 };
  for (const e of edges) counts[e.kind] = (counts[e.kind] || 0) + 1;
  const noteCount = nodes.filter((n) => !n.isGroup).length;
  const parts = [`${noteCount} note${noteCount === 1 ? "" : "s"}`];
  if (counts.link) parts.push(`${counts.link} link${counts.link === 1 ? "" : "s"}`);
  if (counts.thread) parts.push(`${counts.thread} thread${counts.thread === 1 ? "" : "s"}`);
  if (counts.similar) parts.push(`${counts.similar} similarity line${counts.similar === 1 ? "" : "s"}`);
  if (counts.filing) parts.push(`${counts.filing} filed under a category`);
  // "on a mind map", not "map link": the edge means this note is a node on
  // that map, and naming the relationship is the whole reason this line
  // exists rather than a legend of colours.
  if (counts.map) parts.push(`${counts.map} on a mind map`);
  // In cluster mode the structural facts replace the "bigger notes are the
  // ones you use most" hint, because they are what the colours are now saying.
  const shape =
    colourMode === "cluster" && graphStructure
      ? `, ${graphStructure.clusters.length} cluster` +
        `${graphStructure.clusters.length === 1 ? "" : "s"}` +
        (graphStructure.small_clusters
          ? ` + ${graphStructure.small_clusters} pair${
              graphStructure.small_clusters === 1 ? "" : "s"
            }`
          : "") +
        `, ${graphStructure.orphan_count} connected to nothing.`
      : layoutKind === "tree"
        ? ", filed left to right; replies branch off the note they answer."
        : layoutKind === "radial"
          ? ", categories around the centre; replies branch off the note they answer."
          : layoutKind === "arc"
            ? ", one line, filed left to right; arcs below show what answers what."
            : "";
  // The shape sentence is an *explanation*, and it was costing a full row
  // above the canvas on every layout, reported as the graph "feeling
  // squashed on my screen due to the top dock". Counts stay on the line
  // because they are facts about this notebook that change; the sentence
  // that describes how a layout works is the same every time you read it,
  // so it moves to the line's own tooltip, next to the "?" that already
  // exists for exactly this kind of thing.
  $("graph-stats").textContent = parts.join(" · ");
  $("graph-stats").title = shape ? shape.replace(/^\s*: \s*/, "") : "";

  // Hover-highlight (spotlight a note's connections). Uses the same dimming
  // pipeline as search so the two never fight each other.
  nodeGroups
    .on("mouseenter", (_event, d) => {
      if (graphIsPanning) return; // a node sliding past mid-pan isn't a hover
      graphHoveredId = d.id;
      applyGraphHighlight();
    })
    .on("mouseleave", () => {
      if (graphIsPanning) return;
      graphHoveredId = null;
      applyGraphHighlight();
    });

  if (tree) {
    // Laid out, not simulated: the paths are already drawn, so this only has
    // to place the nodes and frame the result. Same guard as the force
    // layout's own fit-on-settle below, a fresh tab visit frames the tree,
    // a legend-filter or physics-slider re-render doesn't recentre a camera
    // the user may have already zoomed in with on purpose.
    nodeGroups.attr("transform", (d) => `translate(${d.x},${d.y})`);
    labelGroups.attr("transform", (d) => `translate(${d.x},${d.y})`);
    if (!graphAutoFitDone) {
      //: Only commit the one auto-fit this view gets if the box it is being
      //: fitted to was real. On a first visit it often is not (see
      //: `boxMeasured` above), and framing a tree against the 800x540
      //: fallback is what the owner saw: a tree drawn to the wrong frame
      //: that came good only after a trip through another layout. Out of a
      //: real measurement the fit waits one frame for layout rather than
      //: spending `graphAutoFitDone` on a guess. The flag is re-checked
      //: inside, because a render that arrives in between has a better
      //: claim on the camera than this retry does.
      if (boxMeasured) {
        graphAutoFitDone = true;
        frameTree(svg, zoomBehavior, canvas, nodes, width, height, tree.radial);
      } else {
        requestAnimationFrame(() => {
          const realWidth = box.clientWidth;
          const realHeight = box.clientHeight;
          if (graphAutoFitDone || !realWidth || !realHeight) return;
          graphAutoFitDone = true;
          //: The viewBox was written from the same guess, so it is corrected
          //: here too: framing against a real size inside a fake viewBox
          //: would just move the error rather than fix it.
          svg.attr("viewBox", [0, 0, realWidth, realHeight]);
          frameTree(svg, zoomBehavior, canvas, nodes, realWidth, realHeight, tree.radial);
        });
      }
    }
  }

  let fitted = false;
  // Hoisted out of the tick: `$()` is a getElementById call, and looking the
  // same element up 300 times to read one class is measurable next to the work
  // the tick is actually for.
  const graphBox = $("graph-box");

  // Labels are the expensive half of the per-tick DOM work and are often not
  // visible: the layer fades to opacity 0 when zoomed out and the Labels
  // tickbox hides it outright. `catchUpLabels` is the other half of skipping
  // them: whatever makes them visible again calls it, so they are never left
  // stale on a settled simulation that has no further ticks to come.
  const labelsOnScreen = () =>
    labelLayer.style("opacity") !== "0"
    && !graphBox.classList.contains("graph-labels-hidden");
  let labelsStale = false;
  graphCatchUpLabels = () => {
    if (!labelsStale || !labelsOnScreen()) return;
    labelGroups.attr("transform", (d) => `translate(${d.x},${d.y})`);
    labelsStale = false;
  };

  graphSimulation?.on("tick", () => {
    // Keep the layout inside its own frame. Reported as "the graph ui is out
    // of bounds", and the mechanism is that the view is framed exactly *once*
    //, the first time the simulation settles, while the simulation itself
    // never stops for good: every drag reheats it (`alphaTarget(0.3)`), and a
    // reheated repulsion force pushes the outermost notes a little further out
    // each time. Nothing ever pulls them back, and after a few drags the notes
    // at the edge of the map are off the edge of the box, with no way to know
    // they are there.
    //
    // A clamp rather than a repeated re-fit, because a re-fit would zoom the
    // map out from under someone who had just zoomed in on purpose. This bounds
    // the world instead, so the one framing stays correct for as long as the
    // map is open. The padding is the node radius plus room for its label,
    // which is drawn below the circle, a node clamped exactly to the edge
    // would have its own name outside the frame.
    //
    // **The box is the world, not the viewport**, and that distinction was
    // the second bug. Clamping to `width`/`height` meant the simulation was
    // solving inside the visible rectangle, and a graph box is wide and short
    //, so a notebook of seventeen notes, each with a collide radius of about
    // 50px, had nowhere to go but a lattice. Reported exactly as it looked:
    // *"the graph nodes are like locked into a box"*. They were: repulsion
    // pushed everything outwards, the walls pushed back, and what settles
    // between those two is a grid.
    //
    // The world is a generous multiple of the frame instead, so the forces
    // decide the shape and the clamp only stops the endless outward drift it
    // was written for. Zoom-to-fit frames whatever they end up occupying, so
    // a bigger world costs nothing on screen.
    for (const node of nodes) {
      const pad = graphNodeRadius(node) + 28;
      node.x = Math.max(worldLeft + pad, Math.min(worldRight - pad, node.x));
      node.y = Math.max(worldTop + pad, Math.min(worldBottom - pad, node.y));
    }
    edgeLines
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);
    edgeHitLines
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);
    // The traced path joins the same nodes, so it moves with them. Cheap: it
    // is a handful of lines beside every edge in the notebook.
    positionTraceLines();
    nodeGroups.attr("transform", (d) => `translate(${d.x},${d.y})`);
    // Labels are the other half of the per-tick DOM cost, one <g> per note,
    // same as the nodes, and they are frequently not on screen: the layer
    // fades to opacity 0 when zoomed out (see the zoom handler) and the
    // Labels tickbox hides it outright. Moving something invisible is work
    // nobody can see, ~300 times per settle, on every note in the notebook.
    //
    // Their positions are restored on the next visible tick, and the
    // simulation is still running whenever the layer is turned back on
    // (a drag or a filter reheats it), so nothing can be left stale in a
    // way the user sees.
    if (labelsOnScreen()) {
      labelGroups.attr("transform", (d) => `translate(${d.x},${d.y})`);
      labelsStale = false;
    } else {
      // Remember that they are now behind the nodes, so turning them back on
      // repositions them immediately rather than waiting for the next tick.
      // Without this the labels can be left permanently where they were when
      // the layer was hidden: the simulation stops when it settles, so if
      // nothing reheats it there is no next tick to fix them, and the names
      // sit detached from their notes until something else redraws the map.
      labelsStale = true;
    }
    clusterGroups.attr("transform", (d) => {
      // One pass, not two. `d3.mean` walks the whole member list, and calling
      // it twice per cluster per tick walks every clustered note twice on
      // every one of the ~300 ticks a settle takes.
      let sx = 0;
      let sy = 0;
      for (const n of d.nodes) {
        sx += n.x;
        sy += n.y;
      }
      const count = d.nodes.length || 1;
      return `translate(${sx / count},${sy / count})`;
    });
    // Once the layout settles, frame all the notes so nothing sits off
    // the edge (Wave N: the old view often had nodes half-cropped). Only
    // for a fresh visit to the tab, though (graphAutoFitDone, set by
    // switchTab() below): every render used to re-fit unconditionally, so
    // toggling a legend filter or dragging a physics slider while looking
    // at a note you'd zoomed in on would silently recentre and rescale the
    // camera out from under you. Panning and zooming after that point is
    // the user's business; the dedicated Fit button (graph-zoom-fit) is
    // still there for "put it back".
    if (!fitted && !graphAutoFitDone && graphSimulation.alpha() < 0.08) {
      fitted = true;
      graphAutoFitDone = true;
      fitGraphToView(svg, canvas, zoomBehavior, nodes, width, height);
    }
    // Repaint the minimap as the layout settles, but not on every one of the
    // ~300 ticks a cooling simulation fires, the dots barely move between
    // frames and a full rebuild each time would cost more than the map it is
    // summarising.
    if (graphMinimapTick++ % 8 === 0) graphMinimapPaint();
  });

  // Search-highlight (Wave M): remember the selections and re-apply any
  // query that's already typed.
  graphNodeSelection = nodeGroups;
  graphEdgeSelection = edgeLines;
  graphLabelSelection = labelGroups;
  // The pickers describe the map, so they are refilled with it, and the trace
  // is redrawn, because a refresh (a new note, a new link, a layout change)
  // must not silently drop the answer on screen.
  fillTracePickers(nodes);
  drawTrace();
  applyGraphHighlight();
  //: A full paint, because this is the moment the dots are wrong: a different
  //: set of notes, at different places. A pan only moves the rectangle now
  //: (`graphMinimapFrame`), so nothing else on this path repaints them.
  graphMinimapPaint();

  // Set up temporal filter slider bounds based on data.
  //
  // Bounds used to be computed once, on the first render that had any notes,
  // behind a `window.graphSliderInitialized` flag that never reset. Every
  // later render, a new note, a refresh, a re-filed entry, kept the first
  // render's `max` forever, so any note created after that point sat beyond
  // the slider's own "all time" end and stayed permanently hidden the moment
  // the filter had ever run once. Recomputed every render now; the guard
  // below preserves what the user was actually doing with it (parked at "all
  // time", or deliberately looking at an earlier cut-off) instead of
  // snapping back to the far right on every refresh.
  const timeLabel = $("graph-time-label");
  const slider = $("graph-time-slider");
  if (data.nodes.length > 0 && slider) {
    const timestamps = data.nodes
      .map(n => new Date(n.created_at || Date.now()).getTime())
      .filter(Number.isFinite);
    const minTime = timestamps.length ? Math.min(...timestamps) : Date.now();
    const maxTime = timestamps.length ? Math.max(...timestamps) : Date.now();
    const previousMax = Number(slider.max);
    // "At the end" before this render's bounds change: i.e. no filter was
    // actually applied: is the case to keep snapped to the new end rather
    // than freeze at whatever timestamp used to be the newest note.
    const wasAtEnd = !slider.dataset.graphInit || Number(slider.value) >= previousMax;
    slider.min = minTime;
    slider.max = maxTime;
    slider.step = (maxTime - minTime) / 100 || 1;
    slider.value = wasAtEnd ? maxTime : Math.min(Number(slider.value), maxTime);
    slider.dataset.graphInit = "1";

    const renderTimeLabel = (val) => {
      if (!timeLabel) return;
      timeLabel.textContent = val >= maxTime ? "All time" : `Up to ${new Date(val).toLocaleDateString()}`;
    };

    // Tree/Radial/Arc draw category-heading and root nodes alongside real
    // notes (Force never does: it only ever has real notes/links). Those
    // headings have no `created_at` at all, so `d.created_at || Date.now()`
    // read them as "created this instant", always later than any cutoff
    // short of "All time", which hid the heading *and* every edge touching
    // it the moment the slider moved at all. A heading is organising
    // furniture, not a dated note; it and its edges should never be subject
    // to the time filter.
    const timeVisible = (d, val) =>
      d.isGroup || new Date(d.created_at || Date.now()).getTime() <= val;
    const applyTimeFilter = (val) => {
      renderTimeLabel(val);
      // Apply temporal filter without rebuilding simulation
      nodeGroups.style("visibility", d => timeVisible(d, val) ? "visible" : "hidden");
      labelGroups.style("visibility", d => timeVisible(d, val) ? "visible" : "hidden");
      edgeLines.style("visibility", d =>
        timeVisible(d.source, val) && timeVisible(d.target, val) ? "visible" : "hidden"
      );
    };

    slider.oninput = (e) => applyTimeFilter(Number(e.target.value));
    renderTimeLabel(Number(slider.value));
    // Re-apply the (possibly re-clamped) filter so a note added since the
    // last render obeys whatever cut-off the user had actually set.
    if (Number(slider.value) < maxTime) applyTimeFilter(Number(slider.value));
  }

  initGraphKeyboard();
}

// --- driving the graph from the keyboard ------------------------------------------
// The graph was the one tab that failed a keyboard-first test outright: every
// way of reaching a note was a mouse gesture, so the whole map, and the notes
// only reachable through it, was unusable without a pointer.
//
// A tab stop per node is not the answer; a big map would be hundreds of stops
// to get past. The map takes one stop, and inside it the arrow keys move to
// the nearest note in that direction, which is the way you already think about
// a map. Tab out again in one press.

let graphKeyboardId = null; // the note the keyboard is "on", or null

function graphNodeById(id) {
  return (graphNodesRef || []).find((n) => n.id === id) || null;
}

// The nearest node roughly in `direction` from the current one. Scored by
// distance, penalised by how far off the axis it sits, so "right" prefers a
// node to the right over a nearer one that happens to be below.
function graphNeighbourInDirection(from, direction) {
  const vectors = { right: [1, 0], left: [-1, 0], up: [0, -1], down: [0, 1] };
  const [dirX, dirY] = vectors[direction] || vectors.right;
  let best = null;
  let bestScore = Infinity;
  for (const node of graphNodesRef || []) {
    if (node === from) continue;
    const dx = node.x - from.x;
    const dy = node.y - from.y;
    const along = dx * dirX + dy * dirY;
    if (along <= 0) continue; // behind us
    const across = Math.abs(dx * dirY - dy * dirX);
    const score = along + across * 2.5;
    if (score < bestScore) {
      bestScore = score;
      best = node;
    }
  }
  return best;
}

function focusGraphNode(node, { announceIt = true } = {}) {
  if (!node) return;
  graphKeyboardId = node.id;
  // Reuse the hover spotlight: keyboard focus and pointer hover mean the same
  // thing here, and two highlight systems would fight each other.
  graphHoveredId = node.id;
  applyGraphHighlight();
  if (graphNodeSelection) {
    graphNodeSelection.classed("graph-keyfocus", (d) => d.id === node.id);
  }
  // The canvas renderer rings `graphKeyboardId` in the same pass as the hover
  // ring, so moving the keyboard focus is one more frame.
  if (typeof gcRequestDraw === "function") gcRequestDraw();
  if (announceIt) {
    const links = graphAdjacency?.get(node.id)?.size || 0;
    announce(
      `${node.preview}. ${node.category}. ` +
        `${links} connection${links === 1 ? "" : "s"}. Press Enter to open.`
    );
  }
}

// The popup positions itself from a click's coordinates, so a keyboard open
// has to supply the equivalent point: where the node actually is on screen.
function graphNodeScreenPoint(node) {
  const box = document.getElementById("graph-box");
  const rect = box ? box.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
  // Read from the zoom behaviour rather than by parsing a `transform`
  // attribute off a `<g>`. The old version did the latter, which only ever
  // worked on the SVG renderer and quietly mis-parsed a transform d3 had
  // written as a matrix; `d3.zoomTransform` is the same number on either
  // renderer because both attach the same `d3.zoom` to their own element.
  const transform = graphSvg && graphSvg.node() ? d3.zoomTransform(graphSvg.node()) : null;
  const scale = transform ? transform.k : 1;
  const tx = transform ? transform.x : 0;
  const ty = transform ? transform.y : 0;
  return {
    clientX: rect.left + tx + node.x * scale,
    clientY: rect.top + ty + node.y * scale,
  };
}

function initGraphKeyboard() {
  const box = document.getElementById("graph-box");
  if (!box || box.dataset.keyboardReady) return;
  box.dataset.keyboardReady = "1";
  box.tabIndex = 0;
  box.setAttribute("role", "application");
  box.setAttribute(
    "aria-label",
    "Map of your notes. Arrow keys move between notes, Shift with an arrow " +
      "pans the view, plus and minus zoom, 0 fits the whole map, Enter opens " +
      "a note, Escape leaves the map."
  );

  box.addEventListener("focus", () => {
    if (!graphNodesRef?.length) return;
    // **A pan is not a request to select a note.** Reported: "sometimes when
    // I scroll and pan on the graph, a random single separated and unlinked
    // note will highlight itself and show its label". This box is
    // `tabIndex = 0`, so a press anywhere on the map focuses it, and this
    // listener then handed the keyboard to `graphNodesRef[0]`, an arbitrary
    // note, while `focusGraphNode` (below) deliberately sets the *hover* id
    // too: the canvas dims every non-neighbour to 20% and draws that one
    // note's label. Measured after a single pan drag on empty map:
    // activeElement=graph-box, hovered=1, graphKeyboardId=1, and node 1 is
    // simply the first in the payload.
    //
    // `:focus-visible` is the browser's own answer to "did this focus come
    // from the keyboard", which is exactly the question: a Tab into the map
    // should land on a note, a mouse press should not. It is checked here
    // rather than by tracking pointerdown ourselves because the browser
    // already knows about every route in (Tab, shift-Tab, a script focus
    // after a keyboard action, assistive tech) and a hand-rolled flag would
    // have to learn them one bug at a time.
    if (!box.matches(":focus-visible")) return;
    const current = graphNodeById(graphKeyboardId) || graphNodesRef[0];
    focusGraphNode(current);
  });
  box.addEventListener("blur", () => {
    if (graphNodeSelection) graphNodeSelection.classed("graph-keyfocus", false);
    graphHoveredId = null;
    applyGraphHighlight();
  });

  box.addEventListener("keydown", (event) => {
    // The map's own shortcuts (arrows to move between notes, Enter/Space to
    // open one, N to step through links, +/-/0 to zoom) live on this box
    // because it's the thing with `role="application"`, but the note popup
    // and the "Grow the map" form are both DOM descendants of it too, so
    // every keystroke typed into their textareas/inputs bubbles up here as
    // well. Reported: typing in a just-grown note wouldn't take input and
    // kept reopening the note it was grown from, that was Space/Enter, on
    // every keystroke, being read as "open the currently keyboard-selected
    // node" instead of being typed. Any real text field wins outright.
    const typingTarget =
      ["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName) ||
      event.target?.isContentEditable;
    if (typingTarget) return;
    if (!graphNodesRef?.length) return;
    const current = graphNodeById(graphKeyboardId) || graphNodesRef[0];

    // Zoom and pan from the keyboard. Deliberately checked *before* the arrow
    // keys below, because Shift+arrow pans the view while a bare arrow moves
    // between notes: two different jobs on the same keys, which is the only
    // arrangement that leaves the plain arrows doing the thing this map is
    // mostly for. The characters are the ones every map on the web uses:
    // +/- to zoom, 0 to fit. `=` is listed with `+` because on a US layout
    // the plus is a shifted equals and nobody reaches for the shift.
    const zoomKeys = { "+": 1.3, "=": 1.3, "-": 1 / 1.3, _: 1 / 1.3 };
    if (Object.prototype.hasOwnProperty.call(zoomKeys, event.key) && graphSvg && graphZoom) {
      event.preventDefault();
      graphSvg.transition().duration(200).call(graphZoom.scaleBy, zoomKeys[event.key]);
      announce(zoomKeys[event.key] > 1 ? "Zoomed in." : "Zoomed out.");
      return;
    }
    if (event.key === "0" && graphNodesRef.length) {
      event.preventDefault();
      fitGraphToView(graphSvg, graphCanvas, graphZoom, graphNodesRef, graphDims.w, graphDims.h);
      announce("Fitted the whole map to view.");
      return;
    }
    const panBy = { ArrowRight: [-80, 0], ArrowLeft: [80, 0], ArrowUp: [0, 80], ArrowDown: [0, -80] };
    if (event.shiftKey && panBy[event.key] && graphSvg && graphZoom) {
      event.preventDefault();
      const [dx, dy] = panBy[event.key];
      // translateBy works in the transform's own (pre-scale) units, so a
      // fixed step would move a hair at high zoom and half the map at low.
      // Dividing by k keeps the movement a constant number of screen pixels.
      const k = d3.zoomTransform(graphSvg.node()).k || 1;
      graphSvg.transition().duration(150).call(graphZoom.translateBy, dx / k, dy / k);
      return;
    }

    const directions = {
      ArrowRight: "right",
      ArrowLeft: "left",
      ArrowUp: "up",
      ArrowDown: "down",
    };
    // Alt+arrow is the app-wide Back/Forward shortcut (app.js's own
    // DEFAULT_SHORTCUTS): without this check, this box's own bare-arrow
    // "move to the neighbour note" handler ran first (it's the keydown
    // target while the map has focus) and consumed the keystroke with its
    // own preventDefault() before the global handler had anything clean
    // left to act on, so Alt+Left silently moved the graph selection
    // instead of navigating back. Bare arrows still work exactly as before.
    if (directions[event.key] && !event.altKey) {
      event.preventDefault();
      const next = graphNeighbourInDirection(current, directions[event.key]);
      // No node that way is not an error, say so rather than silently
      // doing nothing, which reads as the keys not working.
      if (next) focusGraphNode(next);
      else announce("No note in that direction.");
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openGraphPopup(
        { ...graphNodeScreenPoint(current), stopPropagation() {} },
        current
      );
      return;
    }
    // Step through this note's own connections: the relationship the map is
    // actually for, which "nearest in a direction" doesn't follow.
    if (event.key === "n" || event.key === "N") {
      event.preventDefault();
      const linked = [...(graphAdjacency?.get(current.id) || [])];
      if (!linked.length) {
        announce("This note has no connections.");
        return;
      }
      const seen = graphNodeById(graphKeyboardId);
      const position = linked.indexOf(seen?.id);
      const nextId = linked[(position + 1) % linked.length];
      focusGraphNode(graphNodeById(nextId));
      return;
    }
    if (event.key === "Escape") {
      box.blur();
    }
  });
}

// Zoom/pan so every node fits with a margin (Wave N).
function fitGraphToView(svg, canvas, zoomBehavior, nodes, width, height) {
  if (!nodes.length) return;
  // Reported: fit-to-view "zooms out like crazy so you only see the generic
  // cluster blobs". Two bugs, both in how the old version measured the map:
  // it bounded only the node *centres* (a node's halo, ring and the label
  // drawn below it all extend past that point, so a real graph always
  // rendered a bit outside the box this used to fit), and its scale had no
  // floor: `Math.min(3, ...)` clamps how far it can zoom IN but not how far
  // it can zoom OUT, so one node that drifted far from the rest (the collide
  // simulation allows this) could shrink everything else to specks trying to
  // fit it in frame too.
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of nodes) {
    // Same pad the force simulation's own world-clamp uses (see the comment
    // above it): node radius, the halo ring (+6) and the label drawn below
    // the circle, so a fitted node's own name is never left outside frame.
    const pad = graphNodeRadius(n) + 34;
    minX = Math.min(minX, n.x - pad);
    maxX = Math.max(maxX, n.x + pad);
    minY = Math.min(minY, n.y - pad);
    maxY = Math.max(maxY, n.y + pad);
  }
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  // A comfortable margin scales with the container instead of a flat 60px,
  // which was a sliver of a 1400px-wide window and most of a 300px panel.
  const margin = Math.min(width, height) * 0.09;
  const rawScale = Math.min(
    (width - margin * 2) / spanX,
    (height - margin * 2) / spanY
  );
  // The floor is the actual fix for "zooms out like crazy": no single
  // outlier can push the whole map below a still-readable scale.
  const scale = Math.max(0.25, Math.min(2.5, rawScale));
  const tx = width / 2 - scale * (minX + maxX) / 2;
  const ty = height / 2 - scale * (minY + maxY) / 2;
  svg
    .transition()
    .duration(500)
    .call(
      zoomBehavior.transform,
      d3.zoomIdentity.translate(tx, ty).scale(scale)
    );
}

// Dim everything except nodes that match the search box AND (when hovering)
// the hovered note plus its direct neighbours; edges stay bright only when
// both ends survive. Search (Wave M) and hover-spotlight share one pass so
// they can't contradict each other.
// Set by "≈ Similar" to spotlight an explicit set of notes; cleared by the
// next search or refresh.
let graphHighlightIds = null;

function applyGraphHighlight() {
  const query = $("graph-search").value.trim().toLowerCase();
  if (query) graphHighlightIds = null; // typing takes over the spotlight
  // Reported: no way to cancel the "≈ Similar" highlight - it only ever
  // reset as a side effect of something else (typing over it, or a full
  // refresh). Same shape as #graph-focus-clear: shown exactly while there's
  // something to clear, synced here since this is the one function every
  // path that sets or resets graphHighlightIds already runs through.
  $("graph-highlight-clear")?.classList.toggle("hidden", !graphHighlightIds);
  // The canvas renderer computes the same four-way spotlight (search, the
  // "similar notes" set, a traced path, the hover neighbourhood) inside its own
  // draw, from this same state, see `gcHighlight`. There are no selections to
  // classed() there, so all this has to do is ask for a frame.
  if (graphRenderer() === "canvas" && typeof gcRequestDraw === "function") {
    gcRequestDraw();
    return;
  }
  if (!graphNodeSelection) return;
  // A traced path is the strongest spotlight there is: it is the answer to a
  // question that was just asked, so it outranks a search box someone typed in
  // earlier. Everything not on the chain dims, which is what makes a six-note
  // route legible on a map of three hundred.
  const onPath = graphTrace ? new Set(graphTrace.ids) : null;
  const searchOk = (d) =>
    onPath
      ? onPath.has(d.id)
      : graphHighlightIds
        ? graphHighlightIds.has(d.id)
        : !query || d.preview.toLowerCase().includes(query);

  const neighbours =
    graphHoveredId != null && graphAdjacency
      ? graphAdjacency.get(graphHoveredId)
      : null;
  const hoverOk = (id) =>
    neighbours == null || id === graphHoveredId || neighbours.has(id);
  // After forceLink binds, edge.source/target are node objects, not ids.
  const idOf = (end) => (end && end.id != null ? end.id : end);

  const isSearchActive = !!(query || graphHighlightIds || onPath);
  graphNodeSelection.classed(
    "graph-dim",
    (d) => !(searchOk(d) && hoverOk(d.id))
  );
  graphNodeSelection.classed(
    "graph-match",
    (d) => isSearchActive && searchOk(d)
  );
  graphNodeSelection.classed("graph-focus", (d) => d.id === graphHoveredId);
  // Labels live in their own layer, a sibling of the node circles rather
  // than nested inside them (graphNodeSelection above), so a hovered node
  // can't reveal its label through a CSS descendant selector, it has to
  // be told directly which label is its own.
  graphLabelSelection.classed("graph-focus", (d) => d.id === graphHoveredId);
  graphEdgeSelection.classed("graph-dim", (d) => {
    const s = idOf(d.source);
    const t = idOf(d.target);
    const bySearch =
      !(query || graphHighlightIds || onPath) ||
      (searchOk(d.source) && searchOk(d.target));
    const byHover =
      neighbours == null || s === graphHoveredId || t === graphHoveredId;
    return !(bySearch && byHover);
  });
}

// --- graph node popup: edit a note without leaving the map -------------------

let graphPopupId = null;
let graphPopupAnchor = null;
//: What the note said when it arrived. Save is a primary action and a primary
//: action that is always on screen stops meaning "do this": the panel is
//: opened to *read* a note far more often than to edit one (GRAPH_PLAN Phase
//: 6). Comparing against the loaded text, rather than listening for any
//: keystroke, means typing a word and deleting it again puts the button away.
let graphPopupClean = { content: "", tags: "" };

//: The header's identity line, the muted meta line under it, and the Save
//: gate all read the same entry, so they are filled from one place.
function renderGraphPopupHeader(entry, node) {
  const titleEl = $("graph-popup-title");
  //: The title used to be the *category*, with the category also sitting in
  //: the chip row below it: the note's own name was nowhere on a panel about
  //: that note. `entry.title` when the AI (or the owner) gave it one, the
  //: first line otherwise, which is what every other note surface shows.
  const firstLine =
    typeof notePreviewText === "function"
      ? notePreviewText(entry.content || "").split("\n")[0]
      : (entry.content || "").split("\n")[0];
  titleEl.textContent =
    entry.title || firstLine.slice(0, 80).trim() || node.category || "Note";
  //: The title is ellipsised to one line now, so the whole of it has to be
  //: reachable some other way: hover is the cheapest, and it is what every
  //: other truncated label in this app already does.
  titleEl.title = titleEl.textContent;

  const confidence = $("graph-popup-confidence");
  //: `> 0`, not `typeof === "number"`: a note the AI never filed carries 0,
  //: and "0%" beside a title reads as a verdict on the note rather than as
  //: "there is no figure here". The old chip had the same bug and said
  //: "0% confident" out loud.
  const hasConfidence = typeof entry.ai_confidence === "number" && entry.ai_confidence > 0;
  confidence.classList.toggle("hidden", !hasConfidence);
  if (hasConfidence) {
    confidence.textContent = `${entry.ai_confidence}%`;
    confidence.title = `The AI was ${entry.ai_confidence}% confident filing this note`;
  }

  const category = $("graph-popup-category");
  const name = entry.category || node.category || "";
  category.classList.toggle("hidden", !name);
  if (name) setLabel(category, `ph:folders ${name}`);
}

async function openGraphPopup(event, node) {
  event.stopPropagation();
  graphPopupId = node.id;
  const popup = $("graph-popup");
  const status = $("graph-popup-status");
  status.textContent = "";
  status.classList.remove("error");
  //: The node's own preview while the note is on its way, not its category:
  //: the title says what this note is now, and a placeholder reading
  //: "Uncategorised" for the length of a fetch is a wrong answer to that
  //: question rather than an absent one. `preview` is the same string the
  //: canvas paints beside the node (`gcLabelText`), so the panel opens
  //: saying what the map said.
  const mapTitle = $("graph-popup-title");
  mapTitle.textContent = node.preview || node.category || "Note";
  mapTitle.title = mapTitle.textContent;
  $("graph-popup-confidence").classList.add("hidden");
  $("graph-popup-category").classList.add("hidden");
  $("graph-popup-info").textContent = "";
  $("graph-popup-content").value = "Loading…";
  $("graph-popup-tags").value = "";
  graphPopupClean = { content: "Loading…", tags: "" };
  syncGraphPopupSave();
  popup.classList.remove("hidden");

  // Remember where the click was: the popup has to be placed again once the
  // note arrives, because the info chips and action buttons render afterwards
  // and grow it. Positioning only on open is what let a tall note hang off
  // the bottom of the map.
  graphPopupAnchor = { x: event.clientX, y: event.clientY };
  placeGraphPopup();

  const entry = await apiJson(`/entries/${node.id}`).catch(() => null);
  if (!entry || graphPopupId !== node.id) {
    if (graphPopupId === node.id) {
      $("graph-popup-content").value = "";
      status.textContent = "Couldn't load this note.";
      status.classList.add("error");
    }
    return;
  }
  $("graph-popup-content").value = entry.content;
  $("graph-popup-tags").value = (entry.tags || []).join(", ");
  graphPopupClean = { content: entry.content, tags: (entry.tags || []).join(", ") };
  syncGraphPopupSave();
  renderGraphPopupHeader(entry, node);
  renderGraphPopupInfo(entry);
  renderGraphPopupMedia(entry);
  renderGraphPopupActions(entry);
  //: The editor is sized to the note it just received, not to a fixed slot.
  //: `autoGrow` measures `scrollHeight`, so it has to run after the value is
  //: set and while the panel is visible, which it now is.
  if (typeof autoGrow === "function") autoGrow($("graph-popup-content"));
  placeGraphPopup(); // now that it's at its real height
  $("graph-popup-content").focus();
}

//: Save appears when the content or the tags differ from what loaded, and
//: goes away again when they match. Called from the two fields' `input`
//: events (app.js wires them) and after every load or save.
function syncGraphPopupSave() {
  const save = $("graph-popup-save");
  if (!save) return;
  const dirty =
    $("graph-popup-content").value !== graphPopupClean.content ||
    $("graph-popup-tags").value !== graphPopupClean.tags;
  save.classList.toggle("hidden", !dirty);
}

// A link edge's own management panel, asked for directly: "a visual way
// to see the reasons for each connection and a way to manage/add/remove/
// edit them." Clicking a `kind: "link"` edge (see `renderGraph`'s own
// click handler) opens this rather than only ever showing the reason on
// hover. A dynamic overlay, the same `promptDialog`/`confirmDialog`
// pattern, rather than fixed markup, this is the one place in the app
// that edits a *connection* rather than a note or a whiteboard item, so it
// doesn't share a container with either.
function openGraphLinkPanel(edge, nodes) {
  const sourceId = typeof edge.source === "object" ? edge.source.id : edge.source;
  const targetId = typeof edge.target === "object" ? edge.target.id : edge.target;
  const sourceNode = nodes.find((n) => n.id === sourceId);
  const targetNode = nodes.find((n) => n.id === targetId);
  // A raw slice cut mid-word with nothing to say so ("This g" from "This
  // guide") reads as broken text, not a shortened title, trim to the last
  // whole word instead, and only add the ellipsis when something was
  // actually cut.
  const label = (n, id) => {
    const text = n?.preview || `Note ${id}`;
    if (text.length <= 60) return text;
    const cut = text.slice(0, 60);
    return `${cut.slice(0, cut.lastIndexOf(" ") + 1 || 60).trimEnd()}…`;
  };

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay confirm-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Manage this connection");

  const card = document.createElement("div");
  card.className = "card modal-card confirm-card graph-link-panel";

  // Two notes on their own lines, not one run-on sentence joined by an
  // arrow: reported as unreadable once both previews ran long enough to
  // wrap, since nothing showed which half belonged to which note.
  const title = document.createElement("div");
  title.className = "confirm-text graph-link-panel-title";
  const sourceLine = document.createElement("div");
  sourceLine.textContent = label(sourceNode, sourceId);
  const arrow = document.createElement("div");
  arrow.className = "muted graph-link-panel-arrow";
  arrow.textContent = "↕ connected to";
  const targetLine = document.createElement("div");
  targetLine.textContent = label(targetNode, targetId);
  title.append(sourceLine, arrow, targetLine);
  card.appendChild(title);

  if (edge.reason_confidence != null) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = `Deduced (${Math.round(edge.reason_confidence * 100)}% confidence): editing replaces it with your own words.`;
    card.appendChild(note);
  }

  const textarea = document.createElement("textarea");
  textarea.className = "graph-link-panel-reason";
  textarea.placeholder = "Why are these connected? (optional)";
  textarea.value = edge.reason || "";
  textarea.rows = 3;
  card.appendChild(textarea);

  const returnFocus = document.activeElement;
  const close = () => {
    overlay.remove();
    returnFocus?.focus?.();
  };

  const row = document.createElement("div");
  row.className = "row confirm-actions";

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.textContent = "Save";

  const generateBtn = document.createElement("button");
  generateBtn.type = "button";
  generateBtn.className = "ghost";
  setLabel(generateBtn, "ph:magic-wand Generate");
  generateBtn.addEventListener("click", async () => {
    generateBtn.disabled = true;
    generateBtn.textContent = "Generating…";
    try {
      const res = await apiJson(`/entries/${sourceId}/links/${edge.id}/generate-reason`, { method: "POST" });
      textarea.value = res.reason;
    } catch (e) {
      toast(e.message, true);
    } finally {
      generateBtn.disabled = false;
      setLabel(generateBtn, "ph:magic-wand Generate");
    }
  });

  saveBtn.addEventListener("click", async () => {
    await apiJson(`/entries/${sourceId}/links/${edge.id}/reason`, {
      method: "PUT",
      body: JSON.stringify({ reason: textarea.value.trim() || null }),
    }).catch((e) => toast(e.message, true));
    toast("Saved.");
    close();
    renderGraph();
  });

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "ghost danger";
  setLabel(removeBtn, "ph:trash Remove link");
  removeBtn.addEventListener("click", async () => {
    if (!(await confirmDialog("Remove this connection entirely?\n\nThe two notes are untouched, only the link between them goes."))) return;
    //: Captured before the delete, because after it there is nothing left to
    //: read the other end and the reason off.
    const targetId = edge.target?.id ?? edge.target;
    const linkType = edge.link_type || null;
    const reason = edge.reason || null;
    await apiJson(`/entries/${sourceId}/links/${edge.id}`, { method: "DELETE" }).catch((e) => toast(e.message, true));
    //: **A link is the one thing in this notebook you cannot rebuild from
    //: memory.** Which two notes, in which direction, with what reason, a
    //: confirm dialog is not an undo, and this had only the dialog. The
    //: recreated link gets a new id, so the redo closure re-reads it rather
    //: than assuming the old one comes back.
    let recreatedId = null;
    pushUndo(
      "Removed a link",
      async () => {
        const made = await apiJson(`/entries/${sourceId}/links`, {
          method: "POST",
          body: JSON.stringify({ target_id: targetId, link_type: linkType, reason }),
        });
        recreatedId = made.link_id ?? made.id ?? null;
        renderGraph();
      },
      async () => {
        if (recreatedId === null) return;
        await apiJson(`/entries/${sourceId}/links/${recreatedId}`, { method: "DELETE" });
        renderGraph();
      }
    );
    toast("Link removed.");
    close();
    renderGraph();
  });

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "ghost";
  cancelBtn.textContent = "Close";
  cancelBtn.addEventListener("click", close);

  row.append(saveBtn, generateBtn, removeBtn, cancelBtn);
  card.appendChild(row);
  overlay.appendChild(card);
  wireBackdropClose(overlay, () => close());
  document.body.appendChild(overlay);
  textarea.focus();
}

// Show a note's images in the popup, biggest reason being sketches.
//
// A sketch is stored as a note carrying the caption plus a PNG attachment, so
// on the map it is an ordinary node and the popup showed its caption and
// nothing else. There was no way to see the drawing from the graph at all, 
// "Open" only took you to the Notes tab, where you still had to find the card
// and click its thumbnail. Reported as "sketches don't open from the graph",
// and that is exactly right: the one thing the note is *about* was missing.
//: **And the same for everything that is not a picture.** Reported: "files and
//: attachments dont render in the timeline and popups." This popup and the
//: timeline's both filtered to `is_image` and dropped the rest, so a note
//: whose whole point is the PDF attached to it opened a popup with nothing in
//: it: no hint that anything was attached, which reads as the note having
//: lost the file. `fileCard` is the app's own control for an attached file
//: (the note cards, the chat transcript and the widgets all use it); this
//: surface was the one place a file did not appear at all.
function renderGraphPopupMedia(entry) {
  const box = $("graph-popup-media");
  box.replaceChildren();
  const all = entry.attachments || [];
  const images = all.filter((a) => a.is_image);
  const files = all.filter((a) => !a.is_image);
  box.classList.toggle("hidden", all.length === 0);
  if (!all.length) return;
  for (const attachment of files) {
    box.appendChild(
      fileCard(attachment.filename || attachment.name || "", attachment.url || `/files/${attachment.id}`)
    );
  }
  for (const attachment of images) {
    const img = document.createElement("img");
    img.className = "graph-popup-thumb";
    img.alt = attachment.filename;
    img.title = `${attachment.filename}: click to view full size`;
    // The bytes need the auth header, so they arrive as an object URL rather
    // than a plain src. Cached per attachment by attachmentObjectUrl.
    attachmentObjectUrl(attachment)
      .then((url) => {
        img.src = url;
        placeGraphPopup(); // the popup just got taller
      })
      .catch(() => img.remove());
    img.addEventListener("click", () => {
      openLightbox(
        images.map((a) => ({ filename: a.filename, getUrl: () => attachmentObjectUrl(a) })),
        images.indexOf(attachment)
      );
    });
    box.appendChild(img);
  }
  //: A file card is a block with height, and this popup is placed against its
  //: own: the image path already re-places once the bytes land, and the cards
  //: need the same or the popup hangs off the edge of the map.
  placeGraphPopup();
}

// Clamp the popup inside the graph box. Called on open and again once the
// note has loaded, since the popup is taller by then.
function placeGraphPopup() {
  const popup = $("graph-popup");
  if (!graphPopupAnchor || popup.classList.contains("hidden")) return;
  const box = $("graph-box").getBoundingClientRect();
  //: **On a phone the panel is a sheet, and JS has to be the one to say so**
  //: (GRAPH_PLAN Phase 6). The position is inline `left`/`top` written here,
  //: which no stylesheet rule can override without `!important`, so a media
  //: query alone could style the sheet and never place it. The band is the
  //: app's own 600px one, spelled the same way as in the stylesheet.
  if (window.matchMedia("(max-width: 599.98px)").matches) {
    popup.classList.add("graph-popup-sheet");
    // Three quarters of the map: enough to read the note, and the map it
    // came from stays visible above it so the sheet has an origin.
    popup.style.maxHeight = `${Math.max(160, Math.round(box.height * 0.75))}px`;
    popup.style.left = "0px";
    const sheet = popup.getBoundingClientRect();
    popup.style.top = `${Math.max(0, Math.round(box.height - sheet.height))}px`;
    return;
  }
  popup.classList.remove("graph-popup-sheet");
  // Never taller than the map it sits in, beyond that the popup scrolls
  // itself rather than growing off the edge.
  popup.style.maxHeight = `${Math.max(120, box.height - 16)}px`;
  const size = popup.getBoundingClientRect();
  const left = Math.min(
    Math.max(graphPopupAnchor.x - box.left + 12, 8),
    Math.max(8, box.width - size.width - 8)
  );
  const top = Math.min(
    Math.max(graphPopupAnchor.y - box.top + 12, 8),
    Math.max(8, box.height - size.height - 8)
  );
  popup.style.left = `${left}px`;
  popup.style.top = `${top}px`;
}

//: The facts about a note, as **one muted line**.
//:
//: This was five chips (category, date, links, views, confidence) plus up to
//: six tag chips, every one of them the same weight, so the panel opened with
//: eleven equal marks above the note it was about, and the provenance ones
//: (confidence, views) shouted as loudly as the category. Reported with a
//: screenshot, INBOX 59.
//:
//: Category and confidence moved into the header where identity belongs; the
//: tags were already in the tags field two rows down, spelled a second way.
//: What is left is the three facts that are genuinely the same rank: when it
//: was made, how connected it is, how often it has been read. A `·`-joined
//: muted line says "the same kind of small fact" in a way five bordered chips
//: cannot.
function renderGraphPopupInfo(entry) {
  const box = $("graph-popup-info");
  const links = (entry.links || []).length;
  const views = entry.access_count || 0;
  const parts = [
    new Date(entry.created_at).toLocaleDateString(),
    `${links} link${links === 1 ? "" : "s"}`,
    `${views} view${views === 1 ? "" : "s"}`,
  ];
  //: **Star and "Favourite", not pin and "Pinned".** `entry.pinned` is one
  //: flag with one meaning, it floats a note to the top *and* collects it
  //: into the sidebar's Favourites row: and app.js's own note cards were
  //: renamed to say so. The graph and the dashboard were not, so the same
  //: flag had two names and two icons depending on which screen you were
  //: looking at. Found while fixing the star button's missing glyph. The
  //: toolbar's star now carries the state, so this line only says it for the
  //: reader who is scanning the text rather than the icons.
  if (entry.pinned) parts.push("Favourite");
  box.textContent = parts.join(" · ");
}

// Everything you can do to this note from the map, as one toolbar row.
//
//: **Nine equal buttons in a 3x3 grid is a menu, not a toolbar.** Reported
//: with a screenshot (INBOX 59): Favourite, Grow, Focus, Similar, Link,
//: Trace, Remind, Open, Bin, all the same width, the same weight and the
//: same distance apart, so the one you almost always want (Open) took as
//: long to find as the one you almost never do (Bin), and the block was
//: taller than the note's own text.
//:
//: The grid is now one row of icon buttons in three groups, each group a
//: verb class, separated by a hairline rather than by a heading:
//:
//: - **read** (Open, Similar, Trace): go somewhere, change nothing.
//: - **shape** (Grow, Focus, Link, Remind): change the map or the note's
//:   place in it.
//: - **keep** (Favourite, then Bin after a gap): the note's own fate.
//:
//: Open is the single filled control, the DESIGN.md button ramp's "the one
//: action this surface is for" (test_dock_grammar's one-primary rule is
//: about docks; this panel follows the same rule by hand). Every other
//: button is tonal, and Bin is last, set apart, so the destructive one is
//: never the neighbour of the one you meant.
//:
//: The labels live in `title`/`aria-label` only. That is a real trade: the
//: previous pass added words to these cells *because* an unlabelled star
//: beside eight labelled buttons read as a failed render. In a row of nine
//: icons with no words anywhere, nothing is the odd one out, and the state
//: the words carried (Favourite vs Favourited, Trace vs Trace to) is in the
//: tooltip and in `aria-pressed`.
function renderGraphPopupActions(entry) {
  const box = $("graph-popup-actions");
  box.replaceChildren();

  const group = (name) => {
    const el = document.createElement("div");
    el.className = `graph-popup-tool-group graph-popup-tool-${name}`;
    box.appendChild(el);
    return el;
  };
  const read = group("read");
  const shape = group("shape");
  const keep = group("keep");

  // read ---------------------------------------------------------------
  //: The filled one. `smallButton(..., ghost=false)` is the accent recipe;
  //: it stays square because `smallButton` adds `.icon-only` for a label
  //: that is a glyph and nothing else.
  const open = smallButton(
    "ph:note-pencil",
    "Open this note in the Notes tab",
    () => {
      const id = entry.id;
      closeGraphPopup();
      flashEntry(id);
    },
    false
  );
  //: The class, not just the absence of `.ghost`: a late rule paints every
  //: `.icon-only:not(.ghost)` button tonal (07-whiteboard-misc.css, "a
  //: control inside a grouped strip does not need its own ground"), so
  //: leaving Open non-ghost made it *look* exactly like its eight
  //: neighbours. Measured on the running panel, which is the only way that
  //: was ever going to show up: the markup said one filled button and the
  //: pixels said none.
  open.classList.add("graph-popup-tool-primary");
  read.appendChild(open);
  read.appendChild(
    smallButton("≈", "Highlight notes that mean something similar", async () => {
      const related = await apiJson(`/entries/${entry.id}/related`).catch(() => []);
      if (!related.length) {
        toast("No similar notes found.");
        return;
      }
      // Reuse the existing highlight pass by searching for these ids.
      graphHighlightIds = new Set(related.map((r) => r.id).concat(entry.id));
      applyGraphHighlight();
      closeGraphPopup();
      toast(`Highlighted ${related.length} similar note${related.length === 1 ? "" : "s"}.`);
    })
  );
  // Two clicks, the same shape as Link: this note becomes one end of the
  // trace, and the next one you pick becomes the other. The tooltip says
  // which end it will be, because a button that does two different things
  // without saying which is a button you have to try to understand.
  const tracingFrom = Boolean(traceFromNode);
  read.appendChild(
    smallButton(
      "ph:path",
      tracingFrom
        ? "Trace to here: find how this note connects to the one you started from"
        : "Trace from here: start tracing a path from this note",
      () => {
        closeGraphPopup();
        setTraceEnd(tracingFrom ? "to" : "from", entry.id);
        if (!tracingFrom) toast("Now pick the other note, use Trace to here.");
      }
    )
  );

  // shape --------------------------------------------------------------
  shape.appendChild(
    smallButton("ph:plant", "Grow: add a new note linked to this one", (event) =>
      openGraphNewNote(event, entry.id)
    )
  );
  if (graphFocusModeId !== entry.id) {
    shape.appendChild(
      smallButton("ph:target", "Focus: isolate this note's neighbourhood", () => {
        graphFocusModeId = entry.id;
        recordTabVisit("graph", `focus:${entry.id}`);
        $("graph-focus-clear")?.classList.remove("hidden");
        closeGraphPopup();
        renderGraph();
        toast("Focus Mode active. Showing local neighborhood.");
      })
    );
  }
  shape.appendChild(
    smallButton("ph:link", "Link: start linking this note to another", () => {
      closeGraphPopup();
      beginOrCompleteLink(entry);
      toast("Now click another note on the map to link them.");
    })
  );
  shape.appendChild(
    smallButton("ph:alarm", "Remind me about this note", () => {
      closeGraphPopup();
      switchTab("reminders");
      $("reminder-text").value = `Follow up: ${entry.content.slice(0, 60)}`;
      setDue(defaultDueValue()); // keeps the visible date/time fields in step
      $("reminder-text").focus();
    })
  );

  // keep ---------------------------------------------------------------
  //: One glyph in both states, coloured when it is on, the note cards'
  //: own rule, and for the reason `favouriteButton` (app.js) records: the
  //: "off" version used a *different icon*, and one of those was missing
  //: from the font and drew nothing at all.
  const favourite = smallButton(
    "ph:star",
    entry.pinned ? "Remove from Favourites" : "Add to Favourites",
    async () => {
      await apiJson(`/entries/${entry.id}`, {
        method: "PUT",
        body: JSON.stringify({ pinned: !entry.pinned }),
      }).catch((e) => toast(e.message, true));
      toast(entry.pinned ? "Removed from Favourites." : "Added to Favourites.");
      closeGraphPopup();
      await loadEntries().catch(() => {});
      renderGraph();
    }
  );
  favourite.classList.toggle("is-favourite", Boolean(entry.pinned));
  favourite.setAttribute("aria-pressed", String(Boolean(entry.pinned)));
  keep.appendChild(favourite);
  const bin = smallButton("ph:trash", "Move this note to the recycle bin", async () => {
    if (!(await confirmDialog("Move this note to the recycle bin?"))) return;
    await api(`/entries/${entry.id}`, { method: "DELETE" }).catch((e) =>
      toast(e.message, true)
    );
    closeGraphPopup();
    await loadEntries().catch(() => {});
    renderGraph();
    toastAction("Moved to the recycle bin.", "Undo", async () => {
      await api(`/entries/${entry.id}/restore`, { method: "POST" });
      await loadEntries();
      renderGraph();
      toast("Note restored.");
    });
  });
  //: Set apart by a gap of its own inside the keep group rather than by a
  //: fourth divider: three groups is the structure, and a hairline whose
  //: only job is to isolate one button would read as a fourth.
  bin.classList.add("graph-popup-tool-bin");
  keep.appendChild(bin);
}

function closeGraphPopup() {
  graphPopupId = null;
  $("graph-popup").classList.add("hidden");
}

async function saveGraphPopup() {
  if (graphPopupId === null) return;
  const status = $("graph-popup-status");
  const tags = $("graph-popup-tags")
    .value.split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  status.classList.remove("error");
  status.textContent = "Saving…";
  try {
    await apiJson(`/entries/${graphPopupId}`, {
      method: "PUT",
      body: JSON.stringify({ content: $("graph-popup-content").value, tags }),
    });
    status.textContent = "Saved.";
    //: What was just written is the new clean state, so the button puts
    //: itself away for the 600ms the panel is still open.
    graphPopupClean = {
      content: $("graph-popup-content").value,
      tags: $("graph-popup-tags").value,
    };
    syncGraphPopupSave();
    await loadEntries().catch(() => {});
    renderGraph(); // content/tags may change what the map shows
    setTimeout(closeGraphPopup, 600);
  } catch (error) {
    status.textContent = error.message;
    status.classList.add("error");
  }
}

// --- grow the map: add a note as a new node ----------------------------------
// The graph stops being read-only here, you can extend your notebook from the
// map itself, and a note grown from an existing one is linked to it, so the
// new node appears already connected.

let graphNewLinkFrom = null; // note id the new one should link to, if any

function openGraphNewNote(event, linkFrom = null) {
  closeGraphPopup();
  graphNewLinkFrom = linkFrom;
  const popup = $("graph-new");
  $("graph-new-content").value = "";
  $("graph-new-note-title").value = "";
  $("graph-new-tags").value = "";
  $("graph-new-status").textContent = "";
  $("graph-new-status").classList.remove("error");
  $("graph-new-title").textContent = linkFrom ? "＋ Connected note" : "＋ New note";
  $("graph-new-hint").textContent = linkFrom
    ? "This note will be linked to the one you grew it from."
    : "It joins the map as soon as you add it.";
  popup.classList.remove("hidden");

  const box = $("graph-box").getBoundingClientRect();
  // Never taller than the map it sits in, beyond that the popup scrolls
  // itself rather than growing off the edge (same fix placeGraphPopup()
  // already has; this popup was missing it, so on a short viewport its
  // Save/Close/Tags controls rendered below the fold with nothing to
  // scroll them into view).
  popup.style.maxHeight = `${Math.max(120, box.height - 16)}px`;
  const size = popup.getBoundingClientRect();
  // Centre it when there's no click position (toolbar button).
  const rawX = event ? event.clientX - box.left + 12 : (box.width - size.width) / 2;
  const rawY = event ? event.clientY - box.top + 12 : 60;
  popup.style.left = `${Math.min(Math.max(rawX, 8), Math.max(8, box.width - size.width - 8))}px`;
  popup.style.top = `${Math.min(Math.max(rawY, 8), Math.max(8, box.height - size.height - 8))}px`;
  $("graph-new-content").focus();
}

function closeGraphNewNote() {
  graphNewLinkFrom = null;
  $("graph-new").classList.add("hidden");
}

async function saveGraphNewNote() {
  const content = withTitle($("graph-new-content").value.trim(), $("graph-new-note-title").value);
  const status = $("graph-new-status");
  if (!content) {
    status.textContent = "Type something first.";
    status.classList.add("error");
    return;
  }
  const tags = $("graph-new-tags")
    .value.split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  status.classList.remove("error");
  status.textContent = "Adding…";
  try {
    const created = await apiJson("/entries", {
      method: "POST",
      body: JSON.stringify({ content, tags }),
    });
    if (graphNewLinkFrom !== null) {
      await apiJson(`/entries/${graphNewLinkFrom}/links`, {
        method: "POST",
        body: JSON.stringify({ target_id: created.id }),
      }).catch(() => {}); // the note still exists even if linking fails
    }
    closeGraphNewNote();
    toast(graphNewLinkFrom !== null ? "Added and linked." : "Added to the map.");
    await loadEntries().catch(() => {});
    await renderGraph();
    // Land the eye on the note that was just created.
    graphHighlightIds = new Set([created.id]);
    applyGraphHighlight();
    setTimeout(() => {
      graphHighlightIds = null;
      applyGraphHighlight();
    }, 2500);
  } catch (error) {
    status.textContent = error.message;
    status.classList.add("error");
  }
}

// --- export as PNG (ROADMAP.md gap 3) --------------------------------------
//
// Captures exactly what's on screen right now, the live SVG's own viewBox
// plus whatever pan/zoom transform the canvas <g> currently carries: rather
// than trying to fit the whole graph into frame, matching the whiteboard's
// own "what's on screen now" export option (whiteboard.js's wbExportPng).
//
// The exported SVG is rasterized via a detached <img>, completely outside
// the page's own stylesheets and :root custom properties, so anything
// this app relies on a CSS class or a var(--token) for (node fill, edge
// stroke, label font) would silently vanish. Inlining the resolved
// (already var()-substituted) computed style onto every cloned element is
// what survives that isolation; embedding the stylesheet text instead would
// still leave every var(--accent)-style colour unresolved.
const GRAPH_EXPORT_STYLE_PROPS = [
  "fill", "stroke", "stroke-width", "stroke-opacity", "stroke-dasharray",
  "fill-opacity", "opacity", "font-family", "font-size", "font-weight",
];

function graphInlineComputedStyle(liveEl, cloneEl) {
  const computed = getComputedStyle(liveEl);
  let css = "";
  for (const prop of GRAPH_EXPORT_STYLE_PROPS) {
    const value = computed.getPropertyValue(prop);
    if (value) css += `${prop}:${value};`;
  }
  if (css) cloneEl.setAttribute("style", css);
  for (let i = 0; i < liveEl.children.length; i++) {
    graphInlineComputedStyle(liveEl.children[i], cloneEl.children[i]);
  }
}

function graphRasterizeSvg(svgString, width, height) {
  return new Promise((resolve, reject) => {
    const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width));
      canvas.height = Math.max(1, Math.round(height));
      const ctx = canvas.getContext("2d");
      // A transparent PNG over a dark page reads as "half my graph is
      // missing" the moment it's opened anywhere else, paint a background
      // first, same reasoning as the whiteboard's own PNG export.
      //
      // Neither `body` nor `.card` has a plain colour to read here: `body`
      // has none at all (the page's real background is a gradient painted on
      // `<html>`, `00-tokens-shell.css`), and `.card`/`--card` is
      // deliberately translucent (the app's glass look, `color-mix(...,
      // transparent)`), so both resolve to something that isn't a flat fill
      //, found by actually checking, not assumed: the first draft read
      // `body`'s background and got the same `rgba(0,0,0,0)` in both themes,
      // silently painting nothing (a transparent PNG that a viewer renders
      // as white, which happened to look right only in light mode by
      // coincidence). A flat approximation tied to the resolved theme is a
      // deliberately simpler choice than reproducing the gradient exactly, 
      // the export just needs to not look broken, not to be a pixel match.
      ctx.fillStyle = resolvedTheme() === "dark" ? "#12141c" : "#eef1f5";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob(
        (result) => (result ? resolve(result) : reject(new Error("Couldn't rasterize the graph."))),
        "image/png"
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Couldn't rasterize the graph."));
    };
    img.src = url;
  });
}

async function exportGraphPng() {
  // **The canvas renderer exports the canvas**, which is what §4 meant by
  // "keeps the export path (`canvas.toBlob`) trivial": no clone, no inlining
  // of every computed style, no SVG-to-image round trip. The one thing it
  // still has to do by hand is the background, a transparent PNG over a dark
  // page reads as "half my graph is missing" the moment it is opened
  // anywhere else, so the frame is repainted onto an opaque copy.
  const liveCanvas = document.getElementById("graph-canvas");
  if (liveCanvas && !liveCanvas.classList.contains("hidden")) {
    if (!graphNodesRef || !graphNodesRef.length) {
      toast("Nothing to export yet.", true);
      return;
    }
    // GRAPH_PLAN Phase 4: exactly the visible frame, re-rendered at 2x with
    // the legend and a caption painted on (gcExportPng); the live bitmap is
    // the fallback if the renderer is not wired yet.
    const out =
      (typeof gcExportPng === "function" && gcExportPng(2)) ||
      (() => {
        const fallback = document.createElement("canvas");
        fallback.width = liveCanvas.width;
        fallback.height = liveCanvas.height;
        const ctx = fallback.getContext("2d");
        ctx.fillStyle = resolvedTheme() === "dark" ? "#12141c" : "#eef1f5";
        ctx.fillRect(0, 0, fallback.width, fallback.height);
        ctx.drawImage(liveCanvas, 0, 0);
        return fallback;
      })();
    try {
      const blob = await new Promise((resolve, reject) =>
        out.toBlob((result) => (result ? resolve(result) : reject(new Error("Couldn't export the graph."))), "image/png")
      );
      await saveFile("graph.png", blob);
      toast("Graph exported as PNG.");
    } catch (error) {
      toast(error.message || "Couldn't export the graph.", true);
    }
    return;
  }
  const liveSvg = document.getElementById("graph-svg");
  if (!liveSvg || !liveSvg.querySelector("circle")) {
    toast("Nothing to export yet.", true);
    return;
  }
  const clone = liveSvg.cloneNode(true);
  graphInlineComputedStyle(liveSvg, clone);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const viewBox = liveSvg.viewBox.baseVal;
  const width = viewBox && viewBox.width ? viewBox.width : liveSvg.clientWidth;
  const height = viewBox && viewBox.height ? viewBox.height : liveSvg.clientHeight;
  clone.setAttribute("width", width);
  clone.setAttribute("height", height);
  const svgString = new XMLSerializer().serializeToString(clone);
  try {
    const blob = await graphRasterizeSvg(svgString, width, height);
    await saveFile("graph.png", blob);
    toast("Graph exported as PNG.");
  } catch (error) {
    toast(error.message || "Couldn't export the graph.", true);
  }
}


// --- minimap + saved views (ROADMAP §85.4 items 7) ---------------------------

//: The four corners the minimap can be pinned to, and where that choice lives.
//: Top-left is the default because it is the one corner nothing else claims, 
//: the toolbar owns the top strip, the agent monitor bottom-left, and the zoom
//: buttons bottom-right (which is what the old hard-coded position collided
//: with).
const GRAPH_MINIMAP_CORNERS = ["off", "tl", "tr", "bl", "br"];
const GRAPH_MINIMAP_CORNER_KEY = "graph-minimap-corner";
//
// Both exist for the same reason, named in the roadmap's own words: once a
// notebook is dense enough that the force layout stops being readable, there
// is "nothing to re-find a specific arrangement", no overview of where you
// are in the map, and no way to come back to a combination of filters that
// worked.

let graphMinimapProjection = null; // the last full paint's placement, reused by graphMinimapFrame
const GRAPH_MINIMAP_W = 168;
const GRAPH_MINIMAP_H = 112;

// Where the nodes are, scaled into the minimap box. Recomputed on every paint
// rather than cached: the force layout keeps moving until it cools, so a
// cached extent would be wrong for the first few seconds, which is exactly
// when someone is watching it settle.
function graphMinimapPaint() {
  const svg = document.getElementById("graph-minimap-svg");
  if (!svg || !graphNodesRef?.length) return;
  const nodes = graphNodesRef.filter((n) => Number.isFinite(n.x) && Number.isFinite(n.y));
  if (!nodes.length) return;

  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  // A single node, or a perfectly straight line of them, gives a zero-width
  // extent and a division by zero further down.
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const pad = 6;
  const scale = Math.min(
    (GRAPH_MINIMAP_W - pad * 2) / spanX,
    (GRAPH_MINIMAP_H - pad * 2) / spanY
  );
  const toMini = (x, y) => [
    pad + (x - minX) * scale + (GRAPH_MINIMAP_W - pad * 2 - spanX * scale) / 2,
    pad + (y - minY) * scale + (GRAPH_MINIMAP_H - pad * 2 - spanY * scale) / 2,
  ];

  const dots = document.getElementById("graph-minimap-dots");
  const frame = document.getElementById("graph-minimap-frame");
  if (!dots || !frame) return;

  // One <circle> per node is the whole minimap. Deliberately not reusing the
  // main render path: the minimap has no labels, no edges and no hit-testing,
  // so an SVG of plain dots is both cheaper and clearer than a scaled clone
  // of a canvas that is already too dense to read, which is the problem this
  // is here to solve, not to reproduce in miniature.
  //: **One dot per note stops being one dot per note past a few hundred.**
  //: The box is 168x112 with a 1.6px dot: about 700 dots is the point at which
  //: another one lands on top of an existing one and adds nothing but a DOM
  //: element. Measured on the 2,000-note fixture, rebuilding all 2,000
  //: `<circle>`s while a drag was in flight was a real, repeated main-thread
  //: cost for a picture that looked identical, so a big notebook is sampled
  //: at an even stride instead. Evenly, not randomly or by prefix: a
  //: contiguous slice would draw one corner of the map and leave the rest
  //: blank, and a random sample would shimmer between repaints.
  const MINIMAP_MAX_DOTS = 700;
  const stride = Math.max(1, Math.ceil(nodes.length / MINIMAP_MAX_DOTS));
  const fragment = document.createDocumentFragment();
  for (let i = 0; i < nodes.length; i += stride) {
    const node = nodes[i];
    const [mx, my] = toMini(node.x, node.y);
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", mx.toFixed(1));
    dot.setAttribute("cy", my.toFixed(1));
    dot.setAttribute("r", "1.6");
    dot.setAttribute("fill", node.colour || "currentColor");
    fragment.appendChild(dot);
  }
  dots.replaceChildren(fragment);

  // Clicking the minimap centres the map on that point. Stored on the element
  // so the handler (wired once, below) can invert the projection without
  // recomputing the extent it was painted with.
  svg._toCanvas = (mx, my) => [
    minX + (mx - pad - (GRAPH_MINIMAP_W - pad * 2 - spanX * scale) / 2) / scale,
    minY + (my - pad - (GRAPH_MINIMAP_H - pad * 2 - spanY * scale) / 2) / scale,
  ];
  //: Kept so a pan can move the rectangle without repainting the dots: the
  //: projection is a property of where the *notes* are, and a pan does not
  //: move a note. See `graphMinimapFrame`.
  graphMinimapProjection = { toMini, frame };
  graphMinimapFrame();
}

//: **The viewport rectangle alone, for a pan.**
//:
//: Which part of the map is on screen is the only thing a pan or a zoom
//: changes about the minimap: the dots are where the notes are, and a pan
//: does not move a note. Repainting the whole minimap on every pointer event
//: of a pan was measured at four passes over every node, three document
//: lookups and up to 700 fresh `<circle>` elements per event, for a picture
//: identical to the one already on screen apart from this rectangle. The full
//: paint still runs where the positions really did change: the simulation's
//: ticks, a relayout, a saved view.
function graphMinimapFrame() {
  if (!graphMinimapProjection) {
    graphMinimapPaint();
    return;
  }
  const { toMini, frame } = graphMinimapProjection;
  if (!frame.isConnected) {
    graphMinimapProjection = null;
    graphMinimapPaint();
    return;
  }
  const transform = graphSvg ? d3.zoomTransform(graphSvg.node()) : null;
  if (!transform || !graphDims.w) return;
  const [x0, y0] = transform.invert([0, 0]);
  const [x1, y1] = transform.invert([graphDims.w, graphDims.h]);
  const [fx0, fy0] = toMini(x0, y0);
  const [fx1, fy1] = toMini(x1, y1);
  // Clamped to the minimap's own box. Zoomed far enough out, the viewport is
  // wider than every node in the map, so the raw rectangle runs past the edge
  //, measured at 201x39 inside a 168x112 box. The SVG would clip it anyway,
  // but a rectangle with two edges off-screen reads as "the frame is broken"
  // rather than "you are looking at all of it"; clamped, it sits flush with
  // the border and says the second thing.
  const clampedX0 = Math.max(0, Math.min(fx0, fx1));
  const clampedY0 = Math.max(0, Math.min(fy0, fy1));
  const clampedX1 = Math.min(GRAPH_MINIMAP_W, Math.max(fx0, fx1));
  const clampedY1 = Math.min(GRAPH_MINIMAP_H, Math.max(fy0, fy1));
  frame.setAttribute("x", clampedX0.toFixed(1));
  frame.setAttribute("y", clampedY0.toFixed(1));
  frame.setAttribute("width", Math.max(0, clampedX1 - clampedX0).toFixed(1));
  frame.setAttribute("height", Math.max(0, clampedY1 - clampedY0).toFixed(1));
}

// --- the dock's real height, in the token everything clears it by ------------
//
// `--graph-dock-h` (02-chat-graph.css) is a calc of one row of controls, and
// the dock is not one row at every width: measured at a 700px viewport it
// wraps to 111px while the token still read 51px. Everything that clears the
// dock reads that token, so at that width the minimap's top corners sat 60px
// too high, underneath the dock they exist to stay clear of, and the options
// panel was capped against a top that did not exist.
//
// The same answer, for the same reason, as `initHeaderHeightToken` in app.js:
// a ResizeObserver writes the measured height back into the token everything
// already reads, so nothing gains a second property to learn. Through the
// CSSOM rather than a `style=` attribute, which this app's CSP refuses. No
// feedback loop is possible: the dock's height comes from its own content and
// nothing inside it is sized from this token.
function initGraphDockHeightToken() {
  const card = document.getElementById("graph-card");
  const dock = card?.querySelector('.dock[data-dock-name="graph"]');
  if (!card || !dock || typeof ResizeObserver === "undefined") return;
  if (dock._heightWired) return;
  dock._heightWired = true;
  const write = () => {
    const h = Math.round(dock.getBoundingClientRect().height);
    // Zero while the tab is not on screen (the card is display:none until
    // then), and a zero here would stack the minimap and the selection bar
    // on top of the dock at the next paint. The stylesheet's own calc stands
    // until there is a real measurement to replace it with.
    if (h > 0) card.style.setProperty("--graph-dock-h", `${h}px`);
  };
  new ResizeObserver(write).observe(dock);
  write();
}

function initGraphMinimap() {
  const svg = document.getElementById("graph-minimap-svg");
  if (!svg || svg._wired) return;
  svg._wired = true;
  // Where in canvas coordinates a pointer event over the minimap is pointing.
  // Null whenever the map has not been painted yet (`_toCanvas` is set by
  // graphMinimapPaint) or the zoom behaviour is not up, which is every call
  // before the first render.
  const canvasPointFor = (event) => {
    if (!svg._toCanvas || !graphSvg || !graphZoom) return null;
    const rect = svg.getBoundingClientRect();
    return svg._toCanvas(
      ((event.clientX - rect.left) / rect.width) * GRAPH_MINIMAP_W,
      ((event.clientY - rect.top) / rect.height) * GRAPH_MINIMAP_H
    );
  };

  // Centre the map on a canvas point at a given scale. `animate` is off while
  // a drag is in flight: a 250ms transition per pointermove queues dozens of
  // overlapping tweens and the map lurches behind the cursor instead of
  // tracking it. A single click still animates, because a jump that teleports
  // loses you your bearings.
  const centreOn = (cx, cy, scale, animate) => {
    const target = d3.zoomIdentity
      .translate(graphDims.w / 2, graphDims.h / 2)
      .scale(scale)
      .translate(-cx, -cy);
    const sel = animate ? graphSvg.transition().duration(250) : graphSvg;
    sel.call(graphZoom.transform, target);
  };

  const jump = (event, animate = true) => {
    const point = canvasPointFor(event);
    if (!point) return;
    // Keep the zoom level, change only where it is centred, a click on the
    // minimap is for navigating. Zooming from here is the wheel, below.
    centreOn(point[0], point[1], d3.zoomTransform(graphSvg.node()).k, animate);
  };

  // Press and hold to scrub the map around, rather than clicking, looking,
  // clicking again. Pointer events (not mouse) so a finger on a tablet drags
  // the same way; pointer capture so leaving the little box mid-drag keeps
  // sending moves here instead of dropping the drag where the cursor left.
  let dragging = false;
  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== undefined && event.button !== 0) return;
    if (!canvasPointFor(event)) return;
    dragging = true;
    svg.setPointerCapture?.(event.pointerId);
    svg.classList.add("graph-minimap-dragging");
    // The press itself centres, so a plain click still works, there is no
    // separate click listener any more, which is what stopped a click from
    // firing this and then a second, animated jump on mouseup.
    jump(event, true);
    event.preventDefault();
  });
  svg.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    jump(event, false);
  });
  const endDrag = (event) => {
    if (!dragging) return;
    dragging = false;
    svg.releasePointerCapture?.(event.pointerId);
    svg.classList.remove("graph-minimap-dragging");
  };
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  // Wheel (and a trackpad pinch, which browsers deliver as a wheel event with
  // ctrlKey set) zooms about the point under the cursor, the same gesture the
  // main canvas already answers to. `passive: false` because preventDefault is
  // the whole point: without it the page scrolls behind the minimap.
  svg.addEventListener(
    "wheel",
    (event) => {
      const point = canvasPointFor(event);
      if (!point) return;
      event.preventDefault();
      const current = d3.zoomTransform(graphSvg.node());
      // deltaY is device-dependent (lines vs pixels vs a pinch's fine steps),
      // so only its sign is trusted; the step is ours.
      const factor = event.deltaY < 0 ? 1.2 : 1 / 1.2;
      const extent = graphZoom.scaleExtent ? graphZoom.scaleExtent() : [0.1, 8];
      const scale = Math.max(extent[0], Math.min(extent[1], current.k * factor));
      centreOn(point[0], point[1], scale, false);
    },
    { passive: false }
  );
  // One control for both "is it showing" and "where", see index.html on why
  // these were merged rather than sitting beside each other.
  //
  // Per-device workspace state, so localStorage beside `graph-layout` and the
  // saved views below, not preferences.
  const applyMinimapPosition = (choice) => {
    const box = document.getElementById("graph-minimap");
    if (!box) return;
    const chosen = GRAPH_MINIMAP_CORNERS.includes(choice) ? choice : "tl";
    for (const c of GRAPH_MINIMAP_CORNERS) box.classList.remove(`graph-minimap-${c}`);
    box.classList.toggle("hidden", chosen === "off");
    if (chosen !== "off") {
      box.classList.add(`graph-minimap-${chosen}`);
      graphMinimapPaint();
    }
    const picker = document.getElementById("graph-minimap-corner");
    if (picker) picker.value = chosen;
  };

  // Existing installs kept only "hidden or not" under an older key. Read it
  // once so nobody who had deliberately turned the minimap off has it come
  // back on after an update; the new key takes over from the first change.
  const storedCorner = localStorage.getItem(GRAPH_MINIMAP_CORNER_KEY);
  const legacyHidden = localStorage.getItem("graph-minimap-hidden") === "1";
  applyMinimapPosition(storedCorner || (legacyHidden ? "off" : "tl"));

  document.getElementById("graph-minimap-corner")?.addEventListener("change", (event) => {
    const choice = event.target.value;
    localStorage.setItem(GRAPH_MINIMAP_CORNER_KEY, choice);
    applyMinimapPosition(choice);
  });
}

// --- saved views -------------------------------------------------------------
//
// A "view" is every control that changes *what the map shows and how*, plus
// where you were looking. Stored in localStorage rather than the database on
// purpose: these are per-device workspace state of the same kind as
// `graph-layout` and the sidebar widths already kept there (see
// MIRRORED_UI_EXTRAS in app.js), not notebook content that belongs in a
// backup.
const GRAPH_VIEWS_KEY = "graph-saved-views";

function graphSavedViews() {
  try {
    const parsed = JSON.parse(localStorage.getItem(GRAPH_VIEWS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return []; // corrupt or hand-edited: an empty list beats a broken tab
  }
}

function graphCaptureView() {
  const transform = graphSvg ? d3.zoomTransform(graphSvg.node()) : null;
  return {
    layout: localStorage.getItem("graph-layout") || "force",
    colour: localStorage.getItem("graph-colour") || "",
    hiddenCategories: [...graphHiddenCategories],
    hiddenKeys: [...graphHiddenKeys],
    groups: graphGroups(),
    // graph.md section 1: `#graph-physics` is the Physics *section*
    // (`.dock-menu-section`, index.html), not a checkbox -- it was never
    // anything a saved view could read `.checked` off, so every view stored
    // `physics: true` no matter what the sliders said. "Physics", to a
    // reader, means what Gravity and Spread are set to, so a view captures
    // those two directly now, the same values `renderGraph()` itself reads
    // out of localStorage (graph.js line ~1713).
    gravity: document.getElementById("graph-gravity")?.value ?? "50",
    spread: document.getElementById("graph-spread")?.value ?? "50",
    time: document.getElementById("graph-time-slider")?.value ?? null,
    // Same bug, two more controls: the ids below were never on the page
    // (the checkboxes are `#graph-entities`/`#graph-documents`; app.js binds
    // their "change" listener to those two ids, not to the ones this
    // function used to read), so a saved view's Entities/Documents state was
    // always the `?? false`
    // fallback, regardless of what was actually shown when it was saved.
    entities: document.getElementById("graph-entities")?.checked ?? false,
    documents: document.getElementById("graph-documents")?.checked ?? false,
    orphans: document.getElementById("graph-hide-orphans")?.checked ?? false,
    transform: transform ? { x: transform.x, y: transform.y, k: transform.k } : null,
  };
}

async function graphSaveCurrentView() {
  const name = (await promptDialog("Name this view", "", { confirmLabel: "Save view" })).trim();
  if (!name) return;
  const views = graphSavedViews().filter((v) => v.name !== name); // same name replaces
  views.push({ name, ...graphCaptureView() });
  localStorage.setItem(GRAPH_VIEWS_KEY, JSON.stringify(views));
  renderGraphViews();
  toast(`Saved the view “${name}”.`);
}

function graphApplyView(view) {
  const set = (id, value) => {
    const el = document.getElementById(id);
    if (!el || value === null || value === undefined) return;
    if (el.type === "checkbox") el.checked = Boolean(value);
    else el.value = value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  };
  localStorage.setItem("graph-layout", view.layout);
  if (view.colour) localStorage.setItem("graph-colour", view.colour);
  set("graph-layout", view.layout);
  set("graph-colour", view.colour);
  // Real controls, not the section div: `set()` dispatches "change" on each,
  // which is exactly what the gravity/spread listener (app.js, "Physics
  // sliders: persist, then rebuild the simulation with the new forces")
  // already listens for, so restoring a view re-persists and re-renders
  // through the same path dragging the slider does.
  set("graph-gravity", view.gravity);
  set("graph-spread", view.spread);
  set("graph-entities", view.entities);
  set("graph-documents", view.documents);
  set("graph-hide-orphans", view.orphans);
  set("graph-time-slider", view.time);
  graphHiddenCategories = new Set(view.hiddenCategories || []);
  graphHiddenKeys = new Set(view.hiddenKeys || []);
  if (Array.isArray(view.groups)) {
    localStorage.setItem(GRAPH_GROUPS_KEY, JSON.stringify(view.groups));
    graphRenderGroups();
  }

  // The transform lands *after* the rebuild those change events kick off, 
  // restoring the pan/zoom first would only have it overwritten by the
  // auto-fit that runs when a fresh layout settles.
  setTimeout(() => {
    if (!view.transform || !graphSvg || !graphZoom) return;
    graphSvg.call(
      graphZoom.transform,
      d3.zoomIdentity.translate(view.transform.x, view.transform.y).scale(view.transform.k)
    );
    graphMinimapPaint();
  }, 400);
  toast(`Showing “${view.name}”.`);
}

function renderGraphViews() {
  const select = document.getElementById("graph-view-picker");
  if (!select) return;
  const views = graphSavedViews();
  select.replaceChildren();
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = views.length ? "Saved views…" : "No saved views";
  select.appendChild(blank);
  for (const view of views) {
    const option = document.createElement("option");
    option.value = view.name;
    option.textContent = view.name;
    select.appendChild(option);
  }
  select.disabled = !views.length;
  const remove = document.getElementById("graph-view-delete");
  if (remove) remove.disabled = !views.length;
}

function initGraphViews() {
  const select = document.getElementById("graph-view-picker");
  if (!select || select._wired) return;
  select._wired = true;
  select.addEventListener("change", () => {
    const view = graphSavedViews().find((v) => v.name === select.value);
    if (view) graphApplyView(view);
  });
  initGraphGroups();
  document.getElementById("graph-view-save")?.addEventListener("click", graphSaveCurrentView);
  document.getElementById("graph-view-delete")?.addEventListener("click", async () => {
    const name = select.value;
    if (!name) {
      toast("Pick a view to delete first.");
      return;
    }
    if (!(await confirmDialog(`Delete the saved view “${name}”?`))) return;
    localStorage.setItem(
      GRAPH_VIEWS_KEY,
      JSON.stringify(graphSavedViews().filter((v) => v.name !== name))
    );
    renderGraphViews();
    toast("View deleted.");
  });
  renderGraphViews();
}

// Wired at parse time as well as from the first render: the token has to be
// right before the tab is first looked at, and the render path that calls it
// below does not run at all while the notebook has nothing to draw. Both
// calls are idempotent (`_heightWired`), and the observer's first callback
// arrives with a real height as soon as the card stops being display:none.
initGraphDockHeightToken();
