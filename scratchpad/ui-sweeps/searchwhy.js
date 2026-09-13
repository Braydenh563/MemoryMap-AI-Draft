// The Notes list's "why this result" line, measured in the running app
// (Brief 11). Seeds four notes with one link between two of them, types a
// query, and reads the chips back out of the DOM with their computed styles:
// a screenshot would not say whether the words are the engine's or the
// browser's guess, and this does.
//
//   BASE=http://127.0.0.1:8793 node scratchpad/ui-sweeps/searchwhy.js
const { boot } = require('./lib');

(async () => {
  const { browser, page } = await boot();
  const api = async (path, init) =>
    page.evaluate(
      async ([p, i]) => {
        const res = await fetch(p, {
          ...(i || {}),
          headers: { 'Content-Type': 'application/json', 'X-Auth-Token': localStorage.getItem('token') || '' },
        });
        return { status: res.status, body: await res.json().catch(() => null) };
      },
      [path, init]
    );

  const notes = [
    'sourdough starter needs feeding twice a day',
    'seedlings hardening off before the frost',
    'seedlings from a different year entirely',
    'the plan for the season, beds and rotation',
  ];
  const made = [];
  for (const content of notes) {
    const res = await api('/entries', { method: 'POST', body: JSON.stringify({ content }) });
    made.push(res.body && res.body.id);
  }
  // A link, so the graph signal has something to say when a note is open.
  const linked = await api(`/entries/${made[3]}/links`, { method: 'POST', body: JSON.stringify({ target_id: made[1] }) });
  console.log('link', made[3], '->', made[1], 'status', linked.status);

  const hits = await api('/search?q=seedlings&kind=note,board');
  console.log('GET /search status', hits.status);
  for (const hit of (hits.body && hits.body.hits) || []) {
    console.log('  hit', hit.id, hit.kind, JSON.stringify(hit.scores), hit.explain.join(' · '));
  }

  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(600);
  // Rows view: the open/close control only exists there, and an opened-out
  // row is what this list means by "the note you have open".
  await page.click('#notes-view-rows').catch(() => {});
  await page.waitForTimeout(1500);
  // The notes list is loaded once at boot, so the four notes made above by
  // fetch are not in it yet; the tab's own refresh is what brings them in.
  await page.evaluate(() => (window.loadEntries ? window.loadEntries() : null)).catch(() => {});
  await page.waitForTimeout(1200);
  // Open the note the links run from, so the third signal has a context: the
  // list passes the one expanded row as `entry_id`.
  await page.click(`#entry-list li[data-id="${made[3]}"] .row-expand`).catch(() => {});
  await page.waitForTimeout(500);
  console.log('rows opened out:', await page.evaluate(() => (typeof expandedRows !== 'undefined' ? expandedRows.size : 'n/a')));
  await page.fill('#note-search', 'seedlings');
  await page.waitForTimeout(1800);
  console.log('reasons held:', await page.evaluate(() => (typeof noteSearchWhy !== 'undefined' ? [...noteSearchWhy.values()].map((h) => [h.id, h.scores.graph, h.explain.join('/')]) : 'n/a')));

  const measured = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#entry-list > li')];
    return rows.map((li) => {
      const chip = li.querySelector('.result-reason-why');
      const rect = chip ? chip.getBoundingClientRect() : null;
      const style = chip ? getComputedStyle(chip) : null;
      return {
        id: li.dataset.id,
        text: (li.querySelector('.entry-content')?.textContent || '').slice(0, 40),
        why: chip ? chip.textContent.trim() : null,
        title: chip ? chip.title : null,
        fontSize: style ? style.fontSize : null,
        colour: style ? style.color : null,
        width: rect ? Math.round(rect.width) : 0,
        // Clipped *inside* the chip (the ellipsis doing its job) and spilling
        // *outside* the row (a layout fault) are different failures, so both
        // are measured rather than one standing in for the other.
        ellipsised: chip ? chip.scrollWidth > chip.clientWidth + 1 : false,
        pastTheRow: rect ? Math.round(rect.right - li.getBoundingClientRect().right) : 0,
        pastTheMeta: rect
          ? Math.round(rect.right - li.querySelector('.entry-meta').getBoundingClientRect().right)
          : 0,
        metaScrolls: (() => {
          const meta = li.querySelector('.entry-meta');
          return meta.scrollWidth > meta.clientWidth + 1;
        })(),
        rowHeight: Math.round(li.getBoundingClientRect().height),
        rowScrolls: li.scrollWidth > li.clientWidth + 1,
        // The same two numbers for a chip that was already there before this
        // line existed (the category chip): a spill both of them share is the
        // row's layout, not the new chip's.
        catPastTheRow: (() => {
          const first = li.querySelector('.entry-meta .chip:not(.result-reason-why)');
          if (!first) return null;
          return Math.round(first.getBoundingClientRect().right - li.getBoundingClientRect().right);
        })(),
        metaWidth: Math.round(li.querySelector('.entry-meta').getBoundingClientRect().width),
        metaWraps: (() => {
          const meta = li.querySelector('.entry-meta');
          return getComputedStyle(meta).flexWrap + '/' + getComputedStyle(meta).display;
        })(),
      };
    });
  });
  console.log('rows in the filtered list:', measured.length);
  for (const row of measured) console.log(' ', JSON.stringify(row));

  await page.fill('#note-search', '');
  await page.waitForTimeout(700);
  const afterClear = await page.evaluate(() => document.querySelectorAll('.result-reason-why').length);
  console.log('reason chips after clearing the box:', afterClear);

  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/shots/search-why.png' });
  await browser.close();
})();
