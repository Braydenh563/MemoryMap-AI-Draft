const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  page.on('console', (m) => { if (/toast|save/i.test(m.text())) console.log('C:', m.text().slice(0, 120)); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => { if (typeof openSettingsModal === 'function') openSettingsModal(); else document.getElementById('settings-btn')?.click(); });
  await page.waitForTimeout(1800);
  console.log('nav active:', JSON.stringify(await page.evaluate(() => {
    const a = document.querySelector('#settings-nav button.active');
    return { found: !!a, txt: a ? a.textContent.trim().slice(0, 20) : null, cls: a ? a.className : null, vis: a ? a.offsetParent !== null : null };
  })));
  await page.keyboard.press('Control+s');
  await page.waitForTimeout(120);
  console.log('after press:', JSON.stringify(await page.evaluate(() => {
    const a = document.querySelector('#settings-nav button.active');
    return {
      justSaved: a ? a.classList.contains('just-saved') : null,
      anim: a ? getComputedStyle(a).animationName : null,
      shadow: a ? getComputedStyle(a).boxShadow.replace(/\s+/g, ' ').slice(0, 90) : null,
      rest: a ? a.style.getPropertyValue('--just-saved-rest') : null,
      toastTxt: (document.querySelector('#toast, .toast')?.textContent || '').trim().slice(0, 80),
    };
  })));
  await page.waitForTimeout(700);
  console.log('settled   :', JSON.stringify(await page.evaluate(() => {
    const a = document.querySelector('#settings-nav button.active');
    return { justSaved: a.classList.contains('just-saved'), shadow: getComputedStyle(a).boxShadow.replace(/\s+/g, ' ').slice(0, 60), rest: a.style.getPropertyValue('--just-saved-rest') };
  })));
  await browser.close();
})();
