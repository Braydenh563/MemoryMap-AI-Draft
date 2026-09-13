// Second measurement pass for docs/roadmap/MODERNISATION_AUDIT.md.
//
// measure.js ran against an EMPTY notebook, which is the wrong fixture for
// half the questions the audit asks ("how many notes fit on a screen" has no
// answer with no notes). This one seeds 40 notes through the app's own `api()`
// helper — so the rows are created exactly the way the UI creates them — and
// then measures the things that only mean something with content in the page.
//
//   BASE=http://127.0.0.1:8791 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node scratchpad/audit/measure2.js > scratchpad/audit/results2.json
//
// The deliberate design choices here, so a later session does not "fix" them:
//   * tap targets are bucketed at 24 / 28 / 40px, not counted against one
//     number. 24 is WCAG 2.5.8 AA, 28 is this project's own `--target-min`
//     (DESIGN.md), 40 is the comfort bar. Reporting one bucket as "failures"
//     would be dishonest about which line was actually crossed.
//   * chrome height is measured as the top of the first *content* element,
//     because REDESIGN §R1.1's "344px of chrome above the first item" is the
//     complaint this has to be comparable to.
//   * the same geometry is taken at 1024 and 1440 to test §R1.1's claim that
//     the layout is "a step function, not a response".
const { boot, goTab, TABS } = require('./lib');

const SEED = 40;

async function seed(page) {
  return page.evaluate(async (n) => {
    const words = ['transformer', 'kanban', 'lecture', 'invoice', 'thesis', 'recipe',
      'sprint', 'migration', 'budget', 'interview', 'protein', 'render'];
    let ok = 0;
    for (let i = 0; i < n; i++) {
      const body = {
        content: `Seed note ${i}: ${words[i % words.length]} notes for the audit fixture. ` +
          'A second line so the card has two lines of text to measure against.',
      };
      try {
        // `api()` is a plain global in app.js — it carries X-Auth-Token and
        // X-Workspace-ID, which a raw fetch from here would not.
        await window.api('/entries', { method: 'POST', body: JSON.stringify(body) });
        ok++;
      } catch (e) { /* keep going; the count below reports what landed */ }
    }
    return ok;
  }, SEED);
}

const GEOMETRY_JS = `(() => {
  const px = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; };
  const main = document.querySelector('main');
  const page = document.querySelector('.tab-page:not(.hidden)') || main;
  // The first thing the user actually came to look at, per surface.
  const firstContent = document.querySelector(
    '#entry-list > *, .library-card, .widget, .timeline-item, .reminder-row, .chat-message, .entry-card'
  );
  return {
    innerW: window.innerWidth,
    main: px(main),
    page: px(page),
    firstContentTop: firstContent ? Math.round(firstContent.getBoundingClientRect().top) : null,
    leftGutter: main ? Math.round(main.getBoundingClientRect().left) : null,
    rightGutter: main ? Math.round(window.innerWidth - main.getBoundingClientRect().right) : null,
    sidebar: px(document.querySelector('#category-sidebar, .sidebar, aside')),
    entryCount: document.querySelectorAll('#entry-list > *').length,
    entryFirst: px(document.querySelector('#entry-list > *')),
    // How many rows are inside the viewport at all — the "5 notes in a 900px
    // window" number from REDESIGN §R1.1, remeasured.
    entriesInViewport: [...document.querySelectorAll('#entry-list > *')]
      .filter((el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; }).length,
  };
})()`;

const TAPS_JS = `(() => {
  const buckets = { under24: 0, under28: 0, under40: 0, total: 0 };
  const worst = [];
  for (const el of document.querySelectorAll('button, a[href], [role=button], input[type=checkbox], input[type=radio], select')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    buckets.total++;
    const m = Math.min(r.width, r.height);
    if (m < 40) buckets.under40++;
    if (m < 28) buckets.under28++;
    if (m < 24) { buckets.under24++; worst.push({ sel: (el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + (el.className||'').toString().split(' ')[0]), w: Math.round(r.width), h: Math.round(r.height) }); }
  }
  worst.sort((a, b) => Math.min(a.w, a.h) - Math.min(b.w, b.h));
  return { ...buckets, worst: worst.slice(0, 8) };
})()`;

// Glass costs a full filter pass per layer, and a blurred layer inside another
// blurred layer costs two. HANDOVER records this being brought from 15-35 down
// to 4-13; this re-counts it so the audit quotes a current number, not a
// remembered one.
const GLASS_JS = `(() => {
  const blurred = [...document.querySelectorAll('*')].filter((el) => {
    if (el.offsetParent === null) return false;
    const s = getComputedStyle(el);
    return (s.backdropFilter && s.backdropFilter !== 'none') || (s.webkitBackdropFilter && s.webkitBackdropFilter !== 'none');
  });
  let nested = 0;
  for (const el of blurred) {
    let p = el.parentElement;
    while (p) { if (blurred.includes(p)) { nested++; break; } p = p.parentElement; }
  }
  const shadows = [...document.querySelectorAll('*')].filter((el) => el.offsetParent !== null && getComputedStyle(el).boxShadow !== 'none').length;
  return { blurred: blurred.length, nested, shadows };
})()`;

// Phase 1 of UI_MODERNISATION_PLAN is judged on "one card padding per card
// size, one card gap, one shell gutter". These are those counts, live.
const TOKENS_JS = `(() => {
  const grab = (sel, prop) => {
    const vals = new Map();
    for (const el of document.querySelectorAll(sel)) {
      if (el.offsetParent === null) continue;
      const v = getComputedStyle(el)[prop];
      vals.set(v, (vals.get(v) || 0) + 1);
    }
    return [...vals.entries()].sort((a, b) => b[1] - a[1]);
  };
  return {
    cardPadding: grab('.card', 'padding'),
    cardRadius: grab('.card, .widget, .modal-card', 'borderRadius'),
    rowGap: grab('.row', 'gap'),
    fieldHeights: grab('input[type=text], input[type=search], select, textarea', 'height'),
  };
})()`;

async function main() {
  const results = { generated: new Date().toISOString(), seeded: 0 };

  // Seed once, at the default width; the rows persist in the data dir so the
  // narrow-width pass below sees the same notebook.
  {
    const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
    results.seeded = await seed(page);
    await browser.close();
  }

  for (const [label, viewport, touch] of [
    ['w1440', { width: 1440, height: 900 }, false],
    ['w1024', { width: 1024, height: 768 }, false],
    ['w390', { width: 390, height: 844 }, true],
  ]) {
    const { browser, page, errors } = await boot({ viewport, touch });
    const perTab = {};
    for (const tab of TABS) {
      const t0 = Date.now();
      await goTab(page, tab);
      perTab[tab] = {
        switchMs: Date.now() - t0 - 1800, // minus the fixed settle wait
        geometry: await page.evaluate(GEOMETRY_JS),
        taps: await page.evaluate(TAPS_JS),
        glass: await page.evaluate(GLASS_JS),
      };
      if (tab === 'notes' || tab === 'library') {
        perTab[tab].tokens = await page.evaluate(TOKENS_JS);
      }
    }
    results[label] = { perTab, errors: { page: errors.page.slice(0, 6), console: errors.console.slice(0, 6) } };
    await browser.close();
  }

  process.stdout.write(JSON.stringify(results, null, 2) + '\n');
}

main().catch((e) => { console.error(e); process.exit(1); });
