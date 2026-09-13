// INBOX 107b measurement probe. Numbers only.
const { boot, seed } = require('./libblockers.js');

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await seed(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1500);

  // --- item 4: the file name header ---
  const capInfo = await page.evaluate(() => {
    const fig = document.querySelector('#library-images-grid figure');
    if (!fig) return { err: 'no figure' };
    const cap = fig.querySelector('figcaption');
    const r = cap.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return {
      figClass: fig.className, capClass: cap.className, text: cap.textContent.slice(0, 40),
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      pe: getComputedStyle(cap).pointerEvents,
      topTag: top && top.tagName + '.' + top.className,
      isCap: top === cap || cap.contains(top),
    };
  });
  console.log('cap', JSON.stringify(capInfo));

  let wsBefore = await page.evaluate(() => document.getElementById('ocr-workspace').className);
  await page.click('#library-images-grid figure figcaption').catch(e => console.log('clickerr', e.message.slice(0, 80)));
  await page.waitForTimeout(2500);
  const wsAfter = await page.evaluate(() => {
    const w = document.getElementById('ocr-workspace');
    const r = w.getBoundingClientRect();
    return { cls: w.className, h: Math.round(r.height), lightbox: document.getElementById('lightbox')?.className };
  });
  console.log('workspace before/after', wsBefore, JSON.stringify(wsAfter));

  // --- item 1: the reader select ---
  const sel = await page.evaluate(() => {
    const s = document.getElementById('ocr-reader');
    if (!s) return { err: 'no select' };
    const shell = s.closest('.select-shell');
    const opener = shell?.querySelector('.select-opener');
    const menu = shell?.querySelector('.select-menu');
    const or = opener?.getBoundingClientRect();
    return {
      shell: !!shell, opener: !!opener, menu: !!menu,
      enhanced: s.hasAttribute('data-enhanced-select'),
      shellCls: shell?.className, selCls: s.className, selHidden: s.hidden,
      openerRect: or && [Math.round(or.x), Math.round(or.y), Math.round(or.width), Math.round(or.height)],
      topAtOpener: or && (() => { const t = document.elementFromPoint(or.x + or.width / 2, or.y + or.height / 2); return t.tagName + '.' + t.className; })(),
      opts: s.options.length,
    };
  });
  console.log('select', JSON.stringify(sel));

  if (sel.opener) {
    await page.click('#ocr-reader ~ .select-opener, .select-shell:has(#ocr-reader) .select-opener').catch(e => console.log('openerr', e.message.slice(0, 100)));
    await page.waitForTimeout(600);
    const menuState = await page.evaluate(() => {
      const s = document.getElementById('ocr-reader');
      const opener = s.closest('.select-shell')?.querySelector('.select-opener');
      const menu = document.querySelector('.select-menu:not(.hidden)') ||
        s.closest('.select-shell')?.querySelector('.select-menu');
      if (!menu) return { err: 'no menu' };
      const r = menu.getBoundingClientRect();
      const cs = getComputedStyle(menu);
      const t = document.elementFromPoint(r.x + r.width / 2, r.y + Math.min(20, r.height / 2));
      return {
        hidden: menu.classList.contains('hidden'), cls: menu.className,
        parent: menu.parentElement.tagName + '#' + menu.parentElement.id,
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
        z: cs.zIndex, pos: cs.position, vis: cs.visibility, disp: cs.display, op: cs.opacity,
        aria: opener.getAttribute('aria-expanded'),
        rows: menu.querySelectorAll('[role=option]').length,
        topAtMenu: t && t.tagName + '.' + (t.className || '') + '#' + (t.id || ''),
      };
    });
    console.log('menu', JSON.stringify(menuState));
  }
  await browser.close();
})();
