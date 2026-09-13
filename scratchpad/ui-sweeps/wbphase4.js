// WHITEBOARD_PLAN Phase 4: root placement, edges that follow drags, and Tidy
// measured with thirty nodes.
//
// Three things this file does that a screenshot cannot:
//
//   * it reads the root's own box against `#wb-topbar`'s box on a freshly
//     opened map, and asks the document what is actually under the root's
//     centre (decision 9's first half, and mindmap.md item H);
//   * it drives real drags with `page.mouse` (synthetic PointerEvents never
//     reach d3's drag behaviour, mindmap.md) and measures every drawn edge's
//     two endpoints against its two nodes' boxes *mid-drag*, with the button
//     still down, which is the only moment the per-frame follow can be
//     caught failing;
//   * it lays out thirty nodes in each of the three tree layouts and counts
//     overlapping pairs of rendered boxes.
//
//   BASE=http://127.0.0.1:8932 SCRATCH=/tmp/mm-wb4 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/wbphase4.js
const { boot } = require("./lib.js");

const VIEWPORT = (() => {
  const raw = process.env.VIEWPORT;
  if (!raw) return { width: 1440, height: 900 };
  const [w, h] = raw.split("x").map(Number);
  return { width: w || 1440, height: h || 900 };
})();

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
}

// Clicks through the real UI, `openWhiteboardBoard(id)` from page.evaluate
// leaves the boards landing showing (mindmap.md).
async function newBoard(page, name, type) {
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(500);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(700);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  await page.fill(".confirm-overlay input[type=text]", name);
  if (type === "map") await page.click('.confirm-overlay .seg button[data-value="map"]');
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2500);
  await page.keyboard.press("Escape");
}

// Every drawn edge's two ends, against the two boxes they are meant to touch.
// `getPointAtLength` reads the path the browser actually has, so this cannot
// be fooled by a `d` attribute that was written and then overwritten.
const EDGE_PROBE = () => {
  const objs = new Map((wbState.objects || []).map((o) => [o.id, o]));
  const sizeOf = (o) => {
    const el = document.querySelector(`.wb-object[data-id="${o.id}"]`);
    return el && el.offsetHeight
      ? { w: el.offsetWidth, h: el.offsetHeight }
      : { w: o.width || 200, h: o.height || 56 };
  };
  // Distance from a point to a rectangle: 0 inside or on the edge.
  const gap = (o, p) => {
    const s = sizeOf(o);
    const dx = Math.max(o.x - p.x, 0, p.x - (o.x + s.w));
    const dy = Math.max(o.y - p.y, 0, p.y - (o.y + s.h));
    return Math.hypot(dx, dy);
  };
  const out = [];
  for (const el of document.querySelectorAll(".wb-map-edges .wb-map-edge")) {
    const parent = objs.get(Number(el.dataset.parent));
    const child = objs.get(Number(el.dataset.child));
    if (!parent || !child) continue;
    const len = el.getTotalLength();
    const a = el.getPointAtLength(0);
    const b = el.getPointAtLength(len);
    const twin = document.querySelector(
      `.wb-map-edges .wb-map-edge-hit[data-parent="${parent.id}"][data-child="${child.id}"]`
    );
    out.push({
      parent: parent.id,
      child: child.id,
      parentGap: gap(parent, a),
      childGap: gap(child, b),
      twinMatches: !twin || twin.getAttribute("d") === el.getAttribute("d"),
    });
  }
  return out;
};

// The worst endpoint gap over every drawn edge, and how many twins drifted.
function worstEdge(rows) {
  let worst = 0;
  let twinsOff = 0;
  for (const r of rows) {
    worst = Math.max(worst, r.parentGap, r.childGap);
    if (!r.twinMatches) twinsOff += 1;
  }
  return { worst: Math.round(worst * 10) / 10, twinsOff, count: rows.length };
}

