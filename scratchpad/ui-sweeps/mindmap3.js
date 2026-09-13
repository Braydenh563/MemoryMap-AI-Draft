// Mindmap Phase 3 verification (MINDMAP_PLAN.md §5 items 11, 12, 13, 17).
//
// A sibling of mindmap.js rather than more of it: that script owns Phase 2
// (drawing, keys, tidy, collapse, the Library card) and is the regression net
// for it — 35 assertions that must keep passing untouched. This one owns
// Phase 3, which is the map's life *outside* the canvas: a reference node
// placed by hand, an OPML import, the chip and preview on the dashboard,
// timeline, chat and note bodies, and the map in the graph.
//
//   BASE=http://127.0.0.1:8797 SCRATCH=/tmp/mm-map3 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/mindmap3.js
//
// THEME=dark sweeps the other theme; VIEWPORT=390x844 the narrow one (§10.4
// named both as reasoned-but-never-observed).
const { boot } = require("./lib.js");

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  — " + detail : ""}`);
}

const VIEWPORT = (() => {
  const raw = process.env.VIEWPORT;
  if (!raw) return { width: 1440, height: 900 };
  const [w, h] = raw.split("x").map(Number);
  return { width: w || 1440, height: h || 900 };
})();

// **The two map actions moved behind the dock's ⋯.** The Boards & maps dock
// gained a `dock-more` menu on 2026-09-09 (the owner's "the ui at the top of
// the boards and maps subtab dock is broken and miss wrapped" report), and
// `#wb-boards-import` and `#wb-boards-generate` went into it. A click on a
// button inside a closed `<details>` is a click on something invisible, which
// Playwright reports as a thirty-second timeout rather than as "the control
// moved": this sweep sat at that timeout from the day the dock changed.
async function openBoardsMore(page) {
  await page.evaluate(() => {
    const menu = document.getElementById("library-boards-more");
    if (menu) menu.open = true;
  });
  await page.waitForTimeout(250);
}

