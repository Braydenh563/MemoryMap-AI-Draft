// What a Library image card shows AT REST, and at 390 as well as 1440.
//
// The companion to imagecardbottom.js (which seeds and measures heights).
// This one counts what a reader actually has in front of them before they
// click anything: a control inside a closed kebab or a closed <details> is
// not on the card, and the count that matters is the one the owner sees on a
// wall of twenty tiles ("nine to ten buttons per card").
//
//   BASE=http://127.0.0.1:8879 SCRATCH=/tmp/mm-cards \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/imagecardrest.js
const { boot } = require('./lib.js');

const probe = () => {
  const tiles = [...document.querySelectorAll('.library-image-tile')];
  const seen = (el) => {
    if (!el || !el.offsetParent) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  return tiles.map((t) => {
    const r = t.getBoundingClientRect();
    const frame = t.querySelector('.library-image-frame');
    const fr = frame ? frame.getBoundingClientRect() : null;
    return {
      name: t.querySelector('figcaption')?.textContent.trim().slice(0, 24),
      card: +r.height.toFixed(1),
      picture: fr ? +fr.height.toFixed(1) : null,
      below: fr ? +(r.bottom - fr.bottom).toFixed(1) : null,
      pictureShare: fr ? +((fr.height / r.height) * 100).toFixed(1) : null,
      // Controls a reader can see and hit without opening anything.
      atRest: [...t.querySelectorAll('button, input, summary')].filter(seen).length,
      atRestNames: [...t.querySelectorAll('button, input, summary')]
        .filter(seen)
        .map((e) => (e.textContent || e.type || e.tagName).replace(/\s+/g, ' ').trim().slice(0, 28)),
      facts: t.querySelector('.library-image-facts')?.textContent || null,
      captionShown: seen(t.querySelector('.library-image-caption')),
      overflowsX: t.scrollWidth > t.clientWidth + 1,
    };
  });
};

(async () => {
  const { browser, page, OUT } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  await page.evaluate(() => switchTab('library'));
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#library-subtabs button, [data-subtab]')]
      .find((e) => /image/i.test(e.textContent || e.dataset.subtab || ''));
    if (b) b.click();
  });
  await page.waitForTimeout(1500);
  say('at-1440', await page.evaluate(probe));
  await page.screenshot({ path: OUT + '/imagecards-after-1440.png' });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(900);
  say('at-390', await page.evaluate(probe));
  await page.screenshot({ path: OUT + '/imagecards-after-390.png', fullPage: false });

  // And with the one fold open, which is the whole of "show me everything".
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(700);
  await page.evaluate(() => {
    document.querySelectorAll('.library-image-tile .library-image-reading')
      .forEach((d) => { d.open = true; });
  });
  await page.waitForTimeout(400);
  say('one-open', await page.evaluate(probe));
  await page.screenshot({ path: OUT + '/imagecards-after-open.png' });
  console.log('shots in ' + OUT);
  await browser.close();
})();
