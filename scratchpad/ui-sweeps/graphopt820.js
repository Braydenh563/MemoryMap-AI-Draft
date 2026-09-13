// graph.md section 2 fix, narrow-width check: the "Show" section's two-column
// grid collapses back to one column below 820 (--target-min grows to 44px
// there), so a 22rem panel isn't asked to fit two 44px rows side by side.
// Confirms the grid actually applies and rows don't wrap or clip at 1024 and
// 390 wide, and that the panel still doesn't scroll at those widths.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot({viewport:{width:1024,height:768}});
await page.click('[data-tab="graph"]');await page.waitForTimeout(700);
await page.click('#graph-options-toggle');await page.waitForTimeout(400);
for (const w of [1024, 390]) {
  await page.setViewportSize({width:w, height: w===390?844:768});
  await page.waitForTimeout(300);
  const r = await page.evaluate(()=>{
    const grid = document.querySelector('.graph-toggle-grid');
    const cols = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
    const rows = [...grid.querySelectorAll('.graph-option-row')].map(row=>{
      const rect = row.getBoundingClientRect();
      const label = row.querySelector('span');
      const input = row.querySelector('input');
      return {h: Math.round(rect.height), labelClipped: label.scrollWidth > label.clientWidth + 1, w: Math.round(rect.width)};
    });
    const panel = document.getElementById('graph-options');
    return {cols, rows, scrolls: panel.scrollHeight > panel.clientHeight + 1, scrollH: panel.scrollHeight, clientH: panel.clientHeight};
  });
  console.log(`${w}px: cols=${r.cols} scrolls=${r.scrolls} (${r.scrollH} vs ${r.clientH}) rows=${JSON.stringify(r.rows)}`);
}
await browser.close();})();
