// The Links sub-tab's rows (the owner, 2026-09-13: "is there a wya to redesign
// the links cards/rows in the links library subtab to make them look nicer and
// more modern??").
//
// What it reports, per width: one row height or several, the type sizes inside
// a row, how many controls sit on a row at rest, whether a row wraps (its
// children clustered by vertical centre, the same reading `popupdialogs.js`
// uses so a 16px line beside a 28px button is not read as a wrap), and the
// gap between rows. Seeds eight bookmarks the first time it meets an empty
// notebook, one of them grouped and one with a long title, because a row list
// only shows its problems when the rows differ.
//
//   BASE=http://127.0.0.1:8938 SCRATCH=/tmp/x THEME=dark \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/linkrows.js
const { boot } = require('./lib.js');

const SEED = [
  { url: 'https://news.ycombinator.com/news', title: 'Hacker News' },
  { url: 'https://developer.mozilla.org/en-US/docs/Web/CSS/grid-template-rows', title: 'CSS grid-template-rows, and everything it does to a subgrid', group_name: 'Work/Reading' },
  { url: 'https://www.gutenberg.org/ebooks/84', title: '', group_name: 'Work/Reading' },
  { url: 'https://example.com/a/very/long/path/that/keeps/going/and/going?with=a&query=string', title: 'A page with a long address' },
  { url: 'https://sqlite.org/lang_select.html', title: 'SELECT', group_name: 'Reference' },
  { url: 'https://www.w3.org/WAI/ARIA/apg/patterns/toolbar/', title: 'Toolbar pattern', group_name: 'Reference' },
  { url: 'https://openstreetmap.org', title: 'OpenStreetMap' },
  { url: 'https://arxiv.org/list/cs.HC/recent', title: 'Recent human-computer interaction papers' },
];

(async () => {
  const { browser, page, OUT } = await boot();
  await page.evaluate(async (seed) => {
    const have = await (await api('/bookmarks')).json();
    const rows = Array.isArray(have) ? have : have.items || [];
    if (rows.length) return;
    for (const b of seed) await api('/bookmarks', { method: 'POST', body: JSON.stringify(b) });
  }, SEED);
  await page.evaluate(() => switchTab('library'));
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#library-subtabs button')].find((e) => /link/i.test(e.textContent));
    if (b) b.click();
  });
  await page.waitForTimeout(1200);

  const probe = () => {
    const rows = [...document.querySelectorAll('#bookmark-list .bookmark-row')];
    const seen = (el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const read = (r) => {
      const box = r.getBoundingClientRect();
      const controls = [...r.querySelectorAll('button, input, a, summary')].filter(seen);
      // Lines: distinct vertical centres among the row's own leaf content.
      const mids = [];
      for (const el of [...r.querySelectorAll('*')].filter((e) => seen(e) && !e.children.length)) {
        const b = el.getBoundingClientRect();
        const mid = b.top + b.height / 2;
        if (!mids.some((m) => Math.abs(m - mid) < 6)) mids.push(mid);
      }
      return {
        h: +box.height.toFixed(1),
        controls: controls.length,
        lines: mids.length,
        // Only elements that draw their own words: a wrapper inherits the
        // body's 16px and says nothing about what the row looks like.
        sizes: [...new Set([...r.querySelectorAll('*')]
          .filter((e) => seen(e) && !e.children.length && (e.textContent || '').trim())
          .map((e) => getComputedStyle(e).fontSize))].sort(),
        ctrlH: [...new Set(controls.map((c) => +c.getBoundingClientRect().height.toFixed(1)))].sort((a, b) => a - b),
      };
    };
    const list = document.getElementById('bookmark-list');
    const boxes = rows.map((r) => r.getBoundingClientRect());
    const gaps = boxes.slice(1).map((b, i) => +(b.top - boxes[i].bottom).toFixed(1));
    return {
      rows: rows.length,
      heights: [...new Set(rows.map((r) => +r.getBoundingClientRect().height.toFixed(1)))].sort((a, b) => a - b),
      gaps: [...new Set(gaps)],
      listW: list ? Math.round(list.getBoundingClientRect().width) : null,
      each: rows.map(read),
      overflow: rows.filter((r) => r.scrollWidth > r.clientWidth + 1).length,
    };
  };

  for (const w of [1440, 1024, 820]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.waitForTimeout(600);
    const r = await page.evaluate(probe);
    console.log(w, JSON.stringify({ rows: r.rows, heights: r.heights, gaps: r.gaps, listW: r.listW, overflow: r.overflow }));
    console.log(w, 'each', JSON.stringify(r.each));
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/linkrows-${process.env.THEME || 'light'}.png`, clip: { x: 240, y: 120, width: 1180, height: 620 } });
  console.log('shot in ' + OUT);
  await browser.close();
})();
