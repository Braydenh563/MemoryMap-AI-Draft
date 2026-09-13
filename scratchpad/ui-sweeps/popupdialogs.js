// The three dialogs the owner reported on 2026-09-13 as "not the consistent
// modern look": the quick sketch pad, the popup agent (the Ctrl+Shift+A
// command palette) and the meeting notes recorder.
//
// What it measures, and why each number rather than a screenshot:
//
//   rows      For every control container in the dialog, the number of
//             distinct rounded offsetTop values among its visible controls.
//             Two tops means the container wrapped, which is the owner's
//             report about the sketch toolbar word for word ("the
//             pen/highlighter/eraser group wraps to a second line inside its
//             own box"). A wrap is invisible in a screenshot at one width and
//             obvious as a number at every width.
//   heights   The distinct control heights in each container. The dock
//             grammar is one height per bar; four heights in one strip is
//             what "clumped and ugly" measures as.
//   inset     A bar under a canvas or a list is either flush with the surface
//             above it or deliberately inset; the report is that the sketch
//             caption bar matches neither. Left/right offset against the
//             element above, plus its own border radius.
//   contrast  Every visible text node in the dialog against the first opaque
//             background above it, as a WCAG ratio. The tab sweeps
//             (contrast.js) walk tabs, never dialogs, so these three
//             surfaces had never been contrast-checked at all.
//
// BASE=http://127.0.0.1:8931 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node popupdialogs.js
const { boot } = require('./lib.js');

const WIDTHS = [Number(process.env.W1 || 1440), Number(process.env.W2 || 1024)];

// Injected into the page: the geometry and the contrast pass over one dialog.
const probe = ([cardSel, containerSels]) => {
  const vis = (e) => {
    const b = e.getBoundingClientRect();
    return b.width > 0 && b.height > 0;
  };
  const card = document.querySelector(cardSel);
  if (!card) return { missing: cardSel };
  const out = { rows: [], contrast: [], overflow: null };
  for (const sel of containerSels) {
    for (const box of card.querySelectorAll(sel)) {
      if (!vis(box)) continue;
      // A control is the thing you press: a `.seg` well counts once and its
      // cells not at all, the same reading docks.js settled on.
      const ctrls = [...box.querySelectorAll('button, input, select, .seg, .segmented-control, .select-shell')]
        .filter((c) => {
          if (!vis(c)) return false;
          if (c.classList.contains('hidden')) return false;
          const wrap = c.closest('.seg, .segmented-control, .select-shell');
          if (wrap && wrap !== c) return false;
          return true;
        });
      if (!ctrls.length) continue;
      // Rows are counted from each control's vertical *centre*, clustered at
      // 4px. Tops do not work: controls of different heights sitting on one
      // centred row have tops ten pixels apart (a 16px slider beside a 36px
      // button), which reads as a wrap that is not there, and a `transform:
      // scale` on a selected swatch shifts another. A real second row is a
      // whole control height away from the first.
      const raw = ctrls.map((c) => { const b = c.getBoundingClientRect(); return b.top + b.height / 2; }).sort((a, b) => a - b);
      const tops = raw.filter((t, i) => i === 0 || t - raw[i - 1] > 4);
      const hs = [...new Set(ctrls.map((c) => Math.round(c.getBoundingClientRect().height)))];
      const cs = getComputedStyle(box);
      out.rows.push({
        sel: box.id ? '#' + box.id : '.' + [...box.classList].slice(0, 2).join('.'),
        controls: ctrls.length,
        rowsUsed: tops.length,
        heights: hs.sort((a, b) => a - b).join('/'),
        h: Math.round(box.getBoundingClientRect().height),
        radius: cs.borderTopLeftRadius,
        padX: cs.paddingLeft + '/' + cs.paddingRight,
        left: Math.round(box.getBoundingClientRect().left),
        right: Math.round(box.getBoundingClientRect().right),
      });
    }
  }
  // Contrast, computed colours composited down the tree (contrast.js's method).
  const cv = document.createElement('canvas');
  cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const parse = (c) => {
    if (!c || c === 'transparent') return null;
    const m = c.match(/^rgba?\(([^)]+)\)$/);
    if (m) {
      const p = m[1].split(/[\s,\/]+/).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    }
    cx.clearRect(0, 0, 1, 1);
    cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return { r: d[0], g: d[1], b: d[2], a: d[3] / 255 };
  };
  const lum = (c) => {
    const f = [c.r, c.g, c.b].map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  });
  // The background a piece of text is actually read against, and whether
  // anything translucent was crossed on the way to it. That second half
  // matters: these three dialogs are `.card.glass`, so a strict composite
  // says the text sits on the scrim and the page behind it, while what the
  // eye gets is a backdrop-filter that blurs AND lifts the luminosity of all
  // that, which no computed style can report. Measured on the palette's intro
  // line: composited 2.52:1, the rendered pixels (scratchpad/pngpixel.py on a
  // capture) 4.75:1. So a translucent chain is reported, never failed, which
  // is the same call contrast.js makes.
  const bgOf = (el) => {
    let n = el;
    let acc = null;
    let translucent = false;
    while (n && n !== document.documentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) {
        if (c.a < 0.999) translucent = true;
        acc = acc ? over(acc, c) : c;
      }
      if (acc && acc.a >= 0.999) return { bg: acc, translucent };
      n = n.parentElement;
    }
    const root = parse(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
    return { bg: acc ? over(acc, root) : root, translucent };
  };
  for (const el of card.querySelectorAll('*')) {
    if (!vis(el)) continue;
    const text = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim()).join(' ');
    if (!text) continue;
    const cs = getComputedStyle(el);
    const fg = parse(cs.color);
    if (!fg) continue;
    const { bg, translucent } = bgOf(el);
    const f = fg.a < 1 ? over(fg, bg) : fg;
    const l1 = lum(f);
    const l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const size = parseFloat(cs.fontSize);
    const large = size >= 18.66 || (size >= 14 && Number(cs.fontWeight) >= 700);
    const need = large ? 3 : 4.5;
    if (ratio < need) {
      out.contrast.push({
        text: text.slice(0, 40),
        ratio: ratio.toFixed(2),
        need,
        size,
        // An estimate, not a verdict: settle it from the pixels.
        on: translucent ? 'translucent' : 'opaque',
      });
    }
  }
  // Every field and every button in the dialog, with the two things a report
  // about "a large border" or "clumped" is usually actually about: the border
  // width and the height. A dialog with three border widths in it reads as
  // three different applications, and that is invisible in a capture.
  out.fields = [];
  for (const el of card.querySelectorAll('input, textarea, select, button')) {
    const b = el.getBoundingClientRect();
    if (b.width <= 0 || b.height <= 0) continue;
    const cs = getComputedStyle(el);
    out.fields.push({
      sel: el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + [...el.classList].slice(0, 1).join(''),
      h: Math.round(b.height),
      border: cs.borderTopWidth,
      radius: cs.borderTopLeftRadius,
    });
  }
  out.overflow = { scroll: card.scrollHeight, client: card.clientHeight };
  return out;
};

