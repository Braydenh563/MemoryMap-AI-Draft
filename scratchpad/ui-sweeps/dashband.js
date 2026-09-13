// INBOX 107c "the dashboard band": what sits between the hero and the widgets.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('dashboard'));
  await page.waitForTimeout(2500);
  const out = await page.evaluate(() => {
    const page_ = document.getElementById('tab-dashboard');
    const kids = [...page_.children].filter((el) => el.offsetParent !== null || el.getBoundingClientRect().height > 0);
    return kids.map((el) => {
      const b = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {
        sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : ''),
        y: Math.round(b.y), h: Math.round(b.height),
        bg: cs.backgroundColor, radius: cs.borderRadius, border: cs.borderTopWidth + ' ' + cs.borderTopStyle,
        pad: cs.padding, margin: cs.margin,
        kids: [...el.children].slice(0, 6).map((k) => (k.id || k.className || k.tagName).toString().slice(0, 40)),
      };
    });
  });
  console.log(JSON.stringify(out, null, 1));
  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/dashtop.png', clip: { x: 0, y: 60, width: 1440, height: 620 } });
  await browser.close();
})();
