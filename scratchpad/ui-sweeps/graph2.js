// GRAPH_PLAN.md Phase 2 ("the space"), measured rather than looked at.
//
//   scratchpad/ui-sweeps/serve.sh 8831 /tmp/mm-graph2
//   BASE=http://127.0.0.1:8831 node scratchpad/graph-fixture.js 35 60
//   BASE=http://127.0.0.1:8831 node scratchpad/ui-sweeps/graph2.js
//   BASE=http://127.0.0.1:8831 THEME=dark node scratchpad/ui-sweeps/graph2.js
//
// Four questions, each of which the phase states as a number:
//
//  1. **How much of the card is map?** The phase's target is >= 95%. Measured
//     as `#graph-box`'s height over `#graph-card`'s, plus the same for area,
//     because a floating dock takes width from nothing.
//  2. **Does the page scroll on Graph?** `scrollHeight` vs `clientHeight` on
//     the scrolling element, on arrival and with the options popover open.
//  3. **How far does the layout spread?** The world bounding box of every
//     node once the simulation has settled, the zoom `fitGraphToView` picks
//     to frame it, and how many nodes are inside the frame at zoom 1. A map
//     that only fits at k = 0.3 is a map whose default view is dots.
//     `gcNodes` is a top-level `let` in a classic script, so it is in the
//     global lexical environment and readable here without a debug hook.
//  4. **Does a pan change what is hovered?** A drag across the map and a
//     wheel zoom over a node, with `__graphDebug.hovered` sampled after each.
//  5. **Are the display options one click, and are they a popover?** Where
//     the gear sits in the dock, whether the panel it opens is anchored under
//     it, whether every row is one control height with its label to the left,
//     and the three ways it closes.
//  6. **Is full screen full screen?** The card against the viewport, the
//     radius it keeps, and whether the app chrome is still laid out behind it.
//
// Nothing here is a screenshot. Every line is a number off the live DOM.
const { boot } = require("./lib.js");

const round = (n) => Math.round(n * 10) / 10;

// Every probe states its expectation as a `check`, not as a printed line
// somebody has to read and compare against a plan. A sweep whose output is
// only prose is a sweep whose regression nobody notices: the pan/hover bug
// (INBOX 28) was reported by the owner twice, and this file printed the
// number that would have caught it both times. Failures collect here and the
// run exits non-zero with a FAIL block, so "did it pass" is answerable
// without reading the whole log.
const failures = [];
const check = (ok, what) => {
  if (!ok) failures.push(what);
  return ok;
};

