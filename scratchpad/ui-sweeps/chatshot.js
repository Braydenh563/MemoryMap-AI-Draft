const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('chat'));
  await page.waitForTimeout(2500);
  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/chat-load.png', clip: { x: 300, y: 640, width: 1140, height: 260 } });
  await page.evaluate(() => { document.activeElement.blur(); });
  await page.waitForTimeout(400);
  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/chat-blur.png', clip: { x: 300, y: 640, width: 1140, height: 260 } });
  console.log('ok');
  await browser.close();
})();
