// The selection kebab, opened twice, measured each time.
//
// Reported: "when I highlight text and the popup kebab button appears, the
// first time I click it, a little collapsed line appears below it, then I need
// to click the button to close the popup and reopen it for it to actually
// show, also the popup sitll has the left corner screen flicker before it
// shows in the right place."
//
// Two claims, both measurable: the menu's height on the first open against its
// height on the second, and where the menu is painted on the frame it is
// revealed (a box at the top left of the window for one frame is the flicker).
const { boot } = require("./lib.js");
(async () => {
  const { page, browser } = await boot({});
  const frames = [];
  if (process.env.WHERE === "logs") {
    await page.click("#settings-btn").catch(() => {});
    await page.waitForTimeout(900);
    await page.evaluate(() => {
      const row = [...document.querySelectorAll("#settings-modal [data-section], .modal-nav button")]
        .find((b) => /log/i.test(b.textContent || b.dataset.section || ""));
      row?.click();
    });
    await page.waitForTimeout(1800);
  } else {
    await page.click('[data-tab="notes"]').catch(() => {});
    await page.waitForTimeout(1200);
  }
  // Some prose to select: the app's own empty-state copy is always there.
  const target = await page.evaluate(() => {
    const el = [...document.querySelectorAll("p, .muted, h2, .entry-content, li")]
      .find((n) => {
        const r = n.getBoundingClientRect();
        return (n.textContent || "").trim().length > 30 && r.width > 120 && r.height > 8
          && n.checkVisibility?.() && !n.closest("input, textarea, select, .selection-popup");
      });
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x + 8, y: r.y + r.height / 2, w: r.width, text: el.textContent.trim().slice(0, 40) };
  });
  if (!target) { console.log("no prose to select"); await browser.close(); return; }
  console.log("selecting: " + JSON.stringify(target.text));
  await page.mouse.move(target.x, target.y);
  await page.mouse.down();
  await page.mouse.move(target.x + Math.min(160, target.w - 20), target.y, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(600);

  const open = async (label) => {
    // Watch every animation frame between the click and settling, so a single
    // painted frame at the wrong place is caught rather than reasoned about.
    await page.evaluate(() => {
      window.__mmFrames = [];
      const menu = document.querySelector(".selection-popup .action-menu, body > .action-menu:not(.hidden), body > .action-menu");
      if (!menu) return;
      let n = 0;
      const tick = () => {
        const r = menu.getBoundingClientRect();
        const cs = getComputedStyle(menu);
        window.__mmFrames.push({
          n: n++,
          hidden: menu.classList.contains("hidden"),
          vis: cs.visibility,
          left: Math.round(r.left), top: Math.round(r.top),
          w: Math.round(r.width), h: Math.round(r.height),
        });
        if (n < 12) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    await page.click(".selection-popup [aria-haspopup]");
    await page.waitForTimeout(500);
    const out = await page.evaluate(() => {
      const menu = document.querySelector(".selection-popup .action-menu, body > .action-menu:not(.hidden), body > .action-menu");
      const r = menu ? menu.getBoundingClientRect() : null;
      return {
        frames: (window.__mmFrames || []).filter((f) => !f.hidden),
        settled: r ? { left: Math.round(r.left), top: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) } : null,
        items: menu ? menu.querySelectorAll("button").length : 0,
        maxHeight: menu ? getComputedStyle(menu).maxHeight : null,
      };
    });
    console.log(`${label}: settled=${JSON.stringify(out.settled)} items=${out.items} maxH=${out.maxHeight}`);
    for (const f of out.frames.slice(0, 4)) {
      console.log(`   frame ${f.n}: vis=${f.vis} at ${f.left},${f.top} ${f.w}x${f.h}`);
    }
    frames.push(out);
  };

  await open("open 1");
  await page.click(".selection-popup [aria-haspopup]"); // close
  await page.waitForTimeout(400);
  await open("open 2");

  const [one, two] = frames;
  if (one.settled && two.settled) {
    console.log(`VERDICT height first=${one.settled.h} second=${two.settled.h} ` +
      (one.settled.h < two.settled.h - 4 ? "COLLAPSED ON FIRST OPEN" : "same"));
  }
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
