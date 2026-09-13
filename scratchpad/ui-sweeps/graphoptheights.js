// graph.md section 2: exact per-section heights of the options panel, to
// see where the 627px of list actually goes before trimming it.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot();
await page.click('[data-tab="graph"]');await page.waitForTimeout(700);
await page.click('#graph-options-toggle');await page.waitForTimeout(400);
const r = await page.evaluate(()=>{
  const panel = document.getElementById('graph-options');
  const sections = [...panel.querySelectorAll(':scope > .dock-menu-section')].map(s=>{
    const rect = s.getBoundingClientRect();
    const label = s.querySelector(':scope > .dock-menu-label');
    return {
      name: label ? label.textContent.trim() : '(unnamed)',
      h: Math.round(rect.height),
      labelH: label ? Math.round(label.getBoundingClientRect().height) : null,
      rows: [...s.querySelectorAll(':scope > .graph-option-row')].map(row=>Math.round(row.getBoundingClientRect().height)),
      padding: getComputedStyle(s).padding,
      gap: getComputedStyle(s).gap,
    };
  });
  return {scrollH: panel.scrollHeight, clientH: panel.clientHeight, sections};
});
console.log(JSON.stringify(r, null, 1));
await browser.close();})();
