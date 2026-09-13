const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => { if (typeof openSettingsModal === 'function') openSettingsModal(); else document.getElementById('settings-btn')?.click(); });
  await page.waitForTimeout(1800);
  const navs = await page.evaluate(() => [...document.querySelectorAll('#settings-modal [data-settings-section], #settings-nav button, .settings-nav button')].map((b) => ({ t: b.textContent.trim().slice(0, 24), sec: b.dataset.settingsSection || b.getAttribute('data-section') || '' })));
  console.log('nav:', JSON.stringify(navs.slice(0, 30)));
  const out = [];
  for (const n of navs) {
    await page.evaluate((t) => {
      const b = [...document.querySelectorAll('#settings-modal [data-settings-section], #settings-nav button, .settings-nav button')].find((x) => x.textContent.trim().slice(0, 24) === t);
      if (b) b.click();
    }, n.t);
    await page.waitForTimeout(500);
    const r = await page.evaluate(() => {
      const section = [...document.querySelectorAll('.settings-section')].find((el) => el.offsetParent !== null);
      const onScreen = (el) => el && el.offsetParent !== null && !el.disabled;
      let save = [...(section?.querySelectorAll('button[id$="-save"]') || [])].find(onScreen);
      let via = 'id';
      if (!save) { save = [...document.querySelectorAll('#settings-modal button')].find((el) => onScreen(el) && /^save\b/i.test((el.textContent || '').trim())); via = 'text'; }
      return { section: section ? section.id : null, save: save ? (save.id || save.textContent.trim().slice(0, 20)) : null, via: save ? via : null };
    });
    out.push(r);
  }
  console.log(JSON.stringify(out, null, 0));
  await browser.close();
})();
