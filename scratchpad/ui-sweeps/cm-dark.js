// The engine follows the app's theme, measured rather than reasoned.
//
// The theme object is rebuilt from `<html data-mode>` through a
// MutationObserver, which is the one part of this that no lint can see: if the
// observer never fires, every colour in the editor stays light while the rest
// of the app goes dark, and nothing logs a thing.
//
//   THEME=dark BASE=http://127.0.0.1:8786 node scratchpad/ui-sweeps/cm-dark.js
const { boot } = require("./lib.js");

let failures = 0;
function ok(name, condition, detail) {
  if (!condition) failures += 1;
  console.log(`${condition ? "PASS" : "FAIL"}  ${name}${detail === undefined ? "" : `  — ${detail}`}`);
}

const luminance = (rgb) => {
  const [r, g, b] = (rgb.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(Number);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

(async () => {
  const { browser, page } = await boot();
  const errors = [];
  page.on("pageerror", (e) => errors.push("PAGEERROR " + e.message));

  await page.evaluate(async () => {
    const r = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ title: "Theme sweep", content: "# Heading\n\nSome **bold** text.\n" }),
    });
    const doc = await r.json();
    switchTab("documents");
    await openDocument(doc.id);
  });
  await page.waitForTimeout(2500);
  await page.evaluate(() => setDocView("live"));
  await page.waitForTimeout(600);

  const read = () =>
    page.evaluate(() => {
      const content = document.querySelector("#doc-editor .cm-content");
      const body = getComputedStyle(document.body);
      return {
        mode: document.documentElement.dataset.mode,
        ink: getComputedStyle(content).color,
        appInk: body.color,
        // CodeMirror carries "am I dark?" in a facet, not in a class: its
        // own class names are generated (`ͼ1 ͼ3 ͼ4`), so asserting on a
        // `cm-dark` class would pass or fail for reasons unrelated to the
        // theme. Measured the first time this sweep was written: the facet
        // said true while no such class existed.
        editorDark: docCmView.state.facet(CM6.view.EditorView.darkTheme),
      };
    });

  const first = await read();
  ok("the editor's ink is the app's ink", first.ink === first.appInk, JSON.stringify(first));

  // Switch the theme the way the toggle does, and read it back.
  await page.evaluate(() => applyThemeChoice(document.documentElement.dataset.mode === "dark" ? "light" : "dark"));
  await page.waitForTimeout(700);
  const second = await read();
  ok("the mode changed", second.mode !== first.mode, `${first.mode} -> ${second.mode}`);
  ok("the editor followed it", second.ink === second.appInk, JSON.stringify(second));
  ok(
    "and the ink actually inverted",
    Math.abs(luminance(second.ink) - luminance(first.ink)) > 80,
    `${first.ink} -> ${second.ink}`
  );
  ok(
    "the engine's own dark flag followed too",
    second.editorDark === (second.mode === "dark") && first.editorDark === (first.mode === "dark"),
    JSON.stringify({ before: first.editorDark, after: second.editorDark, mode: second.mode })
  );

  ok("no page errors", errors.length === 0, errors.join(" | "));
  console.log(failures === 0 ? "ALL PASS" : `${failures} FAILED`);
  await browser.close();
})();
