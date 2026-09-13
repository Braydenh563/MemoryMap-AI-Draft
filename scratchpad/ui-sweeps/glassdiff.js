// INBOX 110: "glass looks better on light mode and not dark but idk if thats
// an actual thing or if the values are different". Read the glass tokens and
// the surfaces that use them, in whichever theme lib.js booted.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1800);
  const out = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const tok = {};
    for (const n of ['--glass-blur', '--glass-opacity', '--glass-sheen-strength', '--shadow-intensity',
      '--card', '--inner', '--input-bg', '--glass-border', '--glass-highlight', '--glass-underline',
      '--glass-edge', '--glass-filter', '--glass-rim', '--glass-shadow', '--glass-catch',
      '--shadow-sm', '--shadow-md', '--shadow-lg', '--modal-bg']) {
      tok[n] = cs.getPropertyValue(n).trim().replace(/\s+/g, ' ');
    }
    const surf = {};
    for (const [name, sel] of [['card', 'section.card'], ['topbar', '#top-bar'], ['statusbar', '#status-bar'], ['widget', '.dash-widget']]) {
      const el = document.querySelector(sel);
      if (!el) { surf[name] = 'missing'; continue; }
      const c = getComputedStyle(el);
      surf[name] = {
        bg: c.backgroundColor, backdrop: (c.backdropFilter || c.webkitBackdropFilter || 'none'),
        shadow: c.boxShadow.replace(/\s+/g, ' ').slice(0, 160), border: c.borderColor,
      };
    }
    return { mode: document.documentElement.getAttribute('data-mode'), theme: localStorage.getItem('theme'), tok, surf };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
