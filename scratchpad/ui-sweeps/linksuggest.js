// The suggested-links rows: is the note's name shown, or its markdown?
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const r = await page.evaluate(() => {
    // The helper the list now uses, exercised on the exact strings from the
    // owner's screenshot.
    const samples = [
      '# Leafeon Pokemon image test ![WallpaperEngineOverride_randomODWVLK.jpg](/media/8f5884.jpg)',
      'Some ideas for features I had: ![image.png](/media/8f5884.png) and more text after it',
      '## Girl with bell ![WallpaperEngineOverride_randomODWVLK.jp](/media/x.jpg)',
    ];
    const clean = samples.map((s) => {
      const t = window.__notePreviewProbe ? window.__notePreviewProbe(s) : null;
      return t;
    });
    return { clean, hasProbe: typeof window.__notePreviewProbe === 'function' };
  });
  // The function is module-scope, so measure the rendered row instead.
  const css = await page.evaluate(() => {
    const el = document.createElement('div');
    el.className = 'link-suggestion';
    document.body.append(el);
    const cs = getComputedStyle(el);
    const out = { gap: cs.gap, padding: cs.padding, marginBottom: cs.marginBottom, fontSize: cs.fontSize };
    el.remove();
    return out;
  });
  console.log(JSON.stringify({ probe: r, rowStyle: css }, null, 1));
  await browser.close();
})();
