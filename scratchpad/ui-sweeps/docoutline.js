// The Documents Outline sidebar: does it read as an outline?
//
// The owner, with two screenshots: "redesign and refine the outlines section
// of the documents tab as well". Four measured problems came out of them, and
// this file is one assertion per problem so none of them can come back:
//
//   1. entries centre-aligned. The cause was not `text-align`, which said
//      `left` all along; the bare `button` element rule makes every button an
//      `inline-flex` with `justify-content: center`, and against a flex
//      container `text-align` governs nothing. So this checks the flex
//      property, and it checks that each entry's text actually starts at the
//      same x as its own box plus its indent.
//   2. indented by depth in the wrong direction. Before: 4, 16, 24 and 38.4px
//      of padding for h1 to h4, steps of 12, 8 and 14.4 - uneven, and with
//      the entries centred the visible left edges came out in no order at
//      all. This asserts one constant step.
//   3. an empty state that is a bare heading with nothing under it. The
//      Outline section used to hide itself below two headings, so the tab
//      called Outline showed "References" as its first heading.
//   4. References stacking its close button above its own select, which is
//      `.outline-link { width: 100% }` leaving the ✕ nowhere but the next
//      line. This asserts the two are on one line.
//
// And the fifth, from the same screenshots: "Where are my documents kept?" as
// a full-width underlined link pinned to the bottom like a footer.
//
//   BASE=http://127.0.0.1:8831 node scratchpad/ui-sweeps/docoutline.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const HEADINGS = '# Alpha\n\nbody\n\n## Beta\n\nbody\n\n### Gamma\n\nbody\n\n## Delta\n\nbody\n';
// The setext form, which the editor renders as a heading and the outline used
// to skip: the panel read "2" over a document with three headings in it, one
// of them the largest thing on the page. The `---` after a blank line is a
// horizontal rule and must NOT become one, which is the guard worth keeping.
const SETEXT_DOC = 'Top setext\n==========\n\nbody\n\nSecond setext\n-------------\n\nbody\n\n---\n\n### An ATX third\n\nbody\n';

