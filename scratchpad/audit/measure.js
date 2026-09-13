// The measurement run behind docs/roadmap/MODERNISATION_AUDIT.md.
//
// Everything the audit quotes as a number came out of this script, against a
// real Chromium and a real uvicorn on a fresh data dir. Run:
//
//   BASE=http://127.0.0.1:8791 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/audit/measure.js > scratchpad/audit/results.json
//
// What it collects, and why each one is here rather than eyeballed:
//   * boot timing            — "laggy" needs a first number, not an adjective
//   * idle requests in 60s   — PLAN P1's acceptance gate has no baseline yet
//   * per-tab errors         — a page error is invisible until you listen
//   * horizontal overflow    — the only objective test for "not responsive"
//   * clipped elements       — scrollHeight vs clientHeight, CLAUDE.md's rule
//   * button signatures      — UI_MODERNISATION_PLAN Phase 2 counts these
//   * tap targets < 40px     — AUDIT E11 asked for exactly this sweep
const { boot, goTab, TABS } = require('./lib');

// One computed-style signature per button. The fields are the ones that make
// two buttons read as "different recipes" to the eye: the box, the edge, the
// type and the fill. Deliberately NOT including colour-on-hover or transition
// — those differ legitimately between a filled and a plain button.
const SIGNATURE_JS = `(() => {
  const sigs = new Map();
  const els = [...document.querySelectorAll('button, .btn, [role=button]')];
  let visible = 0;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.offsetParent === null) continue;
    visible++;
    const s = getComputedStyle(el);
    const sig = [
      Math.round(r.height),
      s.padding,
      s.borderWidth, s.borderStyle, s.borderRadius,
      s.fontSize, s.fontWeight, s.letterSpacing,
      s.backgroundColor, s.color,
      s.boxShadow === 'none' ? 'no-shadow' : 'shadow',
    ].join('|');
    sigs.set(sig, (sigs.get(sig) || 0) + 1);
  }
  return { visible, distinct: sigs.size, top: [...sigs.entries()].sort((a,b)=>b[1]-a[1]).slice(0,4) };
})()`;

// scrollHeight > clientHeight on something that does not advertise itself as
// a scroller is text sliced off. `overflow: hidden` is the tell; an `auto`
// pane is doing its job. 2px of slack absorbs sub-pixel rounding.
const CLIPPED_JS = `(() => {
  const out = [];
  for (const el of document.querySelectorAll('.card, .widget, .entry-card, .library-card, .row, li, button')) {
    if (el.offsetParent === null) continue;
    const s = getComputedStyle(el);
    if (s.overflowY !== 'hidden' && s.overflow !== 'hidden') continue;
    if (el.scrollHeight - el.clientHeight > 2) {
      out.push({
        sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + (el.className || '').toString().split(' ').slice(0,2).join('.'),
        client: el.clientHeight, scroll: el.scrollHeight,
      });
    }
  }
  return out.slice(0, 12);
})()`;

const OVERFLOW_JS = `({
  scrollW: document.documentElement.scrollWidth,
  innerW: window.innerWidth,
  over: document.documentElement.scrollWidth - window.innerWidth,
  worst: (() => {
    let worst = null;
    for (const el of document.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.width === 0) continue;
      if (r.right > window.innerWidth + 1 && (!worst || r.right > worst.right)) {
        worst = { right: Math.round(r.right), sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + (el.className || '').toString().split(' ').slice(0,2).join('.') };
      }
    }
    return worst;
  })(),
})`;

// WCAG 2.5.8 asks 24px; Apple's HIG asks 44pt; 40px is the line this project's
// own AUDIT E11 drew. Counted only for pointer targets that are actually on
// screen, because an off-screen control is a different problem.
const TAPS_JS = `(() => {
  let total = 0, small = 0; const worst = [];
  for (const el of document.querySelectorAll('button, a, [role=button], input[type=checkbox], input[type=radio], select')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    total++;
    const m = Math.min(r.width, r.height);
    if (m < 40) {
      small++;
      worst.push({ sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + (el.className||'').toString().split(' ')[0], w: Math.round(r.width), h: Math.round(r.height) });
    }
  }
  worst.sort((a,b)=>Math.min(a.w,a.h)-Math.min(b.w,b.h));
  return { total, small, worst: worst.slice(0, 8) };
})()`;

