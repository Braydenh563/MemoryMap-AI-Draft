// Every control on the three Notes sub-tabs, by id, with its height, so a
// "two heights" claim can name the control that breaks it rather than a set.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(600);
  for (const section of ['capture', 'writing-room', 'ask']) {
    await page.evaluate((s) => {
      const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section || '').includes(s));
      if (b) b.click();
    }, section);
    await page.waitForTimeout(500);
    say(section, await page.evaluate((s) => {
      const card = document.getElementById(s);
      const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      return [...card.querySelectorAll('button, select, input:not([type=hidden]), textarea')].filter(vis).map((c) => {
        const r = c.getBoundingClientRect();
        return { id: c.id || null, tag: c.tagName.toLowerCase(), cls: (c.className||'').toString().slice(0,34), h: +r.height.toFixed(1), w: +r.width.toFixed(1), y: +r.y.toFixed(1), t: (c.textContent||c.placeholder||'').trim().slice(0,16) };
      });
    }, section));
  }
  // The two draft columns and the space under the left one.
  say('draftcols', await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('writing-room'));
    if (b) b.click();
    const cols = [...document.querySelectorAll('#writing-room .draft-column')].map((c) => {
      const r = c.getBoundingClientRect();
      const last = c.lastElementChild.getBoundingClientRect();
      return { h: +r.height.toFixed(1), bottom: +r.bottom.toFixed(1), lastBottom: +last.bottom.toFixed(1), slack: +(r.bottom - last.bottom).toFixed(1) };
    });
    const ta = [...document.querySelectorAll('#writing-room textarea')].map((t) => ({ id: t.id, h: +t.getBoundingClientRect().height.toFixed(1) }));
    return { cols, ta };
  }));
  await browser.close();
})();
