// Per-row detail behind wbmenus.js: what each control in the five whiteboard
// menus actually computes to, so a fix targets the right selector rather than
// the first one that looks plausible.
const {boot}=require('./lib.js');
const MENUS=['wb-insert-menu','wb-view-menu','wb-board-menu','wb-arrange-menu','wb-edit-menu'];
(async()=>{
  const {browser,page}=await boot();
  const id=await page.evaluate(async()=>{const r=await api('/whiteboard/boards',{method:'POST',body:JSON.stringify({name:'Sweep board 2'})});return (await r.json()).id;});
  await page.evaluate((b)=>openWhiteboardBoard(b), id); await page.waitForTimeout(1500);
  for(const m of MENUS){
    await page.evaluate((mid)=>{document.querySelector(`[aria-controls="${mid}"]`)?.click();}, m); await page.waitForTimeout(200);
    const r=await page.evaluate((mid)=>{
      const el=document.getElementById(mid);
      return [...el.querySelectorAll('button,a,select,input,label')].filter(e=>e.checkVisibility&&e.checkVisibility()).map(e=>{
        const c=getComputedStyle(e);
        return `${e.tagName.toLowerCase()}${e.id?'#'+e.id:''}.${[...e.classList].join('.')||'-'} h=${e.getBoundingClientRect().height.toFixed(2)} bg=${c.backgroundColor} pad=${c.padding} fs=${c.fontSize} kbd=${!!e.querySelector('kbd')} parent=${e.parentElement.className}`;
      });
    }, m);
    console.log('== '+m); r.forEach(x=>console.log('  '+x));
    await page.evaluate((mid)=>{document.querySelector(`[aria-controls="${mid}"]`)?.click();}, m); await page.waitForTimeout(120);
  }
  await page.click('[data-tab="notes"]').catch(()=>{}); await page.waitForTimeout(800);
  const ref=await page.evaluate(()=>{
    const d=document.getElementById('notes-more-menu'); if(!d) return 'none';
    if(d.tagName==='DETAILS') d.open=true; else d.classList.remove('hidden');
    return [...d.querySelectorAll('button,a')].filter(e=>e.checkVisibility&&e.checkVisibility()).slice(0,6).map(e=>{const c=getComputedStyle(e);return `${e.className} h=${e.getBoundingClientRect().height.toFixed(2)} bg=${c.backgroundColor} pad=${c.padding} fs=${c.fontSize}`;});
  });
  console.log('== notes-more-menu reference'); (Array.isArray(ref)?ref:[ref]).forEach(x=>console.log('  '+x));
  await browser.close();
})();
