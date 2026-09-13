// Does the Appearance "sheen strength" slider reach dark mode?
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1500);
  const read = () => page.evaluate(() => ({
    mode: document.documentElement.getAttribute('data-mode'),
    strength: getComputedStyle(document.documentElement).getPropertyValue('--glass-sheen-strength').trim(),
    catch_: getComputedStyle(document.documentElement).getPropertyValue('--glass-catch').trim().replace(/\s+/g, ' '),
  }));
  console.log('100%', JSON.stringify(await read()));
  await page.evaluate(() => { localStorage.setItem("glass-sheen-strength", "20"); if (typeof applyAppearance === 'function') applyAppearance(); });
  await page.waitForTimeout(500);
  console.log(' 20%', JSON.stringify(await read()));
  await browser.close();
})();
