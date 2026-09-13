const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('dashboard'));
  await page.waitForTimeout(2500);
  const out = await page.evaluate(() => {
    const grp = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return 'missing';
      const cs = getComputedStyle(el);
      return {
        display: cs.display, grid: cs.gridTemplateColumns, gap: cs.gap, overflowX: cs.overflowX,
        kids: [...el.children].map((k) => {
          const b = k.getBoundingClientRect();
          const kc = getComputedStyle(k);
          return { t: k.textContent.trim().replace(/\s+/g, ' ').slice(0, 22), w: +b.width.toFixed(1), h: +b.height.toFixed(1), flex: kc.flex, radius: kc.borderRadius, bg: kc.backgroundColor };
        }),
      };
    };
    const groups = [...document.querySelectorAll('#dash-launch .launch-group, .launch-group')].map((g, i) => ({
      i, label: (g.querySelector('.launch-label, .muted')?.textContent || '').trim().slice(0, 20),
      row: (() => { const r = g.querySelector('.launch-row, .row, div:last-child'); if (!r) return null; const cs = getComputedStyle(r); return { display: cs.display, grid: cs.gridTemplateColumns, gap: cs.gap, kids: [...r.children].map((k) => ({ t: k.textContent.trim().replace(/\s+/g, ' ').slice(0, 20), w: +k.getBoundingClientRect().width.toFixed(1), flex: getComputedStyle(k).flex })) }; })(),
    }));
    return { groups, stats: grp('#dash-stats'), toolbar: grp('.dash-toolbar') };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
