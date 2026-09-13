// INBOX item 2: kebab menus must stay inside the viewport, everywhere, and
// their submenus (AI actions / Connect / Add) must too. Opens a kebab on
// each of the four reported surfaces at two widths and asserts the menu's
// (and any open submenu's) bounding rect is fully inside the viewport, and
// that every item in it has a non-zero, on-screen box.
const { boot } = require('./lib.js');

function assertInside(label, rect, vw, vh, out) {
  const inside = rect && rect.width > 0 && rect.height > 0 &&
    rect.left >= -0.5 && rect.top >= -0.5 && rect.right <= vw + 0.5 && rect.bottom <= vh + 0.5;
  out.push(`${label}: ${inside ? 'OK' : 'FAIL'} rect=${JSON.stringify(rect)} viewport=${vw}x${vh}`);
  return inside;
}

async function measureMenu(page, menuSel) {
  return page.evaluate((sel) => {
    const menu = document.querySelector(sel);
    if (!menu) return null;
    const r = menu.getBoundingClientRect();
    const items = [...menu.querySelectorAll(':scope > [role="menuitem"], :scope > .menu-group > [role="menuitem"]')];
    const itemBoxes = items.map((it) => {
      const ir = it.getBoundingClientRect();
      return { w: Math.round(ir.width), h: Math.round(ir.height), visible: ir.width > 0 && ir.height > 0 };
    });
    return { rect: { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }, itemCount: items.length, itemBoxes };
  }, menuSel);
}

