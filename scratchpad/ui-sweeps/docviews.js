// Three ways to edit, line numbers on request, and a code file that is a code
// editor. DOCUMENTS_PLAN's INBOX batch of 2026-09-09:
//
//   "I want to be able to use the documents tab as a plain text editor like
//    before as a view option (not the defaul though)"
//   "if I select a txt document, and/or other code file document, and these
//    can have line numbers as well"
//   "for code files, include code syntax and make it a proper code editor
//    like vs code."
//
// The contrast half is the reason this file computes WCAG ratios rather than
// listing colours: the bundle's own `defaultHighlightStyle` is a fixed
// light-page palette with no dark variant, so every token was byte-identical
// in both themes and a keyword read 1.76:1 against the dark ground sampled at
// rgb(27, 31, 44). Nothing logged that, and it is invisible to anyone whose
// theme is light. A number is the only thing that catches it coming back.
//
//   BASE=http://127.0.0.1:8830 node scratchpad/ui-sweeps/docviews.js
//   THEME=dark BASE=... node scratchpad/ui-sweeps/docviews.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const PY = 'def greet(name):\n    """Say hello."""\n    total = 1 + 2\n    print(f"hi {name}", total)\n    return None\n';
const MD = '# Heading\n\nSome **bold** text and a `snippet`.\n\nA second paragraph.\n';

// WCAG 2.x relative luminance, from an `rgb(r, g, b)` string.
function luminance(colour) {
  const [r, g, b] = colour.match(/[\d.]+/g).slice(0, 3).map(Number).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return +((hi + 0.05) / (lo + 0.05)).toFixed(2);
}

