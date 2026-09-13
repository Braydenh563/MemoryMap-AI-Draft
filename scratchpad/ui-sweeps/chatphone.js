// The chat surface on a phone, measured.
//
// Reported: "there needs to be more responsive design, especially for the chat
// page and main chat panel. the bottom chat dock is horrendous and takes up
// half the screen on mobile", with a screenshot of the composer as four
// stacked rows filling roughly the bottom third, and the chat head's title
// overlapping the model name.
const { boot } = require("./lib.js");
const W = Number(process.env.VW || 390);
const H = Number(process.env.VH || 844);
(async () => {
  const { page, browser } = await boot({ viewport: { width: W, height: H } });
  await page.click('[data-tab="chat"]').catch(() => {});
  await page.waitForTimeout(2500);
  console.log(await page.evaluate((vh) => {
    const box = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), left: Math.round(r.left) };
    };
    const composer = document.querySelector(".chat-dock");
    // How many visual rows the composer's own children occupy.
    let rows = 0;
    if (composer) {
      const tops = new Set();
      for (const child of composer.querySelectorAll("*")) {
        const r = child.getBoundingClientRect();
        if (r.height > 6 && r.width > 6 && child.checkVisibility?.()) tops.add(Math.round(r.top / 8));
      }
      rows = tops.size;
    }
    const cr = composer ? composer.getBoundingClientRect() : null;
    // The chat head: does the title overlap the model name?
    const title = document.querySelector("#chat-title, .chat-head-title, .conversation-title");
    const model = document.querySelector("#chat-model-name, .chat-head-model, .chat-model");
    let overlap = null;
    if (title && model) {
      const a = title.getBoundingClientRect(), b = model.getBoundingClientRect();
      overlap = Math.round(Math.min(a.right, b.right) - Math.max(a.left, b.left));
    }
    return JSON.stringify({
      viewport: `${window.innerWidth}x${window.innerHeight}`,
      composer: cr ? { h: Math.round(cr.height), pctOfScreen: Math.round((cr.height / vh) * 100), rows } : "none",
      messages: box("#chat-messages"),
      head: box(".chat-head, #chat-head, .chat-title-row"),
      titleModelOverlapPx: overlap,
      sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    }, null, 1);
  }, H));
  await browser.close();
})().catch((e) => { console.log("ERR " + e.message); process.exit(1); });
