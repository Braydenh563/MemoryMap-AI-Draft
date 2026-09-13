// Every element carrying the `medium` border fingerprint: a computed border
// width of exactly 3px on something that was never designed to have one.
//
// The cause is in 00-tokens-shell.css's own comment: `border: none` sets the
// *style* to none and leaves the *width* at its initial `medium`, and the
// Appearance rule forces `border-style` back with `!important`, at which point
// `medium` (3px, in whatever colour `border-color` inherits) reappears on an
// element every stylesheet involved believes has no border. Fixed once for the
// palette and the file pickers; this is the sweep that says whether it is back.
//
// 3px is the fingerprint because nothing in this design system chooses 3px:
// the scale is 1px hairlines and 2px focus rings.
const { boot } = require("./lib.js");
(async () => {
  const { browser, page } = await boot();
  const tabs = [null, "notes", "library", "chat", "graph", "timeline", "reminders", "whiteboard"];
  const found = new Map();
  const collect = async (label) => {
    const rows = await page.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll("body *")) {
        if (!(el instanceof HTMLElement)) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) continue;
        if (el.checkVisibility && !el.checkVisibility()) continue;
        const cs = getComputedStyle(el);
        const widths = ["borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth"].map((k) => parseFloat(cs[k]));
        if (!widths.some((w) => w === 3)) continue;
        if (cs.borderTopStyle === "none") continue;
        out.push(`${el.tagName.toLowerCase()}#${el.id}${[...el.classList].slice(0, 3).map((c) => "." + c).join("")} ${cs.borderTopColor}`);
      }
      return out;
    });
    for (const row of rows) found.set(row, (found.get(row) || "") + " " + label);
  };
  for (const t of tabs) {
    if (t) { await page.click(`[data-tab="${t}"]`).catch(() => {}); await page.waitForTimeout(800); }
    await collect(t || "dashboard");
  }
  // The sub-tabs of Notes and Library, where most of the app's inputs live.
  for (const sub of ["capture", "write", "ask"]) {
    await page.click('[data-tab="notes"]').catch(() => {});
    await page.waitForTimeout(400);
    await page.click(`#notes-subtabs [data-target*="${sub}"]`).catch(() => {});
    await page.waitForTimeout(700);
    await collect("notes/" + sub);
  }
  await page.click("#settings-btn").catch(() => {});
  await page.waitForTimeout(900);
  await collect("settings");
  const rows = [...found.entries()];
  console.log(rows.length ? rows.map(([k, v]) => `${k} [${v.trim()}]`).join("\n") : "clean: no 3px borders");
  console.log(`TOTAL ${rows.length}`);
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
