// One-off probe: which exact elements docks.js's control-counter matches
// inside the graph dock, so a control move can be checked against the same
// definition the lint's runtime sweep uses.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot();
await page.click('[data-tab="graph"]');await page.waitForTimeout(700);
const r = await page.evaluate(()=>{
  const e = document.querySelector('[data-dock-name="graph"]');
  const ctrls=[...e.querySelectorAll('button, select, input, .seg, .select-shell, label')].filter(c=>c.getBoundingClientRect().width>0&&!c.closest('.doc-dock-menu-list')&&c.closest('.row, .library-toolbar, .graph-toolbar, .chat-toolbar, .wb-topbar, .doc-dock-head, .doc-toolbar, .doc-statusbar, .notes-toolbar, .log-toolbar, [role="toolbar"]')===e);
  return ctrls.map(c=>(c.id?'#'+c.id:'.'+[...c.classList].slice(0,2).join('.'))+':'+c.tagName);
});
console.log(JSON.stringify(r,null,1));
await browser.close();})();
