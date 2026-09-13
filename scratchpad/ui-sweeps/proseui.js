// The writing-intelligence surfaces: how much of the window the suggestions
// panel takes, and where the word menu opens from each of the two ways in.
//
// Reported: "the suggestions box at the bottom takes up a lot of my screen and
// it makes the text editor really small ... and when I click on the issue from
// the suggestions thing, the box just appears right there in my face."
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
      .find((n) => /Spelling probe/.test(n.textContent));
    (t?.closest(".library-card") || t)?.click();
  });
  await page.waitForTimeout(4000);
  await page.click(".cm-content").catch(() => {});
  await page.waitForTimeout(2500);

  // Open the suggestions panel from the count pill.
  await page.evaluate(() => {
    document.querySelector("[aria-controls='doc-prose-panel']")?.click();
  });
  await page.waitForTimeout(900);
  console.log(await page.evaluate(() => {
    const panel = document.getElementById("doc-prose-panel");
    const editor = document.querySelector(".cm-editor");
    const pr = panel?.getBoundingClientRect(), er = editor?.getBoundingClientRect();
    return JSON.stringify({
      panel: pr ? { h: Math.round(pr.height), pctOfWindow: Math.round((pr.height / window.innerHeight) * 100) } : "closed",
      editor: er ? { h: Math.round(er.height), pctOfWindow: Math.round((er.height / window.innerHeight) * 100) } : null,
    });
  }));

  // Press a row in the panel, then ask where the menu landed.
  const where = await page.evaluate(async () => {
    const row = document.querySelector("#doc-prose-panel .doc-prose-list button");
    if (!row) return "no row";
    const rowRect = row.getBoundingClientRect();
    row.click();
    await new Promise((r) => setTimeout(r, 700));
    const menu = document.getElementById("doc-suggest-menu");
    if (!menu || menu.classList.contains("hidden")) return "menu did not open";
    const m = menu.getBoundingClientRect();
    const mark = [...document.querySelectorAll("[data-doc-finding]")][0];
    const k = mark?.getBoundingClientRect();
    return JSON.stringify({
      rowTop: Math.round(rowRect.top),
      menu: { left: Math.round(m.left), top: Math.round(m.top), w: Math.round(m.width), h: Math.round(m.height) },
      word: k ? { left: Math.round(k.left), top: Math.round(k.top), bottom: Math.round(k.bottom) } : null,
      gapFromWord: k ? Math.round(m.left - k.left) : null,
      onScreen: m.left >= 0 && m.top >= 0 && m.right <= window.innerWidth && m.bottom <= window.innerHeight,
    });
  });
  console.log("row click -> " + where);
  console.log("errors: " + (errs.length ? errs.join(" | ") : "0"));
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
