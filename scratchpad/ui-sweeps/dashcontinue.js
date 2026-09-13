const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('dashboard'));
  await page.waitForTimeout(2500);
  const out = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button, a')].find((b) => b.classList.contains("quick-link-continue"));
    if (!btn) return 'missing';
    const bb = btn.getBoundingClientRect();
    const cs = getComputedStyle(btn);
    return {
      box: { w: +bb.width.toFixed(1), h: +bb.height.toFixed(1) },
      justify: cs.justifyContent, align: cs.alignItems, display: cs.display, overflow: cs.overflow, cls: btn.className,
      kids: [...btn.children].map((k) => {
        const b = k.getBoundingClientRect();
        const kc = getComputedStyle(k);
        return { tag: k.tagName, cls: k.className, t: k.textContent.trim().slice(0, 40), w: +b.width.toFixed(1), h: +b.height.toFixed(1), display: kc.display, vis: kc.visibility, fs: kc.fontSize, color: kc.color, clip: kc.webkitLineClamp };
      }),
    };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
