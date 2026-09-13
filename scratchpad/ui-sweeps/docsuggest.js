// Click an underlined word, get a popover of suggestions, press one, see the
// word change. DOCUMENTS_PLAN Phase 0 item 2, and the owner's report against
// it: "i still cant click on a grammar or misspeled underlined word and see a
// popup like in a realworld editor like obsidian, word, notion, vs code."
//
// This file exists because that report and the code disagreed, and the plan's
// entry for it ("the click target and its suggestion popover never landed")
// was written without a browser. It had landed. Every number below is read
// out of a running app, so the next session gets a measurement instead of a
// third reading of the same source.
//
// What it checks, per view (Live and Source, which are the two views with an
// editing surface):
//   - each finding kind draws a mark with a pointer cursor and an underline,
//   - one plain click on a mark opens `.doc-suggest-menu`,
//   - the menu is anchored to the word and stays inside the viewport, at a
//     comfortable width and against the right edge, where a 240px menu
//     hung off `anchor.left` would otherwise run off screen,
//   - pressing the first suggestion changes the document text, and
//   - Alt+Enter (VS Code's gesture) opens the same menu from the keyboard.
//
//   BASE=http://127.0.0.1:8830 node scratchpad/ui-sweeps/docsuggest.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

// One of each kind the underline draws: a repeat (dotted), a spelling (wavy
// red) and a spacing slip (wavy blue). `long-sentence` is deliberately not
// underlined (DOC_FINDING_SKIP) and so is not expected here.
const BODY = 'The the cat sat teh mat , here.';
// A word pushed to the right edge, so the menu has to flip rather than run off.
const EDGE = '\n\n' + 'filler '.repeat(28) + 'recieve';

(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  let bad = 0;
  const fail = (m) => { console.log('FAIL: ' + m); bad++; };

  await openDoc(page, { title: 'Suggestions', content: BODY + EDGE });
  await page.waitForTimeout(1200);

  const menuState = () => page.evaluate(() => {
    const p = document.querySelector('.doc-suggest-menu');
    if (!p) return { present: false };
    if (p.classList.contains('hidden')) return { present: true, open: false };
    const r = p.getBoundingClientRect();
    return {
      present: true, open: true,
      x: +r.x.toFixed(1), y: +r.y.toFixed(1), w: +r.width.toFixed(1), h: +r.height.toFixed(1),
      right: +r.right.toFixed(1), bottom: +r.bottom.toFixed(1),
      inViewport: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
      items: [...p.querySelectorAll('.doc-suggest-item')].map((i) => i.textContent.trim().slice(0, 26)),
    };
  });

  for (const view of ['live', 'source']) {
    await page.evaluate((v) => setDocView(v), view);
    await page.waitForTimeout(800);

    const marks = await page.evaluate(() => [...document.querySelectorAll('#doc-editor [data-doc-finding]')].map((e) => {
      const c = getComputedStyle(e);
      return { kind: e.className.replace('cm-finding ', ''), text: e.textContent.slice(0, 12), cursor: c.cursor, underlined: c.textDecorationLine.includes('underline') };
    }));
    say(`${view}_marks`, marks);
    if (marks.length < 3) fail(`${view}: expected at least three underlines, got ${marks.length}`);
    for (const m of marks) {
      if (m.cursor !== 'pointer') fail(`${view}: "${m.text}" does not say it is clickable (cursor ${m.cursor})`);
      if (!m.underlined) fail(`${view}: "${m.text}" carries no underline`);
    }

    // One plain click on each mark opens the menu, anchored and on screen.
    const n = marks.length;
    for (let i = 0; i < n; i++) {
      const at = await page.evaluate((i) => {
        const e = document.querySelectorAll('#doc-editor [data-doc-finding]')[i];
        if (!e) return null;
        const r = e.getBoundingClientRect();
        if (!r.width) return null;
        return { x: r.x + Math.min(6, r.width / 2), y: r.y + r.height / 2, left: +r.left.toFixed(1), bottom: +r.bottom.toFixed(1), text: e.textContent.slice(0, 12) };
      }, i);
      if (!at) continue;
      await page.mouse.click(at.x, at.y);
      await page.waitForTimeout(400);
      const menu = await menuState();
      say(`${view}_click_${JSON.stringify(at.text)}`, menu);
      if (!menu.open) { fail(`${view}: clicking "${at.text}" opened no menu`); continue; }
      if (!menu.inViewport) fail(`${view}: the menu for "${at.text}" is outside the viewport`);
      if (!menu.items.length) fail(`${view}: the menu for "${at.text}" offers nothing`);
      await page.keyboard.press('Escape');
      await page.waitForTimeout(200);
    }
  }

  // Pressing a suggestion changes the text.
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(700);
  const before = await page.evaluate(() => docSurface().text.slice(0, 32));
  await page.evaluate(() => {
    const e = [...document.querySelectorAll('#doc-editor [data-doc-finding]')].find((x) => x.textContent === 'teh');
    const r = e.getBoundingClientRect();
    window.__at = { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  const at = await page.evaluate(() => window.__at);
  await page.mouse.click(at.x, at.y);
  await page.waitForTimeout(500);
  await page.evaluate(() => document.querySelector('.doc-suggest-menu .doc-suggest-item')?.click());
  await page.waitForTimeout(700);
  const after = await page.evaluate(() => docSurface().text.slice(0, 32));
  say('apply', { before, after });
  if (before === after) fail('pressing the first suggestion changed nothing');
  if (!after.includes('the mat')) fail(`the replacement did not land: ${JSON.stringify(after)}`);

  // Alt+Enter opens the same menu with no pointer at all.
  await page.evaluate(() => { const s = docSurface(); s.focus(); s.setSelection(1, 1); });
  await page.waitForTimeout(300);
  await page.keyboard.press('Alt+Enter');
  await page.waitForTimeout(500);
  const kb = await menuState();
  say('alt_enter', kb);
  if (!kb.open) fail('Alt+Enter opened no menu');

  console.log(bad ? `docsuggest: ${bad} failures` : 'docsuggest: all checks pass');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
