// INBOX 107c: Ctrl+S in settings "needs visual confirmation as well".
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => { if (typeof openSettingsModal === 'function') openSettingsModal(); else document.getElementById('settings-btn')?.click(); });
  await page.waitForTimeout(1800);
  const before = await page.evaluate(() => {
    const section = [...document.querySelectorAll('.settings-section')].find((el) => el.offsetParent !== null);
    const onScreen = (el) => el && el.offsetParent !== null && !el.disabled;
    let save = [...(section?.querySelectorAll('button[id$="-save"]') || [])].find(onScreen);
    if (!save) save = [...document.querySelectorAll('#settings-modal button')].find((el) => onScreen(el) && /^save\b/i.test((el.textContent || '').trim()));
    return {
      modalOpen: typeof settingsModalOpen === 'function' ? settingsModalOpen() : null,
      section: section ? section.id : null,
      saveBtn: save ? (save.id || save.textContent.trim().slice(0, 24)) : null,
      restingShadow: save ? getComputedStyle(save).boxShadow.replace(/\s+/g, ' ').slice(0, 90) : null,
      cls: save ? save.className : null,
    };
  });
  console.log('before  ', JSON.stringify(before));
  await page.keyboard.press('Control+s');
  const frames = [];
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(90);
    frames.push(await page.evaluate(() => {
      const el = document.querySelector('.just-saved');
      return el ? { id: el.id || el.textContent.trim().slice(0, 20), shadow: getComputedStyle(el).boxShadow.replace(/\s+/g, ' ').slice(0, 80), anim: getComputedStyle(el).animationName } : null;
    }));
  }
  console.log('frames  ', JSON.stringify(frames));
  await page.waitForTimeout(900);
  const after = await page.evaluate(() => {
    const section = [...document.querySelectorAll('.settings-section')].find((el) => el.offsetParent !== null);
    const save = [...(section?.querySelectorAll('button[id$="-save"]') || [])].find((el) => el.offsetParent !== null);
    return { anyJustSaved: !!document.querySelector('.just-saved'), restored: save ? getComputedStyle(save).boxShadow.replace(/\s+/g, ' ').slice(0, 90) : null };
  });
  console.log('after   ', JSON.stringify(after));
  await browser.close();
})();
