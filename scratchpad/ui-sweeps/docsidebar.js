// What the Documents sidebar actually is, both tabs, with a realistic
// document open. The owner: "the documents page sidebar needs redesigning as
// well, both for outline and documents but mostly outline."
//
// `docoutline.js` already passes every one of its assertions, so this file
// does not re-check those; it measures the shape the owner is looking at so
// the redesign starts from numbers rather than from a screenshot.
//
//   BASE=http://127.0.0.1:8871 SCRATCH=/tmp/mm-orch \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/docsidebar.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

// A document the length of a real one: twenty headings over four levels.
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

  // Several documents, so the Documents tab has a list worth measuring.
  for (const t of ['Older note on sources', 'Reading list', 'A draft with quite a long title indeed']) {
    await openDoc(page, { title: t, content: '# ' + t + '\n\nbody\n' });
  }
  await openDoc(page, { title: 'Research plan', content: realDoc() });
  await page.waitForTimeout(600);

  const geom = (el) => {};

  // --- the Documents tab ---------------------------------------------------
  const docsTab = await page.evaluate(() => {
    const pick = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const c = getComputedStyle(el);
      return {
        h: +r.height.toFixed(1), w: +r.width.toFixed(1), y: +r.y.toFixed(1),
        font: c.fontSize, weight: c.fontWeight, pad: c.padding, radius: c.borderRadius,
      };
    };
    const side = document.getElementById('doc-sidebar');
    const rows = [...document.querySelectorAll('#doc-list > li')];
    return {
      sidebar: pick(side),
      sidebarPad: getComputedStyle(side).padding,
      tabStrip: pick(document.getElementById('doc-sidebar-tabs')),
      head: pick(document.querySelector('#doc-sidebar-list .sidebar-head')),
      rowCount: rows.length,
      rows: rows.slice(0, 4).map((li) => ({
        ...pick(li),
        text: li.textContent.replace(/\s+/g, ' ').trim().slice(0, 70),
        kids: [...li.children].map((k) => k.tagName + '.' + (k.className || '')),
      })),
      browseAll: pick(document.getElementById('doc-browse-all')),
      listBottom: (() => {
        const l = document.getElementById('doc-list');
        return l ? { box: +l.getBoundingClientRect().height.toFixed(1), scroll: l.scrollHeight, client: l.clientHeight } : null;
      })(),
    };
  });
  say('documents_tab', docsTab);
  await page.screenshot({ path: OUT + '/sidebar-documents.png', clip: await page.evaluate(() => {
    const r = document.getElementById('doc-sidebar').getBoundingClientRect();
    return { x: Math.floor(r.x) - 4, y: Math.floor(r.y) - 4, width: Math.ceil(r.width) + 8, height: Math.ceil(r.height) + 8 };
  }) });

  // --- the Outline tab -----------------------------------------------------
  await page.evaluate(() => document.querySelector('#doc-sidebar-tabs [aria-controls="doc-sidebar-outline"]')?.click());
  await page.waitForTimeout(700);
  const outline = await page.evaluate(() => {
    const panel = document.getElementById('doc-sidebar-outline');
    const sections = [...panel.querySelectorAll(':scope > .doc-outline-wrap')].map((d) => {
      const r = d.getBoundingClientRect();
      const h = d.querySelector('h3');
      const hc = h ? getComputedStyle(h) : null;
      return {
        id: d.id,
        hidden: d.classList.contains('hidden'),
        heading: h ? h.textContent.replace(/\s+/g, ' ').trim() : null,
        headingFont: hc ? hc.fontSize + '/' + hc.fontWeight + ' ' + hc.textTransform + ' ls=' + hc.letterSpacing : null,
        box: +r.height.toFixed(1),
        rows: d.querySelectorAll('li').length,
      };
    });
    const links = [...document.querySelectorAll('#doc-outline .outline-link')];
    const rowOf = (b) => {
      const r = b.getBoundingClientRect();
      const c = getComputedStyle(b);
      return {
        txt: b.textContent.trim().slice(0, 40),
        h: +r.height.toFixed(1), w: +r.width.toFixed(1),
        font: c.fontSize, weight: c.fontWeight, colour: c.color,
        overflow: c.textOverflow + '/' + c.whiteSpace,
        clipped: b.scrollWidth > b.clientWidth + 1,
      };
    };
    const list = document.getElementById('doc-outline');
    const panelR = panel.getBoundingClientRect();
    return {
      sections,
      rowCount: links.length,
      rows: links.slice(0, 6).map(rowOf),
      longest: rowOf(links.reduce((a, b) => (b.scrollWidth > a.scrollWidth ? b : a), links[0])),
      listScroll: list ? { box: +list.getBoundingClientRect().height.toFixed(1), scroll: list.scrollHeight, client: list.clientHeight } : null,
      panel: { h: +panelR.height.toFixed(1), scroll: panel.scrollHeight, client: panel.clientHeight,
               overflowY: getComputedStyle(panel).overflowY },
      // Does anything mark the heading the caret is in?
      marked: [...document.querySelectorAll('#doc-outline li, #doc-outline .outline-link')]
        .filter((e) => /current|active|is-here|aria-current/.test(e.className) || e.getAttribute('aria-current')).length,
    };
  });
  say('outline_tab', outline);
  await page.screenshot({ path: OUT + '/sidebar-outline.png', clip: await page.evaluate(() => {
    const r = document.getElementById('doc-sidebar').getBoundingClientRect();
    return { x: Math.floor(r.x) - 4, y: Math.floor(r.y) - 4, width: Math.ceil(r.width) + 8, height: Math.ceil(r.height) + 8 };
  }) });

  // Scroll the editor a long way down and ask again whether anything in the
  // outline moved: a table of contents that cannot say where you are is a
  // list of links, not an outline.
  await page.evaluate(() => {
    const s = document.querySelector('.cm-scroller');
    if (s) s.scrollTop = s.scrollHeight * 0.7;
  });
  await page.waitForTimeout(900);
  say('after_scroll', await page.evaluate(() => ({
    marked: [...document.querySelectorAll('#doc-outline li, #doc-outline .outline-link')]
      .filter((e) => /current|active|is-here/.test(e.className) || e.getAttribute('aria-current')).length,
    outlineScrollTop: document.getElementById('doc-outline')?.scrollTop,
  })));

  console.log('shots in ' + OUT);
  await browser.close();
})();
