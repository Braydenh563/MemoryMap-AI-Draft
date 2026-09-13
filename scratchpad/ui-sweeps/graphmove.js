// What the graph's own pan, zoom and node drag cost per event.
//
// The frame rate cannot answer this: the sandbox is vsync-bound at about
// 16.7ms in every condition anyone here has tried, so an A/B of frame times
// returns the same number whatever the handler does. Call counts and the
// profiler's self time are real numbers the display cannot hide, so those are
// what this measures: how many times a gesture walks the document, how many
// times it repaints the minimap, and how much self time the handlers take.
//
// Synthetic PointerEvents from page.evaluate never reach d3's drag behaviour
// (measured: 0ms per event, which was measuring nothing). Everything below
// uses page.mouse, which produces trusted events.
//
//   BASE=http://127.0.0.1:8851 SCRATCH=/tmp/mm-graph2 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/graphmove.js
const { boot } = require('./lib.js');

async function counters(page) {
  await page.evaluate(() => {
    if (window.__moveCount) return;
    window.__moveCount = { byId: {}, sel: {}, total: 0 };
    const realId = document.getElementById.bind(document);
    document.getElementById = (id) => {
      if (window.__moveCounting) {
        window.__moveCount.byId[id] = (window.__moveCount.byId[id] || 0) + 1;
        window.__moveCount.total += 1;
      }
      return realId(id);
    };
    const realQs = document.querySelector.bind(document);
    document.querySelector = (s) => {
      if (window.__moveCounting) {
        window.__moveCount.sel[s] = (window.__moveCount.sel[s] || 0) + 1;
        window.__moveCount.total += 1;
      }
      return realQs(s);
    };
    const realQsa = document.querySelectorAll.bind(document);
    document.querySelectorAll = (s) => {
      if (window.__moveCounting) {
        window.__moveCount.sel[s] = (window.__moveCount.sel[s] || 0) + 1;
        window.__moveCount.total += 1;
      }
      return realQsa(s);
    };
  });
}

async function start(page) {
  await page.evaluate(() => {
    window.__moveCount = { byId: {}, sel: {}, total: 0 };
    window.__moveCounting = true;
  });
}
async function stop(page) {
  return page.evaluate(() => {
    window.__moveCounting = false;
    return window.__moveCount;
  });
}

function top(map, n) {
  return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, n)
    .map(([k, v]) => `${k}=${v}`).join(' ');
}

