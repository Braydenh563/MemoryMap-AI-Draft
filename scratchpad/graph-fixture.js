// Build the graph gate's fixture: ~2,000 notes with ~4,000 links.
//
//   BASE=http://127.0.0.1:8812 node scratchpad/graph-fixture.js [notes] [links]
//
// GRAPH_PLAN.md §5 Phase 1's gate is stated in numbers ("a 2,000-note fixture
// ... paints its first frame < 300 ms"), and there is no way to measure any of
// them against the eight-note seed the other sweeps use. This builds the
// notebook through the app's own API from inside the page — `api()` is app.js's
// fetch wrapper and already carries the session cookie and the CSRF header, so
// driving it in `page.evaluate` needs no second auth path.
//
// **Batched, not one request per note.** The first draft posted 2,000 entries
// serially and took minutes; these go out in waves of 40 concurrent POSTs,
// which is what a single SQLite writer will take without the queue backing up
// into 500s. Links go the same way, after every note id is known.
//
// Idempotent enough: it counts what is already there first and only tops up
// the difference, so re-running it on the same data dir is cheap.
const { boot } = require("./ui-sweeps/lib.js");

const WANT_NOTES = Number(process.argv[2] || 2000);
const WANT_LINKS = Number(process.argv[3] || 4000);

(async () => {
  const { browser, page } = await boot();
  const started = Date.now();
  const result = await page.evaluate(
    async ({ wantNotes, wantLinks }) => {
      const CATEGORIES = [
        "Work", "Reading", "Ideas", "Personal", "Research",
        "Projects", "Admin", "Health", "Cooking", "Travel",
      ];
      const WORDS = (
        "graph canvas render worker force layout notebook memory link cluster " +
        "note draft review sketch measure token design system phase plan gate"
      ).split(" ");
      // A deterministic pseudo-random source: a fixture that differs run to run
      // makes a frame-time regression impossible to attribute.
      let seed = 20260908;
      const rand = () => {
        seed = (seed * 1103515245 + 12345) & 0x7fffffff;
        return seed / 0x7fffffff;
      };
      const sentence = (n) =>
        Array.from({ length: 8 + (n % 12) }, () => WORDS[Math.floor(rand() * WORDS.length)]).join(" ");

      // `/entries` answers with a bare JSON array; every other list endpoint in
      // this app answers with `{items: […]}` or similar. Normalised here rather
      // than assumed, because a fixture that silently builds nothing looks
      // exactly like a fixture that ran.
      const asList = (value) =>
        Array.isArray(value) ? value : (value && (value.entries || value.items)) || [];
      const listEntries = async () => asList(await api("/entries?limit=5000").then((r) => r.json()));

      const have = (await listEntries()).length;
      const created = [];
      const batched = async (items, run, size) => {
        for (let i = 0; i < items.length; i += size) {
          await Promise.all(items.slice(i, i + size).map(run));
        }
      };

      const todo = Math.max(0, wantNotes - have);
      await batched(
        Array.from({ length: todo }, (_, i) => i),
        async (i) => {
          const category = CATEGORIES[i % CATEGORIES.length];
          const body = {
            // **The category is set explicitly, not left to the filer.** A
            // fixture built without it lands every note in "Uncategorised",
            // which quietly makes three of the things this fixture exists to
            // measure untestable: the legend has one entry, colour-by-category
            // has one colour, and there is no way to filter the map down to a
            // smaller board. Found the hard way — the first 2,000-note run
            // reported "200 notes (from 1 legend entries)".
            category,
            content: `${category} note ${i}: ${sentence(i)}`,
            tags: [category.toLowerCase(), `t${i % 25}`],
          };
          try {
            const response = await api("/entries", { method: "POST", body: JSON.stringify(body) });
            const entry = await response.json();
            if (entry && entry.id) created.push(entry.id);
          } catch (error) {
            /* a failed post is one fewer note, not a failed fixture */
          }
        },
        40
      );

      // Every id, not only the ones this run made, so links can be topped up
      // on a second run against notes the first one created.
      const rows = await listEntries();
      const ids = rows.map((e) => e.id);
      // Notes filed before the `category` field above was passed on create sit
      // in one bucket; re-file them so a data dir built by an older run of this
      // script still measures ten categories rather than one.
      let refiled = 0;
      const stray = rows.filter((e) => !CATEGORIES.includes(e.category));
      await batched(
        stray,
        async (entry) => {
          const wanted = CATEGORIES[ids.indexOf(entry.id) % CATEGORIES.length];
          try {
            await api(`/entries/${entry.id}`, {
              method: "PUT",
              body: JSON.stringify({ category: wanted }),
            });
            refiled += 1;
          } catch (error) {
            /* one note in the wrong bucket is not a failed fixture */
          }
        },
        40
      );
      const linkCount = await api("/graph")
        .then((r) => r.json())
        .then((g) => (g.edges || []).filter((e) => e.kind === "link").length)
        .catch(() => 0);

      let made = 0;
      const wanted = Math.max(0, wantLinks - linkCount);
      // Mostly-local links with a long tail: a graph where every edge is
      // random is a hairball with no clusters in it, which is not what a
      // notebook looks like and not what the renderer has to survive.
      await batched(
        Array.from({ length: wanted }, (_, i) => i),
        async (i) => {
          const from = Math.floor(rand() * ids.length);
          const near = rand() < 0.8;
          const offset = near ? 1 + Math.floor(rand() * 12) : Math.floor(rand() * ids.length);
          const a = ids[from];
          const b = ids[(from + offset) % ids.length];
          if (!a || !b || a === b) return;
          try {
            await api(`/entries/${a}/links`, {
              method: "POST",
              body: JSON.stringify({ target_id: b }),
            });
            made += 1;
          } catch (error) {
            /* duplicate pair, or a note deleted underneath us */
          }
        },
        40
      );
      return {
        have,
        created: created.length,
        refiled,
        notes: ids.length,
        linksBefore: linkCount,
        linksMade: made,
      };
    },
    { wantNotes: WANT_NOTES, wantLinks: WANT_LINKS }
  );
  const graph = await page.evaluate(async () => {
    const g = await api("/graph").then((r) => r.json());
    return { nodes: g.nodes.length, edges: g.edges.length };
  });
  console.log(JSON.stringify({ ...result, ...graph, seconds: Math.round((Date.now() - started) / 1000) }));
  await browser.close();
})();
