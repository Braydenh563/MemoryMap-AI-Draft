// DOCUMENTS_PLAN Phase 3 item 2: callouts as toggles, footnotes, and task
// progress in the outline, measured in a browser.
//
//   BASE=http://127.0.0.1:8901 node scratchpad/ui-sweeps/docblocks.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const DOC = [
  '# Release',
  '',
  '- [x] write it',
  '- [ ] measure it',
  '- [ ] ship it',
  '',
  '## Later',
  '',
  '- [ ] think about it',
  '',
  '> [!note]- A folded note',
  '> The body of the folded note.',
  '> A second line of it.',
  '',
  '> [!tip] Not a toggle',
  '> This one has no marker.',
  '',
  'A claim that needs a source[^1].',
  '',
  'Inline $E=mc^2$ in a sentence, and $5 and $10 are prices.',
  '',
  '$$\\frac{a}{b} = \\sqrt{2}$$',
  '',
  '[^1]: The source of the claim.',
].join('\n');

const out = [];
const check = (name, ok, detail) => out.push({ name, ok: !!ok, detail });

(async () => {
  const { browser, page } = await boot();
  await openDoc(page, { title: 'Blocks sweep', content: DOC });
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(600);

  // --- the outline's task counts -------------------------------------------
  await page.evaluate(() => {
    document.querySelector('#doc-sidebar [data-doc-section="outline"]')?.click();
    renderDocOutline();
  });
  await page.waitForTimeout(300);
  const outline = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#doc-outline .outline-link')];
    return rows.map((row) => {
      const chip = row.querySelector('.outline-tasks');
      const rowBox = row.getBoundingClientRect();
      const chipBox = chip ? chip.getBoundingClientRect() : null;
      return {
        text: row.firstChild ? row.firstChild.textContent : '',
        chip: chip ? chip.textContent : null,
        done: chip ? chip.classList.contains('outline-tasks-done') : null,
        rightAligned: chipBox ? +(rowBox.right - chipBox.right).toFixed(1) : null,
        title: row.title,
      };
    });
  });
  check('the top section counts its whole subtree',
    outline[0] && outline[0].chip === '1/4', JSON.stringify(outline[0]));
  check('a sub-section counts its own', outline[1] && outline[1].chip === '0/1',
    JSON.stringify(outline[1]));
  check('the count is at the right edge of the row',
    outline[0] && outline[0].rightAligned !== null && outline[0].rightAligned < 8,
    String(outline[0] && outline[0].rightAligned));
  check('the row says what the number means',
    outline[0] && /1 of 4 tasks done/.test(outline[0].title), outline[0] && outline[0].title);

  // --- the callout toggle ---------------------------------------------------
  const folded = await page.evaluate(() => {
    const chips = [...document.querySelectorAll('#doc-editor .cm-md-callout-label')];
    return {
      labels: chips.map((c) => c.textContent.trim()),
      toggles: chips.map((c) => c.dataset.docCalloutFold !== undefined),
      placeholders: document.querySelectorAll('#doc-editor .cm-foldPlaceholder').length,
      bodyOnScreen: document.body.innerText.includes('The body of the folded note.'),
    };
  });
  check('only the marked callout is a toggle',
    folded.toggles.length === 2 && folded.toggles[0] === true && folded.toggles[1] === false,
    JSON.stringify(folded.toggles));
  check('a folded callout keeps its label', /Note/.test(folded.labels[0] || ''), folded.labels[0]);
  check('a folded callout hides its body', folded.placeholders === 1 && !folded.bodyOnScreen,
    JSON.stringify(folded));

  await page.click('#doc-editor .cm-md-callout-label[data-doc-callout-fold]');
  await page.waitForTimeout(300);
  const open = await page.evaluate(() => ({
    placeholders: document.querySelectorAll('#doc-editor .cm-foldPlaceholder').length,
    bodyOnScreen: document.body.innerText.includes('The body of the folded note.'),
    chevron: document.querySelector('#doc-editor .cm-md-callout-fold')?.textContent,
    text: docSurface().text,
  }));
  check('clicking the label unfolds it', open.placeholders === 0 && open.bodyOnScreen,
    JSON.stringify(open.placeholders));
  check('the chevron turns round', open.chevron === '▾', JSON.stringify(open.chevron));
  check('folding does not touch the document', open.text === DOC, 'the source changed');

  // --- footnotes ------------------------------------------------------------
  const notes = await page.evaluate(() => {
    const marks = [...document.querySelectorAll('#doc-editor .cm-md-footnote')];
    const ref = document.querySelector('#doc-editor .cm-md-footnote-ref');
    const style = ref ? getComputedStyle(ref) : null;
    return {
      count: marks.length,
      texts: marks.map((m) => m.textContent),
      refAlign: style ? style.verticalAlign : null,
      refCursor: style ? style.cursor : null,
      brackets: [...document.querySelectorAll('#doc-editor .cm-line')]
        .map((l) => l.textContent).filter((t) => t.includes('[^')).length,
    };
  });
  check('both footnote marks render', notes.count === 2, JSON.stringify(notes.texts));
  check('a footnote shows its identifier alone', notes.texts.join(',') === '1,1',
    JSON.stringify(notes.texts));
  check('the brackets are hidden', notes.brackets === 0, String(notes.brackets));
  check('the reference is raised and clickable',
    notes.refAlign === 'super' && notes.refCursor === 'pointer',
    `${notes.refAlign}/${notes.refCursor}`);

  await page.click('#doc-editor .cm-md-footnote-ref');
  await page.waitForTimeout(250);
  const jumped = await page.evaluate(() => {
    const s = docSurface();
    return { at: s.selectionStart, line: s.text.slice(s.selectionStart).split('\n')[0] };
  });
  check('clicking a footnote goes to its text', jumped.line.startsWith('[^1]:'),
    JSON.stringify(jumped));

  // --- math ------------------------------------------------------------------
  const math = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('#doc-editor math')];
    const prices = [...document.querySelectorAll('#doc-editor .cm-line')]
      .map((l) => l.textContent).find((t) => t.includes('are prices'));
    const block = nodes.find((m) => m.getAttribute('display') === 'block');
    return {
      count: nodes.length,
      namespace: nodes[0] ? nodes[0].namespaceURI : null,
      inlineTags: nodes[0] ? [...nodes[0].querySelectorAll('*')].map((e) => e.tagName).join(',') : null,
      blockTags: block ? [...block.querySelectorAll('*')].map((e) => e.tagName).join(',') : null,
      width: nodes[0] ? +nodes[0].getBoundingClientRect().width.toFixed(1) : 0,
      height: nodes[0] ? +nodes[0].getBoundingClientRect().height.toFixed(1) : 0,
      prices,
    };
  });
  check('both formulas render', math.count === 2, String(math.count));
  check('MathML is in its own namespace',
    math.namespace === 'http://www.w3.org/1998/Math/MathML', math.namespace);
  check('the inline formula is a superscript',
    /MSUP|msup/i.test(math.inlineTags || ''), math.inlineTags);
  check('the block formula is a fraction and a root',
    /MFRAC|mfrac/i.test(math.blockTags || '') && /MSQRT|msqrt/i.test(math.blockTags || ''),
    math.blockTags);
  check('the browser lays it out', math.width > 20 && math.height > 8,
    `${math.width}x${math.height}`);
  console.log(`  math box: ${math.width}x${math.height}`);
  check('prices are not math', math.prices && math.prices.includes('$5 and $10'), math.prices);

  await browser.close();
  const failed = out.filter((c) => !c.ok);
  for (const c of out) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${c.name}${c.ok ? '' : `  -> ${c.detail}`}`);
  console.log(`${out.length - failed.length}/${out.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
