// Does the tab strip fit in the header, band by band?
//
// UI_MODERNISATION_PLAN Phase 9's iPad-portrait band (600 to 820) is the one
// width range where the seven tabs neither fit in the header nor move to the
// bottom: `agent-remaining/responsive.md` item 3 measured 574px of room
// against 608px of tabs at 600, so the strip scrolled sideways and the header
// took a second row for it.
//
// Three numbers per width, because the fault has three different shapes and a
// screenshot tells them apart badly:
//
//   scrollWidth vs clientWidth   the strip scrolls, so a tab is out of reach
//   header rows (offsetHeight)   the strip took a row of its own
//   per-button width and label   a caption is clipped inside its own button
//
//   BASE=http://127.0.0.1:8790 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     WIDTHS=600,720,819,1024 node scratchpad/ui-sweeps/tabfit.js
//
// Exits non-zero if any width scrolls or clips, so it can gate a commit. A
// strip on its own row is reported but is not a failure: below 1100 it cannot
// fit beside the wordmark and wrapping is the design.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8781';
const WIDTHS = (process.env.WIDTHS || '600,720,819,1024,1440').split(',').map(Number);

(async () => {
  const browser = await chromium.launch();
  let bad = 0;
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({
      viewport: { width, height: 900 },
      deviceScaleFactor: 1,
      hasTouch: width < 820,
    });
    await ctx.addInitScript((t) => {
      try {
        localStorage.setItem('theme', t);
        localStorage.setItem('onboardingDone', '1');
      } catch (e) { /* a private window has no storage; the app copes */ }
    }, process.env.THEME || 'light');
    const page = await ctx.newPage();
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
    await page.fill('#lock-password', PW);
    await page.click('#lock-submit');
    await page.waitForTimeout(2500);
    if (await page.$('#lock-password') && await page.isVisible('#lock-password')) {
      await page.fill('#lock-password', PW);
      await page.click('#lock-submit');
      await page.waitForTimeout(2500);
    }
    await page.evaluate(() => {
      const o = document.getElementById('onboarding-overlay');
      if (o) o.classList.add('hidden');
    });
    await page.waitForTimeout(700);
    const r = await page.evaluate(() => {
      const bar = document.getElementById('tab-bar');
      const head = document.getElementById('top-bar');
      if (!bar || !head) return null;
      const btns = [...bar.querySelectorAll('button[data-tab]')];
      // Two clipping questions, because a caption can overflow its button
      // (visible overflow, so the button's own scrollWidth is what grows) or
      // be cut inside it (hidden overflow, so the span's is).
      const clipped = btns.filter((b) => {
        const label = b.querySelector('.tab-label') || b;
        return label.scrollWidth > label.clientWidth + 1
          || b.scrollWidth > b.clientWidth + 1;
      }).map((b) => b.dataset.tab);
      // What the strip needs on one row, and what the header has beside the
      // wordmark and the controls: the pair `syncTabOverflowFade` compares.
      const hs = getComputedStyle(head);
      const hgap = parseFloat(hs.columnGap || hs.gap) || 0;
      let others = 0;
      let siblings = 0;
      for (const child of head.children) {
        if (child === bar || child.classList.contains('hidden')) continue;
        others += child.getBoundingClientRect().width;
        siblings += 1;
      }
      const bs = getComputedStyle(bar);
      const bgap = parseFloat(bs.columnGap || bs.gap) || 0;
      const natural = btns.reduce((t, b) => t + b.getBoundingClientRect().width, 0)
        + (parseFloat(bs.paddingLeft) || 0) + (parseFloat(bs.paddingRight) || 0)
        + bgap * Math.max(0, btns.length - 1);
      return {
        natural: Math.round(natural),
        rowSpace: Math.round(
          head.clientWidth - (parseFloat(hs.paddingLeft) || 0)
          - (parseFloat(hs.paddingRight) || 0) - others - hgap * siblings,
        ),
        scrolls: bar.scrollWidth > bar.clientWidth + 1,
        need: bar.scrollWidth,
        room: bar.clientWidth,
        wrapped: head.classList.contains('tabs-wrapped'),
        headerH: Math.round(head.getBoundingClientRect().height),
        buttons: btns.map((b) => Math.round(b.getBoundingClientRect().width)),
        clipped,
        bottom: getComputedStyle(bar).position === 'fixed',
      };
    });
    if (!r) {
      console.log(`== ${width}px: no tab bar`);
      bad += 1;
    } else {
      // Wrapping is a designed state, not a fault: below 1100 the strip
      // cannot fit beside the wordmark and takes a row of its own on
      // purpose. What fails is a tab out of reach (the row scrolls) or a
      // caption cut off inside its button.
      const verdict = r.bottom ? 'bottom bar' : (r.scrolls || r.clipped.length ? 'FAIL' : 'ok');
      if (verdict === 'FAIL') bad += 1;
      console.log(
        `== ${width}px: ${verdict}  need ${r.need} in ${r.room}, one row needs ` +
        `${r.natural} in ${r.rowSpace}, header ${r.headerH}px` +
        `${r.wrapped ? ', tabs on their own row' : ''}` +
        `${r.clipped.length ? ', clipped: ' + r.clipped.join(',') : ''}\n` +
        `   buttons ${r.buttons.join(' ')}`,
      );
    }
    await ctx.close();
  }
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
