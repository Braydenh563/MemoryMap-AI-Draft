// The *other* editing surfaces, which the documents work changed underneath.
//
// `applyMarkdown`, `wrapDocSelection`, `editorSplice` and the "/" menu are
// shared with the note capture box and the note edit form, and all four now
// receive a surface instead of a textarea. Nothing in the documents sweeps
// touches them, and a Python lint cannot see any of it: this is the check
// that the refactor did not quietly break the two editors it was not about.
//
//   BASE=http://127.0.0.1:8786 node scratchpad/ui-sweeps/cm-notes.js
const { boot } = require("./lib.js");

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

  await page.evaluate(() => {
    switchTab("notes");
    showNotesSection("capture");
  });
  await page.waitForTimeout(1200);

  const value = () => page.evaluate(() => document.getElementById("entry-content").value);

  ok("the capture box is an editor surface", await page.evaluate(() =>
    editorSurfaceKind(document.getElementById("entry-content")) === "note"));

  // The toolbar, through the shared MD_ACTIONS table.
  await page.click("#entry-content");
  await page.keyboard.type("hello world");
  await page.evaluate(() => {
    const box = document.getElementById("entry-content");
    box.setSelectionRange(6, 11);
  });
  await page.waitForTimeout(300);
  await page.evaluate(() => applyMarkdown("bold", "entry-content"));
  await page.waitForTimeout(300);
  ok("Bold from the shared table wraps the note's selection",
    (await value()) === "hello **world**", JSON.stringify(await value()));

  // Ctrl+I, through wireMdFormatShortcuts, which resolves its box by id.
  await page.evaluate(() => {
    const box = document.getElementById("entry-content");
    box.focus();
    box.setSelectionRange(0, 5);
  });
  await page.keyboard.press("Control+i");
  await page.waitForTimeout(300);
  ok("Ctrl+I in the capture box italicises", (await value()).startsWith("*hello*"),
    JSON.stringify(await value()));

  // The "/" menu, which now receives a surface from the delegated listener.
  await page.evaluate(() => {
    const box = document.getElementById("entry-content");
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  });
  await page.keyboard.type("\n/quo");
  await page.waitForTimeout(700);
  ok("the / menu opens in the capture box", await page.evaluate(() => {
    const menu = document.getElementById("editor-menu");
    return Boolean(menu) && !menu.classList.contains("hidden");
  }));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);
  ok("choosing a command inserts into the note",
    (await value()).includes(">") && !(await value()).includes("/quo"),
    JSON.stringify(await value()));

  // The selection bar reaches the note too, and formats it.
  await page.evaluate(() => {
    const box = document.getElementById("entry-content");
    box.focus();
    box.setSelectionRange(1, 6);
  });
  await page.waitForTimeout(500);
  ok("the selection bar appears over a note selection", await page.evaluate(() => {
    const bar = document.getElementById("selection-bar");
    return Boolean(bar) && !bar.classList.contains("hidden");
  }));
  ok("and inline AI is correctly refused there", await page.evaluate(() => {
    const magic = document.querySelector("#selection-bar [data-inline-ai]");
    return Boolean(magic) && magic.hidden;
  }));

  ok("no console errors", errors.length === 0, errors.join(" | "));
  console.log(failures === 0 ? "ALL PASS" : `${failures} FAILED`);
  await browser.close();
})();
