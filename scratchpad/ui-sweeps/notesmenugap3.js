// INBOX 119b, reproduced with the notebook size that produces it. CATS=N
// categories: the File under menu wants more than `.select-menu`'s own 18rem
// cap but less than the room above its opener, which is the only band in which
// `place()`'s flip-above branch places the menu by a height it is then not
// drawn at. Prints opener rect, menu rect, wanted height, drawn height, gap.
const { boot } = require('./lib.js');
const ALL = ['Hobbies', 'Courses and study', 'Work', 'Recipes', 'Travel', 'Health',
  'Money', 'Family', 'Jokes', 'Books', 'Music', 'Ideas', 'Shopping', 'Fitness'];
(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  const n = Number(process.env.CATS || 9);
  say('seeded', await page.evaluate(async (cats) => {
    const existing = await (await api('/entries?limit=500')).json();
    for (const e of existing) await api(`/entries/${e.id}`, { method: 'DELETE' });
    let made = 0;
    for (const c of cats) {
      const r = await api('/entries', { method: 'POST', body: JSON.stringify({ content: `A note filed under ${c}`, category: c }) });
      if (r.ok) made += 1;
    }
    return made;
  }, ALL.slice(0, n)));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3500);
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); switchTab('notes'); });
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('capture'));
    if (b) b.click();
  });
  await page.waitForTimeout(600);
  await page.evaluate(() => document.querySelector('#capture .capture-field-row .select-shell .select-opener').click());
  await page.waitForTimeout(500);
  say('open', await page.evaluate(() => {
    const opener = document.querySelector('#capture .capture-field-row .select-shell .select-opener');
    const menu = [...document.querySelectorAll('.action-menu.select-menu')].find((m) => !m.classList.contains('hidden'));
    const orr = opener.getBoundingClientRect();
    const mr = menu.getBoundingClientRect();
    const inline = menu.style.maxHeight;
    menu.style.maxHeight = 'none';
    const wants = menu.getBoundingClientRect().height;
    menu.style.maxHeight = inline;
    return {
      opener: { top: +orr.top.toFixed(1), bottom: +orr.bottom.toFixed(1) },
      menu: { top: +mr.top.toFixed(1), bottom: +mr.bottom.toFixed(1), h: +mr.height.toFixed(1) },
      gapAboveOpener: +(orr.top - mr.bottom).toFixed(1),
      wants: +wants.toFixed(1), drawn: +mr.height.toFixed(1),
      inlineMaxHeight: inline || null, cssMaxHeight: getComputedStyle(menu).maxHeight,
      options: menu.querySelectorAll('.select-option').length,
      room: { above: +(orr.top - 12).toFixed(1), below: +(innerHeight - 12 - orr.bottom).toFixed(1) },
    };
  }));
  await page.screenshot({ path: (process.env.SCRATCH||'.') + `/shots/menugap-${n}.png` });
  await browser.close();
})();
