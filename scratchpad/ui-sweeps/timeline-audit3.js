// Third pass: keyboard reach and what a row can actually do. How many tab
// stops does each view cost, is anything in the line view focusable at all,
// and what does clicking a note give you.
const { boot } = require('./lib.js');
(async () => {
  const { browser, ctx, page } = await boot();
  await page.evaluate(() => { document.querySelector('[data-tab="timeline"]').click(); });
  await page.waitForTimeout(1200);
  for (const view of ['grid', 'line']) {
    await page.evaluate((v) => { const s = document.getElementById('timeline-view'); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); }, view);
    await page.waitForTimeout(1600);
    const r = await page.evaluate(() => {
      const focusables = Array.from(document.querySelectorAll('#tab-timeline button, #tab-timeline a[href], #tab-timeline input, #tab-timeline select, #tab-timeline summary, #tab-timeline [tabindex]:not([tabindex="-1"])'))
        .filter(e => e.offsetParent !== null || e.getClientRects().length);
      const svgFocusable = Array.from(document.querySelectorAll('#timeline-branch-svg [tabindex], #timeline-branch-svg a')).length;
      return { focusStops: focusables.length, svgFocusable, dockStops: document.querySelectorAll('.dock[data-dock-name="timeline"] button, .dock[data-dock-name="timeline"] input, .dock[data-dock-name="timeline"] select, .dock[data-dock-name="timeline"] summary').length };
    });
    console.log(view, JSON.stringify(r));
  }
  // What opens when a note is clicked
  await page.evaluate(() => { const s = document.getElementById('timeline-view'); s.value = 'grid'; s.dispatchEvent(new Event('change', { bubbles: true })); });
  await page.waitForTimeout(1400);
  await page.evaluate(() => { document.querySelector('#timeline-grid .timeline-dot').click(); });
  await page.waitForTimeout(700);
  const popup = await page.evaluate(() => {
    const p = document.getElementById('timeline-popup');
    const b = p.getBoundingClientRect();
    return {
      hidden: p.classList.contains('hidden'),
      w: Math.round(b.width), h: Math.round(b.height),
      buttons: Array.from(p.querySelectorAll('button')).map(x => x.textContent.trim() || x.getAttribute('aria-label')),
      info: (document.getElementById('timeline-popup-info') || {}).textContent,
    };
  });
  console.log('popup', JSON.stringify(popup));
  await ctx.close(); await browser.close();
})();
