// Brief 7 item 6 (events-history-page): the History sheet has to page, and
// has to say what it is showing. Seeds one note with more edits than one
// page holds, opens the sheet, measures the first page, presses "Load older
// changes" and measures again.
const { boot } = require('./lib.js');

(async () => {
  const { browser, page } = await boot();
  const id = await page.evaluate(async () => {
    // The app's own helper, so the auth token and the space header the
    // server requires come along without this script knowing about either.
    const made = await apiJson('/entries', {
      method: 'POST',
      body: JSON.stringify({ content: 'edit 0', tags: [] }),
    });
    for (let i = 1; i < 60; i += 1) {
      await apiJson(`/entries/${made.id}`, {
        method: 'PUT',
        body: JSON.stringify({ content: `edit ${i}` }),
      });
    }
    return made.id;
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  // The kebab item that opens this sheet is not what is under test and its
  // button only exists once the card is hovered, so the sheet is opened the
  // way the item opens it, with the note the list already holds.
  await page.evaluate(async (noteId) => {
    const note = await apiJson(`/entries/${noteId}`);
    await openEntryHistory(note);
  }, id);
  await page.waitForTimeout(1500);

  const read = () => page.evaluate(() => {
    const list = document.getElementById('history-list');
    const rows = [...list.querySelectorAll('.history-entry')];
    const last = rows[rows.length - 1];
    return {
      rows: rows.length,
      note: (last.querySelector('p.muted') || {}).textContent || '',
      button: [...last.querySelectorAll('button')].map((b) => b.textContent.trim()),
      lastHidden: last.classList.contains('hidden'),
      overflowing: list.scrollHeight > list.clientHeight,
    };
  });

  console.log('first page:', JSON.stringify(await read()));
  await page.click('#history-list button:has-text("Load older changes")');
  await page.waitForTimeout(1200);
  console.log('after load:', JSON.stringify(await read()));
  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/history-paged.png', fullPage: false });
  await browser.close();
})();
