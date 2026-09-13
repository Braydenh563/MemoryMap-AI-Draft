// Where the word menu opens, across the conditions `spellanchor.js` never
// tried: a flagged word at the end of a long line, on the last line, with the
// editor scrolled, in split view, a second occurrence of the same word, a
// narrow window, and Large text + Spacious.
//
// Reported (INBOX 142, 128): "the popup edit suggestions menu screws upn the
// screen and make sit go out of bounds", "the popup didnt appear right next to
// it but off to the side with a wide gap".
const { boot } = require("./lib.js");

// One long line so a flagged word lands near the right edge of the card, one
// with the same word twice, filler so the editor really scrolls, and a flagged
// word on the very last line.
const FILL = "The quick brown fox jumped over the lazy dog and then went home again. ";
const CONTENT = [
  "Draft notes",
  "",
  "A short line with teh first typo in it.",
  `${FILL}${FILL}Then at the end of this one sits idk`,
  "",
  `Another paragraph that mentions idk twice, and again idk near the end of ${FILL}`,
  "",
  ...Array.from({ length: 40 }, (_, i) => `Filler paragraph ${i + 1}. ${FILL}`),
  "",
  "The last line of all ends with seperate",
].join("\n");

(async () => {
  const { page, browser } = await boot({});
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });
  await page.click('[data-tab="library"]').catch(() => {});
  await page.waitForTimeout(900);
  await page.click('[data-target="library-view-documents"]').catch(() => {});
  await page.waitForTimeout(1200);
  const made = await page.evaluate(async (content) => {
    const r = await fetch("/documents", {
      method: "POST",
      headers: { "X-Auth-Token": localStorage.getItem("token") || "", "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Anchor probe", content }),
    });
    const doc = await r.json();
    switchTab("documents");
    await new Promise((res) => setTimeout(res, 400));
    await openDocument(doc.id);
    await new Promise((res) => setTimeout(res, 2500));
    return { id: doc.id, findings: docProseFound.length, view: docView };
  }, CONTENT);
  console.log("seeded: " + JSON.stringify(made));

  // One case: pick a mark by a matcher, click it where it is, report the
  // geometry of both boxes. Everything is measured, nothing is looked at.
  const one = async (name, setup, pick) => {
    await page.evaluate(() => document.getElementById("doc-suggest-menu")?.classList.add("hidden"));
    if (setup) { await page.evaluate(setup); await page.waitForTimeout(700); }
    const out = await page.evaluate(async (pickSrc) => {
      /* eslint no-new-func: 0 */
      const choose = new Function("return " + pickSrc)();
      const marks = [...document.querySelectorAll("[data-doc-finding]")];
      const el = choose(marks);
      if (!el) return { skip: "no mark", marks: marks.length };
      el.scrollIntoView({ block: "center" });
      await new Promise((r) => setTimeout(r, 300));
      const before = el.getBoundingClientRect();
      el.dispatchEvent(new MouseEvent("click", {
        bubbles: true, clientX: before.left + before.width / 2, clientY: before.top + before.height / 2,
      }));
      await new Promise((r) => setTimeout(r, 600));
      const menu = document.getElementById("doc-suggest-menu");
      const open = menu && !menu.classList.contains("hidden");
      // Re-read the word's box after the menu opened: the jump may have moved it.
      const live = [...document.querySelectorAll("[data-doc-finding]")]
        .find((n) => n.dataset.docFinding === el.dataset.docFinding) || el;
      const w = live.getBoundingClientRect();
      const m = open ? menu.getBoundingClientRect() : null;
      const card = document.querySelector(".cm-editor")?.getBoundingClientRect();
      return {
        word: { text: live.textContent, left: Math.round(w.left), right: Math.round(w.right), top: Math.round(w.top), bottom: Math.round(w.bottom) },
        menu: m ? { left: Math.round(m.left), top: Math.round(m.top), right: Math.round(m.right), bottom: Math.round(m.bottom) } : "closed",
        editor: card ? { left: Math.round(card.left), right: Math.round(card.right) } : null,
        win: { w: window.innerWidth, h: window.innerHeight },
        dx: m ? Math.round(m.left - w.left) : null,
        dy: m ? Math.round(m.top - w.bottom) : null,
        inView: m ? (m.left >= 0 && m.top >= 0 && m.right <= window.innerWidth + 1 && m.bottom <= window.innerHeight + 1) : null,
      };
    }, pick.toString());
    const bad = [];
    if (out.menu && out.menu !== "closed") {
      if (!out.inView) bad.push("OUT OF BOUNDS");
      if (Math.abs(out.dx) > 24) bad.push(`dx ${out.dx}`);
      if (out.dy !== null && (out.dy < -10 || out.dy > 40) && Math.abs(out.menu.bottom - out.word.top) > 40) bad.push(`dy ${out.dy}`);
    } else if (!out.skip) bad.push("menu did not open");
    console.log(`${name}: ${JSON.stringify(out)} ${bad.length ? "  <<< " + bad.join(", ") : ""}`);
    return bad.length;
  };

  let bad = 0;
  bad += await one("mid-line (the old probe's case)", null, (m) => m.find((n) => /teh/.test(n.textContent)));
  bad += await one("end of a long line", null, (m) => m.find((n) => /idk/.test(n.textContent)));
  bad += await one("second occurrence of the same word", null,
    (m) => m.filter((n) => /idk/.test(n.textContent))[2] || m.filter((n) => /idk/.test(n.textContent))[1]);
  bad += await one("last line, editor scrolled to the end",
    () => { const s = document.querySelector(".cm-scroller"); if (s) s.scrollTop = s.scrollHeight; },
    (m) => m.find((n) => /seperate/.test(n.textContent)));
  bad += await one("split view, end of a long line",
    () => setDocView("split"),
    (m) => m.find((n) => /idk/.test(n.textContent)));
  bad += await one("source view, end of a long line",
    () => setDocView("source"),
    (m) => m.find((n) => /idk/.test(n.textContent)));
  bad += await one("live view again", () => setDocView("live"), (m) => m.find((n) => /idk/.test(n.textContent)));

  await page.setViewportSize({ width: 1100, height: 760 });
  await page.waitForTimeout(700);
  bad += await one("1100x760, end of a long line", null, (m) => m.find((n) => /idk/.test(n.textContent)));
  await page.setViewportSize({ width: 820, height: 700 });
  await page.waitForTimeout(700);
  bad += await one("820x700, end of a long line", null, (m) => m.find((n) => /idk/.test(n.textContent)));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(700);
  bad += await one("large text + spacious", () => {
    document.documentElement.setAttribute("data-fontsize", "large");
    document.documentElement.setAttribute("data-density", "spacious");
  }, (m) => m.find((n) => /idk/.test(n.textContent)));
  bad += await one("large text + spacious, last line",
    () => { const s = document.querySelector(".cm-scroller"); if (s) s.scrollTop = s.scrollHeight; },
    (m) => m.find((n) => /seperate/.test(n.textContent)));
  await page.evaluate(() => {
    document.documentElement.removeAttribute("data-fontsize");
    document.documentElement.removeAttribute("data-density");
  });
  // The panel's row route, which the owner also reported.
  bad += await one("row in the suggestions panel", () => {
    document.querySelector("[aria-controls='doc-prose-panel']")?.click();
  }, () => null);
  const rowCase = await page.evaluate(async () => {
    const row = document.querySelector("#doc-prose-panel .doc-prose-list button");
    if (!row) return "no row";
    row.click();
    await new Promise((r) => setTimeout(r, 800));
    const menu = document.getElementById("doc-suggest-menu");
    if (!menu || menu.classList.contains("hidden")) return "menu did not open";
    const m = menu.getBoundingClientRect();
    const sel = document.querySelector(".cm-selectionBackground")?.getBoundingClientRect();
    return JSON.stringify({
      menu: { left: Math.round(m.left), top: Math.round(m.top), right: Math.round(m.right), bottom: Math.round(m.bottom) },
      selection: sel ? { left: Math.round(sel.left), top: Math.round(sel.top), bottom: Math.round(sel.bottom) } : null,
      inView: m.left >= 0 && m.top >= 0 && m.right <= window.innerWidth + 1 && m.bottom <= window.innerHeight + 1,
    });
  });
  console.log("panel row -> " + rowCase);
  console.log("console errors: " + (errs.length ? errs.join(" | ") : "0"));
  console.log(bad ? `FAIL: ${bad} case(s) off` : "all cases flush");
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
