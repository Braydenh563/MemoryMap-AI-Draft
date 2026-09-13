// Cold load with a computed layout stored: was the box measured when the tree
// was laid out and framed, or was it the 800x540 fallback?
const { boot } = require('./lib.js');
(async () => {
  for (const layout of ['tree', 'radial']) {
    const { browser, page, ctx } = await boot();
    await ctx.addInitScript((l) => { try { localStorage.setItem('graph-layout', l); } catch (e) {} }, layout);
    await page.evaluate((l) => localStorage.setItem('graph-layout', l), layout);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
    const first = await page.evaluate(() => {
      const box = document.getElementById('graph-box');
      return { boxW: box ? box.clientWidth : -1, boxH: box ? box.clientHeight : -1 };
    });
    await page.evaluate(() => switchTab('graph'));
    await page.waitForTimeout(1800);
    const m = await page.evaluate(() => {
      const box = document.getElementById('graph-box');
      const c = document.getElementById('graph-canvas');
      const d = window.__graphDebug;
      return {
        boxW: box.clientWidth, boxH: box.clientHeight,
        canvasStyle: c.style.width + 'x' + c.style.height,
        layout: d.layout, k: +d.transform.k.toFixed(3),
        span: (() => {
          const xs = d.nodeGeometry.map((n) => n.x), ys = d.nodeGeometry.map((n) => n.y);
          return [Math.round(Math.max(...xs) - Math.min(...xs)), Math.round(Math.max(...ys) - Math.min(...ys))];
        })(),
      };
    });
    console.log(`${layout}: before tab box=${first.boxW}x${first.boxH}; after box=${m.boxW}x${m.boxH} canvas=${m.canvasStyle} layout=${m.layout} k=${m.k} worldSpan=${m.span}`);
    await browser.close();
  }
})();
