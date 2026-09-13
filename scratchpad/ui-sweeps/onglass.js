// Text on a blurred surface, as a contrast ratio (INBOX 102, DESIGN.md rule
// 4: "use vibrant colors on top of materials", and `--text-on-glass` one step
// above `--text`).
//
// contrast.js reports only what *fails* 4.5:1, so it cannot show a change
// that makes passing text better. This prints the number itself, for one text
// element on each blurred surface, in whichever theme is asked for.
//
//   BASE=http://127.0.0.1:8790 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     THEME=dark node scratchpad/ui-sweeps/onglass.js
const { boot } = require('./lib.js');

(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(900);
  // Open a kebab and the Filter menu so their rows are measurable at all.
  const kebab = await page.$('.entry-list .menu-wrap > button');
  if (kebab) { await kebab.click(); await page.waitForTimeout(400); }
  await page.evaluate(() => {
    const d = document.getElementById('notes-filter-menu');
    if (d) d.open = true;
  });
  await page.waitForTimeout(300);
  const rows = await page.evaluate(() => {
    const parse = (c) => {
      const m = c.match(/^rgba?\(([^)]+)\)$/);
      if (!m) return null;
      const p = m[1].split(/[\s,/]+/).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    };
    const lum = ({ r, g, b }) => {
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    // The composite a person actually sees: the surface's own fill over the
    // page, then the text over that. A translucent surface is not a colour.
    const over = (fg, bg) => ({
      r: fg.r * fg.a + bg.r * (1 - fg.a),
      g: fg.g * fg.a + bg.g * (1 - fg.a),
      b: fg.b * fg.a + bg.b * (1 - fg.a),
      a: 1,
    });
    const ratio = (a, b) => {
      const l1 = lum(a); const l2 = lum(b);
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    };
    const page_ = parse(getComputedStyle(document.body).backgroundColor)
      || { r: 255, g: 255, b: 255, a: 1 };
    const out = [];
    for (const sel of ['.action-menu:not(.hidden) .menu-item', '#notes-filter-menu[open] .dock-menu-list label',
      '.tab-page:not(.hidden) .dock .dock-title', 'header#top-bar #tab-bar button', '.notes-subtabs button']) {
      const el = document.querySelector(sel);
      if (!el) { out.push(`${sel}: absent`); continue; }
      const cs = getComputedStyle(el);
      const fg = parse(cs.color);
      let surface = null;
      for (let e = el; e && !surface; e = e.parentElement) {
        const c = parse(getComputedStyle(e).backgroundColor);
        if (c && c.a > 0) surface = c;
      }
      if (!fg || !surface) { out.push(`${sel}: no colour`); continue; }
      const bg = surface.a < 1 ? over(surface, page_) : surface;
      out.push(`${sel}: ${ratio(fg, bg).toFixed(2)}:1  ${cs.color} on rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)})`);
    }
    return out;
  });
  console.log(`== ${process.env.THEME || 'light'}`);
  rows.forEach((r) => console.log('   ' + r));
  await browser.close();
})();
