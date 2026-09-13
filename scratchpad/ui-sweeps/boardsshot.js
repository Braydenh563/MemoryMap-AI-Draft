const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(2500);
  const el = await page.$('#dash-widget-boards, [data-widget="boards"], .dash-widget#boards');
  const target = el || await page.evaluateHandle(() => document.querySelector('.dash-widget .dash-board-thumb').closest('.dash-widget'));
  await target.asElement().scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await target.asElement().screenshot({ path: (process.env.SCRATCH || '.') + '/boards-widget.png' });
  // Sibling for comparison: the documents widget.
  const sib = await page.evaluateHandle(() => document.getElementById('documents') || document.querySelector('#documents'));
  if (sib.asElement()) await sib.asElement().screenshot({ path: (process.env.SCRATCH || '.') + '/documents-widget.png' }).catch(()=>{});
  console.log('shot');
  await browser.close();
})();
