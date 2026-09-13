// A measured look at the documents surface: control affordance, the empty
// states, and the panel chrome. Diagnostic for the 2026-09-12 polish pass.
const { boot } = require("./lib.js");
(async () => {
  const { browser, page } = await boot();
  page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
  await page.evaluate(() => switchTab("documents"));
  await page.waitForTimeout(1500);
  console.log("--- with no documents at all ---");
  console.log(await page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll("#tab-documents *")) {
      if (!el.checkVisibility || !el.checkVisibility()) continue;
      if (el.children.length) continue;
      const t = (el.textContent || "").trim();
      if (t) out.push(`${el.tagName.toLowerCase()}.${el.className || "-"}: ${t.slice(0, 80)}`);
    }
    return out.slice(0, 30).join("\n");
  }));

  await page.evaluate(async () => {
    const r = await api("/documents", { method: "POST",
      body: JSON.stringify({ title: "Polish", content: "# Heading\n\nSome prose with a tets in it.\n" }) });
    const doc = await r.json();
    await openDocument(doc.id);
  });
  await page.waitForTimeout(2500);

  console.log("--- the flat controls, with where they live ---");
  console.log(await page.evaluate(() => {
    const transparent = (v) => /rgba\(0, 0, 0, 0\)|transparent/.test(v) || /, 0\)$/.test(v);
    const out = [];
    for (const b of document.querySelectorAll("#tab-documents button, #tab-documents summary, #tab-documents select")) {
      if (!b.checkVisibility || !b.checkVisibility()) continue;
      const r = b.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) continue;
      const c = getComputedStyle(b);
      if (!(transparent(c.backgroundColor) && (transparent(c.borderTopColor) || c.borderTopWidth === "0px") && c.boxShadow === "none")) continue;
      const chain = [];
      let p = b.parentElement;
      for (let i = 0; i < 3 && p; i += 1) { chain.push(`${p.tagName.toLowerCase()}#${p.id || ""}.${p.className || ""}`); p = p.parentElement; }
      out.push(`${b.tagName.toLowerCase()}#${b.id || "-"}.${b.className || "-"} "${(b.textContent || "").trim().slice(0, 20)}" ${Math.round(r.width)}x${Math.round(r.height)}  in  ${chain.join(" < ")}`);
    }
    return out.join("\n");
  }));

  console.log("--- the prose panel, opened ---");
  console.log(await page.evaluate(() => {
    document.getElementById("doc-prose").click();
    const p = document.getElementById("doc-prose-panel");
    const r = p.getBoundingClientRect();
    const c = getComputedStyle(p);
    return JSON.stringify({ w: Math.round(r.width), h: Math.round(r.height), bg: c.backgroundColor,
      border: c.border, radius: c.borderRadius, pad: c.padding, text: p.textContent.slice(0, 200) });
  }));

  await page.waitForTimeout(400);
  console.log("--- the suggest menu ---");
  console.log(await page.evaluate(() => {
    const finding = docProseFound.find((f) => f.rule === "spelling");
    if (!finding) return "no spelling finding";
    const rect = docSurface().coordsAt(finding.start);
    openDocSuggest(finding, { left: rect.left, top: rect.top, bottom: rect.bottom, right: rect.left + 20, width: 20, height: 16 });
    const m = document.getElementById("doc-suggest-menu");
    const r = m.getBoundingClientRect();
    const rows = [...m.querySelectorAll("button")].map((b) => {
      const br = b.getBoundingClientRect();
      const bc = getComputedStyle(b);
      return `${(b.textContent || "").trim().slice(0, 28)} | ${Math.round(br.width)}x${Math.round(br.height)} | bg ${bc.backgroundColor} | pad ${bc.padding}`;
    });
    return JSON.stringify({ box: `${Math.round(r.width)}x${Math.round(r.height)} at ${Math.round(r.left)},${Math.round(r.top)}`,
      offscreen: r.right > innerWidth || r.bottom > innerHeight || r.left < 0 || r.top < 0, rows }, null, 1);
  }));
  await page.screenshot({ path: (process.env.SCRATCH || "/tmp") + "/docs-polish.png" });
  await browser.close();
})();
