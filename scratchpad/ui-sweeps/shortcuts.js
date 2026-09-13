// Does the keyboard-shortcuts overlay reach its last section at 1440x900?
//
// The overlay is `.modal-overlay` + `.card.modal-card`, and `.modal-card`
// caps itself at 88vh without ever saying what happens to content past that
// cap: Settings gets away with it because its own `.modal-body` owns a
// scroll pane, and this dialog has no inner pane at all. So its "Always
// available" list and the '?' popover under it sit below the fold with no
// scroll mechanism anywhere in the chain. This measures the card's scroll
// height against its client height, and each section's bottom against the
// card's, so the fix can be shown rather than described.
const { boot } = require('./lib.js');

(async () => {
  const { page, browser } = await boot({ width: 1440, height: 900 });
  await page.evaluate(() => openShortcuts());
  await page.waitForTimeout(500);
  const m = await page.evaluate(() => {
    const card = document.getElementById('shortcuts-card');
    const cs = getComputedStyle(card);
    const cr = card.getBoundingClientRect();
    const heads = [...card.querySelectorAll('h2, h3')].map((h) => ({
      text: h.textContent.trim().slice(0, 28),
      bottom: +h.getBoundingClientRect().bottom.toFixed(1),
    }));
    const lists = [...card.querySelectorAll('.shortcut-list')].map((u) => ({
      items: u.children.length,
      bottom: +u.getBoundingClientRect().bottom.toFixed(1),
    }));
    const trigger = card.querySelector('[data-help-for]');
    return {
      viewport: innerHeight,
      cardTop: +cr.top.toFixed(1),
      cardBottom: +cr.bottom.toFixed(1),
      clientHeight: card.clientHeight,
      scrollHeight: card.scrollHeight,
      overflowY: cs.overflowY,
      maxHeight: cs.maxHeight,
      heads,
      lists,
      triggerBottom: trigger ? +trigger.getBoundingClientRect().bottom.toFixed(1) : null,
      scrolledBy: (card.scrollTop = 9999, card.scrollTop),
    };
  });
  console.log(JSON.stringify(m, null, 2));
  await browser.close();
})();
