// The Reminders card's "Magic add" row, which shares `textarea.autogrow`'s
// `min-height: 2.75rem` with the capture box: does it still line up?
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.evaluate(() => switchTab('reminders'));
  await page.waitForTimeout(1200);
  console.log('reminders: ' + JSON.stringify(await page.evaluate(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const row = (sel) => [...document.querySelectorAll(sel)].filter(vis).map((c) => ({
      id: c.id || null, tag: c.tagName.toLowerCase(), h: +c.getBoundingClientRect().height.toFixed(1),
      y: +c.getBoundingClientRect().y.toFixed(1), t: (c.textContent || c.placeholder || '').trim().slice(0, 14),
    }));
    return { magic: row('#reminder-magic-row button, #reminder-magic-row input, #reminder-magic-row textarea, #reminder-magic-row select'),
      form: row('.reminder-form button, .reminder-form input, .reminder-form select') };
  })));
  await browser.close();
})();
