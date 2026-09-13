// The foot of the Library image cards, block by block (INBOX 115 and 118).
//
// `imagecardrow.js` beside this measures the row: six cards, their heights,
// their caption line counts. This one measures what is *under* the picture on
// each of them, which is what both reports are about: every block in the
// card's flow with its class, its height and its words, the gap left under
// the last one, and the computed shape of the two blocks that carry a fact
// (the count and the fold) so "unstyled paragraph" is a number rather than an
// impression.
//
//   BASE=http://127.0.0.1:8897 SCRATCH=/tmp/mm-cards2 THEME=dark WIDTH=1440 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/imagecardfoot.js
const { boot } = require('./lib.js');
const { execFileSync } = require('child_process');

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
  const blocks = (root, tile) =>
    [...root.children].filter(seen).map((el) => {
      const r = el.getBoundingClientRect();
      return {
        cls: el.className.toString().split(' ').filter((c) => c.startsWith('library-')).join('.') || el.tagName.toLowerCase(),
        h: +r.height.toFixed(1),
        top: +(r.top - tile.getBoundingClientRect().top).toFixed(1),
        text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40),
      };
    });
  return tiles.map((t) => {
    const r = t.getBoundingClientRect();
    const fr = t.querySelector('.library-image-frame')?.getBoundingClientRect();
    const fields = t.querySelector('.library-image-fields');
    const uses = t.querySelector('.library-image-uses');
    const fold = t.querySelector('.library-image-reading > summary');
    const cs = (el, props) =>
      el && seen(el)
        ? Object.fromEntries(props.map((p) => [p, getComputedStyle(el)[p]]))
        : null;
    const last = [...t.children].filter(seen).pop();
    const lastInner = fields && seen(fields) ? [...fields.children].filter(seen).pop() : null;
    const bottom = lastInner
      ? lastInner.getBoundingClientRect().bottom
      : last
        ? last.getBoundingClientRect().bottom
        : r.bottom;
    return {
      card: +r.height.toFixed(1),
      cardBottom: +r.bottom.toFixed(1),
      picture: fr ? +fr.height.toFixed(1) : null,
      foot: fr ? +(r.bottom - fr.bottom).toFixed(1) : null,
      tail: +(r.bottom - bottom).toFixed(1),
      rows: fields ? blocks(fields, t) : [],
      usesStyle: cs(uses, ['fontSize', 'marginTop', 'marginBottom', 'color', 'display']),
      foldStyle: cs(fold, ['fontSize', 'background', 'paddingTop', 'paddingLeft']),
      foldBox: fold && seen(fold)
        ? {
            w: +fold.getBoundingClientRect().width.toFixed(1),
            h: +fold.getBoundingClientRect().height.toFixed(1),
          }
        : null,
      atRest: [...t.querySelectorAll('button, input, summary, a')].filter(seen).length,
    };
  });
};

(async () => {
  const width = Number(process.env.WIDTH || 1440);
  const { browser, page, OUT } = await boot({ viewport: { width, height: 900 } });
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);

  // Seed once per data dir: a second run against the same dir would otherwise
  // add six more cards and measure a gallery nobody has.
  const seeded = await page.evaluate(async () => {
    const r = await api('/media');
    const rows = Array.isArray(r) ? r : r.items || r.media || r.files || [];
    return rows.length;
  });
  if (!seeded) {
    await page.evaluate(async ({ b64, captions, ocr }) => {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const ids = [];
      for (let i = 0; i < captions.length; i += 1) {
        const fd = new FormData();
        fd.append('file', new File([bytes], `card-${i}.png`, { type: 'image/png' }));
        fd.append('direct', 'true');
        const res = await fetch('/media/upload', {
          method: 'POST', body: fd,
          headers: { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId() },
        });
        ids.push(await res.json());
      }
      for (let i = 0; i < captions.length; i += 1) {
        if (captions[i]) {
          await api(`/media/${ids[i].id}/caption`, { method: 'POST', body: JSON.stringify({ text: captions[i] }) });
        }
      }
      await api(`/media/${ids[3].id}/vision-ocr`, { method: 'POST', body: JSON.stringify({ text: ocr }) });
      await api(`/media/${ids[4].id}/vision-ocr`, { method: 'POST', body: JSON.stringify({ text: ocr }) });
      await api('/entries', { method: 'POST', body: JSON.stringify({ content: `# Foot sweep\n\n![a](${ids[3].url})\n\n![b](${ids[1].url})`, tags: ['sweep'] }) });
      await api('/entries', { method: 'POST', body: JSON.stringify({ content: `# Foot sweep two\n\n![a](${ids[3].url})`, tags: ['sweep'] }) });
    }, { b64: PNG, captions: CAPTIONS, ocr: OCR });
  }

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
  say('heights', rows.map((r) => r.card));
  say('bottoms', rows.map((r) => r.cardBottom));
  say('pictures', rows.map((r) => r.picture));
  say('tails', rows.map((r) => r.tail));
  say('atRest', rows.map((r) => r.atRest));
  for (const [i, row] of rows.entries()) say(`card${i}`, { foot: row.foot, fold: row.foldBox, rows: row.rows });
  say('usesStyle', rows.map((r) => r.usesStyle).find(Boolean) || null);
  say('foldStyle', rows.map((r) => r.foldStyle).find(Boolean) || null);
  const theme = process.env.THEME || 'light';
  const shot = `${OUT}/imagecardfoot-${width}-${theme}.png`;
  await page.screenshot({ path: shot });

  // Contrast, from the pixels of that screenshot. Not from a composite walked
  // up the DOM: every surface under a picture card is translucent over the
  // page's own art, and both ways of guessing at it are wrong here. See the
  // header of `pixelcontrast.py`, which holds the numbers that settled it.
  const boxes = await page.evaluate(() => {
    const box = (label, el) => {
      if (!el || !el.offsetParent) return null;
      const r = el.getBoundingClientRect();
      if (r.width < 12 || r.height < 8 || r.bottom > innerHeight) return null;
      return { label, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    };
    return [
      box('description', document.querySelector('.library-image-caption')),
      box('uses', document.querySelector('.library-image-uses')),
      box('fold', document.querySelector('.library-image-card-fold > summary')),
    ].filter(Boolean);
  });
  if (boxes.length) {
    const read = execFileSync('python3',
      ['scratchpad/ui-sweeps/pixelcontrast.py', shot, theme, JSON.stringify(boxes)],
      { cwd: '/home/user/MemoryMap-AI', encoding: 'utf8' });
    const rows = JSON.parse(read);
    say('contrast', rows.map((r) => `${r.label} ${r.ratio}`));
    const low = rows.filter((r) => r.ratio < 4.5);
    if (low.length) console.log('LOW CONTRAST: ' + JSON.stringify(low));
  }
  console.log('shots in ' + OUT);
  await browser.close();
})();