(async () => {
  const { browser, page, OUT } = await boot({ viewport: VIEWPORT });
  const narrow = VIEWPORT.width < 700;

  // A note to point a reference node at, made through the API the app itself
  // uses — the point of this sweep is the map UI, not the capture box.
  const noteTitle = `Reference target ${Date.now() % 100000}`;
  const noteId = await page.evaluate(
    (title) =>
      window
        .apiJson("/entries", {
          method: "POST",
          body: JSON.stringify({ content: `# ${title}\n\nSomething to point at.` }),
        })
        .then((e) => e.id),
    noteTitle
  );
  check("a note exists to point at", Boolean(noteId), `entry ${noteId}`);
  await page.evaluate(() => window.loadEntries && window.loadEntries());
  await page.waitForTimeout(1200);

  // --- onto Boards & maps ---------------------------------------------------
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(900);

  // ==========================================================================
  // Item 2 — import UI (§5 item 17)
  // ==========================================================================
  const OPML = `<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0"><head><title>Imported outline</title></head><body>
  <outline text="Roots"><outline text="Alpha"/><outline text="Beta"><outline text="Beta one"/></outline></outline>
  <outline text="Second root"/>
</body></opml>`;
  await openBoardsMore(page);
  const importBtn = await page.$("#wb-boards-import");
  check("the boards landing offers an import action", Boolean(importBtn));
  if (importBtn) {
    await importBtn.click();
    await page.waitForTimeout(500);
    // The file input is the app's own hidden-input pattern, so the file is
    // handed to it directly rather than through a native chooser Playwright
    // cannot drive.
    await page.setInputFiles("#wb-import-map-file", {
      name: "outline.opml",
      mimeType: "text/x-opml",
      buffer: Buffer.from(OPML, "utf8"),
    });
    await page.waitForTimeout(3000);
  }
  const imported = await page.evaluate(() =>
    window.apiJson("/whiteboard/boards").then((rows) => {
      const map = rows.find((b) => b.title === "Imported outline");
      return map ? { id: map.id, type: map.type, objects: map.object_count, edges: (map.preview_edges || []).length } : null;
    })
  );
  // Five outlines in the file: Roots, Alpha, Beta, Beta one, Second root.
  check(
    "an OPML import produces a map with one node per outline",
    imported && imported.type === "map" && imported.objects === 5,
    JSON.stringify(imported)
  );
  check(
    "the imported map's preview carries its tree edges",
    imported && imported.edges >= 3,
    imported ? `${imported.edges} edges` : "no map"
  );

  // The other format, through the same control — the extension is the only
  // thing that picks it, so this is the branch that is not shared.
  await page.click("#wb-back-to-boards");
  await page.waitForTimeout(1600);
  await openBoardsMore(page);
  await page.click("#wb-boards-import");
  await page.waitForTimeout(400);
  await page.setInputFiles("#wb-import-map-file", {
    name: "outline.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Markdown outline\n\n- One\n  - One a\n- Two\n", "utf8"),
  });
  await page.waitForTimeout(3000);
  const mdImport = await page.evaluate(() =>
    window.apiJson("/whiteboard/boards").then((rows) => {
      const map = rows.find((b) => b.title === "Markdown outline");
      return map ? { type: map.type, objects: map.object_count } : null;
    })
  );
  check(
    "a Markdown outline imports through the same control",
    mdImport && mdImport.type === "map" && mdImport.objects === 3,
    JSON.stringify(mdImport)
  );

  // ==========================================================================
  // Item 1 — a reference node placed by hand (§5 item 11)
  // ==========================================================================
  // An import opens the map it just made, so this is back on the canvas.
  const onCanvas = await page.evaluate(
    () => !document.getElementById("wb-canvas-view")?.classList.contains("hidden")
  );
  check("an import opens the map it just created", onCanvas);
  await page.click("#wb-back-to-boards");
  await page.waitForTimeout(1600);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  await page.fill(".confirm-overlay input[type=text]", "Phase 3 map");
  await page.click('.confirm-overlay .seg button[data-value="map"]');
  await page.waitForTimeout(150);
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2500);
  const boardId = await page.evaluate(() => window.currentBoardId);
  check("a map is open to build on", Boolean(boardId), `board ${boardId}`);
  // A one-node map sits at the canvas origin, which is under the top bar —
  // so every pointer gesture below would be intercepted by it. Same fit call
  // mindmap.js makes before it measures layouts.
  await page.evaluate(() => window.wbZoomToFit && window.wbZoomToFit({ animate: false }));
  await page.waitForTimeout(800);

  // The root is selected on creation, so its hover controls are already live.
  const refButton = await page.$(".wb-map-node .wb-map-ref");
  check("a map node offers a 'from the library' control beside +", Boolean(refButton));
  // Both controls are in one row, so they cannot overlap — measured, because
  // two hand-placed buttons off one corner is how this file's own count badge
  // collided with the chevron twice.
  const controlGap = await page.evaluate(() => {
    const add = document.querySelector(".wb-map-node .wb-map-add");
    const ref = document.querySelector(".wb-map-node .wb-map-ref");
    if (!add || !ref) return null;
    const a = add.getBoundingClientRect();
    const b = ref.getBoundingClientRect();
    const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return { overlapX: Math.round(overlapX), overlapY: Math.round(overlapY), aw: Math.round(a.width), bw: Math.round(b.width) };
  });
  check(
    "the + and library buttons do not overlap",
    controlGap && !(controlGap.overlapX > 0 && controlGap.overlapY > 0),
    JSON.stringify(controlGap)
  );

  if (refButton) {
    // Hover the node first: the row is `opacity: 0; pointer-events: none`
    // until the node is hovered or selected, so a forced click at those
    // coordinates lands on whatever is *under* it — which is what a first run
    // of this sweep did, silently, with no error anywhere.
    await page.hover(".wb-map-node");
    await page.waitForTimeout(300);
    await refButton.click();
    await page.waitForTimeout(1200);
  }
  const pickerUp = await page.$(".confirm-overlay .entry-pick-list");
  check("the library picker opens", Boolean(pickerUp));
  const pickerTabs = await page.evaluate(() =>
    [...document.querySelectorAll(".confirm-overlay .seg [data-pick-kind]")].map((b) => b.dataset.pickKind)
  );
  check(
    "the picker offers all four reference kinds",
    pickerTabs.join(",") === "note,document,file,link",
    pickerTabs.join(",")
  );
  //: **The row geometry, reported against this dialog**: "the list rows
  //: overflow their width (long titles run past the row edges, icons drift
  //: off-centre, rows are centred text instead of left-aligned)". All three
  //: were one cause, the row is a `<button>`, so the generic button rule
  //: centred it, and `text-overflow` on a flex container does nothing to a
  //: flex item that will not shrink. Measured before the fix: 63px of title
  //: past the row's own edge.
  const pickRows = await page.evaluate(() => {
    const rows = [...document.querySelectorAll(".confirm-overlay .entry-pick-row")];
    if (!rows.length) return null;
    return rows.map((r) => {
      const rr = r.getBoundingClientRect();
      const label = r.querySelector(".ph-text");
      const icon = r.querySelector(".ph-lead");
      const lr = label && label.getBoundingClientRect();
      const ir = icon && icon.getBoundingClientRect();
      const s = getComputedStyle(r);
      return {
        justify: s.justifyContent,
        shadow: s.boxShadow,
        h: Math.round(rr.height),
        rowOverflow: r.scrollWidth - r.clientWidth,
        labelInside: lr ? Math.round(rr.right - lr.right) : null,
        labelLeft: lr ? Math.round(lr.left - rr.left) : null,
        iconLeft: ir ? Math.round(ir.left - rr.left) : null,
        ellipsis: label ? getComputedStyle(label).textOverflow : null,
      };
    });
  });
  check("(D) every picker row is left-aligned and none overflows its width",
    Boolean(pickRows) && pickRows.every((r) => r.justify === "flex-start" && r.rowOverflow === 0),
    JSON.stringify(pickRows && pickRows[0]));
  check("(D) the title ellipsises inside the row instead of running past it",
    Boolean(pickRows) && pickRows.every((r) => r.ellipsis === "ellipsis" && r.labelInside >= 0),
    JSON.stringify(pickRows && pickRows.map((r) => r.labelInside)));
  check("(D) the icon column is fixed, so every title starts at the same x",
    Boolean(pickRows) && new Set(pickRows.map((r) => r.labelLeft)).size === 1
      && new Set(pickRows.map((r) => r.iconLeft)).size === 1,
    JSON.stringify(pickRows && pickRows.map((r) => [r.iconLeft, r.labelLeft])));
  check("(D) row height is consistent and no row carries the button glow",
    Boolean(pickRows) && new Set(pickRows.map((r) => r.h)).size === 1
      && pickRows.every((r) => r.shadow === "none"),
    JSON.stringify(pickRows && [pickRows[0].h, pickRows[0].shadow]));
  const pickBox = await page.evaluate(() => {
    const card = document.querySelector(".confirm-overlay .entry-pick-card");
    const list = document.querySelector(".confirm-overlay .entry-pick-list");
    const cr = card.getBoundingClientRect();
    return {
      onModalRecipe: card.classList.contains("modal-card") && card.classList.contains("confirm-card"),
      fitsViewport: cr.top >= 0 && cr.bottom <= window.innerHeight,
      listScrolls: getComputedStyle(list).overflowY,
      listContains: getComputedStyle(list).overscrollBehavior,
      bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
    };
  });
  check("(D) the dialog is on the app's modal recipe and the scroll is in the list",
    pickBox.onModalRecipe && pickBox.fitsViewport && pickBox.listScrolls === "auto"
      && pickBox.listContains === "contain" && pickBox.bodyOverflow === 0,
    JSON.stringify(pickBox));

  await page.fill(".confirm-overlay input[type=search]", noteTitle.slice(0, 18));
  await page.waitForTimeout(700);
  const rowCount = await page.$$eval(".confirm-overlay .entry-pick-row", (r) => r.length);
  check("the picker narrows as you type", rowCount >= 1, `${rowCount} row(s)`);
  await page.click(".confirm-overlay .entry-pick-row");
  await page.waitForTimeout(3000);

  const refNode = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".wb-object.wb-map-node")];
    // **A shown icon, not an icon element.** Every node carries a
    // `.wb-map-node-icon` since the node edit strip landed (a topic can wear
    // one of twelve Phosphor icons), hidden when it has nothing to show, so
    // "the node that has an icon element" is now every node and this found
    // the root.
    const ref = nodes.find((el) => {
      const icon = el.querySelector(".wb-map-node-icon");
      return icon && !icon.hidden;
    });
    if (!ref) return null;
    return {
      text: ref.querySelector(".wb-map-text")?.textContent.trim() || "",
      icon: ref.querySelector(".wb-map-node-icon")?.className || "",
      count: nodes.length,
    };
  });
  check(
    "the reference node shows the note's own title",
    refNode && refNode.text === noteTitle,
    JSON.stringify(refNode)
  );
  check(
    "the reference node draws its kind icon",
    refNode && /ph-note\b/.test(refNode.icon),
    refNode ? refNode.icon : "no node"
  );
  const stored = await page.evaluate(
    (id) =>
      window.apiJson(`/whiteboard/boards/${id}/tree`).then((tree) => {
        const flat = [];
        const walk = (ns) => ns.forEach((n) => { flat.push(n); walk(n.children || []); });
        walk(tree.roots || []);
        const ref = flat.find((n) => n.kind !== "topic");
        return ref ? { kind: ref.kind, ref_id: ref.ref_id, text: ref.text } : null;
      }),
    boardId
  );
  check(
    "the node is stored as kind+ref_id, with the label resolved server-side",
    stored && stored.kind === "note" && stored.ref_id === noteId && stored.text === noteTitle,
    JSON.stringify(stored)
  );

  // The right-click is the discoverable half of the same gesture, and on a map
  // node it now opens the node radial rather than the board's flat menu
  // (MINDMAP_PLAN §12.1 item 3). Both ways to add a child are slots in it.
  const ctxItems = await page.evaluate(() => {
    const node = document.querySelector(".wb-object.wb-map-node");
    if (!node) return [];
    selectWbItem("object", Number(node.getAttribute("data-id")));
    node.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, clientX: 300, clientY: 300 }));
    const ring = document.getElementById("wb-map-radial");
    if (ring.classList.contains("hidden")) return [];
    return [...ring.querySelectorAll(".wb-map-radial-slot")]
      .map((b) => b.getAttribute("aria-label"));
  });
  check(
    "a map node's right-click ring offers both ways to add a child",
    // `wbSyncMapRadialAlt` rewrites the two add slots' labels from their
    // titles as soon as the ring opens, so the branch slot reads "Add a
    // branch off this topic (Tab)": matched as a substring rather than whole,
    // which is what that label is actually for.
    ctxItems.some((l) => /Add a branch off this topic/.test(l || ""))
      && ctxItems.some((l) => /Add a child from the library/.test(l || "")),
    ctxItems.join(" | ")
  );
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  // A dark-theme / narrow-viewport reading of the node itself (§10.4).
  const nodePaint = await page.evaluate(() => {
    const node = document.querySelector(".wb-object.wb-map-node");
    if (!node) return null;
    const text = node.querySelector(".wb-map-text");
    const cs = getComputedStyle(node);
    const ts = getComputedStyle(text);
    const r = node.getBoundingClientRect();
    return {
      fill: cs.backgroundColor,
      colour: ts.color,
      branch: cs.getPropertyValue("--wb-branch").trim(),
      width: Math.round(r.width),
      clipped: text.scrollHeight - text.clientHeight,
    };
  });
  check(
    "a map node's text is not clipped by its box",
    nodePaint && nodePaint.clipped <= 0,
    nodePaint ? `scrollHeight-clientHeight = ${nodePaint.clipped}px, node ${nodePaint.width}px wide` : "no node"
  );
  console.log("NODEPAINT " + JSON.stringify(nodePaint));
  await page.screenshot({ path: `${OUT}/mindmap3-node-${process.env.THEME || "light"}-${VIEWPORT.width}.png` });

  // ==========================================================================
  // Item 3 — one mapChip() and one mapPreview(), used everywhere
  // ==========================================================================
  const shared = await page.evaluate(() => ({
    chip: typeof window.mapChip === "function",
    preview: typeof window.mapPreview === "function",
  }));
  check("mapChip() and mapPreview() are one shared pair", shared.chip && shared.preview, JSON.stringify(shared));

  const previewShape = await page.evaluate((id) =>
    window.apiJson("/whiteboard/boards").then((rows) => {
      const board = rows.find((b) => b.id === id);
      const svg = window.mapPreview(board, { size: "card" });
      if (!svg) return null;
      return {
        edges: svg.querySelectorAll(".board-minimap-edge").length,
        blocks: svg.querySelectorAll("rect").length,
        cls: svg.getAttribute("class"),
        inlineStyle: svg.querySelector("[style]") ? "yes" : "no",
      };
    }),
    boardId
  );
  check(
    "mapPreview draws the tree — edges under blocks, no inline style (CSP)",
    previewShape && previewShape.edges >= 1 && previewShape.blocks >= 2 && previewShape.inlineStyle === "no",
    JSON.stringify(previewShape)
  );

  // --- the Library card (the drawing this was factored out of) --------------
  await page.click("#wb-back-to-boards");
  await page.waitForTimeout(1800);
  const libraryCard = await page.evaluate(() => {
    const card = [...document.querySelectorAll(".library-board-card")].find(
      (c) => c.querySelector(".library-card-title")?.textContent === "Phase 3 map"
    );
    if (!card) return null;
    const svg = card.querySelector("svg.board-minimap");
    return svg
      ? { edges: svg.querySelectorAll(".board-minimap-edge").length, dots: svg.querySelectorAll("rect").length }
      : null;
  });
  check(
    "the Library card still draws the map through the shared preview",
    libraryCard && libraryCard.edges >= 1,
    JSON.stringify(libraryCard)
  );

  // --- the dashboard widget -------------------------------------------------
  await page.click('[data-tab="dashboard"]');
  await page.waitForTimeout(2500);
  const dash = await page.evaluate(() => {
    const card = document.querySelector('[data-widget="boards"]');
    if (!card) return { widget: false };
    const chips = [...card.querySelectorAll(".map-chip")];
    const svgs = [...card.querySelectorAll("svg.board-minimap")];
    return {
      widget: true,
      chips: chips.length,
      chipText: chips[0] ? chips[0].textContent.trim() : "",
      previews: svgs.length,
      edges: svgs.reduce((n, s) => n + s.querySelectorAll(".board-minimap-edge").length, 0),
    };
  });
  check(
    "the dashboard boards widget draws map chips with tree previews",
    dash.widget && dash.chips >= 1 && dash.edges >= 1,
    JSON.stringify(dash)
  );

  // --- the timeline ---------------------------------------------------------
  await page.click('[data-tab="timeline"]');
  await page.waitForTimeout(3000);
  const timeline = await page.evaluate(() => {
    const chips = [...document.querySelectorAll("#timeline-grid .timeline-dot .map-chip")];
    return {
      chips: chips.length,
      first: chips[0] ? chips[0].textContent.trim() : "",
      // A chip inside a <button> dot must not itself be a button: nested
      // interactive controls are invalid HTML that browsers silently reflow.
      nested: chips.filter((c) => c.tagName === "BUTTON").length,
      dots: document.querySelectorAll("#timeline-grid .timeline-dot").length,
    };
  });
  check(
    "a map on the timeline reads as a map chip, not as a note",
    timeline.chips >= 1 && timeline.nested === 0,
    JSON.stringify(timeline)
  );

  // --- a note body ----------------------------------------------------------
  const bodyNoteId = await page.evaluate(
    () =>
      window
        .apiJson("/entries", {
          method: "POST",
          body: JSON.stringify({ content: "Planning notes\n\nSee [[# Phase 3 map]] for the shape." }),
        })
        .then((e) => e.id)
  );
  await page.click('[data-tab="notes"]');
  await page.waitForTimeout(500);
  await page.evaluate(() => window.loadEntries && window.loadEntries());
  await page.waitForTimeout(2500);
  const inNote = await page.evaluate((id) => {
    // The note list's cards are `<li data-id>` (entryItem, app.js) — scoped to
    // the card, never to `document`, because a fallback to the whole page
    // finds the dashboard's own chips and reports a pass for the wrong reason
    // (it did, on the first run of this sweep).
    const card = document.querySelector(`#entry-list li[data-id="${id}"]`);
    if (!card) return { card: false };
    const chip = card.querySelector(".map-chip");
    return chip
      ? { card: true, text: chip.textContent.trim(), tag: chip.tagName, wiki: card.querySelectorAll(".wiki-link").length }
      : { card: true, chip: false, html: card.querySelector(".entry-content")?.textContent.slice(0, 120) };
  }, bodyNoteId);
  check(
    "a [[map]] reference in a note body renders as a map chip",
    inNote && inNote.card && /Phase 3 map/.test(inNote.text || "") && inNote.tag === "BUTTON",
    JSON.stringify(inNote)
  );

  // --- the chat transcript --------------------------------------------------
  const chatChip = await page.evaluate(
    (id) => {
      const row = window.toolTouchedRow([
        { kind: "map", id, label: "Phase 3 map" },
      ]);
      if (!row) return null;
      const chip = row.querySelector(".tool-touched-chip");
      return chip ? { text: chip.textContent.trim(), icon: chip.querySelector("i")?.className || "" } : null;
    },
    boardId
  );
  check(
    "a map a tool touched renders as a chip in the transcript",
    chatChip && /Phase 3 map/.test(chatChip.text) && /tree-structure/.test(chatChip.icon),
    JSON.stringify(chatChip)
  );

  // ==========================================================================
  // Item 5 — the map in the graph (§5 item 13)
  // ==========================================================================
  const graphData = await page.evaluate(
    ({ board, note }) =>
      window.apiJson("/graph?include_maps=true").then((data) => {
        const mapNode = (data.nodes || []).find((n) => n.id === board);
        const edge = (data.edges || []).find(
          (e) => e.kind === "map" && e.source === board && e.target === note
        );
        return {
          node: mapNode ? { type: mapNode.type, preview: mapNode.preview } : null,
          edge: Boolean(edge),
          mapEdges: (data.edges || []).filter((e) => e.kind === "map").length,
        };
      }),
    { board: boardId, note: noteId }
  );
  check(
    "the map is a node in the graph, marked as a map",
    graphData.node && graphData.node.type === "map",
    JSON.stringify(graphData.node)
  );
  check(
    "its note-node is an edge from the map to that note",
    graphData.edge,
    `${graphData.mapEdges} map edge(s)`
  );
  const graphOff = await page.evaluate(() =>
    window.apiJson("/graph").then((d) => (d.edges || []).filter((e) => e.kind === "map").length)
  );
  check("map edges are opt-in, like documents and entities", graphOff === 0, `${graphOff} without the flag`);

  // ==========================================================================
  // Item 4 — attaching a map to a chat message (§5 item 11)
  // ==========================================================================
  await page.click('[data-tab="chat"]');
  await page.waitForTimeout(1200);
  await page.click("#attach-note");
  await page.waitForTimeout(600);
  const mapsTab = await page.$('#note-picker-sources [data-picker-source="maps"]');
  check("the composer's attach picker offers Maps", Boolean(mapsTab));
  if (mapsTab) {
    await mapsTab.click();
    await page.waitForTimeout(1200);
    const rows = await page.$$eval("#note-picker-list li", (li) => li.length);
    check("the Maps source lists the notebook's maps", rows >= 1, `${rows} row(s)`);
    await page.click("#note-picker-list li input[type=checkbox], #note-picker-list li button");
    await page.waitForTimeout(700);
  }
  await page.click("#note-picker-done").catch(() => {});
  await page.waitForTimeout(600);
  const staged = await page.evaluate(() => {
    const box = document.getElementById("chat-board-attachments");
    if (!box) return null;
    return {
      hidden: box.classList.contains("hidden"),
      chips: box.querySelectorAll(".attachment-chip").length,
      text: box.textContent.trim(),
    };
  });
  check(
    "an attached map shows as a removable chip on the composer",
    staged && !staged.hidden && staged.chips === 1,
    JSON.stringify(staged)
  );
  //: `attachedBoards` is a top-level `let`, which is *not* on `window` (only
  //: `var` is) — the first version of this check read `window.attachedBoards`,
  //: got `undefined`, and reported a failure about the composer rather than
  //: about itself. The staged state is read through the UI instead, which is
  //: what a person can see anyway: the picker's own count line, and whether
  //: the chip's ✕ takes it back off.
  const countLine = await page.evaluate(() => {
    const el = document.getElementById("note-picker-count");
    return el ? el.textContent.trim() : null;
  });
  check(
    "the picker's count line says a map is attached",
    /1 mind map/.test(countLine || ""),
    String(countLine)
  );
  await page.click("#chat-board-attachments .attachment-remove");
  await page.waitForTimeout(500);
  const afterRemove = await page.evaluate(() => {
    const box = document.getElementById("chat-board-attachments");
    return { chips: box.querySelectorAll(".attachment-chip").length, hidden: box.classList.contains("hidden") };
  });
  check(
    "removing the chip un-stages the map",
    afterRemove.chips === 0 && afterRemove.hidden,
    JSON.stringify(afterRemove)
  );

  await page.screenshot({ path: `${OUT}/mindmap3-chat-${process.env.THEME || "light"}-${VIEWPORT.width}.png` });

  // ==========================================================================
  // Item 5 — the preview redesign (agent-remaining/mindmap.md F)
  //
  // What is being measured, and why a screenshot would not have caught any of
  // it: the miniature used to be drawn with preserveAspectRatio="none" into a
  // fixed 100x56 viewBox, so every board in the Library was the same shape as
  // every other and a map that runs down the page was squashed into one that
  // runs across. The board's own ratio now ships as `preview_aspect` and the
  // drawing is letterboxed at it, which is a number: the rendered paper's
  // width/height against the ratio the server sent.
  // ==========================================================================
  const shapes = await page.evaluate(async () => {
    const api = window.apiJson;
    const made = {};
    const build = async (name, dx, dy) => {
      const board = await api("/whiteboard/boards", {
        method: "POST",
        body: JSON.stringify({ name, type: "map", layout: "tree-right" }),
      });
      const node = (body) =>
        api(`/whiteboard/boards/${board.id}/nodes`, { method: "POST", body: JSON.stringify(body) });
      const root = await node({ kind: "topic", text: "Root", x: 0, y: 0 });
      await node({ kind: "topic", parent_id: root.id, text: "First branch", x: dx, y: 0 });
      await node({ kind: "topic", parent_id: root.id, text: "Second branch", x: dx, y: dy });
      made[name] = board.id;
    };
    // Two boards of deliberately different shape, and one with nothing on it.
    await build("Wide preview map", 800, 220);
    await build("Tall preview map", 160, 700);
    const empty = await api("/whiteboard/boards", {
      method: "POST",
      body: JSON.stringify({ name: "Empty preview map", type: "map", layout: "tree-right" }),
    });
    made["Empty preview map"] = empty.id;
    return made;
  });
  check("three boards exist to measure the preview against", Object.keys(shapes).length === 3, JSON.stringify(shapes));

  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(1800);

  const NAMES = ["Wide preview map", "Tall preview map", "Empty preview map"];
  const drawn = await page.evaluate(async (names) => {
    const rows = await window.apiJson("/whiteboard/boards");
    const out = {};
    for (const name of names) {
      const board = rows.find((b) => b.title === name) || null;
      const card = [...document.querySelectorAll(".library-board-card")].find(
        (c) => c.querySelector(".library-card-title")?.textContent === name
      );
      const svg = card ? card.querySelector("svg.board-minimap") : null;
      const paper = svg ? svg.querySelector(".board-minimap-paper") : null;
      const box = paper ? paper.getBoundingClientRect() : null;
      const svgBox = svg ? svg.getBoundingClientRect() : null;
      const edges = svg ? [...svg.querySelectorAll(".board-minimap-edge")] : [];
      const nodes = svg ? [...svg.querySelectorAll(".board-minimap-branch")] : [];
      out[name] = {
        aspect: board ? board.preview_aspect : null,
        // The paper *is* the board: its rendered ratio is the assertion.
        drawn: box && box.height ? Number((box.width / box.height).toFixed(3)) : null,
        paperW: box ? Number(box.width.toFixed(1)) : null,
        boxW: svgBox ? Number(svgBox.width.toFixed(1)) : null,
        boxH: svgBox ? Number(svgBox.height.toFixed(1)) : null,
        edges: edges.length,
        curves: edges.filter((e) => e.tagName === "path" && /C/.test(e.getAttribute("d") || "")).length,
        colours: [...new Set(nodes.map((n) => n.getAttribute("fill")))],
        rounded: nodes.length > 0 && nodes.every((n) => Number(n.getAttribute("rx")) > 0),
        labels: svg ? svg.querySelectorAll(".board-minimap-label").length : 0,
        emptyState: svg ? Boolean(svg.querySelector(".board-minimap-paper-empty")) : null,
        ghostNodes: svg ? svg.querySelectorAll(".board-minimap-ghost rect").length : 0,
        inlineStyle: svg && svg.querySelector("[style]") ? "yes" : "no",
      };
    }
    return out;
  }, NAMES);

  for (const name of ["Wide preview map", "Tall preview map"]) {
    const m = drawn[name];
    const off = m && m.aspect && m.drawn ? Math.abs(m.drawn / m.aspect - 1) : 1;
    check(
      `${name}: the thumbnail is drawn at the board's own ratio (within 2%)`,
      off <= 0.02,
      JSON.stringify({ ...m, off: Number(off.toFixed(4)) })
    );
  }
  check(
    "a tall board is letterboxed inside the card's box rather than stretched",
    drawn["Tall preview map"].paperW < drawn["Tall preview map"].boxW - 2,
    JSON.stringify({ paper: drawn["Tall preview map"].paperW, box: drawn["Tall preview map"].boxW })
  );
  check(
    "the two boards are drawn at different shapes",
    Math.abs(drawn["Wide preview map"].drawn - drawn["Tall preview map"].drawn) > 0.3,
    `${drawn["Wide preview map"].drawn} vs ${drawn["Tall preview map"].drawn}`
  );
  check(
    "every edge is a curve, not a straight segment",
    drawn["Wide preview map"].edges >= 2 && drawn["Wide preview map"].curves === drawn["Wide preview map"].edges,
    JSON.stringify({ edges: drawn["Wide preview map"].edges, curves: drawn["Wide preview map"].curves })
  );
  check(
    "the two branches draw in two different colours, rounded",
    drawn["Wide preview map"].colours.length >= 2 && drawn["Wide preview map"].rounded,
    JSON.stringify(drawn["Wide preview map"].colours)
  );
  check(
    "a card wide enough to read carries its labels, a letterboxed sliver does not",
    drawn["Wide preview map"].labels >= 2 && drawn["Tall preview map"].labels === 0,
    JSON.stringify({ wide: drawn["Wide preview map"].labels, tall: drawn["Tall preview map"].labels })
  );
  check(
    "an empty map draws the designed empty state, not nothing",
    drawn["Empty preview map"].emptyState === true && drawn["Empty preview map"].ghostNodes === 3,
    JSON.stringify(drawn["Empty preview map"])
  );
  check(
    "no thumbnail carries a style attribute (CSP drops them)",
    NAMES.every((n) => drawn[n].inlineStyle === "no"),
    JSON.stringify(NAMES.map((n) => drawn[n].inlineStyle))
  );
  await page.screenshot({ path: `${OUT}/mindmap3-previews-${process.env.THEME || "light"}-${VIEWPORT.width}.png` });

  // The same picture in the dashboard's widget, from the same function: the
  // failure this guards against is one surface keeping the old drawing, which
  // is exactly what happened before mapPreview was factored out.
  await page.click('[data-tab="dashboard"]');
  await page.waitForTimeout(2500);
  const dashShape = await page.evaluate(() => {
    const card = document.querySelector('[data-widget="boards"]');
    const svg = card ? card.querySelector("svg.board-minimap") : null;
    const paper = svg ? svg.querySelector(".board-minimap-paper") : null;
    const box = paper ? paper.getBoundingClientRect() : null;
    const svgBox = svg ? svg.getBoundingClientRect() : null;
    return {
      papers: card ? card.querySelectorAll(".board-minimap-paper").length : 0,
      thumbs: card ? card.querySelectorAll("svg.board-minimap").length : 0,
      letterboxed: box && svgBox ? box.width <= svgBox.width + 1 && box.height <= svgBox.height + 1 : null,
    };
  });
  check(
    "the dashboard widget draws the same letterboxed paper",
    dashShape.papers >= 1 && dashShape.papers === dashShape.thumbs && dashShape.letterboxed === true,
    JSON.stringify(dashShape)
  );

  // ==========================================================================
  // Item 6 — make a map of these notes (§5 item 15), driven end to end
  //
  // No model runs in this sandbox, so what is exercised here is the path a
  // first run of the app takes anyway: the server falls back to the notebook's
  // own filing and says so, and the dialog reports which of the two wrote the
  // outline. The three steps are the assertion: pick, review, create.
  // ==========================================================================
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(900);

  const madeNotes = await page.evaluate(() =>
    Promise.all(
      ["# Kolmogorov complexity\n\nstrings", "# Entropy\n\nbits"].map((content) =>
        window.apiJson("/entries", { method: "POST", body: JSON.stringify({ content }) })
      )
    ).then((rows) => rows.map((r) => r.id))
  );
  await page.evaluate(() => window.loadEntries && window.loadEntries());
  await page.waitForTimeout(1500);
  check("two notes exist to build a map from", madeNotes.length === 2, JSON.stringify(madeNotes));

  const boardsBefore = await page.evaluate(() =>
    window.apiJson("/whiteboard/boards").then((rows) => rows.length)
  );
  await openBoardsMore(page);
  await page.click("#wb-boards-generate");
  await page.waitForTimeout(700);
  const picker = await page.evaluate(() => {
    const rows = [...document.querySelectorAll(".entry-pick-check")];
    const confirm = [...document.querySelectorAll(".confirm-actions button")].find((b) =>
      /Propose a map/.test(b.textContent)
    );
    return { rows: rows.length, disabled: confirm ? confirm.disabled : null };
  });
  check(
    "the note picker opens with its confirm disabled until something is ticked",
    picker.rows >= 2 && picker.disabled === true,
    JSON.stringify(picker)
  );

  // Tick the two notes by their labels, so this cannot pass by ticking
  // whatever happened to be first in the list.
  const ticked = await page.evaluate(() => {
    let on = 0;
    for (const row of document.querySelectorAll(".entry-pick-check")) {
      if (!/Kolmogorov complexity|Entropy/.test(row.textContent)) continue;
      const box = row.querySelector("input");
      box.checked = true;
      box.dispatchEvent(new Event("change", { bubbles: true }));
      on += 1;
    }
    return on;
  });
  check("both notes can be ticked in one pass", ticked === 2, String(ticked));

  await page.evaluate(() => {
    const confirm = [...document.querySelectorAll(".confirm-actions button")].find((b) =>
      /Propose a map/.test(b.textContent)
    );
    confirm.click();
  });
  await page.waitForTimeout(1500);

  const review = await page.evaluate(async () => {
    const card = document.querySelector(".wb-proposal-card");
    if (!card) return null;
    const outline = card.querySelector(".wb-proposal-outline");
    const style = outline ? getComputedStyle(outline) : null;
    return {
      said: card.querySelector("p.muted")?.textContent || "",
      lines: outline ? outline.value.trim().split("\n").length : 0,
      hasBoth: outline
        ? /Kolmogorov complexity/.test(outline.value) && /Entropy/.test(outline.value)
        : false,
      mono: style ? style.fontFamily : "",
      width: outline ? Math.round(outline.getBoundingClientRect().width) : 0,
      cardWidth: Math.round(card.getBoundingClientRect().width),
      boards: await window.apiJson("/whiteboard/boards").then((rows) => rows.length),
    };
  });
  check(
    "the proposal is shown as an editable outline holding both notes",
    review && review.hasBoth && review.lines >= 3,
    JSON.stringify(review)
  );
  check(
    "it says who wrote the outline rather than implying the model did",
    /model did not answer|local model/.test(review.said || ""),
    JSON.stringify(review.said)
  );
  check(
    "the outline is monospace and fits inside its dialog",
    /mono/i.test(review.mono || "") && review.width <= review.cardWidth,
    JSON.stringify({ mono: review.mono, width: review.width, card: review.cardWidth })
  );

  // The user edits the proposal: this is the step the whole preview exists
  // for, so the map that lands has to be the edited one, not the proposed one.
  await page.evaluate(() => {
    const outline = document.querySelector(".wb-proposal-outline");
    outline.value = "- Information theory\n  - Kolmogorov complexity\n  - Entropy\n";
    const name = document.querySelector(".wb-proposal-card input[type=text]");
    name.value = "Swept map";
  });
  const before = await page.evaluate(
    () => document.querySelectorAll(".library-board-card").length
  );
  await page.evaluate(() => {
    const create = [...document.querySelectorAll(".wb-proposal-card button")].find((b) =>
      /Create the map/.test(b.textContent)
    );
    create.click();
  });
  await page.waitForTimeout(2500);

  const built = await page.evaluate(async () => {
    const boards = await window.apiJson("/whiteboard/boards");
    const board = boards.find((b) => b.title === "Swept map");
    if (!board) return { made: false, before: boards.length };
    const tree = await window.apiJson(`/whiteboard/boards/${board.id}/tree`);
    const flat = [];
    const walk = (nodes) => nodes.forEach((n) => (flat.push(n), walk(n.children)));
    walk(tree.roots);
    return {
      made: true,
      onCanvas: document.querySelectorAll(".wb-map-node").length,
      texts: flat.map((n) => n.text),
      kinds: flat.map((n) => n.kind),
      refs: flat.filter((n) => n.ref_id).length,
    };
  });
  check(
    "the edited outline is what gets built, as real note nodes",
    built.made &&
      built.texts.join("|") === "Information theory|Kolmogorov complexity|Entropy" &&
      built.kinds.join("|") === "topic|note|note" &&
      built.refs === 2,
    JSON.stringify(built)
  );
  check(
    "and the new map is opened, drawn, rather than left in the list",
    built.onCanvas >= 3,
    String(built.onCanvas)
  );
  check(
    "the proposal itself wrote nothing: no board until it was accepted",
    review.boards === boardsBefore,
    JSON.stringify({ before: boardsBefore, atReview: review.boards, atAccept: before })
  );
  await page.screenshot({ path: `${OUT}/mindmap3-generated-${process.env.THEME || "light"}-${VIEWPORT.width}.png` });

  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} checks passed.`);
  console.log("shots in " + OUT);
  await browser.close();
  process.exit(passed === results.length ? 0 : 1);
})().catch((error) => {
  console.error("SWEEP CRASHED", error);
  process.exit(2);
});
