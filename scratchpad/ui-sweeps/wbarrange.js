// The whiteboard properties panel's Arrange section: three named rows, no
// ragged wrap, and every button still reachable inside the panel's width.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="whiteboard"]').catch(() => {});
  await page.waitForTimeout(3500);
  const r = await page.evaluate(() => {
    const row = document.getElementById('wb-prop-multi-row');
    if (!row) return { missing: true };
    row.classList.remove('hidden');
    const panel = row.closest('.whiteboard-floating-panel, .wb-properties, .card') || row.parentElement;
    for (let el = row.parentElement; el && el !== document.body; el = el.parentElement) {
      el.classList.remove('hidden');
    }
    const bar = row.querySelector('.wb-arrange-toolbar');
    const buttons = [...bar.querySelectorAll('button')];
    const tops = [...new Set(buttons.map((b) => Math.round(b.getBoundingClientRect().top)))].sort((a, b) => a - b);
    const perRow = tops.map((t) => buttons.filter((b) => Math.round(b.getBoundingClientRect().top) === t).length);
    const barBox = bar.getBoundingClientRect();
    return {
      barW: Math.round(barBox.width),
      barH: Math.round(barBox.height),
      buttons: buttons.length,
      rows: tops.length,
      perRow,
      labels: [...bar.querySelectorAll('.wb-arrange-label')].map((s) => s.textContent),
      anyOverflowing: buttons.some((b) => b.getBoundingClientRect().right > barBox.right + 0.5),
      allVisible: buttons.every((b) => b.getBoundingClientRect().width > 0),
    };
  });
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
