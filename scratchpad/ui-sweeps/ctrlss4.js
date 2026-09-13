const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => { if (typeof openSettingsModal === 'function') openSettingsModal(); });
  await page.waitForTimeout(1500);
  console.log(JSON.stringify(await page.evaluate(() => {
    const ev = { key: 's', ctrlKey: true, metaKey: false, shiftKey: false, altKey: false };
    const hits = [];
    try { for (const [id, def] of Object.entries(shortcuts)) { if (matchesShortcut(ev, def.keys)) hits.push({ id, keys: def.keys }); } } catch (e) { hits.push(String(e)); }
    return { locked: typeof notebookLocked === 'function' ? notebookLocked() : null, hits, active: document.activeElement?.id || document.activeElement?.tagName };
  }), null, 1));
  await browser.close();
})();
