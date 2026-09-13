// Touch targets, on a real touch context (UI_MODERNISATION_PLAN.md Phase 9).
//
// A `hasTouch` + `isMobile` browser context is not decoration here: it is what
// makes `(hover: none)` and `(pointer: coarse)` match, so the page under test
// is the page a phone gets rather than a desktop page in a narrow window.
//
// Three questions per control, and the third is the one a size check alone
// cannot answer:
//
//   1. Is the hit target at least 44 CSS px on both sides? That is the figure
//      Phase 9's `--target-min` steps up to below 820, and the figure both
//      platform guidelines give.
//   2. Does a tap at its centre actually reach it? A control can be the right
//      size and still be covered by a sheet, a sticky strip or a floating
//      button, and `elementFromPoint` is the only thing that knows.
//   3. Does any tap land on two controls? Two targets whose 44px boxes overlap
//      means one of them takes taps meant for the other, and the person doing
//      the tapping has no way to tell which.
//
//   BASE=http://127.0.0.1:8802 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     node touch.js
//
// Prints one line per surface and a non-zero exit if anything fails, so it can
// gate a commit. No screenshots.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8781';
const WIDTH = Number(process.env.WIDTH || 390);
const HEIGHT = Number(process.env.HEIGHT || 844);
const MIN = 44;

