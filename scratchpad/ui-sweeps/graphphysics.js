// graph.md section 1: saved views never stored the physics state.
// graphCaptureView() read `.checked` off `#graph-physics`, which is the
// Physics *section* div, not a checkbox -- always undefined, so every saved
// view stored `physics: true` regardless of the sliders, and restoring one
// wrote `true` onto a div's `.value` and changed nothing. The fix captures
// the two sliders that "physics" actually means to a reader (Gravity,
// Spread) and restores those.
//
// This probe: set the sliders away from their 50/50 default, save a view,
// move them again (simulating time passing / another view being tried),
// restore the saved view, and read the sliders -- and localStorage, since
// that's what renderGraph() itself reads out of on every rebuild -- back.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot();
await page.click('[data-tab="graph"]');await page.waitForTimeout(700);

const setSliders = (g, s) => page.evaluate(({g, s}) => {
  const set = (id, value) => {
    const el = document.getElementById(id);
    el.value = value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  };
  set("graph-gravity", g);
  set("graph-spread", s);
}, {g, s});

await setSliders(20, 80);
const before = await page.evaluate(() => ({
  gravity: document.getElementById("graph-gravity").value,
  spread: document.getElementById("graph-spread").value,
  ls: { gravity: localStorage.getItem("graph-gravity"), spread: localStorage.getItem("graph-spread") },
}));
console.log("sliders set to 20/80:", JSON.stringify(before));

await page.click('#graph-more-menu summary');await page.waitForTimeout(300);
await page.click('#graph-view-save');await page.waitForTimeout(300);
await page.fill('.confirm-overlay input[type="text"]', 'Physics test view');
await page.keyboard.press('Enter');await page.waitForTimeout(500);

// Capture the actual stored view object, so a failure shows exactly what
// got written rather than only what got read back.
const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("graph-saved-views") || "[]").find(v => v.name === "Physics test view"));
console.log("stored view:", JSON.stringify(stored));

// Move the sliders away from the saved values, as if time passed.
await setSliders(65, 10);

// Reopen the More menu (a fresh render may have replaced it) and restore.
await page.click('#graph-more-menu summary');await page.waitForTimeout(300);
await page.selectOption('#graph-view-picker', 'Physics test view');await page.waitForTimeout(500);

const after = await page.evaluate(() => ({
  gravity: document.getElementById("graph-gravity").value,
  spread: document.getElementById("graph-spread").value,
  ls: { gravity: localStorage.getItem("graph-gravity"), spread: localStorage.getItem("graph-spread") },
}));
console.log("after restoring the saved view:", JSON.stringify(after));

const ok = after.gravity === "20" && after.spread === "80" && after.ls.gravity === "20" && after.ls.spread === "80";
console.log(ok ? "PASS: the saved view restored gravity/spread" : "FAIL: gravity/spread did not restore");
await browser.close();
process.exit(ok ? 0 : 1);
})();
