// TIMELINE_PLAN.md Phase 2's gate, as numbers.
//
// The plan: "sort by each column round-trips; selection bar actions apply to
// the selected rows; two columns only below 600px", plus the promise that the
// icon segment switches views "with no reload of data".
//
//   BASE=http://127.0.0.1:8936 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     SCRATCH=/tmp/claude-0 timeout 110 node timelinetable.js
//
// Seed first (seed-timeline.js, then seed-timeline.py).
const { boot } = require('./lib.js');

let failures = 0;
const check = (label, ok, detail) => {
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}  ${detail}`);
};

(async () => {
  const { browser, page, OUT } = await boot();
  let timelineCalls = 0;
  page.on('request', (r) => {
    if (r.url().includes('/timeline?')) timelineCalls += 1;
  });
  await page.click('[data-tab="timeline"]');
  await page.waitForTimeout(1000);
  const afterLoad = timelineCalls;

  await page.click('#timeline-view-table');
  await page.waitForTimeout(600);
  const shape = await page.evaluate(() => {
    const table = document.getElementById('timeline-table');
    const scroll = document.getElementById('timeline-scroll');
    const head = table.querySelector('thead th:nth-child(2)');
    return {
      shown: !table.classList.contains('hidden'),
      feedHidden: document.getElementById('timeline-feed').classList.contains('hidden'),
      rows: table.querySelectorAll('tbody tr').length,
      columns: [...table.querySelectorAll('thead th')].filter((th) => th.getBoundingClientRect().width > 0).length,
      headSticky: getComputedStyle(head).position,
      overflowX: scroll.scrollWidth - scroll.clientWidth,
      docOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
  check('1440 the table shows instead of the feed', shape.shown && shape.feedHidden, `${shape.rows} rows, ${shape.columns} columns`);
  check('1440 the head is sticky', shape.headSticky === 'sticky', `position=${shape.headSticky}`);
  check('1440 no horizontal scroll', shape.overflowX <= 0 && shape.docOverflowX <= 0, `box=${shape.overflowX}px doc=${shape.docOverflowX}px`);
  check('switching views costs no request', timelineCalls === afterLoad, `${timelineCalls - afterLoad} requests since the tab loaded`);

  // Sticky, measured: scroll the table and ask where the head sits.
  const stuck = await page.evaluate(() => {
    const scroll = document.getElementById('timeline-scroll');
    const before = scroll.scrollTop;
    scroll.scrollTop = before + 300;
    const head = document.querySelector('#timeline-table thead th:nth-child(2)');
    return {
      scrolled: scroll.scrollTop - before,
      gap: Math.round(head.getBoundingClientRect().top - scroll.getBoundingClientRect().top),
    };
  });
  check('1440 the head stays pinned after scrolling', stuck.scrolled > 0 && stuck.gap <= 4,
    `scrolled ${stuck.scrolled}px, head sits ${stuck.gap}px below the top`);
  await page.evaluate(() => {
    document.getElementById('timeline-scroll').scrollTop = 0;
  });

  // Every column sorts, and clicking it again turns it around. The measurement
  // is the column's own values, not the row ids: three of these columns are one
  // value all the way down in a seeded notebook (every row is a Note, in one
  // space, with no links), and "the ids changed" would fail a correct sort on
  // a tied column while passing a broken one on a varied column. What must
  // hold is that the values are ordered, and ordered the other way after the
  // second click.
  const COLUMN_AT = { when: 2, title: 3, kind: 4, category: 5, space: 6, tags: 7, words: 8, links: 9 };
  for (const [key, nth] of Object.entries(COLUMN_AT)) {
    const result = await page.evaluate(async (args) => {
      const { sortKey, nth } = args;
      const read = () =>
        [...document.querySelectorAll('#timeline-table-body tr')].map((tr) => {
          const cell = tr.children[nth - 1];
          const text = cell ? cell.textContent.trim() : '';
          if (sortKey === 'when') return new Date(tr.querySelector('time').dateTime).getTime();
          if (sortKey === 'words' || sortKey === 'links') return text === '' ? null : Number(text);
          return text.toLowerCase();
        });
      const ordered = (values, dir) => {
        for (let i = 1; i < values.length; i++) {
          const a = values[i - 1];
          const b = values[i];
          if (a === null || b === null) continue;
          const cmp = typeof a === 'number' ? a - b : String(a).localeCompare(String(b));
          if (dir === 'ascending' ? cmp > 0 : cmp < 0) return false;
        }
        return true;
      };
      const button = document.querySelector(`.timeline-sort[data-sort="${sortKey}"]`);
      button.click();
      await new Promise((r) => setTimeout(r, 150));
      const firstDir = button.closest('th').getAttribute('aria-sort');
      const firstOk = ordered(read(), firstDir);
      button.click();
      await new Promise((r) => setTimeout(r, 150));
      const secondDir = button.closest('th').getAttribute('aria-sort');
      const secondOk = ordered(read(), secondDir);
      return { rows: read().length, firstDir, firstOk, secondDir, secondOk };
    }, { sortKey: key, nth });
    check(`sort by ${key} round-trips`,
      result.rows > 0 && result.firstOk && result.secondOk && result.firstDir !== result.secondDir,
      `${result.rows} rows, ${result.firstDir} ordered=${result.firstOk}, then ${result.secondDir} ordered=${result.secondOk}`);
  }

  // The selection bar drives the Notes list's own batch actions over the rows
  // ticked here. Tag two rows, then read the notes back from the API.
  const selected = await page.evaluate(async () => {
    document.getElementById('timeline-options-menu').open = true;
    document.getElementById('timeline-select-btn').click();
    await new Promise((r) => setTimeout(r, 400));
    const rows = [...document.querySelectorAll('#timeline-table-body tr')].slice(0, 2);
    for (const row of rows) row.querySelector('.select-check').click();
    await new Promise((r) => setTimeout(r, 200));
    return {
      barShown: !document.getElementById('timeline-batch-bar').classList.contains('hidden'),
      count: document.getElementById('timeline-batch-count').textContent,
      ids: rows.map((r) => Number(r.dataset.id)),
      boxes: document.querySelectorAll('#timeline-table-body .select-check').length,
    };
  });
  check('the selection bar appears with a count', selected.barShown && selected.count === '2 selected',
    `${selected.count}, ${selected.boxes} tick boxes`);

  const tagged = await page.evaluate(async (ids) => {
    document.getElementById('timeline-batch-tag').click();
    await new Promise((r) => setTimeout(r, 400));
    // `promptDialog` builds its own overlay per call (app.js): find the one
    // that is actually open rather than the first `.modal-card` in the page,
    // which is a settings dialog that has never been shown.
    const card = [...document.querySelectorAll('.prompt-card')].pop();
    if (!card) return { ok: false, why: 'no prompt dialog' };
    const input = card.querySelector('input[type="text"]');
    if (!input) return { ok: false, why: 'no field in the prompt dialog' };
    input.value = 'sweepmark';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const confirm = [...card.querySelectorAll('button')].find((b) => /add tag/i.test(b.textContent));
    if (!confirm) return { ok: false, why: 'no confirm button' };
    confirm.click();
    await new Promise((r) => setTimeout(r, 1500));
    const out = [];
    for (const id of ids) {
      const entry = await apiJson(`/entries/${id}`);
      out.push({ id, tags: entry.tags });
    }
    return { ok: true, out, barGone: document.getElementById('timeline-batch-bar').classList.contains('hidden') };
  }, selected.ids);
  check('a bulk action applies to the selected rows',
    tagged.ok && tagged.out.every((e) => e.tags.includes('sweepmark')) && tagged.barGone,
    tagged.ok ? `${tagged.out.map((e) => `${e.id}:${e.tags.join('|')}`).join(' ')}` : tagged.why);

  // Two columns below 600px.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(700);
  const phone = await page.evaluate(() => {
    const table = document.getElementById('timeline-table');
    const scroll = document.getElementById('timeline-scroll');
    return {
      columns: [...table.querySelectorAll('thead th')].filter((th) => th.getBoundingClientRect().width > 0)
        .map((th) => th.textContent.trim()),
      overflowX: scroll.scrollWidth - scroll.clientWidth,
      docOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
  // The select column is not a data column: it exists only while the selection
  // mode is on, and the plan's "two columns" is about what a note shows.
  const dataColumns = phone.columns.filter((c) => c !== 'Selected');
  check('390 two columns only', dataColumns.length === 2, `columns: ${phone.columns.join(', ')}`);
  check('390 no horizontal scroll', phone.overflowX <= 0 && phone.docOverflowX <= 0,
    `box=${phone.overflowX}px doc=${phone.docOverflowX}px`);
  await page.screenshot({ path: `${OUT}/timeline-table-390.png` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/timeline-table-1440.png` });

  await browser.close();
  console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
})();
