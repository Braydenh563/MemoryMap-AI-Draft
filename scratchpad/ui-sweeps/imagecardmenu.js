// Does the picture card's menu actually do what it says? (INBOX 115, the
// "and funection" half of the report.)
//
// Everything the card used to spend a row on is a row of its kebab now: open
// full size, copy the markdown reference, write a description, type the text
// in the picture, and one row per place the picture is used. A row that was
// never clicked once is the second of CLAUDE.md's four review shapes, so this
// opens the menu on a card that has uses and runs three of them for real: the
// copy (clipboard read back), a "Go to" (the tab it lands on) and the open
// (the lightbox it raises).
//
//   BASE=http://127.0.0.1:8898 SCRATCH=/tmp/mm-cards2b THEME=dark \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/imagecardmenu.js
const { boot } = require('./lib.js');

(async () => {
  const { browser, ctx, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write']);
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  let bad = 0;

  await page.evaluate(() => switchTab('library'));
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#library-subtabs button, [data-subtab]')]
      .find((e) => /image/i.test(e.textContent || e.dataset.subtab || ''));
    if (b) b.click();
  });
  await page.waitForTimeout(1500);

  // The card that is used somewhere: its menu is the one with "Go to" rows.
  const idx = await page.evaluate(() =>
    [...document.querySelectorAll('.library-image-tile')]
      .findIndex((t) => /Used in/.test(t.querySelector('.library-image-uses')?.textContent || '')));
  say('cardWithUses', idx);
  if (idx < 0) { console.log('FAIL: no card reports a use'); process.exit(1); }

  const openMenu = async () => {
    await page.evaluate((i) => {
      const t = document.querySelectorAll('.library-image-tile')[i];
      t.querySelector('.menu-wrap > button[aria-haspopup="menu"]')?.click();
    }, idx);
    await page.waitForTimeout(400);
  };
  await openMenu();
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll('.action-menu:not(.hidden) [role="menuitem"]')]
      .map((b) => (b.textContent || '').replace(/\s+/g, ' ').trim()).filter(Boolean));
  say('menuRows', rows);
  for (const want of ['Open full size', 'Copy markdown reference', 'Go to']) {
    if (!rows.some((r) => r.includes(want))) { console.log(`FAIL: no row "${want}"`); bad += 1; }
  }

  const click = async (text) => {
    await page.evaluate((t) => {
      const row = [...document.querySelectorAll('.action-menu:not(.hidden) [role="menuitem"]')]
        .find((b) => (b.textContent || '').includes(t));
      row?.click();
    }, text);
    await page.waitForTimeout(700);
  };

  await click('Copy markdown reference');
  const clip = await page.evaluate(() => navigator.clipboard.readText().catch(() => 'DENIED'));
  say('clipboard', clip);
  if (!/^!\[.+\]\(.+\)$/.test(clip)) { console.log('FAIL: clipboard is not a markdown image reference'); bad += 1; }

  await openMenu();
  const goRow = rows.find((r) => r.includes('Go to'));
  await click(goRow.slice(0, 24));
  const landed = await page.evaluate(() => ({
    tab: document.querySelector('.tab-btn.active, [data-tab].active')?.dataset?.tab
      || [...document.querySelectorAll('section')].find((s) => !s.classList.contains('hidden') && s.id)?.id,
    notesVisible: !document.getElementById('notes')?.classList.contains('hidden'),
  }));
  say('afterGoTo', landed);
  if (!landed.notesVisible) { console.log('FAIL: "Go to" did not land on the note'); bad += 1; }

  await page.evaluate(() => switchTab('library'));
  await page.waitForTimeout(600);
  await openMenu();
  await click('Open full size');
  const lightbox = await page.evaluate(() => {
    const el = document.querySelector('#lightbox, .lightbox, [data-lightbox]');
    return el ? !el.classList.contains('hidden') && el.getBoundingClientRect().height > 100 : false;
  });
  say('lightboxOpen', lightbox);
  if (!lightbox) { console.log('FAIL: "Open full size" opened nothing'); bad += 1; }

  console.log(bad ? `FAILURES: ${bad}` : 'menu clean');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
