// The Library's Boards-and-maps dock, measured (the owner: "the ui at the top
// of the boards and maps subtab dock is broken and miss wrapped. remember
// responsive design!"), and the exact reading `agent-remaining/wrap-sweep.md`
// asks the next person to take: the `.dock-actions` wrap mode at a wide
// viewport, and the `top` of every control in the dock.
//
// Two questions, and the dock grammar answers both: how many rows is the bar,
// and how many different heights are its controls. One height is the rule
// (`docks.js` reports the same defect for the whiteboard's own bar).
//
//   BASE=http://127.0.0.1:8814 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     WIDTHS=2000,1440,1024,820 node scratchpad/ui-sweeps/boardsdock.js
const { boot } = require('./lib.js');

const WIDTHS = (process.env.WIDTHS || '2000,1440,1024,820').split(',').map(Number);

(async () => {
  let bad = 0;
  for (const width of WIDTHS) {
    const { browser, page } = await boot({ viewport: { width, height: 900 } });
    await page.click('[data-tab="library"]').catch(() => {});
    await page.waitForTimeout(800);
    await page.click('#library-subtabs [data-target="library-view-whiteboard"]').catch(() => {});
    await page.waitForTimeout(1200);
    const m = await page.evaluate(() => {
      const dock = document.querySelector('[data-dock-name="library-boards"]');
      if (!dock) return null;
      const box = dock.getBoundingClientRect();
      // **A segment is not a control, its well is.** `08-consistency.css`
      // gives `.dock .seg > button` `height: auto; align-self: stretch` on
      // purpose, so a segmented choice is one control (the well, at
      // `--control-h`) holding buttons inset by the well's own padding. A
      // sweep that counts the segments reports two heights for a bar that
      // has one, which is what the first version of this did: 28px and 36px,
      // where the 28s were the two halves of the Cards/Rows switch inside a
      // 36px well.
      const controls = [...dock.querySelectorAll('button, input, select, summary, .seg, .segmented-control')]
        .filter((e) => e.checkVisibility && e.checkVisibility({ visibilityProperty: true, opacityProperty: true }))
        .filter((e) => !e.closest('.seg, .segmented-control') || e.matches('.seg, .segmented-control'));
      const rows = new Map();
      for (const c of controls) {
        const top = Math.round(c.getBoundingClientRect().top);
        rows.set(top, (rows.get(top) || 0) + 1);
      }
      const heights = {};
      for (const c of controls) {
        const h = Math.round(c.getBoundingClientRect().height);
        (heights[h] = heights[h] || []).push(
          `${c.tagName.toLowerCase()}${c.id ? '#' + c.id : '.' + (c.className || '').split(/\s+/)[0]}`,
        );
      }
      const actions = dock.querySelector('.dock-actions');
      const zones = [...dock.children].map((z) => {
        const r = z.getBoundingClientRect();
        return `${z.className.split(/\s+/)[0]} ${Math.round(r.width)}x${Math.round(r.height)} top=${Math.round(r.top)}`;
      });
      return {
        dock: `${Math.round(box.width)}x${Math.round(box.height)}`,
        controls: controls.length,
        rows: [...rows.entries()].sort((a, b) => a[0] - b[0]).map(([top, n]) => `${top}:${n}`),
        heights: Object.fromEntries(Object.entries(heights).map(([h, ids]) => [h, ids.length])),
        tallest: Object.keys(heights).map(Number).sort((a, b) => b - a)[0],
        shortest: Object.keys(heights).map(Number).sort((a, b) => a - b)[0],
        byHeight: Object.fromEntries(Object.entries(heights).map(([h, ids]) => [h, ids.slice(0, 6).join(' ')])),
        actionsWrap: actions ? getComputedStyle(actions).flexWrap : 'no .dock-actions',
        dockWrap: getComputedStyle(dock).flexWrap,
        zones,
      };
    });
    if (!m) {
      console.log(`== ${width}px: no boards dock`);
      bad += 1;
    } else {
      const oneHeight = m.tallest === m.shortest;
      const oneRow = m.rows.length === 1;
      if (!oneHeight) bad += 1;
      if (!oneRow && width >= 1440) bad += 1;
      console.log(
        `== ${width}px: dock ${m.dock}, ${m.controls} controls on ${m.rows.length} row(s) [${m.rows.join(' ')}]\n`
        + `   heights ${JSON.stringify(m.heights)}${oneHeight ? '' : '  <- more than one height'}\n`
        + `   ${Object.entries(m.byHeight).map(([h, ids]) => `${h}px: ${ids}`).join('\n   ')}\n`
        + `   dock flex-wrap ${m.dockWrap}, .dock-actions flex-wrap ${m.actionsWrap}\n`
        + `   zones: ${m.zones.join(' | ')}`,
      );
    }
    await browser.close();
  }
  console.log(bad ? `FAIL: ${bad} findings` : 'PASS: 0 findings');
  process.exit(bad ? 1 : 0);
})();
