// What the app's own code does per drag event, counted and timed. Frame rate
// is useless here (this sandbox is vsync-bound at ~16.7ms in every
// condition), and synthetic PointerEvents never reach d3's drag behaviour, so
// this wraps the suspect functions and drives a REAL Playwright mouse drag.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="library"]').catch(() => {});
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]').catch(() => {});
  await page.waitForTimeout(900);
  const made = await page.evaluate(async (n) => {
    const h = { 'X-Auth-Token': localStorage.getItem('token') || '', 'Content-Type': 'application/json' };
    const board = await (await fetch('/whiteboard/boards', { method: 'POST', headers: h,
      body: JSON.stringify({ title: 'Drag profile 2', type: 'board' }) })).json();
    const id = board.id ?? board.board?.id;
    let ok = 0;
    for (let i = 0; i < n; i += 1) {
      const r = await fetch('/whiteboard/objects', { method: 'POST', headers: h, body: JSON.stringify({
        kind: 'text', board_id: id, x: (i % 20) * 130, y: Math.floor(i / 20) * 90,
        width: 120, height: 70, z: 0, rotation: null, group_id: null,
        data: { content: `card ${i}` } }) });
      if (r.ok) ok += 1;
    }
    return { id, ok };
  }, 120);
  await page.evaluate((id) => openWhiteboardBoard(id), made.id);
  await page.waitForTimeout(2500);

  const names = ['wbUpdateSelectionBar', 'renderWhiteboardNow', 'wbScheduleRender',
    'wbSyncGridToTransform', 'wbRenderNavigator', 'wbMapIndex', 'wbUpdateLinkedSketches'];
  await page.evaluate((fns) => {
    window.__prof = {};
    for (const name of fns) {
      const original = window[name];
      if (typeof original !== 'function') continue;
      window.__prof[name] = { calls: 0, ms: 0 };
      window[name] = function (...args) {
        const t0 = performance.now();
        try { return original.apply(this, args); }
        finally { const p = window.__prof[name]; p.calls += 1; p.ms += performance.now() - t0; }
      };
    }
    // Also count document-wide queries, the shape that cost the pan frame.
    window.__qs = 0;
    const q = Document.prototype.querySelector;
    Document.prototype.querySelector = function (...a) { window.__qs += 1; return q.apply(this, a); };
  }, names);

  const box = await page.evaluate(() => {
    const el = document.querySelector('.wb-object');
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2) };
  });
  if (!box) { console.log(JSON.stringify({ error: 'no object', made })); await browser.close(); return; }

  await page.evaluate(() => { window.__qs = 0; for (const k in window.__prof) { window.__prof[k].calls = 0; window.__prof[k].ms = 0; } });
  await page.mouse.move(box.x, box.y);
  await page.mouse.down();
  for (let i = 1; i <= 60; i += 1) await page.mouse.move(box.x + i * 3, box.y + i * 2);
  await page.mouse.up();
  await page.waitForTimeout(400);

  const prof = await page.evaluate(() => ({ prof: window.__prof, querySelectors: window.__qs }));
  const rows = Object.entries(prof.prof).filter(([, v]) => v.calls)
    .map(([k, v]) => `${k}: ${v.calls} calls, ${v.ms.toFixed(2)}ms total, ${(v.ms / v.calls).toFixed(3)}ms each`);
  console.log('objects seeded:', made.ok);
  console.log('60 drag moves ->');
  console.log(rows.join('\n') || '  (none of the wrapped functions ran)');
  console.log('document.querySelector calls during the drag:', prof.querySelectors);
  await browser.close();
})();
