// INBOX 107b item 4: does a click on the file name in a Files row open the
// file? Every variant the owner can reach: an attachment, a PDF upload, the
// preview view and the type view, clicked on the glyphs of the name itself.
const { boot, seed } = require('./libblockers.js');

async function seedPdf(page) {
  return page.evaluate(async () => {
    const body = 'BT /F1 12 Tf 40 120 Td (Weekly review) Tj ET';
    const objs = ['<</Type/Catalog/Pages 2 0 R>>', '<</Type/Pages/Kids[3 0 R]/Count 1>>',
      '<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>',
      `<</Length ${body.length}>>\nstream\n${body}\nendstream`, '<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>'];
    let pdf = '%PDF-1.4\n'; const offsets = [];
    objs.forEach((o, i) => { offsets.push(pdf.length); pdf += `${i + 1} 0 obj\n${o}\nendobj\n`; });
    const xref = pdf.length;
    pdf += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
    for (const off of offsets) pdf += String(off).padStart(10, '0') + ' 00000 n \n';
    pdf += `trailer\n<</Size ${objs.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
    const fd = new FormData();
    fd.append('file', new File([pdf], 'weekly-review.pdf', { type: 'application/pdf' }));
    fd.append('direct', 'true');
    const r = await fetch('/media/upload', { method: 'POST', body: fd,
      headers: { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId() } });
    return (await r.json()).id;
  });
}

async function tryRow(page, nameMatch, label) {
  const info = await page.evaluate((nameMatch) => {
    const figs = [...document.querySelectorAll('#library-images-grid figure')];
    const fig = figs.find((f) => f.querySelector('figcaption')?.textContent.includes(nameMatch));
    if (!fig) return { err: 'no row for ' + nameMatch, names: figs.map((f) => f.querySelector('figcaption')?.textContent) };
    const cap = fig.querySelector('figcaption');
    // The glyphs of the name, not the middle of a 1200px box: a range around
    // the text is where a reader actually clicks.
    const range = document.createRange();
    range.selectNodeContents(cap);
    const r = range.getBoundingClientRect().width ? range.getBoundingClientRect() : cap.getBoundingClientRect();
    const x = r.left + Math.min(30, r.width / 2), y = r.top + r.height / 2;
    const top = document.elementFromPoint(x, y);
    document.getElementById('ocr-workspace').classList.add('hidden');
    document.querySelector('.lightbox')?.remove();
    return { x, y, topTag: top && top.tagName + '.' + (top.className || ''), capText: cap.textContent.slice(0, 30),
      w: Math.round(r.width), h: Math.round(r.height) };
  }, nameMatch);
  if (info.err) { console.log(label, JSON.stringify(info)); return; }
  await page.mouse.click(info.x, info.y);
  await page.waitForTimeout(2200);
  const after = await page.evaluate(() => ({
    ws: !document.getElementById('ocr-workspace').classList.contains('hidden'),
    lb: !!document.querySelector('.lightbox'),
    file: document.getElementById('ocr-file')?.textContent || '',
  }));
  console.log(label, JSON.stringify({ ...info, ...after }));
  // Close whatever opened, with the app's own controls, before the next try.
  if (after.ws) { await page.click('#ocr-close'); await page.waitForTimeout(600); }
  if (after.lb) { await page.keyboard.press('Escape'); await page.waitForTimeout(600); }
}

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await seed(page);
  await seedPdf(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1800);
  await tryRow(page, 'lecture_agents.md', 'attachment/preview');
  await tryRow(page, 'weekly-review.pdf', 'pdf/preview      ');
  // the other file view
  await page.click('#library-media-view-type');
  await page.waitForTimeout(1200);
  await tryRow(page, 'lecture_agents.md', 'attachment/type   ');
  await tryRow(page, 'weekly-review.pdf', 'pdf/type          ');
  // and an image row on the Images tab, which must still go to the lightbox
  await page.click('[data-media-kind="images"]');
  await page.waitForTimeout(1500);
  await tryRow(page, 'sweep-shot.png', 'image/lightbox    ');
  await browser.close();
})();
