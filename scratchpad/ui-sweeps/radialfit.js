// What the node radial actually covers (INBOX 114, "fix the look of the
// mindmap item radial").
//
// The ring is geometrically correct and still wrong to look at: eight slots on
// a circle centred on the node's *centre* land inside the node's own box when
// the node is wider than the ring is round. This measures the overlap rather
// than describing it: how many slots intersect the selected topic's box, how
// far each slot's centre is inside it, and how many slots land on a
// neighbouring topic or on a link line.
//
//   BASE=http://127.0.0.1:8853 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//   node scratchpad/ui-sweeps/radialfit.js
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
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await newBoard(page, "Radial fit", "map");
  // A trunk, three children and a grandchild: enough that a ring around one
  // child has a sibling and a line beside it, which is the second screenshot.
  await page.evaluate(async () => {
    const root = wbMapIndex().roots[0];
    await wbMapAddChild(root.id);
    await wbMapAddChild(root.id);
    await wbMapAddChild(root.id);
    const kid = wbMapIndex().childrenOf.get(root.id)[0];
    await wbMapAddChild(kid.id);
  });
  await page.waitForTimeout(2500);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  const kidId = await page.evaluate(() => {
    const i = wbMapIndex();
    return i.childrenOf.get(i.roots[0].id)[0].id;
  });
  await page.evaluate((id) => selectWbItem("object", id), kidId);
  await page.waitForTimeout(300);
  await page.click(`.wb-object[data-id="${kidId}"]`, { button: "right" });
  await page.waitForTimeout(500);

  const m = await page.evaluate((id) => {
    const el = document.getElementById("wb-map-radial");
    const node = document.querySelector(`.wb-object[data-id="${id}"]`);
    const n = node.getBoundingClientRect();
    const hit = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    const slots = [...el.querySelectorAll(".wb-map-radial-slot")].map((b) => {
      const r = b.getBoundingClientRect();
      return { id: b.id, r, cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
    });
    const others = [...document.querySelectorAll(".wb-object")]
      .filter((o) => o.dataset.id !== String(id))
      .map((o) => o.getBoundingClientRect());
    const lines = [...document.querySelectorAll(".wb-map-edge")].map((l) => l.getBoundingClientRect());
    const centreIn = slots.filter((s) => s.cx > n.left && s.cx < n.right && s.cy > n.top && s.cy < n.bottom);
    const cx = slots.reduce((a, s) => a + s.cx, 0) / slots.length;
    const cy = slots.reduce((a, s) => a + s.cy, 0) / slots.length;
    const radii = slots.map((s) => Math.round(Math.hypot(s.cx - cx, s.cy - cy)));
    // The gap between the node's own box and the nearest slot edge: negative
    // where a slot is over the node. This is the number the report is about.
    const gaps = slots.map((s) => {
      const dx = Math.max(n.left - s.r.right, s.r.left - n.right, 0);
      const dy = Math.max(n.top - s.r.bottom, s.r.top - n.bottom, 0);
      if (hit(s.r, n)) {
        return -Math.round(Math.min(
          Math.min(s.r.right - n.left, n.right - s.r.left),
          Math.min(s.r.bottom - n.top, n.bottom - s.r.top),
        ));
      }
      return Math.round(Math.hypot(dx, dy));
    });
    const strip = document.getElementById("wb-map-strip");
    const sr = strip && !strip.classList.contains("hidden") ? strip.getBoundingClientRect() : null;
    return {
      node: { w: Math.round(n.width), h: Math.round(n.height) },
      stripShown: Boolean(sr),
      overStrip: sr ? slots.filter((s) => hit(s.r, sr)).length : 0,
      overNode: slots.filter((s) => hit(s.r, n)).map((s) => s.id),
      centreInNode: centreIn.map((s) => s.id),
      minGap: Math.min(...gaps),
      gaps,
      overOther: slots.filter((s) => others.some((o) => hit(s.r, o))).length,
      overLine: slots.filter((s) => lines.some((l) => hit(s.r, l))).length,
      radius: Math.min(...radii),
      spread: Math.max(...radii) - Math.min(...radii),
      slotW: Math.round(slots[0].r.width),
    };
  }, kidId);
  console.log(JSON.stringify(m, null, 1));
  check("no slot is drawn over the topic it acts on", m.overNode.length === 0, JSON.stringify(m.overNode));
  check("the ring clears the node's box by at least 8px", m.minGap >= 8, String(m.minGap));
  check("and it is still one circle", m.spread <= 2, JSON.stringify({ spread: m.spread, radius: m.radius }));
  const place = await page.evaluate((id) => {
    const host = document.getElementById("library-view-whiteboard").getBoundingClientRect();
    const strip = document.getElementById("wb-map-strip").getBoundingClientRect();
    const n = document.querySelector(`.wb-object[data-id="${id}"]`).getBoundingClientRect();
    const bar = document.getElementById("wb-topbar").getBoundingClientRect();
    const ring = [...document.querySelectorAll("#wb-map-radial .wb-map-radial-slot")].map((b) => b.getBoundingClientRect());
    return {
      hostTop: Math.round(host.top), barBottom: Math.round(bar.bottom),
      nodeTop: Math.round(n.top), nodeBottom: Math.round(n.bottom),
      stripTop: Math.round(strip.top), stripH: Math.round(strip.height),
      ringTop: Math.round(Math.min(...ring.map((r) => r.top))),
      ringBottom: Math.round(Math.max(...ring.map((r) => r.bottom))),
    };
  }, kidId);
  console.log("placement " + JSON.stringify(place));
  console.log("gaps " + JSON.stringify(await page.evaluate(() => {
    const host = document.getElementById("library-view-whiteboard").getBoundingClientRect();
    const container = document.getElementById("whiteboard-container");
    const t = d3.zoomTransform(container);
    const rect = container.getBoundingClientRect();
    const node = wbMapRadialNode();
    const box = wbItemBBox("object", node);
    const top = rect.top - host.top + t.applyY(box.minY);
    const bottom = rect.top - host.top + t.applyY(box.maxY);
    const strip = document.getElementById("wb-map-strip");
    return { top, bottom, over: wbMapRadialOverhang(host, top, bottom),
      h: strip.offsetHeight, w: strip.offsetWidth,
      floor: document.getElementById("wb-topbar").getBoundingClientRect().bottom - host.top + 10 };
  })));
  console.log("re-place " + JSON.stringify(await page.evaluate(() => {
    const before = Math.round(document.getElementById("wb-map-strip").getBoundingClientRect().top);
    wbUpdateSelectionBar();
    return { before, after: Math.round(document.getElementById("wb-map-strip").getBoundingClientRect().top),
      radialFor: wbMapRadialFor, selected: JSON.stringify(wbSelectedItem) };
  })));
  console.log(`neighbours touched: ${m.overOther}, links touched: ${m.overLine}, strip touched: ${m.overStrip}`);
  await page.screenshot({ path: process.env.SHOT || "/tmp/radialfit.png" });

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
