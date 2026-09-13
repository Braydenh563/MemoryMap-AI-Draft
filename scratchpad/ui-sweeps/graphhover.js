// The graph's nodes, hovered.
//
// Asked for: "can you make graph nodes temporarily expand to fill their glow
// bubble when I hover over them or smth??". The graph paints to a <canvas>
// (graph-canvas.js), not to SVG, so there is no element to read a computed
// style off: the only honest measurement is the pixels. This scans a
// horizontal line through a node's centre and counts the run of pixels that
// carry the node's own fully opaque core colour, at rest and hovered.
//
//   BASE=http://127.0.0.1:8931 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node graphhover.js
//
// Expected: the run grows from 2*r*k to 2*(r+6)*k, which is exactly the core
// reaching its own halo (the halo is drawn at r+6).
const { boot } = require("./lib.js");

(async () => {
  const { page, browser } = await boot({});
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });

  // A graph needs a graph. A fresh data dir has no linked notes at all, so the
  // sweep seeds a small connected set through the app's own `api()` rather
  // than depending on whatever happens to be in the scratch notebook.
  console.log(await page.evaluate(async () => {
    const titles = ["Alpha hub", "Beta note", "Gamma note", "Delta note", "Epsilon note"];
    let made = 0;
    for (const title of titles) {
      const body = title === "Alpha hub"
        ? titles.slice(1).map((t) => `[[${t}]]`).join(" ")
        : "[[Alpha hub]]";
      try {
        await api("/entries", {
          method: "POST",
          body: JSON.stringify({ title, content: `${title}. ${body}`, tags: ["sweep"] }),
        });
        made += 1;
      } catch (e) { return "seed failed: " + e.message; }
    }
    return `seeded ${made}`;
  }));

  await page.click('[data-tab="graph"]').catch(() => {});
  await page.waitForTimeout(4000);

  // The nodes, in screen coordinates, straight out of the renderer's own
  // state: `gcNodes` and `gcTransform` are top-level bindings of a classic
  // script, so they are reachable by name from an evaluate.
  const picked = await page.evaluate(() => {
    if (typeof gcNodes === "undefined" || !gcNodes?.length) return null;
    const t = gcTransform || d3.zoomIdentity;
    const rect = document.getElementById("graph-canvas").getBoundingClientRect();
    return gcNodes
      .filter((n) => Number.isFinite(n.x))
      .map((n) => ({
        id: n.id,
        r: n.r,
        k: t.k,
        sx: rect.left + t.x + n.x * t.k,
        sy: rect.top + t.y + n.y * t.k,
        colour: n.colour,
      }))
      .filter((n) => n.sx > rect.left + 40 && n.sx < rect.right - 40
        && n.sy > rect.top + 40 && n.sy < rect.bottom - 40);
  });
  if (!picked?.length) { console.log("FAIL: no nodes on screen"); await browser.close(); process.exit(1); }

  // The width of the opaque core along the node's centre line, in device
  // pixels of the backing store, converted back to CSS pixels.
  const runAt = (node) => page.evaluate((n) => {
    const canvas = document.getElementById("graph-canvas");
    const rect = canvas.getBoundingClientRect();
    const dpr = canvas.width / rect.width;
    const y = Math.round((n.sy - rect.top) * dpr);
    const halfSpan = Math.round(60 * n.k * dpr);
    const x0 = Math.max(0, Math.round((n.sx - rect.left) * dpr) - halfSpan);
    const width = Math.min(canvas.width - x0, halfSpan * 2);
    const data = canvas.getContext("2d").getImageData(x0, y, width, 1).data;
    // The core is filled at globalAlpha 1 over the halo, so its pixels are the
    // strongest run on the line. Anchor on the centre pixel's colour and walk
    // outwards while the colour stays within a small tolerance of it.
    const c = Math.round((n.sx - rect.left) * dpr) - x0;
    const at = (i) => [data[i * 4], data[i * 4 + 1], data[i * 4 + 2]];
    const centre = at(c);
    const near = (p) => Math.abs(p[0] - centre[0]) + Math.abs(p[1] - centre[1]) + Math.abs(p[2] - centre[2]) < 24;
    let lo = c;
    let hi = c;
    while (lo > 0 && near(at(lo - 1))) lo -= 1;
    while (hi < width - 1 && near(at(hi + 1))) hi += 1;
    return { px: (hi - lo + 1) / dpr, centre };
  }, node);

  let bad = 0;
  // Three nodes, so a leaf and a hub are both covered whatever the notebook is.
  const picks = [picked[0], picked[Math.floor(picked.length / 2)], picked[picked.length - 1]];
  for (const node of picks) {
    await page.mouse.move(5, 5);
    await page.waitForTimeout(350);
    const rest = await runAt(node);
    await page.mouse.move(node.sx, node.sy);
    await page.waitForTimeout(400);
    const hot = await runAt(node);
    const wantRest = 2 * node.r * node.k;
    const wantHot = 2 * (node.r + 6) * node.k;
    // **The growth is what is asserted, not the two diameters.** Each of those
    // reads about 3px narrow, and for a reason that is not a fault: the ring
    // (`lineWidth = 2 / k`, so 2 CSS px however far the map is zoomed) is
    // stroked centred on the core's edge, painting over the outer pixel on
    // each side, and antialiasing a 5px disc takes a further fraction. Both
    // erosions are the same at rest and hovered, so they cancel in the
    // difference, which is the number the report is actually about: the core
    // has to travel exactly the 6 world units out to its own halo, or
    // `2 * 6 * k` on screen.
    const grew = hot.px - rest.px;
    const wantGrowth = 12 * node.k;
    const ok = Math.abs(grew - wantGrowth) <= 2.5;
    if (!ok) bad += 1;
    console.log(
      `node ${String(node.id).slice(0, 10)}`.padEnd(18),
      `r=${node.r.toFixed(1)} k=${node.k.toFixed(2)}`,
      `rest ${rest.px.toFixed(1)}px (halo-free ${wantRest.toFixed(1)})`,
      `hover ${hot.px.toFixed(1)}px (${wantHot.toFixed(1)})`,
      `grew ${grew.toFixed(1)}px, want ${wantGrowth.toFixed(1)}`,
      ok ? "ok" : "BAD",
    );
  }
  console.log(`console errors: ${errs.length}${errs.length ? " " + errs.join(" | ") : ""}`);
  await browser.close();
  if (bad || errs.length) { console.log(`FAIL: ${bad} of ${picks.length} nodes wrong`); process.exit(1); }
  console.log(`PASS: ${picks.length} nodes each grow from their core to their own halo`);
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
