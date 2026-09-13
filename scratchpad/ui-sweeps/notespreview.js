// INBOX 119a: "when I press preview in the capture a thought formatting
// toolbar ... the top of the line numbers can still be hidden and is just a
// little dot above the text panel". Measures every child of the composer with
// preview off and on, so the "little dot" has an identity and a rect.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(500);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('capture'));
    if (b) b.click();
  });
  await page.waitForTimeout(400);
  const dump = () => page.evaluate(() => {
    const walk = (root, depth) => {
      const out = [];
      for (const el of root.children) {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        out.push({ d: depth, tag: el.tagName.toLowerCase(), id: el.id || null, cls: (el.className||'').toString().slice(0, 40),
          y: +r.y.toFixed(1), h: +r.height.toFixed(1), w: +r.width.toFixed(1),
          disp: cs.display, ov: cs.overflow, pos: cs.position, t: (el.textContent||'').trim().slice(0, 14) });
        if (depth < 2) out.push(...walk(el, depth + 1));
      }
      return out;
    };
    return walk(document.querySelector('.note-composer'), 0);
  });
  say('off', await dump());
  await page.evaluate(() => { document.getElementById('entry-content').value = 'hello **world**'; document.getElementById('entry-preview-toggle').click(); });
  await page.waitForTimeout(600);
  say('on', await dump());
  // the same toolbar in the note edit form and the documents editor
  say('toolbars', await page.evaluate(() => [...document.querySelectorAll('.doc-toolbar')].map((t) => {
    const r = t.getBoundingClientRect();
    return { id: t.id, cls: t.className, y: +r.y.toFixed(1), h: +r.height.toFixed(1), vis: r.width > 0 };
  })));
  await browser.close();
})();
