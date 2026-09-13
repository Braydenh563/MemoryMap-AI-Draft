// A row of six Library image cards, the shape INBOX 118 reports on.
//
// The owner, with a screenshot of six cards side by side: "also redesign the
// bottom of the images cards again as theyare still poorly designed and look
// unprofessional". The three things read off that screenshot are all
// measurable: whether the description is clamped and how many lines it runs,
// whether the cards' bottoms line up across the row, and how big the control
// under them is.
//
// Six images are seeded with descriptions of deliberately different lengths
// (none, a few words, one line, two, three, five), all by hand through the
// app's own `text:` paths, so no model is involved.
//
//   BASE=http://127.0.0.1:8879 SCRATCH=/tmp/mm-cards THEME=dark \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/imagecardrow.js
const { boot } = require('./lib.js');

const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8DAwMDAxMDAwAAADwEBAAyEAvUAAAAASUVORK5CYII=';
const CAPTIONS = [
  '',
  'A receipt.',
  'A photograph of a lecture slide with a title and three bullet points under it.',
  'A whiteboard photographed at an angle, covered in boxes and arrows sketched in blue marker, with a laptop and two coffee cups on the table below it.',
  'A scanned page from a notebook, ruled, with a long hand-written list down the left margin and a diagram of a pipeline drawn across the middle of it in two colours, annotated at every arrow.',
  'A screenshot of a settings dialog.',
];
const OCR = 'INGEST -> PARSE -> STORE\nnightly batch?\nask Priya about the retry budget';

const probe = () => {
  const tiles = [...document.querySelectorAll('.library-image-tile')];
  const seen = (el) => {
    if (!el || !el.offsetParent) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const box = (el) => {
    if (!seen(el)) return null;
    const r = el.getBoundingClientRect();
    return { w: +r.width.toFixed(1), h: +r.height.toFixed(1) };
  };
  return tiles.map((t) => {
    const r = t.getBoundingClientRect();
    const fr = t.querySelector('.library-image-frame')?.getBoundingClientRect();
    const cap = t.querySelector('.library-image-caption');
    const capStyle = cap ? getComputedStyle(cap) : null;
    const lines = cap && seen(cap)
      ? +(cap.getBoundingClientRect().height / parseFloat(capStyle.lineHeight)).toFixed(2)
      : 0;
    // The last thing in the card's own flow, and the gap under it.
    const last = [...t.children].filter(seen).pop();
    const lastBottom = last ? last.getBoundingClientRect().bottom : r.bottom;
    const fold = t.querySelector('.library-image-reading > summary');
    return {
      w: +r.width.toFixed(1),
      card: +r.height.toFixed(1),
      picture: fr ? +fr.height.toFixed(1) : null,
      below: fr ? +(r.bottom - fr.bottom).toFixed(1) : null,
      capLines: lines,
      capClamped: cap ? cap.classList.contains('library-image-caption-clamped') : null,
      // "Dead space below the last control", the report's own words.
      tail: +(r.bottom - lastBottom).toFixed(1),
      fold: box(fold),
      foldText: fold ? fold.textContent.replace(/\s+/g, ' ').trim() : null,
      atRest: [...t.querySelectorAll('button, input, summary')].filter(seen).length,
    };
  });
};

(async () => {
  const width = Number(process.env.WIDTH || 1440);
  const { browser, page, OUT } = await boot({ viewport: { width, height: 900 } });
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);

  await page.evaluate(async ({ b64, captions, ocr }) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const ids = [];
    for (let i = 0; i < captions.length; i += 1) {
      const fd = new FormData();
      fd.append('file', new File([bytes], `card-${i}.png`, { type: 'image/png' }));
      fd.append('direct', 'true');
      const r = await fetch('/media/upload', {
        method: 'POST', body: fd,
        headers: { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId() },
      });
      ids.push(await r.json());
    }
    for (let i = 0; i < captions.length; i += 1) {
      if (captions[i]) {
        await api(`/media/${ids[i].id}/caption`, { method: 'POST', body: JSON.stringify({ text: captions[i] }) });
      }
    }
    // Two of the six have had their text read, and two are used somewhere.
    await api(`/media/${ids[3].id}/vision-ocr`, { method: 'POST', body: JSON.stringify({ text: ocr }) });
    await api(`/media/${ids[4].id}/vision-ocr`, { method: 'POST', body: JSON.stringify({ text: ocr }) });
    await api('/entries', { method: 'POST', body: JSON.stringify({ content: `# Row sweep\n\n![a](${ids[3].url})\n\n![b](${ids[1].url})`, tags: ['sweep'] }) });
    await api('/entries', { method: 'POST', body: JSON.stringify({ content: `# Row sweep two\n\n![a](${ids[3].url})`, tags: ['sweep'] }) });
  }, { b64: PNG, captions: CAPTIONS, ocr: OCR });

  await page.evaluate(() => switchTab('library'));
  await page.waitForTimeout(700);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#library-subtabs button, [data-subtab]')]
      .find((e) => /image/i.test(e.textContent || e.dataset.subtab || ''));
    if (b) b.click();
  });
  await page.waitForTimeout(1600);
  const rows = await page.evaluate(probe);
  say('width', width);
  say('cards', rows);
  say('heights', rows.map((r) => r.card));
  say('tails', rows.map((r) => r.tail));
  say('capLines', rows.map((r) => r.capLines));
  await page.screenshot({ path: `${OUT}/imagecardrow-${width}-${process.env.THEME || 'light'}.png` });
  console.log('shots in ' + OUT);
  await browser.close();
})();
