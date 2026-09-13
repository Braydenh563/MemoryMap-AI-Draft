// The note composer's formatting strip and the note edit form's clone of it,
// against the document editor's own (INBOX 114, "the height of the cature a
// thought taskbar and note edit form are really high compared to the one in
// the documents editor"). Measures each strip in both toolbar modes and
// screenshots it, rather than reading the stylesheet: the modes are written at
// different specificities and that is where the height came from.
//
//   BASE=http://127.0.0.1:8853 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//   node scratchpad/ui-sweeps/toolbarh.js
const { boot } = require("./lib.js");
const m = (sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const c = getComputedStyle(el);
  const kids = [...el.children].filter((k) => k.getBoundingClientRect().height > 0);
  const tops = new Set(kids.map((k) => Math.round(k.getBoundingClientRect().top)));
  return { h: Math.round(r.height), w: Math.round(r.width), pad: c.padding, rowGap: c.rowGap,
    lines: tops.size, kids: kids.length, mode: el.dataset.toolbarMode || "wrap",
    collapsed: el.classList.contains("is-collapsed"),
    scrollW: el.scrollWidth, clientW: el.clientWidth };
};
(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await page.waitForTimeout(1500);
  await page.evaluate(() => switchTab("notes"));
  await page.waitForTimeout(1200);
  await page.click('#notes-subtabs button[data-section="capture"]');
  await page.waitForTimeout(2500);
  await page.evaluate(() => setDocToolbarCollapsed(false));
  await page.waitForTimeout(800);
  console.log("capture wrap " + JSON.stringify(await page.evaluate(m, "#note-toolbar")));
  const box = await page.$("#note-toolbar");
  await box.screenshot({ path: "/tmp/tb-note-wrap.png" });
  await page.evaluate(() => setDocToolbarMode("row"));
  await page.waitForTimeout(700);
  console.log("capture row  " + JSON.stringify(await page.evaluate(m, "#note-toolbar")));
  await (await page.$("#note-toolbar")).screenshot({ path: "/tmp/tb-note-row.png" });
  // The note card's edit form carries a clone of the same strip.
  for (const mode of ["wrap", "row"]) {
    await page.evaluate((m) => setDocToolbarMode(m), mode);
    await page.waitForTimeout(400);
    await page.click('#notes-subtabs button[data-section="browse"]');
    await page.waitForTimeout(1200);
    const ok = await page.evaluate(() => {
      const b = document.querySelector(".entry-actions [title='Edit this entry']");
      if (!b) return "no edit button";
      b.click();
      return "ok";
    });
    await page.waitForTimeout(1200);
    console.log(`edit form ${mode}  ` + ok + " " + JSON.stringify(await page.evaluate(m, ".note-edit-toolbar")));
    const el = await page.$(".note-edit-toolbar");
    if (el) await el.screenshot({ path: `/tmp/tb-edit-${mode}.png` });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    await page.click('#notes-subtabs button[data-section="capture"]');
    await page.waitForTimeout(800);
  }
  await page.evaluate(() => setDocToolbarMode("wrap"));
  await page.waitForTimeout(500);
  await page.evaluate(() => switchTab("documents"));
  await page.waitForTimeout(1500);
  await page.click("#doc-new");
  await page.waitForTimeout(2000);
  await page.evaluate(() => setDocToolbarCollapsed(false));
  await page.waitForTimeout(800);
  console.log("doc wrap     " + JSON.stringify(await page.evaluate(m, "#doc-toolbar")));
  await (await page.$("#doc-toolbar")).screenshot({ path: "/tmp/tb-doc-wrap.png" });
  await page.evaluate(() => setDocToolbarMode("row"));
  await page.waitForTimeout(700);
  console.log("doc row      " + JSON.stringify(await page.evaluate(m, "#doc-toolbar")));
  await (await page.$("#doc-toolbar")).screenshot({ path: "/tmp/tb-doc-row.png" });
  await browser.close();
})();
