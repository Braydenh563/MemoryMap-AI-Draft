const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const tabs=[null,'notes','library','chat','graph','timeline','reminders'];
  const tally={};
  for(const t of tabs){
    if(t){await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(1100);}
    const r=await page.evaluate(()=>{
      const counts={};
      document.querySelectorAll('button.ghost').forEach(b=>{
        if(!b.checkVisibility||!b.checkVisibility())return;
        const rr=b.getBoundingClientRect(); if(rr.width<6)return;
        const c=getComputedStyle(b);
        if(!/0\.22/.test(c.borderTopColor))return;
        let p=b.parentElement;
        if(p&&p.classList.contains('menu-wrap'))p=p.parentElement;
        const k=p?p.tagName.toLowerCase()+'.'+(typeof p.className==='string'?p.className.split(' ').slice(0,2).join('.'):''):'?';
        counts[k]=(counts[k]||0)+1;
      });
      return counts;
    });
    for(const k in r) tally[k]=Math.max(tally[k]||0,r[k]);
  }
  console.log(Object.entries(tally).sort((a,b)=>b[1]-a[1]).map(([k,v])=>v+'\t'+k).join('\n'));
  await browser.close();
})();