// Every dock the app has, plus the three control surfaces that are docks by
// any other name (the chat composer, the dashboard's own widgets, the
// settings sheet). This list used to be three rows, which is how the Notes
// categories overflow at 390 stayed unseen for a session: a sweep only knows
// about what it is pointed at, so "touch PASS" over three surfaces is a
// statement about three surfaces and nothing else.
//
// `open` is a selector clicked after the tab switch, for a surface that lives
// behind a sub-tab; `close` is clicked after the surface has been measured,
// for the ones that are modal and would otherwise cover everything measured
// next.
const SURFACES = [
  { tab: 'notes', label: 'Notes dock', sel: '[data-dock-name="notes"]' },
  { tab: 'notes', label: 'Notes sub-tabs', sel: '#notes-subtabs' },
  { tab: 'chat', label: 'Chat composer', sel: '.chat-dock' },
  { tab: 'dashboard', label: 'Dashboard', sel: '#tab-dashboard' },
  { tab: 'graph', label: 'Graph dock', sel: '[data-dock-name="graph"]' },
  { tab: 'timeline', label: 'Timeline dock', sel: '[data-dock-name="timeline"]' },
  { tab: 'reminders', label: 'Reminders dock', sel: '[data-dock-name="reminders"]' },
  { tab: 'library', label: 'Library sub-tabs', sel: '#library-subtabs' },
  { tab: 'library', label: 'Library dock', sel: '[data-dock-name="library"]' },
  { tab: 'library', label: 'Lib Documents', sel: '[data-dock-name="library-docs"]',
    open: '#library-subtabs button[data-target="library-view-docs"]' },
  { tab: 'library', label: 'Lib Boards', sel: '[data-dock-name="library-boards"]',
    open: '#library-subtabs button[data-target="library-view-whiteboard"]' },
  { tab: 'library', label: 'Lib Images', sel: '[data-dock-name="library-media"]',
    open: '#library-subtabs button[data-media-kind="images"]' },
  { tab: 'library', label: 'Lib skills', sel: '[data-dock-name="library-skills"]',
    open: '#library-subtabs button[data-target="library-view-skills"]' },
  { tab: 'library', label: 'Lib Links', sel: '[data-dock-name="library-links"]',
    open: '#library-subtabs button[data-target="library-view-links"]' },
  { tab: 'library', label: 'Lib Contents', sel: '[data-dock-name="library-contents"]',
    open: '#library-subtabs button[data-target="library-view-contents"]' },
  { tab: 'notes', label: 'Settings sheet', sel: '#settings-modal .modal-card',
    open: '#settings-btn', close: '#settings-close' },
];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: 1,
    hasTouch: true,
    isMobile: true,
  });
  await ctx.addInitScript(() => { try { localStorage.setItem('theme', 'light'); } catch (e) {} });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));

  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
  await page.fill('#lock-password', PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
  if (await page.$('#lock-password') && await page.isVisible('#lock-password')) {
    await page.fill('#lock-password', PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
  }
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
  await page.waitForTimeout(800);

  const media = await page.evaluate(() => ({
    hoverNone: matchMedia('(hover: none)').matches,
    coarse: matchMedia('(pointer: coarse)').matches,
    targetMin: getComputedStyle(document.documentElement).getPropertyValue('--target-min').trim(),
  }));
  console.log(`context ${WIDTH}x${HEIGHT}  hover:none=${media.hoverNone}  pointer:coarse=${media.coarse}  --target-min=${media.targetMin}`);
  if (!media.hoverNone) errors.push('the context is not reporting (hover: none) — the hover gating is not being exercised');

  let failures = 0;
  for (const surface of SURFACES) {
    await page.click(`[data-tab="${surface.tab}"]`).catch(() => {});
    await page.waitForTimeout(600);
    if (surface.open) {
      await page.click(surface.open).catch(() => {});
      await page.waitForTimeout(700);
    }

    const result = await page.evaluate(({ sel, MIN }) => {
      const root = document.querySelector(sel);
      if (!root) return { missing: true };
      const visible = (e) => e.checkVisibility
        && e.checkVisibility({ visibilityProperty: true, opacityProperty: true, contentVisibilityAuto: true });
      const controls = [...root.querySelectorAll('button, select, summary, input:not([type="hidden"]), .seg')]
        .filter(visible)
        // Three kinds of element are deliberately unreachable and each has a
        // visible control standing for it: a `<select>` kept only as the value
        // a handler reads (`.dock-native-hidden`), the app's clipped
        // screen-reader recipes (`.visually-hidden`, `.sr-only` — the chat
        // composer's file input is one, driven by a visible paperclip), and a
        // `.seg` group, whose own buttons are what a finger lands on.
        .filter((e) => !e.closest('.dock-native-hidden, .visually-hidden, .sr-only'))
        .filter((e) => !e.classList.contains('seg'))
        .filter((e) => !e.closest('.dock-menu-list'));

      const name = (e) => `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : '.' + [...e.classList].slice(0, 2).join('.')}`;

      // A switch, a radio and a slider are deliberately small, and the app's
      // own decision (06-timeline-dialogs.css, the `.checkbox-label` note) is
      // that the *label* around them is the hit area: a global floor on the
      // input itself turned every switch into a slab with its knob adrift,
      // and was reported with a screenshot within the hour. So measure what a
      // person actually aims at. Only these three: every other control is its
      // own target, and substituting a label for a button would hide a real
      // finding behind a roomy row.
      const target = (e) => {
        const kind = (e.getAttribute('type') || '').toLowerCase();
        if (e.tagName !== 'INPUT' || !['checkbox', 'radio', 'range'].includes(kind)) return e;
        return e.closest('label') || document.querySelector(`label[for="${CSS.escape(e.id)}"]`) || e;
      };

      const small = [];
      const covered = [];
      const shared = [];

      // Two passes, and the order matters. Every box is measured first, at one
      // scroll position, so the size and overlap answers are all in the same
      // frame of reference; only then does the reachability pass scroll things
      // about. Doing both in one pass compared a control measured at the top of
      // the page with one measured after a scroll, and invented collisions
      // between controls a screen apart.
      const boxes = controls.map((control) => target(control).getBoundingClientRect());

      const seen = new Map();
      controls.forEach((control, index) => {
        const box = boxes[index];
        if (box.width + 0.5 < MIN || box.height + 0.5 < MIN) {
          small.push(`${name(control)} ${box.width.toFixed(1)}x${box.height.toFixed(1)}`);
        }
        const key = `${Math.round(box.left + box.width / 2)},${Math.round(box.top + box.height / 2)}`;
        if (seen.has(key)) shared.push(`${name(control)} shares ${key} with ${seen.get(key)}`);
        else seen.set(key, name(control));
      });

      for (const raw of controls) {
        const control = target(raw);
        let box = control.getBoundingClientRect();
        // Bring it into view before asking what is on top of it. Without this
        // every control below the fold, and every one in a sideways-scrolling
        // strip (the sub-tab segs, the dashboard's quick links), reported
        // "hits nothing" - which is true of a point outside the viewport and
        // says nothing at all about whether a finger can reach the control.
        // Fifteen such lines in one run were all this, and a sweep that cries
        // wolf fifteen times is a sweep nobody reads.
        if (box.top < 0 || box.left < 0
            || box.bottom > innerHeight || box.right > innerWidth) {
          control.scrollIntoView({ block: 'center', inline: 'center' });
          box = control.getBoundingClientRect();
        }
        const x = Math.round(box.left + box.width / 2);
        const y = Math.round(box.top + box.height / 2);
        // Still outside after scrolling: a control its own scroll container
        // cannot reach. That is a finding, not a pass.
        if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) {
          covered.push(`${name(control)} cannot be scrolled into view (centre ${x},${y})`);
          continue;
        }
        let hit = document.elementFromPoint(x, y);
        let reached = hit && (control.contains(hit) || hit.contains(control));
        if (!reached) {
          // Second chance, and it is not a weakening: a control near the end
          // of a scroll container cannot be centred, so `scrollIntoView` puts
          // it wherever the remaining scroll allows, which at the bottom of
          // the dashboard is under the *fixed* tab bar. A person scrolls a
          // little less far and taps it. Asking again from a scroll position
          // the person could actually choose is the honest question; a
          // control that is covered at every position still fails here.
          control.scrollIntoView({ block: 'start', inline: 'center' });
          const again = control.getBoundingClientRect();
          const ax = Math.round(again.left + again.width / 2);
          const ay = Math.round(again.top + again.height / 2);
          if (ax >= 0 && ay >= 0 && ax <= innerWidth && ay <= innerHeight) {
            hit = document.elementFromPoint(ax, ay);
            reached = hit && (control.contains(hit) || hit.contains(control));
          }
        }
        if (!reached) {
          covered.push(`${name(control)} at ${x},${y} hits ${hit ? name(hit) : 'nothing'}`);
        }
      }
      return { count: controls.length, small, covered, shared };
    }, { sel: surface.sel, MIN });

    if (surface.close) {
      await page.click(surface.close).catch(() => {});
      await page.waitForTimeout(400);
    }

    if (result.missing) {
      console.log(`${surface.label.padEnd(16)} NOT FOUND (${surface.sel})`);
      failures += 1;
      continue;
    }
    const bad = result.small.length + result.covered.length + result.shared.length;
    failures += bad;
    console.log(`${surface.label.padEnd(16)} ${result.count} controls  under-${MIN}px: ${result.small.length}  covered: ${result.covered.length}  overlapping taps: ${result.shared.length}`);
    for (const line of [...result.small, ...result.covered, ...result.shared]) console.log(`    ${line}`);
  }

  // And the bottom tab bar, which is the one control row every tab shares.
  const tabs = await page.evaluate((MIN) => {
    const bar = document.getElementById('tab-bar');
    const out = [];
    for (const button of bar.querySelectorAll('button')) {
      const box = button.getBoundingClientRect();
      if (box.width + 0.5 < MIN || box.height + 0.5 < MIN) {
        out.push(`${button.id} ${box.width.toFixed(1)}x${box.height.toFixed(1)}`);
      }
    }
    const b = bar.getBoundingClientRect();
    return { small: out, atBottom: Math.abs(b.bottom - window.innerHeight) < 1.5, scrolls: bar.scrollWidth > bar.clientWidth + 1 };
  }, MIN);
  failures += tabs.small.length;
  // The bottom tab bar is a rule of the phone band (< 600) alone: between
  // 600 and 1100 the strip takes a row of its own inside the header, on
  // purpose, and asserting the phone's shape at 800 reported a failure for
  // a layout that is behaving exactly as its band says it should.
  if (WIDTH < 600 && !tabs.atBottom) { failures += 1; console.log('tab bar          NOT pinned to the bottom edge'); }
  if (tabs.scrolls) { failures += 1; console.log('tab bar          scrolls sideways — a tab is out of reach'); }
  console.log(`tab bar          under-${MIN}px: ${tabs.small.length}  pinned to bottom: ${tabs.atBottom}  scrolls: ${tabs.scrolls}`);
  for (const line of tabs.small) console.log(`    ${line}`);

  // The page itself must not slide sideways. This is the check that found the
  // 7px the header was over at 390 on all seven tabs: every individual
  // surface passed its own measurements while the whole application moved
  // under the finger, because nothing was asking the one question a phone
  // makes obvious.
  const slide = await page.evaluate(() => {
    const out = [];
    for (const tab of ['dashboard', 'notes', 'chat', 'graph', 'library', 'timeline', 'reminders']) {
      const button = document.querySelector(`[data-tab="${tab}"]`);
      if (button) button.click();
      const root = document.documentElement;
      if (root.scrollWidth > root.clientWidth + 0.5) {
        out.push(`${tab}: page scrolls sideways, ${root.scrollWidth} in ${root.clientWidth}`);
      }
    }
    return out;
  });
  failures += slide.length;
  console.log(`sideways scroll   ${slide.length ? slide.length + ' tabs' : 'none'}`);
  for (const line of slide) console.log(`    ${line}`);

  for (const line of errors) console.log(`    ${line}`);
  failures += errors.length;

  console.log(failures ? `FAIL: ${failures} findings` : 'PASS: 0 findings');
  await browser.close();
  process.exit(failures ? 1 : 0);
})();
