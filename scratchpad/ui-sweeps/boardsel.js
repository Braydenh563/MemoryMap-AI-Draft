// "Whiteboards and mindmaps need to be differentiable in the boards selector"
// (INBOX 115). What each selector says about a board's kind, before and after.
//
//   BASE=http://127.0.0.1:8857 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//   node scratchpad/ui-sweeps/boardsel.js
const { boot } = require("./lib.js");
const OPML = `<?xml version="1.0"?><opml version="2.0"><head><title>Selector map</title></head><body><outline text="Roots"><outline text="Alpha"/></outline></body></opml>`;

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await page.click('[data-tab="library"]'); await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]'); await page.waitForTimeout(900);

  // One map and one plain board, so both kinds are in every list.
  await page.evaluate(() => { const m = document.getElementById("library-boards-more"); if (m) m.open = true; });
  await page.waitForTimeout(250);
  await page.click("#wb-boards-import"); await page.waitForTimeout(400);
  await page.setInputFiles("#wb-import-map-file", { name: "s.opml", mimeType: "text/x-opml", buffer: Buffer.from(OPML) });
  await page.waitForTimeout(3500);

  // The top-bar selector, on the open map.
  const sel = await page.evaluate(() => {
    const s = document.getElementById("wb-board-select");
    if (!s) return null;
    const box = s.getBoundingClientRect();
    return {
      label: s.getAttribute("aria-label"),
      visible: box.width > 0 && box.height > 0,
      groups: [...s.querySelectorAll("optgroup")].map((g) => g.label),
      options: [...s.options].map((o) => `${o.parentElement.tagName === "OPTGROUP" ? "[" + o.parentElement.label + "] " : ""}${o.textContent}`),
    };
  });
  console.log("#wb-board-select:", JSON.stringify(sel, null, 2));

  await page.click("#wb-back-to-boards"); await page.waitForTimeout(1600);
  const cards = await page.evaluate(() =>
    [...document.querySelectorAll("#library-boards-grid .library-board-card")].map((c) => ({
      title: c.querySelector(".library-card-title")?.textContent,
      icon: c.querySelector(".library-card-icon i")?.className || c.querySelector(".library-card-icon")?.className,
      kind: c.querySelector(".library-card-kind")?.textContent || null,
      meta: c.querySelector(".library-card-meta")?.textContent,
    })));
  console.log("gallery cards:", JSON.stringify(cards, null, 2));
  await browser.close();
})();
