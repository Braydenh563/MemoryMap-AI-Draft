const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab('documents'));
  await page.waitForTimeout(2000);
  const out = await page.evaluate(() => {
    const path = (el) => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id; if (el.className && typeof el.className === 'string') s += '.' + el.className.trim().split(/\s+/).join('.'); return s; };
    const hits = [];
    for (const el of document.querySelectorAll('[role="tab"], .subtab, .seg > *, .segmented-control > *, [id^="tab-btn-"], .notes-subtabs *, .sub-tabs *, [class*="subtab"]')) {
      const b = el.getBoundingClientRect();
      if (b.width < 12 || b.height < 8) continue;
      const cs = getComputedStyle(el);
      if (!/^0px( 0px)*$/.test(cs.borderRadius)) continue;
      const chain = [];
      let p = el;
      for (let i = 0; i < 5 && p; i++) { chain.push(path(p) + ' r=' + getComputedStyle(p).borderRadius); p = p.parentElement; }
      hits.push({ text: el.textContent.trim().slice(0, 30), w: +b.width.toFixed(1), h: +b.height.toFixed(1), bg: cs.backgroundColor, border: cs.border, chain });
    }
    // Also: every segmented control anywhere on this tab.
    const segs = [...document.querySelectorAll('.segmented-control, .seg')].filter((s) => s.getBoundingClientRect().width > 10).map((s) => ({
      sel: path(s), r: getComputedStyle(s).borderRadius, bg: getComputedStyle(s).backgroundColor, pad: getComputedStyle(s).padding,
      kids: [...s.children].map((k) => ({ t: k.textContent.trim().slice(0, 20), r: getComputedStyle(k).borderRadius, w: +k.getBoundingClientRect().width.toFixed(1) })),
    }));
    return { hits, segs };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
