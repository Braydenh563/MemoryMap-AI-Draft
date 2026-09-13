// INBOX 119b: "the let the ai decide button popup is a massive gap above the
// picker". Opens the File under picker in Capture and prints the opener's and
// the menu's rects, the menu's own styles, and whether it escaped.
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
  await page.waitForTimeout(400);
  const probe = async (which, sel) => {
    const r = await page.evaluate((s) => {
      const shell = document.querySelector(s);
      const opener = shell.querySelector('.select-opener') || shell;
      opener.click();
      return null;
    }, sel);
    await page.waitForTimeout(450);
    say(which, await page.evaluate((s) => {
      const shell = document.querySelector(s);
      const opener = shell.querySelector('.select-opener') || shell;
      const menu = [...document.querySelectorAll('.action-menu')].find((m) => !m.classList.contains('hidden'));
      if (!menu) return { opener: opener.getBoundingClientRect().toJSON(), menu: null };
      const mr = menu.getBoundingClientRect(); const orr = opener.getBoundingClientRect();
      const cs = getComputedStyle(menu);
      return {
        opener: { top: +orr.top.toFixed(1), bottom: +orr.bottom.toFixed(1), left: +orr.left.toFixed(1) },
        menu: { top: +mr.top.toFixed(1), bottom: +mr.bottom.toFixed(1), left: +mr.left.toFixed(1), h: +mr.height.toFixed(1), w: +mr.width.toFixed(1) },
        gapAboveOpener: +(orr.top - mr.bottom).toFixed(1),
        cls: menu.className, parent: menu.parentElement.tagName + '.' + menu.parentElement.className.slice(0, 24),
        style: { top: cs.top, bottom: cs.bottom, left: cs.left, pos: cs.position, maxH: cs.maxHeight, transform: cs.transform },
        inline: menu.getAttribute('style'),
        scroll: { sh: menu.scrollHeight, ch: menu.clientHeight },
      };
    }, sel));
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
  };
  await probe('category', '#capture .capture-field-row .select-shell');
  await probe('template', '#capture .row.space-between .select-shell');
  // and the document adder, a labelledMenu
  await page.evaluate(() => { const b = [...document.querySelectorAll('#capture button')].find((x) => x.textContent.trim().startsWith('Add to document')); if (b) b.click(); });
  await page.waitForTimeout(450);
  say('docadder', await page.evaluate(() => {
    const opener = [...document.querySelectorAll('#capture button')].find((x) => x.textContent.trim().startsWith('Add to document'));
    const menu = [...document.querySelectorAll('.action-menu')].find((m) => !m.classList.contains('hidden'));
    if (!menu) return null;
    const mr = menu.getBoundingClientRect(); const orr = opener.getBoundingClientRect();
    return { opener: { top: +orr.top.toFixed(1), bottom: +orr.bottom.toFixed(1) }, menu: { top: +mr.top.toFixed(1), bottom: +mr.bottom.toFixed(1), h: +mr.height.toFixed(1) }, gapAboveOpener: +(orr.top - mr.bottom).toFixed(1), cls: menu.className, inline: menu.getAttribute('style') };
  }));
  await browser.close();
})();
