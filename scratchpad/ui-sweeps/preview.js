// The board and map previews, measured (INBOX 68). The owner, twice:
// "Boards & maps preview looks so bad, especially in the dashboard" and "the
// boards and maps dashboard widget is ugly and needs fixing".
//
// What a screenshot cannot tell you and this does: whether the blocks in a
// preview have the *shapes of the things they stand for* (a banner across the
// top of a board is wide, a sticky is small: if every block is the same
// rectangle, the picture is of the renderer rather than of the board), whether
// any preview has a scrollbar inside it, whether labels sit inside their
// shapes or float beside them, and what the two surfaces disagree about.
//
//   BASE=http://127.0.0.1:8812 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/preview.js
//
// Needs boards to look at: `node scratchpad/ui-sweeps/seed-boards.js` first.
const { boot } = require('./lib.js');

const report = (label, m) => {
  if (!m) { console.log(`${label}: nothing drawn`); return; }
  console.log(
    `${label}: svg ${m.w}x${m.h}, paper ${m.paperW}x${m.paperH} (aspect ${m.aspect})\n`
    + `   blocks ${m.blocks} in ${m.distinctSizes} distinct size(s): ${m.sizes}\n`
    + `   edges ${m.edges}, labels ${m.labels} (${m.labelsInside} inside a block), sketches ${m.sketches}\n`
    + `   worst label contrast: ${m.labelContrast === null ? 'no labels' : m.labelContrast + ':1'}\n`
    + `   scrollable: ${m.scrolls}`,
  );
};

const measure = () => {
  const round = (n) => Math.round(n * 10) / 10;
  const out = [];
  for (const svg of document.querySelectorAll('.tab-page:not(.hidden) .board-minimap')) {
    const r = svg.getBoundingClientRect();
    const paper = svg.querySelector('.board-minimap-paper');
    const pr = paper ? paper.getBoundingClientRect() : null;
    const blocks = [...svg.querySelectorAll('rect')].filter((el) => el !== paper);
    const sizes = blocks.map((b) => {
      const box = b.getBoundingClientRect();
      return `${round(box.width)}x${round(box.height)}`;
    });
    const labels = [...svg.querySelectorAll('.board-minimap-label')];
    // A label is "inside" when its own box sits within some block's box.
    const inside = labels.filter((t) => {
      const tb = t.getBoundingClientRect();
      return blocks.some((b) => {
        const bb = b.getBoundingClientRect();
        return tb.left >= bb.left - 1 && tb.right <= bb.right + 1
          && tb.top >= bb.top - 1 && tb.bottom <= bb.bottom + 1;
      });
    }).length;
    // Anything between the preview and the page that scrolls: the report's
    // "a scrollbar beside it".
    let scrolls = 'no';
    for (let e = svg.parentElement; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (/auto|scroll/.test(cs.overflowY) && e.scrollHeight > e.clientHeight + 2) {
        scrolls = `${e.className || e.tagName} ${e.scrollHeight}/${e.clientHeight}`;
        break;
      }
    }
    // **A label that sits on a block has to read against the block**, not
    // against the paper it used to float over. SVG text takes its colour from
    // `fill`, which `contrast.js` does not look at (it reads `color`), so
    // these labels are invisible to that sweep and have to be measured here.
    const parse = (c) => {
      const m = String(c).match(/^rgba?\(([^)]+)\)$/);
      if (!m) return null;
      const p = m[1].split(/[\s,/]+/).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    };
    const lum = ({ r, g, b }) => {
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const over = (fg, bg) => ({
      r: fg.r * fg.a + bg.r * (1 - fg.a),
      g: fg.g * fg.a + bg.g * (1 - fg.a),
      b: fg.b * fg.a + bg.b * (1 - fg.a),
      a: 1,
    });
    const ratio = (a, b) => {
      const l1 = lum(a); const l2 = lum(b);
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    };
    // **The page is a gradient, so its `background-color` is transparent**,
    // and compositing over a transparent *black* is what the first version of
    // this check did: it reported ink-on-pale-blue as 1.03:1, which is the
    // arithmetic of a black page rather than anything on screen. The theme's
    // own resolved mode decides the ground instead.
    const parsedBody = parse(getComputedStyle(document.body).backgroundColor);
    const dark = document.documentElement.dataset.mode === 'dark';
    const pageBg = parsedBody && parsedBody.a > 0.9
      ? parsedBody
      : (dark ? { r: 22, g: 24, b: 31, a: 1 } : { r: 244, g: 246, b: 251, a: 1 });
    let worst = null;
    for (const t of labels) {
      const cs = getComputedStyle(t);
      const fill = parse(cs.fill);
      if (!fill) continue;
      const ink = { ...fill, a: (fill.a || 1) * Number(cs.opacity || 1) };
      // Whichever block the label is drawn on, or the paper when it is beside
      // one, composited over the page since both are translucent.
      const tb = t.getBoundingClientRect();
      const host = blocks.find((b) => {
        const bb = b.getBoundingClientRect();
        return tb.left >= bb.left - 1 && tb.right <= bb.right + 1
          && tb.top >= bb.top - 1 && tb.bottom <= bb.bottom + 1;
      }) || paper;
      const hostCs = host ? getComputedStyle(host) : null;
      const hostFill = hostCs ? parse(hostCs.fill) : null;
      if (!hostFill) continue;
      const ground = over({ ...hostFill, a: (hostFill.a || 1) * Number(hostCs.opacity || 1) }, pageBg);
      const value = ratio(over(ink, ground), ground);
      if (worst === null || value < worst) worst = value;
    }

    out.push({
      labelContrast: worst === null ? null : Math.round(worst * 100) / 100,
      w: round(r.width),
      h: round(r.height),
      paperW: pr ? round(pr.width) : 0,
      paperH: pr ? round(pr.height) : 0,
      aspect: pr && pr.height ? round(pr.width / pr.height) : 0,
      blocks: blocks.length,
      distinctSizes: new Set(sizes).size,
      sizes: [...new Set(sizes)].slice(0, 6).join(' '),
      edges: svg.querySelectorAll('.board-minimap-edge').length,
      labels: labels.length,
      labelsInside: inside,
      sketches: svg.querySelectorAll('.board-minimap-sketch').length,
      scrolls,
    });
  }
  return out;
};

(async () => {
  const { browser, page } = await boot();

  await page.click('[data-tab="dashboard"]').catch(() => {});
  await page.waitForTimeout(1500);
  const dash = await page.evaluate(measure);
  console.log('== dashboard widget');
  dash.forEach((m, i) => report(`   #${i + 1}`, m));

  await page.click('[data-tab="library"]').catch(() => {});
  await page.waitForTimeout(900);
  await page.click('#library-subtabs [data-target="library-view-whiteboard"]').catch(() => {});
  await page.waitForTimeout(1500);
  const lib = await page.evaluate(measure);
  console.log('== library, boards and maps');
  lib.forEach((m, i) => report(`   #${i + 1}`, m));

  await browser.close();
})();
