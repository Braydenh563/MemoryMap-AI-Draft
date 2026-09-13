// Final visual QA pass across the whole app (pre-merge). Not a single-
// surface probe: this walks every tab, every Notes/Library sub-tab, every
// Settings section, and the whiteboard, at 1440 and 1024, in both themes,
// and reports what breaks when unrelated changes land together -- a row
// that wraps, a control at the wrong height, clipped or overflowing text,
// a panel past the end of its scroll, an off-screen control, a console
// error. Errors.js already does console/overflow/off-screen per top-level
// tab, but its Library sub-tab clicks use `[data-section]`/`[data-view]`,
// which Library's own sub-tabs never carry (they use `data-target`), so
// every Library sub-tab beyond the default has gone unchecked by it; this
// covers those, adds a control-height/row-wrap check per dock-like row,
// and a sticky-panel-vs-its-scroller overrun check (the shape INBOX 105's
// sibling report, the AI skills sidebar, turned out to be).
//
//   BASE=http://127.0.0.1:8794 SCRATCH=/tmp/mm-8794 \
//     PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node finalqa.js
//   WIDTHS=1440,1024 THEMES=light,dark (defaults shown)
const { boot } = require('./lib.js');

const TABS = ['dashboard', 'notes', 'chat', 'graph', 'library', 'timeline', 'reminders'];
const NOTES_SUBTABS = ['browse', 'capture', 'writing-room', 'ask'];
const LIBRARY_SUBTABS = [
  { label: 'all', sel: '[data-target="library-view-documents"]' },
  { label: 'documents', sel: '[data-target="library-view-docs"]' },
  { label: 'boards', sel: '[data-target="library-view-whiteboard"]' },
  { label: 'images', sel: '[data-target="library-view-media"][data-media-kind="images"]' },
  { label: 'files', sel: '[data-target="library-view-media"][data-media-kind="files"]' },
  { label: 'skills', sel: '[data-target="library-view-skills"]' },
  { label: 'links', sel: '[data-target="library-view-links"]' },
  { label: 'contents', sel: '[data-target="library-view-contents"]' },
];
const SETTINGS_SECTIONS = [
  'models', 'personas', 'skills', 'templates', 'memory', 'tools', 'appearance',
  'extras', 'shortcuts', 'preferences', 'websearch', 'tasks', 'data', 'account',
  'logs', 'help', 'about',
];

