// INBOX 107b items 2 and 3: does the reading disclosure survive a scroll to
// the bottom of the text, a poll, and a "see more"?
const { boot, seed } = require('./libblockers.js');

async function watch(page) {
  await page.evaluate(() => {
    window.__rebuilds = 0;
    const grid = document.getElementById('library-images-grid');
    new MutationObserver((recs) => {
      for (const r of recs) if (r.addedNodes.length || r.removedNodes.length) window.__rebuilds++;
    }).observe(grid, { childList: true });
  });
}

async function snap(page, sel) {
  return page.evaluate((sel) => {
    const grid = document.getElementById('library-images-grid');
    const d = document.querySelector('details.library-image-reading');
    const inner = document.querySelector('details.library-file-reading-full');
    const pre = document.querySelector('pre.library-file-reading-text');
    const more = document.querySelector(sel);
    const scroller = document.querySelector('.library-media-scroll, #library-images-grid')?.parentElement;
    return {
      outer: d ? d.open : null,
      inner: inner ? inner.open : null,
      preScrollTop: pre ? Math.round(pre.scrollTop) : null,
      preScrollH: pre ? pre.scrollHeight : null,
      preClientH: pre ? pre.clientHeight : null,
      moreText: more ? more.textContent : null,
      rebuilds: window.__rebuilds,
      pageY: Math.round(window.scrollY),
      gridChildren: grid.children.length,
    };
  }, sel);
}

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await seed(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);

  // ---------- FILES ----------
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1500);
  await watch(page);
  await page.click('details.library-image-reading > summary');
  await page.waitForTimeout(300);
  await page.click('details.library-file-reading-full > summary');
  await page.waitForTimeout(400);
  console.log('files opened   ', JSON.stringify(await snap(page, '.library-file-reading-more')));
  // scroll the reading text to its bottom, the way a reader does
  await page.evaluate(() => {
    const pre = document.querySelector('pre.library-file-reading-text');
    pre.scrollTop = pre.scrollHeight;
    pre.dispatchEvent(new Event('scroll', { bubbles: true }));
  });
  await page.mouse.move(700, 500);
  await page.mouse.wheel(0, 600);
  await page.waitForTimeout(700);
  console.log('files scrolled ', JSON.stringify(await snap(page, '.library-file-reading-more')));
  await page.waitForTimeout(8000); // one full poll cycle (6s)
  console.log('files polled   ', JSON.stringify(await snap(page, '.library-file-reading-more')));

  // ---------- IMAGES ----------
  await page.click('[data-media-kind="images"]');
  await page.waitForTimeout(1500);
  await watch(page);
  await page.click('details.library-image-reading > summary');
  await page.waitForTimeout(300);
  console.log('imgs opened    ', JSON.stringify(await snap(page, '.library-image-vision-ocr-more')));
  await page.click('.library-image-vision-ocr-more');
  await page.waitForTimeout(500);
  console.log('imgs see-more  ', JSON.stringify(await snap(page, '.library-image-vision-ocr-more')));
  await page.mouse.move(700, 500);
  await page.mouse.wheel(0, 800);
  await page.waitForTimeout(700);
  console.log('imgs scrolled  ', JSON.stringify(await snap(page, '.library-image-vision-ocr-more')));
  await page.waitForTimeout(8000);
  console.log('imgs polled    ', JSON.stringify(await snap(page, '.library-image-vision-ocr-more')));
  await browser.close();
})();
