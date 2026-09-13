// Ctrl+S on the Notes tab still saves the note, and on Documents the document.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(1500);
  console.log('capture visible:', JSON.stringify(await page.evaluate(() => {
    const b = document.getElementById('save-btn');
    return { onScreen: b.offsetParent !== null, disabled: b.disabled };
  })));
  const before = await page.evaluate(async () => (await (await api('/entries')).json()).length);
  await page.evaluate(() => { const t = document.getElementById('entry-content'); t.value = 'A note saved with the keyboard.'; t.dispatchEvent(new Event('input', { bubbles: true })); t.focus(); });
  await page.keyboard.press('Control+s');
  await page.waitForTimeout(1500);
  const after = await page.evaluate(async () => (await (await api('/entries')).json()).length);
  console.log('entries before/after:', before, after, after === before + 1 ? 'SAVED' : 'NOT SAVED');
  // Empty composer
  await page.keyboard.press('Control+s');
  await page.waitForTimeout(500);
  console.log('empty toast:', JSON.stringify(await page.evaluate(() => (document.querySelector('#toast, .toast')?.textContent || '').trim().slice(0, 60))));
  await browser.close();
})();