(async () => {
  const { browser, page } = await boot();
  await page.evaluate(() => {
    try {
      localStorage.setItem("graph-renderer", "canvas");
      localStorage.setItem("graph-layout", "force");
      localStorage.setItem("graph-colour", "category");
      localStorage.setItem("graph-options-open", "0");
      localStorage.setItem("graphLegendCollapsed", "0");
    } catch (e) {
      /* private mode; defaults match */
    }
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await page.click("#tab-btn-graph");
  // The layout is framed twice (graph-canvas.js): once on the first tick and
  // again when it settles. Wait for the settle, not for a screenshot.
  await page.waitForTimeout(9000);

  const geometry = await page.evaluate(() => {
    const rect = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height, visible: r.width > 0 && r.height > 0 };
    };
    const scroller = document.scrollingElement || document.documentElement;
    return {
      viewport: { w: innerWidth, h: innerHeight },
      tab: rect("#tab-graph"),
      card: rect("#graph-card"),
      box: rect("#graph-box"),
      canvas: rect("#graph-canvas"),
      dock: rect('.dock[data-dock-name="graph"]'),
      legend: rect(".graph-legend-row"),
      stats: rect("#graph-stats"),
      zoom: rect("#graph-zoom"),
      minimap: rect("#graph-minimap"),
      pageScroll: { scrollH: scroller.scrollHeight, clientH: scroller.clientHeight },
      cardRadius: getComputedStyle(document.getElementById("graph-card")).borderTopLeftRadius,
      dockBg: getComputedStyle(document.querySelector('.dock[data-dock-name="graph"]')).backgroundColor,
      statsInDock: !!document.querySelector('.dock[data-dock-name="graph"] #graph-stats'),
    };
  });

  const share = geometry.box && geometry.card ? geometry.box.h / geometry.card.h : 0;
  const areaShare =
    geometry.box && geometry.card
      ? (geometry.box.w * geometry.box.h) / (geometry.card.w * geometry.card.h)
      : 0;
  console.log("== the space ==");
  console.log(
    `card ${round(geometry.card.w)}x${round(geometry.card.h)} in a ` +
      `${geometry.viewport.w}x${geometry.viewport.h} viewport; map box ` +
      `${round(geometry.box.w)}x${round(geometry.box.h)}`
  );
  console.log(
    `map gets ${round(share * 100)}% of the card's height, ${round(areaShare * 100)}% of its area ` +
      `(target >= 95%)`
  );
  console.log(
    `page scroll: scrollHeight ${geometry.pageScroll.scrollH} vs clientHeight ` +
      `${geometry.pageScroll.clientH} (equal = no scroll)`
  );
  console.log(
    `dock ${round(geometry.dock.w)}x${round(geometry.dock.h)} at y=${round(geometry.dock.y)}, ` +
      `bg ${geometry.dockBg}; card radius ${geometry.cardRadius}; ` +
      `stats chip in the dock: ${geometry.statsInDock}`
  );
  if (geometry.legend) {
    console.log(`legend ${round(geometry.legend.w)}x${round(geometry.legend.h)} at y=${round(geometry.legend.y)}`);
  }

  const spread = await page.evaluate(() => {
    const nodes = typeof gcNodes !== "undefined" ? gcNodes : [];
    const t = window.__graphDebug ? window.__graphDebug.transform : { k: 1, x: 0, y: 0 };
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of nodes) {
      if (!Number.isFinite(n.x)) continue;
      minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
    }
    const box = document.getElementById("graph-box").getBoundingClientRect();
    // How many nodes would be on screen at zoom 1 centred on the map's middle:
    // "does a 300-note graph fit the viewport at the default zoom".
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    let insideAt1 = 0;
    for (const n of nodes) {
      if (Math.abs(n.x - cx) <= box.width / 2 && Math.abs(n.y - cy) <= box.height / 2) insideAt1 += 1;
    }
    // Nearest-neighbour distance, the "clusters readable" half: a map that
    // fits because everything is in one blob is not the target either.
    const sample = nodes.slice(0, 200);
    const gaps = sample.map((a) => {
      let best = Infinity;
      for (const b of nodes) {
        if (b === a || !Number.isFinite(b.x)) continue;
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d < best) best = d;
      }
      return best;
    }).filter(Number.isFinite).sort((a, b) => a - b);
    return {
      count: nodes.length,
      spanX: maxX - minX,
      spanY: maxY - minY,
      k: t.k,
      insideAt1,
      medianGap: gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0,
      alpha: window.__graphDebug ? window.__graphDebug.alpha : null,
      ticks: window.__graphDebug ? window.__graphDebug.ticks : null,
    };
  });
  console.log("== the spread ==");
  console.log(
    `${spread.count} nodes, world bounding box ${Math.round(spread.spanX)} x ` +
      `${Math.round(spread.spanY)} px, fit zoom k=${round(spread.k)}, ` +
      `${spread.insideAt1}/${spread.count} nodes inside the box at zoom 1, ` +
      `median nearest-neighbour gap ${Math.round(spread.medianGap)} px ` +
      `(alpha ${round(spread.alpha)}, ${spread.ticks} ticks)`
  );

  // The spread, stated as the three numbers the plan states it in: a map that
  // is framed at a readable zoom, mostly on screen at 1:1, and still made of
  // separable notes rather than one packed disc. The gap floor is the collide
  // diameter (`COLLIDE_PAD` in graph-worker.js, twice a small node's radius
  // plus six): below it the layout has stopped being a layout.
  check(spread.k >= 0.5, `the map only frames at zoom ${round(spread.k)}`);
  check(
    spread.insideAt1 / Math.max(spread.count, 1) >= 0.85,
    `${spread.count - spread.insideAt1} of ${spread.count} notes are off screen at zoom 1`
  );
  check(
    spread.medianGap >= 24,
    `median nearest-neighbour gap is ${Math.round(spread.medianGap)}px: the map fits because it is one blob`
  );

  // 4. A pan must not change hover, and neither must a wheel zoom.
  const hoverProbe = await page.evaluate(() => {
    const nodes = (typeof gcNodes !== "undefined" ? gcNodes : []).filter((n) => Number.isFinite(n.x));
    const t = window.__graphDebug.transform;
    const box = document.getElementById("graph-canvas").getBoundingClientRect();
    // A node in screen coordinates, to aim the gestures at.
    const target = nodes[Math.floor(nodes.length / 2)];
    const screen = (n) => [box.x + n.x * t.k + t.x, box.y + n.y * t.k + t.y];
    const [tx, ty] = screen(target);
    // Where a pan may start: on the map, clear of every floating panel (the
    // dock, the legend, the zoom strip and the minimap all swallow a press
    // now), and with no node under it, or the press is a node drag instead.
    // The column itself spans the whole card and is `pointer-events: none`,
    // so it is its *children* that swallow a press: taking the column's own
    // rect here would leave the sweep with nowhere on the map to start a pan.
    const panels = [
      ...document.querySelectorAll(".graph-overlay > *"),
      ...[".graph-legend-row", "#graph-zoom", "#graph-minimap"].map((sel) =>
        document.querySelector(sel)
      ),
    ]
      .filter((el) => el && !el.classList.contains("hidden"))
      .map((el) => el.getBoundingClientRect())
      .filter((r) => r.width > 0 && r.height > 0);
    const free = (x, y) =>
      !panels.some((r) => x >= r.x - 4 && x <= r.right + 4 && y >= r.y - 4 && y <= r.bottom + 4) &&
      !nodes.some((n) => {
        const [nx, ny] = screen(n);
        return Math.hypot(nx - x, ny - y) < 30;
      });
    let start = null;
    for (let dx = 40; dx < box.width - 40 && !start; dx += 20) {
      for (let dy = 40; dy < box.height - 40 && !start; dy += 20) {
        const x = box.x + dx;
        const y = box.y + dy;
        // Far enough from the target that the drag actually crosses the map.
        if (Math.hypot(x - tx, y - ty) < 200) continue;
        if (free(x, y)) start = { x, y };
      }
    }
    return {
      x: tx, y: ty, id: target.id, start,
      boxX: box.x, boxY: box.y, boxW: box.width, boxH: box.height,
    };
  });
  if (!hoverProbe.start) throw new Error("no free spot on the map to start a pan from");
  // A drag that crosses a node: press on empty map, then move across the
  // target node. A pan must never change what is hovered.
  await page.mouse.move(hoverProbe.start.x, hoverProbe.start.y);
  await page.waitForTimeout(300);
  await page.mouse.down();
  const during = [];
  for (let i = 1; i <= 8; i++) {
    const x = hoverProbe.start.x + ((hoverProbe.x - hoverProbe.start.x) * i) / 8;
    const y = hoverProbe.start.y + ((hoverProbe.y - hoverProbe.start.y) * i) / 8;
    await page.mouse.move(x, y);
    await page.waitForTimeout(60);
    during.push(await page.evaluate(() => window.__graphDebug.hovered));
  }
  await page.mouse.up();
  await page.waitForTimeout(300);
  const afterPan = await page.evaluate(() => window.__graphDebug.hovered);
  const hoveredDuringPan = during.filter((h) => h != null).length;
  const activeDuringPan = await page.evaluate(
    () => document.activeElement && document.activeElement.id
  );
  console.log("== hover during a pan ==");
  console.log(
    `drag across the map: ${hoveredDuringPan}/8 samples had a hovered node ` +
      `(want 0); after mouseup hovered=${afterPan}, activeElement=${activeDuringPan}`
  );
  check(hoveredDuringPan === 0, `a pan lit up a node in ${hoveredDuringPan}/8 samples`);
  check(afterPan == null, `hover survived the mouseup of a pan: ${afterPan}`);

  // The other half of the same bug, and the half that actually fired:
  // `#graph-box` is `tabIndex = 0`, so a press on the map focuses it, and its
  // focus listener used to hand the keyboard (and, through `focusGraphNode`,
  // the hover) to `graphNodesRef[0]`: an arbitrary note, dimmed-except and
  // labelled, that nobody pointed at. A press on a node is the gesture that
  // reproduces it, because d3-zoom's own `preventDefault` on an accepted pan
  // suppresses the focus and a press on a node is not an accepted pan.
  await page.mouse.move(hoverProbe.x, hoverProbe.y);
  await page.mouse.down();
  await page.mouse.move(hoverProbe.x - 60, hoverProbe.y + 20);
  await page.mouse.up();
  await page.waitForTimeout(500);
  const afterPress = await page.evaluate(() => ({
    active: document.activeElement && document.activeElement.id,
    hovered: window.__graphDebug.hovered,
    keyboardId: typeof graphKeyboardId !== "undefined" ? graphKeyboardId : null,
    first: (typeof gcNodes !== "undefined" && gcNodes[0] && gcNodes[0].id) || null,
  }));
  console.log(
    `press and drag on a node: activeElement=${afterPress.active}, ` +
      `hovered=${afterPress.hovered}, keyboard=${afterPress.keyboardId} ` +
      `(want neither equal to the first node in the payload, ${afterPress.first}, ` +
      `unless that is the node pressed: ${hoverProbe.id})`
  );
  // The bug itself: `#graph-box` takes focus from the press, and the focus
  // listener used to hand the keyboard and the hover to `graphNodesRef[0]`.
  // Focus on the box is fine and expected; a node chosen by that focus is not.
  const arbitrary = (id) => id != null && id === afterPress.first && id !== hoverProbe.id;
  check(!arbitrary(afterPress.hovered), `a press focused the box and hovered node ${afterPress.hovered}`);
  check(
    !arbitrary(afterPress.keyboardId),
    `a press focused the box and selected node ${afterPress.keyboardId}`
  );

  // A wheel zoom with the pointer parked over empty space: the map slides
  // under a stationary cursor, and Chromium replays a move at the same client
  // point. Nothing moved under the user's hand, so nothing should light up.
  await page.mouse.move(hoverProbe.boxX + 30, hoverProbe.boxY + 30);
  await page.waitForTimeout(400);
  const beforeWheel = await page.evaluate(() => window.__graphDebug.hovered);
  for (let i = 0; i < 6; i++) {
    await page.mouse.wheel(0, -120);
    await page.waitForTimeout(120);
  }
  await page.waitForTimeout(700);
  const afterWheel = await page.evaluate(() => window.__graphDebug.hovered);
  console.log(
    `wheel zoom under a stationary cursor: hovered ${beforeWheel} -> ${afterWheel} ` +
      `(want unchanged)`
  );
  check(
    beforeWheel === afterWheel,
    `a wheel zoom changed the hover: ${beforeWheel} -> ${afterWheel}`
  );

  // The labels (INBOX 27, "labels pile up at fit zoom"). The collision pass
  // landed in 1cd59c2 without its probe; this is the probe. A canvas cannot
  // be asked what it looks like, so the draw hands out the boxes it placed
  // (`__graphDebug.labelBoxes`, world coordinates, with a priority rank) and
  // the overlap test happens here.
  const overlaps = (boxes) => {
    const hits = [];
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        if (a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top) {
          hits.push([a.id, b.id, a.rank, b.rank]);
        }
      }
    }
    return hits;
  };
  const labels = await page.evaluate(() => {
    const d = window.__graphDebug;
    return {
      wanted: d.labelsWanted,
      drawn: d.labelsDrawn,
      priority: d.labelsPriority,
      boxes: d.labelBoxes,
      labelsOn: document.getElementById("graph-labels").checked,
      zoom: d.transform.k,
    };
  });
  const ordinaryClashes = overlaps(labels.boxes.filter((b) => b.rank === 2));
  console.log("== labels ==");
  console.log(
    `labels on ${labels.labelsOn} at zoom ${round(labels.zoom)}: ${labels.drawn} drawn of ` +
      `${labels.wanted} wanted (${labels.priority} asked for by name); ` +
      `${ordinaryClashes.length} overlapping pairs among the rest`
  );
  check(labels.boxes.length > 0, "no labels were drawn at all with the Labels switch on");
  check(
    ordinaryClashes.length === 0,
    `labels stack: ${JSON.stringify(ordinaryClashes.slice(0, 4))}`
  );
  check(
    labels.drawn <= labels.wanted,
    `more labels drawn (${labels.drawn}) than the frame wanted (${labels.wanted})`
  );

  // A hovered note always shows its own label, clash or no clash: a label you
  // asked for and cannot see is a bug, not tidiness.
  const hoverTarget = await page.evaluate(() => {
    const nodes = (typeof gcNodes !== "undefined" ? gcNodes : []).filter((n) => Number.isFinite(n.x));
    const t = window.__graphDebug.transform;
    const box = document.getElementById("graph-canvas").getBoundingClientRect();
    // A node the pointer can actually reach: on the canvas, and clear of every
    // floating panel, since those swallow the move before the map sees it.
    // The map has been panned and zoomed by the probes above, so where a node
    // is on screen is not where the payload put it.
    const panels = [
      ...document.querySelectorAll(".graph-overlay > *"),
      ...[".graph-legend-row", "#graph-zoom", "#graph-minimap"].map((sel) =>
        document.querySelector(sel)
      ),
    ]
      .filter((el) => el && !el.classList.contains("hidden"))
      .map((el) => el.getBoundingClientRect())
      .filter((r) => r.width > 0 && r.height > 0);
    const reachable = nodes
      .map((n) => ({ n, x: box.x + n.x * t.k + t.x, y: box.y + n.y * t.k + t.y }))
      .filter(
        (p) =>
          p.x > box.x + 30 &&
          p.x < box.right - 30 &&
          p.y > box.y + 30 &&
          p.y < box.bottom - 30 &&
          !panels.some((r) => p.x >= r.x - 6 && p.x <= r.right + 6 && p.y >= r.y - 6 && p.y <= r.bottom + 6)
      )
      // The best connected of them: the one the dense middle of a map is most
      // likely to have covered.
      .sort((a, b) => (b.n.r || 0) - (a.n.r || 0));
    if (!reachable.length) return null;
    const best = reachable[0];
    return { id: best.n.id, x: best.x, y: best.y };
  });
  if (!hoverTarget) throw new Error("no node on the map the pointer can reach");
  await page.mouse.move(hoverTarget.x - 40, hoverTarget.y - 40);
  await page.waitForTimeout(150);
  await page.mouse.move(hoverTarget.x, hoverTarget.y);
  await page.waitForTimeout(700);
  const hovered = await page.evaluate(() => {
    const d = window.__graphDebug;
    return { hovered: d.hovered, boxes: d.labelBoxes, priority: d.labelsPriority };
  });
  const hoveredDrawn = hovered.boxes.some((b) => b.id === hovered.hovered && b.rank === 0);
  console.log(
    `hovering note ${hovered.hovered}: its label is drawn ${hoveredDrawn}, ` +
      `${hovered.priority} priority labels in the frame`
  );
  check(hovered.hovered != null, "the hover probe did not land on a node");
  check(hoveredDrawn, "the hovered note's own label was dropped by the collision pass");

  // A search hit is the second thing that is never dropped, and the trade
  // that sits behind it: a handful of hits keep their labels through any
  // clash, a search that matches most of the notebook is a filter and its
  // labels go back through the same collision test as everything else.
  const readLabels = async () =>
    page.evaluate(() => {
      const d = window.__graphDebug;
      return { boxes: d.labelBoxes, priority: d.labelsPriority, drawn: d.labelsDrawn, wanted: d.labelsWanted };
    });
  await page.mouse.move(hoverProbe.boxX + 20, hoverProbe.boxY + 20);
  await page.fill("#graph-search", "note");
  await page.waitForTimeout(1400);
  const broad = await readLabels();
  const broadMatches = broad.boxes.filter((b) => b.rank === 1);
  const broadClashes = overlaps(broad.boxes.filter((b) => b.rank >= 1));
  console.log(
    `searching "note" (matches most of the notebook): ${broadMatches.length} matched labels ` +
      `drawn of ${broad.wanted} wanted, ${broadClashes.length} overlapping pairs`
  );
  check(broadMatches.length > 0, "a search highlighted notes and drew none of their labels");
  check(
    broadClashes.length === 0,
    `a broad search piles the labels up again: ${JSON.stringify(broadClashes.slice(0, 4))}`
  );

  // The other half: one hit, drawn wherever it lands.
  await page.fill("#graph-search", "note 12:");
  await page.waitForTimeout(1400);
  const narrow = await readLabels();
  const narrowMatches = narrow.boxes.filter((b) => b.rank === 1);
  console.log(
    `searching "note 12:" (one note): ${narrowMatches.length} matched labels drawn, ` +
      `${narrow.drawn} labels in the frame`
  );
  check(narrowMatches.length >= 1, "a search for one note drew no label for it");
  check(
    narrow.priority === narrowMatches.length + narrow.boxes.filter((b) => b.rank === 0).length,
    "the priority count and the boxes disagree, so one of the two is stale"
  );
  await page.fill("#graph-search", "");
  await page.waitForTimeout(900);

  // 5. The display options are one click from the dock, and they open as a
  //    popover under their gear rather than as a strip across the column
  //    (INBOX 21 and 41). Where the button sits is checked in the markup, not
  //    by eye: in the actions zone, icon-only, and not in the View menu.
  const gear = await page.evaluate(() => {
    const button = document.getElementById("graph-options-toggle");
    if (!button) return { missing: true };
    const zone = button.closest(".dock-actions, .dock-arrange, .dock-find, .dock-identity");
    return {
      zone: zone ? zone.className : null,
      inViewMenu: !!button.closest("#graph-view-menu"),
      iconOnly: button.classList.contains("icon-only"),
      icon: (button.querySelector("i") || {}).className || null,
      label: button.getAttribute("aria-label"),
      // The utilities run, in the order it is painted, so the kebab staying
      // last is a measurement and not a claim about the markup.
      actions: Array.from(document.querySelectorAll(".dock[data-dock-name='graph'] .dock-actions > *"))
        .map((el) => el.id || el.className),
    };
  });
  console.log("== display options ==");
  console.log(
    `gear in ${gear.zone}, icon ${gear.icon}, icon-only ${gear.iconOnly}, ` +
      `in the View menu: ${gear.inViewMenu}; actions run: ${JSON.stringify(gear.actions)}`
  );
  check(!gear.missing, "the display options button is gone");
  check(gear.zone === "dock-actions", `the gear is in ${gear.zone}, not the utilities zone`);
  check(!gear.inViewMenu, "the gear is still inside the View menu");
  check(gear.iconOnly, "the gear is not icon-only, so it counts against the dock's one primary");

  await page.click("#graph-options-toggle");
  await page.waitForTimeout(400);
  const panel = await page.evaluate(() => {
    const el = document.getElementById("graph-options");
    const button = document.getElementById("graph-options-toggle");
    const dock = document.querySelector(".dock[data-dock-name='graph']");
    const r = el.getBoundingClientRect();
    const d = dock.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      open: !el.classList.contains("hidden"),
      expanded: button.getAttribute("aria-expanded"),
      w: r.width, h: r.height, x: r.x, y: r.y, right: r.right,
      dockRight: d.right, dockBottom: d.bottom,
      radius: cs.borderTopLeftRadius,
      background: cs.backgroundColor,
      overflowY: cs.overflowY,
      sections: document.querySelectorAll("#graph-options .dock-menu-section").length,
    };
  });
  console.log(
    `panel ${round(panel.w)}x${round(panel.h)} at (${round(panel.x)}, ${round(panel.y)}), ` +
      `right edge ${round(panel.right)} against the dock's ${round(panel.dockRight)}, ` +
      `top ${round(panel.y)} under the dock's bottom ${round(panel.dockBottom)}, ` +
      `radius ${panel.radius}, ground ${panel.background}, ${panel.sections} sections`
  );
  check(panel.open && panel.expanded === "true", "one click on the gear did not open the panel");
  check(
    Math.abs(panel.right - panel.dockRight) <= 2,
    `the panel is not anchored under the gear: right edge ${round(panel.right)} vs the dock's ${round(panel.dockRight)}`
  );
  check(panel.y >= panel.dockBottom - 1, "the panel overlaps the dock it hangs from");
  check(panel.w <= 384, `the panel is ${round(panel.w)}px wide, wider than a menu`);

  // The panel's own shape (INBOX 41). One row per setting, one control height
  // down the panel, the words on the left and the control on the right, and
  // named sections. Every line of this is a rect, not a look.
  const rows = await page.evaluate(() => {
    const panel = document.getElementById("graph-options");
    const sections = Array.from(panel.querySelectorAll(".dock-menu-section")).map((el) => {
      const label = el.querySelector(".dock-menu-label");
      return { name: label ? label.textContent.trim() : "(unnamed)", rows: el.querySelectorAll(".graph-option-row").length };
    });
    const measured = Array.from(panel.querySelectorAll(".graph-option-row")).map((row) => {
      const r = row.getBoundingClientRect();
      const text = row.querySelector("label, span");
      const control = row.querySelector("input, select, button");
      const t = text ? text.getBoundingClientRect() : null;
      const c = control ? control.getBoundingClientRect() : null;
      return {
        name: text ? text.textContent.trim() : "(none)",
        h: Math.round(r.height * 10) / 10,
        labelLeft: t && c ? t.left < c.left : null,
        labelX: t ? Math.round(t.left) : null,
        controlRight: c ? Math.round(c.right) : null,
        panelRight: Math.round(panel.getBoundingClientRect().right),
        fontSize: text ? getComputedStyle(text).fontSize : null,
      };
    });
    return {
      sections,
      rows: measured,
      scrolls: panel.scrollHeight > panel.clientHeight + 1,
      scrollH: panel.scrollHeight,
      clientH: panel.clientHeight,
    };
  });
  const heights = [...new Set(rows.rows.map((r) => r.h))];
  const fonts = [...new Set(rows.rows.map((r) => r.fontSize))];
  console.log(
    `sections: ${rows.sections.map((s) => `${s.name} (${s.rows})`).join(", ")}`
  );
  console.log(
    `${rows.rows.length} rows, heights ${JSON.stringify(heights)}, label sizes ` +
      `${JSON.stringify(fonts)}, panel scrolls: ${rows.scrolls} ` +
      `(${rows.scrollH} vs ${rows.clientH})`
  );
  check(rows.sections.length >= 5, `only ${rows.sections.length} sections in the panel`);
  check(
    rows.sections.every((s) => s.name !== "(unnamed)"),
    "a section in the display options has no heading"
  );
  check(heights.length === 1, `rows come at ${heights.length} heights: ${JSON.stringify(heights)}`);
  check(fonts.length === 1, `row labels come at ${fonts.length} sizes: ${JSON.stringify(fonts)}`);
  check(
    rows.rows.every((r) => r.labelLeft === true),
    "a row draws its control to the left of its label"
  );
  check(
    rows.rows.every((r) => r.controlRight <= r.panelRight),
    "a control runs past the panel's right edge"
  );
  // Scrolling inside is allowed and printed; running past the card, or over
  // the zoom strip, is not. A settings list of five sections is taller than
  // the room between the dock and the zoom buttons at this size, and the
  // honest answer to that is a scroll with the cut-off row in sight.
  const covered = await page.evaluate(() => {
    const panel = document.getElementById("graph-options").getBoundingClientRect();
    const hit = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return null;
      const overlapX = Math.min(panel.right, r.right) - Math.max(panel.left, r.left);
      const overlapY = Math.min(panel.bottom, r.bottom) - Math.max(panel.top, r.top);
      return { sel, overlap: Math.round(Math.max(0, overlapX) * Math.max(0, overlapY)), top: Math.round(r.top), bottom: Math.round(r.bottom) };
    };
    return {
      panelBottom: Math.round(panel.bottom),
      zoom: hit("#graph-zoom"),
      minimap: hit("#graph-minimap"),
      legend: hit(".graph-legend-row"),
    };
  });
  console.log(
    `panel bottom ${covered.panelBottom}; overlap with the zoom strip ` +
      `${covered.zoom ? covered.zoom.overlap : "n/a"} px2 (strip at ` +
      `${covered.zoom ? covered.zoom.top : "n/a"}), with the minimap ` +
      `${covered.minimap ? covered.minimap.overlap : "n/a"} px2`
  );
  check(!covered.zoom || covered.zoom.overlap === 0, "the panel covers the zoom strip");
  check(!covered.minimap || covered.minimap.overlap === 0, "the panel covers the minimap");
  check(
    covered.panelBottom <= Math.round(geometry.card.y + geometry.card.h),
    "the panel runs past the bottom of the card"
  );

  // **Every control in the rebuilt panel still drives the map.** The markup
  // was restructured (a strip of groups became sections of rows), and the one
  // way a rebuild like that fails silently is a control that still looks
  // right and no longer reaches its handler. Each of these asserts on what
  // the map is drawing, not on the tickbox.
  const drives = { };
  await page.click("#graph-labels");
  await page.waitForTimeout(400);
  drives.labelsOff = await page.evaluate(() =>
    document.getElementById("graph-box").classList.contains("graph-labels-hidden")
  );
  await page.click("#graph-labels");
  await page.waitForTimeout(400);
  drives.labelsBack = await page.evaluate(
    () => !document.getElementById("graph-box").classList.contains("graph-labels-hidden")
  );
  const nodesBefore = await page.evaluate(() => window.__graphDebug.nodes);
  await page.click("#graph-hide-orphans");
  await page.waitForTimeout(2500);
  const nodesAfter = await page.evaluate(() => window.__graphDebug.nodes);
  drives.hideUnlinked = nodesAfter <= nodesBefore;
  await page.click("#graph-hide-orphans");
  await page.waitForTimeout(2500);
  await page.selectOption("#graph-minimap-corner", "br");
  await page.waitForTimeout(400);
  drives.minimapCorner = await page.evaluate(() =>
    document.getElementById("graph-minimap").classList.contains("graph-minimap-br")
  );
  await page.selectOption("#graph-minimap-corner", "tl");
  await page.waitForTimeout(300);
  // Gravity and Spread have nothing to act on under a tree layout, so the
  // whole Physics section dims. `#graph-physics` moved from a span inside the
  // strip to the section itself, and this is what says the id still lands on
  // the thing setGraphPhysicsEnabled() means to dim.
  await page.evaluate(() => {
    const tree = document.querySelector('input[name="graph-layout"][value="tree"]');
    tree.checked = true;
    tree.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(2500);
  drives.physicsDimmed = await page.evaluate(() => {
    const el = document.getElementById("graph-physics");
    return el.classList.contains("is-disabled") && Number(getComputedStyle(el).opacity) < 1;
  });
  await page.evaluate(() => {
    const force = document.querySelector('input[name="graph-layout"][value="force"]');
    force.checked = true;
    force.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(3000);
  console.log(
    `controls still drive the map: labels off ${drives.labelsOff}, labels back ` +
      `${drives.labelsBack}, hide unlinked ${nodesBefore} -> ${nodesAfter}, ` +
      `minimap corner ${drives.minimapCorner}, physics dimmed under tree ` +
      `${drives.physicsDimmed}`
  );
  check(drives.labelsOff && drives.labelsBack, "the Labels switch no longer reaches the map");
  check(drives.hideUnlinked, "Hide unlinked did not change what is drawn");
  check(drives.minimapCorner, "the minimap position select no longer moves the minimap");
  check(drives.physicsDimmed, "the Physics section is not dimmed under a tree layout");

  // The three ways a popover closes. Escape must not also leave full screen:
  // one key press, one thing.
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  const afterEscape = await page.evaluate(() => ({
    open: !document.getElementById("graph-options").classList.contains("hidden"),
    full: document.getElementById("graph-card").classList.contains("graph-fullscreen"),
  }));
  check(!afterEscape.open, "Escape did not close the display options");
  check(!afterEscape.full, "Escape closed the panel and entered full screen with the same press");
  await page.click("#graph-options-toggle");
  await page.waitForTimeout(300);
  await page.mouse.click(hoverProbe.boxX + 60, hoverProbe.boxY + hoverProbe.boxH / 2);
  await page.waitForTimeout(300);
  const afterOutside = await page.evaluate(
    () => !document.getElementById("graph-options").classList.contains("hidden")
  );
  console.log(
    `closes: Escape ${!afterEscape.open}, click outside ${!afterOutside} ` +
      `(and Escape left full screen alone: ${!afterEscape.full})`
  );
  check(!afterOutside, "a click on the map did not close the display options");

  // 5. Fullscreen keeps the card's radius and hides the app chrome.
  await page.click("#graph-fullscreen");
  await page.waitForTimeout(1200);
  const measureFull = () =>
    page.evaluate(() => {
      const card = document.getElementById("graph-card");
      const r = card.getBoundingClientRect();
      const box = document.getElementById("graph-box").getBoundingClientRect();
      const canvas = document.getElementById("graph-canvas").getBoundingClientRect();
      const cs = getComputedStyle(card);
      const chrome = ["#top-bar", "#tab-bar", "#status-bar", "#sidebar"]
        .map((sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const rect = el.getBoundingClientRect();
          return {
            sel,
            visible: rect.height > 0 && getComputedStyle(el).visibility !== "hidden",
            h: Math.round(rect.height),
          };
        })
        .filter(Boolean);
      return {
        card: { w: r.width, h: r.height, x: r.x, y: r.y },
        box: { w: box.width, h: box.height },
        canvas: { w: canvas.width, h: canvas.height },
        viewport: { w: innerWidth, h: innerHeight },
        radius: cs.borderTopLeftRadius,
        overflow: cs.overflowY,
        gutter: parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--space-3")) || 0,
        chrome,
      };
    });
  const full = await measureFull();
  console.log("== fullscreen ==");
  console.log(
    `card ${round(full.card.w)}x${round(full.card.h)} at (${round(full.card.x)}, ${round(full.card.y)}), ` +
      `radius ${full.radius}, map ${round(full.box.w)}x${round(full.box.h)} ` +
      `(${round((full.box.h / full.card.h) * 100)}% of the card)`
  );
  console.log(`app chrome still laid out: ${JSON.stringify(full.chrome)}`);
  // INBOX 29, the three parts of it: the chrome is gone, the canvas is the
  // viewport minus its gutters, and the card keeps its corner.
  check(
    full.chrome.every((c) => !c.visible),
    `app chrome still on screen in full screen: ${JSON.stringify(full.chrome.filter((c) => c.visible))}`
  );
  // The card's own left offset is the gutter, so this needs no token maths:
  // "the canvas is the viewport minus its gutters" in the terms the sweep can
  // actually see.
  const wantW = full.viewport.w - full.card.x * 2;
  const wantH = full.viewport.h - full.card.y * 2;
  check(
    Math.abs(full.canvas.w - wantW) <= 6 && Math.abs(full.canvas.h - wantH) <= 6,
    `the canvas is ${round(full.canvas.w)}x${round(full.canvas.h)} in full screen, not the ` +
      `viewport minus its gutters (${wantW}x${wantH})`
  );
  check(full.radius === geometry.cardRadius, `full screen changed the card's corner to ${full.radius}`);
  await page.click("#graph-fullscreen");
  await page.waitForTimeout(900);
  const restored = await measureFull();
  console.log(
    `after exit: card ${round(restored.card.w)}x${round(restored.card.h)}, canvas ` +
      `${round(restored.canvas.w)}x${round(restored.canvas.h)}, chrome back: ` +
      `${JSON.stringify(restored.chrome.map((c) => `${c.sel}:${c.h}`))}`
  );
  check(
    Math.abs(restored.card.w - geometry.card.w) <= 2 && Math.abs(restored.card.h - geometry.card.h) <= 2,
    `the card did not come back to its tab size: ${round(restored.card.w)}x${round(restored.card.h)} ` +
      `against ${round(geometry.card.w)}x${round(geometry.card.h)}`
  );
  check(
    Math.abs(restored.canvas.w - geometry.box.w) <= 4 && Math.abs(restored.canvas.h - geometry.box.h) <= 4,
    `the canvas did not come back to the card: ${round(restored.canvas.w)}x${round(restored.canvas.h)}`
  );
  check(
    restored.chrome.filter((c) => c.sel !== "#sidebar").every((c) => c.visible),
    "the app chrome did not come back after full screen"
  );

  // The other two ways out, both of which now have to put the chrome back:
  // Escape, and leaving the tab (the tab bar is hidden in full screen, but
  // the command palette and the keyboard shortcuts are not, so this is
  // reachable and used to strand somebody on a tab with no tab bar).
  await page.click("#graph-fullscreen");
  await page.waitForTimeout(700);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(700);
  const afterEsc = await page.evaluate(() => ({
    full: document.getElementById("graph-card").classList.contains("graph-fullscreen"),
    body: document.body.classList.contains("graph-fullscreen-on"),
    topBar: document.getElementById("top-bar").getBoundingClientRect().height,
  }));
  await page.click("#graph-fullscreen");
  await page.waitForTimeout(700);
  await page.evaluate(() => document.getElementById("tab-btn-notes").click());
  await page.waitForTimeout(900);
  const afterLeave = await page.evaluate(() => ({
    full: document.getElementById("graph-card").classList.contains("graph-fullscreen"),
    body: document.body.classList.contains("graph-fullscreen-on"),
    topBar: document.getElementById("top-bar").getBoundingClientRect().height,
  }));
  console.log(
    `Escape leaves full screen: ${!afterEsc.full} (top bar ${afterEsc.topBar}px); ` +
      `leaving the tab leaves it: ${!afterLeave.full} (top bar ${afterLeave.topBar}px)`
  );
  check(!afterEsc.full && !afterEsc.body && afterEsc.topBar > 0, "Escape did not leave full screen");
  check(
    !afterLeave.full && !afterLeave.body && afterLeave.topBar > 0,
    "leaving the tab left the app in full screen with no chrome"
  );

  await browser.close();
  if (failures.length) {
    console.log(`== FAIL (${failures.length}) ==`);
    for (const line of failures) console.log(`  - ${line}`);
    process.exitCode = 1;
  } else {
    console.log("== every probe passed ==");
  }
})();
