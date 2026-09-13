// The three Notes sub-tabs as they stand: Capture, Write with AI, Ask.
//
// The owner: "redesign and give each of the capture, write with ai, and ask
// tabs a new and improved look", after "fix the add to document combobox not
// changing". This measures the shape of each so the brief starts at numbers:
// the card box, every row of controls with its height and count, the biggest
// and smallest control on the page, and the type sizes in play.
//
//   BASE=http://127.0.0.1:8871 SCRATCH=/tmp/mm-orch THEME=dark \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/notessubtabs.js
const { boot } = require('./lib.js');

(async () => {
  const { browser, page, OUT } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(800);
  say('subtabs', await page.evaluate(() => [...document.querySelectorAll('#notes-subtabs button')].map((b) => ({
    text: b.textContent.trim(), section: b.dataset.section || b.dataset.subtab || b.getAttribute('aria-controls'),
  }))));

  for (const section of ['capture', 'writing-room', 'ask']) {
    await page.evaluate((s) => {
      const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section || x.getAttribute('aria-controls') || '').includes(s));
      if (b) b.click();
    }, section);
    await page.waitForTimeout(700);
    const shape = await page.evaluate((s) => {
      const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      // The section's card: the first visible .card inside #tab-notes whose id or class names the section.
      const cards = [...document.querySelectorAll('#tab-notes section.card, #tab-notes .card')].filter(visible);
      const card = cards.find((c) => (c.id + ' ' + c.className).includes(s)) || cards[0];
      if (!card) return { section: s, card: null };
      const cr = card.getBoundingClientRect();
      const controls = [...card.querySelectorAll('button, select, input:not([type=hidden]), textarea')].filter(visible);
      const rows = new Map();
      for (const c of controls) {
        const r = c.getBoundingClientRect();
        const key = Math.round(r.y / 6) * 6;
        if (!rows.has(key)) rows.set(key, []);
        rows.get(key).push({ tag: c.tagName.toLowerCase(), id: c.id || null, cls: (c.className || '').toString().slice(0, 40), h: +r.height.toFixed(1), w: +r.width.toFixed(1), text: (c.textContent || c.placeholder || '').trim().slice(0, 18) });
      }
      const heights = controls.map((c) => +c.getBoundingClientRect().height.toFixed(1));
      const fonts = new Set(controls.map((c) => getComputedStyle(c).fontSize));
      const labels = [...card.querySelectorAll('label, h2, h3, .capture-field-label')].filter(visible).map((l) => ({ tag: l.tagName.toLowerCase(), text: l.textContent.trim().slice(0, 24), font: getComputedStyle(l).fontSize, colour: getComputedStyle(l).color }));
      return {
        section: s, cardId: card.id, cardCls: card.className,
        card: { y: +cr.y.toFixed(1), h: +cr.height.toFixed(1), w: +cr.width.toFixed(1), pad: getComputedStyle(card).padding },
        controls: controls.length, rows: rows.size,
        rowList: [...rows.entries()].sort((a, b) => a[0] - b[0]).map(([y, items]) => ({ y, n: items.length, hs: [...new Set(items.map((i) => i.h))], items: items.map((i) => i.text || i.id || i.tag) })),
        heightSet: [...new Set(heights)].sort((a, b) => a - b),
        fontSet: [...fonts],
        labels,
        scroll: { page: document.documentElement.scrollHeight, view: innerHeight },
      };
    }, section);
    say(section, shape);
    await page.screenshot({ path: `${OUT}/notes-${section}.png`, fullPage: false });
  }
  await browser.close();
})();
