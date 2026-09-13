// INBOX 86: the zoom readout must be visible over an open Settings modal and
// over a native <dialog>, which is a different problem (top layer).
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const r = await page.evaluate(() => {
    const hud = document.getElementById('hud');
    const z = (el) => getComputedStyle(el).zIndex;
    const overlay = document.querySelector('.modal-overlay');
    return { hudZ: z(hud), overlayZ: overlay ? z(overlay) : 'no overlay', hudParent: hud.parentElement.tagName };
  });
  // Open settings, fire the zoom shortcut, and see whether the HUD is on top.
  await page.evaluate(() => document.getElementById('settings-btn')?.click());
  await page.waitForTimeout(1200);
  await page.keyboard.down('Control');
  await page.keyboard.press('Equal');
  await page.keyboard.up('Control');
  await page.waitForTimeout(300);
  const over = await page.evaluate(() => {
    const hud = document.getElementById('hud');
    const box = hud.getBoundingClientRect();
    const cx = Math.round(box.left + box.width / 2);
    const cy = Math.round(box.top + box.height / 2);
    const top = document.elementFromPoint(cx, cy);
    return {
      hudHidden: hud.classList.contains('hidden'),
      hudText: hud.textContent,
      hudZ: getComputedStyle(hud).zIndex,
      // pointer-events is off on the HUD, so elementFromPoint reports what is
      // painted under it; the useful test is whether the modal sits ABOVE.
      topAtCentre: top ? (top.id || top.className || top.tagName) : null,
      modalOpen: !document.getElementById('settings-modal')?.classList.contains('hidden'),
    };
  });
  console.log(JSON.stringify({ before: r, withSettingsOpen: over }, null, 1));
  await browser.close();
})();
