// Boot helper for the MODERNISATION_AUDIT measurements.
//
// Copied from scratchpad/ui-sweeps/lib.js and kept separate on purpose: the
// audit runs against its own data dir and port, and a sweep script that grows
// a new option later must not silently change what the audit measured.
//
// Two traps this encodes (CLAUDE.md): `networkidle` never settles against
// this app (it polls reminders, model status and tasks), so every navigation
// uses `domcontentloaded` plus an explicit wait; and the lock screen is ONE
// field in two modes, so first run and a later unlock are the same two lines.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8791';
const OUT = process.env.SCRATCH || '/tmp/audit-out';
require('fs').mkdirSync(OUT, { recursive: true });

async function boot(opts = {}) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: opts.viewport || { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    hasTouch: !!opts.touch,
    isMobile: !!opts.touch,
  });
  const page = await ctx.newPage();
  const errors = { page: [], console: [] };
  page.on('pageerror', (e) => errors.page.push(String(e.message).slice(0, 200)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.console.push(m.text().slice(0, 200));
  });
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
  await page.fill('#lock-password', PW);
  await page.click('#lock-submit');
  await page.waitForTimeout(3000);
  if ((await page.$('#lock-password')) && (await page.isVisible('#lock-password'))) {
    await page.fill('#lock-password', PW);
    await page.click('#lock-submit');
    await page.waitForTimeout(3000);
  }
  await page.evaluate(() => {
    const o = document.getElementById('onboarding-overlay');
    if (o) o.classList.add('hidden');
  });
  await page.waitForTimeout(800);
  return { browser, ctx, page, errors, OUT };
}

// The seven top-strip tabs, as data so every script walks the same surfaces
// and the numbers line up between runs.
const TABS = ['dashboard', 'notes', 'chat', 'graph', 'library', 'timeline', 'reminders'];

async function goTab(page, tab) {
  await page.evaluate((t) => {
    const btn = document.getElementById('tab-btn-' + t);
    if (btn) btn.click();
  }, tab);
  await page.waitForTimeout(1800);
}

module.exports = { boot, goTab, TABS, PW, BASE, OUT };
