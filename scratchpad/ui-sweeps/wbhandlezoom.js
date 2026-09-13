// A grip is the same size to the hand at every zoom level.
//
// `agent-remaining/whiteboard-phases.md` item 3: "a sketch's handles scale
// with the zoom; a card's do not". A card's and a text box's handles are
// absolutely positioned HTML at a CSS pixel size, so they are 10px at any
// zoom; a sketch's are SVG rects of 10 *board units* inside `#wb-zoom-group`,
// so at 2x they were 20px on screen and at 0.5x they were 5px, which is a
// target smaller than the pointer that has to hit it. The same held for the
// rotate grip, its stem, and the three circles a link's own handles draw.
//
// This measures the thing the eye cannot: `getBoundingClientRect()` on every
// handle at three zoom levels, against the card handle sitting on the same
// board, which is the app's own definition of the right size.
//
//   BASE=http://127.0.0.1:8932 SCRATCH=/tmp/mm-wb4 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/wbhandlezoom.js
const { boot } = require("./lib.js");

const VIEWPORT = (() => {
  const [w, h] = (process.env.VIEWPORT || "1440x900").split("x").map(Number);
  return { width: w, height: h };
})();

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
}

// Through the real UI: `openWhiteboardBoard` from `page.evaluate` leaves the
// boards landing showing (agent-remaining/mindmap.md).
async function newBoard(page, name) {
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(500);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(700);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  await page.fill(".confirm-overlay input[type=text]", name);
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2500);
  await page.keyboard.press("Escape");
}

// The zoom is set through `wbZoom.transform`, which is the same path the wheel
// and the zoom buttons take, so `handleWbZoom` runs exactly as it does for a
// person. A plain scale keeps both seeded items on screen at 0.5x and at 2x.
const setZoom = async (page, k) => {
  await page.evaluate((scale) => {
    const container = document.getElementById("whiteboard-container");
    d3.select(container).call(wbZoom.transform, d3.zoomIdentity.scale(scale));
  }, k);
  await page.waitForTimeout(250);
};

// Every handle on the board, in screen pixels, with the zoom it was measured
// at. A rect is reported by its own box; a circle by its diameter.
const measure = (page) => page.evaluate(() => {
  const box = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 };
  };
  return {
    k: d3.zoomTransform(document.getElementById("whiteboard-container")).k,
    sketch: box(".wb-sketch-resize-handle"),
    rotate: box(".wb-sketch-rotate-handle"),
    stem: (() => {
      const el = document.querySelector(".wb-rotate-handle-stem");
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 };
    })(),
    card: box(".wb-resize-handle"),
  };
});

const measureLink = (page) => page.evaluate(() => {
  const box = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 };
  };
  return {
    k: d3.zoomTransform(document.getElementById("whiteboard-container")).k,
    bend: box(".wb-link-bend-handle"),
    endpoint: box(".wb-link-endpoint-handle"),
  };
});

// 10px is what a card's handle is (`.wb-resize-handle` in
// 07-whiteboard-misc.css) and what a sketch's is at zoom 1. Half a pixel of
// tolerance, because a rect drawn at a fractional board coordinate lands on a
// fractional device pixel.
const near = (value, want, tol = 0.6) => value != null && Math.abs(value - want) <= tol;

