const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(2500);
  const out = await page.evaluate(() => {
    const w = document.querySelector('.dash-widget .dash-board-thumb').closest('.dash-widget');
    return [...w.querySelectorAll('.dash-board-thumb')].map((svg) => {
      const edges = [...svg.querySelectorAll('.board-minimap-edge')];
      const cs = edges[0] ? getComputedStyle(edges[0]) : null;
      return {
        viewBox: svg.getAttribute('viewBox'),
        kids: [...svg.children].map((c) => c.getAttribute('class')),
        edgeCount: edges.length,
        edgeStroke: cs ? cs.stroke : null,
        edgeWidth: cs ? cs.strokeWidth : null,
        edgeOpacity: cs ? cs.opacity : null,
        edgeBBox: edges[0] ? (() => { const b = edges[0].getBoundingClientRect(); return { w: +b.width.toFixed(1), h: +b.height.toFixed(1) }; })() : null,
        blocks: svg.querySelectorAll('.board-minimap-card, .board-minimap-object, .board-minimap-branch').length,
      };
    });
  });
  console.log(JSON.stringify(out, null, 1));
  // Compare with the Library's card-size preview of the same map.
  await browser.close();
})();
