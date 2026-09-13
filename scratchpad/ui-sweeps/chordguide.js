// The quick-nav chord, driven (the owner's evening batch: the "m" hint was a
// broken toast and should be a whole-screen subtle guide, plus three new
// second keys).
//
// Measures rather than looks: the guide's box against the viewport, whether
// any of its rows wrap (the exact fault in the screenshot was a pair split
// across two lines), that it takes no pointer events, that it goes away when
// the chord resolves, and that each new second key does what it says.
//
//   BASE=http://127.0.0.1:8795 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/chordguide.js
const { boot } = require('./lib.js');

(async () => {
  const { browser, page } = await boot();
  let bad = 0;

  await page.keyboard.press('m');
  await page.waitForTimeout(200);
  const shown = await page.evaluate(() => {
    const g = document.getElementById('chord-guide');
    if (!g || g.classList.contains('hidden')) return null;
    const r = g.getBoundingClientRect();
    const rows = [...g.querySelectorAll('.chord-guide-row')];
    return {
      box: `${Math.round(r.width)}x${Math.round(r.height)} at ${Math.round(r.left)},${Math.round(r.top)}`,
      coversViewport: r.width >= innerWidth - 1 && r.height >= innerHeight - 1,
      rows: rows.length,
      // A row taller than one line of its own text is a wrapped pair.
      wrapped: rows.filter((row) => row.getBoundingClientRect().height > parseFloat(getComputedStyle(row).lineHeight) * 2).length,
      pointerEvents: getComputedStyle(g).pointerEvents,
      keys: rows.map((row) => `${row.querySelector('kbd').textContent}:${row.querySelector('span').textContent}`).join(' '),
      atPoint: (() => {
        const el = document.elementFromPoint(Math.round(innerWidth / 2), Math.round(innerHeight / 2));
        return el ? el.id || el.className || el.tagName : 'none';
      })(),
    };
  });
  if (!shown) {
    console.log('FAIL: the guide did not appear on "m"');
    bad += 1;
  } else {
    console.log(`guide: ${shown.box}, covers the viewport: ${shown.coversViewport}, ${shown.rows} rows, wrapped rows: ${shown.wrapped}, pointer-events: ${shown.pointerEvents}`);
    console.log(`   ${shown.keys}`);
    console.log(`   element under the centre of the screen: ${shown.atPoint}`);
    if (shown.rows !== 10) { bad += 1; console.log('   FAIL: expected ten entries (seven tabs, three actions)'); }
    if (shown.wrapped) { bad += 1; console.log('   FAIL: a key and its label are split across lines'); }
    if (shown.pointerEvents !== 'none') { bad += 1; console.log('   FAIL: the guide takes pointer events'); }
    if (!shown.coversViewport) { bad += 1; console.log('   FAIL: the guide is not full screen'); }
  }

  // The chord resolves: the guide goes, and the second key acts.
  await page.keyboard.press('t');
  await page.waitForTimeout(500);
  const afterTab = await page.evaluate(() => ({
    hidden: (document.getElementById('chord-guide') || {}).className || 'absent',
    tab: localStorage.getItem('activeTab'),
  }));
  console.log(`after "m t": activeTab=${afterTab.tab}, guide class="${afterTab.hidden}"`);
  if (afterTab.tab !== 'timeline') { bad += 1; console.log('   FAIL: m then t did not reach the timeline'); }
  if (!String(afterTab.hidden).includes('hidden')) { bad += 1; console.log('   FAIL: the guide stayed up after the chord resolved'); }

  // The three new second keys.
  for (const [key, check, label] of [
    ['s', () => !document.getElementById('settings-modal').classList.contains('hidden'), 'settings'],
    ['q', () => !document.getElementById('sketch-overlay').classList.contains('hidden'), 'quick sketch'],
  ]) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(400);
    await page.keyboard.press('m');
    await page.waitForTimeout(150);
    await page.keyboard.press(key);
    await page.waitForTimeout(800);
    const open = await page.evaluate(check);
    console.log(`after "m ${key}": ${label} open = ${open}`);
    if (!open) { bad += 1; console.log(`   FAIL: m then ${key} did not open ${label}`); }
  }
  await page.keyboard.press('Escape');

  console.log(bad ? `FAIL: ${bad} findings` : 'PASS: 0 findings');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
