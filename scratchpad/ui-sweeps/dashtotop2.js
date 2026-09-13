const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.waitForTimeout(2000);
  const r=await page.evaluate(async()=>{
    const out=[];
    const btn=document.getElementById('scroll-top');
    const look=(label)=>{
      const b=btn.getBoundingClientRect();
      out.push({label, hidden:btn.classList.contains('hidden'), opacity:getComputedStyle(btn).opacity,
        visibility:getComputedStyle(btn).visibility, visible:btn.checkVisibility(),
        y:Math.round(b.top), scrollTop:Math.round((scrollTopTargetEl()||{scrollTop:-1}).scrollTop)});
    };
    look('at rest');
    for (const tab of ['notes','library','timeline','reminders']) {
      switchTab(tab);
      await new Promise(r=>setTimeout(r,800));
      look(tab+' at rest');
    }
    switchTab('dashboard');
    await new Promise(r=>setTimeout(r,800));
    look('back on dashboard');
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