// Where a node is on screen right now, so a drag can start on it.
async function nodeCentre(page, id) {
  return page.evaluate((nodeId) => {
    const el = document.querySelector(`.wb-object[data-id="${nodeId}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height };
  }, id);
}

(async () => {
  const { browser, page } = await boot({ viewport: VIEWPORT });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  // --- A. Root placement on open -------------------------------------------
  await newBoard(page, "Phase 4 map", "map");
  const placement = await page.evaluate(() => {
    const root = wbMapIndex().roots[0];
    const el = document.querySelector(`.wb-object[data-id="${root.id}"]`);
    const bar = document.getElementById("wb-topbar");
    const r = el.getBoundingClientRect();
    const b = bar.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const hit = document.elementFromPoint(cx, cy);
    return {
      root: { left: Math.round(r.left), top: Math.round(r.top), right: Math.round(r.right), bottom: Math.round(r.bottom) },
      bar: { left: Math.round(b.left), top: Math.round(b.top), right: Math.round(b.right), bottom: Math.round(b.bottom) },
      overlaps: r.left < b.right && r.right > b.left && r.top < b.bottom && r.bottom > b.top,
      hitsNode: Boolean(hit && hit.closest(`.wb-object[data-id="${root.id}"]`)),
      hit: hit ? (hit.id || hit.className.toString().slice(0, 40)) : "none",
      inCanvas: (() => {
        const c = document.getElementById("whiteboard-container").getBoundingClientRect();
        return r.left >= c.left && r.right <= c.right && r.top >= c.top && r.bottom <= c.bottom;
      })(),
    };
  });
  check("a new map's root does not sit under the top bar", !placement.overlaps,
    `root ${placement.root.top}-${placement.root.bottom}, bar ${placement.bar.top}-${placement.bar.bottom}`);
  check("the root's own centre hits the root", placement.hitsNode, `elementFromPoint -> ${placement.hit}`);
  check("the root is inside the canvas", placement.inCanvas, JSON.stringify(placement.root));

  // --- B. Thirty nodes, seeded through the map's own create path -----------
  // A four-level tree: root, 4 branches, 3 children each, 2 leaves under the
  // first child of each branch. 1 + 4 + 12 + 8 = 25 topics, plus five more
  // leaves to take it past thirty.
  const built = await page.evaluate(async () => {
    const root = wbMapIndex().roots[0];
    const made = [];
    for (let b = 0; b < 4; b += 1) {
      const branch = await wbMapCreateNode({ parentId: root.id, text: `Branch ${b + 1}` });
      made.push(branch.id);
      for (let c = 0; c < 3; c += 1) {
        const child = await wbMapCreateNode({ parentId: branch.id, text: `Child ${b + 1}.${c + 1}` });
        made.push(child.id);
        if (c === 0) {
          for (let l = 0; l < 2; l += 1) {
            const leaf = await wbMapCreateNode({ parentId: child.id, text: `Leaf ${b + 1}.${c + 1}.${l + 1}` });
            made.push(leaf.id);
          }
        }
      }
    }
    for (let e = 0; e < 5; e += 1) {
      const extra = await wbMapCreateNode({ parentId: root.id, text: `Extra ${e + 1}` });
      made.push(extra.id);
    }
    await wbRefreshMapState();
    renderWhiteboardNow();
    return { total: wbMapIndex().nodes.length, made: made.length };
  });
  await page.waitForTimeout(1200);
  check("thirty nodes seeded", built.total >= 30, `${built.total} nodes`);

  // --- C. Tidy, measured, in each tree layout ------------------------------
  const overlapReport = async (layout) => {
    await page.evaluate(async (l) => {
      await wbMapSetLayout(l);
      await wbMapTidy({ quiet: true });
      renderWhiteboardNow();
    }, layout);
    await page.waitForTimeout(1500);
    return page.evaluate(() => {
      const index = wbMapIndex();
      const boxes = [];
      for (const o of index.nodes) {
        const el = document.querySelector(`.wb-object[data-id="${o.id}"]`);
        if (!el) continue;
        boxes.push({ id: o.id, x: o.x, y: o.y, w: el.offsetWidth, h: el.offsetHeight });
      }
      let overlaps = 0;
      let worstArea = 0;
      let example = null;
      for (let i = 0; i < boxes.length; i += 1) {
        for (let j = i + 1; j < boxes.length; j += 1) {
          const a = boxes[i];
          const b = boxes[j];
          const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
          const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
          if (ox > 0 && oy > 0) {
            overlaps += 1;
            if (ox * oy > worstArea) { worstArea = ox * oy; example = [a.id, b.id, Math.round(ox), Math.round(oy)]; }
          }
        }
      }
      // The smallest gap between any two boxes that share a column (same
      // depth band), which is what WB_MAP_GAP_BREADTH is meant to buy.
      let minGap = Infinity;
      for (let i = 0; i < boxes.length; i += 1) {
        for (let j = i + 1; j < boxes.length; j += 1) {
          const a = boxes[i];
          const b = boxes[j];
          const dx = Math.max(a.x - (b.x + b.w), b.x - (a.x + a.w), 0);
          const dy = Math.max(a.y - (b.y + b.h), b.y - (a.y + a.h), 0);
          minGap = Math.min(minGap, Math.hypot(dx, dy));
        }
      }
      return { boxes: boxes.length, overlaps, example, minGap: Math.round(minGap * 10) / 10 };
    });
  };

  for (const layout of ["tree-right", "tree-down", "radial"]) {
    const r = await overlapReport(layout);
    check(`tidy with thirty nodes leaves no overlaps: ${layout}`, r.overlaps === 0,
      `${r.boxes} boxes, ${r.overlaps} overlapping pairs${r.example ? ` worst ${JSON.stringify(r.example)}` : ""}, min gap ${r.minGap}`);
  }
  const backToRight = await overlapReport("tree-right");
  check("the tidied map's own gap is the one the constant asks for",
    backToRight.minGap >= 20, `min gap ${backToRight.minGap} board units`);

  // --- D. Edges follow a drag ----------------------------------------------
  const ids = await page.evaluate(() => {
    const index = wbMapIndex();
    const root = index.roots[0];
    const branch = (index.childrenOf.get(root.id) || [])[0];
    const child = (index.childrenOf.get(branch.id) || [])[0];
    const leaf = (index.childrenOf.get(child.id) || [])[0];
    return { root: root.id, branch: branch.id, child: child.id, leaf: leaf.id };
  });

  // Frame the map so the nodes we drag are on screen at a workable scale.
  await page.evaluate(() => wbZoomToFit({ animate: false }));
  await page.waitForTimeout(600);

  const restBefore = worstEdge(await page.evaluate(EDGE_PROBE));
  check("at rest, every edge ends on both of its nodes", restBefore.worst <= 1.5,
    `${restBefore.count} edges, worst endpoint gap ${restBefore.worst}px`);

  // A leaf dragged alone: nothing under it, one edge into it.
  const dragAndProbe = async (id, dx, dy, opts = {}) => {
    const c = await nodeCentre(page, id);
    if (!c) return null;
    await page.mouse.move(c.x, c.y);
    if (opts.ctrl) await page.keyboard.down("Control");
    await page.mouse.down();
    // Three moves: d3-drag needs a first frame to decide the gesture, and the
    // per-frame follow is what this is here to catch.
    await page.mouse.move(c.x + dx / 3, c.y + dy / 3, { steps: 4 });
    await page.mouse.move(c.x + (dx * 2) / 3, c.y + (dy * 2) / 3, { steps: 4 });
    await page.mouse.move(c.x + dx, c.y + dy, { steps: 4 });
    await page.waitForTimeout(120);
    const mid = worstEdge(await page.evaluate(EDGE_PROBE));
    await page.mouse.up();
    if (opts.ctrl) await page.keyboard.up("Control");
    await page.waitForTimeout(900);
    const after = worstEdge(await page.evaluate(EDGE_PROBE));
    return { mid, after };
  };

  const leafDrag = await dragAndProbe(ids.leaf, 140, -90, { ctrl: true });
  check("a dragged leaf's edge endpoint follows it, mid-drag",
    leafDrag && leafDrag.mid.worst <= 1.5,
    leafDrag ? `worst ${leafDrag.mid.worst}px over ${leafDrag.mid.count} edges` : "no node");
  check("the invisible hit twin follows the visible line",
    leafDrag && leafDrag.mid.twinsOff === 0,
    leafDrag ? `${leafDrag.mid.twinsOff} twins adrift` : "no node");
  check("after the drop, every edge is still on its nodes",
    leafDrag && leafDrag.after.worst <= 1.5,
    leafDrag ? `worst ${leafDrag.after.worst}px` : "no node");

  // A branch dragged whole: the node's own edge, its children's, and the
  // edges further down the branch that only `wbApplyBulkMove` touches.
  const branchDrag = await dragAndProbe(ids.child, -120, 160);
  check("a dragged branch keeps every edge inside it, mid-drag",
    branchDrag && branchDrag.mid.worst <= 1.5,
    branchDrag ? `worst ${branchDrag.mid.worst}px over ${branchDrag.mid.count} edges` : "no node");
  check("after a branch drop, every edge is still on its nodes",
    branchDrag && branchDrag.after.worst <= 1.5,
    branchDrag ? `worst ${branchDrag.after.worst}px` : "no node");

  // A marquee-selected pair dragged together: the case the plan's decision 9
  // names ("the marquee fix must not have detached them").
  const marquee = await page.evaluate((nodeIds) => {
    wbMultiSelection.clear();
    wbMultiSelection.add(wbMultiKey("object", nodeIds.child));
    wbMultiSelection.add(wbMultiKey("object", nodeIds.leaf));
    wbApplySelectionHighlight();
    return wbMultiSelection.size;
  }, ids);
  const marqueeDrag = marquee === 2 ? await dragAndProbe(ids.child, 90, 110) : null;
  check("a marquee drag of two nodes keeps their edges, mid-drag",
    marqueeDrag && marqueeDrag.mid.worst <= 1.5,
    marqueeDrag ? `worst ${marqueeDrag.mid.worst}px over ${marqueeDrag.mid.count} edges` : `selection ${marquee}`);
  await page.evaluate(() => { wbMultiSelection.clear(); wbApplySelectionHighlight(); });

  // --- E. Root placement when a big map is re-opened -----------------------
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(900);
  // By name, not by position: the gallery's first card is the default board,
  // which is not a map at all, and clicking it opened an empty whiteboard.
  await page.click('.library-board-card:has-text("Phase 4 map")');
  await page.waitForSelector(".wb-object", { timeout: 20000 });
  // The frame-on-open runs after the tree endpoint answers, so the number
  // this section is here to read is not final at the first painted node.
  await page.waitForTimeout(3000);
  const reopened = await page.evaluate(() => {
    const root = wbMapIndex().roots[0];
    const el = document.querySelector(`.wb-object[data-id="${root.id}"]`);
    const bar = document.getElementById("wb-topbar").getBoundingClientRect();
    const container = document.getElementById("whiteboard-container");
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const hit = document.elementFromPoint(cx, cy);
    return {
      scale: Math.round(d3.zoomTransform(container).k * 1000) / 1000,
      overlaps: r.left < bar.right && r.right > bar.left && r.top < bar.bottom && r.bottom > bar.top,
      hitsNode: Boolean(hit && hit.closest(`.wb-object[data-id="${root.id}"]`)),
      hit: hit ? (hit.id || hit.className.toString().slice(0, 40)) : "none",
      onScreen: (() => {
        const c = container.getBoundingClientRect();
        return r.right > c.left && r.left < c.right && r.bottom > c.top && r.top < c.bottom;
      })(),
    };
  });
  check("a thirty-node map re-opens with its root clear of the top bar", !reopened.overlaps,
    `scale ${reopened.scale}`);
  check("the re-opened root is on the canvas and clickable", reopened.onScreen && reopened.hitsNode,
    `elementFromPoint -> ${reopened.hit}`);
  check("the open frame is legible, not a thumbnail", reopened.scale >= 0.45,
    `scale ${reopened.scale}`);

  check("no console errors over the whole run", errors.length === 0, errors.slice(0, 3).join(" | "));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) console.log("FAILED: " + failed.map((r) => r.label).join("; "));
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})();