(async () => {
  const { browser, page } = await boot();
  await page.evaluate(() => switchTab('graph'));
  await page.waitForTimeout(1200);
  // Force, explicitly: the drag below only exists in the force layout, and the
  // stored layout is whatever the last sweep left behind.
  await page.evaluate(() => {
    const i = document.querySelector('input[name="graph-layout"][value="force"]');
    i.checked = true; i.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForTimeout(5000); // let the simulation settle: this is about the gesture
  await counters(page);

  const box = await page.evaluate(() => {
    const c = document.getElementById('graph-canvas');
    const r = c.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  const cx = Math.round(box.x + box.w / 2);
  const cy = Math.round(box.y + box.h / 2);

  const session = await page.context().newCDPSession(page);
  await session.send('Profiler.enable');
  await session.send('Profiler.setSamplingInterval', { interval: 80 });

  // --- a pan across empty space -------------------------------------------
  // The start has to be empty canvas (a node under it makes this a drag) and
  // clear of the floating chrome (the dock, the legend, the minimap, the zoom
  // strip all sit over the canvas and eat the gesture).
  // Zoomed in first: fitted to the view, the minimap's viewport rectangle
  // already covers the whole extent and is clamped to the box, so a pan could
  // not move it and the check below would prove nothing.
  await page.mouse.move(cx, cy);
  for (let i = 0; i < 6; i += 1) await page.mouse.wheel(0, -120);
  await page.waitForTimeout(500);
  const from = await page.evaluate(() => {
    const d = window.__graphDebug;
    const c = document.getElementById('graph-canvas');
    const r = c.getBoundingClientRect();
    const t = d.transform;
    const pts = d.nodeGeometry.map((n) => [r.left + n.x * t.k + t.x, r.top + n.y * t.k + t.y]);
    const chrome = ['graph-dock', 'graph-legend', 'graph-minimap', 'graph-zoom', 'graph-selection-dock', 'graph-time']
      .map((id) => document.getElementById(id))
      .filter((el) => el && el.offsetParent !== null)
      .map((el) => el.getBoundingClientRect());
    for (let gy = r.top + 60; gy < r.bottom - 60; gy += 20) {
      for (let gx = r.left + 60; gx < r.right - 60; gx += 20) {
        if (pts.some(([px, py]) => Math.hypot(px - gx, py - gy) < 60)) continue;
        if (chrome.some((b) => gx > b.left - 12 && gx < b.right + 12 && gy > b.top - 12 && gy < b.bottom + 12)) continue;
        if (gx + 40 * 6 > r.right - 20 || gy + 40 * 4 > r.bottom - 20) continue;
        return { x: Math.round(gx), y: Math.round(gy) };
      }
    }
    return null;
  });
  if (!from) { console.log('no empty start point for a pan'); await browser.close(); return; }
  const frameBefore = await page.evaluate(() => {
    const f = document.getElementById('graph-minimap-frame');
    return f ? [f.getAttribute('x'), f.getAttribute('y')].join(',') : 'none';
  });
  const dotsBefore = await page.evaluate(() => document.querySelectorAll('#graph-minimap-dots circle').length);
  await start(page);
  await session.send('Profiler.start');
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  for (let i = 1; i <= 40; i += 1) {
    await page.mouse.move(from.x + i * 6, from.y + i * 4);
  }
  await page.mouse.up();
  await page.waitForTimeout(300);
  const panProfile = await session.send('Profiler.stop');
  const pan = await stop(page);
  const frameAfter = await page.evaluate(() => {
    const f = document.getElementById('graph-minimap-frame');
    return f ? [f.getAttribute('x'), f.getAttribute('y')].join(',') : 'none';
  });

  // --- a wheel zoom --------------------------------------------------------
  await start(page);
  await page.mouse.move(cx, cy);
  for (let i = 0; i < 20; i += 1) await page.mouse.wheel(0, -60);
  await page.waitForTimeout(300);
  const zoom = await stop(page);

  // --- a node drag ---------------------------------------------------------
  // Refit first: the pan and the zoom above have moved the camera, and a drag
  // needs a node actually on screen.
  await page.click('#graph-canvas');
  await page.keyboard.press('0');
  await page.waitForTimeout(700);
  const target = await page.evaluate(() => {
    const d = window.__graphDebug;
    const c = document.getElementById('graph-canvas');
    const r = c.getBoundingClientRect();
    const t = d.transform;
    for (const n of d.nodeGeometry) {
      if (n.group) continue;
      const sx = r.left + n.x * t.k + t.x;
      const sy = r.top + n.y * t.k + t.y;
      if (sx > r.left + 80 && sx < r.right - 200 && sy > r.top + 80 && sy < r.bottom - 200) {
        return { x: Math.round(sx), y: Math.round(sy), id: n.id };
      }
    }
    return null;
  });
  let drag = { total: 0, byId: {}, sel: {} };
  let dragProfile = null;
  if (target) {
    await start(page);
    await session.send('Profiler.start');
    await page.mouse.move(target.x, target.y);
    await page.mouse.down();
    for (let i = 1; i <= 40; i += 1) await page.mouse.move(target.x + i * 3, target.y + i * 2);
    await page.mouse.up();
    await page.waitForTimeout(300);
    dragProfile = await session.send('Profiler.stop');
    drag = await stop(page);
  }

  const selfTime = (profile, names) => {
    if (!profile) return {};
    const p = profile.profile;
    const byId = new Map(p.nodes.map((n) => [n.id, n]));
    const hits = new Map();
    for (const n of p.nodes) hits.set(n.id, n.hitCount || 0);
    const out = {};
    for (const n of p.nodes) {
      const name = n.callFrame.functionName;
      if (!names.includes(name)) continue;
      out[name] = (out[name] || 0) + (hits.get(n.id) || 0);
    }
    void byId;
    return out;
  };
  const WATCH = ['graphMinimapPaint', 'gcDraw', 'gcHighlight', 'graphNodeUnder', 'gcRequestDraw'];
  const samples = 0.08; // ms per profiler sample at the interval set above

  console.log(`pan  (40 moves): ${pan.total} document lookups  [${top(pan.byId, 4)}] [${top(pan.sel, 2)}]`);
  const ps = selfTime(panProfile, WATCH);
  console.log(`     self time: ${Object.entries(ps).map(([k, v]) => `${k} ${(v * samples).toFixed(2)}ms`).join(', ') || 'none sampled'}`);
  console.log(`zoom (20 wheels): ${zoom.total} document lookups  [${top(zoom.byId, 4)}] [${top(zoom.sel, 2)}]`);
  console.log(`drag (40 moves, node ${target ? target.id : '-'}): ${drag.total} document lookups  [${top(drag.byId, 4)}]`);
  const ds = selfTime(dragProfile, WATCH);
  console.log(`     self time: ${Object.entries(ds).map(([k, v]) => `${k} ${(v * samples).toFixed(2)}ms`).join(', ') || 'none sampled'}`);
  // The minimap must still do its job: the viewport rectangle follows the pan,
  // and a relayout still repaints the dots rather than leaving the last set.
  console.log(`minimap frame ${frameBefore} -> ${frameAfter} (${dotsBefore} dots before the pan)`);
  await page.evaluate(() => {
    const i = document.querySelector('input[name="graph-layout"][value="tree"]');
    i.checked = true; i.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForTimeout(1600);
  const dotsTree = await page.evaluate(() => document.querySelectorAll('#graph-minimap-dots circle').length);
  const nodesTree = await page.evaluate(() => window.__graphDebug.nodes);
  console.log(`minimap dots after a relayout: ${dotsTree} for ${nodesTree} nodes`);

  const fails = [];
  const graphish = (m) => Object.entries(m).filter(([k]) => k.startsWith('graph')).map(([k, v]) => `${k}=${v}`);
  const panGraph = graphish(pan.byId);
  const zoomGraph = graphish(zoom.byId);
  const dragGraph = graphish(drag.byId);
  // One lookup per gesture is a one-off (closing a popup, say). What this is
  // guarding against is a lookup that scales with the number of events, which
  // shows up as a count near the 40 moves rather than as a 1.
  const perEvent = (m) => Object.entries(m).filter(([k, v]) => k.startsWith('graph') && v > 3).map(([k, v]) => `${k}=${v}`);
  const panGraph2 = perEvent(pan.byId);
  const zoomGraph2 = perEvent(zoom.byId);
  if (panGraph2.length) fails.push(`pan walks the document once per event: ${panGraph2.join(' ')}`);
  if (zoomGraph2.length) fails.push(`zoom walks the document once per event: ${zoomGraph2.join(' ')}`);
  // The drag is deliberately not held to that: the notes really are moving
  // under it, so the worker's own throttled repaint (one in eight ticks) is
  // the minimap doing its job rather than work in the wrong place.
  void panGraph; void zoomGraph; void dragGraph;
  if (frameBefore === frameAfter) fails.push(`the minimap viewport rectangle did not move during the pan (${frameAfter})`);
  if (dotsTree !== nodesTree) fails.push(`the minimap has ${dotsTree} dots for ${nodesTree} nodes after a relayout`);
  await browser.close();
  if (fails.length) { console.log('FAIL\n- ' + fails.join('\n- ')); process.exit(1); }
  console.log('PASS');
})();
