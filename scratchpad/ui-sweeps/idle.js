// What a notebook costs when nobody is touching it (WORLD_CLASS_PLAN 10, F6).
//
// Two numbers, because they fail in different ways and only one of them shows
// up in a network panel:
//
//   1. requests per idle minute, visible and hidden. A poll nobody needs is a
//      process woken, and on a laptop that is battery.
//   2. intervals still alive while the tab is hidden. `setInterval` is wrapped
//      before any page script runs, so every interval the app starts is
//      counted by its callback's name and the line that started it, and every
//      `clearInterval` is subtracted. A screenshot cannot see this at all.
//
// The gate: 0 one-second timers while hidden, and nothing polling while hidden
// except the reminder check, which is the one thing a background tab is
// *supposed* to keep doing (a reminder that waited for you to look at the tab
// is not a reminder).
//
//   BASE=http://127.0.0.1:8781 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node idle.js            # ~2.5 minutes: a visible minute and a hidden one
//   QUICK=1 node idle.js      # timers only, ~20 seconds
//
// Hidden is emulated by overriding `document.hidden` and firing
// `visibilitychange`, which is what the app itself listens for. Chromium's own
// throttling of a real background tab would also slow the timers down, which
// would hide the very thing being measured.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const BASE = process.env.BASE || 'http://127.0.0.1:8781';
const PW = 'testpassword123';
const QUICK = Boolean(process.env.QUICK);
const MINUTE = 60000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const setHidden = (page, hidden) =>
  page.evaluate((value) => {
    Object.defineProperty(document, 'hidden', { get: () => value, configurable: true });
    Object.defineProperty(document, 'visibilityState', {
      get: () => (value ? 'hidden' : 'visible'),
      configurable: true,
    });
    document.dispatchEvent(new Event('visibilitychange'));
  }, hidden);

const timers = (page) =>
  page.evaluate(() =>
    [...window.__timers.values()]
      .map((t) => `${t.ms}ms ${t.name} (${t.where})`)
      .sort()
  );

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript(() => {
    window.__timers = new Map();
    const realSet = window.setInterval.bind(window);
    const realClear = window.clearInterval.bind(window);
    window.setInterval = function (fn, ms, ...rest) {
      const id = realSet(fn, ms, ...rest);
      const line = ((new Error().stack || '').split('\n')[2] || '').trim();
      window.__timers.set(id, { ms, name: (fn && fn.name) || 'anon', where: line });
      return id;
    };
    window.clearInterval = function (id) {
      window.__timers.delete(id);
      return realClear(id);
    };
  });
  const page = await ctx.newPage();
  const seen = [];
  page.on('request', (r) => {
    try {
      const url = new URL(r.url());
      if (url.origin === new URL(BASE).origin && !/\.(js|css|svg|png|webmanifest)$/.test(url.pathname)) {
        seen.push({ t: Date.now(), p: url.pathname });
      }
    } catch (e) { /* a data: or blob: url, not ours */ }
  });

  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
  await page.fill('#lock-password', PW);
  await page.click('#lock-submit');
  await sleep(4000);
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
  await sleep(5000);

  const count = (from) => {
    const rows = seen.filter((s) => s.t >= from);
    const by = {};
    for (const r of rows) by[r.p] = (by[r.p] || 0) + 1;
    return { total: rows.length, by };
  };

  let failures = 0;
  const visibleTimers = await timers(page);
  console.log(`intervals while visible: ${visibleTimers.length}`);
  for (const line of visibleTimers) console.log(`    ${line}`);

  if (!QUICK) {
    let mark = Date.now();
    await sleep(MINUTE);
    const visible = count(mark);
    console.log(`requests, visible minute: ${visible.total}  ${JSON.stringify(visible.by)}`);
  }

  await setHidden(page, true);
  await sleep(1500);
  const hiddenTimers = await timers(page);
  const fast = hiddenTimers.filter((line) => Number(line.split('ms')[0]) < 10000);
  failures += fast.length;
  console.log(`intervals while hidden:  ${hiddenTimers.length}  (under 10s: ${fast.length})`);
  for (const line of hiddenTimers) console.log(`    ${line}`);

  if (!QUICK) {
    const mark = Date.now();
    await sleep(MINUTE);
    const hidden = count(mark);
    console.log(`requests, hidden minute:  ${hidden.total}  ${JSON.stringify(hidden.by)}`);
  }

  await setHidden(page, false);
  await sleep(1500);
  const back = await timers(page);
  if (back.length !== visibleTimers.length) {
    failures += 1;
    console.log(`    a timer did not come back: ${visibleTimers.length} before, ${back.length} after`);
  }
  // A clock that resumes on the next tick shows the time it stopped at, which
  // is the one way stopping these can be wrong in a way a person sees.
  const stale = await page.evaluate(() => {
    const el = document.querySelector('.live-clock .clock-time') || document.getElementById('dash-clock-time');
    const now = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    const shown = el ? el.textContent.trim() : '';
    return { shown, now, ok: !el || shown.replace(/^0/, '') === now.replace(/^0/, '') };
  });
  if (!stale.ok) {
    failures += 1;
    console.log(`    the clock says ${stale.shown} on return, the time is ${stale.now}`);
  }
  console.log(`clock on return: ${stale.shown || 'no clock on screen'}`);

  console.log(failures ? `FAIL: ${failures} findings` : 'PASS: 0 findings');
  await browser.close();
  process.exit(failures ? 1 : 0);
})();
