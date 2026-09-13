// DOCUMENTS_PLAN Phase 3 item 5: `:::columns` blocks and image options,
// measured in a browser.
//
//   BASE=http://127.0.0.1:8911 node scratchpad/ui-sweeps/doccols.js
//
// What this has to prove:
//
//  - a columns block is actually side by side in Live, with real geometry: two
//    boxes at the same top, neither overlapping the other, and the block no
//    wider than the writing around it;
//  - the caret can get in and out of it, by click and by arrow key, and while
//    the caret is inside it the source is what is on screen (the live-preview
//    rule this editor already follows one line at a time);
//  - Read renders the same block the same way;
//  - `![[name|300|center]]` and `![alt|300](url)` are 300px wide, aligned and
//    captioned, in both views;
//  - a phone gets one column.
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const DOC = [
  '# A page with columns',
  '',
  ':::columns',
  '## Left',
  '',
  'The left hand column, with enough words in it to wrap at least once so the',
  'measurement is of a paragraph rather than of a word.',
  ':::column',
  '## Right',
  '',
  'The right hand column.',
  ':::',
  '',
  'After the block.',
  '',
  '![A river at dusk|300|center](/icon-512.png)',
  '',
].join('\n');

const out = [];
const check = (name, ok, detail) => out.push({ name, ok: !!ok, detail });

