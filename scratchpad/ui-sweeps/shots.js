// The screenshot set (UI_MODERNISATION_PLAN.md Phase 0 item 3): every tab and
// every Settings section, light and dark, at 1440 and 1024 wide, into
// $SCRATCH/shots/<label>/. Same script every session, so two runs are
// comparable file for file.
//
//   SCRATCH=<dir> BASE=http://127.0.0.1:8781 LABEL=before node scratchpad/ui-sweeps/shots.js
//
// Theme is forced through localStorage before the page boots (theme-boot.js
// reads `theme`), which is exactly what the Settings control writes — so this
// is the real light/dark path, not a `data-mode` poke the widgets ignore.
const {chromium} = require('/opt/node22/lib/node_modules/playwright');
const fs = require('fs');
const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8781';
const LABEL = process.env.LABEL || new Date().toISOString().replace(/[:.]/g, '-');
const ROOT = (process.env.SCRATCH || '.') + '/shots/' + LABEL;
const TABS = ['dashboard', 'notes', 'library', 'chat', 'graph', 'timeline', 'reminders'];
const SECTIONS = ['account', 'appearance', 'preferences', 'models', 'tools', 'skills', 'personas',
  'templates', 'websearch', 'memory', 'tasks', 'data', 'logs', 'shortcuts', 'extras', 'help', 'about'];
const WIDTHS = [1440, 1024];
const THEMES = ['light', 'dark'];

async function unlock(page) {
  await page.goto(BASE + '/', {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#lock-password', {state: 'visible', timeout: 20000});
  await page.fill('#lock-password', PW);
  await page.click('#lock-submit');
  await page.waitForTimeout(2500);
  if (await page.$('#lock-password') && await page.isVisible('#lock-password')) {
    await page.fill('#lock-password', PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
  }
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
  await page.waitForTimeout(600);
}

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  let count = 0;
  for (const theme of THEMES) {
    for (const width of WIDTHS) {
      const dir = `${ROOT}/${theme}-${width}`;
      fs.mkdirSync(dir, {recursive: true});
      const ctx = await browser.newContext({viewport: {width, height: 900}, deviceScaleFactor: 1, colorScheme: theme});
      await ctx.addInitScript((t) => { try { localStorage.setItem('theme', t); } catch (e) {} }, theme);
      const page = await ctx.newPage();
      page.on('pageerror', e => errors.push(`${theme}-${width}: ${e.message}`));
      await unlock(page);
      for (const tab of TABS) {
        await page.click(`[data-tab="${tab}"]`).catch(() => {});
        await page.waitForTimeout(700);
        await page.screenshot({path: `${dir}/${tab}.png`});
        count++;
      }
      await page.click('#settings-btn').catch(() => {});
      await page.waitForTimeout(600);
      for (const s of SECTIONS) {
        const ok = await page.click(`#settings-modal [data-section="${s}"]`).then(() => true).catch(() => false);
        if (!ok) continue;
        await page.waitForTimeout(350);
        await page.screenshot({path: `${dir}/settings-${s}.png`});
        count++;
      }
      await ctx.close();
    }
  }
  await browser.close();
  console.log(`${count} screenshots in ${ROOT}`);
  if (errors.length) console.log('PAGE ERRORS:\n' + errors.join('\n'));
})();
