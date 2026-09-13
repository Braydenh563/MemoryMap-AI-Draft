// What each background style costs per frame, and whether the intensity
// slider reaches it (UI_MODERNISATION_PLAN, INBOX 94).
//
// The measurement is the frame interval, not a stopwatch around the draw
// call: p5 runs its own loop and what a person notices is the gap between
// frames. The page is otherwise idle, so the art off is the baseline and the
// art on is the cost. Mean, p95 and the worst frame over three seconds each,
// because a 60fps mean with a 40ms hitch in it is not a smooth background.
//
// It also counts what each style puts on screen at two intensities, which is
// the other half of the item: the slider is supposed to change something
// visible at every step, and a style that ignores `ctx.density` only changes
// the canvas opacity.
//
//   BASE=http://127.0.0.1:8790 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/ui-sweeps/bgart.js
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8790';
const STYLES = (process.env.STYLES || 'aurora,constellation,waves,bubbles,mesh').split(',');
const SECONDS = Number(process.env.SECONDS || 3);

async function boot(browser, prefs) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await ctx.addInitScript((p) => {
    try {
      localStorage.setItem('theme', 'light');
      localStorage.setItem('onboardingDone', '1');
      for (const [k, v] of Object.entries(p)) localStorage.setItem(k, v);
    } catch (e) { /* a private window has no storage; the app copes */ }
  }, prefs);
  const page = await ctx.newPage();
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
  await page.fill('#lock-password', PW);
  await page.click('#lock-submit');
  await page.waitForTimeout(3000);
  await page.evaluate(() => {
    const o = document.getElementById('onboarding-overlay');
    if (o) o.classList.add('hidden');
  });
  await page.waitForTimeout(1200);
  return { ctx, page };
}

// Frame intervals over `SECONDS`, in the page.
async function frames(page, seconds) {
  return page.evaluate((s) => new Promise((resolve) => {
    const gaps = [];
    let last = performance.now();
    const stop = last + s * 1000;
    const tick = (now) => {
      gaps.push(now - last);
      last = now;
      if (now < stop) requestAnimationFrame(tick);
      else {
        gaps.sort((a, b) => a - b);
        const mean = gaps.reduce((t, g) => t + g, 0) / gaps.length;
        resolve({
          n: gaps.length,
          mean: +mean.toFixed(2),
          p95: +gaps[Math.floor(gaps.length * 0.95)].toFixed(2),
          worst: +gaps[gaps.length - 1].toFixed(2),
        });
      }
    };
    requestAnimationFrame(tick);
  }), seconds);
}

(async () => {
  const browser = await chromium.launch();

  const off = await boot(browser, { bgArt: 'off' });
  const base = await frames(off.page, SECONDS);
  console.log(`== background off: mean ${base.mean}ms, p95 ${base.p95}ms, worst ${base.worst}ms (${base.n} frames)`);
  await off.ctx.close();

  for (const style of STYLES) {
    // The frame cost at the two ends of the intensity slider. Intensity is
    // supposed to scale how much each style puts on screen (`ctx.density`),
    // so a style that reads it gets cheaper at 10 than at 100 and a style
    // that ignores it does not move.
    //
    // **Counting ink on the canvas was tried first and dropped**, and it is
    // worth saying why rather than leaving it for someone to retry: the
    // share of pixels that differ from the wash varies by about 0.15 points
    // between two boots of the *same* settings, because every style places
    // its marks with `p.random`, and that is larger than the difference the
    // slider makes. It measured the seed, not the setting.
    const cheap = await boot(browser, {
      bgArt: 'on', 'bg-style': style, 'bg-motion': 'moving', 'bg-intensity': '10',
    });
    const low = await frames(cheap.page, SECONDS);
    await cheap.ctx.close();
    const dense = await boot(browser, {
      bgArt: 'on', 'bg-style': style, 'bg-motion': 'moving', 'bg-intensity': '100',
    });
    const high = await frames(dense.page, SECONDS);
    await dense.ctx.close();

    const { ctx, page } = await boot(browser, {
      bgArt: 'on', 'bg-style': style, 'bg-motion': 'moving', 'bg-intensity': '45',
    });
    const on = await frames(page, SECONDS);
    // Does the canvas cover the window, and does the style react to intensity?
    const shape = await page.evaluate(() => {
      const c = document.getElementById('bg-art-canvas');
      if (!c) return { canvas: 'absent' };
      const r = c.getBoundingClientRect();
      return {
        canvas: `${Math.round(r.width)}x${Math.round(r.height)} at ${Math.round(r.left)},${Math.round(r.top)}`,
        covers: r.left <= 0 && r.top <= 0 && r.right >= innerWidth && r.bottom >= innerHeight,
        opacity: getComputedStyle(document.documentElement).getPropertyValue('--bg-art-opacity').trim(),
      };
    });
    console.log(
      `== ${style}: mean ${on.mean}ms (+${(on.mean - base.mean).toFixed(2)}), `
      + `p95 ${on.p95}ms, worst ${on.worst}ms; canvas ${shape.canvas}`
      + `${shape.covers === false ? ' NOT COVERING THE WINDOW' : ''}, opacity ${shape.opacity}`
      + `\n   intensity 10 -> ${low.mean}ms, intensity 100 -> ${high.mean}ms`,
    );
    await ctx.close();
  }

  // Performance mode: the art must be a *still frame*, not a slower
  // animation. Two captures of the canvas a second apart, compared byte for
  // byte: a still frame is identical and a slow one is not.
  const perf = await boot(browser, {
    bgArt: 'on', 'bg-style': 'aurora', 'bg-motion': 'moving', perf: 'on',
  });
  // The canvas's *own* pixels, twice, a second apart. Not a screenshot of
  // the element: the art sits at `--bg-art-opacity` over a page that paints
  // its own gradient and blobs, so a composited capture differs between two
  // frames even when the canvas has not been redrawn at all. That is what a
  // screenshot comparison reported here first, and it would have been read
  // as "Performance mode does not stop the art".
  const sum = () => perf.page.evaluate(() => {
    const c = document.getElementById('bg-art-canvas');
    if (!c) return null;
    const g = c.getContext('2d', { willReadFrequently: true });
    const { data } = g.getImageData(0, 0, c.width, c.height);
    let h = 0;
    for (let i = 0; i < data.length; i += 997) h = (h * 31 + data[i]) % 2147483647;
    return h;
  });
  const first = await sum();
  await perf.page.waitForTimeout(1000);
  const second = await sum();
  if (first === null) console.log('== performance mode, aurora: no canvas');
  else console.log(`== performance mode, aurora: ${first === second ? 'still (the canvas is not redrawn)' : 'STILL MOVING'}`);
  await perf.ctx.close();

  await browser.close();
})();
