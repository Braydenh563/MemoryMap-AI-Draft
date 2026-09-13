// Links between the seeded notes, so the graph shows what a graph is for.
// The README's own caption promises "links between related notes", and a
// notebook seeded by `seed.js` alone has none, so the map was a field of
// unconnected dots.
//
// Pairs are chosen by subject, the way a person's own links would be: the
// reading notes to each other, the work notes to each other, and a few
// cross-links of the kind that make a graph worth looking at.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const out = await page.evaluate(async () => {
    const r = await api('/entries?limit=200');
    const rows = await r.json();
    const find = (needle) =>
      (rows.items || rows).find((e) => (e.content || '').toLowerCase().includes(needle.toLowerCase()));
    const pairs = [
      ['reading list', 'book: thinking in sys'],
      ['reading list', 'wine notes'],
      ['reading: everyday', 'reading list'],
      ['weekly review', 'sprint retro'],
      ['weekly review', 'q4 planning'],
      ['meeting with sam', 'q4 planning'],
      ['meeting with sam', 'standup notes'],
      ['sprint retro', 'refactor the graph'],
      ['api redesign', 'refactor the graph'],
      ['api redesign', 'database indexes'],
      ['cache strategy', 'database indexes'],
      ['idea: a mindmap', 'mindmap idea'],
      ['idea: a mindmap', 'product strategy'],
      ['call the dentist', 'doctor follow up'],
      ['marathon training', 'running log'],
      ['marathon training', 'yoga class'],
      ['recipe: tomato soup', 'dinner party menu'],
      ['trip to kyoto', 'camping list'],
      ['passport renewal', 'trip to kyoto'],
      ['budget for the quarte', 'insurance renewal'],
    ];
    let made = 0;
    const missed = [];
    for (const [a, b] of pairs) {
      const s = find(a);
      const t = find(b);
      if (!s || !t || s.id === t.id) { missed.push(`${a} -> ${b}`); continue; }
      const res = await api(`/entries/${s.id}/links`, {
        method: 'POST',
        body: JSON.stringify({ target_id: t.id, reason: 'Same subject' }),
      }).catch(() => null);
      if (res && res.ok) made += 1; else missed.push(`${a} -> ${b} (${res ? res.status : 'threw'})`);
    }
    return { made, missed };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
