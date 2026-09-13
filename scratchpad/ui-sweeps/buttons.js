const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const tabs=[null,'notes','library','chat','graph','timeline','reminders'];
  const collect=async(label)=>{
    const r=await page.evaluate(()=>{
      const res={};
      document.querySelectorAll('button').forEach(b=>{
        if(!b.checkVisibility||!b.checkVisibility())return;
        const r=b.getBoundingClientRect(); if(r.width<6||r.height<6)return;
        const c=getComputedStyle(b);
        const icon=b.classList.contains('icon-only')?'ICON':(b.textContent.trim().length<=1?'icon?':'text');
        // A *recipe* is what the eye sees: fill, edge, shadow, radius. The class
        // list is an example, not part of the key — keying on it counted
        // `ghost.small` and `ghost.small.conv-browse-all` as two recipes when
        // they render identically. Fields that happen to be <button>s
        // (.select-opener) belong to the field family and are skipped.
        if(b.classList.contains('select-opener'))return;
        const key=`${icon} bg=${c.backgroundColor} bd=${c.borderTopWidth} ${c.borderTopColor} sh=${c.boxShadow==='none'?'none':'shadow'} r=${c.borderTopLeftRadius}`;
        const cls=(b.id?'#'+b.id:'')+'.'+[...b.classList].filter(x=>!/^ph/.test(x)).slice(0,3).join('.');
        res[key]=res[key]||{n:0,ex:new Set()}; res[key].n++; if(res[key].ex.size<4)res[key].ex.add(cls);
      });
      for(const k in res)res[k]={n:res[k].n,ex:[...res[k].ex]};
      return res;
    });
    const rows=Object.entries(r).sort((a,b)=>b[1].n-a[1].n);
    console.log('\n== '+label+' ('+rows.length+' signatures)\n'+rows.map(([k,v])=>v.n+'\t'+k+'\t'+v.ex.join(' ')).join('\n'));
  };
  for(const t of tabs){ if(t){await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(800);} await collect(t||'dashboard'); }
  await browser.close();
})();
