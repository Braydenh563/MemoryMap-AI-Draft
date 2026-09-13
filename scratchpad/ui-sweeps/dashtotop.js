const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.waitForTimeout(1600);
  const r=await page.evaluate(async()=>{
    const page_=document.getElementById('tab-dashboard');
    const btn=document.getElementById('scroll-top');
    const before={hidden:btn?btn.classList.contains('hidden'):null, scrollH:page_.scrollHeight, clientH:page_.clientHeight,
      target:(typeof scrollTopTargetEl==='function')?(scrollTopTargetEl()?.id||scrollTopTargetEl()?.className||'?'):'n/a'};
    page_.scrollTop = 1200;
    page_.dispatchEvent(new Event('scroll',{bubbles:true}));
    window.dispatchEvent(new Event('scroll'));
    await new Promise(r=>setTimeout(r,900));
    const b=btn?btn.getBoundingClientRect():null;
    return {before, afterScrollTop:page_.scrollTop,
      hiddenAfter:btn?btn.classList.contains('hidden'):null,
      rect:b?{x:Math.round(b.left),y:Math.round(b.top),w:Math.round(b.width),h:Math.round(b.height)}:null,
      bodyClass:document.body.classList.contains('scroll-top-visible'),
      parent:btn?(btn.parentElement.id||btn.parentElement.className):null};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
