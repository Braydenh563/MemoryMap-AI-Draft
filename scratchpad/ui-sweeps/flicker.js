// "They flicker into the top corner for a second then appear in the right
// place" (the owner, INBOX 111, never investigated until now).
//
// The shape being hunted: a popover is made visible first and positioned
// afterwards, so the browser paints one frame of it wherever its CSS left it
// (usually 0,0 or the far edge) before the JS moves it. It is one or two
// frames, so a screenshot almost never catches it and a person always does.
//
// How this sees it: a MutationObserver installed before any page script runs
// watches every attribute change in the document. When an element goes from
// not-rendered to rendered, its rect is sampled on the next animation frame
// and again four frames later. A popover that was positioned before it was
// shown does not move between those two samples; one that was not, jumps.
//
//   BASE=http://127.0.0.1:8781 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node flicker.js
//
// A finding is a name, the first rect and the settled rect. Anything under
// MOVED px is ignored: a menu that nudges itself 4px off an edge is doing its
// job, and one that arrives 300px away was drawn in the wrong place.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const BASE = process.env.BASE || 'http://127.0.0.1:8781';
const PW = 'testpassword123';
const MOVED = 24;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript(() => {
    window.__jumps = [];
    const name = (e) =>
      e.tagName.toLowerCase() +
      (e.id ? '#' + e.id : '') +
      (e.className && typeof e.className === 'string'
        ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.')
        : '');
    const rendered = (e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && e.isConnected && getComputedStyle(e).visibility !== 'hidden';
    };
    const watched = new WeakMap();
    const sample = (el) => {
      const first = el.getBoundingClientRect();
      let frames = 0;
      const step = () => {
        frames += 1;
        if (frames < 4) return requestAnimationFrame(step);
        const settled = el.getBoundingClientRect();
        const dx = Math.abs(settled.left - first.left);
        const dy = Math.abs(settled.top - first.top);
        if (dx > 24 || dy > 24) {
          window.__jumps.push({
            el: name(el),
            from: [Math.round(first.left), Math.round(first.top)],
            to: [Math.round(settled.left), Math.round(settled.top)],
            moved: [Math.round(dx), Math.round(dy)],
          });
        }
      };
      requestAnimationFrame(step);
    };
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        const el = record.target;
        if (!(el instanceof HTMLElement)) continue;
        const was = watched.get(el) || false;
        let is = false;
        try { is = rendered(el); } catch (e) { is = false; }
        watched.set(el, is);
        // Only the transition into view, and only for the kind of element
        // this is about: something that floats over the page.
        if (is && !was) {
          const position = getComputedStyle(el).position;
          if (position === 'absolute' || position === 'fixed') sample(el);
        }
      }
    });
    observer.observe(document.documentElement, {
      attributes: true,
      subtree: true,
      attributeFilter: ['class', 'style', 'hidden', 'open', 'aria-expanded', 'data-open'],
    });
  });

  const page = await ctx.newPage();
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
  await page.fill('#lock-password', PW);
  await page.click('#lock-submit');
  await sleep(3500);
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
  await sleep(1200);

  // Everything that floats: the dock menus and kebabs on every tab, the
  // header's own popovers, a tooltip, and the status bar's clock panel.
  const openers = [
    ['notes', '.dock [aria-haspopup], .dock summary, .dock .kebab-btn'],
    ['chat', '.chat-dock [aria-haspopup], .chat-dock summary'],
    ['graph', '.dock [aria-haspopup], .dock summary'],
    ['library', '.dock [aria-haspopup], .dock summary'],
    ['timeline', '.dock [aria-haspopup], .dock summary'],
    ['reminders', '.dock [aria-haspopup], .dock summary'],
    ['dashboard', '#tab-dashboard [aria-haspopup], #tab-dashboard summary'],
  ];

  let opened = 0;
  for (const [tab, selector] of openers) {
    await page.click(`[data-tab="${tab}"]`).catch(() => {});
    await page.waitForTimeout(600);
    const handles = await page.$$(selector);
    for (const handle of handles.slice(0, 8)) {
      await handle.click({ timeout: 1500 }).catch(() => {});
      opened += 1;
      await page.waitForTimeout(320);
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(180);
    }
  }

  // The header's own three, and the clock panel, which are the ones the report
  // named ("dropdown menus and tooltips").
  for (const id of ['#notif-btn', '#theme-btn', '#space-switcher-btn', '#status-clock']) {
    const el = await page.$(id);
    if (!el) continue;
    await el.click({ timeout: 1500 }).catch(() => {});
    opened += 1;
    await page.waitForTimeout(350);
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(180);
  }

  // A tooltip, which is hover rather than click.
  const tip = await page.$('[data-help-for], [title]');
  if (tip) { await tip.hover().catch(() => {}); await page.waitForTimeout(900); }

  const jumps = await page.evaluate(() => window.__jumps);
  console.log(`opened ${opened} floating surfaces`);
  const seen = new Map();
  for (const jump of jumps) {
    const key = `${jump.el} ${jump.from} ${jump.to}`;
    if (!seen.has(key)) seen.set(key, jump);
  }
  for (const jump of seen.values()) {
    console.log(`    ${jump.el}: painted at ${jump.from}, settled at ${jump.to} (moved ${jump.moved})`);
  }
  const findings = seen.size;
  console.log(findings ? `FAIL: ${findings} surfaces painted before they were placed` : 'PASS: 0 findings');
  await browser.close();
  process.exit(findings ? 1 : 0);
})();
