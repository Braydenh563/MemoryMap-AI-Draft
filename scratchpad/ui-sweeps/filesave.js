// The Files row's kebab, and whether "Save a copy" really hands over the file.
const { boot } = require("./lib.js");
(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(1200);
  await page.evaluate(async () => {
    const h = { "X-Auth-Token": localStorage.getItem("token") || "" };
    const e = await fetch("/entries", { method: "POST", headers: { ...h, "Content-Type": "application/json" },
      body: JSON.stringify({ content: "A note that carries a handout." }) });
    const entry = await e.json();
    const fd = new FormData();
    fd.append("file", new File(["# Agents\n\nsome text"], "saveme.md", { type: "text/markdown" }));
    await fetch(`/entries/${entry.id}/files`, { method: "POST", body: fd, headers: h });
  });
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"], [data-subtab="files"], #library-subtab-files').catch(() => {});
  await page.waitForTimeout(2500);
  await page.click(".library-file-rows .library-image-tile .library-image-actions button");
  await page.waitForTimeout(400);
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll('[role="menu"] [role="menuitem"], .menu-item')]
      .filter((el) => el.getBoundingClientRect().width > 0)
      .map((el) => el.textContent.trim()));
  console.log("kebab rows:", JSON.stringify(rows));
  const dl = page.waitForEvent("download", { timeout: 8000 }).catch((e) => null);
  await page.evaluate(() => {
    const item = [...document.querySelectorAll('[role="menuitem"], .menu-item')]
      .find((el) => /save a copy/i.test(el.textContent));
    if (item) item.click();
  });
  const got = await dl;
  console.log("download:", got ? got.suggestedFilename() : "none");
  await browser.close();
})();
