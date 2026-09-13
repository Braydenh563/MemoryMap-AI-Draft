// DOCUMENTS_PLAN Phase 3 item 3: `![[…]]` draws the thing, through the
// renderer that already owns that kind.
//
// What this measures is mostly the "one renderer per kind" rule, because that
// is the part a reading of the source cannot settle: an embedded note has to
// be the *same DOM* the Notes tab builds (`.entry-list li`), a map the same
// minimap the Library draws (`.board-minimap`), a file the same tile
// (`.file-card`). A second card renderer would pass a screenshot and fail
// these.
//
//   BASE=http://127.0.0.1:8901 node scratchpad/ui-sweeps/docembed.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const out = [];
const check = (name, ok, detail) => out.push({ name, ok: !!ok, detail });

(async () => {
  const { browser, page } = await boot();

  // A note and a map to point at, made through the app's own API.
  const made = await page.evaluate(async () => {
    const note = await (await api('/entries', {
      method: 'POST',
      //: No `# ` on the first line: this is the form the `[[` picker inserts,
      //: the note's opening words verbatim, and it is what `resolveWikiTarget`
      //: has always matched. The note below is the other form, and the check
      //: on it is the one this sweep used to record as a gap.
      body: JSON.stringify({ content: 'Embedded note\nWith a body worth reading.' }),
    })).json();
    //: **A note whose first line is a heading.** `resolveWikiTarget` matched a
    //: note by content prefix only, so `[[Headed note]]` (the title anybody
    //: reading the note can see) resolved to nothing while `[[# Headed note]]`
    //: resolved: the content starts with the hash, so the prefix test failed
    //: on the first character. Fixed in app.js; measured here.
    await (await api('/entries', {
      method: 'POST',
      body: JSON.stringify({ content: '# Headed note\nWritten under its own title.' }),
    })).json();
    const board = await (await api('/whiteboard/boards', {
      method: 'POST',
      body: JSON.stringify({ name: 'Embedded map', title: 'Embedded map', type: 'map' }),
    })).json();
    //: The page's own indexes were loaded before these two existed, and a
    //: name resolves against them (`resolveWikiTarget`). Reloaded here rather
    //: than by reloading the page, so the sweep measures the same code path a
    //: user gets when they make a note and then link to it.
    //: A real attachment in the Library, so the file branch is measured
    //: rather than assumed: `/entries/{id}/files` is the app's own upload.
    const blob = new Blob(['a,b\n1,2\n'], { type: 'text/csv' });
    const form = new FormData();
    form.append('file', new File([blob], 'embedded-table.csv', { type: 'text/csv' }));
    //: The app's own header set, minus the JSON content type a multipart
    //: body must not carry: `api()` always sends one, so this goes direct.
    await fetch('/entries/' + note.id + '/files', {
      method: 'POST',
      body: form,
      headers: { 'X-Auth-Token': authToken(), 'X-Workspace-ID': activeSpaceId() },
    });
    mapBoardIndexCache = null;
    await loadMapBoardIndex();
    await loadEntries();
    return { note: note.id, board: board.id };
  });

  const DOC = [
    '# Embeds',
    '',
    '![[Embedded note]]',
    '',
    '![[Embedded map]]',
    '',
    '![[embedded-table.csv]]',
  '',
  '![[Nothing called this]]',
    '',
    'A [[Embedded note]] link is still a link.',
  ].join('\n');
  await openDoc(page, { title: 'Embed sweep', content: DOC });
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(900);

  const shape = await page.evaluate(() => {
    const hosts = [...document.querySelectorAll('#doc-editor .cm-md-embed')];
    const byName = Object.fromEntries(hosts.map((h) => [h.dataset.docEmbed, h]));
    const note = byName['Embedded note'];
    const map = byName['Embedded map'];
    const missing = byName['Nothing called this'];
    const box = (el) => (el ? +el.getBoundingClientRect().width.toFixed(1) : null);
    return {
      hosts: hosts.length,
      noteCard: note ? !!note.querySelector('.entry-list > li') : false,
      noteText: note ? note.textContent.includes('With a body worth reading') : false,
      noteWidth: box(note),
      mapChip: map ? !!map.querySelector('.map-chip, .chip') : false,
      mapPreview: map ? !!map.querySelector('svg.board-minimap') : false,
      mapWidth: box(map),
      fileTile: byName['embedded-table.csv']
        ? !!byName['embedded-table.csv'].querySelector('.file-card .file-card-name')
        : false,
      fileName: byName['embedded-table.csv']
        ? byName['embedded-table.csv'].textContent.trim()
        : null,
      missingChip: missing ? missing.textContent.trim() : null,
      missingTitle: missing ? missing.querySelector('.chip')?.title : null,
      // The plain link on the last line is still a link, not an embed.
      wikiLinks: document.querySelectorAll('#doc-editor .cm-md-wiki').length,
      bang: [...document.querySelectorAll('#doc-editor .cm-line')]
        .map((l) => l.textContent).filter((t) => t.includes('![[')).length,
    };
  });

  check('four embeds render', shape.hosts === 4, String(shape.hosts));
  check('a file embed is the Library\u2019s own tile', shape.fileTile, shape.fileName);
  check('a note embed is the app’s own note card', shape.noteCard, 'no .entry-list > li');
  check('the note card has the note in it', shape.noteText, 'the body is missing');
  check('a map embed is the app’s own minimap', shape.mapPreview && shape.mapChip,
    `chip ${shape.mapChip} preview ${shape.mapPreview}`);
  check('the cards are given a width to work in',
    shape.noteWidth > 100 && shape.noteWidth <= 421 && shape.mapWidth > 100 && shape.mapWidth <= 321,
    `${shape.noteWidth} / ${shape.mapWidth}`);
  check('a name with nothing behind it says so',
    shape.missingChip === 'Nothing called this' && /Nothing called/.test(shape.missingTitle || ''),
    `${shape.missingChip} / ${shape.missingTitle}`);
  check('a plain [[link]] is still a link', shape.wikiLinks === 1, String(shape.wikiLinks));
  check('no ![[ is left on screen', shape.bang === 0, String(shape.bang));

  //: Both ways of naming a note whose first line is a heading resolve to it,
  //: and neither resolves to the other note.
  const headed = await page.evaluate(() => {
    const one = resolveWikiTarget('Headed note');
    const two = resolveWikiTarget('# Headed note');
    const other = resolveWikiTarget('Embedded note');
    const opening = (t) => (t && t.entry ? (t.entry.content || '').split('\n')[0] : null);
    return { one: opening(one), two: opening(two), other: opening(other) };
  });
  check('a note is found by the title you can see',
    headed.one === '# Headed note', JSON.stringify(headed));
  check('and by the opening words the picker inserts',
    headed.two === '# Headed note', JSON.stringify(headed));
  check('and the exact-prefix match still wins first',
    headed.other === 'Embedded note', JSON.stringify(headed));

  // The source is untouched by any of it.
  const text = await page.evaluate(() => docSurface().text);
  check('the document is the text that was typed', text === DOC, JSON.stringify(text));

  // The caret on the line shows the markdown again, which is how you edit it.
  await page.evaluate(() => {
    const s = docSurface();
    const at = s.text.indexOf('![[Embedded note]]');
    s.focus();
    s.setSelectionRange(at + 4, at + 4);
  });
  await page.waitForTimeout(300);
  const revealed = await page.evaluate(() => ({
    hosts: document.querySelectorAll('#doc-editor .cm-md-embed').length,
    bang: [...document.querySelectorAll('#doc-editor .cm-line')]
      .map((l) => l.textContent).filter((t) => t.includes('![[')).length,
  }));
  check('the caret on the line shows the markdown', revealed.hosts === 3 && revealed.bang === 1,
    JSON.stringify(revealed));

  await browser.close();
  const failed = out.filter((c) => !c.ok);
  for (const c of out) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${c.name}${c.ok ? '' : `  -> ${c.detail}`}`);
  console.log(`${out.length - failed.length}/${out.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
