// The sketch pad's top bar, measured the way the report about it is worded:
// does any group sit on a different row, and how much of the bar is empty.
//
// Reported a second time (INBOX 123, the owner): "the quick sketch top dock
// still needs a better redesign", with a screenshot showing the Paper group
// alone on a second row while the right half of the first row was empty. It
// did not reproduce at 1440 or 1024 with the default appearance settings,
// which is exactly why this script sweeps the settings as well as the widths:
// the card is capped in px (`min(900px, 96vw)`) and everything inside it is
// sized in rem, so Large text (18px root) or Spacious density (a 1.35x
// spacing scale) buys the contents more width than the card ever gets.
//
//   BASE=http://127.0.0.1:8931 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node sketchbar.js
//
// Prints one line per (width x setting): the number of distinct group rows,
// each group's top and width, and the slack left at the right-hand end of the
// bar. A non-zero exit if any combination puts a group on a second row.
const { boot } = require('./lib.js');

const WIDTHS = [1440, 1024, 820];
const SETTINGS = [
  { name: 'default', fontsize: null, density: null },
  { name: 'large-text', fontsize: 'large', density: null },
  { name: 'spacious', fontsize: null, density: 'spacious' },
  { name: 'large+spacious', fontsize: 'large', density: 'spacious' },
];

const probe = () => {
  const bar = document.getElementById('sketch-toolbar');
  const groups = [...bar.children].filter((el) => el.getBoundingClientRect().height > 0);
  const rects = groups.map((el) => {
    const b = el.getBoundingClientRect();
    return {
      label: (el.querySelector('.wb-tool-section-label') || {}).textContent || '?',
      top: Math.round(b.top),
      left: Math.round(b.left),
      right: Math.round(b.right),
      w: Math.round(b.width),
    };
  });
  const bb = bar.getBoundingClientRect();
  const cs = getComputedStyle(bar);
  const padL = parseFloat(cs.paddingLeft);
  const padR = parseFloat(cs.paddingRight);
  const inner = { left: bb.left + padL, right: bb.right - padR };
  const last = rects.reduce((a, b) => (b.right > a.right ? b : a), rects[0]);
  const first = rects.reduce((a, b) => (b.left < a.left ? b : a), rects[0]);
  return {
    rows: [...new Set(rects.map((r) => r.top))].length,
    groups: rects,
    bar: { w: Math.round(bb.width), h: Math.round(bb.height) },
    // The two numbers the report is about: what is left over at the right end
    // of the bar, and what the contents actually take.
    slackRight: Math.round(inner.right - last.right),
    slackLeft: Math.round(first.left - inner.left),
    contentW: Math.round(last.right - first.left),
    innerW: Math.round(inner.right - inner.left),
  };
};

(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(300);
  let bad = 0;
  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w, height: 900 });
    for (const s of SETTINGS) {
      await page.evaluate((s) => {
        const root = document.documentElement;
        if (s.fontsize) root.setAttribute('data-fontsize', s.fontsize);
        else root.removeAttribute('data-fontsize');
        if (s.density) root.setAttribute('data-density', s.density);
        else root.removeAttribute('data-density');
      }, s);
      await page.evaluate(() => document.getElementById('sketch-btn').click());
      await page.waitForTimeout(400);
      const r = await page.evaluate(probe);
      if (r.rows > 1) bad += 1;
      console.log(
        `${w}/${s.name}`.padEnd(24),
        `rows=${r.rows}`,
        `content=${r.contentW}/${r.innerW}`,
        `slackR=${r.slackRight}`,
        `slackL=${r.slackLeft}`,
        r.groups.map((g) => `${g.label}@${g.top}:${g.w}`).join(' '),
      );
      await page.evaluate(() => document.getElementById('sketch-close').click());
      await page.waitForTimeout(250);
    }
  }
  await browser.close();
  if (bad) {
    console.log(`FAIL: ${bad} of ${WIDTHS.length * SETTINGS.length} combinations wrap`);
    process.exit(1);
  }
  console.log(`PASS: one row in all ${WIDTHS.length * SETTINGS.length} combinations`);
})();
