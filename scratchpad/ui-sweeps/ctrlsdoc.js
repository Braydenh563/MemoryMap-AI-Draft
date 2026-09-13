const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const calls = [];
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('documents'));
  await page.waitForTimeout(2000);
  await page.evaluate(() => {
    window.__saveDocCalled = 0;
    const orig = window.saveDocument;
    window.saveDocument = function (...a) { window.__saveDocCalled++; return orig.apply(this, a); };
  });
  await page.keyboard.press('Control+s');
  await page.waitForTimeout(900);
  console.log('documents:', JSON.stringify(await page.evaluate(() => ({
    hidden: document.getElementById('tab-documents').classList.contains('hidden'),
    saveDocCalls: window.__saveDocCalled,
    toast: (document.querySelector('#toast, .toast')?.textContent || '').trim().slice(0, 60),
  }))));
  await browser.close();
})();