(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  let bad = 0;
  const fail = (m) => { console.log('FAIL: ' + m); bad++; };

  // --- the view menu ------------------------------------------------------
  await openDoc(page, { title: 'Views', content: MD });
  await page.waitForTimeout(1000);
  const options = await page.evaluate(() => [...document.querySelectorAll('#doc-view-menu [data-doc-view]')].map((b) => b.dataset.docView));
  say('edit_views', options);
  for (const want of ['live', 'source', 'plain']) {
    if (!options.includes(want)) fail(`the edit menu has no "${want}"`);
  }
  say('default_view', await page.evaluate(() => docView));
  if (await page.evaluate(() => docView) === 'plain') fail('Plain is the default, and was asked not to be');

  // Plain has no grammar, so no highlighting; Source and Live do.
  const spans = () => page.evaluate(() => {
    const c = document.querySelector('#doc-editor .cm-content');
    const ink = getComputedStyle(c).color;
    const set = new Set();
    for (const s of c.querySelectorAll('span')) {
      const col = getComputedStyle(s).color;
      if (col !== ink) set.add(col);
    }
    return { coloured: set.size, ink };
  });
  for (const view of ['source', 'plain']) {
    await page.evaluate((v) => setDocView(v), view);
    await page.waitForTimeout(700);
    const s = await spans();
    say(`${view}_colours`, s);
    if (view === 'source' && s.coloured === 0) fail('Source shows no markdown highlighting at all');
    if (view === 'plain' && s.coloured !== 0) fail(`Plain still colours ${s.coloured} kinds of token`);
  }
  // Plain keeps the text and the editor: it is a view, not a different box.
  say('plain_text_intact', await page.evaluate(() => docSurface().text === undefined ? null : docSurface().text.startsWith('# Heading')));
  if (!(await page.evaluate(() => docSurface().text.startsWith('# Heading')))) fail('Plain lost the document');
  say('plain_is_the_engine', await page.evaluate(() => Boolean(document.querySelector('#doc-editor .cm-content'))));

  // --- line numbers, on request, from a control anyone can find -----------
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(500);
  const numbers = () => page.evaluate(() => document.querySelectorAll('#doc-editor .cm-lineNumbers .cm-gutterElement').length);
  say('md_numbers_default', await numbers());
  if (await numbers() !== 0) fail('a markdown document numbers its lines before being asked');
  // **The control is on the formatting strip, not in the view menu**, and
  // this sweep asserted the wrong door for two sessions. `#doc-view-gutter`
  // existed while the strip was collapsed by default; the owner asked for it
  // back off once the strip reopened ("remove the line numbers view option":
  // numbering is a toggle, not a view), and index.html says so where the row
  // used to be. The sweep kept asking for the removed row, failed, and then
  // threw on `null.click()`, which is why it has been red against a correct
  // app. `.doc-toolbar-gutter` is the one the app actually draws
  // (`documents.js`, the strip's tools group), and it is also what a person
  // reaches for, which is the point of checking it.
  const gutterBtn = '#doc-toolbar .doc-toolbar-gutter';
  const strip = await page.evaluate((sel) => Boolean(document.querySelector(sel)), gutterBtn);
  say('strip_has_line_numbers', strip);
  if (!strip) {
    fail('the formatting strip has no line-numbers button');
  } else {
    await page.evaluate((sel) => document.querySelector(sel).click(), gutterBtn);
    await page.waitForTimeout(800);
    say('md_numbers_after_ask', await numbers());
    if (await numbers() < 2) fail('asking for line numbers on a markdown document produced none');
    say('button_pressed', await page.evaluate(
      (sel) => document.querySelector(sel).getAttribute('aria-pressed'), gutterBtn));
    await page.evaluate((sel) => document.querySelector(sel).click(), gutterBtn);
    await page.waitForTimeout(700);
    say('md_numbers_off_again', await numbers());
    if (await numbers() !== 0) fail('turning the line numbers off left them on');
  }

  // --- a code file --------------------------------------------------------
  // Back to "follow the file type" first, and this matters. `docGutterWanted`
  // reads a *remembered* choice ahead of the type, so the two presses above
  // left an explicit "off" that a `.py` file then honours. That is the right
  // behaviour (someone who turned numbers off meant it), and it is also why
  // "a code file numbers itself" can only be asserted from a profile that has
  // never been asked. Clearing the key is what a fresh profile looks like.
  await page.evaluate(() => {
    try { localStorage.removeItem('doc-gutter'); } catch (e) { /* private mode */ }
  });
  await openDoc(page, { title: 'Code', content: PY, ext: 'py' });
  await page.waitForTimeout(1200);
  say('code_type', await page.evaluate(() => docFileType().ext));
  say('code_view', await page.evaluate(() => docView));
  say('code_numbers_by_default', await numbers());
  if (await numbers() < 5) fail('a code file did not number its own lines');
  say('code_wrap_off', await page.evaluate(() => getComputedStyle(document.querySelector('#doc-editor .cm-content')).whiteSpace));
  say('code_findings_suppressed', await page.evaluate(() => docProseFound.length));
  say('plain_offered_for_code', await page.evaluate(() => {
    const b = document.querySelector('#doc-view-menu [data-doc-view="plain"]');
    return b ? !b.disabled : 'absent';
  }));
  if (await page.evaluate(() => document.querySelector('#doc-view-menu [data-doc-view="plain"]').disabled)) {
    fail('Plain is refused for a code file, and it is exactly what a code file wants');
  }

  // Plain on a code file, and back. This is the round trip that would break
  // silently: Plain empties the language compartment, so leaving it has to put
  // the grammar back, and the line numbers and the text must survive both hops.
  const codeState = () => page.evaluate(() => {
    const c = document.querySelector('#doc-editor .cm-content');
    const ink = getComputedStyle(c).color;
    const set = new Set();
    for (const s of c.querySelectorAll('span')) { const col = getComputedStyle(s).color; if (col !== ink) set.add(col); }
    return {
      view: docView,
      coloured: set.size,
      numbers: document.querySelectorAll('#doc-editor .cm-lineNumbers .cm-gutterElement').length,
      textKept: docSurface().text.startsWith('def greet'),
    };
  });
  const asSource = await codeState();
  await page.evaluate(() => setDocView('plain'));
  await page.waitForTimeout(700);
  const asPlain = await codeState();
  await page.evaluate(() => setDocView('source'));
  await page.waitForTimeout(700);
  const andBack = await codeState();
  say('code_round_trip', { asSource, asPlain, andBack });
  if (!asSource.coloured) fail('a Python file in Source colours nothing');
  if (asPlain.coloured) fail(`Plain on a code file still colours ${asPlain.coloured} kinds of token`);
  if (andBack.coloured !== asSource.coloured) fail(`coming back from Plain left ${andBack.coloured} colours, not ${asSource.coloured}`);
  for (const [name, st] of [['Source', asSource], ['Plain', asPlain], ['Source again', andBack]]) {
    if (!st.textKept) fail(`${name} lost the file's text`);
    if (st.numbers < 3) fail(`${name} lost the line numbers (${st.numbers})`);
  }
  // Live stays refused for a code file, which is the rule Plain had to be
  // carved out of rather than folded into.
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(500);
  const afterLive = await page.evaluate(() => docView);
  say('live_on_a_code_file_lands_on', afterLive);
  if (afterLive !== 'source') fail(`asking for Live on a .py file left the view at "${afterLive}"`);

  // Every file type the app offers, against whether the bundle can highlight
  // it. Two are deliberately plain and are asserted as such, so "php has no
  // colours" reads as a decision here rather than as a gap someone should go
  // and fill: `@codemirror/lang-php` is a full Lezer grammar that also drags
  // in lang-html, measured at +28,563 bytes gzipped (10.6% of the bundle) for
  // one language, and a CSV has no syntax to colour at all.
  const MODES = [
    ['swift', 'func greet(name: String) -> Int {\n    let total = 1 + 2\n    return total\n}\n', true],
    ['r', 'greet <- function(name) {\n  total <- 1 + 2\n  return(total)\n}\n', true],
    ['ini', '[server]\nport = 8080\n; a comment\n', true],
    ['php', '<?php\nfunction greet($name) { echo "hi"; }\n', false],
    ['csv', 'name,count\nalpha,1\n', false],
  ];
  for (const [ext, body, wantColour] of MODES) {
    await openDoc(page, { title: 'Mode ' + ext, content: body, ext });
    await page.waitForTimeout(800);
    const m = await page.evaluate(() => {
      const c = document.querySelector('#doc-editor .cm-content');
      const ink = getComputedStyle(c).color;
      const colours = new Set();
      let styled = 0;
      for (const sp of c.querySelectorAll('span')) {
        const cs = getComputedStyle(sp);
        if (cs.color !== ink) colours.add(cs.color);
        // A mode can mark a token by weight or slant rather than by colour,
        // which is what the INI mode does: bold sections, 600 keys, a muted
        // italic comment, and plain values. Counting colours alone would call
        // that "no highlighting".
        if (cs.color !== ink || cs.fontWeight !== '400' || cs.fontStyle !== 'normal') styled += 1;
      }
      return { type: docFileType().ext, colours: colours.size, styledTokens: styled };
    });
    say(`mode_${ext}`, m);
    if (m.type !== ext) fail(`asking for .${ext} gave a ${m.type} document`);
    if (wantColour && m.styledTokens === 0) fail(`.${ext} has a mode in the bundle and highlighted nothing`);
    if (!wantColour && m.styledTokens !== 0) {
      fail(`.${ext} is meant to be plain text and highlighted ${m.styledTokens} tokens; if a mode was added on purpose, update this list and the decision in DOCUMENTS_PLAN`);
    }
  }

  // Back to the Python file the contrast block below measures.
  await openDoc(page, { title: 'Code', content: PY, ext: 'py' });
  await page.waitForTimeout(900);

  // The colours, as ratios against the page's own ground.
  const ground = await page.evaluate(() => {
    const p = document.createElement('div');
    p.style.background = 'var(--page)';
    document.body.appendChild(p);
    let c = getComputedStyle(p).backgroundColor;
    p.remove();
    // `--page` is a gradient in this app, so it resolves to nothing as a
    // background-color. The mode decides the ground, and both are measured.
    if (!c || c === 'rgba(0, 0, 0, 0)') {
      c = document.documentElement.dataset.mode === 'dark' ? 'rgb(27, 31, 44)' : 'rgb(247, 248, 252)';
    }
    return c;
  });
  say('ground', ground);
  const tokens = await page.evaluate(() => {
    const c = document.querySelector('#doc-editor .cm-content');
    const out = new Map();
    for (const s of c.querySelectorAll('span')) {
      const col = getComputedStyle(s).color;
      if (!out.has(col)) out.set(col, s.textContent.slice(0, 12));
    }
    return [...out.entries()];
  });
  if (tokens.length < 3) fail(`a Python file drew only ${tokens.length} kinds of token: this is not syntax highlighting`);
  for (const [colour, sample] of tokens) {
    const ratio = contrast(colour, ground);
    say(ratio < 4.5 ? 'LOW_CONTRAST' : 'token', { sample, colour, ratio });
    if (ratio < 4.5) fail(`"${sample}" reads at ${ratio}:1 against the page, under WCAG AA's 4.5`);
  }

  console.log(bad ? `docviews: ${bad} failures` : 'docviews: all checks pass');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
