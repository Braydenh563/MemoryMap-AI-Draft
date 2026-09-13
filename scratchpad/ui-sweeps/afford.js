const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const tabs=[null,'notes','library','chat','graph','timeline','reminders'];
  const seen=new Map();
  for(const t of tabs){
    if(t){await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(900);}
    const rows=await page.evaluate((tab)=>{
      const out=[];
      document.querySelectorAll('button, summary').forEach(b=>{
        if(!b.checkVisibility||!b.checkVisibility())return;
        const r=b.getBoundingClientRect(); if(r.width<6||r.height<6)return;
        const c=getComputedStyle(b);
        const transparent=(v)=>/rgba\(0, 0, 0, 0\)|transparent/.test(v)||/, 0\)$/.test(v);
        const noFill=transparent(c.backgroundColor);
        const noEdge=transparent(c.borderTopColor)||c.borderTopWidth==='0px';
        const noShadow=c.boxShadow==='none';
        if(!(noFill&&noEdge&&noShadow))return;
        const inBar=!!b.closest('.dock, .toolbar, .tabs, .status-bar, #status-bar, .segmented, .seg, .wb-selection-bar, .whiteboard-floating-panel');
        out.push({tab,
          sel:(b.id?'#'+b.id:'')+'.'+[...b.classList].filter(x=>!/^ph/.test(x)).slice(0,3).join('.'),
          text:(b.textContent||'').trim().slice(0,24), inBar,
          parent:(b.parentElement?.className||'').slice(0,40)});
      });
      return out;
    }, t||'dashboard');
    for(const r of rows) if(!seen.has(r.sel+r.text)) seen.set(r.sel+r.text,r);
  }
  const all=[...seen.values()];
  console.log('total text-only:',all.length,' outside a bar:',all.filter(r=>!r.inBar).length);
  for(const r of all.filter(r=>!r.inBar)) console.log(' ',r.tab,'|',r.sel,'|',JSON.stringify(r.text),'| parent:',r.parent);
  await browser.close();
})();
