// Third pass: the specific controls measure2.js flagged, checked one by one
// so the audit reports what they ARE rather than what a bounding box implies.
//
// CLAUDE.md's rule, applied to my own numbers: a 1x1 <select> is either a real
// unclickable control or a native element deliberately clipped behind a styled
// sibling (DESIGN.md names that exception). A bbox alone cannot tell those
// apart, so this reads opacity/clip/pointer-events and asks the browser where
// a click at the control's centre would actually land.
//
//   BASE=http://127.0.0.1:8791 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/audit/probe.js > scratchpad/audit/probe.json
const { boot, goTab } = require('./lib');

const SUSPECTS = [
  ['notes', '#semantic-search-toggle'],
  ['library', '#library-semantic-toggle'],
  ['library', '#library-show-binned'],
  ['chat', '#chat-sidebar-sort'],
  ['reminders', '#reminder-priority'],
  ['reminders', '#reminder-recurring'],
  ['reminders', '#reminders-page-size'],
];

const PROBE = (sel) => `(() => {
  const sel = ${JSON.stringify(sel)};
  const el = document.querySelector(sel);
  if (!el) return { sel, missing: true };
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
  const hit = document.elementFromPoint(cx, cy);
  // The label/wrapper a styled switch would be drawn by.
  const wrap = el.closest('label, .switch, .toggle, .field, .select-wrap');
  const wr = wrap ? wrap.getBoundingClientRect() : null;
  return {
    sel, tag: el.tagName.toLowerCase(), type: el.type || null,
    box: { w: +r.width.toFixed(1), h: +r.height.toFixed(1) },
    opacity: s.opacity, clipPath: s.clipPath, position: s.position,
    pointerEvents: s.pointerEvents, appearance: s.appearance,
    hitAtCentre: hit ? (hit.id ? '#' + hit.id : hit.tagName.toLowerCase() + '.' + (hit.className||'').toString().split(' ')[0]) : null,
    hitIsSelf: hit === el,
    wrapper: wrap ? { sel: (wrap.id ? '#' + wrap.id : wrap.tagName.toLowerCase() + '.' + (wrap.className||'').toString().split(' ')[0]), w: +wr.width.toFixed(1), h: +wr.height.toFixed(1) } : null,
  };
})()`;

// The Notes screen's chrome, broken into the rows that make it up — the
// number REDESIGN §R1.1 quotes for Library ("344px across four stacked
// control rows"), re-taken for Notes at three widths.
const CHROME = `(() => {
  const rows = [];
  const first = document.querySelector('#entry-list > *');
  const top = first ? first.getBoundingClientRect().top : null;
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (!r.height || r.width < window.innerWidth * 0.4) continue;
    if (top === null || r.bottom > top + 1 || r.top < 0) continue;
    if (el.children.length && [...el.children].some((c) => c.getBoundingClientRect().width >= r.width * 0.9 && c.getBoundingClientRect().height >= r.height * 0.9)) continue;
    rows.push({ sel: (el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + (el.className||'').toString().split(' ').slice(0,2).join('.')), y: Math.round(r.top), h: Math.round(r.height) });
  }
  rows.sort((a, b) => a.y - b.y);
  return { firstItemTop: top === null ? null : Math.round(top), viewportH: window.innerHeight, rows: rows.slice(0, 14) };
})()`;

async function main() {
  const out = { generated: new Date().toISOString(), widths: {} };
  for (const [label, viewport, touch] of [
    ['w1440', { width: 1440, height: 900 }, false],
    ['w390', { width: 390, height: 844 }, true],
  ]) {
    const { browser, page } = await boot({ viewport, touch });
    const bucket = { suspects: [], chrome: null, shots: [] };
    for (const [tab, sel] of SUSPECTS) {
      await goTab(page, tab);
      bucket.suspects.push(await page.evaluate(PROBE(sel)));
    }
    await goTab(page, 'notes');
    bucket.chrome = await page.evaluate(CHROME);
    await page.screenshot({ path: `${process.env.SCRATCH || '/tmp/audit-out'}/notes-${label}.png` });
    await goTab(page, 'library');
    await page.screenshot({ path: `${process.env.SCRATCH || '/tmp/audit-out'}/library-${label}.png` });
    out.widths[label] = bucket;
    await browser.close();
  }
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

main().catch((e) => { console.error(e); process.exit(1); });
