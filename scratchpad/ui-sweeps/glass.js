// Phase 3 glass restraint: every visible element with a backdrop-filter, per
// tab, grouped by class signature, with how many sit inside another blurred
// element. The number the phase is judged by.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  for(const t of ['dashboard','notes','library','chat','graph','timeline','reminders']){
    await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(700);
    const r=await page.evaluate(()=>{
      const vis=e=>e.checkVisibility&&e.checkVisibility();
      const blurred=[...document.querySelectorAll('body *')].filter(e=>vis(e)&&getComputedStyle(e).backdropFilter!=='none');
      const groups={};let nested=0;
      for(const e of blurred){const k=`${e.tagName.toLowerCase()}.${[...e.classList].slice(0,2).join('.')}`;groups[k]=(groups[k]||0)+1;let p=e.parentElement;while(p){if(blurred.includes(p)){nested++;break;}p=p.parentElement;}}
      const shadows=[...document.querySelectorAll('body *')].filter(e=>vis(e)&&getComputedStyle(e).boxShadow!=='none').length;
      return {total:blurred.length,nested,shadows,groups};
    });
    console.log(`== ${t}: blurred=${r.total} nested=${r.nested} shadows=${r.shadows}`);
    console.log('  '+Object.entries(r.groups).sort((a,b)=>b[1]-a[1]).map(([k,n])=>n+' '+k).join('\n  '));
  }
  await browser.close();
})();
