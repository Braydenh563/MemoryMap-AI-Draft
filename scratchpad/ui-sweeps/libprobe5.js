// INBOX 107b items 2/3, the other half: the Images tab's "text in this image"
// fold and its "See more", and the Files reading's own scroll offset, across a
// poll that finds a real change.
const { boot, seed } = require('./libblockers.js');

const snap = (page) => page.evaluate(() => {
  const d = document.querySelector('details.library-image-reading');
  const more = document.querySelector('.library-image-vision-ocr-more');
  const pre = document.querySelector('pre.library-file-reading-text');
  return {
    outer: d ? d.open : null,
    more: more && !more.classList.contains('hidden') ? more.textContent : null,
    preTop: pre ? Math.round(pre.scrollTop) : null,
    rebuilds: window.__rebuilds,
  };
});

const watch = (page) => page.evaluate(() => {
  window.__rebuilds = 0;
  new MutationObserver((r) => { for (const x of r) if (x.addedNodes.length || x.removedNodes.length) window.__rebuilds++; })
    .observe(document.getElementById('library-images-grid'), { childList: true });
});

const bump = (page, path, id, text) => page.evaluate(({ path, id, text }) => fetch(path, {
  method: 'POST',
  headers: { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId(), 'Content-Type': 'application/json' },
  body: JSON.stringify(text),
}).then((r) => r.status), { path, id, text });

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  const ids = await seed(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);

  // ---- Images tab ----
  await page.click('[data-media-kind="images"]');
  await page.waitForTimeout(1500);
  await watch(page);
  await page.click('details.library-image-reading > summary');
  await page.waitForTimeout(200);
  await page.click('.library-image-vision-ocr-more');
  await page.waitForTimeout(300);
  console.log('imgs open+more ', JSON.stringify(await snap(page)));
  console.log('  caption POST ', await bump(page, `/media/${ids.media}/caption`, ids.media, { text: 'Described in the background at ' + Date.now() }));
  await page.waitForTimeout(9000);
  console.log('imgs after poll', JSON.stringify(await snap(page)));

  // ---- Files tab, reading scrolled to its bottom ----
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1500);
  await watch(page);
  await page.click('details.library-image-reading > summary');
  await page.waitForTimeout(200);
  await page.click('details.library-file-reading-full > summary');
  await page.waitForTimeout(300);
  await page.evaluate(() => {
    const pre = document.querySelector('pre.library-file-reading-text');
    pre.scrollTop = pre.scrollHeight;
  });
  await page.waitForTimeout(400);
  console.log('files bottom   ', JSON.stringify(await snap(page)));
  console.log('  caption POST ', await bump(page, `/files/${ids.attachment}/analyse`, ids.attachment, { kind: 'caption', text: 'Rewritten at ' + Date.now() }));
  await page.waitForTimeout(9000);
  console.log('files after    ', JSON.stringify(await snap(page)));
  await browser.close();
})();
