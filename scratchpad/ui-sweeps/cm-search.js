// DOCUMENTS_PLAN Phase 2 step 4: find and replace, and folding on headings.
//
//   BASE=http://127.0.0.1:8786 node scratchpad/ui-sweeps/cm-search.js
const { boot } = require("./lib.js");

const BODY = [
  "# One",
  "",
  "alpha beta alpha",
  "",
  "## One point one",
  "",
  "more text here",
  "",
  "# Two",
  "",
  "the end",
].join("\n");

let failures = 0;
function ok(name, condition, detail) {
  if (!condition) failures += 1;
  console.log(`${condition ? "PASS" : "FAIL"}  ${name}${detail === undefined ? "" : `  — ${detail}`}`);
}

(async () => {
  const { browser, page } = await boot();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 200)));
  page.on("pageerror", (e) => errors.push("PAGEERROR " + e.message));

  await page.evaluate(async (body) => {
    const r = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ title: "Search sweep", content: body }),
    });
    const doc = await r.json();
    switchTab("documents");
    await openDocument(doc.id);
  }, BODY);
  await page.waitForTimeout(2500);
  await page.evaluate(() => setDocView("source"));
  await page.waitForTimeout(400);

  // Ctrl+F opens the engine's panel, not the old bar.
  await page.click("#doc-editor .cm-content");
  await page.keyboard.press("Control+f");
  await page.waitForTimeout(500);
  ok("Ctrl+F opens the engine's search panel", (await page.$("#doc-editor .cm-search")) !== null);
  ok("the old find bar stays down", await page.evaluate(() =>
    document.getElementById("doc-find-bar").classList.contains("hidden")));

  // Restyled onto the app's own field recipe: measured, not looked at.
  const field = await page.evaluate(() => {
    const input = document.querySelector("#doc-editor .cm-search .cm-textfield");
    if (!input) return null;
    const own = getComputedStyle(input);
    const app = getComputedStyle(document.getElementById("doc-find-input"));
    return {
      radius: own.borderTopLeftRadius,
      appRadius: app.borderTopLeftRadius,
      family: own.fontFamily === app.fontFamily,
      colour: own.color === app.color,
    };
  });
  ok("the search field wears the app's field recipe", field && field.family && field.colour,
    JSON.stringify(field));

  // Replace all goes through the editor, so one undo puts it back.
  // Typed rather than assigned: the panel commits its query from real input
  // events, and a scripted `.value =` is exactly the shape that looks like it
  // worked and changes nothing.
  await page.click("#doc-editor .cm-search input[name=search]");
  await page.keyboard.type("alpha");
  await page.click("#doc-editor .cm-search input[name=replace]");
  await page.keyboard.type("OMEGA");
  await page.click("#doc-editor .cm-search button[name=replaceAll]");
  await page.waitForTimeout(500);
  const replaced = await page.evaluate(async () => {
    const after = docSurface().text;
    document.querySelector("#doc-editor .cm-content").focus();
    CM6.commands.undo(docCmView);
    await new Promise((r) => setTimeout(r, 300));
    return {
      after: (after.match(/OMEGA/g) || []).length,
      undone: docSurface().text.includes("alpha beta alpha"),
    };
  });
  ok("Replace all replaces, and one undo puts it back", replaced.after === 2 && replaced.undone,
    JSON.stringify(replaced));

  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  // Folding follows the line-number preference and folds a heading's section.
  await page.evaluate(() => setDocGutter(true));
  await page.waitForTimeout(500);
  ok("the fold column appears with the numbers",
    (await page.$("#doc-editor .cm-foldGutter")) !== null);
  const folded = await page.evaluate(async () => {
    const before = document.querySelectorAll("#doc-editor .cm-line").length;
    const arrow = document.querySelector("#doc-editor .cm-foldGutter .cm-gutterElement span[title=\"Fold line\"]");
    if (!arrow) return "no fold arrow";
    arrow.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 300));
    return { before, after: document.querySelectorAll("#doc-editor .cm-line").length };
  });
  ok("a heading folds its section", folded.after < folded.before, JSON.stringify(folded));

  await page.evaluate(() => setDocGutter(false));
  await page.waitForTimeout(400);
  ok("turning the numbers off takes the fold column with them",
    (await page.$("#doc-editor .cm-foldGutter")) === null);

  ok("no console errors", errors.length === 0, errors.join(" | "));
  console.log(failures === 0 ? "ALL PASS" : `${failures} FAILED`);
  await browser.close();
})();
