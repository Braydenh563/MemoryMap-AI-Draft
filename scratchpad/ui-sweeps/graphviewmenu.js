// graph.md section 3: #graph-view-picker moved from dock-arrange into the
// More menu to bring the dock's control count from 9 to <=7. Confirms the
// move didn't break the saved-views feature: open the menu, the select is
// there and reachable, save a view, it appears as an option, still selected
// after closing and reopening the menu.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot();
await page.click('[data-tab="graph"]');await page.waitForTimeout(2000);
const wired = await page.evaluate(()=>document.getElementById('graph-view-picker')?._wired);
console.log('wired?', wired);
await page.click('#graph-more-menu summary');await page.waitForTimeout(300);
const before = await page.evaluate(()=>{
  const sel = document.getElementById('graph-view-picker');
  return {found: !!sel, inMenu: !!sel?.closest('.doc-dock-menu-list'), options: sel?.options.length};
});
console.log('before save', JSON.stringify(before));
// graphSaveCurrentView() uses the app's own promptDialog overlay, not a
// native prompt() -- fill its input and press Enter (its own keydown
// handler submits, see app.js's promptDialog).
const vis = await page.evaluate(()=>{const b=document.getElementById('graph-view-save');const r=b?.getBoundingClientRect();return {exists:!!b, w:r?.width, h:r?.height, open: document.getElementById('graph-more-menu')?.open};});
console.log('view-save visibility', JSON.stringify(vis));
await page.evaluate(()=>document.getElementById('graph-view-save').click());await page.waitForTimeout(400);
const overlayCount = await page.evaluate(()=>document.querySelectorAll('.confirm-overlay').length);
console.log('overlay count (direct .click())', overlayCount);
if (overlayCount) {
  await page.fill('.confirm-overlay input[type="text"]', 'Sweep test view');
  await page.keyboard.press('Enter');await page.waitForTimeout(500);
}
await page.click('#graph-more-menu summary');await page.waitForTimeout(300);
const after = await page.evaluate(()=>{
  const sel = document.getElementById('graph-view-picker');
  return {options: [...sel.options].map(o=>o.textContent), value: sel.value};
});
console.log('after save', JSON.stringify(after));
await browser.close();})();
