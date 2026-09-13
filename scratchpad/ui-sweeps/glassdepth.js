// "glass looks better on light mode and not dark but idk if thats an actual
// thing or if the values are different" (the owner's evening batch).
//
// It is answerable with pixels rather than with an opinion. Three numbers per
// theme, sampled from a real card on the running app:
//
//   rim       the lit top edge against the card's own fill, one pixel below
//             it. This is what makes a pane read as having thickness.
//   lift      the card's fill against the page immediately outside it. This
//             is what makes it read as material rather than as a hole.
//   spread    how far the rim's brightness has decayed eight pixels down,
//             as a share of the rim, so a hard line and a soft one can be
//             told apart.
//
// Every figure is in 0 to 255 luminance units on the composited page, which
// is the only place the answer lives: the tokens are alphas over different
// grounds and cannot be compared as written.
//
//   BASE=http://127.0.0.1:8795 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/glassdepth.js
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8795';

const lum = (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b;

(async () => {
  const browser = await chromium.launch();
  const rows = [];
  for (const theme of ['light', 'dark']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    await ctx.addInitScript((t) => {
      try {
        localStorage.setItem('theme', t);
        localStorage.setItem('onboardingDone', '1');
      } catch (e) { /* no storage */ }
    }, theme);
    const page = await ctx.newPage();
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
    await page.fill('#lock-password', PW);
    await page.click('#lock-submit');
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
      const o = document.getElementById('onboarding-overlay');
      if (o) o.classList.add('hidden');
    });
    await page.click('[data-tab="dashboard"]').catch(() => {});
    await page.waitForTimeout(1200);

    const target = await page.evaluate(() => {
      const card = document.querySelector('.tab-page:not(.hidden) .card');
      if (!card) return null;
      const r = card.getBoundingClientRect();
      const cs = getComputedStyle(document.documentElement);
      return {
        x: Math.round(r.left + r.width / 2),
        y: Math.round(r.top),
        mode: document.documentElement.dataset.mode,
        highlight: cs.getPropertyValue('--glass-highlight').trim(),
        filter: cs.getPropertyValue('--glass-filter').trim(),
      };
    });
    if (!target) { console.log(`${theme}: no card found`); await ctx.close(); continue; }

    // A 1px column through the card's top edge: three above it, twelve below.
    const shot = await page.screenshot({
      clip: { x: target.x, y: target.y - 3, width: 1, height: 16 },
    });
    // Decode the PNG in the page, which has a canvas and no dependencies.
    const column = await page.evaluate(async (bytes) => {
      const blob = new Blob([new Uint8Array(bytes)], { type: 'image/png' });
      const bitmap = await createImageBitmap(blob);
      const cv = document.createElement('canvas');
      cv.width = bitmap.width;
      cv.height = bitmap.height;
      const g = cv.getContext('2d');
      g.drawImage(bitmap, 0, 0);
      const { data } = g.getImageData(0, 0, bitmap.width, bitmap.height);
      const out = [];
      for (let i = 0; i < data.length; i += 4) out.push([data[i], data[i + 1], data[i + 2]]);
      return out;
    }, [...shot]);

    const L = column.map(([r, g, b]) => lum(r, g, b));
    const outside = L[0];            // 3px above the card's top edge
    const rim = Math.max(...L.slice(2, 5));  // the lit edge itself
    const fill = L[8];               // the card's own fill, 5px in
    const eight = L[11];             // eight pixels below the rim
    rows.push({
      theme,
      mode: target.mode,
      outside: Math.round(outside),
      rim: Math.round(rim),
      fill: Math.round(fill),
      rimOverFill: +(rim - fill).toFixed(1),
      lift: +(fill - outside).toFixed(1),
      decay: +(100 * (1 - Math.abs(eight - fill) / Math.max(1, Math.abs(rim - fill)))).toFixed(0),
      highlight: target.highlight,
      filter: target.filter,
    });
    await ctx.close();
  }
  for (const r of rows) {
    console.log(
      `${r.theme} (data-mode=${r.mode}): page ${r.outside}, rim ${r.rim}, fill ${r.fill}\n`
      + `   rim over fill ${r.rimOverFill} units, card over page ${r.lift} units, rim decayed ${r.decay}% by 8px\n`
      + `   --glass-highlight ${r.highlight}\n   --glass-filter ${r.filter}`,
    );
  }
  await browser.close();
})();
