// INBOX 75, the last unmeasured part of HANDOVER done-when item 5: a card's
// kebab must open on the first click, not the second.
//
// The earlier attempt looked for `[aria-haspopup]` and found nothing. The
// recipe is `kebabMenu()` in app.js: a `.menu-wrap` holding a `.action-menu`
// and a `smallButton` opener, so the wrap is what to look for.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  // A note to hang a kebab on.
  await page.evaluate(async () => {
    await api('/entries', { method: 'POST', body: JSON.stringify({ content: 'A note whose kebab is under test.' }) });
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(2000);

  const found = await page.evaluate(() => {
    const wraps = [...document.querySelectorAll('.menu-wrap')]
      .filter((w) => w.getBoundingClientRect().width > 0 && w.querySelector('.action-menu'));
    return { wraps: wraps.length, first: wraps[0] ? wraps[0].className : null };
  });
  if (!found.wraps) { console.log(JSON.stringify({ found })); await browser.close(); return; }

  // Click the opener once and read whether its menu is on screen.
  const after1 = await page.evaluate(() => {
    const wrap = [...document.querySelectorAll('.menu-wrap')]
      .find((w) => w.getBoundingClientRect().width > 0 && w.querySelector('.action-menu'));
    const opener = wrap.querySelector('button');
    opener.click();
    return null;
  });
  await page.waitForTimeout(400);
  const state1 = await page.evaluate(() => {
    // The menu may have been reparented to <body> while open (action-menu-escaped).
    const menus = [...document.querySelectorAll('.action-menu')]
      .filter((m) => !m.classList.contains('hidden') && m.getBoundingClientRect().height > 0);
    return { openMenus: menus.length, height: menus[0] ? Math.round(menus[0].getBoundingClientRect().height) : 0 };
  });
  // And a second click, which must close it rather than being the one that opens it.
  await page.evaluate(() => {
    const wrap = [...document.querySelectorAll('.menu-wrap')]
      .find((w) => w.getBoundingClientRect().width > 0 && w.querySelector('.action-menu'));
    wrap.querySelector('button').click();
  });
  await page.waitForTimeout(400);
  const state2 = await page.evaluate(() => ({
    openMenus: [...document.querySelectorAll('.action-menu')]
      .filter((m) => !m.classList.contains('hidden') && m.getBoundingClientRect().height > 0).length,
  }));
  console.log(JSON.stringify({
    found,
    openedOnFirstClick: state1.openMenus > 0,
    firstClick: state1,
    closedOnSecondClick: state2.openMenus === 0,
    secondClick: state2,
  }, null, 1));
  await browser.close();
})();
