// INBOX 119a reproduced: line numbers on, then Preview. What is left above the
// preview panel, with rects.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(500);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('capture'));
    if (b) b.click();
  });
  await page.waitForTimeout(300);
  const shot = () => page.evaluate(() => {
    const q = (s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
      return { y: +r.y.toFixed(1), h: +r.height.toFixed(1), w: +r.width.toFixed(1), disp: cs.display, cls: e.className, bg: cs.backgroundColor, bd: cs.borderRightWidth }; };
    return { wrap: q('#capture .gutter-wrap'), gutter: q('#capture .doc-gutter'), ta: q('#entry-content'), prev: q('#entry-preview'), toolbar: q('#note-toolbar') };
  });
  // expand the toolbar so the gutter button is reachable, then toggle line numbers
  await page.evaluate(() => { document.querySelector('#note-toolbar .doc-toolbar-collapse, #note-toolbar .doc-toolbar-collapse-btn')?.click(); });
  await page.waitForTimeout(300);
  say('toolbarbtns', await page.evaluate(() => [...document.querySelectorAll('#note-toolbar button')].filter((b) => b.getBoundingClientRect().width > 0).map((b) => ({ cls: b.className.slice(0, 30), t: (b.textContent||'').trim().slice(0,10), title: b.title.slice(0,30) }))));
  await page.evaluate(() => { document.getElementById('entry-content').value = 'line one\nline two\nline three'; });
  await page.evaluate(() => { document.querySelector('#note-toolbar .doc-toolbar-gutter')?.click(); });
  await page.waitForTimeout(400);
  say('gutter-on-edit', await shot());
  await page.evaluate(() => document.getElementById('entry-preview-toggle').click());
  await page.waitForTimeout(500);
  say('gutter-on-preview', await shot());
  await page.screenshot({ path: (process.env.SCRATCH||'.') + '/shots/gutter-preview.png', clip: { x: 150, y: 200, width: 700, height: 300 } });
  await browser.close();
})();
