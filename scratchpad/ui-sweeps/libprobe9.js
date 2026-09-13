// INBOX 107b item 1, the rest of the interaction: choosing a reader actually
// changes the select, and a kebab menu elsewhere still opens and picks.
const { boot, seed } = require('./libblockers.js');

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await seed(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1600);
  await page.click('#library-images-grid figure figcaption');
  await page.waitForTimeout(2500);

  const before = await page.evaluate(() => {
    const s = document.getElementById('ocr-reader');
    return { value: s.value, label: s.closest('.select-shell').querySelector('.select-value').textContent };
  });
  const pt = await page.evaluate(() => {
    const o = document.getElementById('ocr-reader').closest('.select-shell').querySelector('.select-opener');
    const r = o.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.mouse.click(pt.x, pt.y);
  await page.waitForTimeout(400);
  const rows = await page.evaluate(() => ({
    rows: [...document.querySelectorAll('.select-menu:not(.hidden) [role=option]')]
      .map((r) => ({ v: r.dataset.value, t: r.textContent, ariaDis: r.getAttribute('aria-disabled') })),
    opts: [...document.getElementById('ocr-reader').options]
      .map((o) => ({ v: o.value, hidden: o.hidden, disabled: o.disabled })),
  }));
  console.log('options', JSON.stringify(rows));
  // pick the last visible option that is not the current one
  const target = rows.rows.filter((r) => r.v !== before.value).slice(-1)[0];
  await page.evaluate((v) => {
    document.querySelector(`.select-menu:not(.hidden) [role=option][data-value="${v}"]`).click();
  }, target.v);
  await page.waitForTimeout(500);
  const after = await page.evaluate(() => {
    const s = document.getElementById('ocr-reader');
    const menu = s.closest('.select-shell').querySelector('.select-menu');
    return { value: s.value, label: s.closest('.select-shell').querySelector('.select-value').textContent,
      menuHidden: menu.classList.contains('hidden') };
  });
  console.log('reader select', JSON.stringify({ before, rows: rows.rows.length, chose: target.v, after }));

  // a kebab menu on another surface, to be sure the focus change did not
  // break the ordinary path
  await page.click('#ocr-close');
  await page.waitForTimeout(600);
  const kebab = await page.evaluate(() => {
    const b = document.querySelector('#library-images-grid .menu-wrap [aria-haspopup]');
    if (!b) return { err: 'no kebab' };
    b.click();
    const m = document.querySelector('#library-images-grid .action-menu:not(.hidden), body > .action-menu:not(.hidden)');
    return { open: !!m, items: m ? m.querySelectorAll('button').length : 0, focused: document.activeElement.className };
  });
  console.log('library kebab', JSON.stringify(kebab));
  await browser.close();
})();
