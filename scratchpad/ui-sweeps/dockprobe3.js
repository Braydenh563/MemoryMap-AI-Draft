// One-off probe (same purpose as dockprobe2.js, generalised to any dock):
// which exact elements docks.js's control-counter matches, so a control move
// can be checked against the same definition the sweep uses.
const {boot}=require('./lib.js');
const NAME=process.argv[2]||'library';
const TAB=process.argv[3]||NAME;
(async()=>{const {browser,page}=await boot();
await page.click(`[data-tab="${TAB}"]`);await page.waitForTimeout(700);
const r = await page.evaluate((NAME)=>{
  const e = document.querySelector(`[data-dock-name="${NAME}"]`);
  if(!e) return 'NOT FOUND';
  const ctrls=[...e.querySelectorAll('button, select, input, .seg, .select-shell, label')].filter(c=>c.getBoundingClientRect().width>0&&!c.closest('.doc-dock-menu-list')&&c.closest('.row, .library-toolbar, .graph-toolbar, .chat-toolbar, .wb-topbar, .doc-dock-head, .doc-toolbar, .doc-statusbar, .notes-toolbar, .log-toolbar, [role="toolbar"]')===e);
  return ctrls.map(c=>(c.id?'#'+c.id:'.'+[...c.classList].slice(0,2).join('.'))+':'+c.tagName);
}, NAME);
console.log(JSON.stringify(r,null,1));
await browser.close();})();
