// A whiteboard and a mind map with real, *differently sized* things on them,
// so a preview has something to be right or wrong about (INBOX 68). The
// stock seed makes notes only, and a board list with nothing in it previews
// as the empty state, which is the one case that already looked fine.
//
//   BASE=http://127.0.0.1:8811 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/seed-boards.js
const { boot } = require('./lib.js');

(async () => {
  const { browser, page } = await boot();

  const made = await page.evaluate(async () => {
    // `api()` (app.js), not a bare fetch: the app holds an unlock token and a
    // plain fetch to the same path comes back 401 "Locked: unlock first".
    // `api()` (app.js), not a bare fetch: the app holds an unlock token and a
    // plain fetch to the same path comes back 401 "Locked: unlock first".
    // It throws on a non-2xx of its own accord, so a bad body shows up as a
    // message rather than as a silently empty board.
    const post = async (path, body) => (await api(path, { method: 'POST', body: JSON.stringify(body) })).json();

    // 1. A whiteboard whose objects are genuinely different shapes and sizes:
    //    a banner across the top, a tall column, two small stickies and a
    //    wide footnote. This is the board whose preview the owner called
    //    "grey blobs".
    const board = await post('/whiteboard/boards', { name: 'Launch plan', type: 'board' });
    const shapes = [
      { x: 40, y: 40, width: 760, height: 120, text: 'Launch plan' },
      { x: 40, y: 200, width: 220, height: 420, text: 'Backlog' },
      { x: 300, y: 200, width: 180, height: 140, text: 'Ship the editor' },
      { x: 300, y: 380, width: 180, height: 140, text: 'Ship the graph' },
      { x: 520, y: 200, width: 280, height: 90, text: 'Blocked on the licence question' },
    ];
    for (const s of shapes) {
      await post('/whiteboard/objects', {
        kind: 'text',
        board_id: board.id,
        x: s.x,
        y: s.y,
        width: s.width,
        height: s.height,
        data: { content: s.text },
      });
    }

    // 2. A mind map: a root, three branches and two leaves, so the preview
    //    has a tree to draw and labels to place.
    const map = await post('/whiteboard/boards', { name: 'Bubble tea', type: 'map' });
    // `POST /whiteboard/boards/{id}/nodes`, not the generic object create:
    // the parent link is a column on the row, and only this route sets it.
    // A tree built through /objects has no edges and previews as a scatter,
    // which is the bug this seed exists to be able to see.
    const topic = async (content, x, y, parent) => post(`/whiteboard/boards/${map.id}/nodes`, {
      kind: 'topic',
      text: content,
      x,
      y,
      ...(parent ? { parent_id: parent } : {}),
    });
    const root = await topic('Bubble tea', 420, 300, null);
    const brew = await topic('Brewing', 120, 160, root.id);
    const milk = await topic('Milk and syrup', 120, 420, root.id);
    const pearls = await topic('Pearls', 760, 300, root.id);
    await topic('Oolong, 3 minutes', 60, 60, brew.id);
    await topic('Brown sugar', 60, 520, milk.id);
    return { board: board.id, map: map.id, pearls: pearls.id };
  });

  console.log('seeded', JSON.stringify(made));
  await browser.close();
})();
