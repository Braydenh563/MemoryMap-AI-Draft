// Every `.modal-overlay` in the page, measured for content it cannot reach.
//
// `.modal-card` caps itself at 88vh and never says what happens to content
// past the cap. Settings survives because its own `.modal-body` owns a
// scroll pane; a dialog without one simply loses everything below the fold,
// which is what the keyboard-shortcuts overlay does. This unhides each
// overlay under script (they are all `.hidden` until opened) and reports
// scrollHeight against clientHeight, so the fix covers whichever dialogs
// actually have the fault rather than the one that was reported.
const { boot } = require('./lib.js');

(async () => {
  const { page, browser } = await boot({ width: 1440, height: 900 });
  const rows = await page.evaluate(() => {
    const out = [];
    for (const ov of document.querySelectorAll('.modal-overlay')) {
      const wasHidden = ov.classList.contains('hidden');
      ov.classList.remove('hidden');
      const card = ov.querySelector('.modal-card');
      if (card) {
        const cs = getComputedStyle(card);
        card.scrollTop = 9999;
        out.push({
          id: ov.id || '(no id)',
          card: card.id || '(no id)',
          clientHeight: card.clientHeight,
          scrollHeight: card.scrollHeight,
          overflowY: cs.overflowY,
          scrollTopAfter: card.scrollTop,
          innerPane: !!card.querySelector('.modal-body, [style*="overflow"], .settings-pane'),
        });
        card.scrollTop = 0;
      }
      if (wasHidden) ov.classList.add('hidden');
    }
    return out;
  });
  for (const r of rows) {
    const lost = r.scrollHeight - r.clientHeight;
    const bad = lost > 2 && r.scrollTopAfter === 0;
    console.log(
      `${bad ? 'UNREACHABLE' : 'ok         '} ${r.id} / ${r.card}: ` +
        `${r.scrollHeight} in ${r.clientHeight} (overflow-y ${r.overflowY}, ` +
        `scrollTop ${r.scrollTopAfter})`
    );
  }
  await browser.close();
})();