// One evaluate call, everything this pass wants to know about the surface
// on screen right now.
const CHECK_SRC = () => {
  const vis = (e) => e.checkVisibility && e.checkVisibility({ visibilityProperty: true, opacityProperty: true, contentVisibilityAuto: true });
  const findings = [];

  // 1. Horizontal page scroll.
  if (document.documentElement.scrollWidth > window.innerWidth + 1) {
    findings.push(`page scrolls horizontally: ${document.documentElement.scrollWidth} > ${window.innerWidth}`);
  }

  // 2. Clipped text: a card/heading/paragraph whose content is taller than
  // its own box, excluding things that are SUPPOSED to scroll.
  const NOT_SCROLLABLE_EXEMPT = 'textarea, .tab-page, [class*="scroll"], .entry-list, ul, ol, .cm-editor, .cm-scroller, #doc-editor, [id$="-list"]';
  for (const e of document.querySelectorAll('.tab-page:not(.hidden) .card, .tab-page:not(.hidden) h2, .tab-page:not(.hidden) h3, .tab-page:not(.hidden) p, .modal:not(.hidden) h2, .modal:not(.hidden) h3, #settings-modal:not(.hidden) h3')) {
    if (!vis(e)) continue;
    if (e.matches(NOT_SCROLLABLE_EXEMPT) || e.closest(NOT_SCROLLABLE_EXEMPT)) continue;
    const cs = getComputedStyle(e);
    if (cs.overflow === 'visible' || cs.overflowY === 'visible') continue;
    if (e.scrollHeight > e.clientHeight + 2) {
      const id = e.id ? '#' + e.id : '.' + [...e.classList].slice(0, 2).join('.');
      findings.push(`clipped: ${e.tagName.toLowerCase()}${id} ${e.scrollHeight}>${e.clientHeight}`);
    }
  }

  // 3. Off-screen controls not inside a legitimately horizontally-scrolling strip.
  const inHScrollStrip = (e) => {
    for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if ((o === 'auto' || o === 'scroll') && p.scrollWidth > p.clientWidth + 1) return true;
    }
    return false;
  };
  for (const e of document.querySelectorAll('.tab-page:not(.hidden) button, .tab-page:not(.hidden) input, .tab-page:not(.hidden) select, #settings-modal:not(.hidden) button')) {
    if (!vis(e) || inHScrollStrip(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (r.right > window.innerWidth + 1 || r.left < -1) {
      const id = e.id ? '#' + e.id : '.' + [...e.classList].slice(0, 2).join('.');
      findings.push(`off-screen: ${e.tagName.toLowerCase()}${id} left=${Math.round(r.left)} right=${Math.round(r.right)}`);
    }
  }

  // 4. Control-height consistency and row-wrap, per dock-like row. Two
  // controls sharing a row that disagree on height, or a row whose
  // children have landed on more than one line, are both "assembled, not
  // designed" (DESIGN.md's own phrase) -- reported as findings, not
  // auto-judged, since a genuinely mixed-height row can be intentional
  // (a filled action beside two ghosts is allowed to differ; a `.seg`
  // pill beside a plain button is not always a bug either). This flags
  // candidates for a human to read against the dock grammar, it does not
  // decide for them.
  const DOCK_SEL = '.dock, .seg, [role="toolbar"], .library-toolbar, .graph-toolbar, .chat-toolbar, .notes-toolbar, .doc-toolbar, .doc-dock, .wb-topbar';
  for (const row of document.querySelectorAll(DOCK_SEL)) {
    if (!vis(row)) continue;
    const rowRect = row.getBoundingClientRect();
    if (rowRect.height === 0 || rowRect.top > window.innerHeight || rowRect.top < -50) continue;
    // `.dock-identity` (the heading text) is excluded: it is label text,
    // not a control, and a short line of text centred beside a 36px
    // button is not a height mismatch -- DESIGN.md's own dock grammar
    // already treats identity as a separate zone from controls.
    const kids = [...row.querySelectorAll(':scope > button, :scope > select, :scope > input, :scope > .seg, :scope > label, :scope > .dock-group > button, :scope > .dock-group > select, :scope > .dock-actions > button, :scope > .dock-find > input')]
      .filter((c) => vis(c) && c.getBoundingClientRect().width > 0 && !c.closest('.dock-identity'));
    if (kids.length < 2) continue;
    const tops = kids.map((c) => Math.round(c.getBoundingClientRect().top));
    const minTop = Math.min(...tops), maxTop = Math.max(...tops);
    // A real wrap moves a control down by roughly a control's own height
    // (24px-plus), not the few px that `align-items: center` alone can put
    // between two controls of slightly different height on one line.
    const wrapped = maxTop - minTop > 16;
    if (wrapped) {
      const id = row.id ? '#' + row.id : '.' + [...row.classList].slice(0, 2).join('.');
      findings.push(`row wraps: ${id} tops=${[...new Set(tops)].sort((a, b) => a - b).join(',')}`);
    }
    // Height mismatch only among controls that stayed on the row's own
    // first line -- a wrapped row's second line is a different report
    // (above), not a second height mismatch on top of it.
    const sameLine = kids.filter((c, i) => Math.abs(tops[i] - minTop) <= 2);
    const heights = [...new Set(sameLine.map((c) => Math.round(c.getBoundingClientRect().height)))];
    if (heights.length > 1) {
      const id = row.id ? '#' + row.id : '.' + [...row.classList].slice(0, 2).join('.');
      findings.push(`control heights differ: ${id} heights=${heights.sort((a, b) => a - b).join('/')}`);
    }
  }

  // 5. A sticky/fixed panel that overruns the scroll container it is
  // supposed to match (the AI-skills-sidebar shape: a sticky sidebar
  // whose max-height tracks a container-query or viewport figure that can
  // drift from the container's own current border-box).
  for (const el of document.querySelectorAll('[style*="position: sticky"], .sidebar-panel, aside.card')) {
    if (!vis(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.position !== 'sticky' && cs.position !== 'fixed') continue;
    let scroller = el.parentElement;
    while (scroller && scroller !== document.body) {
      const so = getComputedStyle(scroller).overflowY;
      if (so === 'auto' || so === 'scroll') break;
      scroller = scroller.parentElement;
    }
    if (!scroller || scroller === document.body) continue;
    const er = el.getBoundingClientRect();
    const sr = scroller.getBoundingClientRect();
    if (er.bottom > sr.bottom + 2) {
      const id = el.id ? '#' + el.id : '.' + [...el.classList].slice(0, 2).join('.');
      findings.push(`sticky panel past its scroller: ${id} bottom=${Math.round(er.bottom)} scroller-bottom=${Math.round(sr.bottom)}`);
    }
  }

  return findings;
};

async function check(page, label, findingsOut) {
  const r = await page.evaluate(CHECK_SRC);
  if (r.length) findingsOut.push(...r.map((f) => `[${label}] ${f}`));
}

async function run(width, height, theme) {
  process.env.THEME = theme;
  const { browser, page } = await boot({ viewport: { width, height } });
  const errs = [];
  page.on('pageerror', (e) => errs.push(`[js] ${e.message.slice(0, 160)}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/401|Failed to load resource/.test(m.text())) errs.push(`[console] ${m.text().slice(0, 160)}`); });
  page.on('response', (r) => { if (r.status() >= 500) errs.push(`[http] ${r.status()} ${r.request().method()} ${r.url()}`); });

  const findings = [];
  const label = (s) => `${width}x${height}/${theme} ${s}`;

  for (const t of TABS) {
    await page.click(`[data-tab="${t}"]`).catch(() => {});
    await page.waitForTimeout(550);
    await check(page, label(t), findings);
    if (t === 'notes') {
      for (const s of NOTES_SUBTABS) {
        const ok = await page.click(`#tab-notes [data-section="${s}"]`, { timeout: 1500 }).then(() => true).catch(() => false);
        if (!ok) continue;
        await page.waitForTimeout(450);
        await check(page, label(`notes/${s}`), findings);
      }
    }
    if (t === 'library') {
      for (const { label: subLabel, sel } of LIBRARY_SUBTABS) {
        const ok = await page.click(sel, { timeout: 1500 }).then(() => true).catch(() => false);
        if (!ok) { findings.push(label(`library/${subLabel}`) + ' could not click sub-tab'); continue; }
        await page.waitForTimeout(500);
        await check(page, label(`library/${subLabel}`), findings);
      }
      // Boards & maps: also open a real board, not just the landing list.
      const boardId = await page.evaluate(async () => {
        const r = await api('/whiteboard/boards');
        const items = (await r.json()).items || [];
        return items[0]?.id ?? null;
      });
      if (boardId != null) {
        await page.evaluate((id) => openWhiteboardBoard(id), boardId);
        await page.waitForTimeout(700);
        await check(page, label('library/boards (open board)'), findings);
      }
      // Documents: open a real document too.
      const docId = await page.evaluate(async () => {
        const r = await api('/documents');
        const items = (await r.json()).items || [];
        return items[0]?.id ?? null;
      });
      if (docId != null) {
        await page.evaluate((id) => { switchTab('documents'); openDocument(id); }, docId);
        await page.waitForTimeout(900);
        await check(page, label('library/documents (open doc)'), findings);
        await page.evaluate(() => { switchTab('library'); });
        await page.waitForTimeout(300);
      }
    }
  }

  // Settings.
  await page.evaluate(() => document.getElementById('settings-btn')?.click());
  await page.waitForTimeout(500);
  for (const s of SETTINGS_SECTIONS) {
    const ok = await page.click(`#settings-modal [data-section="${s}"]`, { timeout: 1500 }).then(() => true).catch(() => false);
    if (!ok) continue;
    await page.waitForTimeout(350);
    await check(page, label(`settings/${s}`), findings);
  }
  await page.keyboard.press('Escape').catch(() => {});

  console.log(`\n== ${width}x${height} ${theme}: ${errs.length} console/js errors, ${findings.length} layout findings ==`);
  errs.forEach((e) => console.log('  ' + e));
  findings.forEach((f) => console.log('  ' + f));

  await browser.close();
  return { errs, findings };
}

(async () => {
  const widths = (process.env.WIDTHS || '1440,1024').split(',').map(Number);
  const themes = (process.env.THEMES || 'light,dark').split(',');
  let totalErr = 0, totalFind = 0;
  for (const w of widths) {
    for (const theme of themes) {
      const { errs, findings } = await run(w, 900, theme);
      totalErr += errs.length;
      totalFind += findings.length;
    }
  }
  console.log(`\n== TOTAL: ${totalErr} console/js errors, ${totalFind} layout findings across ${widths.length * themes.length} passes ==`);
})();
