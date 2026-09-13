// Probe: Tab/Shift+Tab in the documents editor. Diagnostic for the 2026-09-12
// documents polish: list items indent as blocks, the caret survives, and the
// Escape-then-Tab hatch still leaves the editor.
const { boot } = require("./lib.js");
let bad = 0;
const ok = (n, c, d) => { if (!c) bad += 1; console.log(`${c ? "PASS" : "FAIL"}  ${n}${d === undefined ? "" : "  — " + d}`); };
(async () => {
  const { browser, page } = await boot();
  page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
  await page.evaluate(async () => {
    const r = await api("/documents", { method: "POST",
      body: JSON.stringify({ title: "Tab probe", content: "- alpha\nplain line\n" }) });
    const doc = await r.json();
    switchTab("documents");
    await openDocument(doc.id);
  });
  await page.waitForTimeout(2500);
  await page.evaluate(() => setDocView("source"));
  await page.waitForTimeout(500);
  await page.click("#doc-editor .cm-content");
  const state = () => page.evaluate(() => ({ text: docSurface().text, sel: docSurface().selection() }));

  await page.evaluate(() => docSurface().setSelection(4, 4)); // "- al|pha"
  await page.keyboard.press("Tab");
  await page.waitForTimeout(250);
  let s = await state();
  ok("Tab indents the list item as a block", s.text.startsWith("  - alpha"), JSON.stringify(s.text.slice(0, 12)));
  ok("the caret follows the text it was in", s.sel.from === 6 && s.sel.to === 6, `${s.sel.from}-${s.sel.to}`);

  await page.keyboard.press("Shift+Tab");
  await page.waitForTimeout(250);
  s = await state();
  ok("Shift+Tab outdents it again", s.text.startsWith("- alpha"), JSON.stringify(s.text.slice(0, 12)));
  ok("and leaves a caret, not a selected line", s.sel.from === s.sel.to && s.sel.from === 4, `${s.sel.from}-${s.sel.to}`);
  ok("focus stays in the editor", await page.evaluate(() => document.activeElement.classList.contains("cm-content")));

  // a plain prose line still takes a caret indent
  await page.evaluate(() => docSurface().setSelection(13, 13)); // inside "plain line"
  await page.keyboard.press("Tab");
  await page.waitForTimeout(250);
  s = await state();
  ok("a plain line still indents at the caret", s.text.includes("plain   line"), JSON.stringify(s.text));

  // the escape hatch
  await page.keyboard.press("Escape");
  await page.keyboard.press("Tab");
  await page.waitForTimeout(300);
  ok("Escape then Tab still leaves the editor",
    !(await page.evaluate(() => document.activeElement.classList.contains("cm-content"))),
    await page.evaluate(() => document.activeElement.id || document.activeElement.className));
  console.log(bad ? `${bad} FAILURES` : "all clear");
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
