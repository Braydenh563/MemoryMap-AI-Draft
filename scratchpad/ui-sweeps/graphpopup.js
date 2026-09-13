// The graph node panel's header rules, measured on a real element carrying
// the real classes at the panel's real width. The live panel is positioned
// by the graph's own click path and lays out at zero height when revealed by
// hand, so the header is rebuilt here instead: the rules under test are pure
// CSS and apply by class either way.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const r = await page.evaluate(() => {
    const host = document.createElement('div');
    host.className = 'card graph-popup';
    host.style.position = 'fixed';
    host.style.left = '20px';
    host.style.top = '20px';
    host.style.width = '340px';
    const head = document.createElement('div');
    head.className = 'row space-between graph-popup-head';
    const ident = document.createElement('span');
    ident.className = 'graph-popup-ident';
    const strong = document.createElement('strong');
    strong.id = 'graph-popup-title-probe';
    const chip = document.createElement('span');
    chip.className = 'chip tag';
    chip.textContent = 'Social Connections';
    ident.append(strong, chip);
    const close = document.createElement('button');
    close.id = 'graph-popup-close';
    close.className = 'ghost small icon-only';
    close.textContent = 'x';
    head.append(ident, close);
    host.append(head);
    document.body.append(host);
    const lh = () => parseFloat(getComputedStyle(strong).lineHeight) || 16;
    const read = () => ({
      headH: Math.round(head.getBoundingClientRect().height),
      titleLines: Math.round(strong.getBoundingClientRect().height / lh()),
      closeTop: Math.round(close.getBoundingClientRect().top - head.getBoundingClientRect().top),
      closeRight: Math.round(head.getBoundingClientRect().right - close.getBoundingClientRect().right),
      closeW: Math.round(close.getBoundingClientRect().width),
      ellipsisOn: getComputedStyle(strong).textOverflow === 'ellipsis'
        && getComputedStyle(strong).whiteSpace === 'nowrap',
      truncated: strong.scrollWidth > strong.clientWidth,
      headWrap: getComputedStyle(head).flexWrap,
      identFlex: getComputedStyle(ident).flex,
      closeFlex: getComputedStyle(close).flex,
      identH: Math.round(ident.getBoundingClientRect().height),
    });
    strong.textContent = 'Short note';
    const short = read();
    strong.textContent = 'Ice Breakers: - "If you were a spice, which one would you be and why?"';
    const long = read();
    host.remove();
    return { short, long };
  });
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
