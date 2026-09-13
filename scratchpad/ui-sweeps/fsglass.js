// INBOX 66 and 88: the lightbox must sit above the full-screen graph card,
// and full screen must keep its glass when the background art is on.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="graph"]').catch(() => {});
  await page.waitForTimeout(2500);
  const r = await page.evaluate(() => {
    const card = document.getElementById('graph-card');
    const z = (el) => (el ? getComputedStyle(el).zIndex : null);
    const lightbox = document.createElement('div');
    lightbox.className = 'lightbox';
    document.body.append(lightbox);
    const out = { lightboxZ: z(lightbox) };
    if (card) {
      card.classList.add('graph-fullscreen');
      document.body.classList.add('graph-fullscreen-on');
      const read = () => {
        const cs = getComputedStyle(card);
        return { z: cs.zIndex, background: cs.backgroundColor, filter: cs.backdropFilter };
      };
      document.documentElement.dataset.bgArt = 'off';
      out.artOff = read();
      document.documentElement.dataset.bgArt = 'on';
      delete document.documentElement.dataset.glass;
      out.artOn = read();
      document.documentElement.dataset.glass = 'off';
      out.glassOff = read();
      delete document.documentElement.dataset.glass;
      card.classList.remove('graph-fullscreen');
      document.body.classList.remove('graph-fullscreen-on');
    }
    lightbox.remove();
    out.lightboxAboveFullscreen = Number(out.lightboxZ) > Number(out.artOn ? out.artOn.z : 0);
    return out;
  });
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
