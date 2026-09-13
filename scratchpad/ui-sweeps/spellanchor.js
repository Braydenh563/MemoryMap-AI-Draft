// Where the spelling popup opens, against where the flagged word is.
//
// Reported: "I clicked on a flagged word and the popup didnt appear right next
// to it but off to the side with a wide gap".
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
  // Let the spell pass run.
  await page.click(".cm-content").catch(() => {});
  await page.waitForTimeout(2500);
  const mark = await page.evaluate(() => {
    const el = [...document.querySelectorAll("[data-doc-finding]")]
      .find((n) => /idk/i.test(n.textContent || ""));
    if (!el) return { found: false, marks: document.querySelectorAll("[data-doc-finding]").length };
    const r = el.getBoundingClientRect();
    return { found: true, text: el.textContent, left: Math.round(r.left), top: Math.round(r.top), bottom: Math.round(r.bottom), right: Math.round(r.right) };
  });
  console.log("mark: " + JSON.stringify(mark));
  if (!mark.found) { console.log("errors: " + errs.join(" | ")); await browser.close(); return; }
  await page.evaluate(() => {
    const el = [...document.querySelectorAll("[data-doc-finding]")].find((n) => /idk/i.test(n.textContent || ""));
    const r = el.getBoundingClientRect();
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
  });
  await page.waitForTimeout(900);
  const menu = await page.evaluate(() => {
    const m = document.getElementById("doc-suggest-menu");
    if (!m || m.classList.contains("hidden")) return { open: false };
    const r = m.getBoundingClientRect();
    return { open: true, left: Math.round(r.left), top: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  });
  console.log("menu: " + JSON.stringify(menu));
  if (menu.open) {
    console.log(`GAP left: menu.left - mark.left = ${menu.left - mark.left}px, vertical: menu.top - mark.bottom = ${menu.top - mark.bottom}px`);
  }
  console.log("errors: " + (errs.length ? errs.join(" | ") : "0"));
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
