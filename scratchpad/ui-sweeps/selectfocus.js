// Focusing a `<select>` in this app, and why `.focus()` on one is dead code.
//
// `enhanceSelect` (app.js) replaces every select in the page with a shell
// holding a `<button class="select-opener">` and a listbox, and takes the
// native control out of the tab order: `select-native-hidden`,
// `tabIndex = -1`, `aria-hidden="true"`. So `select.focus()` either focuses
// nothing or focuses an aria-hidden element, and a `keydown` bound to a select
// never fires because the select never has the focus. Nothing throws, nothing
// logs, and the call reads as correct at the line that makes it. Four call
// sites in this codebase were written that way (the documents editor's attach
// picker, the note's own bookmark picker, the chat skills panel and the
// note-to-document picker); `focusSelect(select)` is the one way to do it.
//
// **This file exists because the rule cannot be a lint.** The lints in
// `tests/` read the source as text, and what decides here is what a variable
// *holds* at runtime: `picker.focus()` is dead when `picker` is a select and
// correct when it is an input, and nothing in the text says which. A
// name-based rule would both miss `box.focus()` on a select and fire on
// `picker.focus()` for a text input, and CLAUDE.md's rule is that a lint which
// fires on the wrong thing gets widened until it means nothing. So the guard
// is `focusSelect` plus its comment, and this is the check.
//
// Per select, on every tab, with every disclosure opened first so the ones
// that live in a menu are covered rather than skipped:
//   1. the native control really is out of the tab order, which is the shape
//      that makes the direct call dead. If that stops being true, the note it
//      prints means `focusSelect`'s comment needs re-reading.
//   2. `focusSelect(select)` lands the focus on that select's own opener.
//   3. what the plain `select.focus()` would have done instead, printed rather
//      than asserted: it is the difference the helper exists for, and on this
//      app it is either BODY (nothing at all) or the aria-hidden SELECT.
// Then the attach picker end to end, because that is where it was found.
//
//   BASE=http://127.0.0.1:8834 node scratchpad/ui-sweeps/selectfocus.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const TABS = ['dashboard', 'notes', 'chat', 'library', 'timeline', 'reminders', 'graph'];

(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  let bad = 0;
  const fail = (m) => { console.log('FAIL: ' + m); bad++; };

  const helper = await page.evaluate(() => typeof focusSelect);
  say('focusSelect_defined', helper);
  if (helper !== 'function') fail('focusSelect is not defined; nothing below is measured');

  let seen = 0;
  const direct = {};
  for (const tab of TABS) {
    await page.evaluate((t) => switchTab(t), tab);
    await page.waitForTimeout(700);
    // Open every disclosure on the visible tab: six of this app's selects live
    // inside one, and a control in a shut `<details>` is not focusable by
    // design. Skipping them would leave the menus, which is where the pickers
    // that were actually broken live, untested.
    await page.evaluate(() => {
      const page_ = document.querySelector('.tab-page:not(.hidden)');
      if (!page_) return;
      for (const d of page_.querySelectorAll('details')) d.open = true;
    });
    await page.waitForTimeout(500);
    const rows = await page.evaluate(() => {
      const out = [];
      const page_ = document.querySelector('.tab-page:not(.hidden)');
      if (!page_) return out;
      for (const select of page_.querySelectorAll('select[data-enhanced-select]')) {
        const opener = select.closest('.select-shell')?.querySelector('.select-opener');
        // Off screen for a reason of its own (a collapsed panel, a dialog that
        // is not up): nothing here can be asserted about it.
        if (!opener || !opener.getClientRects().length) continue;
        document.body.focus();
        focusSelect(select);
        const landed = document.activeElement;
        out.push({
          id: select.id || String(select.className).slice(0, 24),
          nativeOutOfTabOrder: select.tabIndex === -1 && select.getAttribute('aria-hidden') === 'true',
          openerTabbable: opener.tabIndex !== -1 && !opener.disabled,
          landedOnOpener: landed === opener,
          landedOn: landed ? landed.tagName + (landed.className ? '.' + String(landed.className).split(' ')[0] : '') : 'null',
          directCallLandsOn: (() => {
            document.body.focus();
            select.focus();
            const a = document.activeElement;
            return a ? a.tagName : 'null';
          })(),
        });
      }
      return out;
    });
    say(tab, rows.map((r) => r.id));
    for (const r of rows) {
      seen += 1;
      direct[r.directCallLandsOn] = (direct[r.directCallLandsOn] || 0) + 1;
      if (!r.nativeOutOfTabOrder) {
        console.log(`NOTE ${tab}/${r.id}: the native select is back in the tab order; re-read focusSelect`);
      }
      if (!r.openerTabbable) fail(`${tab}/${r.id}: its opener cannot take focus`);
      if (!r.landedOnOpener) fail(`${tab}/${r.id}: focusSelect landed on ${r.landedOn}, not on its opener`);
    }
  }
  say('selects_checked', seen);
  // The point of the whole exercise, as one line: where a plain `.focus()`
  // would have put the focus instead. Neither answer is the opener.
  say('plain_focus_would_land_on', direct);
  if (seen < 10) fail(`only ${seen} selects were reachable; this sweep is not covering enough to mean anything`);

  // The picker built on demand, which is where the trap was found.
  await page.evaluate(async () => {
    await api('/bookmarks', { method: 'POST', body: JSON.stringify({ title: 'A link', url: 'https://example.invalid/x' }) });
  });
  await openDoc(page, { title: 'Focus', content: '# A\n\n## B\n' });
  await page.evaluate(() => document.querySelector('#doc-sidebar-tabs [aria-controls="doc-sidebar-outline"]')?.click());
  await page.waitForTimeout(600);
  await page.evaluate(() => { document.body.focus(); document.getElementById('doc-attach-bookmark').click(); });
  await page.waitForTimeout(900);
  const picker = await page.evaluate(() => {
    const a = document.activeElement;
    return {
      landedOn: a ? a.tagName + (a.className ? '.' + String(a.className).split(' ')[0] : '') : 'null',
      insideTheRow: Boolean(a && a.closest && a.closest('.doc-attach-row')),
    };
  });
  say('attach_picker_focus', picker);
  if (!picker.insideTheRow) fail(`the attach picker opened with the focus on ${picker.landedOn}, outside its own row`);
  // Escape is the listener half of the same trap: it is on the document,
  // because a keydown bound to the select would never have fired.
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  const closed = await page.evaluate(() => !document.querySelector('.doc-attach-row'));
  say('escape_closes', closed);
  if (!closed) fail('Escape left the attach picker open');

  console.log(bad ? `selectfocus: ${bad} failures` : 'selectfocus: all checks pass');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
