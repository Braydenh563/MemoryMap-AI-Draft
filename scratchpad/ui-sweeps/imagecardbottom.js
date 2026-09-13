// What the bottom of a Library image card is, with every field filled.
//
// The owner, with a screenshot of six cards: "the bottom of the image cards
// in the library images subsaection needs a desperate redesign and funection".
// The screenshot shows, under each thumbnail: a "Used in" chip, a wrapped
// description, a "More" button, a "Text in this image" fold, and a two-line
// "Described by <model> · read by <model>" footer.
//
// Everything below is seeded through the app's own API (`/media/upload`, then
// `/caption`, `/ocr` and `/vision-ocr` with a `text`, which is the by-hand
// path, no model involved), so the card is measured with the fields a real
// card would have rather than empty.
//
//   BASE=http://127.0.0.1:8871 SCRATCH=/tmp/mm-orch \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/imagecardbottom.js
const { boot } = require('./lib.js');

const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8DAwMDAxMDAwAAADwEBAAyEAvUAAAAASUVORK5CYII=';
const CAPTION = 'A whiteboard photographed at an angle, covered in boxes and arrows sketched in blue marker, with a laptop and two coffee cups on the table below it.';
const OCR = 'INGEST -> PARSE -> STORE\nnightly batch?\nask Priya about the retry budget';

(async () => {
  const { browser, page, OUT } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);

  const seeded = await page.evaluate(async ({ b64, caption, ocr }) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const ids = [];
    for (const name of ['board-photo.png', 'lecture-slide.png', 'receipt-scan.png']) {
      const fd = new FormData();
      fd.append('file', new File([bytes], name, { type: 'image/png' }));
      fd.append('direct', 'true');
      const r = await fetch('/media/upload', {
        method: 'POST', body: fd,
        headers: { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId() },
      });
      const j = await r.json();
      ids.push({ id: j.id, url: j.url });
    }
    // Fill every field on the first card, half of them on the second, none on
    // the third: the three states the gallery actually renders.
    await api(`/media/${ids[0].id}/caption`, { method: 'POST', body: JSON.stringify({ text: caption }) });
    await api(`/media/${ids[0].id}/ocr`, { method: 'POST', body: JSON.stringify({ text: ocr }) });
    await api(`/media/${ids[0].id}/vision-ocr`, { method: 'POST', body: JSON.stringify({ text: ocr }) });
    await api(`/media/${ids[1].id}/caption`, { method: 'POST', body: JSON.stringify({ text: 'A slide with a title and three bullets.' }) });
    // One usage chip, so "Used in" has something to name.
    await api('/entries', { method: 'POST', body: JSON.stringify({ content: `# Card sweep\n\n![board](${ids[0].url})`, tags: ['sweep'] }) });
    return ids;
  }, { b64: PNG, caption: CAPTION, ocr: OCR });
  say('seeded', seeded);

  await page.evaluate(() => switchTab('library'));
  await page.waitForTimeout(700);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#library-subtabs button, [data-subtab]')]
      .find((e) => /image/i.test(e.textContent || e.dataset.subtab || ''));
    if (b) b.click();
  });
  await page.waitForTimeout(1500);

  const cards = await page.evaluate(() => {
    const tiles = [...document.querySelectorAll('.library-image-tile')];
    const box = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { h: +r.height.toFixed(1), w: +r.width.toFixed(1), y: +r.y.toFixed(1) };
    };
    return tiles.map((t) => {
      const frame = t.querySelector('.library-image-frame');
      const r = t.getBoundingClientRect();
      const fr = frame ? frame.getBoundingClientRect() : null;
      // Every direct child under the picture, in order, with its own height:
      // the "bottom of the card" is exactly this stack.
      const stack = [...t.children].filter((c) => c !== frame).map((c) => ({
        cls: c.className,
        h: +c.getBoundingClientRect().height.toFixed(1),
        text: c.textContent.replace(/\s+/g, ' ').trim().slice(0, 60),
        controls: c.querySelectorAll('button').length,
      }));
      return {
        name: t.querySelector('.library-image-name, figcaption')?.textContent.trim().slice(0, 30),
        card: +r.height.toFixed(1),
        picture: fr ? +fr.height.toFixed(1) : null,
        below: fr ? +(r.bottom - fr.bottom).toFixed(1) : null,
        pictureShare: fr ? +((fr.height / r.height) * 100).toFixed(1) : null,
        buttons: t.querySelectorAll('button').length,
        stack,
      };
    });
  });
  say('cards', cards);

  const gallery = await page.evaluate(() => {
    const g = document.querySelector('.library-image-gallery, #library-images-gallery, #library-images');
    if (!g) return null;
    const c = getComputedStyle(g);
    return { id: g.id, cls: g.className, display: c.display, cols: c.gridTemplateColumns, gap: c.gap };
  });
  say('gallery', gallery);

  const shot = await page.evaluate(() => {
    const t = document.querySelector('.library-image-tile');
    if (!t) return null;
    const r = t.getBoundingClientRect();
    return { x: Math.max(0, Math.floor(r.x) - 6), y: Math.max(0, Math.floor(r.y) - 6), width: Math.ceil(r.width) + 12, height: Math.ceil(r.height) + 12 };
  });
  if (shot) await page.screenshot({ path: OUT + '/imagecard-one.png', clip: shot });
  await page.screenshot({ path: OUT + '/imagecards.png' });
  console.log('shots in ' + OUT);
  await browser.close();
})();
