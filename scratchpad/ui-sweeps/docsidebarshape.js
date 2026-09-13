// The Documents sidebar after the redesign, as numbers: the outline owns the
// column, says where you are, reads as a hierarchy, and the Documents tab is
// a list of rows rather than one boxed row and seven loose blocks.
//
// The owner, INBOX 115: "the documents page sidebar needs redesigning as well,
// both for outline and documents but mostly outline." `docsidebar.js` beside
// this file measured what it was; this one asserts what it has to be, so the
// five things that were wrong cannot come back quietly:
//
//   1. 224px of box around 520px of scroll, with 290px of empty column below
//      it: 13 of 21 headings hidden with no scrollbar and no fade.
//   2. nothing marked where you were. Scrolled to 70% of a 21-heading
//      document, zero rows carried a current class or `aria-current`, and the
//      outline's own scrollTop stayed 0.
//   3. hierarchy flat: 0.8px of type size between h1 and h3, one colour, one
//      weight, depth carried by 12.8px of indent alone.
//   4. an empty References reserving a 12px uppercase heading and the
//      heaviest-looking control on the panel over nothing.
//   5. Documents rows at two heights (56.5 and 78.5) with a container drawn
//      around the selected one only.
//
//   BASE=http://127.0.0.1:8875 SCRATCH=/tmp/mm-docside \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/docsidebarshape.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

// The same fixture `docsidebar.js` measured: four documents, the open one a
// 21-heading research plan over three levels.
function realDoc() {
  const out = ['# Research plan', '', 'An opening paragraph that says what this is for.', ''];
  const sections = ['Background', 'Method', 'Results', 'Discussion', 'Next steps'];
  for (const s of sections) {
    out.push(`## ${s}`, '', 'Body text under the section heading.', '');
    for (const sub of ['First part', 'Second part', 'A third part with a much longer heading than the others']) {
      out.push(`### ${sub}`, '', 'More body text, a couple of sentences long so the document scrolls.', '');
    }
  }
  return out.join('\n');
}

