// Every `.seg` strip in the app: its buttons' font-size, the strip's own
// width and whether it wraps. Run before and after the type change.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const tabs=[null,'notes','library','chat','graph','timeline','reminders','documents'];
  const seen=new Map();
  for(const t of tabs){
    if(t){await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(1000);}
    const rows=await page.evaluate((tab)=>{
      const out=[];
      document.querySelectorAll('.seg').forEach(seg=>{
        if(!seg.checkVisibility||!seg.checkVisibility())return;
        const sb=seg.getBoundingClientRect(); if(sb.width<6)return;
        const btns=[...seg.querySelectorAll('button')].filter(b=>b.getBoundingClientRect().width);
        if(!btns.length)return;
        const tops=[...new Set(btns.map(b=>Math.round(b.getBoundingClientRect().top)))];
        out.push({tab, id:seg.id||seg.className.slice(0,26),
          fs:getComputedStyle(btns[0]).fontSize, n:btns.length,
          segW:Math.round(sb.width), segH:Math.round(sb.height),
          btnH:Math.round(btns[0].getBoundingClientRect().height),
          rows:tops.length, overflows:seg.scrollWidth>seg.clientWidth+1});
      });
      return out;
    }, t||'dashboard');
    for(const r of rows) if(!seen.has(r.tab+r.id)) seen.set(r.tab+r.id,r);
  }
  const all=[...seen.values()];
  const sizes={}; all.forEach(r=>{sizes[r.fs]=(sizes[r.fs]||0)+1;});
  console.log('strips:',all.length,' sizes:',JSON.stringify(sizes));
  console.log('wrapped:',all.filter(r=>r.rows>1).length,' overflowing:',all.filter(r=>r.overflows).length);
  for(const r of all) console.log(` ${r.tab}\t${r.id}\tfs=${r.fs}\tn=${r.n}\tw=${r.segW}\th=${r.segH}/${r.btnH}\trows=${r.rows}${r.overflows?' OVERFLOW':''}`);
  await browser.close();
})();
