// Eight notes a person could actually have written, newest in the notebook.
//
// `seed-timeline.js` fills a notebook with 48 notes for density: it pairs 48
// titles against 10 bodies by index, which is right for measuring a timeline
// and wrong for a screenshot, where it produces "Product strategy: roast the
// tomatoes first and add a little smoked paprika". The README's Notes shot is
// sorted newest first, so seeding these last puts eight coherent cards at the
// top of it without touching a fixture other sweeps measure against.
//
// Nothing here is special-cased for the camera: they are ordinary notes
// through `POST /entries`, with the categories and tags the app itself uses.
//
//   BASE=http://127.0.0.1:8941 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/seed-readme.js
const { boot } = require('./lib.js');

const NOTES = [
  [
    '# Why the graph felt slow\n\nIt was not the physics. The simulation kept ticking after leaving the tab, so every other screen paid for it. Stopping it on navigate fixed the whole class.',
    ['engineering', 'performance'],
    'Work',
  ],
  [
    '# Bread, third attempt\n\nLonger cold proof, 20 hours. Better crumb, still pale on the bottom: try the stone lower next time.',
    ['cooking', 'baking'],
    'Personal',
  ],
  [
    '# Reading: Thinking in Systems\n\nStocks and flows, and why a delay inside a feedback loop makes a system oscillate instead of settle.',
    ['reading', 'systems'],
    'Reading',
  ],
  [
    '# Kyoto, what to book first\n\nThe ryokan in Arashiyama fills six months out. Trains can wait; that cannot.',
    ['travel', 'planning'],
    'Travel',
  ],
  [
    '# Retro: what actually helped\n\nMeasuring before changing. What did not: reading the source instead of running it, twice in one week.',
    ['work', 'retro'],
    'Work',
  ],
  [
    '# Mind map idea\n\nA node on a board can be a real note, so the map and the notebook stay one thing. Tab adds a branch, Enter one beside it.',
    ['ideas', 'memorymap'],
    'Ideas',
  ],
  [
    '# Half marathon, week 4\n\nEasy pace is still too fast. Slow the Tuesday run down until it is boring, then hold it.',
    ['running', 'health'],
    'Health',
  ],
  [
    '# Questions for Thursday\n\nWho owns the migration after launch, and what happens to the old export format when it goes.',
    ['work', 'meetings'],
    'Work',
  ],
];

(async () => {
  const { browser, page } = await boot();
  const made = await page.evaluate(async (notes) => {
    const out = [];
    for (const [content, tags, category] of notes) {
      const r = await api('/entries', {
        method: 'POST',
        body: JSON.stringify({ content, tags, category }),
      });
      out.push(r.status);
      // One at a time and in order: `created_at` is what "newest first" sorts
      // on, and a burst of eight in the same second sorts by id, which is the
      // same order anyway but for the wrong reason.
      await new Promise((r2) => setTimeout(r2, 120));
    }
    return out;
  }, NOTES);
  console.log('seeded', JSON.stringify(made));
  await browser.close();
})();
