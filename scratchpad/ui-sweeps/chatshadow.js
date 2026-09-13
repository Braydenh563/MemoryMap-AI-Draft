// INBOX 110: "in the chat tab, the main chat panel shadow actually reaches all
// the way down on the gap" / "chat panel shadow".
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('chat'));
  await page.waitForTimeout(2200);
  const snap = () => page.evaluate(() => {
    const dock = document.querySelector('.chat-dock');
    const main = document.getElementById('chat-main');
    const ae = document.activeElement;
    const r = (el) => { const b = el.getBoundingClientRect(); return { x: +b.x.toFixed(1), y: +b.y.toFixed(1), w: +b.width.toFixed(1), h: +b.height.toFixed(1), bottom: +b.bottom.toFixed(1) }; };
    const cs = (el) => { const c = getComputedStyle(el); return { shadow: c.boxShadow, border: c.borderColor, radius: c.borderRadius, bg: c.backgroundColor }; };
    return {
      active: ae ? (ae.tagName + '#' + (ae.id || '') + '.' + (typeof ae.className === 'string' ? ae.className : '')) : null,
      dockFocusWithin: dock ? dock.matches(':focus-within') : null,
      dock: dock ? { box: r(dock), ...cs(dock) } : null,
      main: main ? { box: r(main), ...cs(main) } : null,
      viewportH: innerHeight,
      mainBottomToViewport: main ? +(innerHeight - main.getBoundingClientRect().bottom).toFixed(1) : null,
      dockBottomToMainBottom: (dock && main) ? +(main.getBoundingClientRect().bottom - dock.getBoundingClientRect().bottom).toFixed(1) : null,
    };
  });
  console.log('on load :', JSON.stringify(await snap(), null, 1));
  // Click somewhere neutral to blur the composer.
  await page.evaluate(() => { const t = document.activeElement; if (t && t.blur) t.blur(); document.body.focus(); });
  await page.waitForTimeout(500);
  console.log('blurred:', JSON.stringify(await snap(), null, 1));
  await browser.close();
})();
