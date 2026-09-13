// INBOX 119a across all three surfaces that carry the formatting toolbar: the
// capture composer, the note edit form and the documents editor. Line numbers
// on, then Preview (the editor's Rendered view), and what is left of the
// gutter above the panel that replaced the box it numbered.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  const rect = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return { y: +r.y.toFixed(1), h: +r.height.toFixed(1), w: +r.width.toFixed(1), disp: cs.display }; };
  await page.evaluate(() => switchTab('notes'));
  await page.waitForTimeout(700);

  // 1. the capture composer
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('capture'));
    if (b) b.click();
  });
  await page.waitForTimeout(400);
  await page.evaluate(() => {
    document.getElementById('entry-content').value = 'line one\nline two\nline three';
    const g = document.querySelector('#note-toolbar .doc-toolbar-gutter');
    if (g && document.querySelector('#capture .doc-gutter.hidden')) g.click();
  });
  await page.waitForTimeout(400);
  await page.evaluate(() => document.getElementById('entry-preview-toggle').click());
  await page.waitForTimeout(500);
  say('capture', await page.evaluate((r) => {
    const f = new Function('el', 'return (' + r + ')(el)');
    const g = document.querySelector('#capture .doc-gutter');
    return { gutter: g ? f(g) : null, preview: f(document.getElementById('entry-preview')) };
  }, rect.toString()));

  // And back: the numbers must return with the box they number.
  await page.evaluate(() => document.getElementById('entry-preview-toggle').click());
  await page.waitForTimeout(400);
  say('capture-back', await page.evaluate((r) => {
    const f = new Function('el', 'return (' + r + ')(el)');
    const g = document.querySelector('#capture .doc-gutter');
    const ta = document.getElementById('entry-content');
    return { gutter: g ? f(g) : null, box: f(ta) };
  }, rect.toString()));

  // Back out of Capture's preview before the next surface: the edit form's
  // strip is a *clone* of this one, so a Preview button left pressed here is
  // cloned pressed and the form's first click then turns it off.
  // (already back in the box: the click above left it there)

  // 2. the note edit form: open the first note for editing
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#notes-subtabs button')].find((x) => (x.dataset.section||'').includes('browse'));
    if (b) b.click();
  });
  await page.waitForTimeout(700);
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('#entry-list button')].find((b) => (b.title || '') === 'Edit this entry');
    if (btn) btn.click();
  });
  await page.waitForTimeout(1200);
  say('noteedit-before-preview', await page.evaluate((r) => {
    const f = new Function('el', 'return (' + r + ')(el)');
    const g = document.querySelector('#entry-list .doc-gutter');
    const ta = document.querySelector('#entry-list .gutter-wrap > textarea');
    return { gutter: g ? f(g) : null, box: ta ? f(ta) : null, hasWrap: !!document.querySelector('#entry-list .gutter-wrap') };
  }, rect.toString()));
  await page.evaluate(() => {
    const btn = document.querySelector('#entry-list [data-note-preview]');
    if (btn) btn.click();
  });
  await page.waitForTimeout(500);
  say('noteedit-preview', await page.evaluate((r) => {
    const f = new Function('el', 'return (' + r + ')(el)');
    const g = document.querySelector('#entry-list .doc-gutter');
    const pv = document.querySelector('#entry-list .note-edit-preview');
    const ta = document.querySelector('#entry-list .gutter-wrap > textarea');
    const btn = document.querySelector('#entry-list [data-note-preview]');
    return { gutter: g ? f(g) : null, preview: pv ? f(pv) : null, box: ta ? f(ta) : null,
      pressed: btn ? btn.getAttribute('aria-pressed') : null, boxCls: ta ? ta.className : null,
      forms: document.querySelectorAll('#entry-list .note-edit-preview').length };
  }, rect.toString()));

  // 3. the documents editor, rendered view
  await page.evaluate(() => switchTab('documents'));
  await page.waitForTimeout(1500);
  say('documents', await page.evaluate((r) => {
    const f = new Function('el', 'return (' + r + ')(el)');
    const g = document.getElementById('doc-gutter');
    const wrap = document.getElementById('doc-source-wrap');
    return { gutter: g ? f(g) : null, wrap: wrap ? f(wrap) : null, wrapCls: wrap ? wrap.className : null };
  }, rect.toString()));
  await browser.close();
})();
