// The dashboard's start band, measured (UI_MODERNISATION_PLAN, INBOX 60).
//
// The owner's report is about proportion: "three pill links, three skill
// pills with dashed borders, four stat tiles, all left-aligned in a band
// with most of its width empty". That is a measurable claim, so this prints
// the numbers rather than an impression: how wide each row's content is
// against the band it sits in, how much of the band is empty on the right,
// and the height of the whole thing (the recommendation says the band's
// height must not grow).
//
//   BASE=http://127.0.0.1:8795 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/dashstart.js
const { boot } = require('./lib.js');

const WIDTHS = (process.env.WIDTHS || '1440').split(',').map(Number);

(async () => {
  for (const width of WIDTHS) {
    const { browser, page } = await boot({ viewport: { width, height: 900 } });
    await page.click('[data-tab="dashboard"]').catch(() => {});
    await page.waitForTimeout(1200);
    const out = await page.evaluate(() => {
      const box = (el) => {
        const r = el.getBoundingClientRect();
        return { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.left), y: Math.round(r.top) };
      };
      const rows = [];
      const band = document.getElementById('dash-quicklinks');
      if (!band) return ['no #dash-quicklinks'];
      const bandBox = box(band);
      rows.push(`band #dash-quicklinks ${bandBox.w}x${bandBox.h} at y=${bandBox.y}`);
      for (const group of band.querySelectorAll('.launch-group')) {
        const row = group.querySelector('.launch-row');
        const label = group.querySelector('.launch-label');
        const kids = [...(row ? row.children : [])];
        const right = kids.length ? Math.max(...kids.map((k) => k.getBoundingClientRect().right)) : 0;
        const rowBox = box(row || group);
        const used = kids.length ? Math.round(right - rowBox.x) : 0;
        rows.push(
          `  ${label ? label.textContent : '?'}: ${kids.length} items, content ${used}px `
          + `of ${rowBox.w}px (${rowBox.w ? Math.round(100 * used / rowBox.w) : 0}% used, `
          + `${rowBox.w - used}px empty), row ${rowBox.h}px tall`,
        );
        rows.push(`     items: ${kids.map((k) => `${Math.round(k.getBoundingClientRect().width)}x${Math.round(k.getBoundingClientRect().height)}`).join(' ')}`);
      }
      const stats = document.getElementById('dash-stats');
      if (stats) {
        const sb = box(stats);
        const tiles = [...stats.children];
        const right = tiles.length ? Math.max(...tiles.map((t) => t.getBoundingClientRect().right)) : 0;
        const used = tiles.length ? Math.round(right - sb.x) : 0;
        rows.push(`stats #dash-stats ${sb.w}x${sb.h}: ${tiles.length} tiles, content ${used}px (${sb.w - used}px empty)`);
        rows.push(`     tiles: ${tiles.map((t) => `${Math.round(t.getBoundingClientRect().width)}x${Math.round(t.getBoundingClientRect().height)}`).join(' ')}`);
      }
      // The first configurable widget, so a change to the band can be checked
      // against "the band's height unchanged".
      const grid = document.getElementById('dash-grid');
      if (grid && grid.firstElementChild) {
        rows.push(`first widget starts at y=${Math.round(grid.firstElementChild.getBoundingClientRect().top)} of ${window.innerHeight}`);
      }
      const heat = document.querySelector('.heatmap, #dash-heatmap, [class*="heatmap"]');
      if (heat) {
        const hb = box(heat);
        const cell = heat.querySelector('div, span, rect');
        rows.push(`heatmap ${heat.className} ${hb.w}x${hb.h}${cell ? `, cell ${Math.round(cell.getBoundingClientRect().width)}x${Math.round(cell.getBoundingClientRect().height)}` : ''}`);
      }
      const toTop = document.querySelector('.scroll-top');
      rows.push(`scroll-top button: ${toTop ? (toTop.checkVisibility && toTop.checkVisibility({ visibilityProperty: true, opacityProperty: true }) ? 'visible' : 'present but hidden') : 'absent'}`);
      return rows;
    });
    console.log(`== ${width}px`);
    out.forEach((r) => console.log('   ' + r));
    await browser.close();
  }
})();
