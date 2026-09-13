// The documents editor's spelling check, against the vendored word list.
//   BASE=http://127.0.0.1:8798 node scratchpad/ui-sweeps/docs-spell.js
const { boot } = require("./lib.js");
let bad = 0;
const ok = (n, c, d) => { if (!c) bad += 1; console.log(`${c ? "PASS" : "FAIL"}  ${n}${d === undefined ? "" : "  — " + d}`); };
const BODY = [
  "This is a tets of the checker.",
  "",
  "A word it knows: environment. A word it does not: xyzzyqq.",
  "",
  "```",
  "def teh_function(recieve): return recieve  # tets",
  "```",
  "",
  "An address: https://exampple.com/teh/path and `inline teh code`.",
  "",
  "Identifiers like MemoryMap, HTTP and app.js are not typos.",
  "",
].join("\n");
(async () => {
  const { browser, page } = await boot();
  page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
  await page.evaluate(async (body) => {
    const r = await api("/documents", { method: "POST",
      body: JSON.stringify({ title: "Spelling", content: body }) });
    const doc = await r.json();
    switchTab("documents");
    await openDocument(doc.id);
  }, BODY);
  await page.waitForTimeout(3500);
  await page.evaluate(() => renderDocProse());
  await page.waitForTimeout(500);

  ok("the word list loaded", await page.evaluate(() => docWordlistReady()),
    await page.evaluate(() => (docWordlist ? docWordlist.size : "not loaded")));
  const found = await page.evaluate(() =>
    docProseFound.filter((f) => f.rule === "spelling").map((f) => [f.text, f.message, f.replacement]));
  console.log("   spelling findings:", JSON.stringify(found));
  const words = found.map((f) => f[0]);
  ok("a plain typo is flagged", words.includes("tets"));
  ok("a nonsense word is flagged", words.includes("xyzzyqq"));
  ok("the code fence is not read", !words.includes("teh_function") && found.filter((f) => f[0] === "recieve").length === 0);
  ok("the tets inside the fence is not counted twice", words.filter((w) => w === "tets").length === 1);
  ok("a url is not read", !words.includes("exampple"));
  ok("inline code is not read", words.filter((w) => w === "teh").length === 0);
  ok("an identifier is not flagged", !words.includes("MemoryMap") && !words.includes("HTTP") && !words.includes("app"));
  ok("a known word is not flagged", !words.includes("environment"));

  const guesses = await page.evaluate(() => docSpellGuesses("tets"));
  console.log("   guesses for tets:", JSON.stringify(guesses));
  ok("the dictionary suggests test for tets", guesses.includes("test"));
  const g2 = await page.evaluate(() => docSpellGuesses("enviroment"));
  console.log("   guesses for enviroment:", JSON.stringify(g2));
  ok("and environment for enviroment", g2.includes("environment"));

  // the browser's own squiggle is off now that the app has a dictionary
  ok("the browser's spellcheck is off", await page.evaluate(() =>
    document.querySelector("#doc-editor .cm-content").getAttribute("spellcheck") === "false"),
    await page.evaluate(() => document.querySelector("#doc-editor .cm-content").getAttribute("spellcheck")));

  // clicking the app's own underline opens the menu
  const opened = await page.evaluate(() => {
    const finding = docProseFound.find((f) => f.text === "tets");
    if (!finding) return "no finding";
    const rect = docSurface().coordsAt(finding.start);
    openDocSuggest(finding, { left: rect.left, top: rect.top, bottom: rect.bottom, right: rect.left + 20, width: 20, height: 16 });
    const menu = document.getElementById("doc-suggest-menu");
    return menu.classList.contains("hidden") ? "hidden" : menu.textContent.slice(0, 160);
  });
  console.log("   menu:", JSON.stringify(opened));
  ok("the menu opens on a flagged word with suggestions", typeof opened === "string" && opened !== "hidden" && opened !== "no finding" && /test/.test(opened));

  // timing
  const ms = await page.evaluate(() => {
    const text = docText();
    const t0 = performance.now();
    for (let i = 0; i < 10; i += 1) docProseFindings(text);
    return (performance.now() - t0) / 10;
  });
  console.log(`   docProseFindings: ${ms.toFixed(2)}ms per pass over ${BODY.length} chars`);
  ok("a pass stays under 20ms", ms < 20, `${ms.toFixed(2)}ms`);

  console.log(bad ? `${bad} FAILURES` : "all clear");
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
