const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => { if (typeof openSettingsModal === 'function') openSettingsModal(); else document.getElementById('settings-btn')?.click(); });
  await page.waitForTimeout(1500);
  await page.evaluate(() => { const b = document.querySelector("#settings-nav button[data-section=\"preferences\"]"); if (b) b.click(); });
  await page.waitForTimeout(900);
  const rest = await page.evaluate(() => { const b = document.getElementById('prefs-save'); return { cls: b.className, shadow: getComputedStyle(b).boxShadow.replace(/\s+/g, ' '), sec: [...document.querySelectorAll('.settings-section')].find((e) => e.offsetParent !== null)?.id }; });
  console.log('resting ', JSON.stringify(rest));
  await page.keyboard.press('Control+s');
  const frames = [];
  for (let i = 0; i < 5; i++) { await page.waitForTimeout(80); frames.push(await page.evaluate(() => { const el = document.querySelector('.just-saved'); return el ? { id: el.id, shadow: getComputedStyle(el).boxShadow.replace(/\s+/g, ' ').slice(0, 70) } : null; })); }
  console.log('frames  ', JSON.stringify(frames));
  await page.waitForTimeout(800);
  console.log('after   ', JSON.stringify(await page.evaluate(() => { const b = document.getElementById('prefs-save'); return { still: b.classList.contains('just-saved'), shadow: getComputedStyle(b).boxShadow.replace(/\s+/g, ' ') }; })));
  await browser.close();
})();