async function run(viewport) {
  const out = [];
  const { browser, page } = await boot({ viewport });
  const vw = viewport.width, vh = viewport.height;

  // Seed enough notes that the list scrolls, so a kebab near the bottom is
  // the case actually reported ("nothing but a scrollbar").
  await page.evaluate(async () => {
    const post = async (url, body) => { try { await api(url, { method: 'POST', body: JSON.stringify(body) }); } catch (e) {} };
    for (let i = 0; i < 25; i++) {
      await post('/entries', { content: `Sweep note ${i} for kebab-viewport.js, long enough to take a full row in the list.`, tags: ['sweep'] });
    }
  });

  // --- Notes: a card near the bottom of the list ---
  await page.click('[data-tab="notes"]');
  await page.waitForTimeout(600);
  // `#entry-list` itself does not scroll (no `overflow` set); the real
  // scroll container is `#tab-notes .layout > main` one level up
  // (04-chat-dock-appearance.css) - scrolling `#entry-list` is a no-op, and
  // `scrollIntoView` aligns to the *visible* edge of that container
  // regardless of any padding-bottom trailing after the target, so neither
  // reproduces "scrolled all the way down". Setting the real container's
  // `scrollTop` to its `scrollHeight` does. Both the scroll and reading the
  // last row's id happen in the same `evaluate` call: splitting them across
  // two round-trips let a poll's re-render land in between and hand back a
  // row id that no longer matched what was actually at the bottom.
  const lastRowId = await page.evaluate(() => {
    const main = document.querySelector('#tab-notes .layout > main');
    if (main) main.scrollTop = main.scrollHeight;
    // The list appends a `.list-window-sentinel` li (windowing/lazy-load
    // marker) after the real rows, so `li:last-child` finds an empty node,
    // not a note: pick the last row that actually carries `data-id`.
    const rows = [...document.querySelectorAll('#entry-list li[data-id]')];
    const last = rows[rows.length - 1];
    return last ? last.dataset.id : null;
  });
  await page.waitForTimeout(300);
  const lastKebab = lastRowId
    ? await page.$(`#entry-list li[data-id="${lastRowId}"] .menu-wrap > button[aria-haspopup]`)
    : null;
  if (lastKebab) {
    await lastKebab.click();
    await page.waitForTimeout(300);
    // The menu may have been reparented to <body> (escapeMenuIfClipped) if
    // it would otherwise spill past the list's own clipping ancestor - that
    // reparenting is exactly what this sweep exists to confirm, so look in
    // both places rather than assuming it stayed under the row.
    const m = await measureMenu(
      page,
      `#entry-list li[data-id="${lastRowId}"] .action-menu:not(.hidden), body > .action-menu-escaped:not(.hidden)`
    );
    if (m) {
      assertInside('Notes (bottom card) kebab', m.rect, vw, vh, out);
      out.push(`  items=${m.itemCount} allVisible=${m.itemBoxes.every((b) => b.visible)}`);
      // Open the "AI actions" submenu (a `.has-submenu` trigger) and measure it too.
      // The parent menu may or may not itself be escaped, so look wherever it landed.
      const aiTrigger = await page.$(`#entry-list li[data-id="${lastRowId}"] .has-submenu, body > .action-menu-escaped .has-submenu`);
      if (aiTrigger) {
        await aiTrigger.click();
        await page.waitForTimeout(250);
        const sub = await measureMenu(page, '.action-menu.submenu:not(.hidden)');
        if (sub) {
          assertInside('Notes (bottom card) AI actions submenu', sub.rect, vw, vh, out);
          out.push(`  submenu items=${sub.itemCount} allVisible=${sub.itemBoxes.every((b) => b.visible)}`);
        } else out.push('Notes submenu: NOT FOUND (open failed)');
      } else out.push('Notes submenu trigger: NOT FOUND');
    } else out.push('Notes bottom kebab: menu did not open');
  } else out.push('Notes bottom kebab: opener not found');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);

  // Outside pointerdown closes it (capture phase): click far from the menu.
  await lastKebab?.click();
  await page.waitForTimeout(250);
  await page.mouse.click(5, 5);
  await page.waitForTimeout(150);
  const stillOpen = await page.$('.action-menu:not(.hidden)');
  out.push(`Outside pointerdown closes menu: ${stillOpen ? 'FAIL (still open)' : 'OK'}`);

  // --- Library: a card's kebab ---
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(700);
  const libKebab = await page.$('.library-card .menu-wrap > button[aria-haspopup], .library-card button[aria-haspopup]');
  if (libKebab) {
    await libKebab.click();
    await page.waitForTimeout(300);
    const m = await measureMenu(page, '.action-menu:not(.hidden)');
    if (m) {
      assertInside('Library card kebab', m.rect, vw, vh, out);
      out.push(`  items=${m.itemCount} allVisible=${m.itemBoxes.every((b) => b.visible)}`);
    } else out.push('Library card kebab: menu did not open');
  } else out.push('Library card kebab: opener not found (no cards?)');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);

  // --- Chat head kebab ---
  await page.click('[data-tab="chat"]');
  await page.waitForTimeout(700);
  const chatKebab = await page.$('#chat-actions-menu button[aria-haspopup]');
  if (chatKebab) {
    await chatKebab.click();
    await page.waitForTimeout(300);
    const m = await measureMenu(page, '.action-menu:not(.hidden)');
    if (m) {
      assertInside('Chat head kebab', m.rect, vw, vh, out);
      out.push(`  items=${m.itemCount} allVisible=${m.itemBoxes.every((b) => b.visible)}`);
    } else out.push('Chat head kebab: menu did not open');
  } else out.push('Chat head kebab: opener not found');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);

  // --- Documents head kebab (#doc-dock-menu, opened document's toolbar) ---
  // "documents" has no top-level tab button of its own, it is a Library
  // sub-view; switchTab('documents') is the same route every in-app link uses.
  await page.evaluate(async () => {
    try {
      await api('/documents', { method: 'POST', body: JSON.stringify({ title: 'Sweep doc', content: '# Sweep doc\n\nFor kebab-viewport.js.' }) });
    } catch (e) {}
    if (window.switchTab) window.switchTab('documents');
    if (window.loadDocuments) await window.loadDocuments();
  });
  await page.waitForTimeout(700);
  const docItem = await page.$('.doc-item-button, [data-doc-id]');
  if (docItem) {
    await docItem.click();
    await page.waitForTimeout(500);
    const docKebabSummary = await page.$('#doc-dock-menu > summary');
    if (docKebabSummary) {
      await docKebabSummary.click();
      await page.waitForTimeout(300);
      const rect = await page.evaluate(() => {
        const list = document.querySelector('#doc-dock-menu .doc-dock-menu-list');
        if (!list) return null;
        const r = list.getBoundingClientRect();
        return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
      });
      assertInside('Documents head (#doc-dock-menu)', rect, vw, vh, out);
    } else out.push('Documents head kebab: opener not found');
  } else out.push('Documents head kebab: no document to open');

  console.log(`\n=== ${vw}x${vh} ===`);
  console.log(out.join('\n'));
  await browser.close();
  return out;
}

