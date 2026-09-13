// The Files sub-tab row: are the title, the meta strip and the reading pill
// on the same left edge, and does the title open the OCR workspace?
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="library"]').catch(()=>{});
  await page.waitForTimeout(1200);
  // Upload one small file so the row exists on a fresh profile.
  const made = await page.evaluate(async () => {
    const h = {'X-Auth-Token': localStorage.getItem('token') || ''};
    const e = await fetch('/entries', {method:'POST', headers:{...h,'Content-Type':'application/json'},
      body: JSON.stringify({content: 'A note that carries a lecture handout.'})});
    if (!e.ok) return 'entry ' + e.status;
    const entry = await e.json();
    const fd = new FormData();
    fd.append('file', new File(['# Agents\n\nSome text extracted from this file, at length, for the row to summarise.'],
      'cab432_lecture_agents.md', {type:'text/markdown'}));
    const r = await fetch(`/entries/${entry.id}/files`, {method:'POST', body: fd, headers: h});
    return 'file ' + r.status;
  });
  await page.click('[data-media-kind="files"], [data-subtab="files"], #library-subtab-files').catch(()=>{});
  await page.waitForTimeout(2500);
  const r = await page.evaluate(() => {
    const tile = document.querySelector('.library-file-rows .library-image-tile');
    if (!tile) return { rows: document.querySelectorAll('.library-image-tile').length, gridClass: document.getElementById('library-images-grid')?.className };
    const box = (s) => { const e = tile.querySelector(s); return e ? Math.round(e.getBoundingClientRect().left) : null; };
    return {
      tileLeft: Math.round(tile.getBoundingClientRect().left),
      figcaption: box('figcaption'),
      meta: box('.library-file-meta'),
      readingPill: box('.library-file-open-reading'),
      summaryLine: box('.library-file-summary'),
      details: box('.library-image-reading'),
      captionField: box('.library-image-fields > :first-child'),
      readingSummary: box('.library-image-reading > summary'),
      caret: (() => { const e = tile.querySelector('.library-image-reading > summary');
        if (!e) return null; const cs = getComputedStyle(e, '::before');
        return { content: cs.content, marginLeft: cs.marginLeft }; })(),
    };
  });
  console.log(JSON.stringify({ upload: made, ...r }, null, 1));
  await browser.close();
})();
