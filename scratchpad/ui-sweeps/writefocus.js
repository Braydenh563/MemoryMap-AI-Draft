// Does clicking into the Write with AI box change the layout, or only the
// focus?
//
// Reported: "when I clcik on the text box in the 'write with ai' subtab, the
// structure goes all funky", with before/after pairs showing Undo, the hint and
// Draft it on one row, then stacked on three.
const { boot } = require("./lib.js");
(async () => {
  const { page, browser } = await boot({ viewport: { width: Number(process.env.VW || 1440), height: 900 } });
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 120)); });
  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll("#notes-subtabs button, [data-target]")]
      .find((x) => /write/i.test(x.textContent || ""));
    b?.click();
  });
  await page.waitForTimeout(1500);

  const shot = () => page.evaluate(() => {
    const rows = {};
    for (const sel of [".draft-compose-row", ".draft-column-foot", ".draft-actions", ".draft-tags-row"]) {
      const row = document.querySelector(sel);
      if (!row) continue;
      const kids = [...row.children].filter((c) => c.getBoundingClientRect().height > 4);
      rows[sel] = {
        h: Math.round(row.getBoundingClientRect().height),
        //: Counted by the *bands* the children fall into, not by distinct
        //: `offsetTop` values: a label and the input beside it sit a pixel
        //: apart on the same visual line, which a raw set of tops reports as
        //: two rows and is how the first version of this probe reported a
        //: perfectly ordinary row as broken.
        lines: new Set(kids.map((c) => Math.round(c.getBoundingClientRect().top / 12))).size,
        wrap: getComputedStyle(row).flexWrap,
        dir: getComputedStyle(row).flexDirection,
        kids: kids.map((c) => `${c.tagName.toLowerCase()}#${c.id || ""}`),
      };
    }
    const ta = document.getElementById("draft-thoughts");
    return { rows, textarea: ta ? { id: ta.id, h: Math.round(ta.getBoundingClientRect().height) } : null };
  });

  // The appearance settings, not the width: the same rem-against-px pressure
  // that made the quick sketch bar wrap (see sketchbar.js). Large text moves
  // the root to 18px and Spacious multiplies every spacing token by 1.35,
  // while a column capped in pixels does not grow to match.
  const SETTINGS = [
    { name: "default", fontsize: null, density: null },
    { name: "large-text", fontsize: "large", density: null },
    { name: "spacious", fontsize: null, density: "spacious" },
    { name: "large+spacious", fontsize: "large", density: "spacious" },
  ];
  for (const s of SETTINGS) {
    await page.evaluate((set) => {
      const root = document.documentElement;
      if (set.fontsize) root.setAttribute("data-fontsize", set.fontsize);
      else root.removeAttribute("data-fontsize");
      if (set.density) root.setAttribute("data-density", set.density);
      else root.removeAttribute("data-density");
    }, s);
    await page.waitForTimeout(400);
    const r = await shot();
    const c = r.rows[".draft-compose-row"] || {};
    const g = r.rows[".draft-tags-row"] || {};
    console.log(`  ${s.name.padEnd(15)} compose lines=${c.lines} h=${c.h}   tags lines=${g.lines} h=${g.h}`);
  }
  await page.evaluate(() => {
    document.documentElement.removeAttribute("data-fontsize");
    document.documentElement.removeAttribute("data-density");
  });
  await page.waitForTimeout(300);
  console.log("before: " + JSON.stringify(await shot(), null, 1));
  await page.click("#draft-thoughts");
  await page.waitForTimeout(800);
  console.log("after:  " + JSON.stringify(await shot(), null, 1));
  console.log("errors: " + (errs.length ? errs.join(" | ") : "0"));
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
