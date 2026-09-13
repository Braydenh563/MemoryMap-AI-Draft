// Third report of "laggy to drag and pan". The two earlier passes profiled
// PAN and found this sandbox vsync-bound at ~16.7ms in every condition. This
// profiles the DRAG handlers themselves: how long the app's own JS runs per
// drag event, which is a number the display's refresh rate cannot hide.
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
      body: JSON.stringify({ title: 'Drag profile', type: 'board' }) })).json();
    const id = board.id ?? board.board?.id;
    for (let i = 0; i < n; i += 1) {
      await fetch('/whiteboard/objects', { method: 'POST', headers: h, body: JSON.stringify({
        kind: 'text', board_id: id, x: (i % 20) * 130, y: Math.floor(i / 20) * 90,
        width: 120, height: 70, z: 0, data: { content: `card ${i}` } }) });
    }
    return { id, n };
  }, 120);
  await page.evaluate((id) => openWhiteboardBoard(id), made.id);
  await page.waitForTimeout(2500);

  const out = await page.evaluate(async () => {
    const el = document.querySelector('.wb-object');
    if (!el) return { error: 'no object on the board' };
    const box = el.getBoundingClientRect();
    const objects = document.querySelectorAll('.wb-object').length;
    // Time the app's own work per drag event by wrapping the frame the
    // handler runs in: performance marks around a synthetic pointer drag.
    const samples = [];
    const start = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
    el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: start.x, clientY: start.y, pointerId: 1, button: 0 }));
    for (let i = 1; i <= 60; i += 1) {
      const t0 = performance.now();
      window.dispatchEvent(new PointerEvent('pointermove', { bubbles: true,
        clientX: start.x + i * 3, clientY: start.y + i * 2, pointerId: 1 }));
      samples.push(performance.now() - t0);
      await new Promise((r) => requestAnimationFrame(r));
    }
    window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true,
      clientX: start.x + 180, clientY: start.y + 120, pointerId: 1 }));
    samples.sort((a, b) => a - b);
    const at = (p) => samples[Math.min(samples.length - 1, Math.floor(samples.length * p))];
    return {
      objects,
      perEventMs: { median: +at(0.5).toFixed(3), p90: +at(0.9).toFixed(3), max: +samples[samples.length - 1].toFixed(3) },
      total: +samples.reduce((a, b) => a + b, 0).toFixed(2),
    };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
