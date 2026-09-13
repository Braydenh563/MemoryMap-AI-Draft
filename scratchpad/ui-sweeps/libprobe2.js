// Why the OCR reader select will not open: trace class mutations + close calls.
const { boot, seed } = require('./libblockers.js');

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await seed(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1500);
  await page.click('#library-images-grid figure figcaption');
  await page.waitForTimeout(2500);

  await page.evaluate(() => {
    window.__log = [];
    const s = document.getElementById('ocr-reader');
    const shell = s.closest('.select-shell');
    const menu = shell.querySelector('.select-menu');
    window.__menu = menu;
    new MutationObserver(() => {
      window.__log.push('class=' + menu.className + ' parent=' + menu.parentElement.tagName);
    }).observe(menu, { attributes: true, attributeFilter: ['class'] });
    for (const type of ['pointerdown', 'mousedown', 'click', 'pointerup', 'mouseup', 'focusin', 'scroll']) {
      document.addEventListener(type, (e) => {
        window.__log.push(`doc-capture ${type} target=${e.target.tagName}.${(e.target.className || '').toString().slice(0, 30)}`);
      }, true);
    }
    const orig = window.closeActionMenus;
    if (orig) {
      window.closeActionMenus = function () {
        window.__log.push('closeActionMenus ' + new Error().stack.split('\n').slice(1, 5).join(' | '));
        return orig.apply(this, arguments);
      };
    } else window.__log.push('closeActionMenus not global');
  });

  const box = await page.evaluate(() => {
    const o = document.getElementById('ocr-reader').closest('.select-shell').querySelector('.select-opener');
    const r = o.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.mouse.click(box.x, box.y);
  await page.waitForTimeout(500);
  const log = await page.evaluate(() => ({
    log: window.__log,
    hidden: window.__menu.classList.contains('hidden'),
    parent: window.__menu.parentElement.tagName,
  }));
  console.log(JSON.stringify(log, null, 1));
  await browser.close();
})();