const DIALOGS = [
  {
    name: 'sketch',
    open: () => document.getElementById('sketch-btn').click(),
    card: '#sketch-card',
    containers: ['#sketch-toolbar', '#sketch-toolbar > *', '#sketch-foot', '#sketch-card > .row'],
    close: () => document.getElementById('sketch-close').click(),
  },
  {
    name: 'agent',
    open: () => document.getElementById('status-agent').click(),
    card: '.command-palette-card',
    containers: ['.command-palette-bar', '.command-palette-foot', '.command-palette-examples'],
    close: () => document.getElementById('status-agent').click(),
  },
  {
    name: 'meeting',
    open: () => { document.getElementById('meeting-overlay').classList.remove('hidden'); },
    card: '#meeting-card',
    containers: ['#meeting-controls', '#meeting-save-row', '#meeting-card > .row'],
    close: () => { document.getElementById('meeting-overlay').classList.add('hidden'); },
  },
];

(async () => {
  const { browser, page, OUT } = await boot();
  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(400);
  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.waitForTimeout(300);
    for (const d of DIALOGS) {
      await page.evaluate(d.open);
      await page.waitForTimeout(600);
      // The save row is hidden until a recording exists; show it so the bar
      // that the report is about can be measured at all.
      if (d.name === 'meeting') {
        await page.evaluate(() => {
          document.getElementById('meeting-save-row')?.classList.remove('hidden');
          document.getElementById('meeting-transcript')?.classList.remove('hidden');
        });
        await page.waitForTimeout(200);
      }
      const r = await page.evaluate(probe, [d.card, d.containers]);
      console.log(`${d.name}@${w}`, JSON.stringify(r));
      await page.screenshot({ path: `${OUT}/pd-${d.name}-${w}.png` });
      await page.evaluate(d.close);
      await page.waitForTimeout(400);
    }
  }
  await browser.close();
})();
