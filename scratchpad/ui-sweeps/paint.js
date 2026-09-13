// **Dead paint attributes, found in the browser rather than in the source.**
//
//   BASE=… PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node paint.js
//
// A `fill` or `stroke` attribute is a declaration at the bottom of the
// cascade, under every author rule however unspecific, so any stylesheet rule
// for that property wins and the attribute is dead markup that reads as live
// code. It cost a measurement round once already: a map label painted white by
// attribute came back 3.82:1 before and 3.82:1 after, because
// `.board-minimap-label { fill: var(--ink) }` was quietly winning.
//
// `tests/test_svg_paint_attributes.py` catches the half of this that a text
// scan can see: an attribute on an element whose own class the stylesheets
// paint. It cannot see the other half, an unclassed element reached by a
// descendant selector (`.graph-node text { fill: … }`), because that needs the
// tree. This is the tree: for every rendered SVG element carrying one of these
// attributes, take the computed paint, then set the same value as an inline
// style (which sits *above* the stylesheet) and take it again. If the two
// differ, a rule is overriding the attribute and the attribute is doing
// nothing. `var(--accent)`, `currentColor` and `none` all resolve correctly
// this way because the browser resolves them, in place, on the real element.
const { boot } = require('./lib.js');

const SCAN = () => {
  const rows = [];
  for (const el of document.querySelectorAll('svg [fill], svg [stroke], svg[fill], svg[stroke]')) {
    for (const paint of ['fill', 'stroke']) {
      const attr = el.getAttribute(paint);
      if (attr === null) continue;
      const before = getComputedStyle(el)[paint];
      const saved = el.style[paint];
      el.style[paint] = attr;
      const after = getComputedStyle(el)[paint];
      el.style[paint] = saved;
      if (before === after) continue;
      rows.push({
        el: el.tagName + (el.getAttribute('class') ? '.' + el.getAttribute('class').split(/\s+/).join('.') : ''),
        paint,
        attr,
        computed: before,
        wanted: after,
      });
    }
  }
  // One line per distinct element+property, not one per instance: a map with
  // 700 dots on it would otherwise bury everything else in the report.
  const seen = new Map();
  for (const row of rows) {
    const key = `${row.el} ${row.paint} ${row.attr}`;
    seen.set(key, { ...row, count: (seen.get(key)?.count || 0) + 1 });
  }
  return [...seen.values()];
};

(async () => {
  const { browser, page } = await boot();
  // **The sweep proves it can see the fault before it reports none.** A scan
  // that silently matches nothing prints the same "0" as a clean app, and the
  // difference matters more here than usual: this is the check for the half
  // the lint cannot reach, so a broken one leaves that half unchecked while
  // looking checked. The probe is the original bug, rebuilt: a label carrying
  // the class whose `fill` beat it.
  const selfCheck = await page.evaluate((scan) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('class', 'board-minimap-label');
    text.setAttribute('fill', '#ffffff');
    text.textContent = 'probe';
    svg.appendChild(text);
    document.body.appendChild(svg);
    const rows = new Function(`return (${scan})()`)();
    svg.remove();
    return rows.filter((row) => row.el.includes('board-minimap-label'));
  }, SCAN.toString());
  if (selfCheck.length !== 1) {
    console.log(`self-check FAILED: the probe was not reported (${JSON.stringify(selfCheck)})`);
    await browser.close();
    process.exitCode = 1;
    return;
  }
  console.log(`self-check: ok, the probe reads ${selfCheck[0].computed} against fill="#ffffff"`);
  let total = 0;
  const report = async (label) => {
    const rows = await page.evaluate(SCAN);
    total += rows.length;
    console.log(`${label}: ${rows.length} dead paint attribute${rows.length === 1 ? '' : 's'}`);
    for (const row of rows) {
      console.log(`   ${row.el} ${row.paint}="${row.attr}" computes ${row.computed}, wanted ${row.wanted} (x${row.count})`);
    }
  };
  for (const tab of ['dashboard', 'notes', 'chat', 'graph', 'library', 'timeline', 'reminders']) {
    await page.click(`[data-tab="${tab}"]`).catch(() => {});
    await page.waitForTimeout(900);
    await report(tab);
  }
  // The board and map previews, then a board itself: the minimap labels that
  // started this file are only rendered on the Boards and maps sub-tab, and
  // the whiteboard's own guides and handles only once a board is open.
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(400);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(1000);
  await report('library boards');
  const card = await page.$('#library-boards-grid .library-card');
  if (card) {
    await card.click();
    await page.waitForTimeout(1400);
    await report('whiteboard');
  }
  console.log(`total: ${total}`);
  await browser.close();
})();
