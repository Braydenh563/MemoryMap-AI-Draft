// A `[[link]]` in the document editor shows the note's name, not the markup
// its first line happens to start with.
//
// Reported twice: "note links have inline md not rendered or suppressed", then
// "document reference links still show inline md" with a screenshot of the
// editor drawing "# Girl with bell" inside the link chip.
const { boot } = require("./lib.js");
(async () => {
  const { page, browser } = await boot({});
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 120)); });
  await page.click('[data-tab="library"]'); await page.waitForTimeout(700);
  await page.click('[data-target="library-view-documents"]').catch(() => {});
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    const t = [...document.querySelectorAll("#library-view-documents .library-card-title")]
      .find((n) => /Link markup probe/.test(n.textContent));
    (t?.closest(".library-card") || t)?.click();
  });
  await page.waitForTimeout(4000);
  const seen = await page.evaluate(() => {
    const chips = [...document.querySelectorAll(".cm-md-wiki")];
    return chips.map((c) => ({ shown: c.textContent, target: c.getAttribute("data-doc-wiki") }));
  });
  console.log("chips: " + JSON.stringify(seen, null, 1));
  const bad = seen.filter((c) => /^#/.test(c.shown));
  console.log(bad.length ? `FAIL: ${bad.length} chip(s) still draw a heading marker` : "PASS: no chip draws a heading marker");
  console.log("targets keep the full spec: " + seen.every((c) => c.target && c.target.length >= c.shown.length));
  console.log("errors: " + (errs.length ? errs.join(" | ") : "0"));
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