(async () => {
  const { browser, page } = await boot({ viewport: VIEWPORT });
  await newBoard(page, "Handle zoom sweep");

  const made = await page.evaluate(async () => {
    const board = window.currentBoardId;
    const post = async (path, body) => (await api(path, { method: "POST", body: JSON.stringify(body) })).json();
    const sketch = async (data) => post("/whiteboard/sketches", { board_id: board, data: JSON.stringify(data), x: 0, y: 0 });
    const out = {};
    out.shape = (await sketch({ d: "M 60 260 L 260 260 L 260 360 L 60 360 Z", color: "#112233", width: 4, shape: "rect" })).id;
    // A link between two free points, so the endpoint handles exist without
    // needing two cards to resolve against.
    out.link = (await sketch({
      type: "link-straight",
      sourcePoint: { x: 320, y: 260 }, targetPoint: { x: 520, y: 360 },
      color: "#112233", width: 3,
    })).id;
    const entry = await post("/entries", { content: "A note on a board", tags: ["wbhandlezoom"] });
    out.note = (await post("/whiteboard/nodes", { entry_id: entry.id, board_id: board, x: 60, y: 60, z: 1 })).id;
    await fetchWhiteboardState();
    renderWhiteboard();
    return out;
  });
  await page.waitForTimeout(700);

  // The card first, as the reference: its handles are HTML at a CSS size, so
  // whatever they measure is what "right" means on this board.
  await page.evaluate((id) => { wbMultiSelection.clear(); selectWbItem("node", id); }, made.note);
  await page.waitForTimeout(300);
  const cardAt1 = await measure(page);
  await setZoom(page, 2);
  const cardAt2 = await measure(page);
  check("a card's handle is the same size at 1x and at 2x",
    near(cardAt1.card?.w, 10) && near(cardAt2.card?.w, 10),
    `${cardAt1.card?.w}px at 1x, ${cardAt2.card?.w}px at 2x`);

  await setZoom(page, 1);
  await page.evaluate((id) => { wbMultiSelection.clear(); selectWbItem("sketch", id); }, made.shape);
  await page.waitForTimeout(300);
  const shapeAt1 = await measure(page);
  check("a sketch's resize handle is 10px at 1x", near(shapeAt1.sketch?.w, 10),
    `${shapeAt1.sketch?.w}x${shapeAt1.sketch?.h}px`);
  check("a sketch's rotate grip is 12px across at 1x", near(shapeAt1.rotate?.w, 12),
    `${shapeAt1.rotate?.w}px, card grip is 12px`);

  await setZoom(page, 2);
  const shapeAt2 = await measure(page);
  check("a sketch's resize handle is still 10px at 2x", near(shapeAt2.sketch?.w, 10),
    `${shapeAt2.sketch?.w}x${shapeAt2.sketch?.h}px at k=${shapeAt2.k}`);
  check("a sketch's rotate grip is still 12px across at 2x", near(shapeAt2.rotate?.w, 12),
    `${shapeAt2.rotate?.w}px at k=${shapeAt2.k}`);
  check("the rotate stem is the same length at 2x as at 1x",
    near(shapeAt2.stem?.h, shapeAt1.stem?.h, 1.5),
    `${shapeAt1.stem?.h}px at 1x, ${shapeAt2.stem?.h}px at 2x`);

  await setZoom(page, 0.5);
  const shapeAtHalf = await measure(page);
  check("a sketch's resize handle is still 10px at 0.5x", near(shapeAtHalf.sketch?.w, 10),
    `${shapeAtHalf.sketch?.w}x${shapeAtHalf.sketch?.h}px at k=${shapeAtHalf.k}`);
  check("a sketch's rotate grip is still 12px across at 0.5x", near(shapeAtHalf.rotate?.w, 12),
    `${shapeAtHalf.rotate?.w}px at k=${shapeAtHalf.k}`);

  // The link's three circles, which live in the overlay layer and are drawn by
  // a different function, so they are their own measurement.
  await setZoom(page, 1);
  await page.evaluate((id) => { wbMultiSelection.clear(); selectWbItem("sketch", id); }, made.link);
  await page.waitForTimeout(300);
  const linkAt1 = await measureLink(page);
  check("a link's bend grip is 12px across at 1x", near(linkAt1.bend?.w, 12), `${linkAt1.bend?.w}px`);
  check("a link's endpoint grip is 14px across at 1x", near(linkAt1.endpoint?.w, 14), `${linkAt1.endpoint?.w}px`);

  await setZoom(page, 2);
  const linkAt2 = await measureLink(page);
  check("a link's bend grip is still 12px across at 2x", near(linkAt2.bend?.w, 12),
    `${linkAt2.bend?.w}px at k=${linkAt2.k}`);
  check("a link's endpoint grip is still 14px across at 2x", near(linkAt2.endpoint?.w, 14),
    `${linkAt2.endpoint?.w}px at k=${linkAt2.k}`);

  await setZoom(page, 0.5);
  const linkAtHalf = await measureLink(page);
  check("a link's endpoint grip is still 14px across at 0.5x", near(linkAtHalf.endpoint?.w, 14),
    `${linkAtHalf.endpoint?.w}px at k=${linkAtHalf.k}`);

  // And the grip still does its job after the resize: a drag of the east
  // handle at 2x widens the shape by the distance dragged in board units, not
  // by twice or half of it.
  await setZoom(page, 1);
  await page.evaluate((id) => { wbMultiSelection.clear(); selectWbItem("sketch", id); }, made.shape);
  await page.waitForTimeout(400);
  const before = await page.evaluate(() => {
    const r = document.querySelector('.sketch-group .sketch-path').getBoundingClientRect();
    return { w: Math.round(r.width * 10) / 10 };
  });
  const grip = await page.evaluate(() => {
    const el = document.querySelector('.wb-sketch-resize-handle[data-handle="e"]');
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  // Synthetic PointerEvents never reach d3 drag: a real mouse, in steps.
  await page.mouse.move(grip.x, grip.y);
  await page.mouse.down();
  for (let i = 1; i <= 10; i += 1) await page.mouse.move(grip.x + i * 6, grip.y);
  await page.mouse.up();
  await page.waitForTimeout(700);
  const after = await page.evaluate(() => {
    const r = document.querySelector('.sketch-group .sketch-path').getBoundingClientRect();
    return { w: Math.round(r.width * 10) / 10 };
  });
  check("dragging the east grip 60px widens the shape by 60px",
    after.w - before.w > 50 && after.w - before.w < 70,
    `${before.w}px to ${after.w}px`);

  // The same drag at 2x. A grip that is the right size and moves the shape by
  // the wrong amount is no better than one that is the wrong size: d3 resolves
  // a drag's dx through the drag container's own screen CTM, and this
  // container sits inside a CSS-transformed group, so whether the handler
  // should divide by the zoom is a question with one right answer and no way
  // to tell at 1x.
  await setZoom(page, 2);
  await page.waitForTimeout(300);
  const before2 = await page.evaluate(() => {
    const r = document.querySelector('.sketch-group .sketch-path').getBoundingClientRect();
    return { w: Math.round(r.width * 10) / 10 };
  });
  const grip2 = await page.evaluate(() => {
    const el = document.querySelector('.wb-sketch-resize-handle[data-handle="e"]');
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.mouse.move(grip2.x, grip2.y);
  await page.mouse.down();
  for (let i = 1; i <= 10; i += 1) await page.mouse.move(grip2.x + i * 6, grip2.y);
  await page.mouse.up();
  await page.waitForTimeout(700);
  const after2 = await page.evaluate(() => {
    const r = document.querySelector('.sketch-group .sketch-path').getBoundingClientRect();
    return { w: Math.round(r.width * 10) / 10 };
  });
  check("dragging the east grip 60px at 2x widens the shape by 60px on screen",
    after2.w - before2.w > 50 && after2.w - before2.w < 70,
    `${before2.w}px to ${after2.w}px at k=2`);

  // And the move drags, which are the same question asked of the thing itself
  // rather than of its grip: a sketch's drag container is its own SVG parent
  // (board units), a card's is `#wb-html-layer` (screen pixels), and only one
  // of the two should be dividing by the zoom.
  const screenBox = (page, sel) => page.evaluate((s) => {
    const r = document.querySelector(s).getBoundingClientRect();
    return { x: Math.round(r.x * 10) / 10, y: Math.round(r.y * 10) / 10 };
  }, sel);

  const dragBy = async (page, from, dx) => {
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    for (let i = 1; i <= 10; i += 1) await page.mouse.move(from.x + (i * dx) / 10, from.y);
    await page.mouse.up();
    await page.waitForTimeout(700);
  };

  await setZoom(page, 2);
  await page.evaluate(() => { wbMultiSelection.clear(); wbSelectedItem = null; wbClearSketchHandles(); renderWhiteboard(); });
  await page.waitForTimeout(400);
  const shapeBefore = await screenBox(page, ".sketch-group .sketch-path");
  const shapeGrab = await page.evaluate(() => {
    const r = document.querySelector(".sketch-group .sketch-path").getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await dragBy(page, shapeGrab, 60);
  const shapeAfter = await screenBox(page, ".sketch-group .sketch-path");
  check("dragging a shape 60px at 2x moves it 60px on screen",
    Math.abs(shapeAfter.x - shapeBefore.x - 60) < 10,
    `moved ${Math.round((shapeAfter.x - shapeBefore.x) * 10) / 10}px for a 60px drag at k=2`);

  const cardBefore = await screenBox(page, ".node-card");
  const cardGrab = await page.evaluate(() => {
    const r = document.querySelector(".node-card").getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await dragBy(page, cardGrab, 60);
  const cardAfter = await screenBox(page, ".node-card");
  check("dragging a card 60px at 2x moves it 60px on screen",
    Math.abs(cardAfter.x - cardBefore.x - 60) < 10,
    `moved ${Math.round((cardAfter.x - cardBefore.x) * 10) / 10}px for a 60px drag at k=2`);

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) console.log("FAILED: " + failed.map((r) => r.label).join("; "));
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})();
