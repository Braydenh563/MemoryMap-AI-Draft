// Fourth pass: one specific thing the 390px screenshot suggested, checked by
// measurement rather than by looking — CLAUDE.md's rule, and the reason the
// nav-history popup survived four "fixes".
//
// The suggestion: on a touch viewport the note card's inline action icons
// (star / copy / edit) sit ON TOP of the first line of the note's own text
// instead of beside it. A screenshot cannot settle that; two bounding boxes
// and an `elementFromPoint` can.
//
//   BASE=http://127.0.0.1:8791 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/audit/overlap.js > scratchpad/audit/overlap.json
const { boot, goTab } = require('./lib');

const OVERLAP = `(() => {
  const card = document.querySelector('#entry-list > *');
  if (!card) return { missing: true };
  const text = card.querySelector('.entry-text, .note-text, p, .entry-content') || card;
  const tr = text.getBoundingClientRect();
  const hits = [];
  for (const b of card.querySelectorAll('button, a[role=button]')) {
    const r = b.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const ox = Math.max(0, Math.min(r.right, tr.right) - Math.max(r.left, tr.left));
    const oy = Math.max(0, Math.min(r.bottom, tr.bottom) - Math.max(r.top, tr.top));
    if (ox > 0 && oy > 0) {
      // Does a click in the middle of that overlap reach the button or the
      // text? If the button, the text under it is unselectable there.
      const cx = Math.max(r.left, tr.left) + ox / 2;
      const cy = Math.max(r.top, tr.top) + oy / 2;
      const hit = document.elementFromPoint(cx, cy);
      hits.push({
        label: (b.getAttribute('aria-label') || b.title || b.textContent || '').trim().slice(0, 30),
        overlapPx: Math.round(ox * oy),
        opacity: getComputedStyle(b).opacity,
        coversText: hit === b || b.contains(hit),
      });
    }
  }
  return {
    cardBox: { w: Math.round(card.getBoundingClientRect().width), h: Math.round(card.getBoundingClientRect().height) },
    textBox: { w: Math.round(tr.width), h: Math.round(tr.height) },
    overlapping: hits,
  };
})()`;

async function main() {
  const out = { generated: new Date().toISOString() };
  for (const [label, viewport, touch] of [
    ['w390_touch', { width: 390, height: 844 }, true],
    ['w1440_mouse', { width: 1440, height: 900 }, false],
  ]) {
    const { browser, page } = await boot({ viewport, touch });
    await goTab(page, 'notes');
    out[label] = await page.evaluate(OVERLAP);
    await browser.close();
  }
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

main().catch((e) => { console.error(e); process.exit(1); });
