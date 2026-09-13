// Where a pan's work happens: in the event, or a frame later.
//
// The owner: "when I pan the whiteboard and mindmap around, it is still laggy
// and the shapes and links and everything feels like it lags behind a bit".
// The previous run A/B'd six conditions and read identical frame times,
// because this sandbox is vsync-bound at ~16.7ms and cannot show what the
// owner sees. This measures the *structural* half instead, which needs no
// timing at all: after `handleWbZoom` runs, is the layer transform the new
// matrix in the same task, and are the per-frame extras still coalesced?
//
// Deliberately not a claim about latency. Chromium dispatches coalesced input
// at the start of a frame and runs requestAnimationFrame later in that same
// frame, so for input on that path the deferred write was already painting in
// the right frame. What is asserted here is only what can be asserted here.
//
//   BASE=http://127.0.0.1:8803 SCRATCH=/tmp/mm-map9 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/panlag.js
const { boot } = require("./lib.js");

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
}

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

(async () => {
  const { browser, page } = await boot();
  await newBoard(page, "Pan map", "map");

  // One task: press, move, read. Nothing here yields, so a rAF cannot have
  // run between the move and the read, which is the whole point.
  const pan = await page.evaluate(() => {
    wbSelectToolRef("pan");
    const c = document.getElementById("whiteboard-container");
    const layers = ["wb-html-layer", "wb-zoom-group", "wb-overlay-zoom-group"]
      .map((id) => document.getElementById(id));
    const r = c.getBoundingClientRect();
    const x = Math.round(r.left + r.width / 2);
    const y = Math.round(r.top + r.height / 2);
    const mouse = (type, cx, cy, buttons) => new MouseEvent(type, {
      bubbles: true, cancelable: true, view: window, button: 0, buttons,
      clientX: cx, clientY: cy,
    });
    c.dispatchEvent(mouse("mousedown", x, y, 1));
    const before = layers.map((el) => el.style.transform);
    const gridBefore = c.style.getPropertyValue("--wb-grid-offset-x");
    // d3-zoom binds the drag half on the view, not on the target.
    window.dispatchEvent(mouse("mousemove", x + 140, y + 90, 1));
    const after = layers.map((el) => el.style.transform);
    const gridAfter = c.style.getPropertyValue("--wb-grid-offset-x");
    window.dispatchEvent(mouse("mouseup", x + 140, y + 90, 0));
    return { before, after, gridBefore, gridAfter };
  });
  check("a pan moves all three layers in the same task as the event",
    pan.after.every((t, i) => t && t !== pan.before[i]),
    JSON.stringify({ before: pan.before[1], after: pan.after[1] }));
  check("and the grid variables are still left to the frame",
    pan.gridAfter === pan.gridBefore,
    JSON.stringify({ gridBefore: pan.gridBefore, gridAfter: pan.gridAfter }));

  // A burst of wheel events in one task: every one moves the layers, none of
  // them writes the grid, which is the optimisation this must not undo.
  const burst = await page.evaluate(() => {
    const c = document.getElementById("whiteboard-container");
    const layer = document.getElementById("wb-zoom-group");
    const r = c.getBoundingClientRect();
    const x = Math.round(r.left + r.width / 2);
    const y = Math.round(r.top + r.height / 2);
    const gridBefore = c.style.getPropertyValue("--wb-grid-size");
    // Alternating direction, so the zoom cannot sit on its own scale clamp
    // and report two identical transforms as a coalescing failure: that is
    // what the first version of this check measured.
    const seen = [];
    for (let i = 0; i < 4; i += 1) {
      c.dispatchEvent(new WheelEvent("wheel", {
        bubbles: true, cancelable: true, view: window,
        clientX: x, clientY: y, deltaY: i % 2 ? 60 : -60, ctrlKey: true,
      }));
      const t = d3.zoomTransform(c);
      seen.push({
        layer: layer.style.transform,
        d3: `translate(${t.x}px, ${t.y}px) scale(${t.k})`,
      });
    }
    return { gridBefore, gridAfter: c.style.getPropertyValue("--wb-grid-size"), seen };
  });
  // Numbers, not strings: CSS serialises a transform to six significant
  // digits, so 423.7109375 comes back as 423.711 and a scale of
  // 0.9999999999999997 as 1. Comparing the text would have been a check that
  // failed on rounding rather than on behaviour.
  const nums = (text) => (String(text).match(/-?\d+(\.\d+)?/g) || []).map(Number);
  const inStep = burst.seen.every((row) => {
    const a = nums(row.layer), b = nums(row.d3);
    return a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < 0.01);
  });
  const moved = new Set(burst.seen.map((row) => row.layer)).size;
  check("every wheel event in one task leaves the layer on d3's own transform",
    inStep && moved > 1, JSON.stringify({ inStep, moved, last: burst.seen[3] }));
  check("and none of them writes the grid: still one per frame",
    burst.gridAfter === burst.gridBefore,
    JSON.stringify({ before: burst.gridBefore, after: burst.gridAfter }));

  // The frame does catch up: after one rAF the grid matches the transform.
  const settled = await page.evaluate(() => new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const c = document.getElementById("whiteboard-container");
      const t = d3.zoomTransform(c);
      resolve({
        grid: c.style.getPropertyValue("--wb-grid-offset-x"),
        x: `${t.x}px`,
      });
    }));
  }));
  check("and the frame after the burst puts the grid back in step",
    settled.grid === settled.x, JSON.stringify(settled));

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
