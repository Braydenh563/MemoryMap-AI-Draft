// The two new doors into the page reader, and the one it already had from a
// PDF lightbox (which must now take the lightbox away with it).
const {boot} = require('/home/user/MemoryMap-AI/scratchpad/ui-sweeps/lib.js');
(async () => {
  const {browser, page} = await boot();
  const errs = [];
  page.on('pageerror', e => errs.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0,120)); });
  const shot = async (n) => page.screenshot({path: `/tmp/claude-0/ocrwork/${n}.png`});

  // 1. The command palette.
  await page.keyboard.press('Control+k');
  await page.waitForTimeout(700);
  await page.fill('#palette-input', 'read a document');
  await page.waitForTimeout(600);
  const rows = await page.evaluate(() => [...document.querySelectorAll('#palette-list *')]
    .map(e => e.textContent.trim()).filter(t => /read a document/i.test(t)).slice(0,2));
  console.log('PALETTE ROWS', JSON.stringify(rows));
  await page.keyboard.press('Enter');
  await page.waitForTimeout(3500);
  const afterPalette = await page.evaluate(() => {
    const ws = document.getElementById('ocr-workspace');
    const box = ws.getBoundingClientRect();
    const pt = document.elementFromPoint(Math.round(box.left + box.width/2), Math.round(box.top + 40));
    return {hidden: ws.classList.contains('hidden'), z: getComputedStyle(ws).zIndex,
      topmostInWs: pt ? !!pt.closest('#ocr-workspace') : null,
      title: (document.getElementById('ocr-title') || {}).textContent || '',
      railItems: document.querySelectorAll('#ocr-rail > *').length,
      text: ws.innerText.slice(0, 120).replace(/\n/g, ' | ')};
  });
  console.log('AFTER PALETTE', JSON.stringify(afterPalette));
  await shot('reader-palette');
  await page.evaluate(() => window.closeOcrWorkspace ? closeOcrWorkspace() : document.getElementById('ocr-workspace').classList.add('hidden'));
  await page.waitForTimeout(600);

  // 2. Tools & features.
  await page.evaluate(() => window.openFeatures && openFeatures());
  await page.waitForTimeout(700);
  await page.fill('#features-search', 'page reader');
  await page.waitForTimeout(500);
  const feat = await page.evaluate(() => {
    const hits = [...document.querySelectorAll('#features-list *')]
      .filter(e => /Page reader/.test(e.textContent) && e.tagName === 'BUTTON');
    const first = hits[0];
    if (first) first.click();
    return {matches: hits.length, count: (document.getElementById('features-count')||{}).textContent || ''};
  });
  console.log('FEATURES', JSON.stringify(feat));
  await page.waitForTimeout(3000);
  const afterFeat = await page.evaluate(() => {
    const ws = document.getElementById('ocr-workspace');
    return {wsHidden: ws.classList.contains('hidden'),
      featuresHidden: document.getElementById('features-overlay').classList.contains('hidden')};
  });
  console.log('AFTER FEATURES', JSON.stringify(afterFeat));
  await shot('reader-features');
  console.log('ERRORS', errs.length, JSON.stringify(errs.slice(0,5)));
  await browser.close();
})();
