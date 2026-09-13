// The conditions the first anchor probe could not reach: a finding far enough
// down the document that pressing its panel row has to scroll to it, a
// multi-word finding that spans a soft wrap, and a flagged word inside a
// markdown construct the live view rewrites.
const { boot } = require("./lib.js");

const FILL = "The quick brown fox jumped over the lazy dog and then went home again. ";
const CONTENT = [
  "Draft notes",
  "",
  "A short line with teh first typo in it.",
  "",
  `A wrapped line: ${FILL}${FILL}and here we have the the doubled pair near a wrap point ${FILL}`,
  "",
  "**A bold word that is wrnog here.**",
  "",
  "[A link with occured in it](https://example.com/page)",
  "",
  "# A heading with recieve in it",
  "",
  "| a | b |",
  "| --- | --- |",
  "| seperate | fine |",
  "",
  ...Array.from({ length: 60 }, (_, i) => `Filler paragraph ${i + 1}. ${FILL}`),
  "",
  "The very last line ends with definately",
].join("\n");

(async () => {
  const { page, browser } = await boot({});
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });
  await page.click('[data-tab="library"]').catch(() => {});
  await page.waitForTimeout(900);
  console.log("seeded: " + await page.evaluate(async (content) => {
    const r = await fetch("/documents", {
      method: "POST",
      headers: { "X-Auth-Token": localStorage.getItem("token") || "", "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Anchor probe 2", content }),
    });
    const doc = await r.json();
    switchTab("documents");
    await new Promise((res) => setTimeout(res, 400));
    await openDocument(doc.id);
    await new Promise((res) => setTimeout(res, 2500));
    return JSON.stringify({ id: doc.id, findings: docProseFound.map((f) => `${f.rule}:${(f.text || "").trim().slice(0, 18)}`) });
  }, CONTENT));

  const geom = async (label) => {
    const out = await page.evaluate(() => {
      const menu = document.getElementById("doc-suggest-menu");
      const open = menu && !menu.classList.contains("hidden");
      const m = open ? menu.getBoundingClientRect() : null;
      const mark = document.querySelector(".cm-finding[data-doc-finding]");
      const sel = document.querySelector(".cm-selectionBackground");
      const s = sel ? sel.getBoundingClientRect() : null;
      const ed = document.querySelector(".cm-editor")?.getBoundingClientRect();
      return {
        menu: m ? { left: Math.round(m.left), top: Math.round(m.top), right: Math.round(m.right), bottom: Math.round(m.bottom) } : "closed",
        selection: s ? { left: Math.round(s.left), top: Math.round(s.top), bottom: Math.round(s.bottom) } : null,
        editor: ed ? { left: Math.round(ed.left), top: Math.round(ed.top), right: Math.round(ed.right), bottom: Math.round(ed.bottom) } : null,
        win: { w: window.innerWidth, h: window.innerHeight },
        inView: m ? (m.left >= 0 && m.top >= 0 && m.right <= window.innerWidth + 1 && m.bottom <= window.innerHeight + 1) : null,
      };
    });
    let flag = "";
    if (out.menu !== "closed") {
      if (!out.inView) flag += "  <<< OUT OF BOUNDS";
      if (out.selection) {
        const dx = out.menu.left - out.selection.left;
        const dy = out.menu.top - out.selection.bottom;
        out.dx = dx; out.dy = dy;
        if (Math.abs(dx) > 24 || dy < -400 || dy > 40) flag += `  <<< ANCHOR OFF dx=${dx} dy=${dy}`;
      }
    } else flag += "  <<< did not open";
    console.log(`${label}: ${JSON.stringify(out)}${flag}`);
    return flag ? 1 : 0;
  };

  let bad = 0;
  // Case A: press the panel row of the LAST finding while the editor sits at
  // the top, so the jump has to scroll a long way to reach it.
  bad += await (async () => {
    await page.evaluate(() => {
      document.getElementById("doc-suggest-menu")?.classList.add("hidden");
      const s = document.querySelector(".cm-scroller"); if (s) s.scrollTop = 0;
      const chip = document.querySelector("[aria-controls='doc-prose-panel']");
      if (chip && chip.getAttribute("aria-expanded") !== "true") chip.click();
    });
    await page.waitForTimeout(700);
    const which = await page.evaluate(async () => {
      const rows = [...document.querySelectorAll("#doc-prose-panel .doc-prose-jump")];
      const row = rows.find((r) => /definately/i.test(r.textContent)) || rows[rows.length - 1];
      if (!row) return "no row";
      const label = row.textContent.slice(0, 60);
      row.click();
      await new Promise((r) => setTimeout(r, 900));
      return label;
    });
    return geom(`panel row for the last finding (${which})`);
  })();

  // Case B: same row again, now that the editor is already there.
  bad += await (async () => {
    await page.evaluate(async () => {
      document.getElementById("doc-suggest-menu")?.classList.add("hidden");
      const rows = [...document.querySelectorAll("#doc-prose-panel .doc-prose-jump")];
      const row = rows.find((r) => /definately/i.test(r.textContent)) || rows[rows.length - 1];
      row?.click();
      await new Promise((r) => setTimeout(r, 900));
    });
    await page.waitForTimeout(300);
    return geom("the same row pressed a second time");
  })();

  // Case C..: click each shape's mark where it sits.
  const clickMark = async (label, re) => {
    await page.evaluate(() => {
      closeDocSuggest();
      // A live selection makes the plain-click route bail out (it reads as a
      // drag), and the panel jump above left one on the word it jumped to.
      const box = docSurface();
      if (box) box.setSelection(0, 0);
    });
    const res = await page.evaluate(async (src) => {
      const rx = new RegExp(src, "i");
      const s = document.querySelector(".cm-scroller"); if (s) s.scrollTop = 0;
      await new Promise((r) => setTimeout(r, 400));
      const el = [...document.querySelectorAll("[data-doc-finding]")].find((n) => rx.test(n.textContent || ""));
      if (!el) return { skip: "no mark", have: [...document.querySelectorAll("[data-doc-finding]")].map((n) => n.textContent) };
      const r = el.getBoundingClientRect();
      const boxes = [...el.getClientRects()].map((b) => `${Math.round(b.left)}..${Math.round(b.right)}@${Math.round(b.top)}`);
      el.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: r.left + 2, clientY: r.top + r.height / 2 }));
      await new Promise((res) => setTimeout(res, 700));
      return { rect: { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom) }, fragments: boxes };
    }, re);
    if (res.skip) { console.log(`${label}: ${JSON.stringify(res)}`); return 0; }
    console.log(`${label}: mark ${JSON.stringify(res.rect)} fragments=${res.fragments.join(" ")}`);
    return geom(`  ${label} menu`);
  };

  bad += await clickMark("the the (doubled pair near a wrap)", "the the");
  bad += await clickMark("wrnog inside bold", "wrnog");
  bad += await clickMark("occured inside a link", "occured");
  bad += await clickMark("recieve in a heading", "recieve");
  bad += await clickMark("seperate in a table cell", "seperate");

  console.log("console errors: " + (errs.length ? errs.join(" | ") : "0"));
  console.log(bad ? `FAIL: ${bad} case(s) off` : "all cases flush");
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
