// **Behaviour probe for every dock brought onto the grammar (Phase 8).**
//
// `subdocks.js` counts controls; this one *drives* them, because the two
// failures a dock can have are invisible to a count: a menu that opens but
// whose items do nothing, and a menu that opens and will not close. Both have
// been shipped in this app before: the Reminders "Quick set" list opened
// underneath the card after it, and nothing in it could be clicked.
//
// For each dock named below, at 1440 and at 390:
//   * every `details.dock-menu` opens on click, and its list is on screen
//     (inside the viewport, non-zero box) rather than clipped past an edge;
//   * picking the first item in it leaves the menu closed (the delegated
//     handler in app.js). A `dock-menu-check` is ticked instead and the
//     menu is expected to *stay* open, which is the documented behaviour;
//   * Escape closes it and focus returns to its own summary;
//   * a click outside closes it.
//
//   BASE=http://127.0.0.1:8799 SCRATCH=/tmp/mm-docks \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node dockprobe.js
const { boot } = require('./lib.js');

// tab, an optional sub-tab target, the dock's `data-dock-name`.
const SURFACES = [
  { tab: 'library', target: 'library-view-docs', dock: 'library-docs' },
  { tab: 'library', target: 'library-view-whiteboard', dock: 'library-boards' },
  { tab: 'library', target: 'library-view-media', dock: 'library-media' },
  { tab: 'library', target: 'library-view-links', dock: 'library-links' },
  { tab: 'library', target: 'library-view-contents', dock: 'library-contents' },
  { tab: 'library', target: 'library-view-skills', dock: 'library-skills' },
  { tab: 'chat', dock: 'chat' },
  { tab: 'notes', dock: 'notes' },
];

const fails = [];
function check(ok, what) { if (!ok) fails.push(what); return ok; }

// **Picking a real verb runs the real verb**, which is the point of driving a
// menu rather than counting it, and several of them open a dialog: "New group"
// on Links puts up a prompt. Playwright then reports the *next* click only as
// "<div class='modal-overlay'> intercepts pointer events", which names the
// symptom and not the cause and cost half an hour once. So the probe closes
// whatever dialog it opened before carrying on, and says so.
async function dismissModals(page) {
  for (let i = 0; i < 5; i += 1) {
    if (!(await page.$('.modal-overlay:not(.hidden)'))) return;
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    if (!(await page.$('.modal-overlay:not(.hidden)'))) return;
    await page.evaluate(() => {
      const o = document.querySelector('.modal-overlay:not(.hidden)');
      if (!o) return;
      const buttons = [...o.querySelectorAll('button')];
      const cancel = buttons.find((b) => /cancel|close|not now|dismiss/i.test(b.textContent || ''))
        || buttons.find((b) => b.classList.contains('ghost')) || buttons[0];
      if (cancel) cancel.click();
    });
    await page.waitForTimeout(300);
  }
}

