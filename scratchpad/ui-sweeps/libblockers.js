// INBOX 107b probe: the OCR workspace reader select, the reading disclosure
// closing on scroll/poll/see-more, and the Files row title click.
const { boot } = require('./lib.js');

const LONG = Array.from({ length: 60 }, (_, i) => `Line ${i + 1}: extracted text from the handout page.`).join('\n');

async function seed(page) {
  return page.evaluate(async (long) => {
    const h = { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId() };
    const j = { ...h, 'Content-Type': 'application/json' };
    const e = await fetch('/entries', { method: 'POST', headers: j,
      body: JSON.stringify({ content: 'A note that carries a lecture handout.' }) });
    const entry = await e.json();
    const fd = new FormData();
    fd.append('file', new File(['# Agents\n\n' + long], 'lecture_agents.md', { type: 'text/markdown' }));
    const r = await fetch(`/entries/${entry.id}/files`, { method: 'POST', body: fd, headers: h });
    const att = await r.json();
    const id = (att.attachments || []).slice(-1)[0]?.id ?? att.id;
    const codes = {};
    for (const kind of ['ocr', 'vision']) {
      const res = await fetch(`/files/${id}/analyse`, { method: 'POST', headers: j,
        body: JSON.stringify({ kind, text: long }) });
      codes['file-' + kind] = res.status;
    }
    const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
    const bin = Uint8Array.from(atob(png), (c) => c.charCodeAt(0));
    const fd2 = new FormData();
    fd2.append('file', new File([bin], 'sweep-shot.png', { type: 'image/png' }));
    fd2.append('direct', 'true');
    const m = await fetch('/media/upload', { method: 'POST', body: fd2, headers: h });
    const media = await m.json();
    const mid = media.id ?? media.upload?.id;
    if (mid) {
      for (const [path, kind] of [['ocr', 'ocr'], ['vision-ocr', 'vision']]) {
        const res = await fetch(`/media/${mid}/${path}`, { method: 'POST', headers: j,
          body: JSON.stringify({ text: long }) });
        codes['media-' + kind] = res.status;
      }
    }
    return { attachment: id, media: mid, codes };
  }, LONG);
}
module.exports = { seed, boot, LONG };

if (require.main === module) (async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  console.log('seed', JSON.stringify(await seed(page)));
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(1200);
  const shape = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('[data-media-kind],[data-library-sub],[data-lib-sub]')]
      .map(b => b.tagName + '#' + b.id + '.' + b.className + '|' + JSON.stringify(b.dataset));
    return { btns: btns.slice(0, 12) };
  });
  console.log(JSON.stringify(shape, null, 1));
  await browser.close();
})();
