// Does the Appearance "shadow strength" slider reach dark mode at all?
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1500);
  const read = () => page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const card = document.querySelector('section.card');
    return {
      mode: document.documentElement.getAttribute('data-mode'),
      intensity: cs.getPropertyValue('--shadow-intensity').trim(),
      sm: cs.getPropertyValue('--shadow-sm').trim().replace(/\s+/g, ' '),
      md: cs.getPropertyValue('--shadow-md').trim().replace(/\s+/g, ' '),
      lg: cs.getPropertyValue('--shadow-lg').trim().replace(/\s+/g, ' '),
      cardShadow: card ? getComputedStyle(card).boxShadow.replace(/\s+/g, ' ').slice(0, 90) : null,
    };
  });
  console.log('at 5%  ', JSON.stringify(await read()));
  await page.evaluate(() => { localStorage.setItem('shadow-intensity', '40'); if (typeof applyAppearance === 'function') applyAppearance(); });
  await page.waitForTimeout(600);
  console.log('at 40% ', JSON.stringify(await read()));
  await browser.close();
})();
