// Live view: do the markdown markers go invisible, and come back when the
// selection reaches them?
//
// The owner: "md formatting should go invisible unless i click back on that
// word or section or navigate with backspace, delete or arrow keys etc to
// where those formatting markers are."
//
// Two halves, and the second is the one nothing checked before. The first is
// an inventory: with the caret parked away from everything, which constructs
// still render their own syntax? That is how the two gaps this sweep was
// written alongside were found (`---` drew a border *and* its three dashes;
// `> [!note]` hid its `>` and kept its `[!note]`). The second is the reveal
// itself, driven through the three gestures the owner named, because they are
// three different code paths into the same selection change and only one of
// them is a keypress the plugin could plausibly miss.
//
// `- a bullet`, `1. a number` and a fenced block's ``` are expected to keep
// their markers: a list without bullets is not a list, and a fence with no
// boundary has none. Tables are Phase 3. Those are recorded as expected
// rather than skipped, so a change that starts hiding them fails here.
//
//   BASE=http://127.0.0.1:8830 node scratchpad/ui-sweeps/cm-reveal.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

// Each line, and what it should render as with the caret elsewhere.
const CASES = [
  ['# H1 heading', 'H1 heading'],
  ['Some **bold** and *em* and ~~struck~~ and `code`.', 'Some bold and em and struck and code.'],
  ['> a block quote', 'a block quote'],
  ['- a bullet', '- a bullet'],
  ['1. a number', '1. a number'],
  ['- [ ] a task', '-  a task'],
  ['---', ''],
  ['==highlighted== and [[wikilink]] and [label](/path).', 'highlighted and wikilink and label.'],
];
// The `Title` / `=====` form. Its underline is a HeaderMark like any other, so
// it was already being hidden while the heading branch matched `ATXHeading`
// only: the markers went and the line stayed body text. Both lines are checked
// here, the second for the hidden underline and the first for the class.
const SETEXT = ['A setext heading', '================'];
// A callout is its own block: put it after a blank line, or the blockquote
// above swallows it and the first line the plugin reads is that one instead.
const CALLOUT = '> [!warning] a callout';

