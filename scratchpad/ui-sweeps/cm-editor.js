// editor.js's four surfaces, on the engine (DOCUMENTS_PLAN Phase 2).
//
// The "/" menu, the `[[` picker, the selection toolbar and the inline AI bar
// were all written against a `<textarea>` and now receive a surface instead.
// None of that is visible to a Python lint and none of it was observed by the
// three sweeps beside this one, so this is the check that says the refactor
// works rather than that it compiles.
//
//   BASE=http://127.0.0.1:8786 node scratchpad/ui-sweeps/cm-editor.js
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

  await page.evaluate(async () => {
    const r = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ title: "Editor layer", content: "The quick brown fox.\n" }),
    });
    const doc = await r.json();
    switchTab("documents");
    await openDocument(doc.id);
  });
  await page.waitForTimeout(2500);
  await page.evaluate(() => setDocView("source"));
  await page.waitForTimeout(500);

  const text = () => page.evaluate(() => docSurface().text);

  // --- the surface reports itself as a document ---------------------------
  ok("the engine is a document surface", await page.evaluate(() => {
    const el = document.querySelector("#doc-editor .cm-content");
    return editorSurfaceKind(el) === "document";
  }));

  // --- the selection toolbar ------------------------------------------------
  await page.click("#doc-editor .cm-content");
  await page.evaluate(() => docSurface().setSelection(4, 9)); // "quick"
  await page.waitForTimeout(500);
  ok("the selection bar appears over a selection in the engine",
    await page.evaluate(() => {
      const bar = document.getElementById("selection-bar");
      return Boolean(bar) && !bar.classList.contains("hidden");
    }));
  const barBox = await page.evaluate(() => {
    const bar = document.getElementById("selection-bar");
    const caret = docSurface().coordsAt(docSurface().selection().from);
    const r = bar.getBoundingClientRect();
    return { barTop: Math.round(r.top), caretTop: Math.round(caret.top), w: Math.round(r.width) };
  });
  ok("it is anchored near the selection, not at the top of the pane",
    Math.abs(barBox.barTop - barBox.caretTop) < 120, JSON.stringify(barBox));

  await page.evaluate(() => {
    document
      .querySelector('#selection-bar button[data-md="bold"]')
      .dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  });
  await page.waitForTimeout(400);
  ok("Bold from the selection bar wraps the selection", (await text()).includes("**quick**"),
    JSON.stringify(await text()));

  // One undo, because the wrap is one transaction on the engine's history.
  await page.evaluate(() => {
    document.querySelector("#doc-editor .cm-content").focus();
    CM6.commands.undo(docCmView);
  });
  await page.waitForTimeout(300);
  ok("one undo takes it back", !(await text()).includes("**quick**"), JSON.stringify(await text()));

  // --- the "/" menu ----------------------------------------------------------
  await page.click("#doc-editor .cm-content");
  await page.keyboard.press("Control+End");
  await page.keyboard.type("\n/divid");
  await page.waitForTimeout(600);
  ok("the / menu opens in the engine", await page.evaluate(() => {
    const menu = document.getElementById("editor-menu");
    return Boolean(menu) && !menu.classList.contains("hidden");
  }));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(500);
  ok("choosing a command inserts and drops the token",
    (await text()).includes("---") && !(await text()).includes("/divid"),
    JSON.stringify(await text()));

  // --- the [[ picker ---------------------------------------------------------
  // `[[` alone, then the query: the picker fetches the documents list on the
  // first `[[` and redraws when it lands, so typing the whole token in one
  // burst asks it to match against a cache that does not exist yet.
  await page.keyboard.type("\n[[");
  await page.waitForTimeout(900);
  await page.keyboard.type("Editor");
  await page.waitForTimeout(600);
  ok("the [[ picker opens in the engine", await page.evaluate(() => {
    const menu = document.getElementById("editor-menu");
    return Boolean(menu) && !menu.classList.contains("hidden");
  }));
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  // --- ask about the selection ----------------------------------------------
  await page.evaluate(() => docSurface().setSelection(4, 9));
  await page.waitForTimeout(400);
  const context = await page.evaluate(() => {
    const where = selectionContextFrom(docSurface());
    return { id: where.surfaceId, kind: where.kind, text: where.text, line: where.line };
  });
  ok("a selection reports itself as this document, in document coordinates",
    context.id === "doc-content" && context.kind === "document" && context.text === "quick" && context.line === 1,
    JSON.stringify(context));

  // --- the inline AI bar opens (the model itself is not called) --------------
  ok("inline AI knows it can run here",
    await page.evaluate(() => inlineAiAvailable(docSurface())));
  await page.evaluate(() => inlineAiOpen(docSurface()));
  await page.waitForTimeout(500);
  const inline = await page.evaluate(() => {
    const bar = document.getElementById("inline-ai");
    const scope = document.getElementById("inline-ai-scope");
    return { open: Boolean(bar) && !bar.classList.contains("hidden"), scope: scope.textContent };
  });
  ok("the inline AI bar opens and describes the selection",
    inline.open && /Rewrites the word/.test(inline.scope), JSON.stringify(inline));
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  // --- the completion popup --------------------------------------------------
  await page.click("#doc-editor .cm-content");
  await page.keyboard.press("Control+End");
  await page.keyboard.type("\nqui");
  await page.waitForTimeout(700);
  ok("the word completion popup opens", await page.evaluate(() => {
    const list = document.getElementById("doc-complete-list");
    return Boolean(list) && !list.classList.contains("hidden");
  }));
  await page.keyboard.press("Tab");
  await page.waitForTimeout(400);
  ok("Tab completes the word", /\bquick\b/.test((await text()).split("\n").pop() || ""),
    JSON.stringify((await text()).split("\n").pop()));

  ok("no console errors", errors.length === 0, errors.join(" | "));
  console.log(failures === 0 ? "ALL PASS" : `${failures} FAILED`);
  await browser.close();
})();
