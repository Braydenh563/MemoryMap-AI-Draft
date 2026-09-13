const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(()=>{
    const out=[];
    document.querySelectorAll('dialog').forEach(d=>{
      let ok=true;
      try{ d.showModal(); }catch(e){ ok=false; }
      if(!ok) return;
      const b=d.getBoundingClientRect(); const cs=getComputedStyle(d);
      out.push({id:d.id, left:Math.round(b.left), right:Math.round(b.right),
        w:Math.round(b.width), top:Math.round(b.top),
        centredX:Math.abs((b.left+b.width/2)-window.innerWidth/2)<=2,
        margin:cs.margin, position:cs.position});
      d.close();
    });
    return {vw:window.innerWidth, vh:window.innerHeight, dialogs:out};
  });
  const bad=r.dialogs.filter(d=>!d.centredX);
  console.log('viewport',r.vw,'x',r.vh,' dialogs:',r.dialogs.length,' off-centre:',bad.length);
  for(const d of bad) console.log(' OFF', JSON.stringify(d));
  await browser.close();
})();