(async () => {
  const { browser, page } = await boot();
  await openDoc(page, { title: 'Columns sweep', content: DOC });
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(700);

  // --- the block is two boxes, side by side ---------------------------------
  const live = await page.evaluate(() => {
    const box = document.querySelector('#doc-editor .doc-cols');
    if (!box) return null;
    const cols = [...box.querySelectorAll('.doc-col')].map((c) => {
      const r = c.getBoundingClientRect();
      return { left: +r.left.toFixed(1), right: +r.right.toFixed(1), top: +r.top.toFixed(1), w: +r.width.toFixed(1), text: c.textContent.trim().slice(0, 12) };
    });
    const content = document.querySelector('#doc-editor .cm-content').getBoundingClientRect();
    const b = box.getBoundingClientRect();
    return {
      cols,
      boxLeft: +b.left.toFixed(1),
      boxRight: +b.right.toFixed(1),
      contentLeft: +content.left.toFixed(1),
      contentRight: +content.right.toFixed(1),
      headings: box.querySelectorAll('h3, h4, h5').length,
      fenceOnScreen: document.querySelector('#doc-editor .cm-content').textContent.includes(':::columns'),
    };
  });
  check('the block renders as columns in Live', live && live.cols.length === 2, JSON.stringify(live && live.cols));
  if (live && live.cols.length === 2) {
    const [a, b] = live.cols;
    console.log(`  columns: ${a.left}..${a.right} and ${b.left}..${b.right}, tops ${a.top}/${b.top}`);
    check('they are side by side, not stacked', a.right <= b.left + 1, `${a.right} vs ${b.left}`);
    check('and they start at the same height', Math.abs(a.top - b.top) < 1, `${a.top} vs ${b.top}`);
    check('and they are the same width', Math.abs(a.w - b.w) < 1, `${a.w} vs ${b.w}`);
    check('the left column holds the left text', a.text.includes('Left'), a.text);
    check('the right column holds the right text', b.text.includes('Right'), b.text);
  }
  check('the block stays inside the writing measure',
    live && live.boxLeft >= live.contentLeft - 1 && live.boxRight <= live.contentRight + 1,
    live && `${live.boxLeft}..${live.boxRight} in ${live.contentLeft}..${live.contentRight}`);
  check('a column renders markdown, not text', live && live.headings === 2, live && String(live.headings));
  check('the fences are not on screen while the caret is away', live && live.fenceOnScreen === false,
    live && String(live.fenceOnScreen));

  // --- clicking a column puts the caret in that column -----------------------
  const clicked = await page.evaluate(() => {
    const col = document.querySelectorAll('#doc-editor .doc-col')[1];
    const r = col.getBoundingClientRect();
    col.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: r.left + 5, clientY: r.top + 5 }));
    return new Promise((resolve) =>
      setTimeout(() => {
        const at = docCmView.state.selection.main.head;
        const text = docText();
        resolve({
          at,
          line: text.slice(text.lastIndexOf('\n', at - 1) + 1, text.indexOf('\n', at)),
          stillRendered: !!document.querySelector('#doc-editor .doc-cols'),
          fenceOnScreen: document.querySelector('#doc-editor .cm-content').textContent.includes(':::columns'),
        });
      }, 300)
    );
  });
  check('a click lands the caret in the column that was clicked',
    clicked.line.includes('Right'), JSON.stringify(clicked));
  check('and the block becomes its source while you are in it',
    clicked.stillRendered === false && clicked.fenceOnScreen === true, JSON.stringify(clicked));

  // --- arrowing into the block from the line above ---------------------------
  const arrowed = await page.evaluate(() => {
    const text = docText();
    //: The blank line immediately above the block. Deliberately the line
    //: *next to* it rather than two above: the step only happens from the line
    //: whose neighbour is the block, which is what "into it rather than over
    //: it" means.
    const at = text.indexOf(':::columns') - 1;
    docCmView.focus();
    docCmView.dispatch({ selection: { anchor: at } });
    return new Promise((resolve) =>
      setTimeout(() => {
        const before = docCmView.state.selection.main.head;
        docCmView.contentDOM.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true })
        );
        setTimeout(() => {
          const head = docCmView.state.selection.main.head;
          const t = docText();
          resolve({ before, head, line: t.slice(t.lastIndexOf('\n', head - 1) + 1, t.indexOf('\n', head)) });
        }, 250);
      }, 250)
    );
  });
  check('ArrowDown steps into the block, not over it', arrowed.line.includes('Left'), JSON.stringify(arrowed));

  // --- the image's options, in Live -----------------------------------------
  const image = await page.evaluate(() => {
    docCmView.dispatch({ selection: { anchor: 0 } });
    return new Promise((resolve) =>
      setTimeout(() => {
        const fig = document.querySelector('#doc-editor .cm-md-figure');
        const img = fig && fig.querySelector('img');
        const caption = fig && fig.querySelector('.cm-md-caption');
        resolve({
          figure: !!fig,
          align: fig ? fig.className : null,
          width: img ? img.style.width : null,
          rendered: img ? +img.getBoundingClientRect().width.toFixed(1) : null,
          caption: caption ? caption.textContent : null,
          textAlign: fig ? getComputedStyle(fig).textAlign : null,
        });
      }, 400)
    );
  });
  check('a markdown image with options is a figure', image.figure === true, JSON.stringify(image));
  check('the width option is the width', image.width === '300px' && image.rendered === 300,
    `${image.width} / ${image.rendered}`);
  check('the alignment option is the alignment',
    (image.align || '').includes('cm-md-figure-center') && image.textAlign === 'center', JSON.stringify(image));
  check('the caption option is the caption', image.caption === 'A river at dusk', image.caption);

  // --- Read renders the same block ------------------------------------------
  const read = await page.evaluate(() => {
    setDocView('rendered');
    return new Promise((resolve) =>
      setTimeout(() => {
        const preview = document.querySelector('#doc-preview');
        const box = preview.querySelector('.doc-cols');
        const cols = box ? [...box.querySelectorAll('.doc-col')].map((c) => {
          const r = c.getBoundingClientRect();
          return { left: +r.left.toFixed(1), right: +r.right.toFixed(1), top: +r.top.toFixed(1) };
        }) : [];
        const fig = preview.querySelector('.cm-md-figure');
        const img = fig && fig.querySelector('img');
        resolve({
          cols,
          fences: preview.textContent.includes(':::'),
          order: [...preview.children].map((c) => c.className || c.tagName).join(','),
          figure: !!fig,
          width: img ? img.style.width : null,
          caption: fig && fig.querySelector('.cm-md-caption') ? fig.querySelector('.cm-md-caption').textContent : null,
        });
      }, 600)
    );
  });
  check('Read draws two columns too', read.cols.length === 2, JSON.stringify(read.cols));
  check('side by side there as well',
    read.cols.length === 2 && read.cols[0].right <= read.cols[1].left + 1 && Math.abs(read.cols[0].top - read.cols[1].top) < 1,
    JSON.stringify(read.cols));
  check('and no fence text is left in the prose', read.fences === false, read.order);
  check('the image is a figure in Read as well', read.figure === true, JSON.stringify(read));
  check('with the same width and caption', read.width === '300px' && read.caption === 'A river at dusk',
    `${read.width} / ${read.caption}`);

  // --- a phone ---------------------------------------------------------------
  await page.setViewportSize({ width: 390, height: 780 });
  await page.evaluate(() => setDocView('live'));
  await page.waitForTimeout(700);
  const phone = await page.evaluate(() => {
    const box = document.querySelector('#doc-editor .doc-cols');
    if (!box) return null;
    const cols = [...box.querySelectorAll('.doc-col')].map((c) => {
      const r = c.getBoundingClientRect();
      return { left: +r.left.toFixed(1), top: +r.top.toFixed(1), right: +r.right.toFixed(1) };
    });
    return { cols, overflows: box.scrollWidth > box.clientWidth + 1, right: +box.getBoundingClientRect().right.toFixed(1) };
  });
  check('a phone gets one column under the other',
    phone && phone.cols.length === 2 && phone.cols[1].top > phone.cols[0].top && phone.cols[0].left === phone.cols[1].left,
    JSON.stringify(phone));
  check('and nothing runs off the side', phone && phone.overflows === false && phone.right <= 390,
    JSON.stringify(phone));

  await browser.close();
  const failed = out.filter((c) => !c.ok);
  for (const c of out) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${c.name}${c.ok ? '' : `  -> ${c.detail}`}`);
  console.log(`${out.length - failed.length}/${out.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
