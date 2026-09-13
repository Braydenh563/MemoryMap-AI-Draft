# Mindmaps — a dev plan

> Companions: [ROADMAP.md](../ROADMAP.md) · [HANDOVER.md](HANDOVER.md) ·
> [UI_MODERNISATION_PLAN.md](UI_MODERNISATION_PLAN.md) ·
> [AGENT_SKILLS_REFORM.md](AGENT_SKILLS_REFORM.md) · [PLAN.md](PLAN.md) ·
> [../ARCHITECTURE.md](../ARCHITECTURE.md) · [../DESIGN.md](../DESIGN.md)
>
> **Note for Fable: this plan is a first pass and is meant to be extended and
> refined, not executed verbatim.** Everything in §2 is grounded in the code as
> it stands; §5 onward is design intent that should be pressure-tested against
> the running app before any of it is built.

## 1. The instruction, verbatim

> I have a vision. I want to extend the whiteboard and make a mindmap feature
> like kaggle. any and all text boxes and things that are in the map stay
> bundled within the map and basically the mindmap as a whole becomes its own
> entity that can be attached to notes and is its own object and has its own
> library subtab or is a part of the boards and maps subtab. do deep research
> and figure out all the features and functions kaggle.it has as well as other
> mindmapping websites and programs and create a detailed dev plan to make it a
> reality. mindmaps should be readable by the ai, exportable as images and
> pdfs, built off the whiteboard, have lots of utility, have the ability to
> link and reference notes and documents and files etc. the mindmap as a whole
> can be an item that can be attached to, linked to, referenced in notes and
> documents. this features needs to be properly integrated with everything,
> with rendered previews and chips if attached to notes and/or the chat as well
> as if they appear in the dashboard widgets and/or the timeline and/or graph
> etc.

**The naming question is settled.** Asked directly, the user confirmed
"kaggle" was a typo for **Coggle (coggle.it)** — and said all of the tools
named here are good references, so the feature set below draws on **Coggle**
(immediacy, branch colours, loops and joins, image nodes, PNG/PDF/text/OPML
export, `.mm` import), **Kumu** (attributes, perspectives, focus mode, signed
edges), **XMind** (output quality, structure templates) and **Obsidian Canvas
Mindmap** (the keyboard set). They also named **Lucidchart** as a reference,
"but that's more for the whiteboard" — its smart connectors, containers,
alignment tools and shape libraries map onto PLAN.md W1–W5, not this plan.

**The scope call in §4 is made: option B** (confirmed by the user in the same
exchange). Everything from §5 on assumes it.

## 2. What already exists (checked in the code, not assumed)

This is the single most important section: a large part of this feature is
already built, and CLAUDE.md's first rule exists because three sessions have
rebuilt existing work here.

- **A board is already an `Entry`.** `WhiteboardNode.board_id`,
  `WhiteboardSketch.board_id` and `WhiteboardObject.board_id` are all
  `ForeignKey("entries.id")` (`src/memorymap/core/database.py` ~930-1010). A
  board *is* a note row. So "the mindmap as a whole is its own object that can
  be attached to, linked to and referenced" is **already true at the data
  layer** — it inherits linking, tags, categories, the graph, the timeline and
  full-text search for free. The work is surfacing that, not adding it.
- **Nodes, sketches and objects are all board-scoped and workspace-scoped**
  (`WorkspaceMixin`), with `x/y/z`, optional `width/height/rotation`, and a
  `group_id` — so grouping and z-order exist.
- **`WhiteboardObject` uses one table with a `kind` discriminator**, which is
  the extension point for new node kinds (a mindmap topic, an embedded file
  card) without a migration per kind.
- **Boards have a preview renderer** (`_board_preview`, `_preview_items` in
  `routes_whiteboard.py`) and a Library "Boards & maps" sub-tab that lists and
  manages them, plus duplicate.
