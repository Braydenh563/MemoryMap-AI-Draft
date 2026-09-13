const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const OUT = (process.env.SCRATCH||'.') + '/shots';
require('fs').mkdirSync(OUT,{recursive:true});
const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8781';
async function boot(opts={}) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({viewport: opts.viewport||{width:1440,height:900}, deviceScaleFactor:1});
  // Deterministic theme: the app remembers the last theme server-side, so a
  // sweep after a dark screenshot run would otherwise measure dark. THEME=dark
  // to sweep the other one.
  // The welcome tour is a race, not a step. Every context is a fresh profile,
  // so `maybeShowOnboarding` opens it after unlock, sometimes *after* the
  // hide below has already run, and then every click times out on
  // "#onboarding-overlay intercepts pointer events" (it cost two sweep runs).
  // Marking it done before the app boots is the only ordering that cannot
  // lose; the hide below stays as the belt to this braces.
  await ctx.addInitScript((t) => {
    try {
      localStorage.setItem('theme', t);
      localStorage.setItem('onboardingDone', '1');
    } catch (e) {}
  }, process.env.THEME || 'light');
  const page = await ctx.newPage();
  page.on('pageerror', e=>console.log('PAGEERROR:', e.message, '\n', (e.stack||'').split('\n').slice(0,6).join('\n')));
  page.on('console', m=>{ if(m.type()==='error') console.log('CONSOLE-ERR:', m.text().slice(0,160)); });
  await page.goto(BASE + '/', {waitUntil:'domcontentloaded'});
  await page.waitForSelector('#lock-password', {state:'visible', timeout:20000});
  await page.fill('#lock-password', PW);
  await page.click('#lock-submit');
  await page.waitForTimeout(3000);
  if (await page.$('#lock-password') && await page.isVisible('#lock-password')) {
    await page.fill('#lock-password', PW); await page.click('#lock-submit'); await page.waitForTimeout(3000);
  }
  await page.evaluate(()=>{ const o=document.getElementById('onboarding-overlay'); if(o) o.classList.add('hidden'); });
  await page.waitForTimeout(800);
  return {browser, ctx, page, OUT};
}
module.exports = {boot, OUT, PW, BASE};
