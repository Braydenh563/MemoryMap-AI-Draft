// The five whiteboard menus (Insert, Edit, Arrange, View, Board), measured
// rather than reasoned. consistency.md item 1 left them unverified because
// "open a board" defeated the driver; the way in is the API plus the app's
// own `openWhiteboardBoard(id)` global, not a click path through the Library.
//
// Checks per menu row, against the one menu recipe (WORLD_CLASS_PLAN 1.3):
// a non-transparent background at rest is a failure; heights and paddings
// must be one value across all five menus.
const {boot}=require('./lib.js');
const MENUS=['wb-insert-menu','wb-edit-menu','wb-arrange-menu','wb-view-menu','wb-board-menu'];
(async()=>{
  const {browser,page}=await boot();
  const id=await page.evaluate(async()=>{
    const r=await api('/whiteboard/boards',{method:'POST',body:JSON.stringify({name:'Sweep board'})});
    const j=await r.json(); return j.id;
  });
  console.log('board', id);
  await page.evaluate((b)=>openWhiteboardBoard(b), id);
  await page.waitForTimeout(1500);
  const shells=[];
  for(const m of MENUS){
    const opened=await page.evaluate((mid)=>{
      const btn=document.querySelector(`[aria-controls="${mid}"]`);
      if(!btn) return 'no toggle';
      btn.click();
      return document.getElementById(mid)?.classList.contains('hidden') ? 'still hidden' : 'open';
    }, m);
    // Park the pointer off every menu before measuring. Without this the row
    // under the virtual mouse reports `--ghost-btn-bg` and reads as a recipe
    // failure: the first run of this script called `Connector` filled at rest
    // when `el.matches(':hover')` was true. Hover is not rest.
    await page.mouse.move(1430, 890);
    await page.waitForTimeout(250);
    const r=await page.evaluate((mid)=>{
      const el=document.getElementById(mid); if(!el) return null;
      const cs=getComputedStyle(el);
      const rows=[...el.querySelectorAll('button, a, [role="menuitem"], [role="menuitemcheckbox"]')].filter(e=>e.checkVisibility&&e.checkVisibility());
      const filled=rows.filter(e=>{const b=getComputedStyle(e).backgroundColor;const m=b.match(/rgba?\(([^)]+)\)/);if(!m)return false;const p=m[1].split(/[\s,\/]+/).map(Number);return (p.length<4?1:p[3])>0.01;});
      const h=[...new Set(rows.map(e=>+e.getBoundingClientRect().height.toFixed(2)))];
      const pad=[...new Set(rows.map(e=>{const c=getComputedStyle(e);return c.paddingTop+'/'+c.paddingLeft;}))];
      const fs=[...new Set(rows.map(e=>getComputedStyle(e).fontSize))];
      return {rows:rows.length, filled:filled.map(e=>(e.id||e.textContent.trim().slice(0,18))+' '+getComputedStyle(e).backgroundColor), h, pad, fs,
        shell:{bg:cs.backgroundColor, border:cs.borderTopWidth+' '+cs.borderTopColor, radius:cs.borderTopLeftRadius, pad:cs.paddingTop, minW:cs.minWidth, w:+el.getBoundingClientRect().width.toFixed(1)}};
    }, m);
    console.log(`== ${m} (${opened})`, r? `rows=${r.rows} filled=${r.filled.length} h=${JSON.stringify(r.h)} pad=${JSON.stringify(r.pad)} fs=${JSON.stringify(r.fs)}` : 'MISSING');
    if(r&&r.filled.length) r.filled.forEach(f=>console.log('   FILLED '+f));
    if(r) { console.log('   shell', JSON.stringify(r.shell)); shells.push([m,JSON.stringify(r.shell)]); }
    await page.evaluate((mid)=>{const b=document.querySelector(`[aria-controls="${mid}"]`); if(b) b.click();}, m);
    await page.waitForTimeout(150);
  }
  const distinct=new Set(shells.map(s=>s[1].replace(/"w":[\d.]+/,'')));
  console.log('distinct shell recipes (ignoring width):', distinct.size);
  await browser.close();
})();
