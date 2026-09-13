// Ctrl+S inside the settings modal: does the handler find a Save button?
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.evaluate(() => document.getElementById('settings-btn')?.click());
  await page.waitForTimeout(1500);
  const r = await page.evaluate(() => {
    const sections = [...document.querySelectorAll('.settings-section')];
    const visible = sections.filter((s) => !s.classList.contains('hidden'));
    const shown = sections.filter((s) => s.getBoundingClientRect().height > 0);
    const saveIds = [...document.querySelectorAll('button[id$="-save"]')]
      .map((b) => ({ id: b.id, disabled: b.disabled, visible: b.getBoundingClientRect().height > 0 }));
    return {
      sectionCount: sections.length,
      notHidden: visible.map((s) => s.id || s.className).slice(0, 4),
      renderedCount: shown.length,
      renderedIds: shown.map((s) => s.id).slice(0, 4),
      saveButtons: saveIds,
      modalOpen: !document.getElementById('settings-modal')?.classList.contains('hidden'),
    };
  });
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
