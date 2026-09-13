// The keyboard-only pass per band that Phase 8's acceptance asked for and
// Phase 9 never ran (`agent-remaining/responsive.md` section 7). Three
// questions, each about something the responsive work introduced:
//
//   1. The sidebar sheet (below 820). Does focus enter it when it opens, and
//      does it return to the toggle on Escape? Escape is wired; focus return
//      was only ever wired for the Escape path, so this asks both halves.
//   2. The folded arrange zone. Below 1100 `foldDockArrange` moves the sort
//      select into the dock's own overflow menu, which is a closed
//      `<details>`. A control inside one is not tabbable, by design, so the
//      question is whether the *summary* is, and whether opening it reveals
//      the select: two stops instead of one is fine, unreachable is not.
//   3. The tab strip's roving tabindex. Only the selected tab is in the tab
//      order and the arrows move between them; that has to survive the strip
//      becoming icons (820 to 1100) and taking a row of its own.
//
//   BASE=http://127.0.0.1:8795 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     WIDTHS=1440,1024,800 node scratchpad/ui-sweeps/keysbands.js
//
// Prints one block per width and exits non-zero on a finding.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8795';
const WIDTHS = (process.env.WIDTHS || '1440,1024,800').split(',').map(Number);

const describe = (e) => (e ? `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}${e.className && typeof e.className === 'string' ? '.' + e.className.split(/\s+/).slice(0, 2).join('.') : ''}` : 'nothing');

(async () => {
  const browser = await chromium.launch();
  let bad = 0;
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({
      viewport: { width, height: 900 },
      deviceScaleFactor: 1,
      hasTouch: width < 820,
    });
    await ctx.addInitScript(() => {
      try {
        localStorage.setItem('theme', 'light');
        localStorage.setItem('onboardingDone', '1');
      } catch (e) { /* no storage in a private window */ }
    });
    const page = await ctx.newPage();
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
    await page.fill('#lock-password', PW);
    await page.click('#lock-submit');
    await page.waitForTimeout(2500);
    await page.evaluate(() => {
      const o = document.getElementById('onboarding-overlay');
      if (o) o.classList.add('hidden');
    });
    await page.waitForTimeout(700);
    console.log(`== ${width}px`);

    // --- 3. the tab strip -------------------------------------------------
    await page.click('[data-tab="notes"]').catch(() => {});
    await page.waitForTimeout(600);
    const strip = await page.evaluate(() => {
      const bar = document.getElementById('tab-bar');
      const buttons = [...bar.querySelectorAll('button[data-tab]')];
      return {
        inTabOrder: buttons.filter((b) => b.getAttribute('tabindex') !== '-1').length,
        active: buttons.filter((b) => b.classList.contains('active')).map((b) => b.dataset.tab),
      };
    });
    await page.focus('#tab-bar button.active');
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(400);
    const afterArrow = await page.evaluate(() => {
      const el = document.activeElement;
      return { focused: el ? el.dataset.tab || el.id || el.tagName : 'none', inBar: Boolean(el && el.closest('#tab-bar')) };
    });
    const stripOk = strip.inTabOrder === 1 && afterArrow.inBar;
    if (!stripOk) bad += 1;
    console.log(`   tab strip: ${strip.inTabOrder} button(s) in the tab order (want 1), arrow moved focus to ${afterArrow.focused} ${afterArrow.inBar ? 'inside the strip' : 'OUT of the strip'} ${stripOk ? '' : ' <- FINDING'}`);

    // The arrow key does not only move focus, it *selects*: the strip
    // activates on focus, which is the automatic-activation pattern for a
    // tablist. So the next two checks would otherwise run on whatever tab
    // the arrow landed on rather than on Notes.
    await page.click('[data-tab="notes"]').catch(() => {});
    await page.waitForTimeout(700);

    // --- 2. the folded arrange zone --------------------------------------
    const opened = await page.evaluate(() => {
      const dock = document.querySelector('.tab-page:not(.hidden) .dock');
      if (!dock) return { note: 'no dock on this tab' };
      const details = dock.querySelector('details.dock-menu');
      if (!details) return { note: 'no folded menu on this dock' };
      const summary = details.querySelector('summary');
      details.open = true;
      return {
        tabbableSummary: Boolean(summary && summary.tabIndex >= 0),
        selects: details.querySelectorAll('select').length,
      };
    });
    // **After the open animation, not during it.** Measured mid-animation the
    // menu's contents are at `opacity: 0` for the first frame of the 0.16s
    // reveal added by INBOX 103, and `checkVisibility({opacityProperty:true})`
    // correctly says "not visible", so the first version of this check
    // reported every dock menu as revealing nothing at all.
    await page.waitForTimeout(400);
    const fold = opened.note ? opened : {
      ...opened,
      revealed: await page.evaluate(() => {
        const details = document.querySelector('.tab-page:not(.hidden) .dock details.dock-menu');
        if (!details) return 0;
        const n = [...details.querySelectorAll('select, button, input')].filter(
          (e) => e.checkVisibility && e.checkVisibility({ visibilityProperty: true, opacityProperty: true })
        ).length;
        details.open = false;
        return n;
      }),
    };
    if (fold.note) {
      console.log(`   folded arrange zone: ${fold.note}`);
    } else {
      const foldOk = fold.tabbableSummary && fold.revealed > 0;
      if (!foldOk) bad += 1;
      console.log(`   folded arrange zone: summary ${fold.tabbableSummary ? 'is' : 'is NOT'} in the tab order, opening it reveals ${fold.revealed} control(s)${foldOk ? '' : ' <- FINDING'}`);
    }

    // --- 1. the sidebar sheet --------------------------------------------
    if (width < 820) {
      const toggle = await page.$('#tab-notes .sidebar-collapse-toggle, #sidebar > .sidebar-collapse-toggle');
      if (!toggle) {
        console.log('   sheet: no collapse toggle found');
      } else {
        await toggle.focus();
        await toggle.press('Enter');
        await page.waitForTimeout(600);
        const opened = await page.evaluate(() => {
          const sheet = document.getElementById('sidebar');
          const el = document.activeElement;
          return {
            open: Boolean(sheet && sheet.classList.contains('sidebar-sheet-open')),
            focusInside: Boolean(sheet && el && sheet.contains(el)),
            focused: el ? `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}` : 'none',
          };
        });
        await page.keyboard.press('Escape');
        await page.waitForTimeout(500);
        const closed = await page.evaluate(() => {
          const sheet = document.getElementById('sidebar');
          const el = document.activeElement;
          return {
            open: Boolean(sheet && sheet.classList.contains('sidebar-sheet-open')),
            onToggle: Boolean(el && el.classList && el.classList.contains('sidebar-collapse-toggle')),
            focused: el ? `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}` : 'none',
          };
        });
        if (!opened.open || !opened.focusInside || closed.open || !closed.onToggle) bad += 1;
        console.log(`   sheet: opens ${opened.open}, focus enters ${opened.focusInside} (${opened.focused}); Escape closes ${!closed.open}, focus returns to the toggle ${closed.onToggle} (${closed.focused})`);
      }
    }
    await ctx.close();
  }
  await browser.close();
  console.log(bad ? `FAIL: ${bad} findings` : 'PASS: 0 findings');
  process.exit(bad ? 1 : 0);
})();
