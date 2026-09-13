// Seed a notebook with enough notes, spread over enough months, that the
// Timeline is measuring a real screen rather than an empty state. Notes go in
// through the API (so categories, tags and the search index are all real) and
// their `created_at` is back-dated afterwards by `seed-timeline.py`, because
// `POST /entries` has no "pretend this was written in June" field and should
// not grow one.
const { boot } = require('./lib.js');
const CATS = ["Work", "Personal", "Ideas", "Reading", "Health", "Travel"];
const TAGS = [["work", "planning"], ["personal"], ["ideas", "memorymap"], ["reading"], ["health"], ["travel", "trip"], ["work", "meetings"], ["ideas"], ["reading", "notes"], ["personal", "admin"]];
(async () => {
  const { browser, page } = await boot();
  const r = await page.evaluate(async (args) => {
    const { CATS, TAGS } = args;
    const post = async (url, body) => { try { const r = await api(url, { method: 'POST', body: JSON.stringify(body) }); return r.status || r.id || 'ok'; } catch (e) { return String(e).slice(0, 60); } };
    const titles = [
      "Weekly review", "Dentist appointment", "Reading list", "Mindmap idea", "Meeting with Sam",
      "Tomato soup recipe", "Sprint retro", "Passport renewal", "Q4 planning notes", "Book: Thinking in Systems",
      "Running log", "Trip to Kyoto", "Design tokens", "Interview notes", "Budget for the quarter",
      "Garden plan", "Podcast notes", "Refactor the graph", "Doctor follow up", "Conference talk draft",
      "Onboarding checklist", "Bike service", "Wine notes", "Team offsite", "Piano practice",
      "Server migration", "Birthday plans", "Paper on attention", "Kitchen renovation", "Standup notes",
      "Marathon training", "Photography trip", "API redesign", "Insurance renewal", "Reading: everyday things",
      "Hiring loop", "Camping list", "Database indexes", "Dinner party menu", "Retro actions",
      "Language practice", "Backlog grooming", "Museum visit", "Cache strategy", "Spring cleaning",
      "Product strategy", "Yoga class", "Note taking systems"
    ];
    const bodies = [
      "Shipped the sweep tooling; next is component consistency by count, then the reform.",
      "Ask about the retainer and whether the follow up can be the same week.",
      "Three books queued, one half finished, and a fourth someone recommended twice.",
      "A node on the board can be a real note. Tab adds a child, Enter a sibling.",
      "Agreed the plan, three workstreams, review on the twentieth of the month.",
      "Roast the tomatoes first and add a little smoked paprika at the end.",
      "What went well: measuring before changing. What did not: reading instead of running.",
      "Do this before March or the trip in the spring becomes a problem.",
      "Two bets, one maintenance track, and an explicit list of what is not being done.",
      "Stocks and flows, and why a delay in a feedback loop makes a system oscillate.",
    ];
    const out = [];
    for (let i = 0; i < 48; i++) {
      const title = titles[i % titles.length];
      const body = bodies[i % bodies.length];
      out.push(await post('/entries', { content: `# ${title}\n\n${body}`, tags: TAGS[i % TAGS.length], category: CATS[i % CATS.length] }));
    }
    return out.length;
  }, { CATS, TAGS });
  console.log('seeded', r);
  await browser.close();
})();
