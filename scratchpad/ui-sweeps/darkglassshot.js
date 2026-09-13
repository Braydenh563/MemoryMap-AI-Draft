// A look at the dark surfaces the token work touched, so the glass change is
// not only a set of computed values.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('dashboard'));
  await page.waitForTimeout(2500);
  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/dark-dash.png', clip: { x: 0, y: 380, width: 1440, height: 320 } });
  await page.evaluate(() => switchTab('chat'));
  await page.waitForTimeout(2000);
  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/dark-chat.png', clip: { x: 300, y: 640, width: 1140, height: 240 } });
  console.log('ok', await page.evaluate(() => document.documentElement.getAttribute('data-mode')));
  await browser.close();
})();
