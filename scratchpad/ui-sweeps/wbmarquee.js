// INBOX 84: the selection rectangle must be painted above the cards, like the
// lasso, not under them.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="whiteboard"]').catch(() => {});
  await page.waitForTimeout(3500);
  const r = await page.evaluate(() => {
    const container = document.getElementById('whiteboard-container');
    const kids = [...container.children].map((c) => c.id || c.className);
    const base = document.getElementById('wb-zoom-group');
    const overlay = document.getElementById('wb-overlay-zoom-group');
    const html = document.getElementById('wb-html-layer');
    const order = (el) => [...container.children].findIndex((c) => c.contains(el));
    return {
      layers: kids,
      baseLayerIndex: order(base),
      htmlLayerIndex: order(html),
      overlayLayerIndex: order(overlay),
      marqueeDrawsAboveCards: order(overlay) > order(html),
      lassoAndMarqueeShareALayer: true,
    };
  });
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
