// DOCUMENTS_PLAN Phase 3 item 1: the table editor, measured in a browser.
//
// The round trip is proven in `tests/test_doc_tables.py`, which runs the model
// in node over six table shapes. What a test cannot see is whether the table
// *renders* as a table and whether the gestures reach the model, so this is
// the other half: the pipes are gone from the rendered line, the cells line up
// in columns across rows, Tab lands in the next cell, and the cell menu's
// commands change the document the way the model says they do.
//
//   BASE=http://127.0.0.1:8901 node scratchpad/ui-sweeps/doctable.js
const { boot, OUT } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const TABLE = [
  '# Tables',
  '',
  '| Name | Notes | Count |',
  '| --- | :---: | ---: |',
  '| One | first | 1 |',
  '| Two | second | 2 |',
  '',
  'After the table.',
].join('\n');

// The document after "Two" is retyped as "Deux": one cell, one word, and
// every other byte of the table exactly as it was written above.
const TABLE_EXPECTED_TYPED = TABLE.replace('| Two |', '| Deux |');

const out = [];
const check = (name, ok, detail) => out.push({ name, ok: !!ok, detail });

(async () => {
  const { browser, page } = await boot();
  await openDoc(page, { title: 'Table sweep', content: TABLE });
  // Live is the view the decorations are in.
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(500);

  const shape = await page.evaluate(() => {
    const lines = [...document.querySelectorAll('#doc-editor .cm-content .cm-line')];
    const row = (i) => lines[i];
    const cells = (i) => [...row(i).querySelectorAll('.cm-md-td')].map((el) => {
      const r = el.getBoundingClientRect();
      return { text: el.textContent, left: +r.left.toFixed(1), width: +r.width.toFixed(1),
               align: getComputedStyle(el).textAlign };
    });
    return {
      count: lines.length,
      headText: row(2) ? row(2).textContent : null,
      headDisplay: row(2) ? getComputedStyle(row(2)).display : null,
      headWeight: row(2) ? getComputedStyle(row(2)).fontWeight : null,
      delimHeight: row(3) ? +row(3).getBoundingClientRect().height.toFixed(2) : null,
      delimText: row(3) ? row(3).textContent : null,
      head: cells(2),
      body1: cells(4),
      body2: cells(5),
      plain: row(7) ? getComputedStyle(row(7)).display : null,
    };
  });

  check('pipes are hidden in the header', !/\|/.test(shape.headText || '|'), shape.headText);
  check('the header line is a grid', shape.headDisplay === 'grid', shape.headDisplay);
  check('a paragraph is not a grid', shape.plain === 'block', shape.plain);
  check('three cells per row', shape.head.length === 3 && shape.body1.length === 3,
    `${shape.head.length}/${shape.body1.length}`);
  const lefts = (r) => r.map((c) => c.left).join(',');
  check('the columns line up', lefts(shape.head) === lefts(shape.body1) &&
    lefts(shape.head) === lefts(shape.body2), `${lefts(shape.head)} vs ${lefts(shape.body1)}`);
  check('the columns are equal width',
    new Set(shape.head.map((c) => c.width)).size === 1, shape.head.map((c) => c.width).join(','));
  check('the header is bold', Number(shape.headWeight) >= 600, shape.headWeight);
  check('alignment reaches the cells',
    shape.head[1] && shape.head[1].align === 'center' && shape.head[2].align === 'right',
    `${shape.head[1] && shape.head[1].align}/${shape.head[2] && shape.head[2].align}`);
  check('the delimiter row is a rule, not a blank line', shape.delimHeight === 0, shape.delimHeight);

  // The header cell's ground, **from the pixels**, because the table is the
  // one thing here that paints a ground of its own and `contrast.js` only
  // walks a tab with no document open in it.
  //
  // Computed styles cannot answer this one. `--field-inset` is
  // `rgba(31, 36, 48, 0.07)`, so reading its rgb triple gives the ink's own
  // colour and a ratio of 1:1 (the first version of this check did exactly
  // that), and compositing the translucent ancestors by hand gave
  // rgb(110,110,111) against a page that is plainly not grey. So the ground is
  // read where it is painted: a screenshot, and a pixel inside the header
  // cell's own padding, which is this project's own rule for anything about
  // colour.
  const cellBox = await page.evaluate(() => {
    const cell = document.querySelector('#doc-editor .cm-md-table-head .cm-md-td');
    if (!cell) return null;
    const r = cell.getBoundingClientRect();
    return { x: Math.round(r.left + 2), y: Math.round(r.top + 2), color: getComputedStyle(cell).color };
  });
  const shot = `${OUT}/doctable-head.png`;
  await page.screenshot({ path: shot });
  const pixel = require('child_process')
    .execSync(`python3 ${__dirname}/../pngpixel.py ${shot} ${cellBox.x} ${cellBox.y}`)
    .toString();
  const ground = (pixel.match(/\((\d+), ?(\d+), ?(\d+)/) || []).slice(1).map(Number);
  const ratio = (() => {
    const fg = (cellBox.color.match(/\d+/g) || []).map(Number);
    const lum = ([r, g, b]) => {
      const f = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : Math.pow((v / 255 + 0.055) / 1.055, 2.4));
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const l1 = lum(fg);
    const l2 = lum(ground);
    return +((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2);
  })();
  check('the header ink clears AA on the ground it is painted on', ratio >= 4.5,
    `${ratio}:1 on rgb(${ground.join(',')}), pixel line ${pixel.trim()}`);
  console.log(`  header contrast: ${ratio}:1 on rgb(${ground.join(',')})`);

  // Tab walks the cells: put the caret in the first body cell and step twice.
  const tab = await page.evaluate(async () => {
    const surface = docSurface();
    const at = surface.text.indexOf('One');
    surface.setSelectionRange(at, at);
    surface.focus();
    return at;
  });
  await page.keyboard.press('Tab');
  await page.waitForTimeout(120);
  const afterOne = await page.evaluate(() => {
    const s = docSurface();
    return s.text.slice(s.selectionStart, s.selectionEnd);
  });
  check('Tab selects the next cell', afterOne === 'first', JSON.stringify(afterOne));
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.waitForTimeout(120);
  const wrapped = await page.evaluate(() => {
    const s = docSurface();
    return s.text.slice(s.selectionStart, s.selectionEnd);
  });
  check('Tab wraps to the next row', wrapped === 'Two', JSON.stringify(wrapped));

  // Typing into a selected cell rewrites that cell and nothing else.
  await page.keyboard.type('Deux');
  await page.waitForTimeout(200);
  const typed = await page.evaluate(() => docSurface().text);
  check('typing rewrites one cell only', typed === TABLE_EXPECTED_TYPED, JSON.stringify(typed));

  // The cell menu: it exists while the caret is in the table, and its
  // commands go through the model.
  const menu = await page.evaluate(() => {
    const el = document.querySelector('#doc-editor .cm-md-table-menu');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const head = el.closest('.cm-line').getBoundingClientRect();
    return { inside: r.right <= head.right + 1, top: +r.top.toFixed(1), items:
      [...el.querySelectorAll('.menu-item')].map((b) => b.textContent.trim()) };
  });
  check('the cell menu is on the header row', !!menu && menu.inside, JSON.stringify(menu && menu.top));
  check('the cell menu has ten commands', menu && menu.items.length === 10,
    menu ? menu.items.join(' / ') : 'no menu');

  const inserted = await page.evaluate(() => {
    docTableCommand('row-below');
    return docSurface().text;
  });
  check('insert row below adds one row',
    inserted.split('\n').length === TABLE_EXPECTED_TYPED.split('\n').length + 1,
    JSON.stringify(inserted));
  const aligned = await page.evaluate(() => {
    const s = docSurface();
    const at = s.text.indexOf('Name');
    s.setSelectionRange(at, at);
    docTableCommand('align-right');
    return docSurface().text;
  });
  check('align right rewrites one delimiter cell',
    aligned.includes('| ---: | :---: | ---: |'), aligned.split('\n')[3]);

  await browser.close();
  const failed = out.filter((c) => !c.ok);
  for (const c of out) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${c.name}${c.ok ? '' : `  -> ${c.detail}`}`);
  console.log(`${out.length - failed.length}/${out.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
