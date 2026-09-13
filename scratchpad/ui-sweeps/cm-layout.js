// Where the engine sits in the pane: the reading measure, full width, Split
// and Read. The three sweeps beside this one measure what the editor *does*;
// this one measures where it is, which is the half a decoration cannot fix.
//
//   BASE=http://127.0.0.1:8786 node scratchpad/ui-sweeps/cm-layout.js
const { boot } = require("./lib.js");

let failures = 0;
function ok(name, condition, detail) {
  if (!condition) failures += 1;
  console.log(`${condition ? "PASS" : "FAIL"}  ${name}${detail === undefined ? "" : `  — ${detail}`}`);
}

(async () => {
  const { browser, page } = await boot();
  const errors = [];
  page.on("pageerror", (e) => errors.push("PAGEERROR " + e.message));

  await page.evaluate(async () => {
    const words = [];
    for (let i = 0; i < 400; i += 1) words.push("word" + i);
    const r = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ title: "Layout", content: "# Layout\n\n" + words.join(" ") }),
    });
    const doc = await r.json();
    switchTab("documents");
    await openDocument(doc.id);
  });
  await page.waitForTimeout(2500);

  const box = (selector) =>
    page.evaluate((s) => {
      const el = document.querySelector(s);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) };
    }, selector);

  const view = async (mode) => {
    await page.evaluate((m) => setDocView(m), mode);
    await page.waitForTimeout(600);
  };

  await view("live");
  const pane = await box("#doc-panes");
  const content = await box("#doc-editor .cm-editor");
  ok("the editor fills the pane's height", content.h > pane.h * 0.6,
    JSON.stringify({ pane: pane.h, content: content.h }));
  ok("the reading measure caps the column", content.w < pane.w - 40,
    JSON.stringify({ pane: pane.w, content: content.w }));
  const centred = Math.abs((content.x - pane.x) - (pane.x + pane.w - (content.x + content.w)));
  ok("and centres it", centred < 4, `off by ${centred}px`);

  // Full width releases the cap; the toggle is the same control the rest of
  // the editor already uses.
  await page.evaluate(() => setDocWidth(true));
  await page.waitForTimeout(400);
  const wide = await box("#doc-editor .cm-editor");
  ok("full width releases the cap", wide.w > content.w + 40,
    JSON.stringify({ measure: content.w, wide: wide.w }));
  await page.evaluate(() => setDocWidth(false));
  await page.waitForTimeout(400);

  // Split: the editor and the preview side by side, both real.
  await view("split");
  const left = await box("#doc-source-wrap");
  const right = await box("#doc-preview");
  ok("Split puts the editor and the preview side by side",
    left && right && right.x >= left.x + left.w - 4 && left.w > 100 && right.w > 100,
    JSON.stringify({ left, right }));
  ok("the engine is still the left half", (await box("#doc-editor .cm-editor")).w > 100);

  // Read hides the editor entirely and gives the preview the pane.
  await view("rendered");
  ok("Read hides the editor", await page.evaluate(() =>
    document.getElementById("doc-source-wrap").classList.contains("hidden")));
  const reading = await box("#doc-preview");
  ok("and the preview has the pane", reading.w > 200, JSON.stringify(reading));

  // Back to Live: the engine has to be re-measured after being hidden, or
  // every line is positioned against a zero-height box.
  await view("live");
  const again = await box("#doc-editor .cm-editor");
  ok("coming back from Read re-measures the engine",
    again.h > pane.h * 0.6 && again.w === content.w, JSON.stringify({ before: content, after: again }));

  ok("no page errors", errors.length === 0, errors.join(" | "));
  console.log(failures === 0 ? "ALL PASS" : `${failures} FAILED`);
  await browser.close();
})();
