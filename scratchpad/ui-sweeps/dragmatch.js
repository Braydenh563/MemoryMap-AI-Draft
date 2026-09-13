// Does the thing you are dragging keep up with the pointer?
//
// Reported repeatedly as "the whiteboard is still laggy to drag and pan
// around", unattributed after three passes, and measured once by an agent that
// was cut off before it could fix it: "The shape moves 30px for a 60px drag at
// 2x; a card moves 60px."
//
// "Lag" is the word for what that looks like: an item that travels less than
// the pointer trails behind it and never catches up, which reads as the canvas
// being slow rather than as the arithmetic being wrong. This measures it
// directly: drag a known screen distance, ask how far the item's own box moved
// on screen, and compare. A correct drag moves the item exactly as far as the
// pointer, at every zoom.
const { boot } = require("./lib.js");
(async () => {
  const { page, browser } = await boot({});
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 120)); });
  await page.click('[data-tab="library"]'); await page.waitForTimeout(700);
  await page.click('[data-target="library-view-whiteboard"]'); await page.waitForTimeout(1500);
  await page.evaluate(() => {
    const card = [...document.querySelectorAll("#library-boards-grid .library-board-card")]
      .find((c) => /Default board/i.test(c.textContent));
    (card || document.querySelector("#library-boards-grid .library-board-card"))?.click();
  });
  await page.waitForTimeout(3500);

  const boxOf = (sel) => page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: +(r.left + r.width / 2).toFixed(1), y: +(r.top + r.height / 2).toFixed(1), w: Math.round(r.width) };
  }, sel);

  const zoomTo = async (clicks, which) => {
    for (let i = 0; i < clicks; i += 1) { await page.click(which); await page.waitForTimeout(300); }
    await page.waitForTimeout(500);
    return page.evaluate(() => {
      const g = document.querySelector("#wb-zoom-group");
      return g ? +new DOMMatrix(getComputedStyle(g).transform).a.toFixed(3) : null;
    });
  };

  const dragBy = async (sel, dx, dy) => {
    const before = await boxOf(sel);
    if (!before) return null;
    await page.mouse.move(before.x, before.y);
    await page.mouse.down();
    // Several steps, the way a hand moves: one jump can be coalesced into a
    // single event and hide a per-frame arithmetic error entirely.
    for (let i = 1; i <= 6; i += 1) {
      await page.mouse.move(before.x + (dx * i) / 6, before.y + (dy * i) / 6);
      await page.waitForTimeout(30);
    }
    await page.mouse.up();
    await page.waitForTimeout(400);
    const after = await boxOf(sel);
    return { movedX: +(after.x - before.x).toFixed(1), movedY: +(after.y - before.y).toFixed(1) };
  };

  const report = async (label, k) => {
    for (const [what, sel] of [["card", ".node-card"], ["sketch", ".sketch-group"]]) {
      const got = await dragBy(sel, 60, 0);
      if (!got) { console.log(`${label} ${what}: not on this board`); continue; }
      const ratio = (got.movedX / 60).toFixed(2);
      const verdict = Math.abs(got.movedX - 60) <= 3 ? "follows the pointer" : `LAGS: ${ratio}x the pointer`;
      console.log(`${label} k=${k} ${what}: pointer 60px -> moved ${got.movedX}px  (${verdict})`);
      await dragBy(sel, -got.movedX, 0); // put it back
    }
  };

  let k = await page.evaluate(() => {
    const g = document.querySelector("#wb-zoom-group");
    return g ? +new DOMMatrix(getComputedStyle(g).transform).a.toFixed(3) : null;
  });
  await report("1x  ", k);
  k = await zoomTo(4, "#wb-zoom-in");
  await report("zoom", k);
  k = await zoomTo(8, "#wb-zoom-out");
  await report("out ", k);
  console.log("errors: " + (errs.length ? errs.join(" | ") : "0"));
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
