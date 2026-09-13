// The whiteboard/mindmap View menu's height (INBOX 114, "the view dropdown
// menu in the whiteboard and mindmap is still broken"). Reported with "Snap to
// grid" cut in half at the bottom edge and a scrollbar present.
//
// Measures, per viewport: where the menu was put, what it was capped to, what
// it wants, how much of the window is left under it, and whether it scrolls.
//
//   BASE=http://127.0.0.1:8853 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//   node scratchpad/ui-sweeps/viewmenu.js
const { boot } = require("./lib.js");

const SIZES = (process.env.SIZES || "1440x900,1280x640,1512x830,1440x700").split(",")
  .map((s) => { const [w, h] = s.split("x").map(Number); return { width: w, height: h }; });
const KIND = process.env.KIND || "map";

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
}

(async () => {
  const { browser, page } = await boot({ viewport: SIZES[0] });
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(500);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(700);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  await page.fill(".confirm-overlay input[type=text]", "View menu");
  if (KIND === "map") await page.click('.confirm-overlay .seg button[data-value="map"]');
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2500);
  await page.keyboard.press("Escape");

  for (const size of SIZES) {
    await page.setViewportSize(size);
    await page.waitForTimeout(500);
    await page.click('[aria-controls="wb-view-menu"]');
    await page.waitForTimeout(400);
    const m = await page.evaluate(() => {
      const menu = document.getElementById("wb-view-menu");
      const r = menu.getBoundingClientRect();
      const cs = getComputedStyle(menu);
      const last = menu.querySelector(".wb-panel-group:last-child");
      const lr = last ? last.getBoundingClientRect() : null;
      return {
        top: Math.round(r.top), bottom: Math.round(r.bottom),
        h: Math.round(r.height), scrollH: menu.scrollHeight, clientH: menu.clientHeight,
        cap: cs.maxHeight, inline: menu.style.maxHeight,
        escaped: menu.classList.contains("action-menu-escaped"),
        win: window.innerHeight,
        roomBelowTop: Math.round(window.innerHeight - r.top),
        wasted: Math.round(window.innerHeight - r.bottom),
        scrolls: menu.scrollHeight > menu.clientHeight + 1,
        lastBottom: lr ? Math.round(lr.bottom) : null,
      };
    });
    console.log(`${size.width}x${size.height} ${JSON.stringify(m)}`);
    check(`${size.width}x${size.height}: the menu is as tall as the room under it`,
      !m.scrolls || m.wasted <= 16, JSON.stringify({ h: m.h, scrollH: m.scrollH, wasted: m.wasted }));
    check(`${size.width}x${size.height}: no item is cut in half`,
      !m.scrolls || m.clientH >= m.scrollH - 1 || m.wasted <= 16,
      JSON.stringify({ clientH: m.clientH, scrollH: m.scrollH }));
    await page.screenshot({ path: `/tmp/viewmenu-${size.width}x${size.height}.png` });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
  }

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
