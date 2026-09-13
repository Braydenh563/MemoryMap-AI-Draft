// How many requests the app makes per minute while nobody touches it.
//
// WORLD_CLASS_PLAN section 6 lists "Idle requests per minute: 14, target
// 2" against a script that did not exist. This is it: log in, land on the
// dashboard, do nothing for IDLE_MS, and count every request by path with
// the query string stripped, so a polling loop shows up as one line with a
// big number. A local-first app that polls the machine it is running on
// fourteen times a minute is spending battery to ask itself whether it has
// changed.
//
//   BASE=http://127.0.0.1:8871 IDLE_MS=60000 TAB=dashboard \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/audit/idle.js
const { boot } = require('../ui-sweeps/lib.js');

(async () => {
  const { browser, page } = await boot();
  const tab = process.env.TAB || 'dashboard';
  const idleMs = Number(process.env.IDLE_MS || 60000);
  await page.evaluate((t) => switchTab(t), tab);
  await page.waitForTimeout(3000); // let the tab's own first loads finish
  const counts = new Map();
  const onReq = (r) => {
    const u = new URL(r.url());
    if (u.origin !== new URL(process.env.BASE || 'http://127.0.0.1:8781').origin) return;
    const key = r.method() + ' ' + u.pathname.replace(/\/\d+(?=\/|$)/g, '/{id}');
    counts.set(key, (counts.get(key) || 0) + 1);
  };
  page.on('request', onReq);
  const t0 = Date.now();
  await page.waitForTimeout(idleMs);
  page.off('request', onReq);
  const minutes = (Date.now() - t0) / 60000;
  const rows = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  let total = 0;
  for (const [k, n] of rows) { total += n; console.log(String(n).padStart(4), (n / minutes).toFixed(1).padStart(6) + '/min', k); }
  console.log(`idle: ${total} requests in ${minutes.toFixed(2)} min on ${tab} = ${(total / minutes).toFixed(1)} per minute`);
  await browser.close();
})();
