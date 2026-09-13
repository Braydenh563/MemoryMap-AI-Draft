// INBOX 119b reproduced: "the let the ai decide button popup is a massive gap
// above the picker". A notebook with enough categories to make the File under
// list taller than the room under its opener. Seeds notes through the API from
// the page (one per category), reloads, then opens the picker and prints the
// opener's rect, the menu's rect, the height the menu WANTS (max-height: none)
// and the height it is DRAWN at (.select-menu's own 18rem cap).
const { boot } = require('./lib.js');
const CATS = ['Hobbies', 'Courses and study', 'Work', 'Recipes', 'Travel', 'Health',
  'Money', 'Family', 'Jokes', 'Books', 'Music', 'Ideas', 'Shopping', 'Fitness'];
(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  const made = await page.evaluate(async (cats) => {
    let n = 0;
    for (const c of cats) {
      const r = await api('/entries', { method: 'POST', body: JSON.stringify({ content: `A note filed under ${c}`, category: c }) });
      if (r.ok) n += 1;
    }
    return n;
  }, CATS);
  say('seeded', made);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3500);
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); switchTab('notes'); });
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('capture'));
    if (b) b.click();
  });
  await page.waitForTimeout(600);
  // The click and the measurement in two evaluates: `place()` runs from a
  // MutationObserver, which is a microtask AFTER the calling script, so a rect
  // read in the same evaluate is the pre-placement one.
  await page.evaluate(() => document.querySelector('#capture .capture-field-row .select-shell .select-opener').click());
  await page.waitForTimeout(500);
  say('open', await page.evaluate(() => {
    const shell = document.querySelector('#capture .capture-field-row .select-shell');
    const opener = shell.querySelector('.select-opener');
    const menu = [...document.querySelectorAll('.action-menu.select-menu')].find((m) => !m.classList.contains('hidden'));
    const orr = opener.getBoundingClientRect();
    const mr = menu.getBoundingClientRect();
    const cs = getComputedStyle(menu);
    // what it wants, with every cap off, without moving it
    const inline = menu.style.maxHeight;
    menu.style.maxHeight = 'none';
    const wants = menu.getBoundingClientRect().height;
    menu.style.maxHeight = inline;
    return {
      opener: { top: +orr.top.toFixed(1), bottom: +orr.bottom.toFixed(1) },
      menu: { top: +mr.top.toFixed(1), bottom: +mr.bottom.toFixed(1), h: +mr.height.toFixed(1) },
      gapBetweenMenuBottomAndOpenerTop: +(orr.top - mr.bottom).toFixed(1),
      wants: +wants.toFixed(1), drawn: +mr.height.toFixed(1), cssMaxHeight: cs.maxHeight,
      inlineMaxHeight: menu.style.maxHeight || null, options: menu.querySelectorAll('.select-option').length,
      room: { above: +(orr.top - 12).toFixed(1), below: +(innerHeight - 8 - orr.bottom - 4).toFixed(1) },
    };
  }));
  await page.screenshot({ path: (process.env.SCRATCH||'.') + '/shots/menugap.png' });
  await browser.close();
})();
