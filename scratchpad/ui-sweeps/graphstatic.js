// A computed layout is read-only for position: no held ring, no drag, and a
// double click leaves every node exactly where the layout put it.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="graph"]').catch(()=>{});
  await page.waitForTimeout(2500);
  const out = {};
  for (const layout of ['force', 'tree', 'radial', 'arc']) {
    await page.evaluate((l) => { localStorage.setItem('graph-layout', l); localStorage.setItem('activeTab', 'graph'); }, layout);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    const before = await page.evaluate(() => {
      const c = document.querySelector('#graph-canvas, canvas.graph-canvas, #graph-card canvas');
      return c ? { w: c.width, h: c.height } : null;
    });
    if (!before) { out[layout] = 'no canvas'; continue; }
    await page.click('[data-tab="graph"]').catch(()=>{});
    await page.waitForTimeout(2500);
    // Double click the middle of the canvas, twice, then compare the drawn
    // pixels: a layout that re-solves changes far more than a click ever
    // should.
    const box = await page.evaluate(() => {
      const c = document.querySelector('#graph-canvas, canvas.graph-canvas, #graph-card canvas');
      const r = c.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    });
    if (!box || !box.width || !box.height) { out[layout] = { box }; continue; }
    const pct = (a, b) => {
      const n = Math.min(a.length, b.length); let d = 0, s = 0;
      for (let i = 0; i < n; i += 37) { s++; if (a[i] !== b[i]) d++; }
      return { sampled: s, differing: d, pct: +(100 * d / s).toFixed(1),
               sizeDelta: Math.abs(a.length - b.length) };
    };
    const a = await page.screenshot({ clip: box });
    await page.waitForTimeout(2500);
    const b = await page.screenshot({ clip: box });        // control: no input
    await page.mouse.dblclick(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(2500);
    const c = await page.screenshot({ clip: box });        // after a double click
    out[layout] = { idle: pct(a, b), afterDblClick: pct(b, c) };
  }
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
