// Second pass of the Timeline audit: the numbers the first pass raised
// questions about. How much of the grid is empty, how badly the line view's
// dots collide at each width, where the line view's colours come from, and
// what the two views cost in DOM nodes.
const { boot } = require('./lib.js');

(async () => {
  const { browser, ctx, page } = await boot();
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => { const b = document.querySelector('[data-tab="timeline"]'); if (b) b.click(); });
    await page.waitForTimeout(1200);

    await page.evaluate(() => { const s = document.getElementById('timeline-view'); s.value = 'grid'; s.dispatchEvent(new Event('change', { bubbles: true })); });
    await page.waitForTimeout(1400);
    const grid = await page.evaluate(() => {
      const cells = Array.from(document.querySelectorAll('#timeline-grid .timeline-cell'));
      const empty = cells.filter(c => !c.children.length).length;
      const areaAll = cells.reduce((a, c) => a + c.getBoundingClientRect().width * c.getBoundingClientRect().height, 0);
      const areaEmpty = cells.filter(c => !c.children.length).reduce((a, c) => a + c.getBoundingClientRect().width * c.getBoundingClientRect().height, 0);
      return {
        cells: cells.length, empty, emptyPct: Math.round(100 * empty / cells.length),
        emptyAreaPct: Math.round(100 * areaEmpty / areaAll),
        nodes: document.getElementById('timeline-grid').querySelectorAll('*').length,
        gridW: document.getElementById('timeline-grid').getBoundingClientRect().width,
        colTemplate: getComputedStyle(document.getElementById('timeline-grid')).gridTemplateColumns.split(' ').length,
      };
    });

    await page.evaluate(() => { const s = document.getElementById('timeline-view'); s.value = 'line'; s.dispatchEvent(new Event('change', { bubbles: true })); });
    await page.waitForTimeout(1800);
    const line = await page.evaluate(() => {
      const dots = Array.from(document.querySelectorAll('#timeline-branch-svg circle.timeline-branch-dot'));
      const pts = dots.map(d => ({ x: +d.getAttribute('cx'), y: +d.getAttribute('cy'), r: +d.getAttribute('r') }));
      let collide = 0;
      for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
        if (Math.hypot(dx, dy) < 20) collide++;
      }
      const svg = document.getElementById('timeline-branch-svg');
      const vb = svg.getAttribute('viewBox');
      const labels = Array.from(svg.querySelectorAll('text.timeline-branch-label')).map(t => ({ text: t.textContent, fill: t.getAttribute('fill') }));
      return {
        dots: dots.length, collidingPairs: collide, viewBox: vb,
        nodes: svg.querySelectorAll('*').length,
        labels,
        textNodes: svg.querySelectorAll('text').length,
        // Does any dot carry a title, a date, a tag? Everything a person reads.
        readableTextInSvg: Array.from(svg.querySelectorAll('text')).map(t => t.textContent).join(' | ').slice(0, 300),
      };
    });
    console.log(`\n=== ${width} ===`);
    console.log('grid', JSON.stringify(grid));
    console.log('line', JSON.stringify(line, null, 1));
  }
  await ctx.close(); await browser.close();
})();
