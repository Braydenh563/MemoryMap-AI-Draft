// The Ask card's vertical rhythm against the two panels beside it: every block
// in the card with its y, height and the gap above it, plus the two chip rows'
// own labels, so "the same rhythm" is a set of numbers rather than a feeling.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(700);
  for (const section of ['capture', 'writing-room', 'ask']) {
    await page.evaluate((s) => {
      const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes(s));
      if (b) b.click();
    }, section);
    await page.waitForTimeout(500);
    say(section, await page.evaluate((s) => {
      const card = document.getElementById(s);
      const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      let last = null;
      const out = [];
      for (const el of card.children) {
        if (!vis(el)) continue;
        const r = el.getBoundingClientRect();
        out.push({ tag: el.tagName.toLowerCase(), id: el.id || null, cls: (el.className||'').toString().slice(0, 26),
          y: +r.y.toFixed(1), h: +r.height.toFixed(1), gapAbove: last === null ? null : +(r.y - last).toFixed(1) });
        last = r.bottom;
      }
      const label = (sel) => { const e = document.querySelector(sel); if (!e) return null; const cs = getComputedStyle(e);
        return { text: e.textContent.trim().slice(0, 14), size: cs.fontSize, colour: cs.color, weight: cs.fontWeight }; };
      return { blocks: out, chipLabels: [label('#suggested-questions .muted'), label('#recent-questions .muted')],
        captureLabel: label('.capture-field-label') };
    }, section));
  }
  await browser.close();
})();
