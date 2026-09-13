// The capture composer's own rules against the box they were written for.
// `mountGutterFor` wraps the textarea in a `.gutter-wrap`, so every
// `.note-composer > …` rule stopped matching it: this prints what the box
// actually computes to.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('capture'));
    if (b) b.click();
  });
  await page.waitForTimeout(400);
  console.log('composer: ' + JSON.stringify(await page.evaluate(() => {
    const box = document.getElementById('entry-content');
    const title = document.getElementById('entry-title');
    const shell = document.querySelector('.note-composer');
    const read = (el) => { const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
      return { h: +r.height.toFixed(1), minH: cs.minHeight, border: cs.borderTopWidth + ' ' + cs.borderTopStyle,
        radius: cs.borderTopLeftRadius, bg: cs.backgroundColor, shadow: cs.boxShadow === 'none' ? 'none' : 'inset', parent: el.parentElement.className.slice(0, 20) }; };
    return { box: read(box), title: read(title), shell: { h: +shell.getBoundingClientRect().height.toFixed(1) } };
  })));
  await browser.close();
})();
