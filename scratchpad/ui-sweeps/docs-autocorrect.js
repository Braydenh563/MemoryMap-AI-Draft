// Autocorrect in the documents editor: what it fixes and what it refuses.
//   BASE=http://127.0.0.1:8798 node scratchpad/ui-sweeps/docs-autocorrect.js
const { boot } = require("./lib.js");
let bad = 0;
const ok = (n, c, d) => { if (!c) bad += 1; console.log(`${c ? "PASS" : "FAIL"}  ${n}${d === undefined ? "" : "  — " + d}`); };
(async () => {
  const { browser, page } = await boot();
  page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
  await page.evaluate(async () => {
    const r = await api("/documents", { method: "POST",
      body: JSON.stringify({ title: "Autocorrect", content: "" }) });
    const doc = await r.json();
    switchTab("documents");
    await openDocument(doc.id);
  });
  await page.waitForTimeout(3000);
  ok("autocorrect is still off by default",
    await page.evaluate(() => document.getElementById("doc-autocorrect").checked === false));
  await page.evaluate(() => {
    const box = document.getElementById("doc-autocorrect");
    box.checked = true;
    box.dispatchEvent(new Event("change", { bubbles: true }));
    setDocView("source");
  });
  await page.waitForTimeout(600);
  ok("the word list is loaded", await page.evaluate(() => docWordlistReady()));

  const type = async (text) => {
    await page.evaluate(() => { docSurface().replaceRange(0, docSurface().text.length, ""); });
    await page.click("#doc-editor .cm-content");
    await page.keyboard.type(text, { delay: 12 });
    await page.waitForTimeout(300);
    return page.evaluate(() => docSurface().text);
  };

  ok("a table typo is still fixed", (await type("teh ")).startsWith("the "), await page.evaluate(() => docSurface().text));
  const swapped = await type("I ran a tets ");
  ok("a unique transposition is fixed", swapped.includes("test "), JSON.stringify(swapped));
  const missed = await type("the enviroment ");
  ok("a unique dropped letter is fixed", missed.includes("environment "), JSON.stringify(missed));
  const correct = await type("the environment is fine ");
  ok("a correct word is never rewritten", correct === "the environment is fine ", JSON.stringify(correct));
  const ambiguous = await type("the tho ");
  ok("an ambiguous short word is left alone", ambiguous === "the tho ", JSON.stringify(ambiguous));
  const name = await type("Hi Brayden ");
  ok("an unknown name is left alone", name === "Hi Brayden ", JSON.stringify(name));
  const acronym = await type("the HTTPX ");
  ok("an acronym is left alone", acronym === "the HTTPX ", JSON.stringify(acronym));
  const ident = await type("call docSurfase ");
  ok("an identifier is left alone", ident === "call docSurfase ", JSON.stringify(ident));

  // Ctrl+Z after a correction gives back what was typed, which is what the
  // toast promises.
  await type("I ran a tets ");
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(300);
  const undone = await page.evaluate(() => docSurface().text);
  ok("undo gives back the typed word", undone.includes("tets"), JSON.stringify(undone));

  console.log(bad ? `${bad} FAILURES` : "all clear");
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
