// The note edit form's formatting bar, while the note is scrolled.
//
// Reported: "when I open the edit form for a note and scroll down, only the
// bottom of the formatting bar sticks to the top of the screen and the bar is
// clear so it is hard to see", with a screenshot of the bar's icons and the
// note's own text legible through each other.
const { boot } = require("./lib.js");
(async () => {
  const { page, browser } = await boot({});
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 120)); });
  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(1500);
  // Open the edit form on the long note.
  const opened = await page.evaluate(() => {
    const cards = [...document.querySelectorAll("#entry-list li")];
    // Any note will do: the bar is the same markup on every one. The named
    // note was a seeded fixture that does not survive a fresh data dir.
    const card = cards.find((li) => /sticky toolbar/i.test(li.textContent || "")) || cards[0];
    if (!card) return "no card";
    const edit = [...card.querySelectorAll("button")].find((b) => /edit/i.test(b.textContent + (b.title || "")));
    if (!edit) return "no edit button";
    edit.click();
    return "opened";
  });
  console.log("open: " + opened);
  await page.waitForTimeout(1800);
  console.log(await page.evaluate(() => {
    const bar = document.querySelector(".note-edit-toolbar") || document.querySelector("#entry-list .doc-toolbar");
    if (!bar) return "no toolbar";
    const cs = getComputedStyle(bar);
    const r = bar.getBoundingClientRect();
    return JSON.stringify({
      position: cs.position, top: cs.top, zIndex: cs.zIndex,
      // Both layers: with the tint stacked over an opaque base the colour
      // layer is the base and the tint lives in background-image, so reading
      // backgroundColor alone would report the wrong thing either way.
      background: cs.backgroundColor,
      backgroundImage: cs.backgroundImage,
      opaque: !/rgba\([^)]*,\s*0?\.\d+\s*\)/.test(cs.backgroundColor),
      backdrop: cs.backdropFilter,
      rows: new Set([...bar.children].filter((c) => c.getBoundingClientRect().height > 4)
        .map((c) => Math.round(c.getBoundingClientRect().top / 12))).size,
      box: { top: Math.round(r.top), h: Math.round(r.height) },
    });
  }));
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
