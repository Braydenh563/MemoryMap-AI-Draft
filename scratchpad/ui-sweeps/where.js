const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('[data-tab="notes"]').catch(()=>{}); await page.waitForTimeout(1400);
  const r=await page.evaluate(()=>{
    const counts={};
    document.querySelectorAll('button.ghost').forEach(b=>{
      if(!b.checkVisibility||!b.checkVisibility())return;
      const rr=b.getBoundingClientRect(); if(rr.width<6)return;
      const c=getComputedStyle(b);
      if(!/0\.22/.test(c.borderTopColor))return;
      let chain=[],e=b.parentElement,n=0;
      while(e&&n<3){chain.push(e.tagName.toLowerCase()+(e.className&&typeof e.className==='string'?'.'+e.className.split(' ').slice(0,2).join('.'):''));e=e.parentElement;n++;}
      const k=chain.join(' < ');
      counts[k]=(counts[k]||0)+1;
    });
    return counts;
  });
  console.log(Object.entries(r).sort((a,b)=>b[1]-a[1]).map(([k,v])=>v+'\t'+k).join('\n'));
  await browser.close();
})();
