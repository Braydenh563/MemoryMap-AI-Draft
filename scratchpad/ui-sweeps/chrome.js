// Chrome vs content, by the MODERNISATION_AUDIT B1 definition: how much of
// the viewport's height is spent before the first piece of real content.
//
//   chrome% = (first content item's top y) / viewport height
//
// B1 measured 76% on Notes at 390 and called it "the single largest gap
// between what the app is and what it claims to be". This sweep runs the same
// measurement across five tabs so a responsive phase has a number to move,
// and prints the chrome stack (which strip is how tall) so the number says
// *what* to fix rather than only that something is wrong.
//
//   BASE=http://127.0.0.1:8802 WIDTHS=390,1024 node chrome.js
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8781';
const WIDTHS = (process.env.WIDTHS || '390').split(',').map(Number);

// Per tab: the click target, and the first thing on the page that is content
// rather than furniture. Ordered as the tab bar orders them.
const TABS = [
  // Two readings for the Dashboard, because the strict one is unfair to it
  // and the fair one is easy to hide behind. `dashboard` is the first
  // configurable widget, the page's own content; `dash-actions` is the first
  // thing you can press, which is what the greeting banner sits above.
  { tab: 'dashboard', content: '#dash-grid > *' },
  { tab: 'dashboard', label: 'dash-actions', content: '.dash-quicklinks .quick-link' },
  { tab: 'notes', content: '#entry-list > li' },
  { tab: 'chat', content: '#chat-messages > *, #chat-messages' },
  { tab: 'library', content: '#library-grid > *, #library-grid' },
  // The whiteboard is a surface, not a tab: reached through Library > Boards
  // and then into a board, where the thing that has to be big is the canvas.
  { tab: 'library', board: true, label: 'whiteboard', content: '#whiteboard-container' },
];

(async () => {
  const browser = await chromium.launch();
  for (const width of WIDTHS) {
    const height = width < 600 ? 844 : 900;
    const ctx = await browser.newContext({
      viewport: { width, height }, deviceScaleFactor: 1,
      hasTouch: width < 820, isMobile: width < 600,
    });
    await ctx.addInitScript(() => { try { localStorage.setItem('theme', 'light'); } catch (e) {} });
    const page = await ctx.newPage();
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
    await page.fill('#lock-password', PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
    if (await page.$('#lock-password') && await page.isVisible('#lock-password')) {
      await page.fill('#lock-password', PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
    }
    await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
    await page.waitForTimeout(700);

    console.log(`== ${width}x${height}`);
    for (const t of TABS) {
      await page.click(`[data-tab="${t.tab}"]`).catch(() => {});
      await page.waitForTimeout(700);
      if (t.board) {
        await page.click('#library-subtabs button[data-target="library-view-whiteboard"]', { timeout: 3000 }).catch(() => {});
        await page.waitForTimeout(900);
        // Open the first board if there is one, else make one, so the canvas
        // is on screen rather than the boards landing.
        const opened = await page.click('#library-boards-grid .library-card, #library-boards-grid > *', { timeout: 2500 }).then(() => true).catch(() => false);
        if (!opened) await page.click('[data-empty-action="new-board"]', { timeout: 2500 }).catch(() => {});
        await page.waitForTimeout(1800);
      }
      const r = await page.evaluate((sel) => {
        const vh = window.innerHeight;
        const vis = (e) => e && e.checkVisibility && e.checkVisibility();
        const first = [...document.querySelectorAll(sel)].filter(vis)[0];
        const top = first ? Math.round(first.getBoundingClientRect().top) : null;
        // The chrome stack: every visible strip whose box sits above that
        // first content item, named so the number points somewhere.
        const strips = [];
        const named = [
          ['#top-bar', 'header#top-bar'], ['#tab-bar', '#tab-bar'],
          ['#status-bar', '#status-bar'],
          ['dock', '.tab-page:not(.hidden) .dock'],
          ['subtabs', '.tab-page:not(.hidden) .notes-subtabs, .tab-page:not(.hidden) .library-subtabs'],
          ['sidebar', '.tab-page:not(.hidden) > .layout > aside'],
          ['chips', '.tab-page:not(.hidden) #category-strip, .tab-page:not(.hidden) .library-filters'],
          ['toolbar', '.tab-page:not(.hidden) .library-toolbar, .tab-page:not(.hidden) .doc-toolbar'],
          ['wb-topbar', '#wb-topbar'],
          ['wb-tools', '.whiteboard-floating-panel.bottom-center'],
        ];
        for (const [name, s] of named) {
          const e = [...document.querySelectorAll(s)].filter(vis)[0];
          if (e) {
            const b = e.getBoundingClientRect();
            if (b.height > 0) strips.push(`${name} ${Math.round(b.height)}`);
          }
        }
        // How many whole content items fit above the fold.
        const items = [...document.querySelectorAll(sel)].filter(vis);
        const whole = items.filter((e) => e.getBoundingClientRect().bottom <= vh).length;
        // The whiteboard's content is one big canvas, so "first content y" is
        // the wrong question there: what matters is how much of it is left
        // once the two floating strips have taken their share.
        const canvas = document.getElementById('whiteboard-container');
        let free = null;
        if (canvas && vis(canvas)) {
          const cb = canvas.getBoundingClientRect();
          const h = (s) => { const e = document.querySelector(s); return e && vis(e) ? e.getBoundingClientRect().height : 0; };
          free = Math.round(Math.min(cb.bottom, vh) - Math.max(cb.top, 0) - h('#wb-topbar') - h('.whiteboard-floating-panel.bottom-center'));
        }
        return { top, vh, strips, whole, n: items.length, free };
      }, t.content);
      const pct = r.top === null ? 'n/a' : Math.round((r.top / r.vh) * 100) + '%';
      const name = t.label || t.tab;
      console.log(`  ${name.padEnd(10)} first content y=${String(r.top).padStart(4)}  chrome ${pct.padStart(4)}  whole items above fold ${r.whole}/${r.n}`);
      console.log(`             stack: ${r.strips.join(' | ')}`);
      if (t.board && r.free !== null) {
        console.log(`             free canvas ${r.free}px of ${r.vh} -> chrome ${Math.round((1 - r.free / r.vh) * 100)}%`);
      }
    }
    await ctx.close();
  }
  await browser.close();
})();
