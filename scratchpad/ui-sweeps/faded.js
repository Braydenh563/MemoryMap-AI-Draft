// The Rediscover widget, driven (WORLD_CLASS_PLAN 15, I4).
//
// It seeds fourteen notes (past `resurface.MIN_NOTEBOOK`, which is what makes
// the scored path run at all rather than the shuffle), opens the dashboard,
// and reads the three cards: their titles, the reason line each carries, the
// width they get in the widget column, and the size of the dismiss control.
// Then it presses "Never again" on one and checks the card actually goes.
//
//   BASE=http://127.0.0.1:8781 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node faded.js
//
// Use a fresh data dir: a notebook that already has dismissals will show
// fewer cards, which is the feature working rather than a finding.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const BASE = process.env.BASE;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
  await page.fill('#lock-password', 'testpassword123');
  await page.click('#lock-submit');
  await sleep(4000);
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
  await sleep(1200);
  // Fourteen notes, past resurface.MIN_NOTEBOOK.
  const token = await page.evaluate(() => localStorage.getItem('auth_token') || sessionStorage.getItem('auth_token'));
  for (let i = 0; i < 14; i++) {
    await page.evaluate(async (n) => {
      await fetch('/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Auth-Token': (window.authToken ? window.authToken() : ''), 'X-Workspace-ID': (window.activeSpaceId ? window.activeSpaceId() : '') },
        body: JSON.stringify({ content: `Note ${n}\n\nSomething written down a while ago about subject ${n}.` }),
      });
    }, i);
  }
  await page.reload({ waitUntil: 'domcontentloaded' });
  await sleep(4000);
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
  await page.click('[data-tab="dashboard"]').catch(() => {});
  await sleep(2500);
  // Make sure the widget is on the dashboard.
  const shown = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.faded-card')];
    return {
      cards: cards.length,
      titles: cards.map((c) => c.querySelector('.faded-title')?.textContent),
      reasons: cards.map((c) => c.querySelector('.faded-why')?.textContent),
      widths: cards.map((c) => Math.round(c.getBoundingClientRect().width)),
      dismissSize: cards.map((c) => { const b = c.querySelector('.faded-dismiss')?.getBoundingClientRect(); return b ? `${Math.round(b.width)}x${Math.round(b.height)}` : null; }),
      widgetPresent: Boolean(document.querySelector('[data-widget="random"]')),
    };
  });
  console.log(JSON.stringify(shown, null, 1));
  if (shown.cards) {
    await page.click('.faded-card .faded-dismiss');
    await sleep(1200);
    const after = await page.evaluate(() => document.querySelectorAll('.faded-card').length);
    console.log('cards after one dismissal:', after);
  }
  console.log('errors:', errors.length, errors.slice(0, 4));
  await b.close();
})();