async function main() {
  const results = { generated: new Date().toISOString() };

  // --- 1. Boot timing + CSS weight, at the default desktop width ----------
  {
    const { browser, page, errors } = await boot({ viewport: { width: 1440, height: 900 } });
    results.boot = await page.evaluate(() => {
      const t = performance.timing;
      const paints = {};
      for (const p of performance.getEntriesByType('paint')) paints[p.name] = Math.round(p.startTime);
      const nav = performance.getEntriesByType('navigation')[0] || {};
      return {
        domContentLoaded_ms: t.domContentLoadedEventEnd - t.navigationStart,
        loadEvent_ms: t.loadEventEnd - t.navigationStart,
        firstPaint_ms: paints['first-paint'] ?? null,
        firstContentfulPaint_ms: paints['first-contentful-paint'] ?? null,
        domInteractive_ms: Math.round(nav.domInteractive || 0),
        transferBytesTotal: performance.getEntriesByType('resource')
          .reduce((a, r) => a + (r.transferSize || 0), 0),
        resourceCount: performance.getEntriesByType('resource').length,
      };
    });
    results.assets = await page.evaluate(() => {
      let cssBytes = 0, cssRules = 0, jsBytes = 0;
      for (const r of performance.getEntriesByType('resource')) {
        if (r.name.includes('.css')) cssBytes += r.decodedBodySize || r.transferSize || 0;
        if (r.name.includes('.js')) jsBytes += r.decodedBodySize || r.transferSize || 0;
      }
      for (const sheet of document.styleSheets) {
        try { cssRules += sheet.cssRules.length; } catch (e) { /* cross-origin */ }
      }
      return {
        cssBytes, jsBytes, cssRules,
        styleSheets: document.styleSheets.length,
        domNodes: document.querySelectorAll('*').length,
        scripts: document.querySelectorAll('script[src]').length,
      };
    });

    // --- 2. Sixty seconds of doing nothing on the dashboard ---------------
    await goTab(page, 'dashboard');
    await page.evaluate(() => { performance.clearResourceTimings(); window.__t0 = performance.now(); });
    await page.waitForTimeout(60000);
    results.idle60s = await page.evaluate(() => {
      const rs = performance.getEntriesByType('resource');
      const byPath = {};
      for (const r of rs) {
        const p = new URL(r.name).pathname;
        byPath[p] = (byPath[p] || 0) + 1;
      }
      return {
        total: rs.length,
        elapsed_ms: Math.round(performance.now() - window.__t0),
        byPath: Object.entries(byPath).sort((a, b) => b[1] - a[1]),
      };
    });
    results.idleErrors = { page: errors.page.slice(0, 10), console: errors.console.slice(0, 10) };
    await browser.close();
  }

  // --- 3. Per-tab sweeps at three widths ---------------------------------
  for (const [label, viewport, touch] of [
    ['desktop_1440x900', { width: 1440, height: 900 }, false],
    ['small_1024x768', { width: 1024, height: 768 }, false],
    ['mobile_390x844', { width: 390, height: 844 }, true],
  ]) {
    const { browser, page, errors } = await boot({ viewport, touch });
    const perTab = {};
    for (const tab of TABS) {
      const before = { p: errors.page.length, c: errors.console.length };
      await goTab(page, tab);
      perTab[tab] = {
        overflow: await page.evaluate(OVERFLOW_JS),
        buttons: await page.evaluate(SIGNATURE_JS),
        clipped: await page.evaluate(CLIPPED_JS),
        taps: await page.evaluate(TAPS_JS),
        pageErrors: errors.page.length - before.p,
        consoleErrors: errors.console.length - before.c,
      };
    }
    results[label] = { perTab, errors: { page: errors.page.slice(0, 10), console: errors.console.slice(0, 10) } };
    await browser.close();
  }

  process.stdout.write(JSON.stringify(results, null, 2) + '\n');
}

main().catch((e) => { console.error(e); process.exit(1); });
