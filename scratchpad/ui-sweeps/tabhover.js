// Every tab-like control's *hover* paint: a filled rectangle with square
// corners is what "square tab corners" looks like in a screenshot.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('documents'));
  await page.waitForTimeout(1800);
  for (const sel of ['#doc-sidebar-tabs button:not(.active)', '#doc-view-seg button:not(.active)', '#tab-btn-notes']) {
    const el = await page.$(sel);
    if (!el) { console.log(sel, 'MISSING'); continue; }
    const before = await el.evaluate((e) => { const c = getComputedStyle(e); return { bg: c.backgroundColor, r: c.borderRadius }; });
    await el.hover();
    await page.waitForTimeout(350);
    const after = await el.evaluate((e) => { const c = getComputedStyle(e); const b = e.getBoundingClientRect(); return { bg: c.backgroundColor, r: c.borderRadius, w: +b.width.toFixed(1), h: +b.height.toFixed(1) }; });
    console.log(sel, 'rest', JSON.stringify(before), 'hover', JSON.stringify(after));
    await page.mouse.move(5, 5);
    await page.waitForTimeout(200);
  }
  // Focus-visible ring shape too.
  const f = await page.evaluate(() => {
    const b = document.querySelector('#doc-sidebar-tabs button:not(.active)');
    b.focus();
    const c = getComputedStyle(b);
    return { outline: c.outline, offset: c.outlineOffset, r: c.borderRadius };
  });
  console.log('focus', JSON.stringify(f));
  await page.hover('#doc-sidebar-tabs button:not(.active)');
  await page.waitForTimeout(300);
  const box = await (await page.$('#doc-sidebar-tabs')).boundingBox();
  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/tabhover.png', clip: { x: box.x - 6, y: box.y - 6, width: box.width + 12, height: box.height + 14 } });
  await browser.close();
})();
