// The "m" chord guide: are its rows real controls, and do they go anywhere?
//
// Reported: "also make these popup options when I press m, actual clickable
// nav buttons". They were `<div>`s inside a `pointer-events: none` sheet.
const { boot } = require("./lib.js");
(async () => {
  const { page, browser } = await boot({});
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 120)); });
  await page.click('[data-tab="dashboard"]').catch(() => {});
  await page.waitForTimeout(900);
  await page.keyboard.press("m");
  await page.waitForTimeout(600);
  console.log(await page.evaluate(() => {
    const guide = document.getElementById("chord-guide");
    const rows = [...guide.querySelectorAll(".chord-guide-row")];
    const r0 = rows[0]?.getBoundingClientRect();
    return JSON.stringify({
      open: !guide.classList.contains("hidden"),
      rows: rows.length,
      tags: [...new Set(rows.map((r) => r.tagName))],
      pointerEvents: rows[0] ? getComputedStyle(rows[0]).pointerEvents : null,
      scrimPointerEvents: getComputedStyle(guide).pointerEvents,
      firstRow: r0 ? `${Math.round(r0.width)}x${Math.round(r0.height)}` : null,
      labels: rows.map((r) => r.textContent),
      tabbable: rows.filter((r) => r.tabIndex >= 0).length,
    });
  }));
  // The real test: click "Graph" and see where we land.
  const before = await page.evaluate(() => document.querySelector("#tab-bar button.active")?.textContent?.trim());
  await page.evaluate(() => {
    [...document.querySelectorAll(".chord-guide-row")].find((r) => /Graph/.test(r.textContent))?.click();
  });
  await page.waitForTimeout(1500);
  const after = await page.evaluate(() => ({
    tab: document.querySelector("#tab-bar button.active")?.textContent?.trim(),
    guideHidden: document.getElementById("chord-guide")?.classList.contains("hidden"),
  }));
  console.log(`clicked Graph: tab ${before} -> ${after.tab}, guide hidden: ${after.guideHidden}`);
  // And the keyboard still works.
  await page.keyboard.press("m"); await page.waitForTimeout(400);
  await page.keyboard.press("n"); await page.waitForTimeout(1200);
  console.log("then pressed m,n -> " + await page.evaluate(() => document.querySelector("#tab-bar button.active")?.textContent?.trim()));
  console.log("errors: " + (errs.length ? errs.join(" | ") : "0"));
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