// INBOX 31: the `details.dock-menu` family (Notes Filter, Graph View,
// Timeline Options, Reminders Quick set, Library Filter) is a different
// component from `.action-menu` and had no vertical-clipping story at all --
// the stylesheet's cap on `.doc-dock-menu-list` is a flat `calc(100vh -
// space-9*2)`, blind to where the menu actually opened, so a button in the
// lower part of a short window could open a list well under that cap and
// still land with its own bottom edge past the viewport: nothing to scroll,
// because nothing overflowed the box the stylesheet gave it. 1440 wide so
// the graph dock's own Arrange group is not folded into its "..." overflow
// menu first (a separate, unrelated responsive behaviour); three notes
// seeded first, since the graph's View menu does not exist on the "nothing
// to map yet" empty state.
const DOCK_MENUS = [
  { tab: 'notes', menu: '#notes-filter-menu' },
  { tab: 'graph', menu: '#graph-view-menu' },
  { tab: 'timeline', menu: '#timeline-options-menu' },
  { tab: 'reminders', menu: '#reminder-presets-menu' },
  { tab: 'library', menu: '#library-filter-menu' },
];

async function runDockMenus(viewport) {
  const out = [];
  const { browser, page } = await boot({ viewport });
  const vw = viewport.width, vh = viewport.height;
  await page.evaluate(async () => {
    for (let i = 0; i < 3; i++) {
      try { await api('/entries', { method: 'POST', body: JSON.stringify({ content: `Dock menu sweep note ${i}`, tags: ['sweep'] }) }); } catch (e) {}
    }
  });
  for (const c of DOCK_MENUS) {
    await page.click(`[data-tab="${c.tab}"]`);
    await page.waitForTimeout(900);
    const summary = await page.$(`${c.menu} > summary`);
    if (!summary) { out.push(`${c.menu}: opener not found`); continue; }
    await summary.click();
    await page.waitForTimeout(300);
    const info = await page.evaluate((sel) => {
      // `escapeMenuIfClipped` may have reparented the list to <body> if a
      // scrolling ancestor was clipping it: look there first.
      const escaped = document.querySelector('body > .doc-dock-menu-list.action-menu-escaped');
      const details = document.querySelector(sel);
      const list = escaped || details?.querySelector(':scope > .dock-menu-list, :scope .doc-dock-menu-list');
      if (!list) return null;
      const r = list.getBoundingClientRect();
      return {
        rect: { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height },
        scrollHeight: list.scrollHeight,
        clientHeight: list.clientHeight,
      };
    }, c.menu);
    if (!info) {
      out.push(`${c.menu}: menu did not open`);
    } else {
      assertInside(c.menu, info.rect, vw, vh, out);
      // A list that had to be capped shorter than its content must be the
      // one thing that scrolls, not the one thing that silently loses items.
      const capped = info.rect.height < info.scrollHeight - 1;
      const scrolls = info.scrollHeight > info.clientHeight + 1;
      out.push(`  scrollHeight=${info.scrollHeight} clientHeight=${info.clientHeight} capped=${capped} scrolls=${capped ? scrolls : 'n/a (not capped)'}`);
    }
    await page.keyboard.press('Escape');
    await page.waitForTimeout(150);
  }
  console.log(`\n=== dock-menu family ${vw}x${vh} ===`);
  console.log(out.join('\n'));
  await browser.close();
  return out;
}


// INBOX 43: the whiteboard's five top-bar menus are the third family on the
// same recipe. They were already capped to the window, and that was not the
// bug: measured at 1280x640 with a board open, View and Arrange ended at
// y=628 inside a 640px window while their clipping ancestor
// (`#library-view-whiteboard`, `overflow: hidden`) ended at y=579, so the
// last 49px of each was cut off by the ancestor whatever the cap said. The
// fix is `escapeMenuIfClipped` first, then the cap, exactly as the
// `details.dock-menu` family got it in d8775e6.
const WB_MENUS = ['wb-insert-menu', 'wb-edit-menu', 'wb-arrange-menu', 'wb-view-menu', 'wb-board-menu'];

