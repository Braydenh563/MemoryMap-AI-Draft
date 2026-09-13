// The History sheet against a log that has been compacted (Brief 7 item 1):
// a row whose text is no longer kept has to say so, not render blank.
const { boot } = require('./lib.js');

(async () => {
  const { browser, page } = await boot();
  const id = await page.evaluate(async () => (await apiJson('/entries'))[0].id);
  await page.evaluate(async (noteId) => {
    const note = await apiJson(`/entries/${noteId}`);
    await openEntryHistory(note);
  }, id);
  await page.waitForTimeout(1500);
  const seen = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#history-list .history-entry')];
    return {
      rows: rows.length,
      texts: rows.map((r) => [...r.querySelectorAll('p')].map((p) => p.textContent.trim().slice(0, 60))),
    };
  });
  console.log('rows:', seen.rows);
  console.log('first three:', JSON.stringify(seen.texts.slice(0, 3)));
  console.log('last three:', JSON.stringify(seen.texts.slice(-3)));
  await browser.close();
})();
