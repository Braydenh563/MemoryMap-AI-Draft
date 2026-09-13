// Open a document in the running app, from Playwright, and wait for the
// CodeMirror engine to be under it.
//
// Why this is a shared file rather than eight copies. The `.doc-dock` chrome
// only exists once a document is open, so *every* visual check of the
// documents editor starts with the same twelve lines: POST a document,
// switch the tab, call `openDocument`, wait for the engine's lazy bundle.
// Eight sweeps had written those lines out again, each with its own timeout,
// and a measurement session that got them slightly wrong reported the dock
// unreachable and filed a rule-reading instead of a number (DOCUMENTS_PLAN,
// the Edit/Read entry: "three attempts to open one from a Playwright probe
// did not reach the editor"). The trap it hit is in `openDoc` below: the
// Documents *sub-tab* can activate while `#tab-documents` is still hidden,
// because `openDocument` is async and the engine's bundle is fetched on the
// first open. Waiting on `.cm-editor` rather than on the tab is the fix, and
// it is the reason this file waits on what the engine renders instead of on
// a timeout.
//
//   const { boot } = require('./lib.js');
//   const { openDoc } = require('./docopen.js');
//   const { page } = await boot();
//   await openDoc(page, { title: 'Seg sweep', content: '# Hi' });

// Make a document through the app's own API and open it in the editor.
//
// `opts.ext` names the file type the way `GET /documents/file-types` does
// ("md", "txt", "py", ...); it is applied through the app's own file-type
// select after the open, so the language mode and the gutter follow the same
// path a user's choice would.
//
// Returns the document's id.
async function openDoc(page, opts = {}) {
  const title = opts.title || 'Sweep document';
  const content = opts.content == null ? '' : opts.content;
  const id = await page.evaluate(
    async ({ title, content }) => {
      const r = await api('/documents', {
        method: 'POST',
        body: JSON.stringify({ title, content }),
      });
      const doc = await r.json();
      switchTab('documents');
      await openDocument(doc.id);
      return doc.id;
    },
    { title, content }
  );
  // The engine is loaded lazily on the first open, so the first call in a
  // page pays for a 772 KB script and the rest do not. Waiting on the
  // rendered `.cm-content` covers both, and covers the fallback too: if the
  // bundle is refused the textarea is still the surface, so the wait is
  // allowed to fail rather than throwing the whole sweep away.
  await page
    .waitForSelector('#doc-editor .cm-content', { state: 'visible', timeout: 15000 })
    .catch(() => {});
  await page.waitForTimeout(600);
  if (opts.ext) {
    // `doc-file-type`, with both hyphens: the select moved into the ⋯ menu in
    // Phase 1 and kept its id. Written as `doc-filetype` once here, which set
    // nothing, said nothing, and cost a probe that reported a Python file with
    // no syntax highlighting at all. It throws now rather than carrying on
    // measuring a markdown document that was asked to be code.
    const problem = await page.evaluate((ext) => {
      const sel = document.getElementById('doc-file-type');
      if (!sel) return 'no #doc-file-type in the page';
      sel.value = ext;
      if (sel.value !== ext) return `#doc-file-type has no option "${ext}"`;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      return null;
    }, opts.ext);
    if (problem) throw new Error(`openDoc: ${problem}`);
    await page.waitForTimeout(900);
  }
  return id;
}

// The rectangle of one element, or null when it is not in the page. Every
// sweep here wants the same four numbers and the same "did it exist" answer.
async function rect(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      top: +r.top.toFixed(2),
      left: +r.left.toFixed(2),
      bottom: +r.bottom.toFixed(2),
      right: +r.right.toFixed(2),
      w: +r.width.toFixed(2),
      h: +r.height.toFixed(2),
    };
  }, selector);
}

module.exports = { openDoc, rect };
