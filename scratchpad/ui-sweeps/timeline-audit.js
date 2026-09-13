// The Timeline as it is, measured before anything is redesigned (the audit
// step of TIMELINE_PLAN.md). Prints, per view and per width: how many nodes,
// their heights, the distinct font-size/colour/padding/radius recipes, how far
// the page scrolls sideways, and what a row actually offers a person.
const { boot } = require('./lib.js');

const WIDTHS = [1440, 1024, 390];

(async () => {
  const { browser, ctx, page } = await boot();
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => { const b = document.querySelector('[data-tab="timeline"]'); if (b) b.click(); });
    await page.waitForTimeout(1500);
    for (const view of ['grid', 'line']) {
      await page.evaluate((v) => {
        const sel = document.getElementById('timeline-view');
        sel.value = v; sel.dispatchEvent(new Event('change', { bubbles: true }));
      }, view);
      await page.waitForTimeout(1600);
      const out = await page.evaluate(() => {
        const sig = (el) => {
          const s = getComputedStyle(el);
          return [s.fontSize, s.fontWeight, s.color, s.backgroundColor, s.padding, s.borderRadius, s.borderWidth].join('|');
        };
        const box = (sel) => Array.from(document.querySelectorAll(sel));
        const dots = box('#timeline-grid .timeline-dot');
        const heads = box('#timeline-head, #timeline-grid .timeline-head');
        const bands = box('#timeline-grid .timeline-band');
        const svgDots = box('#timeline-branch-svg circle.timeline-branch-dot');
        const heights = (els) => Array.from(new Set(els.map(e => Math.round(e.getBoundingClientRect().height * 10) / 10)));
        const scroll = document.getElementById('timeline-scroll');
        const page_ = document.getElementById('tab-timeline');
        const svg = document.getElementById('timeline-branch-svg');
        const wrap = document.getElementById('timeline-branch-wrap');
        // What can a person do from one row/dot?
        const first = dots[0];
        const affordances = first ? {
          tag: first.tagName,
          children: Array.from(first.children).map(c => c.className),
          hasMenu: !!first.querySelector('[data-menu], .action-menu-btn'),
        } : null;
        return {
          dotCount: dots.length,
          dotHeights: heights(dots),
          dotSigs: Array.from(new Set(dots.map(sig))).length,
          headHeights: heights(heads),
          bandHeights: heights(bands),
          svgDots: svgDots.length,
          svgH: svg ? Math.round(svg.getBoundingClientRect().height) : 0,
          wrapH: wrap ? Math.round(wrap.getBoundingClientRect().height) : 0,
          wrapScrollH: wrap ? wrap.scrollHeight : 0,
          gridScrollW: scroll ? scroll.scrollWidth : 0,
          gridClientW: scroll ? scroll.clientWidth : 0,
          docScrollW: document.documentElement.scrollWidth,
          docClientW: document.documentElement.clientWidth,
          pageScrollW: page_ ? page_.scrollWidth : 0,
          pageClientW: page_ ? page_.clientWidth : 0,
          count: (document.getElementById('timeline-count') || {}).textContent,
          affordances,
          // Every distinct font-size used anywhere inside the timeline tab.
          fontSizes: Array.from(new Set(Array.from(document.querySelectorAll('#tab-timeline *'))
            .filter(e => e.textContent && e.getBoundingClientRect().height)
            .map(e => getComputedStyle(e).fontSize))).sort(),
        };
      });
      console.log(`\n=== ${width}px / ${view} ===`);
      console.log(JSON.stringify(out, null, 1));
    }
  }
  await ctx.close(); await browser.close();
})();