(async () => {
  const { browser, page, OUT } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  let bad = 0;
  const fail = (m) => { console.log('FAIL: ' + m); bad++; };

  const openOutline = async () => {
    await page.evaluate(() => document.querySelector('#doc-sidebar-tabs [aria-controls="doc-sidebar-outline"]')?.click());
    await page.waitForTimeout(600);
  };

  for (const t of ['Older note on sources', 'Reading list', 'A draft with quite a long title indeed']) {
    await openDoc(page, { title: t, content: '# ' + t + '\n\nbody\n' });
  }
  await openDoc(page, { title: 'Research plan', content: realDoc() });
  await page.waitForTimeout(600);

  // --- 5: the Documents tab is a list of rows ------------------------------
  const docsTab = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#doc-list > li')];
    return rows.map((li) => {
      const b = li.querySelector('.doc-item-button');
      const c = getComputedStyle(b);
      const title = li.querySelector('.doc-item-title');
      const type = li.querySelector('.doc-item-type');
      return {
        h: +li.getBoundingClientRect().height.toFixed(1),
        bg: c.backgroundColor,
        titleLines: title ? Math.round(title.getBoundingClientRect().height / parseFloat(getComputedStyle(title).lineHeight)) : null,
        type: type ? type.textContent.trim() : null,
        text: li.textContent.replace(/\s+/g, ' ').trim().slice(0, 48),
      };
    });
  });
  say('documents_rows', docsTab);
  const heights = [...new Set(docsTab.map((r) => r.h))];
  if (heights.length !== 1) fail(`the rows are ${heights.length} different heights: ${heights.join(', ')}`);
  const bare = docsTab.filter((r) => r.bg === 'rgba(0, 0, 0, 0)' || r.bg === 'transparent');
  if (bare.length) fail(`${bare.length} of ${docsTab.length} rows draw no container of their own`);
  const untyped = docsTab.filter((r) => !r.type);
  if (untyped.length) fail(`${untyped.length} rows do not say what kind of file they are`);

  // --- 1: the outline owns the column --------------------------------------
  await openOutline();
  const shape = await page.evaluate(() => {
    const list = document.getElementById('doc-outline');
    const panel = document.getElementById('doc-sidebar-outline');
    const rows = [...list.querySelectorAll('li')];
    const box = list.getBoundingClientRect();
    const visible = rows.filter((li) => {
      const r = li.getBoundingClientRect();
      return r.top >= box.top - 1 && r.bottom <= box.bottom + 1;
    }).length;
    const last = rows.length ? rows[rows.length - 1].getBoundingClientRect() : null;
    const side = document.getElementById('doc-sidebar').getBoundingClientRect();
    return {
      rows: rows.length,
      visible,
      list: { box: +box.height.toFixed(1), scroll: list.scrollHeight, client: list.clientHeight },
      panel: { box: +panel.getBoundingClientRect().height.toFixed(1), scroll: panel.scrollHeight, client: panel.clientHeight },
      // How much column is left under the last thing on the panel.
      tailBelowOutline: last ? +(side.bottom - last.bottom).toFixed(1) : null,
    };
  });
  say('outline_shape', shape);
  if (shape.visible !== shape.rows) {
    fail(`${shape.rows - shape.visible} of ${shape.rows} headings are out of view in a column with room for them`);
  }

  // --- 3: depth reads --------------------------------------------------------
  const depth = await page.evaluate(() => {
    const one = (sel) => {
      const b = document.querySelector(sel);
      if (!b) return null;
      const c = getComputedStyle(b);
      return { size: c.fontSize, weight: c.fontWeight, colour: c.color, padLeft: c.paddingLeft };
    };
    return { h1: one('.outline-h1 .outline-link'), h2: one('.outline-h2 .outline-link'), h3: one('.outline-h3 .outline-link') };
  });
  say('depth', depth);
  if (depth.h1 && depth.h2 && depth.h3) {
    const w = (x) => Number(x.weight);
    if (!(w(depth.h1) > w(depth.h3))) fail(`h1 and h3 are the same weight (${depth.h1.weight} vs ${depth.h3.weight})`);
    if (depth.h1.colour === depth.h3.colour) fail(`every level is the same colour (${depth.h1.colour})`);
  } else {
    fail('the outline has no three levels to compare');
  }

  // --- 2: it says where you are ---------------------------------------------
  const at = async (fraction) => {
    await page.evaluate((f) => {
      const s = document.querySelector('.cm-scroller');
      if (s) s.scrollTop = (s.scrollHeight - s.clientHeight) * f;
    }, fraction);
    await page.waitForTimeout(500);
    return page.evaluate(() => {
      const marked = [...document.querySelectorAll('#doc-outline .outline-link')].filter(
        (b) => b.getAttribute('aria-current') || b.classList.contains('is-current')
      );
      const list = document.getElementById('doc-outline');
      const box = list.getBoundingClientRect();
      const row = marked[0] ? marked[0].getBoundingClientRect() : null;
      return {
        count: marked.length,
        text: marked[0] ? marked[0].textContent.trim().slice(0, 40) : null,
        ariaCurrent: marked[0] ? marked[0].getAttribute('aria-current') : null,
        inView: row ? row.top >= box.top - 1 && row.bottom <= box.bottom + 1 : null,
        listScrollTop: list.scrollTop,
      };
    });
  };
  const marks = {};
  for (const f of [0, 0.3, 0.7, 1]) {
    marks[f] = await at(f);
    say(`marked_at_${f}`, marks[f]);
    if (marks[f].count !== 1) fail(`at ${f * 100}% of the document, ${marks[f].count} rows are marked, not one`);
    else {
      if (marks[f].ariaCurrent !== 'location') fail(`the marked row at ${f * 100}% has aria-current="${marks[f].ariaCurrent}"`);
      if (marks[f].inView === false) fail(`the marked row at ${f * 100}% is out of the outline's own view`);
    }
  }
  if (marks[0].text === marks[0.7].text || marks[0.7].text === marks[1].text) {
    fail(`the mark does not move: 0% "${marks[0].text}", 70% "${marks[0.7].text}", 100% "${marks[1].text}"`);
  }

  // --- 4: an empty section does not reserve a heading and a button ----------
  const refs = await page.evaluate(() => {
    const wrap = document.getElementById('doc-bookmarks-wrap');
    const h = wrap.querySelector('h3');
    const attach = document.getElementById('doc-attach-bookmark');
    const side = document.getElementById('doc-sidebar').getBoundingClientRect();
    return {
      rows: wrap.querySelectorAll('li').length,
      box: +wrap.getBoundingClientRect().height.toFixed(1),
      headingShown: h ? h.getBoundingClientRect().height > 0 : false,
      attach: { w: +attach.getBoundingClientRect().width.toFixed(1), sidebar: +side.width.toFixed(1) },
    };
  });
  say('empty_references', refs);
  if (refs.rows === 0) {
    if (refs.headingShown) fail('an empty References still reserves its heading');
    if (refs.attach.w > refs.attach.sidebar * 0.7) fail(`"Attach a link" is ${refs.attach.w}px wide over nothing`);
    if (refs.box > 48) fail(`an empty References is ${refs.box}px of column`);
  }

  await page.screenshot({ path: OUT + '/sidebar-outline-after.png', clip: await page.evaluate(() => {
    const r = document.getElementById('doc-sidebar').getBoundingClientRect();
    return { x: Math.floor(r.x) - 4, y: Math.floor(r.y) - 4, width: Math.ceil(r.width) + 8, height: Math.ceil(r.height) + 8 };
  }) });

  // --- 1b: a document longer than the column ---------------------------------
  // The outline scrolls inside itself rather than pushing References off the
  // panel, and the way out of an empty References is a whole button rather
  // than a sliver of one. Measured before this was asserted: with 60 headings
  // the outline wanted 1498px in a 686px panel and the References section was
  // shared into 11px around a 28px action.
  const long = [];
  for (let i = 1; i <= 60; i++) {
    long.push(`${i % 3 === 1 ? '#' : i % 3 === 2 ? '##' : '###'} Heading number ${i}`, '', 'body', '');
  }
  await openDoc(page, { title: 'Long plan', content: long.join('\n') });
  await openOutline();
  const deep = await page.evaluate(() => {
    const list = document.getElementById('doc-outline');
    const panel = document.getElementById('doc-sidebar-outline');
    const refs = document.getElementById('doc-bookmarks-wrap').getBoundingClientRect();
    const attach = document.getElementById('doc-attach-bookmark').getBoundingClientRect();
    const side = document.getElementById('doc-sidebar').getBoundingClientRect();
    return {
      rows: list.querySelectorAll('li').length,
      list: { box: +list.getBoundingClientRect().height.toFixed(1), scroll: list.scrollHeight, client: list.clientHeight },
      panel: { scroll: panel.scrollHeight, client: panel.clientHeight },
      references: { box: +refs.height.toFixed(1), attach: +attach.height.toFixed(1), onScreen: refs.bottom <= side.bottom + 1 },
    };
  });
  say('long_document', deep);
  if (deep.list.scroll <= deep.list.client) fail('a 60-heading outline is not scrolling inside itself');
  if (deep.panel.scroll > deep.panel.client + 1) fail('the panel scrolls as a whole instead of the outline scrolling');
  if (!deep.references.onScreen) fail('References is pushed off the panel by a long outline');
  if (deep.references.box < deep.references.attach) {
    fail(`References is ${deep.references.box}px around a ${deep.references.attach}px action`);
  }

  // The type on a row is the document's own, not a default printed eight
  // times: a .py document says .py. Last, because opening one changes which
  // document every measurement above was about.
  await openDoc(page, { title: 'A script', content: 'print("hi")\n', ext: 'py' });
  await page.waitForTimeout(900);
  const pyRow = await page.evaluate(() => {
    const li = [...document.querySelectorAll('#doc-list > li')].find((x) =>
      x.textContent.includes('A script')
    );
    return li ? (li.querySelector('.doc-item-type') || {}).textContent : null;
  });
  say('py_row_type', pyRow);
  if (pyRow !== '.py') fail(`the .py document's row says "${pyRow}"`);

  console.log(bad ? `docsidebarshape: ${bad} failures` : 'docsidebarshape: all checks pass');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
