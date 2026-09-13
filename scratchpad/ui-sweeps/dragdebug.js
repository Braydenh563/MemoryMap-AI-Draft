const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="library"]').catch(() => {});
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]').catch(() => {});
  await page.waitForTimeout(1200);
  const r = await page.evaluate(() => {
    const objs = [...document.querySelectorAll('.wb-object')];
    const first = objs[0];
    const b = first ? first.getBoundingClientRect() : null;
    return {
      count: objs.length,
      boardOpen: !!document.getElementById('whiteboard-container'),
      landing: !document.querySelector('#wb-boards-landing')?.classList.contains('hidden'),
      first: b ? { x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height),
                   visible: first.checkVisibility(), cls: first.className.slice(0, 40) } : null,
      topAt: b ? (document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2)?.className || '').slice(0, 50) : null,
    };
  });
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
