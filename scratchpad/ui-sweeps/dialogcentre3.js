const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(()=>{
    const tab=document.getElementById('tab-documents');
    const prev=tab.style.display;
    tab.classList.remove('hidden'); tab.style.display='block';
    const out=[];
    for(const id of ['doc-ai-history-dialog','doc-history-dialog','doc-template-dialog']){
      const d=document.getElementById(id);
      try{ d.showModal(); }catch(e){ out.push({id,err:String(e)}); continue; }
      const b=d.getBoundingClientRect(); const cs=getComputedStyle(d);
      out.push({id,left:Math.round(b.left),w:Math.round(b.width),
        centredX:Math.abs((b.left+b.width/2)-window.innerWidth/2)<=2,
        margin:cs.margin, top:Math.round(b.top),
        centredY:Math.abs((b.top+b.height/2)-window.innerHeight/2)<=2});
      d.close();
    }
    tab.style.display=prev;
    return {vw:window.innerWidth,vh:window.innerHeight,out};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
