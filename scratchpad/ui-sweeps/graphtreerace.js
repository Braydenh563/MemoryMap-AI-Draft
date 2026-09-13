// Does a tick from the force worker land after the tree has been laid out?
// Switch to the tree while the simulation is still hot and read the geometry
// back: a clean tree has every node of one depth at one x, a scattered one
// does not. Reported as "the tree view on the graph is still broken" (INBOX
// 114) and intermittent from both ends, which is why this walks the whole
// cooling curve rather than sampling it once.
const { boot } = require('./lib.js');
// The window is one message hop wide, so a single pass over the curve hits it
// only now and then (1 of 15 against the pre-fix code). Two passes.
const MOMENTS = [];
for (let pass = 0; pass < 2; pass += 1) for (let t = 0; t <= 1400; t += 100) MOMENTS.push(t);
(async () => {
  const { browser, page } = await boot();
  const bad = [];
  for (const wait of MOMENTS) {
    // Back to force, hot, then switch after `wait` ms.
    await page.evaluate(() => switchTab('notes'));
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const i = document.querySelector('input[name="graph-layout"][value="force"]');
      i.checked = true; i.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.evaluate(() => switchTab('graph'));
    await page.waitForTimeout(wait);
    const alphaAt = await page.evaluate(() => window.__graphDebug.alpha);
    await page.evaluate(() => {
      const i = document.querySelector('input[name="graph-layout"][value="tree"]');
      i.checked = true; i.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.waitForTimeout(450);
    const m = await page.evaluate(() => {
      const d = window.__graphDebug;
      const by = new Map();
      for (const n of d.nodeGeometry) {
        if (n.depth == null) continue;
        if (!by.has(n.depth)) by.set(n.depth, []);
        by.get(n.depth).push(n.x);
      }
      const bands = [...by.entries()].sort((a, b) => a[0] - b[0]).map(([dd, v]) => ({
        d: dd, n: v.length, spread: +(Math.max(...v) - Math.min(...v)).toFixed(1),
      }));
      return { layout: d.layout, nodes: d.nodes, alpha: d.alpha, bands };
    });
    const dirty = m.bands.some((b) => b.spread > 0.5);
    if (dirty || m.layout !== 'tree') bad.push(`${wait}ms (alpha ${alphaAt.toFixed(3)}): ${JSON.stringify(m.bands)}`);
    console.log(`switch after ${wait}ms (alpha ${alphaAt.toFixed(3)}): layout=${m.layout} nodes=${m.nodes} bands=${JSON.stringify(m.bands)} ${dirty ? 'SCATTERED' : 'clean'}`);
  }
  await browser.close();
  if (bad.length) {
    console.log(`FAIL\n- the tree was scattered at ${bad.length} of ${MOMENTS.length} switch moments\n- ` + bad.join('\n- '));
    process.exit(1);
  }
  console.log(`PASS ${MOMENTS.length} switch moments, every depth band at one x`);
})();
