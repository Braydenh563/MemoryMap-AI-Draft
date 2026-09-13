// What a Files row shows and what it lets you do, measured (INBOX 115: "the
// files rows in files still needs some ui improvement and redesign, and
// better function"). One PDF and one markdown attachment, then the row's own
// geometry, its ink, its empty space, and every control on it.
//
//   BASE=http://127.0.0.1:8857 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//   node scratchpad/ui-sweeps/filesrow2.js
const { boot } = require("./lib.js");

(async () => {
  const { browser, page } = await boot({ viewport: (process.env.VIEWPORT ? { width: +process.env.VIEWPORT.split("x")[0], height: +process.env.VIEWPORT.split("x")[1] } : { width: 1440, height: 900 }) });
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(1200);

  await page.evaluate(async () => {
    const h = { "X-Auth-Token": localStorage.getItem("token") || "" };
    const e = await fetch("/entries", {
      method: "POST", headers: { ...h, "Content-Type": "application/json" },
      body: JSON.stringify({ content: "A note that carries a lecture handout." }),
    });
    const entry = await e.json();
    const fd = new FormData();
    fd.append("file", new File(["# Agents\n\n" + "Extracted text. ".repeat(60)],
      "cab432_lecture_agents.md", { type: "text/markdown" }));
    await fetch(`/entries/${entry.id}/files`, { method: "POST", body: fd, headers: h });
  });
  await page.waitForTimeout(800);
  await page.click('[data-media-kind="files"], [data-subtab="files"], #library-subtab-files').catch(() => {});
  await page.waitForTimeout(2500);

  const r = await page.evaluate(() => {
    const tile = document.querySelector(".library-file-rows .library-image-tile");
    if (!tile) return { error: "no file row", rows: document.querySelectorAll(".library-image-tile").length };
    const R = (el) => { const b = el.getBoundingClientRect(); return { l: Math.round(b.left), t: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) }; };
    const row = R(tile);
    // Every laid-out descendant, so "empty space" is a number rather than a look.
    let inkBottom = row.t, inkRight = row.l;
    const kids = [];
    for (const el of tile.querySelectorAll("*")) {
      const b = el.getBoundingClientRect();
      if (b.width === 0 || b.height === 0) continue;
      inkBottom = Math.max(inkBottom, b.bottom);
      inkRight = Math.max(inkRight, b.right);
      if (el.parentElement === tile) kids.push({ tag: el.tagName.toLowerCase(), cls: el.className.toString().slice(0, 44), ...R(el) });
    }
    const controls = [...tile.querySelectorAll("button, input, a, [role=button]")]
      .filter((el) => el.getBoundingClientRect().width > 0)
      .map((el) => `${el.tagName.toLowerCase()}.${el.className.toString().split(" ")[0]}: ${(el.textContent || el.title || el.getAttribute("aria-label") || "").trim().slice(0, 40)}`);
    const hidden = [...tile.querySelectorAll("button, a")]
      .filter((el) => el.getBoundingClientRect().width === 0)
      .map((el) => `${el.className.toString().slice(0, 40)}`);
    return {
      row, kids, controls, hidden,
      textColumnLefts: [...tile.children].map((c) => Math.round(c.getBoundingClientRect().left)),
      unusedHeightPx: Math.round(row.t + row.h - inkBottom),
      unusedWidthPx: Math.round(row.l + row.w - inkRight),
      rowCount: document.querySelectorAll(".library-file-rows .library-image-tile").length,
      facts: [...(tile.querySelector(".library-file-facts")?.children || [])].map((c) => ({ cls: c.className.toString().slice(0, 30), ...R(c), disp: getComputedStyle(c).display, w2: getComputedStyle(c).width })),
    };
  });
  console.log(JSON.stringify(r, null, 2));
  await browser.close();
})();
