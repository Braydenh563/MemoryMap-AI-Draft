// Settings section heads (UI_MODERNISATION_PLAN.md Phase 8 item 8): the plan
// leaves the forms alone and asks only that a section's head row be the
// grammar's identity zone, which means a heading and no control beside it.
// This walks every Settings section, opens it, and lists each row that holds a
// heading together with whatever controls share that row.
//
//   BASE=http://127.0.0.1:8799 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node setheads.js
const { boot } = require('./lib.js');
const SECTIONS = ['account', 'appearance', 'preferences', 'models', 'tools', 'skills',
  'personas', 'templates', 'websearch', 'memory', 'tasks', 'data', 'logs', 'shortcuts',
  'extras', 'help', 'about'];
(async () => {
  const { browser, page } = await boot();
  await page.evaluate(() => document.getElementById('settings-btn')?.click());
  await page.waitForTimeout(1200);
  for (const s of SECTIONS) {
    await page.evaluate((name) => {
      const nav = document.querySelector(`#settings-nav [data-section="${name}"]`);
      if (nav) nav.click();
    }, s);
    await page.waitForTimeout(450);
    const rows = await page.evaluate((name) => {
      const sec = document.getElementById('settings-' + name);
      if (!sec || sec.classList.contains('hidden')) return 'not open';
      const vis = (e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
      return [...sec.querySelectorAll('.row, .settings-subgroup > .row')]
        .filter((r) => vis(r) && r.querySelector(':scope > h2, :scope > h3, :scope > h4'))
        .map((r) => {
          const head = r.querySelector(':scope > h2, :scope > h3, :scope > h4');
          const ctrls = [...r.querySelectorAll('button, select, input:not([type=hidden]), summary')]
            .filter((c) => vis(c) && !c.closest('.action-menu'));
          return {
            heading: head.textContent.trim().slice(0, 30),
            controls: ctrls.map((c) => (c.id || c.className.slice(0, 16)) + '='
              + Math.round(c.getBoundingClientRect().height)),
          };
        })
        .filter((r) => r.controls.length);
    }, s);
    if (rows !== 'not open' && rows.length) console.log(s, JSON.stringify(rows));
    else if (rows === 'not open') console.log(s, 'NOT OPEN');
  }
  await browser.close();
})();