async function probe(page, s, width) {
  await dismissModals(page);
  await page.click(`[data-tab="${s.tab}"]`);
  await page.waitForTimeout(500);
  if (s.target) {
    await page.click(`[data-target="${s.target}"]`);
    await page.waitForTimeout(600);
  }
  const sel = `[data-dock-name="${s.dock}"]`;
  const present = await page.$(sel);
  if (!present) { check(false, `${s.dock}@${width}: dock not in the DOM`); return; }
  const menus = await page.$$eval(`${sel} details.dock-menu`, (els) => els.map((e) => e.id));
  const box = await page.$eval(sel, (e) => {
    const b = e.getBoundingClientRect();
    const ctrls = [...e.querySelectorAll('button, select, input:not([type=hidden]), .seg, summary')]
      .filter((c) => c.getBoundingClientRect().width > 0 && !c.closest('.dock-menu-list'));
    return {
      h: Math.round(b.height),
      controls: ctrls.length,
      heights: [...new Set(ctrls.filter((c) => !c.closest('.seg'))
        .map((c) => Math.round(c.getBoundingClientRect().height)))].sort((a, b2) => a - b2),
      overflow: Math.round(e.scrollWidth - e.clientWidth),
    };
  });
  check(box.overflow <= 1, `${s.dock}@${width}: the dock scrolls sideways by ${box.overflow}px`);
  console.log(`  ${s.dock}@${width}`, JSON.stringify({ ...box, menus }));

  for (const id of menus) {
    if (!id) { check(false, `${s.dock}@${width}: a dock menu has no id`); continue; }
    const m = `#${id}`;
    await page.click(`${m} > summary`);
    await page.waitForTimeout(250);
    const open = await page.$eval(m, (e) => e.open);
    check(open, `${m}@${width}: did not open`);
    const listBox = await page.$eval(`${m} .dock-menu-list`, (e) => {
      const b = e.getBoundingClientRect();
      return { w: Math.round(b.width), h: Math.round(b.height), l: Math.round(b.left), r: Math.round(b.right) };
    });
    check(listBox.w > 0 && listBox.h > 0, `${m}@${width}: list has no box`);
    check(listBox.l >= -1 && listBox.r <= width + 1,
      `${m}@${width}: list runs off the viewport (${listBox.l}..${listBox.r} of ${width})`);
    // Pick something in it. A check stays open by design; a verb closes.
    // `:not(.hidden)` is load-bearing: the Notes filter menu keeps a hidden
    // "Save this filter" item that only appears once a filter is typed, and
    // clicking a hidden button waits thirty seconds and then blames the click.
    const kind = await page.$eval(m, (e) => (e.querySelector('.doc-dock-menu-item:not(.hidden)') ? 'item'
      : e.querySelector('.dock-menu-check') ? 'check' : 'section'));
    if (kind === 'item') {
      await page.click(`${m} .doc-dock-menu-item:not(.hidden)`);
      await page.waitForTimeout(300);
      check(!(await page.$eval(m, (e) => e.open)), `${m}@${width}: stayed open after picking an item`);
      await dismissModals(page);
      await page.click(`${m} > summary`);
      await page.waitForTimeout(250);
    } else if (kind === 'check') {
      const before = await page.$eval(`${m} .dock-menu-check input`, (e) => e.checked);
      await page.click(`${m} .dock-menu-check`);
      await page.waitForTimeout(250);
      const after = await page.$eval(`${m} .dock-menu-check input`, (e) => e.checked);
      check(before !== after, `${m}@${width}: ticking a check did nothing`);
      check(await page.$eval(m, (e) => e.open), `${m}@${width}: a check closed the menu`);
      await page.click(`${m} .dock-menu-check`); // put it back
      await page.waitForTimeout(200);
    }
    // Escape closes and hands focus back.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    check(!(await page.$eval(m, (e) => e.open)), `${m}@${width}: Escape did not close it`);
    check(await page.$eval(`${m} > summary`, (e) => e === document.activeElement),
      `${m}@${width}: Escape did not return focus to the summary`);
    // Outside click closes.
    await page.click(`${m} > summary`);
    await page.waitForTimeout(250);
    await page.mouse.click(4, Math.round(width === 390 ? 500 : 700));
    await page.waitForTimeout(300);
    check(!(await page.$eval(m, (e) => e.open)), `${m}@${width}: an outside click did not close it`);
  }
}

(async () => {
  const only = process.argv.slice(2);
  const list = only.length ? SURFACES.filter((s) => only.includes(s.dock)) : SURFACES;
  const { browser, page } = await boot();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.waitForTimeout(400);
    console.log(`--- ${width} ---`);
    for (const s of list) {
      try { await probe(page, s, width); } catch (e) {
        const modal = await page.evaluate(() => {
          const o = document.querySelector('.modal-overlay:not(.hidden)');
          return o ? o.className + ' :: ' + o.textContent.trim().slice(0, 120) : 'none';
        }).catch(() => 'unknown');
        fails.push(`${s.dock}@${width}: ${String(e).slice(0, 140)} | modal: ${modal}`);
      }
    }
  }
  await browser.close();
  console.log(fails.length ? 'FAIL\n' + fails.map((f) => '  ' + f).join('\n') : 'all dock probes passed');
  process.exitCode = fails.length ? 1 : 0;
})();
