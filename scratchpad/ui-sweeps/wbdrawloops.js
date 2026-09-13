// How many draw loops are running behind a whiteboard that nobody is touching.
//
// Found while profiling the drag report (WHITEBOARD_PLAN Phase 4): six p5
// emblems are built at boot and five of them live inside a panel that is
// `display: none` almost all the time, each with its own 24fps loop. Measured
// on an idle board: six canvases alive, one visible, and 5.0
// `requestAnimationFrame` requests per displayed frame.
//
// The count of rAF *requests* per displayed frame is the measurement, and it
// is machine-independent in a way frame timing here is not: each live p5
// instance asks for exactly one per frame, so the number is the number of
// draw loops, whatever the machine is doing.
//
// Deliberately not a claim about the drag lag itself, which is still
// unattributed (`agent-remaining/mindmap.md`).
//
//   BASE=http://127.0.0.1:8932 SCRATCH=/tmp/mm-wb4 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/wbdrawloops.js
const { boot } = require("./lib.js");

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
}

const RAF_PROBE = () => new Promise((resolve) => {
  const orig = window.requestAnimationFrame;
  let requests = 0;
  let frames = 0;
  window.requestAnimationFrame = function (cb) { requests += 1; return orig.call(window, cb); };
  const t0 = performance.now();
  const tick = () => {
    frames += 1;
    if (performance.now() - t0 < 2000) orig.call(window, tick);
    // Minus this probe's own tick, which is one request per frame.
    else { window.requestAnimationFrame = orig; resolve({ frames, requests: requests - frames }); }
  };
  orig.call(window, tick);
});

(async () => {
  const { browser, page } = await boot({});

  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(1200);
  await page.click(".library-board-card");
  await page.waitForTimeout(2500);

  const alive = await page.evaluate(() => {
    const canvases = [...document.querySelectorAll("canvas.p5Canvas")];
    return {
      canvases: canvases.length,
      visible: canvases.filter((c) => c.offsetWidth > 0 && c.offsetHeight > 0).length,
      looping: [...emblemInstances].filter(([, i]) => i.isLooping()).length,
      loopingUnseen: [...emblemInstances]
        .filter(([h, i]) => i.isLooping() && h.offsetWidth === 0 && h.offsetHeight === 0)
        .map(([h]) => h.id),
    };
  });
  check("no emblem draws while its own holder has no box",
    alive.loopingUnseen.length === 0,
    `${alive.canvases} canvases, ${alive.visible} visible, ${alive.looping} looping` +
    (alive.loopingUnseen.length ? `, unseen and looping: ${alive.loopingUnseen.join(", ")}` : ""));

  // The same two seconds twice, the second time with every emblem loop forced
  // back on: an A/B inside one run, so the difference is attributable to the
  // loops and to nothing about this machine.
  const quiet = await page.evaluate(RAF_PROBE);
  const forced = await page.evaluate(async () => {
    for (const [, instance] of emblemInstances) instance.loop();
    return true;
  });
  const loud = await page.evaluate(RAF_PROBE);
  await page.evaluate(() => {
    for (const [holder, instance] of emblemInstances) {
      if (holder.offsetWidth === 0 && holder.offsetHeight === 0) instance.noLoop();
    }
  });
  const quietPer = quiet.requests / Math.max(quiet.frames, 1);
  const loudPer = loud.requests / Math.max(loud.frames, 1);
  check("an idle board asks for fewer animation frames than it used to",
    forced && quietPer < loudPer - 1,
    `${quietPer.toFixed(1)} rAF requests per frame now, ${loudPer.toFixed(1)} with every ` +
    "emblem loop forced back on");

  // And the other half of the bargain: a mark that comes back on screen turns
  // again ("never static and always rotating", the owner, on the emblem).
  await page.click('[data-tab="chat"]');
  await page.waitForTimeout(1500);
  const resumed = await page.evaluate(() => {
    const holder = document.getElementById("chat-empty-emblem");
    const instance = emblemInstances.get(holder);
    return {
      shown: Boolean(holder && holder.offsetWidth > 0),
      looping: Boolean(instance && instance.isLooping()),
    };
  });
  check("an emblem that comes back into view turns again",
    !resumed.shown || resumed.looping,
    `chat-empty-emblem shown ${resumed.shown}, looping ${resumed.looping}`);

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) console.log("FAILED: " + failed.map((r) => r.label).join("; "));
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})();
