// Mindmap frontend verification (MINDMAP_PLAN.md §5 Phase 2 + §5 item 10).
//
// Drives a real Chromium against the running app: creates a map through the
// board dialog, builds five nodes with Tab/Enter and no mouse, tidies,
// collapses a branch, and asserts what the DOM and the API actually say —
// rather than looking at a screenshot and calling it good, which CLAUDE.md
// records costing six rounds on one popup.
//
//   BASE=http://127.0.0.1:8793 SCRATCH=/tmp/mm-shots \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/mindmap.js
const { boot } = require("./lib.js");

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  — " + detail : ""}`);
}

(async () => {
  const { browser, page, OUT } = await boot();

  // --- get onto the Boards & maps sub-tab -----------------------------------
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(800);

  // --- create a map through the real dialog (item 2) -------------------------
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  const seg = await page.$(".confirm-overlay .seg");
  check("the New board dialog carries a type segmented control", Boolean(seg));
  await page.fill(".confirm-overlay input[type=text]", "Verification map");
  // Choose "Mind map".
  await page.click('.confirm-overlay .seg button[data-value="map"]');
  await page.waitForTimeout(150);
  const segActive = await page.$eval(
    '.confirm-overlay .seg button[data-value="map"]',
    (b) => b.classList.contains("active")
  );
  check("choosing Mind map marks that segment active", segActive);
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2500);

  const boardId = await page.evaluate(() => window.currentBoardId);
  check("a board id is open after creating the map", Boolean(boardId), `board ${boardId}`);

  //: **A map is not a note.** Reported: "I made a mindmap naming it test and I
  //: think it came up as a new note??", it did, on every surface built on
  //: `GET /entries`, which had no board filter at all. Asserted at the
  //: endpoint *and* in the rendered list, because the two failed together and
  //: either one alone would let the other come back.
  const notNote = await page.evaluate(async (id) => {
    const rows = await window.apiJson("/entries?limit=500");
    const boards = await window.apiJson("/entries?boards=only&limit=500");
    return {
      inNotes: rows.some((e) => e.id === id),
      anyBoardInNotes: rows.some((e) => e.is_board),
      inBoardsOnly: boards.some((e) => e.id === id),
    };
  }, boardId);
  check("(C) the new map is not in the notes list, and neither is any board",
    !notNote.inNotes && !notNote.anyBoardInNotes, JSON.stringify(notNote));
  check("(C) ?boards=only still hands the map back, for the pickers that need it",
    notNote.inBoardsOnly, JSON.stringify(notNote));

  const chipVisible = await page.evaluate(() => {
    const c = document.getElementById("wb-map-chip");
    return Boolean(c && !c.hidden && c.getBoundingClientRect().width > 0);
  });
  check("the Map chip shows in the board top bar", chipVisible);
  const layoutValue = await page.evaluate(() => {
    const s = document.getElementById("wb-map-layout");
    return s && !s.hidden ? s.value : null;
  });
  check("the layout picker shows and reads tree-right", layoutValue === "tree-right", String(layoutValue));

  // --- the root topic is DRAWN (item 1, the blocker) ------------------------
  const rootDrawn = await page.evaluate(() =>
    document.querySelectorAll(".wb-object.wb-map-node").length
  );
  check("the root topic renders as a map node", rootDrawn === 1, `${rootDrawn} node(s)`);
  const rootText = await page.evaluate(() => {
    const el = document.querySelector(".wb-map-node .wb-map-text");
    return el ? el.textContent.trim() : null;
  });
  check("the root node shows its text", rootText === "Verification map", String(rootText));

  // --- five nodes with Tab/Enter and no mouse (item 3) ----------------------
  // The root is already selected by createNewBoard, so the keyboard is live.
  // Tab, Enter, Tab builds a root + 4 = five topics without a click.
  await page.evaluate(() => document.getElementById("whiteboard-container")?.focus());
  const press = async (key) => {
    await page.keyboard.press(key);
    await page.waitForTimeout(1100);
    // A new node opens in edit mode; blur it so the next key is a gesture and
    // not text (which is exactly what the editor's own stopPropagation does).
    await page.evaluate(() => document.activeElement?.blur?.());
    await page.waitForTimeout(250);
  };
  await press("Tab");    // child of root
  await press("Enter");  // sibling of that child
  await press("Tab");    // child of the sibling
  await press("Enter");  // sibling of that child

  // Through the app's own `apiJson`, not a bare fetch: the notebook is behind
  // the lock, and a hand-rolled header gets the token's storage key wrong
  // (it is "token") and 401s while the UI beside it works perfectly.
  const tree = await page.evaluate(
    (id) => window.apiJson(`/whiteboard/boards/${id}/tree`),
    boardId
  );
  const countTopics = (nodes) =>
    (nodes || []).reduce((n, x) => n + (x.kind === "topic" ? 1 : 0) + countTopics(x.children), 0);
  const topics = countTopics(tree.roots);
  check("(a) five topic nodes are in GET /tree", topics === 5, `${topics} topics`);

  const depth = (nodes, d = 1) =>
    (nodes || []).reduce((m, x) => Math.max(m, depth(x.children, d + 1), d), 0);
  check("the keyboard built a real tree, not a flat list", depth(tree.roots) >= 3,
    `depth ${depth(tree.roots)}`);

  // --- Tidy, then no two node boxes overlap (item 4) ------------------------
  await page.click("#wb-map-tidy");
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.wbZoomToFit && window.wbZoomToFit({ animate: false }));
  await page.waitForTimeout(600);

  const boxes = await page.evaluate(() =>
    [...document.querySelectorAll(".wb-object.wb-map-node")].map((el) => {
      const r = el.getBoundingClientRect();
      return { id: el.dataset.id, x: r.x, y: r.y, w: r.width, h: r.height };
    })
  );
  let overlaps = [];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i], b = boxes[j];
      const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (ox > 1 && oy > 1) overlaps.push(`${a.id}×${b.id} (${Math.round(ox)}×${Math.round(oy)}px)`);
    }
  }
  check("(b) no two node boxes overlap after Tidy", overlaps.length === 0,
    `${boxes.length} nodes, ${overlaps.length} overlaps ${overlaps.join(", ")}`);

  // Is any label cut off? `scrollHeight` vs `clientHeight`, the one number
  // that settles it (CLAUDE.md) — measured on **`.wb-map-text`**, not on the
  // node. Measuring the node was the first thing tried here and it reported
  // every node clipped: a node is `overflow: visible` and carries two
  // deliberately overhanging children (the `+` affordance below it and the
  // count badge above), so its own `scrollHeight` is larger than its box by
  // design and says nothing at all about the text. The label element is
  // where a clip would actually happen.
  const clipped = await page.evaluate(() =>
    [...document.querySelectorAll(".wb-object.wb-map-node")]
      .map((el) => ({ el, t: el.querySelector(".wb-map-text") }))
      .filter(({ t }) => t && t.scrollHeight > t.clientHeight + 1)
      .map(({ el, t }) => `${el.dataset.id}: ${t.scrollHeight}>${t.clientHeight}`)
  );
  check("no map node clips its own label", clipped.length === 0, clipped.join(", "));

  // A node grows with its text rather than slicing it: give one a long label
  // and its box must get taller than the one-line minimum.
  const grew = await page.evaluate(async () => {
    const index = window.wbMapIndex();
    const leaf = index.nodes.find((n) => !(index.childrenOf.get(n.id) || []).length);
    if (!leaf) return null;
    const before = document.querySelector(`.wb-object[data-id="${leaf.id}"]`)?.offsetHeight;
    leaf.data = { ...leaf.data, content: "A deliberately long topic label that has to wrap onto several lines inside its own node box" };
    window.renderWhiteboardNow();
    const after = document.querySelector(`.wb-object[data-id="${leaf.id}"]`)?.offsetHeight;
    const text = document.querySelector(`.wb-object[data-id="${leaf.id}"] .wb-map-text`);
    return { before, after, textClipped: text ? text.scrollHeight > text.clientHeight + 1 : null };
  });
  check("a long label grows its node instead of being clipped",
    grew && grew.after > grew.before && grew.textClipped === false,
    grew ? `${grew.before}px → ${grew.after}px, label clipped: ${grew.textClipped}` : "no leaf");

  // Inline markdown really becomes elements, not literal asterisks.
  const inline = await page.evaluate(() => {
    const index = window.wbMapIndex();
    const leaf = index.nodes.find((n) => !(index.childrenOf.get(n.id) || []).length);
    if (!leaf) return null;
    leaf.data = { ...leaf.data, content: "**bold** and *italic* and `code`" };
    window.renderWhiteboardNow();
    const el = document.querySelector(`.wb-object[data-id="${leaf.id}"] .wb-map-text`);
    return el
      ? { strong: el.querySelectorAll("strong").length, em: el.querySelectorAll("em").length,
          code: el.querySelectorAll("code").length, text: el.textContent }
      : null;
  });
  check("a topic renders inline bold / italic / code",
    inline && inline.strong === 1 && inline.em === 1 && inline.code === 1,
    inline ? `strong=${inline.strong} em=${inline.em} code=${inline.code} "${inline.text}"` : "none");
  // Put the map back the way the rest of the run expects it.
  await page.evaluate(() => {
    const index = window.wbMapIndex();
    const leaf = index.nodes.find((n) => !(index.childrenOf.get(n.id) || []).length);
    if (leaf) { leaf.data = { ...leaf.data, content: "Branch" }; window.renderWhiteboardNow(); }
  });

  const edgeCount = await page.evaluate(() =>
    document.querySelectorAll(".wb-map-edges .wb-map-edge").length
  );
  check("parent→child edges are drawn", edgeCount === 4, `${edgeCount} edges`);

  await page.screenshot({ path: OUT + "/mindmap-tidy.png" });

  // --- collapse a branch (item 5) -------------------------------------------
  // Fold the root's first child, which has a subtree under it.
  // `wbState` is a module-level `let`, so it is not a property of `window`;
  // `wbMapIndex` is a top-level function declaration, so it is. Reading the
  // tree through the app's own index is also the more honest check — it is
  // what the renderer itself uses.
  const target = await page.evaluate(() => {
    const index = window.wbMapIndex();
    const withKids = index.nodes.find(
      (o) => o.parent_id != null && (index.childrenOf.get(o.id) || []).length > 0
    );
    return withKids ? withKids.id : null;
  });
  check("a branch with children exists to collapse", Boolean(target), `node ${target}`);
  const before = await page.evaluate(() => document.querySelectorAll(".wb-map-node").length);
  await page.click(`.wb-object[data-id="${target}"] .wb-map-collapse`);
  await page.waitForTimeout(1400);
  const after = await page.evaluate(() => document.querySelectorAll(".wb-map-node").length);
  const hiddenIds = await page.evaluate((t) => {
    const index = window.wbMapIndex();
    return (index.childrenOf.get(t) || [])
      .map((o) => o.id)
      .filter((id) => document.querySelector(`.wb-object[data-id="${id}"]`) !== null);
  }, target);
  check("(c) the collapsed branch is not in the DOM", hiddenIds.length === 0 && after < before,
    `${before} → ${after} nodes, ${hiddenIds.length} children still present`);
  const badge = await page.evaluate((t) => {
    const el = document.querySelector(`.wb-object[data-id="${t}"] .wb-map-count`);
    return el && !el.hidden ? el.textContent : null;
  }, target);
  check("(c) its count badge shows the buried total", Boolean(badge) && Number(badge) > 0,
    `badge "${badge}"`);

  // The badge must not land on the control you press to undo the fold.
  const badgeClash = await page.evaluate((t) => {
    const node = document.querySelector(`.wb-object[data-id="${t}"]`);
    const b = node.querySelector(".wb-map-count").getBoundingClientRect();
    const c = node.querySelector(".wb-map-collapse").getBoundingClientRect();
    const ox = Math.min(b.right, c.right) - Math.max(b.left, c.left);
    const oy = Math.min(b.bottom, c.bottom) - Math.max(b.top, c.top);
    return { ox: Math.round(ox), oy: Math.round(oy) };
  }, target);
  check("the count badge does not cover the collapse chevron",
    badgeClash.ox <= 0 || badgeClash.oy <= 0,
    `overlap ${badgeClash.ox}×${badgeClash.oy}px`);

  await page.screenshot({ path: OUT + "/mindmap-collapsed.png" });

  // --- export (item 7) ------------------------------------------------------
  // Expand again first, so the export is asked about the whole map.
  await page.click(`.wb-object[data-id="${target}"] .wb-map-collapse`);
  await page.waitForTimeout(1200);
  // Export lives behind the top bar's "Board" menu, not loose in the bar.
  await page.click('[aria-controls="wb-board-menu"]');
  await page.waitForTimeout(500);
  await page.click("#wb-export");
  await page.waitForTimeout(500);
  const menu = await page.evaluate(() =>
    [...document.querySelectorAll("#wb-export-menu button")].map((b) => b.textContent.trim())
  );
  check("the export menu offers Markdown and OPML on a map",
    menu.includes("Markdown (.md)") && menu.includes("OPML (.opml)"),
    menu.join(" | "));
  await page.keyboard.press("Escape");
  await page.evaluate(() => document.getElementById("wb-export-menu")?.remove());
  await page.waitForTimeout(300);

  // The server's own outline, through the endpoint the menu entry calls.
  const outline = await page.evaluate(async (id) => {
    const res = await window.api(`/whiteboard/boards/${id}/export?format=markdown`);
    return res.text();
  }, boardId);
  check("the Markdown outline comes back with the map's nodes in it",
    outline.includes("Verification map") && outline.split("\n").filter((l) => l.trim().startsWith("-")).length >= 4,
    `${outline.split("\n").length} lines`);

  // PNG/SVG: the canvas export has to actually draw the new node kinds. It
  // did not before this session — every map exported as an empty rectangle.
  const svg = await page.evaluate(() => window.wbBuildExportSvg("whole").svg);
  check("the SVG export draws the map's nodes and edges",
    svg.includes("Verification map") && (svg.match(/<path/g) || []).length >= 4,
    `${(svg.match(/<rect/g) || []).length} rects, ${(svg.match(/<path/g) || []).length} paths`);

  // --- the rest of the keyboard set (item 3) --------------------------------
  const shape = () => page.evaluate(() => {
    const index = window.wbMapIndex();
    return Object.fromEntries(index.nodes.map((n) => [n.id, n.parent_id]));
  });
  // Arrow navigation: from the root, Right goes to its first child, Down to
  // that child's next sibling, Left back to the parent.
  await page.evaluate(() => {
    const index = window.wbMapIndex();
    window.selectWbItem("object", index.roots[0].id);
  });
  await page.waitForTimeout(400);
  // From the DOM, not from `wbSelectedItem` — that is a module-level `let`, so
  // it is not a property of `window` and reads as `undefined` from here. The
  // selection class is the same fact and is the one the user can see.
  const selectedId = () => page.evaluate(() => {
    const el = document.querySelector(".wb-object.wb-map-node.wb-selected");
    return el ? Number(el.dataset.id) : null;
  });
  const rootId = await selectedId();
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(700);
  const child = await selectedId();
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(700);
  const sibling = await selectedId();
  await page.keyboard.press("ArrowLeft");
  await page.waitForTimeout(700);
  const backUp = await selectedId();
  check("arrows walk the tree (right = child, down = sibling, left = parent)",
    child !== rootId && sibling !== child && backUp === rootId,
    `root ${rootId} → child ${child} → sibling ${sibling} → parent ${backUp}`);

  // Shift+Tab outdents: the node's parent becomes its grandparent.
  const deep = await page.evaluate(() => {
    const index = window.wbMapIndex();
    const node = index.nodes.find((n) => {
      const p = index.byId.get(n.parent_id);
      return p && p.parent_id != null;
    });
    if (node) window.selectWbItem("object", node.id);
    return node ? { id: node.id, parent: node.parent_id, grandparent: index.byId.get(node.parent_id).parent_id } : null;
  });
  check("a node two levels deep exists to outdent", Boolean(deep), JSON.stringify(deep));
  await page.waitForTimeout(400);
  await page.keyboard.down("Shift");
  await page.keyboard.press("Tab");
  await page.keyboard.up("Shift");
  await page.waitForTimeout(1600);
  const afterOutdent = (await shape())[deep.id];
  check("Shift+Tab re-parents to the grandparent",
    Number(afterOutdent) === deep.grandparent,
    `parent ${deep.parent} → ${afterOutdent} (grandparent was ${deep.grandparent})`);

  // Delete takes the subtree, and the toast's Undo puts it back with its
  // shape intact — not as a heap of roots.
  const beforeDelete = await shape();
  const doomed = await page.evaluate(() => {
    const index = window.wbMapIndex();
    const node = index.nodes.find((n) => n.parent_id != null && (index.childrenOf.get(n.id) || []).length);
    if (node) window.selectWbItem("object", node.id);
    return node ? { id: node.id, size: 1 + (index.childrenOf.get(node.id) || []).length } : null;
  });
  check("a branch exists to delete", Boolean(doomed), JSON.stringify(doomed));
  await page.waitForTimeout(400);
  await page.keyboard.press("Delete");
  await page.waitForTimeout(1800);
  const afterDelete = await shape();
  check("Delete removes the whole subtree",
    Object.keys(afterDelete).length === Object.keys(beforeDelete).length - doomed.size,
    `${Object.keys(beforeDelete).length} → ${Object.keys(afterDelete).length} nodes`);
  const undoBtn = await page.$(".toast button, .toast-action");
  check("the delete offers an Undo on its toast", Boolean(undoBtn));
  if (undoBtn) {
    await undoBtn.click();
    await page.waitForTimeout(3000);
  }
  const afterUndo = await shape();
  // Ids change on a re-create (they are new rows), so the shape is compared by
  // the *count* of nodes and by the parent-child edge count — which is what
  // "the tree came back with the shape it had" actually means.
  const edgesOf = (m) => Object.values(m).filter((p) => p !== null && p !== undefined).length;
  check("Undo restores the subtree with its parent links",
    Object.keys(afterUndo).length === Object.keys(beforeDelete).length
      && edgesOf(afterUndo) === edgesOf(beforeDelete),
    `${Object.keys(afterUndo).length} nodes / ${edgesOf(afterUndo)} edges vs ${Object.keys(beforeDelete).length} / ${edgesOf(beforeDelete)}`);

  // --- the other layouts (item 4) -------------------------------------------
  for (const layout of ["tree-down", "radial"]) {
    await page.selectOption("#wb-map-layout", layout);
    await page.waitForTimeout(3000);
    await page.evaluate(() => window.wbZoomToFit && window.wbZoomToFit({ animate: false }));
    await page.waitForTimeout(700);
    const laid = await page.evaluate(() =>
      [...document.querySelectorAll(".wb-object.wb-map-node")].map((el) => {
        const r = el.getBoundingClientRect();
        return { id: el.dataset.id, x: r.x, y: r.y, w: r.width, h: r.height };
      })
    );
    let clashes = 0;
    for (let i = 0; i < laid.length; i += 1) {
      for (let j = i + 1; j < laid.length; j += 1) {
        const a = laid[i], b = laid[j];
        if (Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 1
          && Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 1) clashes += 1;
      }
    }
    check(`${layout}: no two node boxes overlap`, clashes === 0,
      `${laid.length} nodes, ${clashes} overlaps`);
    await page.screenshot({ path: `${OUT}/mindmap-${layout}.png` });
  }
  // Back to the layout the rest of the run expects.
  await page.selectOption("#wb-map-layout", "tree-right");
  await page.waitForTimeout(2500);

  // --- the Library card draws the map as a tree (item 6) --------------------
  await page.click("#wb-back-to-boards");
  await page.waitForTimeout(1800);
  const chips = await page.evaluate(() =>
    [...document.querySelectorAll("#library-boards-filter .library-chip")].map((b) => b.textContent.trim())
  );
  check("the Maps / Boards / All chip row exists", chips.length === 3, chips.join(" | "));

  const preview = await page.evaluate((title) => {
    const cards = [...document.querySelectorAll(".library-board-card")];
    const card = cards.find((c) => c.querySelector(".library-card-title")?.textContent === title);
    if (!card) return null;
    return {
      edges: card.querySelectorAll(".board-minimap-edge").length,
      dots: card.querySelectorAll(".board-minimap-card, .board-minimap-object").length,
    };
  }, "Verification map");
  check("(d) the Library card draws >= 4 preview edges",
    preview && preview.edges >= 4,
    preview ? `${preview.edges} edges, ${preview.dots} dots` : "card not found");

  // Filtering to Maps keeps it and drops ordinary boards.
  await page.click('#library-boards-filter [data-board-filter="map"]');
  await page.waitForTimeout(1200);
  const filtered = await page.evaluate(() =>
    [...document.querySelectorAll(".library-board-card .library-card-title")].map((t) => t.textContent)
  );
  check("the Maps chip filters the gallery to maps only",
    filtered.includes("Verification map") && !filtered.includes("Default board"),
    filtered.join(" | "));

  await page.screenshot({ path: OUT + "/mindmap-library.png" });

  // --- an ordinary whiteboard is untouched ----------------------------------
  // Everything above runs on every board, gated on `wbIsMap()`. This is the
  // other half of that claim: open a plain board, put a text box on it, and
  // check the map chrome stays away and the text box still behaves.
  await page.click('#library-boards-filter [data-board-filter="all"]');
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    const cards = [...document.querySelectorAll(".library-board-card")];
    const plain = cards.find((c) => /Default board/.test(c.textContent));
    if (plain) plain.click();
  });
  await page.waitForTimeout(2500);
  const plainBoard = await page.evaluate(async () => {
    const chip = document.getElementById("wb-map-chip");
    const picker = document.getElementById("wb-map-layout");
    const tidy = document.getElementById("wb-map-tidy");
    const before = document.querySelectorAll(".wb-object").length;
    await window.wbCreateTextBox(300, 300);
    await new Promise((r) => setTimeout(r, 900));
    const box = document.querySelector(".wb-object-text");
    return {
      chipHidden: chip.hidden, pickerHidden: picker.hidden, tidyHidden: tidy.hidden,
      isMap: window.wbIsMap(),
      edges: document.querySelectorAll(".wb-map-edges").length,
      mapNodes: document.querySelectorAll(".wb-map-node").length,
      added: document.querySelectorAll(".wb-object").length - before,
      textBoxHasGrip: Boolean(box && box.querySelector(".wb-object-grip")),
      textBoxHasHandles: box ? box.querySelectorAll(".wb-resize-handle").length : 0,
      textBoxHeight: box ? box.style.height : null,
    };
  });
  check("an ordinary board shows no map chrome",
    plainBoard.chipHidden && plainBoard.pickerHidden && plainBoard.tidyHidden
      && !plainBoard.isMap && plainBoard.edges === 0 && plainBoard.mapNodes === 0,
    JSON.stringify(plainBoard));
  check("a text box on an ordinary board still gets its grip and 8 handles",
    plainBoard.added === 1 && plainBoard.textBoxHasGrip && plainBoard.textBoxHasHandles === 8
      && /px$/.test(plainBoard.textBoxHeight || ""),
    `added ${plainBoard.added}, grip ${plainBoard.textBoxHasGrip}, handles ${plainBoard.textBoxHasHandles}, height ${plainBoard.textBoxHeight}`);
  await page.screenshot({ path: OUT + "/mindmap-plain-board.png" });

  // --- the owner's reports A and B, on a real map ---------------------------
  //
  // A: "there's a permanent selection box on my mindmap". Reproduced first
  // (a marquee released outside the container left a 552x440 `.wb-marquee`
  // that survived Escape, an empty-canvas click and a board reopen), so
  // these four checks are the four leaks, not a guess at one.
  await page.evaluate(async () => {
    const rows = await window.apiJson("/whiteboard/boards");
    const map = rows.find((r) => r.type === "map");
    window.openWhiteboardBoard(map.id);
  });
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.wbZoomToFit({ animate: false }));
  await page.waitForTimeout(900);
  const canvas = await page.evaluate(() => {
    const r = document.getElementById("whiteboard-container").getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  const emptyAt = { x: canvas.x + canvas.w * 0.62, y: canvas.y + canvas.h * 0.74 };
  const strayCount = () => page.evaluate(() => document.querySelectorAll(".wb-marquee, .wb-lasso").length);

  await page.mouse.move(emptyAt.x, emptyAt.y);
  await page.mouse.down();
  await page.mouse.move(emptyAt.x - 240, emptyAt.y - 250, { steps: 8 });
  const drawing = await page.evaluate(() =>
    [...document.querySelectorAll(".wb-marquee")].map((e) => `${e.getAttribute("width")}x${e.getAttribute("height")}`).join(",")
  );
  check("(A) the marquee still draws while the drag is running", /^\d+(\.\d+)?x\d+(\.\d+)?$/.test(drawing), drawing);
  await page.mouse.move(6, 6, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(500);
  const afterOutside = await strayCount();
  check("(A) a marquee released outside the board leaves nothing behind", afterOutside === 0, `${afterOutside} stray`);

  // A second pointerdown mid-drag used to orphan the first rectangle: one
  // variable held it, and the second gesture overwrote the reference.
  await page.mouse.move(emptyAt.x, emptyAt.y);
  await page.mouse.down();
  await page.mouse.move(emptyAt.x - 200, emptyAt.y - 180, { steps: 6 });
  await page.evaluate((p) => {
    document.getElementById("whiteboard-container").dispatchEvent(
      new PointerEvent("pointerdown", { clientX: p.x - 300, clientY: p.y - 40, bubbles: true, pointerId: 7 })
    );
  }, emptyAt);
  await page.mouse.up();
  await page.waitForTimeout(400);
  const afterSecond = await strayCount();
  check("(A) a second pointerdown mid-drag orphans no rectangle", afterSecond === 0, `${afterSecond} stray`);

  // And the sweep of last resort: whatever put one there, Escape and a click
  // on empty canvas both clear it, and a board reopen does not carry it over.
  await page.evaluate(() => {
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("class", "wb-marquee");
    rect.setAttribute("x", 40); rect.setAttribute("y", 40);
    rect.setAttribute("width", 330); rect.setAttribute("height", 375);
    document.getElementById("wb-zoom-group").appendChild(rect);
  });
  const planted = await strayCount();
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  const afterEscape = await strayCount();
  check("(A) Escape clears a stray selection rectangle", planted === 1 && afterEscape === 0,
    `planted ${planted}, after Escape ${afterEscape}`);
  await page.evaluate(() => {
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("class", "wb-marquee");
    rect.setAttribute("width", 330); rect.setAttribute("height", 375);
    document.getElementById("wb-zoom-group").appendChild(rect);
  });
  await page.mouse.click(emptyAt.x, emptyAt.y);
  await page.waitForTimeout(400);
  const afterClick = await strayCount();
  check("(A) a click on empty canvas clears a stray selection rectangle", afterClick === 0, `${afterClick} stray`);

  // B: "I cant highlight text in mindmap text boxes". Reproduced first, the
  // drag selected the empty string and moved the node 165px, because
  // `objDrag`'s filter excluded `.wb-text-content` and a map node's editor
  // is `.wb-map-text`.
  await page.evaluate(() => window.wbZoomToFit({ animate: false }));
  await page.waitForTimeout(800);
  const textSel = ".wb-object.wb-map-node .wb-map-text";
  await page.dblclick(textSel);
  await page.waitForTimeout(600);
  await page.keyboard.type("Alpha beta gamma");
  await page.waitForTimeout(500);
  const tr = await page.evaluate((s) => {
    const r = document.querySelector(s).getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  }, textSel);
  const transformBefore = await page.evaluate((s) => document.querySelector(s).closest(".wb-object").style.transform, textSel);
  await page.mouse.click(tr.x + 3, tr.y + tr.h / 2);
  await page.waitForTimeout(200);
  await page.mouse.move(tr.x + 3, tr.y + tr.h / 2);
  await page.mouse.down();
  await page.mouse.move(tr.x + tr.w - 8, tr.y + tr.h / 2, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(350);
  const dragSelection = await page.evaluate(() => String(window.getSelection()));
  const transformAfter = await page.evaluate((s) => document.querySelector(s).closest(".wb-object").style.transform, textSel);
  check("(B) a click-drag inside a node's editor selects its text",
    dragSelection.trim().length > 3, JSON.stringify(dragSelection));
  check("(B) that drag does not move the node",
    transformBefore === transformAfter, `${transformBefore} → ${transformAfter}`);
  const wordSel = await page.evaluate(async (t) => {
    const el = document.querySelector(t);
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  }, textSel);
  await page.mouse.dblclick(wordSel.x + 20, wordSel.y + wordSel.h / 2);
  await page.waitForTimeout(300);
  const word = await page.evaluate(() => String(window.getSelection()));
  check("(B) double-click selects a word inside the editor", word.trim().length > 0, JSON.stringify(word));
  await page.keyboard.press("End");
  await page.keyboard.down("Shift");
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
  await page.keyboard.up("Shift");
  await page.waitForTimeout(250);
  const shifted = await page.evaluate(() => String(window.getSelection()));
  check("(B) Shift+arrows extend the selection instead of walking the tree",
    shifted.length > 0 && shifted.length <= 4, JSON.stringify(shifted));
  await page.evaluate(() => document.activeElement?.blur?.());
  await page.waitForTimeout(400);
  await page.screenshot({ path: OUT + "/mindmap-select-and-edit.png" });

  // --- report E: an edge does not outlive its node -------------------------
  //
  // Reported with a screenshot: a node with "a dangling curved edge to
  // nowhere". Reproduced first: deleting one end of a cross-link removed the
  // link's row on the server but left the client's `<g class="sketch-group">`
  // on the canvas with an empty path, and it survived until a reload.
  const edgeProbe = await page.evaluate(async () => {
    const board = await window.apiJson("/whiteboard/boards", {
      method: "POST",
      body: JSON.stringify({ name: "Edge integrity", type: "map", layout: "tree-right" }),
    });
    const root = await window.apiJson(`/whiteboard/boards/${board.id}/nodes`, {
      method: "POST", body: JSON.stringify({ kind: "topic", text: "Bubble Tea", x: 200, y: 200 }),
    });
    const a = await window.apiJson(`/whiteboard/boards/${board.id}/nodes`, {
      method: "POST",
      body: JSON.stringify({ kind: "topic", text: "Tapioca", parent_id: root.id, x: 520, y: 200 }),
    });
    const b = await window.apiJson(`/whiteboard/boards/${board.id}/nodes`, {
      method: "POST",
      body: JSON.stringify({ kind: "topic", text: "Milk", parent_id: root.id, x: 520, y: 340 }),
    });
    await window.apiJson("/whiteboard/sketches", {
      method: "POST",
      body: JSON.stringify({
        board_id: board.id,
        data: JSON.stringify({
          type: "link-curve", sourceKind: "object", sourceId: a.id,
          targetKind: "object", targetId: b.id,
        }),
      }),
    });
    return { board: board.id, doomed: b.id };
  });
  await page.evaluate((id) => window.openWhiteboardBoard(id), edgeProbe.board);
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.wbZoomToFit({ animate: false }));
  await page.waitForTimeout(700);
  const edgesBefore = await page.evaluate(() => document.querySelectorAll(".sketch-group").length);
  check("(E) the cross-link is drawn before its node is deleted", edgesBefore === 1, `${edgesBefore} link(s)`);
  await page.evaluate((id) => {
    document.querySelector(`.wb-object[data-id="${id}"]`)
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));
  }, edgeProbe.doomed);
  await page.waitForTimeout(500);
  await page.keyboard.press("Delete");
  await page.waitForTimeout(2000);
  const edgesAfter = await page.evaluate(() => ({
    groups: document.querySelectorAll(".sketch-group").length,
    emptyPaths: [...document.querySelectorAll(".sketch-group .sketch-path")]
      .filter((el) => !el.getAttribute("d")).length,
  }));
  check("(E) deleting a node takes its edge off the canvas with it",
    edgesAfter.groups === 0 && edgesAfter.emptyPaths === 0, JSON.stringify(edgesAfter));
  const afterReload = await page.evaluate(async (id) => {
    const state = await window.apiJson(`/whiteboard/?board_id=${id}`);
    return state.sketches.length;
  }, edgeProbe.board);
  check("(E) and the row is gone from the board, not just from the screen",
    afterReload === 0, `${afterReload} sketch row(s)`);

  // --- report F: a new map's root opens centred, not under the top bar -----
  //
  // Reported: "new mind map's first node under the top bar". The root used
  // to be handed a fixed board coordinate on the theory that an unzoomed,
  // unpanned view puts the canvas origin at the container's own top-left,
  // which assumed a container size nobody had measured. `wbCenterOn` fixes
  // this by reading the real, rendered `#whiteboard-container` rect.
  await page.click("#wb-back-to-boards").catch(() => {});
  await page.waitForTimeout(500);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  await page.fill(".confirm-overlay input[type=text]", "Centering check");
  await page.click('.confirm-overlay .seg button[data-value="map"]');
  await page.waitForTimeout(150);
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2500);
  const centering = await page.evaluate(() => {
    const container = document.getElementById("whiteboard-container");
    const containerRect = container.getBoundingClientRect();
    const rootEl = document.querySelector(".wb-object.wb-selected");
    if (!rootEl) return null;
    const rootRect = rootEl.getBoundingClientRect();
    return {
      dx: (rootRect.left + rootRect.right) / 2 - (containerRect.left + containerRect.right) / 2,
      dy: (rootRect.top + rootRect.bottom) / 2 - (containerRect.top + containerRect.bottom) / 2,
    };
  });
  check(
    "(F) the new map's root is centred in the visible canvas",
    centering && Math.abs(centering.dx) < 4 && Math.abs(centering.dy) < 4,
    JSON.stringify(centering)
  );

  // --- report G: an edge follows every node a bulk drag moves, not only ----
  //     the one card the pointer is on --------------------------------------
  //
  // Reported: "the connections/edges get left behind when i move the
  // notes/nodes around", specifically on a multi-select drag. A single
  // card's own drag always kept its edges live (`dragging()` calls
  // `wbUpdateLinkedSketches` for the card under the pointer); the bug was
  // in `wbApplyBulkMove`, which moved every other selected card's position
  // but never touched *their* edges. The edge under test deliberately does
  // not touch the card the pointer drags, so a re-render triggered by that
  // card's own drag cannot accidentally mask the bug.
  const edgeFollow = await page.evaluate(async () => {
    const board = await window.apiJson("/whiteboard/boards", { method: "POST", body: JSON.stringify({ name: "Edge follow check" }) });
    const e1 = await window.apiJson("/entries", { method: "POST", body: JSON.stringify({ content: "Dragged", tags: [], defer_filing: true }) });
    const e2 = await window.apiJson("/entries", { method: "POST", body: JSON.stringify({ content: "Bulk-moved", tags: [], defer_filing: true }) });
    const e3 = await window.apiJson("/entries", { method: "POST", body: JSON.stringify({ content: "Bystander", tags: [], defer_filing: true }) });
    const n1 = await window.apiJson("/whiteboard/nodes", { method: "POST", body: JSON.stringify({ entry_id: e1.id, board_id: board.id, x: 200, y: 200, z: 1 }) });
    const n2 = await window.apiJson("/whiteboard/nodes", { method: "POST", body: JSON.stringify({ entry_id: e2.id, board_id: board.id, x: 500, y: 200, z: 1 }) });
    const n3 = await window.apiJson("/whiteboard/nodes", { method: "POST", body: JSON.stringify({ entry_id: e3.id, board_id: board.id, x: 500, y: 500, z: 1 }) });
    await window.apiJson("/whiteboard/sketches", {
      method: "POST",
      body: JSON.stringify({
        board_id: board.id, x: 0, y: 0, z: 1,
        data: JSON.stringify({ type: "link-straight", sourceId: n2.id, sourceKind: "node", targetId: n3.id, targetKind: "node" }),
      }),
    });
    await window.loadEntries();
    return { board: board.id, n1: n1.id, n2: n2.id };
  });
  await page.evaluate((id) => window.openWhiteboardBoard(id), edgeFollow.board);
  await page.waitForTimeout(1200);
  const card1 = await page.$(`.node-card[data-id="${edgeFollow.n1}"]`);
  const card2 = await page.$(`.node-card[data-id="${edgeFollow.n2}"]`);
  await card1.click();
  await page.waitForTimeout(150);
  await card2.click({ modifiers: ["Shift"] });
  await page.waitForTimeout(150);
  const pathBefore = await page.evaluate(() => document.querySelector(".sketch-group .sketch-path")?.getAttribute("d"));
  const box1 = await card1.boundingBox();
  await page.mouse.move(box1.x + box1.width / 2, box1.y + box1.height / 2);
  await page.mouse.down();
  await page.mouse.move(box1.x + box1.width / 2 + 150, box1.y + box1.height / 2 + 100, { steps: 10 });
  await page.waitForTimeout(200);
  const pathDuring = await page.evaluate(() => document.querySelector(".sketch-group .sketch-path")?.getAttribute("d"));
  await page.mouse.up();
  await page.waitForTimeout(300);
  check(
    "(G) a bulk-dragged card's own edge follows it mid-drag, not just the card the pointer is on",
    Boolean(pathBefore) && pathBefore !== pathDuring,
    `before=${pathBefore}  during=${pathDuring}`
  );


  // --- INBOX 42: a tree edge follows a SINGLE node's drag ------------------
  //
  // Reported with a screenshot: "a dangling curve not attached to either
  // node after a drag; the root and New topic far apart". The bulk-drag half
  // was fixed in c2912cd; a map's tree edges are not link sketches at all
  // (`wbRenderMapEdges` derives them from `parent_id`), so nothing updated
  // them during a one-node drag. Measured before the fix: 155.6px from the
  // node the edge is meant to touch mid-drag, and still 155.6px after the
  // drop once the node was pinned, because `wbMapPinOnDrag` only renders the
  // first time it pins.
  //
  // The measurement is deliberately geometric rather than "the `d` string
  // changed": every parent/child pair is matched to the edge nearest it and
  // the answer is the worst distance, in screen px, from an endpoint to the
  // rect of the node it belongs to. Zero is attached; anything else is the
  // dangling curve in the screenshot.
  const EDGE_PROBE = () => {
    const svg = document.getElementById("wb-svg-layer").getBoundingClientRect();
    const t = d3.zoomTransform(document.getElementById("whiteboard-container"));
    const toScreen = (p) => ({ x: svg.left + t.x + p.x * t.k, y: svg.top + t.y + p.y * t.k });
    const rectOf = (id) => document.querySelector(`.wb-object[data-id="${id}"]`)?.getBoundingClientRect();
    const dist = (p, r) => Math.hypot(Math.max(r.left - p.x, 0, p.x - r.right), Math.max(r.top - p.y, 0, p.y - r.bottom));
    const paths = [...document.querySelectorAll(".wb-map-edges .wb-map-edge")];
    const kinds = new Set(["topic", "note", "document", "file", "link"]);
    const objs = (wbState.objects || []).filter((o) => kinds.has(o.kind));
    let worst = 0;
    let pairs = 0;
    for (const o of objs) {
      if (o.parent_id == null || !objs.some((p) => p.id === o.parent_id)) continue;
      pairs += 1;
      const pr = rectOf(o.parent_id), cr = rectOf(o.id);
      if (!pr || !cr) { worst = Infinity; continue; }
      let best = Infinity;
      for (const path of paths) {
        const a = toScreen(path.getPointAtLength(0));
        const b = toScreen(path.getPointAtLength(path.getTotalLength()));
        best = Math.min(best, Math.max(Math.min(dist(a, pr), dist(b, pr)), Math.min(dist(a, cr), dist(b, cr))));
      }
      worst = Math.max(worst, best);
    }
    return { edges: paths.length, pairs, worst: Math.round(worst * 10) / 10 };
  };
  const dragBy = async (selector, dx, dy) => {
    const el = await page.$(selector);
    const b = await el.boundingBox();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2 + dx, b.y + b.height / 2 + dy, { steps: 12 });
    await page.waitForTimeout(150);
    const during = await page.evaluate(EDGE_PROBE);
    await page.mouse.up();
    await page.waitForTimeout(700);
    const after = await page.evaluate(EDGE_PROBE);
    return { during, after };
  };

  await page.click("#wb-back-to-boards").catch(() => {});
  await page.waitForTimeout(500);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  await page.fill(".confirm-overlay input[type=text]", "Edge drag check");
  await page.click('.confirm-overlay .seg button[data-value="map"]');
  await page.waitForTimeout(150);
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2500);
  const dragBoard = await page.evaluate(() => window.currentBoardId);
  await page.evaluate(() => document.getElementById("whiteboard-container")?.focus());
  await page.keyboard.press("Tab");
  await page.waitForTimeout(1200);
  await page.evaluate(() => document.activeElement?.blur?.());
  await page.waitForTimeout(400);

  // The other half of the screenshot: "the root and New topic far apart". The
  // server places a child (§9.3), so this asserts the placement lands beside
  // the parent and inside the visible canvas, not off-screen.
  const childPlacement = await page.evaluate(() => {
    const kinds = new Set(["topic", "note", "document", "file", "link"]);
    const objs = (wbState.objects || []).filter((o) => kinds.has(o.kind));
    const child = objs.find((o) => o.parent_id != null);
    if (!child) return null;
    const cr = document.querySelector(`.wb-object[data-id="${child.id}"]`)?.getBoundingClientRect();
    const pr = document.querySelector(`.wb-object[data-id="${child.parent_id}"]`)?.getBoundingClientRect();
    const cont = document.getElementById("whiteboard-container").getBoundingClientRect();
    if (!cr || !pr) return null;
    return {
      gap: Math.round(cr.left - pr.right),
      inside: cr.left >= cont.left - 1 && cr.right <= cont.right + 1 && cr.top >= cont.top - 1 && cr.bottom <= cont.bottom + 1,
      id: child.id, parent: child.parent_id,
    };
  });
  check("(42) a new child lands beside its parent, on screen",
    childPlacement && childPlacement.inside && childPlacement.gap > 0 && childPlacement.gap < 240,
    JSON.stringify(childPlacement));

  const atRest = await page.evaluate(EDGE_PROBE);
  check("(42) at rest, the tree edge meets both of its nodes",
    atRest.pairs === 1 && atRest.edges === 1 && atRest.worst < 2, JSON.stringify(atRest));

  const childDrag = await dragBy(`.wb-object[data-id="${childPlacement.id}"]`, 150, 100);
  check("(42) the edge follows a single-node drag of the child, mid-drag",
    childDrag.during.worst < 2, `worst ${childDrag.during.worst}px mid-drag`);
  check("(42) and is still attached after the drop",
    childDrag.after.worst < 2, `worst ${childDrag.after.worst}px`);

  // The second drag is the one the screenshot caught: the node is pinned by
  // now, so `wbMapPinOnDrag` returns early and nothing re-renders after the
  // drop. Only the per-frame follow can keep this one attached.
  const childDrag2 = await dragBy(`.wb-object[data-id="${childPlacement.id}"]`, -80, 60);
  check("(42) a second drag of the now-pinned node keeps its edge attached",
    childDrag2.during.worst < 2 && childDrag2.after.worst < 2,
    `during ${childDrag2.during.worst}px, after ${childDrag2.after.worst}px`);

  const rootDrag = await dragBy(`.wb-object[data-id="${childPlacement.parent}"]`, -120, -70);
  check("(42) the edge follows a single-node drag of the root",
    rootDrag.during.worst < 2 && rootDrag.after.worst < 2,
    `during ${rootDrag.during.worst}px, after ${rootDrag.after.worst}px`);

  await page.evaluate((id) => window.openWhiteboardBoard(id), dragBoard);
  await page.waitForTimeout(1500);
  const edgeAfterReload = await page.evaluate(EDGE_PROBE);
  check("(42) and after a reload of the board",
    edgeAfterReload.worst < 2, JSON.stringify(edgeAfterReload));

  // The concept map is the *other* creation path (`createConceptMap`, not
  // `createNewBoard("map")`), and it is a plain board of note cards joined by
  // link sketches, not a map board with derived tree edges: a fix to one is
  // not a fix to the other (agent-remaining/inbox.md records the same trap).
  // Its single-card drag goes through `dragging()` and `wbUpdateLinkedSketches`.
  const conceptDrag = await page.evaluate(async () => {
    const board = await window.apiJson("/whiteboard/boards", { method: "POST", body: JSON.stringify({ name: "Concept drag check" }) });
    const a = await window.apiJson("/entries", { method: "POST", body: JSON.stringify({ content: "Concept root", tags: [], defer_filing: true }) });
    const b = await window.apiJson("/entries", { method: "POST", body: JSON.stringify({ content: "Concept child", tags: [], defer_filing: true }) });
    const n1 = await window.apiJson("/whiteboard/nodes", { method: "POST", body: JSON.stringify({ entry_id: a.id, board_id: board.id, x: 200, y: 200, z: 1 }) });
    const n2 = await window.apiJson("/whiteboard/nodes", { method: "POST", body: JSON.stringify({ entry_id: b.id, board_id: board.id, x: 520, y: 260, z: 1 }) });
    await window.apiJson("/whiteboard/sketches", {
      method: "POST",
      body: JSON.stringify({
        board_id: board.id, x: 0, y: 0, z: 1,
        data: JSON.stringify({ type: "link-curved", sourceId: n1.id, sourceKind: "node", targetId: n2.id, targetKind: "node" }),
      }),
    });
    await window.loadEntries();
    return { board: board.id, n2: n2.id };
  });
  await page.evaluate((id) => window.openWhiteboardBoard(id), conceptDrag.board);
  await page.waitForTimeout(1400);
  const conceptCard = await page.$(`.node-card[data-id="${conceptDrag.n2}"]`);
  const cb = await conceptCard.boundingBox();
  const cardProbe = (id) => {
    const svg = document.getElementById("wb-svg-layer").getBoundingClientRect();
    const t = d3.zoomTransform(document.getElementById("whiteboard-container"));
    const path = document.querySelector(".sketch-group .sketch-path");
    const r = document.querySelector(`.node-card[data-id="${id}"]`).getBoundingClientRect();
    const ends = [0, path.getTotalLength()].map((l) => {
      const p = path.getPointAtLength(l);
      return { x: svg.left + t.x + p.x * t.k, y: svg.top + t.y + p.y * t.k };
    });
    const dist = (p) => Math.hypot(Math.max(r.left - p.x, 0, p.x - r.right), Math.max(r.top - p.y, 0, p.y - r.bottom));
    return Math.round(Math.min(dist(ends[0]), dist(ends[1])) * 10) / 10;
  };
  await page.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2);
  await page.mouse.down();
  await page.mouse.move(cb.x + cb.width / 2 + 140, cb.y + cb.height / 2 + 90, { steps: 12 });
  await page.waitForTimeout(150);
  const conceptDuring = await page.evaluate(cardProbe, conceptDrag.n2);
  await page.mouse.up();
  await page.waitForTimeout(600);
  const conceptAfter = await page.evaluate(cardProbe, conceptDrag.n2);
  check("(42) on the concept map path, a single card's connector follows it too",
    conceptDuring < 2 && conceptAfter < 2, `during ${conceptDuring}px, after ${conceptAfter}px`);


  // --- H2: a map frames itself when it opens ------------------------------
  //
  // mindmap.md H item 2, measured before the fix: a map whose root sits at
  // the board origin opened with the root's box at (16, 128)-(216, 172) and
  // the top bar at (24, 136)-(1416, 182), so `elementFromPoint` at the root's
  // own centre returned a top-bar button and the double-click that edits a
  // node never reached it. `wbFrameMapOnOpen` fits the map (or frames its
  // root at 1:1 when a fit would be illegible) on every open.
  const framingBoard = await page.evaluate(async () => {
    const b = await window.apiJson("/whiteboard/boards", {
      method: "POST",
      body: JSON.stringify({ name: "Framing check", type: "map", layout: "tree-right" }),
    });
    const root = await window.apiJson(`/whiteboard/boards/${b.id}/nodes`, {
      method: "POST",
      body: JSON.stringify({ kind: "topic", text: "Framing root", x: 0, y: 0 }),
    });
    await window.apiJson(`/whiteboard/boards/${b.id}/nodes`, {
      method: "POST",
      body: JSON.stringify({ kind: "topic", text: "Framing child", parent_id: root.id }),
    });
    return { board: b.id, root: root.id };
  });
  await page.evaluate((id) => window.openWhiteboardBoard(id), framingBoard.board);
  await page.waitForTimeout(1800);
  const framed = await page.evaluate((rootId) => {
    const el = document.querySelector(`.wb-object[data-id="${rootId}"]`);
    const bar = document.getElementById("wb-topbar");
    if (!el || !bar) return null;
    const r = el.getBoundingClientRect(), b = bar.getBoundingClientRect();
    const overlap =
      Math.max(0, Math.min(r.bottom, b.bottom) - Math.max(r.top, b.top)) *
      Math.max(0, Math.min(r.right, b.right) - Math.max(r.left, b.left));
    const hit = document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2);
    return {
      root: { t: Math.round(r.top), b: Math.round(r.bottom) },
      barBottom: Math.round(b.bottom),
      overlap: Math.round(overlap),
      inNode: Boolean(hit && hit.closest(`.wb-object[data-id="${rootId}"]`)),
    };
  }, framingBoard.root);
  check("(H2) a map opens with its root clear of the top bar",
    framed && framed.overlap === 0, JSON.stringify(framed));
  check("(H2) and a click at the root's own centre reaches the node",
    framed && framed.inNode, JSON.stringify(framed));

  // --- H1: tidy at scale --------------------------------------------------
  //
  // Every overlap number in this feature's history was measured on a
  // five-node map (MINDMAP_PLAN §10.4 says so). This builds 201 nodes through
  // the API, tidies, and measures: overlaps, the layout's own wall time, and
  // one full render, so "tidy does not overlap" is a claim about a real map.
  const scale = await page.evaluate(async () => {
    const b = await window.apiJson("/whiteboard/boards", {
      method: "POST",
      body: JSON.stringify({ name: "Scale check", type: "map", layout: "tree-right" }),
    });
    const add = (text, parent) => window.apiJson(`/whiteboard/boards/${b.id}/nodes`, {
      method: "POST",
      body: JSON.stringify(parent == null
        ? { kind: "topic", text, x: 0, y: 0 }
        : { kind: "topic", text, parent_id: parent }),
    });
    const root = await add("Scale root", null);
    let made = 1;
    for (let i = 0; i < 10; i++) {
      const branch = await add(`Branch ${i}`, root.id);
      made += 1;
      let first = null;
      for (let j = 0; j < 10; j++) {
        const leaf = await add(`Leaf ${made}`, branch.id);
        if (j === 0) first = leaf.id;
        made += 1;
      }
      for (let j = 0; j < 9; j++) {
        await add(`Deep ${made}`, first);
        made += 1;
      }
    }
    return { board: b.id, made };
  });
  await page.evaluate((id) => window.openWhiteboardBoard(id), scale.board);
  await page.waitForTimeout(2500);
  const tidyRun = await page.evaluate(async () => {
    const t0 = performance.now();
    const moved = await window.wbMapTidy({ quiet: true });
    const total = Math.round(performance.now() - t0);
    const t1 = performance.now();
    window.renderWhiteboardNow();
    return { moved, total, render: Math.round(performance.now() - t1) };
  });
  await page.waitForTimeout(1200);
  const scaleOverlaps = await page.evaluate(() => {
    const boxes = [...document.querySelectorAll(".wb-object.wb-map-node")].map((el) => el.getBoundingClientRect());
    let n = 0;
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
            Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1) n++;
      }
    }
    return { nodes: boxes.length, overlaps: n };
  });
  check("(H1) 200+ nodes: Tidy leaves no two node boxes overlapping",
    scale.made > 200 && scaleOverlaps.nodes > 200 && scaleOverlaps.overlaps === 0,
    `${scale.made} built, ${scaleOverlaps.nodes} drawn, ${scaleOverlaps.overlaps} overlaps, tidy ${tidyRun.total}ms (${tidyRun.moved} moved), one full render ${tidyRun.render}ms`);

  // A drag on that map: the edges of the node under the pointer must still
  // follow it (INBOX 42's fix at scale, where a full render per frame would
  // be the "glitchy and slow" report all over again).
  const scaleDrag = await page.evaluate(() => {
    const kinds = new Set(["topic", "note", "document", "file", "link"]);
    const objs = (wbState.objects || []).filter((o) => kinds.has(o.kind));
    const child = objs.find((o) => o.parent_id != null && (objs.filter((x) => x.parent_id === o.id).length > 0));
    return child ? child.id : null;
  });
  if (scaleDrag) {
    // The pointer phase is timed on its own: `EDGE_PROBE` compares every
    // parent/child pair against every drawn edge, which is 200x200
    // `getPointAtLength` calls on this map and would otherwise be reported
    // as if the app had spent that time.
    const el = await page.$(`.wb-object[data-id="${scaleDrag}"]`);
    const box = await el.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    const movedAt = Date.now();
    await page.mouse.move(box.x + box.width / 2 + 90, box.y + box.height / 2 + 60, { steps: 12 });
    const pointerMs = Date.now() - movedAt;
    const during = await page.evaluate(EDGE_PROBE);
    await page.mouse.up();
    await page.waitForTimeout(900);
    const after = await page.evaluate(EDGE_PROBE);
    check("(H1) and a node's edges still follow a drag on a 200-node map",
      during.worst < 2 && after.worst < 2,
      `during ${during.worst}px, after ${after.worst}px, ${pointerMs}ms for 12 pointer frames`);
  }

  // ==========================================================================
  // Phase 5 — focus, perspectives, metrics, templates (MINDMAP_PLAN.md §5
  // items 18 to 21)
  //
  // Measured on the 200-node map this file has just built, which is the size
  // at which focus is worth having at all: the assertion is how many nodes
  // the canvas actually draws, before and after.
  // ==========================================================================
  const bigRoot = await page.evaluate(() => {
    const index = window.wbMapIndex ? window.wbMapIndex() : null;
    return index && index.roots.length ? index.roots[0].id : null;
  });
  const drawn = () => page.evaluate(() => document.querySelectorAll(".wb-map-node").length);
  const allNodes = await drawn();
  check("(P5) the big map is fully drawn to start with", allNodes > 50, `${allNodes} nodes`);

  await page.evaluate((id) => window.wbMapSetFocus(id, 1), bigRoot);
  await page.waitForTimeout(700);
  const atOne = await drawn();
  const focusBar = await page.evaluate(() => {
    const bar = document.getElementById("wb-map-focus");
    if (!bar || bar.hidden) return null;
    const box = bar.getBoundingClientRect();
    return {
      label: document.getElementById("wb-map-focus-label")?.textContent || "",
      depth: document.getElementById("wb-map-focus-depth")?.textContent || "",
      onScreen: box.width > 0 && box.top >= 0,
    };
  });
  check(
    "(P5) focus at one step draws the node and its neighbours, not the map",
    atOne > 1 && atOne < allNodes / 4,
    `${atOne} of ${allNodes} nodes drawn`
  );
  check(
    "(P5) and the focus bar says what is focused and how far it reaches",
    focusBar && focusBar.onScreen && /step/.test(focusBar.depth) && /of \d+ nodes/.test(focusBar.depth),
    JSON.stringify(focusBar)
  );
  // **Clear of the top bar.** Not a nicety: at `top: var(--space-4)` this bar
  // rendered inside `#wb-topbar`'s box and its own + button could not be
  // clicked at all, which cost this sweep a four-minute timeout rather than a
  // failure. An overlap in pixels is the only honest test of it.
  const focusClear = await page.evaluate(() => {
    const bar = document.getElementById("wb-map-focus").getBoundingClientRect();
    const top = document.getElementById("wb-topbar").getBoundingClientRect();
    const at = document.elementFromPoint(
      Math.round((bar.left + bar.right) / 2),
      Math.round((bar.top + bar.bottom) / 2)
    );
    return {
      overlap: Math.round(Math.max(0, Math.min(bar.bottom, top.bottom) - Math.max(bar.top, top.top))),
      hitsItself: Boolean(at && at.closest("#wb-map-focus")),
    };
  });
  check(
    "(P5) the focus bar is clear of the top bar and is what the pointer lands on",
    focusClear.overlap === 0 && focusClear.hitsItself,
    JSON.stringify(focusClear)
  );

  await page.click("#wb-map-focus-more");
  await page.waitForTimeout(700);
  const atTwo = await drawn();
  check("(P5) one step more reveals more of the map", atTwo > atOne, `${atOne} then ${atTwo}`);

  await page.click("#wb-map-focus-clear");
  await page.waitForTimeout(900);
  const cleared = await drawn();
  const barGone = await page.evaluate(() => document.getElementById("wb-map-focus")?.hidden);
  check(
    "(P5) show all puts every node back and takes the bar away",
    cleared === allNodes && barGone === true,
    `${cleared} of ${allNodes}, bar hidden ${barGone}`
  );

  // --- perspectives ---------------------------------------------------------
  const paintUnder = async (key) => {
    await page.evaluate((k) => window.wbMapSetPerspective(k), key);
    await page.waitForTimeout(800);
    return page.evaluate(() => {
      const nodes = [...document.querySelectorAll(".wb-map-node")].slice(0, 60);
      const colours = nodes.map((n) => n.style.getPropertyValue("--wb-branch").trim());
      const legend = document.getElementById("wb-map-legend");
      return {
        distinct: [...new Set(colours.filter(Boolean))].length,
        legend: legend && !legend.hidden ? legend.querySelectorAll(".wb-map-legend-row").length : 0,
        title: legend && !legend.hidden ? legend.querySelector(".wb-map-legend-title")?.textContent : "",
      };
    });
  };
  const branch = await paintUnder("branch");
  const notes = await paintUnder("notes");
  check(
    "(P5) branch colouring uses several colours and shows no legend",
    branch.distinct >= 2 && branch.legend === 0,
    JSON.stringify(branch)
  );
  check(
    "(P5) 'behind a note' collapses a map of topics to one colour, with a legend",
    notes.distinct === 1 && notes.legend >= 2 && /Behind a note/.test(notes.title || ""),
    JSON.stringify(notes)
  );
  const legendClear = await page.evaluate(() => {
    const legend = document.getElementById("wb-map-legend").getBoundingClientRect();
    const tools = document.querySelector(".whiteboard-floating-panel:not(.hidden)");
    const box = tools ? tools.getBoundingClientRect() : null;
    const at = document.elementFromPoint(
      Math.round((legend.left + legend.right) / 2),
      Math.round((legend.top + legend.bottom) / 2)
    );
    return {
      overlap: box
        ? Math.round(
            Math.max(0, Math.min(legend.right, box.right) - Math.max(legend.left, box.left)) *
              Math.max(0, Math.min(legend.bottom, box.bottom) - Math.max(legend.top, box.top))
          )
        : 0,
      hitsItself: Boolean(at && at.closest("#wb-map-legend")),
      inViewport: legend.top >= 0 && legend.bottom <= window.innerHeight,
    };
  });
  check(
    "(P5) the legend sits clear of the tool row and inside the viewport",
    legendClear.overlap === 0 && legendClear.hitsItself && legendClear.inViewport,
    JSON.stringify(legendClear)
  );

  const byAge = await paintUnder("age");
  check(
    "(P5) age draws its four buckets in the legend",
    byAge.legend >= 4,
    JSON.stringify(byAge)
  );
  await page.evaluate(() => window.wbMapSetPerspective("branch"));
  await page.waitForTimeout(500);

  // --- metrics --------------------------------------------------------------
  await page.evaluate(() => document.getElementById("wb-map-stats-item")?.click());
  await page.waitForTimeout(600);
  const stats = await page.evaluate(() => {
    const list = document.querySelector(".wb-map-stats");
    if (!list) return null;
    const rows = [...list.querySelectorAll("dt")].map((dt) => [
      dt.textContent,
      dt.nextElementSibling?.textContent || "",
    ]);
    return { rows: Object.fromEntries(rows), count: rows.length };
  });
  check(
    "(P5) the stats dialog reports the map it is looking at",
    stats && stats.count >= 6 && new RegExp(`^${allNodes} `).test(stats.rows.Nodes || ""),
    JSON.stringify(stats && stats.rows)
  );
  await page.evaluate(() => {
    const close = [...document.querySelectorAll(".confirm-actions button")].find((b) =>
      /Close/.test(b.textContent)
    );
    close?.click();
  });
  await page.waitForTimeout(400);

  // --- templates ------------------------------------------------------------
  // A brand new map, which is the only state the offer is made in.
  const freshMap = await page.evaluate(() =>
    window
      .apiJson("/whiteboard/boards", {
        method: "POST",
        body: JSON.stringify({ name: "Template map", type: "map", layout: "tree-right" }),
      })
      .then((board) =>
        window
          .apiJson(`/whiteboard/boards/${board.id}/nodes`, {
            method: "POST",
            body: JSON.stringify({ kind: "topic", text: "Template map" }),
          })
          .then(() => board.id)
      )
  );
  await page.evaluate((id) => window.openWhiteboardBoard(id), freshMap);
  await page.waitForTimeout(2500);
  const offered = await page.evaluate(() => {
    const panel = document.getElementById("wb-map-templates");
    if (!panel || panel.hidden) return null;
    const box = panel.getBoundingClientRect();
    return {
      buttons: panel.querySelectorAll("[data-wb-template]").length,
      onScreen: box.width > 0 && box.top >= 0 && box.bottom <= window.innerHeight,
    };
  });
  check(
    "(P5) a map that is still just its root offers a starting shape",
    offered && offered.buttons === 4 && offered.onScreen,
    JSON.stringify(offered)
  );

  await page.click('[data-wb-template="brainstorm"]');
  await page.waitForTimeout(3000);
  const started = await page.evaluate(() => ({
    nodes: document.querySelectorAll(".wb-map-node").length,
    texts: [...document.querySelectorAll(".wb-map-node .wb-map-text")].map((n) => n.textContent.trim()),
    panel: document.getElementById("wb-map-templates")?.hidden,
  }));
  check(
    "(P5) the template fills the map and the offer does not come back",
    started.nodes >= 6 && started.texts.includes("Ideas") && started.panel === true,
    JSON.stringify(started)
  );
  await page.screenshot({ path: `${OUT}/mindmap-phase5-${process.env.THEME || "light"}.png` });

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed.`);
  if (failed.length) console.log("FAILED: " + failed.map((f) => f.label).join(" ; "));
  console.log("shots in " + OUT);
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})();
