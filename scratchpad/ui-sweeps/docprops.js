// DOCUMENTS_PLAN Phase 3 item 4: frontmatter as an editable properties panel,
// measured in a browser rather than reasoned about.
//
//   BASE=http://127.0.0.1:8911 node scratchpad/ui-sweeps/docprops.js
//
// What this has to prove, and why each one is here:
//
//  - the YAML is *gone* from the writing surface in Live (the panel is what
//    you read instead), and back the moment the caret is on its line, which is
//    the rule every other marker in this view follows;
//  - a field's write reaches the document as an edit over the value's own
//    span: the test in tests/test_doc_frontmatter.py proves that of the model,
//    this proves the panel is wired to it;
//  - the panel lines up with the writing under it (one measure, one left
//    edge), because a panel at the pane's width over a 78ch column reads as
//    two unrelated surfaces;
//  - Source shows the YAML itself and has no panel, Read renders it as rows;
//  - it fits a phone.
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const DOC = [
  '---',
  'category: Work',
  'tags: [one, two]',
  'status:    draft   ',
  '---',
  '',
  '# A document with properties',
  '',
  'The first line of prose.',
].join('\n');

const out = [];
const check = (name, ok, detail) => out.push({ name, ok: !!ok, detail });

(async () => {
  const { browser, page } = await boot();
  await openDoc(page, { title: 'Properties sweep', content: DOC });
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(600);

  // --- the panel exists, and says what the block says ------------------------
  const rows = await page.evaluate(() => {
    const host = document.querySelector('#doc-editor .doc-props');
    if (!host) return null;
    return {
      hidden: host.classList.contains('hidden'),
      keys: [...host.querySelectorAll('.doc-prop-key')].map((el) => el.textContent),
      chips: [...host.querySelectorAll('.doc-prop-chip')].map((el) => el.textContent.trim()),
      inputs: [...host.querySelectorAll('.doc-prop-row .doc-prop-input')].map((el) => el.value),
      adders: host.querySelectorAll('.doc-prop-add').length,
      newBtn: !!host.querySelector('.doc-prop-new-btn'),
    };
  });
  check('the panel is in the page', rows && !rows.hidden, JSON.stringify(rows));
  check('every key has a row', rows && rows.keys.join(',') === 'category,tags,status', rows && rows.keys.join(','));
  check('a list is chips', rows && rows.chips.join('|') === 'one|two', rows && rows.chips.join('|'));
  check('a scalar is a field, padding trimmed for display',
    rows && rows.inputs.join('|') === 'Work|draft', rows && rows.inputs.join('|'));
  check('a list has one adder', rows && rows.adders === 1, rows && String(rows.adders));
  check('there is a way to add a property', rows && rows.newBtn, JSON.stringify(rows && rows.newBtn));

  // --- the YAML is not also on the writing surface ---------------------------
  const hidden = await page.evaluate(() => {
    const lines = [...document.querySelectorAll('#doc-editor .cm-line')];
    const marked = lines.filter((l) => l.classList.contains('cm-md-frontmatter'));
    const heights = marked.map((l) => +l.getBoundingClientRect().height.toFixed(2));
    const first = lines.find((l) => !l.classList.contains('cm-md-frontmatter') && l.textContent.trim());
    return {
      marked: marked.length,
      heights,
      firstVisible: first ? first.textContent : null,
      //: The *document*, not the DOM: a replace decoration takes the text out
      //: of the rendered line, which is the whole point of it, so asking
      //: `.cm-content` whether the YAML is still there answers "no" for a
      //: document that has it.
      text: docText().includes('category: Work'),
    };
  });
  check('every frontmatter line is marked', hidden.marked === 5, String(hidden.marked));
  check('and every one of them is zero high',
    hidden.heights.length === 5 && hidden.heights.every((h) => h === 0), JSON.stringify(hidden.heights));
  check('the first line you can see is the heading',
    (hidden.firstVisible || '').includes('A document with properties'), hidden.firstVisible);
  check('the text itself is untouched (it is hidden, not removed)', hidden.text === true, String(hidden.text));

  // --- the caret on a line brings it back ------------------------------------
  const revealed = await page.evaluate(() => {
    const view = docCmView;
    view.focus();
    view.dispatch({ selection: { anchor: view.state.doc.line(2).from + 3 } });
    return new Promise((resolve) =>
      setTimeout(() => {
        const lines = [...document.querySelectorAll('#doc-editor .cm-line')];
        const on = lines.find((l) => l.textContent.startsWith('category:'));
        resolve({
          height: on ? +on.getBoundingClientRect().height.toFixed(2) : null,
          marked: lines.filter((l) => l.classList.contains('cm-md-frontmatter')).length,
        });
      }, 250)
    );
  });
  check('the line the caret is on comes back', revealed.height > 8, JSON.stringify(revealed));
  check('and the other four stay down', revealed.marked === 4, String(revealed.marked));

  // --- a field writes one edit, over the value's own span --------------------
  const written = await page.evaluate(() => {
    const before = docText();
    docCmView.dispatch({ selection: { anchor: docText().length } });
    const input = [...document.querySelectorAll('#doc-editor .doc-prop-row .doc-prop-input')][0];
    input.value = 'Personal';
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return new Promise((resolve) =>
      setTimeout(() => resolve({ before, after: docText() }), 250)
    );
  });
  check('the value changed in the document', written.after.includes('category: Personal'), written.after.slice(0, 60));
  check('and nothing else did',
    written.after.replace('category: Personal', 'category: Work') === written.before,
    JSON.stringify(written.after.slice(0, 90)));
  check('the padded value kept its padding', /status:    draft   /.test(written.after), 'status line rewritten');

  // --- a tag added and removed ----------------------------------------------
  const tagged = await page.evaluate(() => {
    const add = document.querySelector('#doc-editor .doc-prop-add');
    add.value = 'three';
    add.dispatchEvent(new Event('change', { bubbles: true }));
    return new Promise((resolve) =>
      setTimeout(() => {
        const text = docText();
        const chip = [...document.querySelectorAll('#doc-editor .doc-prop-chip')]
          .find((c) => c.textContent.trim().startsWith('one'));
        chip.querySelector('button').click();
        setTimeout(() => resolve({ added: text, removed: docText() }), 250);
      }, 250)
    );
  });
  check('a tag typed into the adder reaches the document',
    /tags: \[one, two, three\]/.test(tagged.added), tagged.added.split('\n')[2]);
  check('and removing a chip takes exactly that tag out',
    /tags: \[two, three\]/.test(tagged.removed), tagged.removed.split('\n')[2]);

  // --- the panel and the writing share one measure and one left edge ---------
  const geometry = await page.evaluate(() => {
    const host = document.querySelector('#doc-editor .doc-props');
    //: `.cm-editor`, not `.cm-content`: the content element moves with the
    //: scroller, so measuring the writing's top against it says "the panel
    //: overlaps the text" the moment anybody scrolls.
    const content = document.querySelector('#doc-editor .cm-editor');
    const h = host.getBoundingClientRect();
    const c = content.getBoundingClientRect();
    const key = host.querySelector('.doc-prop-key').getBoundingClientRect();
    const value = host.querySelector('.doc-prop-value').getBoundingClientRect();
    return {
      panelLeft: +h.left.toFixed(1),
      panelRight: +h.right.toFixed(1),
      contentLeft: +c.left.toFixed(1),
      contentRight: +c.right.toFixed(1),
      panelHeight: +h.height.toFixed(1),
      keyLeft: +key.left.toFixed(1),
      valueLeft: +value.left.toFixed(1),
      overflowY: getComputedStyle(host).overflowY,
      scrolls: host.scrollHeight > host.clientHeight,
      below: +(c.top - h.bottom).toFixed(1),
    };
  });
  console.log(`  panel ${geometry.panelLeft}..${geometry.panelRight} (${geometry.panelHeight}px tall), text ${geometry.contentLeft}..${geometry.contentRight}`);
  check('the panel starts no further left than the writing',
    geometry.panelLeft <= geometry.contentLeft + 1 && geometry.contentLeft - geometry.panelLeft < 40,
    `${geometry.panelLeft} vs ${geometry.contentLeft}`);
  check('and ends no further right', Math.abs(geometry.panelRight - geometry.contentRight) < 40,
    `${geometry.panelRight} vs ${geometry.contentRight}`);
  check('the writing starts below the panel', geometry.below >= 0, String(geometry.below));
  check('the panel does not eat the document', geometry.panelHeight < 260, String(geometry.panelHeight));

  // --- Source shows the YAML, and has no panel ------------------------------
  const source = await page.evaluate(() => {
    setDocView('source');
    return new Promise((resolve) =>
      setTimeout(() => {
        const host = document.querySelector('#doc-editor .doc-props');
        resolve({
          panel: host ? !host.classList.contains('hidden') : false,
          firstLine: document.querySelector('#doc-editor .cm-line').textContent,
          height: +document.querySelector('#doc-editor .cm-line').getBoundingClientRect().height.toFixed(1),
        });
      }, 400)
    );
  });
  check('Source has no panel', source.panel === false, JSON.stringify(source));
  check('Source shows the fence itself', source.firstLine === '---', source.firstLine);
  check('and the line has its height back', source.height > 8, String(source.height));

  // --- Read renders the properties as rows, not as a rule and a paragraph ----
  const read = await page.evaluate(() => {
    setDocView('rendered');
    return new Promise((resolve) =>
      setTimeout(() => {
        const preview = document.querySelector('#doc-preview');
        const props = preview.querySelector('.doc-props-read');
        resolve({
          rows: props ? props.querySelectorAll('.doc-prop-row').length : 0,
          rules: preview.querySelectorAll('hr').length,
          hasYaml: preview.textContent.includes('category: Personal'),
          firstAfter: props && props.nextElementSibling ? props.nextElementSibling.tagName : null,
        });
      }, 500)
    );
  });
  check('Read draws a row per property', read.rows === 3, String(read.rows));
  check('and no horizontal rules where the fences were', read.rules === 0, String(read.rules));
  check('and no raw YAML in the prose', read.hasYaml === false, String(read.hasYaml));

  // --- a phone --------------------------------------------------------------
  await page.setViewportSize({ width: 390, height: 780 });
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(500);
  const phone = await page.evaluate(() => {
    const host = document.querySelector('#doc-editor .doc-props');
    const row = host.querySelector('.doc-prop-row');
    const key = row.querySelector('.doc-prop-key').getBoundingClientRect();
    const value = row.querySelector('.doc-prop-value').getBoundingClientRect();
    return {
      overflowsX: host.scrollWidth > host.clientWidth + 1,
      stacked: value.top >= key.bottom - 1,
      right: +host.getBoundingClientRect().right.toFixed(1),
      width: +host.getBoundingClientRect().width.toFixed(1),
    };
  });
  console.log(`  phone: panel ${phone.width}px wide, right edge ${phone.right}`);
  check('nothing scrolls sideways at 390', phone.overflowsX === false, JSON.stringify(phone));
  check('the key sits above its value at 390', phone.stacked === true, JSON.stringify(phone));
  check('and the panel stays inside the phone', phone.right <= 390, String(phone.right));

  await browser.close();
  const failed = out.filter((c) => !c.ok);
  for (const c of out) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${c.name}${c.ok ? '' : `  -> ${c.detail}`}`);
  console.log(`${out.length - failed.length}/${out.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
