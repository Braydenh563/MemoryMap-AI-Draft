// Where does #ocr-image go? It is null in ocrLoadPage after a text file has
// been opened in the workspace.
const { boot, seed } = require('./libblockers.js');
const where = (page, tag) => page.evaluate((tag) => {
  const img = document.getElementById('ocr-image');
  const stage = document.getElementById('ocr-stage');
  return { tag, img: !!img, imgParent: img && img.parentElement && (img.parentElement.id || img.parentElement.className),
    stageKids: stage ? [...stage.children].map((c) => c.tagName + '#' + (c.id || '') + '.' + (c.className || '')) : null };
}, tag);

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await seed(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1800);
  console.log(JSON.stringify(await where(page, 'before')));
  await page.click('#library-images-grid figure figcaption');
  await page.waitForTimeout(2500);
  console.log(JSON.stringify(await where(page, 'md open')));
  await page.click('#ocr-close');
  await page.waitForTimeout(600);
  console.log(JSON.stringify(await where(page, 'closed')));
  await browser.close();
})();