async function runWbMenus(viewport) {
  const out = [];
  const { browser, page } = await boot({ viewport });
  const vw = viewport.width, vh = viewport.height;
  const boardId = await page.evaluate(async () => {
    const r = await api('/whiteboard/boards', { method: 'POST', body: JSON.stringify({ name: 'Menu viewport sweep' }) });
    return (await r.json()).id;
  });
  await page.evaluate((id) => openWhiteboardBoard(id), boardId);
  await page.waitForTimeout(1500);
  for (const mid of WB_MENUS) {
    const info = await page.evaluate((id) => {
      const btn = document.querySelector(`[aria-controls="${id}"]`);
      if (!btn) return null;
      btn.click();
      const el = document.getElementById(id);
      if (!el || el.classList.contains('hidden')) return null;
      const r = el.getBoundingClientRect();
      // What the menu is actually inside once it is open: an escaped menu is
      // a child of <body> and nothing clips it any more.
      let clipBottom = null;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const s = getComputedStyle(p);
        if (s.overflowX !== 'visible' || s.overflowY !== 'visible') { clipBottom = p.getBoundingClientRect().bottom; break; }
      }
      return {
        rect: { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height },
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        overflowY: getComputedStyle(el).overflowY,
        clipBottom,
        escaped: el.classList.contains('action-menu-escaped'),
      };
    }, mid);
    if (!info) { out.push(`#${mid}: did not open`); continue; }
    assertInside(`#${mid}`, info.rect, vw, vh, out);
    // Every row has to be reachable: either nothing clips the menu, or the
    // clipper's own bottom is past the menu's.
    const unclipped = info.clipBottom === null || info.rect.bottom <= info.clipBottom + 1;
    const capped = info.rect.height < info.scrollHeight - 1;
    const scrolls = info.scrollHeight > info.clientHeight + 1;
    out.push(`  ${unclipped ? 'OK' : 'FAIL'} no ancestor cuts it off (clipBottom=${info.clipBottom === null ? 'none' : Math.round(info.clipBottom)}, menu bottom=${Math.round(info.rect.bottom)}, escaped=${info.escaped})`);
    out.push(`  ${!capped || scrolls ? 'OK' : 'FAIL'} scrollHeight=${info.scrollHeight} clientHeight=${info.clientHeight} overflowY=${info.overflowY} capped=${capped} scrolls=${capped ? scrolls : 'n/a (not capped)'}`);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(150);
    // Closed: back home, and no leftover cap for the next open to inherit.
    const restored = await page.evaluate((id) => {
      const el = document.getElementById(id);
      return { hidden: el.classList.contains('hidden'), escaped: el.classList.contains('action-menu-escaped'), inline: el.style.maxHeight };
    }, mid);
    out.push(`  ${restored.hidden && !restored.escaped && !restored.inline ? 'OK' : 'FAIL'} closed clean: ${JSON.stringify(restored)}`);
  }
  console.log(`\n=== whiteboard top-bar menus ${vw}x${vh} ===`);
  console.log(out.join('\n'));
  await browser.close();
  return out;
}

(async () => {
  await run({ width: 1440, height: 900 });
  await run({ width: 1024, height: 768 });
  await runDockMenus({ width: 1440, height: 900 });
  // Short enough that every one of these lists opens with less room below
  // its button than its own content needs -- the shape actually reported.
  await runDockMenus({ width: 1440, height: 300 });
  // 1280x640 is the shape the whiteboard menus were reported at; 1440x900
  // is the control, where nothing should need to escape anything.
  await runWbMenus({ width: 1440, height: 900 });
  await runWbMenus({ width: 1280, height: 640 });
  // Shorter than the tallest menu's own content, so escaping the clipper is
  // not enough on its own and the cap plus `overflow-y: auto` has to carry
  // the last rows: the "scrolls when taller" half of the report.
  await runWbMenus({ width: 1280, height: 420 });
})();