(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  let bad = 0;
  const fail = (m) => { console.log('FAIL: ' + m); bad++; };

  const body = CASES.map(([src]) => src).join('\n\n') + '\n\n' + CALLOUT
    + '\n\n' + SETEXT.join('\n') + '\n\ntail\n';
  await openDoc(page, { title: 'Reveal', content: body });
  await page.waitForTimeout(1400);
  say('view', await page.evaluate(() => docView));

  const lines = () => page.evaluate(() => [...document.querySelectorAll('#doc-editor .cm-line')].map((l) => l.innerText.replace(/\n/g, '')));

  // The caret goes to the very end, so nothing on any case line is touched.
  await page.evaluate(() => { const s = docSurface(); const n = s.text.length; s.focus(); s.setSelection(n, n); });
  await page.waitForTimeout(500);
  const parked = await lines();
  // Case i sits on rendered line 2i: the body joins the cases with a blank
  // line, and a blank source line is a rendered line of its own.
  for (let i = 0; i < CASES.length; i++) {
    const [src, want] = CASES[i];
    const got = parked[i * 2];
    say(`hidden_${i}`, { src, want, got });
    if (got !== want) fail(`"${src}" rendered as ${JSON.stringify(got)}, wanted ${JSON.stringify(want)}`);
  }
  const setext = await page.evaluate((first) => {
    const line = [...document.querySelectorAll('#doc-editor .cm-line')].find((l) => l.innerText.trim() === first);
    if (!line) return null;
    const next = line.nextElementSibling;
    return { classes: line.className, underlineHidden: next ? next.innerText.trim() === '' : null };
  }, SETEXT[0]);
  say('setext_heading', setext);
  if (!setext) fail('the setext heading is not in the render at all');
  else {
    if (!/cm-md-h1/.test(setext.classes)) fail(`a setext heading gets no heading class (${setext.classes})`);
    if (setext.underlineHidden === false) fail('a setext heading shows its own === underline');
  }

  const label = await page.evaluate(() => {
    const e = document.querySelector('.cm-md-callout-label');
    return e ? e.textContent : null;
  });
  say('callout_label', label);
  if (!label || !/Warning/.test(label)) fail(`the callout kept its [!warning] marker (label ${JSON.stringify(label)})`);

  // The reveal, through each gesture the owner named. The bold run is the
  // subject, and the unit is the **line**: a marker reveals when the caret is
  // on its line, not when it is inside its range. That is not a detail, it is
  // the fix for a measured defect, and the last block here is what checks it.
  const boldAt = await page.evaluate(() => docSurface().text.indexOf('**bold**'));
  const boldLine = await page.evaluate((p) => docCmView.state.doc.lineAt(p).number, boldAt);
  const shows = () => page.evaluate(() => document.querySelector('#doc-editor .cm-content').innerText.includes('**bold**'));
  const park = (n) => page.evaluate((p) => { const s = docSurface(); s.focus(); s.setSelection(p, p); }, n);
  // A position on a different line, which is what "away" means now.
  const elsewhere = await page.evaluate(() => docSurface().text.length);

  // Click: put the selection inside the run, which is what a click does.
  await park(boldAt + 3);
  await page.waitForTimeout(300);
  say('reveal_by_selection', await shows());
  if (!(await shows())) fail('a selection inside **bold** did not reveal its markers');

  // Off the line: hidden again.
  await park(elsewhere);
  await page.waitForTimeout(300);
  say('hidden_from_another_line', !(await shows()));
  if (await shows()) fail('the markers stayed up with the caret on another line');

  // Arrow keys: arrive on the line from the line below it.
  const lineBelowEnd = await page.evaluate((n) => {
    const line = docCmView.state.doc.line(n + 2);
    return line.to;
  }, boldLine);
  await park(lineBelowEnd);
  await page.waitForTimeout(300);
  if (await shows()) fail('the markers were showing before the caret reached the line');
  for (let i = 0; i < 4 && !(await shows()); i++) {
    await page.keyboard.press('ArrowUp');
    await page.waitForTimeout(150);
  }
  say('reveal_by_arrowup', await shows());
  if (!(await shows())) fail('arrowing onto the line did not reveal its markers');

  // Backspace and Delete both move the selection, so both must repaint.
  for (const key of ['Backspace', 'Delete']) {
    await park(elsewhere);
    await page.waitForTimeout(200);
    if (await shows()) fail(`the markers were up before ${key} was pressed`);
    await park(boldAt + 20);
    await page.waitForTimeout(150);
    await page.keyboard.press(key);
    await page.waitForTimeout(300);
    say(`reveal_by_${key.toLowerCase()}`, await shows());
    if (!(await shows())) fail(`${key} on the line did not reveal its markers`);
    await page.keyboard.press('Control+z');
    await page.waitForTimeout(250);
  }

  // **The caret only ever moves left when you press left.** This is the whole
  // reason the reveal is per line rather than per range. Before: walking left
  // across `A **bold** word` read x 560.3, 554, 544.2, 531.1 and then 559.5 on
  // the press that revealed the markers, a 28.4px jump to the *right* on a
  // leftward keystroke, because four characters appeared immediately to the
  // caret's left. atomicRanges is the usual answer and is the wrong one: it
  // would step over the marker rather than into it, and stepping into it is
  // what the owner asked for.
  await park(boldAt + 14);
  await page.waitForTimeout(300);
  const walk = [];
  for (let i = 0; i < 14; i++) {
    walk.push(await page.evaluate(() => {
      const head = docCmView.state.selection.main.head;
      const c = docCmView.coordsAtPos(head);
      return { pos: head, x: c ? +c.left.toFixed(1) : null };
    }));
    await page.keyboard.press('ArrowLeft');
    await page.waitForTimeout(110);
  }
  say('caret_walk', walk.map((w) => w.x));
  for (let i = 1; i < walk.length; i++) {
    if (walk[i].x === null || walk[i - 1].x === null) continue;
    if (walk[i].x > walk[i - 1].x) {
      fail(`ArrowLeft moved the caret right, ${walk[i - 1].x} to ${walk[i].x}, at position ${walk[i].pos}`);
    }
  }

  console.log(bad ? `cm-reveal: ${bad} failures` : 'cm-reveal: all checks pass');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
