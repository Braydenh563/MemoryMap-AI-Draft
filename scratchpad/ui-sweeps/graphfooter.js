// The graph node panel's action footer: centred, as wide as the panel, and
// ending on the panel's own corners.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const r = await page.evaluate(() => {
    const host = document.createElement('div');
    host.className = 'card graph-popup';
    host.style.position = 'fixed';
    host.style.left = '20px';
    host.style.top = '20px';
    const body = document.createElement('p');
    body.textContent = 'A note preview sits above the actions.';
    const actions = document.createElement('div');
    actions.className = 'graph-popup-actions';
    const groups = [3, 4, 2];
    for (const n of groups) {
      const g = document.createElement('div');
      g.className = 'graph-popup-tool-group';
      for (let i = 0; i < n; i++) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'ghost small icon-only';
        b.textContent = 'o';
        g.append(b);
      }
      actions.append(g);
    }
    host.append(body, actions);
    document.body.append(host);
    const hostBox = host.getBoundingClientRect();
    const actBox = actions.getBoundingClientRect();
    const buttons = [...actions.querySelectorAll('button')];
    const first = buttons[0].getBoundingClientRect();
    const last = buttons[buttons.length - 1].getBoundingClientRect();
    const cs = getComputedStyle(actions);
    const out = {
      panelW: Math.round(hostBox.width),
      footerW: Math.round(actBox.width),
      edgeGapLeft: +(actBox.left - hostBox.left).toFixed(1),
      edgeGapRight: +(hostBox.right - actBox.right).toFixed(1),
      bottomGap: +(hostBox.bottom - actBox.bottom).toFixed(1),
      borderWidth: getComputedStyle(host).borderLeftWidth,
      centred: Math.abs((first.left - actBox.left) - (actBox.right - last.right)) < 2,
      leftInset: Math.round(first.left - actBox.left),
      rightInset: Math.round(actBox.right - last.right),
      justify: cs.justifyContent,
      tinted: cs.backgroundColor,
      bottomRadius: cs.borderBottomLeftRadius,
      buttons: buttons.length,
    };
    host.remove();
    return out;
  });
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
