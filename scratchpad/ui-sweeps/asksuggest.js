// INBOX 120: "the try asking and ask again suggestions are nearly identical".
// Prints both rows of the Ask tab as rendered, with the overlap between them.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(700);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('ask'));
    if (b) b.click();
  });
  await page.waitForTimeout(1200);
  const rows = await page.evaluate(() => {
    const chips = (id) => [...document.querySelectorAll(`#${id} .chip, #${id} button`)].map((c) => c.title || c.textContent.trim()).filter(Boolean);
    return { tryAsking: chips('suggested-questions'), askAgain: chips('recent-questions') };
  });
  const overlap = rows.tryAsking.filter((q) => rows.askAgain.includes(q));
  console.log('try asking: ' + JSON.stringify(rows.tryAsking));
  console.log('ask again:  ' + JSON.stringify(rows.askAgain));
  console.log('overlap:    ' + JSON.stringify(overlap));
  await browser.close();
})();
