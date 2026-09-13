// The Settings -> Logs head, measured the way docks.js measures a tab's dock:
// one height per row, how many controls the eye counts, and which zones the
// row is built from. docks.js itself walks the seven tabs and never opens the
// settings modal, so this is the same reading for the one dock that lives
// inside it. Run: BASE=… PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node logsdock.js
const {boot} = require('/home/user/MemoryMap-AI/scratchpad/ui-sweeps/lib.js');
(async () => {
  const {browser, page, OUT} = await boot();
  await page.evaluate(() => openSettingsModal('logs'));
  await page.waitForTimeout(1200);
  for (const w of [1440, 1024, 820]) {
    await page.setViewportSize({width: w, height: 900});
    await page.waitForTimeout(500);
    const r = await page.evaluate(() => {
      const head = document.querySelector('#settings-logs .dock, #settings-logs .log-toolbar');
      if (!head) return {missing: true};
      const WRAP = '.seg, .segmented-control, .select-shell';
      const ctrls = [...head.querySelectorAll('button, select, input, .seg, .segmented-control, .select-shell, label')]
        .filter(c => {
          const b = c.getBoundingClientRect();
          if (b.width <= 0 || b.height <= 0) return false;
          if (c.closest('.doc-dock-menu-list, .dock-menu-list')) return false;
          if (c.matches('.dock-native-hidden, .dock-menu-label, .visually-hidden')) return false;
          const wrap = c.closest(WRAP);
          return !(wrap && wrap !== c);
        });
      const box = head.getBoundingClientRect();
      // Rows, clustered by each control's vertical centre: a bar that wraps
      // reports two rows, which is the whole question here.
      const rows = [];
      for (const c of ctrls) {
        const b = c.getBoundingClientRect();
        const mid = b.top + b.height / 2;
        const row = rows.find(r => Math.abs(r.mid - mid) < 8);
        if (row) { row.n += 1; row.mid = (row.mid * (row.n - 1) + mid) / row.n; }
        else rows.push({mid, n: 1});
      }
      return {
        h: +box.height.toFixed(1),
        controls: ctrls.length,
        rows: rows.length,
        heights: [...new Set(ctrls.map(c => +c.getBoundingClientRect().height.toFixed(1)))].sort((a, b) => a - b),
        zones: [...head.children].map(e => [...e.classList].find(c => c.startsWith('dock-')) || e.tagName.toLowerCase()),
        ids: ctrls.map(c => c.id || c.tagName.toLowerCase()),
      };
    });
    console.log(w, JSON.stringify(r));
  }
  await page.setViewportSize({width: 1440, height: 900});
  await page.waitForTimeout(400);
  await page.screenshot({path: OUT + '/logs-dock.png', clip: {x: 300, y: 80, width: 1100, height: 320}});
  await browser.close();
})();
