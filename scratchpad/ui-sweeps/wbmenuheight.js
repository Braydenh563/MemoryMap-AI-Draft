// INBOX 107c: "fix the whiteboard dropdown menu heights, make sure they arent
// too short but also not clipped off the bottom".
const { boot } = require('./lib.js');
(async () => {
  const vh = Number(process.env.VH || 900);
  const { browser, page } = await boot({ viewport: { width: 1440, height: vh } });
  await page.waitForTimeout(1200);
  // Open the first seeded board.
  const opened = await page.evaluate(async () => {
    const boards = await (await api('/whiteboard/boards')).json();
    const b = boards.find((x) => x.type !== 'map') || boards[0];
    if (!b) return 'no boards';
    openWhiteboardBoard(b.id);
    return b.title;
  });
  console.log('board:', opened, 'viewport h', vh);
  await page.waitForTimeout(3000);
  for (const id of ['wb-view-menu', 'wb-arrange-menu', 'wb-board-menu', 'wb-insert-menu', 'wb-edit-menu']) {
    const res = await page.evaluate((menuId) => {
      const menu = document.getElementById(menuId);
      if (!menu) return { id: menuId, err: 'missing' };
      const wrap = menu.closest('.wb-board-menu-wrap');
      const btn = wrap && wrap.querySelector('[data-wb-menu-toggle]');
      if (btn) btn.click();
      return { id: menuId, clicked: !!btn };
    }, id);
    await page.waitForTimeout(600);
    const m = await page.evaluate((menuId) => {
      const menu = document.getElementById(menuId);
      const b = menu.getBoundingClientRect();
      const cs = getComputedStyle(menu);
      return {
        hidden: menu.classList.contains('hidden'),
        top: +b.top.toFixed(1), bottom: +b.bottom.toFixed(1), h: +b.height.toFixed(1),
        scrollHeight: menu.scrollHeight, clientHeight: menu.clientHeight,
        overflowing: menu.scrollHeight > menu.clientHeight + 1,
        maxHeight: cs.maxHeight, overflowY: cs.overflowY,
        pastBottom: +(b.bottom - innerHeight).toFixed(1),
        roomBelowTop: +(innerHeight - b.top).toFixed(1),
        vh: innerHeight,
      };
    }, id);
    console.log(id, JSON.stringify({ ...res, ...m }));
    await page.evaluate((menuId) => { const menu = document.getElementById(menuId); const wrap = menu.closest('.wb-board-menu-wrap'); const btn = wrap && wrap.querySelector('[data-wb-menu-toggle]'); if (btn) btn.click(); }, id);
    await page.waitForTimeout(300);
  }
  await browser.close();
})();
