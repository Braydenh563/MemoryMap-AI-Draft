// A board worth photographing.
//
// `seed-boards.js` makes the board whose *preview* the sweeps measure: five
// plain boxes, deliberately different sizes, no colour. That is the right
// fixture for a preview test and the wrong one for the README, where the
// whiteboard shot came out as four grey rectangles with the top card cut off
// and two thirds of the canvas empty.
//
// So this seeds a second board, laid out to fill a 1440x900 window at the
// default zoom: a banner, three columns of coloured cards, and a note off to
// the side. Nothing here is a state a person could not produce with the board's
// own tools, the colours are the ones the properties panel offers, and the
// text is the sort of thing a board actually holds.
//
//   BASE=http://127.0.0.1:8935 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/seed-boardrich.js
const { boot } = require('./lib.js');

// x, y, width, height, text, background, border. Laid out on the board's own
// coordinates: the banner across the top, then three columns 260 apart.
const CARDS = [
  [40, 30, 860, 70, 'Website relaunch', '#4f6df5', '#4f6df5'],
  [40, 140, 240, 44, 'Now', null, null],
  [40, 200, 240, 110, 'Rewrite the landing copy: one sentence, then the proof', '#1f3a5f', '#3d6fb8'],
  [40, 330, 240, 110, 'Photograph the three product shots', '#1f3a5f', '#3d6fb8'],
  [320, 140, 240, 44, 'Next', null, null],
  [320, 200, 240, 110, 'Move the pricing table above the fold', '#2c3a22', '#5f8f3f'],
  [320, 330, 240, 110, 'Cut the sign-up form from nine fields to four', '#2c3a22', '#5f8f3f'],
  [320, 460, 240, 110, 'Decide on the new type scale', '#2c3a22', '#5f8f3f'],
  [600, 140, 300, 44, 'Waiting on someone else', null, null],
  [600, 200, 300, 110, 'Legal have the licence question until Thursday', '#4a2c2c', '#b85555'],
  [600, 330, 300, 150, 'Notes from the review: the hero reads as three competing offers. Pick one.', null, '#6b7280'],
];

(async () => {
  const { browser, page } = await boot();
  const made = await page.evaluate(async (cards) => {
    // `api()` (app.js) rather than a bare fetch: the app holds the unlock
    // token, and a plain fetch to the same path comes back 401.
    const post = async (path, body) =>
      (await api(path, { method: 'POST', body: JSON.stringify(body) })).json();
    const board = await post('/whiteboard/boards', { name: 'Website relaunch', type: 'board' });
    for (const [x, y, width, height, content, bg, border] of cards) {
      await post('/whiteboard/objects', {
        kind: 'text',
        board_id: board.id,
        x,
        y,
        width,
        height,
        data: {
          content,
          ...(bg ? { bg } : {}),
          ...(border ? { border_color: border } : {}),
        },
      });
    }
    return { board: board.id, cards: cards.length };
  }, CARDS);
  console.log('seeded', JSON.stringify(made));
  await browser.close();
})();
