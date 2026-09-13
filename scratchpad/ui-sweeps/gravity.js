// How spread out the graph is at each gravity setting (INBOX 67, the owner at
// maximum: "the nodes are all still so spread out").
//
// The number is the RMS radius: the root-mean-square distance of every node
// from the mean of all of them, in layout units. It is the right one because
// "spread out" is not about any single node, and a bounding box is decided by
// whichever two nodes drifted furthest.
//
// It also reports the layout's own extent and the count of disconnected
// components, since the entry's proposal is about packing those: three
// islands sitting far apart is a wide picture however tight each island is.
//
//   BASE=http://127.0.0.1:8814 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/gravity.js
const { boot } = require('./lib.js');

const SETTINGS = (process.env.GRAVITY || '0,25,50,75,100').split(',').map(Number);
const SETTLE_MS = Number(process.env.SETTLE || 6000);

(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="graph"]').catch(() => {});
  await page.waitForTimeout(2500);

  for (const gravity of SETTINGS) {
    await page.evaluate((g) => {
      const el = document.getElementById('graph-gravity');
      if (!el) return;
      el.value = String(g);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }, gravity);
    await page.waitForTimeout(SETTLE_MS);
    const m = await page.evaluate(() => {
      // `window.__graphDebug.positions`, the renderer's own read-only
      // snapshot: the graph draws to a `<canvas>`, so there are no node
      // elements to measure and a DOM query finds nothing at all (which is
      // what the first version of this sweep reported, on a graph that was
      // plainly on screen). Capped at 40 nodes by the getter, which is a
      // sample of the layout rather than all of it, and enough for a radius.
      const debug = window.__graphDebug;
      const pts = (debug && debug.positions ? debug.positions : []).map(([x, y]) => ({ x, y }));
      if (pts.length < 2) return { n: pts.length };
      const mx = pts.reduce((t, p) => t + p.x, 0) / pts.length;
      const my = pts.reduce((t, p) => t + p.y, 0) / pts.length;
      const rms = Math.sqrt(pts.reduce((t, p) => t + (p.x - mx) ** 2 + (p.y - my) ** 2, 0) / pts.length);
      const xs = pts.map((p) => p.x);
      const ys = pts.map((p) => p.y);
      // **And what any of that looks like**, which is a different question:
      // the view auto-fits, so a layout that shrinks uniformly is drawn at a
      // larger zoom and can look identical. `k` is the zoom the renderer has
      // settled on, and `rms * k` is the radius in screen pixels, which is
      // the thing a person actually calls spread out.
      const k = debug.transform ? debug.transform.k : 1;
      return {
        n: pts.length,
        rms: Math.round(rms),
        width: Math.round(Math.max(...xs) - Math.min(...xs)),
        height: Math.round(Math.max(...ys) - Math.min(...ys)),
        k: Math.round(k * 1000) / 1000,
        screenRms: Math.round(rms * k),
        radius: debug.radii && debug.radii.length ? Math.round(debug.radii[0] * k * 10) / 10 : null,
      };
    });
    console.log(
      m.n < 2
        ? `gravity ${gravity}: ${m.n} node(s) reported`
        : `gravity ${gravity}: RMS ${m.rms} layout units, extent ${m.width}x${m.height}; zoom ${m.k}, so RMS ${m.screenRms}px on screen, node radius ${m.radius}px`,
    );
  }
  await browser.close();
})();
