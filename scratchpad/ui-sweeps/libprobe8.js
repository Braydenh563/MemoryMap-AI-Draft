// INBOX 107b item 4: clicking a Files row's name opens that file, and keeps
// opening files after a text file has been through the workspace.
const { boot, seed } = require('./libblockers.js');
const { seedPdf } = { seedPdf: null };

async function pdf(page) {
  return page.evaluate(async () => {
    const body = 'BT /F1 12 Tf 40 120 Td (Weekly review) Tj ET';
    const objs = ['<</Type/Catalog/Pages 2 0 R>>', '<</Type/Pages/Kids[3 0 R]/Count 1>>',
      '<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>',
      `<</Length ${body.length}>>\nstream\n${body}\nendstream`, '<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>'];
    let out = '%PDF-1.4\n'; const offs = [];
    objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
    const xref = out.length;
    out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
    for (const o of offs) out += String(o).padStart(10, '0') + ' 00000 n \n';
    out += `trailer\n<</Size ${objs.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
    const fd = new FormData();
    fd.append('file', new File([out], 'weekly-review.pdf', { type: 'application/pdf' }));
    fd.append('direct', 'true');
    const r = await fetch('/media/upload', { method: 'POST', body: fd,
      headers: { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId() } });
    return (await r.json()).id;
  });
}

const stage = (page) => page.evaluate(() => {
  const img = document.getElementById('ocr-image');
  return {
    file: document.getElementById('ocr-file')?.textContent || '',
    img: !!img,
    imgHidden: img ? img.classList.contains('hidden') : null,
    imgW: img ? img.naturalWidth : null,
    textView: !!document.querySelector('#ocr-stage .ocr-text-view'),
    regions: document.querySelectorAll('#ocr-region-list li').length,
    ws: !document.getElementById('ocr-workspace').classList.contains('hidden'),
  };
});

async function openByName(page, name) {
  await page.evaluate((name) => {
    const fig = [...document.querySelectorAll('#library-images-grid figure')]
      .find((f) => f.querySelector('figcaption')?.textContent.includes(name));
    fig.querySelector('figcaption').scrollIntoView({ block: 'center' });
  }, name);
  await page.waitForTimeout(200);
  const pt = await page.evaluate((name) => {
    const fig = [...document.querySelectorAll('#library-images-grid figure')]
      .find((f) => f.querySelector('figcaption')?.textContent.includes(name));
    const cap = fig.querySelector('figcaption');
    const r = document.createRange(); r.selectNodeContents(cap);
    const b = r.getBoundingClientRect();
    return { x: b.left + Math.min(30, b.width / 2), y: b.top + b.height / 2 };
  }, name);
  await page.mouse.click(pt.x, pt.y);
  await page.waitForTimeout(2500);
}

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await seed(page);
  await pdf(page);
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"]');
  await page.waitForTimeout(1800);
  await openByName(page, 'lecture_agents.md');
  console.log('1 md   ', JSON.stringify(await stage(page)));
  await page.click('#ocr-close'); await page.waitForTimeout(600);
  await openByName(page, 'weekly-review.pdf');
  console.log('2 pdf  ', JSON.stringify(await stage(page)));
  await page.click('#ocr-close'); await page.waitForTimeout(600);
  await openByName(page, 'lecture_agents.md');
  console.log('3 md   ', JSON.stringify(await stage(page)));
  await browser.close();
})();