- **A Concept Map feature exists** (task #7, "Build the authored mindmap"),
  reachable from the Graph tab's toolbar. Its learnability is a known open item
  (task #103). **Read what it does before designing a second one** — the
  likeliest right answer is that "mindmap" and "concept map" become one feature,
  not two.
- **The graph already renders note-to-note structure** (`frontend/graph.js`),
  and the Library already has a Boards & maps sub-tab (the user's own preferred
  home for this).

**So the honest framing of this work is: promote the board from "a canvas that
happens to be an entry" to "a first-class map object with mindmap semantics,
surfaced everywhere the app already surfaces notes."**

## 3. Research: what the field actually offers

Sources at the end. Grouped by what it would mean here.

### 3.1 Structure and layout
- **Reingold–Tilford "tidy" tree**, improved to linear time by Buchheim et al.,
  is the standard mind-map layout; `d3-hierarchy`'s `tree()` implements it, and
  treating `x` as angle and `y` as radius gives the classic radial map from the
  same call. `d3-flextree` extends it to variable-sized nodes, which matters
  here because a node may be a note card, not a word.
- **Obsidian Canvas Mindmap** is the closest model for keyboard-first editing:
  Tab adds a child, Enter adds a sibling, arrow keys navigate, a node's whole
  subtree can be selected and moved, and edges can be coloured for grouping.
  This is the interaction set to copy — it is what makes a mindmap fast rather
  than a drawing.
- **XMind** is the benchmark for *output* quality and offline work; **Coggle**
  for immediacy (no ceremony, real-time concurrent edits); **MindMeister** for
  idea→task workflows; **Whimsical** for mixing maps with flowcharts and docs.

### 3.2 Semantics beyond a tree
- **Kumu** is the one worth studying hardest for this app: elements and
  connections carry **tags and attributes**, and "perspectives" turn that data
  into decorations — colour, size, filter. It adds **social-network metrics**
  (betweenness, closeness, eigenvector centrality), **automated community
  detection**, and a **focus mode** that starts from one element and unfolds the
  network step by step. It supports **systems maps and causal loop diagrams**
  (signed, directional edges), not just trees.
- That maps onto MemoryMap directly: a map's nodes are often *real notes*, which
  already have tags and categories, so "perspectives" is a filter over data the
  app already holds — and the graph tab already computes some of these metrics.

### 3.3 Integration patterns
- **Excalidraw-in-Obsidian** is the reference for "a drawing is a first-class
  linked document": backlinks work, links survive a rename, and drawings appear
  in the graph view. That is precisely the integration bar the user is setting.
- Obsidian's own warning is worth heeding: with Canvas you end up with **two
  levels of linking** (through the canvas and through the notes), which
  confuses people. **Decide once, here: a map-to-note link is a real link and
  shows in the graph; a node's position on a canvas is not a link.**

## 4. Scope decision (make this call first)

Three options, with a recommendation.

| | Option | Consequence |
| --- | --- | --- |
| A | Mindmap as a **mode of the whiteboard** — same board, a toggle that turns on tree semantics, auto-layout and keyboard editing | Least new code, no second data model, one Library home. Risk: modes are a learnability tax. |
| B | Mindmap as a **new board `type`** on the existing board entry (`board.type = "map" \| "board"`) | One data model, two behaviours, two filters in the Library. Clean. **Recommended.** |
| C | A **separate entity** with its own tables and sub-tab | Duplicates linking, preview, export, permissions and the Library plumbing that boards already have. Not recommended. |

**Decision: B — confirmed by the user.** A board is already an entry; add a
`type` and a `layout` to it. Everything in §5 and §6 assumes B.

### What Coggle specifically does that the phases below must keep

Recorded because Coggle is the reference the user actually meant:

- **Zero ceremony.** A new map is one click and one central node; a child is
  the `+` on hover or `Tab`; there is no "mode" to enter. Phase 2 item 5 is
  the keyboard half of this; the `+` affordance on the hovered node is the
  pointer half and belongs in the same item.
- **Branch colour carries down the branch** — every descendant inherits the
  first-level colour unless overridden. Phase 2 item 8's "inherit-from-parent
  by default" is exactly this; the default palette is one colour per
  first-level branch, assigned in order.
- **Loops and joins**: a second parent link between branches, drawn as a
  curve distinct from the tree edges. Phase 2 item 9.
- **Text is markdown-ish** (bold, italics, links, code) and a node may be an
  image. Node kinds in Phase 1 item 3 cover the image; the text renderer is
  the whiteboard's existing markdown pass.
- **Export**: PNG, PDF, plain-text outline, `.mm` (FreeMind) and OPML;
  **import** `.mm` and OPML. Phase 4 items 16–17 add `.mm` to their list.
- **Auto-arrange** on demand rather than always: the user can drag a branch
  and it stays; "tidy" re-lays it out. Phase 2 item 6 becomes a command, with
  free placement kept per branch (a `pinned` flag on a node).
- **Presentation/print**: a map fits to page for PDF. Covered by Phase 4.

## 5. The feature set, in build order

### Phase 1 — the map object (foundation)
1. **`type` and `layout` on the board entry.** `type: "board" | "map"`;
   `layout: "free" | "tree-right" | "tree-down" | "radial"`. Stored on the
   board's own `Entry` (a JSON settings column or a dedicated table —
   `WhiteboardObject`'s `kind` discriminator is the precedent for not adding a
   table per idea).
2. **A parent edge for nodes.** Mindmaps are trees; the whiteboard's links are
   a general graph. Add `parent_id` to whatever carries a map node, and keep the
   existing free links for cross-branch connections (which every serious
   mindmapper supports and calls a "relationship" or "cross-link").
3. **Node kinds**, on the existing discriminator: `topic` (text), `note` (a real
   `Entry` — this is `WhiteboardNode` today), `document`, `file`, `image`,
   `link`. A node that *is* a note keeps its identity: editing it edits the note.
4. **Containment is real.** "any and all text boxes and things that are in the
   map stay bundled within the map" — enforce it: deleting a map deletes its
   `topic` nodes (they exist only there) and *unlinks* its `note`/`document`/
   `file` nodes (those live in the library and must survive). Write the test
   first; this is the rule most likely to be got wrong.

### Phase 2 — editing that feels like a mindmap
5. **Keyboard-first**: Tab = child, Enter = sibling, Shift+Tab = outdent,
   arrows = navigate, F2/double-click = rename, Delete = subtree with confirm.
   Copy Obsidian Canvas Mindmap's set; it is the de-facto standard.
6. **Auto-layout** via Reingold–Tilford with variable node sizes (d3-flextree's
   algorithm, implemented locally — **no CDN, the app is offline-first**;
   `frontend/graph.js` already hand-rolls layout, so this is a sibling of
   existing code, not a new dependency).
7. **Collapse/expand a branch**, with a count badge on the collapsed node.
8. **Styling that carries meaning, not decoration**: per-node colour, shape and
   icon; per-edge colour and thickness; inherit-from-parent by default.
9. **Cross-links** (non-tree edges) rendered distinctly — dashed, per the
   systems-map convention — and optionally **signed/directional** for causal
   loop diagrams (Kumu's model).

### Phase 3 — the map as a citizen of the app
10. **Library**: maps live in **Boards & maps** with a Maps filter chip (the
    user's stated preference), with the existing board preview upgraded to
    render map structure.
11. **Attachable and referenceable**: a map can be attached to a note, a
    document and a chat message, exactly as a file can today
    (`routes_chat.py`'s `file_ids` is the pattern to copy), and referenced
    inline with the existing `@` picker.
12. **Rendered previews and chips** everywhere the user listed: note bodies,
    the chat transcript, dashboard widgets, the timeline and the graph. One
    `mapChip()` and one `mapPreview()`, used by all of them — the app's
    recurring failure is the same object drawn five ways.
13. **Graph integration**: a map is a node in the graph; its note-nodes are
    edges from the map to those notes. This is the "decide once" call from
    §3.3 — a map's *membership* is a link, a node's *position* is not.

### Phase 4 — AI and export
14. **The AI can read a map.** A `read_mindmap` tool returning an indented
    outline (title, then the tree, with each node's kind and any note id), which
    is the form a small model handles best. Plus `create_mindmap`,
    `add_map_node`, `link_map_nodes` — gated behind the tool toggles, and
    written to the *contract* shape the skills reform (Phase A of
    [AGENT_SKILLS_REFORM.md](AGENT_SKILLS_REFORM.md)) defines, so they are
    usable by a 4B model.
15. **AI generation**: "make a map of these notes" — the agent proposes a tree,
    the user accepts or edits it. Every mainstream tool now has this; the
    differentiator here is that the nodes are *the user's real notes*, not
    invented text.
16. **Export**: PNG and SVG from the existing canvas render, and PDF via the
    same path the app already uses for "Print or save as PDF" in the documents
    kebab. Also **Markdown outline**, **OPML** and **FreeMind `.mm`** — the
    interchange formats every mindmapper (Coggle included) reads — cheap, and
    it makes the feature not a lock-in.
17. **Import**: OPML, FreeMind `.mm` and indented Markdown, so an existing map
    can come in.

### Phase 5 — utility
18. **Focus mode** (Kumu): start at one node, reveal the network step by step.
19. **Filter/perspective**: colour or hide by tag, category, age, or "has a
    note behind it" — reusing the notebook's own metadata, which is the thing
    a general mindmapper cannot do.
20. **Map metrics** where they are honest: node count, depth, orphan branches,
    and — for cross-linked maps — the centrality measures the graph tab already
    computes.
21. **Templates**: a few starting shapes (brainstorm, decision tree, project
    breakdown, cause-and-effect), because an empty canvas is the main reason
    mindmap features go unused.

## 6. Files this will touch

- `src/memorymap/core/database.py` — board `type`/`layout`, node `parent_id`,
  new `kind` values. One Alembic migration.
- `src/memorymap/api/routes_whiteboard.py` — map CRUD, layout endpoint, node
  tree endpoints, export; extend `_board_preview` for map structure.
- `src/memorymap/ai/tools*.py` — the four map tools, contract-shaped.
- `frontend/whiteboard.js` (and `frontend/graph.js` for layout precedent) — the
  map mode, keyboard editing, auto-layout, collapse.
- `frontend/library.js` — the Maps filter and the upgraded preview.
- `frontend/app.js` — `mapChip()`/`mapPreview()`, the `@` picker source, chat
  attachment, dashboard widget, timeline row.
- `docs/DESIGN.md` — the node/edge visual language, once, so it is not
  reinvented per surface.

## 7. Acceptance

- A map created from three notes shows those notes as nodes; editing a node
  edits the note; deleting the map leaves the notes intact and deletes only its
  own topics (test first).
- The same map appears as a chip in a note, in a chat message, in the graph, in
  a dashboard widget and on the timeline — all drawn by one renderer.
- `read_mindmap` returns an outline a 4B model can act on, verified against a
  real local model (the standing caveat in CLAUDE.md applies).
- Export produces PNG, SVG, PDF, Markdown and OPML; OPML round-trips through
  import.
- Keyboard: Tab/Enter/arrows build a twenty-node map without touching the mouse.

## 8. Risks

- **Two linking levels** (§3.3) — decide the rule before building, or the graph
  fills with noise.
- **A second concept-map feature.** Check task #7 and #103 first; merging is
  almost certainly right.
- **Layout performance** on a large map — the whiteboard already had "shapes
  and links lag behind notes when panning" (task #71); auto-layout must run off
  the paint path.
- **Scope.** Phases 1-3 are the user's actual request; 4-5 are where a
  mindmap becomes worth having. Ship 1-3 completely before starting 4.

## Sources

- [Kumu](https://kumu.io/) · [Kumu — network mapping](https://kumu.io/markets/network-mapping)
- [Best Mind Mapping Software for 2026 — ClickHelp](https://clickhelp.com/clickhelp-technical-writing-blog/best-mind-mapping-software/)
- [The 12 Best Mind Mapping Tools and Apps — Storyflow](https://storyflow.so/blog/best-mind-mapping-tools-2025)
- [Canvas Mindmap — Obsidian plugin](https://community.obsidian.md/plugins/canvas-mindmap)
- [Mind mapping with Excalidraw in Obsidian](https://www.zsolt.blog/2021/09/mind-mapping-with-excalidraw-in-obsidian.html)
- [Spatial canvases and your notes](https://tfthacker.substack.com/p/spatial-canvases-and-your-notes)
- [d3-hierarchy `tree()` — Reingold–Tilford](https://d3js.org/d3-hierarchy/tree) · [d3-flextree](https://github.com/Klortho/d3-flextree)
- [Radial tree component — Observable](https://observablehq.com/@d3/radial-tree-component)

## 9. Built — Phase 1 (backend)

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", MINDMAP_PLAN.md) on 2026-09-09: a plan holds open work only.

## 10. Built — Phase 2 (frontend)

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", MINDMAP_PLAN.md) on 2026-09-09: a plan holds open work only.

## 11. Built: the previews, Phase 4 and Phase 5

Moved to HISTORY.md ("Moved from the plans, 2026-09-09", MINDMAP_PLAN.md) on 2026-09-09: a plan holds open work only.

## 12. The map as its own tool (INBOX 93, the owner's ask, 2026-09-09)

The owner: "the mindmap needs more specialised and targeted controls, yes
it is built off the whiteboard but it isn't the whiteboard ... it doesn't
need to stop at Coggle, it can straight up copy, merge and make better
many mindmap software." This section is the complete spec: every bug and
missing feature the owner named, every feature worth taking from Coggle,
XMind, MindMeister, MindNode, Freeplane, Miro and Whimsical, and the
things a notebook-native map can do that none of them can. Two sessions,
Opus, one worktree, each phase gated by `scratchpad/ui-sweeps/mindmap.js`
extended with the numbers named.

### 12.0 Decisions made (do not remake)

- A map is a board of `type: "map"`; it keeps the whiteboard's storage,
  undo, export and previews, and gets its **own toolbar, its own context
  menus and its own keys**. The whiteboard's tool rail is hidden on a map;
  nothing of the whiteboard's chrome shows unless it applies to a map.
- **A map is never empty and never stuck.** Deleting the last node leaves
  a root placeholder ("Untitled map, type to start"); the toolbar always
  has "Add topic", "Add sub-topic", "Add sibling" enabled for the
  selection; a collapsed branch shows a count badge that reopens it on
  click and on Space.
- Every node action is reachable three ways: the node's edit strip, the
  right-click radial, and a key. The keys are the industry's: Tab child,
  Enter sibling, Shift+Enter above, Delete removes the node and re-parents
  its children, Shift+Delete removes the branch, F2 edits, Space toggles
  collapse, arrows walk the tree, Ctrl+D duplicate, Ctrl+Shift+arrows
  move within siblings, Alt held turns adds into removes (Coggle).
- Styling is per node and per link and is stored in `data` (shape, fill,
  border, text size, weight, alignment, icon, image, link style, link
  label position), with **inheritance down the branch** and "Reset to
  branch" on any node; the theme picks defaults, never overrides a
  choice.
- Layouts: tree right, tree left, both sides (Coggle), org chart down,
  logic chart, fishbone, timeline (XMind), radial (MindNode); a branch
  can override the map's layout; auto-arrange is a command, not a
  constant, so a hand-placed node stays put until asked.
- Everything the map shows is in the tree endpoint and the FreeMind and
  OPML exports round-trip; a feature that cannot round-trip is not built.
- **The last topic cannot be deleted; clearing the map is offered
  instead** (the owner asked directly: "should the user even be able to
  delete the primary core node??"). A map with no nodes is a dead end by
  construction: every add gesture hangs off a node that is already there,
  so removing the last one removes the way to make the next one. Refusing
  the delete is a smaller surprise than silently recreating a root under
  the same name, and "clear the map" says what it does, so the refusal
  carries that action: it takes the whole map away and leaves one blank
  topic ready to type into. Enforced at both delete paths (the map's own
  subtree delete, and the generic object delete the Delete tool, the
  context menu and the selection bar use), because a rule enforced at one
  of two doors is not a rule.
- **Multiple roots are allowed** ("should the user be able to make
  multiple main core nodes??"). Yes: real maps have several trunks, and
  nothing in the code has ever assumed one, `wbMapIndex` returns a list of
  roots, the tidy pass lays out a forest, and Enter on a root already adds
  another root. So this is a decision to keep and to surface, not to build:
  "Add topic" in the map dock adds a top-level topic whatever is selected,
  which is the only visible way to make the second trunk.
- **There is no "sub core" node type** ("sub core nodes??"). A node with
  children *is* the sub core: it already draws larger than its leaves
  through the branch colour and the depth it sits at, and its subtree
  already collapses, tidies, transplants and exports as a unit. A third
  tier would be a concept the data model does not have (`parent_id` and
  `kind`, nothing else), and every export format this plan commits to
  round-tripping (FreeMind, OPML, Markdown outline) has no way to carry
  it, so it would be a decoration that vanishes on the first export.

- **Space keeps the pan; `C` folds a branch; Space works on the fold
  control itself** (left open by the previous run, decided here). Held space
  is this canvas's pan gesture from every tool (`wbZoomFilter`) and a map
  node is selected nearly all the time once someone is editing, so binding
  Space to collapse would take the pan away exactly when it is most used and
  would make a map pan differently from a board, which is the opposite of
  "the mindmap can keep important and usable parts of the whiteboard". So
  the key on the canvas is `C` (bare, beside Tab, Enter, F and the arrows;
  `c` is not a tool key), and §12.1 item 7's "reopens on click and on Space"
  is met where it actually reads as a button: with the keyboard focus on a
  node's chevron or on the dock's Collapse button, the Space handler stands
  aside and the browser's own activation folds the branch.
- **A node carries its colour on its own card, so a trunk can set one.** The
  previous run disabled the picker on a root because "a colour paints only
  the line coming into a node and a root has no incoming line". That is true
  of the edge and false of the card: `wbPaintMapNode` writes `--wb-branch` on
  every node and `.wb-map-node` already draws it as the 4px spine down the
  leading edge, so a root's colour was drawn all along and only the control
  refused to set it. It does not cascade: the roots' children are the
  first-level topics and start the palette over by design, which is Coggle's
  rule, so a trunk's colour marks the trunk and every branch under it keeps
  its own. The picker's title says which of the two it is doing.

### 12.1 Phase 6a, the controls (1 session)

1. **The map toolbar** (replaces the whiteboard rail on a map): Add
   topic, Add sub-topic, Add sibling, Delete, Collapse/Expand branch,
   Layout ▾, Style ▾ (theme, branch colours, line style), Insert ▾ (note
   card, image, link, icon, boundary, summary, relationship), Arrange
   (auto, tidy siblings, centre root), Focus, Present, Export ▾, and the
   undo pair; seven visible at most, the rest in ▾ menus, per the dock
   grammar. **Part of this is built**: the board-only sections (draw,
   shapes, the free adds) are hidden on a map and the map's own Topic and
   Branch sections carry add topic, add child, add sibling, collapse,
   branch colour and focus; the layout picker and Tidy are still in the
   top bar, and the Style, Insert, Arrange, Present and Export menus are
   not written. See `agent-remaining/mindmap.md` for the measured numbers
   and the rest of the list.
2 to 9. **Built, 2026-09-12**: the node edit strip, the node radial, the
   link radial, the mid-line add, the text-size grip, uncollapse, drag to
   transplant and sever. Moved whole to HISTORY.md ("Moved from the plans,
   2026-09-12", MINDMAP_PLAN.md §12.1 items 2 to 9); a plan holds open work
   only. What is left of those eight, with the reason each was left:

   - **An image in a node** (item 2's fourth). It needs the board's upload
     path and a node whose body is a picture rather than a label, which is a
     second node shape, not a fourth button on a strip.
   - **Comment on a node** (item 3's sixth) is §12.2 item 6 and belongs
     there, not here.
   - **The control points on a curve drag to reshape it** (item 5's third).
     A tree edge is derived from `parent_id` and has no row to store a
     control point on; it would be two more `data` fields on the child and a
     third hit target per line, and it now has to compose with the three
     line shapes item 4 added.
   - **Line thickness** (item 4's "style") was not built: the three shapes
     and the dash carry the distinction, and a fourth axis on a 2px line is
     a setting nobody can see.
   - **Shift+drag off a node to sever** (item 9's second gesture). Sever is
     on both rings; the drag gesture would collide with drag-to-transplant,
     which took the same pointer.

Gate: every action reachable by strip, radial and key (mindmap.js counts
the three routes per action); an empty map recreates a root; 0 console
errors; export/import round-trip of a map using every feature.

**The gate's round-trip half is met** (2026-09-12, sixth run): everything the
strip and the two rings write is in the FreeMind and OPML exports and comes
back through both imports, and the two rings stay inside the canvas at any
viewport. The account, including which field each format has an honest home
for and which ride as private attributes, is in HISTORY.md ("Moved from the
plans, 2026-09-12", "what the sixth run closed behind items 2 to 9"). What is
still open of §12.1 is item 1's four dock menus and the five sub-items above.
**Node shape is built too** (2026-09-12, same run): four shapes, decided in
§12.0 and recorded in HISTORY with the rest.

### 12.2 Phase 6b, structure and richness (1 session)

1. **Boundaries** (XMind): a shaded background shape around a branch or
   a lasso'd set, with a label, a colour and a style (rounded, cloud,
   dashed); moves with its nodes.
2. **Summaries** (XMind): a bracket beside a set of siblings with a
   summary node.
3. **Relationships**: a cross-link between any two nodes with an arrow
   and a label, curved, dashed by default so it reads as secondary.
4. **Markers and task info**: priority 1 to 5, progress 0 to 100, flags,
   due date (a reminder can be created from it), a checkbox; filter the
   map by marker; the outline view shows them as columns.
5. **Notes on nodes**: a text note behind a node (the small marker
   opens it); a node that is a notebook note shows the note's own text
   here, editable both ways.
6. **Comments** (MindMeister): a thread per node, count marker.
7. **Multiple roots and floating topics**; **numbering** of branches
   (1, 1.1, 1.1.1) as a toggle; **auto-colour by branch** as the
   default theme with eight curated palettes.
8. **Outline view** beside the map (a two-pane split): the same tree as
   indented text, editable, Tab and Shift+Tab re-parent, every edit
   mirrored live.
9. **Presentation mode** (MindMeister): step through branches with the
   arrow keys, each step zooming to a branch; Escape ends.
10. **Export**: PNG at 2x with the theme, PDF, SVG, FreeMind .mm, OPML,
    Markdown outline, plain-text outline; **import** by drop of .mm,
    .opml, .txt outline or Markdown, and from XMind's .xmind (its
    content.json) read-only.
Gate: mindmap3.js extended with one check per feature; the 201-node map
keeps 60 fps pan (measured with the frame probe); round-trip of every
export that claims it.

### 12.3 Phase 6c, what only a notebook can do (½ session)

1. **Nodes are notes**: any node can become a note (and stays linked); a
   note dragged from the Library becomes a node with its card; the map
   node and the note title edit each other.
2. **Grow with the AI**: on any node, "Suggest branches" proposes five
   children from the notebook (grounded, with the source note on each),
   "Expand from my notes" fills a branch from search results,
   "Summarise this branch" writes the parent's note.
3. **From a question**: "Make a map of..." in chat proposes a map
   (exists, Phase 4) and now opens it in the map editor with the
   proposal as floating topics to accept or discard.
4. **Graph sync**: a map's cross-links become graph links (kind "map");
   the graph's "Mind map" selection action (Phase 4) opens here with the
   layout pre-chosen.
5. **Study mode**: hide all but the root, reveal a branch at a time,
   with a "recall" prompt before revealing (the note's own text is the
   answer); progress stored per map.
Gate: each AI action grounded (its sources listed) and faked in tests;
the study mode measured on a 40-node map.

### 12.4 Not built until asked

Real-time collaboration, cloud sync, voice-to-map, AI image generation
in nodes.

## Placed from INBOX, 2026-09-09

The owner's reports this plan owns, moved whole from INBOX.md with their numbers (never reused). Each becomes a phase row when its phase is written; until then this list is the phase.

24. **"New board" and "New mind map": same or different?** Decision: the
    dock grammar allows one filled button per dock, so one filled "New"
    button opens a two-row menu (Board, Mind map), each with its icon and a
    one-line hint. Two side-by-side filled buttons is the wrong answer.
    Owner: docks.md.

## Placed from INBOX, 2026-09-09 (the owner's evening batch)

- "in the all library subtab, the mindmap I made called bubble tea shows as
  a note" (two screenshots: the All list draws a "bubble tea" row with a
  note's pencil icon, while Boards & maps draws the same thing as a map
  with 3 nodes). The All view's kind test does not know about maps, so a
  map falls through to the note branch.
- "the boards and maps dashboard widget is ugly and needs fixing", and
  "also the ui at the top of the boards and maps subtab dock is broken and
  miss wrapped. remember responsive design!" (screenshot at ~2000px: the
  search box and sort/view controls on one line, then New board, New mind
  map, Map from notes, Import outline, refresh and help wrapped onto a
  second line below them, left-aligned under nothing).