(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  let bad = 0;
  const fail = (m) => { console.log('FAIL: ' + m); bad++; };

  const openOutline = async () => {
    await page.evaluate(() => document.querySelector('#doc-sidebar-tabs [aria-controls="doc-sidebar-outline"]')?.click());
    await page.waitForTimeout(600);
  };

  // --- 1 and 2: alignment and indent ---------------------------------------
  await openDoc(page, { title: 'Outline shape', content: HEADINGS });
  await openOutline();
  const entries = await page.evaluate(() => [...document.querySelectorAll('#doc-outline li')].map((li) => {
    const b = li.querySelector('.outline-link');
    const c = getComputedStyle(b);
    const r = b.getBoundingClientRect();
    // Where the glyphs actually begin, not where the box does.
    const range = document.createRange();
    range.selectNodeContents(b);
    const t = range.getBoundingClientRect();
    range.detach();
    return {
      txt: b.textContent.trim(),
      level: Number((li.className.match(/outline-h(\d)/) || [])[1]),
      justify: c.justifyContent,
      padLeft: +parseFloat(c.paddingLeft).toFixed(2),
      boxX: +r.x.toFixed(1),
      textX: +t.x.toFixed(1),
    };
  }));
  say('entries', entries);
  if (entries.length !== 4) fail(`expected four entries, got ${entries.length}`);
  for (const e of entries) {
    if (e.justify !== 'flex-start') fail(`"${e.txt}" is laid out ${e.justify}, not flex-start`);
    // The text begins at the box plus its own indent, give or take a border.
    const want = e.boxX + e.padLeft;
    if (Math.abs(e.textX - want) > 2) fail(`"${e.txt}" starts at ${e.textX}, not at its indent ${want.toFixed(1)}`);
  }
  // Depth is the only thing that moves an entry, and it moves it one step.
  const byLevel = new Map(entries.map((e) => [e.level, e.padLeft]));
  const steps = [2, 3, 4].filter((l) => byLevel.has(l)).map((l) => +(byLevel.get(l) - byLevel.get(l - 1)).toFixed(2));
  say('indent_steps', steps);
  if (steps.length && new Set(steps).size !== 1) fail(`the indent steps are uneven: ${steps.join(', ')}`);
  if (steps.some((s) => s <= 0)) fail(`a deeper heading is indented less, not more: ${steps.join(', ')}`);
  // Deeper entries have to start further right on screen, which is the
  // half the centring broke even while the padding was correct.
  const textXByLevel = entries.filter((e) => e.level <= 3).map((e) => ({ l: e.level, x: e.textX }));
  say('text_x_by_level', textXByLevel);
  for (const a of textXByLevel) {
    for (const b of textXByLevel) {
      if (a.l < b.l && a.x >= b.x) fail(`an h${a.l} starts at ${a.x} and an h${b.l} at ${b.x}: the indent reads backwards`);
    }
  }
  say('outline_count', await page.evaluate(() => document.getElementById('doc-outline-count')?.textContent));

  // Setext headings count, and a horizontal rule does not.
  await openDoc(page, { title: 'Setext outline', content: SETEXT_DOC });
  await openOutline();
  const setext = await page.evaluate(() => [...document.querySelectorAll('#doc-outline li')].map((li) => ({
    txt: li.textContent.trim(),
    level: Number((li.className.match(/outline-h(\d)/) || [])[1]),
  })));
  say('setext_outline', setext);
  const want = [['Top setext', 1], ['Second setext', 2], ['An ATX third', 3]];
  if (setext.length !== want.length) fail(`the outline lists ${setext.length} headings, not ${want.length}: ${JSON.stringify(setext)}`);
  for (let i = 0; i < want.length && i < setext.length; i++) {
    if (setext[i].txt !== want[i][0]) fail(`outline row ${i} is "${setext[i].txt}", wanted "${want[i][0]}"`);
    if (setext[i].level !== want[i][1]) fail(`"${setext[i].txt}" is level ${setext[i].level}, wanted ${want[i][1]}`);
  }

  // --- 3: the empty state --------------------------------------------------
  await openDoc(page, { title: 'No headings', content: 'A paragraph, and not a heading in sight.\n' });
  await openOutline();
  const empty = await page.evaluate(() => {
    const wrap = document.getElementById('doc-outline-wrap');
    const note = document.getElementById('doc-outline-empty');
    return {
      sectionShown: wrap ? !wrap.classList.contains('hidden') : false,
      noteShown: note ? !note.classList.contains('hidden') : false,
      note: note ? note.textContent.trim() : null,
      firstHeading: document.querySelector('#doc-sidebar-outline h3')?.textContent.trim(),
    };
  });
  say('empty_state', empty);
  if (!empty.sectionShown) fail('the Outline tab hides its own outline section when there are no headings');
  if (!empty.noteShown || !empty.note) fail('the empty outline says nothing about what would fill it');
  if (!/^Outline/.test(empty.firstHeading || '')) fail(`the first heading on the Outline tab is "${empty.firstHeading}"`);

  // --- 3b: a section is as tall as what is in it ---------------------------
  // The hole in the owner's screenshot. Both `.doc-outline-wrap` sections
  // carried `flex: 1 1 auto`, so with a two-heading document the outline was
  // 312.4px of box around 68.3px of content and References 296.5px around
  // 46px: 243.1px of empty column between the last entry and the References
  // heading, and as much again below it.
  await openDoc(page, { title: 'Short outline', content: '# Alpha\n\nbody\n\n## Beta\n\nbody\n' });
  await openOutline();
  const boxes = await page.evaluate(() => [...document.querySelectorAll('#doc-sidebar-outline > .doc-outline-wrap')]
    .filter((d) => !d.classList.contains('hidden'))
    .map((d) => {
      let content = 0;
      for (const k of d.children) content += k.getBoundingClientRect().height;
      return {
        id: d.id,
        box: +d.getBoundingClientRect().height.toFixed(1),
        content: +content.toFixed(1),
        slack: +(d.getBoundingClientRect().height - content).toFixed(1),
        flex: getComputedStyle(d).flex,
      };
    }));
  say('section_boxes', boxes);
  for (const b of boxes) {
    // Padding and the heading's own margin are real; a section twice its
    // content is a section that grew into space it had nothing to put in.
    if (b.slack > 40) fail(`${b.id} is ${b.box}px of box around ${b.content}px of content (${b.slack}px of nothing)`);
  }

  // A text link may not carry the filled button's drop shadow: `.linklike`
  // cancels the fill and the border and used to leave the accent glow, which
  // reads as a soft filled pill around a link.
  const linkShadow = await page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll('.linklike')) {
      if (!el.getClientRects().length) continue;
      out.push({ txt: el.textContent.trim().slice(0, 24), shadow: getComputedStyle(el).boxShadow });
    }
    return out;
  });
  say('linklike_shadows', linkShadow);
  for (const l of linkShadow) {
    if (l.shadow !== 'none') fail(`the link "${l.txt}" draws a button shadow: ${l.shadow}`);
  }

  // --- 4: References is a row, and its picker has a way out ----------------
  await page.evaluate(async () => {
    await api('/bookmarks', { method: 'POST', body: JSON.stringify({ title: 'A saved link', url: 'https://example.invalid/one' }) });
  });
  await openDoc(page, { title: 'Refs', content: HEADINGS });
  await openOutline();
  await page.evaluate(() => document.getElementById('doc-attach-bookmark').click());
  await page.waitForTimeout(800);
  const picker = await page.evaluate(() => {
    const row = document.querySelector('.doc-attach-row');
    if (!row) return null;
    const kids = [...row.children].map((c) => ({ tag: c.tagName, r: c.getBoundingClientRect() }));
    return {
      children: kids.map((k) => k.tag),
      sameLine: kids.length > 1 && Math.abs(kids[0].r.y - kids[1].r.y) < 8,
      buttonHidden: document.getElementById('doc-attach-bookmark').classList.contains('hidden'),
    };
  });
  say('attach_picker', picker);
  if (!picker) fail('the attach picker never opened');
  else {
    if (!picker.sameLine) fail('the picker and its way out are stacked, not on one line');
    if (!picker.buttonHidden) fail('"Attach a link" is still on screen under its own picker');
  }
  // Escape closes it and puts the button back.
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  say('escape_closes', await page.evaluate(() => ({
    rowGone: !document.querySelector('.doc-attach-row'),
    buttonBack: !document.getElementById('doc-attach-bookmark').classList.contains('hidden'),
  })));
  if (await page.evaluate(() => Boolean(document.querySelector('.doc-attach-row')))) fail('Escape left the picker open');

  // Attach one, and check the reference row.
  await page.evaluate(() => document.getElementById('doc-attach-bookmark').click());
  await page.waitForTimeout(1200);
  await page.evaluate(() => {
    const s = document.querySelector('.bookmark-attach-picker');
    s.value = s.options[1].value;
    s.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForTimeout(1100);
  const rows = await page.evaluate(() => [...document.querySelectorAll('#doc-bookmarks li')].map((li) => {
    const kids = [...li.children].map((c) => c.getBoundingClientRect());
    if (kids.length < 2) return { children: kids.length };
    return { children: kids.length, sameLine: Math.abs(kids[0].y - kids[1].y) < 6, gap: +(kids[1].x - kids[0].right).toFixed(1) };
  }));
  say('reference_rows', rows);
  if (!rows.length) fail('attaching a link added no reference row');
  for (const r of rows) {
    if (r.children < 2) fail('a reference has no remove button');
    else if (!r.sameLine) fail('a reference stacks its ✕ under its own link');
  }

  // --- 5: the storage help is help, not a footer ---------------------------
  const help = await page.evaluate(() => {
    const el = document.getElementById('doc-storage-toggle');
    if (!el) return null;
    const c = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const side = document.getElementById('doc-sidebar').getBoundingClientRect();
    return {
      align: c.textAlign,
      decoration: c.textDecorationLine,
      width: +r.width.toFixed(1),
      contentWidth: el.scrollWidth,
      sidebarWidth: +side.width.toFixed(1),
      leftEdge: +(r.x - side.x).toFixed(1),
    };
  });
  say('storage_help', help);
  if (!help) fail('the storage help is gone');
  else {
    if (help.align === 'center') fail('the storage help is centred, and nothing else in the column is');
    if (help.decoration.includes('underline')) fail('the storage help is underlined at rest, which in this app means a link out');
    // Its box is its text, not the column: the "full-width footer" report.
    if (help.width > help.contentWidth + 4) fail(`the storage help is stretched to ${help.width} for ${help.contentWidth} of text`);
  }
  await page.hover('#doc-storage-toggle');
  await page.waitForTimeout(350);
  const hovered = await page.evaluate(() => getComputedStyle(document.getElementById('doc-storage-toggle')).textDecorationLine);
  say('storage_help_hover', hovered);
  if (!hovered.includes('underline')) fail('the storage help gives no sign it can be pressed');

  console.log(bad ? `docoutline: ${bad} failures` : 'docoutline: all checks pass');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
