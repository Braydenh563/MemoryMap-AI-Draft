// Reproduction probe for two owner reports (INBOX 114):
//   "the tree view on the graph is still broken"
//   "the note node popups dont show on any of the graph views ... except force"
// It measures rather than looks: per layout it reads the laid-out positions
// off `__graphDebug`, counts link crossings, checks that depth increases away
// from the root, and then clicks a real node with a trusted mouse event and
// records whether the popup opened.
const { boot } = require('./lib.js');

// Segment intersection, proper crossings only (shared endpoints do not count:
// a tree's edges all meet at their parents).
function crosses(a, b) {
  const same = (p, q) => Math.abs(p[0] - q[0]) < 0.01 && Math.abs(p[1] - q[1]) < 0.01;
  for (const p of [a[0], a[1]]) for (const q of [b[0], b[1]]) if (same(p, q)) return false;
  const d = (p, q, r) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const d1 = d(a[0], a[1], b[0]), d2 = d(a[0], a[1], b[1]);
  const d3v = d(b[0], b[1], a[0]), d4 = d(b[0], b[1], a[1]);
  return ((d1 > 0) !== (d2 > 0)) && ((d3v > 0) !== (d4 > 0));
}

(async () => {
  const { browser, page } = await boot();
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text().slice(0, 140)); });
  await page.evaluate(() => switchTab('graph'));
  await page.waitForTimeout(2500);

  const fails = [];
  for (const layout of ['force', 'tree', 'radial', 'arc']) {
    await page.evaluate((l) => {
      const input = document.querySelector(`input[name="graph-layout"][value="${l}"]`);
      input.checked = true;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, layout);
    await page.waitForTimeout(2200);

    const geo = await page.evaluate(() => {
      const d = window.__graphDebug;
      return {
        layout: d.layout, renderer: d.renderer, nodes: d.nodes, edges: d.edges,
        k: d.transform.k, x: d.transform.x, y: d.transform.y,
        n: d.nodeGeometry, e: d.edgeGeometry,
      };
    });

    // Depth monotonicity: on tree and arc, x must increase with depth; on the
    // radial, the radius must.
    const byDepth = new Map();
    for (const n of geo.n) {
      if (n.depth == null) continue;
      const v = layout === 'radial' ? Math.hypot(n.x, n.y) : n.x;
      if (!byDepth.has(n.depth)) byDepth.set(n.depth, []);
      byDepth.get(n.depth).push(v);
    }
    const depths = [...byDepth.keys()].sort((a, b) => a - b);
    const bands = depths.map((dd) => {
      const v = byDepth.get(dd);
      return { d: dd, n: v.length, min: +Math.min(...v).toFixed(1), max: +Math.max(...v).toFixed(1) };
    });
    let monotonic = true;
    for (let i = 1; i < bands.length; i += 1) if (bands[i].min <= bands[i - 1].max - 0.5) monotonic = false;

    let cross = 0;
    for (let i = 0; i < geo.e.length; i += 1) {
      for (let j = i + 1; j < geo.e.length; j += 1) {
        const a = [[geo.e[i][0], geo.e[i][1]], [geo.e[i][2], geo.e[i][3]]];
        const b = [[geo.e[j][0], geo.e[j][1]], [geo.e[j][2], geo.e[j][3]]];
        if (crosses(a, b)) cross += 1;
      }
    }

    // Click a real node with a trusted event, and see whether the popup opened.
    const target = await page.evaluate(() => {
      const nodes = window.__graphDebug.nodeGeometry.filter((n) => !n.group);
      if (!nodes.length) return null;
      const t = window.__graphDebug.transform;
      const canvas = document.getElementById('graph-canvas');
      const box = canvas.getBoundingClientRect();
      // Pick the node nearest the centre of the viewport so the click lands
      // inside the canvas whatever the camera did.
      let best = null;
      for (const n of nodes) {
        const sx = box.left + n.x * t.k + t.x;
        const sy = box.top + n.y * t.k + t.y;
        if (sx < box.left + 20 || sx > box.right - 20 || sy < box.top + 20 || sy > box.bottom - 20) continue;
        const dd = Math.hypot(sx - (box.left + box.width / 2), sy - (box.top + box.height / 2));
        if (!best || dd < best.d) best = { d: dd, x: sx, y: sy, id: n.id };
      }
      return best;
    });

    let popup = 'no node on screen';
    if (target) {
      await page.evaluate(() => { if (typeof closeGraphPopup === 'function') closeGraphPopup(); });
      await page.mouse.move(target.x, target.y);
      await page.waitForTimeout(120);
      await page.mouse.down();
      await page.mouse.up();
      await page.waitForTimeout(900);
      popup = await page.evaluate(() => {
        const p = document.getElementById('graph-popup');
        if (!p) return 'no #graph-popup';
        const r = p.getBoundingClientRect();
        const shown = !p.classList.contains('hidden') && r.width > 0 && r.height > 0;
        return shown ? `open ${Math.round(r.width)}x${Math.round(r.height)}` : 'closed';
      });
    }

    console.log(`${layout}: renderer=${geo.renderer} layout=${geo.layout} nodes=${geo.nodes} edges=${geo.edges} k=${geo.k.toFixed(3)} crossings=${cross}`);
    console.log(`  depth bands ${JSON.stringify(bands)} monotonic=${monotonic}`);
    console.log(`  click node ${target ? target.id : '-'} -> popup ${popup}`);
    if (layout !== 'force' && geo.layout !== layout) fails.push(`${layout}: __graphDebug says layout=${geo.layout}`);
    // The arc is the exception by design: it puts *every* node, whatever its
    // depth, on one baseline in pre-order, so depth maps to nothing on x. Its
    // own invariant is that single baseline, checked instead.
    if ((layout === 'tree' || layout === 'radial') && !monotonic) {
      fails.push(`${layout}: depth does not increase away from the root`);
    }
    if (layout === 'arc') {
      const ys = geo.n.map((n) => n.y);
      const spread = Math.max(...ys) - Math.min(...ys);
      console.log(`  arc baseline spread ${spread.toFixed(1)}`);
      if (spread > 0.5) fails.push(`arc: nodes are ${spread.toFixed(1)}px off one baseline`);
    }
    if (layout === 'tree' && cross) fails.push(`${layout}: ${cross} pairs of links cross`);
    if (!String(popup).startsWith('open')) fails.push(`${layout}: clicking a node did not open the popup (${popup})`);
  }

  if (errs.length) fails.push(`page errors: ${errs.slice(0, 3).join(' | ')}`);
  if (fails.length) { console.log('FAIL\n- ' + fails.join('\n- ')); await browser.close(); process.exit(1); }
  console.log('PASS');
  await browser.close();
})();
