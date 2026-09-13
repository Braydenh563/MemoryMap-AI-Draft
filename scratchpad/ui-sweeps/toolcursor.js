// Per-tool cursor truthfulness on the whiteboard and the mind map.
//
// Reported (INBOX 115): "when Im on the delete tool on the mindmap and hover
// over a mindmap text node, the cursor changes to the grabber hand". A cursor
// is a promise about what a click will do, so this measures the promise:
// `getComputedStyle(el).cursor` for the board background and for every kind of
// item on it, once per tool, on a map and on a whiteboard.
//
//   BASE=http://127.0.0.1:8857 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//   node scratchpad/ui-sweeps/toolcursor.js
const { boot } = require("./lib.js");

const TOOLS = ["select", "pan", "lasso", "draw", "highlighter", "eraser", "bucket",
               "line", "arrow", "rect", "circle", "triangle", "diamond",
               "sticky", "text", "link-straight", "link-curved", "delete"];

// A cursor that promises a drag. `url(...)` cursors keep their keyword
// fallback in the computed value, so the test is a substring one.
const DRAGGY = (c) => /\bgrab\b|\bgrabbing\b|\bmove\b/.test(c);

const OPML = `<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0"><head><title>Cursor map</title></head><body>
  <outline text="Roots"><outline text="Alpha"/><outline text="Beta"/></outline>
</body></opml>`;

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  const rows = [];

  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(900);

  // A map, made the way the app makes one.
  await page.evaluate(() => { const m = document.getElementById("library-boards-more"); if (m) m.open = true; });
  await page.waitForTimeout(250);
  await page.click("#wb-boards-import");
  await page.waitForTimeout(400);
  await page.setInputFiles("#wb-import-map-file", {
    name: "cursor.opml", mimeType: "text/x-opml", buffer: Buffer.from(OPML, "utf8"),
  });
  await page.waitForTimeout(3500);

  const measure = async (surface) => {
    for (const tool of TOOLS) {
      const r = await page.evaluate((tool) => {
        const btn = document.querySelector(`#whiteboard-view [data-tool="${tool}"], [data-tool="${tool}"]`);
        if (btn) btn.click();
        const cs = (sel) => {
          const el = document.querySelector(sel);
          return el ? getComputedStyle(el).cursor : null;
        };
        return {
          tool,
          active: document.getElementById("whiteboard-container")?.getAttribute("data-current-tool"),
          container: cs("#whiteboard-container"),
          mapNode: cs(".wb-map-node"),
          mapText: cs(".wb-map-text"),
          card: cs(".node-card"),
          object: cs(".wb-object"),
        };
      }, tool);
      r.surface = surface;
      rows.push(r);
    }
  };

  await measure("map");

  // A plain whiteboard with a card and an object on it, for the same sweep.
  await page.click("#wb-back-to-boards");
  await page.waitForTimeout(1600);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(2000);
  await measure("board");

  const short = (c) => (c || "-").replace(/url\([^)]*\)[, ]*/, "svg+");
  console.log("surface tool          active        container        mapNode          mapText          card             object");
  for (const r of rows) {
    console.log(
      `${r.surface.padEnd(7)} ${r.tool.padEnd(13)} ${(r.active || "-").padEnd(13)} ` +
      `${short(r.container).padEnd(16)} ${short(r.mapNode).padEnd(16)} ${short(r.mapText).padEnd(16)} ` +
      `${short(r.card).padEnd(16)} ${short(r.object).padEnd(16)}`
    );
  }

  const bad = rows.filter((r) =>
    !["select", "pan"].includes(r.tool) &&
    [r.mapNode, r.mapText, r.card, r.object].some((c) => c && DRAGGY(c))
  );
  console.log(`\nitems promising a drag under a tool that does not drag: ${bad.length}`);
  for (const r of bad) console.log(`  ${r.surface}/${r.tool}: node=${short(r.mapNode)} text=${short(r.mapText)} card=${short(r.card)} object=${short(r.object)}`);
  const dead = rows.filter((r) => !["select", "pan"].includes(r.tool) && r.container && DRAGGY(r.container));
  console.log(`tools whose own background cursor still says "drag": ${dead.length} (${dead.map((r) => r.surface + "/" + r.tool).join(", ") || "none"})`);

  await browser.close();
})();
