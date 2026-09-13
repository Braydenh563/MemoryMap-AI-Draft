// INBOX 146, measured: "when i expand timeline items, the top text and stuff
// gets pushed up slightly and the vertical line on the right clashes with the
// other text and elements".
//
// Two numbers hold the fix in place:
//
//   1. Opening a row must not move its header. The measurement is the title's
//      own top, relative to the row's top, collapsed against expanded, plus
//      the row's padding-top in both states. A row that re-aligns its items
//      when it grows a second grid row moves the title by a few pixels, which
//      is what "gets pushed up slightly" is.
//   2. The spine (`.timeline-rows::before`, the hairline through the kind
//      markers) must run *beside* an opened note, never through it. The
//      measurement is the spine's right edge against the left edge of
//      everything inside the opened detail: the body, the actions, the title.
//
//   BASE=http://127.0.0.1:8936 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     SCRATCH=/tmp/claude-0 timeout 110 node timelineexpand.js
const { boot } = require('./lib.js');

let failures = 0;
const check = (label, ok, detail) => {
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}  ${detail}`);
};

(async () => {
  const { browser, page, OUT } = await boot();
  for (const { w, h } of [{ w: 1440, h: 900 }, { w: 390, h: 844 }]) {
    await page.setViewportSize({ width: w, height: h });
    await page.click('[data-tab="timeline"]');
    await page.waitForTimeout(900);

    const before = await page.evaluate(() => {
      const row = document.querySelector('.timeline-row');
      const title = row.querySelector('.timeline-row-title');
      const box = row.getBoundingClientRect();
      return {
        padTop: getComputedStyle(row).paddingTop,
        titleOffset: Math.round((title.getBoundingClientRect().top - box.top) * 10) / 10,
        height: Math.round(box.height),
      };
    });

    await page.evaluate(() => {
      const row = document.querySelector('.timeline-row');
      row.focus();
      row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    await page.waitForTimeout(900);

    const after = await page.evaluate(() => {
      const row = document.querySelector('.timeline-row');
      const title = row.querySelector('.timeline-row-title');
      const detail = row.querySelector('.timeline-row-detail');
      const box = row.getBoundingClientRect();
      const list = row.closest('.timeline-rows');
      // The spine is a pseudo element, so its box is read from the rule rather
      // than from the DOM: its left edge is the list's own left plus the
      // offset the stylesheet gives it, and it is 1px wide.
      const spineLeft =
        list.getBoundingClientRect().left +
        parseFloat(getComputedStyle(list, '::before').left || '0');
      const spineRight = spineLeft + parseFloat(getComputedStyle(list, '::before').width || '1');
      const inside = [...detail.querySelectorAll('.timeline-row-body, .timeline-row-actions, button, p, img')]
        .map((el) => el.getBoundingClientRect())
        .filter((r) => r.width > 0 && r.height > 0);
      return {
        padTop: getComputedStyle(row).paddingTop,
        titleOffset: Math.round((title.getBoundingClientRect().top - box.top) * 10) / 10,
        height: Math.round(box.height),
        spineRight: Math.round(spineRight * 10) / 10,
        detailLeft: Math.round(detail.getBoundingClientRect().left * 10) / 10,
        worstLeft: inside.length ? Math.round(Math.min(...inside.map((r) => r.left)) * 10) / 10 : null,
        pieces: inside.length,
      };
    });

    check(`${w} opening a row keeps its padding`, before.padTop === after.padTop,
      `${before.padTop} collapsed, ${after.padTop} expanded`);
    check(`${w} opening a row does not move its title`, Math.abs(before.titleOffset - after.titleOffset) <= 0.6,
      `title sat ${before.titleOffset}px below the row top, now ${after.titleOffset}px (row ${before.height}px to ${after.height}px)`);
    check(`${w} the spine runs beside the opened note, not through it`,
      after.pieces > 0 && after.spineRight <= after.detailLeft && after.spineRight <= after.worstLeft,
      `spine ends at ${after.spineRight}px, the detail starts at ${after.detailLeft}px, its leftmost of ${after.pieces} pieces at ${after.worstLeft}px`);

    await page.screenshot({ path: `${OUT}/timeline-expand-${w}.png` });
    await page.keyboard.press('Escape');
  }
  await browser.close();
  console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
})();
