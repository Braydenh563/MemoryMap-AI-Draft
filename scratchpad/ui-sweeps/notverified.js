// HANDOVER done-when item 5: three fixes that were reasoned, never observed.
// INBOX 75 (a kebab opens on the first click), 82 (settings rows: a select
// and a button in one row are the same height) and 91 (the chat header does
// not wrap).
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const out = {};

  // A note to hang a kebab on: a fresh profile has none.
  await page.evaluate(async () => {
    const h = { 'X-Auth-Token': localStorage.getItem('token') || '', 'Content-Type': 'application/json' };
    await fetch('/entries', { method: 'POST', headers: h,
      body: JSON.stringify({ content: 'A note with a kebab menu on its card.' }) });
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  // 75: the first click on a card's kebab must open its menu.
  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(2000);
  out.kebab = await page.evaluate(() => {
    const btn = document.querySelector('[aria-haspopup="true"].kebab, .menu-wrap [aria-haspopup="true"]');
    if (!btn) return { found: false };
    const before = btn.getAttribute('aria-expanded');
    btn.click();
    const after = btn.getAttribute('aria-expanded');
    const menu = btn.closest('.menu-wrap')?.querySelector('.action-menu')
      || document.querySelector('.action-menu:not(.hidden)');
    const open = menu ? !menu.classList.contains('hidden') && menu.getBoundingClientRect().height > 0 : false;
    if (menu) menu.classList.add('hidden');
    return { found: true, before, after, openedOnFirstClick: open };
  });

  // 82: a settings row's select and its button share a height.
  await page.evaluate(() => document.getElementById('settings-btn')?.click());
  await page.waitForTimeout(1500);
  out.settingsRows = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.settings-section .row')]
      .filter((r) => r.getBoundingClientRect().height > 0
        && r.querySelector('select, input[type="text"]') && r.querySelector('button'));
    const bad = [];
    for (const r of rows) {
      const field = r.querySelector('select, input[type="text"]').getBoundingClientRect().height;
      const btn = r.querySelector('button').getBoundingClientRect().height;
      if (Math.abs(field - btn) > 4) bad.push({ field: +field.toFixed(1), btn: +btn.toFixed(1) });
    }
    return { rowsChecked: rows.length, mismatched: bad.length, worst: bad.slice(0, 3) };
  });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(600);

  // 91: the chat header must stay on one line.
  await page.click('[data-tab="chat"]').catch(() => {});
  await page.waitForTimeout(2000);
  out.chatHeader = await page.evaluate(() => {
    const read = (sel) => {
      const head = document.querySelector(sel);
      if (!head) return null;
      const kids = [...head.children].filter((c) => c.getBoundingClientRect().height > 0);
      const tops = [...new Set(kids.map((c) => Math.round(c.getBoundingClientRect().top)))];
      return { sel, children: kids.length, distinctRows: tops.length,
               overflowsX: head.scrollWidth > head.clientWidth + 1,
               wrap: getComputedStyle(head).flexWrap };
    };
    // `.chat-headline` is the one line that must not wrap; `.dock-identity`
    // stacks a headline over a subline on purpose, so two rows there is right.
    return { found: true, headline: read('.chat-headline'), identity: read('.chat-toolbar.dock .dock-identity') };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
