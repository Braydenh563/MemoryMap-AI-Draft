const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(()=>{
    const out=[];
    document.querySelectorAll('dialog').forEach(d=>{
      const cs=getComputedStyle(d);
      // Which ancestor is hidden, if any
      let hidden=null,e=d.parentElement;
      while(e){ const s=getComputedStyle(e); if(s.display==='none'){hidden=e.id||e.className;break;} e=e.parentElement; }
      out.push({id:d.id, cls:d.className, margin:cs.margin, hiddenAncestor:hidden});
    });
    return out;
  });
  for(const d of r) console.log(d.id,'|',d.margin,'| hidden:',d.hiddenAncestor,'|',d.cls);
  await browser.close();
})();
