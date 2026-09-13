// INBOX 107b items 2/3, the real trigger: a poll that finds a genuine change
// (a caption written in the background) rebuilds every tile, which is what
// closes the reading and scrolls the list back to the top.
const { boot, seed, LONG } = require('./libblockers.js');

async function state(page) {
  return page.evaluate(() => {
    const grid = document.getElementById('library-images-grid');
    let sc = grid, chain = [];
    for (let n = grid; n && n !== document.body; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (/auto|scroll/.test(cs.overflowY) && n.scrollHeight > n.clientHeight) { sc = n; chain.push(n.className); break; }
    }
    const d = document.querySelector('details.library-image-reading');
    const inner = document.querySelector('details.library-file-reading-full');
    return {
      outer: d ? d.open : null,
      inner: inner ? inner.open : null,
      scroller: sc === grid ? 'window' : sc.className.slice(0, 30),
      scTop: Math.round(sc === grid ? window.scrollY : sc.scrollTop),
      winY: Math.round(window.scrollY),
      rebuilds: window.__rebuilds,
    };
  });
}

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  const ids = await seed(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    window.__rebuilds = 0;
    new MutationObserver((r) => { for (const x of r) if (x.addedNodes.length || x.removedNodes.length) window.__rebuilds++; })
      .observe(document.getElementById('library-images-grid'), { childList: true });
  });
  await page.click('details.library-image-reading > summary');
  await page.waitForTimeout(200);
  await page.click('details.library-file-reading-full > summary');
  await page.waitForTimeout(300);
  // scroll the list down, the way a reader who has opened a row three rows in has
  await page.evaluate(() => {
    const grid = document.getElementById('library-images-grid');
    for (let n = grid; n && n !== document.body; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (/auto|scroll/.test(cs.overflowY) && n.scrollHeight > n.clientHeight) { n.scrollTop = 240; return; }
    }
    window.scrollTo(0, 240);
  });
  await page.waitForTimeout(300);
  console.log('open+scrolled ', JSON.stringify(await state(page)));

  // A caption arrives in the background, exactly what the six-second poll is for.
  await page.evaluate(async (id) => {
    const h = { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId(), 'Content-Type': 'application/json' };
    await fetch(`/files/${id}/analyse`, { method: 'POST', headers: h,
      body: JSON.stringify({ kind: 'caption', text: 'A handout about agents, described later.' }) });
  }, ids.attachment);
  await page.waitForTimeout(9000);
  console.log('after poll    ', JSON.stringify(await state(page)));
  await browser.close();
})();
