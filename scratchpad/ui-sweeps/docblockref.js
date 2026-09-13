// DOCUMENTS_PLAN Phase 4 item 2: block references, measured in a browser.
//
//   BASE=http://127.0.0.1:8931 node scratchpad/ui-sweeps/docblockref.js
//
// What this has to prove, and why each one is here:
//
//  - the `^id` marker is *gone* from the writing surface in Live, and back the
//    moment the caret is on its line, which is the rule every other marker in
//    this view follows (a marker that never hides is a marker in the prose; a
//    marker that never comes back cannot be deleted);
//  - "Link to this block" writes an id into the document and copies the
//    reference, and running it twice on one block gives the same id back,
//    because a link written yesterday has to keep resolving;
//  - `[[Doc#^id]]` opens the document *at the block*, not at the top;
//  - `![[Doc#^id]]` draws the block's own text, fetched for a document that
//    was never opened, and not the whole document;
//  - a `^` in arithmetic is not a block id.
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const out = [];
const check = (name, ok, detail) => out.push({ name, ok: !!ok, detail });

const SOURCE = [
  '# Source document',
  '',
  'The paragraph we will link to.',
  'It has a second line.',
  '',
  'Nothing to do with it. 2^31 is a big number.',
].join('\n');

(async () => {
  const { browser, page } = await boot();
  const sourceId = await openDoc(page, { title: 'Source document', content: SOURCE });

  // Put the caret in the first paragraph and copy a block link.
  const copied = await page.evaluate(() => {
    const surface = docSurface();
    const at = docText().indexOf('The paragraph');
    surface.focus();
    surface.setSelectionRange(at + 4, at + 4);
    const made = docBlockRefAtCaret();
    return { id: made.id, reason: made.reason, text: docText() };
  });
  check('an id is written into the document', /\^[a-z0-9]{6}/.test(copied.text), copied.text.slice(0, 90));
  check('and it lands on the block\'s last line', copied.text.includes(`It has a second line. ^${copied.id}`), copied.text.split('\n')[3]);
  check('the arithmetic line is untouched', copied.text.includes('2^31 is a big number.'), '');

  const again = await page.evaluate(() => {
    const at = docText().indexOf('The paragraph');
    docSurface().setSelectionRange(at + 4, at + 4);
    return docBlockRefAtCaret();
  });
  check('asking twice gives the same id back', again.id === copied.id && again.reason === 'already', `${again.id}/${again.reason}`);

  // The marker is hidden in Live until the caret is on its line.
  await page.evaluate(() => {
    docSurface().setSelectionRange(0, 0);
  });
  await page.waitForTimeout(500);
  const hidden = await page.evaluate((id) => {
    const lines = [...document.querySelectorAll('#doc-editor .cm-line')];
    const line = lines.find((l) => l.textContent.includes('It has a second line'));
    return { text: line ? line.textContent : null, marks: document.querySelectorAll('.cm-md-blockid').length };
  }, copied.id);
  check('the marker is gone from the writing', hidden.text === 'It has a second line.', JSON.stringify(hidden.text));
  check('and nothing is marked while it is hidden', hidden.marks === 0, String(hidden.marks));

  await page.evaluate(() => {
    const at = docText().indexOf('It has a second line');
    docSurface().setSelectionRange(at + 2, at + 2);
  });
  await page.waitForTimeout(500);
  const shown = await page.evaluate(() => {
    const lines = [...document.querySelectorAll('#doc-editor .cm-line')];
    const line = lines.find((l) => l.textContent.includes('It has a second line'));
    const mark = document.querySelector('.cm-md-blockid');
    return {
      text: line ? line.textContent : null,
      mark: mark ? mark.textContent : null,
      font: mark ? getComputedStyle(mark).fontFamily : null,
    };
  });
  check('the caret on the line brings it back', shown.text === `It has a second line. ^${copied.id}`, JSON.stringify(shown.text));
  check('and it is marked as scaffolding', !!shown.mark && /mono|ui-monospace|monospace/i.test(shown.font || ''), `${shown.mark} / ${shown.font}`);

  // Save, then make a second document that links to and embeds the block.
  await page.evaluate(() => saveDocument({ silent: true }));
  await page.waitForTimeout(800);
  const readerId = await page.evaluate(
    async ({ id }) => {
      const r = await api('/documents', {
        method: 'POST',
        body: JSON.stringify({
          title: 'The reader',
          content: `A link: [[Source document#^${id}]]\n\nAn embed:\n\n![[Source document#^${id}]]\n`,
        }),
      });
      const doc = await r.json();
      await loadDocuments(doc.id);
      await openDocument(doc.id);
      return doc.id;
    },
    { id: copied.id }
  );
  await page.waitForTimeout(2500);

  const embed = await page.evaluate(() => {
    const box = document.querySelector('.doc-embed-block');
    return {
      present: !!box,
      body: box ? box.querySelector('.doc-embed-block-body').textContent.trim() : null,
      source: box ? box.querySelector('.doc-embed-block-source').textContent.trim() : null,
      width: box ? box.getBoundingClientRect().width : 0,
      editorWidth: document.querySelector('#doc-editor .cm-content')?.getBoundingClientRect().width || 0,
      rawLeft: document.body.textContent.includes('![[Source document#^'),
    };
  });
  check('the embed draws the block', embed.present, '');
  check(
    'and it is the block, not the document',
    embed.body === 'The paragraph we will link to.\nIt has a second line.' ||
      embed.body === 'The paragraph we will link to. It has a second line.',
    JSON.stringify(embed.body)
  );
  check('the id itself is not in the drawn text', !(embed.body || '').includes('^'), embed.body);
  check('it says where it came from', embed.source === 'Source document', embed.source);
  check('it fits the writing measure', embed.width > 0 && embed.width <= embed.editorWidth + 1, `${embed.width} vs ${embed.editorWidth}`);
  check('no raw embed markdown is left on screen', !embed.rawLeft, '');

  // Following the link lands on the block.
  const landed = await page.evaluate(() => {
    const chip = [...document.querySelectorAll('.cm-md-wiki')].find((el) =>
      (el.getAttribute('data-doc-wiki') || '').includes('#^')
    );
    if (!chip) return { clicked: false };
    chip.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    chip.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return { clicked: true };
  });
  await page.waitForTimeout(2500);
  const where = await page.evaluate(() => {
    const sel = docSurface().selection();
    return {
      title: document.getElementById('doc-title').value,
      selected: docText().slice(sel.from, sel.to),
    };
  });
  check('the link was clickable at all', landed.clicked, '');
  check('following it opens the source document', where.title === 'Source document', where.title);
  check(
    'and lands on the block rather than the top',
    where.selected.startsWith('The paragraph we will link to.'),
    JSON.stringify(where.selected.slice(0, 60))
  );

  // Read view: the same two lines, drawn by the pane that has no caret.
  await page.evaluate((id) => openDocument(id), readerId);
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    setDocView('rendered');
    renderDocPreview();
  });
  await page.waitForTimeout(2000);
  const read = await page.evaluate(() => {
    const pane = document.getElementById('doc-preview');
    const box = pane.querySelector('.doc-embed-block');
    return {
      block: !!box,
      body: box ? box.querySelector('.doc-embed-block-body').textContent.trim() : null,
      nothing: pane.textContent.includes('Nothing called'),
      text: pane.textContent,
      width: box ? box.getBoundingClientRect().width : 0,
      paneWidth: pane.getBoundingClientRect().width,
    };
  });
  check('read view draws the block too', read.block, JSON.stringify(read.text.slice(0, 120)));
  check('and not "nothing called that"', !read.nothing, '');
  check('with the block\'s own words in it', (read.body || '').startsWith('The paragraph we will link to.'), JSON.stringify(read.body));
  check('inside the reading pane', read.width > 0 && read.width <= read.paneWidth + 1, `${read.width} vs ${read.paneWidth}`);

  // And the source document's own Read view has no scaffolding in it.
  await page.evaluate(async (id) => {
    await openDocument(id);
    setDocView('rendered');
    renderDocPreview();
    return null;
  }, sourceId);
  await page.waitForTimeout(1500);
  const marker = await page.evaluate(() => document.getElementById('doc-preview').textContent);
  check('the marker is not in the reader\'s copy', !marker.includes(`^${copied.id}`), JSON.stringify(marker.slice(0, 160)));
  check('but the prose caret still is', marker.includes('2^31'), '');
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(800);

  // A phone: the embed must not push the editor sideways.
  await page.evaluate((id) => openDocument(id), readerId);
  await page.waitForTimeout(1500);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(1200);
  const phone = await page.evaluate(() => ({
    over: document.documentElement.scrollWidth > window.innerWidth + 1,
    box: (() => {
      const el = document.querySelector('.doc-embed-block');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { right: +r.right.toFixed(1), width: +r.width.toFixed(1) };
    })(),
  }));
  check('nothing scrolls sideways at 390', !phone.over, '');
  check('the embed stays inside the phone', phone.box && phone.box.right <= 391, JSON.stringify(phone.box));

  await browser.close();
  let bad = 0;
  for (const row of out) {
    if (!row.ok) bad++;
    console.log(`${row.ok ? 'ok  ' : 'FAIL'} ${row.name}${row.ok ? '' : `  <- ${row.detail}`}`);
  }
  console.log(`${out.length - bad}/${out.length} checks passed`);
  process.exit(bad ? 1 : 0);
})();
