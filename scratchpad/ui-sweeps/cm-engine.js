// DOCUMENTS_PLAN Phase 2: is the engine actually under the editor?
//
// Every line here is a number read out of the page, never a screenshot looked
// at: whether the bundle is absent from the boot request list, whether the
// view mounted, whether the CSP raised anything, and whether a keystroke in
// Source reaches the document the app saves.
//
//   BASE=http://127.0.0.1:8786 node scratchpad/ui-sweeps/cm-engine.js
const { boot } = require('./lib.js');

(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);

  // Every securitypolicyviolation from here on, collected on the page.
  await page.evaluate(() => {
    window.__csp = [];
    document.addEventListener('securitypolicyviolation', (e) =>
      window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });

  // The bundle must not be in the boot request list.
  say('bundle_at_boot', await page.evaluate(() =>
    performance.getEntriesByType('resource').filter((r) => r.name.includes('codemirror')).length));

  // Make a document and open it, which is what loads the engine.
  await page.evaluate(async () => {
    const r = await api('/documents', {
      method: 'POST',
      body: JSON.stringify({ title: 'Engine sweep', content: '' }),
    });
    const doc = await r.json();
    switchTab('documents');
    await openDocument(doc.id);
  });
  await page.waitForTimeout(2500);

  say('bundle_after_open', await page.evaluate(() =>
    performance.getEntriesByType('resource').filter((r) => r.name.includes('codemirror')).length));
  say('cm_mounted', await page.evaluate(() => Boolean(document.querySelector('#doc-editor .cm-editor'))));
  say('textarea_hidden', await page.evaluate(() => {
    const t = document.getElementById('doc-content');
    return t ? getComputedStyle(t).display : 'gone';
  }));

  // Source view, then type into the engine and read the app's own state back.
  await page.evaluate(() => setDocView('source'));
  await page.waitForTimeout(400);
  await page.click('#doc-editor .cm-content');
  await page.keyboard.type('# Heading\n\nHello teh world.');
  await page.waitForTimeout(900);
  say('surface_text', await page.evaluate(() => docSurface().text));
  say('surface_kind', await page.evaluate(() => docSurface().kind));
  say('outline_rows', await page.evaluate(() => document.querySelectorAll('#doc-outline li').length));
  say('counts', await page.evaluate(() => document.getElementById('doc-counts').textContent));
  say('caret', await page.evaluate(() => document.getElementById('doc-caret').textContent));
  say('prose_chip', await page.evaluate(() => document.getElementById('doc-prose-count').textContent));

  // Geometry: the view has a real box, and the content column is measured.
  say('cm_box', await page.evaluate(() => {
    const r = document.querySelector('#doc-editor .cm-editor').getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  }));
  say('cm_lines', await page.evaluate(() => document.querySelectorAll('#doc-editor .cm-line').length));
  say('highlight_spans', await page.evaluate(() =>
    document.querySelectorAll('#doc-editor .cm-content [class*="tok-"], #doc-editor .cm-content span[class]').length));

  // Undo: type in Live, switch to Source, Ctrl+Z gives the Live edit back.
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(500);
  await page.click('#doc-editor .cm-content');
  await page.keyboard.press('Control+End');
  await page.waitForTimeout(300);
  await page.keyboard.type('LIVEEDIT');
  await page.waitForTimeout(700);
  const withLive = await page.evaluate(() => docSurface().text);
  say('live_reached_document', withLive.includes('LIVEEDIT'));
  await page.evaluate(() => setDocView('source'));
  await page.waitForTimeout(400);
  await page.click('#doc-editor .cm-content');
  await page.keyboard.press('Control+z');
  await page.waitForTimeout(500);
  say('undo_removed_live_edit', await page.evaluate(() => !docSurface().text.includes('LIVEEDIT')));

  // Save round trip: what the server has is what the engine holds.
  await page.evaluate(() => saveDocument({ silent: true }));
  await page.waitForTimeout(900);
  say('saved_matches_engine', await page.evaluate(async () => {
    const id = currentDoc && currentDoc.id;
    if (!id) return 'no document';
    const doc = await apiJson(`/documents/${id}`);
    return doc.content === docSurface().text;
  }));

  say('csp_violations', await page.evaluate(() => window.__csp));
  say('style_tags_added', await page.evaluate(() => document.querySelectorAll('style').length));
  say('adopted_sheets', await page.evaluate(() => document.adoptedStyleSheets.length));

  await browser.close();
})();
