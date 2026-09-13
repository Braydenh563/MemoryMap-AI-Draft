// The letterboxed board inside the dashboard row's square thumbnail box.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(2500);
  const out = await page.evaluate(() => {
    const svg = document.querySelector('.dash-widget .dash-board-thumb');
    if (!svg) return { err: 'no thumb' };
    const box = svg.getBoundingClientRect();
    const paper = svg.querySelector('.board-minimap-paper');
    const pb = paper ? paper.getBoundingClientRect() : null;
    const cs = getComputedStyle(svg);
    const paperCs = paper ? getComputedStyle(paper) : null;
    // The Library's own row thumb, for comparison.
    return {
      svgBox: { w: +box.width.toFixed(1), h: +box.height.toFixed(1) },
      svgBorder: cs.borderColor + ' ' + cs.borderWidth, svgBg: cs.backgroundColor, svgRadius: cs.borderRadius,
      viewBox: svg.getAttribute('viewBox'),
      paperBox: pb ? { w: +pb.width.toFixed(1), h: +pb.height.toFixed(1), dx: +(pb.left - box.left).toFixed(1), dy: +(pb.top - box.top).toFixed(1) } : null,
      paperFill: paperCs ? paperCs.fill : null, paperStroke: paperCs ? paperCs.stroke : null,
      emptyBandTop: pb ? +(pb.top - box.top).toFixed(1) : null,
      emptyBandBottom: pb ? +(box.bottom - pb.bottom).toFixed(1) : null,
      fillRatio: pb ? +((pb.width * pb.height) / (box.width * box.height)).toFixed(3) : null,
    };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
