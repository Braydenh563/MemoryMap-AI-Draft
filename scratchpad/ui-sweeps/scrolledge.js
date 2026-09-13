// The scroll edge effect, measured (UI_MODERNISATION_PLAN Phase 10, INBOX 100).
//
// Two jobs. First, before the effect exists: find out *what actually scrolls*
// on each tab, and which bar sits above it, because the effect is worthless if
// it is wired to the wrong element and a screenshot cannot tell you which one
// moved. Second, after it exists: assert the gradient is absent at scrollTop 0
// and present once the region has been scrolled.
//
//   BASE=http://127.0.0.1:8790 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/scrolledge.js
//
// Prints one block per tab and exits non-zero if the effect is on at rest or
// off after a scroll.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8781';
const WIDTH = Number(process.env.WIDTH || 1440);
const TABS = (process.env.TABS || 'notes,library,timeline,reminders,chat').split(',');

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: WIDTH, height: 900 },
    deviceScaleFactor: 1,
  });
  await ctx.addInitScript((t) => {
    try {
      localStorage.setItem('theme', t);
      localStorage.setItem('onboardingDone', '1');
    } catch (e) { /* no storage in a private window; the app copes */ }
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
  await page.waitForTimeout(800);

  let bad = 0;
  for (const tab of TABS) {
    await page.click(`[data-tab="${tab}"]`).catch(() => {});
    await page.waitForTimeout(700);
    const before = await page.evaluate(() => {
      const page_ = document.querySelector('.tab-page:not(.hidden)');
      const scrollers = [...(page_ ? page_.querySelectorAll('*') : [])]
        .filter((e) => e.scrollHeight > e.clientHeight + 4
          && /auto|scroll/.test(getComputedStyle(e).overflowY))
        .slice(0, 4)
        .map((e) => `${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].slice(0, 2).join('.')} ${e.scrollHeight}/${e.clientHeight}`);
      const docScrolls = document.documentElement.scrollHeight > window.innerHeight + 4;
      const marked = [...document.querySelectorAll('[data-scrolled="1"]')]
        .map((e) => `${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].slice(0, 2).join('.')}`);
      const bars = [...document.querySelectorAll('.tab-page:not(.hidden) .dock, .tab-page:not(.hidden) .edge-fade, header#top-bar')]
        .map((e) => `${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].slice(0, 2).join('.')}`);
      return { scrollers, docScrolls, marked, bars };
    });
    // Scroll the first real scroller (or the window) and look again.
    const after = await page.evaluate(() => {
      const page_ = document.querySelector('.tab-page:not(.hidden)');
      const target = [...(page_ ? page_.querySelectorAll('*') : [])]
        .find((e) => e.scrollHeight > e.clientHeight + 4
          && /auto|scroll/.test(getComputedStyle(e).overflowY));
      if (target) target.scrollTop = 240;
      else window.scrollTo(0, 240);
      return new Promise((resolve) => setTimeout(() => resolve({
        marked: [...document.querySelectorAll('[data-scrolled="1"]')]
          .map((e) => `${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].slice(0, 2).join('.')}`
            + ` shadow=${getComputedStyle(e).boxShadow.slice(0, 60)}`),
        // The effect must not turn a horizontal strip into a vertical
        // scroller: the `::after` version of it did exactly that, and a
        // 16px vertical scroll on a sub-tab strip is invisible until you
        // put a finger on it.
        strips: [...document.querySelectorAll('.notes-subtabs, .library-subtabs, .dock')]
          .filter((e) => e.scrollHeight > e.clientHeight + 4)
          .map((e) => `${e.id || e.className} ${e.scrollHeight}/${e.clientHeight}`),
      }), 200));
    });
    console.log(`== ${tab} @${WIDTH}`);
    console.log(`   scrollers: ${before.scrollers.join(' | ') || 'none'}${before.docScrolls ? ' | (document)' : ''}`);
    console.log(`   bars: ${before.bars.join(' | ') || 'none'}`);
    console.log(`   marked at rest: ${before.marked.join(' | ') || 'none'}`);
    console.log(`   marked after scroll: ${after.marked.join(' | ') || 'none'}`);
    if (before.marked.length) { bad += 1; console.log('   FAIL: the edge is painted at scrollTop 0'); }
    if (!after.marked.length && (before.scrollers.length || before.docScrolls)) {
      bad += 1; console.log('   FAIL: nothing marked after scrolling a region');
    }
    if (after.strips.length) {
      bad += 1;
      console.log(`   FAIL: a bar gained vertical scroll: ${after.strips.join(', ')}`);
    }
    // Put it back so the next tab starts at rest.
    await page.evaluate(() => {
      const page_ = document.querySelector('.tab-page:not(.hidden)');
      const target = [...(page_ ? page_.querySelectorAll('*') : [])]
        .find((e) => e.scrollHeight > e.clientHeight + 4
          && /auto|scroll/.test(getComputedStyle(e).overflowY));
      if (target) target.scrollTop = 0; else window.scrollTo(0, 0);
    });
    await page.waitForTimeout(200);
  }
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
