const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(()=>{
    const m=document.getElementById('agent-monitor');
    m.classList.remove('hidden');
    document.body.classList.add('has-agent-monitor');
    const cs=getComputedStyle(m); const b=m.getBoundingClientRect();
    const btns=[...m.querySelectorAll('button')].map(x=>{
      const c=getComputedStyle(x); const r=x.getBoundingClientRect();
      return {id:x.id, bg:c.backgroundColor, bd:c.borderTopWidth+' '+c.borderTopColor,
              sh:c.boxShadow==='none'?'none':'shadow', h:Math.round(r.height), r:c.borderTopLeftRadius};
    });
    const head=m.querySelector('.monitor-header');
    return {
      rect:{l:Math.round(b.left),t:Math.round(b.top),w:Math.round(b.width),h:Math.round(b.height)},
      padding:cs.padding, radius:cs.borderRadius, shadow:cs.boxShadow.slice(0,40),
      border:cs.borderTopWidth+' '+cs.borderTopColor,
      headPad:getComputedStyle(head).paddingBottom, headBorder:getComputedStyle(head).borderBottomWidth,
      title:getComputedStyle(m.querySelector('.monitor-title')).fontSize,
      btns,
      viewportGapLeft:Math.round(b.left), viewportGapBottom:Math.round(window.innerHeight-b.bottom),
    };
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
