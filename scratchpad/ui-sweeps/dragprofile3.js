// Where a drag's main-thread time actually goes, from a real CPU profile.
//
// The three dead ends are recorded in `agent-remaining/mindmap.md`: frame rate
// is useless here (this sandbox is vsync-bound at about 16.7ms in every
// condition anyone has tried), synthetic PointerEvents never reach d3's drag
// behaviour, and `openWhiteboardBoard(id)` from `page.evaluate` leaves the
// boards landing showing. This starts past all three.
//
// It also starts past `dragprofile2.js`, which wrapped the *global* suspects.
// The drag handlers themselves (`objDragStart`, `objDragMove`, `objDragEnd`,
// `wbAlignmentGuides`) are inside an IIFE and have no global binding, so no
// amount of monkey-patching can see them. A CDP CPU profile can: it samples
// the stack, so every frame of it is attributed whether or not the function
// has a name anyone else can reach.
//
//   BASE=http://127.0.0.1:8932 SCRATCH=/tmp/mm-wb4 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/dragprofile3.js
const { boot } = require("./lib.js");

const MOVES = Number(process.env.MOVES || 60);
const OBJECTS = Number(process.env.OBJECTS || 120);

// Self time per function, from a CDP profile's sample counts. `timeDeltas`
// are the real microsecond gaps between samples, so this is measured time and
// not sample count times a nominal interval.
function selfTimes(profile) {
  const byId = new Map(profile.nodes.map((n) => [n.id, n]));
  const totals = new Map();
  const deltas = profile.timeDeltas || [];
  profile.samples.forEach((id, i) => {
    const node = byId.get(id);
    if (!node) return;
    const f = node.callFrame;
    const key = `${f.functionName || "(anonymous)"}  ${(f.url || "").split("/").pop()}:${f.lineNumber + 1}`;
    // The delta *after* a sample is the time that sample stands for.
    const dt = (deltas[i + 1] ?? deltas[i] ?? 0) / 1000;
    totals.set(key, (totals.get(key) || 0) + dt);
  });
  const wall = deltas.reduce((a, b) => a + b, 0) / 1000;
  return { rows: [...totals.entries()].sort((a, b) => b[1] - a[1]), wall };
}

async function profileDrag(page, client, at) {
  await client.send("Profiler.start");
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  for (let i = 1; i <= MOVES; i += 1) {
    await page.mouse.move(at.x + Math.round(Math.sin(i / 6) * 120), at.y + i * 2);
  }
  await page.mouse.up();
  await page.waitForTimeout(200);
  const { profile } = await client.send("Profiler.stop");
  return selfTimes(profile);
}

function report(title, { rows, wall }) {
  console.log(`\n=== ${title} (${MOVES} moves, ${wall.toFixed(0)}ms of profile) ===`);
  const idle = rows.find(([k]) => k.startsWith("(idle)"));
  const busy = rows.filter(([k]) => !k.startsWith("(idle)") && !k.startsWith("(program)"))
    .reduce((a, [, v]) => a + v, 0);
  console.log(`busy ${busy.toFixed(1)}ms, idle ${(idle ? idle[1] : 0).toFixed(1)}ms, ` +
    `${(busy / MOVES).toFixed(2)}ms of work per move`);
  for (const [k, v] of rows.slice(0, 18)) {
    if (v < 0.4) break;
    console.log(`  ${v.toFixed(1).padStart(7)}ms  ${k}`);
  }
}

(async () => {
  const { browser, page } = await boot({});
  const client = await page.context().newCDPSession(page);
  await client.send("Profiler.enable");
  // 100us: the drag frames are short and the default 1ms hides them inside
  // one sample each.
  await client.send("Profiler.setSamplingInterval", { interval: 100 });

  // --- An ordinary board with a hundred and twenty objects on it ----------
  await page.click('[data-tab="library"]').catch(() => {});
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]').catch(() => {});
  await page.waitForTimeout(900);
  const board = await page.evaluate(async (n) => {
    const h = { "X-Auth-Token": localStorage.getItem("token") || "", "Content-Type": "application/json" };
    const made = await (await fetch("/whiteboard/boards", {
      method: "POST", headers: h,
      body: JSON.stringify({ name: "Drag profile 3", type: "board" }),
    })).json();
    const id = made.id ?? made.board?.id;
    for (let i = 0; i < n; i += 1) {
      await fetch("/whiteboard/objects", {
        method: "POST", headers: h,
        body: JSON.stringify({
          kind: "text", board_id: id, x: (i % 20) * 130, y: Math.floor(i / 20) * 90,
          width: 120, height: 70, z: 0, rotation: null, group_id: null,
          data: { content: `card ${i}` },
        }),
      });
    }
    return id;
  }, OBJECTS);
  // Through the gallery, not `openWhiteboardBoard`: see the header.
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(1200);
  await page.click('.library-board-card:has-text("Drag profile 3")');
  await page.waitForSelector(".wb-object", { timeout: 20000 });
  await page.waitForTimeout(2000);
  const count = await page.evaluate(() => document.querySelectorAll(".wb-object").length);
  const at = await page.evaluate(() => {
    const el = document.querySelector(".wb-object");
    const b = el.getBoundingClientRect();
    return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2) };
  });
  console.log(`board: ${count} objects on screen`);
  report("board, one object dragged", await profileDrag(page, client, at));

  // --- How many draw loops are running behind that drag -------------------
  const loops = await page.evaluate(() => {
    const canvases = [...document.querySelectorAll("canvas.p5Canvas")];
    const visible = canvases.filter((c) => c.offsetWidth > 0 && c.offsetHeight > 0);
    return { canvases: canvases.length, visible: visible.length };
  });
  const raf = await page.evaluate(() => new Promise((resolve) => {
    // Count rAF *requests* over two idle seconds: each live p5 instance asks
    // for one per frame, so this counts the draw loops without knowing
    // anything about p5 itself.
    const orig = window.requestAnimationFrame;
    let requests = 0;
    let frames = 0;
    window.requestAnimationFrame = function (cb) { requests += 1; return orig.call(window, cb); };
    const t0 = performance.now();
    const tick = () => {
      frames += 1;
      if (performance.now() - t0 < 2000) orig.call(window, tick);
      else { window.requestAnimationFrame = orig; resolve({ frames, requests }); }
    };
    orig.call(window, tick);
  }));
  console.log(`\np5 canvases alive: ${loops.canvases}, of them visible: ${loops.visible}`);
  console.log(`idle rAF over 2s: ${raf.frames} frames, ${raf.requests} requests ` +
    `(${(raf.requests / raf.frames).toFixed(1)} per frame)`);

  // --- The same drag with the invisible draw loops stopped ----------------
  const stopped = await page.evaluate(() => {
    let n = 0;
    for (const [holder, instance] of emblemInstances) {
      if (holder && holder.offsetWidth === 0 && holder.offsetHeight === 0) { instance.noLoop(); n += 1; }
    }
    return n;
  });
  console.log(`\n(${stopped} invisible emblem loops stopped: the same drag again)`);
  report("board, invisible emblem loops stopped", await profileDrag(page, client, at));

  // --- And with everything else on the board hidden as well ---------------
  const hidden = await page.evaluate(() => {
    const els = [...document.querySelectorAll(".wb-object")].slice(1);
    els.forEach((e) => { e.style.display = "none"; });
    return els.length;
  });
  console.log(`\n(${hidden} objects hidden as well)`);
  report("board, everything else hidden", await profileDrag(page, client, at));

  await browser.close();
})();
